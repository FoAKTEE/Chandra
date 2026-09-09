# Knowledgebase redesign — diagnosis, refutation, staged proposal

Status: PROPOSAL, REFUTED ONCE (2026-09-09). Written from code reading and
measurements (§9), then attacked by an independent fresh-context reviewer whose
report reproduced every demonstration, downgraded three severities, and found
six defects the first draft missed — the worst being that parallel appends
corrupt the hash chain. The amendments are applied below; the refutation is
recorded in §10. A second, cross-model refutation by GPT-6 is owed once the
Codex quota resets (obligation `kb-gpt6-review`; prompts in
`notes/kb_redesign/prompts/`). Nothing here is implemented; §6 is the DAG a
self-optimize mission would work, and each defect below is an open obligation
under paper `self`.

## 0. Scope

"Knowledgebase" = everything an agent or the runtime reads to know what is
true and what to do:

| layer | artifacts |
|---|---|
| research memory (data) | the four JSONL ledgers under `results/ledgers/<db>/paper_<P>/`, their hash chains, the admission gate, the DAG (`predecessors`, `PAPER::node`, `_shared::`), rendered views (`results.md`, `claims.md`, `summary.csv`, HTML, Mermaid, dashboard), loop policies |
| mission memory | the three notes under gitignored `progress/`, the human digest, the runtime journal, packet WALs |
| agent knowledge | `alignment.md`, `_common/contracts/*.md`, `INDEX.md`, `README.md`, `pipelines/*/spec.md`, the 33 skills and their registry, `AGENTS.md`, the prompts in `orchestrator/src/agents.ts` |

They are treated together because they fail together: 29 of the drift
obligations recorded on 2026-09-09 are prose describing data behavior the data
layer does not have.

## 1. What the design is today

One research graph — claims, obligations, assumptions, DAG nodes, results,
trials, sources, evidence — stored as four append-only, per-paper JSONL files
whose rows point at each other by free-text ids. Identity is "latest row per
id wins" (`ledger_common.latest_per_node`, `result_database.latest_per_result`,
`claims_database.latest_per_entry`). Correction is a new row with the same id;
amendment is a row with `status: amended` plus prose in `notes`. Integrity is
enforced at append for exactly five reference kinds (`claims_database.check_refs`:
`result_ref`, `discharged_by`, `reduction_obligation`; `admission.py`: `::`
dependencies and solid predecessors) and only at the dependent's own append.
Every other reference — `node_ids` on results and claims, `node_id` on
trials, `dependencies`, `source_ids`, `error_db_refs` — is unchecked text.
Every read is a full-file scan; every append rewrites `summary.csv`; no
append takes a lock. The TypeScript runtime rebuilds the mission from one
paper's rows per wave through `python3 … query` subprocesses
(`orchestrator/src/ledger.ts`; 14 launches per wave counted statically across
`main.ts`, `scheduler.ts`, `jobs.ts`, `gate.ts`). Prose (contracts, specs,
INDEX, README, skills) restates the data layer's behavior by hand; only the
enum manifest (`_common/contract.py`) is shared mechanically.

## 2. Diagnosis — sixteen design problems, with evidence

Severity: **C** blocks correctness · **S** silently wrong · **T** costs time · **D** drift.
"Demonstrated" = reproduced by both the author and the reviewer in throwaway
repos (scripts in `notes/kb_redesign/`).

**P11 (C) No cross-process lock: parallel appends corrupt the hash chain.**
`ledger_common.chain_append` reads the tail hash, then appends, with no lock
and no fsync (`_common/ledgers/ledger_common.py:134-149`). Four processes
each appending 25 trials to one ledger broke the chain in 3 of 3 runs for the
author (`break_at` 5, 1, 18 of 100) and 3 of 3 for the reviewer (`break_at`
1, 6, 2). The runtime runs packets in `Promise.all` and non-packet jobs
concurrently with them (`orchestrator/src/scheduler.ts:97`,
`orchestrator/src/main.ts:187-190`), and workers flush with `append-batch`;
the end-of-wave chain check then halts the mission `ledger_tampered`
(`main.ts:239-245`, exit 8), and the chain cannot be repaired without editing
hashed rows. `node_seq` is racy for the same reason
(`knowledge_database.py:211-213`). This is the defect a real parallel mission
hits first. Root cause: a multi-writer file with single-writer assumptions.

