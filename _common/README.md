# Common Infrastructure

`_common/` holds shared contracts, schemas, renderers, loop controls, and
multi-agent helpers used by the pipeline stages. The root-level Python files are
compatibility wrappers; the implementation now lives in grouped subpackages.

## Layout

- `contracts/` — small markdown contracts that are injected or referenced by
  agents: result admission, markers, note discipline, progress principles, and the
  commit-message template (`commit_template.md`).
- `hooks/` — tracked git hooks. `commit-msg` enforces `contracts/commit_template.md`;
  `install.sh` activates them via `core.hooksPath`. Self-hosted by
  `tests/test_commit_msg_gate.py`.
- `ledgers/` — schema-as-code modules for append-only research memory:
  `error_database.py`, `result_database.py`, `knowledge_database.py`,
  `claims_database.py` (claims / obligations / assumptions), their shared base
  `ledger_common.py`, and `admission.py` — the executable admission gate run by
  every result/knowledge/claim append (verification commands executed, evidence
  content-hashed, cited dependencies resolved; bypasses recorded on the row).
  Markdown artifacts (`results.md`, `claims.md`, `obligations.md`,
  `assumptions.md`, the research-state accepted-results block) are rendered
  views over these ledgers (`render-md` / `render-state`), never hand-authored.
- `loop/` — live-loop control: `loop_policy.py` for read-only ledger queries and
  `loop_gate.py` for progress-gated termination.
- `visualization/` — `dag_mermaid.py`, the DAG-as-Mermaid renderer and per-node
  progress views, and `dashboard.py`, the self-contained per-paper HTML mission
  dashboard (KPIs, inline-SVG DAG with node drill-down, searchable ledger
  tables, hash-chain badges; light + dark).
- `quality/` — coding/review prompt bundles.

## Compatibility Wrappers

The historical CLI paths remain valid:

```bash
python _common/result_database.py schema
python _common/error_database.py describe-fields
python _common/knowledge_database.py query --paper P
python _common/claims_database.py schema
python _common/loop_policy.py describe-domain --domain symbolic
python _common/loop_gate.py status
```

Those files import and dispatch to the grouped implementations. New internal
imports should prefer package paths such as `_common.ledgers.result_database`.

Adversarial validation mechanics (context isolation, refuter→judge scheduling)
live in the v2 orchestrator (`orchestrator/`), not here — the former
`multiagent/` prompt framework was deleted when process-level isolation
replaced prose isolation.

## Validation Commands

Run after touching `_common`:

```bash
python3 -m pytest
python _common/ledgers/result_database.py schema
```

For the stage adapters, also run a temporary `init -> check-isolation -> next ->
status` flow. A valid long-horizon run must have more than ten iterations; the
adapters intentionally reject shorter plans.
