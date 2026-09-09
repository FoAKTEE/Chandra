---
name: ledger-error-trial
description: Record every pass, fail, crash, and partial trial in the error ledger with measured attribution, domain tags, and a DAG anchor. Load for "log this trial", "record a failure", "flush the packet WAL", or a repeated uncategorized failure.
---

# ledger-error-trial — retain every trial under its DAG node

## When to use

- A verifier finishes, fails, crashes, or produces only partial evidence.
- A packet reaches its flush boundary or must stop for structural escalation.
- A failure tag does not fit, or a prior trial needs an amendment.

## Steps

1. Read `alignment.md` §1 and the packet contract in `pipelines/2-work/spec.md`.
   Run from the consumer repo root. Set `P`, `TASK`, and `NODE` to the actual
   paper, task, and globally namespaced DAG node. Preserve the command output
   and elapsed seconds even when the verifier exits nonzero. This ledger records
   observations; its append does not execute or certify a verification command.

2. Query the vocabulary instead of inventing a failure tag:
   ```bash
   python3 _common/ledgers/error_database.py schema
   python3 _common/ledgers/error_database.py describe-fields
   python3 _common/ledgers/error_database.py describe-domain --domain software
   python3 _common/ledgers/error_database.py list-tags --domain software
   python3 _common/ledgers/error_database.py describe-tag --domain software --tag test_failure
   ```
   Domains are symbolic, numerical, proof, and software. Use the actual domain
   in the last three commands; describe-domain supplies metrics, metadata keys,
   evidence-path templates, and tag meanings. Stages are source_import,
   decomposition, implementation, validation, result_log, writing, and escalation.

3. Compose one full row per trial. Required fields are `paper`, `task_id`,
   `iteration`, `stage`, `domain`, `change_type`, `change_summary`, `metric`,
   `pass_fail`, and `wall_clock_seconds`. The metric object requires name,
   value, threshold, and pass. A minimal pass example with its DAG anchor is:
   ```json
   {
     "paper": "P", "task_id": "integer-check", "iteration": 1,
     "stage": "validation", "domain": "software", "change_type": "structural",
     "change_summary": "Check the integer equality with a direct assertion",
     "metric": {"name": "build_exit_code", "value": 0, "threshold": 0, "pass": true},
     "pass_fail": "pass", "wall_clock_seconds": 0.02, "node_id": "P::integer-check"
   }
   ```
   Replace illustrative values with the observed trial. Include expected,
   observed, root_cause, and fix_hypothesis on every trial per the kernel; on a
   pass, state that no failure was observed and what check follows.
   For fail, crash, or partial, those four fields plus `failure_mode` are
   mechanically required. Add this shape to a complete row and set the actual
   failing outcome, metric, time, and evidence location:
   ```json
   {
     "expected": "The integer assertion exits 0",
     "observed": "AssertionError; command output retained with the trial evidence",
     "root_cause": "The checked expression evaluates to 4; the assertion expected 5",
     "fix_hypothesis": "Reconcile the expected value with the stated equality",
     "failure_mode": "test_failure"
   }
   ```
   Cite tool-verified evidence in observed and root_cause. If the cause remains
   unknown, say so and name the next diagnostic; do not convert a guess to fact.

4. Anchor each row to its existing `node_id`. Omit `node_seq` so append assigns
   the next index under that node; knowledge and trial sequences are separate.
   The schema permits no anchor, but a node's work must remain linked to its DAG.
   Keep `change_type` honest: structural changes the method, scalar changes a
   parameter, refactor simplifies while preserving behavior. This field feeds
   the no-tweak and simplification queries; a retry is not a structural pivot.
   `pass_fail` is pass, fail, crash, partial, or amended. Append an amended row
   with the prior timestamp and git_commit in notes; never erase the prior trial.

