/* move47 MCTS v2: fast board, features, weighted playouts and the tree hot loop.
 *
 * Points are "bordered" indices bp = (y + 1) * stride + (x + 1) with stride = size + 2; the
 * Python side uses gotree's row-major index p = y * size + x (row 0 at the top) and -1 for pass.
 * Colours: 0 empty, 1 black, 2 white, 3 off-board.  Values in the tree are in [-1, 1] from the
 * point of view of the side to move at the node.
 */
#ifndef MC_H
#define MC_H

#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define MC_MAXSIZE 19
#define MC_MAXSTRIDE (MC_MAXSIZE + 2)
#define MC_MAXPTS (MC_MAXSTRIDE * MC_MAXSTRIDE)
#define MC_MAXMOVES (MC_MAXSIZE * MC_MAXSIZE + 1)

enum { MC_EMPTY = 0, MC_BLACK = 1, MC_WHITE = 2, MC_BORDER = 3 };
#define MC_PASS (-1)

enum { MC_OK = 0, MC_ERR_OCCUPIED = 1, MC_ERR_KO = 2, MC_ERR_SUICIDE = 3, MC_ERR_OFFBOARD = 4,
       MC_ERR_GAMEOVER = 5 };

typedef struct {
    int16_t size, stride;
    int8_t to_play, passes;   /* passes = consecutive passes so far (2 = game over) */
    int16_t ko;               /* bordered point the side to move may not play, 0 = none */
    int16_t last, last2;      /* bordered points of the last two moves, 0 = none or pass */
    float komi;
    uint64_t hash;            /* Zobrist of the stones only (positional superko) */
    uint8_t c[MC_MAXPTS];
} MCBoard;

/* ----------------------------------------------------------------- zobrist */
extern uint64_t mc_zob[3][MC_MAXPTS];
extern uint64_t mc_zob_ko[MC_MAXPTS];
extern uint64_t mc_zob_white;
extern uint64_t mc_zob_pass[3];

void mc_init(void);

static inline uint64_t mc_key(const MCBoard* b) {
    uint64_t k = b->hash ^ (b->to_play == MC_WHITE ? mc_zob_white : 0) ^ mc_zob_ko[b->ko] ^
                 mc_zob_pass[b->passes > 2 ? 2 : b->passes];
    return k ? k : 1;   /* 0 marks an empty transposition-table slot */
}

static inline int mc_bp(const MCBoard* b, int p) {
    return p < 0 ? MC_PASS : (p / b->size + 1) * b->stride + (p % b->size + 1);
}
static inline int mc_gp(const MCBoard* b, int bp) {
    return bp <= 0 ? -1 : (bp / b->stride - 1) * b->size + (bp % b->stride - 1);
}

/* ----------------------------------------------------------------- board */
void mc_board_clear(MCBoard* b, int size, float komi);
int mc_play(MCBoard* b, int bp);                 /* MC_OK or an MC_ERR_* code; no superko */
int mc_is_legal(const MCBoard* b, int bp);       /* simple ko + suicide */
int mc_chain_libs(const MCBoard* b, int p, int limit, int16_t* stones, int* ns);
/* full chain through stone p: stones (optional), and the first maxl liberties; returns the liberty count */
int mc_chain_full(const MCBoard* b, int p, int16_t* stones, int* ns, int16_t* libs, int maxl);
int mc_is_eye(const MCBoard* b, int bp, int color);
float mc_score(const MCBoard* b);                /* Tromp-Taylor: black - white - komi */

/* chains of a whole board, for the features */
typedef struct {
    int16_t id[MC_MAXPTS];     /* chain index per stone point, -1 elsewhere */
    int16_t next[MC_MAXPTS];   /* next stone of the same chain, -1 ends the list */
    int n;
    int16_t head[MC_MAXPTS];
    int16_t size[MC_MAXPTS];
    int16_t nlibs[MC_MAXPTS];  /* exact liberty count */
    int16_t lib[MC_MAXPTS][4]; /* the first (up to) four liberties */
} MCChains;

void mc_chains(const MCBoard* b, MCChains* ch);

/* ----------------------------------------------------------------- features */
#define MC_NPAT_MAX 1200
#define MC_NTAC 41
#define MC_NF_MAX (MC_NPAT_MAX + MC_NTAC)
#define MC_MAXACTIVE 16

