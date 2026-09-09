---
name: chandra-orient
description: Orient in the Chandra repo — the closed-loop invariant, where every contract, ledger CLI, pipeline spec, and skill lives, and which skill to load for which moment (acquire, decompose, work a node, validate, write, commit, self-optimize). Load at the start of any Chandra task, when unsure which doc governs something, or when a worker prompt says "read the kernel first".
---

# chandra-orient — the map, and which skill for which moment

**Invariant:** the agent proposes; the verifier admits. Progress is a gated ledger append
(`_common/ledgers/admission.py` runs the row's verification command, hashes evidence,
resolves dependencies). Markdown is a rendered view. Read `alignment.md` (the ~2.4 KB kernel,
binding) and `_common/contracts/research_admission_contract.md` before any work;
`INDEX.md` wins when docs disagree.

## Where things live

| need | source of truth |
|---|---|
| kernel + admission contract | `alignment.md`, `_common/contracts/research_admission_contract.md` |
| stage contracts | `pipelines/0-acquire/spec.md`, `pipelines/1-decompose/spec.md`, `pipelines/2-work/spec.md` (+ `pipelines/2-work/template.md`), `pipelines/3-write/spec.md` |
| ledgers (schema-as-code; `schema` / `describe-fields` print the spec) | `_common/ledgers/{result,error,knowledge,claims}_database.py`, gate `_common/ledgers/admission.py`, chains `_common/ledgers/ledger_common.py` |
| loop controls | `_common/loop/loop_policy.py` (crash-triage, check-pivot, simplification-status, paper-refresh), `_common/loop/loop_gate.py` (circuit breaker) |
| views | `_common/visualization/dag_mermaid.py`, `_common/visualization/dashboard.py`, `render-md` / `render-state` on the ledgers |
| commit grammar (enforced) | `_common/contracts/commit_template.md`, hook `_common/hooks/commit-msg` |
| markers, note discipline, cadence | `_common/contracts/markers.md`, `_common/contracts/note_discipline.md`, `_common/contracts/progress_principles.md`, `notes/multi_timescale_tracking_template.md` |
| runtime (waves, workers, validators, observer, digest) | `orchestrator/src/main.ts` and `orchestrator/README.md` |
| machine-readable constants shared with the runtime | `python _common/contract.py manifest` |
| skills (this registry) | `.claude/skills/INDEX.md` (generated), `python _common/skill_registry.py list` |

Domains: `symbolic`, `numerical`, `proof`, and `software` (the repo optimizing itself).
Roles: appends need `CHANDRA_ROLE` ∈ worker / validator / observer under `.delegation-policy: strict`.

## Which skill, which moment

`python _common/skill_registry.py list` prints the live index. By moment:

- start of a mission / unsure what governs → this skill, then `mission-run`
- source missing, stalled node → `acquire-source` (and `vlm-pdf-to-tex` for PDF-only math)
- paper → claims + DAG → `decompose-paper`, `ledger-claims`, `ledger-knowledge-node`, `dag-mermaid`
- working a leased node/packet → `work-packet`, `task-template`, `ledger-error-trial`, `ledger-result-admit`, `loop-no-tweak`
- candidate evidence exists → `adversarial-validate`
- every N iterations / at closure → `write-paper`, `intro-cars`, `paper-checkpoints`
- before any commit → `commit-gated`; the three notes → `three-notes`; markers → `markers-discipline`
- code changes to the methodology itself → `code-quality-orientation` … `code-quality-review`, `self-optimize`, `tool-promote`
- delegating to a GPT-6 worker → `codex-gpt6-max`; keeping a new recipe → `skill-write`; loading skills into any client → `skill-load`

## Verify

```bash
python3 _common/contract.py manifest >/dev/null && python3 _common/skill_registry.py validate --root . chandra-orient
```
