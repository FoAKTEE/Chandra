/* Move features (one fixed spec, see FEATURES.md) shared by the playout policy and the tree priors. */
#include "mc.h"

int mc_npat;
int16_t mc_pat_index[65536];
uint16_t mc_pat_code[MC_NPAT_MAX];

/* the 8 neighbours clockwise from north: N NE E SE S SW W NW */
static int pat_valid(int code) {
    int off = 0;
    for (int i = 0; i < 8; i++)
        if (((code >> (2 * i)) & 3) == 3) off |= 1 << i;
    /* off-board sets of a point on a board of size >= 2: none, one edge, or a corner */
    static const int ok[9] = {
        0,
        (1 << 0) | (1 << 1) | (1 << 7),                         /* top */
        (1 << 3) | (1 << 4) | (1 << 5),                         /* bottom */
        (1 << 5) | (1 << 6) | (1 << 7),                         /* left */
        (1 << 1) | (1 << 2) | (1 << 3),                         /* right */
        (1 << 0) | (1 << 1) | (1 << 7) | (1 << 5) | (1 << 6),   /* top-left */
        (1 << 0) | (1 << 1) | (1 << 7) | (1 << 2) | (1 << 3),   /* top-right */
        (1 << 3) | (1 << 4) | (1 << 5) | (1 << 6) | (1 << 7),   /* bottom-left */
        (1 << 3) | (1 << 4) | (1 << 5) | (1 << 1) | (1 << 2),   /* bottom-right */
    };
    for (int i = 0; i < 9; i++)
        if (off == ok[i]) return 1;
    return 0;
}

/* symmetry sigma: rotate by (sigma & 3) quarter turns, mirrored first if sigma & 4 */
static int pat_sym(int code, int sigma) {
    int k = sigma & 3, refl = sigma >> 2, out = 0;
    for (int i = 0; i < 8; i++) {
        int v = (code >> (2 * i)) & 3;
        int j = refl ? ((8 - i) + 2 * k) & 7 : (i + 2 * k) & 7;
        out |= v << (2 * j);
    }
    return out;
}

static int pat_canon(int code) {
    int best = code;
    for (int s = 1; s < 8; s++) {
        int c = pat_sym(code, s);
        if (c < best) best = c;
    }
    return best;
}

void mc_features_init(void) {
    static int16_t canon_index[65536];
    mc_npat = 0;
    for (int c = 0; c < 65536; c++) canon_index[c] = -1;
    for (int c = 0; c < 65536; c++) {
        if (!pat_valid(c) || pat_canon(c) != c) continue;
        canon_index[c] = (int16_t)mc_npat;
        mc_pat_code[mc_npat++] = (uint16_t)c;
    }
    for (int c = 0; c < 65536; c++) mc_pat_index[c] = pat_valid(c) ? canon_index[pat_canon(c)] : -1;
}

static const uint8_t vmap[3][4] = {{0, 0, 0, 3}, {0, 1, 2, 3}, {0, 2, 1, 3}};

int mc_pattern_code(const MCBoard* b, int p, int me) {
    const int s = b->stride;
    const int off[8] = {-s, -s + 1, 1, s + 1, s, s - 1, -1, -s - 1};
    const uint8_t* m = vmap[me];
    int code = 0;
    for (int i = 0; i < 8; i++) code |= m[b->c[p + off[i]]] << (2 * i);
    return code;
}

static inline int is_stone(uint8_t c) { return c == MC_BLACK || c == MC_WHITE; }

static inline int in_list(const int* a, int n, int v) {
    for (int i = 0; i < n; i++)
        if (a[i] == v) return 1;
    return 0;
}

static inline void add_lib(int16_t* libs, int* nl, int q) {
    if (*nl >= 4) return;
    for (int i = 0; i < *nl; i++)
        if (libs[i] == q) return;
    libs[(*nl)++] = (int16_t)q;
}

