#!/usr/bin/env python3
"""Code-only MCTS v2 ablation games with ONE online learner shared by parallel game streams.

    python3 scripts/ablation_play.py --run <dir outside Chandra> --plan plan.json [--dry-run]

plan.json:
    {"time_per_move": 30, "threads": 16,
     "arenas": {"ladder": {"url": "http://127.0.0.1:8766", "dir": "<arena dir>"},
                "kata1":  {"url": "http://127.0.0.1:8765", "dir": "<arena dir>"}},
     "streams": {"A": [{"arena": "ladder", "opponent": "lv7", "games": 6},
                       {"arena": "kata1", "opponent": "k1-full", "games": 1, "color": "B"}],
                 "B": [...]},
     "play_args": ["--set", "KEY=VALUE", ...]}          # optional, extra `mcts play` arguments

What runs: every stream is a thread that plays its segments in order; a segment is one arena run
(created through the arena's admin API on first use, resumed afterwards) against one opponent.
Each game is exactly what `python3 -m mcts play --llm off --learn` plays: the engine, decision and
learner settings come from mcts.play's own parser (`play_args` on top), one tree per game
(mcts.play.Player), the arena loop mcts.play.play_games.  The difference: all streams share one
mcts.hl.OnlineLearner in <run>/hl (its weights provider, its samples and its update sequence), so
the weights keep improving from game to game across streams.  update() calls are serialised by a
lock (two concurrent fits would both start from the same parent version).  A separate process per
stream cannot share one learner directory safely: each process numbers its versions from its own
memory (see the report).

Per segment directory <run>/<stream>/<segment>/: config.json, log.txt, moves.jsonl (one line per
decision, incl. the weights version the search used), arena.json (run id, url, opponent; no token)
and agent.token (mode 600).  <run>/plan.json is a copy of the plan; <run>/driver.log the driver's log.
A restart resumes every segment (arena runs by id, active games from the arena, the learner from
its directory).  Code only: no model sessions, no cost.  KataGo is only the opponent and the
arena's referee/reviewer; nothing it computes reaches the search or the learner.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

M47 = Path(__file__).resolve().parent.parent
if str(M47) not in sys.path:
    sys.path.insert(0, str(M47))

from harness.arena_client import ArenaClient  # noqa: E402
from mcts import play as P  # noqa: E402
from mcts.cli import _run_dir  # noqa: E402


class SerialLearner:
    """The shared learner with update() (and observe_game()) serialised; everything else passes through."""

    def __init__(self, learner):
        self._l = learner
        self._ulock = threading.Lock()

    def update(self):
        with self._ulock:
            return self._l.update()

    def observe_game(self, result, our_color):
        with self._ulock:
            return self._l.observe_game(result, our_color)

    def __getattr__(self, name):
        return getattr(self._l, name)


def play_namespace(run: Path, opponent: str, plan: dict, seed: int) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    P.add_parsers(ap.add_subparsers())
    argv = ["play", "--run", str(run), "--opponent", opponent, "--llm", "off", "--learn",
            "--time-per-move", str(plan["time_per_move"]), "--threads", str(plan["threads"]),
            "--seed", str(seed), "--save-every", str(plan.get("save_every", 0)), "--max-load-frac", "0",
            *plan.get("play_args", [])]
    return ap.parse_args(argv)


def _logger(path: Path, prefix: str, lock: threading.Lock):
    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        with lock:
            print(f"{prefix} {line}", flush=True)
        with open(path, "a") as f:
            f.write(line + "\n")
    return log


def ensure_run(seg_dir: Path, arena: dict, seg: dict, stream: str, plan: dict) -> tuple[str, str]:
    """(run id, agent token) of the segment's arena run; created on first use."""
    meta_f, tok_f = seg_dir / "arena.json", seg_dir / "agent.token"
    if meta_f.exists() and tok_f.exists():
        return json.loads(meta_f.read_text())["run_id"], tok_f.read_text().strip()
    admin = (Path(arena["dir"]) / "admin.token").read_text().strip()
    name = plan.get("name", "MCTS v2 code-only + HL (ablation)") + f" / {stream} {seg['opponent']}"
    out = ArenaClient(arena["url"], admin_token=admin).create_run(
        name=name, model="", harness="mcts", reasoning="", context="",
        notes=f"ablation: --llm off --learn, {plan['time_per_move']}s/move, {plan['threads']} threads, "
              f"shared learner; stream {stream}",
        target_games=int(seg["games"]), config={"opponents": [seg["opponent"]]})
    if not out.get("ok"):
        raise RuntimeError(f"could not create the arena run: {out}")
    run = out["run"]
    fd = os.open(tok_f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(run["token"] + "\n")
    meta_f.write_text(json.dumps({"run_id": run["id"], "url": arena["url"], "arena": seg["arena"],
                                  "opponent": seg["opponent"], "games": int(seg["games"]),
                                  "color": seg.get("color"), "name": name}, indent=1) + "\n")
    return run["id"], run["token"]


def play_segment(run: Path, stream: str, idx: int, seg: dict, plan: dict, learner, printlock, dlog) -> list:
    arena = plan["arenas"][seg["arena"]]
    seg_dir = run / stream / f"{idx:02d}-{seg['arena']}-{seg['opponent']}"
    seg_dir.mkdir(parents=True, exist_ok=True)
    log = _logger(seg_dir / "log.txt", f"[{stream}/{seg['opponent']}]", printlock)
    a = play_namespace(seg_dir, seg["opponent"], plan, seed=plan.get("seed", 0) * 100 + ord(stream[0]) + idx)
    cfg, dcfg = P._engine_config(a), P._decide_config(a)
    dcfg.rule = "visits"                                  # code-only, as cmd_play does without the service
    run_id, token = ensure_run(seg_dir, arena, seg, stream, plan)
    P._write_config(seg_dir, a, cfg, None, a.threads)
    log(f"segment {idx}: {seg['games']} game(s) vs {seg['opponent']} on {arena['url']} (run {run_id}), "
        f"{a.time_per_move}s/move, {a.threads} threads, shared learner {learner.run_dir}; load "
        f"{os.getloadavg()[0]:.0f}")
    player = P.Player(seg_dir, cfg, a.time_per_move, a.threads, a.sims, learner.provider, learner, None,
                      a.save_every, log, decide_cfg=dcfg)
    client = ArenaClient(arena["url"], token)
    for attempt in range(1, int(plan.get("retries", 5)) + 1):
        try:
            res = P.play_games(client, seg["opponent"], int(seg["games"]), player, seg.get("color"),
                               record=seg_dir / "moves.jsonl", abstract=False, log=log)
            player.close()
            st = client.status().get("summary") or {}
            if st.get("games_played", 0) >= st.get("target_games", 1):
                return res
            log(f"play_games returned with {st.get('games_played')}/{st.get('target_games')} games; again")
        except Exception as e:  # resumable: the arena keeps the game, the learner its directory
            player.close()
            log(f"segment error (attempt {attempt}): {e!r}\n{traceback.format_exc()}")
            dlog(f"stream {stream} segment {idx} error {e!r}; retrying in 60s")
            time.sleep(60)
    raise RuntimeError(f"stream {stream} segment {idx}: gave up")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True, help="run directory outside the Chandra tree")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--dry-run", action="store_true", help="print the per-segment settings and exit")
    a = ap.parse_args(argv)
    run = _run_dir(a.run)
    plan = json.loads(Path(a.plan).read_text())
    if not (run / "plan.json").exists():
        (run / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    printlock = threading.Lock()
    dlog = _logger(run / "driver.log", "[driver]", printlock)
    total = len(plan["streams"]) * int(plan["threads"])
    if a.dry_run:
        for s, segs in plan["streams"].items():
            for i, seg in enumerate(segs):
                ns = play_namespace(run / s / f"{i:02d}", seg["opponent"], plan, 0)
                cfg = P._engine_config(ns)
                print(json.dumps({"stream": s, "segment": i, **seg, "time_per_move": ns.time_per_move,
                                  "threads": ns.threads, "llm": ns.llm, "learn": ns.learn,
                                  "root_noise": cfg.root_noise, "n_thr": cfg.n_thr, "max_nodes": cfg.max_nodes,
                                  "decide": "visits", "save_every": ns.save_every}))
        print(f"search threads in all: {total}")
        return 0
    learner = SerialLearner(P.make_learner(run, None, dlog))     # <run>/hl, base default-v1, as `--learn`
    dlog(f"start: {len(plan['streams'])} streams x {plan['threads']} threads = {total} search threads, "
         f"{plan['time_per_move']}s/move; learner {learner.run_dir} at {learner.current_weights().version}; "
         f"load {os.getloadavg()[0]:.0f}")
    errors: dict = {}

    def stream_main(name: str, segs: list) -> None:
        try:
            for i, seg in enumerate(segs):
                res = play_segment(run, name, i, seg, plan, learner, printlock, dlog)
                dlog(f"stream {name} segment {i} done: {json.dumps(res)}")
        except Exception as e:
            errors[name] = repr(e)
            dlog(f"stream {name} failed: {e!r}\n{traceback.format_exc()}")

    threads = [threading.Thread(target=stream_main, args=(n, s), name=f"stream-{n}")
               for n, s in plan["streams"].items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    learner.flush()
    dlog(f"done; learner at {learner.current_weights().version} after {learner.updates} updates "
         f"({learner.accepted} accepted); errors {errors or 'none'}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
