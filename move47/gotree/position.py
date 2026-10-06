"""Frozen positions ("残局") — the unit of memory.

A Position is everything that matters for the rest of the game under area
scoring: the stones, the side to move, the simple-ko point and whether the
previous move was a pass.  Move order and capture counts are deliberately
NOT part of it, so the same position reached by different move orders is
one node (a transposition) and the DAG can merge them.

Every position has a canonical form under the 8 symmetries of the square
board; the canonical form (and its 16-hex key) is what the DAG stores.
Moves stored in the DAG are in the canonical frame of their parent.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Optional

COLUMNS = "ABCDEFGHJKLMNOPQRST"
EMPTY, BLACK, WHITE = ".", "X", "O"


class IllegalMove(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# ------------------------------------------------------------------ geometry
_NEIGHBORS: dict[int, list[list[int]]] = {}
_SYMS: dict[int, list[list[int]]] = {}      # size -> [fwd map per symmetry]
_INV: dict[int, list[list[int]]] = {}


def neighbors(size: int) -> list[list[int]]:
    if size not in _NEIGHBORS:
        nb = []
        for p in range(size * size):
            y, x = divmod(p, size)
            l = []
            if y > 0: l.append(p - size)
            if y < size - 1: l.append(p + size)
            if x > 0: l.append(p - 1)
            if x < size - 1: l.append(p + 1)
            nb.append(l)
        _NEIGHBORS[size] = nb
    return _NEIGHBORS[size]


def _sym_xy(x: int, y: int, s: int, n: int) -> tuple[int, int]:
    if s & 4:
        x, y = y, x
    if s & 1:
        x = n - 1 - x
    if s & 2:
        y = n - 1 - y
    return x, y


def sym_maps(size: int) -> tuple[list[list[int]], list[list[int]]]:
    """fwd[s][p] = image of point p under symmetry s; inv[s] its inverse."""
    if size not in _SYMS:
        fwd, inv = [], []
        for s in range(8):
            f = [0] * (size * size)
            for p in range(size * size):
                y, x = divmod(p, size)
                xx, yy = _sym_xy(x, y, s, size)
                f[p] = yy * size + xx
            i = [0] * (size * size)
            for p, q in enumerate(f):
                i[q] = p
            fwd.append(f)
            inv.append(i)
        _SYMS[size], _INV[size] = fwd, inv
    return _SYMS[size], _INV[size]


def coord(p: Optional[int], size: int) -> str:
    if p is None:
        return "pass"
    y, x = divmod(p, size)
    return f"{COLUMNS[x]}{size - y}"


def point(c: str, size: int) -> Optional[int]:
    c = c.strip().upper()
    if c in ("PASS", ""):
        return None
    if len(c) < 2 or c[0] not in COLUMNS[:size] or not (c[1:].isascii() and c[1:].isdigit()):
        raise IllegalMove("bad_coordinate", f"'{c}' is not a point on a {size}x{size} board (columns skip I)")
    row = int(c[1:])
    if not 1 <= row <= size:
        raise IllegalMove("bad_coordinate", f"row {row} is off the board")
    return (size - row) * size + COLUMNS.index(c[0])


def other(c: str) -> str:
    return WHITE if c == BLACK else BLACK


# ------------------------------------------------------------------ position
@dataclass(frozen=True)
class Position:
    size: int
    cells: str                 # size*size chars of . X O, row-major from the top-left
    to_play: str = BLACK       # X or O
    ko: Optional[int] = None   # point the side to move may not play (simple ko)
    passes: int = 0            # consecutive passes so far (2 = game over)
    komi: float = 7.5
    last: Optional[int] = field(default=None, compare=False)  # display only, not identity

    # -- construction ------------------------------------------------------
    @classmethod
    def empty(cls, size: int = 19, komi: float = 7.5) -> "Position":
        return cls(size, EMPTY * size * size, BLACK, None, 0, komi)

    @classmethod
    def from_moves(cls, size: int, moves: Iterable[tuple[str, Optional[int]]], komi: float = 7.5) -> "Position":
        pos = cls.empty(size, komi)
        for color, p in moves:
            if color != pos.to_play:  # tolerate handicap-style consecutive moves
                pos = Position(pos.size, pos.cells, color, None, pos.passes, pos.komi, pos.last)
            pos = pos.play(p)
        return pos

    @classmethod
    def from_sgf(cls, text: str, upto: Optional[int] = None) -> "Position":
        """Position after the first `upto` moves of an SGF main line (all moves if None)."""
        from goarena.sgf import read_sgf, sgf_to_point
        g = read_sgf(text)
        size, komi = g["size"], g["komi"]
        cells = [EMPTY] * (size * size)
        for prop, col in (("AB", BLACK), ("AW", WHITE)):   # setup / handicap stones
            vals = g["props"].get(prop)
            for v in ([vals] if isinstance(vals, str) else (vals or [])):
                q = sgf_to_point(v, size)
                if q is not None:
                    cells[q] = col
        first = g["moves"][0][0] if g["moves"] else None
        pl = g["props"].get("PL")
        to_play = WHITE if (pl == "W" or (pl is None and first == 2)) else BLACK
        pos = cls(size, "".join(cells), to_play, None, 0, komi)
        mv = [("X" if c == 1 else "O", p) for c, p in g["moves"]]
        if upto is not None:
            mv = mv[:upto]
        for color, p in mv:
            if color != pos.to_play:
                pos = Position(pos.size, pos.cells, color, None, pos.passes, pos.komi, pos.last)
            pos = pos.play(p)
        return pos

    # -- rules -------------------------------------------------------------
    @property
    def terminal(self) -> bool:
        return self.passes >= 2

    def _chain(self, cells: list[str], p: int) -> tuple[set[int], set[int]]:
        nb = neighbors(self.size)
        col = cells[p]
        stones, libs, stack = {p}, set(), [p]
        while stack:
            q = stack.pop()
            for n in nb[q]:
                c = cells[n]
                if c == EMPTY:
                    libs.add(n)
                elif c == col and n not in stones:
                    stones.add(n)
                    stack.append(n)
        return stones, libs

    def chain(self, p: int) -> tuple[set[int], set[int]]:
        return self._chain(list(self.cells), p)

    def play(self, p: Optional[int]) -> "Position":
        """Return the position after the side to move plays p (None = pass)."""
        if self.terminal:
            raise IllegalMove("game_over", "the game is over (two passes)")
        me, opp = self.to_play, other(self.to_play)
        if p is None:
            return Position(self.size, self.cells, opp, None, self.passes + 1, self.komi, None)
        if not 0 <= p < self.size * self.size:
            raise IllegalMove("bad_coordinate", f"point {p} is off the board")
        if self.cells[p] != EMPTY:
            raise IllegalMove("occupied", f"{coord(p, self.size)} is occupied")
        if p == self.ko:
            raise IllegalMove("ko", f"{coord(p, self.size)} retakes a ko immediately")
        cells = list(self.cells)
        cells[p] = me
        captured: list[int] = []
        seen: set[int] = set()
        for n in neighbors(self.size)[p]:
            if cells[n] == opp and n not in seen:
                st, lib = self._chain(cells, n)
                seen |= st
                if not lib:
                    captured.extend(st)
        for c in captured:
            cells[c] = EMPTY
        st, lib = self._chain(cells, p)
        if not lib:
            raise IllegalMove("suicide", f"{coord(p, self.size)} is suicide")
        ko = None
        if len(captured) == 1 and len(st) == 1 and len(lib) == 1:
            ko = captured[0]
        return Position(self.size, "".join(cells), opp, ko, 0, self.komi, p)

    def is_legal(self, p: Optional[int]) -> bool:
        try:
            self.play(p)
            return True
        except IllegalMove:
            return False

    def legal_moves(self) -> list[int]:
        return [p for p in range(self.size * self.size) if self.cells[p] == EMPTY and self.is_legal(p)]

    def is_own_eye(self, p: int, color: Optional[str] = None) -> bool:
        color = color or self.to_play
        if self.cells[p] != EMPTY:
            return False
        nb = neighbors(self.size)[p]
        if any(self.cells[n] != color for n in nb):
            return False
        y, x = divmod(p, self.size)
        diag = [(y + dy) * self.size + (x + dx) for dy in (-1, 1) for dx in (-1, 1)
                if 0 <= y + dy < self.size and 0 <= x + dx < self.size]
        bad = sum(1 for d in diag if self.cells[d] == other(color))
        return bad == 0 if len(diag) < 4 else bad <= 1

    def area_score(self) -> float:
        """Tromp-Taylor area score, Black minus White minus komi (all stones alive)."""
        n = self.size * self.size
        nb = neighbors(self.size)
        b = self.cells.count(BLACK)
        w = self.cells.count(WHITE)
        seen = [False] * n
        for p in range(n):
            if self.cells[p] != EMPTY or seen[p]:
                continue
            region, border, stack = 0, set(), [p]
            seen[p] = True
            while stack:
                q = stack.pop()
                region += 1
                for m in nb[q]:
                    c = self.cells[m]
                    if c == EMPTY:
                        if not seen[m]:
                            seen[m] = True
                            stack.append(m)
                    else:
                        border.add(c)
            if border == {BLACK}:
                b += region
            elif border == {WHITE}:
                w += region
        return b - w - self.komi

    def terminal_value(self) -> float:
        """For a finished game: 1.0 if the side to move has won, else 0.0."""
        s = self.area_score()
        if s == 0:
            return 0.5
        return 1.0 if ((s > 0) == (self.to_play == BLACK)) else 0.0

    # -- symmetry & identity ---------------------------------------------------
    def transformed(self, s: int) -> "Position":
        fwd, _ = sym_maps(self.size)
        f = fwd[s]
        cells = [EMPTY] * (self.size * self.size)
        for p, c in enumerate(self.cells):
            cells[f[p]] = c
        return Position(self.size, "".join(cells), self.to_play,
                        None if self.ko is None else f[self.ko], self.passes, self.komi,
                        None if self.last is None else f[self.last])

    def canonical(self) -> tuple["Position", int]:
        """(canonical position, s) with canonical = self.transformed(s)."""
        best, best_s, best_sig = None, 0, None
        for s in range(8):
            t = self.transformed(s)
            sig = (t.cells, -1 if t.ko is None else t.ko)
            if best_sig is None or sig < best_sig:
                best, best_s, best_sig = t, s, sig
        return best, best_s  # type: ignore[return-value]

    @property
    def key(self) -> str:
        c, _ = self.canonical()
        return c.raw_key

    @property
    def raw_key(self) -> str:
        """Key of this exact orientation (callers normally canonicalize first)."""
        h = hashlib.blake2b(digest_size=8)
        h.update(f"{self.size}|{self.komi:g}|{self.to_play}|{self.ko}|{min(self.passes, 2)}|".encode())
        h.update(self.cells.encode())
        return h.hexdigest()

    def map_move(self, p: Optional[int], s: int) -> Optional[int]:
        return None if p is None else sym_maps(self.size)[0][s][p]

    def unmap_move(self, p: Optional[int], s: int) -> Optional[int]:
        return None if p is None else sym_maps(self.size)[1][s][p]

    # -- misc ----------------------------------------------------------------
    def stones(self) -> int:
        return self.size * self.size - self.cells.count(EMPTY)

    def phase(self) -> str:
        frac = self.stones() / (self.size * self.size)
        return "opening" if frac < 0.12 else "middlegame" if frac < 0.45 else "endgame"

    def to_dict(self) -> dict:
        return {"size": self.size, "cells": self.cells, "to_play": self.to_play, "ko": self.ko,
                "passes": self.passes, "komi": self.komi, "last": self.last}

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(d["size"], d["cells"], d["to_play"], d.get("ko"), d.get("passes", 0), d.get("komi", 7.5),
                   d.get("last"))

    def sgf_setup(self) -> str:
        """SGF of this position as a setup diagram (for humans / other tools)."""
        L = "abcdefghijklmnopqrs"
        ab = "".join(f"[{L[p % self.size]}{L[p // self.size]}]" for p, c in enumerate(self.cells) if c == BLACK)
        aw = "".join(f"[{L[p % self.size]}{L[p // self.size]}]" for p, c in enumerate(self.cells) if c == WHITE)
        return (f"(;GM[1]FF[4]SZ[{self.size}]KM[{self.komi:g}]RU[Chinese]"
                f"{'AB' + ab if ab else ''}{'AW' + aw if aw else ''}PL[{'B' if self.to_play == BLACK else 'W'}])")
