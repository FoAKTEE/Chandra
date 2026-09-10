---
name: dag-mermaid
description: Render per-paper and project-wide Mermaid DAGs, inspect duplicate candidates, and read node progress from linked ledger history. Load for "render logic.md", "merge the giant DAG", "dedupe derivations", "show DAG progress", or "inspect this node".
---

# dag-mermaid — render the giant DAG and inspect its attached records

## When to use

- Decomposition or a node promotion changes the dependency graph.
- Another paper introduces potentially repeated equations or derivations.
- The observer needs progress counts or the evidence and trials under a node.

## Steps

1. Read the Unified DAG section in `pipelines/1-decompose/spec.md` and the
   visualization entries in `INDEX.md`. Run from the consumer repo root. Set
   `P`, `PROJECT`, and `NODE` to the actual paper, project, and namespaced node.
   The renderer reads knowledge and error ledgers; editing Mermaid does not
   update research state. Keep per-paper logic.md and the merged DAG as views.

2. Admit the node records before rendering. Inspect required fields with:
   ```bash
   python3 _common/ledgers/knowledge_database.py schema
   python3 _common/ledgers/knowledge_database.py describe-fields
   ```
   Required fields are paper, node_id, task_id, domain, status, and summary;
   solid also requires verifiable evidence. A minimal shared-node proposal is:
   ```json
   {
     "paper": "_shared", "node_id": "_shared::identity", "task_id": "identity",
     "domain": "symbolic", "status": "hypothesis",
     "summary": "Common identity under an explicit convention", "predecessors": []
   }
   ```
   Use `PAPER::node` for ordinary nodes and `_shared::node` for shared support.
   Preserve predecessor arrays and verbatim equation_labels. Put the actual
   objects in a JSON array; solid rows must pass the gate described in
   `.claude/skills/ledger-knowledge-node/SKILL.md` before claiming closure:
   ```bash
   CHANDRA_ROLE=worker python3 _common/ledgers/knowledge_database.py append-batch --repo-root . --rows-file "${NODE_ROWS:?}"
   ```
   Batch dedup skips a paper/node whose latest status and summary match. Use
   --force when intentionally changing its other fields without changing those
   two; admission still runs. Inspect partial appends before retrying a batch.

3. Render the per-paper graph and merge the project's papers:
   ```bash
   python3 _common/visualization/dag_mermaid.py render --repo-root . --paper "${P:?}" --out "results/${PROJECT:?}/paper_${P}/decomposition/logic.md"
   python3 _common/visualization/dag_mermaid.py merge --repo-root . --papers "${P:?}" "${OTHER_PAPER:?}" _shared --out "results/${PROJECT:?}/GLOBAL_DAG.md"
   ```
   Replace the paper list with the project's actual IDs, including _shared when
   used. Omit --papers to discover every knowledge-ledger paper in either layout;
   that discovery has no project filter. Merge emits a subgraph per paper and
   cross-paper edges, not a semantic deduplication. Render/merge default to
   stdout; --out - also prints Markdown. Missing per-paper nodes reject render;
   automatic discovery with no papers exits 1.

4. Collect duplicate candidates after importing each paper:
   ```bash
   python3 _common/visualization/dag_mermaid.py duplicates --repo-root . --papers "${P:?}" "${OTHER_PAPER:?}" _shared
   ```
   JSON clusters carry reason, key, and nodes containing paper/node_id/summary.
   Reasons are shared_equation_label or matching_summary after normalization.
   They are heuristic candidates, not proofs of equivalence. Have the
   orchestrator assign the reformulation pass required by the decomposition
   spec, with strong mathematical review of scope, conventions, and assumptions.

5. Record the reformulation decision through node appends. Establish the
   canonical shared derivation with its evidence and predecessors; for different
   regimes, retain separate nodes. Cite the old timestamp/git_commit and shared
   ID in amendment notes, then update active dependent rows to point at shared
   support. Inspect history with:
   ```bash
   python3 _common/ledgers/knowledge_database.py query --repo-root . --paper "${P:?}" --node-id "${NODE:?}" --with-history
   ```
   Current code ignores amended rows when choosing the active node. Therefore
   an amended per-paper copy does NOT disappear or redirect its old edges. There
   is no CLI that physically collapses aliases as promised by the spec. Keep
   history, append explicit active dependency changes, and report the remaining
   alias-collapse limitation; do not claim that merge removed duplicate nodes.
   Refresh per-paper logic.md and `results/<project>/GLOBAL_DAG.md` afterward.

