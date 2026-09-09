---
name: code-quality-review
description: Review a candidate diff with the live severity, lenses, finding schema, and anti-patterns bundle, then map verified software findings to error-ledger trials. Load for "review this diff", "review this PR", "gate the merge", or "act as a code refuter" after candidate code and its checks exist.
---

# code-quality-review — turn review findings into evidence and trial records

## When to use

- Review a diff or PR and determine whether its findings allow a merge.
- Refute a candidate's code-correctness or performance claim.
- Recheck a repair and record the outcome of the verification trial.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`,
   and `pipelines/2-work/spec.md`. Fix the review target, base revision, task,
   and verifier. Run the policy and ledger CLIs from the methodology root;
   run consumer checks in the consumer root and pass that root to append.

2. Load the live review bundle. If an index reader leaves the directive
   literal, execute its command and read stdout. Use the emitted severity
   decisions to gate the review; no separate merge-gate section is shipped.

!`python3 _common/quality/code_quality.py --bundle review`

3. Inspect the diff, changed call paths, tests, and governing contracts through
   the relevant injected lenses. Follow the review isolation requirements in
   the contracts. Record each suspected failure's trigger and the smallest
   check that can distinguish it from correct behavior.

4. Emit one `finding` object per issue using every key of the injected schema.
   Set `file` to a path relative to the reviewed repo and `line` to the precise
   location. Fill `claim`, impact, and proposed repair with concrete behavior.
   Put the executed command, observed output, and evidence location in
   `evidence`. Keep untested suspicions at `NEEDS_EVIDENCE`; select `CONFIRMED`
   or `DISMISSED` only from observations. Confidence never substitutes for a
   check. Retain dismissed findings with the evidence that settled them.

5. Run the check and preserve its output, exit status, elapsed seconds, and
   candidate revision in the task's evidence area. Use the software runtime
   evidence layout printed below for scratch transcripts. Diagnose only as
   far as the observations support; record an unresolved cause explicitly.

   ```bash
   export PYTHONDONTWRITEBYTECODE=1
   python3 _common/quality/code_quality.py --help
   python3 _common/ledgers/error_database.py --help
   python3 _common/ledgers/error_database.py schema
   python3 _common/ledgers/error_database.py describe-fields
   python3 _common/ledgers/error_database.py describe-domain --domain software
   ```

6. Map each executed review trial to an error row. Finding severity and status
   remain in the finding artifact; `pass_fail` records the trial's observed
   behavior, not its severity. A reproducer that exits 0 after detecting a bug
   can still establish a failed product criterion. Preserve unresolved
   findings when a passing test does not actually exercise their claims.

   | Finding or trial evidence | Error-row destination |
   |---|---|
   | Criterion under review | `expected`; identify the checked behavior in `change_summary` |
   | Measured counterexample and evidence location | `observed`, plus the measured `metric` |
   | Tool-supported causal trace | `root_cause`; state unknown when unresolved |
   | Proposed repair | `fix_hypothesis` |
   | Full finding, including severity, status, category, confidence, location | Reference its artifact in `notes`; put executed checks in `tests_run` |
   | Task context and measurement | `paper`, `task_id`, optional `node_id`, `iteration`, `wall_clock_seconds` |

   Use `domain: software` and `stage: validation` for these code-review trials.
   Choose `change_type` for the candidate change from the schema's enum.
   Choose `failure_mode` by observed failure, not review category or severity.
   The live software tags are `test_failure`, `build_failure`,
   `type_check_failure`, `regression`, `flaky_test`, `dependency_drift`,
   `spec_drift`, `schema_violation`, `gate_rejection`, `timeout_or_oom`, and
   `uncategorized_software`; consult the printed meanings before selecting.
   For an unfit tag, follow the module's self-correction protocol within the
   assigned scope; report a needed taxonomy change if source edits are excluded.

7. Prepare a JSON object with every field required by `schema`. This minimal
   failure example demonstrates row shape only: replace its placeholders and
   illustrative measurements with observed data before a real append.
   Add `notes` and `tests_run` to link the full finding and actual command.

   ```json
   {
     "paper": "<P>",
     "task_id": "<T>",
     "iteration": 1,
     "stage": "validation",
     "domain": "software",
     "change_type": "structural",
     "change_summary": "Review candidate row validation",
     "metric": {"name": "tests_failed", "value": 1, "threshold": 0, "pass": false},
     "pass_fail": "fail",
     "wall_clock_seconds": 0.2,
     "expected": "The contract test passes",
     "observed": "1 failed; see <evidence-log>",
     "root_cause": "The traced validator rejects an allowed input; see <evidence-log>",
     "fix_hypothesis": "Correct the rejecting branch and rerun the contract test",
     "failure_mode": "test_failure"
   }
   ```

   Failure, crash, and partial rows require the five diagnostic fields shown.
   Passing trials still require all ten base fields; use the actual passing
   metric. Append fills `timestamp` and `git_commit`; `node_id` also enables
   automatic `node_seq`. Do not translate an unrun suspicion into a failed test.

8. Save the completed object outside the repo, set `trial_row_file` to that
   file and `review_repo_root` to the reviewed repository, and append in the
   delegated worker role. Keep an already assigned validator or observer role.

   ```bash
   : "${trial_row_file:?Set the completed trial JSON file}"
   : "${review_repo_root:?Set the reviewed repository root}"
   CHANDRA_ROLE="${CHANDRA_ROLE:-worker}" python3 _common/ledgers/error_database.py append \
     --repo-root "$review_repo_root" --row-file "$trial_row_file"
   ```

   Append validates shape and actor role, writes a chained trial, and refreshes
   its CSV summary. It does not execute a verifier or hash the cited evidence;
   run the check before appending. The canonical output is
   `results/ledgers/error/paper_<P>/trials.jsonl`; if only the legacy paper
   directory exists, `_common/ledgers/ledger_common.py` keeps writing there.

9. Reconcile findings with the injected severity policy and attach verifier
   output to the review verdict. Record any policy-required owner acceptance
   or follow-up explicitly. After a repair, rerun its check and append the new
   trial; retain the earlier row. Hand node admission to `pipelines/2-work/spec.md`.
   Review completion and the wrapper check below do not themselves admit a node.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 _common/quality/code_quality.py --help >/dev/null
python3 _common/quality/code_quality.py --bundle review | grep -q 'REQUIRE QUERY PLAN, BENCHMARK, OR DRY RUN.'
python3 _common/ledgers/error_database.py --help >/dev/null
for command in schema describe-fields describe-domain append; do
  python3 _common/ledgers/error_database.py "$command" --help >/dev/null
done
python3 _common/ledgers/error_database.py schema | grep -q 'wall_clock_seconds'
python3 _common/ledgers/error_database.py describe-domain --domain software | grep -q 'uncategorized_software'
scratch=$(mktemp -d /tmp/chandra-quality-review.XXXXXX)
trap 'rm -rf "$scratch"' EXIT
python3 - "$scratch" <<'PY'
import json, re, sys
from pathlib import Path
from _common.ledgers import error_database as ed
root = Path(sys.argv[1])
body = Path('.claude/skills/code-quality-review/SKILL.md').read_text()
row = json.loads(re.search(r'`{3}json\s*\n(.*?)\n\s*`{3}', body, re.S).group(1))
ed.validate(row)
assert row['domain'] == 'software' and row['failure_mode'] in ed.FAILURE_MODES_SOFTWARE
for path in ('alignment.md', '_common/contracts/research_admission_contract.md', 'pipelines/2-work/spec.md'):
    assert Path(path).is_file(), path
(root / 'trial.json').write_text(json.dumps(row))
(root / '.delegation-policy').write_text('strict\n')
PY
CHANDRA_ROLE=worker python3 _common/ledgers/error_database.py append --repo-root "$scratch" --row-file "$scratch/trial.json" >/dev/null
python3 - "$scratch" <<'PY'
import sys
from pathlib import Path
from _common.ledgers import error_database as ed, ledger_common as lc
root = Path(sys.argv[1])
rows = ed.read_entries(root, '<P>')
assert len(rows) == 1 and rows[0]['actor_role'] == 'worker'
assert {'timestamp', 'git_commit', 'row_hash'} <= rows[0].keys()
directory = lc.db_dir(root, 'error', '<P>')
assert directory == root / 'results/ledgers/error/paper_<P>'
assert (directory / 'summary.csv').is_file()
assert lc.verify_chain(directory, 'trials.jsonl')['ok']
PY
```