**P2 (S) Amendment and identity are conventions, not edges.** Re-appending
`result_id r1` with the opposite claim and status `refuted` silently replaces
the checked row in every latest-view; no link, no warning (demonstrated).
Same-id re-append is the *documented* correction path
(`result_database.py:20-22`, `claims_database.py:17-18`). `status: amended`
rows are ignored by queries but redirect no edge, so the decompose spec's
"collapse duplicates into `_shared::`" cannot be executed (drift
`decompose-amended-aliases`). Root cause: no `supersedes` relation.

**P12 (S) No downstream invalidation.** "Solid rests on solid" and "admitted
cites a passing result" hold only at the dependent's own append
(`admission.py:291-304`, `claims_database.py:143-154`). Demonstrated: demote a
solid predecessor to `hypothesis` — its solid dependent stays solid; re-append
a settling result as `refuted` — the claim it admitted stays `admitted`.
Nothing re-checks, nothing reports.

**P13 (S) Verifiability is proposer-defined.** A caller-supplied
`evidence_sha256` string satisfies the checked/solid evidence rule
(`admission.py:247,284`), and a proposer-chosen `verification.command` run
with `shell=True` (`admission.py:126`) plus free-text evidence yields
`solid` (demonstrated). The row records what the proposer's command printed.
Already partly recorded as drift `adm-contract-evidence-sha`.

**P14 (S) Nodes cannot be retired.** `amended` is skipped by
`latest_per_node` (`ledger_common.py:203-204`), so the prior status persists;
`future` / `blocking` placeholders sit on the frontier every wave
(`dag.ts:69-71`) and block `missionComplete` (`dag.ts:77-81`). Demonstrated:
after amending `P::dup`, `readyFrontier` still lists it. Consolidating
duplicates therefore *adds* work to every wave.

**P3 (S) Partial referential integrity.** A trial anchored to a node that does
not exist is accepted and then appears in `progress` with `status: null`
(demonstrated; no test covers it). Results and claims may cite `node_ids` that
never existed. Readiness ignores open obligations although the spec promises
otherwise (`dag.ts:31-36` collects them; `readyFrontier` never reads them;
drift `dag-readiness-obligations`); the scheduler only marks such a node
`rejected` and re-leases it next wave (`scheduler.ts:127-130`). A hypothesis
cycle `P::a ⇄ P::b` is accepted and then silently omitted from `plan`
(depth −1, no diagnostic).

**P1 (S/T) Cross-paper dependencies are never ready in the runtime.** The DAG
promises one giant graph (`_shared::` nodes, `dag_mermaid.py merge`), but
`buildMission` is fed one paper's rows (`main.ts:70-71,161-162`) and
`readyFrontier` treats a predecessor absent from the mission as not solid
(`dag.ts:66-73`). Demonstrated: `P::top` with the single, solid predecessor
`_shared::base` is excluded; `P::solo` is ready. Downgraded from C because it
fails loudly (`no_ready_jobs`, exit 3), the Python gate already resolves
cross-paper predecessors (`admission.py:185-204`, so gate and frontier
disagree), a mirror row in the paper's own ledger is a workaround, and the fix
is a few lines of TypeScript, not a storage redesign.

**P16 (S) Node identity is not global.** The same `node_id` in papers P and Q
resolves to different rows depending on `paper_hint`
(`admission.py:192-203`); the P1 workaround creates exactly this.

**P15 (S) The runtime swallows claim-ledger failures.** `Ledgers.claims()`
returns `[]` on any CLI error (`ledger.ts:60-69`): one malformed line removes
every acquire job, repair obligation, and discharged count for the wave; the
chain verifier notices only at wave end.

**P5 (S) Tamper evidence stops at the file tail and provenance is self-declared.**
Deleting the last row of a chained ledger leaves `verify-chains` reporting
`{"ok": true}` (demonstrated; drift `chain-tail-truncation`). Chain heads are
anchored nowhere; `git_commit` on a row is the HEAD at append time, not a
content anchor; `actor_role` is an environment variable (`admission.py:67-69`).
`evidence_sha256` is computed once and read only by the renderer
(`result_database.py:345`); a moved or edited artifact is never noticed.

