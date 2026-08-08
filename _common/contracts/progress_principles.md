# Progress Principles (shared)

Applies to every pipeline that runs sub-agents and produces artifacts (source import, decomposition, implementation, validation, result logging, writing, escalation).

## Commit cadence (MECHANICALLY ENFORCED)

- **Per-wave substage commit:** the orchestrator itself commits all zone-1
  changes (`results/`, `progress/`) after EVERY wave with a gate-compliant
  `notes(wave):` message, and **halts the mission if the commit fails**
  (`orchestrator/src/gitops.ts`). A mission refuses to start outside a git
  repo; the commit-msg gate should be installed (`bash _common/hooks/install.sh`).
- **Per-packet flush:** workers buffer trials in a runtime-dir WAL and land
  them at the packet boundary via `append-batch` — one gate pass, one summary
  regeneration, one commit per packet instead of per node.
- v1 solo loops commit per substage themselves (they are their own worker).
- Do **not** commit files under `instructions/` (consumer-repo convention).

## Progress directory layout

- Agent diaries (per-worker scratch, packet WALs, debug artifacts, orchestrator journal) live in the RUNTIME HOME `/tmp/chandra/<repo>-<hash8>/` (override: `CHANDRA_RUNTIME`) — NEVER in the repo.
- The repo keeps only committed deliverables: `results/` (ledgers, views, per-project artifacts) and `progress/<mission>/` (the three notes + digest).
- Stage-wise research diaries + final report for human reading.
- After test finishing: `git rm` the intermediate stagewise progress (including sub-agents'); keep the final report and loop notes.

## Promise tag (commit gate)

- Format: `<promise>{TASK_ID} {METRIC} WITHIN {THRESHOLD}</promise>`.
- Commit only after the verification command has run AND the metric is within threshold.
- Verbatim verification output and the admitted claim/evidence type go in the commit body.
- A `<promise>` without measured evidence is a closed-loop violation per `alignment.md` §0 and §2.

## Commit message grammar (enforced by the commit-msg gate)

Every commit message follows `_common/contracts/commit_template.md`, enforced by the
tracked `_common/hooks/commit-msg` gate (activate per-clone with
`bash _common/hooks/install.sh`). The progress-folder draft is gitignored, so the
template lives in `_common/` as methodology source.

- **Title (hard gate):** `<type>(<scope>)[!]: <imperative summary>` with
  `type ∈ {feat, fix, perf, refactor, docs, test, build, ci, style, revert, diag,
  exp, chore, infra, notes}`. `infra`/`notes` are the methodology-repo process types.
  A non-conforming title **rejects the commit**.
- **Body (advisory):** a markdown list of typed objects
  `- {why|finding|change|run|result|verify|caveat|next|files}: …`; every
  `finding`/`result` carries a `[SOLID|PRELIMINARY|HOLE|FUTURE]` claim tag (the
  `markers.md` vocabulary). `!` pairs with a `BREAKING CHANGE:` footer.
- `COMMIT_GATE_STRICT=1` escalates warnings to errors; `git commit --no-verify`
  bypasses once. Self-test: `python3 -m pytest tests/test_commit_msg_gate.py`.

## Multi-timescale tracking (three-note hierarchy)

The consumer maintains three live state files at `progress/<mission>/` — two full-rewrite snapshots plus one append/modify long-memory note (see `notes/multi_timescale_tracking_template.md` for the binding contract):

- **iteration note** — `loop_notes/current_iter.md`, **fully rewritten every Ralph iter** (keeps only the current iteration): paper anchor, shipped result, next-3 roadmap, verifier output, research-state delta.
- **nodal note** — `nodal_note.md`, **fully rewritten every 10 iters** (keeps only the last 10-iteration window): 10-iter window, Logic-DAG snapshot, accepted-results snapshot, simplification cycle, failure-mode drift.
- **research-state note** — `${RESEARCH_STATE}`, the **only append/modify note** (extend-in-place on scope or status changes): mission, branch, source library, working context, DAG status, accepted-results log, open questions. Inherits `note_discipline.md`.

History is preserved in `git log`, not in-tree. The three files together are the closed-loop deliverable alongside code + paper. The research-state note is **hard-capped at 10240 bytes (10KB)** — the v2 observer agent prunes it after every wave (pruned detail stays recoverable in git history); full state lives in the ledgers, the note keeps pointers and the through-line.

## Append-only per-paper logs (error + result + knowledge + claim)

Four schema-as-code logs — the CANONICAL research memory; markdown is rendered from them, never hand-authored. Append via `python _common/<module>.py append`; `summary.csv` is auto-regenerated; **never delete a row** — amend by appending. **Appends run the executable admission gate** (`_common/ledgers/admission.py`): `verification.command` is executed (exit 0 required, outcome recorded), file evidence is content-hashed into `evidence_sha256`, `::`-namespaced dependencies must resolve, `solid` needs `solid` predecessors; bypass flags land in `admission_flags`, visible in the row.
- **error_database** — every trial (pass / fail / crash / partial). Failures carry `expected / observed / root_cause / fix_hypothesis / failure_mode`. Trials carry `node_id` (the DAG anchor) so each is a numbered `node_seq` entry under its node. Orient with `schema`, `describe-fields`, `describe-domain --domain <D>`. Loop-control queries live in `_common/loop/loop_policy.py`; CLI wrapper `_common/loop_policy.py` remains valid. The progress-gate circuit breaker lives in `_common/loop/loop_gate.py`; wrapper `_common/loop_gate.py` remains valid.
- **result_database** — stage-4 admitted/classified results. `unchecked`, `refuted`, and `conjectural` rows stay report-visible (`PROGRESS_STATUSES`) but do not reset the no-progress gate (`GATE_PROGRESS_STATUSES`). `results.md` and the research-state accepted-results block are GENERATED views: `render-md` / `render-state`.
- **claims_database** — stage-1 claims / obligations / assumptions as records (`claim-database/paper_<P>/entries.jsonl`). Settling references are checked to exist (admitted claim → `result_ref`; discharged obligation → `discharged_by`; relaxed assumption → `reduction_obligation`). `claims.md` / `obligations.md` / `assumptions.md` are GENERATED views: `render-md --out-dir`.
- **knowledge_database** (★ dual) — every converged `logic.md` node. Promotions are appends (`hypothesis -> preliminary -> solid`); `query` returns the latest non-amended row per `node_id` (use `--with-history` for the arc). DAG edges in `predecessors[]`; walk with `predecessors --node-id N [--transitive]`. Solid rows MUST carry `evidence`. Batch a decomposition's nodes with `append-batch`; render the DAG with `_common/visualization/dag_mermaid.py` (always Mermaid; one merged DAG across papers). **Error + knowledge rows attach UNDER a DAG node via `node_id` (auto-numbered `node_seq` 1,2,3…) — doubly linked, never new nodes; `dag_mermaid.py progress` / `node-view` read project progress off the giant DAG.**

## Tool promotion (auto-written tools)

A reusable tool written ad hoc during a run (e.g. a mission's local `dagtools/`) is **promoted into `_common/`** — given a CLI entry point and a `tests/` smoke + rejection check — not left as a one-off. Shared mechanics live once and the infra self-hosts on §0 (`python3 -m pytest`). Run-local scratch stays under gitignored `progress/`; only the promoted, tested version is methodology source.
