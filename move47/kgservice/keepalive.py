"""Keep one KataGo backend per model alive across the 1 h job limit and preemption.

Every tick: drop stale rendezvous files (dead pid / job no longer in squeue), then submit
kg_backend.sbatch when no live, non-draining backend for the model has more than `lead`
seconds left, no job for the model is pending or still starting, and fewer than `max_jobs`
of its jobs are queued or running.  Slurm access goes through an injectable object with
`squeue() -> list[job]`, `sbatch(model, config) -> job id` and `scancel(ids)`.
"""
from __future__ import annotations

import argparse
import getpass
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from .common import (DEFAULT_CONFIG, DEFAULT_MODEL, JOB_PREFIX, ROOT, SBATCH_SCRIPT, Log, backend_alive,
                     fmt_left, job_name, model_key, parse_slurm_time, pid_alive, read_backends, run_dir)

log = Log("keepalive")
QUEUED = {"PENDING", "CONFIGURING", "REQUEUED", "REQUEUE_HOLD", "REQUEUE_FED", "RESIZING", "SUSPENDED"}
ACTIVE = QUEUED | {"RUNNING", "COMPLETING", "STAGE_OUT", "SIGNALING"}


def parse_squeue(out: str) -> list[dict]:
    """Lines of `squeue -h -o %i|%j|%T|%S|%e`."""
    jobs = []
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 5 or not parts[0]:
            continue
        jobs.append({"id": parts[0], "name": parts[1], "state": parts[2].upper(),
                     "start": parse_slurm_time(parts[3]), "end": parse_slurm_time(parts[4])})
    return jobs


