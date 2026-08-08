---
role: template for generating one implementation.md per claim or logic-DAG node
scope: code / symbolic / simulation / counterexample / theorem-transfer / citation-grounding work downstream of stage 1
invoked_by: decomposition completion (`logic.md`, `claims.md`, `obligations.md`, and `implementation_plan_{language}.md` exist)
output: one filled implementation.md per task node, written to `results/{project}/paper_{arxiv_number}/tasks/{task_id}/implementation.md`
companions:
  - ../1-decompose/spec.md
  - ../../notes/multi_timescale_tracking_template.md
  - ../../_common/contracts/markers.md
  - ../../_common/contracts/note_discipline.md
  - ../../_common/contracts/progress_principles.md
  - ../../_common/contracts/research_admission_contract.md
  - ../../alignment.md
---

# Implementation Template

This file is the template. Copy it to `results/{project}/paper_{arxiv_number}/tasks/{task_id}/implementation.md` and fill in the placeholders.

One filled file corresponds to one node, or one tightly coupled cluster of nodes, in `logic.md`. Keep the filled file under ~250 lines; split along `logic.md` boundaries when it grows too large.

## 0. Header

**Task ID:** `{{task_id}}`
**Paper:** `arxiv-{{arxiv_number}}` — `{{paper_short_title}}`
**Logic-graph nodes covered:** `{{node_ids_from_logic_md}}`
**Language:** Mathematica / Python / proof assistant / Julia / C++ / other: `{{lang}}`
**Method class:** symbolic / dimensional / simulation / counterexample / theorem-transfer / assumption-relaxation / refactor

## 1. Claim

State the claim this task tries to support in one sentence.

> {{claim_sentence}}

## 2. Success Criterion

- **Needed evidence type:** `{{proof / derivation / approximation check / simulation / citation / counterexample}}`
- **Done when:** `{{condition_in_one_sentence}}`
- **Verification command:** `{{verification_command}}`
- **Measured tolerance / metric:** `{{metric_with_threshold}}`
- **Open obligations before start:** `{{open_obligations_or_none}}`
- **Reduction-to-baseline test (assumption-relaxation only):** `{{reduction_test_or_NA}}`

If the condition cannot be stated as one verifiable expression, return to `logic.md` and split the task.

## 3. Motivation

Why this node, why now? Tie it to the claim or paper figure/equation.

> {{motivation}}

## 4. Inputs From Decomposition

| Artifact | Path | Required content |
|---|---|---|
| convention | `results/{{project}}/paper_{{arxiv_number}}/decomposition/convention.md` | symbol -> physics meaning |
| derivation | `results/{{project}}/paper_{{arxiv_number}}/decomposition/derivation.md` | equation labels this node implements |
| logic | `results/{{project}}/paper_{{arxiv_number}}/decomposition/logic.md` | DAG node definitions and dependencies |
| implementation_plan | `results/{{project}}/paper_{{arxiv_number}}/decomposition/implementation_plan_{{lang}}.md` | code/work partition for this node |
| ref | `results/{{project}}/paper_{{arxiv_number}}/decomposition/ref.md` | needed external citations |
| assumptions | `results/{{project}}/paper_{{arxiv_number}}/decomposition/assumptions.md` | symmetries / limits / regimes |
| claims | `results/{{project}}/paper_{{arxiv_number}}/decomposition/claims.md` | claim, evidence type, deps, status |
| obligations | `results/{{project}}/paper_{{arxiv_number}}/decomposition/obligations.md` | open obligations and verifier requirements |
| result_seed | `results/{{project}}/paper_{{arxiv_number}}/decomposition/result_seed.md` | initial result status and dependencies |

**Upstream task outputs:** `{{completed task files and result paths, or none}}`

## 5. Execution Rules

- Read `alignment.md` and `_common/contracts/research_admission_contract.md` before work.
- Implement one node or cluster only; no silent scope expansion.
- Sub-agents may run in parallel for independent nodes, but each prompt must include `alignment.md` and `_common/contracts/research_admission_contract.md`.
- If stuck for 30 minutes or 3 iterations, run `pipelines/0-acquire/spec.md` before repeating the same method.

## 6. Files And Links

