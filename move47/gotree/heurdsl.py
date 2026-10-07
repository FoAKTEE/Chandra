"""A small, safe rule language for model-written move heuristics (node move47::mcts-llm-hl).

A heuristic job (gotree.jobs kind ``heuristic``) proposes rules in this language.  Nothing a model
writes is ever executed: a rule is a JSON object that this module parses and checks field by
field; the engine compiles the parsed form into bit masks and integer bounds (mcts/rules.py,
csrc/rules.c).  This module is pure Python (it runs inside the worker sandbox, where only
``gotree`` is visible): ``gtree rule-test`` and ``gtree submit`` use it, and it is the reference
matcher the C matcher is tested against.

A rule describes the moves it applies to:

    {"name": "hane-at-the-head-of-two",              # [a-z0-9-], at most 48 characters
     "text": "Hane at the head of two opponent stones when ...",       # 10..300 characters
     "pattern": ["?????",                            # 5 rows of 5 (or 3 rows of 3) around the move
                 "?.OO?",                            # '*' (the centre) is the move itself
                 "?.*X?",
                 "?.X.?",
                 "?????"],
     "conditions": {"atari": false, "libs_after": [3, 4], "line": [3, 9]},
     "weight": 0.8,                                  # logit added to the move's prior, |w| in [0.05, 3]
     "rationale": "why the search's evidence supports it",
     "evidence": ["S1", "S3"], "lessons": ["L4", "G2"]}

Pattern cells are colour-relative: own stones are those of the side to move.

    X own stone      O opponent stone     .  empty point      #  off the board
    x not own        o not opponent       s  any stone        +  on the board      ?  anything

A rule matches a move in any of the 8 orientations of the board (rotations and reflections).

Conditions (all optional; a rule with several matches only where all hold; a range [lo, hi] is
inclusive, a single integer means exactly that value):

    captures            [lo, hi]   stones the move captures
    libs_after          [lo, hi]   liberties of the move's chain after the move (4 = four or more)
    atari               bool       the move leaves an adjacent opponent chain with one liberty
    self_atari          bool       the move's own chain is left with one liberty
    escape              bool       the move saves an own chain that was in atari (2+ liberties after)
    ladder_capture      bool       ... and the chain it puts in atari dies in a ladder
    ladder_escape_fails bool       the move extends an own chain in atari to two liberties and the
                                   ladder still captures it
    adj_opp             {"libs": [lo, hi], "size": [lo, hi]}   an adjacent opponent chain (before
                                   the move) with that many liberties (4 = 4+) and stones
    adj_own             {"libs": [lo, hi], "size": [lo, hi]}   the same for an adjacent own chain
    line                [lo, hi]   line of the move (1 = edge, 2 = second line, ...)
    dist_last           [lo, hi]   distance to the opponent's last move, d = dx + dy + max(dx, dy):
                                   2 adjacent, 3 diagonal, 4 one-point jump, 5 knight's move, ...
                                   (false when there is no last move or it was a pass)

The tactical terms follow mcts/FEATURES.md exactly (capture, atari, self_atari, escape, ladder).
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

from .position import EMPTY, IllegalMove, Position, coord, neighbors, other, point

# ------------------------------------------------------------------ the language
E, M, T, B = 0, 1, 2, 3          # cell states: empty, own (side to move), opponent, off board
CELL_SETS = {
    "X": {M}, "O": {T}, ".": {E}, "#": {B},
    "x": {E, T, B}, "o": {E, M, B}, "s": {M, T}, "+": {E, M, T}, "?": {E, M, T, B},
}
ALPHABET = "".join(CELL_SETS) + "*"
RANGE_KEYS = {"captures": (0, 361), "libs_after": (1, 4), "line": (1, 10), "dist_last": (2, 30)}
BOOL_KEYS = ("atari", "self_atari", "escape", "ladder_capture", "ladder_escape_fails")
CHAIN_KEYS = {"adj_opp", "adj_own"}
CHAIN_FIELDS = {"libs": (1, 4), "size": (1, 361)}
RULE_KEYS = {"name", "text", "pattern", "conditions", "weight", "rationale", "evidence", "lessons"}
NUDGE_KEYS = {"feature", "delta", "rationale", "evidence"}
ANSWER_KEYS = {"analysis", "rules", "nudges"}
W_MIN, W_MAX = 0.05, 3.0         # |weight| of a new rule
NUDGE_MAX = 1.0                  # |delta| of a weight nudge
MAX_RULES, MAX_NUDGES = 4, 6     # per answer
MIN_SPECIFIC = 2                 # constrained cells + 2 per condition, at least
BROAD_FRAC = 0.2                 # a rule matching more than this share of the legal moves is over-broad
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
ID_RE = re.compile(r"[SGLR]\d{1,5}")
LADDER_BUDGET = 100              # as csrc/features.c


class RuleError(ValueError):
    """A rule or answer that does not follow the language; the message says what to fix."""


def _sym_xy(x: int, y: int, s: int, n: int) -> tuple[int, int]:
    if s & 4:
        x, y = y, x
    if s & 1:
        x = n - 1 - x
    if s & 2:
        y = n - 1 - y
    return x, y


def _clean_text(v: Any, label: str, lo: int, hi: int) -> str:
    if not isinstance(v, str):
        raise RuleError(f"{label} must be a string")
    t = " ".join(v.replace("\x00", " ").split())
    if len(t) < lo:
        raise RuleError(f"{label} is too short (at least {lo} characters)")
    if len(t) > hi:
        raise RuleError(f"{label} is too long ({len(t)} > {hi} characters)")
    return t


def _range(v: Any, label: str, bounds: tuple[int, int]) -> list[int]:
    lo_b, hi_b = bounds
    if isinstance(v, bool):
        raise RuleError(f"{label} must be an integer or a [lo, hi] pair, not a boolean")
    if isinstance(v, int):
        v = [v, v]
    if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, int) and not isinstance(x, bool)
                                                                 for x in v)):
        raise RuleError(f"{label} must be an integer or a [lo, hi] pair of integers")
    lo, hi = int(v[0]), int(v[1])
    if lo > hi:
        raise RuleError(f"{label}: lo {lo} > hi {hi}")
    if lo < lo_b or hi > hi_b:
        raise RuleError(f"{label} must lie within [{lo_b}, {hi_b}]")
    return [lo, hi]


def parse_pattern(rows: Any) -> list[str]:
    """The pattern as 5 rows of 5 characters (a 3x3 pattern is padded with '?')."""
    if not isinstance(rows, list) or len(rows) not in (3, 5):
        raise RuleError("pattern must be a list of 3 or 5 strings (a 3x3 or 5x5 grid around the move)")
    k = len(rows)
    out = []
    for i, r in enumerate(rows):
        if not isinstance(r, str):
            raise RuleError("pattern rows must be strings")
        r = r.replace(" ", "")
        if len(r) != k:
            raise RuleError(f"pattern row {i + 1} has {len(r)} cells, expected {k}")
        bad = sorted({c for c in r if c not in ALPHABET})
        if bad:
            raise RuleError(f"pattern row {i + 1} uses {''.join(bad)!r}; allowed: {ALPHABET}")
        out.append(r)
    c = k // 2
    stars = [(y, x) for y, r in enumerate(out) for x, ch in enumerate(r) if ch == "*"]
    if stars != [(c, c)]:
        raise RuleError("the pattern needs exactly one '*' (the move), in the centre")
    if k == 3:
        out = ["?????"] + ["?" + r + "?" for r in out] + ["?????"]
    return out


def parse_conditions(d: Any) -> dict:
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise RuleError("conditions must be an object")
    out: dict = {}
    for k, v in d.items():
        if k in RANGE_KEYS:
            out[k] = _range(v, k, RANGE_KEYS[k])
        elif k in BOOL_KEYS:
            if not isinstance(v, bool):
                raise RuleError(f"{k} must be true or false")
            out[k] = v
        elif k in CHAIN_KEYS:
            if not isinstance(v, dict) or not v or set(v) - set(CHAIN_FIELDS):
                raise RuleError(f"{k} must be an object with 'libs' and/or 'size' ranges")
            out[k] = {f: _range(v[f], f"{k}.{f}", CHAIN_FIELDS[f]) for f in CHAIN_FIELDS if f in v}
        else:
            raise RuleError(f"unknown condition {k!r}; allowed: {', '.join(sorted([*RANGE_KEYS, *BOOL_KEYS, *CHAIN_KEYS]))}")
    if out.get("ladder_capture") and out.get("atari") is False:
        raise RuleError("ladder_capture requires the move to give atari")
    if out.get("ladder_escape_fails") and out.get("escape") is False:
        raise RuleError("ladder_escape_fails requires an escape")
    return out


def specificity(pattern: list[str], conditions: dict) -> int:
    """Constrained pattern cells (not '?', not the move) plus two per condition."""
    cells = sum(1 for r in pattern for ch in r if ch not in "?*")
    return cells + 2 * len(conditions)


def variants(pattern: list[str]) -> list[tuple[str, ...]]:
    """The distinct orientations of a 5x5 pattern (each a tuple of 25 cell characters)."""
    out, seen = [], set()
    flat = [ch for r in pattern for ch in r]
    for s in range(8):
        g = ["?"] * 25
        for y in range(5):
            for x in range(5):
                xx, yy = _sym_xy(x, y, s, 5)
                g[yy * 5 + xx] = flat[y * 5 + x]
        t = tuple(g)
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def canonical(rule: dict) -> str:
    """Identity of a rule's meaning (orientation-free pattern + conditions), for duplicates."""
    pat = min("".join(v) for v in variants(rule["pattern"]))
    return pat + "|" + json.dumps(rule.get("conditions") or {}, sort_keys=True)


