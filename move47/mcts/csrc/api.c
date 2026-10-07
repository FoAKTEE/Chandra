/* Python-facing wrappers: gotree point indices (p = y * size + x, -1 = pass) in and out. */
#include "mc.h"

int mc_board_sizeof(void) { return (int)sizeof(MCBoard); }
int mc_n_patterns(void) { mc_init(); return mc_npat; }
int mc_n_features(void) { mc_init(); return mc_npat + MC_NTAC; }
int mc_pattern_code_at(int i) { mc_init(); return (i >= 0 && i < mc_npat) ? mc_pat_code[i] : -1; }
int mc_pattern_index_of(int code) { mc_init(); return (code >= 0 && code < 65536) ? mc_pat_index[code] : -1; }

void mcb_clear(MCBoard* b, int size, float komi) {
    mc_init();
    mc_board_clear(b, size, komi);
}

/* cells: size*size values 0/1/2 (gotree order); ko/last/last2 gotree points or -1 */
int mcb_load(MCBoard* b, int size, float komi, const int8_t* cells, int to_play, int ko, int passes, int last,
             int last2) {
    mc_init();
    if (size < 2 || size > MC_MAXSIZE) return -1;
    mc_board_clear(b, size, komi);
    for (int p = 0; p < size * size; p++) {
        int c = cells[p];
        if (c < 0 || c > 2) return -1;
        int bp = mc_bp(b, p);
        b->c[bp] = (uint8_t)c;
        if (c) b->hash ^= mc_zob[c][bp];
    }
    b->to_play = (int8_t)(to_play == MC_WHITE ? MC_WHITE : MC_BLACK);
    b->ko = (int16_t)(ko >= 0 ? mc_bp(b, ko) : 0);
    b->passes = (int8_t)(passes < 0 ? 0 : passes > 2 ? 2 : passes);
    b->last = (int16_t)(last >= 0 ? mc_bp(b, last) : 0);
    b->last2 = (int16_t)(last2 >= 0 ? mc_bp(b, last2) : 0);
    return 0;
}

void mcb_cells(const MCBoard* b, int8_t* out) {
    for (int p = 0; p < b->size * b->size; p++) out[p] = (int8_t)b->c[mc_bp(b, p)];
}

/* size to_play ko passes last last2 */
void mcb_info(const MCBoard* b, int32_t* out) {
    out[0] = b->size;
    out[1] = b->to_play;
    out[2] = b->ko ? mc_gp(b, b->ko) : -1;
    out[3] = b->passes;
    out[4] = b->last ? mc_gp(b, b->last) : -1;
    out[5] = b->last2 ? mc_gp(b, b->last2) : -1;
}

float mcb_komi(const MCBoard* b) { return b->komi; }
uint64_t mcb_key(const MCBoard* b) { return mc_key(b); }
uint64_t mcb_hash(const MCBoard* b) { return b->hash; }

static int in_range(const MCBoard* b, int p) { return p >= -1 && p < b->size * b->size; }

int mcb_play(MCBoard* b, int p) {
    if (!in_range(b, p)) return MC_ERR_OFFBOARD;
    return mc_play(b, mc_bp(b, p));
}

int mcb_legal(const MCBoard* b, int p) { return in_range(b, p) && mc_is_legal(b, mc_bp(b, p)); }

int mcb_legal_moves(const MCBoard* b, int16_t* out) {
    int n = 0;
    for (int p = 0; p < b->size * b->size; p++)
        if (mc_is_legal(b, mc_bp(b, p))) out[n++] = (int16_t)p;
    return n;
}

float mcb_score(const MCBoard* b) { return mc_score(b); }

int mcb_is_eye(const MCBoard* b, int p, int color) {
    if (p < 0 || p >= b->size * b->size) return 0;
    return mc_is_eye(b, mc_bp(b, p), color);
}

