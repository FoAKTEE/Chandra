"""Go rules engine.

Rules implemented (the "arena rules"):
  * Board sizes 5..19 (square).
  * Captures, no suicide (single- or multi-stone suicide is illegal).
  * Positional superko: a move may not recreate any earlier whole-board
    position (regardless of side to move).
  * Area scoring (Chinese rules): stones + empty points surrounded only by
    one colour.  Komi is added to White.
  * The game ends after two consecutive passes, a resignation, a forfeit, or
    when the move cap is hit.

Coordinates use GTP notation: column letters A..T skipping I, row numbers
counted from the bottom (A1 is the lower-left corner).  "pass" is a pass.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable, Optional

EMPTY, BLACK, WHITE = 0, 1, 2
COLUMNS = "ABCDEFGHJKLMNOPQRST"  # no I


def other(color: int) -> int:
    return BLACK if color == WHITE else WHITE


def color_name(color: int) -> str:
    return {BLACK: "black", WHITE: "white"}.get(color, "empty")


def color_letter(color: int) -> str:
    return {BLACK: "B", WHITE: "W"}[color]


def parse_color(s: str) -> int:
    s = s.strip().lower()
    if s in ("b", "black"):
        return BLACK
    if s in ("w", "white"):
        return WHITE
    raise ValueError(f"unknown colour: {s!r}")


class IllegalMove(Exception):
    """Raised for illegal moves. `code` is a short machine-readable reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------

def coord_to_point(coord: str, size: int) -> Optional[int]:
    """'D4' -> point index; 'pass' -> None.  Raises IllegalMove on bad input."""
    c = coord.strip().upper()
    if c == "PASS":
        return None
    if len(c) < 2 or c[0] not in COLUMNS[:size] or not (c[1:].isascii() and c[1:].isdigit()):
        raise IllegalMove("bad_coordinate",
                          f"'{coord}' is not a coordinate on a {size}x{size} board "
                          f"(columns {COLUMNS[0]}-{COLUMNS[size-1]}, skipping I; rows 1-{size}; or 'pass')")
    x = COLUMNS.index(c[0])
    row = int(c[1:])
    if not 1 <= row <= size:
        raise IllegalMove("bad_coordinate", f"row {row} is off the {size}x{size} board")
    y = size - row  # y=0 is the top row
    return y * size + x


def point_to_coord(p: Optional[int], size: int) -> str:
    if p is None:
        return "pass"
    y, x = divmod(p, size)
    return f"{COLUMNS[x]}{size - y}"


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------

_ZOBRIST_CACHE: dict[int, list[tuple[int, int]]] = {}


def _zobrist(size: int) -> list[tuple[int, int]]:
    if size not in _ZOBRIST_CACHE:
        rng = random.Random(12345 + size)
        _ZOBRIST_CACHE[size] = [(rng.getrandbits(64), rng.getrandbits(64)) for _ in range(size * size)]
    return _ZOBRIST_CACHE[size]


@dataclass
class Move:
    color: int
    point: Optional[int]  # None = pass
    captured: list[int] = field(default_factory=list)


