# Knowledgebase redesign — diagnosis, refutations, staged proposal

Status: PROPOSAL, REFUTED TWICE (2026-09-09). Version 3. The first draft
was written from code reading and measurements; a fresh-context reviewer
refuted it and found the writer race; two independent GPT-6 analyses (data
layer; agent-knowledge layer), sealed off from the note, were then merged in;
finally a GPT-6 cross-model refutation of the committed note added fourteen
defects and twelve amendments, all applied here. The reviews are archived
verbatim in `notes/kb_redesign/reviews/`; §10 records what changed and where
the reviewers still disagree. Nothing here is implemented. Every defect is an
open obligation under paper `self` (`kb-*`, six blocking); §6 is the DAG a
self-optimize mission would work.

Reproduction marks: **[A]** author, **[R1]** first refutation (Claude),
**[G-D]** GPT-6 data-model analysis, **[G-K]** GPT-6 agent-knowledge analysis,
**[R2]** GPT-6 refutation. A defect carrying two or more marks was reproduced
independently by each.

## 0. Scope

"Knowledgebase" = everything an agent or the runtime reads to know what is
true and what to do:

| layer | artifacts |
|---|---|
| research memory (data) | the four JSONL ledgers under `results/ledgers/<db>/paper_<P>/`, their hash chains, the admission gate, the DAG (`predecessors`, `PAPER::node`, `_shared::`), rendered views (`results.md`, `claims.md`, `summary.csv`, HTML, Mermaid, dashboard), loop policies |
| mission memory | the three notes under gitignored `progress/`, the human digest, the runtime journal, packet WALs |
| agent knowledge | `alignment.md`, `_common/contracts/*.md`, `INDEX.md`, `README.md`, `pipelines/*/spec.md`, the 33 skills and their registry, `AGENTS.md`, the prompts in `orchestrator/src/agents.ts` |

They are treated together because they fail together: the 29 `drift-*`
obligations are prose describing data behavior the data layer does not have,
and the skill registry that was meant to keep skills true has holes of its own.

## 1. What the design is today

