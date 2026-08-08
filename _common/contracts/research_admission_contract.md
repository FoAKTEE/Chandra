# Research Admission Contract

The central invariant is: **the agent proposes; the verifier admits.**

## State Shape
- `source library` = imported papers, definitions, code, datasets, citations, and prior checked results.
- `working context` = active model, assumptions, regime, symbols, units, frames, and current task constraints.
- `claim` = the statement being advanced.
- `evidence type` = what kind of support the claim requires: proof, derivation, approximation check, simulation, measurement, citation, counterexample, or conjecture.
- `open obligation` = unresolved work item with a clear expected evidence type.

## Accepted Result Schema
Every admitted result records `paper`, `result_id`, `name`, `working_context`, `claim`, `evidence_type`, `evidence`, `verifier_result`, `dependencies`, `assumptions`, `status`, `provenance`, and `open_obligations`.

Allowed statuses: `checked`, `conditional`, `approximate`, `empirical`, `conjectural`, `refuted`, `unchecked`, `existence_only`.
Executable schema: `_common/ledgers/result_database.py` (CLI wrapper: `_common/result_database.py`).
Decomposition claims / obligations / assumptions: `_common/ledgers/claims_database.py` (CLI wrapper: `_common/claims_database.py`).

## Evidence Types
Use distinct evidence types instead of scalar confidence:
- exact proof, symbolic derivation, controlled approximation, dimensional consistency, numerical simulation, empirical measurement, statistical inference, literature grounding, counterexample, conjecture, unchecked external step, existence-only result.

## Admission Gates
A claim is not accepted unless:
- all symbols are defined in the source library or working context;
- every assumption is explicit;
- the evidence matches the evidence type required by the claim;
- units, dimensions, frames, regimes, and dependencies are compatible;
- checked claims have no unresolved `[OPEN]` or `[UNCHECKED]` items;
- simulations, citations, and heuristics are not promoted to exact results.

The gates are EXECUTABLE at append time (`_common/ledgers/admission.py`), not prose:
a row's `verification.command` is run (exit 0 required) and its observed outcome
recorded on the row; evidence naming a file is content-hashed (`evidence_sha256`);
`checked` results and `solid` nodes require evidence in a verifiable form (existing
artifact, resolvable commit citation, or passing verification run); `::`-namespaced
dependencies must resolve to knowledge-ledger nodes; a `solid` node requires `solid`
predecessors. Bypass flags (`--skip-exec`, `--allow-missing-deps`) are recorded on
the row in `admission_flags` — visible in the ledger, never silent.

Under `.delegation-policy: strict` (kernel §6), appends additionally require a
delegated role: the process must carry `CHANDRA_ROLE` ∈ {worker, validator,
observer, human-override} — the orchestrating session has none, so it cannot do
the work itself. The role is recorded on every row as `actor_role`.

## Work-Step Discipline
Every agent action must record input claim, preconditions, candidate step, generated open obligations, evidence or failure, and verifier result.

## Reporting Discipline
Final prose is rendered from the accepted-results log. Open obligations, unchecked steps, existence-only results, and conditional assumptions must remain visible.

The ledgers are canonical; prose artifacts are GENERATED views, never hand-authored:
`results.md` via `python _common/result_database.py render-md`, the research-state
accepted-results block via `render-state`, and `claims.md` / `obligations.md` /
`assumptions.md` via `python _common/claims_database.py render-md`. Correct a view
by appending to its ledger and re-rendering.
