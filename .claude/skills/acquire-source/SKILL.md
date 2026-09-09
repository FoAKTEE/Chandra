---
name: acquire-source
description: Build or extend the source library with immutable paper and code mirrors, provenance, imported declarations, and a settled acquisition obligation. Load for "acquire a source", "missing dependency", "import this paper", or a node stalled for three iterations or thirty minutes.
---

# acquire-source — import a missing source and reconnect the research loop

## When to use

- Start a mission without source material or import a fix found in the error ledger.
- Resolve a scheduled source obligation, a missing theorem, dataset, baseline, or codebase.
- Escalate after three stalled iterations or thirty minutes; recover PDF-only math via vision.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`, and
   `pipelines/0-acquire/spec.md`. Work as a delegated worker with `CHANDRA_ROLE=worker`.
   Record the trigger, blocked node, claim, needed evidence type, and missing dependency
   in the iteration note; preserve that link throughout acquisition.
2. Inspect the actual scheduling condition in `orchestrator/src/jobs.ts`.
   An acquire job requires an existing mission DAG and a latest claim entry with
   `kind=obligation`, `status=open`, and `owner=0-acquire`. An empty DAG only schedules
   decomposition when its mirror already exists; a fresh source import needs a worker.
   From the consumer repo root, set `P`, `TASK`, `PROJECT`, and `SOURCE_ID` to actual ids:
   ```bash
   python3 _common/loop/loop_policy.py crash-triage --paper "$P" --task "$TASK" --repo-root .
   python3 _common/ledgers/claims_database.py schema
   python3 _common/ledgers/claims_database.py query --paper "$P" --kind obligation --status open --repo-root .
   ```
   The query has no owner filter; inspect `owner` in its JSON output.
3. Append a missing-source obligation if one does not already exist. Use a JSON object
   in `$CHANDRA_RUNTIME/acquire-obligation.json`; all five schema-required fields appear here:
   ```json
   {"paper":"arxiv-0000.00000","entry_id":"need-boundary-source","kind":"obligation",
    "statement":"Import the source theorem and decompose its boundary assumptions.",
    "status":"open","owner":"0-acquire","blocking":true,
    "node_ids":["arxiv-0000.00000::boundary"]}
   ```
   ```bash
   CHANDRA_ROLE=worker python3 _common/ledgers/claims_database.py append --repo-root . --row-file "$CHANDRA_RUNTIME/acquire-obligation.json"
   ```
4. Locate the canonical artifact using the supplied identifier. Prefer original tex,
   bibliography, and supporting files; use `.claude/skills/vlm-pdf-to-tex/SKILL.md`
   when only a mathematical PDF is usable. Clone code once, resolve its full commit SHA,
   and keep that revision fixed for the import. Record the actual retrieval command.
   Build new mirrors at `ref-paper/arxiv-<id>/` and `ref-code/<owner>-<repo>/`.
   Inspect and unpack downloads in staging before sealing the mirror.
5. Write `PROVENANCE.md` in each new mirror before consuming it. Include source URL,
   exact retrieval command, retrieval timestamp in UTC, and artifact SHA-256 or full
   code commit SHA; name the file covered by each hash. Record the source revision too.
   With `MIRROR` and `ARTIFACT` set to the actual directory and relative filename:
   ```bash
   sha256sum "$MIRROR/$ARTIFACT"
   git -C "$MIRROR" rev-parse HEAD
   ```
   Use the hash command for downloaded artifacts and the git command for code mirrors.
   Never edit a sealed mirror in place: put commentary in notes and changed code or
   recovered tex in derived outputs; import changed upstream material as a new revision.
6. Create `results/<project>/sources/<source_id>.md`. Include identifier, title, authors,
   year, relevance, expected role (seed/reference/baseline/counterexample), and declarations:
   definitions, assumptions, claims, methods, datasets, and code. Assign an evidence type
   to each imported claim; the ledger spelling for the default is `literature_grounding`.
   Leave missing citation, artifact, or scope as `[OPEN]`; retrieval certifies no theorem.
7. Hand off through `.claude/skills/decompose-paper/SKILL.md` before implementation.
   Require claim entries and rendered decomposition views that cite `source_ids`.
   Resolve the mirror naming drift explicitly: `orchestrator/src/jobs.ts` and
   `orchestrator/src/agents.ts` use `ref-paper/<P>/` literally. For a new mission use
   `P=arxiv-<id>` consistently in configuration, ledger rows, and namespaced node ids.
   Preserve an established mission's id; give its decomposition worker the real mirror path.
8. Run V1–V4 from `pipelines/0-acquire/spec.md` and retain their evidence.
   V1: compare existing artifacts against recorded hashes/SHA. V2: check the named
   source declarations or explicit `[OPEN]` failure. V3: inspect the appended claims and
   rendered source citations. V4, for escalation: update research state, iteration note,
   and ledger links from the original blocker to the acquired dependency and next method.
   An unresolved V1–V3 gate keeps the import open; do not implement against it.
9. Discharge only the resolved acquisition obligation by re-appending its full latest row,
   changing status and adding an existing settling result id or knowledge node id.
   The following row is valid after its `discharged_by` node has actually landed:
   ```json
   {"paper":"arxiv-0000.00000","entry_id":"need-boundary-source","kind":"obligation",
    "statement":"Import the source theorem and decompose its boundary assumptions.",
    "status":"discharged","owner":"0-acquire","blocking":true,
    "node_ids":["arxiv-0000.00000::boundary"],"source_ids":["boundary-source"],
    "discharged_by":"arxiv-0000.00000::source-import"}
   ```
   ```bash
   CHANDRA_ROLE=worker python3 _common/ledgers/claims_database.py append --repo-root . --row-file "$CHANDRA_RUNTIME/acquire-settled.json"
   python3 _common/ledgers/claims_database.py render-md --paper "$P" --out-dir "results/$PROJECT/paper_$P/decomposition" --repo-root .
   ```
   A markdown path alone cannot settle an obligation. The gate checks reference existence;
   personally check that the referenced evidence resolves this obligation. The scheduler
   measures acquire progress when the latest status leaves `open`; enforce V1–V4 as well.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, re, subprocess
from pathlib import Path
from _common.ledgers.claims_database import validate
cli = '_common/ledgers/claims_database.py'
for args in [[], ['schema'], ['query'], ['append'], ['render-md']]:
    subprocess.run(['python3', cli, *args, '--help'], check=True, capture_output=True, timeout=5)
schema = subprocess.check_output(['python3', cli, 'schema'], text=True)
assert all(x in schema for x in ['entry_id', 'statement', 'discharged', 'discharged_by'])
for args in [[], ['crash-triage']]:
    subprocess.run(['python3', '_common/loop/loop_policy.py', *args, '--help'], check=True, capture_output=True, timeout=5)
body = (Path(os.environ['CLAUDE_SKILL_DIR']) / 'SKILL.md').read_text()
fence = chr(96) * 3
for block in re.findall(fence + r'json\n(.*?)\n[ \t]*' + fence, body, re.S):
    validate(json.loads(block))
spec = Path('pipelines/0-acquire/spec.md').read_text()
assert all(f'**V{i} ' in spec for i in range(1, 5))
jobs = Path('orchestrator/src/jobs.ts').read_text()
assert 'c.owner === "0-acquire"' in jobs and 'c.status === "open"' in jobs
for p in ['alignment.md', '_common/contracts/research_admission_contract.md', 'orchestrator/src/agents.ts']:
    assert Path(p).is_file(), p
PY
```

## Companion files

- `notes/multi_timescale_tracking_template.md`
- `_common/ledgers/claims_database.py`
- `.claude/skills/decompose-paper/SKILL.md`
