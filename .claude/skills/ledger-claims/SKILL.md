---
name: ledger-claims
description: Maintain claims, obligations, and assumptions as gated ledger entries and render their decomposition views. Load for "record a claim", "discharge an obligation", "relax an assumption", "request acquisition", or refreshing claims.md after a status change.
---

# ledger-claims — settle structured entries and render decomposition views

## When to use

- Decomposition produces claims, missing support, or explicit assumptions.
- An admitted result settles a claim or discharges a blocking obligation.
- A relaxation needs a reduction-to-baseline obligation, or a source is missing.

## Steps

1. Read `_common/contracts/research_admission_contract.md` and
   `pipelines/1-decompose/spec.md`. Run from the consumer repo root. Set `P` to
   the paper identifier and `PROJECT` to the output project. Use stable entry_id
   values; correct an entry with a complete new row under the same ID.
   Every append must come from an allowed delegated role under strict policy.

2. Inspect the schema and kind-specific requirements:
   ```bash
   python3 _common/ledgers/claims_database.py schema
   python3 _common/ledgers/claims_database.py describe-fields
   ```
   Every row requires paper, entry_id, kind, statement, and status. Timestamp and
   git_commit are filled automatically. Use these status sets:

   | kind | statuses | conditional fields |
   |---|---|---|
   | claim | open, in_progress, admitted, refuted, withdrawn | needed_evidence_type always; result_ref when admitted/refuted |
   | obligation | open, discharged, waived | discharged_by when discharged |
   | assumption | active, relaxed, retired | reduction_obligation when relaxed |

   needed_evidence_type uses the result-ledger evidence vocabulary; inspect it
   with `python3 _common/ledgers/result_database.py schema`. Optional node_ids,
   dependencies, and source_ids must be arrays; blocking must be boolean.

3. Draft an object for a single append or an array for a decomposition flush.
   This minimal array includes one valid entry of each kind:
   ```json
   [
     {"paper": "P", "entry_id": "a-baseline", "kind": "assumption",
      "statement": "Use the stated baseline regime", "status": "active"},
     {"paper": "P", "entry_id": "o-source", "kind": "obligation",
      "statement": "Acquire the source defining the baseline", "status": "open",
      "owner": "0-acquire", "blocking": true, "node_ids": []},
     {"paper": "P", "entry_id": "c-identity", "kind": "claim",
      "statement": "The identity holds in the baseline regime", "status": "open",
      "needed_evidence_type": "exact_proof"}
   ]
   ```
   Supply actual working_context, dependencies, source_ids, and node_ids before
   treating a real claim as ready. The minimal schema does not prove completeness.
   An open obligation with owner exactly `0-acquire` feeds acquisition jobs in
   `orchestrator/src/jobs.ts` once the mission has a DAG. Describe what source or
   method is missing; follow `pipelines/0-acquire/spec.md` for the acquisition.

4. Append the proposed entries through their reference gate:
   ```bash
   CHANDRA_ROLE=worker python3 _common/ledgers/claims_database.py append-batch --repo-root . --rows-file "${CLAIM_ROWS:?}"
   CHANDRA_ROLE=worker python3 _common/ledgers/claims_database.py append --repo-root . --row-file "${CLAIM_ROW:?}"
   ```
   Use one of these forms for the prepared input; omit the file flag for stdin.
   Rows normally land in `results/ledgers/claim/paper_<P>/entries.jsonl`, with
   actor_role and a chain hash recorded. Summary CSV is regenerated automatically.
   Batch dedup compares entry_id plus latest status/statement, not every field.
   Use single append or append-batch --force for an owner, reference, or dependency
   change that keeps status and statement. Force does not bypass admission.
   A later rejection leaves earlier batch rows appended; query before replaying.
   Claim batches currently regenerate summaries per appended row.

5. Settle references in dependency order. Append the supporting result/node or
   reduction obligation first, then submit a complete updated entry:

   | transition | gate actually checks | verify before closure |
   |---|---|---|
   | claim → admitted | latest result_ref in the same paper exists and is neither refuted nor unchecked | evidence type and result scope justify the claim |
   | claim → refuted | latest result_ref in the same paper has status refuted | counterexample covers the stated scope |
   | obligation → discharged | discharged_by exists as a same-paper result or a knowledge node, including cross-paper | the cited result/node actually resolves this obligation |
   | assumption → relaxed | a same-paper historical obligation entry has the reduction_obligation ID | reduction-to-baseline verification passed and that obligation is discharged |

   Existence checks do not demand a solid discharge node or a discharged reduction
   obligation. Keep the stronger work-stage closure gates in `pipelines/2-work/spec.md`.
   The claims append does not run verification.command or resolve arbitrary
   dependencies; admitting evidence belongs in the result/knowledge ledgers.
   Both append forms expose --allow-missing-refs; when used to waive a missing
   reference it records allow_missing_refs in admission_flags. It does not waive
   an existing result's contradictory status or supply a missing required field.