6. Read project progress and drill down beneath a node:
   ```bash
   python3 _common/visualization/dag_mermaid.py progress --repo-root . --papers "${P:?}" "${OTHER_PAPER:?}" _shared
   python3 _common/visualization/dag_mermaid.py node-view --repo-root . --paper "${P:?}" --node-id "${NODE:?}"
   ```
   Progress returns paper, node_id, status, n_knowledge, n_trials, pass, and fail.
   Fail counts fail/crash/partial trials. Node-view returns paper, node_id,
   latest status, knowledge history, and errors; a missing node yields null
   status and possibly empty lists. Knowledge and errors attach UNDER node_id
   with separate auto-numbered node_seq values; extra records are not extra nodes.
   In Mermaid, k<N> counts all knowledge records; t<N>✗<F> counts trials/failures.
   Read status glyphs as ● solid, ◐ preliminary, ○ hypothesis, ✗ blocking,
   □ future; △ marks a concept advance. Dashed edges mean predecessor outside
   the selected scope, not an admitted exemption from the dependency gate.
   Progress may expose error-only anchors with null status; repair their missing
   knowledge records through admission. A failed trial remains activity until
   verified node/result progress is admitted.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, subprocess, tempfile
from pathlib import Path
from _common.ledgers import knowledge_database as kdb
from _common.visualization import dag_mermaid as dag
cli = '_common/visualization/dag_mermaid.py'
for args in [[], *[[s] for s in ('render', 'merge', 'duplicates', 'progress', 'node-view')]]:
    subprocess.run(['python3', cli, *args, '--help'], check=True, stdout=subprocess.DEVNULL)
for sub in ('schema', 'describe-fields', 'append-batch', 'query'):
    subprocess.run(['python3', '_common/ledgers/knowledge_database.py', sub, '--help'], check=True, stdout=subprocess.DEVNULL)
text = (Path(os.environ['CLAUDE_SKILL_DIR']) / 'SKILL.md').read_text()
row = json.loads(text.split(chr(96) * 3 + 'json\n')[1].split(chr(96) * 3)[0])
assert kdb.REQUIRED_FIELDS <= row.keys()
os.environ['CHANDRA_ROLE'] = 'worker'
with tempfile.TemporaryDirectory(prefix='dag-skill-', dir='/tmp') as tmp:
    root = Path(tmp)
    a = {**row, 'paper': 'A', 'node_id': 'A::identity'}
    b = {**row, 'paper': 'B', 'node_id': 'B::identity', 'predecessors': ['A::identity']}
    assert kdb.append_batch([a, b], repo_root=root)['appended'] == 2
    assert dag.find_duplicates(['A', 'B'], repo_root=root)[0]['reason'] == 'matching_summary'
    merged = dag.render_merge(['A', 'B'], repo_root=root)
    assert chr(96) * 3 + 'mermaid' in merged and 'flowchart TD' in merged
    assert 'n_A__identity --> n_B__identity' in merged
    assert '-.->' in dag.render_single('B', repo_root=root)
    assert dag.node_progress(['A'], repo_root=root)[0]['n_knowledge'] == 1
    assert len(dag.node_view('A', 'A::identity', repo_root=root)['knowledge']) == 1
    kdb.append_row({**a, 'status': 'amended'}, repo_root=root)
    assert dag.node_view('A', 'A::identity', repo_root=root)['status'] == 'hypothesis'
    subprocess.run(['python3', cli, 'render', '--paper', 'A', '--repo-root', tmp,
                    '--out', str(root / 'logic.md')], check=True, stdout=subprocess.DEVNULL)
    assert (root / 'logic.md').is_file()
PY
```

## Companion files

- `_common/visualization/dag_mermaid.py`
- `.claude/skills/ledger-error-trial/SKILL.md`
- `.claude/skills/ledger-query-views/SKILL.md`
