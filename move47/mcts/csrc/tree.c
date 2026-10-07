/* The MCTS hot loop: PUCT selection with progressive widening and virtual loss, expansion with the
 * learned priors, transpositions through a Zobrist-keyed table, playout evaluation and backup.
 *
 * Node and edge storage are numpy arrays owned by Python (move47/mcts/tree.py); this file only
 * reads and writes them.  Concurrency (N threads in mc_tree_run, GIL released by ctypes):
 *   - statistics (n, w, nx, wx, vl, e_n) are read with relaxed atomic loads during selection and
 *     updated with atomic adds; a selection may see a slightly stale mix, which is harmless;
 *   - a node is expanded by the one thread whose compare-and-swap moves it NEW -> EXPANDING; the
 *     edges are written before the release store of EXPANDED, so readers that see EXPANDED
 *     (acquire) see the edges;
 *   - edges never move during a search (external priors are written in place), so a simulation's
 *     path of edge indices stays valid until its backup;
 *   - one mutex guards the transposition table and node creation (a lookup-or-insert per new
 *     leaf, ~0.1 us), another the event queue; nothing else is locked;
 *   - eviction / compaction (Python) only runs while no thread is searching.
 */
#include <stdio.h>
#include <time.h>

#include "mc.h"

enum { ST_NEW = 0, ST_EXPANDING = 1, ST_EXPANDED = 2, ST_TERMINAL = 3 };
enum { FL_HOOKED = 1, FL_EXT = 2 };

/* counters (int64, shared with Python) */
enum { C_NODES, C_EDGES, C_SIMS, C_SIMS_STARTED, C_PLAYOUTS, C_FULL, C_EV_DROPPED, C_EXPANSIONS,
       C_SUPERKO, C_DEPTH_SUM, C_DEPTH_MAX, C_TERMINAL, C_UNSTORED, C_EVENTS, C_PLAYOUT_NS, C_EXPAND_NS,
       C_NCTR = 16 };
/* parameters (double, shared with Python) */
enum { P_CPUCT, P_FPU, P_PW_K0, P_PW_C, P_PW_ALPHA, P_PW_ROOT, P_LAM, P_EXPAND_VISITS, P_NTHR, P_HOOK,
       P_HOOK_DEPTH, P_PLAYOUTS, P_MAX_DEPTH, P_STORE, P_PLAYOUT_MAXMOVES, P_NPRM = 32 };
/* reasons mc_tree_run returns */
enum { R_STOP = 1, R_TIME = 2, R_SIMS = 3, R_FULL = 4 };

#define MC_MAXDEPTH 512
#define MC_EV_PATH 64

#define RLX __ATOMIC_RELAXED
#define LD(x) __atomic_load_n(&(x), RLX)
#define ADD(x, v) __atomic_fetch_add(&(x), (v), RLX)

typedef struct {
    uint64_t key;
    int32_t node, depth, n, npath;
    MCBoard board;
    uint64_t path[MC_EV_PATH];   /* keys from the root side down to the node (the last entry) */
} MCEvent;

typedef struct {
    uint64_t* key;
    int32_t* n;        /* playout visits */
    double* w;         /* sum of playout values, side to move at the node */
    int32_t* nx;       /* external (LLM / value head) evaluations backed up through the node */
    double* wx;
    int32_t* vl;       /* virtual loss: simulations in flight through the node */
    float* vext;       /* the node's own external value, NaN if none */
    int64_t* estart;
    int16_t* nedges;
    uint8_t* state;
    uint8_t* flags;
    int8_t* to_play;
    int16_t* e_move;   /* gotree point index, -1 = pass */
    float* e_prior;    /* effective prior (learned, merged with external priors) */
    float* e_plearn;   /* learned prior at expansion */
    int32_t* e_child;  /* -1 until the child node is linked */
    int32_t* e_n;      /* visits through this edge */
    int64_t node_cap, edge_cap;
    int64_t* ctr;
    double* prm;
    /* transposition table (owned here, rebuilt on load and after compaction) */
    uint64_t* tt_key;
    int32_t* tt_val;
    int64_t tt_cap, tt_count;
    pthread_mutex_t mu;      /* transposition table and node creation */
    int32_t stop;
    int32_t root;
    MCBoard root_board;
    uint64_t* hist;          /* sorted stone hashes of the game positions before the root */
    int32_t nhist;
    MCPolicy pol;
    pthread_mutex_t ev_mu;   /* event queue */
    MCEvent* ev;
    int32_t ev_cap, ev_head, ev_count;
    int64_t deadline_ns, sims_target;
} MCTree;

