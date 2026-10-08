#!/usr/bin/env python3
"""Report of a full-system run (scripts/strength_play.py): per opponent, games, W-L, Elo with a 95% interval
where the opponents are rated, the arena reviews' point loss per move (and which net reviewed it), blunders,
match rate, seconds, model sessions and USD per move, the decision rules, decisions without model input and
waits for the model; per game the cost and the heuristics book's growth (rules and nudges proposed,
accepted, rejected; weights versions); a comparison with the code-only ablation and the v1 pilot.

    python3 scripts/strength_report.py <run dir> [--format json|md] [--path-root DIR] [--out-dir DIR]
        [--start-state <run>/start-state.json] [--ablation <ablation summary.json>] [--baseline <pilot report.json>]

Sources: <run>/plan.json; per segment <run>/<S>/<NN>-<arena>-<opp>/{arena.json, moves.jsonl}; per stream
<run>/<S>/llm-jobs.jsonl (sessions, attributed to a decision by the root label <S><NN>g<game>p<ply> they were
requested under); the arenas (viewer token from each arena dir in the plan) for games, results and reviews;
<run>/hl/{updates.jsonl, proposals.jsonl, heuristics-book.json, state.json}; start-state.json (the learning
state the run started from, written when it was copied in).  Elo: goarena.rating.mle_rating as in
scripts/ablation_report.py (the arena's own fit), pooled over all rated games and per opponent.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

M47 = Path(__file__).resolve().parent.parent
for p in (str(M47), str(M47 / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from ablation_report import (EVID, REVIEWER, TIERS, _f, _jsonl, _mean, fit, relabel,  # noqa: E402
                             segment_data)
from goarena.opponents import load_tiers  # noqa: E402

LABEL = re.compile(r"^([A-Z])(\d+)g(\d+)p(\d+)$")


def _game_key(label: str) -> Optional[tuple]:
    m = LABEL.match(label or "")
    return None if not m else (m.group(1), int(m.group(2)), int(m.group(3)))


def _sessions(run: Path) -> dict:
    """label -> {"sessions", "cost", "kinds", "failed", "rate_limited"} over every stream's llm-jobs.jsonl."""
    out: dict = defaultdict(lambda: {"sessions": 0, "cost": 0.0, "kinds": Counter(), "failed": 0, "rate_limited": 0})
    for f in sorted(run.glob("*/llm-jobs.jsonl")):
        for j in _jsonl(f):
            d = out[j.get("root") or ""]
            d["sessions"] += 1
            d["cost"] += float(((j.get("usage") or {}).get("cost_usd")) or 0.0)
            d["kinds"][j.get("kind")] += 1
            d["failed"] += 0 if j.get("ok") else 1
            d["rate_limited"] += 1 if j.get("fail_class") == "rate_limit" else 0
    return out


def _proposals(hl: Path) -> dict:
    """game key -> rules / nudges proposed, accepted, rejected (heuristic jobs of this run only)."""
    out: dict = defaultdict(lambda: {"jobs": 0, "rules_proposed": 0, "rules_accepted": 0, "rules_rejected": 0,
                                     "nudges_proposed": 0, "nudges_accepted": 0, "nudges_rejected": 0,
                                     "accepted_rules": [], "book_versions": []})
    for p in _jsonl(hl / "proposals.jsonl"):
        k = _game_key(p.get("label", ""))
        if k is None:
            continue
        d = out[k]
        d["jobs"] += 1
        for kind in ("rules", "nudges"):
            for x in p.get(kind) or []:
                d[f"{kind}_proposed"] += 1
                s = x.get("status")
                if s == "accepted":
                    d[f"{kind}_accepted"] += 1
                    if kind == "rules":
                        d["accepted_rules"].append(x.get("id"))
                elif s:
                    d[f"{kind}_rejected"] += 1
        if p.get("book_version") is not None:
            d["book_versions"].append(p["book_version"])
    return out


