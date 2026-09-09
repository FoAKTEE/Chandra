# Agent-facing knowledge: measured audit and migration proposal

Read-only audit of branch `GUI`, commit `ac08dc7180b27eae999a040f3021a18c7e9456fc`, on 2026-09-09. Repository files were not changed. Measurements, isolated test copies, and probes are under `/tmp/chandra/kb-analysis/agent/`. No network was used. The competing analysis paths and `kb-*` claim contents were excluded.

The main defect is missing ownership and dependency tracking between executable behavior, instructions, and the material a particular agent actually receives. Chandra already generates useful schema references and verifies many operations, but most agent instructions remain independently editable copies. Recommend **A first, followed by a bounded B**: establish fact ownership and generated references, then make skills the procedural entry point and assemble context by moment and role. A ledger knowledge graph is unnecessary for the measured problem today.

## 1 Inventory + measurements

All sizes below are UTF-8 bytes. Lines count physical lines, including a final unterminated line. Whole-file totals describe the inspected corpus; they are not estimates of how many bytes are redundant.

| Corpus | Files | Lines | Bytes | Interpretation |
|---|---:|---:|---:|---|
| Implementation/configuration owners | 41 | 7,116 | 315,216 | Ledger/loop/registry Python, manifest and wrappers, runtime TypeScript, hooks/configuration; includes comments and render templates |
| Authored agent-facing prose | 51 | 6,124 | 368,197 | Requested documents and 33 skills, plus runtime README |
| Generated skills index on disk | 1 | 42 | 12,198 | Generated from skill frontmatter; regenerated output matches the checked-in file |
| Within authored prose: 33 skills | 33 | 4,036 | 237,277 | 64.4% of the authored corpus |
| Within Python owners: uppercase declaration/reference assignments | 105 spans | 680 | 39,715 | Enums, field/reference tables, constants, and templates; AST-selected |
| Within Python owners: CLI/manifest functions | 9 spans | 663 | 33,755 | `main`, parser builders, and `manifest`; includes dispatch code |
| Within Python owners: module docstrings | 20 spans | 383 | 20,838 | Prose inside code is another maintenance surface |

The last four rows are subsets, not additional corpus totals. A closer, manually annotated audit of the eight requested facts found **382 fact-bearing prose lines / 31,507 bytes across 31 files**, against **77 owner/definition lines / 3,669 bytes**. The prose spans include surrounding explanations; 31,507 is a targeted measurement of factual reference material, not an exact removable-byte count. It covers 8.6% of the authored corpus without attempting to classify every sentence. Prompt instructions, source docstrings, generated templates, and test assertions are separately accounted for in §6.

| Artifact class | What it contains; readers and timing | How it is kept true; restatement exposure |
|---|---|---|
| `alignment.md` — 47 lines / 2,402 B | Admission invariant, evidence discipline, stall/acquire, source handling, context and delegation; launching session at startup, workers/validators when instructed | Hand-edited policy pointing at enforcement. Kernel plus admission contract are injected by the hook. Roles, gates, and thresholds also appear in contracts, skills, and prompts |
| `AGENTS.md` — 50 / 2,888 | Cross-client entry order, ledger/verification/commit/skill rules; compatible clients at startup, other agents on demand | Hand-edited; loading tests check mentions and resolvable paths, not semantic agreement. Repeats kernel and governance rules |
| Five `_common/contracts/*.md` — 518 / 30,717 | Admission record, markers, note discipline, progress and commit grammar; admission contract at startup, others at relevant stages | Hand-edited. Ledger validation and commit hook enforce portions; prose policy and executable behavior are not systematically distinguished |
| Root `INDEX.md` — 80 / 7,623 | Repo map, stage/job table, authority rule; orientation and dispute resolution | Hand-edited despite the separately generated skills index. Restates paths, roles, cadence, gate behavior, and workflow |
| Root, common, runtime READMEs — 423 / 20,990 | Human orientation, CLI/package map, runtime operation; setup and on-demand lookups | Hand-edited. Tests exercise implementations, not all tables and explanatory claims |
| Four pipeline specs — 370 / 21,093 | Stage inputs, outputs, readiness, work/validation/writing procedure; stage workers; work spec also always packed for validators | Hand-edited workflow contracts; overlap with job prompts and corresponding skills. Stage 2 result statuses repeat admission/schema truth |
| `pipelines/2-work/template.md` — 174 / 7,878 | Per-node task scaffold, fields, verification and closure instructions; packet workers and task preparation | Hand-edited template; concrete task evidence can be checked, but template semantics are not generated from CLI/schema owners |
| Tracking template — 129 / 9,588 | Three timescales, required note sections, state scaffold, ledger paths; observer/note maintenance | Hand-edited; repeats runtime cap/cadence/layout and asks for generated result blocks to be pasted manually |
| `notes/pua_skill.md` — 297 / 27,741 | Optional motivational procedure; explicit opt-in only | Authored rationale/procedure. The corresponding skill summarizes and references it. This is mostly procedural prose, not enum duplication; size alone is not a reason to inject or mechanize it |
| 33 `SKILL.md` files — 4,036 / 237,277 | Trigger descriptions, procedural steps, references, examples, Verify commands; selected on demand per task/moment | Author-generated, then registry-admitted. Frontmatter drives the generated index/briefing. Most bodies remain independently authored copies of specs, CLIs, schemas and policy |
| Registry — 640 / 27,127 | `validate`, `render-index`, `briefing`, `new`, `promote`, `harvest`; authoring and per-wave promotion | Structural/path checks plus an optional executed Verify block; no fact ownership, role-stage routing, semantic reference graph, or candidate-content binding guarantee |
| Runtime prompts and packs | Worker/job instructions per packet/job; refuter/judge context per candidate; skill suggestion after each worker/job | Handwritten TypeScript string templates and file lists. Runtime tests check particular strings/behaviors; prompts are not assembled from admitted skill sections |
| Mission notes and digest | Current-wave snapshot, last-ten-wave snapshot, long-memory narrative, periodic human summary | Two notes and digest are generated; research state is scaffolded, then only capped/pruned by the observer. There is no live `progress/` tree in this checkout, so actual mission sizes cannot be measured |
| Runtime journal and packet WAL | Scheduling/outcomes/verdict fragments per event; trial scratch per trial and compaction recovery | Journal has typed runtime events. WAL is an instructed worker convention, outside admission until flush. Both default to runtime storage outside the repository; they are not interchangeable with durable research records |

