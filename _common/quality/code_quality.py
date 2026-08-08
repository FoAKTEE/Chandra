"""code_quality — AI coding session policy as queryable Python.

Static binding policy, embedded as printable section blobs keyed by
`--section`. Agents call this module instead of reading a markdown wall;
each section can be pulled independently to keep token cost proportional
to the question.

This is the static counterpart to `loop_policy.py`, which carries the
LIVE-LEDGER queries (`crash-triage`, `simplification-status`,
`check-pivot`, `describe-domain`). The two modules share no state and
have different change drivers — code-quality policy evolves with
PR-review practice; loop_policy evolves with the error-database schema.

USAGE
    python _common/code_quality.py --list                  # print the bundle index
    python _common/code_quality.py --bundle orientation    # ~43 lines: session start
    python _common/code_quality.py --bundle intake         # ~39 lines: task intake
    python _common/code_quality.py --bundle abstraction    # ~65 lines: KISS/DRY/AHA + checklist
    python _common/code_quality.py --bundle review         # ~84 lines: PR review + merge gate
    python _common/code_quality.py --section <name>        # drill-down to one atomic section
    python _common/code_quality.py                          # equivalent to --bundle all

The bundle is the primary unit. Each one is a coherent prompt for one
read-moment — load it once, work from it, then drop it. Avoid `--bundle all`
(or no-arg) except for archival reads; pulling the whole policy every time
defeats the bundling.

Bundles (in canonical order):
    orientation  intro, principles, bad-metrics, target-state
    intake       tiers, workflow
    abstraction  kiss-dry-aha, aha-checklist
    review       severity, lenses, finding-schema, merge-gate, anti-patterns

The dict content is verbatim from the source policy; any rewording must
be explicit in the diff. The tuple `CODE_QUALITY_SECTION_ORDER` defines
the canonical ordering for `--section all` (the default).
"""

from __future__ import annotations

import argparse
import sys

