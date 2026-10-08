#!/usr/bin/env python3
"""Full-system arena games (node move47::mcts-strength): MCTS v2 with the model service, online learning
from hybrid play and the model-written heuristics book, one learning state shared by parallel game streams.

    python3 scripts/strength_play.py --run <dir outside Chandra> --plan plan.json [--dry-run]

plan.json:
    {"name": "MCTS v2 + model + HL (full system)", "time_per_move": 300, "threads": 28, "llm_workers": 8,
     "worker": "<worker spec, gotree>", "wrap": "<move47>/bin/worker-sandbox {jobdir}",
     "save_every": 5, "seed": 11, "wait_for_model_h": 6, "drain_s": 1200,
     "budget": {"max_cost_usd": 3000, "stop_margin_usd": 40, "game_reserve_usd": 250},
     "arenas": {"ladder": {"url": "http://127.0.0.1:8766", "dir": "<arena dir>"},
                "kata1":  {"url": "http://127.0.0.1:8765", "dir": "<arena dir>"}},
     "streams": {"A": [{"arena": "ladder", "opponent": "lv8", "games": 2},
                       {"arena": "kata1", "opponent": "k1-p", "games": 1, "color": "B"}], "B": [...]},
     "play_args": ["--n-thr", "100000", "--hl", "capacity=80000", ...],     # more `mcts play` arguments
     "teardown": [["bash", "<move47>/scripts/arena_down.sh", "--profile", "ladder"], ...]}   # optional

Every game is what `python3 -m mcts play --learn --heuristics` (model on) plays: mcts.play's parser, Player
and play_games; decisions by mcts/decide.py; a lessons (`abstract`) job and a heuristic job after every
decision.  Shared by all streams: one mcts.hl.OnlineLearner in <run>/hl (hybrid mode, update() serialised,
heuristic gates serialised by the learner's own fit lock), one DAG <run>/dag.db (model evaluations, L0) and
one lesson memory <run>/memory.db, so weights, the heuristics book, evaluations and lessons carry from game
to game across streams.  Each stream has its own model service (at most `llm_workers` sessions in flight)
and heuristic loop, kept across its segments; a segment is one arena run against one opponent.

Model availability: before every decision a game waits (at most wait_for_model_h hours) while its service
is paused for a rate / usage limit, so no search runs without model input; while such a wait has more than
hold_after_s (600) left, the segment's arena run is paused through the admin API (the arena counts no idle
time while a run is paused) and made active again before the search; a run found paused when a segment
(re)starts is made active.  The arenas' MOVE_TIMEOUT should still exceed the search time plus any short wait.  Budget: before every decision and every new game the driver sums the cost of all sessions logged
in <run>/*/llm-jobs.jsonl; at max_cost_usd - stop_margin_usd every stream stops (an unfinished game stays
active in its arena), and no new game starts with less than game_reserve_usd left.  <run>/control.json
(optional, re-read at every check) overrides those keys and can stop the run: {"stop": true, "reason": ".."}.

Files: <run>/plan.json (copy), driver.log; per stream <run>/<S>/: log.txt, llm-jobs.jsonl, heuristics.jsonl,
jobs/, bin/; per segment <run>/<S>/<NN>-<arena>-<opponent>/: config.json, moves.jsonl (one line per decision:
label, rule, model input, wait, session counters and cost), arena.json (run id, no token), agent.token (600),
game<N>-tree.{npz,json}.  A restart resumes everything (arena runs by id, active games and saved trees,
the learner, the DAG).  When every stream has ended (done or stopped by the budget), the teardown commands
run.  KataGo is only the opponent, referee and reviewer: nothing it computes reaches a search, a prompt,
the memory or the learner.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

M47 = Path(__file__).resolve().parent.parent
for p in (str(M47), str(M47 / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from ablation_play import SerialLearner, _logger  # noqa: E402
from harness.arena_client import ArenaClient  # noqa: E402
from mcts import play as P  # noqa: E402
from mcts.cli import _run_dir  # noqa: E402

BUDGET_KEYS = ("max_cost_usd", "stop_margin_usd", "game_reserve_usd")


def play_namespace(seg_dir: Path, opponent: str, plan: dict, seed: int, root: Path) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    P.add_parsers(ap.add_subparsers())
    argv = ["play", "--run", str(seg_dir), "--opponent", opponent, "--llm", "on", "--learn", "--heuristics",
            "--worker", plan["worker"], "--wrap", plan.get("wrap", ""), "--llm-workers", str(plan["llm_workers"]),
            "--time-per-move", str(plan["time_per_move"]), "--threads", str(plan["threads"]),
            "--seed", str(seed), "--save-every", str(plan.get("save_every", 5)), "--max-load-frac", "0",
            "--dag", str(root / "dag.db"), "--memory", str(root / "memory.db"), "--hl-dir", str(root / "hl"),
            "--wait-for-model", str(plan.get("wait_for_model_h", 6.0)), "--drain", str(plan.get("drain_s", 1200)),
            *plan.get("play_args", [])]
    return ap.parse_args(argv)


def session_cost(root: Path) -> float:
    """USD of every session logged by the run's model services (<run>/<stream>/llm-jobs.jsonl)."""
    total = 0.0
    for f in sorted(root.glob("*/llm-jobs.jsonl")):
        for ln in f.read_text().splitlines():
            try:
                total += float(((json.loads(ln).get("usage") or {}).get("cost_usd")) or 0.0)
            except (ValueError, TypeError, AttributeError):
                pass
    return total


