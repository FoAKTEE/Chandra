/* Board rules: play with captures, simple ko and suicide; Tromp-Taylor area score; eyes; chains. */
#include "mc.h"

uint64_t mc_zob[3][MC_MAXPTS];
uint64_t mc_zob_ko[MC_MAXPTS];
uint64_t mc_zob_white;
uint64_t mc_zob_pass[3];

static uint64_t splitmix64(uint64_t* s) {
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

void mc_features_init(void);

static int mc_inited = 0;
static pthread_mutex_t mc_init_mu = PTHREAD_MUTEX_INITIALIZER;

void mc_init(void) {
    pthread_mutex_lock(&mc_init_mu);
    if (!mc_inited) {
        uint64_t s = 0x6D6F766534372D32ULL;   /* fixed seed: keys are stable across runs and files */
        for (int c = 0; c < 3; c++)
            for (int p = 0; p < MC_MAXPTS; p++) mc_zob[c][p] = c ? splitmix64(&s) : 0;
        for (int p = 0; p < MC_MAXPTS; p++) mc_zob_ko[p] = p ? splitmix64(&s) : 0;
        mc_zob_white = splitmix64(&s);
        mc_zob_pass[0] = 0;
        mc_zob_pass[1] = splitmix64(&s);
        mc_zob_pass[2] = splitmix64(&s);
        mc_features_init();
        mc_inited = 1;
    }
    pthread_mutex_unlock(&mc_init_mu);
}

void mc_board_clear(MCBoard* b, int size, float komi) {
    memset(b, 0, sizeof(*b));
    b->size = (int16_t)size;
    b->stride = (int16_t)(size + 2);
    b->to_play = MC_BLACK;
    b->komi = komi;
    for (int p = 0; p < MC_MAXPTS; p++) b->c[p] = MC_BORDER;
    for (int y = 0; y < size; y++)
        for (int x = 0; x < size; x++) b->c[(y + 1) * b->stride + x + 1] = MC_EMPTY;
}

/* thread-local marks for flood fills */
static __thread uint32_t tl_mark[MC_MAXPTS];
static __thread uint32_t tl_stamp;

static inline uint32_t new_stamp(void) {
    if (++tl_stamp == 0) {
        memset(tl_mark, 0, sizeof(tl_mark));
        tl_stamp = 1;
    }
    return tl_stamp;
}

int mc_chain_libs(const MCBoard* b, int p, int limit, int16_t* stones, int* ns) {
    uint32_t st = new_stamp();
    int16_t stack[MC_MAXPTS];
    int sp = 0, nl = 0, n = 0;
    const int s = b->stride;
    const int d[4] = {-s, 1, s, -1};
    uint8_t col = b->c[p];
    stack[sp++] = (int16_t)p;
    tl_mark[p] = st;
    while (sp) {
        int q = stack[--sp];
        if (stones) stones[n] = (int16_t)q;
        n++;
        for (int k = 0; k < 4; k++) {
            int r = q + d[k];
            if (tl_mark[r] == st) continue;
            uint8_t cr = b->c[r];
            if (cr == MC_EMPTY) {
                tl_mark[r] = st;
                if (++nl >= limit && !stones) return nl;
            } else if (cr == col) {
                tl_mark[r] = st;
                stack[sp++] = (int16_t)r;
            }
        }
    }
    if (ns) *ns = n;
    return nl;
}

int mc_play(MCBoard* b, int p) {
    if (b->passes >= 2) return MC_ERR_GAMEOVER;
    int me = b->to_play, opp = 3 - me;
    if (p == MC_PASS) {
        b->to_play = (int8_t)opp;
        b->ko = 0;
        b->passes++;
        b->last2 = b->last;
        b->last = 0;
        return MC_OK;
    }
    if (p <= 0 || p >= MC_MAXPTS || b->c[p] == MC_BORDER) return MC_ERR_OFFBOARD;
    if (b->c[p] != MC_EMPTY) return MC_ERR_OCCUPIED;
    if (p == b->ko) return MC_ERR_KO;
    const int s = b->stride;
    const int d[4] = {-s, 1, s, -1};
    b->c[p] = (uint8_t)me;
    b->hash ^= mc_zob[me][p];
    int16_t stones[MC_MAXPTS];
    int ns, captured = 0, cap_pt = 0;
    for (int k = 0; k < 4; k++) {
        int r = p + d[k];
        if (b->c[r] == opp && mc_chain_libs(b, r, 1, NULL, NULL) == 0) {
            mc_chain_libs(b, r, MC_MAXPTS, stones, &ns);
            for (int i = 0; i < ns; i++) {
                b->c[stones[i]] = MC_EMPTY;
                b->hash ^= mc_zob[opp][stones[i]];
            }
            captured += ns;
            cap_pt = stones[0];
        }
    }
    int own_nb = 0, empty_nb = 0;
    for (int k = 0; k < 4; k++) {
        uint8_t c = b->c[p + d[k]];
        if (c == me) own_nb++;
        else if (c == MC_EMPTY) empty_nb++;
    }
    int nl = own_nb ? mc_chain_libs(b, p, 1, NULL, NULL) : empty_nb;
    if (nl == 0) {   /* suicide (nothing was captured, or p would have a liberty) */
        b->c[p] = MC_EMPTY;
        b->hash ^= mc_zob[me][p];
        return MC_ERR_SUICIDE;
    }
    b->ko = (int16_t)((captured == 1 && own_nb == 0 && empty_nb == 1) ? cap_pt : 0);
    b->to_play = (int8_t)opp;
    b->passes = 0;
    b->last2 = b->last;
    b->last = (int16_t)p;
    return MC_OK;
}

int mc_is_legal(const MCBoard* b, int p) {
    if (p == MC_PASS) return b->passes < 2;
    if (p <= 0 || p >= MC_MAXPTS || b->c[p] != MC_EMPTY || p == b->ko || b->passes >= 2) return 0;
    const int s = b->stride;
    const int d[4] = {-s, 1, s, -1};
    int me = b->to_play, opp = 3 - me;
    for (int k = 0; k < 4; k++)
        if (b->c[p + d[k]] == MC_EMPTY) return 1;
    for (int k = 0; k < 4; k++) {
        int r = p + d[k];
        uint8_t c = b->c[r];
        if (c == me) {
            if (mc_chain_libs(b, r, 2, NULL, NULL) >= 2) return 1;
        } else if (c == opp) {
            if (mc_chain_libs(b, r, 2, NULL, NULL) == 1) return 1;
        }
    }
    return 0;
}

int mc_is_eye(const MCBoard* b, int p, int color) {
    if (b->c[p] != MC_EMPTY) return 0;
    const int s = b->stride;
    const int d[4] = {-s, 1, s, -1};
    const int dg[4] = {-s + 1, s + 1, s - 1, -s - 1};
    for (int k = 0; k < 4; k++) {
        uint8_t c = b->c[p + d[k]];
        if (c != color && c != MC_BORDER) return 0;
    }
    int bad = 0, off = 0;
    for (int k = 0; k < 4; k++) {
        uint8_t c = b->c[p + dg[k]];
        if (c == MC_BORDER) off++;
        else if (c == 3 - color) bad++;
    }
    return off ? bad == 0 : bad <= 1;
}

float mc_score(const MCBoard* b) {
    const int s = b->stride, n = b->size;
    const int d[4] = {-s, 1, s, -1};
    int score[3] = {0, 0, 0};
    uint32_t st = new_stamp();
    int16_t stack[MC_MAXPTS];
    for (int y = 0; y < n; y++) {
        for (int x = 0; x < n; x++) {
            int p = (y + 1) * s + x + 1;
            uint8_t c = b->c[p];
            if (c != MC_EMPTY) {
                score[c]++;
                continue;
            }
            if (tl_mark[p] == st) continue;
            int sp = 0, region = 0, border = 0;
            stack[sp++] = (int16_t)p;
            tl_mark[p] = st;
            while (sp) {
                int q = stack[--sp];
                region++;
                for (int k = 0; k < 4; k++) {
                    int r = q + d[k];
                    uint8_t cr = b->c[r];
                    if (cr == MC_EMPTY) {
                        if (tl_mark[r] != st) {
                            tl_mark[r] = st;
                            stack[sp++] = (int16_t)r;
                        }
                    } else if (cr != MC_BORDER) {
                        border |= cr;
                    }
                }
            }
            if (border == MC_BLACK) score[MC_BLACK] += region;
            else if (border == MC_WHITE) score[MC_WHITE] += region;
        }
    }
    return (float)(score[MC_BLACK] - score[MC_WHITE]) - b->komi;
}

void mc_chains(const MCBoard* b, MCChains* ch) {
    const int s = b->stride, n = b->size;
    const int d[4] = {-s, 1, s, -1};
    memset(ch->id, 0xFF, sizeof(int16_t) * (size_t)(s * s));
    ch->n = 0;
    int16_t stack[MC_MAXPTS];
    for (int y = 0; y < n; y++) {
        for (int x = 0; x < n; x++) {
            int p = (y + 1) * s + x + 1;
            uint8_t col = b->c[p];
            if (col == MC_EMPTY || ch->id[p] >= 0) continue;
            int i = ch->n++;
            uint32_t lst = new_stamp();
            int sp = 0, size = 0, nl = 0, prev = -1;
            stack[sp++] = (int16_t)p;
            ch->id[p] = (int16_t)i;
            ch->head[i] = (int16_t)p;
            while (sp) {
                int q = stack[--sp];
                size++;
                if (prev >= 0) ch->next[prev] = (int16_t)q;
                prev = q;
                for (int k = 0; k < 4; k++) {
                    int r = q + d[k];
                    uint8_t cr = b->c[r];
                    if (cr == MC_EMPTY) {
                        if (tl_mark[r] != lst) {
                            tl_mark[r] = lst;
                            if (nl < 4) ch->lib[i][nl] = (int16_t)r;
                            nl++;
                        }
                    } else if (cr == col && ch->id[r] < 0) {
                        ch->id[r] = (int16_t)i;
                        stack[sp++] = (int16_t)r;
                    }
                }
            }
            ch->next[prev] = -1;
            ch->size[i] = (int16_t)size;
            ch->nlibs[i] = (int16_t)nl;
        }
    }
}

int mc_chain_full(const MCBoard* b, int p, int16_t* stones, int* ns, int16_t* libs, int maxl) {
    uint32_t st = new_stamp();
    int16_t stack[MC_MAXPTS];
    int sp = 0, nl = 0, n = 0;
    const int s = b->stride;
    const int d[4] = {-s, 1, s, -1};
    uint8_t col = b->c[p];
    stack[sp++] = (int16_t)p;
    tl_mark[p] = st;
    while (sp) {
        int q = stack[--sp];
        if (stones) stones[n] = (int16_t)q;
        n++;
        for (int k = 0; k < 4; k++) {
            int r = q + d[k];
            if (tl_mark[r] == st) continue;
            uint8_t cr = b->c[r];
            if (cr == MC_EMPTY) {
                tl_mark[r] = st;
                if (nl < maxl) libs[nl] = (int16_t)r;
                nl++;
            } else if (cr == col) {
                tl_mark[r] = st;
                stack[sp++] = (int16_t)r;
            }
        }
    }
    if (ns) *ns = n;
    return nl;
}
