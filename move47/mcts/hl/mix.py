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