The startup wiring is explicit in [.claude/settings.json:9](/data/haiyangw/harness/Chandra/.claude/settings.json:9) and [inject_infra.sh:41](/data/haiyangw/harness/Chandra/.claude/inject_infra.sh:41). The loading tests establish presence and path validity at [test_skill_loading.py:33](/data/haiyangw/harness/Chandra/tests/test_skill_loading.py:33), not whether different clients receive equivalent instructions.

### How many places state the same facts?

Counting unit: **distinct files with an explicit declaration or operative instruction** in the bounded audit corpus. Bare links, isolated example values, and ordinary symbol uses do not count as complete statements. Partial statements count separately: a three-domain list, one ledger path, or one role-policy facet still creates maintenance work. These are audited statement counts, not counts of regex hits. Multiple statements within one file count once here; their spans remain in the appendix artifacts.

| Fact | Authored declaring files | Literal owners/mirrors or live instruction | Other generated statement |
|---|---:|---|---|
| `DOMAINS` | 6: 5 full lists, 1 incomplete | 3 Python tuples; manifest derives from one | Manifest/schema outputs derive lists |
| Result status enum | 7: 5 full lists, 2 subsets | 1 tuple; field-description string separately restates it | Manifest/schema outputs derive list |
| On-disk ledger layout | 12: 4 complete layouts, 8 subsets | Resolver, manifest and four ledger filename owners: 6 files | 3 generator files contain stale path literals; these are not owner-derived |
| Packet/WAL contract | 9: 2 complete procedures, 7 facets | 1 complete prompt contract; scheduler/batch code enforce only portions | Skills index adds 1 partial statement |
| Commit grammar | 3 complete descriptions | 1 hook owns executable title/body rules | No owner-derived document rendering |
| Research-state cap | 6 | 2 independent literals: manifest and observer | Skills index adds 1 statement; scaffold interpolates observer constant |
| Five-iteration paper cadence | 5 | 1 Python constant plus behavior function | Manifest derives it; skills index adds 1 statement |
| Role policy | 19: 5 full strict/roles/stamp descriptions, 14 facets | Admission policy/check and TypeScript role declaration in 2 owner files | Manifest derives admission constants |

Representative sources: `DOMAINS` at [error_database.py:83](/data/haiyangw/harness/Chandra/_common/ledgers/error_database.py:83), [knowledge_database.py:96](/data/haiyangw/harness/Chandra/_common/ledgers/knowledge_database.py:96), and [loop_policy.py:65](/data/haiyangw/harness/Chandra/_common/loop/loop_policy.py:65); statuses at [result_database.py:40](/data/haiyangw/harness/Chandra/_common/ledgers/result_database.py:40); path resolution at [ledger_common.py:52](/data/haiyangw/harness/Chandra/_common/ledgers/ledger_common.py:52); role enforcement at [admission.py:65](/data/haiyangw/harness/Chandra/_common/ledgers/admission.py:65).

The eight labels are not all single scalar facts. “Packet contract” and “role policy” are bundles. Their complete/partial distinction matters more than a combined total. Generated copies are harmless when derived from the right owner; generation from stale literals merely reproduces drift reliably.

### Context cost

The worker fixture is `paper=self`, wave 1, `self::n1`, summary `Verify contract node 1.`, no predecessor, obligation or steer. A second fixture extends this into four nodes. These are reproducible measurements of actual prompt builders, not averages from production transcripts.

| Payload or read path | Bytes |
|---|---:|
| Raw kernel + admission contract | 6,092 |
| Actual default SessionStart hook, including wrappers and pointers | 6,733 |
| Standalone 33-skill briefing | 11,601 |
| Hook with `--with-skills` | 18,335 |
| Generated skills index | 12,198 |
| Typical skill: median / mean | 7,722 / 7,190.2 |
| Smallest / largest skill | 2,722 / 12,128 |
| Three median-sized skills, arithmetic allowance | 23,166 |
| Actual work-packet + error-trial + result-admit skills | 27,998 |
| One-node worker prompt: SDK / CLI including preamble | 2,012 / 2,328 |
| Four-node worker prompt: SDK / CLI | 2,231 / 2,547 |
| Required stage-2 documents, read once each | 20,661 |
| One-node worker + required reads: SDK / CLI plus index | 22,673 / 35,187 |
| Same worker after loading the actual three skills: SDK / CLI | 50,671 / 63,185 |
| Validator `ALWAYS_PACKED` document bytes | 12,783 |

The CLI preamble itself is 316 B. The CLI total includes the index because its preamble explicitly requests it; the SDK path does not do so. These totals exclude client system prompts, tool schemas, `AGENTS.md` automatic loading, additional referenced documents, mission evidence, tool results and repeated reads. A client that additionally loads `AGENTS.md` adds 2,888 B; actual native skill-discovery overhead cannot be established from this repository alone. Validator totals exclude `CLAIM.md`, evidence, manifest and refuter/judge prompts.

Verify sections alone occupy **869 lines / 40,414 B**, 17.0% of skill bytes. Keeping executable verifier implementations in referenced support files, with a short invocation in the skill, can reduce procedural reading without weakening verification. The four code-quality skills already query live policy bundles, a useful pattern to retain.

The measured growth comes from requested reads, not packet length: adding three more short node descriptions costs 219 B, while three relevant skills cost 27,998 B. The existing manifest is only 2,946 B and all four generated schema summaries total 3,488 B; they are useful reference primitives, but do not contain the procedures needed to replace entire skills.

## 2 Diagnosis — ranked causes with evidence

### 1. Admission checks a document's shape and arbitrary verifier, not its factual dependencies or necessarily its own candidate content

