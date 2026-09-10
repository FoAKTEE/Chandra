---
name: ledger-query-views
description: Query current ledger state or append history, check hash chains, and regenerate the supported Markdown, HTML, and CSV views. Load for "query the ledgers", "refresh all views", "repair a stale view", or "verify ledger integrity".
---

# ledger-query-views — read canonical ledgers and rebuild their views

## When to use

- Inspect evidence, dependencies, open work, or a disputed promotion history.
- Refresh the observer's views after admitted appends or a packet flush.
- A view disagrees with a ledger, or chain verification reports tampering.

## Steps

1. Read `_common/contracts/research_admission_contract.md` and the layout in
   `INDEX.md`. Run from the consumer repo root. Set `P` to the paper identifier
   and `PROJECT` to the output project. Check integrity before relying on views:
   ```bash
   python3 _common/contract.py manifest
   python3 _common/contract.py verify-chains --repo-root .
   ```
   Manifest prints the live enums, paths, roles, and cadences. Chain verification
   returns `{"ok":true,"breaks":[]}` with exit 0, or exit 1 with break records
   containing db, paper, rows, hashed, zero-based break_at, and reason.
   Stop mission work on a break; preserve the evidence and escalate its repair.
   `orchestrator/src/main.ts` halts with ledger_tampered and exit 8 on this signal.
   Do not recalculate hashes to conceal an edit or treat rendering as a repair.

2. Resolve the actual ledger location through `_common/ledgers/ledger_common.py`.
   Canonical files are:

   | db key | JSONL file under the paper directory |
   |---|---|
   | result | `results/ledgers/result/paper_<P>/results.jsonl` |
   | error | `results/ledgers/error/paper_<P>/trials.jsonl` |
   | knowledge | `results/ledgers/knowledge/paper_<P>/nodes.jsonl` |
   | claim | `results/ledgers/claim/paper_<P>/entries.jsonl` |

   Legacy `<db>-database/paper_<P>/` remains the read AND append location only
   when it exists and the canonical paper directory does not. If both exist,
   canonical wins; neither queries nor verify-chains merge the shadowed copy.
   Do not create an empty canonical directory over legacy data to refresh a view.
   Hashes cover row content plus the preceding hash. An unhashed legacy prefix
   is tolerated; an unhashed row after hashed history breaks the chain. Every append
   holds the repository lock at `results/ledgers/.lock` (`_common/ledgers/txn.py`;
   timeout `CHANDRA_LOCK_TIMEOUT_S`) and readers take it shared, so a query never sees a
   half-written row: an incomplete final line is ignored with a stderr warning, and
   `verify-chains` reports it as `incomplete tail (crash mid-write)`, distinct from a
   hash mismatch; the next append truncates it under the lock. An intact chain still
   does not prove semantic admission, unchanged artifact bytes, or absence of a
   deleted whole-row tail without an independently retained head/count.

3. Query current state, or add --with-history for earlier versions:
   ```bash
   python3 _common/ledgers/result_database.py query --repo-root . --paper "${P:?}"
   python3 _common/ledgers/knowledge_database.py query --repo-root . --paper "${P:?}"
   python3 _common/ledgers/claims_database.py query --repo-root . --paper "${P:?}"
   ```
   Result collapses to latest result_id; knowledge to latest non-amended node_id;
   claims to latest entry_id. Collapse uses append order, not timestamp sorting,
   and happens before filtering. Result filters: --status, --result-id, --task-id.
   Knowledge filters: --status, --node-id, --task-id, --domain, --equation-label,
   --concept-advance-only. Claims filters: --kind, --status, --entry-id.
   Error has no query command and no latest collapse; read all trials through
   the public helper, which honors both layouts:
   ```bash
   python3 - "${P:?}" <<'PY'
   import json, sys
   from _common.ledgers.error_database import read_entries
   print(json.dumps(read_entries('.', sys.argv[1]), indent=2))
   PY
   ```

4. Rebuild Markdown and the research-state block with their actual output flags:
   ```bash
   python3 _common/ledgers/result_database.py render-md --repo-root . --paper "${P:?}" --out "results/${PROJECT:?}/paper_${P}/results.md"
   python3 _common/ledgers/result_database.py render-state --repo-root . --paper "${P:?}"
   python3 _common/ledgers/claims_database.py render-md --repo-root . --paper "${P:?}" --out-dir "results/${PROJECT:?}/paper_${P}/decomposition"
   ```
   Result render-md defaults to stdout and permits --with-history. Render-state
   prints only the latest accepted-results block; give it to the note owner to
   replace between its markers. It has no output-file or history flag.
   Claims --out-dir writes all three decomposition views; --kind plus optional
   --out renders one. Claims Markdown has no history flag. Error and knowledge
   have no render-md or render-state command.

