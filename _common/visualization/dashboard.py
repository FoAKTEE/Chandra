#!/usr/bin/env python3
"""dashboard — one self-contained HTML mission dashboard per paper.

The per-ledger `render-html` views show one table each; this module renders the
HUMAN cockpit: a single page that reads all four ledgers (knowledge / result /
claim / error) plus the hash chains and shows, in one place:

  * header      — paper, generated-at, git commit, per-ledger chain integrity
  * KPI row     — solid nodes, admitted results, obligations, claims, trials
  * mission DAG — the knowledge ledger drawn as an inline SVG (no external
                  libraries): columns = topological depth, one card per node,
                  status carried by glyph + word + color (never color alone),
                  `k`/`t✗` badges as in dag_mermaid; click or focus a node for
                  its doubly-linked detail (knowledge history, trials, results,
                  claims that cite it)
  * ledger tabs — the four ledgers as searchable, sortable, status-filterable
                  tables; click a row for its full JSON

Everything is read-only over the ledgers (the ledgers stay canonical; this is
a rendered view, never hand-edited) and the output is fully self-contained:
inline CSS/JS, system fonts, zero network requests. Light and dark themes both
ship; the toggle persists per browser.

USAGE
    python _common/visualization/dashboard.py render --paper P
        [--repo-root DIR] [--out FILE] [--full-history]

Default output: results/views/dashboard/paper_<P>.html
`--paper` may be omitted when `mission.json` at the repo root names one.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from _common.ledgers import claims_database as cdb
    from _common.ledgers import error_database as edb
    from _common.ledgers import knowledge_database as kdb
    from _common.ledgers import ledger_common as lc
    from _common.ledgers import result_database as rdb
else:
    from ..ledgers import claims_database as cdb
    from ..ledgers import error_database as edb
    from ..ledgers import knowledge_database as kdb
    from ..ledgers import ledger_common as lc
    from ..ledgers import result_database as rdb


def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


# --- status vocabulary → semantic class (color NEVER carries meaning alone:
#     every chip and DAG node also shows the glyph and the exact status word) --

STATUS_CLASS = {
    # knowledge nodes
    "solid": "ok", "preliminary": "warn", "hypothesis": "mut",
    "blocking": "bad", "future": "mut", "amended": "mut",
    # results (admitted classifications are verified within their class)
    "checked": "ok", "conditional": "warn", "approximate": "warn",
    "empirical": "ok", "existence_only": "ok",
    "conjectural": "warn", "unchecked": "mut", "refuted": "bad",
    # trials
    "pass": "ok", "partial": "warn", "fail": "bad", "crash": "bad",
    # claims / obligations / assumptions
    "open": "warn", "in_progress": "warn", "admitted": "ok",
    "withdrawn": "mut", "discharged": "ok", "waived": "mut",
    "active": "mut", "relaxed": "warn", "retired": "mut",
}

NODE_GLYPH = {"solid": "●", "preliminary": "◐", "hypothesis": "○",
              "blocking": "✗", "future": "□", "amended": "~"}


def status_chip(status: Any) -> str:
    s = "" if status is None else str(status)
    cls = STATUS_CLASS.get(s, "mut")
    return f'<span class="chip {cls}"><span class="dot"></span>{esc(s) or "—"}</span>'


# --- DAG layout (pure Python; rendered as inline SVG) --------------------------

NODE_W, NODE_H, HGAP, VGAP, PAD = 192, 46, 72, 16, 18


def dag_layout(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Layer the latest non-amended nodes by longest-path depth, order each
    column by predecessor barycenter (one pass, fewer crossings), and assign
    pixel positions. Nodes on a cycle get depth -1 and are reported, not drawn."""
    ids = {n["node_id"] for n in nodes}
    preds = {n["node_id"]: [p for p in (n.get("predecessors") or []) if p in ids]
             for n in nodes}
    depth: dict[str, int] = {}
    frontier = [nid for nid in preds if not preds[nid]]
    for nid in frontier:
        depth[nid] = 0
    # longest-path layering, Kahn-style; anything never resolved is on a cycle
    remaining = {nid for nid in preds if nid not in depth}
    changed = True
    while changed:
        changed = False
        for nid in sorted(remaining):
            if all(p in depth for p in preds[nid]):
                depth[nid] = 1 + max(depth[p] for p in preds[nid])
                remaining.discard(nid)
                changed = True
    cyclic = sorted(remaining)

    cols: dict[int, list[str]] = {}
    for nid, d in depth.items():
        cols.setdefault(d, []).append(nid)
    for d in cols:
        cols[d].sort()
    row: dict[str, int] = {}
    for d in sorted(cols):
        if d > 0:  # barycenter of predecessor rows, stable on ties
            cols[d].sort(key=lambda nid: (
                sum(row[p] for p in preds[nid] if p in row) / max(1, len(preds[nid])),
                nid))
        for i, nid in enumerate(cols[d]):
            row[nid] = i

    ncols = (max(cols) + 1) if cols else 0
    maxrows = max((len(v) for v in cols.values()), default=0)
    height = PAD * 2 + max(0, maxrows * (NODE_H + VGAP) - VGAP)
    width = PAD * 2 + max(0, ncols * NODE_W + (ncols - 1) * HGAP)
    pos: dict[str, tuple[float, float]] = {}
    for d, col in cols.items():
        col_h = len(col) * (NODE_H + VGAP) - VGAP
        y0 = PAD + (height - PAD * 2 - col_h) / 2
        for i, nid in enumerate(col):
            pos[nid] = (PAD + d * (NODE_W + HGAP), y0 + i * (NODE_H + VGAP))
    edges = [(p, nid) for nid, ps in preds.items() if nid in pos
             for p in ps if p in pos]
    return {"pos": pos, "edges": edges, "cyclic": cyclic,
            "width": max(width, 320), "height": max(height, 120)}


