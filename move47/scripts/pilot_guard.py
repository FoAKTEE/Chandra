#!/usr/bin/env python3
"""pilot_guard.py: hard spending stop for a detached tree-harness run.

  python3 scripts/pilot_guard.py RUN_DIR --max-usd 400 [--interval 60] [--arena URL] [--arena-dir DIR]

Every --interval seconds it sums cost_usd over the run's job dirs (the accounting of
scripts/pilot_report.py).  Above --max-usd it pauses the arena run (admin token from
ARENA_DIR/admin.token, sent only as a header; a paused run's game is neither played on nor timed out
and can be resumed), then stops the runner's process group (pid in RUN_DIR/runner.pid; SIGTERM,
SIGKILL after --grace s): gotree play, its sandboxed sessions (bwrap --die-with-parent) and the runner.
It exits 0 when the runner ends on its own, 3 after a stop.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pilot_report import DEFAULT_ARENA_DIR, job_usage, tree_dir  # noqa: E402


def alive(pid: int, match: str) -> bool:
    try:
        return match in Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
    except OSError:
        return False


def pause_run(url: str, admin_token: str, run_id: str) -> str:
    req = urllib.request.Request(f"{url.rstrip('/')}/api/admin/runs/{run_id}/status", method="POST",
                                 data=json.dumps({"status": "paused"}).encode(),
                                 headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return "paused" if json.loads(r.read().decode()).get("ok") else "pause refused"
    except (OSError, ValueError) as e:
        return f"pause failed: {type(e).__name__}: {e}"


def stop_group(pid: int, match: str, grace: float) -> str:
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError as e:
        return f"SIGTERM failed: {e}"
    t0 = time.time()
    while time.time() - t0 < grace:
        if not alive(pid, match):
            return "stopped"
        time.sleep(0.5)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass
    return "killed"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pilot_guard", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir")
    p.add_argument("--max-usd", type=float, required=True)
    p.add_argument("--interval", type=float, default=60)
    p.add_argument("--grace", type=float, default=30)
    p.add_argument("--pidfile", default="", help="default RUN_DIR/runner.pid")
    p.add_argument("--match", default="harness.runner", help="the pid's command line must contain this")
    p.add_argument("--arena", default="http://127.0.0.1:8765", help="'' = do not pause the arena run")
    p.add_argument("--arena-dir", default=str(DEFAULT_ARENA_DIR))
    a = p.parse_args(argv)
    run_dir = Path(a.run_dir)
    pid = int(Path(a.pidfile or run_dir / "runner.pid").read_text().strip())

    def log(msg: str) -> None:
        print(f"[{time.strftime('%F %T')}] {msg}", flush=True)

    log(f"guarding runner pid {pid}: stop above {a.max_usd:.2f} USD, check every {a.interval:.0f}s")
    while True:
        cost = sum(float(u["cost_usd"]) for u in job_usage(tree_dir(run_dir)).values())
        if cost > a.max_usd:
            log(f"cumulative worker cost {cost:.2f} USD > {a.max_usd:.2f} USD: stopping the run")
            if a.arena:
                try:
                    run_id = json.loads((run_dir / "logs" / "run.json").read_text())["id"]
                    tok = (Path(a.arena_dir) / "admin.token").read_text().strip()
                    log(f"arena run {run_id}: {pause_run(a.arena, tok, run_id)}")
                except (OSError, ValueError, KeyError) as e:
                    log(f"arena run not paused: {type(e).__name__}: {e}")
            log(f"runner process group {pid}: {stop_group(pid, a.match, a.grace) if alive(pid, a.match) else 'already gone'}")
            return 3
        if not alive(pid, a.match):
            log(f"runner {pid} has exited; cumulative worker cost {cost:.2f} USD")
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
