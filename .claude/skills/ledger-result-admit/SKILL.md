---
name: ledger-result-admit
description: Append an admitted or classified result through the executable evidence and dependency gate, then refresh its views. Load when asked to "admit a result", "append a result row", "flush result rows", or settle a validated work packet.
---

# ledger-result-admit — admit evidence through the result ledger

## When to use

- A node has candidate evidence and the validation outcome is ready to record.
- A packet has result rows to flush, or an earlier result needs correction.
- An append failed and its admission error needs reconciliation.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`, and
   the validation and closure gates in `pipelines/2-work/spec.md`.
   Run commands from the consumer repo root; set `P` to its paper identifier,
   `PROJECT` to its output project, and `ROW_FILE` to a prepared JSON file.
   As the delegated worker, carry `CHANDRA_ROLE=worker` on appends.
   Under strict delegation, worker, validator, observer, and human-override are
   the accepted roles; the gate records `actor_role`. Do not impersonate a worker
   from an orchestration session or use human-override to clear a rejection.

2. Inspect the executable schema before composing the row:
   ```bash
   python3 _common/ledgers/result_database.py schema
   python3 _common/ledgers/result_database.py describe-fields
   ```
   Required fields are `paper`, `result_id`, `name`, `working_context`, `claim`,
   `evidence_type`, `evidence`, `verifier_result`, `dependencies`, `assumptions`,
   `status`, `provenance`, and `open_obligations`. The last three collection
   fields `dependencies`, `assumptions`, and `open_obligations` must be arrays.
   Status is checked, conditional, approximate, empirical, conjectural, refuted,
   unchecked, or existence_only. Evidence type is exact_proof, symbolic_derivation,
   controlled_approximation, dimensional_consistency, numerical_simulation,
   empirical_measurement, statistical_inference, literature_grounding,
   counterexample, conjecture, unchecked_external_step, or existence_only.
   `verifier_result.verdict` is pass, fail, classified, rejected, or partial.

3. Prepare a complete row. This minimal executable example certifies only its
   stated integer assertion; replace the claim and verifier with the task's test:
   ```json
   {
     "paper": "P", "result_id": "integer-check", "name": "Integer equality",
     "working_context": {"domain": "Python integers", "units": "dimensionless"},
     "claim": "For Python integers, 2 + 2 equals 4.",
     "evidence_type": "exact_proof", "evidence": "Append-time integer assertion",
     "verifier_result": {"verdict": "pass"},
     "dependencies": [], "assumptions": [], "status": "checked",
     "provenance": {"stage": "validation"}, "open_obligations": [],
     "verification": {"command": "python3 -c 'assert 2 + 2 == 4'", "timeout_s": 10}
   }
   ```
   Put the executable command in `verification.command`; a command mentioned
   only in `verifier_result.command` is not executed. Optional `cwd` is resolved
   from the repo root; `timeout_s` defaults to 300. A nonzero exit or timeout
   rejects the append. A passing run with a claimed verdict of fail also rejects.
   The observed command, exit_code, duration_s, output_sha256, output_tail, and
   ran_at land in `verifier_result.execution`.

4. Preserve evidence and resolve support before admission. Use a file path string
   or `{"path":"results/<project>/paper_<P>/evidence/<artifact>"}` for file evidence;
   the gate computes `evidence_sha256`. A checked result needs verdict pass,
   no open obligations, and an existing file, a resolvable commit citation, or
   a verification run that passes at append. Never prefill hashes or execution
   outcomes. Append cited knowledge nodes before using `PAPER::node` or
   `_shared::node` in `dependencies`: these resolve against knowledge, even if
   a similarly named result exists. Plain unnamespaced dependencies are not
   resolved mechanically; verify them in the validation review.

5. Complete adversarial validation, then let the admitting role append:
   ```bash
   CHANDRA_ROLE=worker python3 _common/ledgers/result_database.py append --repo-root . --row-file "${ROW_FILE:?}"
   ```
   The command also accepts one object on stdin. Rows normally land in
   `results/ledgers/result/paper_<P>/results.jsonl`; summary CSV refreshes automatically.
   Inspect the response for `appended`, `status`, and `verified_exit_code` when
   execution ran. Check the stored row with:
   ```bash
   python3 _common/ledgers/result_database.py query --repo-root . --paper "${P:?}" --result-id "${RESULT_ID:?}" --with-history
   ```
   Structural validation does not prove symbol completeness, marker absence,
   absence of cycles, unit compatibility, or evidence sufficiency. Keep those
   checks in the validator's brief despite the broader wording in the work spec.

6. Flush a JSON array with the batch form when the packet is ready:
   ```bash
   CHANDRA_ROLE=worker python3 _common/ledgers/result_database.py append-batch --repo-root . --rows-file "${RESULT_ROWS:?}"
   ```
   Every row's `verification.command` runs first, outside the repository ledger lock; the batch
   then takes the lock once (`_common/ledgers/txn.py`) and re-validates each row's dependencies
   and evidence against the current files before appending, in order; summaries refresh once
   per touched paper. Never call an append CLI from inside a process that already holds the lock.
   A failing row stops the batch, leaving the admitted prefix on disk. Inspect
   history before retrying the remaining suffix; this batch does not deduplicate.
   Correct a result by appending its full replacement under the same `result_id`.
   Both append forms expose `--skip-exec` and `--allow-missing-deps`. They are
   explicit bypasses, not repairs: `skip_exec` is recorded when a supplied verifier
   is skipped; `allow_missing_deps` when missing dependencies are actually waived.
   Skipping execution alone does not satisfy checked-evidence requirements.

7. Record the validation outcome and refresh views after admission. Admit means
   the result append, settling claim transition, and refreshed views. Reject means
   name the failed gate and append an open repair obligation. Fail means log the
   trial with attribution in the error ledger; a failed certifying command cannot
   be smuggled into results. Follow `.claude/skills/ledger-claims/SKILL.md` and
   `.claude/skills/ledger-error-trial/SKILL.md` for those appends.
   Have the observer refresh views after packet flush:
   ```bash
   python3 _common/ledgers/result_database.py render-md --repo-root . --paper "${P:?}" --out "results/${PROJECT:?}/paper_${P}/results.md"
   python3 _common/ledgers/result_database.py render-state --repo-root . --paper "${P:?}"
   ```
   `render-state` prints the marked accepted-results block; replace that block in
   the research-state note through its owner. Never hand-edit the rendered table.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, re, subprocess, tempfile
from pathlib import Path
from _common.ledgers import admission as adm, result_database as db
cli = '_common/ledgers/result_database.py'
for args in [[], *[[s] for s in ('schema', 'describe-fields', 'append', 'append-batch', 'query', 'render-md', 'render-state')]]:
    subprocess.run(['python3', cli, *args, '--help'], check=True, stdout=subprocess.DEVNULL)
schema = subprocess.check_output(['python3', cli, 'schema'], text=True)
assert all(repr(s) in schema for s in (*db.STATUSES, *db.EVIDENCE_TYPES))
text = (Path(os.environ['CLAUDE_SKILL_DIR']) / 'SKILL.md').read_text()
row = json.loads(text.split(chr(96) * 3 + 'json\n')[1].split(chr(96) * 3)[0])
assert db.REQUIRED_FIELDS <= row.keys()
os.environ['CHANDRA_ROLE'] = 'worker'
with tempfile.TemporaryDirectory(prefix='result-skill-', dir='/tmp') as tmp:
    root = Path(tmp)
    (root / '.delegation-policy').write_text('strict\n')
    written = db.append_row(dict(row), repo_root=root)
    assert written['verifier_result']['execution']['exit_code'] == 0
    assert written['actor_role'] == 'worker'
    (root / 'evidence.txt').write_text('integer equality verified\n')
    hashed = db.append_row({**row, 'evidence': 'evidence.txt'}, repo_root=root)
    assert hashed['evidence_sha256'] == adm.sha256_file(root / 'evidence.txt')
    for bad in ({**row, 'verification': {'command': "python3 -c 'raise SystemExit(1)'"}},
                {**row, 'dependencies': ['missing::node']}):
        try:
            db.append_row(bad, repo_root=root)
        except adm.AdmissionError:
            pass
        else:
            raise AssertionError('inadmissible result accepted')
    assert len(db.query('P', repo_root=root)) == 1
    assert len(db.query('P', latest_only=False, repo_root=root)) == 2
    assert 'integer-check' in db.render_md('P', repo_root=root)
    assert 'BEGIN GENERATED: accepted-results' in db.render_state('P', repo_root=root)
PY
```

## Companion files

- `_common/ledgers/admission.py`
- `_common/ledgers/ledger_common.py`
- `pipelines/2-work/template.md`
