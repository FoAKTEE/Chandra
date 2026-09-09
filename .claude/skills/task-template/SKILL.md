---
name: task-template
description: Fill a node's implementation task from the shipped template, with one executable success criterion and evidence-based closure. Load for "fill implementation.md", "prepare this DAG node", "define done", or a task too large to verify as one expression.
---

# task-template — make one DAG node's success criterion executable

## When to use

- Decomposition exists and one node or tightly coupled cluster needs a filled work task.
- A worker has a lease but lacks a precise verification command, tolerance, or baseline test.
- A task exceeds roughly 250 lines or its success criterion combines separable claims.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`, the input/output
   contract in `pipelines/2-work/spec.md`, and all of `pipelines/2-work/template.md`.
   Locate the node in the generated Mermaid DAG and inspect its decomposition inputs,
   upstream task outputs, current claims, assumptions, and open obligations.
2. Set `PROJECT`, `P`, and `TASK_ID` to the consumer task's actual identifiers. Copy the
   template to `results/<project>/paper_<P>/tasks/<task_id>/implementation.md`:
   ```bash
   TASK_DIR="results/$PROJECT/paper_$P/tasks/$TASK_ID"
   mkdir -p "$TASK_DIR"
   test -e "$TASK_DIR/implementation.md" || cp pipelines/2-work/template.md "$TASK_DIR/implementation.md"
   ```
   Fill consumer values and references; replace template-only frontmatter with actual
   task metadata or remove it. Preserve existing task evidence; never edit the template or a generated view.
3. Preserve the complete numbered scaffold: the source has §0 through §16, including
   the header. Fill every section, using explicit N/A only where it truly does not apply:

   | Section | Fill with |
   |---|---|
   | §0 Header | Task/paper ids, exact namespaced DAG nodes, language, method class. |
   | §1 Claim | One sentence stating the bounded claim under test. |
   | §2 Success Criterion | Needed evidence type, one verifiable expression, command, metric/tolerance, open obligations, reduction test or N/A. |
   | §3 Motivation | Why this node matters now; cite the relevant claim, figure, or equation. |
   | §4 Inputs From Decomposition | Actual paths and required content for conventions, derivation, DAG, plan, refs, assumptions, claims, obligations, result seeds; upstream outputs. |
   | §5 Execution Rules | Task scope, explicit kernel/contract injection for sub-agents, and the stall-to-acquire boundary. |
   | §6 Files And Links | Read-only mirrors, decomposition, code, plots, notes, progress location, actual branch. |
   | §7 Architecture | Map each implementation file to its DAG nodes and make the driver fail when validation fails. |
   | §8 Phase Plan | DAG-derived phases, node/file/test mapping, estimates; independent nodes parallel, dependent phases sequential. |
   | §9 Quick-Win Path | Smallest end-to-end smoke result with a stated looser metric; distinguish it from closure. |
   | §10 First Test Parameters | Initial values with source-equation or task rationale. |
   | §11 Risk Mitigation | Observable failure signatures and concrete alternate approaches. |
   | §12 Current State | Evidence-linked solid/preliminary state, blocking signatures, open evidence obligations. |
   | §13 Forbidden Actions | Task-specific bans; point to the kernel for shared rules. |
   | §14 Promise Tag | The exact task-specific tag and evidence needed before it can be committed. |
   | §15 Progress Update Principles | Applicable cadence and paths; packet workers hand view/note updates to the observer after flushing. |
   | §16 Termination Checklist | Keep every check; close only after each relevant item is verified. |

4. Make §2 one executable truth condition. Combine the verification exit code, measured
   tolerance, and reduction-to-baseline outcome into one expression, for example:
   `verification_exit == 0 and max_abs_residual <= 1e-10 and baseline_pass`.
   Put the exact runnable command beside it; the command must enforce the comparison and
   exit nonzero on failure. Specify norm, units, regime, evaluation set, and threshold.
   For an exact identity, state the exact equality and use zero tolerance if appropriate.
   A command that merely prints numbers is insufficient. Do not invent an unimplemented
   CLI flag; name a real verifier or make creating that verifier an explicit task deliverable.
5. For assumption relaxation, name the old assumption and its baseline regime, the limiting
   parameter, comparison quantity, and reduction verifier. Link the assumption's actual
   `reduction_obligation` entry; an existing link alone does not prove the test passed.
   For theorem transfer, require source scope, mapping, preservation obligations, and failure
   mode. Leave the claim conditional/open while required obligations remain unresolved.
6. Split the task along existing DAG boundaries when §2 cannot be one verifiable expression
   or the filled file approaches 250 lines. Return the proposed graph change to decomposition;
   do not silently expand a worker lease. Give each resulting task its own criterion and
   dependency links. Keep independent phase work separate from dependent phase ordering.
7. Enforce §14 literally: commit a `<promise>` tag only after the verification command has
   run and its metric is within threshold. Its form is
   `<promise>{{TASK_ID}} {{METRIC}} WITHIN {{THRESHOLD}}</promise>`.
   When commits are authorized, the commit body must carry verbatim verification output,
   the measured value, admitted claim/evidence type, and artifact path; follow
   `_common/contracts/commit_template.md`. Filling the template never authorizes a promise.
8. Resolve §15's older note instructions using the packet contract in
   `pipelines/2-work/spec.md` and `orchestrator/src/agents.ts`: the worker preserves its WAL
   across compaction and flushes at the boundary; the observer refreshes notes and views.
   Do not stop between packet nodes merely to write progress prose.
9. Check every §16 item before closure: pasted verifier output; admitted result-log delta
   containing claim, evidence type, evidence, dependencies, assumptions, status, and open
   obligations; threshold met; baseline reduction passed where relevant; no blocking/open/
   unchecked items on the checked-claim path; deliverable matches §1; and contracts injected
   into every contributing sub-agent. An unchecked box means the task remains unfinished.
   Use `.claude/skills/work-packet/SKILL.md` for execution and ledger flushes, and
   `.claude/skills/adversarial-validate/SKILL.md` for independent candidate admission.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import re
from pathlib import Path
template = Path('pipelines/2-work/template.md').read_text()
assert [int(x) for x in re.findall(r'^## (\d+)\.', template, re.M)] == list(range(17))
criterion = template.split('## 2. Success Criterion', 1)[1].split('## 3.', 1)[0]
for term in ['Verification command', 'Measured tolerance', 'Reduction-to-baseline', 'one verifiable expression']:
    assert term in criterion, term
promise = template.split('## 14. Promise Tag', 1)[1].split('## 15.', 1)[0]
assert '<promise>{{TASK_ID}} {{METRIC}} WITHIN {{THRESHOLD}}</promise>' in promise
assert template.split('## 16. Termination Checklist', 1)[1].count('- [ ]') == 7
for p in ['alignment.md', '_common/contracts/research_admission_contract.md',
          'pipelines/2-work/spec.md', '_common/contracts/commit_template.md',
          'orchestrator/src/agents.ts', '.claude/skills/work-packet/SKILL.md',
          '.claude/skills/adversarial-validate/SKILL.md']:
    assert Path(p).is_file(), p
PY
```
