# Research Paper Writing Guidelines

*Distilled from Tian Yuandong's "Five-Year PhD Retrospective" (2013), restricted to the parts directly relevant to turning accepted results into a publishable report.*

---

## General Guidelines

These are the underlying principles. They explain the *why* behind the checkpoints in the next section; read them first so that when a checkpoint fails you can judge edge cases instead of mechanically patching the prose.

### 1. Organization is the real bottleneck, not English

For most non-native authors the biggest obstacle is not vocabulary or grammar — it is how the paper is organized. Conference papers usually sit at roughly high-school English complexity, and vocabulary and sentence patterns can be absorbed by reading a handful of strong papers. Many best-paper winners were written by non-native speakers. So when a draft feels weak, the first question is almost never "is my English good enough?" — it is "is the structure right?"

### 2. Avoid the two standard failure modes

- **Toothpaste-squeezing (padding).** Hitting a length target by restating the same idea in different words, piling up filler sentences, or repeating paragraphs with minor rewordings. This leaves the paper hollow and exhausting to read.
- **Technical-report style.** Writing the paper as "first we did X, then Y, then Z, and the results are W" without explaining *why* each choice was made, what motivated it, where it applies, where it does not, or what its limits are. The subtext to the reader becomes "my advisor told me to do this, I just want to graduate, please don't ask." Such a paper is not instructive and gives the reader nothing to take away.

Both failures share the same root cause: *being too lazy to think*. When the argument has not been developed deeply enough, there is nothing to write, so the author pads; when the method has not been understood deeply enough, it degenerates into a list of steps.

### 3. Explain the reasoning behind every non-trivial choice

A little extra thinking turns a bare procedure into a substantive paragraph. For example, an objective function plus a gradient-descent update is two equations. But the surrounding paragraph can — and should — explain: how the initial point is chosen, what that initial point means in this specific application, how the step size is set and why, the typical convergence rate, where acceleration is possible, where parallelism or GPUs help, and so on. The same logic applies to algorithm steps: before the step list, state the design principles, then apply those principles to each step as it is introduced. Readers absorb procedures much more easily when they know the rationale.

### 4. A good paper is written, argued, evidenced — then aims higher

Once the paper has a defensible opening, substantive body, and convincing experiments, it clears the publication bar. To do better than that, raise the ambition of the framing.

- A mediocre framing says: *"We added a new feature; it models some property of the dataset; results improved."* It will usually be accepted but rarely stands out.
- A strong framing says: *"We propose a new framework that unifies prior methods; within this framework, the algorithm can automatically discover new features; results improve."*

Industry cares about results because results translate directly into revenue. Academic writing, in contrast, is supposed to offer a field a concise, principled account of *how to think* about a problem. Every strong paper therefore builds its own small, self-consistent world: it states a worldview and a methodology, places prior work inside that worldview so each is given its due, positions its own contribution on that map, and then walks that map to solve a concrete problem. A PhD thesis is, in the same sense, two or three papers that jointly justify a single worldview.

This sounds grandiose, but the act of constructing a worldview forces the author to catalog prior work, notice new connections, and spot openings that were previously invisible. Some apparent connections will turn out to be coincidence; others will reveal something fundamental. Either way, the exercise improves the research itself — not just the writing.

### 5. Narrative craft — walk the reader through a garden

A well-written paper is like walking a reader through a garden: the path is smooth, there are mountains on one side and water on the other, pavilions appear at natural intervals, and the reader arrives at the end without effort and wanting more. Concretely:

- From the opening, create expectation. Introduce background naturally with appropriate depth, point out what previous work misses, then present the contribution calmly, and close with evidence that the claim holds. An alternative order — lay out evidence for and against, provoke reflection, expose the gap in prior work, then unveil your solution — works equally well.
- Repeat the important claims at appropriate points in the paper, and make sure each repetition fits its surrounding context.
- Trim tedious paragraphs, but never at the cost of a necessary experimental step.
- Every paragraph needs a topic sentence and a wrap — these are the signposts in the garden. Without them, readers get lost.
- No winding detours. Interrogate every logical link. If one layer of reasoning will do, do not use two. If a simple verbal story suffices, do not reach for a complex formula; if a complex formula is truly needed, push it to the appendix.
- Plan what gets detail and what gets summarized. Detail bogs readers down; the trunk of the argument deserves heavy strokes and should leave a strong impression.
- Figures must be self-explanatory, placed where they belong, and capable of serving as paragraph-level annotations.
- Sentences should be reasonably short. Avoid clause-inside-clause constructions. Mix short and long sentences.

Each of these is easy in isolation; together they are hard and require repeated revision.

### 6. Revise, revise, revise

