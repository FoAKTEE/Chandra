"""MCTS v2 engine: one large tree per game, reused across moves, searched by many threads.

Storage is numpy struct-of-arrays owned here (nodes keyed by Zobrist key through a transposition
table, edges in one pool); the per-simulation hot loop (select / expand / playout / backup) runs
in C (csrc/tree.c) with the GIL released, so threads scale.  Python does everything structural:
search control and stop conditions, root statistics and PV, ``advance`` (root reuse), eviction
and compaction, save / load, external priors and values (``set_external``), and the hooks.

Values inside the tree are in [-1, 1] for the side to move at the node; the API reports winrates
in [0, 1] (``q``) and takes external values as winrates for the side to move (as gotree does).

Hooks (for the later nodes M7 / M8):
  * ``on_expand(event)`` is called on the search's control thread whenever a node first reaches
    ``n_thr`` visits (and for every node at depth <= ``hook_depth`` below the root, i.e. the root
    and its children by default).  It must return quickly (queue the work); the search does not
    wait for it.  The result comes back later, from any thread, through
    ``set_external(event.key, priors={move: p}, value=winrate, source="llm")``.
  * ``learner.observe(position, visit_distribution, q, depth)`` (or a plain callable with those
    keyword arguments) receives samples from well-visited nodes after every search.
  * ``weights`` may be a provider (``get() -> Weights``); it is asked at the start of every search
    and a new version is used from then on (new expansions and all playouts), without a restart.
"""
from __future__ import annotations

import ctypes
import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

import numpy as np

from gotree.position import IllegalMove, Position, coord

from ._lib import BOARD_BYTES, EV_PATH_MAX, N_FEATURES, lib
from .board import Board, Move, to_point
from .features import spec_id
from .weights import Weights, as_provider

# keep in sync with csrc/tree.c
ST_NEW, ST_EXPANDING, ST_EXPANDED, ST_TERMINAL = 0, 1, 2, 3
FL_HOOKED, FL_EXT = 1, 2
(C_NODES, C_EDGES, C_SIMS, C_SIMS_STARTED, C_PLAYOUTS, C_FULL, C_EV_DROPPED, C_EXPANSIONS, C_SUPERKO,
 C_DEPTH_SUM, C_DEPTH_MAX, C_TERMINAL, C_UNSTORED, C_EVENTS, C_PLAYOUT_NS, C_EXPAND_NS) = range(16)
N_CTR = 16
(P_CPUCT, P_FPU, P_PW_K0, P_PW_C, P_PW_ALPHA, P_PW_ROOT, P_LAM, P_EXPAND_VISITS, P_NTHR, P_HOOK, P_HOOK_DEPTH,
 P_PLAYOUTS, P_MAX_DEPTH, P_STORE, P_PLAYOUT_MAXMOVES) = range(15)
N_PRM = 32
R_STOP, R_TIME, R_SIMS, R_FULL = 1, 2, 3, 4
REASONS = {R_STOP: "stop", R_TIME: "time", R_SIMS: "sims", R_FULL: "full"}

NODE_FIELDS = (("key", np.uint64), ("n", np.int32), ("w", np.float64), ("nx", np.int32), ("wx", np.float64),
               ("vl", np.int32), ("vext", np.float32), ("estart", np.int64), ("nedges", np.int16),
               ("state", np.uint8), ("flags", np.uint8), ("to_play", np.int8))
EDGE_FIELDS = (("e_move", np.int16), ("e_prior", np.float32), ("e_plearn", np.float32), ("e_child", np.int32),
               ("e_n", np.int32))
TREE_FORMAT = "move47-mcts-tree/1"


