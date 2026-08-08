# Work (stage 2)

## Status

CONTRACT. Merges the former implementation (2), validation (3), and result-log
(4) stages into the loop's unit of work: **one ready DAG node → candidate
evidence → adversarial validation → admitted ledger row.** "Done" means a
ledger append that passed the executable admission gate — nothing else counts
as progress.

## Role

Generate candidate evidence for one `logic.md` node (or tightly-coupled
cluster), verify it against the admission gates, and land the outcome in the
ledgers. Routing between nodes is not decided here: the scheduler computes the
ready frontier from the mission DAG (all predecessors solid, obligations
discharged) and spawns one worker per ready node in parallel.

**Workers only (kernel §6):** this stage's appends are made by spawned worker
agents carrying `CHANDRA_ROLE=worker` — under the strict delegation policy the
orchestrating session's own appends are rejected by the gate.

**Packets (continuous work; no fragmentation):** the scheduler leases each
worker a PACKET — a chain of nodes extended along unambiguous successors —
worked IN ORDER in one session. The worker keeps an ungated scratch WAL at
`$CHANDRA_RUNTIME/paper_<P>/packets/<id>/packet_log.jsonl`, survives context
auto-compaction by re-reading it and continuing, and FLUSHES to the ledgers at
the packet boundary (prefer `append-batch`; summaries regenerate once). A
packet is interrupted only by: completion · structural failure needing
escalation · circuit breaker · budget. Notes, DAG views, and digests are the
observer's job after the flush — never the worker's.

## Invocation triggers

- The scheduler hands this worker a ready frontier node.
- A validation rejection scheduled a repair or a different method.
- An open obligation from a prior wave targets this node.

## Input contract

- Decomposition artifacts under `results/{project}/paper_{arxiv_number}/decomposition/`
  (`convention.md`, `derivation.md`, `ref.md`, `logic.md`,
  `implementation_plan_{lang}.md`, `summary.md`, plus the claim-ledger rendered
  views `claims.md` / `obligations.md` / `assumptions.md` and `result_seed.md`).
- The filled task template (`template.md`) for this node, including
  `§ Success criterion`: verification command, measured tolerance,
  reduction-to-baseline test.
- Upstream task outputs declared in the filled task file.

## Output contract

- Filled task file at `results/{project}/paper_{arxiv_number}/tasks/{task_id}/implementation.md` (see `template.md`; keep under ~250 lines, split along `logic.md` boundaries).
- Code at `results/{project}/paper_{arxiv_number}/codes/`; figures at `.../plots/`; per-iteration loop note at `.../loop_note/`.
- Evidence object: symbolic certificate, dimensional certificate, simulation record, theorem-transfer mapping, test output, counterexample, or citation bundle — with explicit evidence type.
- **Ledger appends (the canonical outcome):**
  - `_common/result_database.py append` — admitted/classified result; the append RUNS the admission gate (`verification.command` executed, evidence content-hashed, dependencies resolved).
  - `_common/claims_database.py append` — claim/obligation status transitions (admitted / refuted / discharged) with their settling `result_ref` / `discharged_by`; re-render the decomposition views after.
  - `_common/error_database.py append` — every trial, pass or fail; failures carry expected / observed / root_cause / fix_hypothesis / failure_mode.
  - `_common/knowledge_database.py append` — node status promotions (`hypothesis → preliminary → solid`; solid requires verifiable evidence and solid predecessors).
- Generated views refreshed: `result_database.py render-md` / `render-state`.

## Validation gates

A candidate result is admitted only if all gates pass:

1. Every symbol is defined in the source library or working context.
2. The claim states working context, evidence type, assumptions, dependencies, and provenance.
3. The evidence object matches the required evidence type.
4. Unit, dimension, frame, regime, and domain constraints are compatible.
5. Approximation claims specify parameter, norm, order, regime, and remainder obligations.
6. Simulation or empirical claims specify code/protocol, checks, uncertainty, and artifacts.
7. Checked claims have no unresolved `[OPEN]`, `[UNCHECKED]`, or circular evidence dependency.

Gates 1–2 and 7 are checked structurally by the ledgers; gates 3–6 are the
validator's brief. **Adversarial validation is process-isolated** (v2
orchestrator): a refuter session with read access only to {candidate evidence,
claim, contracts} must attempt rejection before a judge may admit; the judge
admits by running the ledger append. Admit / Reject / Fail outcomes:

- **Admit:** result-ledger row (gate-checked) + claim transition + rendered views refreshed.
- **Reject:** plain-language rejection naming the failed gate + an `[OPEN]` repair obligation appended to the claim ledger.
- **Fail:** error-ledger row with failed gate, root cause, and fix hypothesis.

## Gate for node closure

A node closes (and its successors join the ready frontier) only if all of:

1. Verification command passed within tolerance.
2. Reduction-to-baseline test passed when assumption relaxation is involved (the relaxed assumption cites its `reduction_obligation` — enforced by the claim ledger).
3. Evidence type is compatible with the claim being advanced.
4. No `[BLOCKING]`, `[OPEN]`, or `[UNCHECKED]` markers remain on the node's checked-claim path.

Theorem-transfer rule: record source theorem scope, mapping, preservation
obligations, and failure mode; transfer is never promoted with undischarged
obligations.

## Routing (computed, not prosed)

The scheduler routes from ledger state; the worker only reports outcomes:

- Missing source support → `pipelines/0-acquire/spec.md`.
- Ambiguous or undefined claim → `pipelines/1-decompose/spec.md`.
- Candidate evidence exists → validate here.
- All report claims admitted or classified → `pipelines/3-write/spec.md`.

## Status vocabulary

`checked`, `conditional`, `approximate`, `empirical`, `conjectural`,
`refuted`, `unchecked`, `existence_only`.

## Open design questions

- **Error-DB similarity metric** `[FUTURE]` — cross-task lookup for prior-fix
  import. Interim rule: match on `node_id` + verbatim error string.

## Companion files

- `template.md` (this directory) — the fill-in task scaffold, one per node.
- Alignment: `/alignment.md` (kernel). Admission contract: `_common/contracts/research_admission_contract.md`.
- Markers / discipline / progress: `_common/contracts/{markers,note_discipline,progress_principles}.md`.
