---
name: ledger-knowledge-node
description: Create namespaced DAG nodes and append evidence-backed promotions from hypothesis through preliminary to solid. Load for "add a DAG node", "promote a node", "append knowledge", "trace predecessors", or correcting a node's history.
---

# ledger-knowledge-node — grow the DAG through gated node records

## When to use

- Decomposition identifies an implementation block and its predecessors.
- A node's evidence supports promotion, demotion, or an amendment.
- A cross-paper dependency or shared derivation needs a stable identity.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`, and
   the Unified DAG section of `pipelines/1-decompose/spec.md`. Work from the
   consumer root with paper `P`, task `TASK`, and globally unique `NODE`.
   Use `PAPER::node` identifiers; keep the paper value free of the directory's
   paper_ prefix. Shared nodes conventionally use paper `_shared` and identifier
   `_shared::node`. The ledger does not enforce namespace syntax; preserve it.

2. Inspect the fields and state vocabulary:
   ```bash
   python3 _common/ledgers/knowledge_database.py schema
   python3 _common/ledgers/knowledge_database.py describe-fields
   ```
   Every row requires `paper`, `node_id`, `task_id`, `domain`, `status`, and
   `summary`; a solid row also requires `evidence`. Domains are symbolic,
   numerical, proof, and software. Status is hypothesis, preliminary, solid,
   blocking, future, or amended. Exist states are solid/preliminary/hypothesis;
   not-exist states are blocking/future. Amended is a historical correction.
   Existence does not imply verified closure: only solid carries that meaning.

3. Prepare a complete node object; this is a minimal hypothesis with its edges:
   ```json
   {
     "paper": "P", "node_id": "P::integer-check", "task_id": "integer-check",
     "domain": "software", "status": "hypothesis",
     "summary": "Check the integer equality", "predecessors": []
   }
   ```
   Use `predecessors` as an array of globally namespaced node IDs. Add verbatim
   `equation_labels`, `code_block_refs`, and boolean `concept_advance` where
   applicable. Add assumptions, source anchors, and task links without creating
   a separate DAG node for each trial or promotion.

4. Append one object or a JSON array of nodes in predecessor order:
   ```bash
   CHANDRA_ROLE=worker python3 _common/ledgers/knowledge_database.py append --repo-root . --row-file "${NODE_ROW:?}"
   CHANDRA_ROLE=worker python3 _common/ledgers/knowledge_database.py append-batch --repo-root . --rows-file "${NODE_ROWS:?}"
   ```
   Omit the file flag to read the corresponding object/array from stdin.
   Under strict delegation, append requires an allowed role and records
   `actor_role`. Rows normally land in `results/ledgers/knowledge/paper_<P>/nodes.jsonl`.
   Omit timestamp, git_commit, and node_seq for automatic assignment (assigned under the
   repository ledger lock, `_common/ledgers/txn.py`; a solid row's verification command runs
   before the lock and its predecessors are re-checked inside it). Each
   node_seq numbers another knowledge record under the same node, independently
   of its error-ledger trial sequence. Summary CSV is rendered automatically.

5. Inspect the existing node and walk its support before promotion:
   ```bash
   python3 _common/ledgers/knowledge_database.py query --repo-root . --paper "${P:?}" --node-id "${NODE:?}"
   python3 _common/ledgers/knowledge_database.py query --repo-root . --paper "${P:?}" --node-id "${NODE:?}" --with-history
   python3 _common/ledgers/knowledge_database.py predecessors --repo-root . --paper "${P:?}" --node-id "${NODE:?}" --transitive
   ```
   Omit --transitive for immediate predecessors. The walk reads only the named
   paper's ledger; cross-paper IDs appear but their ancestors are not expanded.
   Query their owning papers explicitly, including `--paper _shared` when needed.
   Query also supports --status, --task-id, --domain, --equation-label, and
   --concept-advance-only. Filters apply after collapse unless --with-history.

6. Promote by appending a full new row under the same node_id, carrying forward
   predecessors and still-valid fields. Move hypothesis to preliminary while
   obligations remain, then to solid when the verifier and closure gates pass.
   Keep the `evidence` field even when using a passing verification command.
   Cite an existing artifact path, a resolvable commit citation, or supply
   `verification: {command, timeout_s?, cwd?}` with an executable success check.
   The gate runs it with exit 0 required and records `verification_run`; existing
   file evidence is hashed into `evidence_sha256`. Let the gate populate these.
   Solid predecessors must exist and already be solid, including cross-paper
   support. Hypothesis/preliminary appends do not mechanically resolve every edge
   or check acyclicity; inspect the DAG before claiming readiness.
   Both append forms expose --skip-exec and --allow-missing-deps. Actual bypasses
   record skip_exec/allow_missing_deps in admission_flags. Missing-dependency
   bypass cannot waive an existing predecessor's non-solid status.

7. Correct history without losing the active record. Append `status=amended`
   with the prior timestamp/git_commit and reason in notes for an audit pointer.
   Latest views ignore amended rows; an amendment alone neither removes nor
   demotes the last active node. Append an explicit non-amended replacement to
   change active status, summary, or edges. Inspect --with-history afterward.
   Batch dedup compares only the latest status and summary for each paper/node.
   To change evidence or predecessors while keeping those two fields, use a
   single append or the batch override:
   ```bash
   CHANDRA_ROLE=worker python3 _common/ledgers/knowledge_database.py append-batch --repo-root . --rows-file "${NODE_ROWS:?}" --force
   ```
   Force bypasses deduplication, not admission. Batch failures leave earlier rows
   appended; inspect before retrying. Knowledge batches currently regenerate the
   summary per appended row, despite the generic once-per-packet description.

8. Hand the admitted node history to the observer for DAG refresh using
   `.claude/skills/dag-mermaid/SKILL.md`. For shared derivations, preserve the
   evidence scope and update active dependency edges explicitly; amended aliases
   alone do not collapse the rendered DAG. Keep each trial linked under its node
   using `.claude/skills/ledger-error-trial/SKILL.md`.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, re, subprocess, tempfile
from pathlib import Path
from _common.ledgers import admission as adm, knowledge_database as db
cli = '_common/ledgers/knowledge_database.py'
for args in [[], *[[s] for s in ('schema', 'describe-fields', 'append', 'append-batch', 'query', 'predecessors')]]:
    subprocess.run(['python3', cli, *args, '--help'], check=True, stdout=subprocess.DEVNULL)
schema = subprocess.check_output(['python3', cli, 'schema'], text=True)
assert all(repr(s) in schema for s in (*db.STATUSES, *db.DOMAINS))
assert set(db.EXIST_STATUSES) == {'solid', 'preliminary', 'hypothesis'}
assert set(db.NONEXIST_STATUSES) == {'blocking', 'future', 'retired'}
text = (Path(os.environ['CLAUDE_SKILL_DIR']) / 'SKILL.md').read_text()
row = json.loads(text.split(chr(96) * 3 + 'json\n')[1].split(chr(96) * 3)[0])
assert db.REQUIRED_FIELDS <= row.keys()
os.environ['CHANDRA_ROLE'] = 'worker'
with tempfile.TemporaryDirectory(prefix='knowledge-skill-', dir='/tmp') as tmp:
    root = Path(tmp)
    (root / 'evidence.txt').write_text('verified example\n')
    assert db.append_batch([row], repo_root=root)['appended'] == 1
    changed = {**row, 'predecessors': ['_shared::base']}
    try:
        db.append_batch([changed], repo_root=root)
    except adm.AdmissionError as exc:
        assert 'predecessors' in str(exc)
    else:
        raise AssertionError('changed predecessors admitted without lineage')
    changed['supersedes'] = db.query('P', repo_root=root)[0]['row_hash']
    assert db.append_batch([changed], repo_root=root, force=True)['appended'] == 1
    db.append_row({**row, 'status': 'amended'}, repo_root=root)
    assert db.query('P', repo_root=root)[0]['status'] == 'hypothesis'
    assert len(db.query('P', latest_only=False, repo_root=root)) == 3
    try:
        db.append_row({**row, 'node_id': 'P::child', 'status': 'solid',
                       'evidence': 'evidence.txt', 'predecessors': [row['node_id']]}, repo_root=root)
    except adm.AdmissionError:
        pass
    else:
        raise AssertionError('solid accepted on a hypothesis predecessor')
    landed = db.append_row({**row, 'status': 'solid', 'evidence': 'evidence.txt',
                            'supersedes': db.query('P', repo_root=root)[0]['row_hash']}, repo_root=root)
    assert landed['evidence_sha256'] == adm.sha256_file(root / 'evidence.txt')
    assert db.query('P', repo_root=root)[0]['status'] == 'solid'
PY
```

## Companion files

- `_common/ledgers/admission.py`
- `_common/ledgers/ledger_common.py`
- `pipelines/2-work/spec.md`