def parse_rule(obj: Any, strict: bool = True) -> dict:
    """A validated, normalised rule, or RuleError naming the problem.  ``strict``: unknown keys
    (anything outside the language, e.g. code) are refused."""
    if not isinstance(obj, dict):
        raise RuleError("a rule must be an object")
    extra = set(obj) - RULE_KEYS
    if extra and strict:
        raise RuleError(f"unknown rule field(s) {sorted(extra)}; allowed: {sorted(RULE_KEYS)}")
    name = obj.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise RuleError("name must be lower-case letters, digits and '-', at most 48 characters")
    pattern = parse_pattern(obj.get("pattern"))
    cond = parse_conditions(obj.get("conditions"))
    w = obj.get("weight")
    if isinstance(w, bool) or not isinstance(w, (int, float)) or w != w:
        raise RuleError("weight must be a number")
    if not W_MIN <= abs(float(w)) <= W_MAX:
        raise RuleError(f"|weight| must lie within [{W_MIN}, {W_MAX}]")
    if specificity(pattern, cond) < MIN_SPECIFIC:
        raise RuleError(f"over-broad: the rule constrains too little (specificity {specificity(pattern, cond)} < "
                        f"{MIN_SPECIFIC}: constrained cells + 2 per condition)")
    refs = []
    for k in ("evidence", "lessons"):
        v = obj.get(k) or []
        if not isinstance(v, list) or not all(isinstance(x, str) and ID_RE.fullmatch(x.strip().upper()) for x in v):
            raise RuleError(f"{k} must be a list of ids like S1 (surprises) or L4 / G2 (lessons)")
        refs.append(sorted({x.strip().upper() for x in v}))
    out = {"name": name, "text": _clean_text(obj.get("text"), "text", 10, 300), "pattern": pattern,
           "conditions": cond, "weight": round(float(w), 4),
           "rationale": _clean_text(obj.get("rationale", ""), "rationale", 0, 800),
           "evidence": refs[0], "lessons": refs[1]}
    out["canonical"] = canonical(out)
    return out


