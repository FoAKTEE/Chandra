---
name: write-paper
description: Render a living draft, final PRD paper, or rebuttal revision from admitted ledger evidence into the consumer paper scaffold. Load for "write the paper", "refresh the living draft", "final render", or "revise after review", including the five-iteration writing cadence.
---

# write-paper — render ledger evidence into the consumer PRD scaffold

## When to use

- Stage 3 owes a living-paper refresh after five logged iterations.
- Every report claim is admitted or explicitly classified and a final render is due.
- External review requires a revised claim, new evidence, or a rebuttal round.

## Steps

1. Read `pipelines/3-write/spec.md` and the normative
   `pipelines/3-write/paper_prd_agent_template/PAPER_GENERATION_CONTRACT.md`.
   Apply `_common/contracts/research_admission_contract.md` to every scientific claim.
   Work from the repo root; select the paper ID, existing project, and observer-owned state:
   ```bash
   P='<P>'
   project='<project>'
   research_state='progress/<mission>/RESEARCH_STATE.md'
   paper_dir="results/$project/paper_$P/paper"
   ```
   Reuse the existing project for this paper. `orchestrator/src/jobs.ts` searches
   project directories for its generation log and otherwise defaults to project `mission`.
2. Read the last `iter=<N>` in `results/<project>/paper_<P>/paper/GENERATION_LOG`.
   Set `last_iter` to that integer; omit `--since` only when no generation exists:
   ```bash
   python3 _common/loop/loop_policy.py paper-refresh --paper "$P" --since "$last_iter" --every 5 --repo-root .
   # First-render probe, when there is no last_iter:
   python3 _common/loop/loop_policy.py paper-refresh --paper "$P" --every 5 --repo-root .
   ```
   Read the JSON `due` and `latest_iteration`; exit 0 alone does not mean due.
   With `--since`, elapsed iterations >= 5 trigger a refresh even off a multiple.
   Without it, the probe uses latest modulo 5; no logged iteration gives `due: false`.
   The runtime probe currently omits `--since`; check it explicitly before acting.
3. Snapshot the latest admitted state after the relevant worker flush. These commands
   print JSON arrays; keep the snapshots in runtime scratch for this render:
   ```bash
   render_scratch=$(mktemp -d /tmp/chandra-paper.XXXXXX)
   python3 _common/ledgers/knowledge_database.py query --paper "$P" --status solid --repo-root . > "$render_scratch/solid.json"
   python3 _common/ledgers/result_database.py query --paper "$P" --repo-root . > "$render_scratch/results.json"
   ```
   Use latest rows, without `--with-history`; a demoted node must not survive as an old solid claim.
   Read the state note, `results/<project>/paper_<P>/decomposition/summary.md`, and
   evidence artifacts named by those rows. Inspect methods, setup, figures, metrics,
   limits, reproducibility settings, and existing citation metadata.
4. Copy the scaffold ONCE, only when the output directory does not exist:
   ```bash
   if [ ! -e "$paper_dir" ]; then
     mkdir -p "$(dirname "$paper_dir")"
     cp -R pipelines/3-write/paper_prd_agent_template "$paper_dir"
   fi
   test -f "$paper_dir/main.tex"
   ```
   On later refreshes regenerate `results/<project>/paper_<P>/paper/sections/*.tex`
   in place. Repair an incomplete consumer copy deliberately; never recopy over a draft
   or write manuscript content into `pipelines/3-write/paper_prd_agent_template/`.
5. Preserve the required output set relative to the consumer paper directory:
   ```text
   main.tex                 macros.tex                 bibliography.bib
   sections/abstract.tex    sections/introduction.tex  sections/related_work.tex
   sections/method.tex      sections/experiments.tex   sections/results.tex
   sections/discussion.tex  sections/conclusion.tex    sections/appendix.tex
   figures/<repository-generated-figures>             GENERATION_LOG
   ```
   Keep the copied acknowledgments input/file consistent if retaining it.
   Use the single driver and its section inputs, stable section labels, PRD REVTeX,
   one-column `compact` defaults, and explicit reduced spacing in the scaffold.
6. Generate scientific prose from solid knowledge rows plus result rows only.
   Associate each claim/number with a result or node ID and its evidence artifact;
   retain traceability in LaTeX comments or a consumer generation note.
   Preserve `checked`, `conditional`, `approximate`, `empirical`, `conjectural`,
   `refuted`, `unchecked`, and `existence_only` distinctions and open obligations.
   Classifications are reportable, but unchecked steps cannot support checked claims.
   Send missing evidence back through stage 2 admission before asserting it.
7. Write exactly THREE introduction paragraphs: broad context; concrete gap;
   purpose, principal contribution/findings, and section roadmap. Use
   `.claude/skills/intro-cars/SKILL.md` and pass its eight checks.
   Add no introduction subsections, lists, tables, or figures unless explicitly requested.
   Keep the abstract a single paragraph: problem, method, principal result, significance.
   State design principles before method steps; put settings, seeds, tolerances,
   versions, hardware, and reproduction instructions in experiments or appendix.