CODE_QUALITY_SECTIONS: dict[str, str] = {
    "intro": """\
# AI CODING SESSION POLICY — MANDATORY

STATUS: BINDING. Load this before any working session. Every rule below is
non-negotiable unless the human owner explicitly overrides it in writing
within the session. Optimize for BETTER code, NEVER for MORE code.
""",
    "principles": """\
## OPERATING PRINCIPLES — MUST FOLLOW

- MUST treat all AI output as DRAFT. NEVER merge unverified output.
- MUST prefer small, well-understood changes. NEVER produce large opaque diffs.
- MUST slow down and escalate on: auth, migrations, concurrency, money,
  security, public APIs, data loss, perf-critical paths.
- MUST run independent reviewers in ISOLATION on the first pass. NEVER let
  reviewers see each other's findings before they finish.
- MUST treat agent consensus as a PRIORITIZATION signal only. NEVER treat
  consensus as proof.
- MUST validate lone-dissenter findings on high-impact code. NEVER dismiss a
  finding because only one reviewer flagged it.
- MUST attach reproducible evidence (failing test, trace, query plan, PoC)
  to every serious finding. NEVER accept "looks wrong" as a finding.
- MUST require the human owner to explain the change end-to-end. If they
  cannot, the PR is NOT READY.
- MUST embed security review in normal review. NEVER defer to a final audit.
- MUST balance KISS / DRY / AHA. NEVER abstract before the shared concept is
  stable and named.
- NEVER spend review attention on lint-grade nits, formatting, personal style.
- NEVER add features, refactors, error handling, or abstractions beyond what
  the task requires.
""",
    "tiers": """\
## RISK TIERS — MUST CLASSIFY BEFORE CODING

  R0  docs, typos                                       self + CI
  R1  isolated helper, local UI copy                    self + tests + 1 reviewer
  R2  normal feature/fix                                multi-lens AI review + human review
  R3  auth, migration, concurrency, public API          independent multi-agent + security/perf lens + rollback plan
  R4  crypto, irreversible migration, safety-critical   threat model + staged rollout + explicit approval

MUST ESCALATE when: touches authz, data deletion/migration, concurrency,
money/safety/legal, or the author cannot explain the change.
""",
    "workflow": """\
## WORKFLOW — MUST EXECUTE IN ORDER

Each phase has a GATE. NEVER advance past a gate marked BLOCKED.

 1. INTAKE.            Problem, non-goals, risk tier, rollback, owner — all five explicit.
 2. GRILL DESIGN (R2+) Resolve hidden assumptions; inspect codebase before asking.
 3. MAP CODEBASE.      Entry points, call chains, data flows, existing tests, schemas, perms.
 4. PLAN SMALLEST SLICE. One purpose per PR. Define rollback. Split if too broad.
 5. IMPLEMENT WITH TESTS. Regression test per bug fix. Negative tests for security paths.
                        Dry-run plan for migrations.
 6. SELF-REVIEW.       Owner reviews their own PR before requesting any other review.
 7. INDEPENDENT AI REVIEW. ≥2 for R2+, ≥3 for R3+. Reviewers isolated. Lenses listed below.
 8. SYNTHESIZE AND VALIDATE. Compile findings before judging. Deduplicate. Validate against
                        source/runtime evidence. Record dismissals with rationale.
 9. REPAIR LOOP.       Fix critical/high first. Rerun tests AND review. If fixes balloon,
                        STOP and reconsider the design.
10. COMPREHENSION CHECK. Owner explains intent, flow changes, invariants, edge cases,
                        failure modes, rollback, monitoring.
11. MERGE DECISION.    Exactly one of:
                        - READY_TO_MERGE      no unresolved critical/high; rollback acceptable
                        - MERGE_AFTER_FIXES   bounded fixes remain; approach sound
                        - NEEDS_REWORK        systemic problems in design or implementation
                        - ABANDON             plan is wrong, unsafe, or not worth the cost
12. POST-MERGE.        Every confirmed critical/high → regression test, checklist update,
                        or reusable heuristic.
""",
    "severity": """\
## SEVERITY POLICY — MUST ENFORCE

- CRITICAL (security compromise, data loss, irreversible failure, safety):
    MUST FIX OR ABANDON. NEVER merge.
- HIGH (incorrect behavior in realistic cases, broken flows, serious perf
  regression, missing tests for important behavior):
    MUST FIX BEFORE MERGE unless an accountable owner explicitly accepts the
    risk in writing.
- MEDIUM (bounded impact, maintainability decay, unreachable edge case):
    SHOULD FIX if cheap; otherwise file a follow-up with owner and deadline.
- LOW (readability, minor nits):
    MUST NOT BLOCK MERGE.
""",
    "kiss-dry-aha": """\
## KISS / DRY / AHA — MUST BALANCE EXPLICITLY

These three principles pull in different directions. Treat them as a system.
NEVER cite one in isolation to justify a change.

KISS — Keep It Simple, Stupid
  Simplest design that correctly solves the CURRENT problem wins.
  MUST: straight-line code; concrete types until a 2nd concrete use case;
        one function = one thing; standard library / existing patterns;
        inline once, name twice, extract only when the name adds info.
  NEVER: configuration / hooks / plugins "in case we need them later";
         new layer without a current concrete reason ≥ 2 callers cite;
         defensive code for impossible inputs; try/except for cases that
         cannot occur; drive-by refactors outside the stated task.
  Failure signal: trace 3+ files to understand 10 lines → KISS violated.

DRY — Don't Repeat Yourself (about KNOWLEDGE, not characters)
  Same business rule / invariant / constant in multiple places = duplication.
  Similar shape that encodes DIFFERENT decisions ≠ duplication.
  MUST: dedupe when same decision appears; centralize values that must agree;
        treat 3rd occurrence as the signal — not the 2nd.
  NEVER: dedupe on syntactic similarity alone; dedupe across domain
         boundaries; build a "utils"/"helpers"/"common" dumping ground;
         dedupe test setup so aggressively a test can't be read on its own.
  Failure signal: abstraction needs flags / optional params / `if mode == "X"`
  branches to preserve old callers → fused things that should be separate.

AHA — Avoid Hasty Abstractions
  Wrong abstractions are MORE expensive than duplication.
  MUST: duplicate first, abstract later (3rd occurrence is earliest, 4th often
        better); wait until the shared concept has a stable, domain-meaningful
        NAME; verify candidate sites share the same REASON TO CHANGE;
        prefer copy-paste-and-edit during exploration; delete the original
        duplication when extracting.
  NEVER: abstract on 2nd occurrence; abstract because a reviewer said "looks
         similar"; design around hypothetical future callers; keep a wrong
         abstraction alive by adding params/flags — INLINE IT BACK.
  Failure signal — abstraction is wrong if ANY hold:
    - Callers pass flags/booleans/modes to opt in or out.
    - Signature grows with each new caller.
    - Most callers use only a subset of parameters.
    - Name describes mechanism ("Manager", "Helper", "Processor"), not domain.
    - Bug fix requires per-caller verification.

TIE-BREAKING — apply in this order:
  1. CORRECTNESS wins over all three.
  2. AHA beats DRY. When in doubt, duplicate.
  3. KISS beats DRY. Simple duplication beats clever sharing.
  4. DRY applies only after stable + named + ≥3 real call sites encoding the
     SAME decision.
  5. MUST DOCUMENT the tradeoff in the PR description in non-obvious cases.
""",
    "aha-checklist": """\
## AHA CHECKLIST — MUST RUN BEFORE INTRODUCING ANY ABSTRACTION

  [ ] At least 3 real, current call sites exist                       PASS / FAIL
  [ ] All call sites encode the SAME decision, not just similar shape PASS / FAIL
  [ ] All call sites share the SAME reason to change                  PASS / FAIL
  [ ] The shared concept has a clear domain-meaningful name           PASS / FAIL
  [ ] No caller needs a flag/mode/optional param to use it            PASS / FAIL
  [ ] Original duplicated code is DELETED, not left alongside         PASS / FAIL
  [ ] The abstraction is testable independently of its callers        PASS / FAIL

ANY [FAIL] = MUST NOT ABSTRACT YET. DUPLICATE AND REVISIT LATER.
""",
    "lenses": """\
## REVIEWER LENSES — APPLY THE RELEVANT ONES

- FUNCTIONAL       conditionals, off-by-ones, null handling, error paths,
                   state transitions, input assumptions.
- TESTS            regressions, behavior-not-implementation assertions,
                   untested failure modes, fragile mocks, negative cases.
- SECURITY         authz, injection, deserialization, secrets, deps,
                   insecure defaults, weak crypto, audit logs, privilege
                   escalation, business-logic abuse.
- PERFORMANCE      N+1, accidental O(n²), allocations, batching, query plans,
                   locks, unbounded memory, migration locks.
- CONCURRENCY      races, ordering, shared mutable state, idempotency, retry
                   hazards, stale reads, distributed consistency.
- API COMPATIBILITY breaking schema/semantics, missing deprecation path,
                   client-visible changes.
- ACCESSIBILITY    keyboard, labels, focus, headings, alt text, contrast,
                   color-only state.
- MAINTAINABILITY  unnecessary abstraction, drifting duplication, unclear
                   names, hidden side effects, inconsistency with nearby code.
- DOCS / COMPREHENSION  missing "why", undocumented invariants, runbook gaps.
""",
    "finding-schema": """\
## FINDING SCHEMA — MUST USE

finding:
  severity: CRITICAL|HIGH|MEDIUM|LOW
  status: CONFIRMED|DISMISSED|NEEDS_EVIDENCE
  category: ""
  file: ""
  line: ""
  claim: ""
  why_it_matters: ""
  evidence: ""
  suggested_fix: ""
  confidence: LOW|MEDIUM|HIGH
""",
    "merge-gate": """\
## MERGE GATE CHECKLIST — ALL MUST BE PASS

  [ ] One clear purpose; risk tier explicit              PASS / FAIL
  [ ] Owner self-reviewed                                PASS / FAIL
  [ ] Tests meaningful and passing                       PASS / FAIL
  [ ] Independent review at required depth               PASS / FAIL
  [ ] Critical/high fixed or explicitly risk-accepted    PASS / FAIL
  [ ] Dismissed findings have rationale                  PASS / FAIL
  [ ] Security-sensitive paths got security lens         PASS / FAIL
  [ ] Perf claims have evidence, not guesses             PASS / FAIL
  [ ] Migrations have rollback/recovery                  PASS / FAIL
  [ ] Owner can explain the change front-to-back         PASS / FAIL
  [ ] Rollout and monitoring clear                       PASS / FAIL
  [ ] Follow-ups filed for deferred mediums              PASS / FAIL

OVERALL: READY_TO_MERGE | MERGE_AFTER_FIXES | NEEDS_REWORK | ABANDON
RULE: ANY [FAIL] BLOCKS MERGE.
""",
    "anti-patterns": """\
## ANTI-PATTERNS — MUST REFUSE

- SLOP CANNON              large AI PR, weak tests, shallow review, owner
                           cannot explain it. REJECT OR SPLIT.
- CONSENSUS LAUNDERING     treating agent agreement as proof. REQUIRE EVIDENCE.
- LONE-DISSENTER DISMISSAL ignoring a finding because only one reviewer
                           flagged it. VALIDATE THE FINDING.
- PREMATURE DRY            abstracting before the concept is stable.
                           DUPLICATE TEMPORARILY.
- STYLE-REVIEW DISPLACEMENT burning attention on lint-grade nits.
                           AUTOMATE STYLE; RESERVE REVIEW FOR JUDGMENT.
- UNVALIDATED PERF CLAIM   "should be fast enough" without measurement.
                           REQUIRE QUERY PLAN, BENCHMARK, OR DRY RUN.
- NO ROLLBACK STORY        merging a change that cannot be undone.
                           REQUIRE ROLLBACK, FLAG, OR EXPLICIT RISK ACCEPTANCE.
""",
    "bad-metrics": """\
## BAD METRICS — MUST NOT OPTIMIZE FOR

Lines generated. Prompts sent. Suggestions accepted. Raw PR count.
Superficial coverage bumps. Speed without quality.
""",
    "target-state": """\
## TARGET STATE

AI MUST help understand the problem better, write SMALLER changes, find
DEEPER bugs, validate findings with EVIDENCE, fix critical issues BEFORE
merge, and leave the codebase HEALTHIER.

END OF POLICY. STATUS: ACTIVE.
""",
}


