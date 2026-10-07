/* Model-written move heuristics (node move47::mcts-llm-hl): matching compiled rules.
 *
 * A rule (gotree/heurdsl.py, compiled by mcts/rules.py) is a colour-relative 5x5 pattern around the
 * move, matched in any of its distinct orientations, plus integer conditions on the move's tactics
 * (the definitions of FEATURES.md).  The pattern test is four AND masks per orientation against the
 * move's 5x5 neighbourhood; conditions are tested first, tactics and ladders computed lazily once per
 * move.  Rules only add to the tree priors at expansion (mc_all_logits_r); playouts never see them.
 */
#include "mc.h"

/* flat spec layout (mcts/rules.py RULE_INTS) */
enum { S_NV = 0, S_FORBID = 1, S_CAP = 33, S_LIBS = 35, S_LINE = 37, S_DIST = 39, S_ATARI = 41, S_SELF = 42,
       S_ESC = 43, S_LCAP = 44, S_LESC = 45, S_OPP = 46, S_OWN = 51 };

int mc_rules_set(MCRules* R, const int32_t* spec, int n, const double* w) {
    if (n < 0) n = 0;
    if (n > MC_MAXRULES) n = MC_MAXRULES;
    memset(R, 0, sizeof(*R));
    for (int i = 0; i < n; i++) {
        const int32_t* s = spec + (size_t)i * MC_RULE_INTS;
        MCRule* r = &R->r[i];
        r->nv = s[S_NV] < 1 ? 1 : s[S_NV] > 8 ? 8 : s[S_NV];
        for (int v = 0; v < 8; v++)
            for (int k = 0; k < 4; k++) r->forbid[v][k] = (uint32_t)s[S_FORBID + 4 * v + k];
        r->cap_lo = (int16_t)s[S_CAP];
        r->cap_hi = (int16_t)s[S_CAP + 1];
        r->libs_lo = (int16_t)s[S_LIBS];
        r->libs_hi = (int16_t)s[S_LIBS + 1];
        r->line_lo = (int16_t)s[S_LINE];
        r->line_hi = (int16_t)s[S_LINE + 1];
        r->dist_lo = (int16_t)s[S_DIST];
        r->dist_hi = (int16_t)s[S_DIST + 1];
        r->atari = (int8_t)s[S_ATARI];
        r->self_atari = (int8_t)s[S_SELF];
        r->escape = (int8_t)s[S_ESC];
        r->lcap = (int8_t)s[S_LCAP];
        r->lesc = (int8_t)s[S_LESC];
        r->has_opp = (int8_t)s[S_OPP];
        r->opp_l_lo = (int16_t)s[S_OPP + 1];
        r->opp_l_hi = (int16_t)s[S_OPP + 2];
        r->opp_s_lo = (int16_t)s[S_OPP + 3];
        r->opp_s_hi = (int16_t)s[S_OPP + 4];
        r->has_own = (int8_t)s[S_OWN];
        r->own_l_lo = (int16_t)s[S_OWN + 1];
        r->own_l_hi = (int16_t)s[S_OWN + 2];
        r->own_s_lo = (int16_t)s[S_OWN + 3];
        r->own_s_hi = (int16_t)s[S_OWN + 4];
        r->need_tac = r->cap_lo >= 0 || r->libs_lo >= 0 || r->atari >= 0 || r->self_atari >= 0 || r->escape >= 0 ||
                      r->lcap >= 0 || r->lesc >= 0 || r->has_opp || r->has_own;
        /* prefilter: a rule can only match a move whose canonical 3x3 pattern is compatible with
           the centre 3x3 of one of its orientations (the orientations are closed under symmetry,
           so testing the canonical code against all of them is exact) */
        static const int cell[8] = {7, 8, 13, 18, 17, 16, 11, 6};   /* N NE E SE S SW W NW in the 5x5 grid */
        const uint32_t core_mask = (1u << 6) | (1u << 7) | (1u << 8) | (1u << 11) | (1u << 13) | (1u << 16) |
                                   (1u << 17) | (1u << 18);
        memset(r->core, 0, sizeof(r->core));
        for (int pi = 0; pi < mc_npat; pi++) {
            int code = mc_pat_code[pi];
            uint32_t m3[4] = {0, 0, 0, 0};
            for (int k = 0; k < 8; k++) m3[(code >> (2 * k)) & 3] |= 1u << cell[k];
            for (int v = 0; v < r->nv; v++) {
                if (!((m3[0] & r->forbid[v][0] & core_mask) | (m3[1] & r->forbid[v][1] & core_mask) |
                      (m3[2] & r->forbid[v][2] & core_mask) | (m3[3] & r->forbid[v][3] & core_mask))) {
                    r->core[pi >> 6] |= 1ULL << (pi & 63);
                    break;
                }
            }
        }
        R->w[i] = w ? w[i] : 0.0;
    }
    R->n = n;
    return n;
}

