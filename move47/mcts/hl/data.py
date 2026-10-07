"""Learner samples and their featurization.

A sample is one well-visited tree node: the position, the visit distribution of its children
(the policy target), the backed-up winrate q (the value target; the playout-only part ``qp``
separately when the engine gives it), its visits and the game it came from.  Samples are keyed by
the node's Zobrist key; the held-out split is a fixed function of that key ("split by node"), so a
position lands on the same side of the split in every update, game and process.

Policy rows: for every legal move of a sample (the same move set as the tree's edges: all legal
points plus pass), the active feature indices of FEATURES.md with ladders on, as the tree priors
compute them.  Stored flat (``fi``) with the number of features per row (``nf``).
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Optional, Union

import numpy as np

from gotree.position import IllegalMove, Position

from .._lib import plib
from ..board import Board, to_point

PASS = -1
_GOLD = 0x9E3779B97F4A7C15
_M64 = (1 << 64) - 1


def as_board(position: Union[Board, Position, dict]) -> Board:
    if isinstance(position, Board):
        return position
    if isinstance(position, Position):
        return Board.from_position(position)
    if isinstance(position, dict):
        return Board.from_dict(position)
    raise TypeError(f"expected a Board, Position or board dict, got {type(position).__name__}")


def limit_blas_threads(n: int = 1) -> int:
    """Cap numpy's OpenBLAS thread pool (it otherwise starts up to 64 busy-waiting threads for the
    learner's small matrix products, beyond the thread budget).  Returns how many libraries took it."""
    import glob
    import os
    done = 0
    d = os.path.dirname(np.__file__)
    for lib in glob.glob(os.path.join(d, "..", "numpy.libs", "*openblas*")) + glob.glob(os.path.join(d, ".libs", "*openblas*")):
        try:
            h = ctypes.CDLL(lib)
        except OSError:
            continue
        for name in ("scipy_openblas_set_num_threads64_", "scipy_openblas_set_num_threads", "openblas_set_num_threads64_",
                     "openblas_set_num_threads"):
            f = getattr(h, name, None)
            if f is not None:
                f(ctypes.c_int(int(n)))
                done += 1
                break
    return done


def heldout(key: int, frac: float) -> bool:
    """The fixed held-out split: a node is held out iff a mixed hash of its key falls below frac."""
    return ((int(key) * _GOLD) & _M64) / 2.0 ** 64 < frac


def move_code(m, size: int) -> Optional[int]:
    """A move (point, coordinate, None / 'pass' / -1) as an int with PASS = -1; None if unusable."""
    try:
        p = to_point(m, size)
    except (IllegalMove, ValueError, TypeError):
        return None
    return PASS if p is None else int(p)


def norm_dist(d: Optional[dict], size: int) -> dict[int, float]:
    """{move: weight} -> {move code: probability} over the positive entries (empty if none)."""
    out: dict[int, float] = {}
    for m, p in (d or {}).items():
        c = move_code(m, size)
        if c is None or p is None or not np.isfinite(p) or p <= 0:
            continue
        out[c] = out.get(c, 0.0) + float(p)
    z = sum(out.values())
    return {k: v / z for k, v in out.items()} if z > 0 else {}


@dataclass
class Sample:
    sid: int                       # sequence number (monotone over the run)
    key: int                       # node key (Zobrist: stones, side to move, ko, passes)
    board: dict                    # Board.to_dict()
    pi: dict                       # {move code: visit share}
    q: Optional[float]             # backed-up winrate for the side to move
    qp: Optional[float]            # its playout-only part (None if the engine did not say)
    n: int                         # visits of the node
    depth: int                     # below the root of the search that produced it
    game: int                      # game counter of the learner
    version: str                   # weights version in use when it was observed
    t: float                       # unix time

    @property
    def to_play(self) -> str:
        return self.board["to_play"]

    @property
    def size(self) -> int:
        return int(self.board["size"])

    def board_obj(self) -> Board:
        return Board.from_dict(self.board)

    def to_json(self) -> dict:
        return {"sid": self.sid, "key": f"{self.key:016x}", "b": self.board,
                "pi": {str(k): round(v, 5) for k, v in self.pi.items()},
                "q": None if self.q is None else round(self.q, 5), "qp": None if self.qp is None else round(self.qp, 5),
                "n": self.n, "d": self.depth, "g": self.game, "v": self.version, "t": round(self.t, 2)}

    @classmethod
    def from_json(cls, d: dict) -> "Sample":
        return cls(int(d["sid"]), int(d["key"], 16), d["b"], {int(k): float(v) for k, v in d["pi"].items()},
                   d.get("q"), d.get("qp"), int(d["n"]), int(d.get("d", 0)), int(d.get("g", 0)), d.get("v", ""),
                   float(d.get("t", 0.0)))


# ------------------------------------------------------------------ policy rows
@dataclass
class PolicyRows:
    moves: np.ndarray              # int16 (R,), PASS = -1
    nf: np.ndarray                 # int32 (R,), active features per move
    fi: np.ndarray                 # int32 (sum nf,), feature indices, row after row


_FEAT_BUF = (ctypes.c_int32 * 16)()


def policy_rows(b: Board, ladders: bool = True) -> PolicyRows:
    """Feature rows of every legal move of b (the tree's edge set: legal points plus pass)."""
    size = b.size
    cap = size * size + 1
    mv = (ctypes.c_int16 * cap)()
    lg = (ctypes.c_double * cap)()
    zero = _zero_weights()
    n = plib.mcb_logits(b._b, zero.ctypes.data, int(ladders), mv, lg)
    moves = np.array(mv[:n], dtype=np.int16)
    nf = np.empty(n, dtype=np.int32)
    fi: list[int] = []
    for i in range(n):
        k = plib.mcb_features(b._b, int(moves[i]), int(ladders), _FEAT_BUF)
        if k < 0:
            raise ValueError("move set and features disagree")
        nf[i] = k
        fi.extend(_FEAT_BUF[:k])
    return PolicyRows(moves, nf, np.array(fi, dtype=np.int32))


_ZERO: Optional[np.ndarray] = None


def _zero_weights() -> np.ndarray:
    global _ZERO
    if _ZERO is None:
        from .._lib import N_FEATURES
        _ZERO = np.zeros(N_FEATURES)
    return _ZERO


def censor_rows(rows: PolicyRows, t: np.ndarray) -> tuple[PolicyRows, np.ndarray]:
    """Keep only the moves the search visited (t > 0).  Below the root, progressive widening admits
    moves in prior order, so a move that was never admitted has no visits whatever its merit; its
    zero says nothing about the move, and fitting it would push the prior further in the direction
    it already had (self-reinforcement).  The censored likelihood normalises over the visited moves."""
    keep = t > 0
    st = np.concatenate([[0], np.cumsum(rows.nf)])
    idx = np.flatnonzero(keep)
    fi = np.concatenate([rows.fi[st[i]:st[i + 1]] for i in idx]) if len(idx) else np.zeros(0, np.int32)
    return PolicyRows(rows.moves[keep], rows.nf[keep], fi.astype(np.int32)), t[keep] / t[keep].sum()


def target_vector(rows: PolicyRows, pi: dict) -> Optional[np.ndarray]:
    """The visit distribution aligned with rows.moves (moves outside the legal set dropped)."""
    t = np.zeros(len(rows.moves))
    pos = {int(m): i for i, m in enumerate(rows.moves)}
    for m, p in pi.items():
        i = pos.get(int(m))
        if i is not None:
            t[i] += p
    s = t.sum()
    return t / s if s > 0 else None
