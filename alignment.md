# Agent Alignment Kernel — Always-On

Binding rules, kept tiny by design: most enforcement is MECHANICAL (the
executable admission gate, the commit-msg gate, the loop gate), so this file
states the rules and points at the code that enforces them.

## §0 The verifier admits (closed loop)
The agent proposes; the verifier admits. No completion claim without verifier
output. Results, nodes, and claims enter research memory ONLY via ledger
appends (`_common/ledgers/`), which run the admission gate: verification
commands are EXECUTED, evidence is content-hashed, dependencies must resolve.
Markdown views are rendered from ledgers, never hand-authored.

## §1 Fact-driven attribution
No failure attribution without tool-verified evidence. Every trial lands in the
error ledger with expected / observed / root_cause / fix_hypothesis.

## §2 No parameter-tweak loops
Three cycles of the same idea ⇒ switch approach or escalate
(`_common/loop_policy.py crash-triage`). The loop gate is the backstop; never
fake progress or hand-edit its state.

## §3 Stall → acquire (formerly §15)
A node stuck 3 iterations or 30 minutes runs `pipelines/0-acquire/spec.md` to
import the missing source/method, then re-enters the loop.

## §4 Source-artifact discipline (formerly §16)
tex mirrors in `ref-paper/`, code in `ref-code/`, each with `PROVENANCE.md`;
import + decomposition before implementation; never edit mirrors in place.

## §5 Context injection (formerly §17)
SessionStart injects this kernel + the admission contract. Sub-agents receive
explicit context packs — this kernel,
`_common/contracts/research_admission_contract.md`, and only their task's
inputs — never the parent's full context.

## §6 Delegation-only orchestration
The launching session ORCHESTRATES; it does not produce evidence, write
research code, or append rows. All work is done by spawned worker agents
(orchestrator waves or sub-agents running with `CHANDRA_ROLE=worker`).
Enforced by the gate: under `.delegation-policy: strict`, appends without a
worker/validator/observer role are REJECTED; `CHANDRA_ROLE=human-override`
is the visible escape hatch, recorded on the row as `actor_role`.

Pointers: `INDEX.md` (repo map) ·
`_common/contracts/{research_admission_contract,markers,note_discipline,progress_principles}.md`
· `notes/` state templates · `pipelines/{0-acquire,1-decompose,2-work,3-write}/spec.md`