class SlurmCLI:
    def __init__(self, user: Optional[str] = None, script: Path = SBATCH_SCRIPT):
        self.user = user or getpass.getuser()
        self.script = script

    def squeue(self) -> list[dict]:
        r = subprocess.run(["squeue", "-h", "-u", self.user, "-o", "%i|%j|%T|%S|%e"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"squeue failed: {r.stderr.strip()}")
        return parse_squeue(r.stdout)

    def sbatch(self, model: str, config: str) -> str:
        (ROOT / "logs").mkdir(exist_ok=True)
        env = dict(os.environ, MODEL=model, CONFIG=config)
        r = subprocess.run(["sbatch", "--parsable", f"--job-name={job_name(model)}", str(self.script)],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"sbatch failed: {r.stderr.strip()}")
        return r.stdout.strip().split(";")[0]

    def scancel(self, ids: list[str]) -> None:
        if ids:
            subprocess.run(["scancel", *ids], timeout=60, check=False)


def decide(now: float, backends: list[dict], jobs: list[dict], lead: float, max_jobs: int,
           start_grace: float = 600.0) -> tuple[str, str]:
    """-> (action, reason); action in {"ok", "wait", "full", "submit"}.

    backends: live rendezvous dicts for the model; jobs: squeue dicts for the model's job name."""
    jobs = [j for j in jobs if j["state"] in ACTIVE]
    healthy = [b for b in backends
               if not b.get("draining") and (not b.get("deadline") or b["deadline"] - now > lead)]
    if healthy:
        b = max(healthy, key=lambda b: b.get("deadline") or float("inf"))
        return "ok", f"{b['id']} healthy ({fmt_left(b.get('deadline'), now)} left)"
    with_backend = {str(b.get("slurm_job_id")) for b in backends if b.get("slurm_job_id")}
    starting = [j for j in jobs if j["state"] in QUEUED or (
        j["state"] == "RUNNING" and j["id"] not in with_backend
        and (j.get("start") is None or now - j["start"] < start_grace))]
    if starting:
        return "wait", "job " + ",".join(f"{j['id']}({j['state'].lower()})" for j in starting) + " starting"
    if len(jobs) >= max_jobs:
        return "full", f"{len(jobs)} jobs queued/running (max {max_jobs})"
    if backends:
        return "submit", "backends draining or near their deadline: " + ", ".join(
            f"{b['id']}({'draining, ' if b.get('draining') else ''}{fmt_left(b.get('deadline'), now)} left)"
            for b in backends)
    return "submit", "no live backend"


def clean_stale(rdir: Path, jobs: Optional[list[dict]], now: float, grace: float = 30.0) -> list[str]:
    """Remove rendezvous files whose process is dead or whose Slurm job is gone (jobs=None: skip
    the job check, e.g. when squeue failed)."""
    by_id = {j["id"]: j for j in jobs or []}
    host = socket.gethostname()
    removed = []
    for info in read_backends(rdir):
        why = None
        if info.get("hostname") == host and not pid_alive(info.get("pid")):
            why = "process gone"
        elif jobs is not None and info.get("slurm_job_id") and now - info["_mtime"] > grace:
            j = by_id.get(str(info["slurm_job_id"]))
            if j is None or j["state"] not in ACTIVE:
                why = "job finished"
        if why:
            try:
                os.unlink(info["_path"])
                removed.append(f"{info['id']} ({why})")
            except OSError:
                pass
    return removed


class Keepalive:
    def __init__(self, model: str, config: str, slurm, rdir: Optional[Path] = None, lead: float = 600.0,
                 max_jobs: int = 2, start_grace: float = 600.0, min_submit_gap: float = 60.0,
                 clock: Callable[[], float] = time.time):
        self.model, self.config, self.slurm = model, config, slurm
        self.rdir = rdir or run_dir()
        self.lead, self.max_jobs, self.start_grace = lead, max_jobs, start_grace
        self.min_submit_gap, self.clock = min_submit_gap, clock
        self.last_submit = float("-inf")
        self.last_msg = None

    def tick(self) -> dict:
        now = self.clock()
        try:
            all_jobs: Optional[list[dict]] = self.slurm.squeue()
        except Exception as e:  # noqa: BLE001 -- Slurm trouble must not kill the loop
            log(f"squeue failed: {e}")
            all_jobs = None
        removed = clean_stale(self.rdir, all_jobs, now)
        for r in removed:
            log(f"removed stale rendezvous {r}")
        name = job_name(self.model)
        jobs = [j for j in all_jobs or [] if j["name"] == name]
        backends = [b for b in read_backends(self.rdir)
                    if b.get("model") == model_key(self.model) and backend_alive(b)]
        if all_jobs is None:
            action, reason = "wait", "squeue unavailable"
        else:
            action, reason = decide(now, backends, jobs, self.lead, self.max_jobs, self.start_grace)
        if action == "submit" and now - self.last_submit < self.min_submit_gap:
            action, reason = "wait", f"submitted {now - self.last_submit:.0f}s ago"
        job = None
        if action == "submit":
            try:
                job = self.slurm.sbatch(self.model, self.config)
                self.last_submit = now
                log(f"submitted job {job} for {model_key(self.model)}: {reason}")
            except Exception as e:  # noqa: BLE001
                action, reason = "error", str(e)
                log(f"submit failed: {e}")
        elif (action, reason) != self.last_msg:
            log(f"{action}: {reason}")
        self.last_msg = (action, reason)
        return {"action": action, "reason": reason, "job": job, "removed": removed}

    def run(self, interval: float = 30.0, once: bool = False) -> int:
        stop = []
        signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
        signal.signal(signal.SIGINT, lambda *_: stop.append(1))
        log(f"model {model_key(self.model)}; lead {self.lead:g}s; max jobs {self.max_jobs}; every {interval:g}s")
        while not stop:
            self.tick()
            if once:
                break
            t_end = time.time() + interval
            while not stop and time.time() < t_end:
                time.sleep(0.5)
        return 0


def status(slurm, rdir: Optional[Path] = None) -> int:
    now = time.time()
    infos = read_backends(rdir or run_dir())
    print(f"backends ({rdir or run_dir()}):")
    if not infos:
        print("  none")
    for b in infos:
        alive = backend_alive(b)
        print(f"  {b['id']:<18} {b.get('model')}  port {b.get('port')}  job {b.get('slurm_job_id') or '-'}  "
              f"left {fmt_left(b.get('deadline'), now)}  {'DRAINING ' if b.get('draining') else ''}"
              f"{'alive' if alive else 'DEAD (stale file)'}")
    try:
        jobs = [j for j in slurm.squeue() if j["name"].startswith(JOB_PREFIX)]
    except Exception as e:  # noqa: BLE001
        print(f"jobs: squeue failed: {e}")
        return 1
    print("jobs:")
    if not jobs:
        print("  none")
    for j in jobs:
        print(f"  {j['id']:<8} {j['state']:<11} {j['name']}  left {fmt_left(j.get('end'), now)}")
    return 0


def stop(slurm, model: Optional[str] = None, rdir: Optional[Path] = None) -> int:
    want = job_name(model) if model else None
    jobs = [j for j in slurm.squeue() if j["name"].startswith(JOB_PREFIX) and (want is None or j["name"] == want)]
    slurm.scancel([j["id"] for j in jobs])
    host = socket.gethostname()
    local = [b for b in read_backends(rdir or run_dir()) if not b.get("slurm_job_id")
             and b.get("hostname") == host and (model is None or b.get("model") == model_key(model))]
    for b in local:
        try:
            os.kill(int(b["pid"]), signal.SIGTERM)
        except (OSError, ValueError, TypeError):
            pass
    print(f"cancelled jobs {[j['id'] for j in jobs]}; signalled local backends {[b['id'] for b in local]}")
    return 0


def main(cmd: str, argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=f"kgservice {cmd}", description=__doc__.split("\n")[0])
    if cmd == "keepalive":
        ap.add_argument("--model", default=DEFAULT_MODEL)
        ap.add_argument("--config", default=DEFAULT_CONFIG)
        ap.add_argument("--lead", type=float, default=600.0, help="submit a successor when <lead s are left")
        ap.add_argument("--max-jobs", type=int, default=2)
        ap.add_argument("--interval", type=float, default=30.0)
        ap.add_argument("--start-grace", type=float, default=600.0)
        ap.add_argument("--once", action="store_true", help="one decision, then exit")
    elif cmd == "stop":
        ap.add_argument("--model", default=None, help="only this model's jobs (default: all kgservice jobs)")
    a = ap.parse_args(argv)
    slurm = SlurmCLI()
    if cmd == "status":
        return status(slurm)
    if cmd == "stop":
        return stop(slurm, a.model)
    ka = Keepalive(a.model, a.config, slurm, lead=a.lead, max_jobs=a.max_jobs, start_grace=a.start_grace)
    return ka.run(a.interval, a.once)
