"""A fast Go board backed by the C core (rules identical to gotree.position.Position).

Moves are gotree point indices ``p = y * size + x`` (row 0 at the top), ``None`` for pass, or
coordinates such as ``"D4"`` / ``"pass"``.  ``Board`` is mutable (``play`` changes it in place);
``played`` returns a new board.  Positional superko is not a board rule: the tree enforces it
over the game history (simple ko is part of the board, as in gotree).
"""
from __future__ import annotations

import ctypes
from typing import Iterable, Optional, Union

import numpy as np

from gotree.position import BLACK, EMPTY, WHITE, IllegalMove, Position, coord, point

from ._lib import BOARD_BYTES, plib

Move = Union[int, str, None]
_CODES = {1: "occupied", 2: "ko", 3: "suicide", 4: "bad_coordinate", 5: "game_over"}
_COLOR = {BLACK: 1, WHITE: 2}
_CHAR = np.array([ord(EMPTY), ord(BLACK), ord(WHITE)], dtype=np.uint8)


def to_point(move: Move, size: int) -> Optional[int]:
    """gotree point (or None for pass) of an int / None / coordinate string."""
    if move is None:
        return None
    if isinstance(move, str):
        return point(move, size)
    p = int(move)
    if p == -1:
        return None
    if not 0 <= p < size * size:
        raise IllegalMove("bad_coordinate", f"point {p} is off a {size}x{size} board")
    return p


class Board:
    __slots__ = ("_b",)

    def __init__(self, size: int = 9, komi: float = 7.5):
        if not 2 <= size <= 19:
            raise ValueError("board size must be 2..19")
        self._b = ctypes.create_string_buffer(BOARD_BYTES)
        plib.mcb_clear(self._b, size, komi)

    # ------------------------------------------------------------ construction
    @classmethod
    def from_position(cls, pos: Position, last2: Optional[int] = None) -> "Board":
        b = cls.__new__(cls)
        b._b = ctypes.create_string_buffer(BOARD_BYTES)
        cells = np.frombuffer(pos.cells.encode(), dtype=np.uint8)
        arr = np.zeros(len(cells), dtype=np.int8)
        arr[cells == ord(BLACK)] = 1
        arr[cells == ord(WHITE)] = 2
        rc = plib.mcb_load(b._b, pos.size, pos.komi, arr.ctypes.data, _COLOR[pos.to_play],
                           -1 if pos.ko is None else pos.ko, pos.passes,
                           -1 if pos.last is None else pos.last, -1 if last2 is None else last2)
        if rc != 0:
            raise ValueError("bad position")
        return b

    @classmethod
    def from_dict(cls, d: dict) -> "Board":
        b = cls.from_position(Position(d["size"], d["cells"], d["to_play"], d.get("ko"), d.get("passes", 0),
                                       d.get("komi", 7.5), d.get("last")), d.get("last2"))
        return b

    def to_dict(self) -> dict:
        size, tp, ko, passes, last, last2 = self._info()
        return {"size": size, "cells": self.cells, "to_play": BLACK if tp == 1 else WHITE,
                "ko": None if ko < 0 else ko, "passes": passes, "komi": self.komi,
                "last": None if last < 0 else last, "last2": None if last2 < 0 else last2}

    def to_position(self) -> Position:
        d = self.to_dict()
        return Position(d["size"], d["cells"], d["to_play"], d["ko"], d["passes"], d["komi"], d["last"])

    def copy(self) -> "Board":
        b = Board.__new__(Board)
        b._b = ctypes.create_string_buffer(self._b.raw, BOARD_BYTES)
        return b

    # ------------------------------------------------------------ state
    def _info(self) -> tuple:
        out = (ctypes.c_int32 * 6)()
        plib.mcb_info(self._b, out)
        return tuple(out)

    @property
    def size(self) -> int:
        return self._info()[0]

    @property
    def komi(self) -> float:
        return float(plib.mcb_komi(self._b))

    @property
    def to_play(self) -> str:
        return BLACK if self._info()[1] == 1 else WHITE

    @property
    def ko(self) -> Optional[int]:
        k = self._info()[2]
        return None if k < 0 else k

    @property
    def passes(self) -> int:
        return self._info()[3]

    @property
    def last(self) -> Optional[int]:
        v = self._info()[4]
        return None if v < 0 else v

    @property
    def last2(self) -> Optional[int]:
        v = self._info()[5]
        return None if v < 0 else v

    @property
    def terminal(self) -> bool:
        return self.passes >= 2

    @property
    def key(self) -> int:
        """Zobrist key of the node: stones, side to move, ko point and passes (0/1/2)."""
        return int(plib.mcb_key(self._b))

    @property
    def stone_hash(self) -> int:
        """Zobrist hash of the stones only (positional superko)."""
        return int(plib.mcb_hash(self._b))

    def cells_array(self) -> np.ndarray:
        s = self.size
        out = np.empty(s * s, dtype=np.int8)
        plib.mcb_cells(self._b, out.ctypes.data)
        return out

    @property
    def cells(self) -> str:
        return _CHAR[self.cells_array()].tobytes().decode()

    def __eq__(self, other) -> bool:
        return isinstance(other, Board) and self.key == other.key and self.cells == other.cells

    def __hash__(self) -> int:
        return self.key

    def __repr__(self) -> str:
        return f"Board(size={self.size}, to_play={self.to_play}, key={self.key:016x})"

    # ------------------------------------------------------------ rules
    def play(self, move: Move) -> "Board":
        p = to_point(move, self.size)
        rc = plib.mcb_play(self._b, -1 if p is None else p)
        if rc:
            raise IllegalMove(_CODES.get(rc, "illegal"), f"{coord(p, self.size)} is illegal ({_CODES.get(rc)})")
        return self

    def played(self, move: Move) -> "Board":
        return self.copy().play(move)

    def is_legal(self, move: Move) -> bool:
        try:
            p = to_point(move, self.size)
        except IllegalMove:
            return False
        return bool(plib.mcb_legal(self._b, -1 if p is None else p))

    def legal_moves(self) -> list[int]:
        out = (ctypes.c_int16 * (self.size * self.size))()
        n = plib.mcb_legal_moves(self._b, out)
        return list(out[:n])

    def score(self) -> float:
        """Tromp-Taylor area score, black minus white minus komi (every stone counts as alive)."""
        return float(plib.mcb_score(self._b))

    def is_eye(self, p: int, color: Optional[str] = None) -> bool:
        return bool(plib.mcb_is_eye(self._b, p, _COLOR[color or self.to_play]))

    def playout(self, policy, seed: int = 0, max_moves: int = 0) -> list[Optional[int]]:
        """Play the game out in place with the weighted playout policy; returns the moves."""
        cap = max_moves or 3 * self.size * self.size
        out = (ctypes.c_int16 * cap)()
        n = plib.mcb_playout(self._b, policy.ptr, seed, cap, out)
        return [None if m < 0 else m for m in out[:n]]

    def coord(self, move: Optional[int]) -> str:
        return coord(move, self.size)