| Slot | Path / URL |
|---|---|
| Reference paper | `ref-paper/arxiv-{{arxiv_number}}/` |
| Reference code | `ref-code/{{ref_code_dir}}/` |
| Decomposition outputs | `results/{{project}}/paper_{{arxiv_number}}/decomposition/` |
| Code output | `results/{{project}}/paper_{{arxiv_number}}/codes/` |
| Plot / figure output | `results/{{project}}/paper_{{arxiv_number}}/plots/` |
| Loop notes | `results/{{project}}/paper_{{arxiv_number}}/loop_note/` |
| Progress dir | `progress/paper_{{arxiv_number}}/{{task_id}}/` |
| Git branch | `{{branch}}` |

## 7. Architecture

Each file must map to one or more `logic.md` nodes.

```text
results/{{project}}/paper_{{arxiv_number}}/codes/
├── {{NN_module_name}}.{{ext}}     # node {{node_id}} - {{purpose}}
└── main.{{ext}}                   # runs nodes in dependency order, exits non-zero on validation failure
```

## 8. Phase Plan

Phases come directly from `logic.md`. Nodes in one phase may run in parallel; phases are sequential.

### Phase 1 - `{{phase_1_name}}`
- **Nodes:** `{{node_ids}}`
- **Files:** `{{file_list}}`
- **Test:** `{{single_assertion}}`
- **Estimate:** `{{hours}}` h

### Phase 2 - `{{phase_2_name}}`
- **Nodes:** `{{node_ids}}`
- **Files:** `{{file_list}}`
- **Test:** `{{single_assertion}}`
- **Estimate:** `{{hours}}` h

## 9. Quick-Win Path

Minimum sequence that produces one end-to-end smoke result.

1. `{{phase_id}}` — `{{minimal_action}}`
2. `{{phase_id}}` — `{{minimal_action}}`
3. **Smoke check:** `{{looser_metric}}`

## 10. First Test Parameters

| Parameter | Value | Notes |
|---|---|---|
| `{{param}}` | `{{value}}` | `{{rationale_or_source_equation}}` |

## 11. Risk Mitigation

| Risk | Likely signature | Mitigation |
|---|---|---|
| `{{risk}}` | `{{how_you_will_notice}}` | `{{concrete_action}}` |

## 12. Current State

- `[SOLID]` `{{what_works_with_evidence_path}}`
- `[PRELIMINARY]` `{{partial_with_quantitative_gap}}`
- `[BLOCKING]` `{{what_is_blocking_with_signature}}`
- `[OPEN]` `{{remaining_obligation_and_needed_evidence}}`

## 13. Forbidden Actions

List task-specific bans. Do not repeat general rules from `alignment.md`.

- `{{forbidden_action_specific_to_this_task}}`

## 14. Promise Tag

A `<promise>` tag is committed only after the verification command has run and the metric is within threshold.

- **Promise format:** `<promise>{{TASK_ID}} {{METRIC}} WITHIN {{THRESHOLD}}</promise>`
- **Required in commit body:** verbatim verification output, measured metric value, admitted claim/evidence type, and artifact path.

## 15. Progress Update Principles

Inherits `../../_common/contracts/progress_principles.md`. Implementation-specific additions:

- Per-substage commit: every node in the phase plan that completes with a passing test gets its own commit when the user requests commits.
- Joint progress file: `progress/paper_{{arxiv_number}}/{{task_id}}/progress.md`.
- Loop notes: before compaction, write `results/{{project}}/paper_{{arxiv_number}}/loop_note/note_session_{{id}}_loop_{{n}}.md`.
- State-note sync: every stage transition updates `${RESEARCH_STATE}` with result-log outcomes and any `[BLOCKING]`, `[FUTURE]`, `[OPEN]`, or `[UNCHECKED]` markers.

## 16. Termination Checklist

- [ ] Verification command ran and output is pasted.
- [ ] Result-log delta records claim, evidence type, evidence, dependencies, assumptions, status, and open obligations.
- [ ] Metric is within the threshold in §2.
- [ ] Reduction-to-baseline test passed when relevant.
- [ ] No `[BLOCKING]`, `[OPEN]`, or `[UNCHECKED]` markers remain for this checked claim.
- [ ] No silent scope expansion: deliverable matches §1.
- [ ] Contributing sub-agents had `alignment.md` plus `_common/contracts/research_admission_contract.md` injected.

If any box is unchecked, the task is not done.
