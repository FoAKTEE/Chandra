"""Heuristic Learning (HL) support: turn search results into a test suite for
code-level heuristics, so a coding agent can improve them by editing code
(Learning Beyond Gradients style) — "System 2" search results distilled into
"System 1" rules, with regression tests instead of gradients.

  heurtest: for every well-searched DAG node, does the heuristic rank the
            search's preferred move highly, and does its value agree with the
            backed-up value?  Golden positions = nodes with many visits.
"""
from __future__ import annotations

import math

from . import heuristics
from .dag import DAG


def heurtest(dag_path: str, min_visits: int = 6, limit: int = 300) -> dict:
    dag = DAG(dag_path, readonly=True)
    rows = dag.q("SELECT key, n, w FROM nodes WHERE n >= ? AND terminal IS NULL ORDER BY n DESC LIMIT ?",
                 (min_visits, limit))
    top1 = top5 = total = 0
    xs, ys = [], []
    for r in rows:
        st = [c for c in dag.child_stats(r["key"]) if c["n"] > 0]
        if len(st) < 2:
            continue
        pos = dag.position(r["key"])
        best = max(st, key=lambda c: c["n"])["move"]
        ranked = [p for p, _ in heuristics.score_moves(pos)]
        total += 1
        top1 += int(ranked[:1] == [best])
        top5 += int(best in ranked[:5])
        xs.append(heuristics.value(pos))
        ys.append(r["w"] / r["n"])
    corr = None
    if len(xs) >= 3:
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        sy = math.sqrt(sum((y - my) ** 2 for y in ys))
        if sx > 0 and sy > 0:
            corr = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)
    return {"positions": total, "top1": round(top1 / total, 3) if total else None,
            "top5": round(top5 / total, 3) if total else None,
            "value_corr": None if corr is None else round(corr, 3),
            "note": "edit gotree/user_heuristics.py (score_moves / value) and rerun; keep changes that raise top5 "
                    "and value_corr without lowering the arena results"}
