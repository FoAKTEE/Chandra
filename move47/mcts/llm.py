"""Asynchronous LLM expansion for the MCTS v2 engine (node move47::mcts-llm).

The engine's ``on_expand`` hook only appends the event to an inbox.  One dispatcher thread then

  1. triages each event: the node's canonical position and DAG key (gotree L0), dedup (one
     request per canonical position and kind; other engine nodes with the same canonical
     position, e.g. symmetric opening moves, follow it), the DAG cache (an evaluation the DAG
     already holds is applied at once, no model call), a queue cap;
  2. dispatches up to ``W`` concurrent worker sessions (gotree ``CLIWorker`` / ``MockWorker``),
     best first: the root's expand, then root breadth jobs (v1 regional scouts, a refute of the
     current top move) and lessons (``abstract``), then the root's children, then deeper nodes;
     within a class by the node's current visits.  Requests for nodes that left the root's
     subtree after ``advance`` are dropped;
  3. applies each validated result: written to the DAG exactly as gotree v1 writes it (edges with
     priors and sources, static value), mapped from the job's canonical frame back to the
     engine's real board frame, and passed to ``MCTS.set_external(priors, value, source="llm")``.
     The priors passed are the union of every LLM edge the DAG holds for the position, so later
     jobs (scouts, refutes) add to the node's external priors instead of replacing them.

Root breadth and re-asking (node move47::mcts-calib): the moves the model proposes at the root get
minimum visits in the engine (``MCTS.set_root_breadth``: "candidate" for llm / more edges,
"explore" for unconventional and scout edges); every few seconds the most-visited root moves
without a model value of their own get the top priority (``boost``), also at decision time
(mcts/decide.py); a request dropped by the queue cap or as stale re-arms its node's hook
(``MCTS.rearm``) once the queue has room and the node is in the root's subtree again
(``MCTS.in_subtree``, exact for any move order), so the node asks again on its next visit.

Failures (rate limits, overload, sessions that end without an answer, timeouts) are classified
from the JobResult and the session log; rate limits and overload pause dispatching with
exponential backoff and halve the number of concurrent sessions (raised again by one after
successes).  Nothing here raises into the search: the search never waits for the service.
"""
from __future__ import annotations

import inspect
import itertools
import json
import re
import threading
import time
import traceback
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable, Optional

from gotree import heuristics
from gotree.dag import DAG
from gotree.jobs import Job, describe_known
from gotree.memory import Memory
from gotree.position import Position, coord, point, sym_maps
from gotree.search import regions
from gotree.workers import JobResult, Worker, _cli_usage

from ._lib import EV_PATH_MAX
from .board import Board

FL_EXT = 2                                    # mcts.tree flag: external priors merged at the node
LLM_SOURCES = ("llm", "unconventional", "refute", "more", "scout")   # DAG edge sources that are LLM priors
EXPLORE_SOURCES = ("unconventional", "scout")   # root breadth class "explore"; other LLM sources: "candidate"
# priority classes (lower first); CLS_TOP: root moves the search ranks high that lack a model value
CLS_ROOT, CLS_TOP, CLS_BREADTH, CLS_CHILD, CLS_DEEP = 0, 1, 2, 3, 4
USAGE_KEYS = ("input", "output", "cache_read", "cache_write")

RATE_RE = re.compile(r"rate[_ -]?limit|\b429\b|too many requests|usage limit|limit reached|quota exceeded", re.I)
OVERLOAD_RE = re.compile(r"overloaded|\b529\b|\b503\b|service unavailable|api_error|internal server error", re.I)
RESET_RE = re.compile(r"limit reached\|(\d{10})")


@dataclass
class LLMConfig:
    workers: int = 16               # W: model sessions in flight at most
    min_workers: int = 1            # backoff never lowers W below this
    queue_cap: int = 256            # queued requests; beyond it the lowest priority is dropped
    inbox_cap: int = 50_000         # events not yet triaged (overflow is dropped and counted)
    job_timeout: float = 900.0      # per session (the caller builds the worker with it)
    max_jobs: int = 0               # model sessions in total, 0 = no cap
    k_root: int = 10                # v1 SearchConfig: candidates asked for at the root / elsewhere
    k_node: int = 6
    u_root: int = 4                 # v1: unconventional candidates at the root / elsewhere
    u_node: int = 1
    unconv_prior: float = 0.03      # v1: DAG prior of an unconventional candidate
    root_explore_prior: float = 0.0   # optional prior floor for unconventional / scout moves at the root
                                      # (mcts-llm's stand-in; superseded by root_breadth)
    root_breadth: bool = True       # root moves the model proposed get minimum visits in the engine
    boost_top: int = 3              # the most-visited root moves without a model value: top priority ...
    boost_every_s: float = 5.0      # ... re-checked this often (tick())
    child_min_share: float = 0.002  # a root child with less than this share of the root's visits ranks as deep
    rearm: bool = True              # re-arm the hooks of dropped requests once the queue has room
    rearm_every_s: float = 2.0
    boost_max_new: int = 2          # boost() creates a request for a position at most this often
    scouts: bool = True             # v1 regional scouts at every new root (v1 regions(): none below 13x13)
    scout_values: bool = False      # back up a scout's value too (it only looked at one region)
    refute: bool = True             # critic job on the current most-visited root move, once per root
    refute_after_s: float = 60.0    # ... after this much search at the root
    dispatch_delay_s: float = 2.0   # non-root requests wait this long after a new root, so that the
                                    # code search ranks the children before sessions are spent on them
    abstract: bool = True           # lessons job after each decision (needs an LLM evaluation at the root)
    cache: bool = True              # apply evaluations the DAG already holds (no model call)
    backoff_base: float = 30.0      # first pause after a rate limit / overload, doubled each time
    backoff_max: float = 1800.0
    backoff_reset_cap: float = 6 * 3600.0   # longest wait for a usage-limit reset time
    fail_streak_backoff: int = 3    # other failures in a row that are treated like an outage
    max_attempts: int = 2           # sessions per request for ordinary failures
    max_rl_attempts: int = 6        # ... and for rate-limited / overloaded attempts
    ramp_up_after: int = 2          # successes in a row before W grows by one again
    poll_s: float = 0.5

    @classmethod
    def from_dict(cls, d: dict) -> "LLMConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Target:
    """One engine node that wants the evaluation of a canonical position."""
    key: int                        # engine (Zobrist) node key
    board: Board                    # the node's position in the engine's real frame
    path: list                      # node keys from the event's root down to the node
    s: int                          # symmetry: canonical = real.transformed(s)
    depth: int = 0


