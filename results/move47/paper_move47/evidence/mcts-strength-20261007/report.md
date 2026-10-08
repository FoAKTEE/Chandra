# Full system strength: MCTS v2 + model + heuristic learning (2026-10-08)

- condition: MCTS v2 + model service (sandboxed Opus 5.5 xhigh workers) + online heuristic learning (--learn --heuristics), one learning state, DAG and lesson memory shared by all games; 300 s/move, 28 search threads and at most 8 model sessions in flight per game; decision mcts/decide.py (evaluated)
- streams (parallel, one shared learning state): A: lv8 x2, k1-p x1 (B); B: lv7 x2, k1-p x1 (W)
- start: weights hl-v065 with 10 book rules (book v98), copied from `runs/move47/mcts-llm-hl-20261007/hybrid (hl/, dag.db, memory.db)`
- totals: 6 games finished (0 unfinished), 122 decisions, 1986 model sessions (abstract 88, expand 1672, heuristic 121, refute 105), 873.55 USD (7.16 per move); search 288.7 s and wall 338.6 s per move; decisions without model input 0; waited for the model 39608.6 s; failed sessions 45 (rate-limited 42)
- run dir: `runs/move47/mcts-strength-20261007`

| opponent (Elo) | games | W-L | B/W | Elo, 95% CI | point loss / move (reviewer) | blunders (>= 5) | match | search / wall s per move | sessions / move | USD / move | decision rules | end reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lv8 (2064) | 2 | 0-2 | 1/1 | 1805 [1344, 2266] | 2.338 (median 0.80) over 41 (g170e-b10c128, 1600 visits) | 5 | 0.219 | 290.1 / 340.2 | 17.2 | 7.32 | most_visits_evaluated 35, most_visits_unevaluated 6 | adjudicated 2 |
| k1-p (unrated) | 2 | 0-2 | 1/1 | - | 1.449 (median 0.70) over 38 (kata1-tf3-b11c768, 1600 visits) | 3 | 0.132 | 284.9 / 339.1 | 15.6 | 6.57 | most_visits_evaluated 31, most_visits_unevaluated 6, evaluated_among_top 1 | adjudicated 2 |
| lv7 (1850) | 2 | 1-1 | 1/1 | 1850 [1456, 2244] | 1.935 (median 0.35) over 43 (g170e-b10c128, 1600 visits) | 4 | 0.349 | 290.8 / 336.6 | 15.9 | 7.53 | most_visits_evaluated 36, evaluated_among_top 4, most_visits_unevaluated 3 | adjudicated 1, score 1 |

Pooled Elo over the 4 rated games (score 0.25): **1801**, 95% CI [1466, 2136] (se 171), on the calibrated b10c128 ladder scale (lv7 1850, lv8 2064), the arena's own fit (MAP, prior centred on the opponents' mean Elo, sd 350).

## Comparison

| system | opponent(s) | games | W-L | Elo, 95% CI | point loss / move (reviewer) | blunders | match | s / move | USD / move |
|---|---|---|---|---|---|---|---|---|---|
| full system (300 s/move) | lv8 | 2 | 0-2 | 1805 [1344, 2266] | 2.338 (g170e-b10c128) | 5 | 0.219 | 340 | 7.32 |
| full system (300 s/move) | k1-p | 2 | 0-2 | - | 1.449 (kata1-tf3-b11c768) | 3 | 0.132 | 339 | 6.57 |
| full system (300 s/move) | lv7 | 2 | 1-1 | 1850 [1456, 2244] | 1.935 (g170e-b10c128) | 4 | 0.349 | 337 | 7.53 |
| full system | lv7 + lv8 pooled | 4 | 1-3 | 1801 [1466, 2136] | | | | | |
| code-only ablation (30 s/move) | lv7 | 6 | 1-5 | 1629 [1327, 1931] | 1.607 (g170e-b10c128) | 20 | 0.259 | 33 | 0 |
| code-only ablation (30 s/move) | k1-full | 2 | 0-2 | - | 2.377 (kata1-tf3-b11c768) | 4 | 0.318 | 33 | 0 |
| code-only ablation (30 s/move) | lv8 | 6 | 0-6 | 1669 [1277, 2061] | 2.992 (g170e-b10c128) | 26 | 0.197 | 32 | 0 |
| code-only ablation | lv7 + lv8 pooled | 12 | 1-11 | 1596 [1320, 1872] | | | | | |
| v1 pilot (tree harness) | k1-full | 1 | 0-1 | - | 1.214 (kata1-tf3-b11c768) | 0 | 0.263 | 737 | 10.77 |

- point loss / move: mean over all our reviewed moves; the ladder arena's reviewer is its own b10c128 net, the kata1 arena's the strong net (kata1-tf3-b11c768, 1600 visits); only rows with the same reviewer compare.

## Heuristics book and weights

- learner: 122 updates in this run, 114 accepted; weights hl-v065 -> hl-v202; book 10 -> 36 active rules (book version 329)