def parse_nudge(obj: Any, targets: Optional[Iterable[str]] = None) -> dict:
    if not isinstance(obj, dict):
        raise RuleError("a nudge must be an object")
    extra = set(obj) - NUDGE_KEYS
    if extra:
        raise RuleError(f"unknown nudge field(s) {sorted(extra)}; allowed: {sorted(NUDGE_KEYS)}")
    f = obj.get("feature")
    if not isinstance(f, str) or not f.strip():
        raise RuleError("nudge.feature must name a feature or a rule id")
    f = f.strip()
    if targets is not None and f not in set(targets):
        raise RuleError(f"nudge.feature {f!r} is not one of the adjustable weights listed in the job")
    d = obj.get("delta")
    if isinstance(d, bool) or not isinstance(d, (int, float)) or d != d or not 0.02 <= abs(float(d)) <= NUDGE_MAX:
        raise RuleError(f"nudge.delta must be a number with 0.02 <= |delta| <= {NUDGE_MAX}")
    ev = obj.get("evidence") or []
    if not isinstance(ev, list) or not all(isinstance(x, str) and ID_RE.fullmatch(x.strip().upper()) for x in ev):
        raise RuleError("nudge.evidence must be a list of ids like S1")
    return {"feature": f, "delta": round(float(d), 4),
            "rationale": _clean_text(obj.get("rationale", ""), "nudge.rationale", 0, 800),
            "evidence": sorted({x.strip().upper() for x in ev})}