class Budget:
    """The run's spending limit, checked before every decision and every new game (all streams)."""

    def __init__(self, root: Path, plan: dict, log):
        self.root, self.plan, self.log = root, plan, log
        self._said: Optional[str] = None

    def limits(self) -> dict:
        lim = {"max_cost_usd": 3000.0, "stop_margin_usd": 40.0, "game_reserve_usd": 0.0, **(self.plan.get("budget") or {})}
        try:
            ctl = json.loads((self.root / "control.json").read_text())
        except (OSError, ValueError):
            ctl = {}
        lim.update({k: ctl[k] for k in (*BUDGET_KEYS, "stop", "reason") if k in ctl})
        return lim

    def check(self, new_game: bool) -> Optional[str]:
        lim = self.limits()
        why = None
        if lim.get("stop"):
            why = f"stop requested in control.json ({lim.get('reason') or 'no reason given'})"
        else:
            spent, cap = session_cost(self.root), float(lim["max_cost_usd"])
            if spent >= cap - float(lim["stop_margin_usd"]):
                why = f"budget: {spent:.2f} USD spent, cap {cap:.0f} USD (stop margin {float(lim['stop_margin_usd']):.0f})"
            elif new_game and spent > cap - float(lim["game_reserve_usd"]):
                why = (f"budget: {spent:.2f} USD spent; a new game needs {float(lim['game_reserve_usd']):.0f} USD "
                       f"of the {cap:.0f} USD cap")
        if why and why != self._said:
            self._said = why
            self.log(why)
        return why


