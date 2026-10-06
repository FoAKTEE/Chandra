"""gtree — the tool a Claude Code / Codex worker uses inside a job directory.

  gtree card | window P10 [--radius 4] | try P10 Q11 ... [--winrate 0.4] [--note ...]
  gtree ladder Q11 | known | lessons "<keywords>" | schema | submit result.json

Reads the job from $GTREE_JOB (default: current directory).  It never
touches the search tree directly: explored lines go to tries.jsonl and the
accepted answer to accepted.json; the orchestrator ingests both.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .jobs import EXAMPLES, SCHEMAS, InvalidResult, Job, describe_known, validate
from .perception import position_card, window
from .position import coord, point
from .workers import tool_ladder, tool_try


def _job() -> tuple[Job, Path]:
    jd = Path(os.environ.get("GTREE_JOB", "."))
    f = jd / "job.json"
    if not f.exists():
        sys.exit("gtree: no job.json here (set GTREE_JOB)")
    return Job.from_json(json.loads(f.read_text())), jd


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="gtree")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("card")
    w = sub.add_parser("window")
    w.add_argument("center")
    w.add_argument("--radius", type=int, default=4)
    t = sub.add_parser("try")
    t.add_argument("moves", nargs="+")
    t.add_argument("--winrate", type=float, default=None,
                   help="your estimate, at the end of the line, that the side to move NOW wins")
    t.add_argument("--note", default="")
    l = sub.add_parser("ladder")
    l.add_argument("point")
    sub.add_parser("known")
    s = sub.add_parser("lessons")
    s.add_argument("query")
    sub.add_parser("schema")
    sb = sub.add_parser("submit")
    sb.add_argument("file")
    a = p.parse_args(argv)
    job, jd = _job()
    pos = job.pos

    if a.cmd == "card":
        print(position_card(pos, title=job.params.get("title", "Position")))
    elif a.cmd == "window":
        try:
            print(window(pos, point(a.center, pos.size), a.radius))
        except Exception as e:
            print(f"error: {e}")
            return 2
    elif a.cmd == "try":
        moves = [m for m in a.moves if m.strip()]
        out, pts = tool_try(pos, moves)
        print(out)
        if pts:
            with open(jd / "tries.jsonl", "a") as f:
                f.write(json.dumps({"moves": pts, "winrate": a.winrate, "note": a.note[:300]}) + "\n")
    elif a.cmd == "ladder":
        try:
            print(tool_ladder(pos, a.point))
        except Exception as e:
            print(f"error: {e}")
            return 2
    elif a.cmd == "known":
        dag_path = os.environ.get("GTREE_DAG")
        if not dag_path:
            print("(no shared tree available)")
        else:
            from .dag import DAG
            print(describe_known(DAG(dag_path, readonly=True), job.key, pos) or "(nothing yet)")
    elif a.cmd == "lessons":
        mem_path = os.environ.get("GTREE_MEM")
        if not mem_path:
            print("(no lesson memory available)")
        else:
            from .memory import Memory
            rows = Memory(mem_path, readonly=True).search(a.query)
            print("\n".join(f"[{'G' if r['scope'] == 'global' else 'L'}{r['id']}] {r['text']}" for r in rows)
                  or "(no matches)")
    elif a.cmd == "schema":
        print(json.dumps(SCHEMAS[job.kind], indent=1))
        print("Example:")
        print(json.dumps(EXAMPLES[job.kind], indent=1))
    elif a.cmd == "submit":
        try:
            raw = json.loads(sys.stdin.read() if a.file == "-" else Path(a.file).read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"INVALID: cannot read JSON ({e})")
            return 2
        try:
            res = validate(job, raw)
        except InvalidResult as e:
            print(f"INVALID: {e}")
            return 2
        (jd / "accepted.json").write_text(json.dumps(raw))
        warn = res.get("warnings") or []
        print("OK" + (f" (ignored: {'; '.join(warn[:5])})" if warn else ""))
        if job.kind in ("expand", "more", "refute"):
            print("accepted moves: " + ", ".join(coord(c["move"], pos.size) for c in res["candidates"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