# ------------------------------------------------------------------ the reference matcher
def _states(pos: Position, p: int) -> list[int]:
    """The 5x5 neighbourhood of p, row-major, as cell states relative to the side to move."""
    n = pos.size
    y0, x0 = divmod(p, n)
    me = pos.to_play
    out = []
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            y, x = y0 + dy, x0 + dx
            if not (0 <= y < n and 0 <= x < n):
                out.append(B)
            else:
                c = pos.cells[y * n + x]
                out.append(E if c == EMPTY else M if c == me else T)
    return out


def _pattern_ok(states: list[int], vs: list[tuple[str, ...]]) -> bool:
    for v in vs:
        if all(ch == "*" or st in CELL_SETS[ch] for st, ch in zip(states, v)):
            return True
    return False


def _dist(size: int, p: int, q: int) -> int:
    py, px = divmod(p, size)
    qy, qx = divmod(q, size)
    dx, dy = abs(px - qx), abs(py - qy)
    return dx + dy + max(dx, dy)


def _with_turn(pos: Position, color: str) -> Position:
    return Position(pos.size, pos.cells, color, pos.ko, 0, pos.komi)


def _ladder_defend(pos: Position, s0: int, budget: list) -> bool:
    budget[0] -= 1
    if budget[0] < 0:
        return False
    stones, libs = pos.chain(s0)
    if len(libs) != 1:
        return len(libs) == 0
    dfd = pos.cells[s0]
    att = other(dfd)
    nb = neighbors(pos.size)
    for s in sorted(stones):
        for r in nb[s]:
            if pos.cells[r] == att and len(pos.chain(r)[1]) == 1:
                return False
    lib = next(iter(libs))
    try:
        nxt = _with_turn(pos, dfd).play(lib)
    except IllegalMove:
        return True
    nl2 = len(nxt.chain(lib)[1])
    if nl2 >= 3:
        return False
    if nl2 <= 1:
        return True
    return _ladder_attack(nxt, lib, budget)


def _ladder_attack(pos: Position, s0: int, budget: list) -> bool:
    budget[0] -= 1
    if budget[0] < 0:
        return False
    _, libs = pos.chain(s0)
    if len(libs) != 2:
        return len(libs) <= 1
    att = other(pos.cells[s0])
    for lib in sorted(libs):
        try:
            nxt = _with_turn(pos, att).play(lib)
        except IllegalMove:
            continue
        if len(nxt.chain(s0)[1]) != 1:
            continue
        if _ladder_defend(nxt, s0, budget):
            return True
    return False


class Tactics:
    """The tactical facts of one legal move (the definitions of FEATURES.md)."""

    def __init__(self, pos: Position, p: int):
        n = pos.size
        nb = neighbors(n)[p]
        me, opp = pos.to_play, other(pos.to_play)
        self.captures, self.esc, self.atari_size = 0, False, 0
        self.adj_opp: list[tuple[int, int]] = []     # (liberties capped at 4, size) per distinct chain
        self.adj_own: list[tuple[int, int]] = []
        seen: set[int] = set()
        for r in nb:
            c = pos.cells[r]
            if c == EMPTY or r in seen:
                continue
            st, lib = pos.chain(r)
            seen |= st
            nl = len(lib)
            if c == opp:
                self.adj_opp.append((min(4, nl), len(st)))
                if nl == 1:
                    self.captures += len(st)
                elif nl == 2:
                    self.atari_size = max(self.atari_size, len(st))
            else:
                self.adj_own.append((min(4, nl), len(st)))
                if nl == 1:
                    self.esc = True
        self.after = pos.play(p)
        st, lib = self.after.chain(p)
        self.libs_after = min(4, len(lib))
        self.size_after = len(st)
        self._pos, self._p = pos, p
        self._ladder_cap: Optional[bool] = None
        self._ladder_esc: Optional[bool] = None

    @property
    def atari(self) -> bool:
        return self.atari_size > 0

    @property
    def self_atari(self) -> bool:
        return self.libs_after == 1

    @property
    def escape(self) -> bool:
        return self.esc and self.libs_after >= 2

    @property
    def ladder_capture(self) -> bool:
        if self._ladder_cap is None:
            self._ladder_cap = False
            if self.atari:
                nxt, opp = self.after, other(self._pos.to_play)
                for r in neighbors(self._pos.size)[self._p]:
                    if nxt.cells[r] == opp and len(nxt.chain(r)[1]) == 1 and _ladder_defend(nxt, r, [LADDER_BUDGET]):
                        self._ladder_cap = True
                        break
        return self._ladder_cap

    @property
    def ladder_escape_fails(self) -> bool:
        if self._ladder_esc is None:
            self._ladder_esc = bool(self.esc and self.libs_after == 2 and
                                    _ladder_attack(self.after, self._p, [LADDER_BUDGET]))
        return self._ladder_esc