/* the move's facts, computed lazily (once per move, shared by all rules) */
typedef struct {
    int have_tac, lcap, lesc;    /* lcap / lesc: -1 not read yet */
    MCTac t;
    int nopp, nown;
    int16_t opp_l[4], opp_s[4], own_l[4], own_s[4];
} Facts;

static void facts_tac(const MCBoard* b, const MCChains* ch, int p, Facts* f) {
    if (f->have_tac) return;
    f->have_tac = 1;
    const int me = b->to_play, opp = 3 - me, s = b->stride;
    mc_tac(b, ch, p, me, &f->t);
    const int d[4] = {-s, 1, s, -1};
    int ids[4], nid = 0;
    f->nopp = f->nown = 0;
    for (int k = 0; k < 4; k++) {
        int r = p + d[k];
        uint8_t c = b->c[r];
        if (c != me && c != opp) continue;
        int id = ch->id[r], dup = 0;
        for (int i = 0; i < nid; i++)
            if (ids[i] == id) dup = 1;
        if (dup) continue;
        ids[nid++] = id;
        int nl = ch->nlibs[id] > 4 ? 4 : ch->nlibs[id];
        if (c == opp) {
            f->opp_l[f->nopp] = (int16_t)nl;
            f->opp_s[f->nopp++] = ch->size[id];
        } else {
            f->own_l[f->nown] = (int16_t)nl;
            f->own_s[f->nown++] = ch->size[id];
        }
    }
}

static inline int in_r(int v, int lo, int hi) { return v >= lo && v <= hi; }

static int chain_ok(int n, const int16_t* l, const int16_t* sz, int llo, int lhi, int slo, int shi) {
    for (int i = 0; i < n; i++)
        if ((llo < 0 || in_r(l[i], llo, lhi)) && (slo < 0 || in_r(sz[i], slo, shi))) return 1;
    return 0;
}

static inline int bit_of(int8_t want, int have) { return want < 0 || (want ? have != 0 : have == 0); }

static int match_one(const MCBoard* b, const MCChains* ch, int p, const MCRule* r, const uint32_t* m, int line,
                     int dist, Facts* f) {
    if (r->line_lo >= 0 && !in_r(line, r->line_lo, r->line_hi)) return 0;
    if (r->dist_lo >= 0 && (dist < 0 || !in_r(dist, r->dist_lo, r->dist_hi))) return 0;
    int ok = 0;
    for (int v = 0; v < r->nv && !ok; v++)
        ok = !((m[0] & r->forbid[v][0]) | (m[1] & r->forbid[v][1]) | (m[2] & r->forbid[v][2]) |
               (m[3] & r->forbid[v][3]));
    if (!ok) return 0;
    if (!r->need_tac) return 1;
    facts_tac(b, ch, p, f);
    const MCTac* t = &f->t;
    if (r->cap_lo >= 0 && !in_r(t->captures, r->cap_lo, r->cap_hi)) return 0;
    if (r->libs_lo >= 0 && !in_r(t->libs_after, r->libs_lo, r->libs_hi)) return 0;
    if (!bit_of(r->atari, t->atari_size)) return 0;
    if (!bit_of(r->self_atari, t->libs_after == 1)) return 0;
    if (!bit_of(r->escape, t->esc && t->libs_after >= 2)) return 0;
    if (r->has_opp && !chain_ok(f->nopp, f->opp_l, f->opp_s, r->opp_l_lo, r->opp_l_hi, r->opp_s_lo, r->opp_s_hi))
        return 0;
    if (r->has_own && !chain_ok(f->nown, f->own_l, f->own_s, r->own_l_lo, r->own_l_hi, r->own_s_lo, r->own_s_hi))
        return 0;
    if (r->lcap >= 0) {
        if (f->lcap < 0) f->lcap = t->atari_size ? mc_ladder_capture(b, p) : 0;
        if (!bit_of(r->lcap, f->lcap)) return 0;
    }
    if (r->lesc >= 0) {
        if (f->lesc < 0) f->lesc = (t->esc && t->libs_after == 2) ? mc_ladder_escape_fails(b, p) : 0;
        if (!bit_of(r->lesc, f->lesc)) return 0;
    }
    return 1;
}

