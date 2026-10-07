"""Arena play loop for MCTS v2 with asynchronous LLM expansion (node move47::mcts-llm).

    python3 -m mcts play --arena URL --token T --opponent k1-full --games 1 --run <dir outside Chandra> \
        --worker claude:claude-opus-5-5:xhigh --wrap '<move47>/bin/worker-sandbox {jobdir}' \
        --time-per-move 1800 --threads 32 --llm-workers 16 [--learn] [--llm off]
    python3 -m mcts llm-search --sgf game.sgf --upto 20 --run <dir> --worker ... --time 300 --llm-workers 8

One tree per game: after our move and the opponent's reply the engine advances twice (never
reset), so the new root keeps its subtree and statistics; a move list that does not continue the
tree's (resync, another process played) jumps with set_root() and still keeps the tree.  The
decision is the most-visited root move.  The LLM service (mcts/llm.py) evaluates nodes
asynchronously; after each decision an `abstract` job distils lessons (v1 style, with the moves
whose LLM prior disagreed with the final visits as surprises).  Board fetching and move submission
reuse gotree.play (engine outages, resyncs, transport errors).  Per-move JSONL record; the tree is
saved every --save-every decisions and a restarted process resumes the game from it.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from gotree.play import BACKOFF, MAX_WAIT, _call, current_board, play_decision
from gotree.position import IllegalMove

from .arena import board_from_arena
from .tree import MCTS, MCTSConfig

GAUGES = ("queue", "running", "inbox", "w_cur", "paused_s")


class Player:
    """The engine of the current game, kept in step with the arena's move list."""

    def __init__(self, run_dir: Path, config: MCTSConfig, time_s: Optional[float], threads: int,
                 sims: Optional[int] = None, weights=None, learner=None, service=None, save_every: int = 5,
                 log: Callable[[str], None] = print):
        self.run_dir = Path(run_dir)
        self.cfg, self.time_s, self.threads, self.sims = config, time_s, threads, sims
        self.weights, self.learner, self.service = weights, learner, service
        self.save_every, self.log = save_every, log
        self.eng: Optional[MCTS] = None
        self.known: list = []                 # arena moves (points) the tree's root has followed
        self.game_no: Optional[int] = None
        self.decisions = 0                    # in this process, this game
        self._last_stats: Optional[dict] = None

    # ------------------------------------------------------------ files
    def tree_path(self, game_no: int) -> Path:
        return self.run_dir / f"game{game_no}-tree.npz"

    def side_path(self, game_no: int) -> Path:
        return self.run_dir / f"game{game_no}-tree.json"

    # ------------------------------------------------------------ game lifecycle
    def _attach(self, eng: MCTS) -> None:
        self.eng = eng
        if self.service is not None:
            self.service.attach(eng)

    def close(self) -> None:
        if self.service is not None:
            self.service.detach()
        if self.eng is not None:
            self.eng.close()
        self.eng, self.known = None, []

    def start_game(self, game_no: int) -> str:
        """Resume the saved tree of game `game_no` if there is one, else start empty."""
        self.close()
        self.game_no, self.decisions = game_no, 0
        tp, sp = self.tree_path(game_no), self.side_path(game_no)
        if tp.exists() and sp.exists():
            try:
                side = json.loads(sp.read_text())
                if not side.get("finished"):
                    eng = MCTS.load(tp, config=copy.deepcopy(self.cfg), weights=self.weights, learner=self.learner)
                    self.known = list(side["known"])
                    self._attach(eng)
                    self.log(f"  resumed the tree of game {game_no}: {eng.n_nodes} nodes, root after "
                             f"{len(self.known)} moves, root visits {int(eng.a.n[eng.root])}")
                    return "resumed"
            except Exception as e:  # a corrupt or incompatible file: start over
                self.log(f"  cannot resume {tp.name} ({e!r}); starting a new tree")
                self.close()
        return "new"

    def sync(self, resp: dict, komi: float) -> str:
        b, hist, pts = board_from_arena(resp, komi)
        if self.eng is None:
            self._attach(MCTS(b, history=hist, config=copy.deepcopy(self.cfg), weights=self.weights,
                              learner=self.learner))
            self.known = pts
            return "new"
        how = "set_root"
        if pts[:len(self.known)] == self.known:
            try:
                for p in pts[len(self.known):]:
                    self.eng.advance(p)
                if self.eng.root_board.key == b.key:
                    how = "advanced"
            except IllegalMove:
                pass
        if how != "advanced":
            self.eng.set_root(b, hist)
        self.known = pts
        if self.service is not None:
            self.service.new_root(label=f"g{self.game_no}p{len(pts) + 1}")
        return how

    def decide(self) -> dict:
        eng, svc = self.eng, self.service
        n0 = int(eng.a.n[eng.root])
        stop = None
        if svc is not None:
            def stop() -> bool:
                svc.tick()
                return False
            svc.searching = True
        try:
            r = eng.search(time_s=self.time_s, sims=self.sims, threads=self.threads, stop=stop)
        finally:
            if svc is not None:
                svc.searching = False
        self.decisions += 1
        r["root_n_start"] = n0
        r["decision"] = {"real": r["best"] or "pass"}
        r["candidates"] = [{"real": m["coord"], "n": m["n"]} for m in r["moves"]]
        return r

    def llm_delta(self) -> Optional[dict]:
        """LLM service counters since the previous call (jobs, cache hits, cost ...) and its gauges."""
        if self.service is None:
            return None
        now = self.service.stats()
        prev = self._last_stats or {k: 0 for k in now}
        self._last_stats = now
        out = {k: (now[k] if k in GAUGES else round(now[k] - prev.get(k, 0), 4)) for k in now}
        out["total_cost_usd"] = now["cost_usd"]
        return out

    def maybe_save(self, force: bool = False) -> Optional[float]:
        if self.eng is None or (not force and (not self.save_every or self.decisions % self.save_every)):
            return None
        t0 = time.time()
        self.eng.save(self.tree_path(self.game_no))
        side = {"game": self.game_no, "known": self.known, "nodes": self.eng.n_nodes, "saved_at": time.time(),
                "finished": False}
        tmp = self.side_path(self.game_no).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(side))
        os.replace(tmp, self.side_path(self.game_no))
        dt = time.time() - t0
        self.log(f"  saved the tree ({self.eng.n_nodes} nodes) in {dt:.1f}s")
        return dt

    def end_game(self, result: dict) -> None:
        sp = self.side_path(self.game_no)
        if sp.exists():
            side = json.loads(sp.read_text())
            side.update(finished=True, result=result)
            sp.write_text(json.dumps(side))
        self.close()


