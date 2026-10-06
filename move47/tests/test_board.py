import pytest

from goarena.board import (BLACK, WHITE, Board, IllegalMove, coord_to_point,
                           point_to_coord)
from goarena.sgf import read_sgf, replay, write_sgf


def play_seq(b, seq):
    for c in seq:
        b.play_coord(c)


def test_coords_roundtrip():
    for size in (9, 13, 19):
        for p in range(size * size):
            assert coord_to_point(point_to_coord(p, size), size) == p
    assert coord_to_point("A1", 9) == 72
    assert coord_to_point("J9", 9) == 8
    assert coord_to_point("pass", 9) is None
    with pytest.raises(IllegalMove):
        coord_to_point("I5", 9)
    with pytest.raises(IllegalMove):
        coord_to_point("K5", 9)
    with pytest.raises(IllegalMove):
        coord_to_point("A10", 9)


def test_capture_single_stone():
    b = Board(9)
    # Black surrounds white E5
    play_seq(b, ["E4", "E5", "D5", "A1", "F5", "A2", "E6"])
    assert b.cells[coord_to_point("E5", 9)] == 0
    assert b.captures[BLACK] == 1


def test_suicide_illegal_white():
    b = Board(9)
    play_seq(b, ["A2", "J9", "B1"])
    with pytest.raises(IllegalMove) as e:
        b.play_coord("A1")  # white: no liberties and captures nothing
    assert e.value.code == "suicide"


def test_simple_ko_and_superko():
    b = Board(9)
    # Build a ko shape around D5/E5
    play_seq(b, ["D4", "E4", "C5", "F5", "D6", "E6", "J1", "D5", "E5"])
    # Black E5 captured white D5? check
    assert b.cells[coord_to_point("D5", 9)] == 0
    assert b.cells[coord_to_point("E5", 9)] == BLACK
    # white immediate recapture at D5 is ko -> illegal
    with pytest.raises(IllegalMove) as e:
        b.play_coord("D5")
    assert e.value.code == "superko"
    # ko threat elsewhere, then retake is legal
    play_seq(b, ["J9", "J8", "D5"])
    assert b.cells[coord_to_point("E5", 9)] == 0


def test_occupied():
    b = Board(9)
    b.play_coord("E5")
    with pytest.raises(IllegalMove) as e:
        b.play_coord("E5")
    assert e.value.code == "occupied"


def test_area_scoring_empty_board():
    b = Board(9, komi=7.5)
    s = b.area_score()
    assert s["margin"] == -7.5 and s["winner"] == WHITE


def test_area_scoring_split_board():
    b = Board(9, komi=7.5)
    # Black wall on column E, white wall on column F
    for r in range(1, 10):
        b.play_coord(f"E{r}")
        b.play_coord(f"F{r}")
    s = b.area_score()
    assert s["black_area"] == 45 and s["white_area"] == 36
    assert s["margin"] == 45 - 36 - 7.5


def test_dead_stone_removal():
    b = Board(9, komi=0.5)
    for r in range(1, 10):
        b.play_coord(f"E{r}")
        b.play_coord(f"F{r}")
    b.play_coord("J5")  # black stone dead inside white area
    dead = [coord_to_point("J5", 9)]
    s_alive = b.area_score()
    s_dead = b.area_score(dead)
    assert s_dead["white_area"] == 36 and s_dead["black_area"] == 45
    assert s_alive["white_area"] < 36  # J5 region now neutral-ish


def test_render_contains_last_move():
    b = Board(9)
    b.play_coord("E5")
    out = b.render()
    assert "(X)" in out
    assert out.splitlines()[0].strip().startswith("A B C D E F G H J")


def test_sgf_roundtrip():
    b = Board(9)
    play_seq(b, ["E5", "C3", "pass", "G7"])
    sgf = write_sgf(9, 7.5, [(m.color, m.point) for m in b.moves], black="agent", white="bot", result="W+R")
    g = read_sgf(sgf)
    assert g["size"] == 9 and g["komi"] == 7.5
    assert g["moves"] == [(m.color, m.point) for m in b.moves]
    b2 = replay(sgf)
    assert b2.cells == b.cells
