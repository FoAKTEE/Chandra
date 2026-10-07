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

Everything persists in ``run_dir`` so learning continues across moves, games and processes:

    state.json          current version, counters, the value model and the last mix fit
    weights-vNNN.json   every accepted version (v000 = the base); a normal weight file
                        (mcts.weights.Weights.load reads it) plus an "hl" block: parent version
                        and digest, sample counts, train / held-out / regression metrics, guards
    samples.jsonl       the sample ring buffer (append-only, compacted; latest per node key)
    external.jsonl      external evaluations;  games.jsonl  game results
    value-inputs.jsonl  cached value-model inputs;  updates.jsonl  one line per update()
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

from ..features import move_priors
from ..policy import Policy
from ..weights import Weights, load_default
from .data import (PASS, Sample, as_board, censor_rows, heldout, limit_blas_threads, norm_dist, policy_rows,
                   target_vector)
from .fit import PolicySet, fit_policy
from .mix import PRIOR, fit_beta, fit_lam
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
        self.mix: dict = {"lam": {"status": "default", "pairs": 0}, "beta": {"status": "default", "pairs": 0}}
        self._guards = load_guards(Path(self.cfg["guards_path"])) if self.cfg["guards_path"] else None
        self._reg_path = Path(self.cfg["regression_path"]) if self.cfg["regression_path"] else None
        self._base_policy: Optional[Policy] = None
        self._anchor_rows: Optional[list] = None
        self.resumed = (self.run_dir / "state.json").exists()
        if self.resumed:
            self._load()
        else:
            self._init(base)
        self.provider = LearnerProvider(self)

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
                "mix": self.mix, "cfg": {k: v for k, v in self.cfg.items()}, "saved_at": time.time()}

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
        with self._lock:
            s = Sample(self.next_sid, key, b.to_dict(), pi, None if q is None else float(q),
                       None if qp is None else float(qp), n, int(depth), self.game, self.current.version, time.time())
            self.next_sid += 1
            old = self.samples.pop(key, None)
            if old is not None:
                self._rows.pop(old.sid, None)
                self._vin.pop(old.sid, None)
            self.samples[key] = s
            while len(self.samples) > self.cfg["capacity"]:
                _, ev = self.samples.popitem(last=False)
                self._rows.pop(ev.sid, None)
                self._vin.pop(ev.sid, None)
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
               "game": self.game}
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

    def _policy_set(self, samples: list[Sample], extra: Optional[list[tuple]] = None,
                    extra_weight: float = 0.0) -> Optional[PolicySet]:
        rows, tg, ws = [], [], []
        for s in samples:
            r, t = self._rows_of(s)
            if t is None:
                continue
            rows.append(r)
            tg.append(t)
            ws.append(self._weight(s))
        for r, t in extra or []:
            rows.append(r)
            tg.append(t)
            ws.append(extra_weight)
        return PolicySet(rows, tg, ws) if rows else None

    def _game_label(self, s: Sample) -> Optional[float]:
        g = self.games.get(s.game)
        if g is None:
            return None
        res, col = g
        return res if s.to_play == col else -res

    def split(self) -> tuple[list[Sample], list[Sample]]:
        with self._lock:
            ss = [s for s in self.samples.values() if not s.n or s.n >= self.cfg["min_visits"]]
        f = self.cfg["heldout_frac"]
        ho = [s for s in ss if heldout(s.key, f)]
        tr = [s for s in ss if not heldout(s.key, f)]
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
            self._anchor_rows = rows
        return self._anchor_rows

    def _fit_candidate(self, tr: list[Sample], ho: list[Sample], parent: Weights, T: float):
        """Fit, then gate: held-out CE must fall, every guard must hold, the regression set must not
        get worse by more than reg_tol.  With guard anchors on, the 'top' guards are training rows
        (weight guard_weight each); if a guard is still lost the fit is redone with the anchors
        weighted guard_boost times more (twice at most)."""
        cfg = self.cfg
        hos = self._policy_set(ho)
        m_ho0 = hos.metrics(parent.w, T)
        anchors = self._anchors() if (cfg["guards"] and cfg["guard_anchor"]) else []
        aw = float(cfg["guard_weight"])
        tries = []
        l2p, l2b = float(cfg["l2"]), float(cfg["l2_base"])
        center = (l2p * parent.w + l2b * self.base.w) / (l2p + l2b) if l2p + l2b > 0 else parent.w
        for attempt in range(3 if anchors else 1):
            trs = self._policy_set(tr, anchors, aw)
            w_new, info = fit_policy(trs, center, l2p + l2b, T, cfg["max_iter"], cfg["fit_time"], start=parent.w)
            cand = Weights(w_new, "candidate", dict(parent.params))
            g = check_guards(cand, self._guards) if cfg["guards"] else {"passed": True, "failures": []}
            tries.append({"anchor_weight": aw if anchors else 0.0, "guards_failed": g["failures"],
                          "iters": info["iters"], "time_s": round(info["time_s"], 2)})
            if g["passed"] or not anchors:
                break
            aw *= float(cfg["guard_boost"])
        trs_plain = self._policy_set(tr)
        m_tr0, m_tr1 = trs_plain.metrics(parent.w, T), trs_plain.metrics(w_new, T)
        m_ho1 = hos.metrics(w_new, T)
        gain = m_ho0["ce"] - m_ho1["ce"]
        info_d = {"fit": info, "train": {"parent": m_tr0, "candidate": m_tr1},
                  "heldout": {"parent": m_ho0, "candidate": m_ho1}, "gain": gain,
                  "dw_max": float(np.abs(w_new - parent.w).max()), "attempts": tries}
        checks: dict = {"guards": {"passed": g["passed"], "failures": g["failures"]}} if cfg["guards"] else {}
        fails = []
        if gain <= cfg["min_gain"]:
            fails.append(f"held-out CE did not improve ({gain:+.5f} nats)")
        if not g["passed"]:
            fails.append(f"tactical guard(s) lost: {', '.join(g['failures'])}")
        rp = regression_metrics(parent, self._reg_path)
        if rp is not None:
            rc = regression_metrics(cand, self._reg_path)
            rb = regression_metrics(self.base, self._reg_path)
            checks["regression"] = {"parent": rp, "candidate": rc, "base": rb}
            if rc["ce"] > rp["ce"] + cfg["reg_tol"]:
                fails.append(f"regression-set CE rose {rc['ce'] - rp['ce']:+.4f} > {cfg['reg_tol']} over the parent")
            if rc["ce"] > rb["ce"] + cfg["reg_tol_base"]:
                fails.append(f"regression-set CE {rc['ce'] - rb['ce']:+.4f} over the base > {cfg['reg_tol_base']}")
        ok = not fails
        reason = f"held-out CE improved ({gain:+.5f} nats)" if ok else "; ".join(fails)
        return w_new, info_d, checks, ok, reason

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
            w_new = parent.w
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
        if policy_ok and cfg["playout_temp"] == "match":
            params["playout_temperature"] = round(self._match_playout_temperature(tr, w_new), 3)
            out["playout_temperature"] = params["playout_temperature"]
        accepted = policy_ok or mix_changed
        if mix_changed and not policy_ok:
            reason += "; new lam/beta written with the parent's policy weights"
        cand = Weights(w_new if policy_ok else parent.w, f"hl-v{self.version_no + 1:03d}", params,
                       f"online HL (mcts.hl) from {parent.version}" + ("" if policy_ok else " (mix params only)"))
        cand = Weights.from_json(cand.to_json())    # exactly what the file holds (6 decimals), same digest

        # (b) the value model (independent of the policy gate)
        try:
            out["value"] = self._update_value()
        except Exception as e:      # never let the value side break a decision loop
            out["value"] = {"error": repr(e)}

        out["accepted"], out["reason"] = accepted, reason
        self.flush()                                # value inputs computed above
        with self._flock(), self._lock:             # lock order everywhere: file lock, then thread lock
            self.updates += 1
            if accepted:
                self.version_no += 1
                self.accepted += 1
                name = f"weights-v{self.version_no:03d}.json"
                doc = cand.to_json()
                doc["hl"] = {"version_no": self.version_no, "digest": cand.digest, "created": time.time(),
                             "parent": {"version": parent.version, "digest": parent.digest, "file": self.current_file},
                             "samples": {"total": len(self.samples), "train": len(tr), "heldout": len(ho),
                                         "games_finished": len(self.games)},
                             "metrics": {"policy": _brief(policy_info), "checks": checks,
                                         "value": out.get("value"), "mix": mix},
                             "reason": reason}
                self._write_json(name, doc)
                self.current, self.current_file = cand, name
            self._save_state()
        out["version"] = self.current.version
        out["file"] = self.current_file
        out["time_s"] = round(time.monotonic() - t0, 3)
        with open(self._path("updates.jsonl"), "a") as f:
            f.write(json.dumps(_brief_update(out), default=float) + "\n")
        return out

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
        return {"status": "fitted", "version": vm.version, "n": len(rows), "labelled": int((~np.isnan(z)).sum()), **m}

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

    def _fit_mix(self) -> dict:
        cfg = self.cfg
        vals, pris = self.mix_pairs()
        lo, hi, n0 = 0.1, 0.9, cfg["mix_n0"]
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
        self.mix = {"lam": lam, "beta": beta, "external": len(self.external)}
        return self.mix

    # ------------------------------------------------------------------ reporting
    def versions(self) -> list[Path]:
        return sorted(self.run_dir.glob("weights-v[0-9][0-9][0-9].json"))

    def evaluate(self, weights: Weights, samples: Optional[list[Sample]] = None) -> Optional[dict]:
        """Policy metrics of any weights on the given samples (default: the current held-out split)."""
        if samples is None:
            samples = self.split()[1]
        ps = self._policy_set(samples) if samples else None
        return None if ps is None else ps.metrics(weights.w, float(weights.params.get("prior_temperature", 1.0)))

    def close(self) -> None:
        self.flush()
        with self._flock():
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
    return d
