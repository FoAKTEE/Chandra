<task>
You are an independent ANALYST (not an implementer) for the Chandra methodology repo at /data/haiyangw/harness/Chandra (git branch GUI).
The repo owner's verdict: "the current knowledgebase design is clearly not optimal." Your job: a deep, evidence-backed critique of the
RESEARCH-MEMORY layer and concrete redesign proposals. Another analyst covers the agent-facing knowledge layer (docs / contracts / skills);
you cover the DATA layer:
- the four append-only ledgers: _common/ledgers/{error,result,knowledge,claims}_database.py, ledger_common.py (hash chains, layouts),
  admission.py (the executable gate), _common/contract.py (manifest shared with the TS runtime)
- the DAG model: knowledge rows with predecessors, `PAPER::node` ids, `_shared::` nodes, amended rows, node_seq lists, the per-paper
  partition — and how the runtime consumes it: orchestrator/src/{dag,ledger,scheduler,jobs,gate,validator,skills,observer,digest}.ts
- views: results.md / claims.md / render-state, HTML, summary.csv, _common/visualization/dag_mermaid.py (merge, duplicates, progress,
  node-view), _common/visualization/dashboard.py
- loop controls as consumers of the trial log: _common/loop/loop_policy.py, _common/loop/loop_gate.py
- evidence handling (paths, sha256, commit citations, verification_run), provenance (actor_role from an env var), tamper evidence (chains)
- retrieval: how an agent finds prior errors / nodes / results today (no similarity search; the spec marks it FUTURE)
- a REAL sample: results/ledgers/*/paper_self/ — this repo's own self-hosted mission recorded today (14 nodes, 18 trials, 29 open
  obligations). The claim-ledger obligations whose entry_id starts with `drift-` are 29 spec-vs-code drift findings other workers
  already reported: read them, do NOT re-report them as new findings, but use them as symptoms of the design.
Required reading (absolute paths under /data/haiyangw/harness/Chandra): alignment.md, INDEX.md, README.md, _common/README.md,
_common/contracts/*.md, pipelines/*/spec.md, the ledger modules above, orchestrator/src/*.ts, tests/*.py (what is pinned),
.claude/skills/{ledger-result-admit,ledger-error-trial,ledger-knowledge-node,ledger-claims,ledger-query-views,dag-mermaid,mission-run,
work-packet,adversarial-validate}/SKILL.md (operational descriptions written from the code).
</task>

<method>
1. Inventory the design AS IT ACTUALLY IS (not as documented): entities, identities, edges, invariants enforced at append vs never
   enforced, storage layout, query paths, rendering paths, consumers. Anchor every statement with file:line.
2. Find the problems. For EACH problem give (a) a concrete failing scenario or a measurement YOU RAN — create throwaway repos under
   /tmp/chandra/kb-analysis/data/ (cp -r or git clone the repo there); e.g. generate 100 / 1000 / 5000 knowledge rows and time append,
   query, predecessors --transitive, dag_mermaid merge, dashboard render; construct a cross-paper dependency, an amended alias, a cyclic
   predecessor set, a tail-truncated ledger, a duplicated result_id across papers, a discharged obligation whose referent later becomes
   refuted, a result_id reused with a different claim — and show what the code does; (b) severity (blocks correctness / silently wrong /
   costs time / cosmetic) and frequency; (c) the root cause as a DESIGN choice, not a typo. Aim for the 8-15 problems that matter; skip
   lint-grade nits.
3. Propose 3 candidate architectures spanning the cost spectrum:
   (A) incremental hardening of the JSONL ledgers;
   (B) JSONL kept as the canonical hash-chained EVENT LOG + a derived, rebuildable INDEX (e.g. SQLite via the stdlib: entities / edges /
       events tables, FTS5 for retrieval) that every query, scheduler, gate, and view path reads;
   (C) one typed graph/event store replacing the four files (node kinds: claim, obligation, assumption, dag_node, result, trial, source,
       evidence, skill; edge kinds: depends_on, settles, discharges, attaches_to, supersedes, cites), paper as a property not a partition.
   For each: data model; which invariants become enforceable at write time (referential integrity, acyclicity, readiness vs open
   obligations, supersession instead of free-text amendments, cross-paper resolution); the migration path from the current files (must be
   lossless and preserve hash-chain history); impact on the TS runtime and on the 33 skills; effort as a count of DAG nodes each with a
   verifier command; risks. Chandra's non-negotiables stay: append-only + hash-chained history; executable admission at write time;
   rendered views never hand-edited; ledgers canonical over prose; Python >= 3.10 with NO third-party deps (sqlite3 from the stdlib is
   fine); Node 18; the delegation policy (CHANDRA_ROLE) and the git commit gate.
4. Recommend one architecture (or a staged sequence) and justify it with the step-2 evidence. Say what you would NOT change.
5. Give the migration as a DAG of 6-15 nodes: node id, summary, predecessors, verifier command (exits 0 iff the node is done),
   estimated effort.
</method>

<constraints>
- Do NOT modify anything under /data/haiyangw/harness/Chandra. Never run git add / commit / checkout / stash / reset there.
  All measurements happen in throwaway copies under /tmp/chandra/kb-analysis/data/.
- No network. Python 3.12 and Node 18 are available; check `python3 -c "import sqlite3"` before assuming the sqlite3 CLI exists.
- No attribution lines naming any AI tool or vendor.
</constraints>

<output_contract>
Write the memo to /tmp/chandra/kb-analysis/data-model.md (markdown, <= 600 lines) with sections:
1 Inventory · 2 Problems (ranked; each with evidence, scenario or measurement, severity, root cause) · 3 Architectures A / B / C ·
4 Recommendation · 5 Migration DAG (table) · 6 Measurements appendix (exact commands + numbers) · 7 Open questions for the owner.
Your final message = the same memo verbatim.
</output_contract>
