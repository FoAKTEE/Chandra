# Write (stage 3)

## Role

Render accepted and classified results into a publishable paper. Three modes:

- **Living draft** — regenerated every 5 iterations from the knowledge ledger's
  `solid` rows + generated figures, so the paper tracks the loop, not only its end.
- **Final paper** — the terminal render, once every obligation is admitted.
- **Rebuttal/revision loop** — adversarial review/revision rounds after external
  reviews, run as process-isolated validator sessions in the v2 orchestrator
  (same refuter→judge mechanics as stage-2 validation).

Consumes `_common/result_database.py` rows from stage 2-work, the converged nodes
in `_common/knowledge_database.py`, and the consumer's `${RESEARCH_STATE}`.

## Invocation triggers

- **Cadence** — every 5 iterations, when `python _common/loop_policy.py paper-refresh
  --paper P --since L` reports `due: true` (`L` = the last-generated iteration read
  from the paper's `GENERATION_LOG`). Regenerate, then stamp the new iteration.
- **Terminal** — `pipelines/2-work/spec.md` says every report claim is admitted
  or explicitly classified, and no `[OPEN]` / `[UNCHECKED]` / `[BLOCKING]`
  checked-claim markers remain in `${RESEARCH_STATE}` (alignment kernel §0; the
  loop gate is the mechanical backstop).

## Input contract

- `${RESEARCH_STATE}` — the consumer's live verified research state note.
- Result ledger — `python _common/result_database.py query --paper P`: admitted
  or explicitly classified claims with evidence type, verifier result, assumptions,
  dependencies, provenance, status, and open obligations.
- Knowledge ledger — `python _common/knowledge_database.py query --paper P --status solid`:
  the converged `logic.md` nodes that back renderable claims.
- `results/{project}/paper_{arxiv_number}/` — figures, tables, code-reproducible claims.
- `results/{project}/paper_{arxiv_number}/decomposition/summary.md` — motivation, goal, result scope.

## Output contract — generated ELSEWHERE, never over the template

- Generate the real paper at the consumer path `results/{project}/paper_{arxiv_number}/paper/`
  by **copying** the `paper_prd_agent_template/` scaffold there once, then updating its
  `sections/*.tex` in place on each refresh. The scaffold in this directory is a
  read-only template — never write a real paper over it.
- `results/{project}/paper_{arxiv_number}/paper/GENERATION_LOG` — append one line per refresh:
  `<iso-timestamp> iter=<N> git=<sha> <n_solid> solid nodes`. This feeds `--since`.
- Every scientific claim is rendered from an accepted result-database / knowledge-ledger
  entry, not raw agent prose; preserve what is exact, conditional, approximate,
  empirical, refuted, unchecked, existence-only, or open.

## Paper skeleton

The `paper_prd_agent_template/` (PRD one-column REVTeX) is normative — obey
`paper_prd_agent_template/PAPER_GENERATION_CONTRACT.md`. Section craft:

- **Introduction** — apply `moves-intro.md` (Swales' CARS); the contract's 3-paragraph
  hard structure. Run the 8 yes/no checkpoints before closing.
- **Method** — apply `principles.md` §§ A-C (framing, completeness, justification).
- **Results** — `principles.md` § B item 9 (every abstract/intro claim backed here).
- **Discussion** — `principles.md` § B item 10 (limits, regimes, non-claims, obligations).

## Companion files in this directory

- `paper_prd_agent_template/` — copy-me PRD LaTeX scaffold + `PAPER_GENERATION_CONTRACT.md`
  (normative generation rules). The full-paper output target.
- `principles.md` — Tian-distilled writing principles + yes/no checkpoints A-F.
- `moves-intro.md` — CARS model for introductions (introduction-only; not fractal).

## Cross-cutting

- Alignment: `/alignment.md`. Admission contract: `_common/contracts/research_admission_contract.md`.
- Markers / discipline / progress: `_common/contracts/{markers,note_discipline,progress_principles}.md`.
- Cadence: `_common/loop_policy.py paper-refresh`; timescales in
  `notes/multi_timescale_tracking_template.md` (the living draft rides the ~5-iter rhythm).
