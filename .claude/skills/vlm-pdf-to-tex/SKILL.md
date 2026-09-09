---
name: vlm-pdf-to-tex
description: Recover mathematical tex from PDF page images using vision, bounded slice workers, consolidation, and a recorded compile attempt. Load for "PDF-only math", "recover tex from PDF", "no usable source tex", or an acquisition blocked by equations that cannot be imported faithfully.
---

# vlm-pdf-to-tex — recover math visually in slices of at most ten pages

## When to use

- Stage 0 has a mathematical PDF and no usable canonical tex.
- A missing equation, label, caption, or convention blocks source import or decomposition.
- A previous recovery needs a bounded correction against the original page images.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`, and the
   VLM PDF-to-tex routine in `pipelines/0-acquire/spec.md`. Confirm original tex is
   unavailable or unusable. Preserve the original PDF and its acquisition provenance.
   Use vision on rendered page images; never use OCR for mathematical source recovery.
2. Set `PDF` to the immutable PDF, determine its physical page count with the PDF viewer,
   and set `PAGE_COUNT`. Count physical pages, including front matter, rather than printed
   page numbers. Create a derived working directory, for example
   `results/<project>/sources/<source_id>/recovered-tex/`, and set `RECOVERY` to it.
   Do not overwrite an existing source mirror to accommodate the recovery.
3. Generate exhaustive, nonoverlapping page ranges; the last slice may be shorter:
   ```bash
   python3 - "$PAGE_COUNT" <<'PY'
   import sys
   pages = int(sys.argv[1])
   assert pages > 0
   for first in range(1, pages + 1, 10):
       print(f'{first:04d}-{min(first + 9, pages):04d}')
   PY
   ```
   Render/view every page in each range using the available PDF image viewer. The repo
   ships no PDF recovery CLI; a text extraction tool is not a substitute for page vision.
   If page images cannot be accessed, record the missing capability as `[OPEN]`.
4. Spawn exactly one sub-agent per slice, parallel where independent. Give each only:
   the full kernel, the full admission contract, the source identity, its page images or
   permitted PDF page range, the range's physical page numbers, and an exclusive output
   directory. Explicitly inject the two contracts; do not inherit the parent's history.
   Require the sub-agent to inspect the images and preserve displayed math, labels,
   captions, and local symbol conventions without adding an inferred derivation.
5. Assign each worker `slices/<first>-<last>/slice.tex` under `$RECOVERY` and a companion
   `slice-notes.md` there. This is the recovery's local output convention, not a repo CLI.
   Require tex fragments without competing document preambles; preserve printed equation
   numbering and existing labels where visible. When the PDF hides the original tex label,
   record a generated label-to-page/equation map and do not call it a verbatim source label.
   Put unreadable symbols, missing figures, ambiguous references, and guessed conventions
   in the slice notes as `[OPEN]`; retain page references for every uncertainty.
6. Consolidate in physical page order with a separate pass after all slices return.
   Assemble one preamble and `main.tex` under `$RECOVERY`; include the fragments in order.
   Resolve cross-boundary equations, repeated headers, label collisions, numbering, and
   cross-references against the PDF. Check that all pages and captions are accounted for.
   Reconcile slice symbol conventions, retaining uncertainty instead of inventing math.
7. Attempt compilation when a tex compiler is available. For an installed `pdflatex`,
   run from the derived directory so relative includes resolve; keep both passes' output:
   ```bash
   mkdir -p "$RECOVERY/build"
   (
     cd "$RECOVERY"
     pdflatex -interaction=nonstopmode -halt-on-error -output-directory build main.tex >build/pass1.log 2>&1 &&
     pdflatex -interaction=nonstopmode -halt-on-error -output-directory build main.tex >build/pass2.log 2>&1
   )
   ```
   Record the exit code and inspect the logs and rendered PDF. A successful compile proves
   syntax/buildability; compare recovered equations visually before claiming fidelity.
8. On compilation failure, use the actual diagnostic and source page to correct syntax,
   preamble, missing assets, or boundary assembly in the derived files, then retry.
   Do not delete difficult equations or alter their meaning to get a passing build.
   If compilation is unavailable or remains blocked, preserve tex and logs, identify the
   failing page/construct as `[OPEN]`, and report recovery as incomplete. Route every trial
   through `.claude/skills/work-packet/SKILL.md` for its error-ledger row; do not invent
   a root cause without tool output. Escalate a repeated failure instead of tweaking forever.
9. Write `PROVENANCE.md` under `$RECOVERY` for the derivative: original source URL and
   immutable PDF path/hash, retrieval command and UTC time, vision recovery method,
   page ranges, fragment-to-page mapping, recovery time, output hashes, compile command,
   exit status/log paths, and unresolved fidelity issues. Keep it distinct from the
   original artifact's provenance; recovered tex is a transcription, not upstream tex.
10. Hand the source record, PDF, derivative tex, provenance, and open items to stage 1 via
    `.claude/skills/decompose-paper/SKILL.md`. Pass the actual derivative path as an input.
    When building a new mirror, finalize recovered material before sealing that mirror;
    an existing mirror stays immutable. Finish acquisition using V1–V4 from
    `.claude/skills/acquire-source/SKILL.md`; compilation alone does not settle a claim.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
from pathlib import Path
spec = Path('pipelines/0-acquire/spec.md').read_text()
routine = spec.split('## VLM PDF-to-tex routine', 1)[1].split('## Verifier gates', 1)[0]
for text in ['not OCR', 'at most 10 pages', 'one sub-agent per slice', 'compiles']:
    assert text in routine, text
for pages in (1, 10, 11, 23, 100):
    ranges = [(i, min(i + 9, pages)) for i in range(1, pages + 1, 10)]
    assert all(1 <= b - a + 1 <= 10 for a, b in ranges)
    assert [p for a, b in ranges for p in range(a, b + 1)] == list(range(1, pages + 1))
for p in ['alignment.md', '_common/contracts/research_admission_contract.md',
          'pipelines/1-decompose/spec.md', '.claude/skills/acquire-source/SKILL.md',
          '.claude/skills/decompose-paper/SKILL.md', '.claude/skills/work-packet/SKILL.md']:
    assert Path(p).is_file(), p
PY
```

## Companion files

- `pipelines/0-acquire/spec.md`
- `_common/contracts/markers.md`