void mc_tac(const MCBoard* b, const MCChains* ch, int p, int me, MCTac* t) {
    memset(t, 0, sizeof(*t));
    if (b->c[p] != MC_EMPTY || p == b->ko || b->passes >= 2) return;
    const int s = b->stride;
    const int d[4] = {-s, 1, s, -1};
    const int opp = 3 - me;
    int own[4], nown = 0, opps[4], nopp = 0, cap[4], ncap = 0;
    int16_t libs[4];
    int nl = 0, big = 0, size_after = 1;
    for (int k = 0; k < 4; k++) {
        int r = p + d[k];
        uint8_t c = b->c[r];
        if (c == MC_EMPTY) {
            add_lib(libs, &nl, r);
        } else if (c == me) {
            int id = ch->id[r];
            if (in_list(own, nown, id)) continue;
            own[nown++] = id;
            size_after += ch->size[id];
            if (ch->nlibs[id] == 1) {
                t->esc = 1;
                t->esc_size += ch->size[id];
            }
        } else if (c == opp) {
            int id = ch->id[r];
            if (in_list(opps, nopp, id)) continue;
            opps[nopp++] = id;
            if (ch->nlibs[id] == 1) {
                cap[ncap++] = id;
                t->captures += ch->size[id];
            } else if (ch->nlibs[id] == 2 && ch->size[id] > t->atari_size) {
                t->atari_size = ch->size[id];
            }
        }
    }
    for (int i = 0; i < nown && !big; i++) {
        int id = own[i];
        if (ch->nlibs[id] > 4) {
            big = 1;
            break;
        }
        for (int j = 0; j < ch->nlibs[id]; j++)
            if (ch->lib[id][j] != p) add_lib(libs, &nl, ch->lib[id][j]);
    }
    for (int i = 0; i < ncap && !big && nl < 4; i++) {
        for (int q = ch->head[cap[i]]; q >= 0 && nl < 4; q = ch->next[q]) {
            int adj = 0;
            for (int k = 0; k < 4 && !adj; k++) {
                int r = q + d[k];
                if (r == p || (b->c[r] == me && in_list(own, nown, ch->id[r]))) adj = 1;
            }
            if (adj) add_lib(libs, &nl, q);
        }
    }
    t->libs_after = big ? 4 : nl;
    t->size_after = size_after;
    t->legal = t->libs_after >= 1;
}

/* ------------------------------------------------------------------ ladders */
#define LADDER_BUDGET 100

static int ladder_attack(const MCBoard* b, int s0, int* budget);

/* the chain through s0 has one liberty and its owner (the defender) is to move */
static int ladder_defend(const MCBoard* b, int s0, int* budget) {
    if (--*budget < 0) return 0;
    int16_t stones[MC_MAXPTS], libs[2];
    int ns;
    int nl = mc_chain_full(b, s0, stones, &ns, libs, 2);
    if (nl != 1) return nl == 0;
    const int s = b->stride;
    const int d[4] = {-s, 1, s, -1};
    int def = b->c[s0], att = 3 - def;
    for (int i = 0; i < ns; i++)        /* capturing an adjacent attacker chain counts as an escape */
        for (int k = 0; k < 4; k++) {
            int r = stones[i] + d[k];
            if (b->c[r] == att && mc_chain_libs(b, r, 2, NULL, NULL) == 1) return 0;
        }
    MCBoard nb = *b;
    nb.to_play = (int8_t)def;
    nb.passes = 0;
    if (mc_play(&nb, libs[0]) != MC_OK) return 1;
    int nl2 = mc_chain_libs(&nb, libs[0], 3, NULL, NULL);
    if (nl2 >= 3) return 0;
    if (nl2 <= 1) return 1;
    return ladder_attack(&nb, libs[0], budget);
}

/* the chain through s0 has two liberties and the attacker is to move */
static int ladder_attack(const MCBoard* b, int s0, int* budget) {
    if (--*budget < 0) return 0;
    int16_t libs[2];
    int nl = mc_chain_full(b, s0, NULL, NULL, libs, 2);
    if (nl != 2) return nl <= 1;
    int att = 3 - b->c[s0];
    for (int i = 0; i < 2; i++) {
        MCBoard nb = *b;
        nb.to_play = (int8_t)att;
        nb.passes = 0;
        if (mc_play(&nb, libs[i]) != MC_OK) continue;
        if (mc_chain_libs(&nb, s0, 2, NULL, NULL) != 1) continue;
        if (ladder_defend(&nb, s0, budget)) return 1;
    }
    return 0;
}