def root_table(summ: dict, llm_priors: Optional[dict], top: int = 10) -> list[dict]:
    out = []
    for m in summ["moves"][:top]:
        row = {"move": m["coord"], "n": m["n"], "q": None if m["q"] is None else round(m["q"], 4),
               "prior": round(m["prior"], 4), "prior_learned": round(m["prior_learned"], 4), "pv": m["pv"][:6]}
        if llm_priors is not None:
            p = llm_priors.get(m["move"])
            row["llm_prior"] = None if p is None else round(p, 4)
        out.append(row)
    return out


def _status(client, log, sleep, max_wait: float = MAX_WAIT) -> dict:
    delay, waited = BACKOFF[0], 0.0
    while True:
        st = _call(client.status)
        if st.get("ok"):
            return st
        if (st.get("error") or {}).get("code") != "transport" or waited >= max_wait:
            raise RuntimeError(f"arena status failed: {st.get('error')}")
        log(f"  arena unreachable ({st['error']['message']}); retrying in {delay:.0f}s")
        sleep(delay)
        waited += delay
        delay = min(delay * 2, BACKOFF[1])


def play_games(client, opponent: str, games: int, player: Player, color: Optional[str] = None,
               record: Optional[Path] = None, abstract: bool = True, log: Callable[[str], None] = print,
               sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    svc, learner = player.service, player.learner
    results = []
    for _ in range(games):
        st = _status(client, log, sleep)
        s = st["summary"]
        if s["games_played"] >= s["target_games"]:
            log("run complete")
            break
        if st.get("active_game"):
            r = current_board(client, st["active_game"]["game_no"], log, sleep)
        else:
            r = _call(client.new_game, opponent, color)
            if not r.get("game"):  # e.g. 503 while the opponent's first move (we are White) was pending
                ag = _call(client.status).get("active_game")
                if not ag:
                    raise RuntimeError(r)
                r = current_board(client, ag["game_no"], log, sleep)
        komi, game_no, ours = r["game"]["komi"], r["game"]["game_no"], r["game"]["agent_color"]
        how0 = player.start_game(game_no)
        log(f"game #{game_no} vs {r['game']['opponent']} as {ours} ({how0})")
        first = True
        while not r.get("game_over"):
            before = list(r.get("moves") or [])
            t0 = time.time()
            how = player.sync(r, komi)
            if first and how0 == "resumed":
                how = f"resumed+{how}"
            first = False
            ply = len(before) + 1
            summ = player.decide()
            mv = summ["decision"]["real"]
            llm_root = None
            if svc is not None:
                lp = svc.root_llm_priors()
                llm_root = {"evaluated": bool(lp), "value": svc.root_value(), "moves": len(lp)}
            else:
                lp = None
            if svc is not None and abstract:
                svc.request_abstract(summ["moves"], summ["best_move"], summ["q"], summ["root_n"],
                                     label=f"g{game_no}p{ply}")
            rec = {"game": game_no, "ply": ply, "color": "B" if summ["to_play"] == "X" else "W", "move": mv,
                   "sync": how, "time_s": round(summ["time_s"], 2), "sims": summ["sims"],
                   "sims_per_s": round(summ["sims_per_s"]), "nodes": summ["nodes"], "root_n": summ["root_n"],
                   "root_n_start": summ["root_n_start"], "q": summ["q"], "depth_mean": round(summ["depth_mean"], 1),
                   "stop_reason": summ["stop_reason"], "gc_rounds": summ["gc_rounds"], "weights": summ["weights"],
                   "root_table": root_table(summ, lp), "llm_root": llm_root, "llm": player.llm_delta()}
            ll = rec["llm"]
            log(f"  move {ply}: {mv} ({how}) {summ['sims']} sims in {summ['time_s']:.0f}s, root_n {summ['root_n']} "
                f"(start {summ['root_n_start']}), q {summ['q']:.3f}, {summ['nodes']} nodes"
                + (f"; llm jobs {ll['launched']:.0f} ok {ll['ok']:.0f} failed {ll['failed']:.0f} cached "
                   f"{ll['cache_hits']:.0f} applied {ll['applied']:.0f}, ${ll['cost_usd']:.2f} "
                   f"(total ${ll['total_cost_usd']:.2f}), queue {ll['queue']} running {ll['running']}" if ll else ""))
            r = play_decision(client, summ, before, game_no, log, sleep)
            if learner is not None:
                try:
                    learner.update()
                except Exception as e:
                    log(f"  learner.update failed: {e!r}")
            rec["seconds"] = round(time.time() - t0, 2)
            dt = player.maybe_save()
            rec["save_s"] = None if dt is None else round(dt, 2)
            if record:
                with open(record, "a") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
        res = r["result"]
        log(f"  result: {res.get('result')} ({res.get('winner')}, {res.get('end_reason')})")
        if learner is not None and hasattr(learner, "observe_game"):
            try:
                learner.observe_game(res.get("result"), ours)
            except Exception as e:
                log(f"  learner.observe_game failed: {e!r}")
        player.end_game(res)
        results.append({"game": game_no, **res})
    return results


# ================================================================ command line
def _logger(run: Path) -> Callable[[str], None]:
    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(run / "log.txt", "a") as f:
            f.write(line + "\n")
    return log


def check_threads(threads: int, frac: float, log: Callable[[str], None]) -> int:
    """Cap the search threads so that the host stays under `frac` of its hardware threads."""
    if frac <= 0:
        return threads
    ncpu = os.cpu_count() or 1
    load = os.getloadavg()[0]
    room = int(frac * ncpu - load)
    if threads > room:
        log(f"host load {load:.0f} of {ncpu} threads: {threads} search threads would exceed {frac:.0%}; "
            f"using {max(1, room)}")
        return max(1, room)
    return threads


def make_learner(run: Path, weights, log):
    try:
        from .hl import OnlineLearner
    except ImportError as e:
        sys.exit(f"--learn needs mcts.hl.OnlineLearner (node move47::mcts-hl), which cannot be imported: {e}")
    import inspect
    try:
        params = inspect.signature(OnlineLearner).parameters
    except (TypeError, ValueError):
        params = {}
    cand = {"run_dir": run / "hl", "base": weights}      # OnlineLearner(run_dir, base=None, **cfg)
    learner = OnlineLearner(**{k: v for k, v in cand.items() if k in params and v is not None})
    for m in ("observe", "update", "provider"):
        if not hasattr(learner, m):
            sys.exit(f"mcts.hl.OnlineLearner has no {m!r}; --learn expects observe, observe_external, "
                     f"observe_game, update and provider")
    return learner


def _llm_config(a):
    from .llm import LLMConfig
    cfg = LLMConfig(workers=a.llm_workers, job_timeout=a.job_timeout, max_jobs=a.max_llm_jobs)
    for kv in a.llm_set or []:
        k, _, v = kv.partition("=")
        if not hasattr(cfg, k):
            sys.exit(f"unknown LLM config key {k!r}")
        cur = getattr(cfg, k)
        setattr(cfg, k, (v.lower() in ("1", "true", "yes")) if isinstance(cur, bool) else type(cur)(v))
    return cfg


def build_service(a, run: Path, log, learner=None):
    """The LLM service of a run: DAG and memory (default in the run dir), the worker, the config."""
    from gotree.dag import DAG
    from gotree.memory import Memory
    from gotree.workers import make_worker
    from .llm import LLMService
    dag_path = str(Path(a.dag).resolve()) if a.dag else str(run / "dag.db")
    mem_path = str(Path(a.memory).resolve()) if a.memory else str(run / "memory.db")
    dag, mem = DAG(dag_path), Memory(mem_path)
    cfg = _llm_config(a)
    worker = make_worker(a.worker, run_dir=run, dag_path=dag_path, mem_path=mem_path, memory=mem, seed=a.seed,
                         timeout=cfg.job_timeout, wrap=a.wrap, clean=a.claude_clean,
                         claude_args=shlex.split(a.claude_args))
    return LLMService(worker, dag, mem, cfg, learner=learner, log=log, record=run / "llm-jobs.jsonl",
                      jobs_dir=run / "jobs")


def _engine_config(a) -> MCTSConfig:
    from .cli import _config
    cfg = _config(a)
    if a.n_thr and not any(kv.startswith("n_thr=") for kv in (a.set or [])):
        cfg.n_thr = a.n_thr
    return cfg


def _write_config(run: Path, a, cfg: MCTSConfig, svc, threads: int) -> None:
    from dataclasses import asdict
    (run / "config.json").write_text(json.dumps({
        "argv": sys.argv, "engine": asdict(cfg), "threads": threads,
        "llm": None if svc is None else asdict(svc.cfg), "worker": None if svc is None else svc.worker.name,
        "started": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1, default=str))


def cmd_play(a) -> int:
    from harness.arena_client import ArenaClient
    from .cli import _run_dir
    token = a.token or os.environ.get("GOARENA_TOKEN", "")
    if not token:
        sys.exit("--token / GOARENA_TOKEN required")
    run = _run_dir(a.run)
    log = _logger(run)
    cfg = _engine_config(a)
    threads = check_threads(a.threads, a.max_load_frac, log)
    learner, weights = None, a.weights
    if a.learn:
        learner = make_learner(run, weights, log)
        weights = learner.provider
    svc = None
    if a.llm == "on":
        svc = build_service(a, run, log, learner).start()
    _write_config(run, a, cfg, svc, threads)
    log(f"mcts play: {a.games} game(s) vs {a.opponent}, {a.time_per_move}s/move, {threads} threads, "
        f"llm {'off' if svc is None else f'{svc.worker.name} W={svc.cfg.workers}'}"
        f"{', learning' if learner else ''}; run {run}")
    player = Player(run, cfg, a.time_per_move, threads, a.sims, weights, learner, svc, a.save_every, log)
    try:
        res = play_games(ArenaClient(a.arena, token), a.opponent, a.games, player, a.color,
                         record=run / "moves.jsonl", abstract=not a.no_abstract, log=log)
    finally:
        if svc is not None:
            svc.close(wait_s=a.drain)
            log(f"llm totals: {json.dumps(svc.stats())}")
    print(json.dumps(res))
    return 0


def cmd_llm_search(a) -> int:
    """One position: code-only warm-up, then search with the LLM service; root tables over time."""
    from .board import board_from_sgf
    from .cli import _run_dir
    run = _run_dir(a.run)
    log = _logger(run)
    cfg = _engine_config(a)
    threads = check_threads(a.threads, a.max_load_frac, log)
    b, hist, moves = board_from_sgf(Path(a.sgf).read_text(), a.upto)
    svc = build_service(a, run, log)
    _write_config(run, a, cfg, svc, threads)
    eng = MCTS(b, history=hist, config=cfg, weights=a.weights)
    svc.attach(eng)
    log(f"llm-search: {Path(a.sgf).name} after {len(moves)} moves, {b.to_play} to play; warm-up {a.warmup}s code "
        f"only, then {a.time}s with {svc.worker.name}, W={svc.cfg.workers}, at most {svc.cfg.max_jobs or 'any'} "
        f"sessions, n_thr {cfg.n_thr}, {threads} threads")
    t_start = time.time()
    out: dict = {"sgf": str(a.sgf), "upto": len(moves), "to_play": b.to_play, "threads": threads,
                 "worker": svc.worker.name, "llm": svc.cfg.__dict__, "n_thr": cfg.n_thr, "snapshots": []}
    r0 = eng.search(time_s=a.warmup, threads=threads) if a.warmup > 0 else None
    out["before"] = {"sims": r0["sims"] if r0 else 0, "root_n": int(eng.a.n[eng.root]), "q": r0["q"] if r0 else None,
                     "table": eng.root_stats(a.top)}
    log("root table before LLM input (code-only warm-up):\n" + eng.table(a.top))
    svc.start()
    t0 = time.time()
    last = [t0]

    def snapshot(tag: str) -> None:
        st = svc.stats()
        lp = svc.root_llm_priors()
        rows = eng.root_stats(6)
        snap = {"t": round(time.time() - t0, 1), "tag": tag, "root_n": int(eng.a.n[eng.root]),
                "llm": st, "llm_root_moves": len(lp),
                "top": [{"move": m["coord"], "n": m["n"], "q": m["q"], "prior": round(m["prior"], 4),
                         "prior_learned": round(m["prior_learned"], 4),
                         "llm_prior": None if lp.get(m["move"]) is None else round(lp[m["move"]], 4)} for m in rows]}
        out["snapshots"].append(snap)
        log(f"[{snap['t']:.0f}s] root_n {snap['root_n']}; llm events {st['events']:.0f} queued {st['queue']} running "
            f"{st['running']} launched {st['launched']:.0f} ok {st['ok']:.0f} failed {st['failed']:.0f} cached "
            f"{st['cache_hits']:.0f} applied {st['applied']:.0f} (mid-search {st['applied_mid_search']:.0f}) "
            f"${st['cost_usd']:.2f}; top: " + ", ".join(
                f"{m['move']} n={m['n']} q={'-' if m['q'] is None else round(m['q'], 3)} p={m['prior']:.3f}"
                f"/{m['prior_learned']:.3f}" + ("" if m["llm_prior"] is None else f" llm={m['llm_prior']:.2f}")
                for m in snap["top"]))

    def stop() -> bool:
        svc.tick()
        if time.time() - last[0] >= a.snapshot_every:
            last[0] = time.time()
            snapshot("search")
        return False

    svc.searching = True
    r = eng.search(time_s=a.time, threads=threads, stop=stop)
    t_end = time.time()
    while svc.stats()["running"] and time.time() - t_end < a.drain:   # sessions still in flight: keep searching
        r = eng.search(time_s=min(30.0, a.drain), threads=threads, stop=stop)
    svc.searching = False
    snapshot("final")
    svc.close(wait_s=0)
    out["after"] = {"sims": r["sims"], "root_n": int(eng.a.n[eng.root]), "q": r["q"], "best": r["best"],
                    "table": eng.root_stats(a.top), "llm_priors_root": {
                        (m if m is None else eng.root_board.coord(m)): p for m, p in svc.root_llm_priors().items()}}
    out["llm_totals"] = svc.stats()
    out["seconds"] = round(time.time() - t_start, 1)
    jobs_f = run / "llm-jobs.jsonl"
    out["jobs"] = [json.loads(x) for x in jobs_f.read_text().splitlines()] if jobs_f.exists() else []
    log("root table after LLM input:\n" + eng.table(a.top))
    log(f"llm totals: {json.dumps(out['llm_totals'])}; {out['seconds']}s")
    (run / "llm-search.json").write_text(json.dumps(out, indent=1, default=str))
    eng.close()
    return 0


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--run", required=True, help="run directory (outside the Chandra tree): DAG, memory, jobs, logs")
    p.add_argument("--worker", default="mock", help="worker spec, e.g. claude:claude-opus-5-5:xhigh (gotree specs)")
    p.add_argument("--wrap", default="", help="prefix for CLI workers, e.g. '<move47>/bin/worker-sandbox {jobdir}'")
    p.add_argument("--job-timeout", type=float, default=900.0)
    p.add_argument("--llm-workers", type=int, default=16, help="W: LLM sessions in flight at most")
    p.add_argument("--max-llm-jobs", type=int, default=0, help="LLM sessions in total (0 = no cap)")
    p.add_argument("--llm-set", action="append", metavar="KEY=VALUE", help="LLMConfig field (mcts/llm.py)")
    p.add_argument("--dag", default="", help="DAG (L0) file; default <run>/dag.db (share it to reuse evaluations)")
    p.add_argument("--memory", default="", help="lesson memory file; default <run>/memory.db")
    p.add_argument("--no-claude-clean", dest="claude_clean", action="store_false")
    p.add_argument("--claude-args", default="", metavar="ARGS")
    p.add_argument("--n-thr", type=int, default=100_000,
                   help="visits at which a node is queued for an LLM expand job (root and children always)")
    p.add_argument("--threads", type=int, default=32)
    p.add_argument("--max-load-frac", type=float, default=0.7,
                   help="cap the threads so the host stays under this share of its threads (0 = no check)")
    p.add_argument("--weights", default=None, help="weight file (default: mcts/weights/default-v1.json)")
    p.add_argument("--max-nodes", type=int, default=0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--set", action="append", metavar="KEY=VALUE", help="MCTSConfig field")
    p.add_argument("--drain", type=float, default=0.0,
                   help="at the end, wait up to this many seconds for LLM sessions in flight")


def add_parsers(sub) -> None:
    p = sub.add_parser("play", help="arena games with MCTS v2 + asynchronous LLM expansion, one tree per game")
    p.add_argument("--arena", default=os.environ.get("GOARENA_URL", "http://127.0.0.1:8765"))
    p.add_argument("--token", default="", help="agent token (default: $GOARENA_TOKEN)")
    p.add_argument("--opponent", required=True)
    p.add_argument("--games", type=int, default=1)
    p.add_argument("--color", default=None, choices=[None, "B", "W"])
    p.add_argument("--time-per-move", type=float, default=1800.0)
    p.add_argument("--sims", type=int, default=None, help="simulations per move (with or instead of the time)")
    p.add_argument("--llm", default="on", choices=["on", "off"], help="off: code-only ablation")
    p.add_argument("--learn", action="store_true", help="online learning with mcts.hl.OnlineLearner")
    p.add_argument("--no-abstract", action="store_true", help="no lessons job after each decision")
    p.add_argument("--save-every", type=int, default=5, help="save the tree every N decisions (0 = never)")
    _common(p)
    p.set_defaults(fn=cmd_play)

    p = sub.add_parser("llm-search", help="search one SGF position with the LLM service; root tables over time")
    p.add_argument("--sgf", required=True)
    p.add_argument("--upto", type=int, default=None)
    p.add_argument("--time", type=float, default=300.0, help="seconds of search with the LLM service")
    p.add_argument("--warmup", type=float, default=20.0, help="seconds of code-only search first")
    p.add_argument("--snapshot-every", type=float, default=30.0)
    p.add_argument("--top", type=int, default=10)
    _common(p)
    p.set_defaults(fn=cmd_llm_search)


__all__ = ["Player", "play_games", "add_parsers", "check_threads", "root_table"]