typedef struct {
    MCBoard board, saved;
    uint64_t rng;
    int32_t pnode[MC_MAXDEPTH + 2];
    int64_t pedge[MC_MAXDEPTH + 2];   /* edge from pnode[d-1] to pnode[d] */
    uint64_t phash[MC_MAXDEPTH + 2];
    int npath;
    int16_t moves[MC_MAXMOVES];
    double logits[MC_MAXMOVES];
    int64_t excl[64];
    int nexcl;
} MCThread;

int64_t mc_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static inline double ldd(const double* p) {
    double v;
    __atomic_load(p, &v, RLX);
    return v;
}

static inline float ldf(const float* p) {
    float v;
    __atomic_load(p, &v, RLX);
    return v;
}

static inline void add_d(double* p, double v) {
    double cur, nv;
    __atomic_load(p, &cur, RLX);
    do {
        nv = cur + v;
    } while (!__atomic_compare_exchange(p, &cur, &nv, 1, RLX, RLX));
}

/* ------------------------------------------------------------------ transposition table (under mu) */
static void tt_put(uint64_t* keys, int32_t* vals, int64_t cap, uint64_t key, int32_t v) {
    int64_t i = (int64_t)(key & (uint64_t)(cap - 1));
    while (keys[i] != 0 && keys[i] != key) i = (i + 1) & (cap - 1);
    keys[i] = key;
    vals[i] = v;
}

static int tt_resize(MCTree* t, int64_t cap) {
    uint64_t* k = calloc((size_t)cap, sizeof(uint64_t));
    int32_t* v = malloc((size_t)cap * sizeof(int32_t));
    if (!k || !v) {
        free(k);
        free(v);
        return 0;
    }
    for (int64_t i = 0; i < t->tt_cap; i++)
        if (t->tt_key[i]) tt_put(k, v, cap, t->tt_key[i], t->tt_val[i]);
    free(t->tt_key);
    free(t->tt_val);
    t->tt_key = k;
    t->tt_val = v;
    t->tt_cap = cap;
    return 1;
}

static int32_t tt_find(const MCTree* t, uint64_t key) {
    int64_t i = (int64_t)(key & (uint64_t)(t->tt_cap - 1));
    for (;;) {
        uint64_t k = t->tt_key[i];
        if (k == key) return t->tt_val[i];
        if (k == 0) return -1;
        i = (i + 1) & (t->tt_cap - 1);
    }
}

static int tt_insert(MCTree* t, uint64_t key, int32_t v) {
    if ((t->tt_count + 1) * 2 > t->tt_cap && !tt_resize(t, t->tt_cap * 2)) return 0;
    tt_put(t->tt_key, t->tt_val, t->tt_cap, key, v);
    t->tt_count++;
    return 1;
}

/* ------------------------------------------------------------------ nodes (creation under mu) */
static int32_t new_node(MCTree* t, uint64_t key, const MCBoard* b) {
    int64_t i = LD(t->ctr[C_NODES]);
    if (i >= t->node_cap) return -1;
    if (!tt_insert(t, key, (int32_t)i)) return -1;
    t->key[i] = key;
    t->n[i] = 0;
    t->w[i] = 0;
    t->nx[i] = 0;
    t->wx[i] = 0;
    t->vl[i] = 0;
    t->vext[i] = NAN;
    t->estart[i] = -1;
    t->nedges[i] = 0;
    t->flags[i] = 0;
    t->to_play[i] = b->to_play;
    __atomic_store_n(&t->state[i], (uint8_t)(b->passes >= 2 ? ST_TERMINAL : ST_NEW), __ATOMIC_RELEASE);
    __atomic_store_n(&t->ctr[C_NODES], i + 1, __ATOMIC_RELEASE);
    return (int32_t)i;
}

