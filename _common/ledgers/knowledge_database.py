
"""knowledge_database — append-only per-paper log of converged nodes (★).

Canonical implementation. This module's docstring, constants, and `describe-*`
commands ARE the complete spec — there is no companion markdown.

The knowledge database is the ★ dual of the error database. The error
database (`_common/error_database.py`) records every TRIAL — including
failures. The knowledge database records every CONVERGED NODE — the
positive memory: equations reproduced, code blocks that work, concept
advances landed. The agent's question this answers:

    "Have I already proved / implemented this node, in this paper?"

vs. error_database's:

    "Did I already fail this trial?"

A row corresponds to one node in the consumer's `logic.md` DAG. The DAG
shape is captured via the `predecessors[]` field. Multiple rows accrue
UNDER one node (auto-numbered `node_seq` 1,2,3… — the doubly-linked list
under the DAG node, not new nodes); the latest non-amended row is the
node's current status. State markers
(`[SOLID]` / `[PRELIMINARY]` / `[HYPOTHESIS]` / `[BLOCKING]` / `[FUTURE]`)
are first-class fields, not prose; the figure's `●` (exist) / `○`
(not-exist) distinction is `status ∈ {solid, preliminary, hypothesis}`
vs. `status ∈ {blocking, future}` respectively.

USAGE
    python _common/knowledge_database.py schema                  # required/optional fields + enums
    python _common/knowledge_database.py describe-fields         # one-line meaning per field
    echo '{...row JSON...}' | python _common/knowledge_database.py append
    python _common/knowledge_database.py query --paper P [--status S] [--equation-label L]
    python _common/knowledge_database.py predecessors --paper P --node-id N
    python _common/knowledge_database.py regenerate-summary <paper-dir>

`append` auto-fills `timestamp` + `git_commit`, validates, writes to
`knowledge-database/paper_{paper}/nodes.jsonl`, and regenerates
`summary.csv`. Validation errors quote the allowed enum values back —
the agent self-corrects from the error message.

APPEND-ONLY DISCIPLINE
    * Never delete a row. To correct or demote, append a new row with
      status="amended" or the new status, citing the prior row's
      (timestamp, git_commit) in `notes`.
    * Promotions (hypothesis → preliminary → solid) are appended as
      new rows, not in-place edits. The latest row for a (paper, node_id)
      is the current status.
    * summary.csv is regenerated automatically; never hand-edit it.

PRIMITIVES AND DAG
    The figure's three primitives map to optional fields, any combination
    of which a node may carry:
        equation_labels: list[str]   ○ — verbatim labels from derivation.md
        code_block_refs: list[str]   □ — paths into results/<project>/.../codes/
        concept_advance: bool        △ — does this node advance a paper-level concept?
    The DAG edges live in `predecessors[]` — a list of node_id strings
    this node depends on. Walk back with the `predecessors` CLI command.

CROSS-REFERENCE TO ERROR DATABASE
    A solid row should carry `metric_at_landing` — the metric value at
    which it converged, mirroring the schema of an error_database row's
    `metric` field. Optionally `error_db_refs[]` lists the prior failed
    attempts (timestamp, git_commit pairs) that led here — the positive
    memory of the path through failure.

DOWNSTREAM CONSUMERS
    * pipelines/1-decompose — `logic.md` node IDs feed
      `node_id` here.
    * pipelines/2-work — every promise-tag commit
      should append a `status=solid` row for the node it closed.
    * pipelines/2-work — promotes rows from preliminary
      to solid on successful verification.
    * pipelines/3-write — reads solid rows to find which
      claims have evidence to back them in the paper draft.
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

# --- enum constants ---------------------------------------------------------

DOMAINS = ("symbolic", "numerical", "proof")

# Status values. `solid` / `preliminary` / `hypothesis` are EXIST states (●);
# `blocking` / `future` are NOT-EXIST states (○) — placeholders for nodes
# the loop has identified but not yet derived. `amended` is a correction
# pointer to a prior row.
STATUSES = ("hypothesis", "preliminary", "solid", "blocking", "future", "amended")
EXIST_STATUSES = ("solid", "preliminary", "hypothesis")
NONEXIST_STATUSES = ("blocking", "future")

# Risk tiers from code_quality.py (carried for downstream filtering).
RISK_TIERS = ("R0", "R1", "R2", "R3", "R4")

REQUIRED_FIELDS = {
    "paper", "node_id", "task_id", "domain", "status", "summary",
}
REQUIRED_ON_SOLID = {"evidence"}
AUTO_FILLED = {"timestamp", "git_commit"}

# Per-field one-line semantics — queryable via `describe-fields`.
FIELD_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    # required
    "timestamp":         ("ISO-8601 UTC",  "auto-filled"),
    "paper":             ("string",        "arxiv-XXXX.XXXXX"),
    "node_id":           ("string",        "matches logic.md node id"),
    "task_id":           ("string",        "matches implementation.md §0"),
    "git_commit":        ("string",        "short SHA, auto-filled"),
    "domain":            ("enum",          "symbolic / numerical / proof"),
    "status":            ("enum",          "hypothesis / preliminary / solid / blocking / future / amended"),
    "summary":           ("string",        "one-line description of the node"),
    # conditional-required on status=solid
    "evidence":          ("string",        "verifier output path or commit citation"),
    # primitives (figure's legend: ○ □ △)
    "equation_labels":   ("array",         "○ — verbatim labels from derivation.md (e.g. ['eq:D.k', 'eq:D.k+1'])"),
    "code_block_refs":   ("array",         "□ — paths into results/<project>/<paper>/codes/ (with optional :L<a>-<b>)"),
    "concept_advance":   ("bool",          "△ — does this node advance a paper-level concept?"),
    # DAG / provenance
    "predecessors":      ("array",         "node_id strings this node depends on (DAG edges)"),
    "node_seq":          ("int",           "1-based index of this record under its node (auto-filled; the doubly-linked list under the DAG node)"),
    "paper_anchor":      ("string",        "paper section / theorem / figure id"),
    "risk_tier":         ("enum",          "R0..R4 (from code_quality.py risk tiers)"),
    "metric_at_landing": ("object",        "{name, value, threshold, pass} — the error_database row that closed this"),
    "error_db_refs":     ("array",         "list of {timestamp, git_commit} for failed attempts that preceded this success"),
    "assumptions_used":  ("array",         "for proof work: assumptions beyond agreed baseline"),
    "runtime_metadata":  ("object",        "tool-specific; recommended keys mirror error_database describe-domain"),
    "notes":             ("string",        "free text; cite amended rows here"),
    # executable admission (see _common/ledgers/admission.py)
    "verification":      ("object",        "{command, timeout_s?, cwd?} — RUN at append; exit 0 required; outcome recorded in verification_run"),
    "verification_run":  ("object",        "auto-filled observed outcome of the verification command"),
    "evidence_sha256":   ("string",        "auto-filled content hash when evidence names an existing file"),
    "admission_flags":   ("array",         "auto-filled bypass record (skip_exec / allow_missing_deps) — visible, never silent"),
}


# --- helpers ----------------------------------------------------------------

def utc_now_iso() -> str:
    # Microsecond precision so closely-spaced appends are orderable.
    return lc.utc_now_iso(timespec="microseconds")


git_commit_short = lc.git_commit_short


# --- validation -------------------------------------------------------------

def validate(row: dict[str, Any]) -> None:
    """Raise ValueError on schema violation. Allowed values quoted in the message."""
    missing = REQUIRED_FIELDS - row.keys()
    if missing:
        raise ValueError(f"missing required fields: {sorted(missing)}")

    if row["domain"] not in DOMAINS:
        raise ValueError(f"domain={row['domain']!r} not in {DOMAINS}")
    if row["status"] not in STATUSES:
        raise ValueError(f"status={row['status']!r} not in {STATUSES}")
    if "risk_tier" in row and row["risk_tier"] not in RISK_TIERS:
        raise ValueError(f"risk_tier={row['risk_tier']!r} not in {RISK_TIERS}")

    if row["status"] == "solid":
        missing_on_solid = REQUIRED_ON_SOLID - row.keys()
        if missing_on_solid:
            raise ValueError(
                f"status='solid' requires {sorted(missing_on_solid)}; "
                "alignment.md §0 closed-loop — solid rows MUST cite verifier output"
            )

    # Primitive payload shape checks (each is optional but if present must be the right type).
    if "equation_labels" in row and not isinstance(row["equation_labels"], list):
        raise ValueError(f"equation_labels must be a list of strings; got {type(row['equation_labels']).__name__}")
    if "code_block_refs" in row and not isinstance(row["code_block_refs"], list):
        raise ValueError(f"code_block_refs must be a list of strings; got {type(row['code_block_refs']).__name__}")
    if "predecessors" in row and not isinstance(row["predecessors"], list):
        raise ValueError(f"predecessors must be a list of node_id strings; got {type(row['predecessors']).__name__}")
    if "concept_advance" in row and not isinstance(row["concept_advance"], bool):
        raise ValueError(f"concept_advance must be a bool; got {type(row['concept_advance']).__name__}")


# --- core API ---------------------------------------------------------------

def append_row(row: dict[str, Any], *, repo_root: str | Path | None = None,
               skip_exec: bool = False, allow_missing_deps: bool = False) -> dict[str, Any]:
    """Validate + run the executable admission gate + auto-fill + append.

    Auto-fills `timestamp` and `git_commit` if absent. Regenerates summary.csv.
    `solid` rows must carry verifiable evidence (existing file, resolvable
    commit citation, or passing `verification.command`) and solid-only
    predecessors — see `_common/ledgers/admission.py`.
    """
    root = Path(repo_root) if repo_root else Path.cwd()
    row.setdefault("timestamp", utc_now_iso())
    row.setdefault("git_commit", git_commit_short(root))
    validate(row)
    adm.check_knowledge_admission(row, root, skip_exec=skip_exec,
                                  allow_missing_deps=allow_missing_deps)
    if "node_seq" not in row:                       # number this record 1,2,3… under its DAG node
        existing = read_entries(root, row["paper"])
        row["node_seq"] = 1 + sum(1 for r in existing if r.get("node_id") == row["node_id"])

    db_dir = lc.db_dir(root, "knowledge", row["paper"])
    db_dir.mkdir(parents=True, exist_ok=True)
    lc.chain_append(db_dir, "nodes.jsonl", row)
    regenerate_summary(db_dir)
    return row


def append_batch(rows: list[dict[str, Any]], *, repo_root: str | Path | None = None,
                 force: bool = False, skip_exec: bool = False,
                 allow_missing_deps: bool = False) -> dict[str, Any]:
    """Validate + dedup-append a list of node rows (one decomposition's worth).

    Idempotent: a (paper, node_id) whose LATEST non-amended row already has the
    same (status, summary) is skipped unless `force=True`, so re-running a
    decomposition does not duplicate rows. Returns counts + the papers touched.
    """
    if not isinstance(rows, list):
        raise ValueError("rows must be a JSON array of node objects")
    by_paper: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_paper.setdefault(r.get("paper", "?"), []).append(r)
    appended = skipped = 0
    for paper, prows in by_paper.items():
        existing = read_entries(repo_root, paper)
        for row in prows:
            if not force:
                cur = latest_status(existing, paper, row.get("node_id", ""))
                if cur and cur.get("status") == row.get("status") and cur.get("summary") == row.get("summary"):
                    skipped += 1
                    continue
            written = append_row(dict(row), repo_root=repo_root, skip_exec=skip_exec,
                                 allow_missing_deps=allow_missing_deps)
            existing.append(written)
            appended += 1
    return {"appended": appended, "skipped": skipped, "papers": sorted(by_paper)}


def read_entries(repo_root: str | Path | None, paper: str) -> list[dict[str, Any]]:
    """Read existing rows for a paper. Returns [] if the file is missing."""
    return lc.read_jsonl(repo_root, "knowledge", paper, "nodes.jsonl")


def latest_status(rows: list[dict[str, Any]], paper: str, node_id: str) -> dict[str, Any] | None:
    """Return the latest non-amended row for a given (paper, node_id), or None.
    Uses append-order (the JSONL file IS the ordering): last occurrence wins.
    """
    result: dict[str, Any] | None = None
    for r in rows:
        if (r.get("paper") == paper
                and r.get("node_id") == node_id
                and r.get("status") != "amended"):
            result = r
    return result


def node_records(paper: str, node_id: str, *, repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    """The doubly-linked list of knowledge records under a DAG node, in append
    order (`node_seq` 1..n). Records accrue under the node rather than minting
    new DAG nodes."""
    return [r for r in read_entries(repo_root, paper) if r.get("node_id") == node_id]


_SUMMARY_ORDER = [
    "timestamp", "paper", "node_id", "node_seq", "task_id", "git_commit",
    "domain", "status", "summary", "evidence",
    "equation_labels", "code_block_refs", "concept_advance",
    "predecessors", "paper_anchor", "risk_tier",
]


def regenerate_summary(db_dir: Path) -> None:
    lc.regenerate_summary(db_dir, "nodes.jsonl", _SUMMARY_ORDER)


# --- query API --------------------------------------------------------------

def query(paper: str, *,
          status: str | None = None,
          node_id: str | None = None,
          task_id: str | None = None,
          domain: str | None = None,
          equation_label: str | None = None,
          concept_advance_only: bool = False,
          latest_only: bool = True,
          repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Filter knowledge-database rows for a paper.

    `latest_only=True` (default) collapses to the latest non-amended row per
    (paper, node_id). Pass False to see the full append-only history including
    promotions.
    """
    rows = read_entries(repo_root, paper)
    if latest_only:
        # Walk in append-order; later occurrences overwrite. The JSONL file
        # IS the ordering — don't rely on timestamps that can collide at
        # second resolution.
        rows = lc.latest_per_node(rows)
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if node_id is not None:
        rows = [r for r in rows if r.get("node_id") == node_id]
    if task_id is not None:
        rows = [r for r in rows if r.get("task_id") == task_id]
    if domain is not None:
        rows = [r for r in rows if r.get("domain") == domain]
    if equation_label is not None:
        rows = [r for r in rows
                if equation_label in (r.get("equation_labels") or [])]
    if concept_advance_only:
        rows = [r for r in rows if r.get("concept_advance") is True]
    return rows


def predecessors_of(paper: str, node_id: str, *,
                    transitive: bool = False,
                    repo_root: str | Path | None = None) -> list[str]:
    """Return the immediate predecessor node_ids of (paper, node_id). With
    `transitive=True`, returns the full ancestor set."""
    rows = read_entries(repo_root, paper)
    direct = latest_status(rows, paper, node_id)
    if direct is None:
        return []
    preds = list(direct.get("predecessors") or [])
    if not transitive:
        return preds
    seen: set[str] = set()
    frontier = list(preds)
    while frontier:
        n = frontier.pop()
        if n in seen:
            continue
        seen.add(n)
        r = latest_status(rows, paper, n)
        if r is not None:
            frontier.extend(r.get("predecessors") or [])
    return sorted(seen)


# --- HTML render -------------------------------------------------------------

# Per-row status tints (+ the .advance accent); the rest of the ledger CSS and
# the table JS are shared (ledger_common.ledger_css / LEDGER_JS).
_STATUS_CSS = """tr.solid{background:#effff0}
tr.preliminary{background:#fffae0}
tr.hypothesis{background:#e6f0ff}
tr.blocking{background:#ffe2e2}
tr.future{background:#f2f2f2;color:#666}
tr.amended{background:#f2f2f2;color:#777}
"""

_HTML_CSS = lc.ledger_css(_STATUS_CSS, advance=True)
_HTML_JS = lc.LEDGER_JS


def _esc(v: Any) -> str:
    return lc.esc_cell(v, bool_lower=True)


def _pred_links(preds: list[str] | None) -> str:
    if not preds:
        return _esc(None)
    return ", ".join(f'<a href="#node-{p}">{_esc(p)}</a>' for p in preds)


def render_html(paper: str, *, repo_root: str | Path | None = None,
                output_path: str | Path | None = None,
                latest_only: bool = True) -> Path:
    """Render the per-paper knowledge ledger to a self-contained HTML page
    at `results/views/knowledge/paper_<paper>.html` (or a custom path).
    Default shows the latest non-amended row per node_id; `latest_only=False`
    includes the full promotion history."""
    if latest_only:
        rows = query(paper, latest_only=True, repo_root=repo_root)
    else:
        rows = read_entries(repo_root, paper)
    if not rows:
        raise ValueError(f"no entries for paper={paper!r} in knowledge-database/")
    root = Path(repo_root) if repo_root else Path.cwd()
    out = Path(output_path) if output_path else root / "results" / "views" / "knowledge" / f"paper_{paper}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_build_knowledge_html(paper, rows, latest_only=latest_only), encoding="utf-8")
    return out


def _build_knowledge_html(paper: str, rows: list[dict[str, Any]], *, latest_only: bool) -> str:
    n = len(rows)
    by_status: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    advance_count = 0
    for r in rows:
        by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
        if r.get("domain"):
            by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
        if r.get("concept_advance"):
            advance_count += 1
    exist_count = sum(by_status.get(s, 0) for s in EXIST_STATUSES)
    nonexist_count = sum(by_status.get(s, 0) for s in NONEXIST_STATUSES)
    summary_parts = [
        f"<span><strong>nodes</strong> {n}</span>",
        f"<span><strong>● exist</strong> {exist_count}</span>",
        f"<span><strong>○ not-exist</strong> {nonexist_count}</span>",
        f"<span><strong>△ concept advances</strong> {advance_count}</span>",
        *[f"<span><strong>{k}</strong> {v}</span>" for k, v in sorted(by_status.items())],
    ]
    if by_domain:
        summary_parts.append("<span><strong>domains</strong> " +
                             ", ".join(f"{k}:{v}" for k, v in sorted(by_domain.items())) + "</span>")
    summary = "<div class='summary'>" + "".join(summary_parts) + "</div>"

    cols = ("timestamp", "node_id", "task_id", "domain", "status",
            "summary", "equation_labels (○)", "code_block_refs (□)",
            "concept_advance (△)", "predecessors", "evidence")
    head = "".join(f"<th>{c}</th>" for c in cols)
    body_rows: list[str] = []
    for r in rows:
        cls = r.get("status", "")
        nid = r.get("node_id", "")
        ca = r.get("concept_advance")
        ca_cell = '<span class="advance">△ yes</span>' if ca else (_esc(None) if ca is None else "no")
        cells = [
            _esc(r.get("timestamp")),
            f'<span class="cell-mono" id="node-{_esc(nid)}">{_esc(nid)}</span>',
            _esc(r.get("task_id")),
            _esc(r.get("domain")),
            _esc(r.get("status")),
            f'<div class="cell-wrap">{_esc(r.get("summary"))}</div>',
            _esc(r.get("equation_labels")),
            f'<div class="cell-wrap cell-mono">{_esc(r.get("code_block_refs"))}</div>',
            ca_cell,
            _pred_links(r.get("predecessors")),
            f'<div class="cell-wrap">{_esc(r.get("evidence"))}</div>',
        ]
        body_rows.append(f"<tr class='{cls}'>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    body = "".join(body_rows)
    mode_note = "latest non-amended row per node_id" if latest_only else "full append history including promotions and amendments"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>knowledge_database — paper_{_esc(paper)}</title>
<style>{_HTML_CSS}</style></head>
<body>
<h1>Knowledge Database — <span class="cell-mono">paper_{_esc(paper)}</span></h1>
<p class="subtitle">★ dual of error_database. Append-only ledger of converged <span class="cell-mono">logic.md</span> nodes. View: <strong>{mode_note}</strong>. Primitives: ○ equation_labels · □ code_block_refs · △ concept_advance.</p>
{summary}
<div class="controls"><input id="search" class="search" type="text" placeholder="filter rows (substring match across all columns)…"></div>
<table id="rows"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
<script>{_HTML_JS}</script>
</body></html>
"""


# --- CLI --------------------------------------------------------------------

SCHEMA_SUMMARY = """knowledge_database — compact reference

REQUIRED fields:  {required}
AUTO-FILLED:      {auto}
REQUIRED if status=solid: {on_solid}

enums:
  domain     = {domains}
  status     = {statuses}
  risk_tier  = {risk_tiers}

exist (●) statuses:    {exist}
not-exist (○) statuses: {nonexist}

per-field meanings:
  python _common/knowledge_database.py describe-fields

primitives (figure legend): ○ equation_labels  □ code_block_refs  △ concept_advance
"""


def _schema_text() -> str:
    return SCHEMA_SUMMARY.format(
        required=sorted(REQUIRED_FIELDS),
        auto=sorted(AUTO_FILLED),
        on_solid=sorted(REQUIRED_ON_SOLID),
        domains=DOMAINS, statuses=STATUSES, risk_tiers=RISK_TIERS,
        exist=EXIST_STATUSES, nonexist=NONEXIST_STATUSES,
    )


def _describe_fields() -> str:
    groups = [
        ("required (every row)",
         [f for f in FIELD_DESCRIPTIONS if f in REQUIRED_FIELDS or f in AUTO_FILLED]),
        ("required when status=solid",
         [f for f in FIELD_DESCRIPTIONS if f in REQUIRED_ON_SOLID]),
        ("optional / recommended",
         [f for f in FIELD_DESCRIPTIONS
          if f not in REQUIRED_FIELDS and f not in REQUIRED_ON_SOLID and f not in AUTO_FILLED]),
    ]
    width_n = max(len(n) for n in FIELD_DESCRIPTIONS)
    width_t = max(len(t) for t, _ in FIELD_DESCRIPTIONS.values())
    lines: list[str] = []
    for title, names in groups:
        lines.append(f"# {title}")
        for n in names:
            t, m = FIELD_DESCRIPTIONS[n]
            lines.append(f"  {n:<{width_n}}  {t:<{width_t}}  {m}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="knowledge_database")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("schema", help="print compact schema summary")
    sub.add_parser("describe-fields", help="per-field semantics")

    ap_app = sub.add_parser("append", help="validate + run the executable admission gate + append a JSON row from stdin or file")
    ap_app.add_argument("--row-file", type=Path, help="read row JSON from file (default: stdin)")
    ap_app.add_argument("--repo-root", type=Path, default=None)
    ap_app.add_argument("--skip-exec", action="store_true",
                        help="do not run verification.command (recorded in admission_flags)")
    ap_app.add_argument("--allow-missing-deps", action="store_true",
                        help="admit a solid row despite unresolvable predecessors (recorded in admission_flags)")

    ab = sub.add_parser("append-batch",
                        help="validate + dedup-append a JSON array of rows (one decomposition's worth)")
    ab.add_argument("--rows-file", type=Path, help="JSON array of rows (default: stdin)")
    ab.add_argument("--repo-root", type=Path, default=None)
    ab.add_argument("--force", action="store_true",
                    help="append even if an identical latest row already exists")
    ab.add_argument("--skip-exec", action="store_true",
                    help="do not run verification.command (recorded in admission_flags)")
    ab.add_argument("--allow-missing-deps", action="store_true",
                    help="admit solid rows despite unresolvable predecessors (recorded in admission_flags)")

    qy = sub.add_parser("query", help="filter rows; default returns the latest non-amended row per node_id")
    qy.add_argument("--paper", required=True)
    qy.add_argument("--status", choices=STATUSES, default=None)
    qy.add_argument("--node-id", default=None, dest="node_id")
    qy.add_argument("--task-id", default=None, dest="task_id")
    qy.add_argument("--domain", choices=DOMAINS, default=None)
    qy.add_argument("--equation-label", default=None, dest="equation_label")
    qy.add_argument("--concept-advance-only", action="store_true", dest="concept_advance_only")
    qy.add_argument("--with-history", action="store_true",
                    help="include amended/superseded rows (default: latest-only)")
    qy.add_argument("--repo-root", type=Path, default=None)

    pr = sub.add_parser("predecessors", help="walk the DAG back from a node")
    pr.add_argument("--paper", required=True)
    pr.add_argument("--node-id", required=True, dest="node_id")
    pr.add_argument("--transitive", action="store_true",
                    help="return the full ancestor set (default: immediate predecessors only)")
    pr.add_argument("--repo-root", type=Path, default=None)

    rs = sub.add_parser("regenerate-summary", help="regenerate summary.csv for a paper dir")
    rs.add_argument("paper_dir", type=Path)

    rh = sub.add_parser("render-html",
                        help="render a self-contained HTML view at results/views/knowledge/paper_<P>.html")
    rh.add_argument("--paper", required=True)
    rh.add_argument("--output", type=Path, default=None,
                    help="custom output path (default: results/views/knowledge/paper_<paper>.html)")
    rh.add_argument("--repo-root", type=Path, default=None)
    rh.add_argument("--with-history", action="store_true",
                    help="include the full append history (default: latest non-amended per node_id)")

    args = ap.parse_args(argv)

    if args.cmd == "schema":
        sys.stdout.write(_schema_text())
        return 0
    if args.cmd == "describe-fields":
        sys.stdout.write(_describe_fields())
        return 0
    if args.cmd == "append":
        raw = args.row_file.read_text() if args.row_file else sys.stdin.read()
        row = json.loads(raw)
        written = append_row(row, repo_root=args.repo_root, skip_exec=args.skip_exec,
                             allow_missing_deps=args.allow_missing_deps)
        out = {"appended": True,
               "git_commit": written["git_commit"],
               "timestamp": written["timestamp"],
               "paper": written["paper"],
               "node_id": written["node_id"],
               "status": written["status"]}
        for k in ("evidence_sha256", "admission_flags"):
            if k in written:
                out[k] = written[k]
        print(json.dumps(out))
        return 0
    if args.cmd == "append-batch":
        raw = args.rows_file.read_text() if args.rows_file else sys.stdin.read()
        print(json.dumps(append_batch(json.loads(raw), repo_root=args.repo_root, force=args.force,
                                      skip_exec=args.skip_exec,
                                      allow_missing_deps=args.allow_missing_deps)))
        return 0
    if args.cmd == "query":
        results = query(
            args.paper,
            status=args.status,
            node_id=args.node_id,
            task_id=args.task_id,
            domain=args.domain,
            equation_label=args.equation_label,
            concept_advance_only=args.concept_advance_only,
            latest_only=not args.with_history,
            repo_root=args.repo_root,
        )
        print(json.dumps(results, indent=2))
        return 0
    if args.cmd == "predecessors":
        preds = predecessors_of(args.paper, args.node_id,
                                transitive=args.transitive,
                                repo_root=args.repo_root)
        print(json.dumps(preds, indent=2))
        return 0
    if args.cmd == "regenerate-summary":
        regenerate_summary(args.paper_dir)
        return 0
    if args.cmd == "render-html":
        out = render_html(args.paper, repo_root=args.repo_root,
                          output_path=args.output,
                          latest_only=not args.with_history)
        print(json.dumps({"rendered": True, "paper": args.paper, "path": str(out)}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