**P4 (T) Every operation is O(n) in the ledger — but the cost is elsewhere
than the first draft claimed.** Measured (§9): one knowledge append 4 → 49 →
235 ms and one trial append 5 → 60 → 217 ms at 100 / 2,000 / 10,000 rows;
`predecessors --transitive` 1 → 434 → 7,920 ms; a 200-row batch on 2,600 rows
10–13 s. Profiled at 2,000 rows: 57% of an append is regenerating the tracked
`summary.csv` (`ledger_common.py:104-120`), 15% re-reading the file for
`node_seq`, 15% resolving one predecessor. Per wave, the runtime pays ~45 ms
of interpreter start-up per CLI call × 14 calls ≈ 0.7 s at any N, versus
≈ 0.12 s of actual scanning at 2,000 rows. At the owner's scale (10²–10³
nodes per paper) ledger I/O is well under 1% of a wave's wall-clock; at 10⁴
rows it is 1–5%. An index does not remove process start-up; consolidating the
14 calls and untracking the CSV do.

**P6 (D) Prose exceeds the code it describes, and hand-restates facts.**
Contracts 31 KB + specs 57 KB + notes 58 KB, skills 249 KB; the Python and
TypeScript they describe: 282 KB + 92 KB. `CHANDRA_ROLE` is explained in 30
files, the ledger path in 19, the 10 KB cap in 13. Writing the skills against
the code surfaced 29 drift findings in one day. Corrected root cause: a
generator from schema to prose would have prevented only ~5 of the 29
(enum / path / cap facts); ~10 are code bugs and ~14 are prose describing
behavior (readiness, cadence, validation wiring) that only behavior tests can
keep true.

**P7 (D) Mission memory duplicates the ledgers and is not durable.** The
iteration and nodal notes are renderings of journal state
(`observer.ts:104-139`) written into gitignored `progress/`; consumers clone
or vendor the repo and inherit the ignore, so `gitops.ts:42` never stages
them; the research-state note mixes a generated block with hand prose under a
lossy 10 KB pruner. The template's "history in git" does not exist for them
(drift `progress-gitignored`).

**P8 (T) No retrieval beyond exact ids.** No error-ledger `query`
(`error_database.py:657-720`), no search over statements / root causes / fix
hypotheses, `duplicates` is a normalized-summary heuristic
(`dag_mermaid.py:208-241`), and the 0-acquire "import the prior fix" path has
no mechanism. Downgraded from C: workers have Bash, and `grep`/`jq` over a few
MB of JSONL answers "was this failure mode seen on this node family" today.
Semantic similarity would need an external dependency and is out of scope.

**P9 (D) Two runtimes re-implement behavior the manifest does not carry.**
`loop_gate.py:165-168` counts results with empty `open_obligations`;
`gate.ts:39` counts `discharged` obligations. `loop_gate.py` is a leftover of
the retired ralph-loop driver, wired to no hook (`.claude/settings.json`), yet
shipped, wrapped, skilled, and tested.

**P10 (T) Context economics are invisible.** Session start injects 6.7 KB
(18.3 KB with the skills briefing); Claude Code loads 9.2 KB of skill
descriptions every session; a worker prompt is 2.4 KB pointing at a 20.7 KB
read set; no worker prompt reads the research-state note. The only budget in
the system is the 10 KB cap on a prose note no worker reads.

## 3. What an optimal design must satisfy

- G0 Single-writer discipline: one append at a time per ledger file, held across tail-read → gate → write; sequence numbers assigned under the same lock.
- G1 One graph: typed entities and edges, global ids, `paper` an attribute; referential integrity, acyclicity, supersession, retirement, and obligation-aware readiness enforced at write time; dependents re-checked or reported when their support changes.
- G2 The append-only, hash-chained JSONL stays canonical and git-tracked; everything else (index, views, notes, CSV, Mermaid, dashboard, generated doc tables) is derived and rebuildable.
- G3 Indexed reads when the scale demands it; one query call per wave, not fourteen; cross-paper by default.
- G4 Evidence chosen by the verifier, not only the proposer: gate-owned fields (`evidence_sha256`, `verification_run`) are stripped from input; verification commands are registered per task, not free-typed on the row; outputs kept whole under a size cap.
- G5 Retrieval: full-text search over statements, summaries, root causes, and fix hypotheses; skills located by moment (stage × role).
- G6 One source of truth per fact where a fact is data; behavior kept true by behavior tests, not by prose.
- G7 Mission memory = queries over the graph plus a tiny hand-written through-line; generated notes tracked in git.
- G8 Explicit context budgets for session start and worker packs, in bytes, assembled by a tool.
- G9 Chain heads anchored per wave commit so truncation is detectable; provenance carries role and session.