def _short_label(node_id: str, paper: str, limit: int = 24) -> str:
    short = node_id
    prefix = f"{paper}::"
    if short.startswith(prefix):
        short = short[len(prefix):]
    return short if len(short) <= limit else short[:limit - 1] + "…"


def dag_svg(paper: str, nodes: list[dict[str, Any]],
            kcount: dict[str, int],
            tcount: dict[str, tuple[int, int]]) -> tuple[str, list[str]]:
    """The DAG as an accessible inline SVG: each node is a focusable card with
    status glyph + word + accent, k/t badges, and a <title> tooltip."""
    lay = dag_layout(nodes)
    pos, edges = lay["pos"], lay["edges"]
    by_id = {n["node_id"]: n for n in nodes}
    parts: list[str] = []
    parts.append(
        f'<svg class="dag" width="{lay["width"]}" height="{lay["height"]}" '
        f'viewBox="0 0 {lay["width"]} {lay["height"]}" role="group" '
        f'aria-label="mission DAG, {len(pos)} nodes">')
    parts.append(
        '<defs>'
        '<marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0.8 L7,4 L0,7.2 Z" class="arrhead"/></marker>'
        '</defs>')
    for a, b in edges:  # edges under nodes
        ax, ay = pos[a][0] + NODE_W, pos[a][1] + NODE_H / 2
        bx, by = pos[b][0], pos[b][1] + NODE_H / 2
        mx = (ax + bx) / 2
        parts.append(
            f'<path class="edge" data-a="{esc(a)}" data-b="{esc(b)}" '
            f'd="M{ax:.1f},{ay:.1f} C{mx:.1f},{ay:.1f} {mx:.1f},{by:.1f} '
            f'{bx - 2:.1f},{by:.1f}" marker-end="url(#arr)"/>')
    for nid, (x, y) in pos.items():
        n = by_id[nid]
        status = str(n.get("status", ""))
        cls = STATUS_CLASS.get(status, "mut")
        glyph = NODE_GLYPH.get(status, "?")
        k = kcount.get(nid, 0)
        t, f = tcount.get(nid, (0, 0))
        badge = f"k{k}" + (f" · t{t}" + (f"✗{f}" if f else "") if t else "")
        summary = str(n.get("summary") or "")
        tip = f"{nid} — {status}" + (f"\n{summary}" if summary else "")
        parts.append(
            f'<g class="node {cls}" data-node="{esc(nid)}" tabindex="0" '
            f'role="button" aria-label="{esc(tip)}" transform="translate({x:.1f},{y:.1f})">'
            f'<title>{esc(tip)}</title>'
            f'<rect class="card" width="{NODE_W}" height="{NODE_H}" rx="9"/>'
            f'<rect class="accent" x="0" y="0" width="4" height="{NODE_H}" rx="2"/>'
            f'<text class="nid" x="14" y="19">{esc(_short_label(nid, paper))}</text>'
            f'<text class="nstat" x="14" y="35">{glyph} {esc(status)}'
            + (' <tspan class="adv">△</tspan>' if n.get("concept_advance") else "")
            + f'</text>'
            f'<text class="nbadge" x="{NODE_W - 10}" y="35" text-anchor="end">{esc(badge)}</text>'
            f'</g>')
    parts.append("</svg>")
    return "".join(parts), lay["cyclic"]


# --- data assembly --------------------------------------------------------------