def _in(v: int, r: list[int]) -> bool:
    return r[0] <= v <= r[1]


def conditions_hold(cond: dict, pos: Position, p: int, tac: Optional[Tactics] = None) -> bool:
    n = pos.size
    if "line" in cond:
        y, x = divmod(p, n)
        if not _in(min(x, y, n - 1 - x, n - 1 - y) + 1, cond["line"]):
            return False
    if "dist_last" in cond:
        if pos.last is None or not _in(_dist(n, p, pos.last), cond["dist_last"]):
            return False
    if not (set(cond) - {"line", "dist_last"}):
        return True
    t = tac or Tactics(pos, p)
    if "captures" in cond and not _in(t.captures, cond["captures"]):
        return False
    if "libs_after" in cond and not _in(t.libs_after, cond["libs_after"]):
        return False
    for k in BOOL_KEYS:
        if k in cond and bool(getattr(t, k)) != cond[k]:
            return False
    for k in ("adj_opp", "adj_own"):
        if k in cond:
            c = cond[k]
            ok = any(("libs" not in c or _in(lb, c["libs"])) and ("size" not in c or _in(sz, c["size"]))
                     for lb, sz in getattr(t, k))
            if not ok:
                return False
    return True


class CompiledRule:
    """A parsed rule with its orientations, for repeated matching in Python."""

    def __init__(self, rule: dict):
        self.rule = rule
        self.vs = variants(rule["pattern"])
        self.cond = rule.get("conditions") or {}

    def matches(self, pos: Position, p: Optional[int]) -> bool:
        if p is None or pos.cells[p] != EMPTY or pos.terminal:
            return False
        if not _pattern_ok(_states(pos, p), self.vs):
            return False
        try:
            return conditions_hold(self.cond, pos, p)
        except IllegalMove:
            return False

    def hits(self, pos: Position, moves: Optional[Iterable[int]] = None) -> list[int]:
        ms = pos.legal_moves() if moves is None else [m for m in moves if m is not None]
        return [m for m in ms if self.matches(pos, m)]


def match_rate(rule: dict, positions: Iterable[Position]) -> tuple[int, int]:
    """(matched legal moves, legal moves) over the positions."""
    cr = CompiledRule(rule)
    hit = tot = 0
    for pos in positions:
        lm = pos.legal_moves()
        tot += len(lm)
        hit += len(cr.hits(pos, lm))
    return hit, tot