Non-negotiables that stay: the verifier admits; executable admission at write; ledgers canonical over prose; delegation policy; the commit gate; Python ≥ 3.10 with no third-party dependencies; Node 18.

## 4. Candidate architectures

### A — Harden the JSONL ledgers in place (recommended now)

Per-ledger advisory lock (`fcntl.flock` on `<db_dir>/.lock`) held across
tail-read → gate → append, with `node_seq` assigned inside it; a `supersedes`
field (row_hash of the replaced row) on all four ledgers, with a per-ledger
definition of "same id, different content" that rejects unlinked replacement
while leaving promotions (same id, new status) as they are; a `retired`
status excluded from frontier and completion; `node_ids` / `node_id` /
claim `dependencies` checked at append; cycles rejected at append; a
`verify-integrity` CLI reporting dangling references, cycles, orphans, and
dependents whose support was demoted or refuted (P12 as a report first, a
gate later); gate-owned fields stripped from input and verification commands
registered per `task_id`; `readyFrontier` honoring open obligations and built
from every paper's rows, with `missionComplete` and `gateSignal` scoped to the
mission paper; `Ledgers.claims()` failing loudly; `summary.csv` untracked and
rebuilt on demand; the runtime's 14 per-wave CLI calls consolidated into one
`snapshot` query; chain heads recorded per wave commit; an error-ledger
`query`; all enums and paths in one `_common/schema.py`.

Fixes P11, P2, P12 (report), P13, P14, P3, P1, P16, P15, P5 (heads), P9
(partly), and the 57% + 0.6 s/wave halves of P4. Leaves P8 to grep. Effort
~12 nodes, each small; every skill keeps its CLI surface (12 skill bodies
need wording updates for `amended`/`summary.csv`/`retired`).

### B — Event log + derived index (later, threshold-gated)