def collect(paper: str, repo_root: str | Path | None, *,
            latest_only: bool = True) -> dict[str, Any]:
    root = Path(repo_root) if repo_root else Path.cwd()
    nodes_hist = kdb.read_entries(root, paper)          # full history for k-counts
    nodes = kdb.query(paper, latest_only=True, repo_root=root)
    results = rdb.query(paper, latest_only=latest_only, repo_root=root)
    claims = cdb.query(paper, latest_only=latest_only, repo_root=root)
    trials = edb.read_entries(root, paper)
    kcount: dict[str, int] = {}
    for r in nodes_hist:
        nid = r.get("node_id")
        if nid:
            kcount[nid] = kcount.get(nid, 0) + 1
    tcount: dict[str, tuple[int, int]] = {}
    for r in trials:
        nid = r.get("node_id")
        if nid:
            t, f = tcount.get(nid, (0, 0))
            tcount[nid] = (t + 1, f + (1 if r.get("pass_fail") in ("fail", "crash", "partial") else 0))
    chains = []
    for db, filename in lc.LEDGER_FILENAMES.items():
        d = lc.db_dir(root, db, paper)
        if (d / filename).exists():
            chains.append({"db": db, **lc.verify_chain(d, filename)})
    return {"paper": paper, "root": root, "nodes": nodes, "nodes_hist": nodes_hist,
            "results": results, "claims": claims, "trials": trials,
            "kcount": kcount, "tcount": tcount, "chains": chains,
            "git": lc.git_commit_short(root), "generated": lc.utc_now_iso()}


# --- page assembly ---------------------------------------------------------------

def _tile(label: str, value: str, sub: str = "", meter: float | None = None) -> str:
    m = ""
    if meter is not None:
        pct = max(0.0, min(1.0, meter)) * 100
        m = (f'<div class="meter" aria-hidden="true">'
             f'<div class="fill" style="width:{pct:.1f}%"></div></div>')
    return (f'<div class="tile"><div class="tlabel">{label}</div>'
            f'<div class="tvalue">{value}</div>{m}'
            + (f'<div class="tsub">{sub}</div>' if sub else "") + "</div>")


def _kpis(d: dict[str, Any]) -> str:
    nodes, results, claims, trials = d["nodes"], d["results"], d["claims"], d["trials"]
    live = [n for n in nodes if n.get("status") != "amended"]
    n_total = len(live)
    n_solid = sum(1 for n in live if n.get("status") == "solid")
    n_block = sum(1 for n in live if n.get("status") == "blocking")
    prog = [r for r in results if r.get("status") in rdb.GATE_PROGRESS_STATUSES]
    refuted = sum(1 for r in results if r.get("status") == "refuted")
    obs = [c for c in claims if c.get("kind") == "obligation"]
    ob_done = sum(1 for c in obs if c.get("status") == "discharged")
    cls = [c for c in claims if c.get("kind") == "claim"]
    cl_adm = sum(1 for c in cls if c.get("status") == "admitted")
    t_pass = sum(1 for t in trials if t.get("pass_fail") == "pass")
    t_fail = sum(1 for t in trials if t.get("pass_fail") in ("fail", "crash"))
    t_other = len(trials) - t_pass - t_fail
    sub_nodes = " · ".join(s for s in (
        f"{n_block} blocking" if n_block else "",
        f"{sum(1 for n in live if n.get('status') == 'preliminary')} preliminary",
        f"{sum(1 for n in live if n.get('status') == 'hypothesis')} hypothesis") if s)
    return '<section class="kpis" aria-label="mission status">' + "".join([
        _tile("Solid nodes", f"{n_solid}<span class='den'> / {n_total}</span>",
              sub_nodes, meter=(n_solid / n_total) if n_total else 0.0),
        _tile("Verified results", str(len(prog)),
              f"{len(results)} rows · {refuted} refuted" if results else "no rows yet"),
        _tile("Obligations discharged", f"{ob_done}<span class='den'> / {len(obs)}</span>",
              f"{sum(1 for c in obs if c.get('status') == 'open')} open",
              meter=(ob_done / len(obs)) if obs else 0.0),
        _tile("Claims admitted", f"{cl_adm}<span class='den'> / {len(cls)}</span>",
              f"{sum(1 for c in cls if c.get('status') in ('open', 'in_progress'))} open"),
        _tile("Trials", str(len(trials)),
              f"<span class='chip ok'><span class='dot'></span>{t_pass} pass</span> "
              f"<span class='chip bad'><span class='dot'></span>{t_fail} fail</span>"
              + (f" <span class='chip warn'><span class='dot'></span>{t_other} partial</span>"
                 if t_other else "")),
    ]) + "</section>"


def _chain_badges(chains: list[dict[str, Any]]) -> str:
    if not chains:
        return '<span class="chainbadge mut">no ledgers yet</span>'
    out = []
    for c in chains:
        if c["ok"]:
            out.append(f'<span class="chainbadge ok" title="{c["hashed"]}/{c["rows"]} rows hashed">'
                       f'✓ {esc(c["db"])} chain</span>')
        else:
            out.append(f'<span class="chainbadge bad">✗ {esc(c["db"])} chain broken '
                       f'@ row {c["break_at"]}</span>')
    return "".join(out)


