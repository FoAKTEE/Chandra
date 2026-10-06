"""The "divine move" probe: can the system find a specific famous move?

Default target: AlphaGo's move 37 in game 2 against Lee Sedol (Black P10,
the fifth-line shoulder hit).  The probe reports, separately:
  0. recall      does the model recognise the position (contamination)?
  1. prior       is the move among the very first candidates the LLM proposes?
  2. discovery   how its rank / visits evolve as the search budget grows
  3. decision    what the system finally plays
  4. judge       (optional, offline) KataGo's opinion of every move involved
Positions are always presented to workers in their canonical orientation,
which in general differs from the original game's.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from goarena.sgf import read_sgf

from .jobs import Job
from .position import Position, coord, sym_maps
from .search import Search


def load_target(sgf_path: str, move_no: int) -> tuple[Position, Optional[int], str]:
    text = Path(sgf_path).read_text()
    g = read_sgf(text)
    if not 1 <= move_no <= len(g["moves"]):
        raise ValueError(f"the game has {len(g['moves'])} moves")
    pos = Position.from_sgf(text, upto=move_no - 1)
    color, p = g["moves"][move_no - 1]
    return pos, p, ("B" if color == 1 else "W")


def run_probe(sgf_path: str, move_no: int, search: Search, label: str = "", recall: bool = True,
              out_dir: Optional[Path] = None) -> dict:
    pos, target, color = load_target(sgf_path, move_no)
    size = pos.size
    label = label or f"{Path(sgf_path).stem}#{move_no}"
    report: dict = {"label": label, "sgf": str(sgf_path), "move_no": move_no, "target_real": coord(target, size),
                    "to_play": color, "started": time.time()}
    root, can, s = search.dag.ensure(pos)
    target_c = sym_maps(size)[0][s][target] if target is not None else None
    report["presented_orientation"] = s
    report["target_presented"] = coord(target_c, size)
    # 0. recall check (contamination)
    if recall:
        job = Job("recall", root, can, {"title": "Position"})
        res = search.worker_for("recall").run(job)
        rec = res.result or {}
        hit = False
        fm = rec.get("famous_move", "")
        if rec.get("recognized") and fm:
            try:
                from .position import point
                hit = point(fm, size) == target_c
            except Exception:
                hit = False
        report["recall"] = {**rec, "names_target": hit, "ok": res.ok, "error": res.error}
    # 1-3. search
    summary = search.run(pos, label=label, target_real=target)
    edge = search.dag.edge(root, target_c)
    report["prior"] = None if edge is None else {"source": edge.source, "prior": round(edge.prior, 4),
                                                 "why": edge.why[:300]}
    first = search.dag.q1("SELECT result FROM jobs WHERE key=? AND kind='expand' AND status='done' ORDER BY id LIMIT 1",
                          (root,))
    if first and first["result"]:
        r = json.loads(first["result"])
        ranks = [c["move"] for c in sorted(r.get("candidates", []), key=lambda c: -c["prior"])]
        inv = sym_maps(size)[1][s]
        report["first_expand"] = {
            "target_rank": (ranks.index(target_c) + 1) if target_c in ranks else None,
            "target_unconventional": target_c in [u["move"] for u in r.get("unconventional", [])],
            "candidates": [coord(None if m is None else inv[m], size) for m in ranks],
            "unconventional": [coord(None if u["move"] is None else inv[u["move"]], size)
                               for u in r.get("unconventional", [])]}
    report["discovery_curve"] = summary.get("curve", [])
    report["final"] = summary.get("target")
    report["decision"] = summary["decision"]
    report["found"] = summary["decision"].get("real", "").upper() == coord(target, size).upper()
    report["usage"] = summary.get("usage")
    report["top"] = summary["candidates"][:10]
    report["finished"] = time.time()
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"probe-{label.replace('/', '_').replace('#', '-')}.json").write_text(json.dumps(report, indent=2))
    return report


def render_report(r: dict) -> str:
    lines = [f"PROBE {r['label']}: target {r['to_play']} {r['target_real']} "
             f"(shown to workers as {r['target_presented']}, orientation {r['presented_orientation']})"]
    if "recall" in r:
        rc = r["recall"]
        lines.append(f"  recall:    recognized={rc.get('recognized')} names_target={rc.get('names_target')} "
                     f"{rc.get('source', '')}")
    fe = r.get("first_expand")
    if fe:
        lines.append(f"  prior:     first expansion rank={fe['target_rank']} unconventional={fe['target_unconventional']} "
                     f"candidates={' '.join(fe['candidates'][:12])} unconventional={' '.join(fe.get('unconventional', []))}")
    pr = r.get("prior")
    lines.append(f"  in tree:   {'via ' + pr['source'] + ' prior=' + str(pr['prior']) if pr else 'never proposed'}")
    fin = r.get("final") or {}
    lines.append(f"  final:     rank={fin.get('rank')} of {fin.get('of')}  n={fin.get('n')}  q={fin.get('q')}")
    curve = r.get("discovery_curve") or []
    if curve:
        pts = [c for c in curve if c.get("in_tree")]
        first_in = pts[0]["jobs"] if pts else None
        best_rank = min((c["rank"] for c in pts), default=None)
        lines.append(f"  discovery: first in tree after {first_in} jobs; best rank {best_rank}")
    d = r["decision"]
    lines.append(f"  decision:  {d.get('real')} ({d.get('rule')}); found target: {r['found']}")
    top = r.get("top") or []
    lines.append("  top moves: " + "  ".join(f"{c['real']}(n={c['n']},q={c['q']})" for c in top[:6]))
    u = r.get("usage") or {}
    lines.append(f"  cost:      {u.get('jobs')} jobs, {u.get('input')} in / {u.get('output')} out tokens, "
                 f"${u.get('cost_usd', 0):.2f} reported")
    if "judge" in r:
        g = r["judge"]["graded"]
        lines.append(f"  judge:     engine best {r['judge']['engine_best']}; "
                     + "; ".join(f"{k} {v['move']}: loss {v['loss']} pts, engine rank {v['engine_rank']}, "
                                 f"policy rank {v['engine_policy_rank']}" for k, v in g.items()))
    return "\n".join(lines)


def prior_check(sgf_path: str, move_no: int, worker, samples: int = 5, k: int = 10, u: int = 4) -> dict:
    """Cheapest useful experiment: ask for root candidates `samples` times in
    fresh contexts.  Is the target ever proposed, and at what rank?  If it
    never is, no amount of search budget will find it without more breadth."""
    pos, target, color = load_target(sgf_path, move_no)
    can, s = pos.canonical()
    target_c = sym_maps(pos.size)[0][s][target]
    inv = sym_maps(pos.size)[1][s]
    out = {"target_real": coord(target, pos.size), "samples": []}
    for i in range(samples):
        job = Job("expand", can.raw_key, can, {"k": k, "u": u, "title": "Position"})
        job.id = i + 1
        res = worker.run(job)
        if not res.ok:
            out["samples"].append({"ok": False, "error": res.error})
            continue
        r = res.result
        ranks = [c["move"] for c in sorted(r["candidates"], key=lambda c: -c["prior"])]
        unconv = [x["move"] for x in r["unconventional"]]
        out["samples"].append({
            "ok": True, "rank": ranks.index(target_c) + 1 if target_c in ranks else None,
            "prior": next((c["prior"] for c in r["candidates"] if c["move"] == target_c), None),
            "unconventional": target_c in unconv,
            "candidates": [coord(None if m is None else inv[m], pos.size) for m in ranks],
            "unconventional_moves": [coord(None if m is None else inv[m], pos.size) for m in unconv],
            "winrate": r["value"]["winrate"], "usage": res.usage})
    ok = [x for x in out["samples"] if x.get("ok")]
    out["proposed_rate"] = round(sum(1 for x in ok if x["rank"] or x["unconventional"]) / len(ok), 3) if ok else None
    return out
