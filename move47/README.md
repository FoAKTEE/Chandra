# move47 — LLM search for AlphaGo's move 37, managed under Chandra

Mission brief: `progress/prompt/init.md` in the Move47 workspace. Design source:
`ref-code/v0.02` (go-bench: goarena + gotree; see its `PROMPT.md` and `TREE.md`).
go-bench is imported here (origin, hashes, deviations: `PROVENANCE.md`); its docs: `docs/GO-BENCH.md` (README), `TREE.md`, `DESIGN.md`.

## KataGo on GPU

KataGo is only an opponent and an offline judge. Nothing it computes may enter search,
memory or prompts (TREE.md, hard constraint 1).

```bash
scripts/fetch_katago.sh                                  # release + nets, SHA-256 pinned, into engines/ (gitignored)
sbatch scripts/slurm/katago_bench.sbatch                 # thread sweep on one A100
GO_BENCH=<go-bench> sbatch scripts/slurm/engine_check.sbatch   # grade G2 #37 P10 and G4 #78 L11
```

| file | role |
|---|---|
| `engines/katago` | launcher for the v1.18.2 CUDA 12.8 / cuDNN 9.8 release; adds pip nvidia-* libs |
| `engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz` | strongest confidently-rated kata1 net (2026-10-05): judge, referee |
| `engines/models/g170e-b10c128-…`, `g170-b6c96-…` | small nets the 9x9 tiers lv1–lv8 were calibrated with |
| `engines/configs/analysis-gpu.cfg` | analysis engine on one A100: 2×32 search threads, batch 64 |

Host: GPUs exist only inside Slurm (partition `preempt`: 1 h, preemptible, 2× A100 80GB,
4 schedulable CPUs, so 1 GPU + 2 CPUs per job). Outputs go to `logs/` and `judge/`, never tracked.

## KataGo service (kgservice)

GPU jobs live at most 1 h and can be preempted at any moment, so the arena on the login host
reaches KataGo through a small service (`kgservice/`, stdlib only) instead of spawning it:

```bash
python3 -m kgservice keepalive --model engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz &
python3 -m kgservice status                      # backends (rendezvous files) + kgservice jobs
KATAGO_BIN=bin/kg-client python3 -m goarena serve --katago-model <same model> --katago-config <any> ...
python3 -m kgservice stop                        # scancel every kgservice job
```

| piece | role |
|---|---|
| `scripts/slurm/kg_backend.sbatch` | 1 GPU + 2 CPUs, 1 h, `--signal=B:USR1@300`; runs `python3 -m kgservice backend` (MODEL/CONFIG env, strong net by default) |
| backend | one `katago analysis` (winrates as BLACK) shared by many clients on 127.0.0.1:<ephemeral>; token auth; query ids rewritten to `c<conn>:<id>` and restored; USR1 = draining (flag + control line, keeps serving); SIGTERM or engine exit = rendezvous removed, exit |
| `engines/run/backends/<id>.json` | rendezvous (dir 700, file 600, gitignored): host, port, token, model basename, pid, job id, start, deadline, draining |
| `bin/kg-client` | drop-in `KATAGO_BIN`: KataGo's stdio protocol; picks a live non-draining backend for the model basename (latest deadline first; `-config` ignored); refuses unless winrates are BLACK; on disconnect or draining it moves to another backend (waits up to `KGSERVICE_WAIT` s, default 3600) and resends only unfinished queries (remaining analyzeTurns only), deduplicating by (id, turnNumber) |
| keepalive | every 30 s: drop stale rendezvous files; submit a successor when no live non-draining backend has more than `--lead` (600) s left and no job is starting; at most `--max-jobs` (2) jobs |

Tests: `python3 -m pytest -q tests/test_kgservice.py -p no:cacheprovider` (fake engine
`tests/fake_katago.py`, no GPU). GPU smoke across a forced backend kill: `scripts/kg_smoke.py`.

## Worker sessions and sandbox

Every tree-search job is a fresh `claude -p` session (`gotree.workers.CLIWorker`). Two layers keep it
clean and unable to see engine or judge output.

**Clean flags** (default for `claude:` workers; `--no-claude-clean` turns them off, `--claude-args '...'`
appends more, e.g. `--max-budget-usd 5`). Measured on Claude Code 2.1.290 from the stream-json
`system/init` event and a captured request body:

| flag | removes |
|---|---|
| `--setting-sources ""` | user/project/local settings: hooks (atuin, codex plugin), enabled plugins (github, codex), CLAUDE.md, model/effort defaults |
| `--strict-mcp-config` | MCP servers: plugin servers and claude.ai connectors |
| `--tools Bash,Read,Write,Edit` + `--disallowed-tools WebFetch,WebSearch` | every other built-in tool (web, Task/agents, cron, worktrees, notebook, ...) |
| `--disable-slash-commands` | skills (user, plugin, bundled) |
| `--no-session-persistence` | the transcript under `~/.claude/projects` (the job's `session.jsonl` keeps the stream) |
| `--settings '{"autoMemoryEnabled": false}'` | auto-memory (the host's Move47 project memory was injected otherwise) |

The model and effort come only from the worker spec: `claude:claude-opus-5-5:xhigh` sends
`"model": "claude-opus-5-5"` and `"output_config": {"effort": "xhigh"}`. A clean session also drops the
parent session's variables (`CLAUDECODE`, `CLAUDE_CODE_*` including the messaging-socket token,
`CLAUDE_EFFORT`, `SLURM_*`, `KGSERVICE_*`).

**Sandbox** `bin/worker-sandbox` (bubblewrap), passed as gotree's `--wrap`:

```bash
python3 -m gotree search --sgf pos.sgf --run /data/haiyangw/claude/Move47/runs/move47/<run> \
    --worker claude:claude-opus-5-5:xhigh --wrap "$PWD/bin/worker-sandbox {jobdir}" --job-timeout 900
```

The host root is bound read-only; the whole Move47 workspace (Chandra with its git history and ledgers,
`engines/` incl. `engines/run` rendezvous files, `judge/`, `logs/`, `gtp_logs/`, both `ref-code/`
mirrors, `progress/`, every run dir incl. the arena), `$HOME`, `/tmp`, `/run/user/<uid>`, the munge
socket, `/opt/slurm` and `/etc/slurm` are masked by empty tmpfs mounts; `srun`/`sbatch`/`salloc` are not
found. Re-exposed: `move47/gotree` read-only (without `probe.py`, `judge.py`), the run's `bin/gtree`,
`dag.db`/`memory.db` read-only with their `-wal` (read-only) and `-shm` (writable: WAL readers keep
their read marks there), the job dir read-write, `~/.claude` read-write for the OAuth credentials with
every other entry in it masked (host transcripts, auto-memory, history, settings, plugins, skills,
daemon), and a private copy of `~/.claude.json` without its per-project section. The session runs in
its own pid namespace with a cleared environment. `worker-sandbox --print JOBDIR CMD` shows the bwrap
command line. The network is shared (the model API needs it), so services on 127.0.0.1 stay reachable
and must authenticate: the KataGo backend token lives in the masked rendezvous dir; run the arena with
`--viewer-token`.

Tests (no model): `python3 -m pytest -q tests/test_worker_sandbox.py -p no:cacheprovider` (canary with
plain commands, the fake agent through the sandbox, command construction).