One research graph — claims, obligations, assumptions, DAG nodes, results,
trials, sources, evidence — stored as four append-only, per-paper JSONL files
whose rows point at each other by free-text ids. Identity is "latest row per
id wins"; correction is a new row with the same id; amendment is a row with
`status: amended` plus prose in `notes`. Integrity is enforced at append for
five reference kinds only (`claims_database.check_refs`: `result_ref`,
`discharged_by`, `reduction_obligation`; `admission.py`: `::` dependencies
and immediate solid predecessors), by existence, and only at the dependent's
own append. Every read is a full-file scan; no reader verifies the chain; no
append takes a lock; every append rewrites `summary.csv`. The TypeScript
runtime rebuilds the mission from one paper's rows per wave through `python3
… query` subprocesses with a 16 MiB output cap and swallows claim-ledger
failures. Prose (contracts, specs, INDEX, README, 33 skills) restates the data
layer's behavior by hand; only the enum manifest is shared mechanically, and
even it spells the state cap and ledger filenames itself.

## 2. Diagnosis — thirty problems, grouped, with evidence

Severity: **C** blocks correctness · **S** silently wrong · **T** costs time
or liveness · **D** drift. Scripts for [A] demonstrations are in
`notes/kb_redesign/`; the reviewers' scripts and receipts are described in
their memos.

### 2.1 Write path

**P11 (C) Parallel appends corrupt the hash chain.** [A][R1][R2]
`chain_append` reads the tail hash, then appends, with no lock and no fsync
(`_common/ledgers/ledger_common.py:134-149`). Four processes × 25 trials
broke the chain in 3/3 runs for each of three reviewers (`break_at` 1–18 of
100; `node_seq` collapsed to 72–81 distinct values). The runtime runs packets
in `Promise.all` and jobs concurrently with them (`scheduler.ts:97`,
`main.ts:187-190`); the end-of-wave check then halts `ledger_tampered`
(exit 8) with no repair path. An exclusive `flock` around the whole append
was a successful control [R2].

**P17 (C) No transaction or coherent read boundary.** [G-D][R2] Sequence
allocation, dependency validation, hash append, CSV regeneration, and each
consumer's reads are independent operations. Two real appends interleaved
under control produced sequences `[1,2,2]` and a broken chain; a two-row
batch keeps its first row when the second fails; a reader can see a half-
written row (`Expecting value: line 1 column 326`); one legal append between
two dashboard reads yields a node with no displayed history. A per-ledger
lock alone does not serialize the gate's read set: with P locked, Q's
predecessor can be demoted under Q's lock before P's append lands, leaving
P's child solid on a hypothesis [R2].

**P18 (S) Batch identity and retry have no contract.** [G-D][R2] Batch
dedup compares status + summary/statement before validation: rows that change
only predecessors, owner, `node_ids`, or `blocking` — or that carry a failing
verifier — are skipped as duplicates (`knowledge_database.py:240-243`,
`claims_database.py:203`). Result and error batches have no request identity:
replaying after a failed second row duplicates history, and replaying one
trial three times triggers escalation.

**P19 (S) Progress is attributed by snapshot deltas, not events.** [G-D][R2]
A packet that wrote nothing is reported `promoted` when a concurrent acquire
job settles its obligation before the second snapshot (`scheduler.ts:119-130`).
`unchecked → checked` is `no_progress` to the scheduler but progress to the
gate; a new `unchecked` result is `promoted` to the scheduler but not to the
gate (`gate.ts:33-39`).

### 2.2 Identity and lifecycle

**P2 (S/D) Identity and amendment are conventions, not edges.** [A][R1][R2]
Re-appending `result_id r1` with the opposite claim replaces it in every
latest-view with no link (this is the documented correction path,
`result_database.py:20-22`); `amended` rows redirect nothing. R2 downgrades
the standalone case to D/T — history survives — and keeps S for the dependent
support it leaves behind (P12).

**P16 (S) Node identity is not global.** [A][R2] `admission.find_knowledge_node`
resolves the same `node_id` in two papers by `paper_hint`; `dag.ts:7-23`
collapses imported duplicates by input order and overwrites row ownership
with the mission paper.

**P14 (T) Nodes cannot be retired.** [A][R1][R2] `latest_per_node` skips
`amended` rows, so the prior status persists; `future`/`blocking`
placeholders are leased every wave and block `missionComplete`.

**P20 (S) Settlement is semantically unchecked at first admission.** [G-D][R2]
`check_refs` tests existence only: an `exact_proof` claim is admitted on a
`conjectural` or `empirical` result whose verdict is `fail`; an obligation is
discharged by a refuted result or a hypothesis node (spot-checked [A]); a
relaxed assumption may cite an obligation that has since become a claim.
`--allow-missing-refs`, `--allow-missing-deps`, `--skip-exec` are recorded on
rows that no runtime consumer inspects.

**P12 (S) No downstream invalidation.** [R1][G-D][R2] Solid-on-solid and
admitted-cites-passing hold only at the dependent's own append. Demote a
predecessor, refute a settling result: the solid dependent and the admitted
claim stand, and a *new* solid node on the stale support is still accepted
and offered as ready by the runtime.

**P21 (S) Waiver provenance stops at the row.** [G-D] An ancestor admitted
with `allow_missing_deps` carries the flag; its solid child and checked
result carry nothing; `results.md` and `render-state` omit `skip_exec`.

### 2.3 Graph

**P1 (T) Cross-paper dependencies are never ready in the runtime.**
[A][R1][R2] `buildMission` loads one paper (`main.ts:161-162`);
`readyFrontier` treats an absent predecessor as not solid (`dag.ts:66-73`);
the Python gate resolves globally, so gate and frontier disagree. Downgraded
from C: the halt is loud (exit 3 when nothing else is ready), a mirror row
works around it, and R2 notes the fix is more than a few lines because
ownership and packet selection also change.

**P3 (S) Partial referential integrity.** [A][R1][R2] Trials, results, and
claims may anchor to nodes that do not exist; readiness ignores open
obligations (`dag.ts:31-36` collects them, `readyFrontier` never reads them);
completion ignores attached open repairs.

**P22 (C) Cycles are admitted.** [G-D][R2] A solid node citing itself as
predecessor is admitted (spot-checked [A]); a cross-paper cycle `P::a → Q::b
→ P::a` with both solid is admitted with valid chains; the runtime hides
cycles as depth −1 without a diagnostic.

**P23 (T) "Obligations block readiness" deadlocks as stated.** [R2] The
validator files an ownerless blocking repair on the rejected node
(`validator.ts:190`); jobs special-case only `owner === "0-acquire"`
(`jobs.ts:99`). Excluding obligated nodes from the frontier without a repair
job yields `no_ready_jobs` (exit 3). Paper-level blockers with empty
`node_ids` (the three blocking `kb-*` obligations today) are invisible to a
node predicate; interiors of packets bypass `readyFrontier`
(`scheduler.ts:45`); importing all papers lets one paper lease another's
nodes.

### 2.4 Integrity, provenance, verification

**P5 (S) Tamper evidence stops at the file tail; provenance is self-declared.**
[A][R1][R2] Deleting the last rows passes `verify-chains`; the unhashed legacy
prefix is not covered either; `actor_role` is an environment variable.

**P24 (C) Decisions and terminal exits precede integrity checks.** [G-D][R2]
`main.ts:169,231` return `mission_complete` / `no_ready_jobs` before the
chain check at `:239`; a tampered all-solid ledger and a torn claims file
both produced exit 0 "mission complete". No reader verifies the chain, so a
corrupted ledger keeps accepting appends (spot-checked [A]); `ledger.ts:31`
drops the stdout that carries chain diagnostics.

**P15 (S) The runtime swallows claim-ledger failures.** [R1][G-D][R2]
`Ledgers.claims()` returns `[]` on any CLI error (`ledger.ts:60-69`); a
malformed line, a missing CLI, or a valid 17.8 MB ledger over the 16 MiB
`maxBuffer` all empty the wave's obligations silently.

**P13 (S) Verifiability is proposer-defined.** [R1][G-D][R2] Presence of an
`evidence_sha256` key — even `null` — satisfies the checked/solid rule
(`admission.py:247,284`); a proposer-chosen `verification.command` plus free
text yields `solid`; any existing artifact or resolvable commit satisfies the
mechanical alternative. Root cause is not `shell=True` but unspecified
verifier authority and non-immutable inputs.

**P25 (S) Evidence has no lifecycle.** [G-D][R2] The artifact hash is
computed once; modifying and then deleting the file leaves the result
`checked` with valid chains; caller-supplied `execution` / `revision` /
`timestamp` fields persist as observations.

**P26 (C) Validation is not bound to the reviewed submission.** [R2]
`adjudicateCandidate` appends `candidate.resultRow` without comparing it to
`CLAIM.md`: a row for another paper, an opposite claim, or a row mutated
inside the judge callback is admitted (`validator.ts:155-184`). Evidence
paths are joined without containment — `../outside-pack.txt` landed outside
the pack while `checkIsolation` passed. `parseJudgeVerdict` accepts empty
reasons; packs are deleted; the journal keeps 500 characters of findings; the
mission loop never calls the validator, so the production contract is
undecided. Under the explicit `danger-full-access` override the pack is
cwd + prompt only.

### 2.5 Cost and transport

**P4 (T) Costs are real but were mis-attributed.** [A][R1][G-D][R2] Full-file
scans are linear; `predecessors --transitive` is O(V·N) (quadratic on a
chain: 1 → 315 → 8,200 ms at 100 / 2,000 / 10,000 rows); 57–74 % of an append
is regenerating the tracked `summary.csv`; a CLI call costs 46–56 ms at
N=100 (of which ~21 ms is bare interpreter start-up) and 210–216 ms at
N=10,000. The first draft's "every operation is O(n)", "14 launches", and
"0.7 s per wave" were withdrawn: launch counts vary by path and no wave-time
denominator was measured. A real sequential admission series reached 5,000
rows in 286 s [G-D]. Transport: 5,000 rich rows (23 MB) exceed the bridge's
16 MiB `maxBuffer` and the query fails although Python returned every row.
At the owner's scale (10²–10³ nodes) none of this is critical.

### 2.6 Retrieval

**P8 (T) No retrieval beyond exact ids and substring filters.** [A][R1][R2]
No error-ledger `query`; no cross-ledger search or reverse-reference lookup;
`duplicates` is a normalized-summary heuristic; the node view reads 74 rows
to return three. Workarounds exist (`rg`, `jq`, the HTML filter); semantic
similarity is out of scope.

**P27 (T) Task labels stand in for approach identity.** [G-D] `crash-triage`
groups by `task_id`: three independent nodes sharing a label escalate; three
failures of one node under renamed labels each return `fix_and_retry`; there
is no stable attempt id or explicit pivot event.

### 2.7 Mission memory

**P7 (D/S) Mission memory duplicates the ledgers and is not durable.**
[A][R1][G-K][R2] Notes are written into gitignored `progress/`; consumers
inherit the ignore; the template's "history in git" does not exist.

**P28 (S) Pruning destroys generated blocks and never-committed text.** [G-K][R2]
`observer.ts:51` cuts whole lines before `main.ts:249` commits: a tracked
23,568-byte note became 9,979 bytes with the generated block's END marker cut
and a new through-line absent from every git revision, while the footer still
claims full text is in history; `runObserver` never refreshes the
accepted-results block.

**P29 (S) The journal and digest cannot reconstruct a mission.** [R2] A restart
resets wave numbering and gate state; `waveHistory` maps by wave only, so two
"wave 1" records collapse; the digest points at a journal path that does not
exist, is gated on `windowsUsed` that CLI workers hardcode to 1, is emitted
before the integrity check, and is not finalized on halt.

### 2.8 Agent knowledge

**P6 (D) Prose exceeds the code it describes; facts have several editable owners.**
[A][R1][G-K][R2] Authored prose 368 KB against 315 KB of owners [G-K];
`CHANDRA_ROLE` is stated in 19–30 files depending on the counting rule, the
ledger layout in 12, the packet contract in 9, the role policy in 19. Of the
29 drift obligations, 4 are wholly and 3 partly enum/path facts a generator
could render; 22 describe behavior [R2] — so generation fixes a minority and
behavior tests the rest. The manifest itself hand-declares the cap and
filenames (`contract.py:25,71`); the observer declares `10240` again.
`INDEX.md` claims to win disputes while `AGENTS.md` names the same file as
the authority by an unqualified name [G-K].

**P10 (T) Context cost is unbudgeted.** [A][G-K][R2] Session start injects
6,733 bytes (18,335 with the briefing); the 33 skill descriptions cost 11,601
bytes in the briefing; a median skill is 7.7 KB; the three real work skills
cost 27,998 bytes; a one-node worker with its required reads costs 22.7 KB
(SDK) / 35.2 KB (CLI) and 50.7 / 63.2 KB after loading those three skills;
Verify sections are 17 % of skill bytes [G-K]. R2 corrects "the only budget":
turn and time limits exist; what is missing is accounting for the assembled
context.

**P30 (C for the harvest gate) The skill registry's own gate has holes.**
[G-K][R2][A] `verify_block` runs only the first fenced block — a second block
that exits 1 passes; seven shipped skills' Verify blocks read the installed
`.claude/skills/<name>/SKILL.md` rather than `$CLAUDE_SKILL_DIR`, so
promotion certifies the old text, not the candidate (a candidate whose
example uses an impossible status passed); a draft with no Verify block is
promoted; `new` scaffolds straight into the registry and `list_skills`
discovers any directory, so unadmitted drafts load as if admitted; unknown
frontmatter keys only warn, so a `facts` block would not be checked; nested
`metadata` is flattened by the parser; a copy failure mid-harvest leaves a
partial install that the next `notes(wave)` commit stages anyway, and a
promotion in the halting wave stays outside HEAD; harvested skills land in a
`notes(wave)` commit rather than the required `infra(skills)` commit. Also
`dag_mermaid._safe` maps `P::a-b` and `P::a_b` to one identifier [R2].

**P9 (D) Two runtimes re-implement behavior the manifest does not carry.**
[A][R1][R2] `loop_gate.py` counts discharged results, `gate.ts` counts
discharged obligations; the Python gate is unwired but shipped and skilled.

## 3. What an optimal design must satisfy (amended)

- G0 A transaction contract, not just a lock: verification runs against immutable inputs outside the critical section; a short commit section (repository lock or ordered dependency locks) re-validates the read set and versions, allocates sequences, deduplicates by request identity, appends and fsyncs; readers see only committed, whole rows; waves observe coherent before/after epochs.
- G1 Entities have immutable kind and identity; revisions are explicit (`supersedes` to a row hash); aliases and retirement are typed edges with dependent handling; `paper` is ownership, not partition; dependency and supersession relations are acyclic at write time; settlement checks evidence-class compatibility and *current* validity of the referent; support changes are either propagated or reported to a consumer that blocks use.
- G2 The append-only, hash-chained JSONL stays canonical and git-tracked; everything else is derived and rebuildable; a trusted checkpoint (previous commit + ledger inventory + digests of unhashed prefixes) is verified before scheduling, completion, or checkpoint replacement.
- G3 Linear scans replaced by indexed maps where quadratic; bounded, paginated transport; one coherent snapshot per epoch with a measured call budget.
- G4 Evidence authority: gate-owned fields are rejected on input; verifiers are registered per task and executed as immutable definitions; candidate identity, reviewer verdict, execution, and admitted bytes are bound together; outputs retained whole under an aggregate budget with overflow rules; packs are contained by realpath and re-checked between phases.
- G5 Retrieval: cross-ledger search and reverse references; stable attempt ids; skills located by typed moment (stage × role × event) with an executable loader.
- G6 One owner per fact, with a scope and an enforcement label (implemented / intended / rationale); generated reference blocks are drift-tested; behavior is kept true by behavior tests, never by generated prose that would bless a bug as policy.
- G7 Mission memory = ledgers (research) + durable operational events with run identity + a hand-written through-line; prior bytes are preserved before any prune; generated blocks are replaced whole.
- G8 Every delivered context carries a receipt: source commit, selected skill revisions, bytes, ledger watermark; mandatory closure fails or splits explicitly instead of truncating.
- G9 Skill admission binds checks to candidate bytes, requires a Verify block, publishes skill + index atomically, keeps drafts undiscoverable until admitted, and lands in its own commit.

Non-negotiables that stay: the verifier admits; executable admission at write;
ledgers canonical over prose; delegation policy; the commit gate; Python
≥ 3.10 with no third-party dependencies; Node 18.

## 4. Candidate architectures

### A — Harden the four JSONL ledgers in place

Keep the four streams and their CLIs. Add: a global writer lock with the G0
protocol and a committed multi-stream receipt (heads + counts + legacy-prefix
digests) written by the wave commit; typed entity / revision identity with
`supersedes`, alias, and `retired`, and a per-ledger semantic comparison
(assumptions, evidence, scope, kind included) that rejects unlinked
replacement while allowing promotions; request identity for batches and
validation before dedup; typed reference resolution (`node_ids`, `node_id`,
`dependencies`, `source_ids`) and acyclicity for dependency and supersession
at append; settlement compatibility (evidence class, current validity) and a
support-change reducer that reports — later gates — stale dependents;
gate-owned fields rejected, verifiers registered per task, evidence retained
under an aggregate budget; readers that fail closed and a chain/checkpoint
check before any decision or terminal exit; `readyFrontier` built from all
papers with ownership preserved, prerequisite blockers separated from repair
work and from closure, and repair jobs runnable; `summary.csv` untracked; a
coherent `snapshot` query with before/after epochs; an error-ledger `query`;
one `_common/schema.py`; a latest-row map for traversal.

Fixes P11, P17 (within one repository lock), P18, P2, P16, P14, P20, P12
(report first), P21, P1, P3, P22, P23, P5, P24, P15, P13, P25, P26, most of
P4. Effort: R1 estimated days for stage 0; G-D estimates 15–24 person-days
for its fuller A; the two agree that A is the prerequisite for anything else.
Every skill keeps its CLI surface; twelve operational skills need their
executable fixtures changed, not merely reworded (they currently assert
automatic CSV creation, admit an orphan trial, replace predecessors without
lineage, and submit free verifier commands) [R2].

### B — Canonical accepted-transaction log + rebuildable SQLite projection

G-D's version, stronger than the first draft's "index": the four streams are
sealed as immutable archives with genesis manifests; new writes are one-line,
hash-chained transaction envelopes (idempotency key, expected input versions,
actor role, evidence references, generated observations) that can carry
several logical events atomically; SQLite (stdlib; FTS5 present on this host,
must be feature-checked on consumers) is a derived projection of entities,
versions, events, typed edges, evidence, runs, effective validity, and FTS,
storing the last applied sequence and hash; reads pin a head; the gate resolves
references through the projection but the log is the only commit. Adds what A
cannot: atomic multi-ledger flushes, pinned reads, exact replay, effective
validity as a first-class query. Effort 27–44 person-days [G-D]. Risks: crash
recovery, index freshness under parallel writers (the projection must be
built and read under the same lock discipline), consumer `.gitignore`, branch
divergence, two implementations of admission rules unless validators share
adapters.

### C — Universal typed graph store

Nine node kinds and six edge kinds as the public authoring contract; the
backend may still be B's log + projection. 37–59 person-days [G-D]; every
producer contract changes. Justified only if consumers need independently
evolving, queryable historical rule sets or cross-mission procedure reuse
[G-K]; not established by any measurement.

### K — The agent-knowledge layer (independent of A/B/C)

G-K's staged design, adopted over the first draft's K1–K4:

- K-A **Ownership and generated references.** A catalog assigning each fact one owner, a scope, and an enforcement label; source adapters deriving domains, statuses, layouts, schemas, CLI inventories, and the commit grammar from the code that owns them; a behavior contract of executable cases (readiness with obligations, partial batch admission, strict roles, pre-prune persistence, paper-vs-digest cadence) that classifies intended-but-unimplemented rules visibly; rendered reference blocks in `INDEX.md`, the specs, the contracts, and `AGENTS.md` with markers and drift tests. Scope honestly: this covers the enum/path minority of the drift; behavior drift needs the behavior contract's tests.
- K-B **Skills as the procedural unit.** Skills carry checked `facts` records (fact, source symbol, expected value = a generated, reviewed pin) in a typed encoding the parser preserves; the registry verifies the *candidate's* bytes, requires exactly one Verify block, keeps drafts outside discovery, records an admission receipt (hashes of candidate, facts, verification inputs), publishes skill + index atomically, and lands in an `infra(skills)` commit. A deterministic loader maps (stage, role, event) to a small skill set, preserves opt-in skills, and assembles worker, job, and validator packs with a byte budget that fails or splits explicitly and records a receipt. Pilot on the three work skills (target ≤ 4 KB bodies each, down from 28 KB combined; Verify code moved to support files) before migrating all 33 [G-K]. Only 12 of 154 assertion sites in current Verify blocks are equality-to-constant facts (5 of 33 skills) — facts blocks complement, they do not replace, behavior assertions [R2].
- K-C **Mission memory.** One structured, watermarked snapshot feeds the iteration note, nodal note, digest, and generated state sections; the hand-written through-line lives in a preserved narrative source; prior bytes are archived before any prune; generated blocks are replaced whole; run and wave identities are durable; the digest reports integrity status and finalizes on halt; selected notes are tracked, control and scratch files are not.
- K-D **Retrieval.** A disposable local index over facts, procedures, and trial references answering the three lookup questions with source references, and "unknown / not recorded" for missing joins; harvest flags overlapping procedures and invalidates dependents when their source symbols change.

## 5. Recommendation

**A + K now, in stages that each leave the repo runnable; B when its
semantic or scale triggers are met, decided by measurement after A.**

- Stage 0 — emergency correctness (days, the six blocking obligations): the
  writer lock with G0's protocol for a single repository lock, readers that
  fail closed (P15) and a chain/checkpoint check before scheduling and exits
  (P24), the validator bound to its reviewed submission with contained packs
  (P26), the registry binding checks to candidate bytes and refusing drafts
  without a Verify block (P30), and the cross-paper / ownership / repair-aware
  frontier (P1, P3, P23) — with identity rules and reject → repair →
  discharge → admit fixed before global import.
- Stage 1 — semantic hardening (the rest of A): entity/revision model with
  `supersedes`, alias, `retired`; request identity and validation-before-dedup;
  typed references and acyclicity; settlement compatibility and the
  support-change reducer; gate-owned evidence, registered verifiers,
  retention with an aggregate budget; checkpoint manifests with legacy-prefix
  digests; `summary.csv` untracked; coherent snapshot with epochs; error
  `query`; `_common/schema.py`.
- Stage 2 — K-A through K-D, starting with the ownership catalog and the
  behavior contract, then the three-skill pilot, then the loader and packs,
  then memory and retrieval.
- Stage 3 — B, when a mission needs atomic multi-ledger flushes or pinned
  reads that A's single lock cannot give, or when post-A measurements show
  ledger I/O on the wave's critical path, or when a retrieval workload
  exceeds grep. The first draft's 10⁵ rows / 5 % thresholds are provisional
  policy, not measured crossovers [R2].

Where the reviewers disagree: G-D holds that B is justified on correctness
grounds regardless of scale (atomicity, replay, effective validity); R1 and R2
hold that A's transaction contract delivers those within one repository and
that B should follow measurement. This note sides with measurement after A,
and keeps B's design (not just its index) as the target if A's single lock
proves insufficient.

Do not change: the JSONL log and its chains, the executable admission rule,
the rendered-view rule, the delegation policy, the commit gate, the
stdlib-only constraint, the skills' CLI surfaces, the small always-on kernel,
the markers discipline, immutable source mirrors, large data outside git.

## 6. Migration DAG

Verifier cells name the discriminating cases each test must contain (per the
R2 audit of the previous verifiers); a positive fixture alone does not decide
a node. Dependencies follow R2: identity and repair semantics precede global
leasing; schema precedes changed status contracts; registration and
immutable snapshots precede evidence hardening; preservation precedes
tracked notes.

| node | stage | summary | predecessors | verifier must discriminate |
|---|---|---|---|---|
| `kb::ledger-transaction` | 0 | repository lock; verify outside, commit inside; sequences and dedup under the lock; fsync; readers fail closed on partial rows | — | 4 writers × 4 ledgers × 5 runs valid; interrupted write invisible to readers; dependency demoted under a second lock is caught by re-validation; verifier subprocess cannot deadlock on the lock |
| `kb::integrity-before-decisions` | 0 | chain + checkpoint verified before scheduling, completion, halt, digest; `Ledgers.*` throw with stderr/stdout; bridge overflow is an error | — | tampered all-solid ledger, torn claims file, 17 MB claims ledger, missing CLI each halt with the diagnostic; empty ledger still schedules |
| `kb::validator-binding` | 0 | candidate deep-copied and hashed; paper/node/claim/revision bound to `CLAIM.md`; realpath containment; re-check between phases; non-empty reasons; verdict inputs retained | — | other-paper row, opposite claim, judge-time mutation, `../` evidence path all rejected; retained review reproduces the verdict |
| `kb::registry-candidate-binding` | 0 | Verify runs against candidate bytes; exactly one block required; drafts default outside discovery; admission receipt; installed-self references rejected | — | the seven shipped self-reference skills fail until fixed; impossible-status draft rejected; two-block draft rejected; no-Verify draft rejected; scaffold not listed until promoted |
| `kb::identity-revisions` | 1 | immutable kind + id; `supersedes` (row hash); alias; `retired`; per-ledger semantic comparison; promotion/demotion matrix; trial request identity | ledger-transaction | every ledger's transition matrix incl. legacy `amended`; the 14 real promotions replay unchanged; unlinked replacement rejected; retired node absent from frontier and completion, dependents reported |
| `kb::frontier-ownership-repair` | 0/1 | mission from all papers with ownership preserved; blockers vs repair work vs closure; paper-level obligations; repair jobs runnable; interiors use the same eligibility; scoped completion and progress | identity-revisions | `P::top` on solid `_shared::base` ready; reject → repair → discharge → admit through the production entry point; nonblocking obligations do not block; empty-`node_ids` blocker visible; foreign leasing rejected; `_shared` future node does not block P |
| `kb::schema-single-source` | 1 | `_common/schema.py` owns enums, paths, caps, cadences, roles, filenames; manifest and TS consumers derive | — | mutate each source value → manifest, runtime constants, and rendered consumers change together; AST proves one definition site |
| `kb::typed-refs-acyclic` | 1 | `node_ids` / `node_id` / `dependencies` / `source_ids` resolve by type and revision; dependency and supersession cycles rejected; citations may cycle | identity-revisions | self-loop, cross-paper cycle, orphan trial, forward reference in a batch each rejected; citation cycle admitted |
| `kb::settlement-validity` | 1 | evidence-class compatibility; referent current and valid; bypass flags consumed by frontier and completion; support-change reducer reports stale dependents (gate later) | typed-refs-acyclic | exact_proof on conjectural rejected; discharge by refuted rejected; demotion produces a report the frontier honors; every bypass-flagged row visibly excluded from closure |
| `kb::verifier-registration` | 1 | verifiers registered per task file, immutable definitions; gate-owned fields rejected on input; execution bound to candidate identity | schema-single-source | prefilled hash / `null` hash / free command rejected; registered verifier's exact bytes recorded; timeout and overflow handled |
| `kb::evidence-retention` | 1 | outputs stored whole under `results/evidence/`; aggregate budget; overflow → external retention with digest + availability; re-check on read | verifier-registration | modified and deleted artifacts surface as unavailable; budget exceeded refuses; replay reproduces |
| `kb::checkpoint-manifest` | 1 | wave commit writes heads, counts, ledger inventory, legacy-prefix digests; verified against the previous commit before replacement | ledger-transaction | tail deletion, whole-ledger deletion, legacy-prefix edit, concurrent head capture, failed commit each detected |
| `kb::snapshot-epochs` | 1 | one coherent snapshot CLI; before-work and after-all-jobs epochs; `summary.csv` untracked, rebuilt on demand; traversal via a latest-row map | ledger-transaction | progress attributed only to events under the task; concurrent job settlement not credited to a packet; measured call counts on packet / acquire / digest / terminal paths; no tracked CSV; 10,000-row transitive walk linear |
| `kb::error-query-attempts` | 1 | error `query` with filters; stable attempt ids and explicit pivot events; `crash-triage` consumes them | snapshot-epochs | renamed-task and shared-label cases decided correctly; boundary timestamps; legacy rows |
| `kb::ownership-catalog` | 2 | fact owners, scopes, enforcement labels; source adapters; behavior contract with intended-vs-implemented classification | schema-single-source | duplicate or missing owner rejected; each of the 29 drift obligations mapped to owner + label + test or explicit policy decision |
| `kb::rendered-references` | 2 | marked generated blocks in INDEX / specs / contracts / AGENTS; idempotent; stale value or stale output fails | ownership-catalog | missing marker, incomplete render, hand edit inside a block each fail; rationale outside blocks preserved |
| `kb::skill-facts-pilot` | 2 | typed `facts` and `moments`; the three work skills migrated ≤ 4 KB bodies, Verify code in support files | registry-candidate-binding, ownership-catalog | stale pin, type error, missing required fact rejected; essential steps covered by a named task fixture; opt-in skills untouched |
| `kb::moment-loader-packs` | 2 | (stage, role, event) routes; pack assembler with receipts and byte accounting; `agents.ts` and validator packs use it | skill-facts-pilot, frontier-ownership-repair | coverage and conflict rejection; mandatory closure overflow fails explicitly; both runner paths equivalent; receipt lists revisions and bytes |
| `kb::memory-preservation` | 2 | pre-prune archive; whole-block replacement; run/wave identity; truthful digest cadence, paths, finalization; selected notes tracked | snapshot-epochs, checkpoint-manifest | pruned never-committed text recoverable; generated block intact; restart keeps history; halt emits a final digest; consumer-shaped ignore fixture commits the notes |
| `kb::skills-migration-retrieval` | 2 | remaining 30 skills migrated; harvest atomic with its own commit; dependents invalidated on symbol change; local retrieval index | moment-loader-packs, memory-preservation | partial-harvest and halt-before-commit cases; three lookup questions answered with sources; overlap flagged |
| `kb::transaction-log-projection` | 3 | B: archives + genesis, envelopes, projection, pinned reads, parity, cutover | identity-revisions, checkpoint-manifest, settlement-validity | absent / stale / fresh parity under one admission rule set; concurrent writer + reader; crash and lock order; rebuild reproduces effective validity; adoption gate measured |

Stage 0 = 4 nodes (+ the frontier node once identity lands), stage 1 = 9,
stage 2 = 6, stage 3 = 1 umbrella (G-D's B1–B12 inside it). "Each node one
commit" holds for stages 0–2; several stage-1 nodes are multi-day.

## 7. Risks

- Lock semantics: advisory locks do not cover NFS or non-cooperating writers; blocking acquisition inside verifiers can deadlock — verify outside the critical section.
- Supersession without a data model breaks promotions and idempotent batches; the per-ledger comparison must be complete (assumptions, evidence, scope, kind).
- Obligation-aware readiness without runnable repair jobs deadlocks a mission.
- Generated prose that blesses a bug as policy: the behavior contract must label intended vs implemented before any rendering.
- Evidence retention vs the no-large-datasets policy: an aggregate budget and external retention with digests, not a per-file cap alone.
- Skill bloat and rigid routing: the pilot's ≤ 4 KB bodies and explicit conditional additions are the controls.
- B's index divergence: build and read under the same lock discipline; never a second commit path.

## 8. Open questions for the owner

1. Is this the "knowledgebase" you meant, or specifically the knowledge ledger and its DAG?
2. Stage 0 changes runtime semantics: which obligations block readiness (prerequisites) vs create repair work vs block closure? Should `blocking: false` ever block?
3. Should support demotion / refutation demote dependents automatically (a gate) or be reported first?
4. Who authors verifiers: registered per task file by the decomposer, or proposed by the worker and approved by the validator?
5. Track mission notes in git (un-ignore `progress/<mission>/`) or move them to a durable home?
6. Evidence retention: aggregate budget in git, and what external store for overflow?
7. B trigger: correctness-driven (G-D) or measured after A (R1/R2)?
8. Retire the unwired Python `loop_gate.py` now, or keep it as a compatibility CLI?
9. Should the validator be wired into the mission loop (production contract), given that today no admitted result in a real mission passes through it?

## 9. Evidence appendix

Fresh-repo scaling (each N a separate throwaway repo; [R2] independent
measurement; ms; the first draft's table came from a cumulative fixture whose
labels 100/500/2000 meant 100/601/2602 rows — corrected here, script fixed):

| N | knowledge append | query | transitive predecessors | trial append |
|---|---|---|---|---|
| 100 | 6.2 | 0.4 | 1.1 | 5.2 |
| 500 | 13.8 | 1.8 | 20.9 | 15.7 |
| 2,000 | 40.1 | 7.0 | 315.4 | 50.9 |
| 10,000 | 206.0 | 42.9 | 8,203.6 | 258.4 |

Author's rerun with the corrected `notes/kb_redesign/scale.py`: see §9.1.
Append profile at ~2,000 rows: CSV regeneration 57 % [A] / 74 % [R2];
bare interpreter start-up ≈ 21 ms, empty CLI query ≈ 56 ms, CLI query at
10,000 rows ≈ 215 ms [R2]. G-D wide/chain fixtures at 5,000 rows: query 25 ms,
DAG merge 73–78 ms, dashboard 235–260 ms, chain transitive 2,109 ms; real
sequential admission of 5,000 rows 285.6 s; 5,000 rich rows = 23.1 MB query
output > 16 MiB bridge cap.

Concurrency (`concurrent.py`): 4 × 25 appends → chain broken 3/3 for [A]
(`break_at` 5, 1, 18), [R1] (1, 6, 2), [R2] (3, 4, 4; 72–81 distinct
`node_seq`); external exclusive `flock` control → valid, 0.44 s [R2].

Demonstrations (`gaps.py`; held for [A], [R1], [R2]): cross-paper readiness;
same-id replacement; tail deletion vs middle deletion; orphan trial anchor.
Spot-checked by [A] from the GPT-6 memos: solid self-loop admitted; refuted
result discharges a fresh obligation; append accepted on a broken chain.

Context and prose [G-K]: authored prose 368,197 B in 51 files vs 315,216 B
of owners; skills 237,277 B (64 % of prose); Verify sections 40,414 B (17 %);
session start 6,733 B, with briefing 18,335 B; briefing alone 11,601 B; median
skill 7,722 B; three work skills 27,998 B; one-node worker with required reads
22,673 B (SDK) / 35,187 B (CLI); with the three skills 50,671 / 63,185 B;
validator `ALWAYS_PACKED` 12,783 B. Registry census [R2]: 154 assertion
sites in first Verify blocks — 12 equality-to-constant (5 skills), 66 runtime
behavior, 56 source-text, 20 file/path.

Host: SQLite 3.45.1 with FTS5 and JSON1; Python 3.12.3; Node 18.19.1.

### 9.1 Author's fresh-repo rerun

`python3 notes/kb_redesign/scale.py 100 500 2000 5000`, each N a fresh
repo, chains verified after every run (ms):

| N | knowledge append | query | transitive predecessors | trial append | nodes.jsonl |
|---|---|---|---|---|---|
| 100 | 4.5 | 0.5 | 1.3 | 4.8 | 39 KB |
| 500 | 13.0 | 1.8 | 19.5 | 13.7 | 193 KB |
| 2,000 | 36.8 | 6.6 | 330.8 | 46.0 | 777 KB |
| 5,000 | 94.7 | 18.9 | 2,110.5 | 123.8 | 1,949 KB |

Agrees with [R2] within 10 % and with [G-D]'s 2,109 ms chain traversal at
5,000; the transitive walk is quadratic, appends and queries linear.

## 10. Refutation record

**R1 — fresh-context Claude reviewer (read-only, `/tmp/kb-refute/`).** ADMIT
WITH AMENDMENTS. Reproduced the scaling trend and all four demonstrations;
found P11 (writer races), P12, P13, P14, P15, P16; downgraded P1, P4, P8;
corrected P6's root cause; withdrew the first draft's "index rebuilt on head
mismatch is never a second truth"; changed the recommendation from "B + K" to
"A + locking + consolidation now, B threshold-gated". All eight amendments
applied in version 2.

**G-D — GPT-6 data-model analysis (independent, note unseen).** Twelve
ranked problems, of which P17, P18, P19, P20, P21, P22, P24, P25, P27 were new
to the note; recommends emergency A then staged B (accepted-transaction log +
SQLite projection) on correctness grounds; 12-node B DAG, 27–44 person-days;
C 37–59 days.

**G-K — GPT-6 agent-knowledge analysis (independent, note unseen).** Measured
ownership and context costs; found the registry's first-block and
candidate-binding holes (P30) and the unadmitted-discovery path; classified
the 29 drift obligations (9 copied literals, 8 over-claimed guarantees, 6
divergent contracts, 6 imprecise CLI descriptions); recommends ownership +
generated references, then skills as the procedural unit with fact pins,
moment routing, packs, receipts; a knowledge graph not justified; 13-node
K01–K13 DAG. Adopted as K-A … K-D.

**R2 — GPT-6 refutation of version 2 (`notes/kb_redesign/reviews/gpt6-refutation.md`).**
ADMIT WITH AMENDMENTS. Reproduced everything; found the scaling fixture
mislabeled; confirmed P11; downgraded P1 (T), P2 (D/T standalone), P8, P10,
P14; upgraded P3, P4, P5, P7, P12, P13, P15; added P23 (readiness deadlock),
P26 (validator binding, pack containment, disposable provenance), P28, P29,
the harvest / commit disagreement, no-Verify promotion, evidence-budget and
consumer-migration gaps, Mermaid id collision; audited all fifteen verifiers
as non-discriminating and re-ordered dependencies. Its twelve amendments are
applied: §2 and §9 corrected, G0/G1/G2/G4/G7/G9 rewritten, §6 rebuilt with
discriminators and corrected edges, B's triggers labeled provisional, K
narrowed to what facts can check.

**Disagreement retained.** G-D: B on correctness grounds; R1/R2: measure after
A. Recorded in §5 and §8 Q7 for the owner.

## 11. Implementation status (2026-09-10)

Stage 0 of §6 is implemented on branch `GUI`, each node by a GPT-6 (gpt-6-astra,
effort max) worker under a test-first contract, verified alone in an isolated
worktree at HEAD, landed as its own revertible commit, promoted through the gate
with its test suite executed at append, and its obligations discharged:

| node | commits | new tests | obligations discharged |
|---|---|---|---|
| `kb::validator-binding` | 9e99de9 (+ docs 58c5d00) | 24 | kb-validator-submission-binding |
| `kb::integrity-before-decisions` | 2b6bbbc (+ docs 78f8604) | 25 | kb-integrity-before-decisions, kb-claims-fail-loud |
| `kb::ledger-transaction` | 3a7fa39 (+ docs f12ace4) | 53 | kb-ledger-lock |
| `kb::registry-candidate-binding` | 3c69d55 (seven skills), d39ee93 (registry, receipts) (+ docs 3882e84) | 32 | kb-registry-candidate-binding, kb-registry-first-block-only, kb-registry-unadmitted-discovery |

Consequences for §2: P11, P17 (within one repository lock), P15, P24, P26, and
P30 are closed on this branch; `notes/kb_redesign/concurrent.py` now passes
(3/3). Suites after stage 0: pytest 297, orchestrator 128, skills 33/33
admitted. Still open: the frontier node (`kb::frontier-ownership-repair`,
ordered after `kb::identity-revisions`), and everything in stages 1–3; 45
obligations remain, one blocking (`kb-frontier-crosspaper-obligations`).
