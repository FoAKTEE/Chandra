<task>
You are an independent ANALYST (not an implementer) for the Chandra methodology repo at /data/haiyangw/harness/Chandra (git branch GUI).
The repo owner's verdict: "the current knowledgebase design is clearly not optimal." Another analyst covers the ledger / DAG data layer;
YOU cover the AGENT-FACING KNOWLEDGE layer — everything an agent reads to know what to do and what is true:
- alignment.md (always-on kernel, injected by .claude/inject_infra.sh via .claude/settings.json), _common/contracts/*.md, INDEX.md,
  README.md, _common/README.md, pipelines/*/spec.md and template.md, notes/multi_timescale_tracking_template.md, notes/pua_skill.md, AGENTS.md
- the 33 skills in .claude/skills/ (one SKILL.md each; INDEX.md generated) and their registry _common/skills/skill_registry.py
  (validate / render-index / briefing / new / promote / harvest), tests/test_skill_registry.py, tests/test_skill_loading.py
- the runtime's knowledge injection: orchestrator/src/agents.ts (worker / job prompts, CODEX_PREAMBLE, SKILL SUGGESTION CONTRACT),
  validator.ts context packs (ALWAYS_PACKED), observer.ts three notes (10240-byte cap), digest.ts, skills.ts (per-wave harvest)
- the mission memory hierarchy: progress/<mission>/{loop_notes/current_iter.md, nodal_note.md, RESEARCH_STATE.md}, HUMAN_DIGEST.md,
  the runtime journal, the packet WAL (and the fact that progress/ is gitignored)
- the 29 open obligations in results/ledgers/claim/paper_self/entries.jsonl whose entry_id starts with `drift-`: spec-vs-code drift
  found TODAY by workers writing the skills. Read them; treat them as SYMPTOMS of the design, not as your findings.
</task>

<method>
1. Inventory: for each artifact class — what it contains, who reads it and when (session start / on demand / per wave / per node), how it
   is kept true (test? generated? hand-edited?), and how much of it restates a fact whose source of truth is elsewhere. MEASURE and report:
   lines and bytes of (a) code-owned truth (enums, CLIs, schemas), (b) prose that restates it (INDEX / README / specs / contracts / skills),
   (c) generated text. Count in how many places each of these facts is stated: the DOMAINS enum, the result status enum, the on-disk ledger
   paths, the packet/WAL contract, the commit grammar, the 10 KB research-state cap, the 5-iteration paper cadence, the role policy.
   Quantify context cost: bytes injected at session start; bytes of a typical skill; bytes a worker prompt carries; bytes if a worker
   loads three skills.
2. Diagnose WHY drift happens here (design causes with file:line evidence), why the three-note hierarchy duplicates ledger state, why
   writing the skills surfaced 29 drift findings, and what an agent cannot find today (e.g. "which failure_mode did the last worker use
   for X", "what does readiness actually check", "which skill covers this moment").
3. Propose 3 designs across the cost spectrum for a knowledge layer with ONE source of truth per fact and everything else generated:
   (A) contract-driven docs — grow _common/contract.py's manifest into a full schema + behavior manifest from which INDEX sections, spec
       tables, the skills' reference sections, and AGENTS.md rules are RENDERED and drift-tested;
   (B) skills as the primary agent-knowledge unit with specs demoted to rationale; skills carry machine-checked `facts` blocks
       (fact, source symbol, expected value) verified by the registry; a moment-indexed loader (stage x role -> skill set) instead of
       keyword matching; context packs assembled from skills;
   (C) a knowledge graph in the ledgers themselves: every rule / procedure / fact is a versioned, hash-chained node (kinds: rule,
       procedure, fact) from which all prose is rendered, with retrieval (FTS) for agents.
   For each: which drift becomes impossible, what remains prose, context cost per session and per worker, migration steps, effort in
   DAG nodes with verifier commands, risks (generated prose becomes unreadable; over-mechanization; skills too long to load).
4. Recommend one (or a staged sequence) with justification from the measurements. Say what you would NOT change.
5. Migration DAG: 6-15 nodes with predecessors and verifier commands (each exits 0 iff done).
</method>

<constraints>
- Do NOT modify anything under /data/haiyangw/harness/Chandra. Never run git add / commit / checkout / stash / reset there.
  Scratch and measurements only under /tmp/chandra/kb-analysis/agent/.
- No network. Python 3.12 and Node 18 available.
- No attribution lines naming any AI tool or vendor.
</constraints>

<output_contract>
Write the memo to /tmp/chandra/kb-analysis/agent-knowledge.md (markdown, <= 600 lines) with sections:
1 Inventory + measurements · 2 Diagnosis (ranked causes with evidence) · 3 Designs A / B / C · 4 Recommendation ·
5 Migration DAG (table) · 6 Measurements appendix (exact commands + numbers) · 7 Open questions for the owner.
Your final message = the same memo verbatim.
</output_contract>
