"""Minimal SGF (FF[4]) writer and main-line reader."""
from __future__ import annotations

import re
from typing import Iterable, Optional

from .board import BLACK, WHITE, Board

_SGF_LETTERS = "abcdefghijklmnopqrs"


def point_to_sgf(p: Optional[int], size: int) -> str:
    if p is None:
        return ""
    y, x = divmod(p, size)
    return _SGF_LETTERS[x] + _SGF_LETTERS[y]


def sgf_to_point(s: str, size: int) -> Optional[int]:
    s = s.strip()
    if s == "" or (s == "tt" and size <= 19):
        return None
    x, y = _SGF_LETTERS.index(s[0]), _SGF_LETTERS.index(s[1])
    return y * size + x


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("]", "\\]")


def write_sgf(size: int, komi: float, moves: Iterable[tuple[int, Optional[int]]], *,
              black: str = "", white: str = "", result: str = "", date: str = "",
              event: str = "", comment: str = "", move_comments: Optional[dict[int, str]] = None) -> str:
    """moves: iterable of (color, point|None). move_comments: ply(1-based) -> text."""
    props = [f"GM[1]FF[4]CA[UTF-8]AP[goarena:0.1]SZ[{size}]KM[{komi:g}]RU[Chinese]"]
    if black:
        props.append(f"PB[{_esc(black)}]")
    if white:
        props.append(f"PW[{_esc(white)}]")
    if date:
        props.append(f"DT[{_esc(date)}]")
    if event:
        props.append(f"EV[{_esc(event)}]")
    if result:
        props.append(f"RE[{_esc(result)}]")
    if comment:
        props.append(f"GC[{_esc(comment)}]")
    out = ["(;" + "".join(props)]
    move_comments = move_comments or {}
    for i, (color, p) in enumerate(moves, start=1):
        node = f";{'B' if color == BLACK else 'W'}[{point_to_sgf(p, size)}]"
        if i in move_comments:
            node += f"C[{_esc(move_comments[i])}]"
        out.append(node)
    out.append(")")
    # wrap lines for readability
    text, line = [], ""
    for tok in out:
        if line and len(line) + len(tok) > 78:
            text.append(line)
            line = ""
        line += tok
    text.append(line)
    return "\n".join(text) + "\n"


_PROP_RE = re.compile(r"([A-Z]+)((?:\[(?:\\.|[^\]])*\])+)", re.S)
_VAL_RE = re.compile(r"\[((?:\\.|[^\]])*)\]", re.S)


def read_sgf(text: str) -> dict:
    """Parse the main line of an SGF game.  Returns
    {size, komi, props: {...root props}, moves: [(color, point)]}."""
    text = text.strip()
    if not text.startswith("("):
        raise ValueError("not an SGF game")
    # main line only: drop variations by taking first branch greedily
    nodes, depth, buf, in_val, esc = [], 0, "", False, False
    for ch in text:
        if in_val:
            buf += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "]":
                in_val = False
            continue
        if ch == "[":
            in_val = True
            buf += ch
        elif ch == "(":
            depth += 1
            if depth > 2:  # ignore nested variations beyond the main line
                break
        elif ch == ")":
            depth -= 1
        elif ch == ";":
            if buf.strip():
                nodes.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        nodes.append(buf)
    parsed = []
    for n in nodes:
        props = {}
        for m in _PROP_RE.finditer(n):
            vals = [v.replace("\\]", "]").replace("\\\\", "\\") for v in _VAL_RE.findall(m.group(2))]
            props[m.group(1)] = vals
        parsed.append(props)
    root = parsed[0] if parsed else {}
    size = int(root.get("SZ", ["19"])[0])
    komi = float(root.get("KM", ["7.5"])[0] or 7.5)
    moves = []
    for props in parsed[1:]:
        if "B" in props:
            moves.append((BLACK, sgf_to_point(props["B"][0], size)))
        elif "W" in props:
            moves.append((WHITE, sgf_to_point(props["W"][0], size)))
    return {"size": size, "komi": komi, "props": {k: v[0] if len(v) == 1 else v for k, v in root.items()},
            "moves": moves}


def replay(sgf_text: str) -> Board:
    g = read_sgf(sgf_text)
    b = Board(g["size"], g["komi"])
    for color, p in g["moves"]:
        b.play(p, color)
    return b
