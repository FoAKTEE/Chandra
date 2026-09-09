---
name: mission-run
description: Configure, plan, run, and steer a mission using the shipped orchestrator, with its real flags, exit codes, journal, and wave behavior. Load for "run a mission", "plan the frontier", "pause the mission", "steer the next wave", or interpreting a halt or human digest.
---

# mission-run — run the ledger-driven scheduler and interpret its control signals

## When to use

- A consumer repo is ready to adopt a mission configuration and source set.
- An operator wants a frontier plan, an authorized mission run, or a controlled restart.
- A wave halted, a digest appeared, or human steering needs to reach the workers.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`,
   `orchestrator/README.md`, and `orchestrator/src/main.ts`. The launching session
   orchestrates; delegated workers produce research and append rows. Use a git consumer
   repo containing the methodology, Python, Node ≥18, installed orchestrator dependencies,
   and authentication for the chosen session backend. Existing dependencies build offline.
   Setup commands, when setup is authorized, run from the consumer root:
   ```bash
   CONSUMER="$PWD"
   git rev-parse --git-dir
   bash _common/hooks/install.sh
   cd orchestrator
   npm install
   npx tsc -p .
   ```
   Skip installation when dependencies are already present. Building produces the runtime
   used by package scripts; `npm run plan` does not build first. The preflight only warns
   if the hooks path is missing; inspect the installed gate rather than trusting that warning.
2. Create consumer `mission.json` at the repo root using `orchestrator/src/missionspec.ts`.
   For a new arXiv mission, use the prefixed paper id consistently with its mirror:
   ```json
   {"paper":"arxiv-2501.01234","maxWorkers":4,"maxWaves":100,
    "packetSize":4,"digestThreshold":5,"noProgressLimit":8,"maxWallSeconds":0,
    "models":{"worker":"<worker-model-id>","refuter":"<different-refuter-model-id>",
              "judge":"<judge-model-id>","observer":"<observer-model-id>","jobs":"<job-model-id>"},
    "codex":{"effort":"max","timeoutSeconds":3600,"bin":"codex","sandbox":"<chosen-sandbox>"}}
   ```
   Replace model/sandbox placeholders with supported values, or omit those optional keys
   to use defaults. Explain and select every field deliberately:

   | Field | Actual behavior |
   |---|---|
   | `paper` | Required configuration identity, unless there is no config and CLI supplies it; config loading rejects a missing paper even with a CLI override. |
   | `maxWorkers` | Concurrent work packets, default 4; separate acquire/decompose/write budgets live in code. |
   | `maxWaves` | Loop bound, default 100; exhaustion returns 2. |
   | `packetSize` | Initial maximum nodes per continuous packet, default 4; adapted after waves. |
   | `digestThreshold` | Completed context windows per digest, default 5. |
   | `noProgressLimit` | Declared but not forwarded by the CLI; runtime currently uses 8. |
   | `maxWallSeconds` | Declared but not forwarded; current CLI has no active wall-time budget. |
   | `models.worker` | Work packet session override. |
   | `models.jobs` | Decompose/acquire/write-refresh session override. |
   | `models.observer` | Observer session override. |
   | `models.refuter`, `models.judge` | Independent validation overrides, selected by `buildValidatorRunner`; the mission loop still needs an explicit validation call. |
   | `codex.effort` | CLI reasoning effort, default `max`; allowed: none/minimal/low/medium/high/xhigh/max. |
   | `codex.timeoutSeconds` | Positive session timeout, default 3600; distinct from the unused mission wall budget. |
   | `codex.bin` | Executable override; otherwise `CODEX_BIN`, then `codex` on PATH. |
   | `codex.sandbox` | Optional read-only/workspace-write/danger-full-access override for all CLI roles; omit for worker/job danger-full-access and validator read-only defaults. |
   Prefix worker/jobs/refuter/judge models with `codex:` to select the CLI backend; the
   observer stays on the SDK. See `orchestrator/src/codex.ts`; full-access provides no
   filesystem isolation, and a failed sandbox has no automatic fallback.
   The loader checks paper presence, not the remaining types/ranges. Use positive integer
   worker/wave/packet/digest settings; do not invent CLI flags for fields only present in JSON.
3. Mirror the source through `.claude/skills/acquire-source/SKILL.md` before first run.
   The acquire spec uses `ref-paper/arxiv-<id>/`, but `orchestrator/src/jobs.ts` looks for
   `ref-paper/<P>/`. Thus the example sets `paper=arxiv-2501.01234`. A bare numeric id from
   the README example will look in a different directory. Do not rename an established
   ledger identity; explicitly arrange its source/decomposition input mapping instead.
   An empty DAG without a matching mirror returns no ready jobs; stage 0 is not automatic.
4. Export an explicit runtime root outside the consumer repo so workers inherit it:
   ```bash
   export CHANDRA_RUNTIME='/tmp/chandra/<unique-mission-id>'
   ```
   Substitute a unique real directory. Without this override, `orchestrator/src/runtime.ts`
   computes `/tmp/chandra/<repo-basename>-<sha8-of-absolute-path>/`, but does not export the
   result to workers. The journal is `$CHANDRA_RUNTIME/paper_<P>/journal.jsonl` and packet
   WALs are beneath its paper directory. Runtime diaries are not committed research memory.
5. Plan from the consumer's orchestrator directory with the built runtime:
   ```bash
   node dist/src/main.js plan --repo-root "$CONSUMER"
   npm run plan -- --repo-root "$CONSUMER"
   ```
   These are alternatives. A plan prints paper, node/solid counts, completion, ready frontier
   with depth/obligation counts, and parallelism. It shows nodes, not all pending job kinds.
   Inspect the plan before execution; existing open obligations are displayed but do not
   mechanically remove a node from the frontier in `orchestrator/src/dag.ts`.
6. With authorization for sessions, output changes, and automatic wave commits, choose one:
   ```bash
   node dist/src/main.js run --repo-root "$CONSUMER" --paper "$P" --max-workers 4 --max-waves 100
   npm run run-mission -- --repo-root "$CONSUMER" --paper "$P"
   ```
   Set `P` to the selected paper id; explicit flags override configuration defaults.
   The supported flags are `--repo-root`, `--paper`, `--max-workers`, `--max-waves`,
   and `--dry-run`. There is no implemented `--help`; without a paper even help probes
   exit 1, while a configured `run --help` can run a mission. Read source to inspect flags.
7. Treat a dry run as an executing diagnostic, not a read-only or reliably offline plan:
   ```bash
   node dist/src/main.js run --repo-root "$CONSUMER" --paper "$P" --dry-run
   ```
   It uses no-op packet workers and a local observer, then normally returns after one wave.
   It still writes journal/notes and reaches chain verification and automatic commits.
   Current non-packet jobs fall back to real session runners, so decompose/acquire/write
   jobs may need API access even with `--dry-run`. Use `plan` for read-only inspection;
   use a disposable authorized consumer if testing dry-run execution.
8. Read each wave line and the journal together:
   ```text
   wave 3: packets=2 jobs=acquire admitted=1 promoted=2 rejected=0 failed=0 no_progress=1
   ```
   Packets counts leases; jobs lists non-packet kinds. Remaining fields count per-node and
   job reports derived from ledger/filesystem diffs, not worker prose. Packet anchors count
   context windows once. Packet size halves (floor, minimum 1) when maximum windows >3;
   it doubles (cap 8) when maximum windows ≤1 and failed=0. This code includes non-packet
   reports in that maximum. The observer runs after flushes; gate decisions use verified progress.
9. Inspect `progress/orchestrator/paper_<P>/HUMAN_DIGEST.md` after the window threshold;
   journal `digest_emitted` entries reset the count. Windows include completed sessions and
   compactions, not just waves; breakers interrupt independently. Its old progress-directory
   journal footer is stale; use the runtime path in step 4. Steer from the consumer root:
   ```bash
   CONTROL="progress/orchestrator/paper_$P"
   mkdir -p "$CONTROL"
   touch "$CONTROL/PAUSE"
   ```
   Resume with `rm "$CONTROL/PAUSE"`; write guidance to `STEER.md` with the editor.
   File presence pauses at the next wave boundary, not mid-worker. A nonempty `STEER.md`
   is read each wave and injected into packet workers; current non-packet job prompts do
   not receive it. Guidance persists until edited/removed. Resume by rerunning `run` after
   removing PAUSE; ledgers/journal persist, but wave numbering, gate state, and packet size restart.
10. Diagnose exit codes before restarting; do not hide failed gates or patch ledger chains:

    | Exit | Meaning and next action |
    |---|---|
    | 0 | Plan succeeded, mission completed, or one dry-run wave finished; inspect the actual command and halt reason. |
    | 1 | Argument/config/runtime exception; repair the reported setup or input problem. |
    | 2 | Maximum waves exhausted; inspect evidence/progress, then extend the wave budget only if justified. |
    | 3 | No ready jobs; inspect absent mirrors, empty DAG, cycles, missing predecessors, and job readiness. |
    | 4 | Progress circuit breaker; inspect ledger evidence and switch method/acquire/escalate before restarting. |
    | 6 | Wave commit rejected/failed; inspect hook output and staged changes, resolve the concrete failure. |
    | 7 | Human PAUSE; read steering, remove the intentional pause, rerun. |
    | 8 | Broken ledger chain; preserve state, inspect the chain report, reconcile from trusted history through the proper repair process. |

    Inspect chains with the real Python command:
    ```bash
    python3 _common/contract.py verify-chains --repo-root "$CONSUMER"
    ```
    After observer/gate/digest work, successful waves verify chains and call `commitWave`.
    `orchestrator/src/gitops.ts` stages all changes with git add -A, not just results/progress;
    inspect unrelated edits before a run. A halt before the commit step can leave changes.
    Use `.claude/skills/adversarial-validate/SKILL.md` to explicitly validate candidates;
    mission configuration alone does not connect the validator to this loop.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, re, subprocess, tempfile
from pathlib import Path
main = Path('orchestrator/src/main.ts').read_text()
flags = set(re.findall(r'get\("(--[a-z-]+)"', main)) | set(re.findall(r'argv.includes\("(--[a-z-]+)"', main))
assert flags == {'--repo-root', '--paper', '--max-workers', '--max-waves', '--dry-run'}
assert {0, 2, 3, 4, 6, 7, 8} <= {int(n) for n in re.findall(r'return (\d+);', main)}
assert 'decideGate(gateState, DEFAULT_BUDGETS)' in main
spec = Path('orchestrator/src/missionspec.ts').read_text()
for key in ['paper', 'maxWorkers', 'maxWaves', 'packetSize', 'digestThreshold', 'noProgressLimit', 'maxWallSeconds', 'models', 'worker', 'refuter', 'judge', 'observer', 'jobs', 'codex']:
    assert re.search(r'\b' + key + r'\??:', spec), key
package = json.loads(Path('orchestrator/package.json').read_text())
assert all(package['scripts'][k] == v for k, v in {'build': 'tsc -p .', 'plan': 'node dist/src/main.js plan', 'run-mission': 'node dist/src/main.js run'}.items())
for p in ['alignment.md', '_common/contracts/research_admission_contract.md', '_common/hooks/install.sh', 'orchestrator/src/digest.ts', 'orchestrator/src/runtime.ts', 'orchestrator/src/gitops.ts']:
    assert Path(p).is_file(), p
subprocess.run(['python3', '_common/contract.py', '--help'], check=True, capture_output=True, timeout=5)
with tempfile.TemporaryDirectory(prefix='chandra-mission-skill-', dir='/tmp') as tmp:
    for args in [['--help'], []]:
        out = subprocess.check_output(['python3', '_common/contract.py', 'verify-chains', '--repo-root', tmp, *args], text=True, timeout=5)
        assert json.loads(out) == {'ok': True, 'breaks': []}
PY
```
