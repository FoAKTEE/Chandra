---
role: Multi-timescale tracking + research-state scaffold for orchestrator missions — the three-note hierarchy (iteration / nodal / research state)
scope: copied into consumer repos as three live mission-state files at `progress/<mission>/`. The two inner notes are full-rewrite snapshots (history in git); the research-state note is the long append/modify memory.
discipline:
  - ../alignment.md (closed-loop verification; promise-tag rule)
  - ../_common/contracts/research_admission_contract.md (the accepted-result record)
  - ../_common/contracts/markers.md (`[HYPOTHESIS]` / `[PRELIMINARY]` / `[SOLID]` / `[BLOCKING]` / `[FUTURE]` / `[OPEN]`)
  - ../_common/contracts/note_discipline.md (extend-in-place vs overwrite anti-patterns)
  - ../_common/contracts/progress_principles.md (binding cadence + commit policy)
  - ../_common/error_database.py (per-iter log append on every trial)
  - ../_common/loop_policy.py (cadence triggers — `simplification-status`, `crash-triage`)
---

# Multi-timescale Tracking — Three-Note Hierarchy

Long-running missions accumulate work at three natural timescales — `iteration` / `nodal` / `research state` — held in three files under `progress/<mission>/`. **The two inner notes are full-rewrite snapshots**: each keeps only its own window, and history lives in `git log`. **Only the research-state note is append/modify** — it is the longest-time memory and the through-line.

## The three notes

| Timescale | Cadence | Mode | Keeps | Path (consumer) |
|---|---|---|---|---|
| **iteration** (micro) | every wave | **full rewrite** | only the current iteration | `progress/<mission>/loop_notes/current_iter.md` |
| **nodal** (meso) | every 10 iters | **full rewrite** | only the last 10-iteration window | `progress/<mission>/nodal_note.md` |
| **research state** (macro) | scope / status changes | **append / modify (extend-in-place)** | the project through-line, **HARD CAP 10240 bytes (10KB)** | `progress/<mission>/RESEARCH_STATE.md` (`${RESEARCH_STATE}`) |

In v2 the **observer agent** (`orchestrator/src/observer.ts`) owns this cadence
after every wave: it rewrites the two snapshot notes and mechanically enforces
the research-state cap — over-cap notes are pruned/simplified (the note is
committed, so pruned detail is always recoverable from git history); a prune
that still exceeds 10240 bytes fails the wave. Full state belongs in the
ledgers; the research-state note keeps pointers, open questions, and the
mission through-line — not tables.

## Why full-rewrite for the inner two

Append-only iter logs accumulate ~300-row tables that drown the live narrative. A full rewrite keeps only the latest state; full history lives in the file's `git log`. Only the research-state note extends in place — it is genuine long-memory narrative, and losing it would lose the through-line.

## Iteration note — `current_iter.md` (full rewrite every iter; keeps one)

**Every wave, rewrite the WHOLE file** so it holds exactly one iteration. Required sections:

1. **Paper anchor** — which paper equation / figure / `logic.md` node this iter advances.
2. **What shipped this iter** — commits + one-line summaries of appended `error-database` trial rows and `result-database` admitted/classified rows, plus any research-state update.
3. **Next-3 roadmap** — pre-iter planning. Each entry MUST be checked against `crash-triage` so a same-mode loop is rejected before the iter starts.
4. **Simplification flag** — output of `python _common/loop_policy.py simplification-status --paper P --task T`. If `status == required`, the next iter MUST carry `change_type=refactor`.
5. **Verifier output** — verbatim output of the per-domain verification command from the implementation task. Empty = closed-loop violation (alignment.md §0).

## Nodal note — `nodal_note.md` (full rewrite every 10 iters; keeps 10)

The 10-iteration node. **Fully rewritten on each 10-iter boundary**, keeping only the last 10-iteration window (history in `git log`). Required sections:

| Section | Content |
|---|---|
| `## 10-iter window` | error-DB pass/fail counts in the window · `logic.md` node coverage delta · simplification cycles consumed · strategic redirects |
| `## Logic-DAG snapshot` | per-node status (`[BLOCKING]` / `[PRELIMINARY]` / `[SOLID]`) · external dependencies · open obligations (mirrors `logic.md`, rendered Mermaid) |
| `## Accepted-results snapshot` | claim · evidence type · verifier output path · assumptions/dependencies · status · `[OPEN]` items |
| `## Simplification cycle` | trigger · input metric · output metric · code-edit delta · lessons |
| `## Failure-mode drift` | new `failure_mode` enum extensions (loop_policy self-correction) · rationale · backfilled `pass_fail: "amended"` rows |

## Research-state note — `RESEARCH_STATE.md` (the long memory; the ONLY append/modify note)

