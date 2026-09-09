---
name: decompose-paper
description: Turn imported paper sources into decomposition artifacts, claim/obligation/assumption entries, and a namespaced Mermaid DAG. Load for "decompose this paper", "source mirror ready", "empty mission DAG", or a validation finding that exposes an undefined claim or missing assumption.
---

# decompose-paper — turn source claims into executable work boundaries

## When to use

- Stage 0 has imported the source library and sealed its mirrors.
- The orchestrator finds a source mirror and an empty mission DAG.
- Work or validation exposes missing definitions, assumptions, or dependencies.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`, and
   `pipelines/1-decompose/spec.md`. Confirm source provenance and the actual tex inputs,
   including bibliography and sibling tex files. Receive only the task's context pack.
   In `orchestrator/src/agents.ts`, the automatic prompt reads `ref-paper/<P>/` literally;
   for a new arXiv mission use `P=arxiv-<id>` consistently. For an established mission,
   retain its paper id and explicitly supply any differing mirror or recovered-tex path.
2. Set `P`, `PROJECT`, and `DECOMP=results/$PROJECT/paper_$P/decomposition` from the task.
   Work as `CHANDRA_ROLE=worker`. Plan the artifact dependencies, then create the output
   directory. Use `results/<project>/paper_<P>/decomposition/` as the directory contract.
3. Delegate independent artifacts in parallel: `convention.md`, `ref.md`, and `summary.md`
   under `$DECOMP`. Give every sub-agent the kernel and admission contract explicitly,
   its relevant source files, and exclusive output paths; never the parent's full history.
   Sequence dependent work: derivation → logic → implementation plans → assumptions →
   claims → obligations → result seeds. A dependent pass consumes the completed prior pass.
4. Fill all decomposition artifacts; do not stop after a summary:

   | File under the decomposition directory | Required operational content |
   |---|---|
   | `convention.md` | Every variable mapped to its meaning; reconcile sibling tex conventions. |
   | `derivation.md` | Every derivation with original tex equation labels verbatim; explanation no longer than the source. |
   | `ref.md` | References used directly or semi-directly in the calculation, linked to imported sources. |
   | `logic.md` | Generated Mermaid DAG; one node per extractable implementation block. |
   | `implementation_plan_<lang>.md` | One plan per target language, partitioned by exactly those DAG nodes. |
   | `summary.md` | Motivation, goal, scope, conclusions, challenge, method innovation, bottlenecks. |
   | `claims.md`, `obligations.md`, `assumptions.md` | Generated claim-ledger views, never hand-edited. |
   | `result_seed.md` | Proposed result targets, statuses, dependencies, and visible open work. |

   Default language targets are Mathematica, Python, and a proof assistant unless the task
   specifies others. For recovered PDF tex, expose generated-label mappings; do not claim
   hidden upstream labels were recovered verbatim. Seeds do not themselves admit results.
   Use result statuses `checked`, `conditional`, `approximate`, `empirical`, `conjectural`,
   `refuted`, `unchecked`, or `existence_only`; retain `[OPEN]` work and cite admitted rows for checked seeds.
5. Perform the claim pass over every surface claim. Record working context, definitions,
   evidence type, assumptions, dependencies, source ids, and open obligations. Enumerate
   regularity, boundaries, units/frames, approximation remainders, symmetries, limits,
   and regimes where applicable. Classify imported evidence as `literature_grounding`
   unless stronger evidence has actually passed admission; undefined claims stay open.
6. Print both schemas, then prepare JSON arrays in `$CHANDRA_RUNTIME/decompose/`:
   ```bash
   python3 _common/ledgers/knowledge_database.py schema
   python3 _common/ledgers/claims_database.py schema
   ```
   Minimal knowledge batch with all six REQUIRED fields and explicit DAG edges:
   ```json
   [{"paper":"arxiv-0000.00000","node_id":"arxiv-0000.00000::boundary",
     "task_id":"boundary","domain":"symbolic","status":"hypothesis",
     "summary":"Check the boundary identity under explicit regularity assumptions.",
     "predecessors":[],"equation_labels":["eq:boundary"]}]
   ```
   Use global `PAPER::node` ids for both nodes and predecessors. Append in dependency
   order; imported claims start as hypotheses, not solid research results.
7. Prepare assumptions, claims, and obligations using the schema's five REQUIRED fields;
   `kind=claim` additionally requires `needed_evidence_type` even though the compact
   REQUIRED list does not include that conditional field:
   ```json
   [{"paper":"arxiv-0000.00000","entry_id":"a-boundary","kind":"assumption",
     "statement":"The fields satisfy the source boundary regularity conditions.",
     "status":"active","scope":"boundary regime","source_ids":["boundary-source"]},
    {"paper":"arxiv-0000.00000","entry_id":"c-boundary","kind":"claim",
     "statement":"The boundary identity follows under the imported assumptions.",
     "status":"open","needed_evidence_type":"symbolic_derivation",
     "working_context":"Source conventions in the boundary regime.",
     "dependencies":["a-boundary"],"source_ids":["boundary-source"],
     "node_ids":["arxiv-0000.00000::boundary"]},
    {"paper":"arxiv-0000.00000","entry_id":"o-boundary","kind":"obligation",
     "statement":"Verify regularity and the boundary term in eq:boundary.",
     "status":"open","blocking":true,"node_ids":["arxiv-0000.00000::boundary"],
     "source_ids":["boundary-source"]}]
   ```
   Reuse stable entry ids for later transitions. Admitted/refuted claims need an existing
   `result_ref`; discharged obligations need an existing `discharged_by`; relaxed
   assumptions need an existing `reduction_obligation`. Do not manufacture settling refs.
8. Land structured rows first, then render the claim views and both DAG views:
   ```bash
   export CHANDRA_ROLE=worker
   python3 _common/ledgers/knowledge_database.py append-batch --repo-root . --rows-file "$CHANDRA_RUNTIME/decompose/nodes.json"
   python3 _common/ledgers/claims_database.py append-batch --repo-root . --rows-file "$CHANDRA_RUNTIME/decompose/entries.json"
   python3 _common/ledgers/claims_database.py render-md --paper "$P" --repo-root . --out-dir "$DECOMP"
   python3 _common/visualization/dag_mermaid.py render --paper "$P" --repo-root . --out "$DECOMP/logic.md"
   python3 _common/visualization/dag_mermaid.py merge --repo-root . --out "results/$PROJECT/GLOBAL_DAG.md"
   python3 _common/visualization/dag_mermaid.py duplicates --repo-root .
   ```
   Batch dedup compares status/summary for knowledge and status/statement for claims.
   For an intentional change only to edges, sources, or other metadata, pass `--force`
   to the affected batch and verify the queried row; unchanged text otherwise skips it.
9. Give duplicate candidates to a reformulation agent with the strongest available math
   ability and a bounded context pack. Require evidence of identical scope before creating
   `_shared::node`; matching labels alone do not prove identity. The spec proposes amended
   per-paper copies, but queries ignore amended rows: amendment alone does not redirect a
   DAG. Land explicit replacement edges and check the resulting mission before continuing.
   Keep every predecessor visible in the paper's mission: current scheduling reads only
   that paper's knowledge rows, even when the merged Mermaid view spans several papers.
10. Run a final consolidation pass across tex, conventions, derivations, plans, ledger rows,
    and rendered views. Reject undefined symbols, inconsistent labels, missing files, cycles,
    unresolved predecessors, unsupported status upgrades, and omitted claim obligations.
    The scheduler measures decomposition by growth in knowledge rows, which alone does not
    verify this full artifact contract. Hand each work node to
    `.claude/skills/task-template/SKILL.md` only after the cross-check passes.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, re, subprocess, tempfile
from pathlib import Path
env = {**os.environ, 'CHANDRA_ROLE': 'worker'}
def cli(script, *args, data=None):
    return subprocess.run(['python3', script, *args], input=data, text=True,
                          capture_output=True, check=True, timeout=5, env=env).stdout
k = '_common/ledgers/knowledge_database.py'
c = '_common/ledgers/claims_database.py'
d = '_common/visualization/dag_mermaid.py'
for script, subs in [(k, ['schema', 'append-batch']), (c, ['schema', 'append-batch', 'render-md']), (d, ['render', 'merge', 'duplicates'])]:
    for sub in [None, *subs]:
        cli(script, *([sub] if sub else []), '--help')
assert 'hypothesis' in cli(k, 'schema') and 'needed_evidence_type' in cli(c, 'schema')
body = (Path(os.environ['CLAUDE_SKILL_DIR']) / 'SKILL.md').read_text()
fence = chr(96) * 3
nodes, entries = [json.loads(x) for x in re.findall(fence + r'json\n(.*?)\n[ \t]*' + fence, body, re.S)]
with tempfile.TemporaryDirectory(prefix='chandra-decompose-skill-', dir='/tmp') as tmp:
    root = Path(tmp)
    (root / '.delegation-policy').write_text('strict\n')
    for script, rows in [(k, nodes), (c, entries)]:
        cli(script, 'append-batch', '--repo-root', tmp, data=json.dumps(rows))
    out = root / 'decomposition'
    cli(c, 'render-md', '--paper', nodes[0]['paper'], '--repo-root', tmp, '--out-dir', str(out))
    assert all((out / f'{kind}.md').is_file() for kind in ['claims', 'obligations', 'assumptions'])
    assert 'flowchart' in cli(d, 'render', '--paper', nodes[0]['paper'], '--repo-root', tmp)
    assert 'flowchart' in cli(d, 'merge', '--repo-root', tmp)
    json.loads(cli(d, 'duplicates', '--repo-root', tmp))
PY
```

## Companion files

- `orchestrator/src/jobs.ts`
- `orchestrator/src/dag.ts`
- `_common/ledgers/claims_database.py`
