# Chandra — Repo Index & Verified Workflow

Methodology repo for verified, agent-driven scientific research. Pipelines live
under `pipelines/`; shared contracts + ledgers under `_common/`; state templates
under `notes/`; the v2 runtime under `orchestrator/`. **This file is the
canonical index _and_ the plain-language workflow contract.** `README.md` is the
human-facing orientation; `alignment.md` is the always-on ~2.4KB kernel (injected
at session start by `.claude/inject_infra.sh` — everything else is read on
demand). If a doc disagrees with this file, this file wins.

## Core invariant

```text
The agent proposes; the verifier admits.
```

Admission is EXECUTABLE, not prose: results, nodes, and claims enter research
memory only via ledger appends (`_common/ledgers/`), whose admission gate runs
verification commands (exit 0 required, outcome recorded), content-hashes file
evidence, resolves cited dependencies, and requires solid predecessors for
solid nodes. Markdown artifacts are rendered views over the ledgers, never
hand-authored.

## Required record for every accepted result

- **Source library** — papers, code, datasets, citations, prior checked results used.
- **Working context** — model, symbols, units, assumptions, regime.
- **Claim** — the statement being advanced.
- **Evidence type** — proof, derivation, approximation, simulation, measurement,
  citation, counterexample, conjecture, unchecked step, or existence-only.
- **Evidence** — command output, certificate, artifact path, citation bundle, or counterexample.
- **Verifier result** — pass / fail / classified, with tolerance when relevant.
- **Dependencies and open obligations.**

## Pipelines (the loop, 4 stages)

The four stages are JOB KINDS under ONE scheduler (v3): `decompose` (mirror
present, DAG empty), `work-packet` (ready frontier chains, worked continuously),
`acquire` (open obligations owned by 0-acquire), `write-refresh` (living-paper
cadence + the terminal render). Readiness is computed from the ledgers;
outcomes are measured from ledger/filesystem diffs; the table below documents
the job kinds — it is not a workflow a human walks.

| # | Pipeline | Role | Status |
|---|---|---|---|
| 0 | [acquire](pipelines/0-acquire/spec.md) | build + extend the source library (includes mid-loop escalation) | CONTRACT |
| 1 | [decompose](pipelines/1-decompose/spec.md) | paper/code → claim-ledger entries, DAG, obligations | CONTRACT |
| 2 | [work](pipelines/2-work/spec.md) | one ready node → evidence → isolated adversarial validation → admitted ledger row; [template](pipelines/2-work/template.md) | CONTRACT |
| 3 | [write](pipelines/3-write/spec.md) | living paper every 5 iters + final render; [paper-scaffold](pipelines/3-write/paper_prd_agent_template/PAPER_GENERATION_CONTRACT.md) / [principles](pipelines/3-write/principles.md) / [moves-intro](pipelines/3-write/moves-intro.md) | SPEC'D |

## Conventions

- `spec.md` — WHAT a stage does (role, I/O, invocation). Immutable-ish.
- `template.md` — HOW: the fill-in scaffold, present only where a stage emits an artifact.
- Shared boilerplate in `_common/` is **referenced**, not inlined.
- `alignment.md` (root) — the ≤2.5KB always-on kernel; do not grow it. Rules whose
  enforcement is mechanical live in code and are only POINTED TO from the kernel.

## Cross-cutting artifacts

- `alignment.md` (root) — always-on kernel (§0 verifier admits · §1 fact-driven ·
  §2 no tweak-loops · §3 stall→acquire · §4 source discipline · §5 context injection · §6 delegation-only).
- `_common/contracts/research_admission_contract.md` — the admission contract injected at session start.
- `.delegation-policy` (root, `strict`) — kernel §6 enforced by the gate: ledger appends require a delegated `CHANDRA_ROLE` (worker/validator/observer; `human-override` is the visible escape hatch, recorded as `actor_role`). The launching session orchestrates; it cannot append work.
- `_common/ledgers/` — error/result/knowledge/claim schema-as-code modules plus `ledger_common.py` and the **executable admission gate** (`admission.py`). The ledgers are canonical; `results.md`, `claims.md`, `obligations.md`, `assumptions.md`, and the research-state accepted-results block are **rendered views** (`render-md` / `render-state`). On disk: `results/ledgers/<db>/paper_<P>/` — the ONE research-output tree (with `results/views/` and `results/<project>/paper_<P>/{decomposition,tasks,codes,plots,evidence,paper}`); legacy `<db>-database/` keeps working until migrated by `git mv`. Agent diaries (journal, worker scratch, debug) live OUTSIDE the repo in `/tmp/chandra/<repo>-<hash>/` (`CHANDRA_RUNTIME`).
- `_common/loop/` — `loop_policy.py` read-only ledger queries and `loop_gate.py` progress circuit breaker.
- `_common/visualization/dag_mermaid.py` — DAG-as-Mermaid: per-paper render, the one giant merged DAG (`merge`; identical cross-paper derivations → one `_shared::` node), duplicate detection, and per-node progress (`progress` / `node-view`) — error + knowledge rows attach UNDER DAG nodes (`node_id` + auto `node_seq`), doubly linked.
- `_common/visualization/dashboard.py` — the per-paper HTML mission dashboard (`render --paper P` → `results/views/dashboard/paper_<P>.html`): KPI tiles, the mission DAG as inline SVG with doubly-linked node drill-down, all four ledgers as searchable/sortable tables, per-ledger hash-chain badges. Self-contained (no network), light + dark. A rendered VIEW over the ledgers, like every other markdown/HTML artifact.
- `_common/quality/code_quality.py` — static AI coding-session policy prompt bundles.
- `_common/contracts/markers.md` — `[HYPOTHESIS]` / `[PRELIMINARY]` / `[SOLID]` plus gap/result markers.
- `_common/contracts/note_discipline.md` — bidirectional criterion + update guidelines + anti-patterns.
- `_common/contracts/progress_principles.md` — commit cadence, ledger-first rule, **commit-message grammar (enforced)**.
- `_common/contracts/commit_template.md` — the tracked commit-message template; spec for the commit-msg gate.
- `_common/hooks/` — tracked git hooks; `commit-msg` enforces the template (`install.sh` activates via `core.hooksPath`).
- `notes/multi_timescale_tracking_template.md` — three-note hierarchy: iteration (current wave only), nodal (last ~10), research state (long memory, hard ≤10KB — the observer agent prunes it; history in git).
- `notes/pua_skill.md` — OPT-IN motivational-pressure skill (formerly at `alignment.md`). Never injected; load explicitly if wanted.
- `orchestrator/` — v2 TypeScript runtime (Claude Agent SDK): topological scheduler, parallel workers, process-isolated validators, observer memory agent, 5-window human digest cadence.
- `tests/` — pytest smoke + rejection checks; the infra self-hosts on §0 (`python3 -m pytest`).
