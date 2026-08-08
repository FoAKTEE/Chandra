# Orchestrator

TypeScript runtime that drives a Chandra mission: it builds the mission DAG
from the ledgers, schedules parallel workers over the ready frontier, runs
process-isolated adversarial validation, maintains the observer memory, and
paces human digests. See the repository [README](../README.md) for the
methodology; this directory is only the runtime.

## Build, test, run

```bash
npm install
npm test                                       # tsc build + node --test behavioral suite

npm run plan -- --repo-root <consumer-repo>    # print the ready frontier (no side effects)
npm run run-mission -- --repo-root <consumer-repo> [--paper P] [--max-workers N] [--dry-run]
```

Configuration defaults come from `mission.json` at the consumer repo root
(`src/missionspec.ts`); CLI flags override per run. Real missions spawn
Claude Agent SDK sessions and need Anthropic API access; `--dry-run` and the
test suite use stub runners and need neither the SDK nor a key.

## Module map

| Module | Responsibility |
|---|---|
| `src/main.ts` | CLI (`plan` / `run`) and the wave loop |
| `src/missionspec.ts` | `mission.json` spec + human signals (`PAUSE`, `STEER.md`) |
| `src/dag.ts` | Mission DAG from the ledgers; ready frontier (priority is topology) |
| `src/scheduler.ts` | Packet extraction and parallel wave execution |
| `src/jobs.ts` | Job kinds under one scheduler: decompose · work-packet · acquire · write-refresh |
| `src/agents.ts` | Claude Agent SDK runners (dynamically imported, so the core runs SDK-free) |
| `src/validator.ts` | Process-isolated refuter → judge validation packs |
| `src/observer.ts` | Three-note memory; 10 KB research-state cap enforced in code |
| `src/gate.ts` | Progress circuit breaker (component-wise, verified statuses only) |
| `src/digest.ts` | Human digest after 5 completed context windows |
| `src/gitops.ts` | Per-wave commits through the commit-message gate |
| `src/ledger.ts` | Bridge to the Python ledgers — the only write path into research memory |
| `src/journal.ts` | Append-only JSONL operational journal |
| `src/runtime.ts` | Ephemeral diary home outside the repo (`/tmp/chandra/…`, `CHANDRA_RUNTIME`) |
| `src/types.ts` | Ledger row shapes and the journal message vocabulary |

Worker outcomes are always derived from ledger/filesystem diffs, never from
agent prose — the Python ledger schemas remain canonical.