The registry checks frontmatter, path existence and a shell command. It has no typed connection from a sentence such as “allowed statuses are …” to `result_database.STATUSES`. Unknown frontmatter keys are warnings, so adding an unimplemented `facts` block would not establish verification. [skill_registry.py:315](/data/haiyangw/harness/Chandra/_common/skills/skill_registry.py:315)

All 33 shipped skills currently declare Verify sections. The registry nevertheless permits the following cases; independent scratch probes made the gap concrete:

- A skill with a false status assertion and no Verify section passes `validate(execute=True)`.
- A Verify section containing a first block `true` and a second block `exit 1` passes: `verify_block` selects the first fenced block. [skill_registry.py:249](/data/haiyangw/harness/Chandra/_common/skills/skill_registry.py:249)
- A candidate copy of `ledger-result-admit` with `status="impossible_status"` passes registry execution, although the result validator rejects that same example. Its Verify block reads the installed skill by repository path, rather than the candidate directory supplied in `CLAUDE_SKILL_DIR`. [ledger-result-admit/SKILL.md:128](/data/haiyangw/harness/Chandra/.claude/skills/ledger-result-admit/SKILL.md:128)

Promotion runs this verifier before copying the candidate. Therefore even a substantive verifier can certify a different document from the one about to land. Admission is checking the wrong input in this case; many existing skill checks are substantive. [skill_registry.py:480](/data/haiyangw/harness/Chandra/_common/skills/skill_registry.py:480)

Seven skill verifiers contain installed-self references, so candidate binding needs a registry-wide regression check. Discovery is also not an admitted-only view: `new` defaults into `.claude/skills/`, and `list_skills` discovers directories without an admission receipt. A new scaffold can become visible before promotion. [skill_registry.py:457](/data/haiyangw/harness/Chandra/_common/skills/skill_registry.py:457), [skill_registry.py:372](/data/haiyangw/harness/Chandra/_common/skills/skill_registry.py:372)

### 2. Authority is assigned to files, while facts have several independently editable owners

Root `INDEX.md` calls itself both the canonical index and workflow contract and says it wins disagreements. `AGENTS.md` directs readers to the skills index, then uses the unqualified name `INDEX.md` as the authority. This makes discovery and normative authority depend on interpretation of file names, rather than stable fact IDs. [INDEX.md:5](/data/haiyangw/harness/Chandra/INDEX.md:5), [AGENTS.md:15](/data/haiyangw/harness/Chandra/AGENTS.md:15)

The existing manifest is a useful start, but is not uniformly derived: it imports result/knowledge constants, yet spells out the state cap and ledger filenames itself. The observer independently declares `10240`. Current conformance tests compare selected mirrored constants; they do not generate all consumers or bind explanatory prose. [contract.py:25](/data/haiyangw/harness/Chandra/_common/contract.py:25), [contract.py:71](/data/haiyangw/harness/Chandra/_common/contract.py:71), [contract.test.ts:27](/data/haiyangw/harness/Chandra/orchestrator/test/contract.test.ts:27)

Code-owned prose also drifts: the knowledge module announces that its docstring/CLI is the complete spec, then describes appends using the legacy path. The live resolver chooses the canonical layout unless only the legacy directory exists. A `.py` extension does not make its prose derived. [knowledge_database.py:4](/data/haiyangw/harness/Chandra/_common/ledgers/knowledge_database.py:4), [knowledge_database.py:37](/data/haiyangw/harness/Chandra/_common/ledgers/knowledge_database.py:37)

### 3. “Mechanically enforced” combines executable behavior, instructions, and aspirations

The progress contract describes one gate pass and one commit per packet. The batch implementation actually gates each row sequentially, may leave an admitted prefix on failure, and regenerates summaries at the end; the runtime commits by wave. These are different units of work, admission and persistence. [progress_principles.md:12](/data/haiyangw/harness/Chandra/_common/contracts/progress_principles.md:12), [result_database.py:159](/data/haiyangw/harness/Chandra/_common/ledgers/result_database.py:159), [gitops.ts:40](/data/haiyangw/harness/Chandra/orchestrator/src/gitops.ts:40)

Likewise, readiness is not the whole stage contract. `readyFrontier` checks that a node is non-solid, is not on/behind a cycle, and has solid predecessors. It does not check `openObligations`, although `buildMission` collects them. This memo does not decide whether that policy should change; it shows why “readiness” needs an explicit, tested behavioral definition. [dag.ts:31](/data/haiyangw/harness/Chandra/orchestrator/src/dag.ts:31), [dag.ts:63](/data/haiyangw/harness/Chandra/orchestrator/src/dag.ts:63)

The five-iteration paper cadence uses the maximum error-ledger iteration and either elapsed iterations since generation or a modular check. The five-window digest uses journaled `windowsUsed`. Equal numbers do not make these the same cadence. [loop_policy.py:299](/data/haiyangw/harness/Chandra/_common/loop/loop_policy.py:299), [digest.ts:14](/data/haiyangw/harness/Chandra/orchestrator/src/digest.ts:14)

### 4. Knowledge delivery has no shared, versioned assembly boundary

Worker prompts say “your context pack” but provide filenames and a “do not roam” instruction. The SDK receives repository-wide tools and `settingSources: []`; the CLI adds its own index-loading preamble. There is no common implementation that selects and supplies the relevant skill bodies. The current mechanism is agent interpretation of descriptions, not a repository-implemented keyword matcher. Neither `workerPrompt` nor `jobPrompt` directly supplies or requests the three mission notes, journal or prior trial history; producing those memories does not establish a handoff to the next worker. [agents.ts:13](/data/haiyangw/harness/Chandra/orchestrator/src/agents.ts:13), [agents.ts:39](/data/haiyangw/harness/Chandra/orchestrator/src/agents.ts:39), [agents.ts:81](/data/haiyangw/harness/Chandra/orchestrator/src/agents.ts:81)

