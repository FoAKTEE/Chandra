"""The weighted playout policy as a standalone object (the tree keeps its own copy)."""
from __future__ import annotations

from typing import Optional

import numpy as np

from ._lib import N_FEATURES, lib, plib
from .board import Board
from .weights import Weights, load_default


class Policy:
    """softmax(sum of active weights / temperature) over the legal non-eye moves."""

    def __init__(self, weights: Optional[Weights] = None, playout_temperature: Optional[float] = None,
                 prior_temperature: Optional[float] = None, ladders_playout: bool = False, ladders_prior: bool = True):
        self.weights = weights or load_default()
        tp = playout_temperature or float(self.weights.params.get("playout_temperature", 1.0))
        tpr = prior_temperature or float(self.weights.params.get("prior_temperature", 1.0))
        self.ptr = plib.mc_policy_new()
        if not self.ptr:
            raise MemoryError("mc_policy_new failed")
        plib.mc_policy_set(self.ptr, self.weights.w.ctypes.data, N_FEATURES, tp, tpr, int(ladders_playout),
                           int(ladders_prior))

    def __del__(self):
        if getattr(self, "ptr", None):
            plib.mc_policy_free(self.ptr)
            self.ptr = None

    def playouts(self, board: Board, n: int, seed: int = 0) -> np.ndarray:
        """Final Tromp-Taylor scores (black - white - komi) of n playouts from `board` (GIL released)."""
        out = np.empty(n, dtype=np.float32)
        lib.mcb_playouts(board._b, self.ptr, seed, n, out.ctypes.data)
        return out