5. Rebuild the three available ledger HTML tables:
   ```bash
   python3 _common/ledgers/error_database.py render-html --repo-root . --paper "${P:?}"
   python3 _common/ledgers/knowledge_database.py render-html --repo-root . --paper "${P:?}"
   python3 _common/ledgers/result_database.py render-html --repo-root . --paper "${P:?}"
   ```
   Defaults are `results/views/error/paper_<P>.html`,
   `results/views/knowledge/paper_<P>.html`, and `results/views/result/paper_<P>.html`.
   Each accepts --output for a custom path. Result/knowledge accept --with-history;
   error always shows all trials. Each rejects an empty ledger. Claims has no
   standalone render-html; use the dashboard for its HTML table.

6. Rebuild summaries for existing ledger directories, including legacy homes:
   ```bash
   python3 - "${P:?}" <<'PY'
   import subprocess, sys
   from _common.ledgers.ledger_common import db_dir
   for key, module in [('error', 'error'), ('result', 'result'), ('knowledge', 'knowledge'), ('claim', 'claims')]:
       subprocess.run(['python3', f'_common/ledgers/{module}_database.py',
                       'regenerate-summary', str(db_dir('.', key, sys.argv[1]))], check=True)
   PY
   ```
   Regenerate-summary takes a positional paper_dir, not --paper or --repo-root.
   It writes summary.csv beside JSONL, retaining full history and flattened
   object fields. Missing or empty input is a no-op, not proof that data exists.

7. Refresh the remaining combined views via `.claude/skills/dag-mermaid/SKILL.md`
   and `.claude/skills/mission-dashboard/SKILL.md`. A stale or wrong view is
   corrected by a complete gated ledger append and re-rendering. Never hand-edit
   results tables, claims/obligations/assumptions, summary CSV, or rendered HTML.
   Verify chains again after the authorized correction; leave rejected outcomes
   and historical records visible in their canonical ledgers.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, subprocess, tempfile
from pathlib import Path
from _common.ledgers import ledger_common as lc, result_database as rdb, claims_database as cdb
subcommands = {
    'error': ['render-html', 'regenerate-summary'],
    'knowledge': ['query', 'render-html', 'regenerate-summary'],
    'result': ['query', 'render-md', 'render-state', 'render-html', 'regenerate-summary'],
    'claims': ['query', 'render-md', 'regenerate-summary'],
}
for module, subs in subcommands.items():
    for args in [[], *[[s] for s in subs]]:
        subprocess.run(['python3', f'_common/ledgers/{module}_database.py', *args, '--help'], check=True, stdout=subprocess.DEVNULL)
subprocess.run(['python3', '_common/contract.py', '--help'], check=True, stdout=subprocess.DEVNULL)
manifest = json.loads(subprocess.check_output(['python3', '_common/contract.py', 'manifest'], text=True))
assert manifest['ledgers']['claim']['file'] == 'entries.jsonl'
assert manifest['ledgers']['result']['dir'] == 'results/ledgers/result'
assert lc.latest_per_node([{'node_id': 'n', 'status': 'solid'}, {'node_id': 'n', 'status': 'amended'}])[0]['status'] == 'solid'
assert rdb.latest_per_result([{'result_id': 'r', 'status': 'checked'}, {'result_id': 'r', 'status': 'refuted'}])[0]['status'] == 'refuted'
assert cdb.latest_per_entry([{'entry_id': 'c', 'status': 'open'}, {'entry_id': 'c', 'status': 'withdrawn'}])[0]['status'] == 'withdrawn'
with tempfile.TemporaryDirectory(prefix='views-skill-', dir='/tmp') as tmp:
    root = Path(tmp)
    legacy = root / 'error-database' / 'paper_P'
    legacy.mkdir(parents=True)
    assert lc.db_dir(root, 'error', 'P') == legacy
    lc.chain_append(legacy, 'trials.jsonl', {'paper': 'P', 'pass_fail': 'pass'})
    assert lc.verify_all_chains(root)['ok']
    p = legacy / 'trials.jsonl'
    p.write_text(p.read_text().replace('"pass"', '"fail"'))
    report = lc.verify_all_chains(root)
    assert not report['ok'] and report['breaks'][0]['break_at'] == 0
    assert 'P' in rdb.render_md('P', repo_root=root)
    assert 'accepted-results' in rdb.render_state('P', repo_root=root)
    assert all(Path(p).exists() for p in cdb.render_views('P', root / 'decomposition', repo_root=root).values())
PY
```

## Companion files

- `_common/contract.py`
- `_common/ledgers/ledger_common.py`
- `notes/multi_timescale_tracking_template.md`