Validators have a stronger mechanism: an allowlisted, hashed directory. But `ALWAYS_PACKED` still hardcodes whole documents instead of selecting the validation procedure and required facts from the same knowledge system. Its copied-file manifest identifies bytes, not the rule versions the claim was judged under. The code correctly warns that `cwd` alone is not filesystem isolation. [validator.ts:3](/data/haiyangw/harness/Chandra/orchestrator/src/validator.ts:3), [validator.ts:99](/data/haiyangw/harness/Chandra/orchestrator/src/validator.ts:99)

### 5. The three-note hierarchy mixes useful views with unsupported durability and freshness promises

The intended hierarchy repeats the same underlying state at several resolutions: the iteration note asks for trial/result summaries; the nodal note asks for DAG status, accepted results and failure-mode changes; research state carries active claims, accepted results and next work. The digest independently reads ledgers and repeats recent-wave totals. These are sensible *views* if they share sources and watermarks; they become competing memories when an agent must manually synchronize them. [multi_timescale_tracking_template.md:40](/data/haiyangw/harness/Chandra/notes/multi_timescale_tracking_template.md:40), [multi_timescale_tracking_template.md:89](/data/haiyangw/harness/Chandra/notes/multi_timescale_tracking_template.md:89), [digest.ts:36](/data/haiyangw/harness/Chandra/orchestrator/src/digest.ts:36)

The actual observer rewrites iteration and nodal notes every wave, creates a research-state scaffold if absent, and prunes over-cap text. It does not refresh accepted results or implement all the template's required sections. The nodal snapshot is a window of journal counters, not the richer research synthesis the template specifies. [observer.ts:104](/data/haiyangw/harness/Chandra/orchestrator/src/observer.ts:104), [observer.ts:170](/data/haiyangw/harness/Chandra/orchestrator/src/observer.ts:170)

The durability contradiction is concrete in this checkout: `notesLayout` writes under `progress/`, `.gitignore` ignores that tree, and the wave committer uses ordinary `git add -A`. No progress files are tracked here. The truncator nevertheless writes “full text in git history.” Even tracking a note would not preserve newly added text pruned before its first commit. [observer.ts:24](/data/haiyangw/harness/Chandra/orchestrator/src/observer.ts:24), [observer.ts:52](/data/haiyangw/harness/Chandra/orchestrator/src/observer.ts:52), [.gitignore:13](/data/haiyangw/harness/Chandra/.gitignore:13)

Tests currently assert the recovery phrase and byte cap, while the mission fixture does not copy the real `.gitignore`. Thus a green suite does not prove recovery of discarded narrative. The generated scaffold also points to legacy ledger locations, and the digest points to a journal under `progress/` although runtime storage is elsewhere. [observer.test.ts:65](/data/haiyangw/harness/Chandra/orchestrator/test/observer.test.ts:65), [mission.test.ts:33](/data/haiyangw/harness/Chandra/orchestrator/test/mission.test.ts:33), [observer.ts:148](/data/haiyangw/harness/Chandra/orchestrator/src/observer.ts:148), [digest.ts:61](/data/haiyangw/harness/Chandra/orchestrator/src/digest.ts:61)

### 6. Procedure discovery has become another replication step

All 33 skills were read. Writing a skill forces an author to turn scattered instructions into runnable steps and examples, crossing the boundary between spec and implementation. That is why skill-writing exposed the existing disagreements: it acted as a manual integration audit. The registry then preserves the procedure but does not record its semantic dependencies, so later changes can invalidate it silently.

The 29 `drift-*` obligations were filtered and read as symptoms, not adopted as this memo's findings. All are unique, open obligations dated 2026-09-09. An exclusive classification of their reported symptoms is:

| Reported symptom class | Obligations |
|---|---:|
| Copied literals or relocated/renamed knowledge | 9 |
| Claimed guarantees beyond implemented enforcement | 8 |
| Divergent lifecycle, ownership or integration contracts | 6 |
| Imprecise CLI/query behavior descriptions | 6 |

This partition describes the existing reports, not an independently measured defect rate. Their contents and ID partition were filtered before review; [drift-symptoms.json](/tmp/chandra/kb-analysis/agent/docs/drift-symptoms.json) records the classification. The independent examples above are supported by source traces and scratch probes rather than by treating these obligations as proof.

Per-wave harvesting promotes validated drafts and refreshes the index, but does not identify overlapping procedures, establish fact ownership, or invalidate existing skills when their source symbols change. Trigger descriptions also become always-listed material, so each added skill increases discovery cost. [agents.ts:21](/data/haiyangw/harness/Chandra/orchestrator/src/agents.ts:21), [skills.ts:22](/data/haiyangw/harness/Chandra/orchestrator/src/skills.ts:22), [skill_registry.py:417](/data/haiyangw/harness/Chandra/_common/skills/skill_registry.py:417)

### What an agent cannot obtain directly today

| Question | What exists | Missing access path |
|---|---|---|
| “Which failure_mode did the last worker use for X?” | Error rows and domain tag descriptions; `crash-triage --paper P --task T` exposes recent failure modes when the task is known | Error CLI has no general query subcommand; runtime `Ledgers` exposes knowledge/results/claims, not trials. Worker reports have no stable session/trial join. A known task can be recovered by lower-level reads; an arbitrary concept or exact prior worker cannot be resolved reliably |
| “What does readiness actually check?” | Executable predicates in `dag.ts` and `jobs.ts`, plus tests | No generated explanation returning predicates, their observed inputs, failure reasons and policy gaps for this node/job |
| “Which skill covers this moment?” | A helpful handwritten moment list in `chandra-orient` and generated descriptions | No executable stage × role × event routing table, coverage check or consistent loader across runners |
| “What did the prior validator see and why admit?” | Pack file hashes during validation; a journal verdict with a truncated refutation | Temporary packs are deleted; the journal keeps only the first 500 refutation characters and not admitted-verdict reasons. Replay needs durable references and rule/source revisions |
| “Which memory is current and recoverable?” | Ledger chains, generated views, notes, runtime journal and WAL | No unified source watermark/receipt tying the delivered context to ledger revisions, journal position, procedure versions and preserved narrative |