5. Buffer packet trials immediately in the runtime WAL at
   `${CHANDRA_RUNTIME}/paper_<P>/packets/<id>/packet_log.jsonl`.
   This is ungated scratch, not admitted memory. Keep complete trial objects as
   JSONL in the trial portion; if the WAL mixes other events, extract only trial
   payloads. Re-read it after compaction and continue the unfinished packet.
   At completion or a permitted interruption, convert those objects to a JSON
   array in `TRIAL_ROWS`, outside the repo. For a WAL containing only trial rows:
   ```bash
   python3 - "${PACKET_WAL:?}" > "${TRIAL_ROWS:?}" <<'PY'
   import json, sys
   from pathlib import Path
   rows = [json.loads(s) for s in Path(sys.argv[1]).read_text().splitlines() if s.strip()]
   json.dump(rows, sys.stdout)
   PY
   CHANDRA_ROLE=worker python3 _common/ledgers/error_database.py append-batch --repo-root . --rows-file "${TRIAL_ROWS:?}"
   ```
   Append one standalone trial using a row file, or omit the flag for stdin:
   ```bash
   CHANDRA_ROLE=worker python3 _common/ledgers/error_database.py append --repo-root . --row-file "${TRIAL_ROW:?}"
   ```
   Strict delegation requires an allowed role; the row records `actor_role`.
   Appends auto-fill timestamp/git_commit, hash-chain the row, and normally write
   `results/ledgers/error/paper_<P>/trials.jsonl`. Batch summaries refresh once per
   touched paper. A bad row leaves the admitted prefix intact; inspect it before
   retrying the suffix. Neither append form deduplicates or accepts skip flags.

6. Apply the taxonomy self-correction protocol when no existing tag fits.
   On the first instance per failure type, use `uncategorized_<domain>`, explain
   the mismatch in notes, and put a candidate tag in `next_hypothesis`.
   On the second instance with the same root cause, pause that loop and route a
   schema update to `_common/ledgers/error_database.py`: append the tag to the
   domain tuple, add its meaning, and extend metric/evidence templates if needed.
   Land the schema change through its verification and commit workflow, then
   append amended rows citing the earlier records. If schema edits are outside
   the worker's scope, report the needed change to the owner; preserve all trials.
   Three uncategorized rows without the schema update violate the protocol.
   Taxonomy recurrence is a procedural rule; append itself does not count it.

7. Read `.claude/skills/loop-no-tweak/SKILL.md` before the next trial and hand
   rendered-view work to the observer after packet flush. Read trials through
   `.claude/skills/ledger-query-views/SKILL.md`; there is no error-ledger query CLI.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, re, subprocess, tempfile
from pathlib import Path
from _common.ledgers import error_database as db
cli = '_common/ledgers/error_database.py'
for args in [[], *[[s] for s in ('schema', 'describe-fields', 'describe-domain', 'list-tags', 'describe-tag', 'append', 'append-batch')]]:
    subprocess.run(['python3', cli, *args, '--help'], check=True, stdout=subprocess.DEVNULL)
schema = subprocess.check_output(['python3', cli, 'schema'], text=True)
assert all(repr(s) in schema for s in (*db.DOMAINS, *db.CHANGE_TYPES, *db.PASS_FAIL))
tags = subprocess.check_output(['python3', cli, 'list-tags', '--domain', 'software'], text=True)
assert 'uncategorized_software' in tags and 'test_failure' in tags
subprocess.run(['python3', cli, 'describe-tag', '--domain', 'software', '--tag', 'test_failure'], check=True, stdout=subprocess.DEVNULL)
text = Path('.claude/skills/ledger-error-trial/SKILL.md').read_text()
fence = chr(96) * 3
examples = [json.loads(s) for s in re.findall(fence + r'json\n(.*?)\n\s*' + fence, text, re.S)]
row, failure = examples
assert db.REQUIRED_FIELDS <= row.keys() and db.REQUIRED_ON_FAIL == failure.keys()
os.environ['CHANDRA_ROLE'] = 'worker'
with tempfile.TemporaryDirectory(prefix='error-skill-', dir='/tmp') as tmp:
    bad = {**row, 'pass_fail': 'fail'}
    try:
        db.append_row(bad, repo_root=tmp)
    except ValueError:
        pass
    else:
        raise AssertionError('failure without attribution accepted')
    failing = {**row, **failure, 'iteration': 2, 'pass_fail': 'fail',
               'metric': {'name': 'build_exit_code', 'value': 1, 'threshold': 0, 'pass': False}}
    assert db.append_batch([row, failing], repo_root=tmp)['appended'] == 2
    assert [r['node_seq'] for r in db.node_trials('P', 'P::integer-check', repo_root=tmp)] == [1, 2]
PY
```

## Companion files

- `_common/contracts/progress_principles.md`
- `_common/ledgers/admission.py`
