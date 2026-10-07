"""The root decision of MCTS v2 when model values enter the tree (node move47::mcts-calib).

A root move without a model value of its own must not win by default: the search compares it with
its siblings through a stand-in value (csrc/tree.c), and the decision only falls back on such a move
when no top candidate has a value.  Every decision records the rule that made it:

    most_visits               the plain rule: rule="visits", or a search without model values
    most_visits_evaluated     the most-visited root move has its own model value
    evaluated_among_top       the most-visited move has none: the most-visited move that has one
                              among the top candidates (the `top` most-visited moves with at least
                              `min_share` of the leader's visits) is played
    most_visits_unevaluated   no top candidate has a model value: most visits

With a service (mcts/llm.py), decide() first tries to get the missing value: while the most-visited
move has none and a request for it can still run, the request is raised to the top priority and the
search continues in chunks for at most `extend_s` seconds.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, fields
from typing import Callable, Optional

RULES = ("most_visits", "most_visits_evaluated", "evaluated_among_top", "most_visits_unevaluated")


@dataclass
class DecideConfig:
    rule: str = "evaluated"     # "evaluated" (the rules above) | "visits" (plain most visits)
    top: int = 4                # top candidates: the most-visited moves ...
    min_share: float = 0.2      # ... with at least this share of the leader's visits
    extend_s: float = 120.0     # extra search at most while the leader waits for its model value
    chunk_s: float = 5.0        # search chunk during the extension

    @classmethod
    def from_dict(cls, d: dict) -> "DecideConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


def _row(m: dict) -> dict:
    return {"move": m["coord"], "n": m["n"], "q": None if m["q"] is None else round(m["q"], 4),
            "v_ext": None if m.get("v_ext") is None else round(m["v_ext"], 4), "evaluated": bool(m.get("evaluated"))}


def choose(eng, cfg: Optional[DecideConfig] = None) -> dict:
    """The decision on the engine's current root statistics (no search, no service)."""
    cfg = cfg or DecideConfig()
    stats = eng.root_stats()
    lead_mv = eng.best_move()
    out: dict = {"rule": None, "move": None, "coord": None, "lead": None, "candidates": [],
                 "evaluated_moves": [m["coord"] for m in stats if m.get("evaluated")], "waiting": []}
    if lead_mv is None and not stats:
        out["rule"] = "most_visits"
        return out
    lead = next((m for m in stats if m["move"] == lead_mv), stats[0])
    others = [m for m in stats if m is not lead]
    cands = [lead] + [m for m in others[:max(0, cfg.top - 1)] if m["n"] >= cfg.min_share * lead["n"] and m["n"] > 0]
    out["lead"] = lead["coord"]
    out["candidates"] = [_row(m) for m in cands]
    chosen, rule = lead, "most_visits"
    if cfg.rule == "evaluated" and out["evaluated_moves"]:
        if lead.get("evaluated"):
            rule = "most_visits_evaluated"
        else:
            ev = [m for m in cands if m.get("evaluated")]
            if ev:
                chosen, rule = ev[0], "evaluated_among_top"
            else:
                rule = "most_visits_unevaluated"
    elif cfg.rule == "evaluated":
        rule = "most_visits_unevaluated" if stats and lead["n"] > 0 else "most_visits"
    out.update(rule=rule, move=chosen["move"], coord=chosen["coord"], chosen=_row(chosen))
    # unevaluated candidates the search ranks above the chosen move: their values would settle it
    out["waiting"] = [m["move"] for m in cands if not m.get("evaluated") and m["n"] > chosen["n"]] \
        if rule != "most_visits" else []
    if rule == "most_visits_unevaluated":
        out["waiting"] = [m["move"] for m in cands if not m.get("evaluated")]
    return out


def decide(eng, cfg: Optional[DecideConfig] = None, svc=None, search: Optional[Callable[[float], dict]] = None,
           log: Callable[[str], None] = lambda m: None) -> dict:
    """choose(), extended: while the decision is not "most_visits_evaluated", the service still has
    a request for one of the waiting moves (svc.boost(moves) > 0: queued and dispatchable, or
    running) and less than cfg.extend_s has been spent, search(chunk) once more."""
    cfg = cfg or DecideConfig()
    t0 = time.monotonic()
    d = choose(eng, cfg)
    outcome, boosted = None, set()
    while cfg.rule == "evaluated" and svc is not None and search is not None and d["rule"] in (
            "evaluated_among_top", "most_visits_unevaluated") and d["waiting"]:
        spent = time.monotonic() - t0
        if spent >= cfg.extend_s:
            outcome = "time"
            break
        pending = svc.boost(d["waiting"])
        boosted.update(eng.root_board.coord(m) for m in d["waiting"])
        if not pending:
            outcome = outcome or "no_request"
            break
        if outcome is None:
            log(f"decision: waiting up to {cfg.extend_s - spent:.0f}s for the model value of "
                f"{', '.join(eng.root_board.coord(m) for m in d['waiting'])} ({d['rule']} so far)")
        outcome = "searching"
        search(min(cfg.chunk_s, max(0.5, cfg.extend_s - spent)))
        d = choose(eng, cfg)
    if outcome == "searching":
        outcome = "resolved" if d["rule"] == "most_visits_evaluated" else "changed"
    d["extended_s"] = round(time.monotonic() - t0, 1) if outcome else 0.0
    d["extension"] = outcome
    d["boosted"] = sorted(boosted)
    return d