Sources: [error_database.py:657](/data/haiyangw/harness/Chandra/_common/ledgers/error_database.py:657), [ledger.ts:48](/data/haiyangw/harness/Chandra/orchestrator/src/ledger.ts:48), [types.ts:68](/data/haiyangw/harness/Chandra/orchestrator/src/types.ts:68), [chandra-orient/SKILL.md:35](/data/haiyangw/harness/Chandra/.claude/skills/chandra-orient/SKILL.md:35), [validator.ts:175](/data/haiyangw/harness/Chandra/orchestrator/src/validator.ts:175).

## 3 Designs A / B / C

All three need the same distinction: **implemented behavior, intended policy, and explanatory rationale are different things**. Do not generate documentation that silently blesses a bug as policy. Each operational fact needs one owner, an applicability/version scope, an enforcement label, and a verifier where executable. A disagreement between intended policy and current behavior stays visible until resolved.

“Drift becomes impossible” below means **a stale covered assertion cannot pass the proposed gate**. No schema can establish the truth of unrestricted scientific prose or compensate for an incorrect oracle.

### A — Contract-driven documents

Grow `_common/contract.py` into a manifest facade over authoritative schema and behavior definitions. It should expose stable IDs, value/type/unit, source symbol, applicability, enforcement level, verifier and source revision. Existing executable constants remain owned once in code; consumers import them or consume generated artifacts. Facts currently owned only by policy receive one declarative policy owner. Do not make the manifest another handwritten copy of every enum.

Generate root INDEX reference sections, CLI/spec tables, contract reference blocks, skill references and the operational rules in `AGENTS.md`. Include generated-block boundaries and source IDs. Derive CLI inventories from actual parser definitions and ledger paths from the actual resolver, including legacy fallback. A behavior catalog records cases such as readiness with open obligations, partial batch failure, strict roles and pre-prune persistence; its generated tables distinguish enforcement from instruction.

- **Prevented drift:** covered enums, flags, paths, role sets, units/cadences, grammar and declared behavior tables cannot change independently of their sources. Tests reject stale renderings and changes to source behavior without corresponding behavioral expectations.
- **Remaining prose:** rationale, examples of reasoning, scientific judgment, explanations of policy tradeoffs and document composition. Their factual reference sections are generated. New operational assertions must register a fact rather than become a second authority.
- **Context cost:** generation alone gives no reliable saving. Budget against today's 6,733 B startup hook, 18,335 B startup with full briefing, and 50,671/63,185 B read-inclusive worker examples. Generated documentation could be larger; track its size before rollout.
- **Migration:** assign owners → extract schema/CLI/layout → bind behavioral cases → render managed blocks and drift-test. Keep existing skill names and entry paths during this phase.
- **Effort:** 4 initial nodes, K01–K04 below. Verifiers include ownership uniqueness, behavior fixtures, parser/schema parity and stale-render mutation rejection.
- **Risks:** unreadable generated prose, confusing code behavior with intended policy, and an oversized central manifest. Keep hand-designed sentence/table templates and domain-specific owners; require human review of generated diffs.

### B — Skills as the primary procedural unit

Each procedure has one owning skill. Stage specs retain rationale, design constraints and historical tradeoffs; their operational tables link to generated skill/fact views. Skills declare machine-checked `facts` records with `fact`, `source_symbol`, and `expected_value`, plus explicit stage/role/event applicability and dependencies. The expected value is a generated, reviewed revision pin—not an independently maintained truth.

For example, a `result.statuses` fact references `_common.ledgers.result_database:STATUSES`; the registry checks the exact candidate's block against that symbol and renders its status reference. A missing source, changed value, contradictory procedure dependency or absent required verifier rejects promotion. Candidate examples are read through the supplied skill directory, and the admission receipt records hashes of the candidate, source facts and verification inputs. Drafts remain outside discovery until admitted.

A deterministic loader maps `(stage, role, event)` to a small skill set, with explicit conditional additions for stalls, validation, commits and writing. It preserves explicit-only procedures such as `pua`. The same loader assembles worker, job and validator packs; it removes repeated kernel/fact sections and records selected IDs, revisions and sizes. Natural-language search remains a fallback for discovery, not the only routing policy.

- **Prevented drift:** stale fact pins, validating installed text instead of a candidate, missing stage/role coverage, forgotten manual moment-index updates, and mixed procedure/fact revisions in a pack fail the gate. Procedure correctness still needs meaningful tests and review.
- **Remaining prose:** the owning procedure's decisions and explanations, domain reasoning, examples and rationale. Operational facts are rendered from checked blocks; another skill references the owning procedure instead of copying it.
- **Context target, not a measurement:** session ≤8,192 B = 6,144 B shared kernel/admission content + 2,048 B routing/help. Worker ≤19,456 B of reusable knowledge = 6,144 B shared rules + 1,024 B selection/provenance + three ≤4,096 B procedural bodies. Add actual node/mission/evidence data separately; disclose further reads and split oversized procedures instead of silently truncating them.
- **Migration:** A's fact adapters → candidate/fact validation → convert the three measured work skills → migrate remaining operational references → moment matrix → shared pack assembly. Then add watermarked mission views and a local retrieval index. The pilot is a separate decision gate before migrating all remaining skills.
- **Effort:** 9 further nodes K05–K13, 13 including A. Start with the pilot before converting all 33; do not assume every skill needs to fit into three selections for every task.
- **Risks:** long skills merely replace long specs, too many tiny skills increase navigation cost, fact pins become rote updates, or rigid routing misses an unusual task. Keep mandatory rules unconditional, support explicit additions, and test named end-to-end tasks rather than only string matches.

The 19,456 B budget is plausible as a target because the current common documents total 6,092 B, but it is not yet proven: the three pilot skills must retain their essential steps at 12,288 B combined, down from 27,998 B. Measure both the initial pack and total subsequent reads to prevent a cosmetic saving.

### C — Versioned knowledge nodes with ledger-backed retrieval

Create a separate methodology namespace containing versioned `rule`, `procedure`, and `fact` nodes, with stable identity, revision, supersession, applicability, content hash, evidence/verifier and dependency edges. Generate all operational prose from current admitted nodes; keep rationale as authored node payloads. Build a disposable SQLite FTS index over admitted revisions for local agent queries, with scope and revision filters before ranking.

