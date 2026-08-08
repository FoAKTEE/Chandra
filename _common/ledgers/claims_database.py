"""claims_database - append-only per-paper claim / obligation / assumption log.

Canonical schema-as-code for the stage-1 decomposition artifacts that were
previously free-form markdown: `claims.md`, `obligations.md`, and
`assumptions.md` are GENERATED views over this ledger (`render-md`), never
hand-authored. Structured first, prose rendered.

Cross-links are executable at append time (see `_common/ledgers/admission.py`
for the shared machinery):
  * an `admitted`/`refuted` claim must cite a `result_ref` that exists in the
    result ledger with a consistent status;
  * a `discharged` obligation must cite `discharged_by` — an existing result
    row or knowledge node;
  * a `relaxed` assumption must cite `reduction_obligation` — an obligation
    entry in this ledger (the stage-4 reduction-to-baseline rule, executable).

Rows are append-only. To change an entry, append a new row with the same
`entry_id`; latest append wins for the current view.

USAGE
    python _common/claims_database.py schema
    python _common/claims_database.py describe-fields
    echo '{...row JSON...}' | python _common/claims_database.py append
    python _common/claims_database.py append-batch --rows-file rows.json
    python _common/claims_database.py query --paper P [--kind K] [--status S]
    python _common/claims_database.py render-md --paper P --kind claim
    python _common/claims_database.py render-md --paper P --out-dir results/<project>/paper_<P>/decomposition/
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
    from _common.ledgers import result_database as rdb
else:
    from . import admission as adm
    from . import ledger_common as lc
    from . import result_database as rdb

KINDS = ("claim", "obligation", "assumption")

STATUSES_BY_KIND = {
    "claim":      ("open", "in_progress", "admitted", "refuted", "withdrawn"),
    "obligation": ("open", "discharged", "waived"),
    "assumption": ("active", "relaxed", "retired"),
}

# evidence-type vocabulary is owned by the result ledger; referenced, not copied
NEEDED_EVIDENCE_TYPES = rdb.EVIDENCE_TYPES

REQUIRED_FIELDS = {"paper", "entry_id", "kind", "statement", "status"}
AUTO_FILLED = {"timestamp", "git_commit"}

FIELD_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "timestamp":            ("ISO-8601 UTC", "auto-filled"),
    "git_commit":           ("string", "short SHA, auto-filled"),
    "paper":                ("string", "arxiv-XXXX.XXXXX"),
    "entry_id":             ("string", "stable id; re-append the same id to amend (latest wins)"),
    "kind":                 ("enum", "claim / obligation / assumption"),
    "statement":            ("string", "the claim / obligation / assumption in one plain-language sentence"),
    "status":               ("enum", "claim: open/in_progress/admitted/refuted/withdrawn; obligation: open/discharged/waived; assumption: active/relaxed/retired"),
    # claim
    "needed_evidence_type": ("enum", "REQUIRED on kind=claim; what evidence would admit it (result-ledger vocabulary)"),
    "result_ref":           ("string", "REQUIRED on admitted/refuted claims; the result_id that settled it (checked to exist)"),
    "working_context":      ("object/string", "model, regime, units, frames"),
    # obligation
    "discharged_by":        ("string", "REQUIRED on discharged obligations; result_id or knowledge node_id (checked to exist)"),
    "owner":                ("string", "who/what resolves it (agent, stage, human)"),
    "blocking":             ("bool", "true = [BLOCKING]-class; resolution required before section/task closure"),
    # assumption
    "scope":                ("string", "symmetry / limit / regime the assumption covers"),
    "reduction_obligation": ("string", "REQUIRED on relaxed assumptions; obligation entry_id carrying the reduction-to-baseline check"),
    # shared optional
    "node_ids":             ("array", "logic.md DAG node ids this entry attaches to"),
    "dependencies":         ("array", "entry ids / node ids / source ids this entry rests on"),
    "source_ids":           ("array", "source-library ids"),
    "task_id":              ("string", "implementation task id"),
    "iteration":            ("int", "Ralph loop counter"),
    "notes":                ("string", "free text; cite superseded rows"),
    "admission_flags":      ("array", "auto-filled bypass record (allow_missing_refs) — visible, never silent"),
}


def utc_now_iso() -> str:
    return lc.utc_now_iso(timespec="microseconds")


# --- validation (pure shape; no filesystem) -----------------------------------

def validate(row: dict[str, Any]) -> None:
    missing = REQUIRED_FIELDS - row.keys()
    if missing:
        raise ValueError(f"missing required fields: {sorted(missing)}")
    kind = row["kind"]
    if kind not in KINDS:
        raise ValueError(f"kind={kind!r} not in {KINDS}")
    allowed = STATUSES_BY_KIND[kind]
    if row["status"] not in allowed:
        raise ValueError(f"status={row['status']!r} not in {allowed} for kind={kind!r}")

    if kind == "claim":
        if row.get("needed_evidence_type") not in NEEDED_EVIDENCE_TYPES:
            raise ValueError(
                f"kind='claim' requires needed_evidence_type in {NEEDED_EVIDENCE_TYPES}")
        if row["status"] in ("admitted", "refuted") and not row.get("result_ref"):
            raise ValueError(f"status={row['status']!r} requires result_ref (the settling result_id)")
    if kind == "obligation" and row["status"] == "discharged" and not row.get("discharged_by"):
        raise ValueError("status='discharged' requires discharged_by (result_id or knowledge node_id)")
    if kind == "assumption" and row["status"] == "relaxed" and not row.get("reduction_obligation"):
        raise ValueError(
            "status='relaxed' requires reduction_obligation (the reduction-to-baseline obligation entry_id)")

    for field in ("node_ids", "dependencies", "source_ids"):
        if field in row and not isinstance(row[field], list):
            raise ValueError(f"{field} must be a list; got {type(row[field]).__name__}")
    if "blocking" in row and not isinstance(row["blocking"], bool):
        raise ValueError(f"blocking must be a bool; got {type(row['blocking']).__name__}")


# --- executable cross-reference gate -------------------------------------------

def check_refs(row: dict[str, Any], repo_root: str | Path | None, *,
               allow_missing_refs: bool = False) -> dict[str, Any]:
    """Resolve the row's settling references against the other ledgers."""
    root = Path(repo_root) if repo_root else Path.cwd()

    def _bypass(msg: str) -> None:
        if allow_missing_refs:
            flags = row.setdefault("admission_flags", [])
            if "allow_missing_refs" not in flags:
                flags.append("allow_missing_refs")
        else:
            raise adm.AdmissionError(msg + " — or pass --allow-missing-refs")

    kind, status = row["kind"], row["status"]
    if kind == "claim" and status in ("admitted", "refuted"):
        ref_rows = rdb.query(row["paper"], result_id=row["result_ref"], repo_root=root)
        if not ref_rows:
            _bypass(f"result_ref {row['result_ref']!r} not found in result-database/paper_{row['paper']}")
        else:
            ref_status = ref_rows[0].get("status")
            if status == "refuted" and ref_status != "refuted":
                raise adm.AdmissionError(
                    f"claim marked refuted but result {row['result_ref']!r} has status {ref_status!r}")
            if status == "admitted" and ref_status in ("refuted", "unchecked"):
                raise adm.AdmissionError(
                    f"claim marked admitted but result {row['result_ref']!r} has status {ref_status!r}")
    elif kind == "obligation" and status == "discharged":
        ref = row["discharged_by"]
        in_results = bool(rdb.query(row["paper"], result_id=ref, repo_root=root))
        in_knowledge = adm.find_knowledge_node(ref, root, paper_hint=row["paper"]) is not None
        if not (in_results or in_knowledge):
            _bypass(f"discharged_by {ref!r} matches no result row and no knowledge node")
    elif kind == "assumption" and status == "relaxed":
        ref = row["reduction_obligation"]
        hits = [r for r in read_entries(root, row["paper"])
                if r.get("entry_id") == ref and r.get("kind") == "obligation"]
        if not hits:
            _bypass(f"reduction_obligation {ref!r} matches no obligation entry in claim-database")
    return row


