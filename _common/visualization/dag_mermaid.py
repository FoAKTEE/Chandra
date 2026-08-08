#!/usr/bin/env python3
"""dag_mermaid — render the equation/logic DAG (knowledge ledger) as Mermaid.

Promoted from a mission's local `dagtools/` into shared infra (the auto-written
tool-promotion path; see `_common/contracts/progress_principles.md`). The
methodology standard: **every logic DAG is written as Mermaid**, a project keeps
**one giant merged DAG**, and **the error + knowledge ledgers are doubly linked
to that DAG** — each trial / converged record attaches UNDER a DAG node (a
numbered `node_seq` list, 1,2,3…) instead of minting new nodes. The merged DAG is
then the project-progress dashboard: each node carries `k<N>` knowledge records
and `t<N>✗<F>` trials.

Reads `knowledge-database/paper_<P>/nodes.jsonl` + `error-database/paper_<P>/
trials.jsonl` (latest non-amended row per node for the skeleton) under
`--repo-root` (default: cwd). Node ids follow the global convention
`PAPER::nodename`, so a single merged flowchart is unambiguous and a shared
derivation can live under a synthetic paper (e.g. `_shared`).

Modes:
  render     --paper P [--out F]            one paper's flowchart (with badges)
  merge      [--papers ...] [--out F]       one giant flowchart, subgraph per
                                            paper, cross-paper edges; auto-discovers
                                            every paper when --papers is omitted
  node-view  --paper P --node-id N          doubly-linked view of ONE node: its
                                            knowledge list + error list (JSON)
  progress   [--papers ...]                 per-node progress readout across the
                                            giant DAG (JSON): status, k/t counts
  duplicates [--papers ...]                 candidate cross-paper duplicate nodes
                                            (seeds the reformulation pass)

`--out -` (or no --out for render/merge) writes the Mermaid markdown to stdout.
Status -> class: solid/preliminary/hypothesis (● exist), blocking/future (○ todo).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from _common.ledgers import knowledge_database as kdb
    from _common.ledgers import error_database as edb
    from _common.ledgers import ledger_common as lc
else:
    from ..ledgers import knowledge_database as kdb
    from ..ledgers import error_database as edb
    from ..ledgers import ledger_common as lc

_STATUS_GLYPH = {"solid": "●", "preliminary": "◐", "hypothesis": "○",
                 "blocking": "✗", "future": "□", "amended": "~"}
_LEGEND = ("● solid · ◐ preliminary · ○ hypothesis · ✗ blocking · □ future · "
           "△ concept-advance. Node badge `k<N>` = knowledge records under the node, "
           "`t<N>✗<F>` = trials (F failed). Dashed edge = predecessor outside scope.")
_CLASSDEFS = """  classDef solid fill:#e6ffed,stroke:#28a745,color:#000;
  classDef preliminary fill:#fff8e1,stroke:#d4a017,color:#000;
  classDef hypothesis fill:#e7f0ff,stroke:#4977c7,color:#000;
  classDef blocking fill:#ffe3e3,stroke:#d33,color:#000;
  classDef future fill:#f2f2f2,stroke:#999,color:#555;
  classDef amended fill:#f0f0f0,stroke:#aaa,color:#888;"""

_FAIL = ("fail", "crash", "partial")


def _safe(nid: str) -> str:
    return "n_" + re.sub(r"[^0-9A-Za-z]", "_", nid)


def _label(row: dict, badge: str = "") -> str:
    nid = row.get("node_id", "?")
    g = _STATUS_GLYPH.get(row.get("status", ""), "?")
    eqs = row.get("equation_labels") or []
    eqtxt = (" <br/><i>" + ", ".join(eqs[:4]) + ("…" if len(eqs) > 4 else "") + "</i>") if eqs else ""
    summ = (row.get("summary") or "").replace('"', "'").replace("\n", " ")
    if len(summ) > 60:
        summ = summ[:57] + "…"
    short = nid.split("::", 1)[-1]
    adv = " △" if row.get("concept_advance") else ""
    return f'{g} <b>{short}</b>{adv}{badge}<br/>{summ}{eqtxt}'


def _latest_rows(paper: str, repo_root) -> list[dict]:
    return kdb.query(paper, latest_only=True, repo_root=repo_root)


def discover_papers(repo_root) -> list[str]:
    """Every paper with a knowledge ledger under repo_root, sorted (canonical
    results/ledgers/knowledge/ plus the legacy knowledge-database/ layout)."""
    return sorted(paper for paper, _ in lc.iter_paper_dirs(repo_root, "knowledge"))