@dataclass
class MCTSConfig:
    c_puct: float = 1.2             # exploration constant (values in [-1, 1])
    fpu: float = 0.2                # first-play urgency: unvisited child Q = parent Q - fpu
    pw_k0: float = 4.0              # progressive widening: admitted children = k0 + c * N^alpha
    pw_c: float = 2.0
    pw_alpha: float = 0.5
    pw_root: bool = False           # widen at the root too (default: the root admits every move)
    lam: float = 0.5                # V = (1 - lam) * v_ext + lam * z where an external value exists
    beta: float = 0.5               # prior = (1 - beta) * learned + beta * external
    expand_visits: int = 1          # a leaf is expanded once it has this many visits
    n_thr: int = 64                 # expansion hook fires when a node reaches this many visits
    hook_depth: int = 1             # ... and for every node this close to the root (-1: none)
    playouts_per_leaf: int = 1
    max_depth: int = 256
    playout_temperature: float = 1.0
    prior_temperature: float = 1.0
    ladders_playout: bool = False   # ladder features inside playouts (costly; priors always use them)
    ladders_prior: bool = True
    max_nodes: int = 20_000_000
    max_edges: int = 0              # 0 = max_nodes * min(48, size^2 + 1)
    gc_low_water: float = 0.8       # eviction frees the tree down to this fraction of the caps
    observe_min_visits: int = 256   # learner samples: nodes with at least this many visits
    observe_max_samples: int = 256
    early_stop: bool = False        # stop when the most-visited root move can no longer be overtaken
    threads: int = 32
    seed: int = 0
    poll_s: float = 0.005

    @classmethod
    def from_dict(cls, d: dict) -> "MCTSConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class ExpandEvent:
    """A node that reached the expansion threshold (or lies within hook_depth of the root)."""
    key: int
    board: Board
    depth: int                     # below the root at the time of the event
    n: int                         # visits at the time of the event
    path: list[int]                # node keys from the root side down to this node (the last one)

    @property
    def key_hex(self) -> str:
        return f"{self.key:016x}"

    @property
    def position(self) -> Position:
        return self.board.to_position()


class _Arrays:
    def __init__(self, node_cap: int, edge_cap: int):
        self.node_cap, self.edge_cap = int(node_cap), int(edge_cap)
        for name, dt in NODE_FIELDS:
            setattr(self, name, np.empty(self.node_cap, dtype=dt))
        for name, dt in EDGE_FIELDS:
            setattr(self, name, np.empty(self.edge_cap, dtype=dt))
        self.ctr = np.zeros(N_CTR, dtype=np.int64)
        self.prm = np.zeros(N_PRM, dtype=np.float64)

    def pointers(self):
        names = [n for n, _ in NODE_FIELDS] + [n for n, _ in EDGE_FIELDS] + ["ctr", "prm"]
        return (ctypes.c_void_p * len(names))(*[getattr(self, n).ctypes.data for n in names])


def _winrate(v: float) -> float:
    return (1.0 + v) / 2.0