# --- core API -------------------------------------------------------------------

def append_row(row: dict[str, Any], *, repo_root: str | Path | None = None,
               allow_missing_refs: bool = False) -> dict[str, Any]:
    root = Path(repo_root) if repo_root else Path.cwd()
    row.setdefault("timestamp", utc_now_iso())
    row.setdefault("git_commit", lc.git_commit_short(root))
    validate(row)
    adm.check_actor_role(row, root)
    check_refs(row, root, allow_missing_refs=allow_missing_refs)

    db_dir = lc.db_dir(root, "claim", row["paper"])
    db_dir.mkdir(parents=True, exist_ok=True)
    lc.chain_append(db_dir, "entries.jsonl", row)
    regenerate_summary(db_dir)
    return row


def append_batch(rows: list[dict[str, Any]], *, repo_root: str | Path | None = None,
                 force: bool = False, allow_missing_refs: bool = False) -> dict[str, Any]:
    """Dedup-append one decomposition's worth of entries. Idempotent: an
    entry_id whose latest row already has the same (status, statement) is
    skipped unless `force=True`."""
    if not isinstance(rows, list):
        raise ValueError("rows must be a JSON array of entry objects")
    by_paper: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_paper.setdefault(r.get("paper", "?"), []).append(r)
    appended = skipped = 0
    for paper, prows in by_paper.items():
        existing = {r["entry_id"]: r for r in read_entries(repo_root, paper) if "entry_id" in r}
        for row in prows:
            cur = existing.get(row.get("entry_id"))
            if (not force and cur and cur.get("status") == row.get("status")
                    and cur.get("statement") == row.get("statement")):
                skipped += 1
                continue
            written = append_row(dict(row), repo_root=repo_root,
                                 allow_missing_refs=allow_missing_refs)
            existing[written["entry_id"]] = written
            appended += 1
    return {"appended": appended, "skipped": skipped, "papers": sorted(by_paper)}


