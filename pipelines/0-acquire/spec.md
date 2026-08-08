# Acquire (stage 0)

## Status

CONTRACT. Merges the former source-import (stage 0) and escalation (stage 6):
acquisition is one stage, whether it runs at mission start or mid-loop to
unblock a stalled node.

## Role

Build and extend the source library: papers, code repositories, datasets,
citations, and candidate claims/methods. Mirror sources locally, record
provenance, and import declarations. This stage imports material; it does not
certify scientific results.

## Invocation triggers

- Fresh loop start — no prior seed.
- Error-DB hit on a similar prior error → import the referenced fix.
- A scheduled `[OPEN]` item needs source support.
- **Escalation:** a `[BLOCKING]`/`[OPEN]` item names a paper, theorem, dataset,
  codebase, or method not yet in `ref-paper/` or `ref-code/`; the same node has
  not advanced for 3 iterations or 30 minutes (alignment kernel §3);
  `_common/loop_policy.py crash-triage` recommends escalation; or a source has
  PDF-only math and no usable tex.

## Input contract

- Natural-language topic description, OR an error-DB hit `{stage, node,
  root_cause}`, OR an active claim + needed evidence type + missing dependency
  (escalation path), with any known identifier (arXiv id, DOI, repo URL,
  theorem name, citation string).

## Output contract

- Source mirror under `ref-paper/arxiv-<id>/` or `ref-code/<owner>-<repo>/`
  (pinned commit SHA), each with `PROVENANCE.md`: source URL, retrieval
  command, timestamp, sha256 or commit SHA.
- `results/{project}/sources/{source_id}.md`, one per selected artifact: identifier,
  title/authors/year, relevance rationale, expected role (seed / reference /
  baseline / counterexample), candidate declarations (definitions, assumptions,
  claims, methods, datasets, code), evidence type per imported claim
  (default literature-grounded), and `[OPEN]` items where citation, artifact,
  or scope is missing.
- On the escalation path: decomposition follow-up through
  `pipelines/1-decompose/spec.md`, updated `${RESEARCH_STATE}`, and ledger rows
  linking the blocking item to the acquired dependency.

## Procedure

1. Log the trigger in the iteration note before acquisition starts.
2. Identify the canonical source. Prefer arXiv tex; otherwise acquire the PDF
   and run the VLM PDF-to-tex routine below. For code, clone into `ref-code/`
   and pin a commit SHA.
3. Record provenance before using the source.
4. Import declarations into the source library (`sources/*.md`).
5. Hand off to `pipelines/1-decompose/spec.md` for claims, assumptions,
   obligations, and result seeds.
6. Escalation path only: schedule follow-up work through the mission DAG and
   update the multi-timescale notes.

## VLM PDF-to-tex routine

- Use VLM vision, not OCR. OCR is forbidden for math-heavy source recovery.
- Split PDFs into page slices of at most 10 pages.
- Spawn one sub-agent per slice with the alignment kernel,
  `_common/contracts/research_admission_contract.md`, the page range, and the
  output path injected.
- Each slice writes tex preserving displayed math, labels, captions, and local
  symbol conventions.
- A consolidation pass concatenates slices, fixes boundary label/numbering
  issues, and compiles the assembled tex when feasible.

## Verifier gates

- **V1 acquisition:** artifact exists at the recorded path and hash/SHA matches provenance.
- **V2 source import:** the source library gained the named declarations or the failure is recorded as `[OPEN]`.
- **V3 decomposition:** the claim ledger gained the paper's entries and the rendered `claims.md` / `obligations.md` cite the acquired source.
- **V4 integration:** `${RESEARCH_STATE}`, the iteration note, and ledger rows link the original blocking item to the new dependency.

## Anti-patterns

- Treating a retrieved PDF, repo, or citation as certified evidence without source import and decomposition.
- Editing `ref-paper/` or `ref-code/` mirrors in place; commentary belongs in state notes or logs.
- Running implementation work against a dependency before the source library and working context have been updated.
- Repeating the stalled method after escalation without a concrete alternate approach.

## Open design questions

- **Rating system** `[FUTURE]` — multi-dimensional source rating (self-eval,
  peer-review, LLM eval). Interim rule: flat `literature-grounded` rating.
- **Discovery orchestrator shape** `[FUTURE]` — multi-agent subtopic search vs
  single-agent end-to-end. Interim rule: the v2 orchestrator schedules
  acquisition like any other DAG node.

## Companion files

- Alignment: `/alignment.md` (kernel; hook-injected).
- Admission contract: `_common/contracts/research_admission_contract.md`.
- Markers / discipline / progress: `_common/contracts/{markers,note_discipline,progress_principles}.md`.
- Tracking: `notes/multi_timescale_tracking_template.md`.
