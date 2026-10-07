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

Model values (node move47::mcts-calib):
  * a node without an external value of its own is compared with its siblings through a stand-in
    external value (``standin``): the mean external value of its evaluated siblings, else the
    negated value of its parent (recursively the nearest evaluated ancestor, sign by side to move);
  * external values enter calibrated, ``sigmoid(calib_a * logit(v) + calib_b)`` (identity by
    default; a weight file's params ``calib_a`` / ``calib_b`` or ``set_calibration`` change it, and
    the values already in the tree are re-calibrated);
  * root breadth: ``set_root_breadth({move: "candidate" | "explore"})`` gives model-proposed root
    moves minimum visits (``root_min_frac`` of the root's visits, at least ``root_min_floor``) and
    ``root_noise`` mixes uniform noise into the root priors (v1 root breadth);
  * ``rearm(key)`` lets a node's hook fire again, ``in_subtree(key)`` asks whether a node is reachable
    from the current root, ``searching`` tells whether a search is running.
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

import math

from ._lib import BOARD_BYTES, EV_PATH_MAX, N_FEATURES, lib
from .board import Board, Move, to_point
from .features import spec_id
from .weights import Weights, as_provider

# keep in sync with csrc/tree.c
ST_NEW, ST_EXPANDING, ST_EXPANDED, ST_TERMINAL = 0, 1, 2, 3
FL_HOOKED, FL_EXT, FL_EVCHILD = 1, 2, 4
(C_NODES, C_EDGES, C_SIMS, C_SIMS_STARTED, C_PLAYOUTS, C_FULL, C_EV_DROPPED, C_EXPANSIONS, C_SUPERKO,
 C_DEPTH_SUM, C_DEPTH_MAX, C_TERMINAL, C_UNSTORED, C_EVENTS, C_PLAYOUT_NS, C_EXPAND_NS) = range(16)
N_CTR = 16
(P_CPUCT, P_FPU, P_PW_K0, P_PW_C, P_PW_ALPHA, P_PW_ROOT, P_LAM, P_EXPAND_VISITS, P_NTHR, P_HOOK, P_HOOK_DEPTH,
 P_PLAYOUTS, P_MAX_DEPTH, P_STORE, P_PLAYOUT_MAXMOVES, P_STANDIN, P_ROOT_NOISE, P_ROOT_MIN_FRAC, P_ROOT_MIN_FLOOR,
 P_ROOT_MIN_FRAC_X, P_ROOT_MIN_FLOOR_X) = range(21)
STANDIN = {"off": 0, "ancestor": 1, "siblings": 2}
BREADTH = {"candidate": 1, "explore": 2}
BREADTH_NAME = {v: k for k, v in BREADTH.items()}
N_PRM = 32
R_STOP, R_TIME, R_SIMS, R_FULL = 1, 2, 3, 4
REASONS = {R_STOP: "stop", R_TIME: "time", R_SIMS: "sims", R_FULL: "full"}

NODE_FIELDS = (("key", np.uint64), ("n", np.int32), ("w", np.float64), ("nx", np.int32), ("wx", np.float64),
               ("vl", np.int32), ("vext", np.float32), ("estart", np.int64), ("nedges", np.int16),
               ("state", np.uint8), ("flags", np.uint8), ("to_play", np.int8))
EDGE_FIELDS = (("e_move", np.int16), ("e_prior", np.float32), ("e_plearn", np.float32), ("e_child", np.int32),
               ("e_n", np.int32))
TREE_FORMAT = "move47-mcts-tree/1"
CALIB_EPS = 1e-4


def apply_calibration(v: float, a: float, b: float) -> float:
    """sigmoid(a * logit(v) + b) for a winrate v (v clipped to [1e-4, 1 - 1e-4]); identity for a=1, b=0."""
    if a == 1.0 and b == 0.0:
        return float(v)
    v = min(1.0 - CALIB_EPS, max(CALIB_EPS, float(v)))
    z = a * math.log(v / (1.0 - v)) + b
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


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
    standin: str = "siblings"       # external value for a node without one: "siblings" (mean of its evaluated
                                    # siblings, else from the parent), "ancestor" (from the parent only), "off"
    root_noise: float = 0.0         # root priors p -> (1 - x) p + x / moves (v1 uses 0.25; the play CLIs pass it)
    root_min_frac: float = 0.01     # root breadth: a "candidate" root move gets at least this share of the
    root_min_floor: int = 64        # root's visits, and at least root_min_floor visits (v1 root_min_visits)
    root_min_frac_explore: float = 0.005   # ... an "explore" move (unconventional, scout) at least this share
    root_min_floor_explore: int = 32       # ... and at least this many (v1 root_min_visits_explore)
    calib_a: float = 1.0            # external values enter as sigmoid(calib_a * logit(v) + calib_b)
    calib_b: float = 0.0
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


# extra sample fields passed to a learner whose observe() takes **kwargs (the hook's four
# arguments stay the contract; the extras let a learner tell the playout part of q from the
# external part, e.g. to fit lam)
_OBSERVE_EXTRA = ("n", "key", "q_playout", "n_ext", "q_ext")


def _accepts_extra(fn) -> bool:
    import inspect
    try:
        return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return False


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
        self._root_breadth: dict[Optional[int], int] = {}
        self._root_gen = 0                               # bumped when the root or the node indices change
        self._mark: Optional[tuple] = None               # (root_gen, time, mark array, nodes marked)
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
        if c.standin not in STANDIN:
            raise ValueError(f"standin must be one of {sorted(STANDIN)}, not {c.standin!r}")
        p[P_STANDIN] = STANDIN[c.standin]
        p[P_ROOT_NOISE] = max(0.0, min(1.0, c.root_noise))
        p[P_ROOT_MIN_FRAC], p[P_ROOT_MIN_FLOOR] = c.root_min_frac, c.root_min_floor
        p[P_ROOT_MIN_FRAC_X], p[P_ROOT_MIN_FLOOR_X] = c.root_min_frac_explore, c.root_min_floor_explore

    def _refresh_weights(self) -> bool:
        w = self.provider.get()
        sig = (id(w), w.version, w.digest)
        if sig == self._wsig:
            return False
        for k in ("lam", "beta", "playout_temperature", "prior_temperature"):
            if k in w.params:
                setattr(self.cfg, k, float(w.params[k]))
        if "calib_a" in w.params or "calib_b" in w.params:
            self.set_calibration(float(w.params.get("calib_a", 1.0)), float(w.params.get("calib_b", 0.0)))
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
        """Edges of node i: move, visits, priors, child index, q (mixed winrate for the mover at i),
        q_playout (playouts only), v_ext (the child's own external value as a winrate for the mover
        at i; None if it has none), evaluated (has its own external value), n_ext."""
        a = self.a
        if a.state[i] != ST_EXPANDED:
            return []
        e0, ne = int(a.estart[i]), int(a.nedges[i])
        out = []
        for e in range(e0, e0 + ne):
            c = int(a.e_child[e])
            q = self.node_q(c) if c >= 0 else None
            m = int(a.e_move[e])
            nc = int(a.n[c]) if c >= 0 else 0
            ve = float(a.vext[c]) if c >= 0 else math.nan
            out.append({"move": None if m < 0 else m, "n": int(a.e_n[e]), "prior": float(a.e_prior[e]),
                        "prior_learned": float(a.e_plearn[e]), "child": c,
                        "q": None if q is None else _winrate(-q),
                        "q_playout": _winrate(-float(a.w[c]) / nc) if nc else None,
                        "v_ext": None if math.isnan(ve) else _winrate(-ve), "evaluated": not math.isnan(ve),
                        "n_ext": int(a.nx[c]) if c >= 0 else 0})
        return out

    def ext_value(self, i: int) -> Optional[float]:
        """Node i's own external value (calibrated) as a winrate for its side to move, None if none."""
        v = float(self.a.vext[i])
        return None if math.isnan(v) else _winrate(v)

    def standin_value(self, i: int, sv: Optional[float] = None) -> Optional[float]:
        """The stand-in external value (in [-1, 1], side to move at i's children) that selection uses
        for i's children without an external value (csrc/tree.c select_edge): the mean over i's
        children that have one, else -sv where sv is i's own external value (default: its backed-up
        mean, which is what the search uses at the root)."""
        mode = STANDIN[self.cfg.standin]
        if mode == 0:
            return None
        a = self.a
        if mode >= 2 and int(a.flags[i]) & FL_EVCHILD and a.state[i] == ST_EXPANDED:
            e0, ne = int(a.estart[i]), int(a.nedges[i])
            ch = a.e_child[e0:e0 + ne]
            ch = ch[ch >= 0]
            nx = a.nx[ch]
            m = nx > 0
            if m.any():
                return float(np.mean(a.wx[ch[m]] / nx[m]))
        if sv is None and a.nx[i] > 0:
            sv = float(a.wx[i]) / int(a.nx[i])
        return None if sv is None else -float(sv)

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

    def _root_rows(self) -> list[dict]:
        """The root's children with the winrate the selection compares, by visits (ties: that winrate,
        then the prior; best_move and root_stats share this order)."""
        ch = self.children(self.root)
        S = self.standin_value(self.root)
        lam = self.cfg.lam
        for c in ch:
            c["q_raw"], c["standin"] = c["q"], False
            if S is not None and c["child"] >= 0 and c["n_ext"] == 0 and c["q_playout"] is not None:
                qc = 2.0 * (1.0 - c["q_playout"]) - 1.0          # the child's playout value, its side to move
                c["q"], c["standin"] = _winrate(-((1.0 - lam) * S + lam * qc)), True
        ch.sort(key=lambda c: (-c["n"], -(-1.0 if c["q"] is None else c["q"]), -c["prior"]))
        return ch

    def root_stats(self, top: Optional[int] = None, pv_len: int = 10) -> list[dict]:
        """The root's moves by visits.  q is the winrate the selection compares (for a move without an
        external value: its playouts mixed with the stand-in value), q_raw without the stand-in,
        q_playout playouts only, v_ext the move's own (calibrated) external value, evaluated whether it
        has one, standin whether q used the stand-in, breadth its root-breadth class."""
        size = self.root_board.size
        ch = self._root_rows()
        breadth = self._root_breadth
        out = []
        for c in ch[:top] if top else ch:
            pv = [c["move"]] + (self.pv(c["child"], pv_len - 1) if c["child"] >= 0 and c["n"] else [])
            mv = -1 if c["move"] is None else c["move"]
            out.append({"move": c["move"], "coord": coord(c["move"], size), "n": c["n"], "q": c["q"],
                        "q_raw": c["q_raw"], "q_playout": c["q_playout"], "v_ext": c["v_ext"],
                        "evaluated": c["evaluated"], "standin": c["standin"],
                        "breadth": BREADTH_NAME.get(breadth.get(mv)),
                        "prior": c["prior"], "prior_learned": c["prior_learned"],
                        "pv": [coord(m, size) for m in pv]})
        return out

    def best_move(self) -> Optional[int]:
        """The most-visited root move (ties: the higher selection winrate, then the prior)."""
        ch = self._root_rows()
        return ch[0]["move"] if ch else None

    @property
    def searching(self) -> bool:
        """True while search() runs (any thread may ask)."""
        return self._searching

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
            n_i, nx_i = int(self.a.n[i]), int(self.a.nx[i])
            out.append({"position": b, "visit_distribution": {c["move"]: c["n"] / tot for c in ch if c["n"]},
                        "q": None if q is None else _winrate(q), "depth": depth, "n": n_i,
                        "key": int(self.a.key[i]),
                        # the two parts of q separately (playouts only; external values backed up)
                        "q_playout": _winrate(float(self.a.w[i]) / n_i) if n_i else None,
                        "n_ext": nx_i, "q_ext": _winrate(float(self.a.wx[i]) / nx_i) if nx_i else None})
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
        extra = _accepts_extra(fn)
        for s in self.samples():
            kw = {k: s[k] for k in _OBSERVE_EXTRA} if extra else {}
            fn(position=s["position"], visit_distribution=s["visit_distribution"], q=s["q"], depth=s["depth"], **kw)

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
        info = self._ext_info.get(key) or {}
        info.update(source=req.get("source"), n_priors=len(req.get("priors") or {}) or info.get("n_priors", 0))
        if req.get("value") is not None:
            raw = float(req["value"])
            val = self.calibrate(raw) if req.get("calibrate", True) else raw
            path = (self._event_info.get(key) or (None, [key]))[1]
            if not path or path[-1] != key:
                path = [key]
            if len(path) == 1 and key != int(self.a.key[self.root]) and self._is_root_child(i):
                path = [int(self.a.key[self.root]), key]       # the parent is known: siblings see the value
            pa = np.array(path, dtype=np.uint64)
            out["backed_up"] = int(lib.mc_tree_backup_ext(self._t, pa.ctypes.data, len(pa), 2.0 * val - 1.0, 1))
            out["value"] = val
            # every value backed up through this node (a recalibration corrects each once)
            vals = info.get("values") or []
            vals.append({"raw": raw, "value": val, "path": [int(k) for k in path],
                         "calibrated": bool(req.get("calibrate", True))})
            info.update(value=val, value_raw=raw, values=vals)
        self._ext_info[key] = info
        return out

    def _is_root_child(self, i: int) -> bool:
        a = self.a
        if a.state[self.root] != ST_EXPANDED:
            return False
        e0, ne = int(a.estart[self.root]), int(a.nedges[self.root])
        return bool((a.e_child[e0:e0 + ne] == i).any())

    # ------------------------------------------------------------ calibration of external values
    def calibrate(self, v: float) -> float:
        """The winrate an external value v enters the tree with (the current calibration map)."""
        return apply_calibration(v, self.cfg.calib_a, self.cfg.calib_b)

    def set_calibration(self, a: float, b: float) -> int:
        """Use sigmoid(a * logit(v) + b) for external values from now on, and re-calibrate the values
        already in the tree: each node's own value is replaced and the sums along the path through
        which it was backed up are corrected by the difference (values that later simulations
        carried up from an evaluated leaf keep their old calibration).  Returns the values changed."""
        if not a > 0:
            raise ValueError("the calibration slope must be positive (a monotone map)")
        with self._struct:
            self.cfg.calib_a, self.cfg.calib_b = float(a), float(b)
            changed = 0
            for key, info in self._ext_info.items():
                vals = [e for e in (info.get("values") or []) if e.get("calibrated", True)]
                if not vals:
                    continue
                own = 2.0 * self.calibrate(info["values"][-1]["raw"]) - 1.0 \
                    if info["values"][-1].get("calibrated", True) else 2.0 * info["values"][-1]["value"] - 1.0
                for ent in vals:
                    new = self.calibrate(ent["raw"])
                    if abs(new - ent["value"]) < 1e-9:
                        continue
                    pa = np.array(ent["path"] or [key], dtype=np.uint64)
                    lib.mc_tree_adjust_ext(self._t, pa.ctypes.data, len(pa), 2.0 * (new - ent["value"]), own)
                    ent["value"] = new
                    changed += 1
                info["value"] = info["values"][-1]["value"]
            return changed

    def _apply_pending(self) -> None:
        for key in list(self._ext_pending):
            if lib.mc_tree_find(self._t, key) >= 0:
                req = self._ext_pending.pop(key)
                self._apply_external(key, req)

    # ------------------------------------------------------------ root breadth, hooks, subtree
    def set_root_breadth(self, moves: dict) -> int:
        """Minimum visits at the root (v1 root breadth): {move: "candidate" | "explore"} (moves as
        points, coordinates or None for pass).  A "candidate" (a move the model proposed) is selected
        first while its visits are below max(root_min_floor, root_min_frac * root visits), an
        "explore" move (unconventional, scout) below the *_explore pair.  Replaces the previous set;
        advance() and set_root() clear it.  Returns the number of classed moves."""
        size = self.root_board.size
        cls: dict[int, int] = {}
        for m, c in (moves or {}).items():
            try:
                p = to_point(m, size)
            except IllegalMove:
                continue
            k = BREADTH[c] if isinstance(c, str) else int(c)
            if k:
                p = -1 if p is None else p
                cls[p] = min(cls.get(p, k), k)      # both: "candidate" (the larger minimum)
        mv = np.array(list(cls), dtype=np.int16)
        cl = np.array([cls[p] for p in cls], dtype=np.uint8)
        self._root_breadth = dict(cls)
        return int(lib.mc_tree_set_root_cls(self._t, mv.ctypes.data, cl.ctypes.data, len(mv)))

    @property
    def root_breadth(self) -> dict:
        """{move (None = pass): "candidate" | "explore"} at the current root."""
        return {(None if p < 0 else p): BREADTH_NAME[k] for p, k in self._root_breadth.items()}

    def _clear_root_breadth(self) -> None:
        self._root_breadth = {}
        lib.mc_tree_set_root_cls(self._t, None, None, 0)

    def rearm(self, key: Union[int, str]) -> bool:
        """Let the expansion hook fire again for this node, e.g. after the request it raised was
        dropped: it fires on the node's next visit if the node is still within hook_depth of the root
        or has n_thr visits.  False if the node is not in the tree."""
        with self._struct:
            i = self.find(key)
            if i < 0:
                return False
            lib.mc_tree_rearm(self._t, i)
            return True

    def subtree_mask(self) -> np.ndarray:
        """mark[i] = 1 for the nodes reachable from the current root (exact at the time of the call;
        safe during a search)."""
        with self._struct:
            nn = self.n_nodes
            mark = np.zeros(max(nn, 1), dtype=np.uint8)
            lib.mc_tree_reach(self._t, self.root, mark.ctypes.data, nn)
            self._mark = (self._root_gen, time.monotonic(), mark, nn)
            return mark[:nn]

    def in_subtree(self, key: Union[int, str], max_age: float = 2.0) -> bool:
        """Whether the node is reachable from the current root through the tree's edges (any move
        order).  A reachability mark is computed once per root and reused: a node it contains stays
        in the subtree until the root moves (edges are never removed in between); a node created
        after the mark was created by a simulation from this root; a node the mark does not contain
        is checked again on a fresh mark if the mark is older than max_age seconds."""
        with self._struct:
            i = self.find(key)
            if i < 0:
                return False
            m = self._mark
            if m is None or m[0] != self._root_gen:
                self.subtree_mask()
                m = self._mark
            if i >= m[3]:
                return True
            if m[2][i]:
                return True
            if time.monotonic() - m[1] <= max_age:
                return False
            self.subtree_mask()
            m = self._mark
            return True if i >= m[3] else bool(m[2][i])

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
            self._root_gen += 1
            self._clear_root_breadth()
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
            self._root_gen += 1
            self._clear_root_breadth()
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
        self._root_gen += 1
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
                    "root_breadth": {str(p): k for p, k in self._root_breadth.items()},
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
        rb = {int(p): int(k) for p, k in (meta.get("root_breadth") or {}).items()}
        if rb:
            eng._root_breadth = rb
            mv, cl = np.array(list(rb), dtype=np.int16), np.array(list(rb.values()), dtype=np.uint8)
            lib.mc_tree_set_root_cls(eng._t, mv.ctypes.data, cl.ctypes.data, len(mv))
        eng._push_params()
        eng._sync_root()
        if int(arrays.key[eng.root]) != root_board.key:
            raise ValueError("corrupt tree file: the root key does not match the root position")
        return eng

    # ------------------------------------------------------------ misc
    def table(self, top: int = 10) -> str:
        """The root table as text (move, visits, winrate, prior, PV; with external values also the
        move's own model value, '*' when its winrate uses the stand-in, and its root-breadth class)."""
        stats = self.root_stats(top)
        ext = any(m["evaluated"] or m["standin"] for m in stats)
        rows = [f"{'move':>5} {'visits':>8} {'winrate':>8} {'prior':>7}" + (f" {'model':>6}" if ext else "") + "  pv"]
        for m in stats:
            q = "-" if m["q"] is None else f"{m['q']:.3f}" + ("*" if m["standin"] else "")
            mod = ""
            if ext:
                mod = " " + (f"{m['v_ext']:6.3f}" if m["v_ext"] is not None else f"{'-':>6}")
            rows.append(f"{m['coord']:>5} {m['n']:>8} {q:>8} {m['prior']:>7.4f}{mod}  {' '.join(m['pv'])}"
                        + (f"  [{m['breadth']}]" if m.get("breadth") else ""))
        return "\n".join(rows)