static const uint8_t RMAP[3][4] = {{0, 0, 0, 3}, {0, 1, 2, 3}, {0, 2, 1, 3}};
#define GRID_MAX ((MC_MAXSIZE + 4) * (MC_MAXSIZE + 4))

/* the board's cell states relative to the side to move, with two rings of off-board cells */
static void state_grid(const MCBoard* b, uint8_t* g) {
    const int n = b->size, s = b->stride, gs = n + 4, me = b->to_play;
    memset(g, 3, (size_t)gs * gs);
    for (int y = 0; y < n; y++)
        for (int x = 0; x < n; x++) g[(y + 2) * gs + x + 2] = RMAP[me][b->c[(y + 1) * s + x + 1]];
}

/* lcap / lesc: the move's ladder readings when the caller already has them (-1: read lazily) */
static int rule_match(const MCBoard* b, const MCChains* ch, int p, const MCRules* R, int lcap, int lesc, int pi,
                      const uint8_t* grid, int* out) {
    if (!R || R->n <= 0 || p <= 0) return 0;
    const int s = b->stride, n = b->size, me = b->to_play, gs = n + 4;
    if (pi < 0) pi = mc_pat_index[mc_pattern_code(b, p, me)];
    int any = 0;
    for (int i = 0; i < R->n && !any; i++) any = (int)((R->r[i].core[pi >> 6] >> (pi & 63)) & 1);
    if (!any) return 0;
    const int x = p % s - 1, y = p / s - 1;
    uint32_t m[4] = {0, 0, 0, 0};
    const uint8_t* g0 = grid + y * gs + x;     /* the 5x5 window's top-left cell */
    for (int dy = 0; dy < 5; dy++)
        for (int dx = 0; dx < 5; dx++) m[g0[dy * gs + dx]] |= 1u << (dy * 5 + dx);
    int line = x;
    if (y < line) line = y;
    if (n - 1 - x < line) line = n - 1 - x;
    if (n - 1 - y < line) line = n - 1 - y;
    line += 1;
    int dist = -1;
    if (b->last > 0) {
        int dxl = abs(p % s - b->last % s), dyl = abs(p / s - b->last / s);
        dist = dxl + dyl + (dxl > dyl ? dxl : dyl);
    }
    Facts f;
    f.have_tac = 0;
    f.lcap = lcap;
    f.lesc = lesc;
    int k = 0;
    for (int i = 0; i < R->n; i++)
        if (((R->r[i].core[pi >> 6] >> (pi & 63)) & 1) && match_one(b, ch, p, &R->r[i], m, line, dist, &f))
            out[k++] = i;
    return k;
}

int mc_rule_match(const MCBoard* b, const MCChains* ch, int p, const MCRules* R, int* out) {
    uint8_t grid[GRID_MAX];
    state_grid(b, grid);
    return rule_match(b, ch, p, R, -1, -1, -1, grid, out);
}

int mc_all_logits_r(const MCBoard* b, const double* w, int ladders, const MCRules* R, int16_t* moves,
                    double* logits) {
    static __thread MCChains ch;
    int feats[MC_MAXACTIVE];
    int hit[MC_MAXRULES];
    uint8_t grid[GRID_MAX];
    int nm = 0;
    if (b->passes >= 2) return 0;
    mc_chains(b, &ch);
    state_grid(b, grid);
    const int s = b->stride, n = b->size;
    for (int y = 0; y < n; y++)
        for (int x = 0; x < n; x++) {
            int p = (y + 1) * s + x + 1;
            if (b->c[p] != MC_EMPTY) continue;
            int nf = mc_features(b, &ch, p, ladders, feats);
            if (nf < 0) continue;
            double l = 0;
            for (int i = 0; i < nf; i++) l += w[feats[i]];
            int lcap = -1, lesc = -1;
            if (ladders & 1) {          /* the features read both ladders already (FEATURES.md) */
                lcap = lesc = 0;
                for (int i = 0; i < nf; i++) {
                    if (feats[i] == mc_npat + T_LADDER_CAPTURE) lcap = 1;
                    if (feats[i] == mc_npat + T_LADDER_ESCAPE_FAILS) lesc = 1;
                }
            }
            int nh = rule_match(b, &ch, p, R, lcap, lesc, feats[0], grid, hit);   /* feats[0]: the 3x3 pattern */
            for (int i = 0; i < nh; i++) l += R->w[hit[i]];
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