/* Q of node c for its own side to move; virtual losses count as wins for c (losses for the
   parent that selects c).  *valid = 0 when there is nothing to average. */
static inline double node_q(const MCTree* t, int32_t c, int use_vl, int* valid) {
    const double lam = t->prm[P_LAM];
    const int32_t vl = use_vl ? LD(t->vl[c]) : 0;
    const int32_t n = LD(t->n[c]) + vl;
    const double qp = n > 0 ? (ldd(&t->w[c]) + vl) / n : 0.0;
    const int32_t nx = LD(t->nx[c]);
    if (nx > 0) {
        double qx = ldd(&t->wx[c]) / nx;
        *valid = 1;
        return n > 0 ? (1.0 - lam) * qx + lam * qp : qx;
    }
    *valid = n > 0;
    return qp;
}

static inline int is_excluded(const MCThread* th, int64_t e) {
    for (int i = 0; i < th->nexcl; i++)
        if (th->excl[i] == e) return 1;
    return 0;
}

/* PUCT over the admitted edges (progressive widening in prior order; every edge at the root unless
   pw_root, and at nodes that received external priors) */
static int64_t select_edge(const MCTree* t, const MCThread* th, int32_t node, int is_root) {
    const int64_t e0 = t->estart[node];
    const int ne = t->nedges[node];
    const int32_t nn = LD(t->n[node]);
    const double np = (double)nn + LD(t->vl[node]);
    const double sq = sqrt(np > 1 ? np : 1);
    int adm = ne;
    if ((!is_root || t->prm[P_PW_ROOT] > 0) && !(LD(t->flags[node]) & FL_EXT)) {
        double a = t->prm[P_PW_K0] + t->prm[P_PW_C] * pow((double)nn, t->prm[P_PW_ALPHA]);
        if (a < ne) adm = (int)a;
        if (adm < 1) adm = 1;
    }
    int valid;
    const double qp = node_q(t, node, 0, &valid);
    const double fpu_v = (valid ? qp : 0.0) - t->prm[P_FPU];
    const double cp = t->prm[P_CPUCT];
    int64_t best = -1;
    double bs = -1e300;
    for (int i = 0; i < adm; i++) {
        const int64_t e = e0 + i;
        if (th->nexcl && is_excluded(th, e)) continue;
        const int32_t c = LD(t->e_child[e]);
        double q = fpu_v;
        int vlc = 0;
        if (c >= 0) {
            double qc = node_q(t, c, 1, &valid);
            if (valid) q = -qc;
            vlc = LD(t->vl[c]);
        }
        const double sc = q + cp * ldf(&t->e_prior[e]) * sq / (1.0 + LD(t->e_n[e]) + vlc);
        if (sc > bs) {
            bs = sc;
            best = e;
        }
    }
    if (best < 0)   /* every admitted edge was excluded by superko: take the next one */
        for (int i = adm; i < ne; i++)
            if (!is_excluded(th, e0 + i)) return e0 + i;
    return best;
}

static int superko(const MCTree* t, const MCThread* th, uint64_t h) {
    for (int i = 0; i < th->npath; i++)
        if (th->phash[i] == h) return 1;
    int lo = 0, hi = t->nhist - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (t->hist[mid] == h) return 1;
        if (t->hist[mid] < h) lo = mid + 1;
        else hi = mid - 1;
    }
    return 0;
}

typedef struct {
    double p;
    int16_t m;
} PM;

static int pm_cmp(const void* a, const void* b) {
    const PM* x = a;
    const PM* y = b;
    if (x->p > y->p) return -1;
    if (x->p < y->p) return 1;
    return (x->m > y->m) - (x->m < y->m);
}

/* The caller moved state[node] NEW -> EXPANDING.  Computes the priors, allocates and writes the
   edges, publishes EXPANDED.  Returns 0 (state back to NEW) when the edge pool is full. */