int mcb_features(const MCBoard* b, int p, int ladders, int32_t* out) {
    static __thread MCChains ch;
    int f[MC_MAXACTIVE];
    if (!in_range(b, p)) return -1;
    mc_chains(b, &ch);
    int n = mc_features(b, &ch, mc_bp(b, p), ladders, f);
    for (int i = 0; i < n; i++) out[i] = f[i];
    return n;
}

int mcb_logits(const MCBoard* b, const double* w, int ladders, int16_t* moves, double* logits) {
    int n = mc_all_logits(b, w, ladders, moves, logits);
    for (int i = 0; i < n; i++) moves[i] = (int16_t)mc_gp(b, moves[i]);
    return n;
}

MCPolicy* mc_policy_new(void) {
    mc_init();
    return calloc(1, sizeof(MCPolicy));
}
void mc_policy_free(MCPolicy* p) { free(p); }

/* one playout from b (b is modified); moves_out (gotree points, may be NULL) */
int mcb_playout(MCBoard* b, const MCPolicy* pol, uint64_t seed, int max_moves, int16_t* moves_out) {
    uint64_t rng = seed * 0x9E3779B97F4A7C15ULL + 0x632BE59BD9B4E019ULL;
    if (!rng) rng = 1;
    if (max_moves <= 0) max_moves = 3 * b->size * b->size;
    int n = mc_playout(b, pol, &rng, max_moves, moves_out);
    if (moves_out)
        for (int i = 0; i < n; i++) moves_out[i] = (int16_t)mc_gp(b, moves_out[i]);
    return n;
}

/* n playouts from b (unchanged); scores[i] = final Tromp-Taylor score; returns total moves */
int64_t mcb_playouts(const MCBoard* b, const MCPolicy* pol, uint64_t seed, int n, float* scores) {
    uint64_t rng = seed * 0x9E3779B97F4A7C15ULL + 0x632BE59BD9B4E019ULL;
    if (!rng) rng = 1;
    int64_t moves = 0;
    for (int i = 0; i < n; i++) {
        MCBoard pb = *b;
        moves += mc_playout(&pb, pol, &rng, 3 * b->size * b->size, NULL);
        if (scores) scores[i] = mc_score(&pb);
    }
    return moves;
}

/* ---------------------------------------------------------------- rules (mcts/rules.py) */
MCRules* mc_rules_new(void) {
    mc_init();
    return calloc(1, sizeof(MCRules));
}
void mc_rules_free(MCRules* r) { free(r); }
int mc_rules_load(MCRules* r, const int32_t* spec, int n, const double* w) { return mc_rules_set(r, spec, n, w); }
int mc_rule_ints(void) { return MC_RULE_INTS; }
int mc_max_rules(void) { return MC_MAXRULES; }

/* For each of the nm moves (gotree points; pass and illegal moves match nothing): counts[i] = rules
   matching it, their indices appended to idx (at most cap in all).  Returns the total. */
int mcb_rule_hits(const MCBoard* b, const MCRules* R, const int16_t* moves, int nm, int32_t* counts, int32_t* idx,
                  int cap) {
    static __thread MCChains ch;
    int hit[MC_MAXRULES], feats[MC_MAXACTIVE];
    int tot = 0;
    mc_chains(b, &ch);
    for (int i = 0; i < nm; i++) {
        counts[i] = 0;
        int p = moves[i];
        if (p < 0 || !in_range(b, p)) continue;
        int bp = mc_bp(b, p);
        if (b->c[bp] != MC_EMPTY || mc_features(b, &ch, bp, 0, feats) < 0) continue;
        int nh = mc_rule_match(b, &ch, bp, R, hit);
        for (int k = 0; k < nh && tot < cap; k++) idx[tot++] = hit[k];
        counts[i] = nh;
    }
    return tot;
}

int mcb_logits_r(const MCBoard* b, const double* w, int ladders, const MCRules* R, int16_t* moves, double* logits) {
    int n = mc_all_logits_r(b, w, ladders, R, moves, logits);
    for (int i = 0; i < n; i++) moves[i] = (int16_t)mc_gp(b, moves[i]);
    return n;
}
