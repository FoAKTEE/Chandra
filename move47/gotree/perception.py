"""Perception layer: turn a Position into what an LLM can actually use.

LLMs are weak at counting liberties or aligning coordinates on a 19x19
ASCII grid, but good at reasoning over named facts.  So, like AlphaGo's
input feature planes (liberties, ladder capture/escape, atari, ...), we
compute rule-level facts with deterministic code and hand them over as
text.  Nothing here is a learned evaluator or a search engine: chains,
liberties, ladders, Benson's unconditional life and a crude influence map
are all classical, rules-level computations.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .position import BLACK, COLUMNS, EMPTY, WHITE, Position, coord, neighbors, other

NAME = {BLACK: "Black (X)", WHITE: "White (O)"}


# ------------------------------------------------------------------ chains
def chains(pos: Position) -> list[dict]:
    """All chains: [{id, color, stones, libs}] sorted by colour then first stone."""
    seen: set[int] = set()
    out = []
    cells = list(pos.cells)
    for p, c in enumerate(cells):
        if c == EMPTY or p in seen:
            continue
        st, lib = pos._chain(cells, p)
        seen |= st
        out.append({"color": c, "stones": sorted(st), "libs": sorted(lib)})
    nb, nw = 0, 0
    for ch in out:
        if ch["color"] == BLACK:
            nb += 1
            ch["id"] = f"b{nb}"
        else:
            nw += 1
            ch["id"] = f"w{nw}"
    return out


# ------------------------------------------------------------------ ladders
def ladder_captured(pos: Position, p: int, max_depth: int = 120) -> Optional[bool]:
    """Can the chain at p be captured in a ladder?  Considers the chain's
    owner to move if it is in atari, otherwise the attacker to move against
    a 2-liberty chain.  Returns None if not applicable (>2 liberties)."""
    defender = pos.cells[p]
    if defender == EMPTY:
        return None
    st, libs = pos.chain(p)
    if len(libs) > 2:
        return None
    attacker = other(defender)
    if len(libs) == 1:
        start = Position(pos.size, pos.cells, defender, None, 0, pos.komi)
        return _defend(start, p, attacker, max_depth)
    start = Position(pos.size, pos.cells, attacker, None, 0, pos.komi)
    return _attack(start, p, max_depth)


def _attack(pos: Position, p: int, depth: int) -> bool:
    if depth <= 0:
        return False
    _, libs = pos.chain(p)
    if len(libs) == 1:  # attacker simply captures
        return True
    if len(libs) != 2:
        return False
    for lib in libs:
        try:
            nxt = pos.play(lib)
        except Exception:
            continue
        if nxt.cells[p] == EMPTY:
            return True
        _, l2 = nxt.chain(p)
        # (if the atari stone is itself capturable, _defend finds that escape)
        if len(l2) == 1 and _defend(nxt, p, pos.to_play, depth - 1):
            return True
    return False


def _defend(pos: Position, p: int, attacker: str, depth: int) -> bool:
    """Defender (pos.to_play) to move, chain at p in atari.  True if it dies."""
    if depth <= 0:
        return False
    st, libs = pos.chain(p)
    nb = neighbors(pos.size)
    # escape 1: capture an adjacent attacking chain that is in atari
    for s in st:
        for n in nb[s]:
            if pos.cells[n] == attacker:
                _, al = pos.chain(n)
                if len(al) == 1:
                    return False
    # escape 2: extend at the liberty
    (lib,) = tuple(libs)
    try:
        nxt = pos.play(lib)
    except Exception:
        return True
    _, l2 = nxt.chain(p)
    if len(l2) >= 3:
        return False
    if len(l2) <= 1:
        return True
    return _attack(nxt, p, depth - 1)


# ------------------------------------------------------------------ Benson
def benson_alive(pos: Position, color: str) -> set[int]:
    """Stones of `color` that are unconditionally alive (Benson's algorithm)."""
    n = pos.size * pos.size
    nb = neighbors(pos.size)
    cells = pos.cells
    # chains of color
    cid = [-1] * n
    chs: list[tuple[set[int], set[int]]] = []
    for p in range(n):
        if cells[p] == color and cid[p] < 0:
            st, lib = pos.chain(p)
            for s in st:
                cid[s] = len(chs)
            chs.append((st, lib))
    # regions: connected components of points not of `color`
    rid = [-1] * n
    regions: list[set[int]] = []
    for p in range(n):
        if cells[p] != color and rid[p] < 0:
            reg, stack = {p}, [p]
            rid[p] = len(regions)
            while stack:
                q = stack.pop()
                for m in nb[q]:
                    if cells[m] != color and rid[m] < 0:
                        rid[m] = len(regions)
                        reg.add(m)
                        stack.append(m)
            regions.append(reg)
    region_chains = []
    for reg in regions:
        border = set()
        for q in reg:
            for m in nb[q]:
                if cid[m] >= 0:
                    border.add(cid[m])
        region_chains.append(border)

    def vital(ri: int, ci: int) -> bool:
        libs = chs[ci][1]
        return all(q in libs for q in regions[ri] if cells[q] == EMPTY)

    alive_c = set(range(len(chs)))
    healthy_r = set(range(len(regions)))
    changed = True
    while changed:
        changed = False
        for ci in list(alive_c):
            nv = sum(1 for ri in healthy_r if ci in region_chains[ri] and vital(ri, ci))
            if nv < 2:
                alive_c.discard(ci)
                changed = True
        for ri in list(healthy_r):
            if not region_chains[ri] <= alive_c:
                healthy_r.discard(ri)
                changed = True
    out: set[int] = set()
    for ci in alive_c:
        out |= chs[ci][0]
    return out


# ------------------------------------------------------------------ influence
def influence(pos: Position, radius: int = 4) -> list[float]:
    """Crude influence: + for Black, - for White, decaying with distance.
    Stones that Benson proves dead-free are not distinguished; this is a
    rough area sketch, not an evaluation."""
    n, s = pos.size * pos.size, pos.size
    inf = [0.0] * n
    stones = [(p, 1.0 if c == BLACK else -1.0) for p, c in enumerate(pos.cells) if c != EMPTY]
    for p in range(n):
        if pos.cells[p] != EMPTY:
            inf[p] = 9.0 if pos.cells[p] == BLACK else -9.0
            continue
        y, x = divmod(p, s)
        v = 0.0
        for q, sign in stones:
            qy, qx = divmod(q, s)
            d = abs(qy - y) + abs(qx - x)
            if d <= radius:
                v += sign / (1 + d * d)
        inf[p] = v
    return inf


def area_estimate(pos: Position, thresh: float = 0.35) -> dict:
    inf = influence(pos)
    b = sum(1 for v in inf if v > thresh)
    w = sum(1 for v in inf if v < -thresh)
    return {"black": b, "white": w, "lead_black": b - w - pos.komi, "map": inf, "thresh": thresh}


# ------------------------------------------------------------------ rendering
def board_diagram(pos: Position, marks: Optional[dict[int, str]] = None, area: Optional[list[float]] = None,
                  thresh: float = 0.35) -> str:
    """Board with coordinates on all four sides.  Last move in (parens).
    marks: point -> single letter shown on empty points.  area: influence
    map; empty points shown as x / o where one side dominates."""
    s = pos.size
    marks = marks or {}
    head = "    " + " ".join(COLUMNS[x] for x in range(s))
    lines = [head]
    for y in range(s):
        row = s - y
        seps = [" "] * (s + 1)
        ch = []
        for x in range(s):
            p = y * s + x
            c = pos.cells[p]
            if c != EMPTY:
                ch.append(c)
            elif p in marks:
                ch.append(marks[p])
            elif area is not None and area[p] > thresh:
                ch.append("x")
            elif area is not None and area[p] < -thresh:
                ch.append("o")
            elif p == pos.ko:
                ch.append("#")
            else:
                ch.append("+" if _star(p, s) else ".")
            if p == pos.last:
                seps[x], seps[x + 1] = "(", ")"
        lines.append(f"{row:>3}" + "".join(seps[x] + ch[x] for x in range(s)) + seps[s] + f"{row}")
    lines.append(head)
    return "\n".join(lines)


def _star(p: int, s: int) -> bool:
    if s < 9:
        return False
    e = 2 if s < 13 else 3
    pts = {e, s - 1 - e} | ({s // 2} if s % 2 else set())
    y, x = divmod(p, s)
    if s < 13 and (y == s // 2) != (x == s // 2):
        return False
    return y in pts and x in pts


def window(pos: Position, center: int, radius: int = 4) -> str:
    """Zoomed sub-board around a point (coordinates kept)."""
    s = pos.size
    cy, cx = divmod(center, s)
    y0, y1 = max(0, cy - radius), min(s - 1, cy + radius)
    x0, x1 = max(0, cx - radius), min(s - 1, cx + radius)
    head = "    " + " ".join(COLUMNS[x] for x in range(x0, x1 + 1))
    lines = [head]
    for y in range(y0, y1 + 1):
        row = []
        for x in range(x0, x1 + 1):
            p = y * s + x
            c = pos.cells[p]
            row.append(c if c != EMPTY else ("*" if p == center else ("#" if p == pos.ko else ".")))
        edge_l = "|" if x0 == 0 else " "
        edge_r = "|" if x1 == s - 1 else " "
        lines.append(f"{s - y:>3}{edge_l}" + " ".join(row) + f"{edge_r}{s - y}")
    lines.append(head)
    return "\n".join(lines)


def fmt_points(ps: Iterable[int], size: int, limit: int = 12) -> str:
    ps = list(ps)
    txt = ",".join(coord(p, size) for p in ps[:limit])
    return txt + (f",…(+{len(ps) - limit})" if len(ps) > limit else "")


def position_card(pos: Position, *, title: str = "", history: Optional[list[str]] = None,
                  marks: Optional[dict[int, str]] = None, max_chains: int = 40, ladders: bool = True,
                  show_area: bool = True) -> str:
    """The standard text observation of a position for an LLM."""
    s = pos.size
    me = pos.to_play
    out = []
    out.append(f"{title + ' — ' if title else ''}{s}x{s}, komi {pos.komi:g}, Chinese area scoring. "
               f"To play: {NAME[me]}. Stones on board: {pos.stones()} ({pos.phase()}).")
    if pos.ko is not None:
        out.append(f"Ko: {NAME[me]} may NOT play {coord(pos.ko, s)} this turn (marked # on the board).")
    if pos.passes:
        out.append("The previous move was a pass; if you pass too, the game ends and is scored as it stands.")
    if history:
        out.append("Recent moves: " + "  ".join(history[-8:]))
    out.append("")
    out.append(board_diagram(pos, marks=marks))
    chs = chains(pos)
    alive = benson_alive(pos, BLACK) | benson_alive(pos, WHITE)
    # chain table, most urgent first
    def urgency(c):
        return (len(c["libs"]), -len(c["stones"]))
    rows = sorted(chs, key=urgency)
    out.append("")
    out.append(f"CHAINS ({len(chs)} total; sorted by liberties, the most urgent first):")
    out.append("  id   colour size libs  stones                         notes")
    for c in rows[:max_chains]:
        notes = []
        nl = len(c["libs"])
        if nl == 1:
            notes.append(f"IN ATARI — capture/escape at {coord(c['libs'][0], s)}")
        elif nl == 2:
            notes.append(f"2 libs at {fmt_points(c['libs'], s)}")
        if ladders and nl <= 2 and len(c["stones"]) <= 12:
            lad = ladder_captured(pos, c["stones"][0])
            if lad is True:
                notes.append("ladder: CAN be captured")
            elif lad is False and nl == 2:
                notes.append("ladder: escapes")
        if c["stones"][0] in alive:
            notes.append("unconditionally alive")
        out.append(f"  {c['id']:<4} {'X' if c['color'] == BLACK else 'O':<6} {len(c['stones']):<4} {nl:<5} "
                   f"{fmt_points(c['stones'], s, 8):<30} {'; '.join(notes)}")
    if len(rows) > max_chains:
        out.append(f"  … {len(rows) - max_chains} more chains with ≥{len(rows[max_chains]['libs'])} liberties omitted")
    if show_area:
        est = area_estimate(pos)
        lead = est["lead_black"]
        out.append("")
        out.append(f"ROUGH AREA SKETCH (influence only; ignores dead stones and weak groups — do not trust it "
                   f"blindly): Black ~{est['black']}, White ~{est['white']} + komi {pos.komi:g} → "
                   f"{'Black' if lead > 0 else 'White'} ahead by ~{abs(lead):.0f}. x/o = area leaning to Black/White:")
        out.append(board_diagram(pos, area=est["map"], thresh=est["thresh"]))
    return "\n".join(out)


def short_card(pos: Position, title: str = "") -> str:
    """Board + atari/ko facts only (for intermediate positions in variations)."""
    s = pos.size
    out = [f"{title + ' — ' if title else ''}to play: {NAME[pos.to_play]}"
           + (f"; ko: {NAME[pos.to_play]} may not play {coord(pos.ko, s)}" if pos.ko is not None else "")]
    out.append(board_diagram(pos))
    urgent = [c for c in chains(pos) if len(c["libs"]) <= 1]
    if urgent:
        out.append("In atari: " + "; ".join(f"{'X' if c['color'] == BLACK else 'O'} {fmt_points(c['stones'], s, 4)} "
                                             f"(liberty {coord(c['libs'][0], s)})" for c in urgent))
    return "\n".join(out)
