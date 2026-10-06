"""Code-level heuristics ("System 1" written as code, Heuristic-Learning style).

Used for: ordering the mechanical candidate pool when the LLM runs out of
candidates, the mock worker, and as the starting point that a coding agent
(Claude Code / Codex) improves over time.  The HL loop is:

    python -m gotree heurtest --dag runs/x/dag.db      # how well does the code
                                                       # predict what search found?
    (agent edits gotree/user_heuristics.py)            # rules, pattern tables …
    python -m gotree heurtest ...                      # rerun, keep if better

If gotree/user_heuristics.py defines score_moves / value, they override the
defaults below.  These are heuristics written by the agent, never a
pretrained engine.
"""
from __future__ import annotations

import math
from typing import Optional

from .perception import area_estimate
from .position import BLACK, EMPTY, Position, neighbors, other


def _default_score_moves(pos: Position) -> list[tuple[Optional[int], float]]:
    me, opp = pos.to_play, other(pos.to_play)
    s = pos.size
    nb = neighbors(s)
    stones = [p for p, c in enumerate(pos.cells) if c != EMPTY]
    phase = pos.phase()
    out: list[tuple[Optional[int], float]] = []
    for p in pos.legal_moves():
        if pos.is_own_eye(p):
            continue
        nxt = pos.play(p)
        sc = 0.0
        captured = pos.cells.count(opp) - nxt.cells.count(opp)
        sc += 6.0 * captured
        _, libs = nxt.chain(p)
        if len(libs) == 1:
            sc -= 5.0  # self-atari
        # rescue own chains in atari
        for n in nb[p]:
            if pos.cells[n] == me:
                _, l0 = pos.chain(n)
                if len(l0) == 1 and len(libs) >= 2:
                    sc += 5.0
            elif pos.cells[n] == opp:
                _, l1 = nxt.chain(n)
                if len(l1) == 1:
                    sc += 2.0  # atari
        y, x = divmod(p, s)
        line = min(x, y, s - 1 - x, s - 1 - y) + 1
        if phase == "opening":
            sc += {1: -3, 2: -1.5, 3: 1.0, 4: 1.0}.get(line, 0.2)
        else:
            sc += {1: -1.0, 2: -0.3}.get(line, 0.0)
        if stones:
            d = min(abs(y - q // s) + abs(x - q % s) for q in stones)
            sc += 0.8 if 2 <= d <= 4 else (-0.5 if d > 6 else 0.0)
        if pos.last is not None:
            ly, lx = divmod(pos.last, s)
            if abs(ly - y) + abs(lx - x) <= 2:
                sc += 0.7
        out.append((p, sc))
    out.sort(key=lambda t: -t[1])
    return out


def _default_value(pos: Position) -> float:
    est = area_estimate(pos)
    lead = est["lead_black"] if pos.to_play == BLACK else -est["lead_black"]
    return 1 / (1 + math.exp(-lead / 8.0))


try:  # agent-maintained overrides
    from . import user_heuristics as _uh  # type: ignore
except Exception:  # pragma: no cover - optional module
    _uh = None


def score_moves(pos: Position) -> list[tuple[Optional[int], float]]:
    if _uh is not None and hasattr(_uh, "score_moves"):
        return _uh.score_moves(pos)
    return _default_score_moves(pos)


def value(pos: Position) -> float:
    if _uh is not None and hasattr(_uh, "value"):
        return _uh.value(pos)
    return _default_value(pos)


def priors(pos: Position, k: int, temperature: float = 2.0) -> list[tuple[Optional[int], float]]:
    sc = score_moves(pos)[:k]
    if not sc:
        return [(None, 1.0)]
    m = max(v for _, v in sc)
    w = [math.exp((v - m) / temperature) for _, v in sc]
    t = sum(w)
    return [(p, x / t) for (p, _), x in zip(sc, w)]