# ------------------------------------------------------------------ heuristic-job answers
def parse_answer(r: Any, targets: Optional[Iterable[str]] = None, positions: Optional[list[Position]] = None,
                 broad_frac: float = BROAD_FRAC) -> dict:
    """Validate a heuristic job's answer.  Every rule and nudge must follow the language (a list of
    all problems is raised otherwise, so the worker can fix them in one go).  With ``positions``
    (the job's surprise positions), a rule matching more than ``broad_frac`` of their legal moves
    is refused as over-broad."""
    if not isinstance(r, dict):
        raise RuleError("the answer must be a JSON object")
    extra = set(r) - ANSWER_KEYS
    if extra:
        raise RuleError(f"unknown answer field(s) {sorted(extra)}; allowed: {sorted(ANSWER_KEYS)}")
    rules_in, nudges_in = r.get("rules") or [], r.get("nudges") or []
    if not isinstance(rules_in, list) or not isinstance(nudges_in, list):
        raise RuleError("rules and nudges must be lists")
    if len(rules_in) > MAX_RULES or len(nudges_in) > MAX_NUDGES:
        raise RuleError(f"at most {MAX_RULES} rules and {MAX_NUDGES} nudges per answer")
    errors, rules, nudges, names, canon = [], [], [], set(), set()
    tl = list(targets) if targets is not None else None
    for i, x in enumerate(rules_in):
        try:
            rule = parse_rule(x)
            if rule["name"] in names:
                raise RuleError(f"duplicate name {rule['name']!r}")
            if rule["canonical"] in canon:
                raise RuleError("the same pattern and conditions as another rule in this answer")
            if positions:
                hit, tot = match_rate(rule, positions)
                rule["surprise_match"] = [hit, tot]
                if tot and hit > broad_frac * tot:
                    raise RuleError(f"over-broad: it matches {hit} of the {tot} legal moves in the surprise "
                                    f"positions ({hit / tot:.0%} > {broad_frac:.0%}); constrain the pattern or "
                                    f"add conditions")
            names.add(rule["name"])
            canon.add(rule["canonical"])
            rules.append(rule)
        except RuleError as e:
            errors.append(f"rule {i + 1}: {e}")
    for i, x in enumerate(nudges_in):
        try:
            nudges.append(parse_nudge(x, tl))
        except RuleError as e:
            errors.append(f"nudge {i + 1}: {e}")
    if errors:
        raise RuleError("; ".join(errors))
    return {"analysis": _clean_text(r.get("analysis", ""), "analysis", 0, 2000), "rules": rules, "nudges": nudges}


def describe(rule: dict) -> str:
    """A readable one-block rendering: the grid (3x3 if the outer ring is all '?') and conditions."""
    pat = rule["pattern"]
    if all(ch == "?" for ch in pat[0] + pat[4] + "".join(r[0] + r[4] for r in pat)):
        pat = [r[1:4] for r in pat[1:4]]
    cond = rule.get("conditions") or {}
    parts = []
    for k, v in cond.items():
        if isinstance(v, bool):
            parts.append(k if v else f"not {k}")
        elif isinstance(v, dict):
            parts.append(f"{k}(" + ", ".join(f"{f} {a}-{b}" if a != b else f"{f} {a}" for f, (a, b) in v.items()) + ")")
        else:
            parts.append(f"{k} {v[0]}" if v[0] == v[1] else f"{k} {v[0]}-{v[1]}")
    return " / ".join(pat) + (" ; " + ", ".join(parts) if parts else "")


def rule_test_report(raw: Any, surprises: list[dict], targets: Optional[list[str]] = None) -> str:
    """What ``gtree rule-test`` prints: parse errors, or per surprise position the points where the
    rule matches (S1: 'C4* D5', * = the search's preferred move) and the share of legal moves."""
    items = raw.get("rules") if isinstance(raw, dict) and "rules" in raw else (raw if isinstance(raw, list) else [raw])
    lines = []
    for i, x in enumerate(items):
        try:
            rule = parse_rule(x)
        except RuleError as e:
            lines.append(f"rule {i + 1}: INVALID: {e}")
            continue
        cr = CompiledRule(rule)
        hit = tot = 0
        rows = []
        for s in surprises:
            pos = Position.from_dict(s["position"])
            lm = pos.legal_moves()
            h = cr.hits(pos, lm)
            hit += len(h)
            tot += len(lm)
            pref = {point(m, pos.size) for m in s.get("preferred", []) if m and m != "pass"}
            rows.append(f"  {s['id']}: " + (" ".join(coord(m, pos.size) + ("*" if m in pref else "") for m in h)
                                            or "(no match)"))
        frac = hit / tot if tot else 0.0
        lines.append(f"rule {i + 1} {rule['name']}: {describe(rule)}")
        lines.append(f"  matches {hit} of {tot} legal moves ({frac:.1%})"
                     + ("  -> OVER-BROAD (limit {:.0%})".format(BROAD_FRAC) if frac > BROAD_FRAC else ""))
        lines.extend(rows)
    if targets:
        lines.append("adjustable weights for nudges: " + ", ".join(targets))
    return "\n".join(lines) + "\n(* = a move the search preferred at that surprise)"


__all__ = ["RuleError", "parse_rule", "parse_nudge", "parse_answer", "CompiledRule", "Tactics", "variants",
           "canonical", "specificity", "match_rate", "describe", "rule_test_report", "CELL_SETS", "BROAD_FRAC"]
