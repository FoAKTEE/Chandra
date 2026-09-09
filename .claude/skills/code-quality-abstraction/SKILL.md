---
name: code-quality-abstraction
description: Apply the live KISS/DRY/AHA bundle and its checklist to an extraction, shared layer, or deduplication decision. Load for "extract a helper", "add a layer", "dedupe this code", or "remove this abstraction" before changing methodology or consumer research code.
---

# code-quality-abstraction — decide whether the shared concept is ready

## When to use

- Propose a helper extraction, shared layer, or deduplication.
- Review an abstraction whose callers have acquired different requirements.
- Decide whether to retain duplication or inline an existing abstraction.

## Steps

1. Read `alignment.md` and `_common/contracts/research_admission_contract.md`.
   Carry the task scope and verifier from intake. Run policy commands at the
   methodology root; use the consumer's source root for consumer call-site work.

2. Load the live abstraction bundle. If an index reader shows the directive
   literally, run its command and read the output before making the decision.
   Use its checklist and tie-breaking rules directly.

!`python3 _common/quality/code_quality.py --bundle abstraction`

3. Locate the proposed extraction and its current callers. Trace the decision
   each site makes, its input and output contracts, side effects, and error
   handling. For the methodology's ledgers, these searches expose useful
   comparison points; they do not establish that the sites should be merged.

   ```bash
   python3 _common/quality/code_quality.py --help
   rg -n 'def (append_row|append_batch|validate)' _common/ledgers
   rg -n 'check_(actor_role|knowledge_admission|result_admission)' _common/ledgers
   ```

4. Build a small decision table in the existing task or scratch artifact.
   Give each current site a file and line, the invariant it owns, the event
   that would change it, and the existing behavior check. Compare the actual
   contracts of `_common/ledgers/error_database.py`,
   `_common/ledgers/knowledge_database.py`, and `_common/ledgers/admission.py`
   when those sites are involved; a shared function name alone proves nothing.

5. Complete every checkbox in the injected AHA checklist with evidence from
   that table. Record the resulting decision and the decisive evidence.
   For a deferred extraction, name the missing evidence and keep the current
   implementation usable. For an extraction, identify exactly which original
   sites the candidate diff replaces and how its behavior will be checked.

6. Apply the selected change within the assigned scope. Re-read affected
   callers after the edit and rerun the chosen behavior checks. If the
   evidence invalidates a checklist answer, revisit the decision before
   continuing to extend the abstraction.

7. Report the caller evidence, checklist outcome, tradeoff, and verifier
   output in the review handoff. Open
   `.claude/skills/code-quality-review/SKILL.md` for the candidate diff and
   `pipelines/2-work/spec.md` for admission of a completed node.
   The Verify block below establishes bundle availability and source paths;
   it does not certify an extraction's behavior.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
for path in alignment.md _common/contracts/research_admission_contract.md \
  _common/ledgers/error_database.py _common/ledgers/knowledge_database.py \
  _common/ledgers/admission.py pipelines/2-work/spec.md \
  .claude/skills/code-quality-review/SKILL.md; do
  test -f "$path"
done
python3 _common/quality/code_quality.py --help >/dev/null
python3 _common/quality/code_quality.py --bundle abstraction | grep -q 'DUPLICATE AND REVISIT LATER'
```

## Companion files

- `_common/quality/code_quality.py` — live principles and checklist.
- `_common/ledgers/ledger_common.py` — existing shared ledger mechanics.
