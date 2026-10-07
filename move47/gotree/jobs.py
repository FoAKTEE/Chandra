"""Job protocol between the search orchestrator and LLM workers.

Every job is self-contained and is given to a FRESH context (new API
conversation or new Claude Code / Codex session): the frozen position, the
memory briefing, and one narrowly scoped question.  Nothing carries over
between jobs except through the DAG and the lesson memory — that is the
"reset the endgame" idea from the task description, applied at the finest
grain, so no session ever needs auto-compaction.

Kinds:
  expand    policy + value at a node (candidates with priors, unconventional
            candidates, winrate, plan)
  more      progressive widening: NEW candidates not yet in the tree
  refute    critic: the opponent's strongest answers to a move the search likes
  rollout   LLM self-play: a plausible line of d moves for both sides + the
            evaluation at its end
  decide    pick the move to play from the root summary
  abstract  distil the finished search into reusable lessons
  recall    contamination probe: does the model recognise the position?
  heuristic read a finished search's surprises, the lessons and the current heuristics book of
            the MCTS v2 learner and propose explicit rules (gotree.heurdsl) or weight nudges
            (node move47::mcts-llm-hl)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .perception import position_card
from .position import BLACK, IllegalMove, Position, coord, point

KINDS = ("expand", "more", "refute", "rollout", "decide", "abstract", "recall", "consolidate", "heuristic")

ROLE = """You are one worker inside a tree search that is trying to find the strongest move in a game of Go.
You are shown ONE frozen position. How it arose does not matter: only the stones, whose turn it is, the
ko point and komi. Many workers explore different positions in parallel and a program combines everyone's
judgments in a shared search tree, so: answer only the question asked, be calibrated (do not inflate
confidence), and prefer concrete reading of short sequences over vague principles. Your answer is parsed
by code — follow the output schema exactly and use coordinates exactly as printed on the board
(columns skip the letter I; 'pass' is allowed)."""

TOOLS_CLI = """Tools (shell commands in this directory; use them to read sequences instead of guessing):
  gtree card                       the full position card again
  gtree window P10 [--radius 4]    zoomed view around a point
  gtree try P10 Q11 R10 ...        play a sequence from THIS position (alternating colours, starting with the
                                   side to move) and show the result; illegal moves are reported.  Lines you
                                   try are recorded in the shared tree as explored variations.
  gtree ladder Q11                 does the chain at Q11 die in a ladder?
  gtree known                      what the shared tree already knows about this position
  gtree lessons "<keywords>"       search stored lessons
  gtree schema                     the exact output format with an example
  gtree submit result.json         validate and submit your answer (you can resubmit until it says OK)"""

TOOLS_API = """You have tools: try_moves (play a sequence from this position and see the result), window (zoom in),
ladder (ladder status of a chain), lessons (search stored lessons), and submit (your final answer; call it
exactly once, it validates your answer and tells you if something must be fixed)."""


# ------------------------------------------------------------------ schemas
VALUE_SCHEMA = {
    "type": "object",
    "properties": {
        "winrate": {"type": "number", "description": "probability (0-1) that the side to move wins"},
        "score_lead": {"type": "number", "description": "expected final margin in points for the side to move, komi included"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "why": {"type": "string"},
    },
    "required": ["winrate", "confidence", "why"],
}
CAND_SCHEMA = {
    "type": "array",
    "items": {"type": "object", "properties": {
        "move": {"type": "string"}, "prior": {"type": "number"}, "why": {"type": "string"}},
        "required": ["move", "prior"]},
}
SCHEMAS: dict[str, dict] = {
    "expand": {"type": "object", "properties": {
        "candidates": CAND_SCHEMA,
        "unconventional": {"type": "array", "items": {"type": "object", "properties": {
            "move": {"type": "string"}, "why": {"type": "string"}}, "required": ["move"]}},
        "value": VALUE_SCHEMA,
        "plan": {"type": "string"}},
        "required": ["candidates", "value"]},
    "rollout": {"type": "object", "properties": {
        "moves": {"type": "array", "items": {"type": "string"}},
        "value_at_end": VALUE_SCHEMA,
        "comment": {"type": "string"}},
        "required": ["moves", "value_at_end"]},
    "decide": {"type": "object", "properties": {
        "move": {"type": "string"}, "why": {"type": "string"}}, "required": ["move", "why"]},
    "abstract": {"type": "object", "properties": {
        "lessons": {"type": "array", "items": {"type": "object", "properties": {
            "scope": {"type": "string", "enum": ["local", "global"]},
            "at": {"type": "string", "description": "for local lessons: the point the lesson is about"},
            "text": {"type": "string"},
            "relates_to": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string", "description": "existing lesson id like G3 or L7"},
                "rel": {"type": "string", "enum": ["generalizes", "refines", "contradicts", "example_of"]}},
                "required": ["id", "rel"]}}},
            "required": ["scope", "text"]}}},
        "required": ["lessons"]},
    "recall": {"type": "object", "properties": {
        "recognized": {"type": "boolean"}, "source": {"type": "string"}, "famous_move": {"type": "string"}},
        "required": ["recognized"]},
}
SCHEMAS["more"] = SCHEMAS["expand"]
SCHEMAS["refute"] = SCHEMAS["expand"]
SCHEMAS["consolidate"] = {"type": "object", "properties": {
    "merge": {"type": "array", "items": {"type": "object", "properties": {
        "keep": {"type": "string"}, "retire": {"type": "array", "items": {"type": "string"}},
        "text": {"type": "string"}}, "required": ["keep", "retire"]}},
    "concepts": {"type": "array", "items": {"type": "object", "properties": {
        "text": {"type": "string"}, "children": {"type": "array", "items": {"type": "string"}}},
        "required": ["text", "children"]}},
    "contradictions": {"type": "array", "items": {"type": "object", "properties": {
        "a": {"type": "string"}, "b": {"type": "string"}, "note": {"type": "string"}}, "required": ["a", "b"]}},
    "retire": {"type": "array", "items": {"type": "string"}}},
    "required": ["merge", "concepts"]}

EXAMPLES = {
    "expand": {"candidates": [{"move": "D4", "prior": 0.45, "why": "saves the cutting stones"},
                              {"move": "C3", "prior": 0.2, "why": "..."}],
               "unconventional": [{"move": "K10", "why": "tenuki to the centre; the corner is settled"}],
               "value": {"winrate": 0.55, "score_lead": 2.5, "confidence": "low", "why": "..."},
               "plan": "..."},
    "rollout": {"moves": ["D4", "C3", "D3", "C4"], "value_at_end": {"winrate": 0.48, "score_lead": -1,
                                                                    "confidence": "low", "why": "..."},
                "comment": "..."},
    "decide": {"move": "D4", "why": "..."},
    "abstract": {"lessons": [{"scope": "local", "at": "P10", "text": "...", "relates_to": [{"id": "G2", "rel": "refines"}]},
                             {"scope": "global", "text": "..."}]},
    "recall": {"recognized": False, "source": "", "famous_move": ""},
}
EXAMPLES["more"] = EXAMPLES["expand"]
EXAMPLES["refute"] = EXAMPLES["expand"]
EXAMPLES["consolidate"] = {"merge": [{"keep": "G3", "retire": ["G7"], "text": "merged wording"}],
                           "concepts": [{"text": "a more general principle", "children": ["G3", "L5"]}],
                           "contradictions": [{"a": "G2", "b": "G9", "note": "..."}], "retire": ["L4"]}

# heuristic jobs (move47::mcts-llm-hl): explicit rules in the gotree.heurdsl language, weight nudges
_RANGE = {"oneOf": [{"type": "integer"}, {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}]}
_CHAIN = {"type": "object", "properties": {"libs": _RANGE, "size": _RANGE}}
SCHEMAS["heuristic"] = {"type": "object", "properties": {
    "analysis": {"type": "string", "description": "what the surprises have in common (at most 2000 characters)"},
    "rules": {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "text": {"type": "string"},
        "pattern": {"type": "array", "items": {"type": "string"}, "description": "3 or 5 rows; '*' = the move"},
        "conditions": {"type": "object", "properties": {
            "captures": _RANGE, "libs_after": _RANGE, "line": _RANGE, "dist_last": _RANGE,
            "atari": {"type": "boolean"}, "self_atari": {"type": "boolean"}, "escape": {"type": "boolean"},
            "ladder_capture": {"type": "boolean"}, "ladder_escape_fails": {"type": "boolean"},
            "adj_opp": _CHAIN, "adj_own": _CHAIN}},
        "weight": {"type": "number"}, "rationale": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "lessons": {"type": "array", "items": {"type": "string"}}},
        "required": ["name", "text", "pattern", "weight", "rationale"]}},
    "nudges": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
        "feature": {"type": "string"}, "delta": {"type": "number"}, "rationale": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}}}, "required": ["feature", "delta", "rationale"]}}},
    "required": ["analysis", "rules", "nudges"]}
EXAMPLES["heuristic"] = {
    "analysis": "In S1 and S3 the search preferred extending a stone in atari along the second line ...",
    "rules": [{"name": "block-the-two-stone-hane", "text": "Block directly when the opponent hanes at the head of "
               "your two stones and the block gives atari", "pattern": ["?????", "?.O.?", "?X*.?", "?X..?", "?????"],
               "conditions": {"atari": True, "self_atari": False}, "weight": 0.8,
               "rationale": "S1 and S3: the block was the search's top move but the prior ranked it 9th and 14th",
               "evidence": ["S1", "S3"], "lessons": ["L4"]}],
    "nudges": [{"feature": "atari:size1", "delta": 0.3, "rationale": "S2, S4: ataris on single stones were "
                "consistently under-rated", "evidence": ["S2", "S4"]}]}


@dataclass
class Job:
    kind: str
    key: str                       # node the job is about (canonical frame)
    pos: Position                  # the position as presented (canonical frame of `key`)
    params: dict = field(default_factory=dict)
    memory: str = ""               # memory briefing
    known: str = ""                # what the DAG knows about this node
    context: str = ""              # extra text (root summary for decide/abstract)
    id: int = 0

    def prompt(self, tools: str = TOOLS_CLI) -> str:
        p = self.params
        if self.kind == "heuristic":
            from .heurdsl import __doc__ as dsl_doc
            lang = dsl_doc.split("A rule describes the moves it applies to:", 1)[-1].split("The tactical terms", 1)[0]
            parts = [HEURISTIC_ROLE, "", "=== SURPRISES OF THE LAST SEARCH ===", self.context]
            if self.memory:
                parts += ["", "=== LESSONS (memory L1 / L2) ===", self.memory]
            parts += ["", "=== THE HEURISTICS BOOK AND THE ADJUSTABLE WEIGHTS ===", p.get("book_text", "(empty)"),
                      "", "=== YOUR JOB ===", TASKS["heuristic"].format(rules=p.get("max_rules", 4),
                                                                         nudges=p.get("max_nudges", 6)),
                      "", "=== THE RULE LANGUAGE ===", "A rule describes the moves it applies to:" + lang.rstrip(),
                      "", TOOLS_HEURISTIC, "",
                      "=== OUTPUT (JSON) ===", "Schema:", json.dumps(SCHEMAS["heuristic"]), "Example:",
                      json.dumps(EXAMPLES["heuristic"])]
            return "\n".join(parts)
        me = "Black (X)" if self.pos.to_play == BLACK else "White (O)"
        card = position_card(self.pos, title=p.get("title", "Position"), history=p.get("history"))
        region = ""
        if p.get("region"):
            region = (f" REGIONAL SCOUT: look ONLY at {p['region']}. What are the best moves for {me} there, even if "
                      f"you would not play in this region right now? Judge how good they are honestly via their priors.")
        task = TASKS[self.kind].format(me=me, k=p.get("k", 8), u=p.get("u", 3), d=p.get("d", 8), region=region,
                                       exclude=p.get("exclude", "") or "(none)", target=p.get("target", ""),
                                       time=p.get("time_hint", "a few minutes"))
        if self.kind == "consolidate":
            return "\n".join([CONSOLIDATE_ROLE, "", "=== LESSONS ===", self.context, "", "=== YOUR JOB ===",
                              TASKS["consolidate"], "", "=== OUTPUT (JSON) ===", "Schema:",
                              json.dumps(SCHEMAS["consolidate"]), "Example:", json.dumps(EXAMPLES["consolidate"])])
        parts = [ROLE, "", "=== POSITION ===", card]
        if self.known:
            parts += ["", "=== WHAT THE SHARED TREE ALREADY KNOWS HERE ===", self.known]
        if self.memory:
            parts += ["", "=== MEMORY ===", self.memory]
        if self.context:
            parts += ["", "=== SEARCH SUMMARY ===", self.context]
        parts += ["", "=== YOUR JOB ===", task, "", tools, "",
                  "=== OUTPUT (JSON) ===", "Schema:", json.dumps(SCHEMAS[self.kind]), "Example:",
                  json.dumps(EXAMPLES[self.kind])]
        return "\n".join(parts)

    def to_json(self) -> dict:
        return {"kind": self.kind, "key": self.key, "pos": self.pos.to_dict(), "params": self.params,
                "memory": self.memory, "known": self.known, "context": self.context, "id": self.id}

    @classmethod
    def from_json(cls, d: dict) -> "Job":
        return cls(d["kind"], d["key"], Position.from_dict(d["pos"]), d.get("params", {}), d.get("memory", ""),
                   d.get("known", ""), d.get("context", ""), d.get("id", 0))


CONSOLIDATE_ROLE = """You maintain the long-term memory of a Go-playing search system: a set of lessons (G = global
principles, L = local shape lessons) written after earlier searches. Memory must stay small, non-redundant and
organised as a hierarchy of concepts, so that the right lesson is retrieved at the right time."""

HEURISTIC_ROLE = """You improve the fast move intuition of a Go-playing search system. The system combines model
reasoning with a large Monte Carlo tree search: model workers propose candidate moves with priors and values at
selected positions, and the search tests them over millions of simulations. Every one of those simulations
expands positions using a learned prior: a weighted sum of simple move features (3x3 shapes, captures, ataris,
ladders, distance to the last move, line) plus explicit RULES written by workers like you. The rules are the
system's readable heuristics; a learner refits their weights to what the search concludes, and a rule is kept
only if it makes the prior predict the search's own conclusions better on positions it was not fitted on.
Your answer is parsed by code: follow the output schema and the rule language exactly; coordinates as printed
on each board (columns skip the letter I)."""

TOOLS_HEURISTIC = """Tools (shell commands in this directory):
  gtree card --pos S2              the position card of surprise S2 (without --pos: the root position)
  gtree window C4 --pos S2         zoomed view around a point of S2
  gtree try C4 D5 ... --pos S2     play a sequence from S2 and show the result
  gtree ladder C4 --pos S2         ladder status of the chain at C4 in S2
  gtree lessons "<keywords>"       search stored lessons
  gtree rule-test rules.json       check rules (one rule, a list, or your whole answer): parse errors, and the
                                   points where each rule matches in every surprise position, with the share of
                                   legal moves it matches (over-broad above 20%)
  gtree schema                     the exact output format with an example
  gtree submit result.json         validate and submit your answer (resubmit until it prints OK)"""

TASKS = {
    "expand": """You are {me}'s policy and value function at this position.
