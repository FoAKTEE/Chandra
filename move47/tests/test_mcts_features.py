"""MCTS v2 features, weights and playouts."""
import json
import random

import numpy as np
import pytest

from gotree.position import Position, sym_maps
from mcts._lib import N_FEATURES, N_PATTERNS
from mcts.board import Board
from mcts.features import (TACTICAL, feature_index, feature_names, features, move_logits, move_priors,
                           pattern_code, spec_id)
from mcts.policy import Policy
from mcts.weights import DEFAULT_PATH, FileWeights, Weights, default_weights, load_default, mogo_shape

NAMES = feature_names()


def mk(rows, to_play="X"):
    return Board.from_position(Position(len(rows), "".join(r.replace(" ", "") for r in rows), to_play))


def names(b, m):
    return [NAMES[i] for i in features(b, m)]


LADDER = [". . . . . . . . .",
          ". . . . . . . . .",
          ". . . . . . . . .",
          ". . . . . . . . .",
          ". . . X . . . . .",
          ". . X O . . . . .",
          ". . . . X . . . .",
          ". . . . . . . . .",
          ". . . . . . . . ."]


def _random_position(seed, size=9, plies=40):
    rng = random.Random(seed)
    pos = Position.empty(size)
    prev = None
    for _ in range(plies):
        cand = [p for p in pos.legal_moves() if not pos.is_own_eye(p)]
        if not cand:
            break
        m = rng.choice(cand)
        prev = pos.last
        pos = pos.play(m)
    return pos, prev


def test_spec_layout():
    assert N_PATTERNS == 1107                      # 3x3 colour-relative patterns up to the 8 symmetries
    assert N_FEATURES == N_PATTERNS + len(TACTICAL) == len(NAMES)
    assert len(set(NAMES)) == len(NAMES)
    assert NAMES[N_PATTERNS] == "capture:1" and NAMES[-1] == "pass:after_pass"
    codes = [pattern_code(i) for i in range(N_PATTERNS)]
    assert codes == sorted(codes)
    assert spec_id().startswith("move47-mcts-features-v1:")


def test_features_deterministic_and_symmetric():
    for seed in range(6):
        pos, last2 = _random_position(seed)
        b = Board.from_position(pos, last2)
        legal = pos.legal_moves()
        fwd, _ = sym_maps(9)
        for m in legal[:25] + [None]:
            f0 = features(b, m)
            assert f0 == features(Board.from_position(pos, last2), m) == sorted(f0)
            for s in range(8):
                t = pos.transformed(s)
                bt = Board.from_position(t, None if last2 is None else fwd[s][last2])
                assert features(bt, None if m is None else fwd[s][m]) == f0


def test_logits_are_sums_of_active_weights():
    w = np.random.default_rng(0).normal(size=N_FEATURES)
    for seed in range(3):
        pos, last2 = _random_position(10 + seed, plies=50)
        b = Board.from_position(pos, last2)
        lg = move_logits(b, w)
        assert set(lg) == set(pos.legal_moves()) | {None}
        for m, v in lg.items():
            assert v == pytest.approx(sum(w[i] for i in features(b, m)))
        pr = move_priors(b, Weights(w), temperature=1.0)
        assert sum(pr.values()) == pytest.approx(1.0)


