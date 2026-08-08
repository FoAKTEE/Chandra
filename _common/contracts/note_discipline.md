# Note Discipline (shared)

Applies to every live document: research state notes, paper drafts, task state files, decomposition artifacts, and validation records.

## Treat the document as

A publishable research artifact with **explicit, fully-enumerated open obligations** — not a polished deliverable that hides uncertainty behind prose.

- Uncertainty is explicit — use markers (`markers.md`), not hedging.
- Gaps are visible — marked (`[BLOCKING]`, `[FUTURE]`, `[OPEN]`, `[UNCHECKED]`), not smoothed over.
- Assumptions and existence-only results are visible — marked (`[ASSUMPTION]`, `[EXISTENCE]`), not folded silently into definitions.
- Sections can be unbalanced — developed where results exist, skeletal where they do not.
- Abandoned paths are documented in appendix, not omitted.
- Structure is provisional — revise as understanding evolves.

## Bidirectional criterion

- **Forward:** every marker, when resolved, must advance the document.
- **Backward:** every loose end must be captured by a marker and, for claims, an evidence type plus assumptions/dependencies.

If you see an unmarked gap, add a marker. If a marker wouldn't help when resolved, remove it.

## Update guidelines

- **Extend existing sections** by default; new sections fragment the narrative.
- **Add a new section** only when content is a genuinely new thread (would be a standalone section in a published version).
- **Revise in place** when information changes. Do not append "UPDATE: actually..." tails.
- **Prune to appendix** when abandoning an approach. Do not delete — move.
- **Restructure** when the narrative no longer fits. Flag the restructure in the commit; do not do it silently.

## Anti-patterns (each is a violation)

- Smoothing gaps with hedging language instead of marking them.
- Hiding uncertainty to make the document "read better".
- Balancing sections artificially.
- Inserting new content at the top of documents or sections.
- Creating a new section for every thought.
- Orphaned content that doesn't connect to the narrative.
- Premature polishing before content is settled.