CODE_QUALITY_SECTION_ORDER = (
    "intro", "principles", "tiers", "workflow", "severity",
    "kiss-dry-aha", "aha-checklist", "lenses", "finding-schema",
    "merge-gate", "anti-patterns", "bad-metrics", "target-state",
)

# Bundles: a few refined prompt groups, each loaded as a single prompt for
# one read-moment. The bundle is the primary unit of the CLI; --section is
# the granular fallback.
BUNDLES: dict[str, tuple[str, ...]] = {
    "orientation": ("intro", "principles", "bad-metrics", "target-state"),
    "intake":      ("tiers", "workflow"),
    "abstraction": ("kiss-dry-aha", "aha-checklist"),
    "review":      ("severity", "lenses", "finding-schema", "merge-gate", "anti-patterns"),
}

BUNDLE_ORDER = ("orientation", "intake", "abstraction", "review")

BUNDLE_PURPOSE = {
    "orientation": "set tone at session start — operating principles, bad metrics, target state",
    "intake":      "classify and plan a task — risk tier + 12-phase workflow",
    "abstraction": "decide whether to extract — KISS/DRY/AHA + the AHA checklist",
    "review":      "review a PR and gate merge — severity, lenses, finding schema, merge gate, anti-patterns",
}


def bundle_text(bundle: str) -> str:
    """Return the concatenated sections for one bundle, or every bundle in
    order when bundle == 'all'. Raises ValueError on unknown bundle."""
    if bundle == "all":
        return "\n".join(bundle_text(b) for b in BUNDLE_ORDER)
    if bundle not in BUNDLES:
        allowed = ("all",) + BUNDLE_ORDER
        raise ValueError(f"bundle={bundle!r} not in {allowed}")
    return "\n".join(CODE_QUALITY_SECTIONS[s] for s in BUNDLES[bundle])


