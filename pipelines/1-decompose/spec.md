# Decompose (stage 1)

## Role

Convert source artifacts into explicit research artifacts ready for implementation and validation. One source set -> one `results/{project}/paper_{arxiv_number}/decomposition/` directory.

## Motivation

- Avoid rebuilding existing work; avoid inheriting broken work.
- Parse tex/prose/code into artifacts that Mathematica / Python / Julia / C++ / proof-assistant work can consume.
- Turn surface claims into explicit claims with assumptions, dependencies, evidence type, and open obligations.

## Invocation triggers

- Output of `pipelines/0-acquire/spec.md`.
- Feedback from `pipelines/2-work/spec.md` — a new source or clearer claim is
  needed, or validation shows the decomposition missed something.

## Input contract

- `${REFTEX}` = `./ref-paper/arxiv-{arxiv_number}/` with tex + bib + supporting tex.
- Target implementation languages (default: Mathematica, Python, proof assistant; task-specific allowed).

## Output contract - `results/{project_name}/paper_{arxiv_number}/decomposition/`

- `convention.md` — variable -> one-line physics meaning.
- `derivation.md` — every derivation, equation labels preserved verbatim from tex; physical explanation <= original tex.
- `ref.md` — references used directly or semi-directly in the calculation.
- `logic.md` — dependency DAG **rendered as Mermaid** (`python _common/visualization/dag_mermaid.py`); one node = one extractable implementation block. Node ids are globally namespaced `PAPER::node` so every paper's DAG merges into one.
- `implementation_plan_{lang}.md` — code/work partition per `logic.md` node; one file per target language.
- `summary.md` — paper motivation, goal, result scope, conclusions, key challenge, method innovation, possible bottleneck.
- `claims.md` / `obligations.md` / `assumptions.md` — **GENERATED views over the claim
  ledger** (structured first, prose rendered): append entries with
  `python _common/claims_database.py append-batch` (rows land in
  `results/ledgers/claim/paper_{arxiv_number}/entries.jsonl`), then render all three with
  `python _common/claims_database.py render-md --paper P --out-dir <this dir>`.
  Claims carry working context, needed evidence type, dependencies, status;
  obligations carry missing assumptions, regularity, boundary conditions, unit/frame
  checks, approximation remainders; assumptions enumerate symmetries / limits /
  regimes used — do not skip. **Never hand-edit the rendered `.md` views** — amend
  the ledger (re-append the same `entry_id`) and re-render.
- `result_seed.md` — initial result-log entries marked checked, conditional, approximate, empirical, conjectural, unchecked, existence-only, or `[OPEN]`.

## Procedure

1. Plan mode -> edit mode.
2. Sub-agent deployment: non-dependent artifacts (`convention`, `ref`, `summary`) in parallel; dependent artifacts (`derivation` -> `logic` -> `implementation_plan` -> `assumptions` -> `claims` -> `obligations` -> `result_seed`) sequentially.
3. Claim pass: every surface claim gets working context, evidence type, assumptions, dependencies, and open obligations.
4. Cross-tex convention resolution: check sibling tex files in the arXiv folder; converge in `convention.md`.
5. Final consolidation agent cross-checks artifact consistency and rejects undefined claims.

## Unified DAG (one giant DAG, always Mermaid)

Always write DAGs as Mermaid, and keep ONE project-wide DAG so the same derivation appearing in different papers becomes ONE node:

1. **Append** — each paper's `logic.md` nodes go to the knowledge ledger via `python _common/knowledge_database.py append-batch` (dedup; `PAPER::node` ids).
2. **Merge** — `python _common/visualization/dag_mermaid.py merge` renders one Mermaid flowchart (subgraph per paper, cross-paper edges) to `results/{project}/GLOBAL_DAG.md` — the management view, refreshed after every paper is imported.
3. **Reformulate** — spawn a reformulation agent **on the strongest available model (best math ability)**; feed it `dag_mermaid.py duplicates` (candidate cross-paper repeats by shared equation label / matching summary). It adjudicates each and collapses genuinely identical derivations into one canonical `_shared::node`, amending the per-paper copies to point at it (`status=amended`). Different papers, same derivation → one node.

The error + knowledge ledgers are **doubly linked** to this DAG: every trial and converged record attaches UNDER a node via `node_id` (auto-numbered `node_seq` 1,2,3…) rather than minting a node. So `python _common/visualization/dag_mermaid.py progress` (per-node status + `k`/`t✗` counts) and `node-view --node-id N` (a node's full knowledge + error lists) read current project progress straight off the giant DAG.

## Sub-agent injection

Every sub-agent spawned MUST receive `alignment.md` and `_common/contracts/research_admission_contract.md` in its prompt.

## Downstream consumers

- `pipelines/2-work/spec.md` + `template.md` — one filled task per `logic.md`
  node; claim-ledger entries and `result_seed.md` serve as admission targets.

## Companion files

- Research state note: the research-state scaffold in `notes/multi_timescale_tracking_template.md` (copy to consumer's `${RESEARCH_STATE}`).
- Admission contract: `_common/contracts/research_admission_contract.md`.
- Markers / discipline / progress: `_common/contracts/{markers,note_discipline,progress_principles}.md`.
- Alignment: `/alignment.md`.