The longest-time memory: **extend-in-place** on scope or status changes; never overwrite silently — follow `_common/contracts/note_discipline.md` (revise in place; deletions are safe because the note is committed). **Hard cap: 10240 bytes (10KB)**, observer-enforced. Keep pointers to the ledgers and rendered views instead of inlining tables; if something is deletable or simplifiable, delete or simplify it — git history restores anything pruned. Copy this scaffold to the consumer's `${RESEARCH_STATE}`.

Always-on prose sections:

- **Mission + phase**; **branch**; active task IDs · domain (`symbolic` / `numerical` / `proof`) · primary `metric.name`.
- **Living paper pointer** `results/<project>/paper_<arxiv>/paper/`, regenerated every 5 iters by stage 3-write when `python _common/loop_policy.py paper-refresh --paper P --since L` is `due` (see `pipelines/3-write/spec.md`).
- **Paper ingestion record** (write-once historical — what was imported, when, by what command).
- **Open questions** for the human owner; **audit references** (error/result/knowledge-database paths, progress-board path, key debug artifacts).

### Source Library

| ID | Source | Kind | Status | Notes |
|---|---|---|---|---|
| `{{source_id}}` | `{{path_or_url}}` | paper / code / dataset / theorem | literature-grounded | `{{scope}}` |

### Working Context

| Name | Meaning | Assumptions / units / regime |
|---|---|---|
| `{{symbol}}` | `{{plain_english_meaning}}` | `{{assumptions}}` |

### Active Claims

| Claim | Needed evidence | Priority | Owner |
|---|---|---|---|
| `{{claim}}` | `{{proof / derivation / simulation / citation / counterexample}}` | `[BLOCKING]` | `{{agent}}` |

### Accepted Results Log

**GENERATED block — do not hand-edit.** Regenerate with
`python _common/result_database.py render-state --paper P` and paste between the
BEGIN/END markers it emits; correct a row by appending to the result ledger and
re-rendering. Scaffold of the rendered table:

| Claim | Evidence type | Evidence / verifier | Assumptions / deps | Status | Open obligations |
|---|---|---|---|---|---|
| `{{claim_id}}` | `{{evidence_type}}` | `{{path_or_command}}` | `{{deps}}` | `[HYPOTHESIS]` | `[OPEN] {{what_remains}}` |

### Next Work Steps

- `[OPEN] {{goal_id}}` — `{{recommended_method}}`; verifier: `{{command_or_checker}}`.

## Stable semantic registries (alongside, NOT logs)

These live next to the three notes but are not part of the cadence:

- `results/<project>/paper_<arxiv>/decomposition/logic.md` — per-paper DAG (Mermaid); source-of-truth the nodal-note `Logic-DAG snapshot` mirrors.
- `results/<project>/GLOBAL_DAG.md` — the one giant merged DAG across all papers (`python _common/visualization/dag_mermaid.py merge`); identical cross-paper derivations collapse to one `_shared::` node. Error + knowledge rows attach under its nodes as `node_seq` lists; `dag_mermaid.py progress` / `node-view` read per-node project progress off it.
- `results/ledgers/error/paper_<arxiv>/trials.jsonl` — the append-only trial log (schema: `python _common/error_database.py schema`).
- `results/ledgers/result/paper_<arxiv>/results.jsonl` — the append-only admitted/classified result log (schema: `python _common/result_database.py schema`).
- `results/ledgers/knowledge/paper_<arxiv>/nodes.jsonl` — the append-only accepted-node log (schema: `python _common/knowledge_database.py schema`).
- `results/ledgers/claim/paper_<arxiv>/entries.jsonl` — the append-only claim / obligation / assumption log (schema: `python _common/claims_database.py schema`); `claims.md` / `obligations.md` / `assumptions.md` are rendered from it (`render-md --out-dir`).
- `results/<project>/paper_<arxiv>/decomposition/assumptions.md` — assumptions registry, rendered from the claim ledger.
- `ref-paper/<arxiv-id>/` — chunked paper source.

## Companion templates

- This file — the three-note cadence + the research-state scaffold.

## Migration from a single-note setup

If a consumer currently keeps only one research note:

1. Create `progress/<mission>/loop_notes/current_iter.md`; full-rewrite it every iter (keeps one).
2. Create `progress/<mission>/nodal_note.md` with the section headers; full-rewrite it every 10 iters (keeps the 10-iter window).
3. Create `RESEARCH_STATE.md` from the research-state scaffold above; move "in-progress per-iter detail" out of it into the iteration note; keep mission / DAG / accepted-results / open-questions in the research-state note.

A consumer with this layout produces a clean iter-by-iter delta (the iteration note), a 10-iter retrospective (the nodal note), and the long-form research-state memory — three views of the same loop at three timescales.
