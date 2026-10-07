"""Model-written rules as features of the tree prior (node move47::mcts-llm-hl).

A rule comes from a heuristic job in the language of ``gotree/heurdsl.py`` (parsed and checked
there; nothing a model writes is executed).  This module compiles parsed rules into the flat
integer spec of ``csrc/rules.c``: for every distinct orientation of the 5x5 pattern, four bit masks
(the cells where empty / own / opponent / off-board is not allowed), and the conditions as integer
bounds.  The engine adds a matching rule's weight to the move's logit when it expands a node
(``MCTS`` pushes the rules of its weights with ``mc_tree_set_rules``); playouts never use rules.

    rs = RuleSet([{"id": "R1", "name": ..., "pattern": [...], "conditions": {...}}], weights=[0.7])
    rs.hits(board, moves)   -> (counts per move, rule indices)     # what the learner's rows use
    rs.matches(board, move) -> [rule indices]
"""
from __future__ import annotations

import ctypes
import hashlib
import json
from typing import Iterable, Optional, Sequence

import numpy as np

from gotree.heurdsl import CELL_SETS, parse_rule, variants

from ._lib import MAX_RULES, RULE_INTS, plib

S_NV, S_FORBID, S_CAP, S_LIBS, S_LINE, S_DIST = 0, 1, 33, 35, 37, 39
S_ATARI, S_SELF, S_ESC, S_LCAP, S_LESC, S_OPP, S_OWN = 41, 42, 43, 44, 45, 46, 51
BOOLS = (("atari", S_ATARI), ("self_atari", S_SELF), ("escape", S_ESC), ("ladder_capture", S_LCAP),
         ("ladder_escape_fails", S_LESC))
RANGES = (("captures", S_CAP), ("libs_after", S_LIBS), ("line", S_LINE), ("dist_last", S_DIST))


def rule_core(rule: dict) -> dict:
    """The part of a rule that decides what it matches (what weight files store)."""
    return {"pattern": list(rule["pattern"]), "conditions": dict(rule.get("conditions") or {})}


def compile_rule(rule: dict) -> np.ndarray:
    """The flat int32 spec of one parsed rule (csrc/rules.c layout)."""
    spec = np.full(RULE_INTS, -1, dtype=np.int64)
    vs = variants(rule["pattern"])
    spec[S_NV] = len(vs)
    spec[S_FORBID:S_FORBID + 32] = 0
    for vi, v in enumerate(vs):
        for st in range(4):
            mask = 0
            for c, ch in enumerate(v):
                if ch != "*" and st not in CELL_SETS[ch]:
                    mask |= 1 << c
            spec[S_FORBID + 4 * vi + st] = mask
    cond = rule.get("conditions") or {}
    for k, off in RANGES:
        if k in cond:
            spec[off], spec[off + 1] = cond[k]
    for k, off in BOOLS:
        if k in cond:
            spec[off] = 1 if cond[k] else 0
    for k, off in (("adj_opp", S_OPP), ("adj_own", S_OWN)):
        c = cond.get(k)
        spec[off] = 1 if c else 0
        if c:
            if "libs" in c:
                spec[off + 1], spec[off + 2] = c["libs"]
            if "size" in c:
                spec[off + 3], spec[off + 4] = c["size"]
    spec[56:] = 0
    return spec.astype(np.int32)


class RuleSet:
    """Compiled rules with weights, as the C matcher holds them."""

    def __init__(self, rules: Sequence[dict], weights: Optional[Iterable[float]] = None):
        if len(rules) > MAX_RULES:
            raise ValueError(f"at most {MAX_RULES} rules")
        self.rules = [dict(r) for r in rules]
        self.n = len(self.rules)
        self.w = np.zeros(self.n) if weights is None else np.ascontiguousarray(list(weights), dtype=np.float64)
        if self.w.shape != (self.n,):
            raise ValueError("one weight per rule")
        self.spec = np.ascontiguousarray(np.stack([compile_rule(r) for r in self.rules]) if self.n else
                                         np.zeros((0, RULE_INTS), dtype=np.int32), dtype=np.int32)
        self.ptr = plib.mc_rules_new()
        if not self.ptr:
            raise MemoryError("mc_rules_new failed")
        plib.mc_rules_load(self.ptr, self.spec.ctypes.data, self.n, self.w.ctypes.data)

    def __del__(self):
        if getattr(self, "ptr", None):
            plib.mc_rules_free(self.ptr)
            self.ptr = None

    @property
    def digest(self) -> str:
        h = hashlib.sha256(self.spec.tobytes())
        h.update(self.w.tobytes())
        return h.hexdigest()[:16]

    def hits(self, board, moves: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """For each move (gotree points, -1 = pass): how many rules match it, and the matching rule
        indices of all moves in order."""
        mv = np.ascontiguousarray(moves, dtype=np.int16)
        counts = np.zeros(len(mv), dtype=np.int32)
        cap = max(1, len(mv) * max(1, self.n))
        idx = np.zeros(cap, dtype=np.int32)
        if self.n == 0 or len(mv) == 0:
            return counts, idx[:0]
        tot = plib.mcb_rule_hits(board._b, self.ptr, mv.ctypes.data, len(mv), counts.ctypes.data,
                                 idx.ctypes.data, cap)
        return counts, idx[:tot].copy()

    def matches(self, board, move) -> list[int]:
        from .board import to_point
        p = to_point(move, board.size)
        c, i = self.hits(board, np.array([-1 if p is None else p], dtype=np.int16))
        return [int(x) for x in i]

    def logits(self, board, w: np.ndarray, ladders: bool = True) -> dict:
        """{move: base logit + matching rule weights} for every legal move (as the tree's priors)."""
        size = board.size
        cap = size * size + 1
        moves = (ctypes.c_int16 * cap)()
        lg = (ctypes.c_double * cap)()
        w = np.ascontiguousarray(w, dtype=np.float64)
        n = plib.mcb_logits_r(board._b, w.ctypes.data, int(ladders), self.ptr, moves, lg)
        return {(None if moves[i] < 0 else int(moves[i])): float(lg[i]) for i in range(n)}


def load_rules(entries: Sequence[dict]) -> list[dict]:
    """Rules as weight files store them ({"id", "name", "pattern", "conditions"}), re-checked by the
    rule language (strictly: anything outside it is refused)."""
    out = []
    for e in entries:
        r = parse_rule({"name": e.get("name") or str(e["id"]).lower(), "text": e.get("text") or "rule from a weight file",
                        "pattern": e["pattern"], "conditions": e.get("conditions") or {}, "weight": 1.0,
                        "rationale": ""}, strict=True)
        out.append({"id": str(e["id"]), "name": r["name"], **rule_core(r), "canonical": r["canonical"]})
    return out


def rules_json(rules: Sequence[dict], w: np.ndarray) -> list[dict]:
    return [{"id": r["id"], "name": r.get("name", ""), "pattern": list(r["pattern"]),
             "conditions": r.get("conditions") or {}, "w": round(float(x), 6)} for r, x in zip(rules, w)]


def rules_digest(rules: Sequence[dict], w: np.ndarray) -> str:
    h = hashlib.sha256(json.dumps([[r["id"], r["pattern"], r.get("conditions") or {}] for r in rules],
                                  sort_keys=True).encode())
    h.update(np.ascontiguousarray(w, dtype=np.float64).tobytes())
    return h.hexdigest()[:16]


__all__ = ["RuleSet", "compile_rule", "load_rules", "rules_json", "rules_digest", "rule_core"]
