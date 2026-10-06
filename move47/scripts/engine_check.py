#!/usr/bin/env python3
"""Grade the two north-star target moves with the GPU KataGo (offline judge only).

Positions come from the go-bench game records: AlphaGo-Lee Sedol game 2 before
move 37 (Black P10) and game 4 before move 78 (White L11).  For each one the
engine reports its top moves, the target's search rank, policy prior and rank,
and the points the target loses.  Output is JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TARGETS = [("alphago-leesedol-2016-g2.sgf", 37), ("alphago-leesedol-2016-g4.sgf", 78)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--go-bench", default=os.environ.get("GO_BENCH", str(HERE / "go-bench")))
    ap.add_argument("--katago-bin", default=str(HERE / "engines/katago"))
    ap.add_argument("--katago-model", default=str(HERE / "engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz"))
    ap.add_argument("--katago-config", default=str(HERE / "engines/configs/analysis-gpu.cfg"))
    ap.add_argument("--visits", type=int, nargs="+", default=[2000, 20000])
    a = ap.parse_args()

    sys.path.insert(0, a.go_bench)
    from goarena.katago import KataGo, KataGoConfig
    from gotree.judge import judge_root
    from gotree.probe import load_target

    kg = KataGo(KataGoConfig(binary=a.katago_bin, model=a.katago_model, config=a.katago_config,
                             extra_args=("-override-config", f"maxVisits={max(a.visits)}")))
    out = {"model": Path(a.katago_model).name, "results": []}
    try:
        for sgf, move_no in TARGETS:
            pos, target, color = load_target(str(Path(a.go_bench) / "data" / sgf), move_no)
            for v in a.visits:
                t0 = time.time()
                r = judge_root(kg, pos, {"target": target}, visits=v)
                out["results"].append({"game": sgf, "move_no": move_no, "to_play": color, "visits": v,
                                       "seconds": round(time.time() - t0, 1), **r})
                g = r["graded"]["target"]
                print(f"{sgf}#{move_no} visits={v}: engine best {r['engine_best']} lead {r['engine_lead']}; "
                      f"target {g['move']} rank {g['engine_rank']} policy-rank {g['engine_policy_rank']} "
                      f"loss {g['loss']} pts", file=sys.stderr, flush=True)
    finally:
        kg.close()
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