_TABLE_SPECS: dict[str, dict[str, Any]] = {
    "results": {
        "title": "Results", "key": "results",
        "cols": ["timestamp", "result_id", "status", "evidence_type", "name",
                 "claim", "verdict", "open obligations"],
        "row": lambda r: [
            esc(r.get("timestamp")), f'<span class="mono">{esc(r.get("result_id"))}</span>',
            status_chip(r.get("status")), esc(r.get("evidence_type")),
            f'<div class="wrap">{esc(r.get("name"))}</div>',
            f'<div class="wrap">{esc(r.get("claim"))}</div>',
            esc((r.get("verifier_result") or {}).get("verdict")),
            str(len(r.get("open_obligations") or []))],
        "status": lambda r: r.get("status"),
    },
    "nodes": {
        "title": "DAG nodes", "key": "nodes",
        "cols": ["timestamp", "node_id", "status", "domain", "summary",
                 "equation labels", "predecessors"],
        "row": lambda r: [
            esc(r.get("timestamp")), f'<span class="mono">{esc(r.get("node_id"))}</span>',
            status_chip(r.get("status")), esc(r.get("domain")),
            f'<div class="wrap">{esc(r.get("summary"))}</div>',
            esc(", ".join(r.get("equation_labels") or [])),
            f'<span class="mono">{esc(", ".join(r.get("predecessors") or []))}</span>'],
        "status": lambda r: r.get("status"),
    },
    "claims": {
        "title": "Claims & obligations", "key": "claims",
        "cols": ["entry_id", "kind", "status", "statement", "settles / needs",
                 "node_ids"],
        "row": lambda r: [
            f'<span class="mono">{esc(r.get("entry_id"))}</span>', esc(r.get("kind")),
            status_chip(r.get("status")),
            f'<div class="wrap">{esc(r.get("statement"))}</div>',
            f'<span class="mono">{esc(r.get("result_ref") or r.get("discharged_by") or r.get("needed_evidence_type") or "")}</span>',
            f'<span class="mono">{esc(", ".join(r.get("node_ids") or []))}</span>'],
        "status": lambda r: r.get("status"),
    },
    "trials": {
        "title": "Trials", "key": "trials",
        "cols": ["timestamp", "iter", "task_id", "node_id", "stage", "change_type",
                 "metric", "outcome", "failure_mode", "summary"],
        "row": lambda r: [
            esc(r.get("timestamp")), esc(r.get("iteration")), esc(r.get("task_id")),
            f'<span class="mono">{esc(r.get("node_id"))}</span>', esc(r.get("stage")),
            esc(r.get("change_type")),
            esc(_metric_text(r)), status_chip(r.get("pass_fail")),
            esc(r.get("failure_mode")),
            f'<div class="wrap">{esc(r.get("change_summary"))}</div>'],
        "status": lambda r: r.get("pass_fail"),
    },
}


def _metric_text(r: dict[str, Any]) -> str:
    m = r.get("metric")
    if not isinstance(m, dict):
        return ""
    val = m.get("value")
    return f"{m.get('name', '')}={val}" if m.get("name") else str(val or "")


def _table_panel(spec: dict[str, Any], rows: list[dict[str, Any]], active: bool) -> str:
    statuses: dict[str, int] = {}
    for r in rows:
        s = str(spec["status"](r) or "—")
        statuses[s] = statuses.get(s, 0) + 1
    chips = ['<button class="fchip on" data-f="">all <span>%d</span></button>' % len(rows)]
    chips += [f'<button class="fchip" data-f="{esc(s)}">{esc(s)} <span>{c}</span></button>'
              for s, c in sorted(statuses.items())]
    head = "".join(f"<th>{esc(c)}</th>" for c in spec["cols"])
    body = []
    for i, r in enumerate(rows):
        cells = "".join(f"<td>{c}</td>" for c in spec["row"](r))
        body.append(f'<tr data-i="{i}" data-status="{esc(str(spec["status"](r) or "—"))}" '
                    f'tabindex="0">{cells}</tr>')
    empty = '<p class="empty">No rows in this ledger yet.</p>' if not rows else ""
    return f"""
<section class="panel{' on' if active else ''}" data-panel="{spec['key']}">
  <div class="controls">
    <input class="search" type="search" placeholder="filter {spec['key']}…" aria-label="filter {spec['key']}">
    <span class="fchips">{''.join(chips)}</span>
    <span class="count"></span>
  </div>
  {empty}
  <div class="tablewrap"><table data-src="{spec['key']}">
    <thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>
  </table></div>
</section>"""


