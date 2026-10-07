"""Versioned policy weights (one weight per feature of FEATURES.md) and weight providers.

A weight file is JSON:

    {"format": "move47-mcts-weights/1", "spec": "<features.spec_id()>", "version": "default-v1",
     "description": "...", "params": {"playout_temperature": 1.0, ...},
     "weights": {"capture:1": 2.0, "pat3:...": 1.0, ...}}      # non-zero weights by feature name

`params` may also carry the mixing weights a learner fits (`lam`, `beta`); the engine applies the
params it knows (see MCTSConfig) when it picks the weights up.  A file may also carry `rules`
(node move47::mcts-llm-hl): model-written rules in the gotree.heurdsl language, each with its
weight, which the tree priors add to matching moves (mcts/rules.py; never used in playouts):

    "rules": [{"id": "R1", "name": "...", "pattern": [5 rows], "conditions": {...}, "w": 0.7}]  The hand-written default below is
the starting point the online learner (M7) replaces; `python3 -m mcts weights --write-default`
regenerates mcts/weights/default-v1.json from this code (a test checks they agree).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, Union

import numpy as np

from ._lib import N_FEATURES, N_PATTERNS
from .features import feature_index, feature_names, pattern_code, spec_id

FORMAT = "move47-mcts-weights/1"
WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
DEFAULT_PATH = WEIGHTS_DIR / "default-v1.json"


@dataclass
class Weights:
    w: np.ndarray
    version: str = "unversioned"
    params: dict = field(default_factory=dict)
    description: str = ""
    rules: list = field(default_factory=list)       # model-written rules (mcts.rules), in index order
    w_rules: Optional[np.ndarray] = None            # one weight per rule

    def __post_init__(self):
        self.w = np.ascontiguousarray(self.w, dtype=np.float64)
        if self.w.shape != (N_FEATURES,):
            raise ValueError(f"weights must have {N_FEATURES} entries")
        self.rules = list(self.rules or [])
        self.w_rules = np.zeros(len(self.rules)) if self.w_rules is None else \
            np.ascontiguousarray(self.w_rules, dtype=np.float64)
        if self.w_rules.shape != (len(self.rules),):
            raise ValueError("w_rules must have one weight per rule")
        self._rs = None

    @property
    def digest(self) -> str:
        h = hashlib.sha256(self.w.tobytes())
        h.update(json.dumps(self.params, sort_keys=True).encode())
        if self.rules:
            from .rules import rules_digest
            h.update(rules_digest(self.rules, self.w_rules).encode())
        return h.hexdigest()[:16]

    @property
    def full(self) -> np.ndarray:
        """The feature weights followed by the rule weights (the learner's parameter vector)."""
        return np.concatenate([self.w, self.w_rules]) if self.rules else self.w

    @property
    def ruleset(self):
        """The compiled rules with their weights (mcts.rules.RuleSet), None without rules."""
        if not self.rules:
            return None
        from .rules import RuleSet, rules_digest
        d = rules_digest(self.rules, self.w_rules)
        if self._rs is None or self._rs[0] != d:
            self._rs = (d, RuleSet(self.rules, self.w_rules))
        return self._rs[1]

    def with_rules(self, rules: list, w_rules, version: Optional[str] = None) -> "Weights":
        return Weights(self.w.copy(), version or self.version, dict(self.params), self.description, list(rules),
                       np.asarray(w_rules, dtype=np.float64))

    def to_json(self) -> dict:
        names = feature_names()
        d = {"format": FORMAT, "spec": spec_id(), "version": self.version, "description": self.description,
             "params": self.params,
             "weights": {names[i]: round(float(self.w[i]), 6) for i in np.flatnonzero(self.w)}}
        if self.rules:
            from .rules import rules_json
            d["rules"] = rules_json(self.rules, self.w_rules)
        return d

    def save(self, path: Union[str, Path]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(self.to_json(), indent=1) + "\n")
        os.replace(tmp, path)
        return path

    @classmethod
    def from_json(cls, d: dict) -> "Weights":
        if d.get("format") != FORMAT:
            raise ValueError(f"not a weight file ({d.get('format')!r})")
        if d.get("spec") != spec_id():
            raise ValueError(f"weight file is for feature spec {d.get('spec')}, this build has {spec_id()}")
        idx = feature_index()
        w = np.zeros(N_FEATURES)
        for name, v in d.get("weights", {}).items():
            if name not in idx:
                raise ValueError(f"unknown feature {name!r}")
            w[idx[name]] = float(v)
        rules, wr = [], None
        if d.get("rules"):
            from .rules import load_rules
            rules = load_rules(d["rules"])
            wr = np.array([float(e.get("w", 0.0)) for e in d["rules"]])
        return cls(w, d.get("version", "unversioned"), dict(d.get("params") or {}), d.get("description", ""),
                   rules, wr)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Weights":
        return cls.from_json(json.loads(Path(path).read_text()))


# ------------------------------------------------------------------ the hand-written default
# MoGo-style 3x3 shapes (Gelly, Wang, Munos, Teytaud 2006, "Modification of UCT with patterns in
# Monte-Carlo Go"), written as templates around the move (centre).  X / O are the two colours in
# either assignment, x = not X (O, empty or off-board), o = not O, ? = anything, # = off-board.
MOGO_SHAPES = {
    "hane-enclosing": ("XOX", "...", "???"),
    "hane-noncutting": ("XO.", "...", "?.?"),
    "hane-magari": ("XO?", "X..", "x.?"),
    "katatsuke": (".O.", "X..", "..."),
    "cut1-unprotected": ("XO?", "O.o", "?o?"),
    "cut1-peeped": ("XO?", "O.X", "???"),
    "cut2": ("?X?", "O.O", "ooo"),
    "cut-keima": ("OX?", "o.O", "???"),
    "side-chase": ("X.?", "O.?", "###"),
    "side-block-cut": ("OX?", "X.O", "###"),
    "side-block-connection": ("?X?", "x.O", "###"),
    "side-sagari": ("?XO", "x.x", "###"),
    "side-cut": ("?OX", "X.O", "###"),
}
# template cell (row, col) of each neighbour in the order N NE E SE S SW W NW
_CELL = ((0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0), (0, 0))

DEFAULT_TACTICAL = {
    "capture:1": 2.0, "capture:2": 2.5, "capture:3-5": 3.0, "capture:6+": 3.5,
    "escape:size1:libs2": 0.5, "escape:size1:libs3+": 1.5, "escape:size2+:libs2": 1.0, "escape:size2+:libs3+": 2.5,
    "atari:size1": 0.4, "atari:size2+": 0.8,
    "self_atari:size1": -1.0, "self_atari:size2-3": -2.5, "self_atari:size4+": -4.0,
    "ladder:capture": 1.5, "ladder:escape_fails": -2.5,
    "dist_last:2": 1.0, "dist_last:3": 1.0, "dist_last:4": 0.6, "dist_last:5": 0.4, "dist_last:6": 0.2,
    "dist_last2:2": 0.3, "dist_last2:3": 0.3, "dist_last2:4": 0.2,
    "line:1": -1.0, "line:2": -0.2, "line:3": 0.2, "line:4": 0.1,
    "eye_fill": -6.0, "pass": -4.0, "pass:after_pass": 2.0,
}
MOGO_WEIGHT = 1.0
EMPTY_TRIANGLE_WEIGHT = -0.5


def _sym(code: int, sigma: int) -> int:
    k, refl, out = sigma & 3, sigma >> 2, 0
    for i in range(8):
        v = (code >> (2 * i)) & 3
        j = ((8 - i) + 2 * k) & 7 if refl else (i + 2 * k) & 7
        out |= v << (2 * j)
    return out


def _matches(code: int, tpl: tuple[str, str, str], a: int, b: int) -> bool:
    for i, (r, c) in enumerate(_CELL):
        v, ch = (code >> (2 * i)) & 3, tpl[r][c]
        ok = {"X": v == a, "O": v == b, ".": v == 0, "x": v != a, "o": v != b, "?": True, "#": v == 3}[ch]
        if not ok:
            return False
    return True


def mogo_shape(code: int) -> Optional[str]:
    """Name of the first MoGo shape that the pattern matches (any symmetry, either colour)."""
    for name, tpl in MOGO_SHAPES.items():
        for s in range(8):
            c = _sym(code, s)
            if _matches(c, tpl, 1, 2) or _matches(c, tpl, 2, 1):
                return name
    return None


def empty_triangle(code: int) -> bool:
    """Own stones on two orthogonal neighbours with the diagonal between them empty, no opponent."""
    v = [(code >> (2 * i)) & 3 for i in range(8)]
    if 2 in v:
        return False
    return any(v[o1] == 1 and v[o2] == 1 and v[dg] == 0 for o1, dg, o2 in ((0, 1, 2), (2, 3, 4), (4, 5, 6), (6, 7, 0)))


def default_weights() -> Weights:
    idx = feature_index()
    w = np.zeros(N_FEATURES)
    for name, v in DEFAULT_TACTICAL.items():
        w[idx[name]] = v
    for i in range(N_PATTERNS):
        code = pattern_code(i)
        if mogo_shape(code):
            w[i] = MOGO_WEIGHT
        elif empty_triangle(code):
            w[i] = EMPTY_TRIANGLE_WEIGHT
    return Weights(w, "default-v1", {"playout_temperature": 1.0, "prior_temperature": 1.0},
                   "hand-written default: tactical preferences, MoGo 3x3 shapes +1, empty triangle -0.5 "
                   "(mcts/weights.py, FEATURES.md)")


def load_default() -> Weights:
    return Weights.load(DEFAULT_PATH) if DEFAULT_PATH.exists() else default_weights()


# ------------------------------------------------------------------ providers
class WeightsProvider(Protocol):
    def get(self) -> Weights: ...


class StaticWeights:
    """Always the same weights (set() swaps them; the engine picks the change up at the next search)."""

    def __init__(self, weights: Optional[Weights] = None):
        self._w = weights or load_default()

    def get(self) -> Weights:
        return self._w

    def set(self, weights: Weights) -> None:
        self._w = weights


class FileWeights:
    """Weights from a file that a learner rewrites (atomically); re-read when it changes."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self._sig: Optional[tuple] = None
        self._w: Optional[Weights] = None

    def get(self) -> Weights:
        st = self.path.stat()
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        if sig != self._sig or self._w is None:
            self._w = Weights.load(self.path)
            self._sig = sig
        return self._w


def as_provider(weights) -> WeightsProvider:
    if weights is None:
        return StaticWeights()
    if isinstance(weights, Weights):
        return StaticWeights(weights)
    if isinstance(weights, (str, Path)):
        return FileWeights(weights)
    if hasattr(weights, "get"):
        return weights
    raise TypeError("weights must be Weights, a path, or an object with get()")
