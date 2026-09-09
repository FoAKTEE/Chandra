---
name: paper-checkpoints
description: Review and revise a research draft with all 28 yes/no paper checkpoints across framing, completeness, reasoning, flow, formatting, and revision. Load for "review the paper", "run paper checkpoints", "this reads like a technical report", or "remove padding" before a final render.
---

# paper-checkpoints — turn 28 yes/no answers into concrete revisions

## When to use

- Review a living draft or final paper in stage 3.
- Repair padding, weak framing, missing justification, or a bare chronology of work.
- Reassess organization after evidence changes or external review.

## Steps

1. Read the principles before the checklist in `pipelines/3-write/principles.md`.
   Keep `_common/contracts/research_admission_contract.md` beside the draft: stronger
   framing must preserve evidence types, limitations, and open obligations.
   Use the principles as revision priorities, not as permission to inflate claims:
   organization before English polish; reasoning before a step list; evidence before
   ambition; deliberate narrative and detail; structural rewriting; written thinking;
   strategic reading; a contribution that is **unexpected yet reasonable**.
2. Identify two failure modes before line editing. For **padding**, remove restatements
   and develop the missing argument. For **technical-report style**, replace "we did
   X, then Y" with design principles, why each choice follows, regimes, and limits.
   Raise the framing to a framework/unification/principle only where the evidence supports it.
3. Create a review record with columns: checkpoint number, yes/no, draft anchor,
   evidence anchor where relevant, and concrete revision. Walk A–F in order below.
   Every no must yield an edit or an explicit unresolved evidence obligation.
   The wording below normalizes 18 and 28 to yes = pass; their source questions ask
   whether a defect exists, so a literal yes there requires repair.
4. Walk **A — Structure & Framing**; fix the thesis and framing before rearranging details.

   | # | Answer yes/no | Revision on no |
   |---|---|---|
   | 1 | Is one explicit thesis stated in both abstract and introduction? | Write a consistent thesis in both. |
   | 2 | Do prior work, contribution, and experiments have clear roles in a coherent framing? | Rebuild the argument map. |
   | 3 | Does each cited prior work have a position, limit, and relation to this paper? | Explain that relation. |
   | 4 | Is the contribution unexpected yet reasonable? | Explain the surprising insight and its evidence. |
   | 5 | Does the framing rise above incremental feature addition where evidence permits? | Reconsider the supported general lesson; document evidence limits. |

5. Walk **B — Section-level Completeness**; make each section do its assigned job.

   | # | Answer yes/no | Revision on no |
   |---|---|---|
   | 6 | Does the abstract give question, motivation, method, then novel results? | Reorder and supply the missing element. |
   | 7 | Does the introduction set expectations, background, a concrete gap, and contribution? | Apply `.claude/skills/intro-cars/SKILL.md`. |
   | 8 | Does the method state design principles before steps and justify steps with them? | Add the principles and connect each step. |
   | 9 | Is each abstract/intro claim backed by a specific experiment or derivation in Results? | Add admitted evidence or narrow/remove the claim. |
   | 10 | Do discussion/conclusion state limits, applicable regimes, and non-claims? | Make each explicit. |

6. Walk **C — Reasoning & Justification**; replace unexplained choices with reasons.

   | # | Answer yes/no | Revision on no |
   |---|---|---|
   | 11 | Is the why stated for every nontrivial initialization, parameter, architecture, loss, or split? | Explain the reason and evidence. |
   | 12 | Does every procedure have a motivating design-principles paragraph before its steps? | Supply that paragraph. |
   | 13 | Does each non-bookkeeping equation have its contextual meaning explained? | Interpret the equation in this problem. |
   | 14 | Are expected successful and failing data/problem regimes explicit? | State the applicability boundary. |

7. Walk **D — Narrative Flow**; preserve a short, connected argument.

   | # | Answer yes/no | Revision on no |
   |---|---|---|
   | 15 | Does every paragraph have a topic sentence and a closing connection? | Add or repair its signposts. |
   | 16 | Can readers cross paragraphs/sections without reorienting? | Repair the transition. |
   | 17 | Are important claims repeated in forms suited to intro, method, results, and conclusion? | Repeat with local purpose; run CARS for the intro. |
   | 18 | Have skippable sections been tightened or moved to the appendix? | Apply the source's skip test, then tighten/move. |
   | 19 | Is the reasoning chain as shallow as it can be? | Remove unnecessary layers. |

8. Walk **E — Prose & Formatting**; give essential arguments the most space.

   | # | Answer yes/no | Revision on no |
   |---|---|---|
   | 20 | Are sentences mostly short, without nested-clause pileups? | Split and simplify; retain purposeful rhythm. |
   | 21 | Is each figure understandable from caption and labels alone? | Explain setup, quantities, and takeaway. |
   | 22 | Is each figure placed where the narrative first needs it? | Move it and its text reference. |
   | 23 | Are nonessential heavy formulas, derivations, and implementation details in the appendix? | Move details while retaining reproducibility. |
   | 24 | Are trunk arguments detailed and secondary material compressed deliberately? | Redistribute emphasis. |

9. Walk **F — Revision**; use the revision loop to improve understanding.

   | # | Answer yes/no | Revision on no |
   |---|---|---|
   | 25 | Has at least one pass rethought organization from scratch? | Outline the argument anew before editing. |
   | 26 | Does the draft differ substantively in structure from the first version? | Reorganize beyond wording changes. |
   | 27 | Did the latest rewrite change understanding of the research? | Record the new insight or repeat with a structural lens. |
   | 28 | Does a cold end-to-end read avoid forced, padded, or bare-step passages? | Return offending sections to principles 2/3. |

   Rethink organization → identify new understanding → reweight contributions →
   redistribute detail → revise again. Admit any new scientific claim through its
   verifier and ledger before incorporating it as a result.
10. Re-run affected checks and dependent sections after each revision; then complete
    one cold end-to-end pass over all 28. Deliver the answers, anchors, revisions,
    and remaining obligations. Keep a no visible until the repair is actually checked.
    Use `.claude/skills/write-paper/SKILL.md` for compilation and scaffold validation;
    this rhetorical review alone does not certify a LaTeX build or a scientific claim.

## Verify

```bash
set -euo pipefail
test -f pipelines/3-write/principles.md
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import re
from pathlib import Path
text = Path('pipelines/3-write/principles.md').read_text()
checks = text.split('## Checkpoints', 1)[1]
assert re.findall(r'^### ([A-F])\.', checks, re.M) == list('ABCDEF')
assert [int(n) for n in re.findall(r'^(\d+)\. ', checks, re.M)] == list(range(1, 29))
for phrase in ['Toothpaste-squeezing (padding)', 'Technical-report style', 'unexpected yet reasonable', 'Revise, revise, revise']:
    assert phrase in text, phrase
PY
```

## Companion files

- `pipelines/3-write/moves-intro.md`
- `_common/contracts/note_discipline.md`