One-source ownership requires a deliberate rule here. Declarative policies can be graph-owned and generate their consumers. Facts about executable behavior must be imported, verified projections of owning code symbols at a specific source revision; the graph must not become a second hand-editable authority over live code. Alternatively, graph-owned enums must generate code one way. Hash chains prove history integrity, not semantic truth.

- **Prevented drift:** editing rendered prose outside its nodes, unresolved/superseded procedure dependencies, and retrieving the wrong default revision can be rejected mechanically. Code-vs-node drift is prevented only with the same source bindings and behavioral checks required by A/B.
- **Remaining prose:** rationale and procedural reasoning as versioned node payloads, plus renderer templates. Free-text payloads remain reviewable claims, not mechanically established truths.
- **Context target:** mandatory session pack ≤8,192 B; worker reusable knowledge ≤20,480 B = B's 19,456 B plus ≤1,024 B graph/citation metadata. Additional retrieval/evidence is metered separately. A graph does not inherently reduce context; loading dependency closure without a budget can increase it sharply.
- **Migration:** bootstrap schema/admission and namespace isolation → import code-backed facts and policy/procedure sources → render views → build/rebuild FTS → assemble pinned packs → migrate active consumers and validate rollback. Preserve source revision and old identities throughout.
- **Effort:** about 15 nodes: 4 for namespace/schema/revisions/admission; 4 for source adapters and rule/procedure import/rendering; 3 for FTS/retrieval/packs; 4 for mission integration, migration, recovery and acceptance. Proposed verifier families: `python3 -m pytest -q tests/test_methodology_graph.py`, `tests/test_knowledge_import.py`, `tests/test_knowledge_retrieval.py`, and `tests/test_knowledge_replay.py`, each with rejection, rebuild and revision-isolation cases. These tests do not exist today.
- **Risks:** bootstrap circularity, ledger churn for ordinary documentation edits, conflicts between consumer branches, unbounded graph closure, retrieval ranking that hides mandatory rules, and methodology nodes accidentally counting as research progress. Exclude the namespace from mission scheduling and progress counters. Coordinate graph integration with the separate ledger-layer design before implementation.

C is justified if consumers need independently evolving, queryable historical rule sets or cross-mission procedure reuse that a source-versioned manifest and disposable search index cannot serve. The current measurements establish duplication and delivery problems; they do not establish that requirement.

## 4 Recommendation

Adopt **A → a bounded B**, with a decision point after the three-skill pilot. The 31,507 B of directly identified factual reference spans, the existing 2,946 B manifest, and the existing schema CLIs make A an incremental extension of working mechanisms. The 27,998 B three-skill cost and inconsistent runner loading justify B's routing and packaging work. A graph would still need those mechanisms while adding admission/bootstrap and namespace problems.

Prioritize candidate-content binding and explicit fact ownership before generating more text. Make each context receipt identify the source commit, selected fact/procedure versions, actual bytes supplied, ledger watermark and available evidence references. Store mission interpretation separately from generated state: ledgers own research status, the journal owns scheduling events, and a preserved narrative source owns the mission through-line. Views may repeat these sources, but must not independently author their values.

Use a disposable local search index for discovery and recent-trial lookups before considering graph-owned methodology. Return exact source references and “unknown/not recorded” for missing historical worker joins; do not reconstruct identities from truncated prose. Changes to shared trial/session identifiers should be agreed with the ledger-layer analyst.

I would retain:

- The small always-on kernel and admission invariant; optimize repeated delivery around them.
- The four research ledgers, schema-as-code, gated appends, hash chains and generated research views.
- The three useful timescales and human digest, provided they become reproducible, watermarked views with separately preserved narrative.
- Packet work and the distinction between provisional WAL entries and admitted trials; document actual partial-flush behavior and recovery limits.
- Existing skill names, progressive disclosure, explicit-only optional procedures, and human review of scientific reasoning and policy changes.
- Existing markers and uncertainty discipline; generating references must not hide open obligations or upgrade evidence status.

Acceptance should demonstrate that a changed fact invalidates every dependent generated block, an invalid draft example is rejected before copying, a worker gets the right procedure set without reading the whole index, and a pruned narrative passage can actually be recovered. Passing the existing suites alone is insufficient evidence for those properties.

## 5 Migration DAG

This is a proposed implementation DAG, not work performed by this audit. New verifier commands and test modules below must be implemented with their nodes; a missing test/module must fail, never be skipped. Each command exits zero only when its named assertions pass, including the negative cases specified in the deliverable column. Existing regression suites remain the final backstop. Nodes can be divided further for commit granularity.

