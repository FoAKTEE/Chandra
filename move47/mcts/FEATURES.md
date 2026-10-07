# MCTS v2 move features and the weight-vector layout

One fixed feature spec serves the playout policy and the tree priors (and, later, the online
learner M7). A move's logit is the sum of the weights of its active features; the playout policy
samples `softmax(logit / playout_temperature)` over the legal moves that do not fill an own eye
(pass only when there is none), and an expanded tree node gets the priors
`softmax(logit / prior_temperature)` over all legal moves plus pass.

Spec name `move47-mcts-features-v1`; `mcts.features.spec_id()` adds a hash of the feature names
(`move47-mcts-features-v1:b3ab67489b29`). Weight files and saved trees carry it and are refused
by a build with another spec. Implementation: `csrc/features.c` (C, used by playouts and
expansion); `mcts/features.py` exposes it to Python.

## Layout (1148 weights)

| indices | name | count |
|---|---|---|
| 0 .. 1106 | `pat3:<8 chars>` colour-relative 3x3 patterns, canonical over the 8 symmetries | 1107 |
| 1107 .. 1110 | `capture:1`, `capture:2`, `capture:3-5`, `capture:6+` | 4 |
| 1111 .. 1114 | `escape:size1:libs2`, `escape:size1:libs3+`, `escape:size2+:libs2`, `escape:size2+:libs3+` | 4 |
| 1115 .. 1116 | `atari:size1`, `atari:size2+` | 2 |
| 1117 .. 1119 | `self_atari:size1`, `self_atari:size2-3`, `self_atari:size4+` | 3 |
| 1120 | `ladder:capture` | 1 |
| 1121 | `ladder:escape_fails` | 1 |
| 1122 .. 1130 | `dist_last:2`, `:3`, `:4`, `:5`, `:6`, `:7`, `:8`, `:9-10`, `:11+` | 9 |
| 1131 .. 1139 | `dist_last2:` same buckets | 9 |
| 1140 .. 1144 | `line:1`, `line:2`, `line:3`, `line:4`, `line:5+` | 5 |
| 1145 | `eye_fill` | 1 |
| 1146 | `pass` | 1 |
| 1147 | `pass:after_pass` | 1 |

`mcts.features.feature_names()` returns the names in index order. A non-pass move has exactly
one pattern feature plus any of the others, and the active list is sorted. A pass has `pass`, plus
`pass:after_pass` when the previous move was a pass.

## Definitions

Below, "own" means the side to move and "opponent" the other colour.

- **pat3.** The 8 neighbours of the move, clockwise from north (N NE E SE S SW W NW), each 2 bits:
  0 empty, 1 own, 2 opponent, 3 off-board. N takes the lowest bits. The code is canonicalised as
  the minimum over the 8 symmetries; with this order a quarter turn is a cyclic shift by two
  neighbours and the mirror maps neighbour i to (8 - i) mod 8. Only codes whose off-board set is
  empty, one edge or one corner exist: 954 interior + 135 edge + 18 corner = 1107. Indices are in
  ascending canonical code. The name spells the canonical code with `.` empty, `X` own,
  `O` opponent, `#` off-board, for example `pat3:OX......`.
- **capture:k.** k is the total size of the distinct adjacent opponent chains whose only liberty
  is the move.
- **escape:sizeS:libsL.** An adjacent own chain has exactly one liberty (the move), and after the
  move (captures included) the merged chain has L >= 2 liberties (2, or 3 and more). S is the total
  size of the adjacent own chains that were in atari.
- **atari:sizeS.** An adjacent opponent chain has exactly two liberties, one of them the move. S is
  the size of the largest such chain. Liberties that the move's own captures would add to it are
  not counted.
- **self_atari:sizeS.** After the move, captures included, the merged chain has exactly one
  liberty; S is its size. Taking a ko is `self_atari:size1` together with `capture:1`.
- **ladder:capture.** The move leaves an adjacent opponent chain with one liberty, and a ladder
  reading captures it. The reading: the defender extends at its liberty; with 3+ liberties it is
  free, with 1 it is dead; with 2 the attacker tries an atari at each liberty. Capturing an
  adjacent attacker chain in atari counts as an escape. The reading stops after 100 nodes and then
  counts as not captured.
- **ladder:escape_fails.** The move is an escape that leaves the merged chain with exactly two
  liberties, and the same reading, attacker to move, captures it.