@dataclass
class Request:
    kind: str                       # expand | more (scout) | refute | abstract
    dag_key: str
    can: Position                   # canonical position of dag_key (the job's frame)
    targets: list = field(default_factory=list)
    tag: str = ""                   # scout region / abstract label
    params: dict = field(default_factory=dict)
    cls: int = CLS_DEEP
    context: str = ""               # abstract: the search summary
    mem_points: list = field(default_factory=list)
    attempts: int = 0
    rl_attempts: int = 0
    not_before: float = 0.0
    epoch: int = 0                  # engine generation the targets belong to
    root_label: str = ""
    created: float = field(default_factory=time.time)
    started: float = 0.0
    seq: int = 0
    vis: int = -1                   # the targets' visits when last ranked (queue-cap ranking)

    @property
    def rid(self) -> tuple:
        return (self.kind, self.dag_key, self.tag)


def canonical_of(board: Board) -> tuple[str, Position, int]:
    """(DAG key, canonical position without `last`, s) with canonical = real.transformed(s)."""
    can, s = board.to_position().canonical()
    can = Position(can.size, can.cells, can.to_play, can.ko, can.passes, can.komi, None)
    return can.raw_key, can, s


def to_real(move: Optional[int], s: int, size: int) -> Optional[int]:
    return None if move is None else sym_maps(size)[1][s][move]


def to_canonical(move: Optional[int], s: int, size: int) -> Optional[int]:
    return None if move is None else sym_maps(size)[0][s][move]


def classify_failure(res: JobResult, jobdir: Optional[Path]) -> tuple[str, Optional[float]]:
    """Failure class of a JobResult: rate_limit | overloaded | timeout | start_failed | invalid |
    no_answer | exception, plus a usage-limit reset time (epoch seconds) when the log names one."""
    texts = [res.error or ""]
    if jobdir is not None:
        try:
            texts.append((jobdir / "session.err").read_text(errors="ignore")[-20_000:])
        except OSError:
            pass
        try:
            for line in (jobdir / "session.jsonl").read_text(errors="ignore").splitlines()[-400:]:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                typ, sub = d.get("type"), str(d.get("subtype") or "")
                if typ == "result" and d.get("is_error"):
                    texts.append(str(d.get("result", "")) + " " + json.dumps(d.get("error") or ""))
                elif typ == "system" and ("retry" in sub or "error" in sub):
                    texts.append(json.dumps(d))
                elif d.get("error"):
                    texts.append(json.dumps(d.get("error")))
                if typ == "assistant":
                    for c in ((d.get("message") or {}).get("content") or []):
                        if isinstance(c, dict) and str(c.get("text", "")).startswith("API Error"):
                            texts.append(c["text"])
        except OSError:
            pass
    blob = "\n".join(t for t in texts if t)
    reset = None
    m = RESET_RE.search(blob)
    if m:
        reset = float(m.group(1))
    if RATE_RE.search(blob):
        return "rate_limit", reset
    if OVERLOAD_RE.search(blob):
        return "overloaded", reset
    err = res.error or ""
    if "rc=-9" in err or "timed out" in err.lower():
        return "timeout", None
    if err.startswith("cannot start"):
        return "start_failed", None
    if err.startswith("invalid answer"):
        return "invalid", None
    if err.startswith("worker exception"):
        return "exception", None
    return "no_answer", None


