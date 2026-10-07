"""MCTS v2 C board: rules agree with gotree.position on random games; Zobrist keys and the build."""
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from gotree.position import IllegalMove, Position, point
from mcts.board import Board, board_from_moves, board_from_sgf

ROOT = Path(__file__).resolve().parent.parent


def _random_game(seed, size, plies=None):
    """Yield (gotree position, mcts board) pairs along one random game played on both."""
    rng = random.Random(seed)
    pos, b = Position.empty(size), Board(size)
    for _ in range(plies or 3 * size * size):
        yield pos, b
        lm = pos.legal_moves()
        cand = [p for p in lm if not pos.is_own_eye(p)]
        m = rng.choice(cand) if cand and rng.random() > 0.03 else None
        pos = pos.play(m)
        b.play(m)
        if pos.terminal:
            break
    yield pos, b


@pytest.mark.parametrize("size,seed", [(5, 1), (7, 2), (9, 3), (9, 4), (9, 5), (13, 6), (19, 7)])
def test_rules_agree_with_gotree_on_random_games(size, seed):
    rng = random.Random(seed + 100)
    for pos, b in _random_game(seed, size):
        assert b.cells == pos.cells and b.to_play == pos.to_play and b.ko == pos.ko and b.passes == pos.passes
        assert sorted(b.legal_moves()) == sorted(pos.legal_moves())
        for p in rng.sample(range(size * size), min(10, size * size)):
            assert b.is_eye(p) == pos.is_own_eye(p)
            assert b.is_legal(p) == pos.is_legal(p)
            if not pos.is_legal(p) and not pos.terminal:      # same rejection reason
                with pytest.raises(IllegalMove) as e1:
                    pos.play(p)
                with pytest.raises(IllegalMove) as e2:
                    b.copy().play(p)
                assert e1.value.code == e2.value.code
    assert b.score() == pytest.approx(pos.area_score())         # the final area score (Tromp-Taylor)


def test_area_score_matches_on_many_finished_games():
    for seed in range(40):
        size = (5, 7, 9)[seed % 3]
        *_, (pos, b) = _random_game(1000 + seed, size)
        assert b.score() == pytest.approx(pos.area_score())


def test_ko_suicide_and_captures():
    b = Board(9)
    for m in "D4 E4 C5 F5 D6 E6 J1 D5 E5".split():   # black E5 takes the ko stone at D5
        b.play(m)
    assert b.ko == point("D5", 9) and b.cells[point("D5", 9)] == "."
    with pytest.raises(IllegalMove) as e:
        b.copy().play("D5")
    assert e.value.code == "ko"
    q = Board(9).play("A2").play("J9").play("B1")
    with pytest.raises(IllegalMove) as e:
        q.play("A1")
    assert e.value.code == "suicide"
    with pytest.raises(IllegalMove) as e:
        Board(9).play("A1").play("A1")
    assert e.value.code == "occupied"
    g = Board(9).play("pass").play("pass")
    assert g.terminal
    with pytest.raises(IllegalMove):
        g.play("E5")


def test_zobrist_keys_and_transpositions():
    a, _ = board_from_moves(9, [point(c, 9) for c in "C3 G7 C7 G3".split()])
    b, _ = board_from_moves(9, [point(c, 9) for c in "C7 G3 C3 G7".split()])
    assert a.key == b.key and a.stone_hash == b.stone_hash          # transposition: same node key
    c = a.copy()
    c.play(None)                                                     # same stones, other side, one pass
    assert c.stone_hash == a.stone_hash and c.key != a.key
    d = c.copy()
    d.play(None)
    assert d.key not in (a.key, c.key)                               # passes are part of the key
    # incremental hashes (with captures) equal hashes recomputed from the cells
    for pos, bd in _random_game(11, 9):
        r = Board.from_position(pos)
        assert r.stone_hash == bd.stone_hash
        assert r.key == bd.key
    # the ko point is part of the key
    k1 = Board(9)
    for m in "D4 E4 C5 F5 D6 E6 J1 D5 E5".split():
        k1.play(m)
    d = k1.to_dict()
    d["ko"] = None
    assert Board.from_dict(d).key != k1.key and Board.from_dict(d).stone_hash == k1.stone_hash


def test_position_round_trip_and_sgf():
    *_, (pos, b) = _random_game(21, 9, plies=40)
    assert Board.from_position(pos).to_position() == pos
    assert Board.from_dict(b.to_dict()) == b
    sgf = (ROOT / "data/alphago-leesedol-2016-g2.sgf").read_text()
    bd, hist, moves = board_from_sgf(sgf, 36)
    gp = Position.from_sgf(sgf, 36)
    assert bd.cells == gp.cells and bd.to_play == gp.to_play and len(hist) == len(moves) == 36
    assert bd.last == gp.last and bd.last2 == moves[-2]


def test_library_builds_from_tracked_sources(tmp_path):
    """One command rebuilds the core from csrc/ into an empty build dir (as on a fresh checkout)."""
    env = dict(os.environ, MCTS_BUILD_DIR=str(tmp_path / "build"))
    r = subprocess.run([sys.executable, "-m", "mcts", "build"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    so = Path(r.stdout.strip().splitlines()[-1])
    assert so.parent == tmp_path / "build" and so.exists() and so.name.startswith("libmcts-")