def _node_badges(paper: str, repo_root) -> dict[str, str]:
    """node_id -> ` · k<K> t<T>✗<F>`: the count of knowledge records and trials
    attached UNDER each node (the doubly-linked lists), for the DAG render."""
    kc = Counter(r.get("node_id") for r in kdb.read_entries(repo_root, paper))
    erows = edb.read_entries(repo_root, paper)
    tc = Counter(e.get("node_id") for e in erows if e.get("node_id"))
    fc = Counter(e.get("node_id") for e in erows if e.get("node_id") and e.get("pass_fail") in _FAIL)
    badges: dict[str, str] = {}
    for nid in (set(kc) | set(tc)) - {None}:
        parts = []
        if kc.get(nid):
            parts.append(f"k{kc[nid]}")
        if tc.get(nid):
            parts.append(f"t{tc[nid]}" + (f"✗{fc[nid]}" if fc[nid] else ""))
        if parts:
            badges[nid] = " · " + " ".join(parts)
    return badges


def _emit_nodes(rows: list[dict], badges: dict[str, str] | None = None, indent: str = "  ") -> list[str]:
    badges = badges or {}
    return [f'{indent}{_safe(r.get("node_id", "?"))}'
            f'["{_label(r, badges.get(r.get("node_id", ""), ""))}"]:::{r.get("status", "future")}'
            for r in rows]


def _emit_edges(rows: list[dict], known: set[str], indent: str = "  ") -> list[str]:
    out = []
    for r in rows:
        nid = r.get("node_id", "?")
        for p in (r.get("predecessors") or []):
            arrow = "-->" if p in known else "-.->"          # dashed if pred outside scope
            out.append(f"{indent}{_safe(p)} {arrow} {_safe(nid)}")
    return out


def render_single(paper: str, *, repo_root=None) -> str:
    rows = _latest_rows(paper, repo_root)
    if not rows:
        raise ValueError(f"no knowledge-database rows for paper={paper!r}")
    known = {r["node_id"] for r in rows}
    badges = _node_badges(paper, repo_root)
    lines = ["```mermaid", "flowchart TD"]
    lines += _emit_nodes(rows, badges)
    lines += _emit_edges(rows, known)
    lines += [_CLASSDEFS, "```"]
    return (f"# Equation DAG — paper_{paper}\n\n"
            f"{len(rows)} nodes. Legend: {_LEGEND}\n\n" + "\n".join(lines) + "\n")


def render_merge(papers: list[str], *, repo_root=None) -> str:
    all_rows = {p: _latest_rows(p, repo_root) for p in papers}
    known = {r["node_id"] for rows in all_rows.values() for r in rows}
    badges: dict[str, str] = {}
    for p in papers:
        badges.update(_node_badges(p, repo_root))          # PAPER::node ids don't collide
    total = sum(len(v) for v in all_rows.values())
    lines = ["```mermaid", "flowchart TD"]
    for p in papers:
        rows = all_rows[p]
        if not rows:
            continue
        lines.append(f'  subgraph {_safe(p)}_sg["paper {p}  ({len(rows)} nodes)"]')
        lines += _emit_nodes(rows, badges, indent="    ")
        lines.append("  end")
    merged_rows = [r for rows in all_rows.values() for r in rows]
    lines += _emit_edges(merged_rows, known)          # cross-paper edges solid (target in scope)
    lines += [_CLASSDEFS, "```"]
    return (f"# MERGED equation DAG — {', '.join(papers)}\n\n"
            f"One unified DAG across all source papers ({total} nodes). One subgraph per "
            f"paper; edges crossing subgraphs are shared/foundational dependencies. Collapse "
            f"identical cross-paper derivations into one node (see `duplicates`). Per-node "
            f"badges read project progress (see `progress`).\n"
            f"Legend: {_LEGEND}\n\n" + "\n".join(lines) + "\n")


def node_view(paper: str, node_id: str, *, repo_root=None) -> dict:
    """The doubly-linked view of one DAG node: the knowledge list and the error
    list that accrue UNDER it (each numbered by `node_seq`), plus latest status.
    The DAG node is the anchor; records attach to it, they do not become new nodes."""
    krows = kdb.read_entries(repo_root, paper)
    return {
        "paper": paper,
        "node_id": node_id,
        "status": (kdb.latest_status(krows, paper, node_id) or {}).get("status"),
        "knowledge": kdb.node_records(paper, node_id, repo_root=repo_root),
        "errors": edb.node_trials(paper, node_id, repo_root=repo_root),
    }


