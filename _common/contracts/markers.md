# Status Markers (shared vocabulary)

Used across research notes, decomposition artifacts, implementation tasks, validation results, and writing. Referenced from templates and pipeline specs. Do not inline the definitions elsewhere.

## Uncertainty markers

- `[HYPOTHESIS]` — proposed, not yet tested.
- `[PRELIMINARY]` — initial evidence exists; load-bearing but not confirmed.
- `[SOLID]` — confirmed; safe to rely on.

## Gap markers

- `[BLOCKING]` — resolution required before the enclosing section or task can close.
- `[FUTURE]` — known gap that does not block current closure; deferred deliberately.
- `[OPEN]` — unresolved work obligation; state what evidence would close it.
- `[ASSUMPTION]` — explicit modeling assumption or imported postulate; final results must remain conditional on it.
- `[UNCHECKED]` — external or agent-produced step that has not passed a verifier; cannot support a checked result.
- `[EXISTENCE]` — existence-only result; no constructive algorithm or executable artifact is certified.

## Discipline

- Use markers instead of hedging prose ("probably", "seems to", "might be").
- Every loose end MUST carry a marker. If you see an unmarked gap or open obligation, add one.
- Every marker, if resolved, MUST advance the paper or task. If it would not, remove it (bidirectional criterion — see `note_discipline.md`).
- Promote `[HYPOTHESIS]` → `[PRELIMINARY]` → `[SOLID]` as evidence accumulates. Demote freely when evidence degrades.
- `[BLOCKING]` must state what unblocks it and who owns the resolution.
