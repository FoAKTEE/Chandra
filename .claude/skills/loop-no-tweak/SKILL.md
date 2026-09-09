---
name: loop-no-tweak
description: Read trial-ledger verdicts to stop repeated parameter tweaks, choose a structural pivot or acquisition, and complete the simplification cycle. Load for "same failure again", "can I retry", "check pivot", "best metric refreshed", or "is paper refresh due".
---

# loop-no-tweak — query the trial history before another cycle

## When to use

- A trial fails, crashes, or partially succeeds and another change is proposed.
- A best-metric refresh needs its simplification pass before a promise claim.
- A node stalls for three iterations or 30 minutes, or the living paper is due.

## Steps

1. Read `alignment.md` §2–3 and `_common/contracts/progress_principles.md`.
   Run from the consumer repo root. Set `P`, `TASK`, and `DOMAIN` to the paper,
   task_id, and symbolic/numerical/proof/software domain. Preserve every trial
   through `.claude/skills/ledger-error-trial/SKILL.md`. These policy commands
   read admitted error-ledger rows; they do not see an unflushed packet WAL.
   During a packet, apply the same rule to buffered trials; flush completed work
   at a structural interruption before escalation. Do not hide a stall in scratch.

2. Load the domain's recipe and triage a failure before choosing the next step:
   ```bash
   python3 _common/loop/loop_policy.py describe-domain --domain "${DOMAIN:?}"
   python3 _common/loop/loop_policy.py crash-triage --repo-root . --paper "${P:?}" --task "${TASK:?}" --domain "${DOMAIN:?}"
   ```
   Read the JSON recommendation and reason; commands exit 0 even when the
   recommendation demands escalation. With the default --window 3:

   | failing history for the task | recommendation | next action |
   |---|---|---|
   | none | no_action | proceed within the task's verification plan |
   | one, or mixed failure modes in the window | fix_and_retry | diagnose with tool evidence and address the actual fault |
   | two of the same mode | pivot_structural | change the approach before another trial |
   | three of the same mode | escalation | switch methodology and acquire missing support when stalled |

   The implementation selects the last failing rows (fail/crash/partial), not
   necessarily adjacent trials. An intervening pass does not reset that list.
   --domain chooses explanatory hints; it does not filter the task's rows by
   domain. Inspect the history if reused task IDs mix domains or approaches.
   Do not raise --window or rename failure tags to evade the kernel's three cycles.

3. Check the proposed change type before implementing it:
   ```bash
   python3 _common/loop/loop_policy.py check-pivot --repo-root . --paper "${P:?}" --task "${TASK:?}" --domain "${DOMAIN:?}" --change-type scalar
   ```
   Replace scalar with the actual proposed type. `verdict=blocked` means stop
   that proposal and follow triage; exit 0 is only successful query execution.
   Structural always returns verdict ok in code, but a label is not evidence
   of a changed method. A refactor preserves behavior while reducing cost; it
   does not substitute for a required structural pivot. Record scalar honestly
   for mesh, tolerance, step size, or other parameter-only changes.

4. Select a substantive pivot using the returned domain_hint:

   | domain | structural change | change that does not qualify |
   |---|---|---|
   | symbolic | different normal form, starting identity, or derivation route | only changing assumptions |
   | numerical | different integrator, discretization, or contour method | only mesh, tolerance, or step size |
   | proof | different induction, lemma decomposition, or proof strategy | small rewrite-rule additions |
   | software | different algorithm, data structure, module boundary, or test strategy | renaming or rerunning the same test |

   At three stuck iterations or 30 minutes, follow `pipelines/0-acquire/spec.md`
   to import the missing method/source, then re-enter the loop. Record an open
   obligation owned by 0-acquire through `.claude/skills/ledger-claims/SKILL.md`.
   The policy query itself neither schedules acquisition nor checks elapsed time.