static int ladder_capture(const MCBoard* b, int p) {
    MCBoard nb = *b;
    if (mc_play(&nb, p) != MC_OK) return 0;
    const int s = b->stride;
    const int d[4] = {-s, 1, s, -1};
    int opp = nb.to_play;
    for (int k = 0; k < 4; k++) {
        int r = p + d[k];
        if (nb.c[r] == opp && mc_chain_libs(&nb, r, 2, NULL, NULL) == 1) {
            int budget = LADDER_BUDGET;
            if (ladder_defend(&nb, r, &budget)) return 1;
        }
    }
    return 0;
}

static int ladder_escape_fails(const MCBoard* b, int p) {
    MCBoard nb = *b;
    if (mc_play(&nb, p) != MC_OK) return 0;
    int budget = LADDER_BUDGET;
    return ladder_attack(&nb, p, &budget);
}

/* ------------------------------------------------------------------ features */
static inline int dist_bucket(const MCBoard* b, int p, int q) {
    const int s = b->stride;
    int dx = abs(p % s - q % s), dy = abs(p / s - q / s);
    int d = dx + dy + (dx > dy ? dx : dy);
    return d <= 2 ? 0 : d <= 8 ? d - 2 : d <= 10 ? 7 : 8;
}

static inline int line_bucket(const MCBoard* b, int p) {
    const int s = b->stride, n = b->size;
    int x = p % s - 1, y = p / s - 1;
    int l = x;
    if (y < l) l = y;
    if (n - 1 - x < l) l = n - 1 - x;
    if (n - 1 - y < l) l = n - 1 - y;
    return l >= 4 ? 4 : l;
}

int mc_features(const MCBoard* b, const MCChains* ch, int p, int ladders, int* out) {
    const int base = mc_npat;
    int n = 0;
    if (p == MC_PASS) {
        if (b->passes >= 2) return -1;
        out[n++] = base + T_PASS;
        if (b->passes > 0) out[n++] = base + T_PASS_AFTER_PASS;
        return n;
    }
    const int me = b->to_play;
    const int s = b->stride;
    out[n++] = mc_pat_index[mc_pattern_code(b, p, me)];
    if (!is_stone(b->c[p - s]) && !is_stone(b->c[p + 1]) && !is_stone(b->c[p + s]) && !is_stone(b->c[p - 1])) {
        /* no stone next to p: legal (p != ko), no tactics, not an eye */
        if (b->c[p] != MC_EMPTY || p == b->ko || b->passes >= 2) return -1;
        if (b->last > 0) out[n++] = base + T_DIST_LAST + dist_bucket(b, p, b->last);
        if (b->last2 > 0) out[n++] = base + T_DIST_LAST2 + dist_bucket(b, p, b->last2);
        out[n++] = base + T_LINE + line_bucket(b, p);
        return n;
    }
    MCTac t;
    mc_tac(b, ch, p, me, &t);
    if (!t.legal) return -1;
    if (t.captures)
        out[n++] = base + T_CAPTURE + (t.captures == 1 ? 0 : t.captures == 2 ? 1 : t.captures <= 5 ? 2 : 3);
    if (t.esc && t.libs_after >= 2)
        out[n++] = base + T_ESCAPE + (t.esc_size == 1 ? 0 : 2) + (t.libs_after == 2 ? 0 : 1);
    if (t.atari_size) out[n++] = base + T_ATARI + (t.atari_size == 1 ? 0 : 1);
    if (t.libs_after == 1)
        out[n++] = base + T_SELF_ATARI + (t.size_after == 1 ? 0 : t.size_after <= 3 ? 1 : 2);
    if (ladders & 1) {
        if (t.atari_size && ladder_capture(b, p)) out[n++] = base + T_LADDER_CAPTURE;
        if (t.esc && t.libs_after == 2 && ladder_escape_fails(b, p)) out[n++] = base + T_LADDER_ESCAPE_FAILS;
    }
    if (b->last > 0) out[n++] = base + T_DIST_LAST + dist_bucket(b, p, b->last);
    if (b->last2 > 0) out[n++] = base + T_DIST_LAST2 + dist_bucket(b, p, b->last2);
    out[n++] = base + T_LINE + line_bucket(b, p);
    if (!(ladders & 2) && mc_is_eye(b, p, me)) out[n++] = base + T_EYE_FILL;
    return n;
}