def test_tactical_features_on_constructed_positions():
    lad = mk(LADDER)
    assert "ladder:capture" in names(lad, "E4") and "atari:size1" in names(lad, "E4")
    broken = [list(r.replace(" ", "")) for r in LADDER]
    broken[7][1] = "O"                                     # a white stone at B2 breaks the ladder
    assert "ladder:capture" not in names(mk(["".join(r) for r in broken]), "E4")
    esc = lad.played("E4")                                 # white to move, D4 in atari
    assert {"escape:size1:libs2", "ladder:escape_fails"} <= set(names(esc, "D3"))
    cap = mk([". . . . . . . . .",
              ". . . . . . . . .",
              ". . X X X . . . .",
              ". X O O O X . . .",
              ". . X X O X . . .",
              ". . . . . . . . .",
              ". . . . . . . . .",
              ". . . . . . . . .",
              ". . . . . . . . ."])
    assert "capture:3-5" in names(cap, "E4")
    sa = mk([". . . . . . . . .",
             ". . O O O . . . .",
             ". O X X X O . . .",
             ". O X . X O . . .",
             ". . O X O . . . .",
             ". . . . . . . . .",
             ". . . . . . . . .",
             ". . . . . . . . .",
             ". . . . . . . . ."])
    assert "self_atari:size4+" in names(sa, "D6")
    eye = mk([". X . . . . . . .",
              "X X . . . . . . .",
              ". . . . . . . . .",
              ". . . . . . . . .",
              ". . . . . . . . .",
              ". . . . . . . . .",
              ". . . . . . . . .",
              ". . . . . . . . .",
              ". . . . . . . . ."])
    assert "eye_fill" in names(eye, "A9") and "line:1" in names(eye, "A9")
    assert names(eye, None) == ["pass"] and names(eye.played(None), None) == ["pass", "pass:after_pass"]
    near = Board(9).play("E5")
    assert "dist_last:2" in names(near, "E6") and "dist_last:3" in names(near, "D6") and "line:4" in names(near, "E6")
    assert names(Board(9), "E5") == ["pat3:........", "line:5+"]
    with pytest.raises(ValueError):
        features(near, "E5")                              # occupied


def test_default_weights_file_is_reproducible():
    w = default_weights()
    stored = json.loads(DEFAULT_PATH.read_text())
    assert stored == json.loads(json.dumps(w.to_json()))  # `python3 -m mcts weights --write-default`
    assert load_default().version == "default-v1" and stored["spec"] == spec_id()
    idx = feature_index()
    assert w.w[idx["capture:1"]] > 0 > w.w[idx["self_atari:size4+"]]
    assert mogo_shape(pattern_code(0)) is None             # the empty neighbourhood is no shape


def test_weight_files_round_trip_and_provider(tmp_path):
    w = default_weights()
    w2 = Weights(w.w * 0.5, "half", {"lam": 0.3})
    p = w2.save(tmp_path / "w.json")
    r = Weights.load(p)
    assert np.allclose(r.w, w2.w, atol=1e-6) and r.version == "half" and r.params == {"lam": 0.3}
    prov = FileWeights(p)
    assert prov.get().version == "half"
    Weights(w.w, "full").save(p)
    assert prov.get().version == "full"
    bad = json.loads(p.read_text())
    bad["spec"] = "other"
    with pytest.raises(ValueError):
        Weights.from_json(bad)


def _scorable(pos):
    """Every empty region borders stones of one colour only (or none)."""
    nb = [[q for q in (p - 9, p + 9, p - 1, p + 1) if 0 <= q < 81 and (abs(q - p) == 9 or q // 9 == p // 9)]
          for p in range(81)]
    seen = set()
    for p in range(81):
        if pos.cells[p] != "." or p in seen:
            continue
        stack, border = [p], set()
        seen.add(p)
        while stack:
            q = stack.pop()
            for r in nb[q]:
                if pos.cells[r] == ".":
                    if r not in seen:
                        seen.add(r)
                        stack.append(r)
                else:
                    border.add(pos.cells[r])
        if len(border) > 1:
            return False
    return True


def test_playouts_never_fill_own_eyes_and_end_scorable():
    pol = Policy(default_weights())
    starts = [Board(9), Board.from_position(_random_position(3, plies=30)[0])]
    for i in range(40):
        b0 = starts[i % 2]
        b = b0.copy()
        moves = b.playout(pol, seed=i)
        pos = b0.to_position()
        for m in moves:
            assert m is None or not pos.is_own_eye(m), "playout filled its own eye"
            assert pos.is_legal(m)
            pos = pos.play(m)
        assert pos.terminal and b.terminal and pos.cells == b.cells
        assert _scorable(pos)
        assert b.score() == pytest.approx(pos.area_score())
    # the same seed gives the same playout
    assert Board(9).playout(pol, seed=5) == Board(9).playout(pol, seed=5)


def test_playout_rates_reflect_weights():
    """A strongly negative weight on the first line keeps playouts off it (sanity of the softmax)."""
    w = np.zeros(N_FEATURES)
    w[feature_index()["line:1"]] = -8.0
    pol = Policy(Weights(w))
    b = Board(9)
    first = b.copy().playout(pol, seed=1)[:20]
    on_edge = sum(1 for m in first if m is not None and (m // 9 in (0, 8) or m % 9 in (0, 8)))
    assert on_edge <= 2
