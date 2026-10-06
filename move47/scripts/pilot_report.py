#!/usr/bin/env python3
"""pilot_report.py: what a tree-harness arena run did, move by move (finished or mid-game).

  python3 scripts/pilot_report.py RUN_DIR [--arena URL] [--arena-dir DIR] [--format both|json|md]

RUN_DIR is the runner's --run-dir: logs/run.json (arena run id) and workspace/tree/ (the gotree run:
dag.db, moves.jsonl, jobs/<id>-<kind>-<hex>/session.jsonl).  Per search (= one of our moves): jobs
ok / failed / running by kind, seconds, cost and tokens summed over its job dirs (abstract job
included), the top candidates and the decision.  From the arena (viewer token, else admin token, read
from ARENA_DIR/{viewer,admin}.token and sent only as a header, never printed): our colour, the move the
arena recorded at that ply, KataGo's reply and its delay, result and reason, SGF, and, once the game is
finished and reviewed, KataGo's per-move point loss for our moves.  Without the arena, the local part
is reported and `arena.error` says why.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

M47 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(M47))
from gotree.workers import _cli_usage  # noqa: E402  (the harness's own per-job cost accounting)

DEFAULT_ARENA_DIR = Path("/data/haiyangw/claude/Move47/runs/move47/arena")
TOKEN_KEYS = ("input", "output", "cache_read", "cache_write")


# ------------------------------------------------------------------ local: the gotree run
def tree_dir(run_dir: Path) -> Path:
    t = run_dir / "workspace" / "tree"
    return t if t.is_dir() else run_dir          # also accept a bare gotree run directory


def job_usage(tree: Path) -> dict[int, dict]:
    """job id -> usage of its session (cost and tokens); `final` once the session wrote its result."""
    out = {}
    for jd in sorted((tree / "jobs").glob("*-*-*")):
        try:
            jid = int(jd.name.split("-", 1)[0])
        except ValueError:
            continue
        u = _cli_usage(jd / "session.jsonl")
        u["final"] = u["cost_usd"] > 0          # the session's result event (with its cost) has arrived
        u["dir"] = jd.name
        out[jid] = u
    return out


def _ro(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def searches(tree: Path, usage: dict[int, dict], now: Optional[float] = None) -> list[dict]:
    """One entry per search (dag roots table), with the jobs created while it ran."""
    db = tree / "dag.db"
    if not db.exists():
        return []
    now = now or time.time()
    con = _ro(db)
    roots = [dict(r) for r in con.execute("SELECT * FROM roots ORDER BY id")]
    jobs = [dict(r) for r in con.execute("SELECT id, kind, status, created, finished, error FROM jobs ORDER BY id")]
    con.close()
    out = []
    for i, r in enumerate(roots):
        end = r["finished"] or (roots[i + 1]["created"] if i + 1 < len(roots) else now)
        mine = [j for j in jobs if r["created"] <= j["created"] < end + 1e-6]
        summ = json.loads(r["summary"]) if r["summary"] else {}
        kinds: dict[str, dict] = {}
        for j in mine:
            k = kinds.setdefault(j["kind"], {"ok": 0, "failed": 0, "running": 0})
            k["ok" if j["status"] == "done" else "failed" if j["status"] == "failed" else "running"] += 1
        tok = {k: sum(int(usage.get(j["id"], {}).get(k, 0)) for j in mine) for k in TOKEN_KEYS}
        label = r["label"] or ""
        ply = int(label.rsplit("move", 1)[1]) if "move" in label and label.rsplit("move", 1)[1].isdigit() else None
        game = int(label[4:].split("-", 1)[0]) if label.startswith("game") and label[4:].split("-", 1)[0].isdigit() \
            else None
        out.append({
            "label": label, "game": game, "ply": ply, "finished": r["finished"] is not None,
            "started_at": r["created"],
            "seconds": round(end - r["created"], 1),
            "search_seconds": summ.get("seconds"),
            "jobs": len(mine),
            "jobs_ok": sum(1 for j in mine if j["status"] == "done"),
            "jobs_failed": sum(1 for j in mine if j["status"] == "failed"),
            "jobs_running": sum(1 for j in mine if j["status"] not in ("done", "failed")),
            "by_kind": kinds,
            "failures": [f"{j['id']} {j['kind']}: {(j['error'] or '')[:160]}" for j in mine if j["status"] == "failed"],
            "cost_usd": round(sum(float(usage.get(j["id"], {}).get("cost_usd", 0)) for j in mine), 4),
            "jobs_without_cost": sum(1 for j in mine if not usage.get(j["id"], {}).get("final")),
            "tokens": tok,
            "decision": r["decision_real"],
            "rule": (summ.get("decision") or {}).get("rule"),
            "candidates": [{k: c.get(k) for k in ("real", "n", "q", "prior", "source")}
                           for c in (summ.get("candidates") or [])[:6]],
        })
    return out


# ------------------------------------------------------------------ arena (read-only, viewer scope)
def read_token(arena_dir: Path) -> str:
    for name in ("viewer.token", "admin.token"):
        f = arena_dir / name
        try:
            t = f.read_text().strip()
        except OSError:
            continue
        if t:
            return t
    return ""


def _get(url: str, token: str, path: str):
    req = urllib.request.Request(url.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def arena_data(url: str, token: str, run_id: str) -> dict:
    run = _get(url, token, f"/api/runs/{run_id}")
    if not run.get("ok"):
        raise RuntimeError(run.get("error"))
    ids = [g["id"] for g in run.get("games") or []]
    live = (run["summary"].get("live") or {}).get("game_id")
    if live and live not in ids:
        ids.append(live)
    games = [_get(url, token, f"/api/games/{gid}") for gid in ids]
    events, after = [], 0
    while True:
        evs = _get(url, token, f"/api/events?run={run_id}&after={after}").get("events") or []
        events += evs
        if len(evs) < 500:
            break
        after = evs[-1]["id"]
    return {"summary": run["summary"], "games": games, "events": events}


# ------------------------------------------------------------------ report
def build(run_dir: Path, arena_url: str = "", token: str = "", now: Optional[float] = None) -> dict:
    run_dir = Path(run_dir)
    tree = tree_dir(run_dir)
    meta = {}
    try:
        meta = json.loads((run_dir / "logs" / "run.json").read_text())
    except (OSError, ValueError):
        pass
    usage = job_usage(tree)
    srch = searches(tree, usage, now)
    rep: dict = {"run_dir": str(run_dir), "tree_dir": str(tree), "run": meta, "generated_at": time.time(),
                 "searches": srch}
    all_tok = {k: sum(int(u.get(k, 0)) for u in usage.values()) for k in TOKEN_KEYS}
    done = [s for s in srch if s["finished"]]
    rep["totals"] = {
        "searches": len(srch), "searches_finished": len(done),
        "job_dirs": len(usage), "jobs_failed": sum(s["jobs_failed"] for s in srch),
        "cost_usd": round(sum(float(u.get("cost_usd", 0)) for u in usage.values()), 4),
        "tokens": all_tok,
        "jobs_without_cost": sum(1 for u in usage.values() if not u["final"]),
        "per_finished_move": None if not done else {
            "cost_usd": round(sum(s["cost_usd"] for s in done) / len(done), 4),
            "seconds": round(sum(s["seconds"] for s in done) / len(done), 1),
            "jobs": round(sum(s["jobs"] for s in done) / len(done), 1)},
    }
    rep["arena"] = None
    if arena_url and meta.get("id"):
        try:
            rep["arena"] = arena_data(arena_url, token, meta["id"])
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as e:
            rep["arena"] = {"error": f"{type(e).__name__}: {e}"}
    rep["games"] = [_game(g, srch, (rep["arena"] or {}).get("events") or []) for g in
                    ((rep["arena"] or {}).get("games") or [])]
    return rep


def _game(gv: dict, srch: list[dict], events: list[dict]) -> dict:
    g = gv["game"]
    me = g["agent_color"]
    moves = gv.get("moves") or []
    by_ply = {m["ply"]: m for m in moves}
    ts = {}
    for e in events:
        d = e.get("data") or {}
        if e.get("kind") == "move" and d.get("game_id") == g["id"]:
            ts[d["ply"]] = e["ts"]
    review = {r["ply"]: r for r in (gv.get("review") or [])}
    ours = []
    for s in srch:
        if s["ply"] is None or (s["game"] is not None and s["game"] != g["game_no"]):
            continue
        m, opp = by_ply.get(s["ply"]), by_ply.get(s["ply"] + 1)
        row = {"ply": s["ply"], "decision": s["decision"], "played": m["coord"] if m and m["actor"] == "agent" else None,
               "think_ms": m.get("think_ms") if m else None,
               "reply": opp["coord"] if opp and opp["actor"] == "opponent" else None,
               "reply_seconds": round(ts[s["ply"] + 1] - ts[s["ply"]], 2)
               if (s["ply"] in ts and s["ply"] + 1 in ts) else None}
        row["accepted"] = None if not s["finished"] else (row["played"] is not None and
                                                           (row["played"] or "").upper() == (s["decision"] or "").upper())
        rv = review.get(s["ply"])
        if rv and rv["color"] == me:
            row["review"] = {k: rv.get(k) for k in ("loss", "best", "matched", "lead_before", "lead_after")}
        ours.append(row)
    rs = gv.get("review_summary")
    return {"id": g["id"], "game_no": g["game_no"], "opponent": g["opponent"], "our_color": me,
            "status": g["status"], "moves": len(moves), "result": g.get("result"), "winner": g.get("winner"),
            "end_reason": g.get("end_reason"), "margin": g.get("margin"),
            "illegal_count": g.get("illegal_count"), "sgf": gv.get("sgf"),
            "move_list": " ".join(f"{m['ply']}.{m['color']}{m['coord']}" for m in moves),
            "our_moves": ours,
            "review": None if not gv.get("review") else {
                "summary": rs, "our_loss": [{"ply": r["ply"], "move": r["move"], "loss": r["loss"], "best": r["best"]}
                                            for r in gv["review"] if r["color"] == me]},
            "review_note": None if gv.get("review") else ("game in progress: the engine review comes after the game"
                                                          if g["status"] != "finished" else "review pending")}


def _f(x, nd=2):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def markdown(rep: dict) -> str:
    run = rep.get("run") or {}
    t = rep["totals"]
    L = [f"# Pilot report: {run.get('name') or rep['run_dir']}", "",
         f"- run: `{run.get('id', '?')}` (model {run.get('model') or '?'}, harness {run.get('harness') or '?'})",
         f"- run dir: `{rep['run_dir']}`",
         f"- searches: {t['searches']} ({t['searches_finished']} finished); job dirs {t['job_dirs']}, "
         f"failed jobs {t['jobs_failed']}, jobs without a cost line {t['jobs_without_cost']}",
         f"- cost so far: {t['cost_usd']:.2f} USD; tokens in {t['tokens']['input']}, out {t['tokens']['output']}, "
         f"cache read {t['tokens']['cache_read']}, cache write {t['tokens']['cache_write']}"]
    pm = t.get("per_finished_move")
    if pm:
        L.append(f"- per finished move: {pm['cost_usd']:.2f} USD, {pm['seconds']:.0f} s, {pm['jobs']} jobs")
    arena = rep.get("arena")
    if arena is None:
        L.append("- arena: not queried")
    elif "error" in arena:
        L.append(f"- arena: unavailable ({arena['error']})")
    for g in rep.get("games") or []:
        L += ["", f"## Game #{g['game_no']} vs {g['opponent']}: we are {'Black' if g['our_color'] == 'B' else 'White'}",
              "", f"- status: {g['status']}, {g['moves']} moves, illegal attempts {g['illegal_count']}"]
        if g["status"] == "finished":
            L.append(f"- result: {g['result']} (winner {g['winner']}, reason {g['end_reason']}, margin {_f(g['margin'], 1)})")
        L.append(f"- moves: {g['move_list'] or '(none)'}")
    L += ["", "## Our moves", "",
          "| ply | decision | played | ok/failed/run jobs | s | USD | tok in/out/cr/cw | top candidates (n, q) | reply (s) | loss |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    rows = {(g["game_no"], r["ply"]): r for g in rep.get("games") or [] for r in g["our_moves"]}
    for s in rep["searches"]:
        r = rows.get((s["game"], s["ply"]), {})
        tk = s["tokens"]
        cands = ", ".join(f"{c['real']} ({c['n']}, {_f(c['q'])})" for c in s["candidates"][:4])
        loss = (r.get("review") or {}).get("loss")
        L.append(f"| {s['ply']} | {s['decision'] or '(searching)'} | {r.get('played') or '-'}"
                 f"{'' if r.get('accepted') in (None, True) else ' (not the decision)'} | "
                 f"{s['jobs_ok']}/{s['jobs_failed']}/{s['jobs_running']} | {s['seconds']:.0f} | {s['cost_usd']:.2f} | "
                 f"{tk['input']}/{tk['output']}/{tk['cache_read']}/{tk['cache_write']} | {cands} | "
                 f"{r.get('reply') or '-'} ({_f(r.get('reply_seconds'))}) | {_f(loss)} |")
    for g in rep.get("games") or []:
        if g["review"]:
            rs = g["review"]["summary"] or {}
            L += ["", f"## KataGo review, game #{g['game_no']}", "",
                  f"- our moves: {rs.get('moves')}, average point loss {rs.get('avg_loss')}, "
                  f"blunders (>= 5 points) {rs.get('blunders')}, match rate {rs.get('match_rate')}",
                  "- per move: " + ", ".join(f"{x['ply']}.{x['move']} {x['loss']}" for x in g["review"]["our_loss"])]
        else:
            L += ["", f"- review: {g['review_note']}"]
        L += ["", "SGF:", "", "```", g["sgf"] or "", "```"]
    fails = [f for s in rep["searches"] for f in s["failures"]]
    if fails:
        L += ["", "## Failed jobs", ""] + [f"- {x}" for x in fails[:40]]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pilot_report", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir")
    p.add_argument("--arena", default="http://127.0.0.1:8765", help="arena URL ('' = local data only)")
    p.add_argument("--arena-dir", default=str(DEFAULT_ARENA_DIR), help="directory with viewer.token / admin.token")
    p.add_argument("--format", choices=("both", "json", "md"), default="both")
    a = p.parse_args(argv)
    token = read_token(Path(a.arena_dir)) if a.arena else ""
    rep = build(Path(a.run_dir), a.arena, token)
    if a.format in ("both", "json"):
        print(json.dumps(rep, indent=1, default=str))
    if a.format in ("both", "md"):
        print(markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