static int expand(MCTree* t, MCThread* th, int32_t node, const MCBoard* b) {
    int nm = mc_all_logits(b, t->pol.w, t->pol.ladders_prior, th->moves, th->logits);
    PM pm[MC_MAXMOVES];
    double mx = -1e300, z = 0;
    for (int i = 0; i < nm; i++)
        if (th->logits[i] > mx) mx = th->logits[i];
    for (int i = 0; i < nm; i++) {
        pm[i].p = exp((th->logits[i] - mx) / t->pol.t_prior);
        pm[i].m = (int16_t)mc_gp(b, th->moves[i]);
        z += pm[i].p;
    }
    qsort(pm, (size_t)nm, sizeof(PM), pm_cmp);
    int64_t e0 = LD(t->ctr[C_EDGES]);
    do {
        if (e0 + nm > t->edge_cap) {
            __atomic_store_n(&t->ctr[C_FULL], 1, RLX);
            __atomic_store_n(&t->state[node], (uint8_t)ST_NEW, __ATOMIC_RELEASE);
            return 0;
        }
    } while (!__atomic_compare_exchange_n(&t->ctr[C_EDGES], &e0, e0 + nm, 1, RLX, RLX));
    for (int i = 0; i < nm; i++) {
        int64_t e = e0 + i;
        t->e_move[e] = pm[i].m;
        t->e_prior[e] = t->e_plearn[e] = (float)(pm[i].p / z);
        t->e_child[e] = -1;
        t->e_n[e] = 0;
    }
    t->estart[node] = e0;
    t->nedges[node] = (int16_t)nm;
    __atomic_store_n(&t->state[node], (uint8_t)ST_EXPANDED, __ATOMIC_RELEASE);
    ADD(t->ctr[C_EXPANSIONS], 1);
    return 1;
}

static void maybe_hook(MCTree* t, const MCThread* th, int32_t node, int depth, const MCBoard* b) {
    if (t->prm[P_HOOK] <= 0 || (LD(t->flags[node]) & FL_HOOKED)) return;
    if (!(depth <= (int)t->prm[P_HOOK_DEPTH] || (double)LD(t->n[node]) + 1 >= t->prm[P_NTHR])) return;
    if (__atomic_fetch_or(&t->flags[node], (uint8_t)FL_HOOKED, RLX) & FL_HOOKED) return;   /* claimed */
    pthread_mutex_lock(&t->ev_mu);
    if (t->ev_count >= t->ev_cap) {
        pthread_mutex_unlock(&t->ev_mu);
        __atomic_fetch_and(&t->flags[node], (uint8_t)~FL_HOOKED, RLX);   /* try again later */
        ADD(t->ctr[C_EV_DROPPED], 1);
        return;
    }
    MCEvent* e = &t->ev[(t->ev_head + t->ev_count) % t->ev_cap];
    e->key = t->key[node];
    e->node = node;
    e->depth = depth;
    e->n = LD(t->n[node]);
    e->board = *b;
    int np = th->npath, start = np > MC_EV_PATH ? np - MC_EV_PATH : 0;
    e->npath = np - start;
    for (int i = 0; i < e->npath; i++) e->path[i] = t->key[th->pnode[start + i]];
    t->ev_count++;
    pthread_mutex_unlock(&t->ev_mu);
    ADD(t->ctr[C_EVENTS], 1);
}