def board_from_moves(size: int, moves: Iterable[Move], komi: float = 7.5) -> tuple[Board, list[int]]:
    """Board after `moves` from the empty board, and the stone hashes of every earlier position."""
    b = Board(size, komi)
    hist: list[int] = []
    for m in moves:
        hist.append(b.stone_hash)
        b.play(m)
    return b, hist


def board_from_sgf(text: str, upto: Optional[int] = None) -> tuple[Board, list[int], list[Optional[int]]]:
    """(board after the first `upto` main-line moves, stone hashes of the earlier positions, moves)."""
    from goarena.sgf import read_sgf, sgf_to_point
    g = read_sgf(text)
    size, komi = g["size"], g["komi"]
    cells = [EMPTY] * (size * size)
    for prop, col in (("AB", BLACK), ("AW", WHITE)):
        vals = g["props"].get(prop)
        for v in ([vals] if isinstance(vals, str) else (vals or [])):
            q = sgf_to_point(v, size)
            if q is not None:
                cells[q] = col
    first = g["moves"][0][0] if g["moves"] else None
    pl = g["props"].get("PL")
    to_play = WHITE if (pl == "W" or (pl is None and first == 2)) else BLACK
    b = Board.from_position(Position(size, "".join(cells), to_play, None, 0, komi))
    mv = [(BLACK if c == 1 else WHITE, p) for c, p in g["moves"]]
    if upto is not None:
        mv = mv[:upto]
    hist: list[int] = []
    played: list[Optional[int]] = []
    for color, p in mv:
        if color != b.to_play:   # tolerate consecutive moves of one colour (handicap)
            d = b.to_dict()
            d["to_play"], d["ko"] = color, None
            b = Board.from_dict(d)
        hist.append(b.stone_hash)
        b.play(p)
        played.append(p)
    return b, hist, played
