---
name: code-quality-intake
description: Apply the live gated intake workflow before writing code, resolve task scope, and interpret the knowledge ledger's R0–R4 risk labels without inventing missing policy. Load for "take on this task", "plan this change", "grill the design", or "before writing code" on methodology or consumer research code.
---

# code-quality-intake — turn a coding request into a gated work plan

## When to use

- Take on a coding task before implementation begins.
- Re-scope work after inspection reveals a different impact or constraint.
- Resolve a missing intake field or a blocked design decision.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`,
   and the assigned task. Run these policy and schema commands from the
   methodology root; inspect consumer code in the separately named consumer root.

2. Load the live intake bundle. If the directive remains literal in an index
   reader, execute its command and read stdout. Follow the phases it prints;
   use its actual contents when a bundle summary disagrees with them.

!`python3 _common/quality/code_quality.py --bundle intake`

3. Capture the five intake fields named in the bundle in the task artifact.
   Add the target repository, permitted files, node or task identifier, and
   a concrete verification command with its expected outcome. Use
   `pipelines/2-work/template.md` for a research work item. Record missing
   information against the affected gate instead of silently filling it in.

4. Inspect the executable risk field before recording a tier.

   ```bash
   export PYTHONDONTWRITEBYTECODE=1
   python3 _common/quality/code_quality.py --help
   python3 _common/ledgers/knowledge_database.py --help
   python3 _common/ledgers/knowledge_database.py schema
   python3 _common/ledgers/knowledge_database.py describe-fields
   ```

   `risk_tier` is optional on knowledge rows and accepts exactly the five
   strings below. It is task classification metadata, not a node status or
   proof that verification passed. Intake still requires an explicit tier.

   | Tier | Meaning established by the current code and bundle |
   |---|---|
   | `R0` | Accepted label below the bundle's explicit R2+ design trigger. |
   | `R1` | Accepted label below that trigger; no separate R1 gate is defined. |
   | `R2` | First label covered by the explicit R2+ design gate. |
   | `R3` | Covered by R2+; no additional R3-specific gate is defined. |
   | `R4` | Covered by R2+; no additional R4-specific gate is defined. |

   The repo supplies no impact thresholds distinguishing these labels.
   The ledger's attribution of tier definitions to the policy module is stale:
   intake contains the workflow, not a tier-definition section. Use the
   mission's stated rubric; otherwise propose a tier with an explicit impact
   and rollback rationale, identify the missing rubric as a working assumption,
   and resolve it in intake. Do not present an invented rubric as repo policy.

5. Apply the design gate at the tier established above. Inspect relevant code
   before raising unresolved questions. Attach each design decision to a
   source location, test, contract, or explicit task constraint; record what
   evidence would settle an unknown. Keep blocked dependent work pending.

6. Build the codebase map required by the live workflow. Start with `INDEX.md`
   for methodology work; locate entry points and tests with targeted searches.

   ```bash
   rg --files _common tests pipelines
   rg -n 'def main|add_subparsers|REQUIRED_FIELDS' _common
   ```

   For consumer work, search its source and tests instead. Record the relevant
   call path and governing schema; avoid collecting unrelated repository text.

7. Work through the remaining live phases in order. Give each proposed edit
   an existing behavior to preserve or an explicit behavior to change, a
   verifier, and a rollback action. Distinguish code-imposed constraints from
   domain requirements in the plan. Keep deletion and performance work within
   the assignment's authorization; escalate a scope conflict at its gate.

8. Hand off a plan listing phase outcomes, selected tier and rationale, exact
   commands, and unresolved obligations. Carry `risk_tier` to the later
   knowledge-row procedure when applicable; this intake skill appends no row.
   Open `.claude/skills/code-quality-abstraction/SKILL.md` when the plan
   proposes sharing code, and `pipelines/2-work/spec.md` for implementation
   and admission. The loader check below does not admit the plan's claims.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
for path in alignment.md INDEX.md _common/contracts/research_admission_contract.md \
  pipelines/2-work/template.md pipelines/2-work/spec.md \
  .claude/skills/code-quality-abstraction/SKILL.md; do
  test -f "$path"
done
python3 _common/quality/code_quality.py --help >/dev/null
python3 _common/quality/code_quality.py --bundle intake | grep -q 'Find the critical path'
python3 _common/ledgers/knowledge_database.py --help >/dev/null
python3 _common/ledgers/knowledge_database.py schema --help >/dev/null
python3 _common/ledgers/knowledge_database.py describe-fields --help >/dev/null
python3 _common/ledgers/knowledge_database.py schema | grep -q "risk_tier  = ('R0', 'R1', 'R2', 'R3', 'R4')"
python3 _common/ledgers/knowledge_database.py describe-fields | grep -q 'risk_tier'
```

## Companion files

- `_common/quality/code_quality.py` — emitted phases are the policy source.
- `_common/ledgers/knowledge_database.py` — tier enum and row validation.