def read_entries(repo_root: str | Path | None, paper: str) -> list[dict[str, Any]]:
    return lc.read_jsonl(repo_root, "claim", paper, "entries.jsonl")


def latest_per_entry(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_entry: dict[str, dict[str, Any]] = {}
    for r in rows:
        eid = r.get("entry_id")
        if eid is not None:
            by_entry[eid] = r
    return list(by_entry.values())


def query(paper: str, *, kind: str | None = None, status: str | None = None,
          entry_id: str | None = None, latest_only: bool = True,
          repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    rows = read_entries(repo_root, paper)
    if latest_only:
        rows = latest_per_entry(rows)
    if kind is not None:
        rows = [r for r in rows if r.get("kind") == kind]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if entry_id is not None:
        rows = [r for r in rows if r.get("entry_id") == entry_id]
    return rows


_SUMMARY_ORDER = [
    "timestamp", "paper", "entry_id", "kind", "status", "statement",
    "needed_evidence_type", "result_ref", "discharged_by", "reduction_obligation",
    "node_ids", "dependencies", "git_commit",
]


def regenerate_summary(db_dir: Path) -> None:
    lc.regenerate_summary(db_dir, "entries.jsonl", _SUMMARY_ORDER)


# --- generated markdown views ----------------------------------------------------

_VIEW_FILES = {"claim": "claims.md", "obligation": "obligations.md", "assumption": "assumptions.md"}

_VIEW_COLUMNS = {
    "claim":      ("entry_id", "statement", "needed_evidence_type", "status",
                   "result_ref", "dependencies", "node_ids"),
    "obligation": ("entry_id", "statement", "status", "blocking",
                   "discharged_by", "owner", "node_ids"),
    "assumption": ("entry_id", "statement", "scope", "status",
                   "reduction_obligation", "node_ids"),
}


def _md_cell(v: Any) -> str:
    if v is None or v == [] or v == "":
        return "—"
    if isinstance(v, (list, tuple)):
        v = "; ".join(str(x) for x in v)
    elif isinstance(v, dict):
        v = json.dumps(v, ensure_ascii=False)
    elif isinstance(v, bool):
        v = "yes" if v else "no"
    return str(v).replace("|", "\\|").replace("\n", " ")


def render_md(paper: str, kind: str, *, repo_root: str | Path | None = None) -> str:
    if kind not in KINDS:
        raise ValueError(f"kind={kind!r} not in {KINDS}")
    rows = query(paper, kind=kind, repo_root=repo_root)
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
    cols = _VIEW_COLUMNS[kind]
    lines = [
        f"<!-- GENERATED by `python _common/claims_database.py render-md --paper {paper} --kind {kind}` "
        f"— DO NOT EDIT BY HAND; claim-database/paper_{paper}/entries.jsonl is canonical. "
        "Change an entry by appending a new row with the same entry_id, then re-render. -->",
        "",
        f"# {kind.capitalize()}s — paper_{paper}",
        "",
        f"{len(rows)} entries; "
        + ", ".join(f"{n} {s}" for s, n in sorted(by_status.items())) + ".",
        "",
        "| " + " | ".join(cols) + " |",
        "|" + "---|" * len(cols),
    ]
    for r in sorted(rows, key=lambda x: x.get("entry_id", "")):
        lines.append("| " + " | ".join(_md_cell(r.get(c)) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def render_views(paper: str, out_dir: str | Path, *,
                 repo_root: str | Path | None = None) -> dict[str, str]:
    """Write the three decomposition views (claims.md / obligations.md /
    assumptions.md) into `out_dir`. Returns {kind: path}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for kind, filename in _VIEW_FILES.items():
        path = out / filename
        path.write_text(render_md(paper, kind, repo_root=repo_root), encoding="utf-8")
        written[kind] = str(path)
    return written


# --- CLI ---------------------------------------------------------------------------

SCHEMA_SUMMARY = """claims_database - compact reference

REQUIRED fields:  {required}
AUTO-FILLED:      {auto}

enums:
  kind                    = {kinds}
  status[claim]           = {claim_statuses}
  status[obligation]      = {obligation_statuses}
  status[assumption]      = {assumption_statuses}
  needed_evidence_type    = result-ledger vocabulary (python _common/result_database.py schema)

settling references are checked to EXIST at append (executable admission):
  admitted/refuted claim  -> result_ref in result-database
  discharged obligation   -> discharged_by in result- or knowledge-database
  relaxed assumption      -> reduction_obligation in claim-database (kind=obligation)

per-field meanings:
  python _common/claims_database.py describe-fields
"""


def _schema_text() -> str:
    return SCHEMA_SUMMARY.format(
        required=sorted(REQUIRED_FIELDS), auto=sorted(AUTO_FILLED), kinds=KINDS,
        claim_statuses=STATUSES_BY_KIND["claim"],
        obligation_statuses=STATUSES_BY_KIND["obligation"],
        assumption_statuses=STATUSES_BY_KIND["assumption"],
    )


def _describe_fields() -> str:
    width_n = max(len(n) for n in FIELD_DESCRIPTIONS)
    width_t = max(len(t) for t, _ in FIELD_DESCRIPTIONS.values())
    lines = []
    for n, (t, m) in FIELD_DESCRIPTIONS.items():
        lines.append(f"  {n:<{width_n}}  {t:<{width_t}}  {m}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="claims_database")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schema", help="print compact schema summary")
    sub.add_parser("describe-fields", help="per-field semantics")

    ap_app = sub.add_parser("append", help="validate + check settling refs + append a JSON row from stdin or file")
    ap_app.add_argument("--row-file", type=Path, help="read row JSON from file (default: stdin)")
    ap_app.add_argument("--repo-root", type=Path, default=None)
    ap_app.add_argument("--allow-missing-refs", action="store_true",
                        help="admit despite unresolvable settling refs (recorded in admission_flags)")

    ab = sub.add_parser("append-batch", help="validate + dedup-append a JSON array of entries")
    ab.add_argument("--rows-file", type=Path, help="JSON array of rows (default: stdin)")
    ab.add_argument("--repo-root", type=Path, default=None)
    ab.add_argument("--force", action="store_true",
                    help="append even if an identical latest row already exists")
    ab.add_argument("--allow-missing-refs", action="store_true")

    qy = sub.add_parser("query", help="filter rows; default returns latest row per entry_id")
    qy.add_argument("--paper", required=True)
    qy.add_argument("--kind", choices=KINDS, default=None)
    qy.add_argument("--status", default=None)
    qy.add_argument("--entry-id", default=None, dest="entry_id")
    qy.add_argument("--with-history", action="store_true")
    qy.add_argument("--repo-root", type=Path, default=None)

    rs = sub.add_parser("regenerate-summary", help="regenerate summary.csv for a paper dir")
    rs.add_argument("paper_dir", type=Path)

    rm = sub.add_parser("render-md",
                        help="render the generated claims/obligations/assumptions views (ledger is canonical)")
    rm.add_argument("--paper", required=True)
    rm.add_argument("--kind", choices=KINDS, default=None,
                    help="render one kind to stdout/--out (default with --out-dir: all three)")
    rm.add_argument("--out", type=Path, default=None, help="write the single-kind view to a file")
    rm.add_argument("--out-dir", type=Path, default=None, dest="out_dir",
                    help="write claims.md, obligations.md, and assumptions.md into this directory")
    rm.add_argument("--repo-root", type=Path, default=None)

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
                             allow_missing_refs=args.allow_missing_refs)
        out = {"appended": True, "paper": written["paper"],
               "entry_id": written["entry_id"], "kind": written["kind"],
               "status": written["status"], "timestamp": written["timestamp"]}
        if "admission_flags" in written:
            out["admission_flags"] = written["admission_flags"]
        print(json.dumps(out))
        return 0
    if args.cmd == "append-batch":
        raw = args.rows_file.read_text() if args.rows_file else sys.stdin.read()
        print(json.dumps(append_batch(json.loads(raw), repo_root=args.repo_root,
                                      force=args.force,
                                      allow_missing_refs=args.allow_missing_refs)))
        return 0
    if args.cmd == "query":
        rows = query(args.paper, kind=args.kind, status=args.status,
                     entry_id=args.entry_id, latest_only=not args.with_history,
                     repo_root=args.repo_root)
        print(json.dumps(rows, indent=2))
        return 0
    if args.cmd == "regenerate-summary":
        regenerate_summary(args.paper_dir)
        return 0
    if args.cmd == "render-md":
        if args.out_dir:
            written = render_views(args.paper, args.out_dir, repo_root=args.repo_root)
            print(json.dumps({"rendered": True, "paper": args.paper, "paths": written}))
        elif args.kind:
            text = render_md(args.paper, args.kind, repo_root=args.repo_root)
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(text, encoding="utf-8")
                print(json.dumps({"rendered": True, "paper": args.paper, "path": str(args.out)}))
            else:
                sys.stdout.write(text)
        else:
            ap.error("render-md needs --kind (single view) or --out-dir (all three)")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
