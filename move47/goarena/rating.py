"""Ratings and run statistics.

The agent's rating is a maximum-a-posteriori Elo fitted against opponents of
*fixed* (calibrated) strength, over a sliding window of recent games — the
same idea as the chess experiment ("Elo from the last 50 games vs the rated
Stockfish levels"), but with an explicit uncertainty.
"""
from __future__ import annotations

import json
import math
from typing import Iterable, Optional

K = math.log(10) / 400.0


def expected(r: float, ro: float) -> float:
    return 1.0 / (1.0 + 10 ** ((ro - r) / 400.0))


def mle_rating(results: Iterable[tuple[float, float]], prior_mean: Optional[float] = None,
               prior_sd: float = 350.0) -> tuple[float, float]:
    """results: (opponent_elo, score in [0,1]).  Returns (rating, std. error)."""
    res = list(results)
    if not res:
        return (prior_mean or 0.0, float("inf"))
    mu = prior_mean if prior_mean is not None else sum(o for o, _ in res) / len(res)
    r = mu
    for _ in range(100):
        g = -(r - mu) / prior_sd ** 2
        h = -1.0 / prior_sd ** 2
        for ro, s in res:
            e = expected(r, ro)
            g += K * (s - e)
            h -= K * K * e * (1 - e)
        step = -g / h
        step = max(-200.0, min(200.0, step))
        r += step
        if abs(step) < 1e-4:
            break
    info = 1.0 / prior_sd ** 2 + sum(K * K * expected(r, ro) * (1 - expected(r, ro)) for ro, _ in res)
    return r, 1.0 / math.sqrt(info)


def fit_pool(pairs: list[tuple[str, str, float]], anchor: str, anchor_elo: float = 0.0,
             prior_sd: float = 600.0, iters: int = 300) -> dict[str, tuple[float, float]]:
    """Bradley-Terry fit of a pool from (a, b, score_of_a) games, used to
    calibrate opponent tiers.  Coordinate ascent; each player gets a weak
    prior centred on the mean of its opponents so a perfect score stays
    finite.  Returns name -> (elo, std. error); `anchor` is pinned."""
    names = sorted({a for a, _, _ in pairs} | {b for _, b, _ in pairs})
    r = {n: anchor_elo for n in names}
    se = {n: 0.0 for n in names}
    for _ in range(iters):
        delta = 0.0
        for n in names:
            if n == anchor:
                continue
            res = [(r[b], s) for a, b, s in pairs if a == n] + [(r[a], 1 - s) for a, b, s in pairs if b == n]
            new, e = mle_rating(res, prior_sd=prior_sd)
            delta = max(delta, abs(new - r[n]))
            r[n], se[n] = new, e
        if delta < 0.01:
            break
    return {n: (r[n], se[n]) for n in names}


# ---------------------------------------------------------------------------

def rated_games(games: list[dict], tier_elo: dict[str, float], rated_tiers: set[str]) -> list[tuple[int, float, float]]:
    out = []
    for g in games:
        if g.get("agent_score") is None or g["opponent"] not in rated_tiers:
            continue
        out.append((g["game_no"], tier_elo.get(g["opponent"], g.get("opponent_elo", 0.0)), float(g["agent_score"])))
    return out


def journey(games: list[dict], tier_elo: dict[str, float], rated_tiers: set[str],
            window: int = 50, min_games: int = 5) -> list[dict]:
    rg = rated_games(games, tier_elo, rated_tiers)
    pts = []
    for i in range(len(rg)):
        win = rg[max(0, i + 1 - window): i + 1]
        if len(win) < min_games:
            continue
        r, se = mle_rating([(o, s) for _, o, s in win])
        pts.append({"game_no": rg[i][0], "elo": round(r, 1), "se": round(se, 1), "n": len(win)})
    return pts


def phase_table(games: list[dict], tiers: Iterable[str], n_phases: int = 4) -> dict[str, list[Optional[float]]]:
    """Score rate per tier within each of n equal slices of the run."""
    if not games:
        return {t: [None] * n_phases for t in tiers}
    total = len(games)
    out = {}
    for t in tiers:
        row = []
        for k in range(n_phases):
            lo, hi = k * total // n_phases, (k + 1) * total // n_phases
            gs = [g for g in games[lo:hi] if g["opponent"] == t and g.get("agent_score") is not None]
            row.append(round(sum(g["agent_score"] for g in gs) / len(gs), 3) if gs else None)
        out[t] = row
    return out


def run_summary(run: dict, games: list[dict], tier_elo: dict[str, float], rated_tiers: set[str],
                tier_order: list[str], window: int = 50, illegal_total: int = 0) -> dict:
    finished = [g for g in games if g["status"] == "finished"]
    w = sum(1 for g in finished if g["agent_score"] == 1)
    l = sum(1 for g in finished if g["agent_score"] == 0)
    d = len(finished) - w - l
    per_tier = {}
    for t in tier_order:
        gs = [g for g in finished if g["opponent"] == t]
        if gs:
            per_tier[t] = {"games": len(gs), "wins": sum(1 for g in gs if g["agent_score"] == 1),
                           "score": round(sum(g["agent_score"] for g in gs) / len(gs), 3)}
    jr = journey(finished, tier_elo, rated_tiers, window)
    cur = jr[-1] if jr else None
    peak = max(jr, key=lambda p: p["elo"]) if jr else None
    # learning gain: current rating minus the rating over the first full window
    first_full = next((p for p in jr if p["n"] >= window), None)
    gain = round(cur["elo"] - first_full["elo"], 1) if (cur and first_full and cur is not first_full) else None
    losses, matches, n_rev = 0.0, 0.0, 0
    for g in finished:
        if g.get("review_summary"):
            s = json.loads(g["review_summary"])
            if s:
                losses += s["avg_loss"]
                matches += s["match_rate"]
                n_rev += 1
    times = [g for g in games]
    elapsed = 0.0
    for g in times:
        end = g.get("ended_at") or g.get("last_activity") or g["started_at"]
        elapsed += max(0.0, end - g["started_at"])
    return {
        "id": run["id"], "name": run["name"], "model": run["model"], "harness": run["harness"],
        "reasoning": run["reasoning"], "context": run["context"], "status": run["status"],
        "games_played": len(finished), "target_games": run["target_games"],
        "wins": w, "losses": l, "draws": d,
        "win_rate": round(w / len(finished), 3) if finished else None,
        "elo": cur["elo"] if cur else None, "elo_se": cur["se"] if cur else None,
        "peak_elo": peak["elo"] if peak else None,
        "elo_first_window": first_full["elo"] if first_full else None,
        "gain": gain,
        "per_tier": per_tier,
        "illegal": illegal_total,
        "avg_point_loss": round(losses / n_rev, 2) if n_rev else None,
        "engine_match_rate": round(matches / n_rev, 3) if n_rev else None,
        "reviewed_games": n_rev,
        "game_seconds": round(elapsed),
        "wall_seconds": round(((run.get("finished_at") or (max((g.get("ended_at") or g["last_activity"]) for g in games) if games else run["created_at"])) - run["created_at"])),
    }