def ensure_run(seg_dir: Path, arena: dict, seg: dict, stream: str, plan: dict) -> tuple[str, str]:
    """(run id, agent token) of the segment's arena run; created on first use."""
    meta_f, tok_f = seg_dir / "arena.json", seg_dir / "agent.token"
    if meta_f.exists() and tok_f.exists():
        return json.loads(meta_f.read_text())["run_id"], tok_f.read_text().strip()
    admin = (Path(arena["dir"]) / "admin.token").read_text().strip()
    name = plan.get("name", "MCTS v2 + model + HL (full system)") + f" / {stream} {seg['opponent']}"
    out = ArenaClient(arena["url"], admin_token=admin).create_run(
        name=name, model=plan.get("model_label", ""), harness="mcts", reasoning=plan.get("reasoning_label", ""),
        context="", notes=f"full system: model on, --learn --heuristics, {plan['time_per_move']}s/move, "
                          f"{plan['threads']} threads, W={plan['llm_workers']}, shared learner; stream {stream}",
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


def arena_hold(arena: dict, run_id: str, log):
    """hold(True) pauses the segment's arena run (the arena then counts no idle time against the agent),
    hold(False) makes it active again; errors are logged, never raised (a move sent to a paused run is
    retried by the play loop)."""
    def hold(on: bool) -> None:
        status = "paused" if on else "active"
        try:
            admin = (Path(arena["dir"]) / "admin.token").read_text().strip()
            r = ArenaClient(arena["url"], admin_token=admin).set_status(run_id, status)
            log(f"arena run {run_id} set {status}" + ("" if r.get("ok") else f": {r.get('error')}"))
        except Exception as e:
            log(f"arena run {run_id}: could not set {status} ({e!r})")
    return hold


def resume_if_paused(client, hold, log) -> bool:
    """A run paused from outside (e.g. by an operator while the driver was down) is made active again."""
    st = client.status()
    if (st.get("summary") or {}).get("status") == "paused":
        log("the arena run is paused; resuming it")
        hold(False)
        return True
    return False


def play_segment(root: Path, sdir: Path, stream: str, idx: int, seg: dict, plan: dict, learner, svc, heur,
                 last_stats, budget: Budget, log, dlog) -> tuple[list, Optional[dict]]:
    arena = plan["arenas"][seg["arena"]]
    seg_dir = sdir / f"{idx:02d}-{seg['arena']}-{seg['opponent']}"
    seg_dir.mkdir(parents=True, exist_ok=True)
    a = play_namespace(seg_dir, seg["opponent"], plan, plan.get("seed", 0) * 100 + ord(stream[0]) + idx, root)
    cfg, dcfg = P._engine_config(a), P._decide_config(a)
    run_id, token = ensure_run(seg_dir, arena, seg, stream, plan)
    P._write_config(seg_dir, a, cfg, svc, a.threads)

    def slog(msg: str) -> None:
        log(f"{idx:02d}/{seg['opponent']}: {msg}")
    slog(f"segment {idx}: {seg['games']} game(s) vs {seg['opponent']} on {arena['url']} (run {run_id}), "
         f"{a.time_per_move}s/move, {a.threads} threads, W={svc.cfg.workers}, learner at "
         f"{learner.current_weights().version}; spent so far {session_cost(root):.2f} USD; load {os.getloadavg()[0]:.0f}")
    player = P.Player(seg_dir, cfg, a.time_per_move, a.threads, a.sims, learner.provider, learner, svc,
                      a.save_every, slog, decide_cfg=dcfg, label_prefix=f"{stream}{idx}")
    player._last_stats = last_stats              # per-decision session counters continue across segments
    client = ArenaClient(arena["url"], token)
    hold = arena_hold(arena, run_id, slog)
    for attempt in range(1, int(plan.get("retries", 5)) + 1):
        try:
            resume_if_paused(client, hold, slog)
            res = P.play_games(client, seg["opponent"], int(seg["games"]), player, seg.get("color"),
                               record=seg_dir / "moves.jsonl", abstract=True, log=slog, heuristics=heur,
                               wait_for_model_s=a.wait_for_model * 3600, should_stop=budget.check,
                               hold=hold, hold_after_s=float(plan.get("hold_after_s", 600)))
            last = player._last_stats
            player.close()
            if any(r.get("stopped") for r in res):
                return res, last
            st = client.status().get("summary") or {}
            if st.get("games_played", 0) >= st.get("target_games", 1):
                return res, last
            slog(f"play_games returned with {st.get('games_played')}/{st.get('target_games')} games; again")
        except Exception as e:  # resumable: the arena keeps the game, the tree its file, the learner its directory
            last_stats = player._last_stats
            player.close()
            player._last_stats = last_stats
            slog(f"segment error (attempt {attempt}): {e!r}\n{traceback.format_exc()}")
            dlog(f"stream {stream} segment {idx} error {e!r}; retrying in 60s")
            time.sleep(60)
    raise RuntimeError(f"stream {stream} segment {idx}: gave up")


def run_stream(root: Path, name: str, segs: list, plan: dict, learner, budget: Budget, printlock, dlog) -> dict:
    sdir = root / name
    sdir.mkdir(parents=True, exist_ok=True)
    log = _logger(sdir / "log.txt", f"[{name}]", printlock)
    a0 = play_namespace(sdir, segs[0]["opponent"], plan, plan.get("seed", 0) * 100 + ord(name[0]), root)
    svc = P.build_service(a0, sdir, log, learner).start()
    heur = P._heuristics(a0, learner, svc, sdir, log)
    out: dict = {"segments": [], "stopped": None}
    last = None
    try:
        for i, seg in enumerate(segs):
            res, last = play_segment(root, sdir, name, i, seg, plan, learner, svc, heur, last, budget, log, dlog)
            out["segments"].append(res)
            dlog(f"stream {name} segment {i} ended: {json.dumps(res)}")
            stop = next((r["stopped"] for r in res if r.get("stopped")), None)
            if stop:
                out["stopped"] = stop
                break
    finally:
        # the last decisions' heuristic and lessons jobs still run; nothing else is started
        svc.drop_queued(keep=("heuristic", "abstract"))
        t_end = time.time() + a0.drain
        while time.time() < t_end and (svc.stats()["queue"] or svc.stats()["running"]):
            time.sleep(2.0)
        svc.close(wait_s=a0.drain)
        out["llm"] = svc.stats()
        log(f"llm totals: {json.dumps(out['llm'])}")
        if heur is not None:
            heur.close(wait_s=max(600.0, a0.drain))
            out["heuristics"] = heur.stats()
            log(f"heuristics: {json.dumps(out['heuristics'])}")
    return out


def teardown(cmds: list, dlog) -> None:
    for c in cmds or []:
        try:
            p = subprocess.run(c, capture_output=True, text=True, timeout=600)
            dlog(f"teardown {' '.join(c)}: rc {p.returncode}\n{(p.stdout + p.stderr)[-2000:]}")
        except Exception as e:
            dlog(f"teardown {' '.join(c)} failed: {e!r}")


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
                ns = play_namespace(run / s / f"{i:02d}", seg["opponent"], plan, 0, run)
                cfg, dc = P._engine_config(ns), P._decide_config(ns)
                print(json.dumps({"stream": s, "segment": i, **seg, "time_per_move": ns.time_per_move,
                                  "threads": ns.threads, "llm": ns.llm, "llm_workers": ns.llm_workers,
                                  "learn": ns.learn, "heuristics": ns.heuristics, "hl": P._hl_opts(ns),
                                  "root_noise": cfg.root_noise, "n_thr": cfg.n_thr, "max_nodes": cfg.max_nodes,
                                  "decide": dc.rule, "decide_extend": dc.extend_s, "wait_for_model_h": ns.wait_for_model,
                                  "save_every": ns.save_every, "dag": ns.dag, "hl_dir": ns.hl_dir}))
        print(f"search threads in all: {total}; model sessions in flight at most: "
              f"{len(plan['streams']) * int(plan['llm_workers'])}; budget {json.dumps(plan.get('budget'))}")
        return 0
    a0 = play_namespace(run, "-", plan, 0, run)
    learner = SerialLearner(P.make_learner(run, None, dlog, a0.hl_dir, P._hl_opts(a0), hybrid=True))
    budget = Budget(run, plan, dlog)
    w = learner.current_weights()
    dlog(f"start: {len(plan['streams'])} streams x {plan['threads']} threads = {total} search threads, "
         f"W={plan['llm_workers']} per stream, {plan['time_per_move']}s/move; learner {learner.run_dir} at {w.version} "
         f"({len(w.rules)} book rules); spent so far {session_cost(run):.2f} USD of {budget.limits()['max_cost_usd']}; "
         f"load {os.getloadavg()[0]:.0f}")
    errors: dict = {}
    outs: dict = {}

    def stream_main(name: str, segs: list) -> None:
        try:
            outs[name] = run_stream(run, name, segs, plan, learner, budget, printlock, dlog)
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
    learner.close()
    w = learner.current_weights()
    dlog(f"done; learner at {w.version} ({len(w.rules)} book rules) after {learner.updates} updates "
         f"({learner.accepted} accepted); spent {session_cost(run):.2f} USD; stopped: "
         f"{ {k: v.get('stopped') for k, v in outs.items()} }; errors {errors or 'none'}")
    if not errors:
        teardown(plan.get("teardown"), dlog)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
