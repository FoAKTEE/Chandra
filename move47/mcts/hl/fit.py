"""Fitting the shared policy weights: a linear softmax over the legal moves, logit = w . f / T.

    loss(w) = sum_s c_s * CE(pi_s, softmax(F_s w / T)) / sum_s c_s  +  l2/2 * |w - w_prev|^2

pi_s is the visit distribution of a well-visited node (expert iteration), c_s its weight
(more visits, more weight), and the L2 term pulls toward the version being replaced.  The loss is
convex; it is minimised with L-BFGS (numpy only).  Everything is vectorised over a flat sparse
layout: one row per (sample, legal move), the active feature indices of each row in ``fi``.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

import numpy as np

from .._lib import N_FEATURES
from .data import PolicyRows


class PolicySet:
    """Samples' feature rows, targets and weights, concatenated for vectorised loss and gradient.

    ``nfeat``: the length of the parameter vector (N_FEATURES, plus one weight per model-written
    rule whose hits the rows carry in ``xr`` / ``xc``, node move47::mcts-llm-hl).  ``normalize``:
    the sample weights are divided by their sum (False: used as given, e.g. a search term and a
    distillation term with a chosen relative weight)."""

    def __init__(self, rows: Sequence[PolicyRows], targets: Sequence[np.ndarray], weights: Sequence[float],
                 nfeat: int = N_FEATURES, normalize: bool = True):
        if not rows:
            raise ValueError("empty policy set")
        self.nfeat = int(nfeat)
        self.S = len(rows)
        counts = np.array([len(r.moves) for r in rows], dtype=np.int64)
        self.starts = np.zeros(self.S + 1, dtype=np.int64)
        np.cumsum(counts, out=self.starts[1:])
        self.R = int(self.starts[-1])
        nf = np.concatenate([r.nf for r in rows])
        self.fi = np.concatenate([r.fi for r in rows]).astype(np.intp)
        self.ri = np.repeat(np.arange(self.R, dtype=np.intp), nf)
        xs = [(self.starts[k] + r.xr, N_FEATURES + r.xc) for k, r in enumerate(rows)
              if getattr(r, "xr", None) is not None and len(r.xr)]
        if xs:
            xri = np.concatenate([a for a, _ in xs]).astype(np.intp)
            xfi = np.concatenate([b for _, b in xs]).astype(np.intp)
            if int(xfi.max()) >= self.nfeat:
                raise ValueError("a rule column lies beyond nfeat")
            self.ri = np.concatenate([self.ri, xri])
            self.fi = np.concatenate([self.fi, xfi])
        self.sidx = np.repeat(np.arange(self.S, dtype=np.intp), counts)
        self.tgt = np.concatenate(targets).astype(np.float64)
        w = np.asarray(weights, dtype=np.float64)
        self.sw = w / w.sum() if normalize else w
        self.moves = np.concatenate([r.moves for r in rows])
        # entropy of the targets: CE - H = KL, reported for readability
        t = self.tgt
        self.h = -np.add.reduceat(np.where(t > 0, t * np.log(np.where(t > 0, t, 1.0)), 0.0), self.starts[:-1])

    def logits(self, w: np.ndarray) -> np.ndarray:
        return np.bincount(self.ri, weights=w[self.fi], minlength=self.R)

    def _logp(self, w: np.ndarray, temperature: float):
        z = self.logits(w) / temperature
        st = self.starts[:-1]
        z -= np.maximum.reduceat(z, st)[self.sidx]
        ez = np.exp(z)
        se = np.add.reduceat(ez, st)
        return z - np.log(se)[self.sidx], ez / se[self.sidx]

    def per_sample_ce(self, w: np.ndarray, temperature: float = 1.0) -> np.ndarray:
        logp, _ = self._logp(w, temperature)
        return -np.add.reduceat(self.tgt * logp, self.starts[:-1])

    def loss_grad(self, w: np.ndarray, w0: np.ndarray, l2: float, temperature: float = 1.0):
        logp, p = self._logp(w, temperature)
        ce = -np.add.reduceat(self.tgt * logp, self.starts[:-1])
        d = w - w0
        loss = float(self.sw @ ce) + 0.5 * l2 * float(d @ d)
        g_row = self.sw[self.sidx] * (p - self.tgt) / temperature
        g = np.bincount(self.fi, weights=g_row[self.ri], minlength=self.nfeat) + l2 * d
        return loss, g

    def metrics(self, w: np.ndarray, temperature: float = 1.0) -> dict:
        """Weighted CE (the gate's measure), unweighted CE and KL, and top-1 agreement."""
        logp, _ = self._logp(w, temperature)
        st = self.starts[:-1]
        ce = -np.add.reduceat(self.tgt * logp, st)
        top_model = _segment_argmax(logp, self.starts)
        top_tgt = _segment_argmax(self.tgt, self.starts)
        return {"n": self.S, "ce": float(self.sw @ ce), "ce_mean": float(ce.mean()),
                "kl_mean": float((ce - self.h).mean()), "top1": float((top_model == top_tgt).mean())}


    def playout_entropy(self, w: np.ndarray, temperature: float) -> float:
        """Mean entropy of the playout policy over the samples: softmax(logit / T) over the legal
        non-pass moves that do not fill an own eye, with ladder features inactive (as in playouts
        with the default ladders_playout=False)."""
        from ..features import feature_index
        idx = feature_index()
        if not hasattr(self, "_pmask"):
            eye_rows = np.zeros(self.R, dtype=bool)
            eye_rows[self.ri[self.fi == idx["eye_fill"]]] = True
            self._pmask = (self.moves >= 0) & ~eye_rows
            self._pseg = np.add.reduceat(self._pmask.astype(np.int64), self.starts[:-1]) > 0
        wp = np.array(w, dtype=np.float64)
        wp[[idx["ladder:capture"], idx["ladder:escape_fails"]]] = 0.0
        z = np.where(self._pmask, self.logits(wp) / temperature, -np.inf)
        st = self.starts[:-1]
        m = np.maximum.reduceat(z, st)
        m = np.where(np.isfinite(m), m, 0.0)
        e = np.exp(z - m[self.sidx])
        se = np.add.reduceat(e, st)
        p = e / np.where(se > 0, se, 1.0)[self.sidx]
        h = -np.add.reduceat(np.where(p > 0, p * np.log(np.where(p > 0, p, 1.0)), 0.0), st)
        return float(h[self._pseg].mean())

    def match_playout_temperature(self, w: np.ndarray, target: float, lo: float = 0.25, hi: float = 8.0) -> float:
        """The playout temperature at which w's mean playout entropy equals `target` (bisection;
        entropy rises with the temperature)."""
        if self.playout_entropy(w, lo) >= target:
            return lo
        if self.playout_entropy(w, hi) <= target:
            return hi
        for _ in range(30):
            mid = (lo * hi) ** 0.5
            if self.playout_entropy(w, mid) < target:
                lo = mid
            else:
                hi = mid
        return (lo * hi) ** 0.5


def _segment_argmax(x: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """Index (within the segment) of each segment's maximum (first on ties)."""
    S = len(starts) - 1
    counts = np.diff(starts)
    seg = np.repeat(np.arange(S), counts)
    m = np.maximum.reduceat(x, starts[:-1])
    hit = x >= m[seg]
    pos = np.arange(len(x)) - starts[:-1][seg]
    big = np.where(hit, pos, np.iinfo(np.int64).max)
    return np.minimum.reduceat(big, starts[:-1])


def lbfgs(fg: Callable[[np.ndarray], tuple[float, np.ndarray]], x0: np.ndarray, max_iter: int = 100, m: int = 10,
          gtol: float = 1e-7, ftol: float = 1e-10, time_limit: Optional[float] = None) -> tuple[np.ndarray, dict]:
    """Minimise a smooth convex function with L-BFGS and an Armijo backtracking line search."""
    import time
    t0 = time.monotonic()
    x = np.array(x0, dtype=np.float64)
    f, g = fg(x)
    f0 = f
    hist: list[tuple[np.ndarray, np.ndarray, float]] = []
    it, evals, reason = 0, 1, "max_iter"
    for it in range(1, max_iter + 1):
        q = g.copy()
        alphas = []
        for s, y, rho in reversed(hist):
            a = rho * float(s @ q)
            q -= a * y
            alphas.append(a)
        if hist:
            s, y, _ = hist[-1]
            q *= float(s @ y) / float(y @ y)
        else:
            q /= max(float(np.linalg.norm(g)), 1e-12)
        for (s, y, rho), a in zip(hist, reversed(alphas)):
            b = rho * float(y @ q)
            q += s * (a - b)
        d = -q
        gd = float(g @ d)
        if gd >= 0:                       # not a descent direction: restart from steepest descent
            hist.clear()
            d = -g / max(float(np.linalg.norm(g)), 1e-12)
            gd = float(g @ d)
        step = 1.0
        for _ in range(40):
            xn = x + step * d
            fn, gn = fg(xn)
            evals += 1
            if fn <= f + 1e-4 * step * gd:
                break
            step *= 0.5
        else:
            reason = "line_search"
            break
        s, y = xn - x, gn - g
        sy = float(s @ y)
        if sy > 1e-12:
            hist.append((s, y, 1.0 / sy))
            if len(hist) > m:
                hist.pop(0)
        done = abs(f - fn) <= ftol * max(1.0, abs(f))
        x, f, g = xn, fn, gn
        if done:
            reason = "ftol"
            break
        if float(np.abs(g).max()) < gtol:
            reason = "gtol"
            break
        if time_limit is not None and time.monotonic() - t0 > time_limit:
            reason = "time"
            break
    return x, {"iters": it, "evals": evals, "f0": f0, "f": f, "reason": reason, "time_s": time.monotonic() - t0}


def fit_policy(data: PolicySet, w_prev: np.ndarray, l2: float, temperature: float = 1.0, max_iter: int = 100,
               time_limit: Optional[float] = None, frozen: Optional[np.ndarray] = None,
               start: Optional[np.ndarray] = None) -> tuple[np.ndarray, dict]:
    """Minimise the loss with L2 toward w_prev, starting from `start` (default w_prev).  `frozen`
    (bool mask) keeps those weights at w_prev.  Two L2 terms toward a and b combine exactly into
    one: l2a|w-a|^2 + l2b|w-b|^2 = (l2a+l2b)|w-m|^2 + const, m = (l2a a + l2b b) / (l2a+l2b)."""
    w0 = np.asarray(w_prev, dtype=np.float64)
    x0 = w0 if start is None else np.asarray(start, dtype=np.float64)

    if frozen is None:
        fg = lambda w: data.loss_grad(w, w0, l2, temperature)   # noqa: E731
    else:
        def fg(w):
            loss, g = data.loss_grad(w, w0, l2, temperature)
            g = g.copy()
            g[frozen] = 0.0
            return loss, g
    return lbfgs(fg, x0.copy(), max_iter=max_iter, time_limit=time_limit)
