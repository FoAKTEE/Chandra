"""End-of-game scoring and post-game move-quality review."""
from __future__ import annotations

from typing import Optional

from .board import BLACK, WHITE, Board, coord_to_point, point_to_coord
from .katago import KataGo


def result_string(winner: int, margin: Optional[float] = None, reason: str = "score") -> str:
    w = "B" if winner == BLACK else "W"
    if reason in ("resign",):
        return f"{w}+R"
    if reason in ("forfeit", "timeout", "illegal_limit"):
        return f"{w}+F"
    if margin is None:
        return f"{w}+"
    return f"{w}+{abs(margin):g}"


def score_final(board: Board, katago: Optional[KataGo], visits: int = 200,
                dead_threshold: float = 0.5) -> dict:
    """Score a finished game under area rules.

    With KataGo, dead stones are those whose ownership strongly favours the
    other colour.  Without KataGo the position is scored Tromp-Taylor style
    (every stone on the board counts as alive)."""
    dead: list[int] = []
    method = "tromp-taylor"
    ownership = None
    if katago is not None:
        try:
            res = katago.analyze(board, visits, ownership=True)
            ownership = res.get("ownership")
        except Exception as e:  # engine trouble -> fall back, but record it
            method = f"tromp-taylor (referee error: {e})"
    if ownership:
        method = "area+katago-dead-stones"
        for p, c in enumerate(board.cells):
            o = ownership[p]  # +1 = black owns
            if c == BLACK and o < -dead_threshold:
                dead.append(p)
            elif c == WHITE and o > dead_threshold:
                dead.append(p)
    s = board.area_score(dead)
    s["method"] = method
    s["tromp_taylor_margin"] = board.area_score()["margin"]
    return s


def review_moves(moves: list[tuple[int, Optional[int]]], size: int, komi: float,
                 katago: KataGo, visits: int = 100) -> list[dict]:
    """Per-move quality from a strong KataGo search.

    For each ply i: loss = how many points (from the mover's perspective) the
    position got worse compared with the engine's evaluation before the move.
    Returns one dict per ply (1-based `ply`)."""
    b = Board(size, komi)
    for color, p in moves:
        b.play(p, color)
    n = len(moves)
    turns = list(range(n + 1))
    res = katago.analyze(b, visits, analyze_turns=turns, priority=-10)
    out = []
    for i, (color, p) in enumerate(moves):
        before, after = res.get(i), res.get(i + 1)
        if not before or not after:
            continue
        sign = 1 if color == BLACK else -1
        lb, la = before["rootInfo"]["scoreLead"], after["rootInfo"]["scoreLead"]
        wb, wa = before["rootInfo"]["winrate"], after["rootInfo"]["winrate"]
        infos = before.get("moveInfos", [])
        best = infos[0]["move"] if infos else "pass"
        top3 = [mi["move"] for mi in infos[:3]]
        played = point_to_coord(p, size)
        out.append({
            "ply": i + 1,
            "color": "B" if color == BLACK else "W",
            "move": played,
            "best": best,
            "top3": top3,
            "matched": played.upper() == best.upper(),
            "loss": round(max(0.0, sign * (lb - la)), 2),
            "raw_loss": round(sign * (lb - la), 2),
            "wr_loss": round(max(0.0, sign * (wb - wa)), 4),
            "lead_before": round(sign * lb, 2),
            "lead_after": round(sign * la, 2),
        })
    return out


def summarize_review(rows: list[dict], color: str, size: int) -> dict:
    """Aggregate the agent's moves into opening / middle / endgame buckets."""
    mine = [r for r in rows if r["color"] == color]
    if not mine:
        return {}
    n_total = max(r["ply"] for r in rows)
    o_end, m_end = max(1, int(size * size * 0.2)), max(2, int(size * size * 0.6))

    def bucket(r):
        return "opening" if r["ply"] <= o_end else "middle" if r["ply"] <= m_end else "endgame"

    out = {"moves": len(mine), "avg_loss": round(sum(r["loss"] for r in mine) / len(mine), 3),
           "blunders": sum(1 for r in mine if r["loss"] >= 5.0),
           "match_rate": round(sum(1 for r in mine if r["matched"]) / len(mine), 3),
           "phases": {}, "plies": n_total}
    for ph in ("opening", "middle", "endgame"):
        rs = [r for r in mine if bucket(r) == ph]
        if rs:
            out["phases"][ph] = {"moves": len(rs), "avg_loss": round(sum(r["loss"] for r in rs) / len(rs), 3)}
    return out


__all__ = ["score_final", "review_moves", "summarize_review", "result_string", "coord_to_point"]
