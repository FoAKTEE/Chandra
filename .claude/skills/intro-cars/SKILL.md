---
name: intro-cars
description: Draft or repair a research introduction with Swales' CARS territory, niche, and contribution moves, then run eight yes/no checks. Load for "write the introduction", "fix the gap", "introduction is a citation dump", or paper checkpoints 7 and 17.
---

# intro-cars — establish territory, name the gap, occupy the niche

## When to use

- Draft a new research-paper introduction in stage 3.
- Repair an introduction whose motivation, gap, or contribution is unclear.
- Resolve introduction failures at paper checkpoints 7 or 17.
- Apply CARS to the introduction only; use other section guidance for abstracts and methods.

## Steps

1. Read `pipelines/3-write/moves-intro.md` for the operational source and
   `pipelines/3-write/principles.md` for the surrounding paper checkpoints.
   Gather the actual prior findings, citation metadata, and admitted contribution.
   Apply `_common/contracts/research_admission_contract.md`; rhetorical strength
   never upgrades the evidence status of a claim.
2. Outline M1 → M2 → M3 before polishing sentences. In the PRD scaffold,
   `pipelines/3-write/paper_prd_agent_template/PAPER_GENERATION_CONTRACT.md`
   requires exactly three paragraphs: allocate one move to each paragraph.
   Keep the introduction free of subsections, lists, tables, and figures unless requested.
3. Write **M1 — Establishing a Territory**. State why the area matters and what is known.
   Minimum: one centrality sentence OR one topic generalization, plus at least one
   cited prior finding. Use prior findings to advance a stance, not to fill a citation list.
   Select enough background to make the next paragraph's missing object intelligible.
4. Write **M2 — Establishing a Niche**. Name one concrete missing object, counter-claim,
   open question, or continuation of prior work. One such sentence is the minimum.
   Show the turn from known territory to the missing thing. Replace "more work is needed"
   with a precise statement of what earlier work does not establish and why that matters.
5. Write **M3 — Occupying the Niche**. State the purpose/present research AND principal
   findings; both are required. Express a contribution that is unexpected yet reasonable,
   bounded by admitted evidence. A list of experiments is not a contribution.
   Add the article roadmap: optional in CARS generally, mandatory in this repo's PRD
   introduction paragraph 3. Close the exact niche M2 identified.
6. Answer every checkpoint yes/no, citing the sentence that establishes the answer.
   For each no, record the indicated repair and repeat the check after revision:

   | # | Yes/no checkpoint | Repair on no |
   |---|---|---|
   | 1 | Are M1, M2, and M3 all present in that order? | Add or reorder moves. |
   | 2 | Does M1 have a narrative stance rather than a citation dump? | State centrality/generalization and organize findings around it. |
   | 3 | Does M2 name a specific missing object, counter-claim, or question? | Replace the vague gap with a nameable one. |
   | 4 | Is M3 a contribution, unexpected yet reasonable, rather than a task description? | State what the evidence establishes. |
   | 5 | Does M3 contain both purpose/present research and principal findings? | Supply the missing component. |
   | 6 | Is the transition from M1's known territory to M2's gap explicit? | Write the known-to-missing bridge. |
   | 7 | Does M3 visibly occupy M2's niche? | Align the claimed contribution with the gap. |
   | 8 | If M1 cites at least five works, are they grouped by stance? | Group by argument, not chronology. |

   For checkpoint 8 with fewer than five works, answer yes and record that the condition
   is not triggered. Do not add citations just to activate the checkpoint.
7. Diagnose failures using the source's failure-mode table:

   | Failure | Reader signal | Revision |
   |---|---|---|
   | M1 without M2 | Everyone knows this; why read on? | Add an explicit gap. |
   | M2 without M1 | Gap in what field? | Add minimal territory. |
   | M3 before M2 | Solution to what problem? | State the gap before the solution. |
   | M1 citation dump | Citations without an argument. | Group findings by stance. |
   | Vague M2 | More research is needed. | Name the missing object. |
   | Task-list M3 | We ran X, Y, and Z. | Rephrase as the supported contribution. |

8. Integrate the repaired introduction with the rest of the draft. Checkpoint 7 in
   `pipelines/3-write/principles.md` delegates introduction completeness here;
   checkpoint 17 delegates the introduction's context-appropriate claim repetition here.
   Match M3 to specific results and repeat the same qualified claim in method, results,
   and conclusion. Return unsupported statements to evidence work or mark `\TODO{verify}`.
9. Deliver the revised introduction plus eight yes/no answers and their sentence anchors.
   Count the three paragraphs again after edits; do not certify the whole paper from
   an introduction-only check.

## Verify

```bash
set -euo pipefail
test -f pipelines/3-write/moves-intro.md
grep -Fq '### Move 1 — Establishing a Territory' pipelines/3-write/moves-intro.md
grep -Fq '### Move 2 — Establishing a Niche' pipelines/3-write/moves-intro.md
grep -Fq '### Move 3 — Occupying the Niche' pipelines/3-write/moves-intro.md
grep -Fq '8. If M1 cites ≥ 5 works' pipelines/3-write/moves-intro.md
grep -Fq 'Checkpoint 7' pipelines/3-write/moves-intro.md
grep -Fq 'checkpoint 17' pipelines/3-write/moves-intro.md
```

## Companion files

- `.claude/skills/write-paper/SKILL.md`
- `.claude/skills/paper-checkpoints/SKILL.md`
