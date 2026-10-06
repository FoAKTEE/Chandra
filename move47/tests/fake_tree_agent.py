#!/usr/bin/env python3
"""Stand-in for `claude -p` / `codex exec` inside a gotree job directory.

Exercises the real worker protocol: reads job.json, uses the `gtree` tool
on PATH (card, try, schema), writes result.json, and submits it with
`gtree submit` (first a deliberately broken answer, to check that
validation errors are reported and a resubmission is accepted)."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gotree import heuristics  # noqa: E402
from gotree.jobs import Job  # noqa: E402
from gotree.position import coord  # noqa: E402

print(json.dumps({"type": "system", "subtype": "init", "session_id": "fake-session"}), flush=True)
job = Job.from_json(json.loads(Path("job.json").read_text()))
assert Path("JOB.md").read_text().startswith("You are one worker")


def gtree(*args):
    return subprocess.run(["gtree", *args], capture_output=True, text=True)


assert "To play" in gtree("card").stdout
pos = job.pos
pri = heuristics.priors(pos, 5)
if job.kind in ("expand", "more", "refute"):
    first = coord(pri[0][0], pos.size)
    out = gtree("try", first, "--winrate", "0.6", "--note", "first idea")
    assert "Sequence played" in out.stdout, out.stdout + out.stderr
    ans = {"candidates": [{"move": coord(p, pos.size), "prior": w, "why": "fake"} for p, w in pri],
           "value": {"winrate": 0.5, "confidence": "low", "why": "fake"}}
elif job.kind == "rollout":
    ans = {"moves": [coord(pri[0][0], pos.size)], "value_at_end": {"winrate": 0.5, "confidence": "low", "why": "f"}}
elif job.kind == "decide":
    ans = {"move": job.params.get("most_visited", "pass"), "why": "fake"}
elif job.kind == "abstract":
    ans = {"lessons": [{"scope": "global", "text": "fake lesson"}]}
else:
    ans = {"recognized": False}
Path("result.json").write_text(json.dumps({"broken": True} if job.kind != "recall" else ans))
bad = gtree("submit", "result.json")
if job.kind != "recall":
    assert "INVALID" in bad.stdout, bad.stdout
Path("result.json").write_text(json.dumps(ans))
ok = gtree("submit", "result.json")
assert ok.stdout.startswith("OK"), ok.stdout + ok.stderr
print(json.dumps({"type": "result", "usage": {"input_tokens": 1000, "output_tokens": 100}, "total_cost_usd": 0.01}))