def build_html(d: dict[str, Any]) -> str:
    paper = d["paper"]
    svg, cyclic = dag_svg(paper, [n for n in d["nodes"] if n.get("status") != "amended"],
                          d["kcount"], d["tcount"])
    cyc_note = ""
    if cyclic:
        cyc_note = ('<p class="cycwarn">⚠ cycle detected — not drawn: '
                    + esc(", ".join(cyclic)) + "</p>")
    legend = "".join(
        f'<span class="chip {STATUS_CLASS[s]}"><span class="dot"></span>{NODE_GLYPH[s]} {s}</span>'
        for s in ("solid", "preliminary", "hypothesis", "blocking", "future"))
    tabs = "".join(
        f'<button class="tab{" on" if i == 0 else ""}" data-tab="{k}">'
        f'{_TABLE_SPECS[k]["title"]}</button>'
        for i, k in enumerate(_TABLE_SPECS))
    panels = "".join(
        _table_panel(_TABLE_SPECS[k], d[k], i == 0)
        for i, k in enumerate(_TABLE_SPECS))
    payload = {k: d[k] for k in ("nodes", "results", "claims", "trials")}
    payload["nodes_hist"] = d["nodes_hist"]
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chandra — paper_{esc(paper)}</title>
<script>
/* theme before first paint (auto | light | dark, persisted) */
(function(){{var t=localStorage.getItem('chandra-theme');
if(t==='light'||t==='dark')document.documentElement.dataset.theme=t;}})();
</script>
<style>{_CSS}</style></head>
<body>
<header>
  <div>
    <h1>Chandra <span class="mono">paper_{esc(paper)}</span></h1>
    <p class="meta">generated {esc(d["generated"])} · git <span class="mono">{esc(d["git"])}</span>
      · ledgers are canonical — this page is a rendered view</p>
  </div>
  <div class="hright">{_chain_badges(d["chains"])}
    <button id="theme" title="theme: auto / light / dark">◐ theme</button></div>
</header>
{_kpis(d)}
<section class="card">
  <div class="cardhead"><h2>Mission DAG</h2><span class="legend">{legend}
    <span class="legendnote">△ concept advance · k = knowledge rows · t✗ = trials/failed</span></span></div>
  {cyc_note}
  <div class="dagwrap">{svg if d["nodes"] else '<p class="empty">No DAG yet — the knowledge ledger is empty (run decompose).</p>'}</div>
  <div id="nodedetail" class="nodedetail" hidden></div>
</section>
<section class="card">
  <div class="cardhead"><h2>Ledgers</h2><nav class="tabs">{tabs}</nav></div>
  {panels}
</section>
<footer>
  Regenerate: <span class="mono">python _common/visualization/dashboard.py render --paper {esc(paper)}</span>
  — rows enter the ledgers only through the executable admission gate.
</footer>
<script type="application/json" id="dashboard-data">{data_json}</script>
<script>{_JS}</script>
</body></html>
"""


# --- CSS / JS (inline; palette = validated reference instance, light + dark) ---

_CSS = """
:root{color-scheme:light;
  --plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
  --grid:#e1e0d9;--baseline:#c3c2b7;--border:rgba(11,11,11,.10);
  --accent:#2a78d6;--track:#cde2fb;
  --ok:#0ca30c;--warn:#fab219;--bad:#d03b3b;
  --okbg:rgba(12,163,12,.09);--warnbg:rgba(250,178,25,.14);--badbg:rgba(208,59,59,.10);
  --mutbg:rgba(137,135,129,.12);--hover:rgba(11,11,11,.04)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
  --accent:#3987e5;--track:#184f95;
  --okbg:rgba(12,163,12,.16);--warnbg:rgba(250,178,25,.14);--badbg:rgba(208,59,59,.18);
  --mutbg:rgba(137,135,129,.16);--hover:rgba(255,255,255,.05)}}
:root[data-theme=dark]{color-scheme:dark;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
  --accent:#3987e5;--track:#184f95;
  --okbg:rgba(12,163,12,.16);--warnbg:rgba(250,178,25,.14);--badbg:rgba(208,59,59,.18);
  --mutbg:rgba(137,135,129,.16);--hover:rgba(255,255,255,.05)}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--plane);
  color:var(--ink);margin:0 auto;padding:20px 24px 48px;max-width:1260px;font-size:14px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
  flex-wrap:wrap;margin-bottom:18px}
h1{font-size:20px;margin:0}
h2{font-size:15px;margin:0}
.meta{color:var(--ink2);margin:.3em 0 0;font-size:12.5px}
.hright{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#theme{background:var(--surface);border:1px solid var(--border);color:var(--ink2);
  border-radius:7px;padding:5px 10px;cursor:pointer;font:inherit;font-size:12.5px}
#theme:hover{background:var(--hover)}
.chainbadge{font-size:12px;padding:3px 9px;border-radius:99px;border:1px solid var(--border);
  background:var(--surface);color:var(--ink2);white-space:nowrap}