def _book(hl: Path, start: dict) -> dict:
    """The book now against the start state: rules added during the run, with the model's text and the weights."""
    try:
        b = json.loads((hl / "heuristics-book.json").read_text())
    except (OSError, ValueError):
        return {}
    rules = b.get("rules") or []
    if isinstance(rules, dict):
        rules = list(rules.values())
    start_ids = set(start.get("rule_ids") or [])
    active = [r for r in rules if r.get("status", "active") == "active"]
    new = [r for r in active if r.get("id") not in start_ids]

    def brief(r):
        hist = r.get("weight_history") or []
        eff = r.get("heldout_effect") or {}
        prov = r.get("provenance") or {}
        return {"id": r.get("id"), "name": r.get("name"), "text": (r.get("text") or "")[:300],
                "weight_proposed": eff.get("w_proposed", hist[0]["w"] if hist else None),
                "weight_now": hist[-1]["w"] if hist else None, "label": prov.get("label"),
                "accepted_in": r.get("accepted_in"), "gain": eff.get("gain"), "ci90": eff.get("ci90"),
                "gain_as_proposed": eff.get("gain_as_proposed")}
    w0 = start.get("rule_weights") or {}
    kept = [{"id": r.get("id"), "name": r.get("name"), "weight_start": w0.get(r.get("id")),
             "weight_now": (r.get("weight_history") or [{}])[-1].get("w")} for r in active if r.get("id") in start_ids]
    return {"book_version": b.get("version"), "active_rules": len(active), "start_rules": len(start_ids),
            "new_rules": [brief(r) for r in new], "start_rules_now": kept}