static int simulate(MCTree* t, MCThread* th) {
    MCBoard* b = &th->board;
    *b = t->root_board;
    int32_t node = t->root;
    int depth = 0, terminal = 0, full = 0;
    th->npath = 1;
    th->pnode[0] = node;
    th->pedge[0] = -1;
    th->phash[0] = b->hash;
    int maxd = (int)t->prm[P_MAX_DEPTH];
    if (maxd <= 0 || maxd > MC_MAXDEPTH) maxd = MC_MAXDEPTH;
    const int store = t->prm[P_STORE] > 0;

    ADD(t->vl[node], 1);
    for (;;) {
        uint8_t st = __atomic_load_n(&t->state[node], __ATOMIC_ACQUIRE);
        if (st == ST_TERMINAL) {
            terminal = 1;
            break;
        }
        maybe_hook(t, th, node, depth, b);
        if (st == ST_NEW) {
            if (store && (depth == 0 || (double)LD(t->n[node]) >= t->prm[P_EXPAND_VISITS])) {
                uint8_t expect = ST_NEW;
                if (__atomic_compare_exchange_n(&t->state[node], &expect, (uint8_t)ST_EXPANDING, 0,
                                                __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
                    int64_t t0 = mc_now_ns();
                    int ok = expand(t, th, node, b);
                    ADD(t->ctr[C_EXPAND_NS], mc_now_ns() - t0);
                    if (!ok) {
                        full = 1;
                        break;
                    }
                }
                continue;   /* expanded now (by us or another thread), or being expanded: look again */
            }
            break;
        }
        if (st == ST_EXPANDING || depth >= maxd) break;
        th->nexcl = 0;
        int64_t e;
        for (;;) {
            e = select_edge(t, th, node, depth == 0);
            if (e < 0) break;
            int bp = mc_bp(b, t->e_move[e]);
            if (bp == MC_PASS) {
                mc_play(b, MC_PASS);
                break;
            }
            th->saved = *b;
            int bad = mc_play(b, bp) != MC_OK;
            if (!bad && superko(t, th, b->hash)) {
                bad = 1;
                ADD(t->ctr[C_SUPERKO], 1);
            }
            if (!bad) break;
            *b = th->saved;
            if (th->nexcl < 64) th->excl[th->nexcl++] = e;
            else {
                e = -1;
                break;
            }
        }
        if (e < 0) break;
        int32_t c = __atomic_load_n(&t->e_child[e], __ATOMIC_ACQUIRE);
        if (c < 0) {
            uint64_t k = mc_key(b);
            pthread_mutex_lock(&t->mu);
            c = tt_find(t, k);
            if (c < 0 && store) {
                c = new_node(t, k, b);
                if (c < 0) {
                    __atomic_store_n(&t->ctr[C_FULL], 1, RLX);
                    full = 1;
                }
            }
            pthread_mutex_unlock(&t->mu);
            if (c < 0) {   /* tree full or frozen: evaluate the position without storing it */
                th->pnode[th->npath] = -1;
                th->pedge[th->npath] = e;
                th->phash[th->npath] = b->hash;
                th->npath++;
                ADD(t->ctr[C_UNSTORED], 1);
                break;
            }
            int32_t expect = -1;
            if (!__atomic_compare_exchange_n(&t->e_child[e], &expect, c, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
                c = expect;   /* linked by another thread meanwhile (to the same node) */
        }
        th->pnode[th->npath] = c;
        th->pedge[th->npath] = e;
        th->phash[th->npath] = b->hash;
        th->npath++;
        ADD(t->vl[c], 1);
        node = c;
        depth++;
    }

    /* evaluation */
    int k = (int)t->prm[P_PLAYOUTS];
    if (k < 1) k = 1;
    const int leaf_tp = b->to_play;
    double v = 0;
    int np = 0;
    if (terminal || b->passes >= 2) {
        float sc = mc_score(b);
        double z = sc > 0 ? 1.0 : sc < 0 ? -1.0 : 0.0;
        v = (leaf_tp == MC_BLACK ? z : -z) * k;
        terminal = 1;
    } else {
        int maxm = (int)t->prm[P_PLAYOUT_MAXMOVES];
        if (maxm <= 0) maxm = 3 * b->size * b->size;
        int64_t t0 = mc_now_ns();
        for (int i = 0; i < k; i++) {
            MCBoard pb = *b;
            mc_playout(&pb, &t->pol, &th->rng, maxm, NULL);
            float sc = mc_score(&pb);
            double z = sc > 0 ? 1.0 : sc < 0 ? -1.0 : 0.0;
            v += leaf_tp == MC_BLACK ? z : -z;
            np++;
        }
        ADD(t->ctr[C_PLAYOUT_NS], mc_now_ns() - t0);
    }
    int32_t leaf = th->pnode[th->npath - 1];
    double vx = 0;
    int hx = 0;
    if (leaf >= 0) {
        float ve;
        __atomic_load(&t->vext[leaf], &ve, RLX);
        if (!isnan(ve)) {
            hx = 1;
            vx = ve;
        }
    }

    /* backup */
    for (int d = th->npath - 1; d >= 0; d--) {
        int32_t nd = th->pnode[d];
        if (nd >= 0) {
            ADD(t->n[nd], k);
            add_d(&t->w[nd], v);
            ADD(t->vl[nd], -1);
            if (hx) {
                ADD(t->nx[nd], 1);
                add_d(&t->wx[nd], vx);
            }
        }
        if (d > 0) ADD(t->e_n[th->pedge[d]], k);
        v = -v;
        vx = -vx;
    }
    ADD(t->ctr[C_SIMS], 1);
    ADD(t->ctr[C_PLAYOUTS], np);
    if (terminal) ADD(t->ctr[C_TERMINAL], 1);
    ADD(t->ctr[C_DEPTH_SUM], th->npath - 1);
    int64_t dm = LD(t->ctr[C_DEPTH_MAX]);
    while (th->npath - 1 > dm && !__atomic_compare_exchange_n(&t->ctr[C_DEPTH_MAX], &dm, th->npath - 1, 1, RLX, RLX)) {
    }
    return full ? R_FULL : 0;
}

/* ------------------------------------------------------------------ exported */
MCTree* mc_tree_new(int ev_cap) {
    mc_init();
    MCTree* t = calloc(1, sizeof(MCTree));
    if (!t) return NULL;
    pthread_mutex_init(&t->mu, NULL);
    pthread_mutex_init(&t->ev_mu, NULL);
    t->ev_cap = ev_cap > 0 ? ev_cap : 1024;
    t->ev = calloc((size_t)t->ev_cap, sizeof(MCEvent));
    t->tt_cap = 1 << 16;
    t->tt_key = calloc((size_t)t->tt_cap, sizeof(uint64_t));
    t->tt_val = malloc((size_t)t->tt_cap * sizeof(int32_t));
    if (!t->ev || !t->tt_key || !t->tt_val) {
        free(t->ev);
        free(t->tt_key);
        free(t->tt_val);
        free(t);
        return NULL;
    }
    return t;
}

void mc_tree_free(MCTree* t) {
    if (!t) return;
    pthread_mutex_destroy(&t->mu);
    pthread_mutex_destroy(&t->ev_mu);
    free(t->ev);
    free(t->tt_key);
    free(t->tt_val);
    free(t->hist);
    free(t);
}

/* ptrs: key n w nx wx vl vext estart nedges state flags to_play e_move e_prior e_plearn e_child e_n ctr prm */
void mc_tree_attach(MCTree* t, void** ptrs, int64_t node_cap, int64_t edge_cap) {
    pthread_mutex_lock(&t->mu);
    int i = 0;
    t->key = ptrs[i++];
    t->n = ptrs[i++];
    t->w = ptrs[i++];
    t->nx = ptrs[i++];
    t->wx = ptrs[i++];
    t->vl = ptrs[i++];
    t->vext = ptrs[i++];
    t->estart = ptrs[i++];
    t->nedges = ptrs[i++];
    t->state = ptrs[i++];
    t->flags = ptrs[i++];
    t->to_play = ptrs[i++];
    t->e_move = ptrs[i++];
    t->e_prior = ptrs[i++];
    t->e_plearn = ptrs[i++];
    t->e_child = ptrs[i++];
    t->e_n = ptrs[i++];
    t->ctr = ptrs[i++];
    t->prm = ptrs[i++];
    t->node_cap = node_cap;
    t->edge_cap = edge_cap;
    pthread_mutex_unlock(&t->mu);
}

int mc_tree_rebuild_tt(MCTree* t) {
    pthread_mutex_lock(&t->mu);
    int64_t n = t->ctr[C_NODES], cap = 1 << 16;
    while (cap < 2 * (n + 1)) cap *= 2;
    uint64_t* k = calloc((size_t)cap, sizeof(uint64_t));
    int32_t* v = malloc((size_t)cap * sizeof(int32_t));
    int ok = k && v;
    if (ok) {
        free(t->tt_key);
        free(t->tt_val);
        t->tt_key = k;
        t->tt_val = v;
        t->tt_cap = cap;
        t->tt_count = n;
        for (int64_t i = 0; i < n; i++) tt_put(k, v, cap, t->key[i], (int32_t)i);
    } else {
        free(k);
        free(v);
    }
    pthread_mutex_unlock(&t->mu);
    return ok;
}

void mc_tree_set_root(MCTree* t, int32_t root, const MCBoard* b) {
    t->root = root;
    t->root_board = *b;
}

static int u64_cmp(const void* a, const void* b) {
    uint64_t x = *(const uint64_t*)a, y = *(const uint64_t*)b;
    return (x > y) - (x < y);
}

int mc_tree_set_history(MCTree* t, const uint64_t* h, int n) {
    uint64_t* c = malloc(sizeof(uint64_t) * (size_t)(n > 0 ? n : 1));
    if (!c) return 0;
    if (n > 0) memcpy(c, h, sizeof(uint64_t) * (size_t)n);
    qsort(c, (size_t)n, sizeof(uint64_t), u64_cmp);
    free(t->hist);
    t->hist = c;
    t->nhist = n;
    return 1;
}

void mc_tree_set_policy(MCTree* t, const double* w, int nf, double t_playout, double t_prior, int lad_playout,
                        int lad_prior) {
    mc_policy_set(&t->pol, w, nf, t_playout, t_prior, lad_playout, lad_prior);
}

void mc_tree_set_limits(MCTree* t, int64_t deadline_ns, int64_t sims_target) {
    t->deadline_ns = deadline_ns;
    t->sims_target = sims_target;
}

void mc_tree_set_stop(MCTree* t, int v) { __atomic_store_n(&t->stop, v, __ATOMIC_SEQ_CST); }

int mc_tree_run(MCTree* t, MCThread* th) {
    for (;;) {
        if (__atomic_load_n(&t->stop, RLX)) return R_STOP;
        if (__atomic_load_n(&t->ctr[C_FULL], RLX)) return R_FULL;
        if (t->deadline_ns && mc_now_ns() >= t->deadline_ns) return R_TIME;
        int64_t s = ADD(t->ctr[C_SIMS_STARTED], 1);
        if (t->sims_target && s >= t->sims_target) return R_SIMS;
        if (simulate(t, th) == R_FULL) return R_FULL;
    }
}

MCThread* mc_thread_new(uint64_t seed) {
    MCThread* th = calloc(1, sizeof(MCThread));
    if (!th) return NULL;
    th->rng = seed * 0x9E3779B97F4A7C15ULL + 0x632BE59BD9B4E019ULL;
    if (!th->rng) th->rng = 1;
    return th;
}

void mc_thread_free(MCThread* th) { free(th); }

int32_t mc_tree_find(MCTree* t, uint64_t key) {
    pthread_mutex_lock(&t->mu);
    int32_t i = tt_find(t, key);
    pthread_mutex_unlock(&t->mu);
    return i;
}

/* the node of position b: found through the table or created; -1 if the tree is full */
int32_t mc_tree_node_for(MCTree* t, const MCBoard* b) {
    pthread_mutex_lock(&t->mu);
    uint64_t k = mc_key(b);
    int32_t i = tt_find(t, k);
    if (i < 0) i = new_node(t, k, b);
    pthread_mutex_unlock(&t->mu);
    return i;
}

/* expand node i (position b) now; 1 if it is expanded afterwards (0: pool full, or another thread
   is expanding it right now) */
int mc_tree_expand(MCTree* t, int32_t i, const MCBoard* b, MCThread* th) {
    uint8_t expect = ST_NEW;
    if (__atomic_compare_exchange_n(&t->state[i], &expect, (uint8_t)ST_EXPANDING, 0, __ATOMIC_ACQ_REL,
                                    __ATOMIC_ACQUIRE))
        return expand(t, th, i, b);
    return expect == ST_EXPANDED;
}

/* prior = (1 - beta) * learned + beta * external, external normalised over the given moves that are
   edges of node i; written in place (edges never move during a search) and the node then admits all
   its moves (no progressive widening: the merged priors steer PUCT).  Returns the number of given
   moves that are edges (-1 if the node is not expanded). */
int mc_tree_merge_priors(MCTree* t, int32_t i, const int16_t* moves, const double* probs, int n, double beta) {
    if (__atomic_load_n(&t->state[i], __ATOMIC_ACQUIRE) != ST_EXPANDED) return -1;
    int64_t e0 = t->estart[i];
    int ne = t->nedges[i];
    double* ext = calloc((size_t)(ne > 0 ? ne : 1), sizeof(double));
    if (!ext) return -2;
    double tot = 0;
    int matched = 0;
    for (int j = 0; j < n; j++)
        for (int a = 0; a < ne; a++)
            if (t->e_move[e0 + a] == moves[j] && probs[j] > 0) {
                ext[a] += probs[j];
                tot += probs[j];
                matched++;
                break;
            }
    if (tot > 0) {
        for (int a = 0; a < ne; a++) {
            float p = (float)((1.0 - beta) * t->e_plearn[e0 + a] + beta * ext[a] / tot);
            __atomic_store(&t->e_prior[e0 + a], &p, RLX);
        }
        __atomic_fetch_or(&t->flags[i], (uint8_t)FL_EXT, RLX);
    }
    free(ext);
    return matched;
}

/* back up an external value v (side to move at keys[n-1]) through the nodes keys[0..n-1] that
   exist; if set_vext, store it as the node's own external value.  Returns the nodes updated. */
int mc_tree_backup_ext(MCTree* t, const uint64_t* keys, int n, double v, int set_vext) {
    int32_t idx[MC_EV_PATH + 1];
    if (n > MC_EV_PATH) {
        keys += n - MC_EV_PATH;
        n = MC_EV_PATH;
    }
    pthread_mutex_lock(&t->mu);
    for (int j = 0; j < n; j++) idx[j] = tt_find(t, keys[j]);
    pthread_mutex_unlock(&t->mu);
    int32_t node = n > 0 ? idx[n - 1] : -1;
    int done = 0;
    if (node >= 0) {
        if (set_vext) {
            float f = (float)v;
            __atomic_store(&t->vext[node], &f, RLX);
        }
        int8_t tp = t->to_play[node];
        for (int j = n - 1; j >= 0; j--) {
            int32_t i = idx[j];
            if (i < 0) continue;
            ADD(t->nx[i], 1);
            add_d(&t->wx[i], t->to_play[i] == tp ? v : -v);
            done++;
        }
    }
    return done;
}

/* info: node depth n npath; returns 1 if an event was popped */
int mc_tree_pop_event(MCTree* t, MCBoard* bout, uint64_t* path, int32_t* info, uint64_t* key) {
    pthread_mutex_lock(&t->ev_mu);
    if (!t->ev_count) {
        pthread_mutex_unlock(&t->ev_mu);
        return 0;
    }
    MCEvent* e = &t->ev[t->ev_head];
    *bout = e->board;
    memcpy(path, e->path, sizeof(uint64_t) * (size_t)e->npath);
    info[0] = e->node;
    info[1] = e->depth;
    info[2] = e->n;
    info[3] = e->npath;
    *key = e->key;
    t->ev_head = (t->ev_head + 1) % t->ev_cap;
    t->ev_count--;
    pthread_mutex_unlock(&t->ev_mu);
    return 1;
}

int mc_tree_clear_events(MCTree* t) {
    pthread_mutex_lock(&t->ev_mu);
    int n = t->ev_count;
    t->ev_head = 0;
    t->ev_count = 0;
    pthread_mutex_unlock(&t->ev_mu);
    return n;
}

/* mark[i] = 1 for every node reachable from root through child pointers; returns their count
   (call between searches) */
int64_t mc_tree_mark(MCTree* t, int32_t root, uint8_t* mark) {
    int64_t nn = t->ctr[C_NODES], cnt = 0;
    memset(mark, 0, (size_t)nn);
    int32_t* stack = malloc(sizeof(int32_t) * (size_t)(nn + 1));
    if (!stack) return -1;
    int64_t sp = 0;
    if (root >= 0 && root < nn) {
        stack[sp++] = root;
        mark[root] = 1;
    }
    while (sp) {
        int32_t i = stack[--sp];
        cnt++;
        if (t->state[i] != ST_EXPANDED) continue;
        int64_t e0 = t->estart[i];
        for (int a = 0; a < t->nedges[i]; a++) {
            int32_t c = t->e_child[e0 + a];
            if (c >= 0 && !mark[c]) {
                mark[c] = 1;
                stack[sp++] = c;
            }
        }
    }
    free(stack);
    return cnt;
}

int mc_ev_path_max(void) { return MC_EV_PATH; }