.chainbadge.ok{border-color:rgba(12,163,12,.4)}
.chainbadge.bad{background:var(--badbg);border-color:var(--bad);color:var(--ink)}
/* KPI row — stat tiles */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;
  margin-bottom:14px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:11px;
  padding:13px 15px 12px}
.tlabel{font-size:12px;color:var(--ink2)}
.tvalue{font-size:27px;font-weight:600;margin-top:2px}
.tvalue .den{font-size:15px;font-weight:400;color:var(--muted)}
.tsub{font-size:11.5px;color:var(--muted);margin-top:5px}
.meter{height:4px;border-radius:2px;background:var(--track);margin-top:9px;overflow:hidden}
.meter .fill{height:100%;border-radius:2px;background:var(--accent)}
/* cards */
.card{background:var(--surface);border:1px solid var(--border);border-radius:11px;
  padding:14px 16px;margin-bottom:14px}
.cardhead{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
  flex-wrap:wrap;margin-bottom:8px}
.legend{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.legendnote{font-size:11px;color:var(--muted);margin-left:6px}
.empty{color:var(--muted);font-size:13px;padding:12px 2px}
.cycwarn{background:var(--warnbg);border:1px solid var(--warn);border-radius:7px;
  padding:6px 10px;font-size:12.5px}
/* chips (status = dot + glyph/word, never color alone) */
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--ink2);
  border-radius:99px;padding:2px 9px;background:var(--mutbg);white-space:nowrap}
.chip .dot{width:8px;height:8px;border-radius:50%;background:var(--muted);
  box-shadow:0 0 0 2px var(--surface)}
.chip.ok{background:var(--okbg)}.chip.ok .dot{background:var(--ok)}
.chip.warn{background:var(--warnbg)}.chip.warn .dot{background:var(--warn)}
.chip.bad{background:var(--badbg)}.chip.bad .dot{background:var(--bad)}
/* DAG */
.dagwrap{overflow-x:auto;padding:4px 0;scrollbar-color:var(--baseline) transparent;scrollbar-width:thin}
.dag .edge{fill:none;stroke:var(--baseline);stroke-width:1.25}
.dag .arrhead{fill:var(--baseline)}
.dag .edge.hot{stroke:var(--accent);stroke-width:2}
.dag .node .card{fill:var(--surface);stroke:var(--border);rx:9}
.dag .node:hover .card,.dag .node:focus .card{stroke:var(--accent);stroke-width:1.5}
.dag .node{cursor:pointer;outline:none}
.dag .node.sel .card{stroke:var(--accent);stroke-width:2}
.dag .nid{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
  fill:var(--ink)}
.dag .nstat{font-size:10.5px;fill:var(--ink2)}
.dag .nbadge{font-size:10px;fill:var(--muted);font-family:ui-monospace,Menlo,monospace}
.dag .adv{fill:var(--accent)}
.dag .node.ok .accent{fill:var(--ok)}.dag .node.warn .accent{fill:var(--warn)}
.dag .node.bad .accent{fill:var(--bad)}.dag .node.mut .accent{fill:var(--muted)}
.nodedetail{border-top:1px solid var(--grid);margin-top:10px;padding-top:10px;font-size:13px}
.nodedetail h3{margin:.2em 0 .4em;font-size:13.5px}
.nodedetail h4{margin:.8em 0 .3em;font-size:12px;color:var(--ink2)}
.nodedetail ul{margin:.2em 0;padding-left:1.4em}
.nodedetail li{margin:.15em 0}
/* tabs + tables */
.tabs{display:flex;gap:4px;flex-wrap:wrap}
.tab{background:none;border:1px solid transparent;border-radius:7px;padding:5px 11px;
  font:inherit;font-size:13px;color:var(--ink2);cursor:pointer}
.tab:hover{background:var(--hover)}
.tab.on{background:var(--hover);border-color:var(--border);color:var(--ink);font-weight:600}
.panel{display:none}.panel.on{display:block}
.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0 10px}
input.search{background:var(--plane);border:1px solid var(--border);border-radius:7px;
  color:var(--ink);padding:6px 10px;font:inherit;font-size:13px;width:210px}
input.search:focus{outline:2px solid var(--accent);outline-offset:-1px}
.fchips{display:flex;gap:4px;flex-wrap:wrap}
.fchip{background:none;border:1px solid var(--border);border-radius:99px;color:var(--ink2);
  font:inherit;font-size:11.5px;padding:2px 9px;cursor:pointer}
.fchip span{color:var(--muted)}
.fchip:hover{background:var(--hover)}
.fchip.on{background:var(--hover);color:var(--ink);border-color:var(--baseline)}
.count{font-size:11.5px;color:var(--muted);margin-left:auto}
.tablewrap{overflow:auto;max-height:70vh;border:1px solid var(--grid);border-radius:8px;
  scrollbar-color:var(--baseline) transparent;scrollbar-width:thin}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
