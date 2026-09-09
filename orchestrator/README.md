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
(`src/missionspec.ts`); CLI flags override per run. Roles use Claude Agent SDK
sessions by default and need Anthropic API access. Worker, job, refuter and
judge roles can instead use an authenticated Codex CLI. The test suite uses
stub runners and fake executables and needs neither an SDK session nor a key.

### Cross-model workers

Prefix a role's model with `codex:` to select the Codex CLI for that role:

```json
{
  "paper": "2501.01234",
  "models": {
    "worker": "codex:gpt-6-astra",
    "refuter": "codex:gpt-6-astra"
  },
  "codex": {
    "effort": "max",
    "sandbox": "danger-full-access"
  }
}
```

`worker` controls stage-2 packets; `jobs` controls decompose, acquire and
write-refresh. Set `"jobs": "codex:gpt-6-astra"` to run those on the CLI too.
`refuter` and `judge` select independently, including mixed SDK/CLI validation.
`adjudicateCandidate` reads these roles from `mission.json` when no runner is
injected; `buildValidatorRunner(spec)` also exposes the selection directly.
Unprefixed or omitted models use the SDK. The observer always uses the SDK;
`--dry-run` retains the noop worker and truncating observer. An empty `codex:`
model is an error.

CLI options live in the optional `codex` block: `effort` defaults to `max`,
`timeoutSeconds` to 3600, and `bin` to `CODEX_BIN` from the environment or
`codex` on PATH. Set `codex.bin` to override `CODEX_BIN`. Workers and jobs
default to `danger-full-access`; validators default to `read-only`.
An explicit `codex.sandbox` applies to every Codex role in the mission.

Sandbox caveat: on hosts where the bwrap sandbox fails (for example,
`bwrap: loopback: Failed RTM_NEWADDR`), set `codex.sandbox` explicitly to
`danger-full-access`. There is no automatic fallback. Validator isolation
then rests on cwd + prompt only; the context pack is not a filesystem
access-control boundary.

The runner uses [`codex exec`](https://learn.chatgpt.com/docs/non-interactive-mode)
with the prompt written to stdin and stdin closed, `--skip-git-repo-check`,
and `-o` for the final message. Worker/job logs and final messages live under
`<runtimeDir(repoRoot, "paper_<P>")>/codex/<safe-id>.log` and
`<safe-id>.final.md`; ids combine the wave with the packet anchor or job id.
Validator artifacts live under the runtime home's `codex/`, outside the
context pack. Timeouts terminate the session (SIGTERM, then SIGKILL) and are
recorded as failures, as are nonzero exits. A worker's final message is only
diagnostic: progress still comes from ledger diffs and the executable gate.

## Module map

| Module | Responsibility |
|---|---|
| `src/main.ts` | CLI (`plan` / `run`) and the wave loop |
| `src/missionspec.ts` | `mission.json` spec + human signals (`PAUSE`, `STEER.md`) |
| `src/dag.ts` | Mission DAG from the ledgers; ready frontier (priority is topology) |
| `src/scheduler.ts` | Packet extraction and parallel wave execution |
| `src/jobs.ts` | Job kinds under one scheduler: decompose · work-packet · acquire · write-refresh |
| `src/agents.ts` | Shared worker/job prompts and per-role SDK or Codex runners; SDK imports stay inside SDK methods |
| `src/codex.ts` | SDK-free Codex CLI spawn contract, role defaults, closed stdin, runtime transcripts and timeouts |
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
