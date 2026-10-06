"""Template for agent-maintained heuristics (Heuristic Learning loop).

Copy to gotree/user_heuristics.py to activate.  A coding agent (Claude Code /
Codex) improves these functions using the search DAG as data:

    python -m gotree heurtest --run runs/<run>     # baseline numbers
    ... edit score_moves / value ...
    python -m gotree heurtest --run runs/<run>     # keep only real improvements
    python -m pytest tests/test_user_heuristics.py  # golden positions must still pass

Rules: no pretrained Go engines or networks, no downloaded game records.
Pattern tables, rules, small hand-written evaluators are all fine.
"""
from __future__ import annotations

from typing import Optional

from gotree.heuristics import _default_score_moves, _default_value
from gotree.position import Position


def score_moves(pos: Position) -> list[tuple[Optional[int], float]]:
    """Return [(point, score)] sorted best first (point None = pass)."""
    return _default_score_moves(pos)


def value(pos: Position) -> float:
    """Probability (0-1) that the side to move wins."""
    return _default_value(pos)
