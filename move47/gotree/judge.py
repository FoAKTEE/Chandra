"""Offline judge: KataGo grades decisions AFTER the fact.

Firewall: the judge reads the search DAG (read-only) and writes its own
file; nothing it computes is ever shown to workers or fed back into the
search.  Use it to measure, never to steer.
"""
from __future__ import annotations

import json
from typing import Optional

from .position import BLACK, Position, coord, point, sym_maps


def _stones(pos: Position) -> list[list[str]]:
    return [["B" if c == BLACK else "W", coord(p, pos.size)] for p, c in enumerate(pos.cells) if c != "."]


def _ko_setup(pos: Position):
    """If pos has a ko point, rebuild it as (position before the ko capture, capturing move) so that
    KataGo knows the immediate recapture is illegal."""
    from .position import neighbors, other
    if pos.ko is None:
        return None
    mover = other(pos.to_play)
    for n in neighbors(pos.size)[pos.ko]:
        if pos.cells[n] == mover:
            st, libs = pos.chain(n)
            if len(st) == 1 and libs == {pos.ko}:
                cells = list(pos.cells)
                cells[n] = "."
                cells[pos.ko] = pos.to_play
                before = Position(pos.size, "".join(cells), mover, None, 0, pos.komi)
                return before, n
    return None


def analyze_position(kg, pos: Position, visits: int = 400) -> dict:
    """KataGo analysis of a frozen position; values from the side to move."""
    ko = _ko_setup(pos)
    if ko is not None:
        before, mv = ko
        stones, first = _stones(before), "B" if before.to_play == BLACK else "W"
        moves = [[first, coord(mv, pos.size)]]
    else:
        stones, first, moves = _stones(pos), "B" if pos.to_play == BLACK else "W", []
    payload = {"initialStones": stones, "initialPlayer": first, "moves": moves,
               "rules": "chinese", "komi": pos.komi, "boardXSize": pos.size, "boardYSize": pos.size,
               "maxVisits": visits, "includePolicy": True}
    res = next(iter(kg.query(payload).values()))
    sign = 1 if pos.to_play == BLACK else -1   # the client reports values from Black's view
    root = res["rootInfo"]
    moves = []
    for mi in res.get("moveInfos", []):
        moves.append({"move": mi["move"], "visits": mi["visits"],
                      "winrate": mi["winrate"] if sign > 0 else 1 - mi["winrate"],
                      "lead": sign * mi["scoreLead"], "prior": mi.get("prior")})
    return {"winrate": root["winrate"] if sign > 0 else 1 - root["winrate"], "lead": sign * root["scoreLead"],
            "moves": moves, "policy": res.get("policy")}


def move_quality(kg, pos: Position, p: Optional[int], best_lead: float, visits: int = 200) -> dict:
    """Points lost by playing p (side to move's view), via analysing the child position."""
    child = pos.play(p)
    a = analyze_position(kg, child, visits)
    lead_after = -a["lead"]
    return {"lead_after": round(lead_after, 2), "loss": round(best_lead - lead_after, 2),
            "winrate_after": round(1 - a["winrate"], 4)}


def judge_root(kg, pos_real: Position, moves_real: dict[str, Optional[int]], visits: int = 800) -> dict:
    """moves_real: label -> point (real frame) to grade, e.g. {"decision": .., "target": ..}."""
    a = analyze_position(kg, pos_real, visits)
    best = a["moves"][0] if a["moves"] else None
    best_lead = best["lead"] if best else a["lead"]
    pol = a.get("policy") or []
    n = pos_real.size * pos_real.size
    order = sorted(range(n), key=lambda i: -(pol[i] if pol and pol[i] is not None else -1)) if pol else []
    out = {"engine_best": best["move"] if best else None, "engine_lead": round(best_lead, 2),
           "engine_top": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()} for m in a["moves"][:8]],
           "graded": {}}
    for label, p in moves_real.items():
        if label is None:
            continue
        c = coord(p, pos_real.size)
        rank = next((i + 1 for i, m in enumerate(a["moves"]) if m["move"].upper() == c.upper()), None)
        q = move_quality(kg, pos_real, p, best_lead, max(100, visits // 4))
        prior = pol[p] if (pol and p is not None and p < len(pol)) else None
        prior_rank = (order.index(p) + 1) if (order and p is not None) else None
        out["graded"][label] = {"move": c, "engine_rank": rank, "engine_policy": prior, "engine_policy_rank": prior_rank,
                                **q}
    return out


def judge_dag(dag_path: str, kg, visits: int = 800, labels: Optional[set] = None) -> list[dict]:
    from .dag import DAG
    dag = DAG(dag_path, readonly=True)
    out = []
    for r in dag.q("SELECT * FROM roots WHERE finished IS NOT NULL ORDER BY id"):
        if labels and r["label"] not in labels:
            continue
        can = dag.position(r["key"])
        s = r["real_sym"]
        inv = sym_maps(can.size)[1][s]
        # rebuild the real-orientation position
        cells = ["."] * (can.size * can.size)
        for q, c in enumerate(can.cells):
            cells[inv[q]] = c
        real = Position(can.size, "".join(cells), can.to_play, None if can.ko is None else inv[can.ko],
                        can.passes, can.komi)
        summ = json.loads(r["summary"] or "{}")
        moves = {"decision": None if r["decision"] is None or r["decision"] < 0 else inv[r["decision"]]}
        for c in summ.get("candidates", [])[:5]:
            moves[f"search#{c['rank']}"] = point(c["real"], can.size)
        tgt = summ.get("target_real")
        if tgt:
            moves["target"] = point(tgt, can.size)
        out.append({"root_id": r["id"], "label": r["label"], "decision": r["decision_real"],
                    **judge_root(kg, real, moves, visits)})
    return out


def judge_values(dag_path: str, kg, n: int = 100, visits: int = 400, min_visits: int = 0) -> dict:
    """How good is the LLM as a value function?  Compares the static winrates
    the workers gave (evals.kind='static') with KataGo's winrate for the same
    positions.  This is the number that decides whether search can work."""
    import random as _r
    from .dag import DAG
    dag = DAG(dag_path, readonly=True)
    rows = dag.q("SELECT e.key, e.value, n.n FROM evals e JOIN nodes n ON n.key=e.key "
                 "WHERE e.kind='static' AND e.value IS NOT NULL AND n.n >= ?", (min_visits,))
    _r.Random(0).shuffle(rows)
    pairs = []
    for r in rows[:n]:
        pos = dag.position(r["key"])
        if pos.terminal:
            continue
        a = analyze_position(kg, pos, visits)
        node = dag.node(r["key"])
        pairs.append({"llm": r["value"], "engine": a["winrate"],
                      "search": (node["w"] / node["n"]) if node["n"] else None})
    if not pairs:
        return {"positions": 0}

    def stats(key: str) -> dict:
        ps = [p for p in pairs if p[key] is not None]
        if not ps:
            return {}
        mae = sum(abs(p[key] - p["engine"]) for p in ps) / len(ps)
        brier = sum((p[key] - (1.0 if p["engine"] > 0.5 else 0.0)) ** 2 for p in ps) / len(ps)
        agree = sum(1 for p in ps if (p[key] > 0.5) == (p["engine"] > 0.5)) / len(ps)
        return {"n": len(ps), "mae": round(mae, 3), "brier_vs_engine_side": round(brier, 3),
                "same_side_as_engine": round(agree, 3)}
    return {"positions": len(pairs), "llm_static": stats("llm"), "after_search": stats("search")}