| Node | Predecessors | Reviewable deliverable and completion condition | Verifier command |
|---|---|---|---|
| K01 — Ownership | — | Catalog the eight fact families and policy/behavior distinctions; each fact has one owner, scope and enforcement label; duplicate/missing owners rejected | `python3 -m pytest -q tests/test_knowledge_manifest.py::test_ownership_contract` |
| K02 — Source adapters | K01 | Derive domains, statuses, full ledger layout, schemas, CLI inventories and grammar; eliminate independent executable mirrors or generate them; real parser/resolver fixtures agree | `python3 -m pytest -q tests/test_knowledge_manifest.py::test_source_adapters` |
| K03 — Behavior contract | K01 | Executable cases define readiness, role exceptions, paper-vs-digest units, partial batch admission and WAL limits; intended-but-unimplemented rules visibly classified | `python3 -m pytest -q tests/test_knowledge_behavior.py` |
| K04 — Rendered references | K02, K03 | Generate INDEX/spec/contract/AGENTS reference blocks; render deterministically; stale source values and stale outputs both fail | `python3 -m pytest -q tests/test_knowledge_render.py` |
| K05 — Skill admission identity | K02, K03 | Parse/check facts and expected pins; discover only admitted skills; verify exact candidate bytes; reject missing required checks, multiple ambiguous Verify blocks and the invalid-draft regression | `python3 -m pytest -q tests/test_skill_facts.py tests/test_skill_candidate.py` |
| K06 — Three-skill pilot | K04, K05 | Convert work/error/result skills; owning procedures replace duplicate steps; essential-step coverage and ≤4,096 B/body assertions pass; review pilot before broader conversion | `python3 -m pytest -q tests/test_skill_migration.py::test_work_pilot` |
| K07 — Moment routing | K05 | Versioned stage × role × event routes, explicit opt-in rules, coverage and conflict rejection; generated orientation/index agrees | `python3 -m pytest -q tests/test_skill_routes.py` |
| K08 — Context assembly | K06, K07 | Shared worker/job/validator assembler, resolved runtime paths, immutable source receipts, mandatory-rule retention and byte accounting; both runner paths use equivalent selection | `npm --prefix orchestrator run build && node --test orchestrator/dist/test/knowledge-context.test.js` |
| K09 — Mission projections | K02, K03 | One structured snapshot feeds iteration/nodal/digest and generated state sections; ledger/journal watermarks and freshness checks; no manually maintained status tables | `npm --prefix orchestrator run build && node --test orchestrator/dist/test/knowledge-memory.test.js` |
| K10 — Narrative recovery | K09 | Separate canonical narrative from projections; archive exact pre-prune bytes before replacement; recover under real ignore rules, including never-before-committed content | `npm --prefix orchestrator run build && node --test orchestrator/dist/test/knowledge-recovery.test.js` |
| K11 — Retrieval and lifecycle | K06, K08, K09 | Disposable local index over current facts/procedures/trial references; source-backed answers for the three lookup questions; missing joins explicit; harvest flags overlapping procedures and invalidates dependents | `python3 -m pytest -q tests/test_knowledge_retrieval.py tests/test_skill_invalidation.py` |
| K12 — Remaining skill migration | K06, K07, K08 | After the pilot decision, convert remaining operational references; all 33 skills have ownership/applicability coverage; specs retain rationale; no stale duplicate fact blocks | `python3 -m pytest -q tests/test_skill_migration.py::test_all_shipped_skills` |
| K13 — Acceptance and rollout | K04, K08, K10, K11, K12 | Cold-start, packet, rejection/repair, write-refresh and compaction fixtures; measured total reads and recoverability; documented rollback to prior generated revision | `python3 -m pytest && npm --prefix orchestrator test && python3 _common/skill_registry.py validate --exec` |

K03 records current behavior before anyone changes enforcement. If the owner chooses different readiness or commit semantics, that is a separate behavior change with its own evidence; documentation migration must not silently decide it.

## 6 Measurements appendix — exact commands + numbers

All audit scripts are retained under the authorized scratch directory. They read only an explicit source allowlist or scoped globs, filter `drift-*` before emitting claim content, and do not modify the source checkout. Per-file hashes and annotated spans make the measurements inspectable.

```bash
# Run from /data/haiyangw/harness/Chandra; read-only source operations.
git branch --show-current
git rev-parse HEAD
git status --short
PYTHONDONTWRITEBYTECODE=1 python3 -B /tmp/chandra/kb-analysis/agent/measure.py
PYTHONDONTWRITEBYTECODE=1 python3 -B /tmp/chandra/kb-analysis/agent/docs/fact_audit.py
PYTHONDONTWRITEBYTECODE=1 python3 -B /tmp/chandra/kb-analysis/agent/docs/drift_symptoms.py
PYTHONDONTWRITEBYTECODE=1 python3 -B /tmp/chandra/kb-analysis/agent/skills/measure_sections.py
```

Observed branch `GUI`; HEAD `ac08dc7180b27eae999a040f3021a18c7e9456fc`; source status empty. Corpus definitions and complete per-file line/byte/hash results: [measure.py](/tmp/chandra/kb-analysis/agent/measure.py), [measurements.json](/tmp/chandra/kb-analysis/agent/measurements.json). Fact selections and per-fact totals: [fact-spans.json](/tmp/chandra/kb-analysis/agent/docs/fact-spans.json), [fact-summary.json](/tmp/chandra/kb-analysis/agent/docs/fact-summary.json).

The code corpus is `_common/ledgers/*.py`, `_common/loop/*.py`, `_common/skills/*.py`, `_common/contract.py`, flat ledger/loop/skill wrappers, the commit hook/installer, injection script/configuration, and `orchestrator/src/*.ts`. The prose corpus is the explicitly requested Markdown set plus `orchestrator/README.md`. Test source, paper scaffold descendants, mirrors, result ledgers and live runtime data are excluded from those whole-file totals. Tests and live generated interfaces are measured separately where relevant.

| Targeted fact-bearing spans | Lines | Bytes | Notes |
|---|---:|---:|---|
| Authored documents, union across eight facts | 382 | 31,507 | 31 files; overlapping selected lines counted once |
| Owner/definition code spans | 77 | 3,669 | 11 files; includes mirrors and enforcement context |
| Packet prompt contract | 17 | 1,254 | Authored instructions embedded in runtime code |
| Source docstrings/field descriptions | 33 | 2,607 | 9 files; further prose restatement |
| Derived manifest references | 8 | 376 | References to owners, not extra literal owners |
| Literal paths in generator templates | 6 | 510 | 3 files; stale values are generated too |
| Generated skills-index statements | 3 | 1,007 | Packet, cap, cadence; subset of 12,198 B index |
| Embedded skill verification references | 11 | 750 | 8 files; kept separate from procedural prose |
| Selected test assertions/behavior fixtures | 190 | 9,063 | 9 files; not claimed to be complete test coverage |

Per-fact authored span measurements, before union deduplication: domains **11 lines / 1,784 B**; statuses **14 / 1,241**; paths **47 / 4,856**; packet **74 / 5,891**; grammar **142 / 9,173**; cap **28 / 3,359**; cadence **13 / 1,695**; role **60 / 4,932**. Their sum is not the union because some lines state multiple facts.

The central script executes these interfaces with `PYTHONDONTWRITEBYTECODE=1` and `CHANDRA_INJECT_SKILLS=0`, capturing stdout under scratch:

