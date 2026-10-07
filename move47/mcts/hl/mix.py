"""Fitting the mixing weights from nodes that received an external (LLM) evaluation.

    lam   V = (1 - lam) * v_ext + lam * z_playout       (MCTSConfig.lam)
    beta  P = (1 - beta) * p_learned + beta * p_ext      (MCTSConfig.beta)

Each pair is one node: what each source said when the external evaluation arrived (v_ext and a
playout estimate z of the node; p_ext and the learned prior p_learned) and what the node's later,
deeper search found (its deep q; its final visit distribution pi).

    lam:  least squares  min_l sum_i w_i ((1 - l) v_i + l z_i - t_i)^2,  closed form
          l_raw = sum w (z - v)(t - v) / sum w (z - v)^2, clipped to [0, 1]
    beta: max likelihood min_b sum_i w_i CE(pi_i, (1 - b) p_learned_i + b p_ext_i), grid on [0, 1]

Both are then shrunk toward 0.5 with n0 pseudo-pairs, (n * raw + n0 * 0.5) / (n + n0), and
clipped to [lo, hi] = [0.1, 0.9].

    calibration (node move47::mcts-calib): the monotone map that puts a model value v on the scale of
          the deeper search's playout Q,  t ~ sigmoid(a * logit(v) + b),  a > 0.  Fitted by logistic
          regression with soft labels t (Newton), with a ridge toward the identity (a = 1, b = 0) worth
          n0 pairs, so it stays near the identity with little data; a clipped to [0.05, 4], b to
          [-4, 4].  The engine applies it to every external value (MCTSConfig.calib_a / calib_b).
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

PRIOR = 0.5
LO, HI = 0.1, 0.9


def _shrink(raw: float, n: float, n0: float, lo: float, hi: float) -> float:
    return float(np.clip((n * raw + n0 * PRIOR) / (n + n0), lo, hi))


def fit_lam(v_ext: Sequence[float], z_playout: Sequence[float], target: Sequence[float],
            w: Optional[Sequence[float]] = None, n0: float = 10.0, lo: float = LO, hi: float = HI) -> dict:
    v = np.asarray(v_ext, dtype=np.float64)
    z = np.asarray(z_playout, dtype=np.float64)
    t = np.asarray(target, dtype=np.float64)
    w = np.ones(len(v)) if w is None else np.asarray(w, dtype=np.float64)
    n = len(v)
    if n == 0:
        return {"lam": PRIOR, "raw": None, "pairs": 0, "status": "default"}
    x, y = z - v, t - v
    sxx = float(w @ (x * x))
    raw = float(np.clip(float(w @ (x * y)) / sxx, 0.0, 1.0)) if sxx > 1e-12 else PRIOR
    lam = _shrink(raw, n, n0, lo, hi)

    def mse(l):
        return float(w @ (((1 - l) * v + l * z - t) ** 2) / w.sum())
    return {"lam": lam, "raw": raw, "pairs": n, "status": "fitted", "mse_llm": mse(0.0), "mse_playout": mse(1.0),
            "mse_fit": mse(lam), "mse_default": mse(PRIOR)}


def fit_beta(p_learned: Sequence[np.ndarray], p_ext: Sequence[np.ndarray], pi: Sequence[np.ndarray],
             w: Optional[Sequence[float]] = None, n0: float = 10.0, lo: float = LO, hi: float = HI,
             grid: int = 201, eps: float = 1e-6) -> dict:
    n = len(pi)
    if n == 0:
        return {"beta": PRIOR, "raw": None, "pairs": 0, "status": "default"}
    w = np.ones(n) if w is None else np.asarray(w, dtype=np.float64)
    w = w / w.sum()
    bs = np.linspace(0.0, 1.0, grid)
    ce = np.zeros(grid)
    for pl, pe, t, wi in zip(p_learned, p_ext, pi, w):
        pl, pe, t = (np.asarray(a, dtype=np.float64) for a in (pl, pe, t))
        nz = t > 0
        mix = (1.0 - bs[:, None]) * pl[nz][None, :] + bs[:, None] * pe[nz][None, :]
        ce += wi * -(np.log(mix + eps) @ t[nz])
    raw = float(bs[int(np.argmin(ce))])
    beta = _shrink(raw, n, n0, lo, hi)
    at = lambda b: float(np.interp(b, bs, ce))   # noqa: E731
    return {"beta": beta, "raw": raw, "pairs": n, "status": "fitted", "ce_learned": at(0.0), "ce_ext": at(1.0),
            "ce_fit": at(beta), "ce_default": at(PRIOR)}


CALIB_EPS = 0.01          # model values are clipped to [0.01, 0.99] before the logit
A_LO, A_HI, B_LIM = 0.05, 4.0, 4.0


def _sig(z):
    return 0.5 * (1.0 + np.tanh(0.5 * z))


def _calib_loss(a, b, x, y, w, lam_a, lam_b):
    p = np.clip(_sig(a * x + b), 1e-12, 1 - 1e-12)
    return float(-(w @ (y * np.log(p) + (1 - y) * np.log(1 - p))) + 0.5 * lam_a * (a - 1) ** 2 + 0.5 * lam_b * b ** 2)


def _calib_newton(x, y, w, lam_a, lam_b, iters=100):
    a, b = 1.0, 0.0
    f = _calib_loss(a, b, x, y, w, lam_a, lam_b)
    for _ in range(iters):
        p = _sig(a * x + b)
        r, s = p - y, p * (1 - p)
        g = np.array([w @ (r * x) + lam_a * (a - 1), w @ r + lam_b * b])
        H = np.array([[w @ (s * x * x) + lam_a, w @ (s * x)], [w @ (s * x), w @ s + lam_b]]) + 1e-9 * np.eye(2)
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        t = 1.0
        while t > 1e-6:                               # backtracking: the loss is convex, Newton may overshoot
            na, nb = a - t * step[0], b - t * step[1]
            nf = _calib_loss(na, nb, x, y, w, lam_a, lam_b)
            if nf <= f:
                break
            t *= 0.5
        if t <= 1e-6:
            break
        a, b, f = na, nb, nf
        if abs(t * step[0]) + abs(t * step[1]) < 1e-10:
            break
    return a, b


def apply_calib(v, a: float, b: float):
    """sigmoid(a * logit(v) + b) (v clipped to [CALIB_EPS, 1 - CALIB_EPS] only for the fit's inputs;
    the engine's mcts.tree.apply_calibration is the same map)."""
    v = np.clip(np.asarray(v, dtype=np.float64), 1e-4, 1 - 1e-4)
    return _sig(a * np.log(v / (1 - v)) + b)


def fit_calib(v_ext: Sequence[float], target: Sequence[float], w: Optional[Sequence[float]] = None,
              n0: float = 10.0) -> dict:
    """Fit t ~ sigmoid(a * logit(v) + b) (see the module docstring).  Returns a, b (shrunk toward the
    identity with n0 pseudo-pairs), raw_a / raw_b (no shrinkage), pairs and the squared errors of
    the identity and of the fit."""
    v = np.clip(np.asarray(v_ext, dtype=np.float64), CALIB_EPS, 1 - CALIB_EPS)
    t = np.clip(np.asarray(target, dtype=np.float64), 0.0, 1.0)
    n = len(v)
    if n == 0:
        return {"a": 1.0, "b": 0.0, "raw_a": None, "raw_b": None, "pairs": 0, "status": "default"}
    w = np.ones(n) if w is None else np.asarray(w, dtype=np.float64)
    w = w * (n / w.sum())                              # mean weight 1: n0 counts as n0 pairs
    x = np.log(v / (1 - v))
    m2 = max(1.0, float(w @ (x * x)) / n)
    # a pseudo-pair's curvature: sigmoid' <= 1/4, times the mean squared logit for the slope
    ra, rb = _calib_newton(x, t, w, 1e-6, 1e-6)
    a, b = _calib_newton(x, t, w, n0 * 0.25 * m2, n0 * 0.25)
    a, b = float(np.clip(a, A_LO, A_HI)), float(np.clip(b, -B_LIM, B_LIM))

    def mse(aa, bb):
        return float(w @ ((_sig(aa * x + bb) - t) ** 2) / n)
    return {"a": a, "b": b, "raw_a": float(ra), "raw_b": float(rb), "pairs": n, "status": "fitted",
            "mse_identity": mse(1.0, 0.0), "mse_fit": mse(a, b), "mean_v": float(np.mean(v)),
            "mean_t": float(w @ t / n)}
