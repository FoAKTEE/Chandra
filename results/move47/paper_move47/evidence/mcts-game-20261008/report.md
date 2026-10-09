# Full system strength: MCTS v2 + model + heuristic learning (2026-10-08)

- condition: MCTS v2 + model service (sandboxed Opus 5.5 xhigh workers) + online heuristic learning (--learn --heuristics), one learning state, DAG and lesson memory shared by all games; 1800 s/move, 64 search threads and at most 8 model sessions in flight per game; decision mcts/decide.py (evaluated)
- streams (parallel, one shared learning state): A: k1-full x1 (B)
- start: weights hl-v202 with 36 book rules (book v329), copied from `runs/move47/mcts-strength-20261007 (hl/, dag.db, memory.db)`
- totals: 1 games finished (0 unfinished), 19 decisions, 1417 model sessions (abstract 18, expand 1366, heuristic 19, refute 14), 664.6 USD (34.979 per move); search 1632.3 s and wall 2162.9 s per move; decisions without model input 0; waited for the model 3033.8 s; failed sessions 20 (rate-limited 15)
- run dir: `runs/move47/mcts-game-20261008`

| opponent (Elo) | games | W-L | B/W | Elo, 95% CI | point loss / move (reviewer) | blunders (>= 5) | match | search / wall s per move | sessions / move | USD / move | decision rules | end reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| k1-full (unrated) | 1 | 0-1 | 1/0 | - | 1.836 (median 0.88) over 19 (kata1-tf3-b11c768, 1600 visits) | 1 | 0.211 | 1632.3 / 2162.9 | 74.6 | 34.98 | most_visits_evaluated 18, most_visits_unevaluated 1 | adjudicated 1 |

## Comparison

| system | opponent(s) | games | W-L | Elo, 95% CI | point loss / move (reviewer) | blunders | match | s / move | USD / move |
|---|---|---|---|---|---|---|---|---|---|
| full system (1800 s/move) | k1-full | 1 | 0-1 | - | 1.836 (kata1-tf3-b11c768) | 1 | 0.211 | 2163 | 34.98 |
| code-only ablation (30 s/move) | lv7 | 6 | 1-5 | 1629 [1327, 1931] | 1.607 (g170e-b10c128) | 20 | 0.259 | 33 | 0 |
| code-only ablation (30 s/move) | k1-full | 2 | 0-2 | - | 2.377 (kata1-tf3-b11c768) | 4 | 0.318 | 33 | 0 |
| code-only ablation (30 s/move) | lv8 | 6 | 0-6 | 1669 [1277, 2061] | 2.992 (g170e-b10c128) | 26 | 0.197 | 32 | 0 |
| code-only ablation | lv7 + lv8 pooled | 12 | 1-11 | 1596 [1320, 1872] | | | | | |
| v1 pilot (tree harness) | k1-full | 1 | 0-1 | - | 1.214 (kata1-tf3-b11c768) | 0 | 0.263 | 737 | 10.77 |

- point loss / move: mean over all our reviewed moves; the ladder arena's reviewer is its own b10c128 net, the kata1 arena's the strong net (kata1-tf3-b11c768, 1600 visits); only rows with the same reviewer compare.

## Heuristics book and weights

- learner: 19 updates in this run, 19 accepted; weights hl-v202 -> hl-v225; book 36 -> 40 active rules (book version 367)

| game | heuristic jobs | rules proposed / accepted / rejected | nudges proposed / accepted / rejected | weights first -> last |
|---|---|---|---|---|
| A0g1 k1-full (B) | 19 | 43 / 4 / 39 | 13 / 0 / 13 | hl-v202 -> hl-v223 |

Rules added during these games (the model's text; weight proposed -> now):

- R37 open-jump-cap-of-older-lone-opp-stone (A0g1p3): In an open area, the empty third- or fourth-line point a one-point jump straight out from a lone opponent stone they did not just play, with the point between and the stone's sides empty and no other opponent stone near, is a strong cap or approach. [1.20 -> 1.41; held-out gain 0.0007]
- R38 open-third-line-knight-approach-empty-area (A0g1p7): On the third line, in an otherwise empty 5x5 area with none of your stones, the point a knight's move from an opponent stone (or pair) is a big approach or corner move. It is often better than a contact reply near the last move. [0.80 -> 0.38; held-out gain 0.0007]
- R39 first-line-atari-chasing-escaping-chain (A0g1p33): A first-line atari on an opponent chain of two or more stones that escapes the ladder only pushes it out to join its friends; the atari stone gains nothing, so it is usually a slow gote move. [-0.80 -> 0.29; held-out gain 0.0002]
- R40 slow-fill-of-touched-diagonal-link (A0g1p37): Do not fill one cutting point of your own diagonal link when the other cutting point is still empty and opponent stones touch the point from both other sides: the link is miai, so the connection is slow even if it also takes a liberty. [-0.80 -> -0.24; held-out gain 0.0004]

## Games

| game | opponent | we | result | reason | plies | decisions | loss / move | blunders | USD | sessions | no model input | waited s | rules (decisions) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A0g1 | k1-full | B | W+ | adjudicated | 38 | 19 | 1.836 | 1 | 664.6 | 1417 | 0 | 3033.8 | most_visits_evaluated 18, most_visits_unevaluated 1 |
