"""OnlineLearner: Heuristic Learning for MCTS v2 (MISSION.md section 5, node move47::mcts-hl).

The engine and the play loop talk to it through five methods and one attribute:

    learner = OnlineLearner(run_dir, base=None, **cfg)
    eng = MCTS(board, weights=learner.provider, learner=learner)    # provider.get() -> Weights
    learner.observe(position, visit_distribution, q, depth)          # the engine calls it after a search
    learner.observe_external(position, source, priors, value)        # an LLM evaluation of a node arrived
    learner.observe_game(result, our_color)                          # a finished game, +1 / -1 for us
    learner.update() -> dict                                         # refit after a decision

What ``update()`` refits (targets come only from our own search and game results):

(a) the policy weights shared by the tree prior and the playout policy: a linear softmax over the
    legal moves fitted to the visit distributions of well-visited nodes (expert iteration),
    weighted by visits, L2 toward the current version (``l2``) and toward the base version
    (``l2_base``, the anchor that keeps the versions from drifting) (fit.py).  The candidate
    replaces the current version only if its cross-entropy on the held-out nodes (a fixed split
    by node key) is lower, it keeps every tactical guard (regression/guards.json) and its
    cross-entropy on the tracked regression positions is not higher than its parent's by more than
    ``reg_tol`` nor than the base's by more than ``reg_tol_base``; otherwise the old version stays.
(b) a value model (value.py), fitted to the backed-up q of well-visited nodes and to finished
    game results, measured against the short playout estimate on held-out nodes.  It is stored
    (state.json) and reported; the engine does not use it (see the README section).
(c) lam and beta (mix.py) from nodes with an external evaluation of source ``mix_source``,
    compared with the node's later, deeper search; written as params.lam / params.beta of the
    next version once ``mix_min_pairs`` pairs exist (until then the engine's defaults stay).
(d) the calibration of external values (mix.fit_calib, node move47::mcts-calib): a monotone map
    sigmoid(a * logit(v) + b) from the model's value v of a node to the node's playout Q after a
    deeper search (its sample's q_playout with at least ``calib_min_visits`` visits), shrunk toward
    the identity with ``calib_n0`` pseudo-pairs; written as params.calib_a / params.calib_b once
    ``calib_min_pairs`` pairs exist; lam is then fitted on the calibrated values (what the engine
    mixes).  ``fit_calibration()`` refits it on demand (e.g. during a long search).

Learning from model reasoning plus search (node move47::mcts-llm-hl):

(e) hybrid targets: samples observed while the learner's ``mode`` is "hybrid" (the play loop sets it
    when model sessions feed the tree) carry that flag; the held-out split used by every gate is
    restricted to them once there are enough (``hybrid``; False = the code-only path).
(f) distillation: at nodes the model evaluated (observe_external), the learned prior is also fitted
    to the model's candidate priors, with a relative weight chosen every ``distill_every`` updates
    from ``distill_grid`` by held-out cross-entropy on hybrid-search targets, so the model's
    knowledge reaches nodes it never saw.  ``model_agreement()`` measures the learned prior against
    the model's priors at held-out evaluated nodes.
(g) model-written rules: weights may carry rules (mcts.rules, gotree.heurdsl) as extra prior
    features.  ``consider(answer, provenance)`` gates a heuristic job's proposals: a new rule is
    added to the current weights with only its own weight fitted (starting from the model's) and is
    kept only if that predicts the held-out hybrid targets better than the current weights (gain >
    ``rule_min_gain`` nats, the lower end of a cluster-bootstrap interval above 0, at least
    ``rule_min_heldout`` held-out positions matched), the tactical guards hold and the regression
    set does not get worse; a nudge if the nudged weights do better on the held-out targets.  An
    accepted rule's model-proposed weight is its anchor (l2_base pulls toward it), an accepted
    nudge shifts the anchor of its feature; the next update() refits everything jointly.
    Everything lands in the heuristics book (book.py).

Everything persists in ``run_dir`` so learning continues across moves, games and processes:

    state.json          current version, counters, the value model and the last mix fit
    weights-vNNN.json   every accepted version (v000 = the base); a normal weight file
                        (mcts.weights.Weights.load reads it) plus an "hl" block: parent version
                        and digest, sample counts, train / held-out / regression metrics, guards
    samples.jsonl       the sample ring buffer (append-only, compacted; latest per node key)
    external.jsonl      external evaluations;  games.jsonl  game results
    value-inputs.jsonl  cached value-model inputs;  updates.jsonl  one line per update()
    heuristics-book.{json,md}, book/  the heuristics book;  proposals.jsonl  one line per gated proposal
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Union

import numpy as np

from gotree.position import BLACK, WHITE

from .._lib import N_FEATURES
from ..features import feature_index, move_priors
from ..policy import Policy
from ..weights import Weights, load_default
from .book import Book
from .data import (PASS, PolicyRows, Sample, as_board, censor_rows, heldout, is_test, limit_blas_threads, norm_dist,
                   policy_rows, rule_hit_rows, target_vector, with_rule_hits)
from .fit import PolicySet, fit_policy
from .mix import PRIOR, apply_calib, fit_beta, fit_calib, fit_lam
from .regression import check_guards, load_guards, regression_metrics
from .value import ValueModel, fit_value, inputs_for, value_metrics

FORMAT = "move47-mcts-hl/1"

DEFAULTS = dict(
    capacity=30_000,          # sample ring buffer (distinct node keys; the latest observation wins)
    heldout_frac=0.2,         # share of node keys held out (fixed by key)
    min_visits=0,             # extra filter on top of the engine's observe_min_visits
    weight_ref=256,           # sample weight = min(weight_cap, sqrt(n / weight_ref)), at least 1
    weight_cap=8.0,
    censor=False,             # below the root, fit only over the visited moves (data.censor_rows)
    l2=1e-3,                  # pull toward the current version (smooths the step between versions)
    l2_base=1e-3,             # pull toward the base version: the global anchor (0 = none; then the
                              # versions drift without bound, see the README)
    max_iter=80,
    fit_time=12.0,            # seconds for the L-BFGS fit
    max_train=16_000,         # training samples per fit (a uniform subset of the buffer's training split)
    min_train=200,
    min_heldout=50,
    min_gain=1e-4,            # held-out CE must fall by more than this (nats)
    reg_tol=0.02,             # regression-set CE may not rise by more than this over the parent (nats)
    reg_tol_base=0.05,        # ... nor by more than this over the base version (nats)
    playout_temp="keep",      # "keep": the playout policy uses the shared weights at the parent's playout
                              # temperature; "match": refit that temperature so that the playout policy's
                              # mean entropy on the training positions equals the base version's (it lost
                              # an A/B against "keep", see the README)
    guards=True,
    guard_anchor=True,        # the 'top' guards are also training rows (one-hot on the guard move)
    guard_weight=8.0,         # ... each with this sample weight (weight_cap = the best-visited node)
    guard_boost=8.0,          # if a guard is still lost: refit with the anchors this much heavier (2x max)
    value=True,
    value_k=16,               # playouts per value-model input
    value_l2=1e-3,
    value_new_per_update=600,
    value_min=200,
    game_weight=0.5,          # weight of a game-result label relative to a node's q label
    mix_source="llm",
    mix_min_pairs=20,
    mix_n0=10.0,              # shrinkage toward 0.5 (pseudo-pairs)
    mix_playouts=32,          # playouts for the playout estimate at an external evaluation
    mix_min_ratio=2.0,        # the deep observation needs this many times the visits at the evaluation
    mix_min_visits=256,
    calib=True,               # (d) fit the calibration of external values
    calib_n0=10.0,            # shrinkage toward the identity (pseudo-pairs)
    calib_min_pairs=5,
    calib_min_visits=1024,    # the deeper search: the node's sample has at least this many visits
    # (e, f) hybrid targets and distillation of the model's priors (node move47::mcts-llm-hl)
    test_frac=0.0,            # share of node keys kept out of training AND of every gate (an independent hash):
                              # the final evaluation's test split (the play loops use 0.1 in hybrid runs)
    hybrid=True,              # held-out targets from hybrid-search samples once min_heldout of them exist;
                              # False: the code-only path (held-out from every sample, no distillation)
    distill=True,             # fit the prior also to the model's candidate priors at evaluated nodes
    distill_grid="0,0.1,0.3,1,3",   # relative weights of the distillation term tried (held-out selection)
    distill_every=5,          # re-select the weight every this many updates
    distill_min=20,           # training records (model evaluations with priors) needed
    distill_fit_time=4.0,     # seconds per fit while selecting the weight
    ext_value_weight=0.5,     # the model's calibrated values as soft labels of the value model (b)
    # (g) model-written rules from heuristic jobs
    heur_fit_time=6.0,        # seconds per fit when a proposal is gated
    rule_min_gain=1e-4,       # held-out CE gain (nats) of the refit with the rule over the refit without it
    rule_min_heldout=5,       # held-out positions where the rule matches a legal move ...
    rule_min_searches=2,      # ... from at least this many searches (decisions)
    rule_ci=0.9,              # the lower end of this cluster-bootstrap interval of the gain must exceed 0
    nudge_min_gain=1e-4,
    broad_frac=0.2,           # a rule matching more than this share of the legal moves of training positions
    max_rules=48,             # active rules at most
    threads=8,                # value-input playouts in update()
    blas_threads=1,           # cap on numpy's OpenBLAS pool (process-wide), None = leave it
    seed=0,
    flush_every=2000,
    guards_path=None,
    regression_path=None,
)


def _color(c: str) -> str:
    c = str(c).strip().upper()
    if c in ("B", "BLACK", "X"):
        return BLACK
    if c in ("W", "WHITE", "O"):
        return WHITE
    raise ValueError(f"unknown colour {c!r}")


def _our_result(result, our_color: str) -> float:
    """+1 / -1 / 0 from our side, from a number or an SGF-style result string."""
    if isinstance(result, str):
        r = result.strip().upper()
        if r in ("0", "DRAW", "JIGO", "D"):
            return 0.0
        if r[:2] in ("B+", "W+"):
            winner = BLACK if r[0] == "B" else WHITE
            return 1.0 if winner == our_color else -1.0
        try:
            result = float(r)
        except ValueError:
            raise ValueError(f"cannot read game result {result!r}") from None
    v = float(result)
    return 1.0 if v > 0 else -1.0 if v < 0 else 0.0


class LearnerProvider:
    """The weights provider of an OnlineLearner: get() returns the current accepted version."""

    def __init__(self, learner: "OnlineLearner"):
        self._learner = learner

    def get(self) -> Weights:
        return self._learner.current_weights()


class OnlineLearner:
    def __init__(self, run_dir: Union[str, Path], base: Union[Weights, str, Path, None] = None, **cfg):
        unknown = set(cfg) - set(DEFAULTS)
        if unknown:
            raise TypeError(f"unknown OnlineLearner option(s): {sorted(unknown)}")
        self.cfg = {**DEFAULTS, **cfg}
        if self.cfg["blas_threads"]:
            limit_blas_threads(int(self.cfg["blas_threads"]))
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.samples: "OrderedDict[int, Sample]" = OrderedDict()
        self.external: list[dict] = []
        self.games: dict[int, tuple[float, str]] = {}
        self._rows: dict[int, tuple] = {}            # sid -> (PolicyRows, target)
        self._vin: dict[int, np.ndarray] = {}        # sid -> value inputs
        self._pending: dict[str, list[str]] = {"samples": [], "external": [], "games": [], "value-inputs": []}
        self._lines_written = 0
        self._state_sig = None
        self.value_model: Optional[ValueModel] = None
        self.mix: dict = {"lam": {"status": "default", "pairs": 0}, "beta": {"status": "default", "pairs": 0},
                          "calib": {"status": "default", "pairs": 0, "a": 1.0, "b": 0.0}}
        self._guards = load_guards(Path(self.cfg["guards_path"])) if self.cfg["guards_path"] else None
        self._reg_path = Path(self.cfg["regression_path"]) if self.cfg["regression_path"] else None
        self._base_policy: Optional[Policy] = None
        self._anchor_rows: Optional[list] = None
        self._anchor_boards: list = []
        # mcts-llm-hl: hybrid mode, the anchor of nudged features and rules, distillation, rule hits
        self.mode = "code"                           # "hybrid" while model sessions feed the searches
        self.anchor: dict = {"features": {}, "rules": {}}
        self.distill_state: dict = {"lam": None, "at_update": None, "table": None}
        self._hits: dict = {}                        # cache key -> {rule id: row indices it matches}
        self._rs_cache: dict = {}
        self._ext_rows: dict = {}                    # external record index -> (rows, target)
        self._fit_lock = threading.RLock()           # update() and consider() never interleave
        self.book = Book(self.run_dir)
        self.resumed = (self.run_dir / "state.json").exists()
        if self.resumed:
            self._load()
        else:
            self._init(base)
        self.provider = LearnerProvider(self)

    @classmethod
    def resume(cls, run_dir: Union[str, Path], **overrides) -> "OnlineLearner":
        """The learner of an existing run dir with the options it was run with (state.json), plus
        overrides (for reports: the same test split and targets as the run)."""
        st = json.loads((Path(run_dir) / "state.json").read_text())
        saved = {k: v for k, v in (st.get("cfg") or {}).items() if k in DEFAULTS}
        return cls(run_dir, **{**saved, **overrides})

    # ------------------------------------------------------------------ persistence
    def _path(self, name: str) -> Path:
        return self.run_dir / name

    @contextmanager
    def _flock(self):
        with open(self._path(".lock"), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    @contextmanager
    def _gate(self):
        """Serialises writers of the heuristics book across processes (consider() as a whole, and the
        book notes of update()).  Lock order: gate, file lock, thread lock."""
        with open(self._path(".gate.lock"), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _sync_disk(self) -> bool:
        """Under the file lock: adopt what another process sharing this run dir committed since we last
        looked (a newer current version, the anchor, the counters), so this process never numbers a
        version from a stale count nor rolls state.json back.  True if the current version changed."""
        try:
            d = json.loads(self._path("state.json").read_text())
        except (OSError, ValueError):
            return False
        changed = False
        if int(d.get("version_no", -1)) > self.version_no or (
                int(d.get("version_no", -1)) == self.version_no and d.get("current") != self.current_file):
            self._load_current(d)
            self.anchor = d.get("anchor") or self.anchor
            changed = True
        self.updates = max(self.updates, int(d.get("updates", 0)))
        self.accepted = max(self.accepted, int(d.get("accepted", 0)))
        self.game = max(self.game, int(d.get("game", 0)))
        return changed

    def _write_version(self, make) -> tuple[str, Weights, dict]:
        """Allocate the next version number and create its file exclusively (never overwriting one
        another process wrote); `make(n)` returns (Weights, doc) for version n.  Call under the file lock
        after _sync_disk()."""
        while True:
            n = self.version_no + 1
            name = f"weights-v{n:03d}.json"
            p = self._path(name)
            if p.exists():
                self.version_no = n
                continue
            w, doc = make(n)
            tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
            tmp.write_text(json.dumps(doc, indent=1, default=float) + "\n")
            try:
                os.link(tmp, p)                    # atomic and exclusive: fails if the name exists
            except FileExistsError:
                tmp.unlink(missing_ok=True)
                self.version_no = n
                continue
            tmp.unlink(missing_ok=True)
            self.version_no = n
            return name, w, doc

    def _write_json(self, name: str, obj) -> None:
        p = self._path(name)
        tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
        tmp.write_text(json.dumps(obj, indent=1, default=float) + "\n")
        os.replace(tmp, p)

    def _init(self, base) -> None:
        if base is None:
            w = load_default()
        elif isinstance(base, Weights):
            w = base
        else:
            w = Weights.load(base)
        self.base = Weights.from_json(w.to_json())  # as the file will hold it
        self.version_no = 0
        self.next_sid = 0
        self.game = 0
        self.updates = 0
        self.accepted = 0
        doc = self.base.to_json()
        doc["hl"] = {"version_no": 0, "role": "base", "digest": self.base.digest, "created": time.time()}
        self._write_json("weights-v000.json", doc)
        self.current = self.base
        self.current_file = "weights-v000.json"
        self._save_state()

    def _state(self) -> dict:
        return {"format": FORMAT, "current": self.current_file, "current_version": self.current.version,
                "current_digest": self.current.digest, "version_no": self.version_no, "next_sid": self.next_sid,
                "game": self.game, "updates": self.updates, "accepted": self.accepted,
                "base": {"version": self.base.version, "digest": self.base.digest},
                "value_model": None if self.value_model is None else self.value_model.to_json(),
                "mix": self.mix, "anchor": self.anchor, "distill": self.distill_state,
                "book_version": self.book.version,
                "cfg": {k: v for k, v in self.cfg.items()}, "saved_at": time.time()}

    def _save_state(self) -> None:
        self._write_json("state.json", self._state())
        st = self._path("state.json").stat()
        self._state_sig = (st.st_mtime_ns, st.st_size, st.st_ino)

    def _read_jsonl(self, name: str):
        p = self._path(name)
        if not p.exists():
            return
        with open(p) as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    yield json.loads(ln)
                except json.JSONDecodeError:      # a torn last line after a crash
                    continue

    def _load(self) -> None:
        st = json.loads(self._path("state.json").read_text())
        if st.get("format") != FORMAT:
            raise ValueError(f"{self.run_dir}: not a learner run dir ({st.get('format')!r})")
        self.base = Weights.load(self._path("weights-v000.json"))
        self._load_current(st)
        self.next_sid = int(st["next_sid"])
        self.game = int(st["game"])
        self.updates = int(st.get("updates", 0))
        self.accepted = int(st.get("accepted", 0))
        self.mix = st.get("mix") or self.mix
        self.anchor = st.get("anchor") or self.anchor
        self.distill_state = st.get("distill") or self.distill_state
        cap = self.cfg["capacity"]
        n = 0
        for d in self._read_jsonl("samples.jsonl"):
            s = Sample.from_json(d)
            self.samples.pop(s.key, None)
            self.samples[s.key] = s
            if len(self.samples) > cap:
                self.samples.popitem(last=False)
            n += 1
            self.next_sid = max(self.next_sid, s.sid + 1)
        self._lines_written = n
        self.external = list(self._read_jsonl("external.jsonl"))
        for d in self._read_jsonl("games.jsonl"):
            self.games[int(d["game"])] = (float(d["result"]), d["our_color"])
        live = {s.sid for s in self.samples.values()}
        for d in self._read_jsonl("value-inputs.jsonl"):
            if d["sid"] in live:
                self._vin[int(d["sid"])] = np.array(d["x"], dtype=np.float64)
        if st.get("value_model"):
            self.value_model = ValueModel.from_json(st["value_model"])

    def _load_current(self, st: dict) -> None:
        self.current_file = st["current"]
        self.version_no = int(st["version_no"])
        self.current = Weights.load(self._path(self.current_file))

    def flush(self) -> None:
        """Append the buffered samples / evaluations / results to their files."""
        with self._lock:
            pend = {k: v for k, v in self._pending.items() if v}
            for k in self._pending:
                self._pending[k] = []
        if not pend:
            return
        with self._flock():
            for name, lines in pend.items():
                with open(self._path(f"{name}.jsonl"), "a") as f:
                    f.write("\n".join(lines) + "\n")
            self._lines_written += len(pend.get("samples", []))
            if self._lines_written > 3 * self.cfg["capacity"]:
                self._compact()

    def _compact(self) -> None:
        with self._lock:
            lines = [json.dumps(s.to_json(), separators=(",", ":")) for s in self.samples.values()]
            vlines = [json.dumps({"sid": sid, "x": [round(float(v), 6) for v in x]}) for sid, x in self._vin.items()]
        for name, ls in (("samples.jsonl", lines), ("value-inputs.jsonl", vlines)):
            p = self._path(name)
            tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
            tmp.write_text("\n".join(ls) + ("\n" if ls else ""))
            os.replace(tmp, p)
        self._lines_written = len(lines)

    # ------------------------------------------------------------------ the provider
    def current_weights(self) -> Weights:
        """The current accepted version (re-read when another process has advanced the run dir)."""
        try:
            st = self._path("state.json").stat()
            sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return self.current
        if sig != self._state_sig:
            with self._lock:
                try:
                    d = json.loads(self._path("state.json").read_text())
                    if d.get("current") != self.current_file or int(d.get("version_no", -1)) != self.version_no:
                        self._load_current(d)
                        self.anchor = d.get("anchor") or self.anchor
                        if int(d.get("book_version", 0)) != self.book.version:
                            self.book = Book(self.run_dir)
                    self._state_sig = sig
                except (OSError, ValueError, KeyError):
                    pass
        return self.current

    # ------------------------------------------------------------------ hooks
    def observe(self, position, visit_distribution: dict, q: Optional[float], depth: int, **extra) -> None:
        """One well-visited node after a search (the engine's learner hook).  Optional extras
        from mcts.tree: n (visits), key, q_playout, n_ext, q_ext."""
        b = as_board(position)
        pi = norm_dist(visit_distribution, b.size)
        if not pi:
            return
        n = int(extra.get("n") or 0)
        if n and n < self.cfg["min_visits"]:
            return
        key = int(extra.get("key") or b.key)
        qp = extra.get("q_playout")
        hy = bool(extra.get("hybrid", self.mode == "hybrid"))
        with self._lock:
            s = Sample(self.next_sid, key, b.to_dict(), pi, None if q is None else float(q),
                       None if qp is None else float(qp), n, int(depth), self.game, self.current.version, time.time(),
                       hy, bool(extra.get("ext_priors")), self.updates)
            self.next_sid += 1
            old = self.samples.pop(key, None)
            if old is not None:
                self._rows.pop(old.sid, None)
                self._vin.pop(old.sid, None)
                self._hits.pop(old.sid, None)
            self.samples[key] = s
            while len(self.samples) > self.cfg["capacity"]:
                _, ev = self.samples.popitem(last=False)
                self._rows.pop(ev.sid, None)
                self._vin.pop(ev.sid, None)
                self._hits.pop(ev.sid, None)
            self._pending["samples"].append(json.dumps(s.to_json(), separators=(",", ":")))
            big = len(self._pending["samples"]) >= self.cfg["flush_every"]
        if big:
            self.flush()

    def observe_external(self, position, source: str, priors: Optional[dict], value: Optional[float],
                         **extra) -> dict:
        """An external evaluation (source e.g. "llm") of a node arrived: priors {move: p} (points,
        coordinates or None / "pass"), value = winrate for the side to move (as set_external).
        Recorded with what the learned side said at that moment (the current version's priors
        and a playout estimate; pass q_playout= / n= to use the node's own instead) for the lam /
        beta fit."""
        b = as_board(position)
        w = self.current_weights()
        T = float(w.params.get("prior_temperature", 1.0))
        pl = move_priors(b, w, temperature=T, ladders=True)
        zp = extra.get("q_playout")
        if zp is None and value is not None and not b.terminal:
            pol = Policy(w)
            sc = pol.playouts(b, int(self.cfg["mix_playouts"]), seed=int(self.next_sid) + 17)
            sgn = 1.0 if b.to_play == BLACK else -1.0
            zp = float((1.0 + np.mean(np.sign(sgn * sc))) / 2.0)
        rec = {"key": f"{b.key:016x}", "board": b.to_dict(), "source": str(source),
               "value": None if value is None else float(value),
               "priors": {str(k): round(v, 6) for k, v in norm_dist(priors, b.size).items()},
               "p_learned": {str(PASS if m is None else m): round(p, 7) for m, p in pl.items()},
               "z_playout": zp, "n_at": int(extra.get("n") or 0), "version": w.version, "t": time.time(),
               "game": self.game, "dec": self.updates}
        with self._lock:
            self.external.append(rec)
            self._pending["external"].append(json.dumps(rec, separators=(",", ":")))
        return {"recorded": True, "key": rec["key"]}

    def observe_game(self, result: Union[float, str], our_color: str) -> None:
        """A finished game: result +1 (we won) / -1 (we lost) / 0, our colour B/W (X/O).  Labels
        the game's samples (side to move's view) for the value fit and starts the next game.  An
        SGF-style result string ("B+3.5", "W+R", "0", "Draw") is accepted too and read from our
        colour's side."""
        c = _color(our_color)
        res = _our_result(result, c)
        with self._lock:
            self.games[self.game] = (res, c)
            self._pending["games"].append(json.dumps({"game": self.game, "result": res, "our_color": c,
                                                      "given": str(result), "t": time.time()}))
            self.game += 1
        self.flush()
        with self._flock():
            self._sync_disk()
            self._save_state()

    # ------------------------------------------------------------------ fitting helpers
    def _weight(self, s: Sample) -> float:
        if s.n <= 0:
            return 1.0
        return float(min(self.cfg["weight_cap"], max(1.0, (s.n / self.cfg["weight_ref"]) ** 0.5)))

    def _rows_of(self, s: Sample):
        r = self._rows.get(s.sid)
        if r is None:
            rows = policy_rows(_board_of(s))
            t = target_vector(rows, s.pi)
            if t is not None and self.cfg["censor"] and s.depth > 0:
                rows, t = censor_rows(rows, t)
            r = (rows, t)
            self._rows[s.sid] = r
        return r

    # ------------------------------------------------------------------ rule columns (mcts-llm-hl)
    def _ruleset(self, rules: list):
        from ..rules import RuleSet
        k = tuple(r["canonical"] for r in rules)
        rs = self._rs_cache.get(k)
        if rs is None:
            if len(self._rs_cache) > 64:
                self._rs_cache.clear()
            rs = self._rs_cache[k] = RuleSet(rules)
        return rs

    def _with_rules(self, key, rows: PolicyRows, board, rules: list) -> PolicyRows:
        """rows plus the columns of `rules` (hits cached per row set and rule id)."""
        if not rules:
            return rows
        have = self._hits.setdefault(key, {})
        missing = [r for r in rules if r["id"] not in have]
        if missing:
            per = rule_hit_rows(self._ruleset(missing), as_board(board), rows.moves)
            for r, h in zip(missing, per):
                have[r["id"]] = h
        return with_rule_hits(rows, have, {r["id"]: j for j, r in enumerate(rules)})

    def drop_rule_hits(self, rid: str) -> None:
        for h in self._hits.values():
            h.pop(rid, None)

    def _policy_set(self, samples: list[Sample], extra: Optional[list[tuple]] = None,
                    extra_weight: float = 0.0, rules: Optional[list] = None, distill: Optional[list] = None,
                    lam: float = 0.0) -> Optional[PolicySet]:
        """Policy rows of the samples (plus `extra` rows, the guard anchors, each with extra_weight),
        with the columns of `rules`.  With distillation rows and lam > 0 the search part keeps a total
        weight of 1 and the distillation part gets lam (lam / count per row)."""
        rules = list(rules or [])
        rows, tg, ws = [], [], []
        for s in samples:
            r, t = self._rows_of(s)
            if t is None:
                continue
            rows.append(self._with_rules(s.sid, r, s.board, rules))
            tg.append(t)
            ws.append(self._weight(s))
        for i, (r, t) in enumerate(extra or []):
            if rules and i < len(self._anchor_boards):
                r = self._with_rules(("a", i), r, self._anchor_boards[i], rules)
            rows.append(r)
            tg.append(t)
            ws.append(extra_weight)
        if not rows:
            return None
        nfeat = N_FEATURES + len(rules)
        if distill and lam > 0:
            tot = float(sum(ws))
            ws = [w / tot for w in ws]
            for key, r, bd, t in distill:
                rows.append(self._with_rules(key, r, bd, rules))
                tg.append(t)
                ws.append(lam / len(distill))
            return PolicySet(rows, tg, ws, nfeat=nfeat, normalize=False)
        return PolicySet(rows, tg, ws, nfeat=nfeat)

    @staticmethod
    def _weights_from(wfull: np.ndarray, like: Weights, version: str, params: Optional[dict] = None,
                      rules: Optional[list] = None) -> Weights:
        rules = like.rules if rules is None else rules
        return Weights(wfull[:N_FEATURES], version, dict(like.params if params is None else params), like.description,
                       list(rules), wfull[N_FEATURES:N_FEATURES + len(rules)])

    def _anchor_full(self, rules: list) -> np.ndarray:
        """The anchor l2_base pulls toward: the base weights with the accepted nudges, and each rule's
        model-proposed weight."""
        w = self.base.w.copy()
        idx = feature_index()
        for f, d in (self.anchor.get("features") or {}).items():
            if f in idx:
                w[idx[f]] += float(d)
        wr = np.array([float((self.anchor.get("rules") or {}).get(r["id"], 0.0)) for r in rules])
        return np.concatenate([w, wr]) if rules else w

    # ------------------------------------------------------------------ (f) distillation data
    def test_split(self) -> list[Sample]:
        """The samples of the test split (never trained on, never used by a gate); hybrid ones only
        when ``hybrid`` is on and there are any."""
        with self._lock:
            ss = [s for s in self.samples.values() if is_test(s.key, self.cfg["test_frac"])]
        hy = [s for s in ss if s.hy]
        return hy if (self.cfg["hybrid"] and hy) else ss

    def test_records(self) -> list:
        """Model evaluations with priors (latest per node) of the test split."""
        latest: dict = {}
        with self._lock:
            ext = list(enumerate(self.external))
        for i, e in ext:
            if e.get("source") == self.cfg["mix_source"] and e.get("priors") and is_test(int(e["key"], 16),
                                                                                        self.cfg["test_frac"]):
                latest[e["key"]] = (i, e)
        return list(latest.values())

    def _distill_records(self) -> tuple[list, list]:
        """(training, held-out) model evaluations with priors (the latest per node), split by node key
        (test-split nodes are left out)."""
        latest: dict = {}
        with self._lock:
            ext = list(enumerate(self.external))
        for i, e in ext:
            if e.get("source") == self.cfg["mix_source"] and e.get("priors"):
                latest[e["key"]] = (i, e)
        f, tf = self.cfg["heldout_frac"], self.cfg["test_frac"]
        tr, ho = [], []
        for i, e in latest.values():
            k = int(e["key"], 16)
            if tf > 0 and is_test(k, tf):
                continue
            (ho if heldout(k, f) else tr).append((i, e))
        return tr, ho

    def _distill_rows(self, recs: list) -> list:
        out = []
        for i, e in recs:
            r = self._ext_rows.get(i)
            if r is None:
                rows = policy_rows(as_board(e["board"]))
                t = target_vector(rows, {int(k): float(v) for k, v in e["priors"].items()})
                r = self._ext_rows[i] = (rows, t)
            if r[1] is not None:
                out.append((("e", i), r[0], e["board"], r[1]))
        return out

    def model_agreement(self, weights: Weights, recs: Optional[list] = None) -> Optional[dict]:
        """The learned prior against the model's candidate priors at evaluated nodes (default: the
        held-out ones): CE(model, learned), top-1 agreement, the learned prior's mass on the model's
        candidates, and the mean rank of the model's top move under the learned prior."""
        if recs is None:
            recs = self._distill_records()[1]
        rows = self._distill_rows(recs)
        if not rows:
            return None
        ps = PolicySet([self._with_rules(k, r, bd, weights.rules) for k, r, bd, _ in rows], [t for *_, t in rows],
                       [1.0] * len(rows), nfeat=N_FEATURES + len(weights.rules))
        T = float(weights.params.get("prior_temperature", 1.0))
        m = ps.metrics(weights.full, T)
        logp, p = ps._logp(weights.full, T)
        st = ps.starts
        mass, ranks = [], []
        for k in range(ps.S):
            a, b = st[k], st[k + 1]
            t, lp = ps.tgt[a:b], logp[a:b]
            mass.append(float(np.exp(lp[t > 0]).sum()))
            top = int(np.argmax(t))
            ranks.append(int((lp > lp[top]).sum()) + 1)
        return {"n": ps.S, "ce": m["ce_mean"], "top1": m["top1"], "mass_on_model_moves": float(np.mean(mass)),
                "model_top_rank_mean": float(np.mean(ranks)), "model_top_in_top3": float(np.mean(np.array(ranks) <= 3))}

    def _game_label(self, s: Sample) -> Optional[float]:
        g = self.games.get(s.game)
        if g is None:
            return None
        res, col = g
        return res if s.to_play == col else -res

    def split(self) -> tuple[list[Sample], list[Sample]]:
        """(training, held-out) by the fixed key split.  With ``hybrid`` on, the held-out side keeps
        only hybrid-search samples once at least min_heldout of them exist."""
        with self._lock:
            ss = [s for s in self.samples.values() if not s.n or s.n >= self.cfg["min_visits"]]
        f = self.cfg["heldout_frac"]
        if self.cfg["test_frac"] > 0:
            ss = [s for s in ss if not is_test(s.key, self.cfg["test_frac"])]
        ho = [s for s in ss if heldout(s.key, f)]
        tr = [s for s in ss if not heldout(s.key, f)]
        if self.cfg["hybrid"]:
            hy = [s for s in ho if s.hy]
            if len(hy) >= self.cfg["min_heldout"]:
                ho = hy
        return tr, ho

    # ------------------------------------------------------------------ (a) policy
    def _anchors(self) -> list[tuple]:
        """The 'top' guards as training rows: a one-hot target on the guard move(s)."""
        if self._anchor_rows is None:
            from .regression import guard_board, load_guards as _lg
            from gotree.position import point
            rows = []
            for g in (self._guards if self._guards is not None else _lg()):
                if g["kind"] != "top":
                    continue
                b = guard_board(g)
                r = policy_rows(b)
                pi = {PASS if point(m, b.size) is None else point(m, b.size): 1.0 for m in g["moves"]}
                t = target_vector(r, pi)
                if t is not None:
                    rows.append((r, t))
                    self._anchor_boards.append(b.to_dict())
            self._anchor_rows = rows
        return self._anchor_rows

    def _fit_candidate(self, tr: list[Sample], ho: list[Sample], parent: Weights, T: float):
        """Fit, then gate: held-out CE must fall, every guard must hold, the regression set must not
        get worse by more than reg_tol.  With guard anchors on, the 'top' guards are training rows
        (weight guard_weight each); if a guard is still lost the fit is redone with the anchors
        weighted guard_boost times more (twice at most).  The parameters are the feature weights and
        the weights of the parent's model-written rules; with distillation the model's priors at the
        training nodes it evaluated are a second term (mcts-llm-hl)."""
        cfg = self.cfg
        rules = parent.rules
        hos = self._policy_set(ho, rules=rules)
        m_ho0 = hos.metrics(parent.full, T)
        anchors = self._anchors() if (cfg["guards"] and cfg["guard_anchor"]) else []
        aw = float(cfg["guard_weight"])
        tries = []
        l2p, l2b = float(cfg["l2"]), float(cfg["l2_base"])
        center = (l2p * parent.full + l2b * self._anchor_full(rules)) / (l2p + l2b) if l2p + l2b > 0 else parent.full
        lam, d_tr, dsel = self._distill_weight(tr, hos, parent, T, center, l2p + l2b, anchors, aw)
        for attempt in range(3 if anchors else 1):
            trs = self._policy_set(tr, anchors, aw, rules=rules, distill=d_tr, lam=lam)
            w_new, info = fit_policy(trs, center, l2p + l2b, T, cfg["max_iter"], cfg["fit_time"], start=parent.full)
            cand = self._weights_from(w_new, parent, "candidate")
            g = check_guards(cand, self._guards) if cfg["guards"] else {"passed": True, "failures": []}
            tries.append({"anchor_weight": aw if anchors else 0.0, "guards_failed": g["failures"],
                          "iters": info["iters"], "time_s": round(info["time_s"], 2)})
            if g["passed"] or not anchors:
                break
            aw *= float(cfg["guard_boost"])
        trs_plain = self._policy_set(tr, rules=rules)
        m_tr0, m_tr1 = trs_plain.metrics(parent.full, T), trs_plain.metrics(w_new, T)
        m_ho1 = hos.metrics(w_new, T)
        gain = m_ho0["ce"] - m_ho1["ce"]
        info_d = {"fit": info, "train": {"parent": m_tr0, "candidate": m_tr1},
                  "heldout": {"parent": m_ho0, "candidate": m_ho1}, "gain": gain,
                  "dw_max": float(np.abs(w_new - parent.full).max()), "attempts": tries,
                  "heldout_hybrid": sum(1 for x in ho if x.hy), "rules": len(rules),
                  "distill": {"lam": lam, "rows": len(d_tr or []), **({"selection": dsel} if dsel else {})}}
        checks: dict = {"guards": {"passed": g["passed"], "failures": g["failures"]}} if cfg["guards"] else {}
        fails = []
        if gain <= cfg["min_gain"]:
            fails.append(f"held-out CE did not improve ({gain:+.5f} nats)")
        if not g["passed"]:
            fails.append(f"tactical guard(s) lost: {', '.join(g['failures'])}")
        fails += self._regression_fails(cand, parent, checks)
        ok = not fails
        reason = f"held-out CE improved ({gain:+.5f} nats)" if ok else "; ".join(fails)
        return w_new, info_d, checks, ok, reason

    def _regression_fails(self, cand: Weights, parent: Weights, checks: dict) -> list[str]:
        fails = []
        rp = regression_metrics(parent, self._reg_path)
        if rp is not None:
            rc = regression_metrics(cand, self._reg_path)
            rb = regression_metrics(self.base, self._reg_path)
            checks["regression"] = {"parent": rp, "candidate": rc, "base": rb}
            if rc["ce"] > rp["ce"] + self.cfg["reg_tol"]:
                fails.append(f"regression-set CE rose {rc['ce'] - rp['ce']:+.4f} > {self.cfg['reg_tol']} over the parent")
            if rc["ce"] > rb["ce"] + self.cfg["reg_tol_base"]:
                fails.append(f"regression-set CE {rc['ce'] - rb['ce']:+.4f} over the base > {self.cfg['reg_tol_base']}")
        return fails

    def _distill_weight(self, tr, hos, parent: Weights, T: float, center, l2: float, anchors, aw):
        """(lam, training distillation rows, selection table or None).  The weight is re-selected from
        distill_grid by held-out CE on the (hybrid) search targets every distill_every updates."""
        cfg = self.cfg
        if not (cfg["hybrid"] and cfg["distill"]):
            return 0.0, None, None
        recs, _ = self._distill_records()
        if len(recs) < cfg["distill_min"]:
            return 0.0, None, None
        d_tr = self._distill_rows(recs)
        st = self.distill_state
        due = st.get("lam") is None or st.get("at_update") is None or \
            self.updates - int(st["at_update"]) >= int(cfg["distill_every"])
        table = None
        if due:
            grid = [float(x) for x in str(cfg["distill_grid"]).split(",") if x.strip()]
            table = []
            for lam in grid:
                ps = self._policy_set(tr, anchors, aw, rules=parent.rules, distill=d_tr, lam=lam)
                w, info = fit_policy(ps, center, l2, T, cfg["max_iter"], cfg["distill_fit_time"], start=parent.full)
                cand = self._weights_from(w, parent, "lam-trial")
                agr = self.model_agreement(cand)
                table.append({"lam": lam, "heldout_ce": hos.metrics(w, T)["ce"], "iters": info["iters"],
                              "agreement_ce": None if agr is None else agr["ce"],
                              "agreement_top1": None if agr is None else agr["top1"]})
            best = min(table, key=lambda r: r["heldout_ce"])
            self.distill_state = {"lam": best["lam"], "at_update": self.updates, "table": table,
                                  "records": len(recs)}
        return float(self.distill_state["lam"]), d_tr, table

    def _match_playout_temperature(self, tr: list[Sample], w: np.ndarray) -> float:
        """Playout temperature for w that keeps the base version's playout entropy (on the 400 most
        recent training positions)."""
        ps = self._policy_set(sorted(tr, key=lambda s: s.sid)[-400:])
        tb = float(self.base.params.get("playout_temperature", 1.0))
        return ps.match_playout_temperature(w, ps.playout_entropy(self.base.w, tb))

    # ------------------------------------------------------------------ update
    def update(self) -> dict:
        """Refit after a decision.  Returns the metrics and the version now current (a new one, or
        the old one with the reason it was kept)."""
        with self._fit_lock:
            return self._update()

    def _update(self) -> dict:
        t0 = time.monotonic()
        self.flush()
        cfg = self.cfg
        parent = self.current_weights()
        T = float(parent.params.get("prior_temperature", 1.0))
        tr, ho = self.split()
        if len(tr) > cfg["max_train"]:     # a uniform subset: the same distribution as the held-out nodes
            rng = np.random.default_rng(cfg["seed"] * 1_000_003 + self.updates)
            pick = np.sort(rng.choice(len(tr), size=cfg["max_train"], replace=False))
            tr = [tr[i] for i in pick]
        out: dict = {"update": self.updates + 1, "parent": parent.version, "samples": len(self.samples),
                     "train_n": len(tr), "heldout_n": len(ho), "game": self.game}
        policy_info, checks = None, {}
        if len(tr) < cfg["min_train"] or len(ho) < cfg["min_heldout"]:
            policy_ok, reason = False, f"not enough samples (train {len(tr)} < {cfg['min_train']} or " \
                                       f"held-out {len(ho)} < {cfg['min_heldout']})"
            w_new = parent.full
        else:
            w_new, policy_info, checks, policy_ok, reason = self._fit_candidate(tr, ho, parent, T)
        out["policy"] = policy_info
        out["checks"] = checks

        # (c) lam / beta
        mix = self._fit_mix()
        out["mix"] = mix
        params = dict(parent.params)
        mix_changed = False
        for k in ("lam", "beta"):
            if mix[k].get("status") == "fitted" and mix[k]["pairs"] >= cfg["mix_min_pairs"]:
                v = round(float(mix[k][k]), 4)
                if abs(float(params.get(k, PRIOR)) - v) > 1e-3:
                    mix_changed = True
                params[k] = v
        cal = mix.get("calib") or {}
        if cfg["calib"] and cal.get("status") == "fitted" and cal["pairs"] >= cfg["calib_min_pairs"]:
            for k, d in (("a", 1.0), ("b", 0.0)):
                v = round(float(cal[k]), 4)
                if abs(float(params.get(f"calib_{k}", d)) - v) > 1e-3:
                    mix_changed = True
                params[f"calib_{k}"] = v
        if policy_ok and cfg["playout_temp"] == "match":
            params["playout_temperature"] = round(self._match_playout_temperature(tr, w_new), 3)
            out["playout_temperature"] = params["playout_temperature"]
        accepted = policy_ok or mix_changed
        if mix_changed and not policy_ok:
            reason += "; new lam/beta written with the parent's policy weights"
        w_cand = w_new if policy_ok else parent.full
        desc = f"online HL (mcts.hl) from {parent.version}" + ("" if policy_ok else " (mix params only)")

        # (b) the value model (independent of the policy gate)
        try:
            out["value"] = self._update_value()
        except Exception as e:      # never let the value side break a decision loop
            out["value"] = {"error": repr(e)}

        self.flush()                                # value inputs computed above
        with self._flock(), self._lock:             # lock order everywhere: file lock, then thread lock
            self._sync_disk()
            self.updates += 1
            if accepted and self.current.digest != parent.digest:      # another process committed meanwhile
                accepted = False
                reason = (f"superseded: {self.current.version} was accepted by another process sharing this run dir "
                          f"while this fit ran from {parent.version}; the candidate is dropped")
            if accepted:
                pfile = self.current_file

                def make(n):
                    c = self._weights_from(w_cand, parent, f"hl-v{n:03d}", params)
                    c.description = desc
                    c = Weights.from_json(c.to_json())    # exactly what the file holds (6 decimals), same digest
                    doc = c.to_json()
                    doc["hl"] = {"version_no": n, "digest": c.digest, "created": time.time(),
                                 "parent": {"version": parent.version, "digest": parent.digest, "file": pfile},
                                 "samples": {"total": len(self.samples), "train": len(tr), "heldout": len(ho),
                                             "games_finished": len(self.games)},
                                 "metrics": {"policy": _brief(policy_info), "checks": checks,
                                             "value": out.get("value"), "mix": mix},
                                 "reason": reason}
                    return c, doc
                name, cand, _ = self._write_version(make)
                self.accepted += 1
                self.current, self.current_file = cand, name
            self._save_state()
        out["accepted"], out["reason"] = accepted, reason
        if self.current.rules:
            try:
                with self._gate():
                    self.book = Book(self.run_dir)      # the latest book (another process may have written it)
                    if self.book.note_weights(self.current, "refit") or accepted:
                        self.book.set_hits(self.rule_hits(self.current.rules))
                        with self._flock():
                            self.book.save()
                            self._sync_disk()
                            self._save_state()
            except Exception as e:              # the book must never break a decision loop
                out["book_error"] = repr(e)
        try:
            agr = self.model_agreement(self.current)
            if agr is not None:
                out["agreement"] = agr
        except Exception as e:
            out["agreement"] = {"error": repr(e)}
        out["version"] = self.current.version
        out["file"] = self.current_file
        out["time_s"] = round(time.monotonic() - t0, 3)
        with open(self._path("updates.jsonl"), "a") as f:
            f.write(json.dumps(_brief_update(out), default=float) + "\n")
        return out

    # ------------------------------------------------------------------ (g) proposals of heuristic jobs
    def rule_hits(self, rules: list) -> dict:
        """Hit counts of rules in the current samples: positions with a matching legal move, matched
        moves, positions where a rule matches the most-visited move, the mean visit share of the
        matched moves, and held-out positions matched."""
        if not rules:
            return {}
        tr, ho = self.split()
        hos = {s.sid for s in ho}
        st = {r["id"]: {"positions": 0, "moves": 0, "top": 0, "mass": 0.0, "heldout_positions": 0} for r in rules}
        for smp in tr + ho:
            rows, t = self._rows_of(smp)
            if t is None:
                continue
            self._with_rules(smp.sid, rows, smp.board, rules)
            h = self._hits[smp.sid]
            top = int(np.argmax(t))
            for r in rules:
                hr = h.get(r["id"])
                if hr is None or not len(hr):
                    continue
                d = st[r["id"]]
                d["positions"] += 1
                d["moves"] += int(len(hr))
                d["top"] += int(top in set(hr.tolist()))
                d["mass"] += float(t[hr].sum())
                d["heldout_positions"] += int(smp.sid in hos)
        for d in st.values():
            d["mass"] = round(d["mass"] / d["positions"], 4) if d["positions"] else 0.0
        return st

    def _gain_ci(self, ho: list[Sample], d: np.ndarray, w: np.ndarray, level: float, reps: int = 2000) -> list:
        """Bootstrap interval of the weighted mean gain: clusters = the search a held-out node came from
        once there are at least 5 searches (nodes of one search are correlated), else nodes."""
        keys = [(x.game, x.dec) for x in ho]
        if len(set(keys)) < 5:
            keys = list(range(len(ho)))
        uniq = {k: i for i, k in enumerate(dict.fromkeys(keys))}
        cid = np.array([uniq[k] for k in keys])
        W = np.bincount(cid, weights=w, minlength=len(uniq))
        D = np.bincount(cid, weights=w * d, minlength=len(uniq))
        rng = np.random.default_rng(12345)
        pick = rng.integers(0, len(uniq), size=(reps, len(uniq)))
        g = D[pick].sum(1) / np.maximum(W[pick].sum(1), 1e-12)
        a = (1.0 - level) / 2.0
        return [float(np.quantile(g, a)), float(np.quantile(g, 1.0 - a))]

    def consider(self, answer: dict, provenance: Optional[dict] = None) -> dict:
        """Gate the proposals of one heuristic job (a validated gotree.heurdsl answer).  Returns a
        report; accepted rules and nudges make a new weights version; everything is recorded in the
        heuristics book with its reason."""
        with self._fit_lock, self._gate():
            return self._consider(answer or {}, provenance or {})

    def _consider(self, answer: dict, prov: dict) -> dict:
        from gotree.heurdsl import parse_answer
        cfg = self.cfg
        t0 = time.monotonic()
        self.flush()
        parent = self.current_weights()
        self.book = Book(self.run_dir)                    # another process may have written it
        book = self.book
        T = float(parent.params.get("prior_temperature", 1.0))
        tr, ho = self.split()
        if len(tr) > cfg["max_train"]:
            rng = np.random.default_rng(cfg["seed"] * 1_000_003 + 7919 * (self.updates + 1))
            pick = np.sort(rng.choice(len(tr), size=cfg["max_train"], replace=False))
            tr = [tr[i] for i in pick]
        pv = {k: prov.get(k) for k in ("job_id", "label", "dag_key", "decision", "surprises", "worker") if k in prov}
        rep: dict = {"job_id": prov.get("job_id"), "label": prov.get("label"), "parent": parent.version,
                     "rules": [], "nudges": [], "accepted": False, "train_n": len(tr), "heldout_n": len(ho),
                     "heldout_hybrid": sum(1 for x in ho if x.hy)}
        try:     # the gate checks the language again (the answer may come from anywhere)
            from gotree.heurdsl import NUDGE_KEYS, RULE_KEYS
            ans = parse_answer({"analysis": answer.get("analysis", ""),
                                "rules": [{k: v for k, v in r.items() if k in RULE_KEYS} for r in answer.get("rules") or []],
                                "nudges": [{k: v for k, v in n.items() if k in NUDGE_KEYS}
                                           for n in answer.get("nudges") or []]}, targets=None, positions=None)
        except Exception as e:
            rep["error"] = f"invalid answer: {e}"
            book.note_job({**pv, "rules": 0, "nudges": 0, "error": rep["error"]})
            with self._flock():
                book.save()
            return rep
        rules_in, nudges_in = ans["rules"], ans["nudges"]

        def record(kind: str, item: dict, status: str, reason: str, metrics: Optional[dict] = None,
                   retry_ok: bool = False) -> str:
            pid = book.add_proposal({"kind": kind, "job_id": prov.get("job_id"), "label": prov.get("label"),
                                     kind: item, "status": status, "reason": reason, "metrics": metrics or {},
                                     **({"retry_ok": True} if retry_ok else {})})
            rep["rules" if kind == "rule" else "nudges"].append({"id": pid, "name": item.get("name") or
                                                                 item.get("feature"), "status": status,
                                                                 "reason": reason, "metrics": metrics or {}})
            return pid

        if len(tr) < cfg["min_train"] or len(ho) < cfg["min_heldout"]:
            why = f"not enough samples to judge (train {len(tr)}, held-out {len(ho)})"
            for r in rules_in:
                record("rule", r, "rejected", why, retry_ok=True)
            for n in nudges_in:
                record("nudge", n, "rejected", why, retry_ok=True)
            book.note_job({**pv, "rules": len(rules_in), "nudges": len(nudges_in), "accepted": 0})
            with self._flock():
                book.save()
            return rep

        anchors = self._anchors() if (cfg["guards"] and cfg["guard_anchor"]) else []
        aw = float(cfg["guard_weight"])
        hcache: dict = {}

        def ho_set(rules):
            k = tuple(r["id"] for r in rules)
            if k not in hcache:
                hcache[k] = self._policy_set(ho, rules=rules)
            return hcache[k]

        def gate_checks(wfull, rules, label):
            cand = self._weights_from(wfull, parent, label, rules=rules)
            g = check_guards(cand, self._guards) if cfg["guards"] else {"passed": True, "failures": []}
            checks: dict = {}
            fails = ([f"tactical guard(s) lost: {', '.join(g['failures'])}"] if not g["passed"] else []) + \
                self._regression_fails(cand, parent, checks)
            reg = checks.get("regression") or {}
            return fails, {"guards": g["passed"], "regression_ce": (reg.get("candidate") or {}).get("ce")}

        # ---- nudges: the nudged weights against the parent on the held-out targets (no refit)
        cur, cur_rules = parent.full.copy(), list(parent.rules)
        fidx = feature_index()
        rpos = {r["id"]: N_FEATURES + j for j, r in enumerate(cur_rules)}
        hos0 = ho_set(cur_rules)
        ce_cur = hos0.metrics(cur, T)["ce"]
        acc_nudges = []
        for nd in nudges_in:
            i = rpos.get(nd["feature"], fidx.get(nd["feature"]))
            if i is None or (nd["feature"].startswith("pat3:")):
                record("nudge", nd, "rejected", f"{nd['feature']!r} is not an adjustable weight")
                continue
            w_try = cur.copy()
            w_try[i] += nd["delta"]
            ce_try = hos0.metrics(w_try, T)["ce"]
            gain = ce_cur - ce_try
            fails, ck = gate_checks(w_try, cur_rules, "nudge-trial")
            m = {"ce_before": ce_cur, "ce_after": ce_try, "gain": gain, "w_before": float(cur[i]),
                 "w_after": float(w_try[i]), **ck}
            if gain <= cfg["nudge_min_gain"]:
                fails.insert(0, f"held-out CE did not improve ({gain:+.5f} nats)")
            if fails:
                record("nudge", nd, "rejected", "; ".join(fails), m)
                continue
            pid = record("nudge", nd, "accepted", f"held-out CE improved ({gain:+.5f} nats)", m)
            cur, ce_cur = w_try, ce_try
            acc_nudges.append((nd, pid, m))

        # ---- rules: language checks again, duplicates, breadth on training positions
        active = book.rules()
        cands = []
        ref = tr if len(tr) <= 600 else [tr[i] for i in np.random.default_rng(3).choice(len(tr), 600, replace=False)]
        for k, r in enumerate(rules_in):
            dup = book.by_canonical(r["canonical"])
            rej = book.rejected_like(r["canonical"])
            if dup is not None and dup.get("status") == "active":
                record("rule", r, "rejected", f"duplicate of book rule {dup['id']} ({dup['name']})")
                continue
            if rej is not None:
                record("rule", r, "rejected", f"same pattern and conditions as rejected proposal {rej['id']} "
                                              f"({rej['reason'][:120]})")
                continue
            if len(active) + len(cands) >= cfg["max_rules"]:
                record("rule", r, "rejected", f"the book is full ({cfg['max_rules']} active rules)", retry_ok=True)
                continue
            c = {**r, "id": f"cand-{prov.get('job_id', 'x')}-{k}"}
            hit = tot = pos = 0
            for smp in ref:
                rows, t = self._rows_of(smp)
                if t is None:
                    continue
                self._with_rules(smp.sid, rows, smp.board, [c])
                h = self._hits[smp.sid][c["id"]]
                hit += len(h)
                tot += len(rows.moves)
                pos += int(len(h) > 0)
            frac = hit / tot if tot else 0.0
            m = {"train_match_frac": round(frac, 4), "train_positions_matched": pos, "train_positions": len(ref)}
            if frac > cfg["broad_frac"]:
                self.drop_rule_hits(c["id"])
                record("rule", r, "rejected", f"over-broad: matches {frac:.1%} of the legal moves in training "
                                              f"positions (> {cfg['broad_frac']:.0%})", m)
                continue
            if pos == 0:
                self.drop_rule_hits(c["id"])
                record("rule", r, "rejected", f"matches no legal move in {len(ref)} training positions", m)
                continue
            cands.append((c, m))

        # ---- rules: the current weights plus the rule, only the rule's weight fitted (all others frozen),
        #      against the current weights on the held-out hybrid targets; the regular update refits all
        acc_rules = []
        final_w, final_rules = cur, cur_rules
        if cands:
            l2 = float(cfg["l2"]) + float(cfg["l2_base"])
            lam = float(self.distill_state.get("lam") or 0.0) if (cfg["hybrid"] and cfg["distill"]) else 0.0
            d_tr = self._distill_rows(self._distill_records()[0]) if lam > 0 else None
            ce_cur_s = hos0.per_sample_ce(cur, T)
            ho_rows = [x for x in ho if self._rows_of(x)[1] is not None]

            def fit_rules(new):
                rules_n = cur_rules + list(new)
                x0 = np.concatenate([cur, [c["weight"] for c in new]])
                frozen = np.ones(len(x0), dtype=bool)
                frozen[len(cur):] = False
                trs_n = self._policy_set(tr, anchors, aw, rules=rules_n, distill=d_tr, lam=lam)
                w_n, info = fit_policy(trs_n, x0, l2, T, cfg["max_iter"], cfg["heur_fit_time"], frozen=frozen,
                                       start=x0)
                return rules_n, x0, w_n, info

            trial = []
            for c, m in cands:
                rules_c, x0, w_c, info = fit_rules([c])
                hos_c = ho_set(rules_c)
                ce_c_s = hos_c.per_sample_ce(w_c, T)
                dlt = ce_cur_s - ce_c_s
                gain = float(hos_c.sw @ dlt)
                ci = self._gain_ci(ho_rows, dlt, hos_c.sw, cfg["rule_ci"])
                ap = float(hos0.sw @ (ce_cur_s - hos_c.per_sample_ce(x0, T)))
                ho_hit = [x for x in ho if len(self._hits.get(x.sid, {}).get(c["id"], ())) > 0]
                ho_pos = len(ho_hit)
                ho_searches = len({(x.game, x.dec) for x in ho_hit})
                fails, ck = gate_checks(w_c, rules_c, "rule-trial")
                m.update({"ce_before": float(hos0.sw @ ce_cur_s), "ce_with": float(hos_c.sw @ ce_c_s), "gain": gain,
                          "ci90": ci, "ci_over": "searches" if len({(x.game, x.dec) for x in ho_rows}) >= 5 else "nodes",
                          "gain_as_proposed": ap, "heldout_positions": ho_pos, "heldout_searches": ho_searches,
                          "w_proposed": c["weight"], "w_fitted": float(w_c[-1]), "fit_iters": info["iters"], **ck})
                if ho_pos < cfg["rule_min_heldout"] or ho_searches < cfg["rule_min_searches"]:
                    fails.insert(0, f"matches only {ho_pos} held-out positions from {ho_searches} searches (needs "
                                    f"{cfg['rule_min_heldout']} from {cfg['rule_min_searches']})")
                    m["too_little_evidence"] = True      # not a verdict: the rule may be proposed again later
                if gain <= cfg["rule_min_gain"] or ci[0] <= 0:
                    fails.insert(0, f"held-out CE gain {gain:+.5f} nats (90% CI {ci[0]:+.5f} .. {ci[1]:+.5f}) is "
                                    f"not enough")
                trial.append((c, m, w_c, fails))
            ok = [(c, m, w_c) for c, m, w_c, f in trial if not f]
            if len(ok) == 1:
                final_w, final_rules = ok[0][2], cur_rules + [ok[0][0]]
            elif len(ok) > 1:               # all accepted rules together; else the best one alone
                rules_a, _, w_a, _ = fit_rules([c for c, _, _ in ok])
                g_a = float(hos0.metrics(cur, T)["ce"] - ho_set(rules_a).metrics(w_a, T)["ce"])
                fails, _ = gate_checks(w_a, rules_a, "rules-trial")
                best = max(ok, key=lambda x: x[1]["gain"])
                if not fails and g_a >= best[1]["gain"] - 1e-6:
                    final_w, final_rules = w_a, rules_a
                else:
                    ok = [best]
                    final_w, final_rules = best[2], cur_rules + [best[0]]
            okids = {c["id"] for c, _, _ in ok}
            for c, m, w_c, fails in trial:
                if c["id"] in okids:
                    acc_rules.append((c, m))
                else:
                    if not fails:
                        fails = ["a better rule from the same job was kept instead (the two together did not "
                                 "improve on it)"]
                    self.drop_rule_hits(c["id"])
                    record("rule", {k: v for k, v in c.items() if k != "id"}, "rejected", "; ".join(fails), m,
                           retry_ok=bool(m.get("too_little_evidence")))

        # ---- the new version (check, allocate and write under the file lock: another process may share the dir)
        with self._flock(), self._lock:
            self._sync_disk()
            if (acc_rules or acc_nudges) and self.current.digest != parent.digest:
                why = (f"superseded: {self.current.version} was accepted by another process sharing this run dir "
                       f"while this job was gated against {parent.version}; it may be proposed again")
                for c, m in acc_rules:
                    self.drop_rule_hits(c["id"])
                    record("rule", {k: v for k, v in c.items() if k != "id"}, "rejected", why, m, retry_ok=True)
                for nd, pid, m in acc_nudges:
                    p_ = next(p for p in book.d["proposals"] if p["id"] == pid)
                    p_.update(status="rejected", reason=why, retry_ok=True)
                    for r_ in rep["nudges"]:
                        if r_["id"] == pid:
                            r_.update(status="rejected", reason=why)
                acc_rules, acc_nudges = [], []
            if acc_rules or acc_nudges:
                new_ids = {}
                for c, m in acc_rules:
                    new_ids[c["id"]] = book.next_id("R")
                    pid = book.add_proposal({"kind": "rule", "job_id": prov.get("job_id"), "label": prov.get("label"),
                                             "rule": {k: v for k, v in c.items() if k != "id"}, "status": "accepted",
                                             "reason": f"held-out CE gain {m['gain']:+.5f} nats (90% CI "
                                                       f"{m['ci90'][0]:+.5f} .. {m['ci90'][1]:+.5f}), guards and "
                                                       f"regression set pass",
                                             "metrics": m, "rule_id": new_ids[c["id"]]})
                    rep["rules"].append({"id": pid, "name": c["name"], "status": "accepted",
                                         "rule_id": new_ids[c["id"]], "reason": book.d["proposals"][-1]["reason"],
                                         "metrics": m})
                    c["_pid"] = pid
                rules_v = []
                for r in final_rules:
                    if r["id"] in new_ids:
                        rid = new_ids[r["id"]]
                        for h in self._hits.values():
                            if r["id"] in h:
                                h[rid] = h.pop(r["id"])
                        rules_v.append({"id": rid, "name": r["name"], "pattern": r["pattern"],
                                        "conditions": r.get("conditions") or {}, "canonical": r["canonical"]})
                    else:
                        rules_v.append(r)
                new_anchor = {"features": dict(self.anchor.get("features") or {}),
                              "rules": dict(self.anchor.get("rules") or {})}
                for nd, pid, m in acc_nudges:
                    if nd["feature"] in rpos:
                        new_anchor["rules"][nd["feature"]] = float(new_anchor["rules"].get(nd["feature"], 0.0)) + \
                            nd["delta"]
                    else:
                        new_anchor["features"][nd["feature"]] = float(new_anchor["features"].get(nd["feature"], 0.0)) + \
                            nd["delta"]
                for c, m in acc_rules:
                    new_anchor["rules"][new_ids[c["id"]]] = float(c["weight"])
                pfile = self.current_file

                def make(n):
                    w_ = self._weights_from(final_w, parent, f"hl-v{n:03d}", rules=rules_v)
                    w_.description = (f"heuristic job {prov.get('job_id')} on {parent.version}: "
                                      f"{len(acc_rules)} rule(s), {len(acc_nudges)} nudge(s)")
                    w_ = Weights.from_json(w_.to_json())
                    doc = w_.to_json()
                    doc["hl"] = {"version_no": n, "digest": w_.digest, "created": time.time(),
                                 "role": "heuristic", "job_id": prov.get("job_id"), "label": prov.get("label"),
                                 "parent": {"version": parent.version, "digest": parent.digest, "file": pfile},
                                 "rules_added": [new_ids[c["id"]] for c, _ in acc_rules],
                                 "nudges": [{"feature": nd["feature"], "delta": nd["delta"]} for nd, _, _ in acc_nudges],
                                 "samples": {"total": len(self.samples), "train": len(tr), "heldout": len(ho)}}
                    return w_, doc
                name, cand, _ = self._write_version(make)
                self.accepted += 1
                self.current, self.current_file = cand, name
                self.anchor = new_anchor
                hits = self.rule_hits(cand.rules)
                w_of = {r["id"]: float(x) for r, x in zip(cand.rules, cand.w_rules)}
                for c, m in acc_rules:
                    rid = new_ids[c["id"]]
                    book.add_rule({k: v for k, v in c.items() if k not in ("id", "_pid")}, c["weight"], w_of[rid],
                                  {**pv}, {k: m.get(k) for k in ("ce_before", "ce_with", "gain", "ci90", "ci_over",
                                                                "gain_as_proposed", "heldout_positions",
                                                                "heldout_searches", "w_proposed", "w_fitted")},
                                  hits.get(rid, {}), cand.version, c["_pid"])
                for nd, pid, m in acc_nudges:
                    book.add_nudge(nd, {**pv}, m, cand.version, pid)
                book.note_weights(cand, "refit at acceptance")
                book.set_hits(hits)
                rep["accepted"] = True
                rep["version"] = cand.version
            n_acc = len(acc_rules) + len(acc_nudges)
            book.note_job({**pv, "rules": len(rules_in), "nudges": len(nudges_in), "accepted": n_acc,
                           "analysis": ans.get("analysis", "")[:600]})
            book.save()
            self._save_state()
        rep["book_version"] = book.version
        rep["time_s"] = round(time.monotonic() - t0, 2)
        with open(self._path("proposals.jsonl"), "a") as f:
            f.write(json.dumps(rep, default=float) + "\n")
        return rep

    # ------------------------------------------------------------------ (b) value
    def _base_pol(self) -> Policy:
        if self._base_policy is None:
            self._base_policy = Policy(self.base)
        return self._base_policy

    def _update_value(self) -> Optional[dict]:
        cfg = self.cfg
        if not cfg["value"]:
            return None
        with self._lock:
            have = [s for s in self.samples.values() if s.q is not None]
        todo = [s for s in reversed(have) if s.sid not in self._vin][:cfg["value_new_per_update"]]
        if todo:
            X = inputs_for([_board_of(s) for s in todo], self._base_pol(), cfg["value_k"],
                           [cfg["seed"] * 7919 + s.sid for s in todo], threads=cfg["threads"])
            lines = []
            for s, x in zip(todo, X):
                self._vin[s.sid] = x
                lines.append(json.dumps({"sid": s.sid, "x": [round(float(v), 6) for v in x]}))
            with self._lock:
                self._pending["value-inputs"].extend(lines)
        got = [(s, self._vin.get(s.sid)) for s in have]
        got = [(s, x) for s, x in got if x is not None]
        if len(got) < cfg["value_min"]:
            return {"status": "not enough samples", "n": len(got)}
        f = cfg["heldout_frac"]
        rows = [s for s, _ in got]
        X = np.array([x for _, x in got])
        tq = np.array([s.qp if s.qp is not None else s.q for s in rows])
        wq = np.array([self._weight(s) for s in rows])
        ho = np.array([heldout(s.key, f) for s in rows])
        z = np.array([np.nan if self._game_label(s) is None else self._game_label(s) for s in rows])
        Xs, ts, ws = [X[~ho]], [tq[~ho]], [wq[~ho]]
        lab = ~ho & ~np.isnan(z)
        if lab.any():
            Xs.append(X[lab])
            ts.append((1.0 + z[lab]) / 2.0)
            ws.append(cfg["game_weight"] * wq[lab])
        ext_n = 0
        if cfg["hybrid"] and cfg["ext_value_weight"] > 0:          # (e) the model's calibrated values (mcts-llm-hl)
            try:
                xe, te = self._ext_value_rows()
                if len(te):
                    Xs.append(xe)
                    ts.append(te)
                    ws.append(np.full(len(te), cfg["ext_value_weight"] * float(np.median(wq))))
                    ext_n = len(te)
            except Exception:
                ext_n = 0
        Xt, tt, wt = np.concatenate(Xs), np.concatenate(ts), np.concatenate(ws)
        if len(tt) < 20 or ho.sum() < 10:
            return {"status": "not enough samples", "n": len(rows)}
        prev = self.value_model.coef if self.value_model is not None else None
        coef = fit_value(Xt, tt, wt, cfg["value_l2"], prev)
        vm = ValueModel(coef, cfg["value_k"], f"value-u{self.updates + 1:04d}")
        m = {"heldout_q": value_metrics(vm, X[ho], tq[ho], wq[ho]),
             "train_q": value_metrics(vm, X[~ho], tq[~ho], wq[~ho])}
        hz = ho & ~np.isnan(z)
        if hz.sum() >= 10:
            m["heldout_game"] = value_metrics(vm, X[hz], (1.0 + z[hz]) / 2.0)
        vm.metrics = m
        self.value_model = vm
        return {"status": "fitted", "version": vm.version, "n": len(rows), "labelled": int((~np.isnan(z)).sum()),
                "model_value_labels": ext_n, **m}

    def _ext_value_rows(self) -> tuple[np.ndarray, np.ndarray]:
        """Value-model inputs and calibrated targets of the training model evaluations (latest per node)."""
        cfg = self.cfg
        cal = (self.mix or {}).get("calib") or {}
        a, b = float(cal.get("a", 1.0)), float(cal.get("b", 0.0))
        latest: dict = {}
        with self._lock:
            ext = list(enumerate(self.external))
        for i, e in ext:
            if e.get("source") == cfg["mix_source"] and e.get("value") is not None and \
                    not heldout(int(e["key"], 16), cfg["heldout_frac"]) and not is_test(int(e["key"], 16),
                                                                                      cfg["test_frac"]):
                latest[e["key"]] = (i, e)
        if not hasattr(self, "_vin_ext"):
            self._vin_ext = {}
        todo = [(i, e) for i, e in latest.values() if i not in self._vin_ext][:cfg["value_new_per_update"]]
        if todo:
            X = inputs_for([as_board(e["board"]) for _, e in todo], self._base_pol(), cfg["value_k"],
                           [cfg["seed"] * 7919 + 1_000_003 + i for i, _ in todo], threads=cfg["threads"])
            for (i, _), x in zip(todo, X):
                self._vin_ext[i] = x
        got = [(self._vin_ext[i], float(apply_calib(e["value"], a, b))) for i, e in latest.values() if i in self._vin_ext]
        if not got:
            return np.zeros((0, 0)), np.zeros(0)
        return np.array([x for x, _ in got]), np.array([t for _, t in got])

    # ------------------------------------------------------------------ (c) lam / beta
    def mix_pairs(self) -> tuple[list[dict], list[dict]]:
        """(value pairs, prior pairs) of external evaluations matched with a deeper observation."""
        cfg = self.cfg
        vals, pris = [], []
        with self._lock:
            ext = [e for e in self.external if e.get("source") == cfg["mix_source"]]
            smp = dict(self.samples)
        for e in ext:
            s = smp.get(int(e["key"], 16))
            if s is None or s.t < e["t"]:
                continue
            need = max(cfg["mix_min_visits"], cfg["mix_min_ratio"] * int(e.get("n_at") or 0))
            if s.n and s.n < need:
                continue
            w = self._weight(s)
            tgt = s.qp if s.qp is not None else s.q
            if e.get("value") is not None and e.get("z_playout") is not None and tgt is not None:
                vals.append({"v": float(e["value"]), "z": float(e["z_playout"]), "t": float(tgt), "w": w})
            if e.get("priors"):
                rows, pi = self._rows_of(s)
                if pi is None:
                    continue
                mv = [int(m) for m in rows.moves]
                pl = np.array([float(e["p_learned"].get(str(m), 0.0)) for m in mv])
                pe = np.array([float(e["priors"].get(str(m), 0.0)) for m in mv])
                if pe.sum() <= 0 or pl.sum() <= 0:
                    continue
                pris.append({"pl": pl / pl.sum(), "pe": pe / pe.sum(), "pi": pi, "w": w})
        return vals, pris

    def calib_pairs(self) -> list[dict]:
        """(model value, deeper playout Q) pairs: each external evaluation of source mix_source with
        a value, and the latest sample of that node observed after it with at least
        calib_min_visits visits (its q_playout is the target)."""
        cfg = self.cfg
        with self._lock:
            ext = [e for e in self.external if e.get("source") == cfg["mix_source"] and e.get("value") is not None]
            smp = dict(self.samples)
        out = []
        for e in ext:
            s = smp.get(int(e["key"], 16))
            if s is None or s.t < e["t"] or s.qp is None or (s.n and s.n < cfg["calib_min_visits"]):
                continue
            out.append({"v": float(e["value"]), "t": float(s.qp), "w": self._weight(s), "key": e["key"],
                        "n": s.n, "depth": s.depth})
        return out

    def fit_calibration(self) -> dict:
        """(d) on the current samples: {"a", "b", "pairs", "status", ...}; also kept in self.mix."""
        cfg = self.cfg
        pairs = self.calib_pairs()
        if not cfg["calib"]:
            cal = {"status": "off", "pairs": len(pairs), "a": 1.0, "b": 0.0}
        elif len(pairs) >= cfg["calib_min_pairs"]:
            cal = fit_calib([p["v"] for p in pairs], [p["t"] for p in pairs], [p["w"] for p in pairs],
                            n0=cfg["calib_n0"])
        else:
            cal = {"status": "default", "pairs": len(pairs), "a": 1.0, "b": 0.0,
                   "note": f"needs {cfg['calib_min_pairs']} '{cfg['mix_source']}' values matched with a deeper search"}
        with self._lock:
            self.mix = {**self.mix, "calib": cal}
        return cal

    def _fit_mix(self) -> dict:
        cfg = self.cfg
        cal = self.fit_calibration()
        vals, pris = self.mix_pairs()
        lo, hi, n0 = 0.1, 0.9, cfg["mix_n0"]
        if cal.get("status") == "fitted" and cal["pairs"] >= cfg["calib_min_pairs"]:
            for p in vals:                     # lam weighs what the engine mixes: the calibrated value
                p["v"] = float(apply_calib(p["v"], cal["a"], cal["b"]))
        if len(vals) >= cfg["mix_min_pairs"]:
            lam = fit_lam([p["v"] for p in vals], [p["z"] for p in vals], [p["t"] for p in vals],
                          [p["w"] for p in vals], n0=n0, lo=lo, hi=hi)
        else:
            lam = {"status": "default", "pairs": len(vals), "lam": PRIOR,
                   "note": f"needs {cfg['mix_min_pairs']} matched '{cfg['mix_source']}' value pairs"}
        if len(pris) >= cfg["mix_min_pairs"]:
            beta = fit_beta([p["pl"] for p in pris], [p["pe"] for p in pris], [p["pi"] for p in pris],
                            [p["w"] for p in pris], n0=n0, lo=lo, hi=hi)
        else:
            beta = {"status": "default", "pairs": len(pris), "beta": PRIOR,
                    "note": f"needs {cfg['mix_min_pairs']} matched '{cfg['mix_source']}' prior pairs"}
        if cal.get("status") == "fitted" and isinstance(lam, dict):
            lam["on"] = "calibrated values"
        self.mix = {"lam": lam, "beta": beta, "calib": cal, "external": len(self.external)}
        return self.mix

    # ------------------------------------------------------------------ reporting
    def versions(self) -> list[Path]:
        return sorted(self.run_dir.glob("weights-v[0-9][0-9][0-9].json"))

    def evaluate(self, weights: Weights, samples: Optional[list[Sample]] = None) -> Optional[dict]:
        """Policy metrics of any weights on the given samples (default: the current held-out split)."""
        if samples is None:
            samples = self.split()[1]
        ps = self._policy_set(samples, rules=weights.rules) if samples else None
        return None if ps is None else ps.metrics(weights.full, float(weights.params.get("prior_temperature", 1.0)))

    def close(self) -> None:
        self.flush()
        with self._flock():
            self._sync_disk()
            self._save_state()


def _board_of(s: Sample):
    return as_board(s.board)


def _brief(p: Optional[dict]) -> Optional[dict]:
    if not p:
        return p
    return {"heldout_ce": {"parent": p["heldout"]["parent"]["ce"], "candidate": p["heldout"]["candidate"]["ce"]},
            "heldout_top1": {"parent": p["heldout"]["parent"]["top1"], "candidate": p["heldout"]["candidate"]["top1"]},
            "train_ce": {"parent": p["train"]["parent"]["ce"], "candidate": p["train"]["candidate"]["ce"]},
            "n": {"train": p["train"]["parent"]["n"], "heldout": p["heldout"]["parent"]["n"]},
            "gain": p["gain"], "dw_max": p["dw_max"], "fit": {k: p["fit"][k] for k in ("iters", "reason", "time_s")},
            "attempts": p.get("attempts")}


def _brief_update(u: dict) -> dict:
    d = {k: u[k] for k in ("update", "parent", "version", "file", "accepted", "reason", "samples", "train_n",
                           "heldout_n", "game", "time_s")}
    d["t"] = time.time()
    d["policy"] = _brief(u.get("policy"))
    d["checks"] = u.get("checks")
    v = u.get("value") or {}
    d["value"] = {k: v[k] for k in ("status", "version", "n", "labelled", "heldout_q", "heldout_game") if k in v}
    m = u.get("mix") or {}
    d["mix"] = {k: {kk: m[k].get(kk) for kk in ("status", "pairs", k, "raw")} for k in ("lam", "beta") if k in m}
    if "calib" in m:
        d["mix"]["calib"] = {kk: m["calib"].get(kk) for kk in ("status", "pairs", "a", "b", "raw_a", "raw_b")}
    p = u.get("policy") or {}
    if p.get("distill"):
        d["distill"] = p["distill"]
    if p:
        d["heldout_hybrid"] = p.get("heldout_hybrid")
        d["rules"] = p.get("rules")
    if u.get("agreement"):
        d["agreement"] = u["agreement"]
    return d
