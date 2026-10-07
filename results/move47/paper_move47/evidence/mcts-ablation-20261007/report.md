# Code-only MCTS v2 ablation (2026-10-07)

- condition: MCTS v2 code only (--llm off), online learning (--learn), one learner shared by all games; 30 s/move, 16 search threads per game; decision most visits; root noise 0.25; model sessions 0 (0 USD)
- streams (parallel, one shared learner): A: lv7 x6, k1-full x1 (B); B: lv8 x6, k1-full x1 (W)
- run dir: `runs/move47/mcts-ablation-20261007`

| opponent (Elo) | games | W-L | B/W | Elo, 95% CI | point loss / move (reviewer) | blunders | match | search s / wall s per move | median sims / move | USD / move | end reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|
| lv7 (1850) | 6 | 1-5 | 3/3 | 1629 [1327, 1931] (se 154) | 1.607 (median 0.23) over 212 (g170e-b10c128, 1600 visits) | 20 | 0.259 | 33.15 / 36.79 | 2162958 | 0 | adjudicated 4, score 2 |
| k1-full (unrated) | 2 | 0-2 | 1/1 | - | 2.377 (median 0.07) over 44 (kata1-tf3-b11c768, 1600 visits) | 4 | 0.318 | 33.11 / 36.62 | 2030727 | 0 | adjudicated 2 |
| lv8 (2064) | 6 | 0-6 | 3/3 | 1669 [1277, 2061] (se 200) | 2.992 (median 1.25) over 127 (g170e-b10c128, 1600 visits) | 26 | 0.197 | 32.38 / 36.87 | 1795473 | 0 | adjudicated 6 |
| v1 pilot: k1-full | 1 | 0-1 | 1/0 | - | 1.214 (median 0.57) over 19 (kata1-tf3-b11c768, 1600 visits) | 0 | 0.263 | - / 736.6 | 33.0 model sessions | 10.77 | adjudicated 1 |

Pooled Elo over all 12 rated games (score 0.083): **1596**, 95% CI [1320, 1872] (se 141), on the calibrated b10c128 scale (random = 0; lv7 1850, lv8 2064).
- vs lv7 alone: the arena's own per-run rating 1629.0 (se 154.0) (same fit as the table; with 1 wins in 6 games it is dominated by the fit's prior, centred on that tier's Elo with sd 350: read the pooled value)
- vs lv8 alone: the arena's own per-run rating 1669.1 (se 200.0) (same fit as the table; with 0 wins in 6 games it is dominated by the fit's prior, centred on that tier's Elo with sd 350: read the pooled value)
- per-move search time above 31 s (tree eviction pauses at the 20M-node cap count in the move's search time): lv7 58 of 212 (max 53.2 s), k1-full 9 of 44 (max 50.4 s), lv8 20 of 127 (max 59.1 s)
- point loss / move: mean over all our reviewed moves of the opponent's games; the ladder arena's reviewer is its own b10c128 net, so only the k1-full rows compare with the v1 pilot

## Learning

- one OnlineLearner for all games: 383 updates, 157 accepted, now hl-v157; mean update 2.83 s
- weights version used per game (first -> last decision): lv7: Ag1:default-v1->hl-v023, Ag2:hl-v025->hl-v068, Ag3:hl-v070->hl-v096, Ag4:hl-v098->hl-v119, Ag5:hl-v119->hl-v137, Ag6:hl-v137->hl-v149; k1-full: Ag1:hl-v149->hl-v156, Bg1:hl-v118->hl-v129; lv8: Bg1:default-v1->hl-v024, Bg2:hl-v026->hl-v051, Bg3:hl-v051->hl-v072, Bg4:hl-v073->hl-v077, Bg5:hl-v078->hl-v098, Bg6:hl-v099->hl-v117
- accepted versions: hl-v001 (update 4), hl-v014 (update 26), hl-v027 (update 39), hl-v040 (update 55), hl-v053 (update 83), hl-v066 (update 104), hl-v079 (update 156), hl-v092 (update 179), hl-v105 (update 222), hl-v118 (update 253), hl-v131 (update 301), hl-v144 (update 356), hl-v157 (update 383)

## Games

| stream | opponent | game | we | result | reason | plies | loss/move | blunders | weights |
|---|---|---|---|---|---|---|---|---|---|
| A | lv7 | 1 | B | W+ | adjudicated | 38 | 2.232 | 2 | default-v1 -> hl-v023 |
| A | lv7 | 2 | W | B+ | adjudicated | 71 | 2.708 | 11 | hl-v025 -> hl-v068 |
| A | lv7 | 3 | B | W+12.5 | score | 95 | 0.585 | 0 | hl-v070 -> hl-v096 |
| A | lv7 | 4 | W | B+ | adjudicated | 57 | 2.471 | 4 | hl-v098 -> hl-v119 |
| A | lv7 | 5 | B | B+1.5 | score | 104 | 0.712 | 1 | hl-v119 -> hl-v137 |
| A | lv7 | 6 | W | B+ | adjudicated | 61 | 2.307 | 2 | hl-v137 -> hl-v149 |
| A | k1-full | 1 | B | W+ | adjudicated | 42 | 3.877 | 3 | hl-v149 -> hl-v156 |
| B | lv8 | 1 | B | W+ | adjudicated | 38 | 1.787 | 2 | default-v1 -> hl-v024 |
| B | lv8 | 2 | W | B+ | adjudicated | 43 | 1.787 | 2 | hl-v026 -> hl-v051 |
| B | lv8 | 3 | B | W+ | adjudicated | 38 | 4.219 | 7 | hl-v051 -> hl-v072 |
| B | lv8 | 4 | W | B+ | adjudicated | 37 | 3.553 | 6 | hl-v073 -> hl-v077 |
| B | lv8 | 5 | B | W+ | adjudicated | 54 | 4.065 | 6 | hl-v078 -> hl-v098 |
| B | lv8 | 6 | W | B+ | adjudicated | 47 | 2.375 | 3 | hl-v099 -> hl-v117 |
| B | k1-full | 1 | W | B+ | adjudicated | 47 | 1.008 | 1 | hl-v118 -> hl-v129 |

## Ply-22 judge reproduction (evidence judge-ply22)

- 20000 visits, 3 runs: H7 loss [1.76, 1.99, 2.1] (ranks [3, 3, 3]), E6 loss [2.89, 2.95, 2.97] (ranks [15, 15, 15]), best ['C2', 'G8', 'G8']; earlier ad-hoc run: H7 rank 4 loss 1.69, E6 rank 13 loss 2.91, best C2
