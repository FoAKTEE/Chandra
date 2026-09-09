---
name: markers-discipline
description: Make uncertainty, gaps, assumptions, and evidence status explicit while revising research documents and commit claims. Load for "mark open obligations", "promote or demote a claim", "clean up research notes", or "replace UPDATE tails" without hiding unresolved work.
---

# markers-discipline — mark every useful loose end and revise it in place

## When to use

- Draft or revise research prose, a task state, decomposition, or a validation record.
- Evidence improves or degrades and a claim's displayed status must change.
- Audit unmarked gaps, silent assumptions, abandoned approaches, or commit claim tags.
- For mission notes, supply the observer with corrections; workers never write those notes.

## Steps

1. Read `_common/contracts/markers.md` for the vocabulary and
   `_common/contracts/note_discipline.md` for editing rules.
   Treat the document as a research artifact with fully enumerated open obligations.
   Apply `_common/contracts/research_admission_contract.md` before changing a factual status.
2. Walk every claim and loose end. Use this operational selection table;
   the source contract remains authoritative for the definitions:

   | Marker | Use for | Record next to it |
   |---|---|---|
   | `[HYPOTHESIS]` | Proposed, untested claim | What test/evidence could advance it. |
   | `[PRELIMINARY]` | Initial evidence, not confirmed | Existing support and remaining verification. |
   | `[SOLID]` | Confirmed, safe-to-rely-on statement | Admitted evidence and its applicable scope. |
   | `[BLOCKING]` | Gap preventing enclosing task/section closure | What unblocks it and who owns resolution. |
   | `[FUTURE]` | Deliberately deferred gap not blocking current closure | Deferred work and why closure does not depend on it. |
   | `[OPEN]` | Unresolved work obligation | Evidence and verifier that would close it. |
   | `[ASSUMPTION]` | Modeling assumption or imported postulate | Scope and which results remain conditional on it. |
   | `[UNCHECKED]` | External or proposed step without a passing verifier | Missing verification; exclude it from checked support. |
   | `[EXISTENCE]` | Existence-only result | Lack of a certified construction/algorithm/artifact. |

3. Make the **forward** pass: for each marker, identify how resolving it advances
   the document or task. Remove markers that do no useful work, not the underlying
   uncertainty. Use concrete closure criteria rather than generic "needs work" tags.
4. Make the **backward** pass: every loose end must have a marker. For claims also
   record needed evidence type, assumptions, and dependencies. Mark missing symbol
   definitions, regime restrictions, unchecked imported steps, and unresolved evidence.
   Use `[BLOCKING]` plus ownership when that loose end prevents closure.
   A useful local shape is `[OPEN] <obligation>: <missing evidence>; verifier: <command>`.
   Fill the placeholders with an executable check appropriate to the actual claim.
5. Promote `[HYPOTHESIS]` → `[PRELIMINARY]` → `[SOLID]` only as admitted evidence
   supports the transition. Demote when evidence degrades; attach the failed check,
   narrower scope, or newly discovered obligation. A text edit never performs admission.
   Have the responsible worker append the evidence-backed state through the ledger gate;
   render canonical views afterward. Keep earlier ledger rows; correct by appending.
   Never relabel simulations or citations as exact proofs, or existence as construction.
6. Keep gap markers until their closure criteria are met. A `[BLOCKING]` item becomes
   `[FUTURE]` only after an explicit scope decision establishes it is unnecessary for
   current closure. Preserve assumptions on every dependent result; a solid result may
   still be conditional, approximate, empirical, or existence-only in the result ledger.
   Check that checked-claim paths have no unresolved `[OPEN]` or `[UNCHECKED]` work.
7. Revise live prose using the note discipline:
   - Extend an existing section by default; add one only for a genuinely new thread.
   - Revise changed information in place; never append "UPDATE: actually..." tails.
   - Move abandoned approaches to an appendix instead of silently deleting them.
   - Restructure when the narrative no longer fits and flag the restructure in the commit.
   - Let evidence-rich sections grow and unsupported sections stay skeletal.

   For the observer's two snapshot notes and the research-state cap, use
   `.claude/skills/three-notes/SKILL.md`: full rewrites/pruning have explicit history rules.
8. Reject these anti-patterns in the editing pass: hedging over a gap; hiding uncertainty
   for readability; artificially balanced sections; new text inserted at the top;
   a section per thought; orphaned content; premature polish before content settles.
   Replace each with the applicable marker, in-place revision, or appendix move.
9. Map claims in commit bodies using `_common/contracts/commit_template.md`:

   | Commit tag | Relation to document markers |
   |---|---|
   | `[SOLID]` | Confirmed evidence; preserve the actual evidence type and scope. |
   | `[PRELIMINARY]` | Indicative support; do not present an untested hypothesis as measured. |
   | `[HOLE]` | Commit shorthand for an unresolved gap; explain whether `[OPEN]`, `[BLOCKING]`, or `[UNCHECKED]` applies in the document. |
   | `[FUTURE]` | Work deliberately deferred without blocking current closure. |

   Every `finding`/`result` object needs one of those four tags. `[HOLE]` is defined
   by the commit contract, not by the nine-marker vocabulary file.
   Use `caveat`/`next` for untested plans rather than inventing a supported result.
   Keep `[ASSUMPTION]` and `[EXISTENCE]` qualifications explicit; there is no automatic
   one-to-one translation from these markers to a commit evidence level.
10. Deliver the corrected artifact or observer handoff with resolved/demoted items,
    still-open criteria, and evidence anchors. Re-run the bidirectional passes after
    restructuring; an attractive document with an unmarked gap fails this procedure.

## Verify

```bash
set -euo pipefail
test -f _common/contracts/markers.md
test -f _common/contracts/note_discipline.md
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
markers = Path('_common/contracts/markers.md').read_text()
for name in 'HYPOTHESIS PRELIMINARY SOLID BLOCKING FUTURE OPEN ASSUMPTION UNCHECKED EXISTENCE'.split():
    assert f'`[{name}]`' in markers, name
discipline = Path('_common/contracts/note_discipline.md').read_text()
for phrase in ['**Forward:**', '**Backward:**', 'Revise in place', 'Prune to appendix', 'Anti-patterns']:
    assert phrase in discipline, phrase
commit = Path('_common/contracts/commit_template.md').read_text()
for name in 'SOLID PRELIMINARY HOLE FUTURE'.split():
    assert f'`[{name}]`' in commit, name
PY
```

## Companion files

- `.claude/skills/commit-gated/SKILL.md`
- `alignment.md`