- **dist_last:b / dist_last2:b.** Distance from the move to the previous move (the opponent's
  last move) and to the move before it (the mover's own previous move). The distance is
  d = dx + dy + max(dx, dy) (orthogonal neighbour 2, diagonal 3, one-point jump 4, knight's
  move 5, ...), bucketed as `2` (d <= 2), `3` ... `8`, `9-10`, `11+`. The feature is inactive when
  that move was a pass or does not exist. A `gotree.position.Position` carries only the last move,
  so for it `dist_last2` is never active; use `mcts.board.Board` (which tracks both) where it
  matters.
- **line:L.** Distance to the nearest edge + 1 (1 .. 4, `5+`).
- **eye_fill.** The move fills an own eye: every orthogonal neighbour is own or off-board, and
  there is no opponent stone on a diagonal (on the edge) or at most one (in the middle). This is
  the rule of `gotree.position.Position.is_own_eye`. Playouts never play such a move, whatever its
  weight. In the tree it is a legal edge with a low prior.
- **pass / pass:after_pass.** Pass, and pass right after the opponent passed.

Ladder features cost about 30% of the playout speed (1970 vs 1410 playouts/s from the empty 9x9
board, one thread). They are always computed for the tree
priors, and in playouts only with `MCTSConfig.ladders_playout=True` (default off). With the
default, a playout sees them as inactive. A learner that fits playout behaviour should use
`features(position, move, ladders=False)` for that purpose.

## Weight files

```json
{"format": "move47-mcts-weights/1", "spec": "move47-mcts-features-v1:b3ab67489b29",
 "version": "default-v1", "description": "...",
 "params": {"playout_temperature": 1.0, "prior_temperature": 1.0},
 "weights": {"capture:1": 2.0, "pat3:OX......": 1.0, "...": 0.0}}
```

Only non-zero weights are listed, by name, and missing names are 0. `params` may also set `lam`
and `beta` (the mixing weights of `MCTSConfig`); the engine applies them when it picks the weights
up. `mcts.weights.Weights` loads and saves the files. The default is
`mcts/weights/default-v1.json`, written by `python3 -m mcts weights --write-default` from
`mcts/weights.py`, and a test checks that the two agree. Providers: `StaticWeights`, and
`FileWeights(path)`, which re-reads a file that a learner replaces atomically. The engine asks its
provider at the start of every search.

## The hand-written default (`default-v1`)

The default holds simple tactical preferences, nothing learned. The online learner (M7) replaces
it.

| feature | weight |
|---|---|
| capture 1 / 2 / 3-5 / 6+ | +2.0 / +2.5 / +3.0 / +3.5 |
| escape size1 libs2 / size1 libs3+ / size2+ libs2 / size2+ libs3+ | +0.5 / +1.5 / +1.0 / +2.5 |
| atari size1 / size2+ | +0.4 / +0.8 |
| self_atari size1 / size2-3 / size4+ | -1.0 / -2.5 / -4.0 |
| ladder capture / escape fails | +1.5 / -2.5 |
| dist_last 2 / 3 / 4 / 5 / 6 | +1.0 / +1.0 / +0.6 / +0.4 / +0.2 |
| dist_last2 2 / 3 / 4 | +0.3 / +0.3 / +0.2 |
| line 1 / 2 / 3 / 4 | -1.0 / -0.2 / +0.2 / +0.1 |
| eye_fill | -6.0 |
| pass / pass:after_pass | -4.0 / +2.0 |
| pat3 matching a MoGo shape (473 patterns) | +1.0 |
| pat3 forming an empty triangle with no opponent stone around (23 patterns) | -0.5 |

The MoGo shapes are the 3x3 hane, cut and edge patterns of Gelly, Wang, Munos and Teytaud (2006),
"Modification of UCT with patterns in Monte-Carlo Go". They are written as templates in
`mcts/weights.py` (`MOGO_SHAPES`) and matched in any orientation and in either colour assignment.
Both temperatures are 1.

## Python API

```python
from mcts.board import Board
from mcts.features import features, move_logits, move_priors, feature_names
from mcts.weights import load_default

b = Board(9).play("E5").play("C3")          # or Board.from_position(gotree_position)
features(b, "D4")                           # -> [pattern index, ..., line index]
move_logits(b, load_default())              # -> {point or None: logit} for every legal move
move_priors(b, load_default(), temperature=1.0)
```