1. candidates: up to {k} moves for {me}, each with a prior = your probability that it is the best move here
   (priors should sum to at most 1). Include urgent forcing moves (captures, saving a chain in atari) when relevant.
2. unconventional: up to {u} moves a strong human would dismiss at first glance — e.g. a fifth-line shoulder
   hit, an early tenuki, a sacrifice, a move far from the last move — but which might be good here. They are
   explored separately at low cost; it is fine if most are refuted.
3. value: winrate for {me} (0-1), score lead estimate for {me}, confidence, and the decisive factors.
4. plan: one or two sentences.
Spend about {time}. Read short sequences with the tools before trusting a move.""",
    "more": """The search wants MORE candidate moves for {me} at this position.{region}
These moves are already in the tree, do NOT repeat them: {exclude}
Give up to {k} NEW candidates with priors (relative to each other) and up to {u} unconventional ones, plus your
value judgement as usual. If you honestly see no other reasonable move, return an empty candidates list.""",
    "refute": """CRITIC JOB. The previous move was played by the other side because the search currently believes
it is strong. Your job is to REFUTE it: find {me}'s strongest answers — forcing moves, cuts, invasions,
captures — and read them out with the tools. List up to {k} candidates for {me} with priors, then give the
value for {me} after your best answer. Be skeptical of the previous move, but honest: if it is good, say so
with a low winrate for {me}.""",
    "rollout": """SELF-PLAY JOB. Play a plausible continuation of about {d} moves starting with {me}, alternating