A first draft and a final draft can differ enormously — the original may look like a clumsy rough-hewn object and the final may read as if written in one breath. Every rewrite pass tends to surface a better organization, and the better organization in turn reveals new understanding, which pushes the underlying research forward, which shifts the relative weight of the paper's contributions, which changes what should be detailed vs. summarized, which triggers yet more revision. This loop is where writing and research fuse: writing improves the research, and the research improves the writing. That is when an author has reached expert level.

### 7. Write ideas down as you think them

Thinking without writing is a finite-state machine; thinking *and* writing is a Turing machine. A pen and paper (or a scratch file) extend working memory, widen the search space, and let you see connections and flaws you could not hold in your head. Seemingly ordinary ideas become non-trivial results once written out; promising ideas reveal their flaws the moment they are on paper. Pure head-thinking tends to spin in circles.

### 8. Read strategically, not exhaustively

Too many papers are published each year to read them all carefully. After closely reading a few of the most important papers in the area, summarize what most authors are doing and the strengths and weaknesses of each approach. When a new paper arrives, skim it predictively: guess what it does, then verify. This preserves the big picture, avoids getting trapped by surface-level variation, and — importantly — helps your own ideas steer clear of crowded paths.

### 9. The bar for a contribution is "unexpected yet reasonable"

The strongest contributions produce the response: *"of course — why didn't I see that?"* The proposition is surprising before the explanation, inevitable after. This is the target that every thesis statement, every method section, and every experimental takeaway should aim for.

---

## Checkpoints

A downstream agent should be able to answer every item below with *yes* or *no* on a given draft. A *no* tells the agent exactly what to revise. Items are grouped by aspect; within each group they are ordered roughly by what to check first.

### A. Structure & Framing

1. Is there a single, explicit thesis sentence somewhere in the abstract and again in the introduction?
2. Does the paper build its own self-consistent "worldview" — a framing in which prior work, the new contribution, and the experiments all have clearly assigned roles?
3. Is every cited prior work given a clear position inside that framing (what it does, where it stops, how this paper extends or diverges from it)?
4. Is the contribution statement phrased as *unexpected-yet-reasonable* rather than "we added feature X and got +2%"?
5. Is the ambition level one tier above "incremental feature addition" where the evidence supports it (e.g., a framework, a unification, a new principle)?

### B. Section-level Completeness

6. Abstract: does it contain — in this order — the research question, the motivation, the method, and the novel result(s)?
7. Introduction: does it set up reader expectation, summarize background with appropriate depth, identify a concrete gap in prior work, and state the contribution?
8. Method: before the step-by-step description, are the design principles stated and then used to justify each step?
9. Results: is every claim in the abstract and introduction backed by a specific experiment or derivation here?
10. Discussion / Conclusion: does it name the method's limits, the data regimes where it applies, and what it does *not* claim?

### C. Reasoning & Justification

11. For each non-trivial choice (initialization, step size, hyperparameter, architectural decision, loss term, data split), is the *why* stated, not just the *what*?
12. For each algorithm / procedure, is there a short motivating paragraph before the step list that states the design principles the steps implement?
13. For each equation that is not pure bookkeeping, is there a sentence explaining what it means in the context of this paper (not just how it is computed)?
14. Does the paper explicitly state what kinds of data / problems the method is expected to work on and where it would fail?

### D. Narrative Flow

15. Does every paragraph have a topic sentence and a closing line that connects to the next paragraph?
16. Are transitions between sections and between paragraphs smooth — can the reader move forward without re-orienting?
17. Are the paper's most important claims stated more than once, each time in a form that fits its local context (intro, method, results, conclusion)?
18. Is there any section that the reader could skip without losing the thread? If yes, either tighten it or move it to an appendix.
19. Is the logical chain as shallow as possible — one layer of reasoning where one suffices, not nested arguments?

### E. Prose & Formatting

20. Are sentences mostly short, with long sentences used only where they add rhythm? No clause-inside-clause pileups?
21. Is every figure self-explanatory from its caption and labels alone — i.e., understandable without reading the surrounding text?
22. Is every figure placed at the point in the narrative where the reader first needs it?
23. Are heavy formulas, long derivations, and implementation minutiae pushed to the appendix if they are not essential to the main argument?
24. Is detail distributed deliberately — trunk arguments rendered in heavy strokes, secondary details compressed — rather than uniformly?

### F. Revision

25. Has the draft been through at least one pass in which the organization was rethought from scratch, not just line-edited?
26. Does the current draft differ substantively from the first draft in its structure (not merely in wording)?
27. After the latest revision, did the author's understanding of the research itself change in any way? If nothing was learned from rewriting, the rewrite was cosmetic — revise again with a structural lens.
28. Before declaring the draft done, read it cold end-to-end: does any part feel forced, padded, or like a bare list of steps? If yes, return to guideline 2 or 3 and rewrite the offending section.
