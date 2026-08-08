"""result_database - append-only per-paper admitted/classified result log.

Canonical schema-as-code for stage 4 — the ledger IS the result log; the
markdown views (`results.md`, the RESEARCH_STATE accepted-results table) are
GENERATED from it via `render-md` / `render-state`, never hand-authored.
`append` runs the executable admission gate (_common/ledgers/admission.py):
verification commands are executed, evidence files content-hashed, and
::-namespaced dependencies resolved before a row is admitted.

USAGE
    python _common/result_database.py schema
    python _common/result_database.py describe-fields
    echo '{...row JSON...}' | python _common/result_database.py append
    python _common/result_database.py query --paper P [--status S] [--result-id R]
    python _common/result_database.py regenerate-summary <paper-dir>
    python _common/result_database.py render-html --paper P
    python _common/result_database.py render-md --paper P [--out results.md]
    python _common/result_database.py render-state --paper P

Rows are append-only. To correct a result, append a new row with the same
`result_id`; latest append wins for the current view, while history remains in
`results.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from _common.ledgers import admission as adm
    from _common.ledgers import ledger_common as lc
else:
    from . import admission as adm
    from . import ledger_common as lc

STATUSES = (
    "checked", "conditional", "approximate", "empirical", "conjectural",
    "refuted", "unchecked", "existence_only",
)

# Statuses that count as explicit result-log progress for reporting.
# `unchecked` is preserved for reporting, but does not keep a loop alive.
PROGRESS_STATUSES = tuple(s for s in STATUSES if s != "unchecked")

# Statuses the LOOP GATE counts as verified forward motion. `refuted` and
# `conjectural` remain report-visible above, but appending them must not
# reset the no-progress circuit breaker (a clean defeat vector otherwise).
GATE_PROGRESS_STATUSES = tuple(
    s for s in STATUSES if s not in ("unchecked", "refuted", "conjectural"))

EVIDENCE_TYPES = (
    "exact_proof", "symbolic_derivation", "controlled_approximation",
    "dimensional_consistency", "numerical_simulation", "empirical_measurement",
    "statistical_inference", "literature_grounding", "counterexample",
    "conjecture", "unchecked_external_step", "existence_only",
)

VERDICTS = ("pass", "fail", "classified", "rejected", "partial")

REQUIRED_FIELDS = {
    "paper", "result_id", "name", "working_context", "claim",
    "evidence_type", "evidence", "verifier_result", "dependencies",
    "assumptions", "status", "provenance", "open_obligations",
}
AUTO_FILLED = {"timestamp", "git_commit"}

FIELD_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "timestamp":        ("ISO-8601 UTC", "auto-filled"),
    "git_commit":       ("string", "short SHA, auto-filled"),
    "paper":            ("string", "arxiv-XXXX.XXXXX"),
    "result_id":        ("string", "stable accepted/classified result id"),
    "name":             ("string", "short human-readable result name"),
    "working_context":  ("object/string", "model, regime, units, frames, task constraints"),
    "claim":            ("string", "statement being advanced or classified"),
    "evidence_type":    ("enum", "query with schema"),
    "evidence":         ("object/string", "verifier output, certificate, artifact path, or citation bundle"),
    "verifier_result":  ("object", "{verdict, command?, metric?, output?}"),
    "dependencies":     ("array", "result ids, source ids, code paths, theorem ids"),
    "assumptions":      ("array", "explicit assumptions this result depends on"),
    "status":           ("enum", "checked / conditional / approximate / empirical / conjectural / refuted / unchecked / existence_only"),
    "provenance":       ("object/string", "source row, stage, agent, commit, or retrieval provenance"),
    "open_obligations": ("array", "remaining obligations; [] for checked results"),
    "task_id":          ("string", "implementation task id"),
    "node_ids":         ("array", "logic.md node ids covered by this result"),
    "iteration":        ("int", "Ralph loop counter"),
    "source_ids":       ("array", "source-library ids used directly"),
    "notes":            ("string", "free text; cite superseded prior rows"),
    # executable admission (see _common/ledgers/admission.py)
    "verification":     ("object", "{command, timeout_s?, cwd?} — RUN at append; exit 0 required; outcome recorded in verifier_result.execution"),
    "evidence_sha256":  ("string", "auto-filled content hash when evidence names an existing file"),
    "admission_flags":  ("array", "auto-filled bypass record (skip_exec / allow_missing_deps) — visible, never silent"),
}


def utc_now_iso() -> str:
    return lc.utc_now_iso(timespec="microseconds")


def validate(row: dict[str, Any]) -> None:
    missing = REQUIRED_FIELDS - row.keys()
    if missing:
        raise ValueError(f"missing required fields: {sorted(missing)}")
    if row["status"] not in STATUSES:
        raise ValueError(f"status={row['status']!r} not in {STATUSES}")
    if row["evidence_type"] not in EVIDENCE_TYPES:
        raise ValueError(f"evidence_type={row['evidence_type']!r} not in {EVIDENCE_TYPES}")

    vr = row["verifier_result"]
    if not isinstance(vr, dict):
        raise ValueError(f"verifier_result must be an object; got {type(vr).__name__}")
    if vr.get("verdict") not in VERDICTS:
        raise ValueError(f"verifier_result.verdict={vr.get('verdict')!r} not in {VERDICTS}")

    for field in ("dependencies", "assumptions", "open_obligations"):
        if not isinstance(row[field], list):
            raise ValueError(f"{field} must be a list; got {type(row[field]).__name__}")
    if "node_ids" in row and not isinstance(row["node_ids"], list):
        raise ValueError(f"node_ids must be a list; got {type(row['node_ids']).__name__}")
    if "source_ids" in row and not isinstance(row["source_ids"], list):
        raise ValueError(f"source_ids must be a list; got {type(row['source_ids']).__name__}")
    if row["status"] == "checked" and row["open_obligations"]:
        raise ValueError("status='checked' requires open_obligations=[]")


def append_row(row: dict[str, Any], *, repo_root: str | Path | None = None,
               skip_exec: bool = False, allow_missing_deps: bool = False) -> dict[str, Any]:
    root = Path(repo_root) if repo_root else Path.cwd()
    row.setdefault("timestamp", utc_now_iso())
    row.setdefault("git_commit", lc.git_commit_short(root))
    validate(row)
    adm.check_result_admission(row, root, skip_exec=skip_exec,
                               allow_missing_deps=allow_missing_deps)

    db_dir = lc.db_dir(root, "result", row["paper"])
    db_dir.mkdir(parents=True, exist_ok=True)
    lc.chain_append(db_dir, "results.jsonl", row)
    regenerate_summary(db_dir)
    return row


def _append_row_nosummary(row: dict[str, Any], *, repo_root: str | Path | None = None,
                          skip_exec: bool = False, allow_missing_deps: bool = False) -> dict[str, Any]:
    root = Path(repo_root) if repo_root else Path.cwd()
    row.setdefault("timestamp", utc_now_iso())
    row.setdefault("git_commit", lc.git_commit_short(root))
    validate(row)
    adm.check_result_admission(row, root, skip_exec=skip_exec,
                               allow_missing_deps=allow_missing_deps)
    db_dir = lc.db_dir(root, "result", row["paper"])
    db_dir.mkdir(parents=True, exist_ok=True)
    lc.chain_append(db_dir, "results.jsonl", row)
    return row


def append_batch(rows: list[dict[str, Any]], *, repo_root: str | Path | None = None,
                 skip_exec: bool = False, allow_missing_deps: bool = False) -> dict[str, Any]:
    """Packet-flush append: sequentially gate + append a list of rows,
    regenerating summary.csv ONCE at the end. Append-only semantics: a row
    that fails the gate STOPS the batch there; earlier rows are already in
    (report shows appended count + the failing row)."""
    if not isinstance(rows, list):
        raise ValueError("rows must be a JSON array of result rows")
    appended = 0
    papers: set[str] = set()
    try:
        for row in rows:
            written = _append_row_nosummary(dict(row), repo_root=repo_root,
                                            skip_exec=skip_exec,
                                            allow_missing_deps=allow_missing_deps)
            papers.add(written["paper"])
            appended += 1
    finally:
        root = Path(repo_root) if repo_root else Path.cwd()
        for paper in papers:
            regenerate_summary(lc.db_dir(root, "result", paper))
    return {"appended": appended, "of": len(rows), "papers": sorted(papers)}


def read_entries(repo_root: str | Path | None, paper: str) -> list[dict[str, Any]]:
    return lc.read_jsonl(repo_root, "result", paper, "results.jsonl")


def latest_per_result(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_result: dict[str, dict[str, Any]] = {}
    for r in rows:
        rid = r.get("result_id")
        if rid is not None:
            by_result[rid] = r
    return list(by_result.values())


def query(paper: str, *,
          status: str | None = None,
          result_id: str | None = None,
          task_id: str | None = None,
          latest_only: bool = True,
          repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    rows = read_entries(repo_root, paper)
    if latest_only:
        rows = latest_per_result(rows)
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if result_id is not None:
        rows = [r for r in rows if r.get("result_id") == result_id]
    if task_id is not None:
        rows = [r for r in rows if r.get("task_id") == task_id]
    return rows


_SUMMARY_ORDER = [
    "timestamp", "paper", "result_id", "name", "task_id", "iteration",
    "git_commit", "status", "evidence_type", "claim",
    "verifier_result.verdict", "evidence", "dependencies", "assumptions",
    "open_obligations", "provenance",
]


def regenerate_summary(db_dir: Path) -> None:
    lc.regenerate_summary(db_dir, "results.jsonl", _SUMMARY_ORDER)


_STATUS_CSS = """tr.checked{background:#effff0}
tr.conditional{background:#fffae0}
tr.approximate{background:#fff6e8}
tr.empirical{background:#eef6ff}
tr.conjectural{background:#f0edff}
tr.refuted{background:#ffe2e2}
tr.unchecked{background:#f2f2f2;color:#666}
tr.existence_only{background:#e8f7f5}
"""

_HTML_CSS = lc.ledger_css(_STATUS_CSS)
_HTML_JS = lc.LEDGER_JS
_esc = lc.esc_cell


def render_html(paper: str, *, repo_root: str | Path | None = None,
                output_path: str | Path | None = None,
                latest_only: bool = True) -> Path:
    rows = query(paper, latest_only=latest_only, repo_root=repo_root)
    if not rows:
        raise ValueError(f"no entries for paper={paper!r} in result-database/")
    root = Path(repo_root) if repo_root else Path.cwd()
    out = Path(output_path) if output_path else root / "results" / "views" / "result" / f"paper_{paper}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_build_result_html(paper, rows, latest_only=latest_only), encoding="utf-8")
    return out


def _build_result_html(paper: str, rows: list[dict[str, Any]], *, latest_only: bool) -> str:
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
    progress = sum(by_status.get(s, 0) for s in PROGRESS_STATUSES)
    open_obs = sum(len(r.get("open_obligations") or []) for r in rows)
    summary = "<div class='summary'>" + "".join([
        f"<span><strong>results</strong> {len(rows)}</span>",
        f"<span><strong>progress-classified</strong> {progress}</span>",
        f"<span><strong>open obligations</strong> {open_obs}</span>",
        *[f"<span><strong>{k}</strong> {v}</span>" for k, v in sorted(by_status.items())],
    ]) + "</div>"
    cols = ("timestamp", "result_id", "status", "evidence_type", "name",
            "claim", "verdict", "evidence", "open_obligations")
    head = "".join(f"<th>{c}</th>" for c in cols)
    body_rows: list[str] = []
    for r in rows:
        cls = r.get("status", "")
        cells = [
            _esc(r.get("timestamp")),
            f'<span class="cell-mono">{_esc(r.get("result_id"))}</span>',
            _esc(r.get("status")),
            _esc(r.get("evidence_type")),
            f'<div class="cell-wrap">{_esc(r.get("name"))}</div>',
            f'<div class="cell-wrap">{_esc(r.get("claim"))}</div>',
            _esc((r.get("verifier_result") or {}).get("verdict")),
            f'<div class="cell-wrap">{_esc(r.get("evidence"))}</div>',
            f'<div class="cell-wrap">{_esc(r.get("open_obligations"))}</div>',
        ]
        body_rows.append(f"<tr class='{cls}'>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    mode_note = "latest row per result_id" if latest_only else "full append history"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>result_database - paper_{_esc(paper)}</title>
<style>{_HTML_CSS}</style></head>
<body>
<h1>Result Database - <span class="cell-mono">paper_{_esc(paper)}</span></h1>
<p class="subtitle">Append-only admitted/classified result ledger. View: <strong>{mode_note}</strong>. Schema: <span class="cell-mono">python _common/result_database.py describe-fields</span>.</p>
{summary}
<div class="controls"><input id="search" class="search" type="text" placeholder="filter rows (substring match across all columns)..."></div>
<table id="rows"><thead><tr>{head}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>
<script>{_HTML_JS}</script>
</body></html>
"""


# --- generated markdown views (the ledger is canonical; prose is rendered) ----

def _md_cell(v: Any) -> str:
    if v is None or v == [] or v == "":
        return "—"
    if isinstance(v, (list, tuple)):
        v = "; ".join(str(x) for x in v)
    elif isinstance(v, dict):
        v = json.dumps(v, ensure_ascii=False)
    return str(v).replace("|", "\\|").replace("\n", " ")


def _generated_header(paper: str, subcommand: str) -> str:
    return (f"<!-- GENERATED by `python _common/result_database.py {subcommand} --paper {paper}` "
            f"— DO NOT EDIT BY HAND; result-database/paper_{paper}/results.jsonl is canonical. "
            "Correct by appending a new row with the same result_id, then re-render. -->")


def render_md(paper: str, *, repo_root: str | Path | None = None,
              latest_only: bool = True) -> str:
    """The stage-4 `results.md` log as a generated view over the ledger."""
    rows = query(paper, latest_only=latest_only, repo_root=repo_root)
    by_status: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_status.setdefault(r.get("status", "?"), []).append(r)
    mode = "latest row per result_id" if latest_only else "full append history"
    lines = [
        _generated_header(paper, "render-md"),
        "",
        f"# Results — paper_{paper}",
        "",
        f"View: {mode}. {len(rows)} results; "
        + ", ".join(f"{len(by_status.get(s, []))} {s}" for s in STATUSES if s in by_status)
        + ".",
    ]
    cols = ("result_id", "name", "claim", "evidence_type", "verdict",
            "evidence", "dependencies", "assumptions", "open_obligations")
    for status in STATUSES:
        if status not in by_status:
            continue
        lines += ["", f"## {status} ({len(by_status[status])})", "",
                  "| " + " | ".join(cols) + " |",
                  "|" + "---|" * len(cols)]
        for r in by_status[status]:
            ev = r.get("evidence")
            if "evidence_sha256" in r:
                ev = f"{_md_cell(ev)} `sha256:{r['evidence_sha256'][:12]}`"
            cells = (r.get("result_id"), r.get("name"), r.get("claim"),
                     r.get("evidence_type"), (r.get("verifier_result") or {}).get("verdict"),
                     ev, r.get("dependencies"), r.get("assumptions"), r.get("open_obligations"))
            lines.append("| " + " | ".join(_md_cell(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def render_state(paper: str, *, repo_root: str | Path | None = None) -> str:
    """The `${RESEARCH_STATE}` Accepted Results Log table as a generated block
    (columns match the scaffold in notes/multi_timescale_tracking_template.md).
    Embed between the BEGIN/END markers; regenerate instead of hand-editing."""
    rows = query(paper, latest_only=True, repo_root=repo_root)
    begin = (f"<!-- BEGIN GENERATED: accepted-results paper_{paper} "
             f"(python _common/result_database.py render-state --paper {paper}) — DO NOT EDIT BY HAND -->")
    lines = [begin,
             "| Claim | Evidence type | Evidence / verifier | Assumptions / deps | Status | Open obligations |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        verdict = (r.get("verifier_result") or {}).get("verdict")
        ev = f"{_md_cell(r.get('evidence'))} ({verdict})" if verdict else _md_cell(r.get("evidence"))
        deps = (r.get("assumptions") or []) + (r.get("dependencies") or [])
        lines.append("| " + " | ".join([
            f"`{_md_cell(r.get('result_id'))}` {_md_cell(r.get('claim'))}",
            _md_cell(r.get("evidence_type")), ev, _md_cell(deps),
            _md_cell(r.get("status")), _md_cell(r.get("open_obligations")),
        ]) + " |")
    lines.append(f"<!-- END GENERATED: accepted-results paper_{paper} -->")
    return "\n".join(lines) + "\n"


SCHEMA_SUMMARY = """result_database - compact reference

REQUIRED fields:  {required}
AUTO-FILLED:      {auto}

enums:
  status        = {statuses}
  progress      = {progress_statuses}
  evidence_type = {evidence_types}
  verdict       = {verdicts}

per-field meanings:
  python _common/result_database.py describe-fields
"""


def _schema_text() -> str:
    return SCHEMA_SUMMARY.format(
        required=sorted(REQUIRED_FIELDS),
        auto=sorted(AUTO_FILLED),
        statuses=STATUSES,
        progress_statuses=PROGRESS_STATUSES,
        evidence_types=EVIDENCE_TYPES,
        verdicts=VERDICTS,
    )


def _describe_fields() -> str:
    width_n = max(len(n) for n in FIELD_DESCRIPTIONS)
    width_t = max(len(t) for t, _ in FIELD_DESCRIPTIONS.values())
    lines = []
    for n, (t, m) in FIELD_DESCRIPTIONS.items():
        lines.append(f"  {n:<{width_n}}  {t:<{width_t}}  {m}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="result_database")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schema", help="print compact schema summary")
    sub.add_parser("describe-fields", help="per-field semantics")

    ap_app = sub.add_parser("append", help="validate + run the executable admission gate + append a JSON row from stdin or file")
    ap_app.add_argument("--row-file", type=Path, help="read row JSON from file (default: stdin)")
    ap_app.add_argument("--repo-root", type=Path, default=None)
    ap_app.add_argument("--skip-exec", action="store_true",
                        help="do not run verification.command (recorded in admission_flags)")
    ap_app.add_argument("--allow-missing-deps", action="store_true",
                        help="admit despite unresolvable ::-namespaced dependencies (recorded in admission_flags)")

    ab = sub.add_parser("append-batch", help="packet flush: gate + append a JSON array; summary regenerated once")
    ab.add_argument("--rows-file", type=Path, help="JSON array of rows (default: stdin)")
    ab.add_argument("--repo-root", type=Path, default=None)
    ab.add_argument("--skip-exec", action="store_true")
    ab.add_argument("--allow-missing-deps", action="store_true")

    qy = sub.add_parser("query", help="filter rows; default returns latest row per result_id")
    qy.add_argument("--paper", required=True)
    qy.add_argument("--status", choices=STATUSES, default=None)
    qy.add_argument("--result-id", default=None, dest="result_id")
    qy.add_argument("--task-id", default=None, dest="task_id")
    qy.add_argument("--with-history", action="store_true")
    qy.add_argument("--repo-root", type=Path, default=None)

    rs = sub.add_parser("regenerate-summary", help="regenerate summary.csv for a paper dir")
    rs.add_argument("paper_dir", type=Path)

    rh = sub.add_parser("render-html", help="render a self-contained HTML result ledger view")
    rh.add_argument("--paper", required=True)
    rh.add_argument("--output", type=Path, default=None)
    rh.add_argument("--repo-root", type=Path, default=None)
    rh.add_argument("--with-history", action="store_true")

    rm = sub.add_parser("render-md", help="render the generated results.md view (ledger is canonical)")
    rm.add_argument("--paper", required=True)
    rm.add_argument("--out", type=Path, default=None, help="write to file (default: stdout)")
    rm.add_argument("--repo-root", type=Path, default=None)
    rm.add_argument("--with-history", action="store_true")

    rst = sub.add_parser("render-state", help="render the RESEARCH_STATE accepted-results generated block")
    rst.add_argument("--paper", required=True)
    rst.add_argument("--repo-root", type=Path, default=None)

    args = ap.parse_args(argv)
    if args.cmd == "schema":
        sys.stdout.write(_schema_text())
        return 0
    if args.cmd == "describe-fields":
        sys.stdout.write(_describe_fields())
        return 0
    if args.cmd == "append":
        raw = args.row_file.read_text() if args.row_file else sys.stdin.read()
        written = append_row(json.loads(raw), repo_root=args.repo_root,
                             skip_exec=args.skip_exec,
                             allow_missing_deps=args.allow_missing_deps)
        out = {"appended": True, "paper": written["paper"],
               "result_id": written["result_id"],
               "status": written["status"],
               "timestamp": written["timestamp"]}
        for k in ("evidence_sha256", "admission_flags"):
            if k in written:
                out[k] = written[k]
        if "execution" in written.get("verifier_result", {}):
            out["verified_exit_code"] = written["verifier_result"]["execution"]["exit_code"]
        print(json.dumps(out))
        return 0
    if args.cmd == "append-batch":
        raw = args.rows_file.read_text() if args.rows_file else sys.stdin.read()
        print(json.dumps(append_batch(json.loads(raw), repo_root=args.repo_root,
                                      skip_exec=args.skip_exec,
                                      allow_missing_deps=args.allow_missing_deps)))
        return 0
    if args.cmd == "query":
        rows = query(args.paper, status=args.status, result_id=args.result_id,
                     task_id=args.task_id, latest_only=not args.with_history,
                     repo_root=args.repo_root)
        print(json.dumps(rows, indent=2))
        return 0
    if args.cmd == "regenerate-summary":
        regenerate_summary(args.paper_dir)
        return 0
    if args.cmd == "render-html":
        out = render_html(args.paper, repo_root=args.repo_root, output_path=args.output,
                          latest_only=not args.with_history)
        print(json.dumps({"rendered": True, "paper": args.paper, "path": str(out)}))
        return 0
    if args.cmd == "render-md":
        text = render_md(args.paper, repo_root=args.repo_root,
                         latest_only=not args.with_history)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
            print(json.dumps({"rendered": True, "paper": args.paper, "path": str(args.out)}))
        else:
            sys.stdout.write(text)
        return 0
    if args.cmd == "render-state":
        sys.stdout.write(render_state(args.paper, repo_root=args.repo_root))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
