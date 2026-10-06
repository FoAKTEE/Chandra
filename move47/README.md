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

## GPU arena: real KataGo as the opponent

`goarena` on the login host plays through the service (`KATAGO_BIN=bin/kg-client`) with the
strong net. One script pair starts and stops everything, detached (setsid + nohup, pid files):

```bash
scripts/arena_up.sh       # keepalive + `goarena serve` on 127.0.0.1:8765; idempotent
scripts/arena_status.sh   # pids, /healthz, runs (viewer token), backends and jobs
GOARENA_ADMIN_TOKEN=$(cat /data/haiyangw/claude/Move47/runs/move47/arena/admin.token) \
  python3 -m harness.runner --harness tree --tree-worker mock --tree-opponent k1-p --games 1 \
  --name smoke --run-dir /data/haiyangw/claude/Move47/runs/move47/<run> -- --budget 8 --workers 2
scripts/arena_down.sh     # arena (+ its kg-client), keepalive, scancel the model's jobs; lists leftovers
```

State lives outside the Chandra tree in `/data/haiyangw/claude/Move47/runs/move47/arena/` (dir 700):
`arena.db`, `admin.token` and `viewer.token` (mode 600, created once, passed to the server through
the environment only, so they never appear in argv, logs or `ps`), `arena.log`, `keepalive.log`,
`kg-client.log`. Website: `http://127.0.0.1:8765/?key=<viewer token>`.

Ladder `config/tiers-9x9-kata1.json` (all `counts_for_rating: false`; the k1 tiers are uncalibrated):

| tier | engine use |
|---|---|
| `random`, `greedy` | no engine (Elo kept from the b10c128 pool calibration) |
| `k1-p` | 1 visit, temperature 0: argmax of the raw policy over legal non-eye-filling moves; `root_symmetries: 8` averages the root evaluation over all 8 symmetries, so the move is a fixed function of the position (with one random symmetry per backend, `nnRandomize`, it was not) |
| `k1-64`, `k1-full` | 64 / 1600 visits, temperature 0: KataGo's best move |

Server settings in `arena_up.sh`: `--move-timeout 3600`; `--referee-visits 1600` (one ownership
search per finished game, ~1 s on the A100); `--review-visits 1600` (per position at priority -10,
so an opponent query waits for at most one review position: a 38-ply game is reviewed in ~30 s, and
k1-full replies took 0.9 s median idle, 1.0-1.7 s median / 3.0 s max under a continuous review backlog);
adjudication `--adjudicate-winrate 0.01 --adjudicate-lead 20 --adjudicate-moves 4 --adjudicate-after 30`.

**Adjudication** (off unless `--adjudicate-winrate` > 0): when the KataGo opponent's own genmove
search gave the agent winrate < W and score lead < -L on N consecutive opponent moves played after
ply P, the game ends as an agent loss, `end_reason=adjudicated`, `RE[W+]`/`RE[B+]` (no margin) and
`GC[end_reason=adjudicated]`. It reads only the evaluations stored with the opponent's moves (so a
restart keeps the streak); the agent sees the result, the reason and the rule (`goban rules`), never
the numbers. Both conditions matter: with komi 7.5 KataGo gives Black ~4% on the empty 9x9 board.

**When no backend is up** (Slurm job pending, preemption): the arena starts and serves anyway;
kg-client holds queries until a backend registers (`KGSERVICE_WAIT`, 3600 s). goarena gives each
engine query 600 s; past that the agent's call returns HTTP 503 `engine_unavailable` (its move is
kept; `goban board` later produces the delayed reply), the referee falls back to Tromp-Taylor with
the error in `scoring.method`, and a failed review is redone by `POST /api/admin/games/<id>/review`.

Tests: `python3 -m pytest -q tests/test_arena_kata1.py -p no:cacheprovider` (stub engines; one test
runs the arena through `bin/kg-client` against a backend that registers late).

## Pilot game (move47::pilot-game)

One game of `claude:claude-opus-5-5:xhigh` + gotree against `k1-full`, through the runner, detached
(run dir outside the Chandra tree; `launch.sh` there records the exact command):

```bash
python3 -m harness.runner --harness tree --tree-worker claude:claude-opus-5-5:xhigh --tree-opponent k1-full \
  --games 1 --name "Opus 5.5 xhigh / gotree" --model claude-opus-5-5 --reasoning xhigh --run-dir <run> \
  --session-timeout 86400 -- --budget 32 --workers 8 --time-limit 1500 --job-timeout 900 \
  --wrap "$PWD/bin/worker-sandbox {jobdir}"           # GOARENA_ADMIN_TOKEN from the arena's admin.token
python3 scripts/pilot_guard.py <run> --max-usd 400      # pauses the arena run, stops the runner group above the cap
python3 scripts/pilot_report.py <run> [--format json|md] # mid-game or finished: per-move jobs/s/USD/tokens, decision,
                                                        # KataGo's reply; result, SGF, review point loss after the game
```

`--claude-args` values that start with `--` need the `=` form (`--claude-args=--max-budget-usd 5`).

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