| game | heuristic jobs | rules proposed / accepted / rejected | nudges proposed / accepted / rejected | weights first -> last |
|---|---|---|---|---|
| A0g1 lv8 (B) | 20 | 43 / 3 / 40 | 13 / 0 / 13 | hl-v065 -> hl-v110 |
| A0g2 lv8 (W) | 18 | 46 / 5 / 41 | 10 / 0 / 10 | hl-v113 -> hl-v153 |
| A1g1 k1-p (B) | 19 | 40 / 3 / 37 | 16 / 0 / 16 | hl-v156 -> hl-v196 |
| B0g1 lv7 (B) | 22 | 51 / 5 / 46 | 12 / 0 / 12 | hl-v065 -> hl-v115 |
| B0g2 lv7 (W) | 19 | 43 / 5 / 38 | 19 / 0 / 19 | hl-v116 -> hl-v161 |
| B1g1 k1-p (W) | 19 | 43 / 5 / 38 | 13 / 0 / 13 | hl-v163 -> hl-v199 |

Rules added during these games (the model's text; weight proposed -> now):

- R11 stretch-head-of-own-two-vs-side-press (A0g1p3): When an opponent stone presses beside the head stone of your two-stone line, stretch one point straight out at the head so they cannot hane at the head of two stones. [0.60 -> 0.51; held-out gain 0.0005]
- R12 capture-abandoned-armpit-stone (A0g1p11): Capturing a lone opponent stone left in atari in the armpit of your own bend, after they played far away, is usually slow; take the big point first. [-1.00 -> -0.76; held-out gain 0.0006]
- R13 kosumi-link-extension-of-lone-two-lib-stone (B0g1p29): Extend your lone two-liberty stone onto a point diagonal to another of your stones, with both linking points empty, so it gains a liberty and is miai-connected instead of being chased alone. [0.50 -> 1.05; held-out gain 0.0005]
- R14 one-two-point-contact-in-corner (A0g1p35): On the corner 1-2 point, with the 1-1 point empty, a first-line move touching an opponent stone (a block of their edge crawl or a hane under their 2-2 stone) is often the key liberty or eye-space point of a corner fight. [0.80 -> 0.67; held-out gain 0.0035]
- R15 corner-2-1-under-crowded-2-2-block (B0g1p33): In a crowded corner where the 2-2, 3-2, 2-3 and 3-3 points are all occupied, the empty 2-1 point beneath them is a vital eye and liberty point for both sides. [0.60 -> 0.46; held-out gain 0.0005]
- R16 connect-cut-lone-two-lib-stone-to-line (B0g1p33): When the opponent already holds one link point between your lone two-liberty stone and your line of stones, connect solidly at the other link point before they atari and cut there. [0.60 -> 0.32; held-out gain 0.0004]
- R17 first-line-block-end-of-opp-crawl-under-wall (B0g1p37): Block on the first line at the end of the opponent's first-line crawl of two or more stones, when your own second-line stone sits right above their end stone, so they cannot push further along the edge. [0.80 -> 1.02; held-out gain 0.0011]
- R18 edge-hane-under-strong-opp-boundary-stone (B0g1p41): On the first line, play directly under the opponent's second-line stone of a big safe chain when your own stone touches it diagonally; this edge hane or push settles the boundary and is bigger than it looks. [0.60 -> 0.55; held-out gain 0.0016]
- R19 complete-cut-through-knights-move (B0g2p6): When your stone already sits on one of the two middle points of the opponent's knight's move, play the other middle point to cut their stones apart. [0.60 -> 0.96; held-out gain 0.0048]
- R20 attach-lone-stone-with-jump-support (B0g2p4): Attach beside a lone opponent stone when your own stone sits a one-point jump behind the contact point, perpendicular to the contact, so the attachment is backed up and claims the side. [0.70 -> 0.90; held-out gain 0.0008]
- R21 atari-crosscut-stone-from-outside (A0g2p12): Ataring the opponent's lone two-liberty crosscutting stone from outside is usually slow even when the ladder works, because your own cut stones stay weak; take the big shape point instead. [-0.80 -> -0.40; held-out gain 0.0006]
- R22 hane-head-of-parallel-opp-two (B0g2p12): When your two-stone line and their two-stone line stand side by side, hane at the head of their pair, diagonally beyond your own head stone, before they hane at yours. [0.60 -> 0.43; held-out gain 0.0003]
- R23 diagonal-move-beside-own-atari-stone-liberty (A0g2p18): When your lone stone is in atari, a move diagonal to it right beside its last liberty neither saves it nor threatens much; the opponent simply captures, so escape or play elsewhere. [-0.80 -> -0.39; held-out gain 0.0017]
- R24 second-line-kosumi-under-opp-third-line-stone (A0g2p18): On the second line, the empty point diagonally under an opponent's third-line stone, with the points between them and toward the edge empty, undermines its base and is a big quiet move. [0.60 -> -0.18; held-out gain 0.0003]
- R25 extend-two-lib-group-to-three-libs (A0g2p20): When your chain of two or more stones is down to two liberties, extending it so it has three or more liberties is usually more urgent than a hane or a move elsewhere. [0.80 -> 0.51; held-out gain 0.0013]
- R26 fill-liberty-of-big-three-lib-chain (A0g2p28): When a large opponent chain of five or more stones is down to three liberties, taking one of those liberties (without self-atari) is usually the urgent move of a capturing race, ahead of side ataris on small chains. [0.90 -> 1.50; held-out gain 0.0011]
- R27 edge-connect-across-opp-cut (B0g2p28): On the first line, connect your edge stone to your own stone directly above it when an opponent stone sits on the cutting diagonal and one of the chains is short of liberties; it removes the cut and atari before capturing elsewhere. [0.80 -> 1.06; held-out gain 0.0006]
- R28 lone-stone-in-armpit-of-strong-chain (B0g2p38): A lone stone dropped into the inner corner of a strong opponent chain's bend, with no friendly stone around, gets only two liberties and is simply ataried; it is a poor invasion or reduction point. [-0.80 -> -1.13; held-out gain 0.0003]
- R29 butt-between-own-and-opp-jump-stones (B1g1p6): In open space, the empty point directly between your healthy stone and a healthy opponent stone a one-point jump away butts head-on into their stone; it strengthens both and is usually a poor move. [-0.80 -> -0.71; held-out gain 0.0002]
- R30 second-line-base-under-own-fourth-line-stone (A1g1p11): A second-line move with all eight neighbours empty, two lines below your own fourth-line stone (straight or one point along), makes a base for a weak group and is bigger than nearby contact moves. [0.60 -> -0.24; held-out gain 0.0003]
- R31 bare-second-line-cut-at-sole-link-two-libs (A1g1p23): Cutting directly at the single second-line link point between their edge stone and their third-line stone, when the cutting stone gets only two liberties, is premature: they atari from the open side and the cutter dies. [-0.70 -> -1.02; held-out gain 0.0018]
- R32 corner-2-2-under-own-pincered-2-3-stone (A1g1p25): Play the corner 2-2 point directly under your own lone stone on the 2-3 point when an opponent stone stands a one-point jump from it along the third line; it gives the invading stone a base and eye shape in their corner. [0.70 -> 1.02; held-out gain 0.0004]
- R33 block-under-own-3rd-line-stone-vs-gap-probe (B1g1p22): When their second-line probe sits diagonally under your third-line stone, block on the second line directly under your own stone, beside the probe, so it cannot slide under you. [0.60 -> 0.36; held-out gain 0.0011]
- R34 slow-capture-of-sealed-dead-stones (B1g1p28): Capturing opponent stones in atari whose last liberty lies between two of your own stones is usually slow: extending there would not save them, so they are already dead; play the big or vital point first. [-1.00 -> -0.71; held-out gain 0.0004]
- R35 atari-dead-chain-between-own-stones (B1g1p30): Ataring an opponent chain of 2-5 stones that is already ladder-dead, on a point between two of your own stones and away from their last move, is usually a slow gote move; the stones are dead anyway. [-0.80 -> -0.32; held-out gain 0.0007]
- R36 slow-capture-of-abandoned-inland-stones (B1g1p30): Capturing 1-3 inland opponent stones that they left in atari while playing elsewhere is usually slow; they were given up, so play the urgent point first. [-0.60 -> -0.32; held-out gain 0.0006]

## Games

| game | opponent | we | result | reason | plies | decisions | loss / move | blunders | USD | sessions | no model input | waited s | rules (decisions) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A0g1 | lv8 | B | W+ | adjudicated | 46 | 23 | 1.466 | 1 | 181.71 | 382 | 0 | 0 | most_visits_evaluated 18, most_visits_unevaluated 5 |
| A0g2 | lv8 | W | B+ | adjudicated | 37 | 18 | 3.453 | 4 | 118.46 | 324 | 0 | 9494.6 | most_visits_evaluated 17, most_visits_unevaluated 1 |
| A1g1 | k1-p | B | W+ | adjudicated | 38 | 19 | 1.657 | 2 | 119.95 | 281 | 0 | 10187.8 | most_visits_evaluated 15, most_visits_unevaluated 4 |
| B0g1 | lv7 | B | W+ | adjudicated | 48 | 24 | 3.312 | 4 | 198.65 | 364 | 0 | 0 | most_visits_evaluated 18, evaluated_among_top 4, most_visits_unevaluated 2 |
| B0g2 | lv7 | W | W+2.5 | score | 38 | 19 | 0.196 | 0 | 125.24 | 322 | 0 | 9808.2 | most_visits_evaluated 18, most_visits_unevaluated 1 |
| B1g1 | k1-p | W | B+ | adjudicated | 39 | 19 | 1.241 | 1 | 129.54 | 313 | 0 | 10118.0 | most_visits_evaluated 16, most_visits_unevaluated 2, evaluated_among_top 1 |
