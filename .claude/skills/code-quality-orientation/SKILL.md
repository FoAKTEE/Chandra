---
name: code-quality-orientation
description: Load the live coding-session policy and connect it to Chandra's contracts, task scope, and verifier. Use at the start of any coding session on the methodology repo or consumer research code, including "start coding", "orient this coding session", and "improve this research code".
---

# code-quality-orientation — start a coding session with the live policy

## When to use

- Start a coding session on the methodology or a consumer's research code.
- Resume after a handoff that omitted coding policy or the target verifier.
- Establish the working scope before selecting an implementation procedure.

## Steps

1. Locate the methodology checkout containing `alignment.md` and `INDEX.md`.
   Read them and `_common/contracts/research_admission_contract.md`.
   Run the policy commands below from that checkout. For consumer work, keep
   the consumer root explicit and run its tests from its own root.

2. Load the live orientation bundle. The native loader expands the directive;
   if a plain index reader leaves it literal, execute its command and read
   stdout before proceeding. Treat that output as the policy for this session.

!`python3 _common/quality/code_quality.py --bundle orientation`

3. Inspect the CLI and bundle index when choosing the next procedure.
   The script has options, not subcommands; select one read-moment bundle.

   ```bash
   python3 _common/quality/code_quality.py --help
   python3 _common/quality/code_quality.py --list
   ```

4. Bind the session to the assigned files, task or node, and observable
   success criterion. Use `pipelines/2-work/template.md` when working a node;
   use the user's file scope for a direct methodology change. Identify the
   worker or validator responsible under `alignment.md` before ledger work.

5. Locate the existing verifier for that criterion in the task or tests.
   Record its command, working directory, expected result, and any relevant
   baseline failure. For a consumer task, use its scientific criterion as
   well as software checks; a passing policy-loader check proves neither.

6. Open the procedure matching the next decision. Carry the live orientation
   output with the task context; load another bundle when its stage arrives.

   | Next decision | Procedure |
   |---|---|
   | Classify and scope work before edits | `.claude/skills/code-quality-intake/SKILL.md` |
   | Decide whether to share code | `.claude/skills/code-quality-abstraction/SKILL.md` |
   | Review a candidate diff or refute a claim | `.claude/skills/code-quality-review/SKILL.md` |

7. Hand off the criterion, verifier, baseline, and unresolved obligations to
   the selected procedure. Use `pipelines/2-work/spec.md` for node closure;
   report completion only with the required verifier output and admission.
   The Verify block below checks this skill's loading prerequisites only.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
for path in alignment.md INDEX.md _common/contracts/research_admission_contract.md \
  pipelines/2-work/spec.md pipelines/2-work/template.md \
  .claude/skills/code-quality-intake/SKILL.md \
  .claude/skills/code-quality-abstraction/SKILL.md \
  .claude/skills/code-quality-review/SKILL.md; do
  test -f "$path"
done
python3 _common/quality/code_quality.py --help >/dev/null
python3 _common/quality/code_quality.py --list >/dev/null
python3 _common/quality/code_quality.py --bundle orientation | grep -q 'END OF POLICY. STATUS: ACTIVE.'
```

## Companion files

- `_common/quality/code_quality.py` — bundle implementation and live section map.
- `_common/contracts/research_admission_contract.md` — acceptance contract.
