#!/usr/bin/env python3
"""GPU smoke for the kgservice: goarena's KataGo class through bin/kg-client, in a loop.

Cycles through 9x9 and 19x19 queries (search with policy, ownership, raw policy at 1 visit,
an analyzeTurns review) until --duration elapses or SIGINT/SIGTERM, printing one JSON line
per query and a final summary: queries, errors, longest query latency and the longest gap
between consecutive answers.  Run it while backend jobs are started, drained and cancelled.
The client's own events (backend chosen, lost, queries resent) go to $KGSERVICE_LOG if set.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goarena.board import Board, point_to_coord  # noqa: E402
from goarena.katago import KataGo, KataGoConfig  # noqa: E402
from goarena.sgf import read_sgf  # noqa: E402


def positions() -> list[tuple[str, Board, dict]]:
    b9 = Board(9, 7.5)
    for mv in ("E5", "C3", "G7", "C7", "G3", "E3", "E7", "D7", "F4", "D4"):
        b9.play_coord(mv)
    g = read_sgf((ROOT / "data/alphago-leesedol-2016-g2.sgf").read_text())
    b19 = Board(g["size"], g["komi"])
    for color, p in g["moves"][:36]:            # AlphaGo-Lee Sedol game 2, before move 37
        b19.play(p, color)
    return [("9x9-search", b9, {"visits": 400, "policy": True}),
            ("19x19-search", b19, {"visits": 400, "ownership": True}),
            ("9x9-raw-policy", b9, {"visits": 1, "policy": True}),
            ("9x9-review", b9, {"visits": 50, "analyze_turns": list(range(len(b9.moves) + 1)), "priority": -10}),
            ("19x19-raw-policy", b19, {"visits": 1, "policy": True})]


def vary(board: Board, rng: random.Random, k: int) -> Board:
    """The base position plus k random legal moves, so most queries are fresh searches."""
    b = board.copy()
    for _ in range(k):
        legal = [p for p in b.legal_moves() if not b.is_eye_like(p, b.to_play)]
        if not legal:
            break
        b.play(rng.choice(legal))
    return b


def best_move(res: dict, size: int) -> str:
    if res.get("moveInfos"):
        return res["moveInfos"][0]["move"]
    pol = res.get("policy") or []                # 1 visit: no children searched, use the raw policy
    if not pol:
        return "?"
    i = max(range(len(pol)), key=pol.__getitem__)
    return point_to_coord(None if i == size * size else i, size)


def long_review(kg: KataGo, visits: int, out) -> int:
    _, b19, _ = positions()[1]
    turns = list(range(len(b19.moves) + 1))
    t0 = time.time()
    rec = {"long_review": True, "board": 19, "visits": visits, "turns_requested": len(turns),
           "start": time.strftime("%H:%M:%S")}
    try:
        res = kg.analyze(b19, visits, analyze_turns=turns, priority=-10)
        rec.update(ok=sorted(res) == turns, turns_answered=len(res),
                   min_visits=min(r["rootInfo"]["visits"] for r in res.values()))
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error=f"{type(e).__name__}: {e}")
    finally:
        kg.close()
    rec.update(seconds=round(time.time() - t0, 2), end=time.strftime("%H:%M:%S"),
               client_stderr_tail=kg._stderr_tail[-8:])
    out(rec)
    return 0 if rec["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--duration", type=float, default=600.0)
    ap.add_argument("--pause", type=float, default=0.25, help="seconds between queries")
    ap.add_argument("--seed", type=int, default=47)
    ap.add_argument("--long-review", type=int, metavar="VISITS", default=0,
                    help="instead of the loop: one 19x19 analyzeTurns review of turns 0..36 at VISITS "
                         "(long enough to cancel a backend underneath it)")
    ap.add_argument("--katago-bin", default=os.environ.get("KATAGO_BIN", str(ROOT / "bin/kg-client")))
    ap.add_argument("--model", default=str(ROOT / "engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz"))
    ap.add_argument("--config", default=str(ROOT / "engines/configs/analysis-gpu.cfg"))
    a = ap.parse_args()
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append("SIGTERM"))
    signal.signal(signal.SIGINT, lambda *_: stop.append("SIGINT"))

    def out(obj):
        print(json.dumps(obj), flush=True)

    kg = KataGo(KataGoConfig(binary=a.katago_bin, model=a.model, config=a.config))
    if a.long_review:
        return long_review(kg, a.long_review, out)
    pos = positions()
    rng = random.Random(a.seed)
    t_start = last_ok = time.time()
    n = errors = 0
    max_lat = max_gap = 0.0
    worst = None
    try:
        while not stop and time.time() - t_start < a.duration:
            kind, base, kw = pos[n % len(pos)]
            board = base if "analyze_turns" in kw else vary(base, rng, rng.randint(0, 6))
            t0 = time.time()
            rec = {"i": n, "t": round(t0 - t_start, 2), "clock": time.strftime("%H:%M:%S"), "kind": kind}
            try:
                res = kg.analyze(board, kw["visits"], policy=kw.get("policy", False),
                                 ownership=kw.get("ownership", False), analyze_turns=kw.get("analyze_turns"),
                                 priority=kw.get("priority", 0))
                one = res if "analyze_turns" not in kw else res[max(res)]
                if "analyze_turns" in kw:
                    assert sorted(res) == kw["analyze_turns"], f"turns {sorted(res)}"
                if kw.get("policy"):
                    assert len(one["policy"]) == board.size ** 2 + 1
                if kw.get("ownership"):
                    assert len(one["ownership"]) == board.size ** 2
                rec.update(ok=True, visits=one["rootInfo"]["visits"], best=best_move(one, board.size),
                           winrate_black=round(one["rootInfo"]["winrate"], 4),
                           turns=len(res) if "analyze_turns" in kw else 1)
            except Exception as e:  # noqa: BLE001 -- the smoke records every failure
                errors += 1
                rec.update(ok=False, error=f"{type(e).__name__}: {e}")
            t1 = time.time()
            lat, gap = t1 - t0, (t1 - last_ok if rec["ok"] else 0.0)
            rec.update(latency=round(lat, 3), gap=round(gap, 3))
            if rec["ok"]:
                last_ok = t1
            if lat > max_lat:
                max_lat, worst = lat, rec
            max_gap = max(max_gap, gap)
            out(rec)
            n += 1
            if a.pause > 0 and not stop:
                time.sleep(a.pause)
    finally:
        kg.close()
    out({"summary": True, "queries": n, "errors": errors, "seconds": round(time.time() - t_start, 1),
         "max_latency": round(max_lat, 3), "max_gap_between_answers": round(max_gap, 3),
         "slowest": worst, "stopped_by": stop[0] if stop else "duration",
         "client_stderr_tail": kg._stderr_tail[-12:]})
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
