#!/usr/bin/env python3
"""Report of a code-only ablation run (scripts/ablation_play.py): per opponent, games, W-L, Elo with a
95% interval where the opponents are rated, the arena reviews' point loss per move, blunders, match
rate, seconds and simulations per move, the learner's weight versions game by game, plus the v1
pilot baseline and the ply-22 judge reproduction.

    python3 scripts/ablation_report.py <run dir> [--format json|md] [--path-root DIR] [--out-dir DIR]
        [--baseline <pilot report.json>] [--judge <judge summary.json>]

Sources: <run>/plan.json; per segment <run>/<stream>/<segment>/{arena.json, moves.jsonl}; the arenas
(viewer token from each arena dir in the plan) for games, results and reviews; <run>/hl/updates.jsonl.
Elo: goarena.rating.mle_rating (the arena's own fit: MAP with a prior centred on the mean opponent Elo,
sd 350) over all rated games pooled, per opponent, and the arena's own per-run value.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

M47 = Path(__file__).resolve().parent.parent
if str(M47) not in sys.path:
    sys.path.insert(0, str(M47))

from goarena.opponents import load_tiers  # noqa: E402
from goarena.rating import mle_rating  # noqa: E402

EVID = M47.parent / "results/move47/paper_move47/evidence"
REVIEWER = {"kata1": "kata1-tf3-b11c768, 1600 visits", "ladder": "g170e-b10c128, 1600 visits"}
TIERS = {"kata1": "config/tiers-9x9-kata1.json", "ladder": "config/tiers-9x9.json"}


def _get(url: str, token: str, path: str):
    req = urllib.request.Request(url.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _token(arena_dir: str) -> str:
    for n in ("viewer.token", "admin.token"):
        p = Path(arena_dir) / n
        if p.exists() and p.read_text().strip():
            return p.read_text().strip()
    return ""


def _jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text().splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def _mean(xs, nd=3):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), nd) if xs else None


def segment_data(seg_dir: Path, plan: dict) -> dict:
    meta = json.loads((seg_dir / "arena.json").read_text())
    arena = plan["arenas"][meta["arena"]]
    tok = _token(arena["dir"])
    run = _get(arena["url"], tok, f"/api/runs/{meta['run_id']}")
    games = []
    recs = _jsonl(seg_dir / "moves.jsonl")
    for g in run.get("games") or []:
        gv = _get(arena["url"], tok, f"/api/games/{g['id']}")
        gg = gv["game"]
        me = gg["agent_color"]
        mine = [r for r in recs if r["game"] == gg["game_no"]]
        rv = [r for r in (gv.get("review") or []) if r["color"] == me]
        versions = [r["weights"] for r in mine]
        games.append({
            "game_no": gg["game_no"], "opponent": gg["opponent"], "our_color": me, "status": gg["status"],
            "result": gg.get("result"), "winner": gg.get("winner"), "end_reason": gg.get("end_reason"),
            "plies": len(gv.get("moves") or []), "decisions": len(mine),
            "score": None if gg.get("winner") is None else (1.0 if gg["winner"] == "agent" else 0.0),
            "review": {"moves": len(rv), "avg_loss": _mean([r["loss"] for r in rv]),
                       "blunders": sum(1 for r in rv if r["loss"] >= 5.0),
                       "match_rate": _mean([1.0 if r["matched"] else 0.0 for r in rv]),
                       "losses": [round(r["loss"], 2) for r in rv]} if rv else None,
            "search_s": _mean([r["time_s"] for r in mine], 2), "wall_s": _mean([r.get("seconds") for r in mine], 2),
            "sims": _mean([r["sims"] for r in mine], 0), "sims_per_s": _mean([r["sims_per_s"] for r in mine], 0),
            "sims_list": [r["sims"] for r in mine], "search_s_list": [round(r["time_s"], 1) for r in mine],
            "root_n_start": _mean([r["root_n_start"] for r in mine[1:]], 0),
            "weights_first": versions[0] if versions else None, "weights_last": versions[-1] if versions else None,
            "weights_distinct": len(set(versions)), "sgf": gv.get("sgf"),
            "move_list": " ".join(f"{m['ply']}.{m['color']}{m['coord']}" for m in gv.get("moves") or [])})
    return {"segment": seg_dir.name, "stream": seg_dir.parent.name, "arena": meta["arena"], "run_id": meta["run_id"],
            "opponent": meta["opponent"], "target_games": meta["games"], "arena_summary": {
                k: run["summary"].get(k) for k in ("games_played", "target_games", "wins", "losses", "elo", "elo_se",
                                                   "avg_point_loss", "engine_match_rate", "status")},
            "games": games, "decisions": len(recs)}


def elo(games: list[dict], tier_elo: dict) -> Optional[dict]:
    """games: dicts with opponent and score; tier_elo: opponent -> Elo (or a list of (Elo, score) pairs)."""
    res = [(tier_elo[g["opponent"]], g["score"]) for g in games if g["score"] is not None and g["opponent"] in tier_elo]
    return fit(res)


def fit(res: list[tuple[float, float]]) -> Optional[dict]:
    if not res:
        return None
    r, se = mle_rating(res)
    return {"elo": round(r), "se": round(se), "ci95": [round(r - 1.96 * se), round(r + 1.96 * se)], "games": len(res),
            "score": round(sum(s for _, s in res) / len(res), 3)}


def build(run: Path, baseline: Optional[Path] = None, judge: Optional[Path] = None) -> dict:
    plan = json.loads((run / "plan.json").read_text())
    segs = []
    for sd in sorted(p for p in run.glob("*/*") if (p / "arena.json").exists()):
        segs.append(segment_data(sd, plan))
    ups = _jsonl(run / "hl" / "updates.jsonl")
    state = json.loads((run / "hl" / "state.json").read_text()) if (run / "hl" / "state.json").exists() else {}
    rated = {}
    for name, path in TIERS.items():
        for t, spec in load_tiers(M47 / path).items():
            if spec.counts_for_rating and spec.elo is not None:
                rated[(name, t)] = spec.elo
    by_opp: dict = {}
    for s in segs:
        by_opp.setdefault((s["arena"], s["opponent"]), []).append(s)
    rows = []
    for (arena, opp), ss in by_opp.items():
        gs = [g for s in ss for g in s["games"] if g["status"] == "finished"]
        rv = [g["review"] for g in gs if g["review"]]
        losses = [x for r in rv for x in r["losses"]]
        tier_elo = {opp: rated[(arena, opp)]} if (arena, opp) in rated else {}
        rows.append({
            "arena": arena, "opponent": opp, "opponent_elo": tier_elo.get(opp), "rated": bool(tier_elo),
            "games": len(gs), "wins": sum(1 for g in gs if g["score"] == 1.0),
            "losses": sum(1 for g in gs if g["score"] == 0.0),
            "colors": {"B": sum(1 for g in gs if g["our_color"] == "B"), "W": sum(1 for g in gs if g["our_color"] == "W")},
            "end_reasons": {r: sum(1 for g in gs if g["end_reason"] == r) for r in sorted({g["end_reason"] for g in gs})},
            "elo": elo(gs, tier_elo) if tier_elo else None,
            "arena_run_elo": [{"run": s["run_id"], "elo": s["arena_summary"]["elo"], "se": s["arena_summary"]["elo_se"]}
                              for s in ss] if tier_elo else None,
            "reviewer": REVIEWER.get(arena), "reviewed_moves": len(losses),
            "point_loss_per_move": round(st.mean(losses), 3) if losses else None,
            "point_loss_game_mean": _mean([r["avg_loss"] for r in rv]),
            "point_loss_median": round(st.median(losses), 3) if losses else None,
            "blunders": sum(r["blunders"] for r in rv),
            "match_rate": round(sum(r["match_rate"] * r["moves"] for r in rv) / sum(r["moves"] for r in rv), 3) if rv else None,
            "decisions": sum(g["decisions"] for g in gs),
            "search_s_per_move": _mean([g["search_s"] for g in gs for _ in range(g["decisions"])], 2),
            "wall_s_per_move": _mean([g["wall_s"] for g in gs for _ in range(g["decisions"])], 2),
            "sims_per_move_median": round(st.median([x for g in gs for x in g["sims_list"]])) if gs else None,
            "search_s_max": max((x for g in gs for x in g["search_s_list"]), default=None),
            "search_s_over_31": sum(1 for g in gs for x in g["search_s_list"] if x > 31),
            "usd_per_move": 0.0,
            "weights": [f"{s['stream']}g{g['game_no']}:{g['weights_first']}->{g['weights_last']}"
                        for s in ss for g in s["games"] if g["status"] == "finished"]})
    pooled = fit([(rated[(s["arena"], g["opponent"])], g["score"]) for s in segs for g in s["games"]
                  if g["status"] == "finished" and g["score"] is not None and (s["arena"], g["opponent"]) in rated])
    acc = [u for u in ups if u.get("accepted")]
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "run_dir": str(run),
           "condition": {"engine": "MCTS v2 code only (--llm off), online learning (--learn), one learner shared by "
                                   "all games", "time_per_move_s": plan["time_per_move"], "threads": plan["threads"],
                         "streams": {k: [f"{x['opponent']} x{x['games']}" + (f" ({x['color']})" if x.get("color") else "")
                                         for x in v] for k, v in plan["streams"].items()},
                         "decision": "most visits", "root_noise": 0.25, "model_sessions": 0},
           "rows": rows, "elo_pooled_rated": pooled,
           "learning": {"updates": len(ups), "accepted": len(acc), "current": state.get("current_version"),
                        "versions": [{"update": u["update"], "version": u["version"], "game": u.get("game"),
                                      "samples": u.get("samples"), "t": round(u["t"])} for u in acc],
                        "update_s_mean": _mean([u.get("time_s") for u in ups], 2),
                        "last_policy": acc[-1].get("policy") if acc else None},
           "segments": segs}
    if baseline and baseline.exists():
        b = json.loads(baseline.read_text())
        g = b["games"][0]
        out["v1_pilot"] = {"opponent": g["opponent"], "our_color": g["our_color"], "result": g["result"],
                           "end_reason": g["end_reason"], "review": g["review"]["summary"],
                           "per_move": b["totals"]["per_finished_move"],
                           "median_loss": round(st.median([x["loss"] for x in g["review"]["our_loss"]]), 3)}
    if judge and judge.exists():
        j = json.loads(judge.read_text())
        out["judge_ply22"] = {"summary": j["summary"], "earlier_adhoc": j["earlier_adhoc"]}
    return out


def relabel(x, root: str):
    if not root:
        return x
    pres = sorted({str(Path(root)).rstrip("/") + "/", str(Path(root).resolve()).rstrip("/") + "/"}, key=len, reverse=True)
    if isinstance(x, dict):
        return {k: relabel(v, root) for k, v in x.items()}
    if isinstance(x, list):
        return [relabel(v, root) for v in x]
    if isinstance(x, str):
        for p in pres:
            x = x.replace(p, "")
    return x


def _f(x, nd=2):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def markdown(rep: dict) -> str:
    c = rep["condition"]
    L = [f"# Code-only MCTS v2 ablation ({rep['generated_at'][:10]})", "",
         f"- condition: {c['engine']}; {c['time_per_move_s']} s/move, {c['threads']} search threads per game; "
         f"decision {c['decision']}; root noise {c['root_noise']}; model sessions {c['model_sessions']} (0 USD)",
         "- streams (parallel, one shared learner): " + "; ".join(f"{k}: {', '.join(v)}" for k, v in c["streams"].items()),
         f"- run dir: `{rep['run_dir']}`", ""]
    L += ["| opponent (Elo) | games | W-L | B/W | Elo, 95% CI | point loss / move (reviewer) | blunders | match | "
          "search s / wall s per move | median sims / move | USD / move | end reasons |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        e = r["elo"]
        L.append(f"| {r['opponent']} ({r['opponent_elo'] or 'unrated'}) | {r['games']} | {r['wins']}-{r['losses']} | "
                 f"{r['colors']['B']}/{r['colors']['W']} | "
                 + (f"{e['elo']} [{e['ci95'][0]}, {e['ci95'][1]}] (se {e['se']})" if e else "-")
                 + f" | {_f(r['point_loss_per_move'], 3)} (median {_f(r['point_loss_median'], 2)}) over {r['reviewed_moves']} "
                 f"({r['reviewer']}) | {r['blunders']} | "
                 f"{_f(r['match_rate'], 3)} | {_f(r['search_s_per_move'])} / {_f(r['wall_s_per_move'])} | "
                 f"{_f(r['sims_per_move_median'], 0)} | 0 | {', '.join(f'{k} {v}' for k, v in r['end_reasons'].items())} |")
    if rep.get("v1_pilot"):
        v = rep["v1_pilot"]
        med = v.get("median_loss")
        L.append(f"| v1 pilot: {v['opponent']} | 1 | 0-1 | {'1/0' if v['our_color'] == 'B' else '0/1'} | - | "
                 f"{_f(v['review']['avg_loss'], 3)} (median {_f(med, 2)}) over {v['review']['moves']} "
                 f"(kata1-tf3-b11c768, 1600 visits) | "
                 f"{v['review']['blunders']} | {_f(v['review']['match_rate'], 3)} | - / {_f(v['per_move']['seconds'], 1)} | "
                 f"{v['per_move']['jobs']} model sessions | {_f(v['per_move']['cost_usd'])} | {v['end_reason']} 1 |")
    p = rep.get("elo_pooled_rated")
    if p:
        L += ["", f"Pooled Elo over all {p['games']} rated games (score {p['score']}): **{p['elo']}**, 95% CI "
                  f"[{p['ci95'][0]}, {p['ci95'][1]}] (se {p['se']}), on the calibrated b10c128 scale (random = 0; "
                  f"lv7 1850, lv8 2064)."]
    for r in rep["rows"]:
        if r.get("arena_run_elo"):
            L.append(f"- vs {r['opponent']} alone: the arena's own per-run rating " + ", ".join(
                f"{x['elo']} (se {x['se']})" for x in r["arena_run_elo"]) + " (same fit as the table; with "
                f"{r['wins']} wins in {r['games']} games it is dominated by the fit's prior, centred on that tier's Elo "
                f"with sd 350: read the pooled value)")
    L.append("- per-move search time above 31 s (tree eviction pauses at the 20M-node cap count in the move's "
             "search time): " + ", ".join(f"{r['opponent']} {r['search_s_over_31']} of {r['decisions']} (max "
                                           f"{r['search_s_max']} s)" for r in rep["rows"]))
    L.append("- point loss / move: mean over all our reviewed moves of the opponent's games; the ladder arena's "
             "reviewer is its own b10c128 net, so only the k1-full rows compare with the v1 pilot")
    lr = rep["learning"]
    L += ["", "## Learning", "",
          f"- one OnlineLearner for all games: {lr['updates']} updates, {lr['accepted']} accepted, now {lr['current']}; "
          f"mean update {lr['update_s_mean']} s",
          "- weights version used per game (first -> last decision): " + "; ".join(
              f"{r['opponent']}: {', '.join(r['weights'])}" for r in rep["rows"])]
    if lr["versions"]:
        L.append("- accepted versions: " + ", ".join(f"{v['version']} (update {v['update']})" for v in lr["versions"][:: max(1, len(lr["versions"]) // 12)]))
    L += ["", "## Games", "", "| stream | opponent | game | we | result | reason | plies | loss/move | blunders | weights |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for s in rep["segments"]:
        for g in s["games"]:
            rv = g["review"] or {}
            L.append(f"| {s['stream']} | {g['opponent']} | {g['game_no']} | {g['our_color']} | {g['result']} | "
                     f"{g['end_reason']} | {g['plies']} | {_f(rv.get('avg_loss'), 3)} | {rv.get('blunders', '-')} | "
                     f"{g['weights_first']} -> {g['weights_last']} |")
    if rep.get("judge_ply22"):
        j = rep["judge_ply22"]["summary"]["20000"]
        L += ["", "## Ply-22 judge reproduction (evidence judge-ply22)", "",
              f"- 20000 visits, 3 runs: H7 loss {j['H7']['losses']} (ranks {j['H7']['ranks']}), E6 loss {j['E6']['losses']} "
              f"(ranks {j['E6']['ranks']}), best {j['best']}; earlier ad-hoc run: H7 rank 4 loss 1.69, E6 rank 13 loss 2.91, best C2"]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run")
    ap.add_argument("--format", default="md", choices=["md", "json"])
    ap.add_argument("--path-root", default="")
    ap.add_argument("--out-dir", default="", help="write summary.json and report.md here")
    ap.add_argument("--baseline", default=str(EVID / "pilot-20261005/report.json"))
    ap.add_argument("--judge", default=str(EVID / "judge-ply22/summary.json"))
    ap.add_argument("--no-segments", action="store_true", help="leave the per-game detail (SGFs) out of the JSON")
    a = ap.parse_args(argv)
    rep = relabel(build(Path(a.run).resolve(), Path(a.baseline), Path(a.judge)), a.path_root)
    if a.no_segments:
        for s in rep["segments"]:
            for g in s["games"]:
                g.pop("sgf", None)
    md = markdown(rep)
    if a.out_dir:
        d = Path(a.out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "summary.json").write_text(json.dumps(rep, indent=1) + "\n")
        (d / "report.md").write_text(md)
    print(md if a.format == "md" else json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