class LLMService:
    """Expansion service for one MCTS engine at a time (attach / detach between games).

    worker   a gotree Worker (CLIWorker for real sessions, MockWorker or a fake in tests)
    dag      gotree DAG (L0): evaluations persist there across moves, games and runs
    mem      gotree Memory (L1/L2): briefings for every job, lessons from abstract jobs
    learner  optional; ``learner.observe_external(position, source, priors, value)`` is called for
             every LLM evaluation applied to the engine (position: mcts Board, priors real frame)
    record   JSONL file, one line per finished session (kind, node, result class, usage, seconds)
    jobs_dir directory of the worker's job dirs (CLIWorker: <run>/jobs), for failure diagnosis
    """

    def __init__(self, worker: Worker, dag: DAG, mem: Memory, cfg: Optional[LLMConfig] = None, *, learner=None,
                 log: Callable[[str], None] = print, record: Optional[Path] = None,
                 jobs_dir: Optional[Path] = None):
        self.worker, self.dag, self.mem = worker, dag, mem
        self.cfg = cfg or LLMConfig()
        self.learner, self.log = learner, log
        self.record = Path(record) if record else None
        self.jobs_dir = Path(jobs_dir) if jobs_dir else None
        self.dag.x("CREATE TABLE IF NOT EXISTS mcts_tags (key TEXT NOT NULL, kind TEXT NOT NULL, tag TEXT NOT NULL, "
                   "job_id INTEGER, ts REAL NOT NULL, PRIMARY KEY (key, kind, tag))")
        self._lock = threading.RLock()        # queue, running, seen, counters, root info
        self._eng_lock = threading.RLock()    # use of the engine object (never held with _lock)
        self._wake = threading.Event()
        self._inbox: deque = deque()
        self._queue: dict[tuple, Request] = {}
        self._running: dict[tuple, Request] = {}
        self._seen: dict[int, str] = {}       # engine key -> DAG key, for every node handled in this tree
        self._done_dkeys: set[str] = set()    # expand requests finished OK by this service
        self._seq = itertools.count()
        self._dropped: "OrderedDict[int, float]" = OrderedDict()   # engine keys of dropped requests
        self._rearm_t = 0.0
        self._boost_t = 0.0
        self._boost_new: dict[str, int] = {}      # DAG key -> requests boost() created (at most boost_max_new)
        self._searching_flag = False
        self._inflight = 0                    # inbox events being triaged (wait_idle counts them as busy)
        self.eng = None
        self.epoch = 0
        self.root_key: Optional[int] = None
        self.root_board: Optional[Board] = None
        self.root_dag, self.root_s, self.root_label = "", 0, ""
        self.root_t0 = 0.0
        self._refuted = True
        self._tick_t = 0.0
        self.w_cur = max(1, self.cfg.workers)
        self.paused_until = 0.0
        self._manual_pause = False
        self._rl_streak = self._fail_streak = self._ok_streak = 0
        self.ctr: dict[str, float] = {k: 0 for k in (
            "events", "inbox_dropped", "followers", "cache_hits", "queued", "cap_dropped", "stale_dropped",
            "launched", "ok", "failed", "rate_limited", "overloaded", "retried", "abandoned", "applied",
            "applied_mid_search", "stale_results", "learner_calls", "rearmed", "boosted", "root_breadth_sets",
            "cost_usd", "job_seconds", *USAGE_KEYS)}
        self._pool = ThreadPoolExecutor(max_workers=max(1, self.cfg.workers), thread_name_prefix="llm-job")
        self._thread: Optional[threading.Thread] = None
        self._stop = False
        self._obs_extra = bool(learner is not None and hasattr(learner, "observe_external")
                               and _accepts_kwargs(learner.observe_external))

    @property
    def searching(self) -> bool:
        """Whether the attached engine is searching (MCTS.searching), or the caller said so."""
        eng = self.eng
        return self._searching_flag or bool(eng is not None and getattr(eng, "searching", False))

    @searching.setter
    def searching(self, v: bool) -> None:
        self._searching_flag = bool(v)

    # ================================================================ lifecycle
    def start(self) -> "LLMService":
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="llm-dispatch", daemon=True)
            self._thread.start()
        return self

    def close(self, wait_s: float = 0.0) -> None:
        """Stop dispatching; wait up to `wait_s` for sessions in flight (their results still reach
        the DAG); sessions still running afterwards finish in the background."""
        if wait_s > 0:
            t_end = time.time() + wait_s
            while time.time() < t_end and self._running:
                time.sleep(0.2)
        self._stop = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._pool.shutdown(wait=False)

    def pause(self) -> None:
        self._manual_pause = True

    def resume(self) -> None:
        self._manual_pause = False
        self._wake.set()

    def attach(self, eng) -> None:
        """Serve this engine (one per game).  Requests of an earlier engine are dropped; results of
        its sessions still in flight only reach the DAG."""
        with self._eng_lock:
            self.eng = eng
            if eng is not None:
                eng.on_expand = self.on_expand
        with self._lock:
            self.epoch += 1
            self._seen.clear()
            self._dropped.clear()
            for rid, r in list(self._queue.items()):
                if r.kind != "abstract":
                    del self._queue[rid]
            self.root_key = None
        if eng is not None:
            self.new_root()

    def detach(self) -> None:
        with self._eng_lock:
            if self.eng is not None:
                self.eng.on_expand = None
            self.eng = None
        with self._lock:
            self.epoch += 1
            self._dropped.clear()
            for rid, r in list(self._queue.items()):
                if r.kind != "abstract":
                    del self._queue[rid]

    # ================================================================ engine side (must be quick)
    def on_expand(self, ev) -> None:
        """MCTS hook: queue the event (called on the search's control thread)."""
        if len(self._inbox) >= self.cfg.inbox_cap:
            self.ctr["inbox_dropped"] += 1
            return
        self._inbox.append((self.epoch, ev))
        self._wake.set()

    def new_root(self, label: str = "") -> None:
        """Call after the engine's root changed (advance / set_root / a new or loaded tree): drops
        requests for nodes outside the new root's subtree, re-ranks the rest and asks for the
        root's evaluation and v1's root breadth jobs."""
        with self._eng_lock:
            eng = self.eng
            if eng is None:
                return
            rkey = int(eng.a.key[eng.root])
            board = eng.root_board.copy()
        dkey, can, s = canonical_of(board)
        with self._lock:
            self.root_key, self.root_board, self.root_dag, self.root_s = rkey, board, dkey, s
            self.root_label = label
            self.root_t0 = time.time()
            self._refuted = not self.cfg.refute
            items = [(rid, r, list(r.targets)) for rid, r in self._queue.items() if r.kind != "abstract"]
        # liveness outside the service lock (the exact subtree query asks the engine)
        live_of = {rid: [t for t in tg if self._in_subtree(t)] for rid, r, tg in items}
        dropped = []
        with self._lock:
            for rid, r, tg in items:
                if self._queue.get(rid) is not r:
                    continue
                live = live_of[rid]
                if not live:
                    del self._queue[rid]
                    self.ctr["stale_dropped"] += 1
                    dropped.extend(tg)
                    continue
                dropped.extend(t for t in r.targets if t not in live)
                r.targets = live
                r.cls = min(self._cls_of(r.kind, t) for t in live)
            self._note_dropped(dropped)
        tgt = Target(rkey, board, [rkey], s, 0)
        self._request_node(tgt, dkey, can, root=True)
        if self._has_eval(dkey):
            self._set_root_breadth()
            self._request_scouts()
        self._wake.set()

    def tick(self) -> None:
        """Call from the search's control thread (e.g. inside search's stop callable): raises the
        priority of the most-visited root moves without a model value (every boost_every_s) and
        launches the refute of the current top move once the root has been searched for
        refute_after_s."""
        now = time.time()
        if now - self._tick_t < 1.0:
            return
        self._tick_t = now
        if self.cfg.boost_top > 0 and now - self._boost_t >= self.cfg.boost_every_s and self.root_key is not None:
            self._boost_t = now
            try:
                self.boost(self.top_unevaluated(self.cfg.boost_top))
            except Exception as e:   # never into the search
                self.log(f"llm: boost failed: {e!r}")
        if self._refuted or self.root_key is None or now - self.root_t0 < self.cfg.refute_after_s:
            return
        with self._eng_lock:
            eng = self.eng
            if eng is None or int(eng.a.key[eng.root]) != self.root_key:
                return
            ch = [c for c in eng.children(eng.root) if c["n"] > 0]
            if not ch:
                return
            top = max(ch, key=lambda c: c["n"])
            board = self.root_board.played(top["move"])
        self._refuted = True
        if board.terminal:
            return
        dkey, can, s = canonical_of(board)
        if self._tag_done(dkey, "refute", ""):
            return
        tgt = Target(board.key, board, [self.root_key, board.key], s, 1)
        r = Request("refute", dkey, can, [tgt], params={"k": self.cfg.k_node, "u": self.cfg.u_node},
                    cls=CLS_BREADTH, epoch=self.epoch, root_label=self.root_label)
        self._enqueue(r)
        self.log(f"llm: refute of the top move {coord(top['move'], board.size)} queued (n={top['n']})")

    def top_unevaluated(self, k: int) -> list:
        """The k most-visited root moves (real frame) whose node has no model value of its own."""
        with self._eng_lock:
            eng = self.eng
            if eng is None or int(eng.a.key[eng.root]) != self.root_key:
                return []
            ch = sorted((c for c in eng.children(eng.root) if c["n"] > 0), key=lambda c: -c["n"])
        out = []
        for c in ch:
            if len(out) >= k:
                break
            if not c.get("evaluated"):
                out.append(c["move"])
        return out

    def boost(self, moves) -> int:
        """Top priority (CLS_TOP) for the evaluation of these root moves (real frame), creating the
        request if there is none (it was never raised, was dropped, or failed); a move whose
        evaluation the DAG already holds is applied at once.  Returns how many of the moves have a
        request that can still run (queued and dispatchable, or running) or got their value now."""
        if self.root_board is None or self.root_key is None:
            return 0
        board0, rkey = self.root_board, self.root_key
        n_ok = 0
        for m in moves or []:
            try:
                board = board0.played(m)
            except Exception:
                continue
            if board.terminal:
                continue
            key = board.key
            if self._node_value(key) is not None:
                n_ok += 1
                continue
            dkey, can, s = canonical_of(board)
            rid = ("expand", dkey, "")
            tgt = Target(key, board, [rkey, key], s, 1)
            with self._lock:
                have = self._queue.get(rid) or self._running.get(rid)
                if have is not None:
                    if all(t.key != key for t in have.targets):
                        have.targets.append(tgt)
                    if have.cls > CLS_TOP:
                        have.cls = CLS_TOP
                        self.ctr["boosted"] += 1
                    running = rid in self._running
                    capped = bool(self.cfg.max_jobs and self.ctr["launched"] >= self.cfg.max_jobs)
                    n_ok += 1 if (running or (not capped and not self._manual_pause)) else 0
                    self._seen[key] = dkey
                    self._dropped.pop(key, None)
                    continue
                self._seen[key] = dkey
                self._dropped.pop(key, None)
            if self.cfg.cache and self._has_eval(dkey):
                self._apply(tgt, dkey, value=self._static(dkey), cached=True, kind="expand")
                with self._lock:
                    self.ctr["cache_hits"] += 1
                n_ok += 1 if self._node_value(key) is not None else 0
                continue
            with self._lock:
                capped = bool(self.cfg.max_jobs and self.ctr["launched"] >= self.cfg.max_jobs)
                tries = self._boost_new.get(dkey, 0)
                if not capped and tries < self.cfg.boost_max_new:
                    self._boost_new[dkey] = tries + 1
            if capped or tries >= self.cfg.boost_max_new:   # e.g. its sessions keep failing
                continue
            r = Request("expand", dkey, can, [tgt], params={"k": self.cfg.k_node, "u": self.cfg.u_node},
                        cls=CLS_TOP, root_label=self.root_label)
            self._enqueue(r)
            with self._lock:
                self.ctr["boosted"] += 1
            n_ok += 1
        self._wake.set()
        return n_ok

    def _node_value(self, key: int) -> Optional[float]:
        with self._eng_lock:
            eng = self.eng
            if eng is None:
                return None
            i = eng.find(key)
            return None if i < 0 else eng.ext_value(i)

    def request_abstract(self, stats: list[dict], best: Optional[int], root_q: Optional[float],
                         root_n: int, label: str = "") -> bool:
        """Queue a lessons job (v1 `abstract`) for the current root after a decision.  `stats` is the
        engine's root table (MCTS.root_stats), `best` the chosen move (real frame)."""
        if not self.cfg.abstract or self.root_board is None:
            return False
        dkey, s, board = self.root_dag, self.root_s, self.root_board
        if not self._has_eval(dkey):
            return False
        can = self.dag.position(dkey)
        llm = self.llm_priors(dkey)
        ctx = abstract_context(stats, llm, s, board.size, root_q, root_n)
        chosen_c = to_canonical(best, s, board.size)
        r = Request("abstract", dkey, can, [], tag=label or f"t{int(time.time())}",
                    params={"chosen": coord(chosen_c, board.size), "title": "Root position"}, cls=CLS_BREADTH,
                    context=ctx, mem_points=[chosen_c] if chosen_c is not None else [], epoch=self.epoch,
                    root_label=self.root_label)
        self._enqueue(r)
        return True

    # ================================================================ reporting
    def stats(self) -> dict:
        with self._lock:
            out = dict(self.ctr)
            out.update(queue=len(self._queue), running=len(self._running), inbox=len(self._inbox), w_cur=self.w_cur,
                       paused_s=max(0.0, round(self.paused_until - time.time(), 1)), dropped=len(self._dropped))
        out["cost_usd"] = round(out["cost_usd"], 4)
        return out

    def queued(self) -> list[dict]:
        with self._lock:
            return [{"kind": r.kind, "dag_key": r.dag_key, "tag": r.tag, "cls": r.cls,
                     "keys": [t.key for t in r.targets], "depths": [self._depth(t) for t in r.targets]}
                    for r in self._queue.values()]

    def wait_idle(self, timeout: float = 30.0, queue_too: bool = True) -> bool:
        """Wait until nothing is in the inbox or running (and, with queue_too, nothing queued that
        could still be dispatched).  Returns False on timeout."""
        t_end = time.time() + timeout
        while time.time() < t_end:
            with self._lock:
                busy = bool(self._inbox) or bool(self._running) or self._inflight > 0
                if queue_too and not busy and self._queue and not self._manual_pause and \
                        (not self.cfg.max_jobs or self.ctr["launched"] < self.cfg.max_jobs):
                    busy = True
            if not busy:
                return True
            self._wake.set()
            time.sleep(0.02)
        return False

    def llm_priors(self, dag_key: str, root: bool = False) -> dict:
        """{canonical move: prior} of every LLM-proposed edge the DAG holds for the position."""
        out: dict = {}
        for e in self.dag.edges(dag_key):
            if e.source not in LLM_SOURCES:
                continue
            p = float(e.prior)
            if root and e.source in EXPLORE_SOURCES and self.cfg.root_explore_prior > 0:
                p = max(p, self.cfg.root_explore_prior)
            out[e.move] = max(out.get(e.move, 0.0), p)
        return out

    def llm_breadth(self, dag_key: str) -> dict:
        """{canonical move: "candidate" | "explore"} of the LLM edges (a move proposed both ways is a
        candidate)."""
        out: dict = {}
        for e in self.dag.edges(dag_key):
            if e.source not in LLM_SOURCES:
                continue
            c = "explore" if e.source in EXPLORE_SOURCES else "candidate"
            if out.get(e.move) != "candidate":
                out[e.move] = c
        return out

    def _set_root_breadth(self) -> int:
        """The root's LLM moves get the engine's minimum visits (real frame)."""
        if not self.cfg.root_breadth or self.root_board is None or not self.root_dag:
            return 0
        size = self.root_board.size
        cls = {to_real(m, self.root_s, size): c for m, c in self.llm_breadth(self.root_dag).items()}
        with self._eng_lock:
            eng = self.eng
            if eng is None or int(eng.a.key[eng.root]) != self.root_key or not hasattr(eng, "set_root_breadth"):
                return 0
            n = eng.set_root_breadth(cls)
        with self._lock:
            self.ctr["root_breadth_sets"] += 1
        return n

    def root_llm_priors(self) -> dict:
        """{real move: prior} of the LLM edges at the current root (empty without an evaluation)."""
        if not self.root_dag or self.root_board is None:
            return {}
        size = self.root_board.size
        return {to_real(m, self.root_s, size): p for m, p in self.llm_priors(self.root_dag).items()}

    def root_value(self) -> Optional[float]:
        n = self.dag.node(self.root_dag) if self.root_dag else None
        return None if not n else n["static_value"]

    # ================================================================ internals: requests
    def _in_subtree(self, t: Target) -> bool:
        """Is the target node reachable from the current root?  Its recorded path running through the
        root proves it (those links stay); otherwise the engine's exact query decides (another move
        order, a truncated path)."""
        if self.root_key is None:
            return True
        if self.root_key in t.path:
            return True
        with self._eng_lock:
            eng = self.eng
            if eng is None:
                return False
            if not hasattr(eng, "in_subtree"):
                return len(t.path) >= EV_PATH_MAX
            return bool(eng.in_subtree(t.key))

    def _note_dropped(self, targets) -> None:
        """Remember dropped targets (caller holds _lock): their hooks are re-armed later."""
        if not self.cfg.rearm:
            return
        now = time.time()
        for t in targets:
            self._dropped.pop(t.key, None)
            self._dropped[t.key] = now
            self._seen.pop(t.key, None)
        while len(self._dropped) > 100_000:
            self._dropped.popitem(last=False)

    def _rearm_dropped(self, now: float) -> int:
        """Re-arm the hooks of dropped nodes that are in the root's subtree, while the queue has room
        (at most a quarter of it per round, newest drops first): such a node raises its request
        again on its next visit, ranked by the visits it has then."""
        if not self.cfg.rearm or now - self._rearm_t < self.cfg.rearm_every_s:
            return 0
        self._rearm_t = now
        with self._lock:
            room = self.cfg.queue_cap - len(self._queue)
            if room < self.cfg.queue_cap // 4 or not self._dropped:
                return 0
            keys = list(reversed(self._dropped))[:500]
        budget, done = max(1, room // 4), []
        with self._eng_lock:                     # never nested with _lock
            eng = self.eng
            if eng is None or not hasattr(eng, "rearm"):
                return 0
            for k in keys:
                if len(done) >= budget:
                    break
                if eng.in_subtree(k) and eng.rearm(k):
                    done.append(k)
        if done:
            with self._lock:
                for k in done:
                    self._dropped.pop(k, None)
                self.ctr["rearmed"] += len(done)
        return len(done)

    def _depth(self, t: Target) -> int:
        if self.root_key is not None and self.root_key in t.path:
            return len(t.path) - 1 - t.path.index(self.root_key)
        return t.depth

    def _cls_of(self, kind: str, t: Target) -> int:
        if kind == "expand":
            d = self._depth(t)
            return CLS_ROOT if d == 0 else CLS_CHILD if d == 1 else CLS_DEEP
        return CLS_BREADTH

    def _has_eval(self, dkey: str) -> bool:
        n = self.dag.node(dkey)
        return bool(n and n["static_value"] is not None and self.llm_priors(dkey))

    def _tag_done(self, dkey: str, kind: str, tag: str) -> bool:
        return bool(self.dag.q1("SELECT 1 AS x FROM mcts_tags WHERE key=? AND kind=? AND tag=?", (dkey, kind, tag)))

    def _enqueue(self, r: Request) -> bool:
        """Queue r unless the same request is queued or running (its targets then follow that one).
        Insert and cap are one atomic step: beyond queue_cap the lowest-ranked request (class, then
        the visits it had when last ranked, then age) is dropped before the lock is released."""
        r.vis = self._visits(r)                       # engine lookup outside the service lock
        with self._lock:
            have = self._queue.get(r.rid) or self._running.get(r.rid)
            if have is not None:
                have.targets.extend(t for t in r.targets if t.key not in {x.key for x in have.targets})
                have.cls = min(have.cls, r.cls)
                self.ctr["followers"] += 1
                return False
            r.seq = next(self._seq)
            r.epoch = self.epoch
            self._queue[r.rid] = r
            self.ctr["queued"] += 1
            while len(self._queue) > self.cfg.queue_cap:
                cands = [q for q in self._queue.values() if q.kind != "abstract" and q.cls > CLS_BREADTH] or \
                    list(self._queue.values())
                worst = max(cands, key=lambda q: (q.cls, -q.vis, q.seq))
                del self._queue[worst.rid]
                self.ctr["cap_dropped"] += 1
                self._note_dropped(worst.targets)
        self._wake.set()
        return True

    def _request_node(self, tgt: Target, dkey: str, can: Position, root: bool = False) -> None:
        """An engine node wants an evaluation: from the cache, by following a queued / running
        request, or as a new expand request."""
        with self._lock:
            self._seen[tgt.key] = dkey
            in_flight = (("expand", dkey, "") in self._queue) or (("expand", dkey, "") in self._running)
            done = dkey in self._done_dkeys
        if not in_flight and (done or self.cfg.cache) and self._has_eval(dkey):
            if root and self._node_has_ext(tgt.key):
                return                                # the root already carries this evaluation
            self._apply(tgt, dkey, value=self._static(dkey), cached=True, kind="expand")
            with self._lock:
                self.ctr["cache_hits"] += 1
            return
        is_root = root or self._depth(tgt) == 0
        r = Request("expand", dkey, can, [tgt],
                    params={"k": self.cfg.k_root if is_root else self.cfg.k_node,
                            "u": self.cfg.u_root if is_root else self.cfg.u_node},
                    cls=CLS_ROOT if is_root else self._cls_of("expand", tgt), root_label=self.root_label)
        self._enqueue(r)

    def _request_scouts(self) -> None:
        if not self.cfg.scouts or self.root_board is None:
            return
        dkey, can, board = self.root_dag, None, self.root_board
        for name, pts in regions(board.size):
            if self._tag_done(dkey, "more", name):
                continue
            if can is None:
                can = canonical_of(board)[1]
            tgt = Target(self.root_key, board, [self.root_key], self.root_s, 0)
            self._enqueue(Request("more", dkey, can, [tgt], tag=name,
                                  params={"k": 3, "u": 1, "region": name, "region_points": list(pts)},
                                  cls=CLS_BREADTH, root_label=self.root_label))

    def _static(self, dkey: str) -> Optional[float]:
        n = self.dag.node(dkey)
        return None if not n else n["static_value"]

    def _node_has_ext(self, key: int) -> bool:
        with self._eng_lock:
            eng = self.eng
            if eng is None:
                return False
            i = eng.find(key)
            return i >= 0 and bool(int(eng.a.flags[i]) & FL_EXT)

    def _visits(self, r: Request) -> int:
        best = -1
        with self._eng_lock:
            eng = self.eng
            if eng is None:
                return -1
            for t in r.targets:
                i = eng.find(t.key)
                if i >= 0:
                    best = max(best, int(eng.a.n[i]))
        return best

    # ================================================================ internals: dispatcher
    def _loop(self) -> None:
        while not self._stop:
            self._wake.wait(self.cfg.poll_s)
            self._wake.clear()
            try:
                self._drain_inbox()
                self._dispatch()
                self._rearm_dropped(time.time())
            except Exception as e:  # the service must never take the search down
                self.log(f"llm: dispatcher error {e!r}\n{traceback.format_exc()}")
                time.sleep(1.0)

    def _drain_inbox(self, limit: int = 5000) -> None:
        for _ in range(limit):
            with self._lock:                          # pop and mark in flight atomically (wait_idle)
                try:
                    epoch, ev = self._inbox.popleft()
                except IndexError:
                    return
                self._inflight += 1
            try:
                self._triage(epoch, ev)
            finally:
                with self._lock:
                    self._inflight -= 1

    def _triage(self, epoch: int, ev) -> None:
        """One hook event: follow, serve from the DAG, or queue an expand request."""
        if epoch != self.epoch or self.eng is None:
            return
        with self._lock:
            self.ctr["events"] += 1
            prev = self._seen.get(ev.key)
        if prev is not None:
            # handled earlier in this tree; an event again means the node was evicted and
            # re-created, so it lost its external priors: re-apply a known evaluation
            if prev in self._done_dkeys and not self._node_has_ext(ev.key) and self._has_eval(prev):
                dkey, _, s = canonical_of(ev.board)
                self._apply(Target(ev.key, ev.board, list(ev.path), s, ev.depth), dkey,
                            value=self._static(dkey), cached=True, kind="expand")
                with self._lock:
                    self.ctr["cache_hits"] += 1
            return
        dkey, can, s = canonical_of(ev.board)
        tgt = Target(ev.key, ev.board, list(ev.path), s, ev.depth)
        if not self._in_subtree(tgt):
            with self._lock:
                self.ctr["stale_dropped"] += 1
                self._note_dropped([tgt])
            return
        self._request_node(tgt, dkey, can)

    def _dispatch(self) -> None:
        while not self._stop:
            now = time.time()
            if self._manual_pause or now < self.paused_until:
                return
            with self._lock:
                if len(self._running) >= self.w_cur or not self._queue:
                    return
                if self.cfg.max_jobs and self.ctr["launched"] >= self.cfg.max_jobs:
                    return
            r = self._pick(now)                       # now in _running (a slot is taken)
            if r is None:
                return
            if r.kind == "expand" and self.cfg.cache and self._has_eval(r.dag_key):
                with self._lock:                      # the DAG got this evaluation meanwhile
                    targets = list(r.targets)
                    self.ctr["cache_hits"] += 1
                self._apply_all(r, value=self._static(r.dag_key), cached=True, targets=targets)
                with self._lock:                      # released after applying (wait_idle means applied)
                    late = [t for t in r.targets if t.key not in {x.key for x in targets}]
                    self._running.pop(r.rid, None)
                if late:
                    self._apply_all(r, value=self._static(r.dag_key), cached=True, targets=late)
                continue
            try:
                job = self._build_job(r)
            except Exception as e:
                with self._lock:
                    self._running.pop(r.rid, None)
                self.log(f"llm: cannot build a {r.kind} job for {r.dag_key[:8]}: {e!r}")
                continue
            with self._lock:
                r.started = time.time()
                self.ctr["launched"] += 1
            self._pool.submit(self._run, r, job)

    def _pick(self, now: float) -> Optional[Request]:
        with self._lock:
            items = list(self._queue.values())
            delay_until = self.root_t0 + self.cfg.dispatch_delay_s
        root_n = 0
        with self._eng_lock:
            if self.eng is not None:
                root_n = int(self.eng.a.n[self.eng.root])
        scored = []
        stale = []
        for r in items:
            if r.not_before > now:
                continue
            if r.kind == "abstract":
                scored.append(((r.cls, 0, r.seq), r))
                continue
            if r.epoch != self.epoch:
                stale.append(r)
                continue
            live = [t for t in r.targets if self._in_subtree(t)]
            if not live:
                stale.append(r)
                continue
            if r.cls >= CLS_CHILD and now < delay_until:
                continue
            vis = self._visits(r)
            r.vis = vis
            cls = r.cls
            if cls == CLS_CHILD and root_n and vis < self.cfg.child_min_share * root_n:
                cls = CLS_DEEP                            # a root child the search hardly visits
            scored.append(((cls, -vis, r.seq), r))
        with self._lock:
            for r in stale:
                if self._queue.pop(r.rid, None) is not None:
                    self.ctr["stale_dropped"] += 1
                    self._note_dropped(r.targets)
            for _, r in sorted(scored, key=lambda x: x[0]):
                if self._queue.pop(r.rid, None) is not None:
                    self._running[r.rid] = r
                    return r
        return None

    def _build_job(self, r: Request) -> Job:
        key, _, _ = self.dag.ensure(r.can)
        if key != r.dag_key:
            raise RuntimeError(f"canonical key mismatch {key} != {r.dag_key}")
        pos = self.dag.position(key)
        if r.kind == "abstract":
            pts = list(r.mem_points)
        else:
            pts = [p for p, _ in heuristics.score_moves(pos)[:6] if p is not None]
        memory = self.mem.briefing(pos, pts)
        known = describe_known(self.dag, key, pos) if r.kind in ("more", "refute") else ""
        params = dict(r.params)
        params.setdefault("title", f"Position {key[:8]}")
        if r.kind == "more":
            edges = self.dag.child_stats(key)
            params.update(exclude=", ".join(coord(e["move"], pos.size) for e in edges),
                          exclude_points=[e["move"] for e in edges])
        job = Job(r.kind, key, pos, params, memory=memory, known=known, context=r.context)
        now = time.time()
        job.id = self.dag.x("INSERT INTO jobs (kind,key,root,status,worker,created,started) VALUES (?,?,?,?,?,?,?)",
                            (r.kind, key, self.root_dag, "running", self.worker.name, now, now))
        return job

    def _jobdir(self, job: Job) -> Optional[Path]:
        if self.jobs_dir is None or not self.jobs_dir.is_dir():
            return None
        hits = sorted(self.jobs_dir.glob(f"{job.id:06d}-{job.kind}-*"))
        return hits[-1] if hits else None

    def _run(self, r: Request, job: Job) -> None:
        t0 = time.time()
        try:
            res = self.worker.run(job)
        except Exception as e:
            res = JobResult(False, error=f"worker exception: {e!r}", worker=getattr(self.worker, "name", ""))
        try:
            self._finish(r, job, res, time.time() - t0)
        except Exception as e:
            self.log(f"llm: finishing job {job.id} failed: {e!r}\n{traceback.format_exc()}")
            with self._lock:
                self._running.pop(r.rid, None)
        finally:
            self._wake.set()

    def _finish(self, r: Request, job: Job, res: JobResult, seconds: float) -> None:
        jd = self._jobdir(job)
        usage = dict(res.usage or {})
        if not usage and jd is not None:
            usage = _cli_usage(jd / "session.jsonl")
        self.dag.x("UPDATE jobs SET status=?, finished=?, result=?, error=?, usage=? WHERE id=?",
                   ("done" if res.ok else "failed", time.time(), json.dumps(res.result) if res.result else None,
                    (res.error or "")[:2000], json.dumps(usage), job.id))
        fclass, reset = (None, None) if res.ok else classify_failure(res, jd)
        rec = {"t": round(time.time(), 1), "job_id": job.id, "kind": r.kind, "tag": r.tag, "dag_key": r.dag_key,
               "root": r.root_label, "targets": len(r.targets), "attempt": r.attempts + r.rl_attempts + 1,
               "ok": res.ok, "fail_class": fclass, "error": (res.error or "")[:300], "seconds": round(seconds, 1),
               "usage": usage, "worker": res.worker, "jobdir": str(jd) if jd else None}
        with self._lock:
            self.ctr["job_seconds"] += seconds
            self.ctr["cost_usd"] += float(usage.get("cost_usd", 0) or 0)
            for k in USAGE_KEYS:
                self.ctr[k] += int(usage.get(k, 0) or 0)
        if res.ok and res.result is not None:
            if r.kind == "abstract":
                rec["lessons"] = self._write_lessons(r, job, res)
            else:
                v = self._write_dag(r, job, res)
            with self._lock:
                self.ctr["ok"] += 1
                if r.kind == "expand":
                    self._done_dkeys.add(r.dag_key)
                targets = list(r.targets)
                self._rl_streak = self._fail_streak = 0
                self._ok_streak += 1
                if self._ok_streak >= self.cfg.ramp_up_after and self.w_cur < self.cfg.workers:
                    self.w_cur += 1
                    self._ok_streak = 0
            if r.kind in ("more", "refute") or r.tag:
                self.dag.x("INSERT OR REPLACE INTO mcts_tags (key,kind,tag,job_id,ts) VALUES (?,?,?,?,?)",
                           (r.dag_key, r.kind, r.tag, job.id, time.time()))
            if r.kind != "abstract":
                value = v if (r.kind != "more" or self.cfg.scout_values) else None
                rec["applied"] = self._apply_all(r, value=value, cached=False, targets=targets, job_id=job.id)
                rec["value"] = v
                rec["n_candidates"] = len(res.result.get("candidates", [])) + len(res.result.get("unconventional", []))
            # the slot is released only after the results are applied (wait_idle means applied);
            # followers that joined meanwhile get the result too
            with self._lock:
                seen_keys = {t.key for t in targets}
                late = [t for t in r.targets if t.key not in seen_keys]
                self._running.pop(r.rid, None)
            if r.kind != "abstract":
                if late:
                    rec["applied"] += self._apply_all(r, value=value, cached=False, targets=late, job_id=job.id)
                if r.kind == "expand" and r.cls == CLS_ROOT and r.dag_key == self.root_dag:
                    self._request_scouts()
        else:
            self._failed(r, res, fclass, reset, rec)
        self._write_record(rec)

    def _failed(self, r: Request, res: JobResult, fclass: str, reset: Optional[float], rec: dict) -> None:
        now = time.time()
        cfg = self.cfg
        with self._lock:
            self.ctr["failed"] += 1
            self._running.pop(r.rid, None)
            self._ok_streak = 0
            outage = fclass in ("rate_limit", "overloaded", "start_failed")
            if fclass in ("rate_limit", "overloaded"):
                self.ctr["rate_limited" if fclass == "rate_limit" else "overloaded"] += 1
                self._rl_streak += 1
                r.rl_attempts += 1
                k = self._rl_streak
            else:
                self._fail_streak += 1
                r.attempts += 1
                outage = outage or self._fail_streak >= cfg.fail_streak_backoff
                k = max(1, self._fail_streak - cfg.fail_streak_backoff + 1)
            if outage:
                delay = min(cfg.backoff_max, cfg.backoff_base * 2 ** (k - 1))
                if reset is not None:
                    delay = max(delay, min(cfg.backoff_reset_cap, reset - now + 5))
                self.paused_until = max(self.paused_until, now + delay)
                self.w_cur = max(cfg.min_workers, self.w_cur // 2)
                rec["backoff_s"] = round(delay, 1)
                rec["w_cur"] = self.w_cur
            retry = (r.rl_attempts < cfg.max_rl_attempts) if fclass in ("rate_limit", "overloaded") else \
                (r.attempts < cfg.max_attempts)
            if retry and (r.kind == "abstract" or r.epoch == self.epoch) and r.rid not in self._queue:
                r.not_before = self.paused_until if outage else now
                self._queue[r.rid] = r
                self.ctr["retried"] += 1
                rec["retry"] = True
            else:
                self.ctr["abandoned"] += 1
        self.log(f"llm: job {rec['job_id']} ({r.kind} {r.dag_key[:8]}) failed [{fclass}]: {(res.error or '')[:160]}"
                 + (f"; pausing {rec['backoff_s']:.0f}s, W={rec['w_cur']}" if "backoff_s" in rec else "")
                 + ("; will retry" if rec.get("retry") else ""))

    # ================================================================ internals: results
    def _write_dag(self, r: Request, job: Job, res: JobResult) -> Optional[float]:
        """Store an expand / more / refute result in the DAG exactly as gotree v1 does."""
        res_ = res.result or {}
        key, kind = r.dag_key, r.kind
        existing = self.dag.child_stats(key)
        mass = 1.0
        if kind == "more" and existing:
            mass = max(0.1, 1.0 - sum(e["prior"] for e in existing))
        tot = sum(c["prior"] for c in res_.get("candidates", [])) or 1.0
        src = {"expand": "llm", "more": "more", "refute": "refute"}[kind]
        if r.params.get("region"):
            src = "scout"
        for c in res_.get("candidates", []):
            pr = c["prior"] if kind == "expand" else mass * c["prior"] / tot
            if kind == "refute":
                pr = max(pr, 0.15)
            self.dag.add_edge(key, c["move"], pr, src, c.get("why", ""))
        for u in res_.get("unconventional", []):
            self.dag.add_edge(key, u["move"], self.cfg.unconv_prior, "unconventional", u.get("why", ""))
        v = res_.get("value") or {}
        if v.get("winrate") is None:
            return None
        pos = self.dag.position(key)
        score_b = None
        if v.get("score_lead") is not None:
            score_b = v["score_lead"] if pos.to_play == "X" else -v["score_lead"]
        self.dag.set_static(key, v["winrate"], score_b, v.get("confidence", "low"), v.get("why", ""),
                            res_.get("plan", ""), worker=res.worker, job_id=job.id)
        return float(v["winrate"])

    def _write_lessons(self, r: Request, job: Job, res: JobResult) -> int:
        """v1 Search._abstract: lessons into the memory (canonical frame of the root)."""
        pos = job.pos
        n = 0
        for l in (res.result or {}).get("lessons", []):
            ev = {"key": r.dag_key, "move": r.params.get("chosen")}
            if l["scope"] == "local" and l["at"] is not None:
                lid = self.mem.add_local(pos, l["at"], l["text"], ev)
            else:
                lid = self.mem.add_global(l["text"], pos.phase(), pos.size, ev)
            n += 1
            for rel in l.get("relates_to", []):
                try:
                    other = int(str(rel["id"]).lstrip("GgLl"))
                except (KeyError, ValueError):
                    continue
                self.mem.relate(lid, other, str(rel.get("rel", "")))
        return n

    def _apply_all(self, r: Request, value: Optional[float], cached: bool, targets: Optional[list] = None,
                   job_id: Optional[int] = None) -> int:
        n = 0
        if r.epoch != self.epoch:
            with self._lock:
                self.ctr["stale_results"] += 1
            return 0
        for t in (targets if targets is not None else r.targets):
            n += self._apply(t, r.dag_key, value, cached, r.kind, job_id)
        return n

    def _apply(self, t: Target, dkey: str, value: Optional[float], cached: bool, kind: str,
               job_id: Optional[int] = None) -> int:
        size = t.board.size
        is_root = t.key == self.root_key
        pri_can = self.llm_priors(dkey, root=is_root)
        pri_real = {to_real(m, t.s, size): p for m, p in pri_can.items()}
        if not self._in_subtree(t):
            with self._lock:
                self.ctr["stale_results"] += 1
                self._note_dropped([t])          # the DAG has it now: served from there if it comes back
            return 0
        with self._eng_lock:
            eng = self.eng
            if eng is None:
                return 0
            out = eng.set_external(t.key, priors=pri_real or None, value=value, source="llm", position=t.board)
            searching = self.searching
            i = eng.find(t.key)
            n_at = int(eng.a.n[i]) if i >= 0 else 0
            mv = ""
            if i >= 0 and not is_root and int(eng.a.key[eng.root]) == self.root_key and eng.a.state[eng.root] == 2:
                e0, ne = int(eng.a.estart[eng.root]), int(eng.a.nedges[eng.root])
                hit = (eng.a.e_child[e0:e0 + ne] == i).nonzero()[0]
                if len(hit):
                    m = int(eng.a.e_move[e0 + int(hit[0])])
                    mv = f" {coord(None if m < 0 else m, size)}"
        if is_root and pri_real:
            self._set_root_breadth()
        with self._lock:
            self.ctr["applied"] += 1
            if searching:
                self.ctr["applied_mid_search"] += 1
        top = sorted(pri_real.items(), key=lambda kv: -kv[1])[:4]
        cal = out.get("value")
        self.log(f"llm: {'cache' if cached else f'job {job_id}'} {kind} {dkey[:8]} depth {self._depth(t)}{mv} sym {t.s}"
                 f" -> priors {' '.join(f'{coord(m, size)}:{p:.2f}' for m, p in top)}"
                 + (f" value {value:.2f}" if value is not None else "")
                 + (f" (calibrated {cal:.3f})" if cal is not None and value is not None and abs(cal - value) > 5e-4 else "")
                 + f" ({'applied' if out.get('applied') else 'pending'}{', mid-search' if searching else ''})")
        if self.learner is not None and hasattr(self.learner, "observe_external"):
            try:
                kw = {"n": n_at} if self._obs_extra else {}
                self.learner.observe_external(position=t.board, source="llm", priors=pri_real, value=value, **kw)
                with self._lock:
                    self.ctr["learner_calls"] += 1
            except Exception as e:
                self.log(f"llm: learner.observe_external failed: {e!r}")
        return 1 if out.get("applied") else 0

    def _write_record(self, rec: dict) -> None:
        if self.record is None:
            return
        with self._lock:
            with open(self.record, "a") as f:
                f.write(json.dumps(rec, default=str) + "\n")


def _accepts_kwargs(fn) -> bool:
    try:
        return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return False


def abstract_context(stats: list[dict], llm_can: dict, s: int, size: int, root_q: Optional[float],
                     root_n: int, top: int = 12) -> str:
    """v1-style search summary for an abstract job, in the job's (canonical) frame.  `stats` is the
    engine's root table (real frame), `llm_can` the LLM priors of the root's DAG key ({canonical
    move: prior}); surprises are moves whose LLM prior disagreed with the final visits."""
    fwd = sym_maps(size)[0][s]

    def c(m: Optional[int]) -> str:
        return coord(None if m is None else fwd[m], size)

    def cline(pv: list[str]) -> str:
        out = []
        for x in pv:
            p = point(x, size)
            out.append(coord(None if p is None else fwd[p], size))
        return " ".join(out)

    llm = {to_real(m, s, size): p for m, p in llm_can.items()}   # real frame, like stats
    rank = {m: i + 1 for i, (m, _) in enumerate(sorted(llm.items(), key=lambda kv: -kv[1]))}
    lines = [f"Search: {root_n} simulations through this position (code playouts guided by LLM priors); "
             f"backed-up winrate for the side to move {0.5 if root_q is None else root_q:.2f}."]
    lines.append("Candidates (n = visits, q = backed-up winrate for the mover, llm = the LLM workers' prior, "
                 "code = the learned feature prior):")
    for i, m in enumerate(stats[:top]):
        q = "-" if m["q"] is None else f"{m['q']:.2f}"
        lp = llm.get(m["move"])
        lines.append(f"  {i + 1:>2}. {c(m['move']):<5} n={m['n']:<9} q={q:<5} "
                     f"llm={'-' if lp is None else f'{lp:.2f}'} (llm rank {rank.get(m['move'], '-')}) "
                     f"code={m.get('prior_learned', 0):.2f}"
                     + (f"\n      line: {cline(m['pv'][:8])}" if m.get("pv") else ""))
    if stats:
        t0 = stats[0]
        sur = [m for m in stats if m["n"] >= 0.5 * t0["n"] and rank.get(m["move"], 99) >= 4]
        bad = [m for m in stats if rank.get(m["move"], 99) <= 2 and m is not t0 and m["q"] is not None and
               t0["q"] is not None and (m["q"] < t0["q"] - 0.1 or m["n"] < 0.1 * t0["n"])]
        if sur or bad:
            lines.append("SURPRISES:")
            for m in sur:
                r = rank.get(m["move"])
                lines.append(f"  {c(m['move'])} had a low LLM prior ({'not proposed' if r is None else f'rank {r}'}) "
                             f"but the search rates it highly (q={m['q'] if m['q'] is None else round(m['q'], 2)}, "
                             f"n={m['n']}).")
            for m in bad:
                lines.append(f"  {c(m['move'])} looked best to the LLM (rank {rank.get(m['move'])}) but scored worse "
                             f"after search (q={m['q']:.2f}, n={m['n']}).")
    return "\n".join(lines)