/* tactical feature offsets after the pattern block (see FEATURES.md) */
enum {
    T_CAPTURE = 0,           /* 4: captures 1, 2, 3-5, 6+ stones */
    T_ESCAPE = 4,            /* 4: saved size 1 / 2+ x liberties after 2 / 3+ */
    T_ATARI = 8,             /* 2: puts a chain of size 1 / 2+ in atari */
    T_SELF_ATARI = 10,       /* 3: own chain left with one liberty, size 1 / 2-3 / 4+ */
    T_LADDER_CAPTURE = 13,
    T_LADDER_ESCAPE_FAILS = 14,
    T_DIST_LAST = 15,        /* 9 buckets */
    T_DIST_LAST2 = 24,       /* 9 buckets */
    T_LINE = 33,             /* 5: line 1..4, 5+ */
    T_EYE_FILL = 38,
    T_PASS = 39,
    T_PASS_AFTER_PASS = 40
};

extern int mc_npat;                    /* number of canonical 3x3 patterns (1107) */
extern int16_t mc_pat_index[65536];    /* raw code -> dense pattern index, -1 if impossible */
extern uint16_t mc_pat_code[MC_NPAT_MAX];

typedef struct {
    int nf;
    double w[MC_NF_MAX];       /* logits */
    double g[MC_NF_MAX];       /* playout gammas exp(w / t_playout) */
    double t_playout, t_prior;
    int ladders_playout, ladders_prior;
} MCPolicy;

typedef struct {
    int legal, captures, libs_after, size_after;
    int esc, esc_size;
    int atari_size;
} MCTac;

int mc_pattern_code(const MCBoard* b, int bp, int me);
void mc_tac(const MCBoard* b, const MCChains* ch, int bp, int me, MCTac* t);
/* active features of move bp (MC_PASS allowed); returns their count, or -1 if the move is illegal */
int mc_features(const MCBoard* b, const MCChains* ch, int bp, int ladders, int* out);
/* all legal moves (pass last) with their logits; returns the count */
int mc_all_logits(const MCBoard* b, const double* w, int ladders, int16_t* moves, double* logits);
void mc_policy_set(MCPolicy* pol, const double* w, int nf, double t_playout, double t_prior, int lad_playout,
                   int lad_prior);

/* ----------------------------------------------------------------- rules (rules.c)
   Model-written move heuristics (gotree/heurdsl.py), compiled by mcts/rules.py.  They add their
   weight to a matching move's logit in the tree priors (expansion), never in playouts. */
#define MC_MAXRULES 128
#define MC_RULE_INTS 64    /* ints per rule in the flat spec mcts/rules.py writes (56 used) */

typedef struct {
    int32_t nv;                    /* distinct orientations (1..8) */
    uint32_t forbid[8][4];         /* per orientation, per cell state (empty, own, opp, off): 5x5 cells
                                      (bit y*5+x) where that state is not allowed */
    int16_t cap_lo, cap_hi;        /* lo < 0: no condition */
    int16_t libs_lo, libs_hi;
    int16_t line_lo, line_hi;
    int16_t dist_lo, dist_hi;
    int8_t atari, self_atari, escape, lcap, lesc;   /* -1 any, 0 must not, 1 must */
    int8_t has_opp, has_own;
    int16_t opp_l_lo, opp_l_hi, opp_s_lo, opp_s_hi;
    int16_t own_l_lo, own_l_hi, own_s_lo, own_s_hi;
    int8_t need_tac;
    uint64_t core[(MC_NPAT_MAX + 63) / 64];   /* canonical 3x3 pattern indices the rule's centre allows */
} MCRule;

typedef struct {
    int32_t n;
    MCRule r[MC_MAXRULES];
    double w[MC_MAXRULES];
} MCRules;

int mc_ladder_capture(const MCBoard* b, int bp);       /* features.c: the ladder feature readings */
int mc_ladder_escape_fails(const MCBoard* b, int bp);
int mc_rules_set(MCRules* R, const int32_t* spec, int n, const double* w);
/* indices of the rules matching legal move bp (not pass); returns their count */
int mc_rule_match(const MCBoard* b, const MCChains* ch, int bp, const MCRules* R, int* out);
/* mc_all_logits plus the weights of the matching rules */
int mc_all_logits_r(const MCBoard* b, const double* w, int ladders, const MCRules* R, int16_t* moves,
                    double* logits);

/* ----------------------------------------------------------------- playouts */
static inline uint64_t mc_rand(uint64_t* s) {   /* xorshift64* */
    uint64_t x = *s;
    x ^= x >> 12; x ^= x << 25; x ^= x >> 27;
    *s = x;
    return x * 0x2545F4914F6CDD1DULL;
}
static inline double mc_rand01(uint64_t* s) { return (mc_rand(s) >> 11) * (1.0 / 9007199254740992.0); }

/* plays the position out with the weighted policy; returns the number of moves played
   (moves_out may be NULL); the final score is mc_score(b) */
int mc_playout(MCBoard* b, const MCPolicy* pol, uint64_t* rng, int max_moves, int16_t* moves_out);

#endif