5. Query simplification after a non-refactor metric pass and before a promise:
   ```bash
   python3 _common/loop/loop_policy.py simplification-status --repo-root . --paper "${P:?}" --task "${TASK:?}" --domain "${DOMAIN:?}" --metric-name "${METRIC_NAME:?}"
   ```
   Omit --metric-name only when inspecting the task across all metric names.
   Read status no_refresh, required, or ok. Required returns best_iteration,
   best_metric_value, metric_name, and the domain recipe when requested.
   Follow its cost metric: expression size for symbolic work, editable-code
   size for numerical work, proof-object size for proof work, and diff/module
   size for software. Remove unused machinery, retain the primary verifier,
   and record a later `change_type=refactor` trial that passes at the same metric
   name. Keep its iteration greater than the refresh iteration.
   The code uses metric.pass and the latest non-refactor pass by iteration;
   it does not prove a numerical best or compare the before/after values.
   Verify unchanged tolerance, assumptions, and metric yourself. If simplification
   regresses, restore the working implementation within scope and retain the failed
   trial. Never weaken checks, delete tests, or add assumptions to manufacture ok.

6. Query the living-paper cadence after flush and at closure:
   ```bash
   python3 _common/loop/loop_policy.py paper-refresh --repo-root . --paper "${P:?}" --every 5 --since "${LAST_PAPER_ITER:?}"
   ```
   Read due, latest_iteration, iterations_since_generation, and next_due_iteration.
   Use the last generation iteration from the paper's GENERATION_LOG. --every
   defaults to 5 and must be positive. Without --since, due is a stateless
   divisibility check and can miss an overdue refresh between multiples.
   No trials yields due false. A due verdict asks the writing stage to refresh;
   the query writes nothing. Follow `pipelines/3-write/spec.md` at termination
   even when the periodic query is not due.

7. Treat the queries as steering, not admission. Carry the chosen change and
   measured outcome into the next trial and the appropriate result/node gate.
   Read `.claude/skills/loop-gate/SKILL.md` if the mission circuit breaker halts;
   neither a retry nor a positive activity count clears that gate.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import subprocess
from pathlib import Path
from unittest.mock import patch
from _common.loop import loop_policy as policy
cli = '_common/loop/loop_policy.py'
for args in [[], *[[s] for s in ('crash-triage', 'check-pivot', 'simplification-status', 'describe-domain', 'paper-refresh')]]:
    subprocess.run(['python3', cli, *args, '--help'], check=True, stdout=subprocess.DEVNULL)
assert policy.PIVOT_WINDOW == 3 and policy.PAPER_REFRESH_EVERY == 5
for domain in ('symbolic', 'numerical', 'proof', 'software'):
    assert domain in policy.CRASH_PIVOT_HINTS and domain in policy.SIMPLIFICATION_RECIPES
    assert 'cost_metric' in policy.describe_domain(domain)
assert Path('pipelines/0-acquire/spec.md').is_file()
rows = []
with patch.object(policy, '_read_entries', return_value=rows):
    assert policy.crash_triage('P', 'T')['recommendation'] == 'no_action'
    for iteration, expected in enumerate(('fix_and_retry', 'pivot_structural', 'escalation'), 1):
        rows.append({'task_id': 'T', 'iteration': iteration, 'pass_fail': 'fail',
                     'failure_mode': 'test_failure'})
        assert policy.crash_triage('P', 'T', domain='software')['recommendation'] == expected
    assert policy.check_pivot('P', 'T', 'scalar')['verdict'] == 'blocked'
    assert policy.check_pivot('P', 'T', 'structural')['verdict'] == 'ok'
    assert policy.simplification_status('P', 'T')['status'] == 'no_refresh'
    passed = {'task_id': 'T', 'iteration': 4, 'pass_fail': 'pass', 'change_type': 'structural',
              'metric': {'name': 'tests_failed', 'value': 0, 'threshold': 0, 'pass': True}}
    rows.append(passed)
    assert policy.simplification_status('P', 'T', domain='software')['status'] == 'required'
    rows.append({**passed, 'iteration': 5, 'change_type': 'refactor'})
    assert policy.simplification_status('P', 'T')['status'] == 'ok'
    assert policy.paper_refresh_due('P', since=0)['due']
PY
```

## Companion files

- `_common/loop/loop_policy.py`
- `_common/ledgers/error_database.py`
- `_common/contracts/progress_principles.md`