colours, as two strong players who both want to win would. Stop earlier if the local fight is settled and
the next move would be a tenuki you cannot judge. Check captures and legality with the tools if unsure.
Then evaluate the position at the END of your line: value_at_end.winrate is the probability that {me}
(the side to move NOW, at the start of the line) wins.""",
    "decide": """DECISION JOB. The search below has finished for this position. Choose the move {me} should play.
Normally pick the most-visited move. Deviate only if you can point to a concrete refutation the search
missed, and say what it is.""",
    "abstract": """MEMORY JOB. The search below has finished. Write lessons that would let a future search reach
the same conclusion faster in a SIMILAR position: what a strong player should recognise.
- local lessons are about a shape around a specific point ("at") and fire whenever that shape recurs;
- global lessons are about the whole-board situation.
Only write lessons supported by the search evidence (especially the surprises: moves whose result differed
from their prior). Write at most 4. Do NOT use absolute coordinates inside the lesson text — they do not
transfer to other positions; describe the shape instead (e.g. "a shoulder hit on a lone fourth-line stone
when the opponent's wall faces your strong area"). Link a lesson to existing ones (relates_to) when it
generalizes, refines or contradicts them.""",
    "consolidate": """Reorganise the lessons above:
- merge: lessons that say the same thing (keep one id, give the merged wording, list ids to retire);
- concepts: new general principles, each with the ids of the lessons it generalizes (this builds the concept
  tree; a concept may have other concepts as children);
- contradictions: pairs of lessons that disagree (both stay, the link warns future readers);
- retire: lessons that are wrong or useless given the evidence counts.
Be conservative: only merge true duplicates and only retire clearly bad lessons.""",
    "heuristic": """HEURISTIC JOB. Read the surprises above: positions from the last search where the final visit
distribution (what the combined search concluded) disagreed most with the learned prior, and/or with the model
workers' own priors. For each you see the search's preferred moves with visits and winrates, what the learned
prior and the model preferred instead, and the main line.
1. Find what several surprises have in common that a local rule could capture: a shape plus tactical
   conditions that makes a move better (or worse) than the prior thinks. Prefer rules supported by two or more
   surprises; a rule that fits only one position rarely helps on positions it was not fitted on.
2. rules: up to {rules} NEW rules in the rule language below, each with a weight (the logit added to a matching
   move's prior: +1 roughly multiplies its prior by e, negative weights discourage), a one-sentence `text` a
   person can read, a `rationale` citing the surprises (S1, S2, ...) and the lessons (L.., G..) that support it.
   Do not repeat a rule of the book or one listed as rejected unless you change what it matches.
3. nudges: up to {nudges} changes (delta, at most 1.0 in size) to the weight of an existing feature or book rule
   from the list of adjustable weights, when the surprises show it is systematically too high or too low.
4. analysis: a short account of what you saw.
Check every rule with `gtree rule-test` before submitting: it must match the moves you mean (marked *) and stay
narrow; a rule that matches more than 20% of the legal moves is refused as over-broad. An empty rules list is a
valid answer when the surprises show nothing general. Spend a few minutes; read short sequences with the tools
when the reason for a surprise is tactical.""",
    "recall": """MEMORY CHECK. Do you recognise this exact position from a famous game (possibly rotated or
mirrored)? If yes, name the game and the move that was famously played next, in THIS board's coordinates.
Do not guess: answer recognized=false unless you are confident.""",
}


# ------------------------------------------------------------------ validation
class InvalidResult(Exception):
    pass


def parse_move(pos: Position, text: Any, check_legal: bool = True) -> Optional[int]:
    if not isinstance(text, str) or not text.strip():
        raise InvalidResult(f"move must be a coordinate like 'D4' or the word 'pass', got {text!r}")
    p = point(text, pos.size)
    if check_legal and not pos.is_legal(p):
        try:
            pos.play(p)
        except IllegalMove as e:
            raise InvalidResult(f"{text}: illegal ({e.message})")
    return p


def _value(v: Any, label: str) -> dict:
    if not isinstance(v, dict):
        raise InvalidResult(f"{label} must be an object")
    try:
        wr = float(v["winrate"])
    except Exception:
        raise InvalidResult(f"{label}.winrate must be a number")
    if not 0 <= wr <= 1:
        raise InvalidResult(f"{label}.winrate must be between 0 and 1")
    sl = v.get("score_lead")
    try:
        sl = None if sl is None else float(sl)
    except Exception:
        sl = None
    conf = v.get("confidence", "low")
    conf = conf if conf in ("low", "medium", "high") else "low"
    return {"winrate": wr, "score_lead": sl, "confidence": conf, "why": str(v.get("why", ""))[:1500]}


def validate(job: Job, r: Any) -> dict:
    """Check a worker's answer; returns a normalised result or raises InvalidResult
    with a message the worker can act on."""
    if not isinstance(r, dict):
        raise InvalidResult("the answer must be a JSON object")
    pos = job.pos
    k = job.kind
    if k in ("expand", "more", "refute"):
        cands, errors, seen = [], [], set()
        for c in r.get("candidates") or []:
            try:
                p = parse_move(pos, c.get("move") if isinstance(c, dict) else c)
            except InvalidResult as e:
                errors.append(str(e))
                continue
            if p in seen:
                continue
            seen.add(p)
            try:
                pr = max(0.0, float(c.get("prior", 0))) if isinstance(c, dict) else 0.0
            except Exception:
                pr = 0.0
            cands.append({"move": p, "prior": pr, "why": str(c.get("why", ""))[:500] if isinstance(c, dict) else ""})
        unconv = []
        for c in r.get("unconventional") or []:
            try:
                p = parse_move(pos, c.get("move") if isinstance(c, dict) else c)
            except InvalidResult as e:
                errors.append(str(e))
                continue
            if p in seen:
                continue
            seen.add(p)
            unconv.append({"move": p, "why": str(c.get("why", ""))[:500] if isinstance(c, dict) else ""})
        if not cands and k != "more" and not unconv:
            raise InvalidResult("no legal candidates: " + "; ".join(errors[:5]))
        tot = sum(c["prior"] for c in cands)
        if tot <= 0 and cands:
            for c in cands:
                c["prior"] = 1.0 / len(cands)
        elif tot > 1:
            for c in cands:
                c["prior"] /= tot
        val = _value(r.get("value"), "value")
        return {"candidates": cands, "unconventional": unconv, "value": val, "plan": str(r.get("plan", ""))[:1500],
                "warnings": errors}
    if k == "rollout":
        moves = r.get("moves")
        if not isinstance(moves, list):
            raise InvalidResult("moves must be a list of coordinates")
        cur, line, warn = pos, [], []
        for m in moves[: max(1, int(job.params.get("d", 8)) * 2)]:
            try:
                p = parse_move(cur, m)
            except InvalidResult as e:
                warn.append(f"line truncated at move {len(line) + 1}: {e}")
                break
            line.append(p)
            cur = cur.play(p)
            if cur.terminal:
                break
        return {"moves": line, "value_at_end": _value(r.get("value_at_end"), "value_at_end"),
                "comment": str(r.get("comment", ""))[:1500], "warnings": warn}
    if k == "decide":
        return {"move": parse_move(pos, r.get("move")), "why": str(r.get("why", ""))[:2000]}
    if k == "abstract":
        out = []
        for l in (r.get("lessons") or [])[:6]:
            if not isinstance(l, dict) or not str(l.get("text", "")).strip():
                continue
            scope = "local" if l.get("scope") == "local" else "global"
            at = None
            if scope == "local":
                try:
                    at = point(str(l.get("at", "")), pos.size)
                except Exception:
                    scope = "global"
            rel = [x for x in (l.get("relates_to") or []) if isinstance(x, dict)]
            out.append({"scope": scope, "at": at, "text": str(l["text"])[:800], "relates_to": rel})
        return {"lessons": out}
    if k == "consolidate":
        def ids(xs):
            return [str(x).strip().upper() for x in (xs or []) if re.fullmatch(r"[GL]\d+", str(x).strip().upper())]
        merge = [{"keep": str(m.get("keep", "")).upper(), "retire": ids(m.get("retire")), "text": str(m.get("text", ""))[:800]}
                 for m in (r.get("merge") or []) if isinstance(m, dict) and ids([m.get("keep")])]
        concepts = [{"text": str(c.get("text", ""))[:800], "children": ids(c.get("children"))}
                    for c in (r.get("concepts") or []) if isinstance(c, dict) and str(c.get("text", "")).strip()]
        contra = [{"a": str(c.get("a", "")).upper(), "b": str(c.get("b", "")).upper(), "note": str(c.get("note", ""))[:300]}
                  for c in (r.get("contradictions") or []) if isinstance(c, dict) and ids([c.get("a"), c.get("b")]) and
                  len(ids([c.get("a"), c.get("b")])) == 2]
        return {"merge": merge, "concepts": concepts, "contradictions": contra, "retire": ids(r.get("retire"))}
    if k == "heuristic":
        from .heurdsl import RuleError, parse_answer
        sur = [Position.from_dict(x["position"]) for x in (job.params.get("surprises") or []) if x.get("position")]
        try:
            return parse_answer(r, targets=job.params.get("targets"), positions=sur or None)
        except RuleError as e:
            raise InvalidResult(str(e))
    if k == "recall":
        return {"recognized": bool(r.get("recognized")), "source": str(r.get("source", ""))[:300],
                "famous_move": str(r.get("famous_move", ""))[:10]}
    raise InvalidResult(f"unknown job kind {k}")


def describe_known(dag, key: str, pos: Position, limit: int = 12) -> str:
    """Summary of the DAG's knowledge at a node, for prompts and `gtree known`."""
    node = dag.node(key)
    if not node:
        return ""
    st = sorted(dag.child_stats(key), key=lambda c: (-c["n"], -c["prior"]))
    lines = []
    if node["n"]:
        lines.append(f"Visited {node['n']} times; backed-up winrate for the side to move ≈ {node['w'] / node['n']:.2f}.")
    if node["static_value"] is not None:
        lines.append(f"An earlier worker's static estimate: winrate {node['static_value']:.2f} "
                     f"({node['static_conf']}): {(node['static_note'] or '')[:300]}")
    if st:
        lines.append("Moves already in the tree (n = visits, q = backed-up winrate for the mover):")
        for c in st[:limit]:
            q = "—" if c["q"] is None else f"{c['q']:.2f}"
            lines.append(f"  {coord(c['move'], pos.size):<5} n={c['n']:<4} q={q:<5} prior={c['prior']:.2f} "
                         f"[{c['source']}] {c['why'][:120]}")
    return "\n".join(lines)