Keep the JSONL files as the canonical event log. Add a derived, gitignored,
rebuildable index `results/ledgers/index.sqlite` (stdlib `sqlite3`; FTS5 is
present on this host, 3.45.1) with `events`, `entities`, `edges`, and an FTS
table; edges derived from row fields plus `supersedes`; queries `search`,
`similar-trials`, `lineage`, `frontier`. Readers move to the index; the gate
resolves references there. Because the index must never be a second truth,
it is built and read only under the same per-ledger locks as the writers
(A's `flock`), rebuilt when its recorded heads differ from the files', and
the gate keeps the file path as the arbiter when the index is absent or
stale. Consumers must ignore the index file or the wave commit will stage it.

B pays off when a paper's ledgers exceed ~10⁵ rows, when a wave's ledger I/O
exceeds 5% of its wall-clock, or when a retrieval need beyond grep is
demonstrated. Below that it adds a second implementation of every admission
rule, schema migrations whenever row fields change, an exact-match index
beside FTS (the default tokenizer splits `_shared::base` and `eq:D.k`), and
rebuild storms under parallel workers. Effort ~8 nodes, several multi-day.

### C — One typed store replacing the four files

A single `events.jsonl` plus the same derived index; per-paper directories
removed. Cleanest model, but re-anchors every chain, changes every skill's
paths and the TypeScript bridge, and forces a consumer migration. Defer until
B has run a real mission.

### K — The agent-knowledge layer (independent of A/B/C)

- K1 `_common/schema.py` as the single source for enums, paths, caps, cadences, role policy; `contract.py manifest` reads it; `render-docs` writes the generated tables in `INDEX.md`, the specs, and `AGENTS.md` between markers, drift-tested like `render-state`. Scope honestly: this fixes the ~5/29 enum-and-path drift; behavior drift needs behavior tests (K5).
- K2 Skills carry a checked `## Facts` block (`symbol == value` assertions the registry imports and compares) and `metadata.moments` (stage × role); a stale fact fails `validate`.
- K3 A pack assembler: `skill_registry.py pack --stage work --role worker --budget 24k` selects skills by moment, adds the node's context from `query` output (no index needed), and stops at the byte budget; `agents.ts` and validator packs use it. Session-start injection gets a budget.
- K4 Notes: the two snapshot notes are generated and tracked; the research-state note keeps a hand-written through-line (≤ 2 KB) plus generated blocks; `progress/<mission>/` leaves `.gitignore` (verified by a consumer-shaped fixture that has the ignore).
- K5 Behavior drift tests: the 14 prose-behavior drift findings each become a test that reads the spec sentence's claim against the code (readiness, cadence, validator wiring), so the spec is either true or the test fails.

## 5. Recommendation

**A + K now, in three stages; B only when its thresholds are met.**

- Stage 0 — correctness, days: the ledger lock (P11), the cross-paper +
  obligation-aware frontier with scoped completion (P1, P3), loud claim-ledger
  failures (P15). These fix defects a real parallel mission hits in its first
  waves.
- Stage 1 — the rest of A: `supersedes` + `retired`, integrity at append and
  `verify-integrity`, evidence hardening, chain heads, CSV untracked, call
  consolidation, single-source schema, error `query`.
- Stage 2 — K: rendered doc tables, skill facts and moments, the pack
  assembler, tracked notes, behavior drift tests.
- Stage 3 — B, when a mission's ledgers pass ~10⁵ rows or ledger I/O passes 5%
  of wave time or retrieval beyond grep is demonstrated necessary.

Do not change: the JSONL event log and its chains, the executable admission
rule, the rendered-view rule, the delegation policy, the commit gate, the
stdlib-only constraint, the skills' CLI surfaces (only add subcommands).

Expected outcome after stages 0–2: parallel missions stop corrupting their own
memory; shared derivations work; a demoted support or refuted result is
reported instead of silently standing; drift in enums, paths, and stated
behavior becomes a failing test; appends cost about half; each wave makes one
ledger call instead of fourteen.

## 6. Migration DAG

| node | stage | summary | predecessors | verifier (exit 0 iff done) |
|---|---|---|---|---|
| `kb::ledger-lock` | 0 | `flock` per ledger dir across tail-read → gate → append; `node_seq` under the lock; `chain_append` fsyncs | — | new `tests/test_ledger_lock.py`: 4 processes × 25 appends → `verify_all_chains` ok, 100 rows, `node_seq` 1..100, in 5/5 runs |
| `kb::frontier-crosspaper-obligations` | 0 | `buildMission` from all papers; `readyFrontier` excludes nodes with open obligations; `missionComplete` and `gateSignal` scoped to the mission paper | — | `cd orchestrator && npm test` with fixtures: `P::top` on solid `_shared::base` ready; a node with an open obligation not ready; `_shared` `future` node does not block P's completion |
| `kb::claims-fail-loud` | 0 | `Ledgers.claims()` throws on CLI failure; the wave halts with the CLI's stderr | — | `npm test`: a malformed claims line halts the wave with a `ledger_unreadable` reason instead of an empty frontier |
| `kb::schema-single-source` | 1 | `_common/schema.py` owns enums, paths, caps, cadences, roles; modules import it; manifest reads it | — | new `tests/test_schema.py`: AST scan proves each enum is defined in exactly one module; manifest equals schema |
| `kb::supersedes-retire` | 1 | `supersedes` on all ledgers; `retired` status; per-ledger "different content" rule (result: claim or evidence_type; claim: statement; knowledge: summary or predecessors) rejects unlinked replacement, allows promotions; frontier and completion exclude `retired` | lock | new `tests/test_supersedes.py`: accept promotion, reject unlinked replacement, redirect via `supersedes`, retired node absent from frontier |
| `kb::integrity` | 1 | `node_ids` / `node_id` / claim `dependencies` must resolve at append; cycles rejected; `contract.py verify-integrity` reports dangling refs, cycles, orphans, and dependents whose support was demoted / refuted | supersedes-retire | new `tests/test_integrity.py` reproducing §9 demonstrations 2–4 and the demotion / refutation cases as rejections or reports |
| `kb::evidence-hardening` | 1 | gate strips caller-supplied `evidence_sha256` / `verification_run`; verification commands registered in the task file and cited by name; output stored whole under `results/evidence/<sha256>` with a 256 KB cap | integrity | `tests/test_admission.py` + new cases: prefilled hash rejected; unregistered command rejected; output file hashed and cited |
| `kb::chain-heads` | 1 | `results/ledgers/CHAIN_HEADS.json` written by the wave commit step (single writer), verified by `verify-chains`; tail truncation since the last commit detected | lock | `tests/test_hash_chain.py::test_tail_truncation_detected` + `npm test` (heads written per wave) |
| `kb::csv-untracked-consolidated` | 1 | `summary.csv` untracked and rebuilt on demand; one `snapshot` CLI returning knowledge + results + claims for a paper; `ledger.ts` makes one call per wave | schema | `git ls-files | grep -c summary.csv` = 0; `npm test`; a test counting subprocess launches per wave ≤ 2 |
| `kb::error-query` | 1 | `error_database.py query` with `--node-id / --task-id / --failure-mode / --since`; `crash-triage` uses it | schema | `tests/test_error_ledger.py` new cases |
| `kb::docs-rendered` | 2 | `render-docs` fills marked blocks in INDEX / specs / AGENTS from the schema; drift test renders and diffs | schema | new `tests/test_docs_rendered.py` |
| `kb::behavior-drift-tests` | 2 | one test per prose-behavior drift obligation (readiness, cadence, validator wiring, steer reach, dry-run) | frontier-crosspaper-obligations | `python3 -m pytest tests/test_spec_behavior.py -q` + `npm test`; each obligation discharged by a test id |
| `kb::skills-facts-moments-pack` | 2 | registry checks `## Facts`; `metadata.moments`; `pack` with byte budget; `agents.ts` and validator packs use it | docs-rendered | `python3 _common/skill_registry.py validate --exec` (facts checked) + `npm test` |
| `kb::notes-tracked` | 2 | snapshot notes generated and tracked; research-state = through-line ≤ 2 KB + generated blocks; `progress/<mission>/` un-ignored | csv-untracked-consolidated | `npm test` with a consumer-shaped fixture carrying the repo's `.gitignore`: the wave commit contains the notes |
| `kb::sqlite-index` | 3 | index + FTS + `search` / `similar-trials` / `lineage`; built and read under the ledger locks; rebuilt on head mismatch; gate reads it only when fresh | lock, chain-heads, integrity | new `tests/test_index.py` incl. a concurrent writer + reader case; `tests/test_admission.py` run with and without an index |

Stage 0 = 3 nodes, stage 1 = 7, stage 2 = 4, stage 3 = 1 (+ follow-ups). Each
is one commit; each can be delegated with the verifier as its contract.

## 7. Risks

- Advisory locks do not cover NFS or Windows; document the constraint, fail loudly when `flock` is unavailable.
- `supersedes` semantics differ per ledger; the "different content" rule must be stated per ledger or promotions break.
- Generated prose nobody can read: render only tables and reference sections; rationale stays hand-written.
- Evidence store growth: the 256 KB cap and the no-large-datasets commit policy must agree; large artifacts stay outside the repo with hashes cited.
- Skill bloat: the pack assembler's byte budget is the control.
- Index divergence if B is adopted early: the lock-and-rebuild rule is necessary, and still leaves the gate depending on index freshness; keep the file path as the arbiter.

## 8. Open questions for the owner

1. Is this the "knowledgebase" you meant — ledgers + DAG + notes + docs/skills together — or specifically the knowledge ledger and its DAG?
2. Stage 0 changes runtime semantics (obligations block readiness; completion scoped per paper). Acceptable, or should obligations only warn?
3. Should demotion / refutation of support demote dependents automatically (a gate) or only be reported by `verify-integrity` first?
4. Track mission notes in git (un-ignore `progress/<mission>/`) or keep them ephemeral?
5. Retrieval: is grep + an error `query` enough until B, or is semantic similarity wanted now (external dependency)?
6. Retire the Python `loop_gate.py` (unwired since the ralph-loop driver was removed) in stage 1?

## 9. Evidence appendix (measured 2026-09-09; scripts in `notes/kb_redesign/`)

Scaling (`scale.py`, author; reviewer's independent rerun in parentheses; ms):

| N | knowledge append | query | predecessors --transitive | trial append | nodes.jsonl |
|---|---|---|---|---|---|
| 100 | 4.4 (5.6) | 0.5 (0.5) | 1.4 (1.3) | 4.7 (5.3) | 39 KB |
| 500 | 15.0 (14.8) | 2.4 (2.1) | 26.0 (22.8) | 16.1 (16.2) | 232 KB |
| 2000 | 48.6 (52.8) | 9.1 (8.3) | 434.1 (325.4) | 59.6 (52.8) | 1009 KB |
| 10000 | (234.5) | (46.1) | (7919.6) | (216.8) | (5074 KB) |

`append_batch` of 200 knowledge rows on ~2,600: 9.9 s (12.7 s). Append profile
at 2,006 rows: `regenerate_summary` 30.3 ms (57%), `read_entries` for
`node_seq` 8.0, `find_knowledge_node` 8.1, chain-tail read 1.7, `git rev-parse`
2.7. CLI `query` subprocess: 46 ms at N=100, 78 ms at 2,000, 193 ms at 10,000;
interpreter start-up alone ≈ 45 ms; 14 CLI launches per wave.

Concurrency (`concurrent.py`): 4 processes × 25 appends to one error ledger →
chain broken 3/3 runs (author: `break_at` 5, 1, 18; reviewer: 1, 6, 2).

Demonstrations (`gaps.py`): (1) `P::top` with solid predecessor `_shared::base`
→ `readyFrontier` = `["P::solo"]`, `plan` agrees; (2) `r1` re-appended with
the opposite claim → latest view shows the new claim, two history rows, no
link, no warning; (3) last row deleted from `results.jsonl` → `verify-chains`
`{"ok": true}`, deleting a middle row is caught; (4) trial with
`node_id: P::does-not-exist` accepted → `progress` row with `status: null`.
Reviewer's additional cases: demoted predecessor leaves dependent solid;
refuted `result_ref` leaves claim admitted; caller-supplied `evidence_sha256`
and free-text evidence + `verification: {command: "true"}` both admitted as
solid; hypothesis cycle accepted and omitted from `plan`; malformed claims
line → `Ledgers.claims()` returns `[]`; same `node_id` in two papers resolves
by `paper_hint`.

Prose vs code (bytes): contracts 30.7 K + specs/templates 57.2 K + notes
57.7 K; skills 249 K; Python 282 K; TypeScript 91.7 K. Session-start injection
6,733 (18,335 with `--with-skills`); 33 skill descriptions 9,240 chars; worker
prompt 2.4 KB over a 20.7 KB read set. Files stating each fact: `CHANDRA_ROLE`
30, `results/ledgers/` 19, 10 KB cap 13, 5-iteration cadence 7, domain enum 5.
Host: SQLite 3.45.1 with FTS5 and JSON1; Python 3.12.3; Node 18.19.1.

## 10. Refutation record

Reviewer: an independent fresh-context session (Claude), 2026-09-09, read-only,
throwaway repos under `/tmp/kb-refute/`. Verdict: ADMIT WITH AMENDMENTS.
Reproduced: the scaling table (within ~30%), all four demonstrations.
Confirmed: P2, P3, P5, P7, P9, P10. Downgraded: P1 (loud halt, workaround,
TS-only fix), P4 (CSV and subprocess start-up dominate; index does not remove
start-up), P8 (grep suffices today). Root cause corrected: P6 (generator
explains ≤ 5/29 drift findings). Added: P11 locking (C), P12 downstream
invalidation, P13 proposer-defined verifiability, P14 no retirement, P15
swallowed claim failures, P16 non-global node identity. Recommendation
changed from "B + K staged" to "A + K now; B threshold-gated"; the §3d claim
that a rebuild-on-head-mismatch index can never become a second truth was
withdrawn (it fails under parallel writers without locks). Nine DAG verifiers
were rewritten because they could not decide their nodes; K no longer depends
on the index. Pending: the cross-model GPT-6 refutation (`kb-gpt6-review`).