def build(run: Path, start_state: Optional[Path] = None, ablation: Optional[Path] = None,
          baseline: Optional[Path] = None) -> dict:
    plan = json.loads((run / "plan.json").read_text())
    start = {}
    sp = start_state if start_state is not None else run / "start-state.json"
    if sp and Path(sp).exists():
        start = json.loads(Path(sp).read_text())
    sess = _sessions(run)
    props = _proposals(run / "hl")
    segs = []
    for sd in sorted(p for p in run.glob("*/*") if (p / "arena.json").exists()):
        s = segment_data(sd, plan)
        s["idx"] = int(sd.name.split("-")[0])
        s["records"] = _jsonl(sd / "moves.jsonl")
        seen = {g["game_no"] for g in s["games"]}
        for gno in sorted({r["game"] for r in s["records"]} - seen):    # not finished (the arena lists finished games)
            rr = [r for r in s["records"] if r["game"] == gno]
            s["games"].append({"game_no": gno, "opponent": s["opponent"], "our_color": rr[0].get("color"),
                               "status": "unfinished", "result": None, "winner": None, "end_reason": None,
                               "plies": 2 * len(rr) - (1 if rr[0].get("color") == "B" else 0), "decisions": len(rr),
                               "score": None, "review": None, "sgf": None, "move_list": None})
        segs.append(s)
    rated = {}
    for name, path in TIERS.items():
        for t, spec in load_tiers(M47 / path).items():
            if spec.counts_for_rating and spec.elo is not None:
                rated[(name, t)] = spec.elo
    games, moves_out = [], []
    for s in segs:
        for g in s["games"]:
            key = (s["stream"], s["idx"], g["game_no"])
            recs = [r for r in s["records"] if r["game"] == g["game_no"]]
            labels = [r.get("label") or f"{s['stream']}{s['idx']}g{g['game_no']}p{r['ply']}" for r in recs]
            gl = [k for k in sess if _game_key(k) == key]
            cost = sum(sess[k]["cost"] for k in gl)
            nsess = sum(sess[k]["sessions"] for k in gl)
            pr = props[key] if key in props else {"jobs": 0, "rules_proposed": 0, "rules_accepted": 0,
                                                  "rules_rejected": 0, "nudges_proposed": 0, "nudges_accepted": 0,
                                                  "nudges_rejected": 0, "accepted_rules": [], "book_versions": []}
            rules = Counter((r.get("decision") or {}).get("rule") for r in recs)
            rv = g["review"] or {}
            losses = rv.get("losses") or []
            for i, (r, lab) in enumerate(zip(recs, labels)):
                d = sess.get(lab) or {"sessions": 0, "cost": 0.0, "kinds": Counter()}
                moves_out.append({"label": lab, "opponent": g["opponent"], "color": r.get("color"), "ply": r["ply"],
                                  "move": r["move"], "rule": (r.get("decision") or {}).get("rule"),
                                  "extension": (r.get("decision") or {}).get("extension"),
                                  "search_s": r.get("time_s"), "wall_s": r.get("seconds"), "sims": r.get("sims"),
                                  "root_n_start": r.get("root_n_start"), "q": None if r.get("q") is None else round(r["q"], 3),
                                  "weights": r.get("weights"), "sessions": d["sessions"], "usd": round(d["cost"], 3),
                                  "kinds": dict(d["kinds"]), "model_input": r.get("model_input"),
                                  "waited_s": r.get("waited_for_model_s"),
                                  "loss": losses[i] if i < len(losses) else None})
            games.append({
                "stream": s["stream"], "segment": s["segment"], "arena": s["arena"], "run_id": s["run_id"],
                "game_no": g["game_no"], "opponent": g["opponent"], "our_color": g["our_color"], "status": g["status"],
                "result": g["result"], "winner": g["winner"], "end_reason": g["end_reason"], "plies": g["plies"],
                "decisions": len(recs), "score": g["score"], "review": g["review"], "rated": (s["arena"], g["opponent"]) in rated,
                "cost_usd": round(cost, 2), "sessions": nsess,
                "usd_per_move": round(cost / len(recs), 3) if recs else None,
                "sessions_per_move": round(nsess / len(recs), 2) if recs else None,
                "search_s": _mean([r.get("time_s") for r in recs], 1), "wall_s": _mean([r.get("seconds") for r in recs], 1),
                "sims_median": round(st.median([r["sims"] for r in recs])) if recs else None,
                "decision_rules": dict(rules), "no_model_input": sum(1 for r in recs if r.get("model_input") is False),
                "waited_for_model_s": round(sum(r.get("waited_for_model_s") or 0 for r in recs), 1),
                "weights_first": recs[0]["weights"] if recs else None, "weights_last": recs[-1]["weights"] if recs else None,
                "book": {k: pr[k] for k in ("jobs", "rules_proposed", "rules_accepted", "rules_rejected", "nudges_proposed",
                                            "nudges_accepted", "nudges_rejected", "accepted_rules")}
                | {"book_version_last": max(pr["book_versions"]) if pr["book_versions"] else None},
                "sgf": g.get("sgf"), "move_list": g.get("move_list")})
    by_opp: dict = defaultdict(list)
    for g in games:
        by_opp[(g["arena"], g["opponent"])].append(g)
    rows = []
    for (arena, opp), gs in by_opp.items():
        fin = [g for g in gs if g["status"] == "finished"]
        rvs = [g["review"] for g in fin if g["review"]]
        losses = [x for r in rvs for x in r["losses"]]
        dec = sum(g["decisions"] for g in gs)
        cost = sum(g["cost_usd"] for g in gs)
        ns = sum(g["sessions"] for g in gs)
        mv = [m for m in moves_out if _game_key(m["label"]) in {(g["stream"], int(g["segment"].split("-")[0]), g["game_no"]) for g in gs}]
        tier_elo = {opp: rated[(arena, opp)]} if (arena, opp) in rated else {}
        rows.append({
            "arena": arena, "opponent": opp, "opponent_elo": tier_elo.get(opp), "rated": bool(tier_elo),
            "games": len(fin), "unfinished": len(gs) - len(fin),
            "wins": sum(1 for g in fin if g["score"] == 1.0), "losses": sum(1 for g in fin if g["score"] == 0.0),
            "colors": {"B": sum(1 for g in fin if g["our_color"] == "B"), "W": sum(1 for g in fin if g["our_color"] == "W")},
            "end_reasons": dict(Counter(g["end_reason"] for g in fin)),
            "elo": fit([(tier_elo[opp], g["score"]) for g in fin if g["score"] is not None]) if tier_elo else None,
            "reviewer": REVIEWER.get(arena), "reviewed_moves": len(losses),
            "point_loss_per_move": round(st.mean(losses), 3) if losses else None,
            "point_loss_median": round(st.median(losses), 3) if losses else None,
            "blunders": sum(r["blunders"] for r in rvs),
            "match_rate": round(sum(r["match_rate"] * r["moves"] for r in rvs) / sum(r["moves"] for r in rvs), 3) if rvs else None,
            "decisions": dec, "search_s_per_move": _mean([m["search_s"] for m in mv], 1),
            "wall_s_per_move": _mean([m["wall_s"] for m in mv], 1),
            "sims_per_move_median": round(st.median([m["sims"] for m in mv])) if mv else None,
            "usd": round(cost, 2), "usd_per_move": round(cost / dec, 3) if dec else None,
            "sessions": ns, "sessions_per_move": round(ns / dec, 2) if dec else None,
            "decision_rules": dict(Counter(m["rule"] for m in mv)),
            "no_model_input": sum(1 for m in mv if m["model_input"] is False),
            "waited_for_model_s": round(sum(m["waited_s"] or 0 for m in mv), 1)})
    pooled = fit([(rated[(g["arena"], g["opponent"])], g["score"]) for g in games
                  if g["status"] == "finished" and g["score"] is not None and g["rated"]])
    ups = _jsonl(run / "hl" / "updates.jsonl")
    st_ = json.loads((run / "hl" / "state.json").read_text()) if (run / "hl" / "state.json").exists() else {}
    first_update = int(start.get("updates", 0))
    ups_run = [u for u in ups if int(u.get("update", 0)) > first_update]
    acc = [u for u in ups_run if u.get("accepted")]
    unattributed = {k: v for k, v in sess.items() if _game_key(k) is None}
    tot_cost = sum(v["cost"] for v in sess.values())
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "run_dir": str(run),
           "condition": {"engine": "MCTS v2 + model service (sandboxed Opus 5.5 xhigh workers) + online heuristic "
                                   "learning (--learn --heuristics), one learning state, DAG and lesson memory shared by "
                                   "all games", "time_per_move_s": plan["time_per_move"], "threads": plan["threads"],
                         "llm_workers_per_stream": plan["llm_workers"],
                         "streams": {k: [f"{x['opponent']} x{x['games']}" + (f" ({x['color']})" if x.get("color") else "")
                                         for x in v] for k, v in plan["streams"].items()},
                         "play_args": [a for a in plan.get("play_args", []) if "/" not in a],
                         "decision": "mcts/decide.py (evaluated)", "start_state": {k: start.get(k) for k in (
                             "copied_from", "version", "rules", "book_version", "updates", "proposals")}},
           "rows": rows, "elo_pooled_rated": pooled, "games": games, "moves": moves_out,
           "totals": {"games_finished": sum(1 for g in games if g["status"] == "finished"),
                      "games_unfinished": sum(1 for g in games if g["status"] != "finished"),
                      "decisions": len(moves_out), "cost_usd": round(tot_cost, 2),
                      "cost_unattributed_usd": round(sum(v["cost"] for v in unattributed.values()), 2),
                      "sessions": sum(v["sessions"] for v in sess.values()),
                      "sessions_by_kind": dict(sum((v["kinds"] for v in sess.values()), Counter())),
                      "failed_sessions": sum(v["failed"] for v in sess.values()),
                      "rate_limited_sessions": sum(v["rate_limited"] for v in sess.values()),
                      "usd_per_move": round(tot_cost / len(moves_out), 3) if moves_out else None,
                      "model_input_decisions": sum(1 for m in moves_out if m["model_input"]),
                      "no_model_input_decisions": sum(1 for m in moves_out if m["model_input"] is False),
                      "waited_for_model_s": round(sum(m["waited_s"] or 0 for m in moves_out), 1),
                      "search_s_per_move": _mean([m["search_s"] for m in moves_out], 1),
                      "wall_s_per_move": _mean([m["wall_s"] for m in moves_out], 1)},
           "learning": {"updates": len(ups_run), "accepted": len(acc), "version_start": start.get("version"),
                        "version_now": st_.get("current_version"),
                        "update_s_mean": _mean([u.get("time_s") for u in ups_run], 2),
                        "book": _book(run / "hl", start)}}
    if ablation and Path(ablation).exists():
        ab = json.loads(Path(ablation).read_text())
        out["ablation"] = {"elo_pooled_rated": ab.get("elo_pooled_rated"), "time_per_move_s": ab["condition"]["time_per_move_s"],
                           "rows": [{k: r.get(k) for k in ("opponent", "opponent_elo", "games", "wins", "losses", "elo",
                                                           "reviewer", "reviewed_moves", "point_loss_per_move",
                                                           "blunders", "match_rate", "search_s_per_move", "usd_per_move")}
                                    for r in ab["rows"]]}
    if baseline and Path(baseline).exists():
        b = json.loads(Path(baseline).read_text())
        g = b["games"][0]
        out["v1_pilot"] = {"opponent": g["opponent"], "our_color": g["our_color"], "result": g["result"],
                           "end_reason": g["end_reason"], "review": g["review"]["summary"],
                           "per_move": b["totals"]["per_finished_move"]}
    return out