8. Place evidence-backed figure artifacts under `results/<project>/paper_<P>/paper/figures/`.
   Use `\paperfig{figure_file.pdf}{Caption text.}{fig:descriptive_label}`;
   the default is exactly `0.8\columnwidth`. Explain any geometry-driven width override
   in a LaTeX comment. Caption what is plotted, how produced, and the conclusion.
   Assign every generated figure to main text, appendix, or a documented exclusion.
   Reference figures near their first use with `Fig.~\ref{fig:...}` and tables with
   `Table~\ref{tab:...}`; provide labels for both.
9. Use existing, verified bibliography metadata; never invent numbers or citations.
   Mark unsupported claims `\TODO{verify}`. For incomplete source metadata, use a
   clearly identified placeholder entry and `\TODO{complete citation}` nearby.
   Preserve `apsrev4-2` and the bibliography input. Run
   `.claude/skills/paper-checkpoints/SKILL.md`; revise every failed checkpoint.
10. Execute the final validation checklist before calling the output final:
    - Compile the consumer copy as a single driver: `make -C "$paper_dir"`.
      `pipelines/3-write/paper_prd_agent_template/README.md` gives the direct build fallback.
      If the TeX toolchain is absent, report compilation unverified; do not claim a final build.
    - Check separate section files, correct inputs/labels, and exactly three introduction paragraphs.
    - Check default figure widths, labeled/referenced figures and tables, and citation-key resolution.
    - Trace every numerical claim to admitted evidence; retain visible TODOs and qualifications.
    - Check PRD, one-column, compact layout and the evidence supporting every abstract/intro claim.
    - For terminal closure, require all report claims admitted or classified and no
      `[OPEN]`, `[UNCHECKED]`, or `[BLOCKING]` on checked-claim paths; apply `pipelines/2-work/spec.md`.
11. Append a log line only after a real refresh and its claimed checks pass:
    ```text
    <iso-timestamp> iter=<N> git=<sha> <n_solid> solid nodes
    ```
    Use the snapshotted `latest_iteration`, current repository SHA, and the count
    of rows in the solid-node snapshot; never invent an iteration for an empty ledger.
    Record a missing iteration as an unresolved prerequisite before stamping.
    Set `refresh_iter` to that observed integer, then stamp the completed refresh:
    ```bash
    solid_count=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$render_scratch/solid.json")
    printf '%s iter=%s git=%s %s solid nodes\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$refresh_iter" "$(git rev-parse HEAD)" "$solid_count" >> "$paper_dir/GENERATION_LOG"
    ```
    Recheck whether concurrent appends made another refresh due.
    Runtime readiness treats a missing log on mission completion as a terminal job;
    an existing log can suppress that job. Outcome measurement checks log existence,
    not manuscript quality or freshness. Independently verify final content and the new log line.
12. For rebuttal, map each review objection to a claim, evidence need, and revision.
    Route changed claims through process-isolated refuter then judge validation using
    `orchestrator/src/validator.ts`; wait for gated ledger admission, then regenerate.
    Re-run the checklist and stamp the revision; a persuasive response is not evidence.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 _common/loop/loop_policy.py --help >/dev/null
python3 _common/loop/loop_policy.py paper-refresh --help >/dev/null
for db in knowledge result; do
  python3 "_common/ledgers/${db}_database.py" --help >/dev/null
  python3 "_common/ledgers/${db}_database.py" query --help >/dev/null
done
python3 - <<'PY'
from pathlib import Path
from unittest.mock import patch
from _common.loop import loop_policy as lp
from _common.ledgers.result_database import STATUSES
assert STATUSES == ('checked', 'conditional', 'approximate', 'empirical',
                    'conjectural', 'refuted', 'unchecked', 'existence_only')
base = Path('pipelines/3-write/paper_prd_agent_template')
sections = 'abstract introduction related_work method experiments results discussion conclusion appendix'.split()
for rel in ['main.tex', 'macros.tex', 'bibliography.bib', 'Makefile', 'README.md', 'PAPER_GENERATION_CONTRACT.md']:
    assert (base / rel).is_file(), rel
driver = (base / 'main.tex').read_text()
for name in sections:
    assert (base / 'sections' / (name + '.tex')).is_file(), name
    assert rf'\input{{sections/{name}.tex}}' in driver, name
assert (base / 'figures').is_dir()
assert 'onecolumn,compact' in driver and '{revtex4-2}' in driver
assert r'\newcommand{\paperfig}[4][0.8\columnwidth]' in (base / 'macros.tex').read_text()
assert lp.PAPER_REFRESH_EVERY == 5
with patch.object(lp, '_read_entries', return_value=[{'iteration': 16}]):
    assert lp.paper_refresh_due('probe', since=11)['due'] is True
    assert lp.paper_refresh_due('probe', since=12)['due'] is False
    assert lp.paper_refresh_due('probe')['due'] is False
with patch.object(lp, '_read_entries', return_value=[]):
    assert lp.paper_refresh_due('probe')['latest_iteration'] is None
jobs = Path('orchestrator/src/jobs.ts').read_text()
assert 'terminalRenderMissing' in jobs and 'GENERATION_LOG' in jobs
PY
```

## Companion files

- `_common/contracts/note_discipline.md`
- `pipelines/3-write/principles.md`
