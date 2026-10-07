"""The move-feature spec shared by the playout policy and the tree priors (see FEATURES.md).

    features(position, move)       -> sorted list of active feature indices
    move_logits(position, weights) -> {move: sum of the active weights} for every legal move
    feature_names()                -> the name of every index (the weight-vector layout)

`position` is an ``mcts.board.Board`` or a ``gotree.position.Position`` (a Position carries the
last move but not the one before it, so the ``dist_last2`` features are inactive for it).
"""
from __future__ import annotations

import ctypes
import hashlib
from functools import lru_cache
from typing import Optional, Union

import numpy as np

from gotree.position import Position

from ._lib import N_FEATURES, N_PATTERNS, plib
from .board import Board, Move, to_point

SPEC_NAME = "move47-mcts-features-v1"
PAT_CHARS = ".XO#"          # empty, own (side to move), opponent, off-board
NEIGHBOURS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

DIST_BUCKETS = ("2", "3", "4", "5", "6", "7", "8", "9-10", "11+")
TACTICAL = (
    ["capture:1", "capture:2", "capture:3-5", "capture:6+",
     "escape:size1:libs2", "escape:size1:libs3+", "escape:size2+:libs2", "escape:size2+:libs3+",
     "atari:size1", "atari:size2+",
     "self_atari:size1", "self_atari:size2-3", "self_atari:size4+",
     "ladder:capture", "ladder:escape_fails"]
    + [f"dist_last:{b}" for b in DIST_BUCKETS]
    + [f"dist_last2:{b}" for b in DIST_BUCKETS]
    + ["line:1", "line:2", "line:3", "line:4", "line:5+", "eye_fill", "pass", "pass:after_pass"]
)
assert N_FEATURES == N_PATTERNS + len(TACTICAL), "C core and Python feature spec disagree"

Positionish = Union[Board, Position]


def pattern_code(i: int) -> int:
    """Canonical raw code of pattern i: 2 bits per neighbour N NE E SE S SW W NW (N lowest)."""
    return int(plib.mc_pattern_code_at(i))


def pattern_string(code: int) -> str:
    return "".join(PAT_CHARS[(code >> (2 * k)) & 3] for k in range(8))


@lru_cache(maxsize=1)
def feature_names() -> tuple[str, ...]:
    return tuple(f"pat3:{pattern_string(pattern_code(i))}" for i in range(N_PATTERNS)) + tuple(TACTICAL)


@lru_cache(maxsize=1)
def feature_index() -> dict[str, int]:
    return {n: i for i, n in enumerate(feature_names())}


@lru_cache(maxsize=1)
def spec_id() -> str:
    """Hash of the layout; weight files carry it and are refused by a different spec."""
    return SPEC_NAME + ":" + hashlib.sha256("\n".join(feature_names()).encode()).hexdigest()[:12]


def as_board(position: Positionish) -> Board:
    if isinstance(position, Board):
        return position
    if isinstance(position, Position):
        return Board.from_position(position)
    raise TypeError(f"expected an mcts Board or a gotree Position, got {type(position).__name__}")


def features(position: Positionish, move: Move, ladders: bool = True) -> list[int]:
    b = as_board(position)
    p = to_point(move, b.size)
    out = (ctypes.c_int32 * 16)()
    n = plib.mcb_features(b._b, -1 if p is None else p, int(ladders), out)
    if n < 0:
        raise ValueError(f"{b.coord(p)} is not a legal move here")
    return list(out[:n])


def _weights_array(weights) -> np.ndarray:
    w = getattr(weights, "w", weights)
    w = np.ascontiguousarray(w, dtype=np.float64)
    if w.shape != (N_FEATURES,):
        raise ValueError(f"weights must have {N_FEATURES} entries, got {w.shape}")
    return w


def move_logits(position: Positionish, weights, ladders: bool = True) -> dict[Optional[int], float]:
    """{move: logit} for every legal move (None = pass); the policy is softmax(logit / T).  Weights
    that carry model-written rules (mcts.rules, node move47::mcts-llm-hl) add the weights of the
    rules matching each move, as the tree priors do."""
    b = as_board(position)
    w = _weights_array(weights)
    rs = getattr(weights, "ruleset", None) if getattr(weights, "rules", None) else None
    if rs is not None:
        return rs.logits(b, w, ladders)
    cap = b.size * b.size + 1
    moves = (ctypes.c_int16 * cap)()
    logits = (ctypes.c_double * cap)()
    n = plib.mcb_logits(b._b, w.ctypes.data, int(ladders), moves, logits)
    return {(None if moves[i] < 0 else int(moves[i])): float(logits[i]) for i in range(n)}


def move_priors(position: Positionish, weights, temperature: float = 1.0,
                ladders: bool = True) -> dict[Optional[int], float]:
    lg = move_logits(position, weights, ladders)
    if not lg:
        return {}
    m = max(lg.values())
    ex = {k: float(np.exp((v - m) / temperature)) for k, v in lg.items()}
    z = sum(ex.values())
    return {k: v / z for k, v in ex.items()}
