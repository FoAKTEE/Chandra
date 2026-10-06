#!/usr/bin/env python3
"""Stand-in for `claude` / `codex` used to test the runner without a model.

Behaves like an agent CLI session: prints a JSON line with a session id,
then plays exactly one game through the `goban` command found on PATH
(checking that the workspace wiring works), and exits.  The runner must
relaunch it until the run is complete."""
import json
import random
import subprocess
import sys
import uuid

print(json.dumps({"type": "system", "subtype": "init", "session_id": str(uuid.uuid4()), "argv": sys.argv[1:]}),
      flush=True)
assert open("TASK.md").read().startswith("# Go training run")


def goban(*args):
    p = subprocess.run(["goban", *args, "--json"], capture_output=True, text=True)
    return json.loads(p.stdout)


st = goban("status")
if st["summary"]["games_played"] >= st["summary"]["target_games"]:
    sys.exit(0)
r = goban("board") if st.get("active_game") else goban("new", "--opponent", "random")
rng = random.Random()
while not r.get("game_over"):
    rows = r["board_rows"]
    empty = [(x, y) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch == "."]
    rng.shuffle(empty)
    for x, y in empty[:5]:
        mv = "ABCDEFGHJKLMNOPQRST"[x] + str(len(rows) - y)
        r2 = goban("play", mv)
        if r2.get("ok"):
            r = r2
            break
    else:
        r = goban("pass")
print(json.dumps({"type": "result", "result": r["result"]["result"]}), flush=True)
