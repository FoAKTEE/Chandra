---
name: loop-gate
description: Inspect and apply the progress circuit breaker, interpret halt reasons, and reset streaks only after the halt is resolved. Load for "why did the loop halt", "check progress gate", "no progress streak", "stuck iteration", or a human-reviewed loop resumption.
---

# loop-gate — stop a loop that exhausts progress or budget

## When to use

- A loop driver needs its next continue/halt decision.
- A reviewer needs to diagnose a stall, stuck counter, or budget limit.
- The human has resolved a halt and directed a reset for resumption.

## Steps

1. Read `alignment.md` §2–3 and `_common/loop/loop_gate.py`. Identify which
   driver owns this run. The Python CLI evaluates the legacy loop state across
   all papers; `orchestrator/src/gate.ts` is the wave gate used by the runtime.
   Both compare progress component by component: an increase in any counted
   component resets the no-progress streak, even if another component decreases.
   Run the commands below from the consumer root; set `CONSUMER` to that root
   if using --repo-root from elsewhere. Inspect state; never hand-edit counters.

2. Read the status without changing persisted state:
   ```bash
   python3 _common/loop/loop_gate.py status --repo-root .
   ```
   Status returns a nested decision object, proposed gate_state, state_file, and
   loop_active. Exit 0 means continue; exit 1 means a halt, not a command failure
   to bypass. The CLI simulates a next check in memory, so its displayed streak
   can be one ahead of the persisted streak. It does not write that proposal.
   Missing files yield default budgets and a baseline; continue does not prove
   that a configured mission exists. Inspect the driver-owned inputs:

   | consumer file | purpose |
   |---|---|
   | `<repo>/.claude/ralph-loop.local.md` | loop-state frontmatter, including active, iteration, budgets, started_at |
   | `<repo>/.claude/loop_gate_state.json` | last progress, last iteration, streaks, bounded decision history |
   | `<repo>/.claude/HUMAN_REVIEW_REQUIRED.md` | rendered human-review request after a circuit-breaker halt |

   Status and decide accept --state-file and --gate-state to select explicit
   paths; overrides resolve from the current working directory, not --repo-root.
   Budgets are state fields, not CLI flags: max_iterations defaults to 1000,
   no_progress_limit to 8, stuck_counter_limit to 3, max_wall_seconds to 0
   (disabled). A wall budget needs parseable started_at; malformed timestamps
   warn and leave that budget unenforced, so report the driver's configuration.

3. Check what counts as progress before interpreting the streak. The result
   source is `GATE_PROGRESS_STATUSES` in `_common/ledgers/result_database.py`:
   checked, conditional, approximate, empirical, and existence_only. Unchecked,
   refuted, and conjectural do not reset the breaker. Error-ledger pass rows,
   reruns, rendered views, and new prose alone are activity, not gate progress.

   | implementation | counted progress components |
   |---|---|
   | Python CLI | latest solid knowledge nodes; latest results in gate statuses; those results with no open_obligations, across every paper |
   | Runtime wave gate | latest solid nodes; latest results in gate statuses; discharged claim-ledger obligations, for the mission paper |

   These are different third components. Python calls its counter
   discharged_results; runtime calls its counter dischargedObligations.
   The status filter assumes admission already happened; it does not rerun each
   verifier or prove semantic correctness. Do not append shallow classified rows
   or cycle statuses to manufacture progress. Use the actual evidence gates.

4. Let the loop driver persist one decision per genuine check:
   ```bash
   python3 _common/loop/loop_gate.py decide --repo-root . --write-gate
   ```
   Decide writes gate state atomically and returns the decision JSON directly.
   Exit 0 is continue; any halt exits 1. --write-gate additionally writes the
   human-review file for circuit-breaker halts. --gate-file selects a different
   review path. Inactive halt writes streak state but no human gate.
   Do not poll decide for display: repeated calls at the same iteration increase
   stuck_streak. Use status for display. A new iteration resets stuck_streak;
   if no component increased it increments no_progress_streak once per check.

5. Follow the Python ladder in priority order; do not choose a later reason:

   | priority | decision | action |
   |---|---|---|
   | 1 | halt:inactive | stop as directed; no human gate needed |
   | 2 | halt:max_iterations | human reviews accepted results and chooses cap, scope, partial outcome, or stop |
   | 3 | halt:time_budget | human reviews time spent and chooses budget or narrower work |
   | 4 | halt:stuck_counter | repair the loop driver or verification/counter transition |
   | 5 | halt:no_progress | choose a structural approach, acquire missing support, or request a scope decision |
   | 6 | continue | continue within the remaining budgets and admission rules |

   The runtime's gate.ts ladder is time_budget, then no_progress, then continue;
   it operates on waves with its own state. Its default no-progress limit is 8
   and wall budget is disabled. The Python CLI is not a runtime reset interface.
   Missing progress at a node also triggers acquisition at three iterations or
   30 minutes per the kernel, before waiting for the broader gate to halt.

6. Surface a halt's reason, progress counts, streak, relevant verifier evidence,
   and a concrete recovery choice to the human. Read the rendered review file
   rather than replacing it with optimistic prose. For stalled research, follow
   `.claude/skills/loop-no-tweak/SKILL.md` and `pipelines/0-acquire/spec.md`.
   After the cause is resolved and the human directs resumption, clear the
   Python streak through its command:
   ```bash
   python3 _common/loop/loop_gate.py reset --repo-root .
   ```
   Reset only deletes the selected gate-state JSON; --gate-state can select it.
   It does not clear the human-review file, change active/budgets, restart a
   mission, or repair evidence. Have the driver/operator complete the appropriate
   resume steps. Never reset, lower the iteration, or edit state to conceal a halt.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 _common/loop/loop_gate.py --help >/dev/null
for sub in decide status reset; do
  python3 _common/loop/loop_gate.py "$sub" --help >/dev/null
done
python3 - <<'PY'
import json, re
from pathlib import Path
from _common.ledgers.result_database import GATE_PROGRESS_STATUSES
from _common.loop import loop_gate as gate
expected = {'checked', 'conditional', 'approximate', 'empirical', 'existence_only'}
assert set(GATE_PROGRESS_STATUSES) == expected
source = Path('orchestrator/src/gate.ts').read_text()
values = re.search(r'GATE_PROGRESS_STATUSES = new Set\(\s*\[([^\]]+)\]', source)[1]
assert set(json.loads('[' + values + ']')) == expected
assert gate.STATE_FILE == '.claude/ralph-loop.local.md'
assert gate.GATE_STATE_FILE == '.claude/loop_gate_state.json'
assert gate.HUMAN_GATE_FILE == '.claude/HUMAN_REVIEW_REQUIRED.md'
assert gate.DEFAULT_NO_PROGRESS_LIMIT == 8 and gate.DEFAULT_STUCK_COUNTER_LIMIT == 3
assert Path('tests/test_loop_gate.py').is_file()
PY
python3 -m pytest tests/test_loop_gate.py -q -p no:cacheprovider
```

## Companion files

- `_common/loop/loop_gate.py`
- `orchestrator/src/gate.ts`
- `tests/test_loop_gate.py`