```bash
bash .claude/inject_infra.sh
bash .claude/inject_infra.sh --with-skills
python3 -B _common/skill_registry.py briefing --root .
python3 -B _common/skill_registry.py render-index --root . --out -
python3 -B _common/contract.py manifest
python3 -B _common/result_database.py schema
python3 -B _common/knowledge_database.py schema
python3 -B _common/claims_database.py schema
python3 -B _common/error_database.py schema
```

| Actual generated stdout | Lines | Bytes |
|---|---:|---:|
| Default hook | 119 | 6,733 |
| Hook with skill briefing | 156 | 18,335 |
| Briefing alone | 36 | 11,601 |
| Rendered skills index | 42 | 12,198 |
| Contract manifest | 154 | 2,946 |
| Result schema | 13 | 970 |
| Knowledge schema | 18 | 692 |
| Claims schema | 19 | 904 |
| Error schema | 17 | 922 |

Skill Verify-section measurements stop at the next level-two heading or EOF, excluding trailing companion sections. The reproducible **869 lines / 40,414 B** result and per-skill breakdown are in [section-measurements.json](/tmp/chandra/kb-analysis/agent/skills/section-measurements.json).

Hook sizes include this checkout's absolute path and wrapper text. All interface commands exited zero. Rendered-index bytes equal the tracked index.

Runtime reproduction uses the existing installed dependencies only; no installation or network is needed:

```bash
python3 -B /tmp/chandra/kb-analysis/agent/runtime/prepare.py
cd /tmp/chandra/kb-analysis/agent/runtime/repo/orchestrator
env PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/chandra/kb-analysis/agent/runtime/tmp npm_config_cache=/tmp/chandra/kb-analysis/agent/runtime/npm-cache npm test
node /tmp/chandra/kb-analysis/agent/runtime/measure.mjs
```

The fixture scripts capture actual worker/job runner prompt inputs using a local executable that only saves stdin. They do not launch external workers. Detailed fixture and output: [runtime/measurements.json](/tmp/chandra/kb-analysis/agent/runtime/measurements.json), [runtime/measure.mjs](/tmp/chandra/kb-analysis/agent/runtime/measure.mjs).

Additional measured job prompts: decompose **1,178 B**, acquire **1,094 B**, write-refresh **1,014 B**; CLI preamble adds **316 B** each. Generated `researchStateScaffold('self')` is **591 B**. Node version was **v18.19.1**. No production progress files, tracked progress paths or default mission journal were available; none of these fixture figures is represented as a live mission average.

Exact runtime verifier tail, from [npm-test.tap](/tmp/chandra/kb-analysis/agent/runtime/npm-test.tap):

```text
1..79
# tests 79
# suites 0
# pass 79
# fail 0
# cancelled 0
# skipped 0
# todo 0
# duration_ms 5584.749273
```

Python verification ran once in a scratch copy; `test_shipped_skills_validate` executes `validate --exec` for all shipped skills, so a separate repeat was unnecessary:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B /tmp/chandra/kb-analysis/agent/skills/run_checks.py
```

The harness invokes `python3 -B -m pytest -p no:cacheprovider --basetemp /tmp/chandra/kb-analysis/agent/skills/tmp/pytest` from its copied source. It redirects explicit Python `tempfile` and shell `mktemp` requests into the allowed scratch tree, disables bytecode/caches and denies Python network connections. Repository source and skill bytes are unchanged. This is an isolated test harness, not a claim that the ordinary checkout is sandboxed.

Exact verifier output from [pytest.log](/tmp/chandra/kb-analysis/agent/skills/pytest.log):

```text
........................................................................ [ 33%]
........................................................................ [ 67%]
....................................................................     [100%]
212 passed in 21.15s
```

Safe reproduction of the bounded semantic probes uses the same temporary-directory redirect harness:

```bash
cd /tmp/chandra/kb-analysis/agent/skills/source
PYTHONDONTWRITEBYTECODE=1 CHANDRA_ANALYSIS_TMP=/tmp/chandra/kb-analysis/agent/skills/tmp TMPDIR=/tmp/chandra/kb-analysis/agent/skills/tmp PYTHONPATH=/tmp/chandra/kb-analysis/agent/skills/harness:/tmp/chandra/kb-analysis/agent/skills/source python3 -B /tmp/chandra/kb-analysis/agent/skills/probe_semantics.py
```

Exact bounded probe output:

```json
{
  "no_verify_false_prose": {
    "ok": true,
    "verify_command": null,
    "errors": []
  },
  "two_verify_blocks": {
    "ok": true,
    "executed": "true",
    "errors": []
  },
  "draft_invalid_example": {
    "registry_ok": true,
    "errors": [],
    "independent_schema_rejection": "status='impossible_status' not in ('checked', 'conditional', 'approximate', 'empirical', 'conjectural', 'refuted', 'unchecked', 'existence_only')",
    "cause": "Verify reads installed .claude/skills/ledger-result-admit/SKILL.md, not CLAUDE_SKILL_DIR draft"
  }
}
```

These probes reproduce missing validation; their success demonstrates the gaps rather than correct admission. Full structured output: [semantic-probes.json](/tmp/chandra/kb-analysis/agent/skills/semantic-probes.json). The original repository remained unchanged; no claim or research ledger was appended by this audit.

## 7 Open questions for the owner

1. When a spec is stronger than the implementation, which obligations should become enforced behavior, and which should be explicitly advisory? Readiness/open obligations and packet/node/wave commit units need deliberate decisions.
2. Must the mission through-line survive machine loss and pruning? If so, which durable home should own narrative and context receipts while disposable projections remain ignored?
3. Is a five-iteration paper refresh keyed to trial iteration still intended, distinct from waves and digest context windows?
4. Which agent clients and stage/role combinations must have equivalent loading guarantees? This determines the required routing coverage and acceptance fixtures.
5. Is the proposed 8,192 B startup / 19,456 B reusable worker-knowledge budget acceptable as a pilot target, measured together with subsequent reads?
6. Is there a demonstrated need for historical cross-mission rule/procedure queries beyond source revisions and a local derived search index? That is the decision criterion for revisiting C.
