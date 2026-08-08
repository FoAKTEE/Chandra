"""loop_policy — read-only ledger queries for agent loop control.

Implements two policies from the autoresearch / learning-beyond-gradients
audit (see ref-code/AUDIT_NOTES.md, items #5 and #6):

  * Crash triage (#6) — alignment.md §0 "no parameter-tweak loops".
    Reads the last N failing rows for a task and recommends fix_and_retry,
    pivot_structural, or escalation. Encodes the "three cycles of the
    same idea auto-escalates severity" rule.

  * Simplification status (#5) — autoresearch atari57 §8.
    After a best-metric refresh (a non-refactor pass row), a
    change_type='refactor' pass row is owed before the promise-tag commit.
    Returns no_refresh / required / ok.

USAGE
    python _common/loop_policy.py crash-triage          --paper P --task T [--domain D]
    python _common/loop_policy.py simplification-status --paper P --task T [--domain D] [--metric-name M]
    python _common/loop_policy.py check-pivot           --paper P --task T --change-type {structural,scalar,refactor} [--domain D]
    python _common/loop_policy.py describe-domain       --domain {symbolic,numerical,proof}
    python _common/loop_policy.py paper-refresh         --paper P [--every N] [--since L]

For the static AI-coding-session policy (risk tiers, workflow, KISS/DRY/AHA,
merge-gate, anti-patterns), see the sibling module:

    python _common/code_quality.py [--section S]

The state machines (no_action -> fix_and_retry -> pivot_structural ->
escalation; no_refresh -> required -> ok) are domain-agnostic. When
`--domain D` is supplied:
  * crash-triage / check-pivot include a domain-specific pivot hint with
    pivot_structural and escalation recommendations (what counts as
    "structural" varies between Mathematica, Python/Julia/C/C++, and proof assistants).
  * simplification-status, when `required`, includes the per-domain
    recipe (cost_metric, actions, anti-patterns).
  * describe-domain prints the recipe + pivot hint alone, for orientation.

All commands are pure reads over error-database/paper_<P>/trials.jsonl —
    no writes, no side effects. The trial-log schema is owned by error_database.py;
this module only consumes its output.

The agent typically calls:
  1. `check-pivot --domain D` before crafting the next row — if blocked,
      switch to structural change or run acquisition per alignment.md §3.
  2. `simplification-status --domain D` before issuing the promise-tag commit
     — if required, append a refactor pass first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _common.ledgers import ledger_common as lc

PIVOT_WINDOW = 3  # alignment.md §0: three cycles of the same idea auto-escalates

PAPER_REFRESH_EVERY = 5  # iterations between living-paper regenerations (pipelines/3-write)

DOMAINS = ("symbolic", "numerical", "proof")

# --- per-domain reference (parallel to error_database.FAILURE_MODE_MEANINGS) ---

SIMPLIFICATION_RECIPES: dict[str, dict[str, Any]] = {
    "symbolic": {
        "cost_metric": "expression size — LeafCount / ByteCount of the certified result",
        "actions": (
            "drop unused ReplaceAll rules and Assuming[] wrappers",
            "consolidate Module/Block scopes; remove intermediate variables no longer load-bearing",
            "preserve the certified simplify_equals_zero residue (or series_order_match)",
            "drop dangling negative_control.wl experiments once the main path is settled",
        ),
        "anti_patterns": (
            "introducing new TimeConstrained wrappers to mask kernel cost",
            "broadening $Assumptions to make FullSimplify close (assumption_too_broad)",
        ),
    },
    "numerical": {
        "cost_metric": "editable-module line count — git diff --shortstat insertions vs the pre-refresh commit",
        "actions": (
            "drop dead branches and unused state machines from search/sweep code",
            "inline single-call-site helpers; factor out helpers used 3+ times",
            "consolidate redundant parameter sweeps that no longer add info",
            "preserve the primary metric (max_rel_error / closure_residual / convergence_order)",
        ),
        "anti_patterns": (
            "raising tolerances or relaxing eval — that's not simplification, that's regression",
            "deleting sanity-check tests instead of fixing them",
        ),
    },
    "proof": {
        "cost_metric": "compiled proof-object size or build-artifact byte count",
        "actions": (
            "replace verbose proof blocks with shorter checked proof steps where the goal shape allows",
            "factor common lemmas; drop one-off helpers that survived the search",
            "tighten global options and classical assumptions to minimum scope",
            "preserve proof_closes=true and the agreed assumptions_baseline",
        ),
        "anti_patterns": (
            "adding admitted placeholders to make the refactor build pass",
            "introducing new assumptions outside assumptions_baseline (assumption_creep)",
        ),
    },
}

CRASH_PIVOT_HINTS: dict[str, str] = {
    "symbolic": ("switch derivation route — different normal form, different source-slot convention, "
                 "different starting identity. Pure $Assumptions changes do not count as structural."),
    "numerical": ("switch numerical method — implicit ↔ explicit integrator, FD ↔ spectral, "
                  "direct mode-sum ↔ contour deformation. Pure mesh / tolerance / step-size changes "
                  "do not count as structural."),
    "proof": ("switch proof strategy — induction to stronger induction, automated decision to manual lemma, "
              "classical to constructive, or single lemma to a mutually dependent block. "
              "Small rewrite-rule additions do not count as structural."),
}



# --- helpers -----------------------------------------------------------------

def _read_entries(repo_root: str | Path | None, paper: str) -> list[dict[str, Any]]:
    """Read error-database/paper_<paper>/trials.jsonl. Returns [] if missing."""
    return lc.read_jsonl(repo_root, "error", paper, "trials.jsonl")


def _task_rows(entries: list[dict[str, Any]], task_id: str) -> list[dict[str, Any]]:
    return [r for r in entries if r.get("task_id") == task_id]


# --- #6 crash triage ---------------------------------------------------------

def crash_triage(paper: str, task_id: str, *,
                 repo_root: str | Path | None = None,
                 window: int = PIVOT_WINDOW,
                 domain: str | None = None) -> dict[str, Any]:
    """Walk the last `window` failing rows for (paper, task_id); recommend
    fix_and_retry vs pivot_structural vs escalation. If `domain` is given,
    pivot/escalation recommendations include a domain-specific hint
    explaining what counts as "structural" for that tooling.
    """
    if domain is not None and domain not in DOMAINS:
        raise ValueError(f"domain={domain!r} not in {DOMAINS}")
    failing = [
        r for r in _task_rows(_read_entries(repo_root, paper), task_id)
        if r.get("pass_fail") in ("fail", "crash", "partial")
    ]
    if not failing:
        return {"recommendation": "no_action",
                "reason": "no failing rows for this task"}
    recent = failing[-window:]
    modes = [r.get("failure_mode") for r in recent]
    if len(recent) == 1:
        return {"recommendation": "fix_and_retry",
                "reason": "first failure on this task — debug and retry",
                "last_failure_mode": modes[0]}
    same = len(set(modes)) == 1 and modes[0] is not None

    def _with_hint(result: dict[str, Any]) -> dict[str, Any]:
        if domain is not None:
            result["domain_hint"] = CRASH_PIVOT_HINTS[domain]
        return result

    if same and len(recent) >= window:
        return _with_hint({
            "recommendation": "escalation",
            "reason": f"{window} consecutive failures with failure_mode={modes[0]!r}; "
                      "alignment.md §0 + §3 — switch methodology entirely",
            "last_failure_mode": modes[0],
            "consecutive_same_mode": len(recent),
        })
    if same:
        return _with_hint({
            "recommendation": "pivot_structural",
            "reason": f"{len(recent)} consecutive failures with same failure_mode "
                      f"{modes[0]!r}; next row must be change_type='structural'",
            "last_failure_mode": modes[0],
            "consecutive_same_mode": len(recent),
        })
    return {"recommendation": "fix_and_retry",
            "reason": "different failure modes — each is a distinct bug; fix the latest",
            "recent_failure_modes": modes}


def check_pivot(paper: str, task_id: str, proposed_change_type: str, *,
                repo_root: str | Path | None = None,
                window: int = PIVOT_WINDOW,
                domain: str | None = None) -> dict[str, Any]:
    """Verdict on whether the proposed next row would violate the no-
    parameter-tweak-loops rule. Pure read; caller decides whether to honor.
    """
    if proposed_change_type == "structural":
        return {"verdict": "ok",
                "reason": "structural changes are always allowed (the escape hatch)"}
    triage = crash_triage(paper, task_id, repo_root=repo_root,
                          window=window, domain=domain)
    if triage["recommendation"] in ("pivot_structural", "escalation"):
        return {"verdict": "blocked",
                "reason": triage["reason"],
                "triage": triage}
    return {"verdict": "ok", "triage": triage}


# --- #5 simplification status -----------------------------------------------

def simplification_status(paper: str, task_id: str, *,
                          metric_name: str | None = None,
                          repo_root: str | Path | None = None,
                          domain: str | None = None) -> dict[str, Any]:
    """Is a `change_type='refactor'` simplification pass owed since the last
    best-metric refresh?

    State machine:
      - no_refresh: no non-refactor pass row yet for this task
      - required:   latest non-refactor pass row is not followed by a refactor
                    pass that maintains the metric
      - ok:         a refactor pass at the same metric.name follows the latest
                    non-refactor pass row
    """
    if domain is not None and domain not in DOMAINS:
        raise ValueError(f"domain={domain!r} not in {DOMAINS}")
    task = _task_rows(_read_entries(repo_root, paper), task_id)
    pass_rows = [r for r in task if r.get("metric", {}).get("pass")]
    if metric_name:
        pass_rows = [r for r in pass_rows if r["metric"]["name"] == metric_name]
    # Refactor passes close the phase; only non-refactor passes trigger it.
    refresh_rows = [r for r in pass_rows if r.get("change_type") != "refactor"]
    if not refresh_rows:
        return {"status": "no_refresh",
                "reason": "no non-refactor pass row yet for this task"}
    best = max(refresh_rows, key=lambda r: r["iteration"])
    best_iter = best["iteration"]
    best_metric = best["metric"]["name"]
    later = [r for r in task if r["iteration"] > best_iter]
    refactor_passes = [
        r for r in later
        if r.get("change_type") == "refactor"
        and r.get("metric", {}).get("pass")
        and r["metric"]["name"] == best_metric
    ]
    if refactor_passes:
        return {"status": "ok",
                "best_iteration": best_iter,
                "best_metric_value": best["metric"]["value"],
                "metric_name": best_metric,
                "simplification_iteration": refactor_passes[-1]["iteration"]}
    result: dict[str, Any] = {
        "status": "required",
        "best_iteration": best_iter,
        "best_metric_value": best["metric"]["value"],
        "metric_name": best_metric,
        "recommendation": "before the next promise-tag commit, append a "
                          "change_type='refactor' row that maintains the metric; "
                          "revert if it drops.",
    }
    if domain is not None:
        result["recipe"] = SIMPLIFICATION_RECIPES[domain]
    return result


# --- living-paper refresh cadence (pipelines/3-write) ----------------------

def paper_refresh_due(paper: str, *,
                      every: int = PAPER_REFRESH_EVERY,
                      since: int | None = None,
                      repo_root: str | Path | None = None) -> dict[str, Any]:
    """Is a living-paper regeneration owed for this paper? Pure read of the
    error ledger's iteration counter — pipelines/3-write regenerates the
    PRD-style paper draft (from the knowledge ledger's solid rows + figures)
    every `every` iterations and at termination.

    `since` = the iteration the paper was last generated at; read it from the
    generated paper's `GENERATION_LOG` (under the consumer's
    `results/<project>/paper_<arxiv>/paper/`). When given, due once `every` iterations have
    elapsed since then — robust to a check that lands off a multiple. When
    omitted, falls back to a stateless modular `latest % every == 0` check.
    """
    if every <= 0:
        raise ValueError(f"--every must be a positive int, got {every}")
    latest = lc.max_iteration(_read_entries(repo_root, paper))
    if latest is None:
        return {"due": False, "latest_iteration": None, "every": every,
                "reason": "no iterations logged in the error ledger yet"}
    if since is not None:
        elapsed = latest - since
        due = elapsed >= every
        return {"due": due, "latest_iteration": latest, "since": since,
                "iterations_since_generation": elapsed, "every": every,
                "next_due_iteration": since + every,
                "reason": (f"{elapsed} iters since last generation (>= {every}) — regenerate"
                           if due else
                           f"only {elapsed} of {every} iters since last generation")}
    due = latest % every == 0
    return {"due": due, "latest_iteration": latest, "every": every,
            "next_due_iteration": (latest // every + 1) * every,
            "reason": (f"iteration {latest} is a multiple of {every} — regenerate"
                       if due else f"iteration {latest} is not a multiple of {every}")}


def describe_domain(domain: str) -> str:
    """Print the per-domain simplification recipe and crash-pivot hint."""
    if domain not in DOMAINS:
        raise ValueError(f"domain={domain!r} not in {DOMAINS}")
    recipe = SIMPLIFICATION_RECIPES[domain]
    pivot = CRASH_PIVOT_HINTS[domain]
    lines = [f"loop_policy: {domain} domain reference", ""]
    lines.append("simplification recipe (run after best-metric refresh):")
    lines.append(f"  cost_metric: {recipe['cost_metric']}")
    lines.append("  actions:")
    for a in recipe["actions"]:
        lines.append(f"    - {a}")
    lines.append("  anti-patterns:")
    for a in recipe["anti_patterns"]:
        lines.append(f"    - {a}")
    lines.append("")
    lines.append("crash-triage structural pivot hint:")
    lines.append(f"  {pivot}")
    return "\n".join(lines) + "\n"


# --- CLI ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="loop_policy")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ct = sub.add_parser("crash-triage", help="fix_and_retry vs pivot_structural vs escalation")
    ct.add_argument("--paper", required=True)
    ct.add_argument("--task", required=True, dest="task_id")
    ct.add_argument("--domain", choices=DOMAINS, default=None,
                    help="if given, include the domain-specific pivot hint in pivot/escalation recommendations")
    ct.add_argument("--repo-root", type=Path, default=None)
    ct.add_argument("--window", type=int, default=PIVOT_WINDOW)

    ss = sub.add_parser("simplification-status",
                        help="is a refactor pass owed since the last best-metric refresh?")
    ss.add_argument("--paper", required=True)
    ss.add_argument("--task", required=True, dest="task_id")
    ss.add_argument("--domain", choices=DOMAINS, default=None,
                    help="if given, include the domain-specific simplification recipe when status=required")
    ss.add_argument("--metric-name", default=None)
    ss.add_argument("--repo-root", type=Path, default=None)

    cp = sub.add_parser("check-pivot",
                        help="would the proposed change_type violate the no-tweak-loops rule?")
    cp.add_argument("--paper", required=True)
    cp.add_argument("--task", required=True, dest="task_id")
    cp.add_argument("--change-type", required=True, choices=("structural", "scalar", "refactor"))
    cp.add_argument("--domain", choices=DOMAINS, default=None)
    cp.add_argument("--repo-root", type=Path, default=None)
    cp.add_argument("--window", type=int, default=PIVOT_WINDOW)

    dd = sub.add_parser("describe-domain",
                        help="print the simplification recipe + crash-pivot hint for one domain")
    dd.add_argument("--domain", required=True, choices=DOMAINS)

    pf = sub.add_parser("paper-refresh",
                        help="is a living-paper regeneration owed? (every N iters; pipelines/3-write)")
    pf.add_argument("--paper", required=True)
    pf.add_argument("--every", type=int, default=PAPER_REFRESH_EVERY,
                    help=f"iterations between regenerations (default {PAPER_REFRESH_EVERY})")
    pf.add_argument("--since", type=int, default=None,
                    help="iteration the paper was last generated at (from the paper's GENERATION_LOG); "
                         "omit for a stateless modular every-N check")
    pf.add_argument("--repo-root", type=Path, default=None)

    args = ap.parse_args(argv)
    if args.cmd == "crash-triage":
        result = crash_triage(args.paper, args.task_id,
                              repo_root=args.repo_root, window=args.window,
                              domain=args.domain)
    elif args.cmd == "simplification-status":
        result = simplification_status(args.paper, args.task_id,
                                       metric_name=args.metric_name,
                                       repo_root=args.repo_root,
                                       domain=args.domain)
    elif args.cmd == "check-pivot":
        result = check_pivot(args.paper, args.task_id, args.change_type,
                             repo_root=args.repo_root, window=args.window,
                             domain=args.domain)
    elif args.cmd == "describe-domain":
        sys.stdout.write(describe_domain(args.domain))
        return 0
    elif args.cmd == "paper-refresh":
        result = paper_refresh_due(args.paper, every=args.every,
                                   since=args.since, repo_root=args.repo_root)
    else:
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
