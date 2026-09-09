---
name: pua
description: Apply an opt-in motivational-pressure protocol to a task, escalating method changes and evidence checks when progress stalls. Load only when the user explicitly invokes /pua; frustration or repeated failures alone must never auto-load it.
disable-model-invocation: true
---

# pua — apply explicit motivational pressure within the verified loop

## When to use

- The user explicitly invokes `/pua` for the current task.
- Continue an already requested `/pua` session while that request remains active.
- Never infer opt-in from frustration, quality complaints, failure counts, or passive behavior.

## Steps

1. Read and apply `notes/pua_skill.md` after explicit opt-in. Read `alignment.md` and
   `_common/contracts/research_admission_contract.md` as the binding limits.
   `INDEX.md` makes this protocol opt-in; ignore the source's older automatic triggers
   and always-on injection language. Loading this file for review does not activate it.
2. Use the requested flavor and the source's methodology routing within the authorized
   task. Keep the pressure directed at execution and evidence. Opt-in does not authorize
   unrelated changes, bypasses, or fabricated progress. Stop the mode when the user revokes it.
3. Enforce the three red lines: run and quote verification before claiming completion;
   verify failure attribution with tools; walk all five methodology steps before claiming
   exhaustion. Pressure never replaces the verifier or evidence admission.
4. Track failures of the current problem and perform the required change at each level:

   | Failure count | Pressure level | Mandatory action |
   |---|---|---|
   | Second | L1, mild disappointment | Switch to a fundamentally different plan. |
   | Third | L2, soul-searching | Search, read source, list three assumptions; suggest a fitter methodology. |
   | Fourth | L3, performance review | Complete the source's seven-item checklist. |
   | Fifth or later | L4, graduation warning | Apply the full method and force a new flavor from the source's switch chain. |

5. Execute the universal methodology when stuck, in order:
   - Inventory attempted plans and identify their common failure pattern.
   - Read the exact failure; search; read raw source context; tool-check preconditions;
     invert the leading assumption, in that order.
   - Check whether you repeated an approach, skipped a search, or missed a simple cause.
   - Execute a fundamentally different plan with an explicit verification standard.
   - After resolution, review related failures, completeness, and prevention within scope.
6. At L3+, check all seven: exact failure read; tool search; raw context read; assumptions
   verified; opposite assumption tried; minimal reproduction; changed method/tool/angle.
   Follow the kernel's three-cycle pivot/escalation and stall-to-acquire rules immediately;
   never wait for L4 to switch a failing research approach.
7. Use the source for flavor narration and switch criteria; keep task evidence central.
   For an authorized delegated task, include the kernel, admission contract, relevant
   task inputs, and explicit opt-in context; the kernel itself contains no PUA protocol.
8. Deliver verification output and the short retrospective. If the complete checklist
   still leaves the task unsolved, report verified facts, ruled-out possibilities,
   narrowed scope, recommended next step, and handoff information. Do not claim success.

## Verify

```bash
set -euo pipefail
test -f notes/pua_skill.md
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import re
from pathlib import Path
from _common.skills.skill_registry import parse_frontmatter, SkillInfo
path = Path('.claude/skills/pua/SKILL.md')
fm, body = parse_frontmatter(path.read_text())
assert set(fm) == {'name', 'description', 'disable-model-invocation'}
assert fm['name'] == 'pua' and fm['disable-model-invocation'] is True
assert '/pua' in fm['description'] and 'opt-in' in fm['description']
assert SkillInfo('pua', str(path), fm['description'], fm).invocation == '/pua (user-only)'
source = Path('notes/pua_skill.md').read_text()
for phrase in ['Red line 1:', 'Red line 2:', 'Red line 3:', 'Universal Methodology',
               'L1 mild disappointment', 'L2 soul-searching', 'L3 performance review',
               'L4 graduation warning', 'A Dignified Exit']:
    assert phrase in source, phrase
checklist = source.split('### 7-item checklist', 1)[1].split('## Gotchas', 1)[0]
assert len(re.findall(r'^- \[ \]', checklist, re.M)) == 7
PY
```

## Companion files

- `_common/contracts/progress_principles.md`