int mc_all_logits(const MCBoard* b, const double* w, int ladders, int16_t* moves, double* logits) {
    static __thread MCChains ch;
    int feats[MC_MAXACTIVE];
    int nm = 0;
    if (b->passes >= 2) return 0;
    mc_chains(b, &ch);
    const int s = b->stride, n = b->size;
    for (int y = 0; y < n; y++)
        for (int x = 0; x < n; x++) {
            int p = (y + 1) * s + x + 1;
            if (b->c[p] != MC_EMPTY) continue;
            int nf = mc_features(b, &ch, p, ladders, feats);
            if (nf < 0) continue;
            double l = 0;
            for (int i = 0; i < nf; i++) l += w[feats[i]];
            moves[nm] = (int16_t)p;
            logits[nm++] = l;
        }
    int nf = mc_features(b, &ch, MC_PASS, ladders, feats);
    double l = 0;
    for (int i = 0; i < nf; i++) l += w[feats[i]];
    moves[nm] = MC_PASS;
    logits[nm++] = l;
    return nm;
}

/* ------------------------------------------------------------------ playouts */
int mc_playout(MCBoard* b, const MCPolicy* pol, uint64_t* rng, int max_moves, int16_t* moves_out) {
    static __thread MCChains ch;
    int16_t cand[MC_MAXMOVES];
    double cw[MC_MAXMOVES];
    int feats[MC_MAXACTIVE];
    int nmoves = 0;
    const int s = b->stride, n = b->size;
    while (b->passes < 2 && nmoves < max_moves) {
        mc_chains(b, &ch);
        const int me = b->to_play;
        int nc = 0;
        double total = 0;
        for (int y = 0; y < n; y++)
            for (int x = 0; x < n; x++) {
                int p = (y + 1) * s + x + 1;
                if (b->c[p] != MC_EMPTY || p == b->ko || mc_is_eye(b, p, me)) continue;
                int nf = mc_features(b, &ch, p, (pol->ladders_playout ? 1 : 0) | 2, feats);
                if (nf < 0) continue;
                double g = 1.0;
                for (int i = 0; i < nf; i++) g *= pol->g[feats[i]];
                cand[nc] = (int16_t)p;
                cw[nc++] = g;
                total += g;
            }
        int mv = MC_PASS;
        if (nc > 0) {
            int i = 0;
            if (total > 0) {
                double r = mc_rand01(rng) * total;
                for (; i < nc - 1; i++) {
                    if (r < cw[i]) break;
                    r -= cw[i];
                }
            } else {
                i = (int)(mc_rand(rng) % (uint64_t)nc);
            }
            mv = cand[i];
        }
        if (mc_play(b, mv) != MC_OK) mc_play(b, MC_PASS);   /* cannot happen: candidates are legal */
        if (moves_out) moves_out[nmoves] = (int16_t)mv;
        nmoves++;
    }
    return nmoves;
}

void mc_policy_set(MCPolicy* pol, const double* w, int nf, double t_playout, double t_prior, int lad_playout,
                   int lad_prior) {
    if (nf > MC_NF_MAX) nf = MC_NF_MAX;
    memset(pol, 0, sizeof(*pol));
    pol->nf = nf;
    pol->t_playout = t_playout > 1e-6 ? t_playout : 1e-6;
    pol->t_prior = t_prior > 1e-6 ? t_prior : 1e-6;
    pol->ladders_playout = lad_playout;
    pol->ladders_prior = lad_prior;
    for (int i = 0; i < nf; i++) {
        double x = w[i];
        if (x > 50) x = 50;
        if (x < -50) x = -50;
        pol->w[i] = x;
        pol->g[i] = exp(x / pol->t_playout);
    }
}
