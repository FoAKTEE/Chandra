"""error_database — append-only per-paper trial log (schema-as-code).

Canonical implementation. This module's docstring, constants, and `describe-*`
commands ARE the complete spec — there is no companion markdown.

The trial log is the audit trail of a paper reproduction: every source-import,
decomposition, implementation, validation, result-log, writing, and escalation
trial (pass, fail, crash, partial) appends one row.
Success rows live alongside failure rows. Replaces prose progress.md.
A trial carries `node_id` (the DAG anchor) and an auto-numbered `node_seq`,
so trials form a doubly-linked list UNDER their `logic.md` node rather than
minting new nodes — the giant DAG is then the project-progress view.

USAGE
    python _common/error_database.py schema                       # required/optional fields + enums
    python _common/error_database.py describe-fields              # one-line meaning per field
    python _common/error_database.py describe-domain --domain D   # D in {symbolic,numerical,proof}
    python _common/error_database.py describe-tag --domain D --tag <tag>
    python _common/error_database.py list-tags --domain D
    echo '{...row JSON...}' | python _common/error_database.py append
    python _common/error_database.py regenerate-summary <paper-dir>

`append` auto-fills `timestamp` + `git_commit`, validates, writes to
`error-database/paper_{paper}/trials.jsonl`, and regenerates `summary.csv`.
Validation errors quote allowed enum values back — the agent self-corrects
from the error message; no markdown to re-read.

APPEND-ONLY DISCIPLINE
    * Never delete a row. To amend, append a new row with pass_fail="amended"
      citing the prior row's (timestamp, git_commit) in `notes`.
    * Failed and crashed runs MUST be appended — never skipped. A loop that
      hides failures cannot be audited.
    * summary.csv is regenerated automatically; never hand-edit it.

SELF-CORRECTION (the taxonomy is append-only too)
    1. First instance of a not-yet-classified failure: log failure_mode
       "uncategorized_<domain>" with a one-paragraph rationale in `notes` and
       a candidate tag in `next_hypothesis`. Permitted once per failure type.
    2. Second instance with the same root cause: pause the Ralph loop and
       edit this module:
         - Append the tag to FAILURE_MODES_<DOMAIN>.
         - Add a one-sentence entry to FAILURE_MODE_MEANINGS[<domain>].
         - If new, extend METRIC_NAMES_BY_DOMAIN or EVIDENCE_PATH_TEMPLATES.
         - Commit. Then append pass_fail="amended" rows for the prior
           uncategorized_<domain> rows now covered.
    3. Three or more uncategorized_<domain> rows without a schema-update commit
       is an alignment.md §0 closed-loop violation.

DOWNSTREAM CONSUMERS
    * pipelines/0-acquire/spec.md — similar-prior-error lookup can add
      missing sources.
    * pipelines/1-decompose/spec.md — recurring failure on a node triggers
      a decomposition refine.
    * pipelines/2-work/spec.md — validation appends rows; failures gate
      the loop gate (alignment.md §2).
    * pipelines/2-work/spec.md — accepted and rejected results link back
      to these trial rows.

In-process API:

    from error_database import append_row
    append_row({"paper": "arxiv-XXXX.XXXXX", "task_id": "...", ...})
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

# --- enum constants (the canonical taxonomy) ---------------------------------

DOMAINS = ("symbolic", "numerical", "proof")
STAGES = ("source_import", "decomposition", "implementation", "validation", "result_log", "writing", "escalation")
CHANGE_TYPES = ("structural", "scalar", "refactor")
PASS_FAIL = ("pass", "fail", "crash", "partial", "amended")
REGIME_SPLITS = ("dev", "holdout", "audit")

FAILURE_MODES_SYMBOLIC = (
    "nonsimplification", "branch_cut_ambiguity",
    "assumption_too_narrow", "assumption_too_broad",
    "noncommutative_order", "series_truncation_short",
    "integration_form_mismatch", "kernel_timeout",
    "kernel_memory_blowup", "verbatim_label_drift",
    "uncategorized_symbolic",
)
FAILURE_MODES_NUMERICAL = (
    "nan_inf_propagation", "mesh_too_coarse",
    "stiffness_unhandled", "boundary_condition_leak",
    "contour_on_branch_cut", "fft_aliasing",
    "precision_underflow", "rng_seed_leak",
    "regime_split_violation", "library_version_drift",
    "oom_or_timeout", "uncategorized_numerical",
)
FAILURE_MODES_PROOF = (
    "term_mismatch", "level_mismatch",
    "missing_rule", "decision_limit",
    "recursion_not_accepted", "rewrite_loop",
    "classical_constructive_mismatch", "library_api_drift",
    "assumption_creep", "proof_too_large",
    "uncategorized_proof",
)
FAILURE_MODES_BY_DOMAIN = {
    "symbolic": FAILURE_MODES_SYMBOLIC,
    "numerical": FAILURE_MODES_NUMERICAL,
    "proof": FAILURE_MODES_PROOF,
}

# --- per-domain reference (failure-mode meanings, metrics, meta, evidence) --

FAILURE_MODE_MEANINGS = {
    "symbolic": {
        "nonsimplification": "FullSimplify left the residual non-zero in a form the agent cannot certify; suspect non-trivial identity, missing assumption, or a literal mistake.",
        "branch_cut_ambiguity": "Two equivalent expressions disagree because of a Sqrt/Log/ArcTan branch choice.",
        "assumption_too_narrow": "The simplification closes only under stronger $Assumptions than the paper allows.",
        "assumption_too_broad": "The simplification holds only because an unstated assumption was silently used; reduction-to-baseline fails.",
        "noncommutative_order": "A term reordering used commutativity where the algebra (operator product, Ore extension, PBW basis) does not commute.",
        "series_truncation_short": "Required order in Series[...] was lower than the paper's claim; higher-order terms exposed the mismatch.",
        "integration_form_mismatch": "Integrate returned an equivalent but differently-shaped form; equality requires a non-trivial identity.",
        "kernel_timeout": "TimeConstrained or external timeout fired before FullSimplify / Integrate returned.",
        "kernel_memory_blowup": "$MemoryLimit hit; intermediate expression swell.",
        "verbatim_label_drift": "An equation label in derivation.md no longer matches the tex source — decomposition verbatim-labels violation.",
        "uncategorized_symbolic": "First instance of a not-yet-classified symbolic failure; on second instance, run the Self-correction protocol.",
    },
    "numerical": {
        "nan_inf_propagation": "A NaN/Inf appeared at a finite input; trace the first occurrence in the source.",
        "mesh_too_coarse": "Refining the grid / step size drops the error past threshold — discretization, not method.",
        "stiffness_unhandled": "An explicit integrator was applied to a stiff system; step-rejection or output oscillation.",
        "boundary_condition_leak": "Wave / signal reflected from a non-absorbing boundary; visible in windowed FFT or t-domain echo.",
        "contour_on_branch_cut": "Complex contour deformed onto a branch cut or pole; sign-flip in the residue sum.",
        "fft_aliasing": "Bandwidth exceeded Nyquist for the chosen sampling; low-frequency ghost peaks.",
        "precision_underflow": "Quantities below machine epsilon treated as zero; affects amplitude ratios more than phases.",
        "rng_seed_leak": "Reported 'deterministic' result depended on a globally-mutated RNG state; rerun differs.",
        "regime_split_violation": "The trial used a holdout or audit parameter regime for tuning. Hard violation; must be amended.",
        "library_version_drift": "Result changed across a known-good library version pin (numpy, scipy, JAX, DifferentialEquations.jl).",
        "oom_or_timeout": "The process hit a memory or wall-time limit before producing output.",
        "uncategorized_numerical": "First instance of a not-yet-classified numerical failure; on second instance, run the Self-correction protocol.",
    },
    "proof": {
        "term_mismatch": "Two proof terms or expressions did not match under the checker.",
        "level_mismatch": "The proof works at one abstraction level but the claim is stated at another.",
        "missing_rule": "A required rule, instance, or lemma is not in scope.",
        "decision_limit": "An automated decision step could not close a goal within its bound.",
        "recursion_not_accepted": "A recursive definition was rejected because termination was not justified.",
        "rewrite_loop": "A rewrite rule cycled instead of simplifying the expression.",
        "classical_constructive_mismatch": "The proof used a classical step where a constructive result was required, or the reverse.",
        "library_api_drift": "A lemma name or signature changed across a library version pin.",
        "assumption_creep": "The proof introduced an unintended extra assumption.",
        "proof_too_large": "The proof checks but is too large or slow for downstream use.",
        "uncategorized_proof": "First instance of a not-yet-classified proof failure; on second instance, run the Self-correction protocol.",
    },
}

METRIC_NAMES_BY_DOMAIN = {
    "symbolic": {
        "simplify_equals_zero": "value is 0 (pass) or a String form of the residual (fail).",
        "series_order_match": "value = highest matched order; threshold = required order.",
        "assumption_set_size": "value = count of extra $Assumptions clauses needed; threshold = budget in implementation.md §2.",
        "kernel_seconds": "value = wall time; secondary metric for timeout failures.",
    },
    "numerical": {
        "max_rel_error": "value = max|x_pred - x_ref| / max|x_ref|; threshold = agreed tolerance.",
        "l2_rel_error": "same as max_rel_error but with the L2 norm.",
        "convergence_order": "value = slope of log(error) vs log(h); threshold = expected order.",
        "closure_residual": "Green-function / source-response closure: ‖G+ + G- - I‖ / ‖I‖.",
        "wronskian_drift": "for ODE pairs: deviation of the Wronskian from its analytic value.",
    },
    "proof": {
        "proof_closes": "value in {true, false}; threshold = true.",
        "placeholder_count": "value = count of admitted placeholders; threshold = agreed budget (usually 0).",
        "extra_assumptions_count": "assumptions beyond agreed baseline; threshold = 0 unless explicitly intended.",
        "proof_size": "compiled proof-object size; used to verify a simplification pass.",
        "build_seconds": "wall time for proof-checker build target; secondary metric for timeout failures.",
    },
}

RECOMMENDED_RUNTIME_METADATA = {
    "symbolic": ("wolfram_version", "kernel", "package_versions", "assumptions_global", "max_extra_rules"),
    "numerical": ("language", "compiler_or_interpreter", "key_libraries", "dtype", "device", "rng_seed"),
    "proof": ("proof_assistant_version", "build_tool_version", "library_rev", "toolchain", "assumptions_baseline", "build_target"),
}

EVIDENCE_PATH_TEMPLATES = {
    "symbolic": {
        "root": "${CHANDRA_RUNTIME}/paper_<arxiv>/debug/symbolic/iter<N>/",
        "files": (
            ("input_expression.wl", "the lhs and rhs that failed to simplify"),
            ("simplify_transcript.txt", "kernel transcript, verbatim"),
            ("assumptions_used.wl", "$Assumptions and any local Assuming[]"),
            ("negative_control.wl", "inverted-assumption probe per alignment.md §4"),
        ),
    },
    "numerical": {
        "root": "${CHANDRA_RUNTIME}/paper_<arxiv>/debug/numerical/iter<N>/",
        "files": (
            ("inputs.npz", "arguments that triggered the trial (or seed for stochastic)"),
            ("output.npz", "raw numerical output"),
            ("reference.npz", "the reference / closed-form / baseline being compared"),
            ("error_plot.png", "rel-error vs domain coordinate"),
            ("convergence_log.csv", "(if applicable) error vs step / grid resolution"),
        ),
    },
    "proof": {
        "root": "${CHANDRA_RUNTIME}/paper_<arxiv>/debug/proof/iter<N>/",
        "files": (
            ("build.log", "full proof-checker output, verbatim"),
            ("target.proof", "the file under test (or a minimized excerpt)"),
            ("error_excerpt.txt", "the first checker error, copied verbatim"),
            ("assumptions_printout.txt", "assumption-dependency output"),
            ("minimized_reproducer.proof", "(if non-trivial) a minimized reproducer of the failure"),
        ),
    },
}

REQUIRED_FIELDS = {
    "paper", "task_id", "iteration", "stage", "domain",
    "change_type", "change_summary", "metric", "pass_fail",
    "wall_clock_seconds",
}
REQUIRED_ON_FAIL = {"expected", "observed", "root_cause", "fix_hypothesis", "failure_mode"}
AUTO_FILLED = {"timestamp", "git_commit"}  # populated if absent

# Per-field one-line semantics — queryable via `describe-fields`. Order within
# this dict is preserved by `describe-fields` so the categories read naturally.
FIELD_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    # required (every row)
    "timestamp":          ("ISO-8601 UTC",  "auto-filled"),
    "paper":              ("string",        "arxiv-XXXX.XXXXX"),
    "task_id":            ("string",        "matches implementation.md §0"),
    "iteration":          ("int",           "Ralph loop counter"),
    "git_commit":         ("string",        "short SHA, auto-filled"),
    "stage":              ("enum",          "source_import / decomposition / implementation / validation / result_log / writing / escalation"),
    "domain":             ("enum",          "symbolic / numerical / proof"),
    "change_type":        ("enum",          "structural / scalar / refactor"),
    "change_summary":     ("string",        "one-line description of the change"),
    "metric":             ("object",        "{name, value, threshold, pass}"),
    "pass_fail":          ("enum",          "pass / fail / crash / partial / amended"),
    "wall_clock_seconds": ("number",        "time around the verification command"),
    # required when pass_fail in {fail, crash, partial}
    "expected":           ("string",        "paper claim under test"),
    "observed":           ("string",        "measured output, verbatim, with evidence path"),
    "root_cause":         ("string",        "one-sentence diagnosis (alignment.md §5) with evidence file"),
    "fix_hypothesis":     ("string",        "concrete next change — NOT a parameter tweak"),
    "failure_mode":       ("enum",          "tag from FAILURE_MODES_<DOMAIN> (query via describe-domain)"),
    # optional / recommended
    "node_id":            ("string",        "logic.md node id — the DAG anchor this trial attaches under"),
    "node_seq":           ("int",           "1-based index of this trial under its node (auto-filled when node_id is set)"),
    "parameter_regime":   ("object",        "parameters used at the trial"),
    "regime_split":       ("enum",          "dev / holdout / audit (benchmark regime split)"),
    "next_hypothesis":    ("string",        "what to try in the next iteration"),
    "tests_run":          ("array",         "named sanity checks executed"),
    "code_edits":         ("object",        "{insertions, deletions, files} from git diff --shortstat"),
    "agent_iterations":   ("int",           "default 1; >1 if multiple Ralph iters collapse"),
    "llm_cost":           ("string/number", "tokens or USD; 'unavailable' if unexposed"),
    "runtime_metadata":   ("object",        "tool-specific; recommended keys via describe-domain"),
    "notes":              ("string",        "free text; cite amended rows here"),
}


# --- helpers -----------------------------------------------------------------

utc_now_iso = lc.utc_now_iso          # seconds precision (ledger_common default)
git_commit_short = lc.git_commit_short


# --- validation --------------------------------------------------------------

def validate(row: dict[str, Any]) -> None:
    """Raise ValueError on schema violation. Allowed values are quoted back in the message."""
    missing = REQUIRED_FIELDS - row.keys()
    if missing:
        raise ValueError(f"missing required fields: {sorted(missing)}")

    for field, allowed in (
        ("stage", STAGES),
        ("domain", DOMAINS),
        ("change_type", CHANGE_TYPES),
        ("pass_fail", PASS_FAIL),
    ):
        if row[field] not in allowed:
            raise ValueError(f"{field}={row[field]!r} not in {allowed}")

    if "regime_split" in row and row["regime_split"] not in REGIME_SPLITS:
        raise ValueError(f"regime_split={row['regime_split']!r} not in {REGIME_SPLITS}")

    m = row["metric"]
    for k in ("name", "value", "threshold", "pass"):
        if k not in m:
            raise ValueError(f"metric missing key {k!r}; got {m!r}")

    failing = row["pass_fail"] in ("fail", "crash", "partial")
    if failing:
        missing_on_fail = REQUIRED_ON_FAIL - row.keys()
        if missing_on_fail:
            raise ValueError(
                f"pass_fail={row['pass_fail']!r} requires {sorted(missing_on_fail)} "
                "(§0 closed-loop)"
            )
        allowed = FAILURE_MODES_BY_DOMAIN[row["domain"]]
        if row["failure_mode"] not in allowed:
            raise ValueError(
                f"failure_mode={row['failure_mode']!r} not in {allowed}. "
                f"Use 'uncategorized_{row['domain']}' for first instance, then "
                "follow Self-correction protocol — see this module's docstring."
            )


# --- core API ----------------------------------------------------------------

def append_row(row: dict[str, Any], *, repo_root: str | Path | None = None) -> dict[str, Any]:
    """Validate + auto-fill + append. Returns the written row.

    Auto-fills `timestamp` and `git_commit` if absent. Regenerates summary.csv.
    """
    root = Path(repo_root) if repo_root else Path.cwd()
    row.setdefault("timestamp", utc_now_iso())
    row.setdefault("git_commit", git_commit_short(root))
    validate(row)
    adm.check_actor_role(row, root)  # trials are work too: delegation policy applies
    if row.get("node_id") and "node_seq" not in row:   # number this trial 1,2,3… under its DAG node
        existing = read_entries(root, row["paper"])
        row["node_seq"] = 1 + sum(1 for r in existing if r.get("node_id") == row.get("node_id"))

    db_dir = lc.db_dir(root, "error", row["paper"])
    db_dir.mkdir(parents=True, exist_ok=True)
    lc.chain_append(db_dir, "trials.jsonl", row)
    regenerate_summary(db_dir)
    return row


_SUMMARY_ORDER = [
    "timestamp", "paper", "task_id", "node_id", "node_seq", "iteration", "git_commit",
    "stage", "domain", "change_type", "change_summary",
    "metric.name", "metric.value", "metric.threshold", "metric.pass",
    "pass_fail", "wall_clock_seconds",
    "failure_mode", "expected", "observed", "root_cause", "fix_hypothesis",
]


def append_batch(rows, *, repo_root=None):
    """Packet-flush append for trials: sequential validate+append with ONE
    summary regeneration at the end. A bad row stops the batch there
    (append-only: earlier rows remain)."""
    if not isinstance(rows, list):
        raise ValueError("rows must be a JSON array of trial rows")
    from pathlib import Path as _P
    appended = 0
    papers = set()
    try:
        for row in rows:
            written = _append_row_nosummary(dict(row), repo_root=repo_root)
            papers.add(written["paper"])
            appended += 1
    finally:
        root = _P(repo_root) if repo_root else _P.cwd()
        for paper in papers:
            regenerate_summary(lc.db_dir(root, "error", paper))
    return {"appended": appended, "of": len(rows), "papers": sorted(papers)}


def _append_row_nosummary(row, *, repo_root=None):
    root = Path(repo_root) if repo_root else Path.cwd()
    row.setdefault("timestamp", utc_now_iso())
    row.setdefault("git_commit", git_commit_short(root))
    validate(row)
    adm.check_actor_role(row, root)
    if row.get("node_id") and "node_seq" not in row:
        existing = read_entries(root, row["paper"])
        row["node_seq"] = 1 + sum(1 for r in existing if r.get("node_id") == row.get("node_id"))
    db_dir = lc.db_dir(root, "error", row["paper"])
    db_dir.mkdir(parents=True, exist_ok=True)
    lc.chain_append(db_dir, "trials.jsonl", row)
    return row


def regenerate_summary(db_dir: Path) -> None:
    lc.regenerate_summary(db_dir, "trials.jsonl", _SUMMARY_ORDER)


def read_entries(repo_root: str | Path | None, paper: str) -> list[dict[str, Any]]:
    """Read trials.jsonl for a paper. Returns [] if missing."""
    return lc.read_jsonl(repo_root, "error", paper, "trials.jsonl")


def node_trials(paper: str, node_id: str, *, repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    """The doubly-linked list of trials under a DAG node, in append order
    (`node_seq` 1..n). Trials attach under the node rather than minting new nodes."""
    return [r for r in read_entries(repo_root, paper) if r.get("node_id") == node_id]


# --- HTML render -------------------------------------------------------------

# Per-row status tints; the rest of the ledger CSS + the table JS are shared
# (ledger_common.ledger_css / LEDGER_JS).
_STATUS_CSS = """tr.pass{background:#effff0}
tr.fail{background:#fff1f1}
tr.crash{background:#ffe2e2}
tr.partial{background:#fffae0}
tr.amended{background:#f2f2f2;color:#777}
"""

_HTML_CSS = lc.ledger_css(_STATUS_CSS)
_HTML_JS = lc.LEDGER_JS

_esc = lc.esc_cell  # cells render bools via str() ("True"/"False")


def _metric_cell(row: dict[str, Any]) -> str:
    m = row.get("metric") or {}
    if not m:
        return _esc(None)
    name = m.get("name", "")
    val = m.get("value", "")
    thr = m.get("threshold", "")
    p = "✓" if m.get("pass") else "✗"
    return f'<span class="cell-mono">{_esc(name)}={_esc(val)} / {_esc(thr)} {p}</span>'


def render_html(paper: str, *, repo_root: str | Path | None = None,
                output_path: str | Path | None = None) -> Path:
    """Render the per-paper ledger to a self-contained HTML page at
    `results/views/error/paper_<paper>.html` (or a custom path).
    Returns the written path. Raises ValueError if no entries exist."""
    rows = read_entries(repo_root, paper)
    if not rows:
        raise ValueError(f"no entries for paper={paper!r} in error-database/")
    root = Path(repo_root) if repo_root else Path.cwd()
    out = Path(output_path) if output_path else root / "results" / "views" / "error" / f"paper_{paper}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_build_error_html(paper, rows), encoding="utf-8")
    return out


def _build_error_html(paper: str, rows: list[dict[str, Any]]) -> str:
    n = len(rows)
    by_pf: dict[str, int] = {}
    by_mode: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for r in rows:
        by_pf[r.get("pass_fail", "?")] = by_pf.get(r.get("pass_fail", "?"), 0) + 1
        if r.get("failure_mode"):
            by_mode[r["failure_mode"]] = by_mode.get(r["failure_mode"], 0) + 1
        if r.get("domain"):
            by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
    summary_parts = [
        f"<span><strong>total</strong> {n}</span>",
        *[f"<span><strong>{k}</strong> {v}</span>" for k, v in sorted(by_pf.items())],
    ]
    if by_domain:
        summary_parts.append("<span><strong>domains</strong> " +
                             ", ".join(f"{k}:{v}" for k, v in sorted(by_domain.items())) + "</span>")
    if by_mode:
        top = sorted(by_mode.items(), key=lambda kv: -kv[1])[:5]
        summary_parts.append("<span><strong>top failure_modes</strong> " +
                             ", ".join(f"{k}:{v}" for k, v in top) + "</span>")
    summary = "<div class='summary'>" + "".join(summary_parts) + "</div>"

    cols = ("timestamp", "iteration", "task_id", "stage", "domain", "change_type",
            "metric", "pass_fail", "failure_mode", "change_summary", "root_cause")
    head = "".join(f"<th>{c}</th>" for c in cols)
    body_rows: list[str] = []
    for r in rows:
        cls = r.get("pass_fail", "")
        cells = [
            _esc(r.get("timestamp")),
            _esc(r.get("iteration")),
            _esc(r.get("task_id")),
            _esc(r.get("stage")),
            _esc(r.get("domain")),
            _esc(r.get("change_type")),
            _metric_cell(r),
            _esc(r.get("pass_fail")),
            _esc(r.get("failure_mode")),
            f'<div class="cell-wrap">{_esc(r.get("change_summary"))}</div>',
            f'<div class="cell-wrap">{_esc(r.get("root_cause"))}</div>',
        ]
        body_rows.append(f"<tr class='{cls}'>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    body = "".join(body_rows)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>error_database — paper_{_esc(paper)}</title>
<style>{_HTML_CSS}</style></head>
<body>
<h1>Error Database — <span class="cell-mono">paper_{_esc(paper)}</span></h1>
<p class="subtitle">Append-only trial ledger. Schema: <span class="cell-mono">python _common/error_database.py describe-fields</span>. Click any column header to sort; type in the search box to filter.</p>
{summary}
<div class="controls"><input id="search" class="search" type="text" placeholder="filter rows (substring match across all columns)…"></div>
<table id="rows"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
<script>{_HTML_JS}</script>
</body></html>
"""


# --- CLI ---------------------------------------------------------------------

SCHEMA_SUMMARY = """error_database — compact reference

REQUIRED fields:  {required}
AUTO-FILLED:      {auto}
REQUIRED if pass_fail in {{fail,crash,partial}}: {on_fail}

enums:
  domain       = {domains}
  stage        = {stages}
  change_type  = {change_types}
  pass_fail    = {pass_fail}
  regime_split = {regime_splits}

per-domain reference (tags+meanings, metrics, meta keys, evidence paths):
  python _common/error_database.py describe-domain --domain <D>
per-field meanings:
  python _common/error_database.py describe-fields
"""


def _schema_text() -> str:
    return SCHEMA_SUMMARY.format(
        required=sorted(REQUIRED_FIELDS),
        auto=sorted(AUTO_FILLED),
        on_fail=sorted(REQUIRED_ON_FAIL),
        domains=DOMAINS, stages=STAGES,
        change_types=CHANGE_TYPES, pass_fail=PASS_FAIL,
        regime_splits=REGIME_SPLITS,
    )


def _describe_domain(domain: str) -> str:
    if domain not in DOMAINS:
        raise ValueError(f"domain={domain!r} not in {DOMAINS}")
    tags = FAILURE_MODES_BY_DOMAIN[domain]
    meanings = FAILURE_MODE_MEANINGS[domain]
    metrics = METRIC_NAMES_BY_DOMAIN[domain]
    meta_keys = RECOMMENDED_RUNTIME_METADATA[domain]
    ev = EVIDENCE_PATH_TEMPLATES[domain]

    lines = [f"error_database: {domain} domain reference", ""]

    lines.append(f"failure_mode tags ({len(tags)}):")
    width = max(len(t) for t in tags)
    for t in tags:
        lines.append(f"  {t:<{width}}  {meanings[t]}")
    lines.append("")

    lines.append(f"recommended metric.name ({len(metrics)}):")
    width = max(len(m) for m in metrics)
    for m, meaning in metrics.items():
        lines.append(f"  {m:<{width}}  {meaning}")
    lines.append("")

    lines.append("recommended runtime_metadata keys:")
    lines.append(f"  {', '.join(meta_keys)}")
    lines.append("")

    lines.append("evidence-path template (fail/partial rows):")
    lines.append(f"  {ev['root']}")
    files = ev["files"]
    for i, (fname, desc) in enumerate(files):
        connector = "└──" if i == len(files) - 1 else "├──"
        lines.append(f"  {connector} {fname:<24} # {desc}")
    lines.append("")

    lines.append(
        f"self-correction: log unfit failure as 'uncategorized_{domain}' once "
        "with rationale in `notes` and a candidate tag in `next_hypothesis`. "
        "On second instance, edit this module — append to "
        f"FAILURE_MODES_{domain.upper()} tuple and FAILURE_MODE_MEANINGS"
        f"['{domain}'] dict — and commit. See module docstring § SELF-CORRECTION."
    )
    return "\n".join(lines) + "\n"


def _describe_fields() -> str:
    sections = [
        ("required (every row)",
         [f for f in FIELD_DESCRIPTIONS if f in REQUIRED_FIELDS or f in AUTO_FILLED]),
        ("required when pass_fail in {fail,crash,partial}",
         [f for f in FIELD_DESCRIPTIONS if f in REQUIRED_ON_FAIL]),
        ("optional / recommended",
         [f for f in FIELD_DESCRIPTIONS
          if f not in REQUIRED_FIELDS and f not in REQUIRED_ON_FAIL and f not in AUTO_FILLED]),
    ]
    width_n = max(len(n) for n in FIELD_DESCRIPTIONS)
    width_t = max(len(t) for t, _ in FIELD_DESCRIPTIONS.values())
    lines: list[str] = []
    for title, names in sections:
        lines.append(f"# {title}")
        for n in names:
            t, m = FIELD_DESCRIPTIONS[n]
            lines.append(f"  {n:<{width_n}}  {t:<{width_t}}  {m}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _describe_tag(domain: str, tag: str) -> str:
    if domain not in DOMAINS:
        raise ValueError(f"domain={domain!r} not in {DOMAINS}")
    if tag not in FAILURE_MODE_MEANINGS[domain]:
        allowed = list(FAILURE_MODE_MEANINGS[domain].keys())
        raise ValueError(f"tag={tag!r} not a {domain} failure_mode; allowed: {allowed}")
    return f"{domain}/{tag}\n  {FAILURE_MODE_MEANINGS[domain][tag]}\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="error_database")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schema", help="print compact schema summary")
    sub.add_parser("describe-fields", help="per-field semantics (required / on-fail / optional)")
    lt = sub.add_parser("list-tags", help="list failure_mode tags for a domain")
    lt.add_argument("--domain", required=True, choices=DOMAINS)
    dd = sub.add_parser("describe-domain", help="per-domain reference: tags + meanings, metrics, meta keys, evidence paths")
    dd.add_argument("--domain", required=True, choices=DOMAINS)
    dt = sub.add_parser("describe-tag", help="describe one failure_mode tag")
    dt.add_argument("--domain", required=True, choices=DOMAINS)
    dt.add_argument("--tag", required=True)
    ap_app = sub.add_parser("append", help="validate + append a JSON row from stdin or file")
    ap_app.add_argument("--row-file", type=Path, help="read row JSON from file (default: stdin)")
    ap_app.add_argument("--repo-root", type=Path, default=None)

    ab = sub.add_parser("append-batch", help="packet flush: validate + append a JSON array; summary regenerated once")
    ab.add_argument("--rows-file", type=Path, help="JSON array of rows (default: stdin)")
    ab.add_argument("--repo-root", type=Path, default=None)
    rs = sub.add_parser("regenerate-summary", help="regenerate summary.csv for a paper dir")
    rs.add_argument("paper_dir", type=Path)
    rh = sub.add_parser("render-html",
                        help="render a self-contained HTML view at results/views/error/paper_<P>.html")
    rh.add_argument("--paper", required=True)
    rh.add_argument("--output", type=Path, default=None,
                    help="custom output path (default: results/views/error/paper_<paper>.html)")
    rh.add_argument("--repo-root", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.cmd == "schema":
        sys.stdout.write(_schema_text())
        return 0
    if args.cmd == "describe-fields":
        sys.stdout.write(_describe_fields())
        return 0
    if args.cmd == "list-tags":
        for tag in FAILURE_MODES_BY_DOMAIN[args.domain]:
            print(tag)
        return 0
    if args.cmd == "describe-domain":
        sys.stdout.write(_describe_domain(args.domain))
        return 0
    if args.cmd == "describe-tag":
        sys.stdout.write(_describe_tag(args.domain, args.tag))
        return 0
    if args.cmd == "append-batch":
        raw = args.rows_file.read_text() if args.rows_file else sys.stdin.read()
        print(json.dumps(append_batch(json.loads(raw), repo_root=args.repo_root)))
        return 0
    if args.cmd == "append":
        raw = args.row_file.read_text() if args.row_file else sys.stdin.read()
        row = json.loads(raw)
        written = append_row(row, repo_root=args.repo_root)
        print(json.dumps({"appended": True, "git_commit": written["git_commit"],
                          "timestamp": written["timestamp"]}))
        return 0
    if args.cmd == "regenerate-summary":
        regenerate_summary(args.paper_dir)
        return 0
    if args.cmd == "render-html":
        out = render_html(args.paper, repo_root=args.repo_root, output_path=args.output)
        print(json.dumps({"rendered": True, "paper": args.paper, "path": str(out)}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
