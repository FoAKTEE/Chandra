---
name: three-notes
description: Maintain the observer-owned iteration, nodal, and research-state notes after a worker flush, including generated accepted results and the 10240-byte state cap. Load for "update the three notes", "observer memory pass", "prune research state", or a stale accepted-results block.
---

# three-notes — let the observer preserve current state after the flush

## When to use

- An observer updates mission memory after a completed wave and worker ledger flush.
- Research scope/status changed or the long-memory note exceeds its byte budget.
- The accepted-results block needs to reflect newly admitted or classified rows.
- A worker needs the handoff contract: provide evidence and row references; never write notes.

## Steps

1. Read `notes/multi_timescale_tracking_template.md`,
   `_common/contracts/note_discipline.md`, and `orchestrator/src/observer.ts`.
   Assign note writes to the observer after the flush; workers hand over ledger IDs,
   verifier output, evidence anchors, and unresolved obligations.
   Use `progress/<mission>/loop_notes/current_iter.md`,
   `progress/<mission>/nodal_note.md`, and `progress/<mission>/RESEARCH_STATE.md`.
   The last path is the consumer's `${RESEARCH_STATE}`.
2. Use the post-wave observer pass wired in `orchestrator/src/main.ts`.
   Read the actual `WavePlan`, measured `WaveResult`, and journal-derived wave history.
   `runObserver` rewrites BOTH snapshots every wave:

   | Note | Current code keeps | Replace/prune rule |
   |---|---|---|
   | Iteration | Current wave, scheduled node IDs/depth/obligations, ledger-diff outcomes, totals | Full rewrite; keep exactly one wave. |
   | Nodal | Last at most 10 waves, scheduled counts, admitted/rejected/failed/no-progress counts | Full rewrite after every wave with a rolling window. |
   | Research state | Mission through-line, ledger pointers, human questions, next steps | Extend/revise in place; prune over-cap prose. |

   Do not append historical wave tables to either snapshot. The template's ten-iteration
   boundary and richer snapshot sections are not what the current renderer emits.
   Anchor paper equations/nodes, shipped changes, and verifier evidence in the handoff;
   do not assert the code automatically emits its requested next-3 roadmap or verifier section.
3. Maintain long-memory prose on scope/status changes: mission/phase and branch;
   active task/domain/metric; source library and ingestion record; working context;
   DAG status and ledger pointers; living-paper pointer; human questions; open obligations.
   Keep the historical ingestion record stable. Let the scheduler compute the ready
   frontier; do not create a competing work plan in the note.
   The code initializes missing research state and prunes it; it does not synthesize
   these ongoing prose updates or regenerate accepted results automatically.
4. Resolve each ledger pointer to the actual consumer layout. Prefer canonical paths:
   `results/ledgers/result/paper_<P>/results.jsonl`,
   `results/ledgers/knowledge/paper_<P>/nodes.jsonl`,
   `results/ledgers/claim/paper_<P>/entries.jsonl`, and
   `results/ledgers/error/paper_<P>/trials.jsonl`.
   The code scaffold still prints legacy database-directory pointers; the ledger resolver
   in `_common/ledgers/ledger_common.py` supports those only when canonical storage is absent.
   Check actual files before retaining a scaffold pointer.
5. Render accepted results after the flush. Set the actual paper ID and note path:
   ```bash
   P='<P>'
   state_note='progress/<mission>/RESEARCH_STATE.md'
   state_scratch=$(mktemp -d /tmp/chandra-state.XXXXXX)
   python3 _common/ledgers/result_database.py render-state --paper "$P" --repo-root . > "$state_scratch/accepted.md"
   ```
   This CLI prints to stdout; it has no `--out` flag. It emits one complete block with
   `BEGIN GENERATED: accepted-results paper_<P>` and matching `END GENERATED` comments.
   Replace the old block INCLUDING its boundary comments with the emitted block exactly.
   Preserve surrounding prose and every row's status, assumptions/dependencies, and obligations.
   On first use add an Accepted Results Log section; never hand-author the result table.
6. Check block integrity before saving: require one matching begin/end pair for this
   paper, the begin before the end, and no second stale table elsewhere in the note.
   Correct a wrong result by having the responsible worker obtain a gated corrective
   ledger append, then rerender. Editing a cell cannot repair the canonical result.
7. Enforce **10240 bytes of UTF-8**, not 10240 characters, on the complete research note:
   ```bash
   python3 - "$state_note" <<'PY'
   from pathlib import Path
   import sys
   size = len(Path(sys.argv[1]).read_bytes())
   print(f'research_state_bytes={size}; cap=10240')
   if size > 10240:
       raise SystemExit(1)
   PY
   ```
   Compress prose and replace duplicated tables with ledger/view pointers. Retain mission,
   phase, open questions, necessary context, and explicitly marked gaps.
   If the generated block cannot fit, keep a ledger pointer and render command in the
   state note and retain the complete generated view outside it; never clip generated rows:
   ```bash
   python3 _common/ledgers/result_database.py render-md --paper "$P" --repo-root . --out "results/ledgers/result/paper_$P/results.md"
   ```
8. Let the observer prune before closure; its code measures bytes again and throws if
   pruning still exceeds the cap. The deterministic pruner cuts whole lines from the tail;
   inspect the result for lost obligations or a cut generated block and restore/regenerate
   the needed content within budget. An over-cap failure is not a warning to ignore.
9. Extend existing narrative sections and revise changed facts in place. Add a section
   only for a new thread; avoid "UPDATE:" tails and orphaned top insertions.
   Preserve abandoned reasoning in an appendix or a recoverable history reference.
   Keep snapshot history and pruned long-memory detail in git history, not live tables.
   Verify the note actually has committed history before relying on recoverability;
   this repo's `.gitignore` ignores `progress/`, so a save alone is not a history guarantee.
10. Hand the observer's result to the authorized landing owner with note paths, actual
    byte count, pruning summary, and generated-block status. The runtime's observer pass
    precedes the wave commit; a failed verifier/prune/commit must remain a failure.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 _common/ledgers/result_database.py --help >/dev/null
python3 _common/ledgers/result_database.py render-state --help >/dev/null
python3 _common/ledgers/result_database.py render-md --help >/dev/null
scratch=$(mktemp -d /tmp/chandra-notes-verify.XXXXXX)
trap 'rm -rf "$scratch"' EXIT
python3 _common/ledgers/result_database.py render-state --paper skill-probe --repo-root "$scratch" > "$scratch/block"
grep -Fq '<!-- BEGIN GENERATED: accepted-results paper_skill-probe ' "$scratch/block"
grep -Fq '<!-- END GENERATED: accepted-results paper_skill-probe -->' "$scratch/block"
python3 - <<'PY'
from pathlib import Path
text = Path('orchestrator/src/observer.ts').read_text()
for fragment in ['RESEARCH_STATE_CAP_BYTES = 10240', 'NODAL_WINDOW = 10',
                 'history.slice(-NODAL_WINDOW)', 'writeIterationNote(layout, plan, result);',
                 'writeNodalNote(layout, history);', 'Buffer.byteLength(content, "utf-8")',
                 'observer prune failed:', '"loop_notes", "current_iter.md"',
                 '"nodal_note.md"', '"RESEARCH_STATE.md"']:
    assert fragment in text, fragment
assert Path('notes/multi_timescale_tracking_template.md').is_file()
assert Path('_common/contracts/note_discipline.md').is_file()
PY
```

## Companion files

- `_common/contracts/markers.md`
- `_common/contracts/progress_principles.md`
