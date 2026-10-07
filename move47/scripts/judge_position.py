#!/usr/bin/env python3
"""Offline judge: grade given moves in an SGF position with the strong KataGo net (measurement only).

    python3 scripts/judge_position.py --sgf game.sgf --upto 22 --moves H7,E6,C2 --visits 1600,20000 \
        [--path-root DIR] [--out FILE]

For each visit count: KataGo analyses the position after the first `--upto` plies of the SGF's main
line (gotree.judge.judge_root: the stones as set up, ko rebuilt), reports its best move and score
lead (side to move), and grades every move in `--moves`: rank in KataGo's move list (null when the
move got no visits), policy prior and its rank, and the points lost (best lead minus the lead after
the move, from a search of the child position with a quarter of the visits, at least 100).

The engine is reached through kgservice (`bin/kg-client`, a live backend for the model's basename;
start one with scripts/arena_up.sh or `python3 -m kgservice keepalive`).  --katago-bin may name any
KataGo-compatible analysis binary (tests use tests/fake_katago.py).  KataGo searches with several
threads and nnRandomize, so repeated runs differ slightly.

Firewall (TREE.md hard constraint 1): this is an offline judge.  Its output is evidence for
reports; it never enters a search, a prompt, the lesson memory or the learned weights.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Optional

M47 = Path(__file__).resolve().parent.parent
if str(M47) not in sys.path:
    sys.path.insert(0, str(M47))

from goarena.katago import KataGo, KataGoConfig  # noqa: E402
from gotree.judge import judge_root  # noqa: E402
from gotree.position import BLACK, IllegalMove, Position, point  # noqa: E402

STRONG = "engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz"
CONFIG = "engines/configs/analysis-gpu.cfg"


def parse_moves(spec: str, size: int) -> list[tuple[str, Optional[int]]]:
    out = []
    for c in (x.strip() for x in spec.split(",")):
        if not c:
            continue
        try:
            p = point(c, size)
        except IllegalMove as e:
            raise ValueError(f"bad move {c!r}: {e}") from None
        out.append((c.upper() if p is not None else "pass", p))
    if not out:
        raise ValueError("no moves given")
    return out


def _rel(path: str, root: str) -> str:
    if not root:
        return path
    for pre in sorted({str(Path(root)).rstrip("/") + "/", str(Path(root).resolve()).rstrip("/") + "/"},
                      key=len, reverse=True):
        if path.startswith(pre):
            return path[len(pre):]
    return path


def judge(kg, pos: Position, moves: list[tuple[str, Optional[int]]], visits: list[int]) -> list[dict]:
    for c, p in moves:
        if p is not None and not pos.is_legal(p):
            raise ValueError(f"{c} is not legal in this position")
    out = []
    for v in visits:
        t0 = time.time()
        r = judge_root(kg, pos, {c: p for c, p in moves}, visits=v)
        out.append({"visits": v, "child_visits": max(100, v // 4), "seconds": round(time.time() - t0, 1), **r})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sgf", required=True)
    ap.add_argument("--upto", type=int, required=True, help="the position after this many main-line plies")
    ap.add_argument("--moves", required=True, help="comma-separated moves to grade, e.g. H7,E6,C2")
    ap.add_argument("--visits", default="1600,20000", help="comma-separated visit counts")
    ap.add_argument("--katago-bin", default=str(M47 / "bin/kg-client"))
    ap.add_argument("--model", default=str(M47 / STRONG))
    ap.add_argument("--config", default=str(M47 / CONFIG), help="ignored by bin/kg-client")
    ap.add_argument("--timeout", type=float, default=1800.0, help="seconds per engine query")
    ap.add_argument("--path-root", default="", help="write paths under DIR relative to DIR")
    ap.add_argument("--out", default="", help="also write the JSON here")
    a = ap.parse_args(argv)

    text = Path(a.sgf).read_text()
    pos = Position.from_sgf(text, upto=a.upto)
    moves = parse_moves(a.moves, pos.size)
    visits = [int(v) for v in a.visits.split(",") if v.strip()]
    kg = KataGo(KataGoConfig(binary=a.katago_bin, model=a.model, config=a.config))
    orig_query = kg.query
    kg.query = lambda payload, expected=1, timeout=a.timeout: orig_query(payload, expected, timeout)
    t0 = time.time()
    try:
        results = judge(kg, pos, moves, visits)
    finally:
        kg.close()
    out = {"tool": "move47/scripts/judge_position.py", "sgf": _rel(str(Path(a.sgf).resolve()), a.path_root),
           "sgf_sha256": hashlib.sha256(text.encode()).hexdigest(), "upto": a.upto, "size": pos.size,
           "komi": pos.komi, "to_play": "B" if pos.to_play == BLACK else "W",
           "model": Path(a.model).name, "engine_bin": Path(a.katago_bin).name,
           "values": "side to move; loss = best lead - lead after the move (points)",
           "moves": [c for c, _ in moves], "date": time.strftime("%Y-%m-%d %H:%M:%S"),
           "seconds": round(time.time() - t0, 1), "results": results}
    js = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(js + "\n")
    print(js)
    for r in results:
        g = ", ".join(f"{k} rank {x['engine_rank']} loss {x['loss']}" for k, x in r["graded"].items())
        print(f"visits {r['visits']}: best {r['engine_best']} lead {r['engine_lead']}; {g} ({r['seconds']}s)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