6. Inspect the current entry and its transition history:
   ```bash
   python3 _common/ledgers/claims_database.py query --repo-root . --paper "${P:?}" --kind obligation --status open
   python3 _common/ledgers/claims_database.py query --repo-root . --paper "${P:?}" --entry-id "${ENTRY_ID:?}" --with-history
   ```
   Default query collapses by entry_id in append order, then applies filters.
   There is no query --owner flag; inspect owner in the returned JSON.
   Keep waived, withdrawn, and retired entries visible through their real states.

7. Re-render all three views into the decomposition directory:
   ```bash
   python3 _common/ledgers/claims_database.py render-md --repo-root . --paper "${P:?}" --out-dir "results/${PROJECT:?}/paper_${P}/decomposition"
   ```
   This writes `results/<project>/paper_<P>/decomposition/claims.md`,
   `results/<project>/paper_<P>/decomposition/obligations.md`, and
   `results/<project>/paper_<P>/decomposition/assumptions.md`.
   For one view, use --kind claim, obligation, or assumption; omit --out for
   stdout or supply --out with a file path. --out-dir always renders all three.
   Markdown rendering is latest-only and has no --with-history option.
   Never hand-edit claims.md, obligations.md, or assumptions.md: append and
   re-render. During packet work, hand this refresh to the observer after flush.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, subprocess, tempfile
from pathlib import Path
from _common.ledgers import admission as adm, claims_database as db
cli = '_common/ledgers/claims_database.py'
for args in [[], *[[s] for s in ('schema', 'describe-fields', 'append', 'append-batch', 'query', 'render-md')]]:
    subprocess.run(['python3', cli, *args, '--help'], check=True, stdout=subprocess.DEVNULL)
subprocess.run(['python3', '_common/ledgers/result_database.py', 'schema'], check=True, stdout=subprocess.DEVNULL)
schema = subprocess.check_output(['python3', cli, 'schema'], text=True)
assert all(repr(s) in schema for states in db.STATUSES_BY_KIND.values() for s in states)
text = (Path(os.environ['CLAUDE_SKILL_DIR']) / 'SKILL.md').read_text()
rows = json.loads(text.split(chr(96) * 3 + 'json\n')[1].split(chr(96) * 3)[0])
assert all(db.REQUIRED_FIELDS <= r.keys() for r in rows)
os.environ['CHANDRA_ROLE'] = 'worker'
with tempfile.TemporaryDirectory(prefix='claims-skill-', dir='/tmp') as tmp:
    root = Path(tmp)
    assert db.append_batch(rows, repo_root=root)['appended'] == 3
    assert db.append_batch(rows, repo_root=root)['skipped'] == 3
    for bad in ({**rows[2], 'status': 'admitted', 'result_ref': 'missing'},
                {**rows[1], 'status': 'discharged', 'discharged_by': 'missing'},
                {**rows[0], 'status': 'relaxed', 'reduction_obligation': 'missing'}):
        try:
            db.append_row(bad, repo_root=root)
        except adm.AdmissionError:
            pass
        else:
            raise AssertionError('missing settling reference admitted')
    db.append_row({**rows[0], 'status': 'relaxed', 'reduction_obligation': 'o-source'}, repo_root=root)
    assert len(db.query('P', repo_root=root)) == 3
    assert len(db.query('P', latest_only=False, repo_root=root)) == 4
    views = db.render_views('P', root / 'decomposition', repo_root=root)
    assert {Path(p).name for p in views.values()} == {'claims.md', 'obligations.md', 'assumptions.md'}
    assert all(Path(p).is_file() for p in views.values())
PY
```

## Companion files

- `_common/ledgers/claims_database.py`
- `.claude/skills/ledger-result-admit/SKILL.md`
- `.claude/skills/ledger-knowledge-node/SKILL.md`