th{background:var(--surface);position:sticky;top:0;cursor:pointer;user-select:none;
  font-size:11.5px;color:var(--ink2);border-bottom:1px solid var(--baseline);z-index:1}
th:hover{color:var(--ink)}
th[data-sort=asc]::after{content:" ▲";font-size:9px;color:var(--muted)}
th[data-sort=desc]::after{content:" ▼";font-size:9px;color:var(--muted)}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--hover)}
tbody tr:focus{outline:2px solid var(--accent);outline-offset:-2px}
tbody td{font-variant-numeric:tabular-nums}
tr.detail,tr.detail:hover{background:var(--plane);cursor:default}
tr.detail pre{margin:0;padding:10px 12px;white-space:pre-wrap;word-break:break-word;
  font-size:11.5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink2)}
.wrap{max-width:26em;overflow-wrap:break-word}
footer{color:var(--muted);font-size:12px;margin-top:6px}
@media (max-width:700px){body{padding:12px}.wrap{max-width:16em}}
"""

_JS = """
(function(){
'use strict';
var data=JSON.parse(document.getElementById('dashboard-data').textContent);

/* theme toggle: auto -> light -> dark -> auto */
var themeBtn=document.getElementById('theme');
function themeState(){return localStorage.getItem('chandra-theme')||'auto';}
function applyTheme(t){
  if(t==='light'||t==='dark'){document.documentElement.dataset.theme=t;}
  else{delete document.documentElement.dataset.theme;}
  themeBtn.textContent='◐ '+t;
}
themeBtn.addEventListener('click',function(){
  var next={auto:'light',light:'dark',dark:'auto'}[themeState()];
  if(next==='auto')localStorage.removeItem('chandra-theme');
  else localStorage.setItem('chandra-theme',next);
  applyTheme(next);
});
applyTheme(themeState());

/* tabs */
var tabs=Array.prototype.slice.call(document.querySelectorAll('.tab'));
tabs.forEach(function(b){b.addEventListener('click',function(){
  tabs.forEach(function(x){x.classList.toggle('on',x===b);});
  document.querySelectorAll('.panel').forEach(function(p){
    p.classList.toggle('on',p.dataset.panel===b.dataset.tab);});
});});

/* per-panel search + status filter + count + sort + row detail */
document.querySelectorAll('.panel').forEach(function(panel){
  var table=panel.querySelector('table');if(!table)return;
  var tbody=table.tBodies[0],search=panel.querySelector('.search'),
      countEl=panel.querySelector('.count'),filter='';
  var rows=Array.prototype.slice.call(tbody.rows).filter(function(r){
    return !r.classList.contains('detail');});
  function refresh(){
    var q=(search.value||'').toLowerCase(),shown=0;
    rows.forEach(function(r){
      var okQ=!q||r.textContent.toLowerCase().indexOf(q)>=0;
      var okF=!filter||r.dataset.status===filter;
      var on=okQ&&okF;r.style.display=on?'':'none';if(on)shown++;
      var det=r.nextElementSibling;
      if(det&&det.classList.contains('detail'))det.style.display=on?det.dataset.open==='1'?'':'none':'none';
    });
    countEl.textContent=shown+' of '+rows.length+' rows';
  }
  search.addEventListener('input',refresh);
  panel.querySelectorAll('.fchip').forEach(function(c){c.addEventListener('click',function(){
    filter=c.dataset.f;
    panel.querySelectorAll('.fchip').forEach(function(x){x.classList.toggle('on',x===c);});
    refresh();
  });});
  Array.prototype.forEach.call(table.tHead.rows[0].cells,function(th,i){
    th.addEventListener('click',function(){
      var asc=th.dataset.sort!=='asc';
      rows.sort(function(a,b){
        var av=a.cells[i].textContent.trim(),bv=b.cells[i].textContent.trim();
        var an=parseFloat(av),bn=parseFloat(bv);
        if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
        return asc?av.localeCompare(bv):bv.localeCompare(av);
      });
      rows.forEach(function(r){
        var det=r.nextElementSibling&&r.nextElementSibling.classList.contains('detail')
          ?r.nextElementSibling:null;
        tbody.appendChild(r);if(det)tbody.appendChild(det);
      });
      Array.prototype.forEach.call(table.tHead.rows[0].cells,function(x){
        x.removeAttribute('data-sort');});
      th.dataset.sort=asc?'asc':'desc';
    });
  });
  function toggleDetail(r){
    var det=r.nextElementSibling;
    if(det&&det.classList.contains('detail')){
      var open=det.dataset.open==='1';det.dataset.open=open?'0':'1';
      det.style.display=open?'none':'';return;
    }
    det=document.createElement('tr');det.className='detail';det.dataset.open='1';
    var td=document.createElement('td');td.colSpan=r.cells.length;
    var pre=document.createElement('pre');
    pre.textContent=JSON.stringify(data[table.dataset.src][+r.dataset.i],null,2);
    td.appendChild(pre);det.appendChild(td);
    r.parentNode.insertBefore(det,r.nextSibling);
  }
  rows.forEach(function(r){
    r.addEventListener('click',function(){toggleDetail(r);});
    r.addEventListener('keydown',function(e){
      if(e.key==='Enter'||e.key===' '){e.preventDefault();toggleDetail(r);}});
  });
  refresh();
});

/* DAG: hover lights the node's edges; click/Enter opens the linked detail */
var detail=document.getElementById('nodedetail');
function addSection(root,title,items){
  if(!items.length)return;
  var h=document.createElement('h4');h.textContent=title;root.appendChild(h);
  var ul=document.createElement('ul');
  items.forEach(function(t){var li=document.createElement('li');li.textContent=t;ul.appendChild(li);});
  root.appendChild(ul);
}
function trialText(t){
  return '#'+(t.iteration||'?')+' '+(t.pass_fail||'')+
    (t.failure_mode?' ['+t.failure_mode+']':'')+' — '+(t.change_summary||'');
}
function showNode(id){
  detail.hidden=false;detail.textContent='';
  var h=document.createElement('h3');h.textContent=id;detail.appendChild(h);
  var hist=data.nodes_hist.filter(function(n){return n.node_id===id;});
  addSection(detail,'knowledge history ('+hist.length+')',hist.map(function(n){
    return (n.timestamp||'')+' — '+(n.status||'')+(n.summary?' — '+n.summary:'');}));
  addSection(detail,'trials',data.trials.filter(function(t){return t.node_id===id;})
    .map(trialText));
  addSection(detail,'results citing this node',data.results.filter(function(r){
    var ids=(r.node_ids||[]).concat(r.dependencies||[]);
    return ids.indexOf(id)>=0;}).map(function(r){
      return r.result_id+' ('+r.status+') — '+(r.name||r.claim||'');}));
  addSection(detail,'claims / obligations on this node',data.claims.filter(function(c){
    return (c.node_ids||[]).indexOf(id)>=0;}).map(function(c){
      return c.entry_id+' ('+c.kind+', '+c.status+') — '+(c.statement||'');}));
  if(detail.childElementCount===1){
    var p=document.createElement('p');p.textContent='No linked rows beyond the node itself.';
    detail.appendChild(p);
  }
  detail.scrollIntoView({behavior:'smooth',block:'nearest'});
}
var edges=Array.prototype.slice.call(document.querySelectorAll('.dag .edge'));
document.querySelectorAll('.dag .node').forEach(function(g){
  var id=g.dataset.node;
  function hot(on){edges.forEach(function(e){
    if(e.dataset.a===id||e.dataset.b===id)e.classList.toggle('hot',on);});}
  g.addEventListener('mouseenter',function(){hot(true);});
  g.addEventListener('mouseleave',function(){hot(false);});
  g.addEventListener('focus',function(){hot(true);});
  g.addEventListener('blur',function(){hot(false);});
  g.addEventListener('click',function(){
    document.querySelectorAll('.dag .node.sel').forEach(function(x){x.classList.remove('sel');});
    g.classList.add('sel');showNode(id);});
  g.addEventListener('keydown',function(e){
    if(e.key==='Enter'||e.key===' '){e.preventDefault();g.dispatchEvent(new Event('click'));}});
});
})();
"""


# --- render + CLI ----------------------------------------------------------------

def render(paper: str, *, repo_root: str | Path | None = None,
           output_path: str | Path | None = None,
           latest_only: bool = True) -> Path:
    d = collect(paper, repo_root, latest_only=latest_only)
    root = d["root"]
    out = (Path(output_path) if output_path
           else root / "results" / "views" / "dashboard" / f"paper_{paper}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(d), encoding="utf-8")
    return out


def _default_paper(repo_root: Path) -> str | None:
    p = repo_root / "mission.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("paper")
        except json.JSONDecodeError:
            return None
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render the per-paper mission dashboard HTML")
    r.add_argument("--paper", help="paper id (default: mission.json's paper)")
    r.add_argument("--repo-root", default=None)
    r.add_argument("--out", default=None, help="custom output path")
    r.add_argument("--full-history", action="store_true",
                   help="tables show every append, not just the latest row per id")
    args = ap.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root else Path.cwd()
    paper = args.paper or _default_paper(root)
    if not paper:
        ap.error("--paper is required (or set \"paper\" in mission.json)")
    out = render(paper, repo_root=root, output_path=args.out,
                 latest_only=not args.full_history)
    print(json.dumps({"rendered": True, "paper": paper, "path": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