def code_quality_text(section: str | None = None) -> str:
    """Return one atomic section. Drill-down API; prefer `bundle_text`.
    `section=None` or `"all"` returns every section in canonical order."""
    if section is None or section == "all":
        return "\n".join(CODE_QUALITY_SECTIONS[s] for s in CODE_QUALITY_SECTION_ORDER)
    if section not in CODE_QUALITY_SECTIONS:
        allowed = ("all",) + CODE_QUALITY_SECTION_ORDER
        raise ValueError(f"section={section!r} not in {allowed}")
    return CODE_QUALITY_SECTIONS[section]


def list_text() -> str:
    """Print the bundle index — what each bundle is for and which sections
    it contains. Cheap orientation for an agent that doesn't yet know what
    to load."""
    lines = ["AI-coding-session policy — bundles", ""]
    for b in BUNDLE_ORDER:
        lines.append(f"  {b:<12} {BUNDLE_PURPOSE[b]}")
        lines.append(f"               sections: {', '.join(BUNDLES[b])}")
        lines.append("")
    lines.append("Usage:")
    lines.append("  --bundle <name>       load a coherent prompt bundle (preferred)")
    lines.append("  --bundle all          load every bundle in canonical order")
    lines.append("  --section <name>      drill down to one atomic section")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="code_quality",
        description="AI coding session policy — load a refined prompt bundle.",
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument(
        "--bundle",
        default=None,
        choices=("all",) + BUNDLE_ORDER,
        help="load one coherent prompt bundle (preferred). 'all' loads everything in order.",
    )
    g.add_argument(
        "--section",
        default=None,
        choices=("all",) + CODE_QUALITY_SECTION_ORDER,
        help="drill down to one atomic section (granular fallback).",
    )
    g.add_argument(
        "--list",
        action="store_true",
        help="print the bundle index and exit",
    )
    args = ap.parse_args(argv)
    if args.list:
        sys.stdout.write(list_text())
    elif args.section is not None:
        sys.stdout.write(code_quality_text(args.section))
    else:
        # default: print all bundles (==full policy) when no flag is given
        sys.stdout.write(bundle_text(args.bundle or "all"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
