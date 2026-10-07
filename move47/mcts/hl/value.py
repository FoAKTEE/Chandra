"""A cheap value model: logistic regression on a few position features, fitted to the backed-up
winrate of well-visited nodes (soft labels) and to finished game results.

Inputs (side to move's view; k playouts with a FIXED policy, the learner's base weights, so the
inputs do not drift when the policy weights change):

    z_play       mean playout result (+1 win / -1 loss)      -- the "short playout estimate"
    score_play   mean playout score / size^2
    zscore_play  mean playout score / (std + 2), clipped to [-5, 5]
    area_now     Tromp-Taylor area score of the position now / size^2
    stage        stones on the board / size^2
    score_x_stage
    atari_own    own stones in atari / size^2
    atari_opp    opponent stones in atari / size^2

The baseline it must beat is the short playout estimate alone, winrate (1 + z_play) / 2.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from gotree.position import BLACK, EMPTY

from ..board import Board
from ..policy import Policy
from .fit import lbfgs

FEATURES = ("bias", "z_play", "score_play", "zscore_play", "area_now", "stage", "score_x_stage", "atari_own",
            "atari_opp")


def _atari_stones(b: Board) -> tuple[int, int]:
    """(own, opponent) stones in chains with exactly one liberty."""
    pos = b.to_position()
    me = pos.to_play
    seen: set[int] = set()
    own = opp = 0
    for p, c in enumerate(pos.cells):
        if c == EMPTY or p in seen:
            continue
        stones, libs = pos.chain(p)
        seen |= stones
        if len(libs) == 1:
            if c == me:
                own += len(stones)
            else:
                opp += len(stones)
    return own, opp


def value_inputs(b: Board, policy: Policy, k: int = 16, seed: int = 0) -> np.ndarray:
    """The model's input vector for position b (k playouts with `policy`; GIL released inside)."""
    A = float(b.size * b.size)
    sgn = 1.0 if b.to_play == BLACK else -1.0
    if b.terminal or k <= 0:
        sc = np.array([b.score()], dtype=np.float64)
    else:
        sc = policy.playouts(b, k, seed).astype(np.float64)
    s = sgn * sc
    z = float(np.mean(np.sign(s)))
    ms = float(s.mean())
    zs = float(np.clip(ms / (float(s.std()) + 2.0), -5, 5))
    area = sgn * b.score() / A
    cells = b.cells_array()
    stage = float((cells != 0).sum()) / A
    ao, ap = _atari_stones(b)
    return np.array([1.0, z, ms / A, zs, area, stage, (ms / A) * stage, ao / A, ap / A])


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))


class ValueModel:
    def __init__(self, coef: Optional[np.ndarray] = None, k: int = 16, version: str = "none", metrics=None):
        self.coef = np.zeros(len(FEATURES)) if coef is None else np.asarray(coef, dtype=np.float64)
        self.k = int(k)
        self.version = version
        self.metrics = dict(metrics or {})

    def predict_x(self, X: np.ndarray) -> np.ndarray:
        """Winrate for the side to move, from input rows X."""
        return _sigmoid(np.atleast_2d(X) @ self.coef)

    def predict(self, b: Board, policy: Policy, seed: int = 0) -> float:
        return float(self.predict_x(value_inputs(b, policy, self.k, seed))[0])

    def to_json(self) -> dict:
        return {"features": list(FEATURES), "coef": [round(float(c), 6) for c in self.coef], "k": self.k,
                "version": self.version, "metrics": self.metrics}

    @classmethod
    def from_json(cls, d: dict) -> "ValueModel":
        if list(d.get("features", [])) != list(FEATURES):
            raise ValueError("value model has a different feature list")
        return cls(np.array(d["coef"]), d.get("k", 16), d.get("version", "?"), d.get("metrics"))


def fit_value(X: np.ndarray, t: np.ndarray, w: Optional[np.ndarray] = None, l2: float = 1e-3,
              coef0: Optional[np.ndarray] = None) -> np.ndarray:
    """Logistic regression with soft targets t in [0, 1] (CE loss), L2 on all but the bias."""
    X = np.asarray(X, dtype=np.float64)
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    w = np.ones(len(t)) if w is None else np.asarray(w, dtype=np.float64)
    w = w / w.sum()
    reg = np.full(X.shape[1], l2)
    reg[0] = 0.0

    def fg(c):
        z = X @ c
        p = _sigmoid(z)
        # CE with soft labels, computed stably: log(1+e^z) - t z
        lse = np.logaddexp(0.0, z)
        loss = float(w @ (lse - t * z)) + 0.5 * float(reg @ (c * c))
        g = X.T @ (w * (p - t)) + reg * c
        return loss, g

    c0 = np.zeros(X.shape[1]) if coef0 is None else np.asarray(coef0, dtype=np.float64)
    c, _ = lbfgs(fg, c0, max_iter=200)
    return c


def value_metrics(model: ValueModel, X: np.ndarray, t: np.ndarray, w: Optional[np.ndarray] = None) -> dict:
    """MSE (and Brier-style) of the model vs targets t, against the short playout estimate."""
    if len(t) == 0:
        return {"n": 0}
    w = np.ones(len(t)) if w is None else np.asarray(w, dtype=np.float64)
    w = w / w.sum()
    pm = model.predict_x(X)
    pb = (1.0 + X[:, FEATURES.index("z_play")]) / 2.0
    return {"n": int(len(t)), "mse_model": float(w @ (pm - t) ** 2), "mse_playouts": float(w @ (pb - t) ** 2),
            "mse_const": float(w @ (0.5 - t) ** 2)}


def inputs_for(boards: Sequence[Board], policy: Policy, k: int, seeds: Sequence[int], threads: int = 1) -> np.ndarray:
    """value_inputs for many boards (a thread pool: the playouts release the GIL)."""
    if threads <= 1 or len(boards) < 8:
        return np.array([value_inputs(b, policy, k, s) for b, s in zip(boards, seeds)])
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=threads) as ex:
        return np.array(list(ex.map(lambda a: value_inputs(a[0], policy, k, a[1]), zip(boards, seeds))))


class ValueHook:
    """An on_expand hook that hands the value model's estimate to the engine as a node's external
    value: ``set_external(key, value=v, source="value")``, mixed as (1 - lam) * Q_ext + lam * Q_playout
    like an LLM value.  This is the only route into the engine without a C change.  It is
    experimental, not part of the default engine: weights-ab --a-value-model measures it.  It
    runs on the search's control thread, so each call (k playouts) delays the event drain."""

    def __init__(self, model: ValueModel, policy: Policy, engine=None, seed: int = 0):
        self.model, self.policy, self.engine = model, policy, engine
        self.calls, self.seconds, self.seed = 0, 0.0, seed

    def __call__(self, ev) -> None:
        import time
        t0 = time.monotonic()
        v = self.model.predict(ev.board, self.policy, seed=self.seed + self.calls)
        self.engine.set_external(ev.key, value=v, source="value", position=ev.board)
        self.calls += 1
        self.seconds += time.monotonic() - t0


def load_value_model(path) -> ValueModel:
    """A value model from a learner's state.json (its "value_model") or a bare model JSON."""
    import json
    from pathlib import Path
    d = json.loads(Path(path).read_text())
    return ValueModel.from_json(d.get("value_model") or d)