def markdown(rep: dict) -> str:
    c, t = rep["condition"], rep["totals"]
    ss = c.get("start_state") or {}
    L = [f"# Full system strength: MCTS v2 + model + heuristic learning ({rep['generated_at'][:10]})", "",
         f"- condition: {c['engine']}; {c['time_per_move_s']} s/move, {c['threads']} search threads and at most "
         f"{c['llm_workers_per_stream']} model sessions in flight per game; decision {c['decision']}",
         "- streams (parallel, one shared learning state): " + "; ".join(f"{k}: {', '.join(v)}" for k, v in c["streams"].items()),
         f"- start: weights {ss.get('version')} with {ss.get('rules')} book rules (book v{ss.get('book_version')}), "
         f"copied from `{ss.get('copied_from')}`",
         f"- totals: {t['games_finished']} games finished ({t['games_unfinished']} unfinished), {t['decisions']} decisions, "
         f"{t['sessions']} model sessions ({', '.join(f'{k} {v}' for k, v in sorted(t['sessions_by_kind'].items()))}), "
         f"{t['cost_usd']} USD ({t['usd_per_move']} per move); search {t['search_s_per_move']} s and wall "
         f"{t['wall_s_per_move']} s per move; decisions without model input {t['no_model_input_decisions']}; waited for "
         f"the model {t['waited_for_model_s']} s; failed sessions {t['failed_sessions']} (rate-limited {t['rate_limited_sessions']})",
         f"- run dir: `{rep['run_dir']}`", ""]
    L += ["| opponent (Elo) | games | W-L | B/W | Elo, 95% CI | point loss / move (reviewer) | blunders (>= 5) | match | "
          "search / wall s per move | sessions / move | USD / move | decision rules | end reasons |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        e = r["elo"]
        L.append(f"| {r['opponent']} ({r['opponent_elo'] or 'unrated'}) | {r['games']}"
                 + (f" (+{r['unfinished']} unfinished)" if r["unfinished"] else "") + f" | {r['wins']}-{r['losses']} | "
                 f"{r['colors']['B']}/{r['colors']['W']} | "
                 + (f"{e['elo']} [{e['ci95'][0]}, {e['ci95'][1]}]" if e else "-")
                 + f" | {_f(r['point_loss_per_move'], 3)} (median {_f(r['point_loss_median'], 2)}) over {r['reviewed_moves']} "
                 f"({r['reviewer']}) | {r['blunders']} | {_f(r['match_rate'], 3)} | {_f(r['search_s_per_move'], 1)} / "
                 f"{_f(r['wall_s_per_move'], 1)} | {_f(r['sessions_per_move'], 1)} | {_f(r['usd_per_move'], 2)} | "
                 + ", ".join(f"{k} {v}" for k, v in sorted(r["decision_rules"].items(), key=lambda x: -x[1]))
                 + f" | {', '.join(f'{k} {v}' for k, v in r['end_reasons'].items())} |")
    p = rep.get("elo_pooled_rated")
    if p:
        L += ["", f"Pooled Elo over the {p['games']} rated games (score {p['score']}): **{p['elo']}**, 95% CI "
                  f"[{p['ci95'][0]}, {p['ci95'][1]}] (se {p['se']}), on the calibrated b10c128 ladder scale (lv7 1850, "
                  f"lv8 2064), the arena's own fit (MAP, prior centred on the opponents' mean Elo, sd 350)."]
    L += ["", "## Comparison", "",
          "| system | opponent(s) | games | W-L | Elo, 95% CI | point loss / move (reviewer) | blunders | match | s / move | USD / move |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        e = r["elo"]
        L.append(f"| full system ({c['time_per_move_s']} s/move) | {r['opponent']} | {r['games']} | {r['wins']}-{r['losses']} | "
                 + (f"{e['elo']} [{e['ci95'][0]}, {e['ci95'][1]}]" if e else "-")
                 + f" | {_f(r['point_loss_per_move'], 3)} ({(r['reviewer'] or '').split(',')[0]}) | {r['blunders']} | "
                 f"{_f(r['match_rate'], 3)} | {_f(r['wall_s_per_move'], 0)} | {_f(r['usd_per_move'], 2)} |")
    if p:
        L.append(f"| full system | lv7 + lv8 pooled | {p['games']} | {round(p['score'] * p['games'])}-"
                 f"{p['games'] - round(p['score'] * p['games'])} | {p['elo']} [{p['ci95'][0]}, {p['ci95'][1]}] | | | | | |")
    ab = rep.get("ablation")
    if ab:
        for r in ab["rows"]:
            e = r.get("elo")
            L.append(f"| code-only ablation ({ab['time_per_move_s']} s/move) | {r['opponent']} | {r['games']} | "
                     f"{r['wins']}-{r['losses']} | " + (f"{e['elo']} [{e['ci95'][0]}, {e['ci95'][1]}]" if e else "-")
                     + f" | {_f(r['point_loss_per_move'], 3)} ({(r['reviewer'] or '').split(',')[0]}) | {r['blunders']} | "
                     f"{_f(r['match_rate'], 3)} | {_f(r['search_s_per_move'], 0)} | 0 |")
        e = ab.get("elo_pooled_rated")
        if e:
            L.append(f"| code-only ablation | lv7 + lv8 pooled | {e['games']} | {round(e['score'] * e['games'])}-"
                     f"{e['games'] - round(e['score'] * e['games'])} | {e['elo']} [{e['ci95'][0]}, {e['ci95'][1]}] | | | | | |")
    v = rep.get("v1_pilot")
    if v:
        L.append(f"| v1 pilot (tree harness) | {v['opponent']} | 1 | 0-1 | - | {_f(v['review']['avg_loss'], 3)} (kata1-tf3-b11c768) | "
                 f"{v['review']['blunders']} | {_f(v['review']['match_rate'], 3)} | {_f(v['per_move']['seconds'], 0)} | "
                 f"{_f(v['per_move']['cost_usd'], 2)} |")
    L += ["", "- point loss / move: mean over all our reviewed moves; the ladder arena's reviewer is its own b10c128 net, "
              "the kata1 arena's the strong net (kata1-tf3-b11c768, 1600 visits); only rows with the same reviewer compare."]
    lr = rep["learning"]
    bk = lr.get("book") or {}
    L += ["", "## Heuristics book and weights", "",
          f"- learner: {lr['updates']} updates in this run, {lr['accepted']} accepted; weights {lr['version_start']} -> "
          f"{lr['version_now']}; book {bk.get('start_rules')} -> {bk.get('active_rules')} active rules (book version "
          f"{bk.get('book_version')})", "",
          "| game | heuristic jobs | rules proposed / accepted / rejected | nudges proposed / accepted / rejected | weights first -> last |",
          "|---|---|---|---|---|"]
    for g in rep["games"]:
        b = g["book"]
        L.append(f"| {g['stream']}{int(g['segment'].split('-')[0])}g{g['game_no']} {g['opponent']} ({g['our_color']}) | {b['jobs']} | "
                 f"{b['rules_proposed']} / {b['rules_accepted']} / {b['rules_rejected']} | {b['nudges_proposed']} / "
                 f"{b['nudges_accepted']} / {b['nudges_rejected']} | {g['weights_first']} -> {g['weights_last']} |")
    if bk.get("new_rules"):
        L += ["", "Rules added during these games (the model's text; weight proposed -> now):", ""]
        for r in bk["new_rules"]:
            L.append(f"- {r['id']} {r['name']} ({r.get('label') or '?'}): {r['text']} "
                     f"[{_f(r['weight_proposed'])} -> {_f(r['weight_now'])}; held-out gain {_f(r.get('gain'), 4)}]")
    L += ["", "## Games", "",
          "| game | opponent | we | result | reason | plies | decisions | loss / move | blunders | USD | sessions | "
          "no model input | waited s | rules (decisions) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in rep["games"]:
        rv = g["review"] or {}
        L.append(f"| {g['stream']}{int(g['segment'].split('-')[0])}g{g['game_no']} | {g['opponent']} | {g['our_color']} | "
                 f"{g['result'] or g['status']} | {g['end_reason'] or '-'} | {g['plies']} | {g['decisions']} | "
                 f"{_f(rv.get('avg_loss'), 3)} | {rv.get('blunders', '-')} | {g['cost_usd']} | {g['sessions']} | "
                 f"{g['no_model_input']} | {g['waited_for_model_s']} | "
                 + ", ".join(f"{k} {v}" for k, v in g["decision_rules"].items()) + " |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run")
    ap.add_argument("--format", default="md", choices=["md", "json"])
    ap.add_argument("--path-root", default="")
    ap.add_argument("--out-dir", default="", help="write summary.json and report.md here")
    ap.add_argument("--start-state", default="")
    ap.add_argument("--ablation", default=str(EVID / "mcts-ablation-20261007/summary.json"))
    ap.add_argument("--baseline", default=str(EVID / "pilot-20261005/report.json"))
    ap.add_argument("--no-sgf", action="store_true", help="leave the SGFs out of the JSON")
    a = ap.parse_args(argv)
    run = Path(a.run).resolve()
    rep = relabel(build(run, Path(a.start_state) if a.start_state else None, Path(a.ablation), Path(a.baseline)),
                  a.path_root)
    if a.no_sgf:
        for g in rep["games"]:
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
