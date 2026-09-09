---
name: mission-dashboard
description: Render and inspect the self-contained HTML mission dashboard over all four ledgers. Load for "show the mission dashboard", "refresh the HTML dashboard", "inspect ledger progress", or reviewing node evidence and hash-chain badges after a flush.
---

# mission-dashboard — render one offline mission page from the ledgers

## When to use

- An observer needs a current human-readable mission snapshot after ledger flush.
- A reviewer needs node history, trial outcomes, open obligations, or chain badges.
- The dashboard is stale or a historical view is needed for diagnosis.

## Steps

1. Read the dashboard entry in `INDEX.md` and the rendered-view rule in
   `_common/contracts/research_admission_contract.md`. Work from the consumer repo
   root. Set `P` to the actual paper identifier; rendering requires no append role.
   The renderer reads ledgers and writes HTML; it does not admit evidence.

2. Inspect the available flags, then render the default snapshot:
   ```bash
   python3 _common/visualization/dashboard.py render --help
   python3 _common/visualization/dashboard.py render --repo-root . --paper "${P:?}"
   ```
   The default output is `results/views/dashboard/paper_<P>.html`. The JSON
   response includes rendered, paper, and path. Open that path in a browser.
   Rendering an empty paper succeeds with “No DAG yet” and “no ledgers yet”;
   a successful render is not evidence that a mission has any admitted results.

3. Use the mission default or a custom output only when appropriate:
   ```bash
   python3 _common/visualization/dashboard.py render --repo-root .
   python3 _common/visualization/dashboard.py render --repo-root . --paper "${P:?}" --out "${DASHBOARD_OUT:?}"
   ```
   Omit --paper only if the consumer's `<repo>/mission.json` has a nonempty
   paper field, for example `{"paper":"P"}`. Otherwise the CLI exits with a
   missing-paper error. An explicit --paper overrides that default. Relative
   --out paths resolve from the process working directory, not --repo-root.

4. Inspect the page's live-state elements. KPI tiles show solid nodes, verified
   results, discharged obligations, admitted claims, and trial activity. The DAG
   is inline SVG arranged by topological depth, with status glyphs and words.
   Click or focus a node and press Enter to inspect its knowledge history,
   trials, results citing it, and linked claims/obligations. Hover/focus highlights
   its edges. Cyclic or unresolved cycle-dependent nodes are reported, not drawn.
   The four ledger tabs support text search, status filters, column sorting,
   and full-row JSON detail. Failed trials remain visible under their node.

5. Read each chain badge before relying on the snapshot. An intact badge shows
   the hashed/total count in its tooltip; legacy unhashed prefixes are tolerated.
   A broken badge names the failing row. The renderer can still succeed with a
   broken chain, so use `.claude/skills/ledger-query-views/SKILL.md` to run the
   integrity gate and halt/escalate mission work. Do not fix a chain in the HTML.

6. Render append history for diagnosis with the dashboard's own flag:
   ```bash
   python3 _common/visualization/dashboard.py render --repo-root . --paper "${P:?}" --full-history --out "${HISTORY_DASHBOARD_OUT:?}"
   ```
   Current implementation expands result and claim histories. The DAG and its
   nodes table still use latest non-amended nodes; node drill-down always carries
   full knowledge history, and trials always carry full history. The help text
   overstates “every append” for all tables. Full-history also changes result and
   claim KPI counts, so use the default snapshot for current mission counts.

7. Use the auto/light/dark theme toggle; its choice persists in the browser.
   CSS, JavaScript, system fonts, and SVG are self-contained with no network
   requests or external renderer. Refresh the HTML after admitted ledger changes
   and reload the browser page; this is a static snapshot, not a live server.
   Never hand-edit the HTML. Correct rows through their ledger gate and re-render.
   Follow `.claude/skills/ledger-query-views/SKILL.md` for the other view formats.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 _common/visualization/dashboard.py --help >/dev/null
python3 _common/visualization/dashboard.py render --help >/dev/null
python3 - <<'PY'
import json, re, subprocess, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='dashboard-skill-', dir='/tmp') as tmp:
    root = Path(tmp)
    (root / 'mission.json').write_text(json.dumps({'paper': 'P'}))
    result = subprocess.run(['python3', '_common/visualization/dashboard.py', 'render',
                             '--repo-root', tmp], check=True, capture_output=True, text=True)
    reply = json.loads(result.stdout)
    out = root / 'results/views/dashboard/paper_P.html'
    assert reply['rendered'] and reply['paper'] == 'P' and Path(reply['path']) == out
    page = out.read_text()
    for marker in ('No DAG yet', 'no ledgers yet', 'Mission DAG', 'dashboard-data', 'data-theme=dark'):
        assert marker in page, marker
    assert not re.search(r'\b(?:src|href)\s*=\s*"(?:https?:)?//', page)
    assert '@import' not in page
PY
python3 -m pytest tests/test_dashboard.py -q -p no:cacheprovider
```

## Companion files

- `_common/visualization/dashboard.py`
- `tests/test_dashboard.py`
- `.claude/skills/dag-mermaid/SKILL.md`