class Board:
    def __init__(self, size: int = 9, komi: float = 7.5):
        if not 5 <= size <= 19:
            raise ValueError("board size must be between 5 and 19")
        self.size = size
        self.komi = komi
        self.cells = [EMPTY] * (size * size)
        self.to_play = BLACK
        self.moves: list[Move] = []
        self.captures = {BLACK: 0, WHITE: 0}  # stones captured BY colour
        self._z = _zobrist(size)
        self.hash = 0
        self.history_hashes: set[int] = {0}
        self.neighbors = [self._nbrs(p) for p in range(size * size)]

    # -- basic geometry --------------------------------------------------
    def _nbrs(self, p: int) -> list[int]:
        s = self.size
        y, x = divmod(p, s)
        out = []
        if y > 0:
            out.append(p - s)
        if y < s - 1:
            out.append(p + s)
        if x > 0:
            out.append(p - 1)
        if x < s - 1:
            out.append(p + 1)
        return out

    def diagonals(self, p: int) -> list[int]:
        s = self.size
        y, x = divmod(p, s)
        out = []
        for dy, dx in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < s and 0 <= xx < s:
                out.append(yy * s + xx)
        return out

    def copy(self) -> "Board":
        b = Board.__new__(Board)
        b.size, b.komi = self.size, self.komi
        b.cells = self.cells[:]
        b.to_play = self.to_play
        b.moves = [Move(m.color, m.point, m.captured[:]) for m in self.moves]
        b.captures = dict(self.captures)
        b._z = self._z
        b.hash = self.hash
        b.history_hashes = set(self.history_hashes)
        b.neighbors = self.neighbors
        return b

    # -- groups ----------------------------------------------------------
    def group(self, p: int, cells: Optional[list[int]] = None) -> tuple[set[int], set[int]]:
        """Return (stones, liberties) of the group containing p."""
        cells = self.cells if cells is None else cells
        color = cells[p]
        stones, libs, stack = {p}, set(), [p]
        while stack:
            q = stack.pop()
            for n in self.neighbors[q]:
                c = cells[n]
                if c == EMPTY:
                    libs.add(n)
                elif c == color and n not in stones:
                    stones.add(n)
                    stack.append(n)
        return stones, libs

    def _hash_toggle(self, p: int, color: int) -> None:
        self.hash ^= self._z[p][color - 1]

    # -- legality --------------------------------------------------------
    def _simulate(self, point: int, color: int) -> tuple[list[int], int]:
        """Check a stone placement. Returns (captured points, resulting hash).
        Raises IllegalMove."""
        if self.cells[point] != EMPTY:
            raise IllegalMove("occupied", f"{point_to_coord(point, self.size)} is already occupied")
        opp = other(color)
        cells = self.cells[:]  # never mutate the live board: other threads may be reading it
        cells[point] = color
        captured: list[int] = []
        seen: set[int] = set()
        for n in self.neighbors[point]:
            if cells[n] == opp and n not in seen:
                stones, libs = self.group(n, cells)
                seen |= stones
                if not libs:
                    captured.extend(stones)
        if not captured:
            _, libs = self.group(point, cells)
            if not libs:
                raise IllegalMove("suicide", f"{point_to_coord(point, self.size)} would be suicide (no liberties)")
        h = self.hash ^ self._z[point][color - 1]
        for c in captured:
            h ^= self._z[c][opp - 1]
        if h in self.history_hashes:
            raise IllegalMove("superko",
                              f"{point_to_coord(point, self.size)} repeats an earlier board position "
                              f"(ko / positional superko)")
        return captured, h

    def is_legal(self, point: Optional[int], color: Optional[int] = None) -> bool:
        if point is None:
            return True
        color = color or self.to_play
        try:
            self._simulate(point, color)
            return True
        except IllegalMove:
            return False

    def legal_moves(self, color: Optional[int] = None) -> list[int]:
        color = color or self.to_play
        return [p for p in range(self.size * self.size)
                if self.cells[p] == EMPTY and self.is_legal(p, color)]

    # -- playing ---------------------------------------------------------
    def play(self, point: Optional[int], color: Optional[int] = None) -> Move:
        color = color or self.to_play
        if color != self.to_play:
            raise IllegalMove("wrong_turn", f"it is {color_name(self.to_play)}'s turn")
        if point is None:
            mv = Move(color, None)
        else:
            captured, h = self._simulate(point, color)
            self.cells[point] = color
            for c in captured:
                self.cells[c] = EMPTY
            self.hash = h
            self.history_hashes.add(h)
            self.captures[color] += len(captured)
            mv = Move(color, point, captured)
        self.moves.append(mv)
        self.to_play = other(color)
        return mv

    def play_coord(self, coord: str, color: Optional[int] = None) -> Move:
        return self.play(coord_to_point(coord, self.size), color)

    def consecutive_passes(self) -> int:
        n = 0
        for m in reversed(self.moves):
            if m.point is not None:
                break
            n += 1
        return n

    @property
    def last_move(self) -> Optional[Move]:
        return self.moves[-1] if self.moves else None

    # -- eyes (used by simple bots) ----------------------------------------
    def is_eye_like(self, p: int, color: int) -> bool:
        """True if p is a single-point eye for `color` (not to be filled)."""
        if self.cells[p] != EMPTY:
            return False
        if any(self.cells[n] != color for n in self.neighbors[p]):
            return False
        diag = self.diagonals(p)
        bad = sum(1 for d in diag if self.cells[d] == other(color))
        if len(diag) < 4:
            return bad == 0
        return bad <= 1

    # -- scoring ---------------------------------------------------------
    def area_score(self, dead: Iterable[int] = ()) -> dict:
        """Chinese area score after removing `dead` stones.
        Returns dict with black/white area, komi, margin (positive = Black ahead)."""
        cells = self.cells[:]
        dead = set(dead)
        for p in dead:
            cells[p] = EMPTY
        n = self.size * self.size
        black = sum(1 for c in cells if c == BLACK)
        white = sum(1 for c in cells if c == WHITE)
        territory = {BLACK: set(), WHITE: set()}
        seen = [False] * n
        for p in range(n):
            if cells[p] != EMPTY or seen[p]:
                continue
            region, border, stack = [], set(), [p]
            seen[p] = True
            while stack:
                q = stack.pop()
                region.append(q)
                for nb in self.neighbors[q]:
                    if cells[nb] == EMPTY:
                        if not seen[nb]:
                            seen[nb] = True
                            stack.append(nb)
                    else:
                        border.add(cells[nb])
            if border == {BLACK}:
                territory[BLACK].update(region)
            elif border == {WHITE}:
                territory[WHITE].update(region)
        b_area = black + len(territory[BLACK])
        w_area = white + len(territory[WHITE])
        margin = b_area - (w_area + self.komi)
        return {
            "black_area": b_area,
            "white_area": w_area,
            "komi": self.komi,
            "margin": margin,
            "winner": BLACK if margin > 0 else WHITE if margin < 0 else EMPTY,
            "dead": sorted(dead),
            "territory": {"black": sorted(territory[BLACK]), "white": sorted(territory[WHITE])},
        }

    # -- rendering -------------------------------------------------------
    def render(self, show_last: bool = True) -> str:
        """ASCII board (GNU Go style).  X = black, O = white, . = empty,
        + = star point.  The last move is wrapped in parentheses: (X)."""
        s = self.size
        last = self.last_move.point if (show_last and self.last_move) else None
        stars = _star_points(s)
        header = "   " + " ".join(COLUMNS[x] for x in range(s))
        lines = [header]
        for y in range(s):
            row = s - y
            seps = [" "] * (s + 1)  # separator before each cell + trailing
            chars = []
            for x in range(s):
                p = y * s + x
                c = self.cells[p]
                chars.append("X" if c == BLACK else "O" if c == WHITE else ("+" if p in stars else "."))
                if p == last:
                    seps[x], seps[x + 1] = "(", ")"
            body = "".join(seps[x] + chars[x] for x in range(s)) + seps[s]
            lines.append(f"{row:>2}{body}{row}")
        lines.append(header)
        return "\n".join(lines)

    def to_rows(self) -> list[str]:
        """Compact machine-friendly rows, top row first: 'X', 'O', '.'"""
        s = self.size
        return ["".join("X" if c == BLACK else "O" if c == WHITE else "." for c in self.cells[y * s:(y + 1) * s])
                for y in range(s)]


def _star_points(size: int) -> set[int]:
    if size < 7:
        return set()
    edge = 2 if size < 13 else 3
    pts = [edge, size - 1 - edge]
    if size % 2 == 1:
        pts.append(size // 2)
    res = set()
    for y in pts:
        for x in pts:
            if size < 13 and (y == size // 2) != (x == size // 2):
                continue
            res.add(y * size + x)
    return res