class MCTS:
    """The search engine for one game.  Construct with the root position (Board, Position or None
    for the empty board) and the game's earlier positions' stone hashes (positional superko)."""

    def __init__(self, root: Union[Board, Position, None] = None, *, size: int = 9, komi: float = 7.5,
                 history: Iterable[int] = (), config: Optional[MCTSConfig] = None, weights=None,
                 on_expand: Optional[Callable[[ExpandEvent], None]] = None, learner=None,
                 _arrays: Optional[_Arrays] = None):
        self.cfg = config or MCTSConfig()
        if root is None:
            root = Board(size, komi)
        elif isinstance(root, Position):
            root = Board.from_position(root)
        self.root_board = root.copy()
        size = self.root_board.size
        edge_cap = self.cfg.max_edges or self.cfg.max_nodes * min(48, size * size + 1)
        self.a = _arrays or _Arrays(self.cfg.max_nodes, edge_cap)
        self._t = lib.mc_tree_new(4096)
        if not self._t:
            raise MemoryError("mc_tree_new failed")
        self._ptrs = self.a.pointers()
        lib.mc_tree_attach(self._t, self._ptrs, self.a.node_cap, self.a.edge_cap)
        self.history: list[int] = [int(h) for h in history]
        self.moves: list[Optional[int]] = []          # moves passed to advance()
        self.provider = as_provider(weights)
        self.weights: Optional[Weights] = None
        self._wsig: Optional[tuple] = None
        self.on_expand = on_expand
        self.learner = learner
        self._struct = threading.RLock()                # structural changes: gc, advance, save, set_external
        self._searching = False
        self._stop_req = False
        self._ths: list = []
        self._main_th = lib.mc_thread_new(0xC0FFEE)
        self._ext_pending: dict[int, dict] = {}
        self._ext_info: dict[int, dict] = {}
        self._event_info: "OrderedDict[int, tuple[Board, list[int]]]" = OrderedDict()
        self.searches = 0
        self.gc_runs = 0
        self.frozen = False
        self.log: list[dict] = []
        self._push_params()
        self._refresh_weights()
        self.root = self._node_for(self.root_board) if _arrays is None else 0   # load() sets the root
        self._sync_root()

    # ------------------------------------------------------------ plumbing
    def close(self) -> None:
        if self._t:
            for th in self._ths:
                lib.mc_thread_free(th)
            lib.mc_thread_free(self._main_th)
            lib.mc_tree_free(self._t)
            self._t = None
            self._ths = []

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _push_params(self) -> None:
        c, p = self.cfg, self.a.prm
        p[P_CPUCT], p[P_FPU] = c.c_puct, c.fpu
        p[P_PW_K0], p[P_PW_C], p[P_PW_ALPHA], p[P_PW_ROOT] = c.pw_k0, c.pw_c, c.pw_alpha, float(c.pw_root)
        p[P_LAM], p[P_EXPAND_VISITS], p[P_NTHR] = c.lam, c.expand_visits, c.n_thr
        p[P_HOOK] = 1.0 if self.on_expand is not None else 0.0
        p[P_HOOK_DEPTH] = c.hook_depth
        p[P_PLAYOUTS], p[P_MAX_DEPTH] = max(1, c.playouts_per_leaf), c.max_depth
        p[P_STORE] = 0.0 if self.frozen else 1.0
        p[P_PLAYOUT_MAXMOVES] = 3 * self.root_board.size ** 2

    def _refresh_weights(self) -> bool:
        w = self.provider.get()
        sig = (id(w), w.version, w.digest)
        if sig == self._wsig:
            return False
        for k in ("lam", "beta", "playout_temperature", "prior_temperature"):
            if k in w.params:
                setattr(self.cfg, k, float(w.params[k]))
        self._push_params()
        lib.mc_tree_set_policy(self._t, w.w.ctypes.data, N_FEATURES, self.cfg.playout_temperature,
                               self.cfg.prior_temperature, int(self.cfg.ladders_playout), int(self.cfg.ladders_prior))
        self.weights, self._wsig = w, sig
        return True

    def _node_for(self, b: Board) -> int:
        i = lib.mc_tree_node_for(self._t, b._b)
        if i < 0:
            self.gc()
            i = lib.mc_tree_node_for(self._t, b._b)
            if i < 0:
                raise MemoryError("tree is full and nothing outside the root's subtree can be evicted")
        return int(i)

    def _sync_root(self) -> None:
        lib.mc_tree_set_root(self._t, self.root, self.root_board._b)
        h = np.array(self.history, dtype=np.uint64)
        lib.mc_tree_set_history(self._t, h.ctypes.data, len(h))

    def _expand(self, i: int, b: Board) -> bool:
        return bool(lib.mc_tree_expand(self._t, i, b._b, self._main_th))

    # ------------------------------------------------------------ counters
    @property
    def n_nodes(self) -> int:
        return int(self.a.ctr[C_NODES])

    @property
    def n_edges(self) -> int:
        return int(self.a.ctr[C_EDGES])

    def counters(self) -> dict:
        names = ["nodes", "edges", "sims", "sims_started", "playouts", "full", "events_dropped", "expansions",
                 "superko_skips", "depth_sum", "depth_max", "terminal", "unstored", "events", "playout_ns",
                 "expand_ns"]
        return {n: int(self.a.ctr[i]) for i, n in enumerate(names)}

    # ------------------------------------------------------------ node statistics
    def node_q(self, i: int) -> Optional[float]:
        """Mixed value of node i for its side to move, in [-1, 1] (None if never evaluated)."""
        a = self.a
        n, nx = int(a.n[i]), int(a.nx[i])
        qp = a.w[i] / n if n else None
        if nx:
            qx = a.wx[i] / nx
            return qx if qp is None else (1 - self.cfg.lam) * qx + self.cfg.lam * qp
        return None if qp is None else float(qp)

    def children(self, i: int) -> list[dict]:
        a = self.a
        if a.state[i] != ST_EXPANDED:
            return []
        e0, ne = int(a.estart[i]), int(a.nedges[i])
        out = []
        for e in range(e0, e0 + ne):
            c = int(a.e_child[e])
            q = self.node_q(c) if c >= 0 else None
            m = int(a.e_move[e])
            out.append({"move": None if m < 0 else m, "n": int(a.e_n[e]), "prior": float(a.e_prior[e]),
                        "prior_learned": float(a.e_plearn[e]), "child": c,
                        "q": None if q is None else _winrate(-q)})
        return out

    def find(self, key: Union[int, str]) -> int:
        k = int(key, 16) if isinstance(key, str) else int(key)
        return int(lib.mc_tree_find(self._t, k))

    def pv(self, i: int, max_len: int = 12) -> list[Optional[int]]:
        line, seen = [], {i}
        while len(line) < max_len:
            ch = [c for c in self.children(i) if c["n"] > 0]
            if not ch:
                break
            best = max(ch, key=lambda c: (c["n"], c["prior"]))
            line.append(best["move"])
            i = best["child"]
            if i < 0 or i in seen:
                break
            seen.add(i)
        return line

    def root_stats(self, top: Optional[int] = None, pv_len: int = 10) -> list[dict]:
        size = self.root_board.size
        ch = sorted(self.children(self.root), key=lambda c: (-c["n"], -c["prior"]))
        out = []
        for c in ch[:top] if top else ch:
            pv = [c["move"]] + (self.pv(c["child"], pv_len - 1) if c["child"] >= 0 and c["n"] else [])
            out.append({"move": c["move"], "coord": coord(c["move"], size), "n": c["n"], "q": c["q"],
                        "prior": c["prior"], "prior_learned": c["prior_learned"],
                        "pv": [coord(m, size) for m in pv]})
        return out

    def best_move(self) -> Optional[int]:
        ch = self.children(self.root)
        if not ch:
            return None
        return max(ch, key=lambda c: (c["n"], -1.0 if c["q"] is None else c["q"], c["prior"]))["move"]

    # ------------------------------------------------------------ search
    def stop(self) -> None:
        """Ask a running search to stop (any thread)."""
        self._stop_req = True
        if self._t:
            lib.mc_tree_set_stop(self._t, 1)

    def _drain_events(self) -> int:
        if not self._t:
            return 0
        n = 0
        buf = ctypes.create_string_buffer(BOARD_BYTES)
        path = (ctypes.c_uint64 * EV_PATH_MAX)()
        info = (ctypes.c_int32 * 4)()
        key = ctypes.c_uint64()
        while lib.mc_tree_pop_event(self._t, buf, path, info, ctypes.byref(key)):
            b = Board.__new__(Board)
            b._b = ctypes.create_string_buffer(buf.raw, BOARD_BYTES)
            ev = ExpandEvent(int(key.value), b, int(info[1]), int(info[2]), [int(x) for x in path[:info[3]]])
            self._event_info[ev.key] = (b, ev.path)
            if len(self._event_info) > 200_000:
                self._event_info.popitem(last=False)
            n += 1
            if self.on_expand is not None:
                try:
                    self.on_expand(ev)
                except Exception as e:  # a broken hook must not break the search
                    self.log.append({"hook_error": repr(e)})
        return n

    def _work(self, th, out: list) -> None:
        out.append(int(lib.mc_tree_run(self._t, th)))

    def _can_be_overtaken(self, rate: float, remaining_s: float) -> bool:
        ch = self.children(self.root)
        if len(ch) < 2:
            return False
        ns = sorted((c["n"] for c in ch), reverse=True)
        return ns[0] - ns[1] <= rate * remaining_s

    def search(self, time_s: Optional[float] = None, sims: Optional[int] = None, threads: Optional[int] = None,
               stop: Optional[Callable[[], bool]] = None) -> dict:
        """Search from the root until `time_s` seconds or `sims` simulations (whichever comes first),
        `stop()` returns True, or ``self.stop()`` is called.  Returns the root statistics."""
        if not time_s and not sims:
            raise ValueError("give time_s and/or sims")
        if self.root_board.terminal:
            raise ValueError("the game is over at the root")
        T = int(threads or self.cfg.threads)
        with self._struct:
            if self._searching:
                raise RuntimeError("search() is already running on this engine")
            self._searching = True
        try:
            with self._struct:
                self._stop_req = False
                refreshed = self._refresh_weights()
                self._push_params()
                self._apply_pending()
                if self.frozen or self.n_nodes >= 0.98 * self.a.node_cap or self.n_edges >= 0.98 * self.a.edge_cap:
                    self.gc()
                self._expand(self.root, self.root_board)
            while len(self._ths) < T:
                self._ths.append(lib.mc_thread_new(self.cfg.seed * 1_000_003 + len(self._ths) + 1))
            self.a.ctr[C_SIMS_STARTED] = self.a.ctr[C_DEPTH_MAX] = 0
            ctr0 = self.a.ctr.copy()
            t0 = time.monotonic()
            deadline = time.monotonic() + time_s if time_s else None
            lib.mc_tree_set_limits(self._t, lib.mc_now_ns() + int(time_s * 1e9) if time_s else 0, int(sims or 0))
            lib.mc_tree_set_stop(self._t, 0)
            reasons: list[int] = []
            rounds, early = 0, False
            while True:
                rounds += 1
                self.a.ctr[C_FULL] = 0
                got: list[int] = []
                workers = [threading.Thread(target=self._work, args=(self._ths[i], got), daemon=True)
                           for i in range(T)]
                for w in workers:
                    w.start()
                while any(w.is_alive() for w in workers):
                    self._drain_events()
                    if not self._stop_req and stop is not None and stop():
                        self.stop()
                    if self.cfg.early_stop and deadline and not self._stop_req:
                        el = time.monotonic() - t0
                        done = self.a.ctr[C_SIMS] - ctr0[C_SIMS]
                        if el > 0.2 and done > 100 and not self._can_be_overtaken(done / el, deadline - time.monotonic()):
                            early = True
                            self.stop()
                    time.sleep(self.cfg.poll_s)
                for w in workers:
                    w.join()
                self._drain_events()
                reasons.extend(got)
                if R_FULL in got and not self._stop_req and (not deadline or time.monotonic() < deadline) and \
                        (not sims or self.a.ctr[C_SIMS] - ctr0[C_SIMS] < sims):
                    with self._struct:
                        self.gc()
                    continue
                break
        finally:
            self._searching = False
        el = time.monotonic() - t0
        self.searches += 1
        d = self.a.ctr - ctr0
        nsims = int(d[C_SIMS])
        if early:
            reason = "early_stop"
        elif self._stop_req:
            reason = "stop"
        else:
            reason = next((REASONS[r] for r in (R_SIMS, R_TIME) if r in reasons),
                          REASONS.get(reasons[-1], "?") if reasons else "?")
        stats = self.root_stats()
        best = self.best_move()
        rq = self.node_q(self.root)
        res = {
            "root_key": f"{int(self.a.key[self.root]):016x}", "to_play": self.root_board.to_play,
            "best": coord(best, self.root_board.size) if stats else None, "best_move": best,
            "root_n": int(self.a.n[self.root]), "q": None if rq is None else _winrate(rq),
            "sims": nsims, "playouts": int(d[C_PLAYOUTS]), "time_s": el, "threads": T,
            "sims_per_s": nsims / el if el > 0 else 0.0, "playouts_per_s": int(d[C_PLAYOUTS]) / el if el > 0 else 0.0,
            "depth_mean": float(d[C_DEPTH_SUM]) / nsims if nsims else 0.0, "depth_max": int(self.a.ctr[C_DEPTH_MAX]),
            "nodes": self.n_nodes, "edges": self.n_edges, "gc_rounds": rounds - 1, "frozen": self.frozen,
            "superko_skips": int(d[C_SUPERKO]), "unstored": int(d[C_UNSTORED]), "events": int(d[C_EVENTS]),
            # share of the threads' time spent in playouts / in computing priors for expansions
            "playout_frac": float(d[C_PLAYOUT_NS]) / (el * 1e9 * T) if el > 0 else 0.0,
            "expand_frac": float(d[C_EXPAND_NS]) / (el * 1e9 * T) if el > 0 else 0.0,
            "stop_reason": reason, "weights": self.weights.version if self.weights else None,
            "weights_refreshed": refreshed, "moves": stats,
        }
        self._observe()
        return res

    # ------------------------------------------------------------ learner samples
    def samples(self, min_visits: Optional[int] = None, max_samples: Optional[int] = None) -> list[dict]:
        """Well-visited nodes of the root's subtree (breadth first): board, visit distribution, q, depth."""
        min_n = self.cfg.observe_min_visits if min_visits is None else min_visits
        cap = self.cfg.observe_max_samples if max_samples is None else max_samples
        out, seen = [], {self.root}
        queue = [(self.root, self.root_board, 0)]
        while queue and len(out) < cap:
            i, b, depth = queue.pop(0)
            if self.a.n[i] < min_n or self.a.state[i] != ST_EXPANDED:
                continue
            ch = self.children(i)
            tot = sum(c["n"] for c in ch)
            if tot <= 0:
                continue
            q = self.node_q(i)
            out.append({"position": b, "visit_distribution": {c["move"]: c["n"] / tot for c in ch if c["n"]},
                        "q": None if q is None else _winrate(q), "depth": depth, "n": int(self.a.n[i]),
                        "key": int(self.a.key[i])})
            for c in sorted(ch, key=lambda c: -c["n"]):
                if c["child"] >= 0 and c["child"] not in seen and c["n"] >= min_n:
                    seen.add(c["child"])
                    try:
                        queue.append((c["child"], b.played(c["move"]), depth + 1))
                    except IllegalMove:
                        pass
        return out

    def _observe(self) -> None:
        if self.learner is None:
            return
        fn = getattr(self.learner, "observe", self.learner)
        for s in self.samples():
            fn(position=s["position"], visit_distribution=s["visit_distribution"], q=s["q"], depth=s["depth"])

    # ------------------------------------------------------------ external priors and values
    def set_external(self, node_key: Union[int, str], priors: Optional[dict] = None, value: Optional[float] = None,
                     source: str = "llm", position: Union[Board, Position, None] = None,
                     beta: Optional[float] = None) -> dict:
        """Merge external priors ({move: p}; moves as points, coordinates or None for pass) into the
        node's learned priors, prior = (1 - beta) * learned + beta * external (external normalised
        over its legal moves; each call replaces the previous external priors of the node).  The
        priors are written in place and the node then admits all its moves (no progressive
        widening there: the merged priors steer PUCT).  `value` (winrate in [0, 1] for the node's
        side to move) is stored as the node's v_ext and backed up once through the node and its
        recorded ancestors; Q mixes it as (1 - lam) * Q_ext + lam * Q_playouts.  Safe from any
        thread, also during a search.  A node not in the tree (yet) keeps the request pending; it
        is applied at the start of a later search if the node exists by then."""
        key = int(node_key, 16) if isinstance(node_key, str) else int(node_key)
        req = {"priors": priors, "value": value, "source": source, "position": position, "beta": beta}
        with self._struct:
            return self._apply_external(key, req)

    def _apply_external(self, key: int, req: dict) -> dict:
        i = int(lib.mc_tree_find(self._t, key))
        if i < 0:
            self._ext_pending[key] = req
            return {"applied": False, "pending": True}
        out: dict = {"applied": True, "node": i}
        size = self.root_board.size
        if req.get("priors"):
            st = int(self.a.state[i])
            if st != ST_EXPANDED:
                b = req.get("position")
                if b is None:
                    b = (self._event_info.get(key) or (None, None))[0]
                if isinstance(b, Position):
                    b = Board.from_position(b)
                if b is None or b.key != key or not self._expand(i, b):
                    self._ext_pending[key] = req
                    return {"applied": False, "pending": True, "reason": "node not expanded and no position"}
            mv, pr = [], []
            for m, p in req["priors"].items():
                try:
                    q = to_point(m, size)
                except IllegalMove:
                    continue
                mv.append(-1 if q is None else q)
                pr.append(float(p))
            mva = np.array(mv, dtype=np.int16)
            pra = np.array(pr, dtype=np.float64)
            beta = self.cfg.beta if req.get("beta") is None else float(req["beta"])
            out["matched"] = int(lib.mc_tree_merge_priors(self._t, i, mva.ctypes.data, pra.ctypes.data, len(mva), beta))
        if req.get("value") is not None:
            v = 2.0 * float(req["value"]) - 1.0
            path = (self._event_info.get(key) or (None, [key]))[1]
            if not path or path[-1] != key:
                path = [key]
            pa = np.array(path, dtype=np.uint64)
            out["backed_up"] = int(lib.mc_tree_backup_ext(self._t, pa.ctypes.data, len(pa), v, 1))
        self._ext_info[key] = {"source": req.get("source"), "value": req.get("value"),
                               "n_priors": len(req.get("priors") or {})}
        return out

    def _apply_pending(self) -> None:
        for key in list(self._ext_pending):
            if lib.mc_tree_find(self._t, key) >= 0:
                req = self._ext_pending.pop(key)
                self._apply_external(key, req)

    # ------------------------------------------------------------ reuse
    def advance(self, move: Move) -> int:
        """Play `move` at the root: the child becomes the root with all statistics of its subtree
        (created if it is not in the tree).  Raises IllegalMove (also for positional superko)."""
        with self._struct:
            if self._searching:
                raise RuntimeError("advance() during a search")
            p = to_point(move, self.root_board.size)
            nb = self.root_board.played(p)
            if p is not None and (nb.stone_hash in self.history or nb.stone_hash == self.root_board.stone_hash):
                raise IllegalMove("superko", f"{coord(p, nb.size)} repeats an earlier position")
            child, edge = -1, -1
            a = self.a
            if a.state[self.root] == ST_EXPANDED:
                e0, ne = int(a.estart[self.root]), int(a.nedges[self.root])
                hit = np.flatnonzero(a.e_move[e0:e0 + ne] == (-1 if p is None else p))
                if len(hit):
                    edge = e0 + int(hit[0])
                    child = int(a.e_child[edge])
            if child < 0:
                child = self._node_for(nb)
                if edge >= 0 and a.state[self.root] == ST_EXPANDED and int(a.e_move[edge]) == (-1 if p is None else p):
                    a.e_child[edge] = child
            self.history.append(self.root_board.stone_hash)
            self.root, self.root_board = child, nb
            self.moves.append(p)
            if self.frozen:
                self.frozen = False
                self._push_params()
            self._sync_root()
            return child

    def set_root(self, board: Union[Board, Position], history: Iterable[int]) -> int:
        """Jump to an arbitrary position (e.g. after an arena resync); the tree is kept, so a
        position already in it keeps its statistics."""
        with self._struct:
            b = Board.from_position(board) if isinstance(board, Position) else board.copy()
            self.root = self._node_for(b)
            self.root_board = b
            self.history = [int(h) for h in history]
            self._sync_root()
            return self.root

    # ------------------------------------------------------------ eviction
    def gc(self, low_water: Optional[float] = None) -> dict:
        """Evict the least-visited nodes outside the root's subtree until the tree uses at most
        `low_water` (default cfg.gc_low_water) of both caps, then compact the arrays.  The root's
        subtree is never evicted; if it alone fills 90% of a cap the tree is frozen (new leaves are
        evaluated by playouts but neither stored nor expanded) until advance() moves the root."""
        with self._struct:
            a = self.a
            low = self.cfg.gc_low_water if low_water is None else low_water
            nn = self.n_nodes
            mark = np.zeros(max(nn, 1), dtype=np.uint8)
            lib.mc_tree_mark(self._t, self.root, mark.ctypes.data)
            reach = mark[:nn].astype(bool)
            per_edges = np.where(a.state[:nn] == ST_EXPANDED, a.nedges[:nn], 0).astype(np.int64)
            n_reach, e_reach = int(reach.sum()), int(per_edges[reach].sum())
            node_budget, edge_budget = int(low * a.node_cap), int(low * a.edge_cap)
            keep = reach.copy()
            if n_reach < node_budget and e_reach < edge_budget:
                outside = np.flatnonzero(~reach)
                order = outside[np.argsort(-a.n[outside].astype(np.int64), kind="stable")]
                cn = n_reach + np.arange(1, len(order) + 1)
                ce = e_reach + np.cumsum(per_edges[order])
                k = int(np.count_nonzero((cn <= node_budget) & (ce <= edge_budget)))
                keep[order[:k]] = True
            evicted = nn - int(keep.sum())
            self._compact(keep)
            self.gc_runs += 1
            self.frozen = n_reach >= 0.9 * a.node_cap or e_reach >= 0.9 * a.edge_cap
            self._push_params()
            info = {"before": nn, "reachable": n_reach, "evicted": evicted, "after": self.n_nodes,
                    "edges_after": self.n_edges, "frozen": self.frozen}
            self.log.append({"gc": info})
            return info

    def _compact(self, keep: np.ndarray) -> None:
        a = self.a
        nn = len(keep)
        idx = np.flatnonzero(keep)
        k = len(idx)
        new_of = np.full(nn, -1, dtype=np.int64)
        new_of[idx] = np.arange(k)
        exp = a.state[idx] == ST_EXPANDED
        lens = np.where(exp, a.nedges[idx], 0).astype(np.int64)
        starts = np.where(exp, a.estart[idx], 0).astype(np.int64)
        total = int(lens.sum())
        new_starts = np.cumsum(lens) - lens
        gather = np.repeat(starts - new_starts, lens) + np.arange(total, dtype=np.int64)
        for name, _ in EDGE_FIELDS:
            arr = getattr(a, name)
            arr[:total] = arr[gather]
        ch = a.e_child[:total].astype(np.int64)
        a.e_child[:total] = np.where(ch >= 0, new_of[np.maximum(ch, 0)], -1)
        for name, _ in NODE_FIELDS:
            arr = getattr(a, name)
            arr[:k] = arr[idx]
        a.estart[:k] = np.where(exp, new_starts, -1)
        a.state[:k] = np.where(a.state[:k] == ST_EXPANDING, ST_NEW, a.state[:k])
        a.vl[:k] = 0
        a.ctr[C_NODES], a.ctr[C_EDGES] = k, total
        self.root = int(new_of[self.root])
        if not lib.mc_tree_rebuild_tt(self._t):
            raise MemoryError("rebuilding the transposition table failed")
        self._sync_root()

    # ------------------------------------------------------------ persistence
    def save(self, path: Union[str, Path]) -> Path:
        """Write the whole tree (arrays, root, history, config, weights) atomically to `path`
        (.npz); load() resumes from it mid-game."""
        path = Path(path)
        with self._struct:
            if self._searching:
                raise RuntimeError("save() during a search")
            a, nn, ne = self.a, self.n_nodes, self.n_edges
            arrays = {name: getattr(a, name)[:nn] for name, _ in NODE_FIELDS}
            arrays.update({name: getattr(a, name)[:ne] for name, _ in EDGE_FIELDS})
            arrays["ctr"] = a.ctr
            arrays["history"] = np.array(self.history, dtype=np.uint64)
            meta = {"format": TREE_FORMAT, "spec": spec_id(), "config": asdict(self.cfg), "root": self.root,
                    "root_board": self.root_board.to_dict(), "moves": self.moves,
                    "weights": self.weights.to_json() if self.weights else None,
                    "ext_info": {f"{k:016x}": v for k, v in self._ext_info.items()},
                    "searches": self.searches, "frozen": self.frozen, "saved_at": time.time()}
            arrays["meta"] = np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.tmp{os.getpid()}.npz")
            np.savez(tmp, **arrays)
            os.replace(tmp, path)
            return path

    @classmethod
    def load(cls, path: Union[str, Path], config: Optional[MCTSConfig] = None, weights=None,
             on_expand=None, learner=None, **overrides) -> "MCTS":
        """Resume a saved tree.  The saved config is used unless `config` is given (keyword
        overrides apply on top); the saved weights are used unless `weights` is given."""
        with np.load(Path(path)) as z:
            meta = json.loads(bytes(z["meta"]).decode())
            if meta.get("format") != TREE_FORMAT:
                raise ValueError(f"not a tree file: {meta.get('format')!r}")
            if meta.get("spec") != spec_id():
                raise ValueError("the tree was saved with a different feature spec")
            cfg = config or MCTSConfig.from_dict(meta["config"])
            for k, v in overrides.items():
                setattr(cfg, k, v)
            nn, ne = len(z["key"]), len(z["e_move"])
            root_board = Board.from_dict(meta["root_board"])
            edge_cap = cfg.max_edges or cfg.max_nodes * min(48, root_board.size ** 2 + 1)
            arrays = _Arrays(max(cfg.max_nodes, nn + 1), max(edge_cap, ne + 1))
            for name, _ in NODE_FIELDS:
                getattr(arrays, name)[:nn] = z[name]
            for name, _ in EDGE_FIELDS:
                getattr(arrays, name)[:ne] = z[name]
            arrays.ctr[:] = z["ctr"]
            history = [int(h) for h in z["history"]]
        arrays.vl[:nn] = 0
        arrays.state[:nn] = np.where(arrays.state[:nn] == ST_EXPANDING, ST_NEW, arrays.state[:nn])
        arrays.ctr[C_NODES], arrays.ctr[C_EDGES], arrays.ctr[C_FULL] = nn, ne, 0
        if weights is None and meta.get("weights"):
            weights = Weights.from_json(meta["weights"])
        eng = cls(root_board, history=history, config=cfg, weights=weights, on_expand=on_expand, learner=learner,
                  _arrays=arrays)
        if not lib.mc_tree_rebuild_tt(eng._t):
            raise MemoryError("rebuilding the transposition table failed")
        eng.root = int(meta["root"])
        eng.moves = [None if m is None else int(m) for m in meta.get("moves", [])]
        eng.searches = int(meta.get("searches", 0))
        eng.frozen = bool(meta.get("frozen", False))
        eng._ext_info = {int(k, 16): v for k, v in (meta.get("ext_info") or {}).items()}
        eng._push_params()
        eng._sync_root()
        if int(arrays.key[eng.root]) != root_board.key:
            raise ValueError("corrupt tree file: the root key does not match the root position")
        return eng

    # ------------------------------------------------------------ misc
    def table(self, top: int = 10) -> str:
        """The root table as text (move, visits, winrate, prior, PV)."""
        rows = [f"{'move':>5} {'visits':>8} {'winrate':>8} {'prior':>7}  pv"]
        for m in self.root_stats(top):
            q = "-" if m["q"] is None else f"{m['q']:.3f}"
            rows.append(f"{m['coord']:>5} {m['n']:>8} {q:>8} {m['prior']:>7.4f}  {' '.join(m['pv'])}")
        return "\n".join(rows)