def node_progress(papers: list[str], *, repo_root=None) -> list[dict]:
    """Per-node progress for the giant DAG: knowledge-record count, trial counts
    (pass/fail), and latest status — the project-progress readout."""
    out: list[dict] = []
    for paper in papers:
        krows = kdb.read_entries(repo_root, paper)
        erows = edb.read_entries(repo_root, paper)
        latest = {r.get("node_id"): r for r in kdb.lc.latest_per_node(krows)}
        kcount = Counter(r.get("node_id") for r in krows)
        node_ids = sorted((set(latest) | {e.get("node_id") for e in erows if e.get("node_id")}) - {None})
        for nid in node_ids:
            trials = [e for e in erows if e.get("node_id") == nid]
            out.append({
                "paper": paper, "node_id": nid,
                "status": (latest.get(nid) or {}).get("status"),
                "n_knowledge": kcount.get(nid, 0),
                "n_trials": len(trials),
                "pass": sum(1 for e in trials if e.get("pass_fail") == "pass"),
                "fail": sum(1 for e in trials if e.get("pass_fail") in _FAIL),
            })
    return out


def _norm_summary(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z ]", " ", (s or "").lower())).strip()


def find_duplicates(papers: list[str], *, repo_root=None) -> list[dict]:
    """Candidate cross-paper duplicate derivations: nodes in >1 distinct paper that
    share an equation_label or normalize to the same summary. A heuristic seed for
    the strongest-math reformulation pass — NOT an automatic merge."""
    rows = [(p, r) for p in papers for r in _latest_rows(p, repo_root)]
    by_eq: dict[str, list[tuple[str, dict]]] = {}
    by_summary: dict[str, list[tuple[str, dict]]] = {}
    for paper, r in rows:
        for eq in (r.get("equation_labels") or []):
            by_eq.setdefault(eq, []).append((paper, r))
        ns = _norm_summary(r.get("summary", ""))
        if ns:
            by_summary.setdefault(ns, []).append((paper, r))

    clusters: list[dict] = []
    seen: set[frozenset] = set()
    for reason, index in (("shared_equation_label", by_eq), ("matching_summary", by_summary)):
        for key, hits in index.items():
            if len({p for p, _ in hits}) < 2:
                continue
            members = frozenset((p, r.get("node_id")) for p, r in hits)
            if members in seen:
                continue
            seen.add(members)
            clusters.append({
                "reason": reason, "key": key,
                "nodes": [{"paper": p, "node_id": r.get("node_id"),
                           "summary": r.get("summary")} for p, r in hits],
            })
    return clusters


def _resolve_out(out, body: str) -> None:
    if out is None or str(out) == "-":
        sys.stdout.write(body)
        return
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(str(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dag_mermaid")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("render", help="render one paper's DAG as Mermaid")
    rp.add_argument("--paper", required=True)
    rp.add_argument("--out", type=Path, default=None, help="output path ('-' or omit = stdout)")
    rp.add_argument("--repo-root", type=Path, default=None)

    mg = sub.add_parser("merge", help="render one giant merged DAG across papers")
    mg.add_argument("--papers", nargs="+", default=None,
                    help="paper ids (default: every paper under knowledge-database/)")
    mg.add_argument("--out", type=Path, default=None, help="output path ('-' or omit = stdout)")
    mg.add_argument("--repo-root", type=Path, default=None)

    nv = sub.add_parser("node-view", help="doubly-linked view of one node: its knowledge + error lists")
    nv.add_argument("--paper", required=True)
    nv.add_argument("--node-id", required=True, dest="node_id")
    nv.add_argument("--repo-root", type=Path, default=None)

    pg = sub.add_parser("progress", help="per-node progress readout across the giant DAG (JSON)")
    pg.add_argument("--papers", nargs="+", default=None)
    pg.add_argument("--repo-root", type=Path, default=None)

    dp = sub.add_parser("duplicates", help="candidate cross-paper duplicate nodes (JSON)")
    dp.add_argument("--papers", nargs="+", default=None)
    dp.add_argument("--repo-root", type=Path, default=None)

    args = ap.parse_args(argv)

    if args.cmd == "render":
        _resolve_out(args.out, render_single(args.paper, repo_root=args.repo_root))
        return 0
    if args.cmd == "node-view":
        print(json.dumps(node_view(args.paper, args.node_id, repo_root=args.repo_root),
                         indent=2, ensure_ascii=False))
        return 0
    papers = args.papers or discover_papers(args.repo_root)
    if not papers:
        print(json.dumps({"error": "no papers found under knowledge-database/"}))
        return 1
    if args.cmd == "merge":
        _resolve_out(args.out, render_merge(papers, repo_root=args.repo_root))
        return 0
    if args.cmd == "duplicates":
        print(json.dumps(find_duplicates(papers, repo_root=args.repo_root), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "progress":
        print(json.dumps(node_progress(papers, repo_root=args.repo_root), indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
