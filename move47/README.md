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

Profiles (`scripts/arena_env.sh`, sourced by all three scripts; `--profile NAME` or `$ARENA_PROFILE`; `--dry-run`
on `arena_up.sh` / `arena_down.sh` prints the settings and commands and starts nothing):

| profile | net | tiers | port | arena dir |
|---|---|---|---|---|
| `kata1` (default, unchanged) | kata1-tf3-b11c768 | `config/tiers-9x9-kata1.json` | 8765 | `runs/move47/arena` |
| `ladder` (calibrated, lv1-lv8 rated) | g170e-b10c128 | `config/tiers-9x9.json` | 8766 | `runs/move47/arena-ladder` |

Both can run at once (each its own keepalive, backend job, pid files, tokens and db; `arena_down.sh --profile X`
stops only X and lists the other profile's processes separately). Environment variables still win over the
profile: `ARENA_DIR MODEL CONFIG TIERS HOST PORT REFEREE_VISITS REVIEW_VISITS ADJUDICATE` (`ADJUDICATE=""` = off).
Tests: `tests/test_arena_profiles.py` (dry runs: the default is unchanged, the ladder profile, overrides, refusals).

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

Server settings in `arena_up.sh`: `--move-timeout 3600` (`MOVE_TIMEOUT`: seconds of agent inactivity before a
game is forfeited; raise it above any wait of the agent for its model, e.g. `MOVE_TIMEOUT=25200` with
`mcts play --wait-for-model 6`); `--referee-visits 1600` (one ownership
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

## MCTS v2 engine (code side, `mcts/`)

MISSION.md section 5, node `move47::mcts-engine`. This package runs simulations as code only, so
that later nodes can add asynchronous LLM expansion (M8) and online learning of the weights (M7)
without touching the hot loop. It is independent of gotree's v1 tree (`gotree/`), which is
unchanged. It reuses `gotree.position` for coordinates and as the reference for the rules.

**Build.** The C core in `mcts/csrc/` (board, features, playouts, tree hot loop) compiles itself
with gcc on first import into `mcts/.build/` (gitignored). The library is named by a hash of the
sources, flags and compiler, so an edited source rebuilds it. To build explicitly, or to see a
compiler error: `python3 -m mcts build [--force]`. Set `MCTS_CC` / `MCTS_BUILD_DIR` to override
the compiler and the output directory.

```bash
python3 -m mcts bestmove --sgf data/alphago-leesedol-2016-g2.sgf --upto 36 --time 10 --threads 16
python3 -m mcts selfplay --size 9 --time 1 --games 1 [--run-dir <outside Chandra> --save-tree]
python3 -m mcts bench --threads 1,8,16,32 --time 5      # sims/s, empty 9x9 and a constructed midgame
python3 -m mcts arena --url http://127.0.0.1:8080 --token $T --opponent k1-p --time 10 --threads 32
python3 -m mcts weights [--write-default]
```

```python
from mcts.board import Board
from mcts.tree import MCTS, MCTSConfig
eng = MCTS(Board(9, 7.5), config=MCTSConfig(threads=32), weights=None)   # default-v1 weights
r = eng.search(time_s=10, threads=32)        # or sims=...; stop=callable; eng.stop() from any thread
r["best"], r["moves"][0]                     # {"coord", "n", "q" (winrate), "prior", "pv", ...}
eng.advance(r["best_move"]); eng.advance(opponent_reply)   # the new root keeps its subtree
eng.save(run_dir / "tree.npz"); eng = MCTS.load(run_dir / "tree.npz")   # resume mid-game
```

| part | design |
|---|---|
| board | C. A bordered array with stride size+2, any size up to 19. Captures, simple ko and suicide follow `gotree.position` exactly (tested on random games of size 5 to 19: legal-move sets, captures, ko point, eyes, final area score). Zobrist hash of the stones (fixed seed, so keys are stable across runs and files); the node key adds side to move, ko point and passes. Tromp-Taylor area score with komi. |
| features | One spec for playouts and priors: a colour-relative 3x3 pattern (1107 canonical) plus 41 tactical features. Layout and the hand-written default weights are in `mcts/FEATURES.md`; `features(position, move)` and `move_logits(position, weights)` in `mcts.features`. |
| playouts | C. Softmax over the legal non-eye moves of `exp(sum of weights / T)`, pass only when no such move exists, simple ko, at most 3·size² moves. The value is win/loss (±1) by Tromp-Taylor score. Own eyes are never filled. |
| tree | Struct-of-arrays in numpy (`mcts/tree.py`). Nodes are keyed by Zobrist key through a transposition table, so transpositions share N/W. Edges carry the move, the prior (learned, and merged with external priors), visits N and the child index. Selection is PUCT `Q + c_puct·P·√N/(1+n)` with virtual loss and FPU (parent Q − `fpu`). Progressive widening admits `k0 + c·N^α` children in prior order (the root, and nodes with external priors, admit all). A leaf is expanded once it has `expand_visits` visits. Leaf value: a playout z, plus the node's external value if it has one; Q at a node is `(1−lam)·Q_ext + lam·Q_playout` (just Q_playout without external values). Backup flips the sign at each ply. Positional superko applies to tree moves over the game history plus the path. |
| threads | `search(time_s, sims, threads)` runs N Python threads, each inside one C call with the GIL released. Selection reads the statistics with relaxed atomics; virtual loss and backup are atomic adds; one compare-and-swap claims an expansion. Only the transposition-table lookup/insert of a new leaf (~0.1 µs) and the event queue take a mutex. Stop conditions: time, simulation count (exact: N totals equal the simulations run), `stop()` callable, `eng.stop()`, optional early stop. |
| reuse | One tree per game, never reset. `advance(move)` moves the root to the child (creating it if needed); the subtree keeps every statistic, and the old root becomes history for superko. `set_root(board, history)` jumps anywhere while keeping the tree. |
| eviction | Caps: `max_nodes` (default 20M) and `max_edges` (default 48 per node). Arrays are allocated lazily, so only used pages cost memory: about 0.4 KB per node on 9x9 (a 1 s/move self-play game ended with 8.6M nodes and a 3.1 GB tree file). When a cap is hit, the search pauses, evicts the least-visited nodes outside the root's subtree down to `gc_low_water` (80%), compacts the arrays and continues. The root's subtree is never evicted; if it alone fills 90% of a cap the tree is frozen (new leaves are evaluated but not stored) until `advance`. |
| persistence | `save(path)` writes the arrays, root, history, moves, config and weights atomically as `.npz`; `MCTS.load(path)` rebuilds the transposition table and resumes. A save writes every node, so it costs seconds for millions of nodes (`selfplay --save-tree` and the arena player save after every move). The CLI refuses run dirs inside the Chandra tree. |

**Hooks for M7 / M8** (docstrings in `mcts/tree.py`):
- `on_expand(event)` runs on the search's control thread for each node that reaches `n_thr`
  visits (default 64), and for every node within `hook_depth` (default 1) of the root. The event
  carries `key`, `board` / `position`, `depth`, `n` and `path`. The hook only queues work; the
  search never waits for it.
- `set_external(node_key, priors={move: p}, value=winrate, source=...)` may be called from any
  thread, also during a search. It merges the priors as `(1−beta)·learned + beta·external`, in
  place. It stores `v_ext` and backs it up once through the node's recorded path. A node that is
  not in the tree stays pending until it is.
- `learner.observe(position, visit_distribution, q, depth)` (or a plain callable) runs after
  every search for each well-visited node (`observe_min_visits`) of the root's subtree, breadth
  first.
- `weights=` takes `Weights`, a path, or any provider with `get()`. The engine asks the provider
  at every search start and uses a new version without a restart. `params.lam/beta/temperatures`
  in the weight file override the config.

**Measured** (`python3 -m mcts bench --threads 1,8,16,32 --time 5`, host anta, 2026-10-07, other
users' load 25 to 27 of 144 threads). The midgame is a 30-move 9x9 position written by hand
(`mcts.cli.MIDGAME_9`).

| position | threads | sims/s | time in playouts | in expansions |
|---|---|---|---|---|
| empty 9x9 | 1 | 2213 | 97% | 2% |
| empty 9x9 | 8 | 21337 | 96% | 2% |
| empty 9x9 | 16 | 43390 | 96% | 2% |
| empty 9x9 | 32 | 85026 | 95% | 2% |
| midgame | 1 | 5496 | 94% | 4% |
| midgame | 8 | 39010 | 91% | 4% |
| midgame | 16 | 73016 | 91% | 4% |
| midgame | 32 | 142074 | 88% | 4% |

The first version held one tree mutex during descent and backup. It capped descents at about 35k/s
and fell to 41k sims/s at 32 threads in the midgame, below the 59k at 16 threads. A run with
4 playouts per leaf confirmed the cause: playouts/s rose 4x while descents stayed flat. The
lock-free hot loop above removed that cap; nearly all time is now in the playouts themselves.

For comparison, a tree in Python objects with C playouts reached 1.9k sims/s on 1 thread and
2.5k on 8 (GIL-bound, falling at 16); that is why the hot loop is in C.

Code-only sanity checks on 9x9, 8 threads, 8 games each with colours alternating: MCTS at
0.2 s/move beat the greedy policy player (argmax of the default priors) 8-0; MCTS at 0.4 s/move
beat MCTS at 0.05 s/move 8-0.

Tests: `python3 -m pytest -q tests/test_mcts_*.py -p no:cacheprovider` (about 30 s). They cover:
- rules vs gotree, Zobrist keys and transpositions, and a build from an empty build dir;
- features (deterministic, symmetric, logits = sums of weights) and tactical features;
- playouts never fill own eyes and end with every empty region bordered by one colour;
- MCTS takes a 4-stone capture, saves a group in atari and avoids a 7-stone self-atari;
- thread safety: N totals equal the simulations, no virtual loss left over, child keys match their moves;
- `advance` and compaction keep the subtree's N/W exactly; the eviction order; save/load;
- superko in the tree; hooks and external results (also during a search); learner samples; the weights provider;
- stop conditions, the CLI, and an arena game against `random` with one tree per game.

Not done here: RAVE/AMAF (not implemented, so not measured). Incremental playout feature updates:
the playouts are 88-97% of the time, so this is the next speed-up. Ladder features inside playouts
are optional and off by default (−30% playout speed). Visit counters are int32 (2^31 visits through
one node, about 4 h at 140k sims/s). The tree's terminal score is Tromp-Taylor without dead-stone
removal, so the engine captures dead stones before it passes.

## MCTS v2 with asynchronous LLM expansion (`mcts/llm.py`, `mcts/play.py`)

MISSION.md section 5, node `move47::mcts-llm`. The code search of `mcts/` runs all simulations;
Opus 5.5 sessions evaluate selected nodes in the background and their priors and values enter the
tree through `set_external` while it is being searched. gotree's v1 code is reused unchanged: the
workers (`CLIWorker` with the clean flags and `bin/worker-sandbox`), the job kinds and prompts
(`expand`, `more` with a region, `refute`, `abstract`), validation, the DAG (L0) and the lesson
memory (L1/L2), the arena helpers (`current_board`, `play_decision`) and `_cli_usage`.

```bash
# a game (token from $GOARENA_TOKEN); --llm off = code-only ablation, --learn = mcts.hl.OnlineLearner
python3 -m mcts play --arena http://127.0.0.1:8765 --opponent k1-full --games 1 --run <dir outside Chandra> \
    --worker claude:claude-opus-5-5:xhigh --wrap "$PWD/bin/worker-sandbox {jobdir}" \
    --time-per-move 1800 --threads 32 --llm-workers 16 [--learn] [--llm off]
# the same through the campaign runner (workspaces, relaunch, logs); args after -- go to `mcts play`
GOARENA_ADMIN_TOKEN=$(cat <arena dir>/admin.token) python3 -m harness.runner --harness mcts \
    --tree-worker claude:claude-opus-5-5:xhigh --tree-opponent k1-full --games 1 --run-dir <dir> \
    -- --time-per-move 1800 --wrap "$PWD/bin/worker-sandbox {jobdir}"
# one position: code-only warm-up, then search with the LLM service; root tables over time
python3 -m mcts llm-search --sgf game.sgf --upto 22 --run <dir> --worker claude:claude-opus-5-5:xhigh \
    --wrap "$PWD/bin/worker-sandbox {jobdir}" --time 420 --warmup 30 --llm-workers 8 --max-llm-jobs 16
```

Main options of `play`: `--n-thr` (default 100000: visits at which a node is queued; the root and
its children always are), `--llm-workers` (W, default 16), `--max-llm-jobs` (session cap, default
none), `--job-timeout` (900 s), `--save-every` (tree checkpoint every N decisions, default 5),
`--dag` / `--memory` (share them between runs to reuse evaluations and lessons), `--set KEY=VALUE`
(MCTSConfig), `--llm-set KEY=VALUE` (LLMConfig), `--max-load-frac` (0.7: the search threads are
capped so that host load plus threads stays under 70% of the hardware threads), `--drain` (wait for
sessions in flight at exit), `--wait-for-model` (6 h: before each decision, wait while the service is paused
for a rate / usage limit, so no search of a game with the model on starts without it; each move record has
`model_input`, `waited_for_model_s` and its decision `label`).

| part | design |
|---|---|
| hook | `on_expand` only appends the event to an inbox (O(1)); it fires when a node reaches `n_thr` visits and for every node within `hook_depth` (1) of the root. |
| triage | One dispatcher thread. Each node's canonical position gives its DAG key and the symmetry `s` (canonical = real.transformed(s)). One request per (kind, DAG key): engine nodes with the same canonical position (symmetric moves, transpositions) follow the first request and all receive its result. A node whose DAG key already has an LLM evaluation is served from the DAG at once, without a session (also across moves, games and runs that share the DAG). |
| queue | Priority classes: the root's expand; the most-visited root moves without a model value (`boost`, mcts-calib); root breadth (scouts, refute) and lessons; the root's children (a child with under 0.2% of the root's visits ranks with the deeper nodes); deeper nodes. Within a class, by the node's current visits (read when a slot frees). Non-root requests wait `dispatch_delay_s` (2 s) after a new root so that the code search ranks the children first. Cap `queue_cap` (256): the lowest priority is dropped (insert and drop in one locked step). After `advance`, requests for nodes no longer reachable from the new root are dropped (exact: `MCTS.in_subtree`, any move order). Dropped requests re-arm their node's hook once the queue has room (mcts-calib). |
| jobs | Built like v1 `_make_job`: position card of the canonical position, memory briefing, `known` for more/refute. Root expand k=10 candidates + u=4 unconventional, other nodes 6 + 1. Root breadth at every new root: v1 `regions()` scouts (v1 defines none below 13x13, so none on 9x9), a refute of the most-visited root move after `refute_after_s` (60 s), and an `abstract` job after each decision. |
| results | Written to the DAG exactly as v1 writes them (edges with prior and source; unconventional at prior 0.03; scouts mass-scaled; refute at least 0.15; `set_static` value). The engine receives the union of all LLM edges of the DAG key, mapped back with `inv[s]` to the real frame, plus the job's value: `set_external(key, priors, value, source="llm", position=board)`. At the root the LLM moves get the engine's minimum visits (`set_root_breadth`, mcts-calib; the 0.05 prior floor `root_explore_prior` that stood in for it is off by default). A supplied learner gets `observe_external(position, source, priors, value)` for every applied evaluation (plus `n=` visits when it takes keyword arguments). A request leaves the running set only after its results are applied, and an inbox event counts as busy until triaged, so `wait_idle()` means applied. |
| failures | Classified from the JobResult and the job's `session.jsonl` / `session.err` (error results, API-retry events, "API Error" texts only, never the model's own text): rate limit (429, usage limit, with its reset time), overload (529/503), timeout, invalid answer, no answer, exception. Rate limits and overload, and 3 other failures in a row, pause dispatching for 30 s doubling to 30 min (or until a usage-limit reset, at most 6 h) and halve the sessions in flight (floor 1); every 2 successes add one back. A request gets at most 2 sessions after ordinary failures and 6 after rate limits. The search never waits and nothing raises into it. |
| accounting | `<run>/llm-jobs.jsonl`: one line per session (kind, DAG key, failure class, seconds, tokens and cost from `_cli_usage`, priors applied). Each move record carries the service's counters since the previous move. |

**Play loop.** One tree per game: after our move and the reply the engine advances twice and
`new_root()` re-ranks the queue; a move list that does not continue the tree's jumps with
`set_root` (still keeping the tree). Decision: `mcts/decide.py` (mcts-calib; most visits with
`--llm off`), the rule recorded per move. Board fetches and submissions use
gotree's resilient helpers (engine outages, resync, transport errors). `<run>/moves.jsonl` per
decision: game, ply, move, sync (`new` / `advanced` / `set_root` / `resumed+...`), sims, sims/s,
nodes, root visits at the start of the search (`root_n_start`: what the reused subtree brought),
root winrate, stop reason, weights version, the root table (visits, winrate, merged prior, learned
prior, LLM prior, PV), whether the root has an LLM evaluation, the LLM counters of the move and the
running cost, wall seconds and save seconds. The tree is saved to `game<N>-tree.npz` (+ a `.json`
with the arena moves it follows) every `--save-every` decisions; a restarted process (e.g. a runner
relaunch) loads it and advances it to the arena's position. `--learn` builds
`mcts.hl.OnlineLearner` (exits with a message if the module is missing), passes its `provider` as
the weights and itself as the engine's learner, calls `update()` after each decision and
`observe_game(result, our_color)` after each game.

Run dir: `config.json`, `log.txt`, `moves.jsonl`, `llm-jobs.jsonl`, `dag.db`, `memory.db`,
`jobs/<id>-<kind>-<tag>/` (one per session), `bin/gtree`, `game<N>-tree.{npz,json}`.

**Smoke runs** (2026-10-07, run dirs in `/data/haiyangw/claude/Move47/runs/move47/mcts-llm-20261007/`, launch
scripts `smoke-a.sh`, `smoke-b.sh` there):

- (a) GPU arena (`scripts/arena_up.sh`), `harness.runner --harness mcts --tree-worker mock --tree-opponent k1-p
  -- --time-per-move 3 --threads 16 --llm-workers 4 --n-thr 20000`: one game, 19 decisions, lost (adjudicated at
  ply 38; arena review 4.66 points lost per move). Every move after the first was `advanced` with the reused root
  holding visits (18 of 18); median 157k simulations per move (52k/s); 2.85M nodes at the end; tree saves after
  5, 10, 15 decisions took 0.7, 6.0, 8.8 s. Mock worker: 773 sessions, 0 failed, 826 results applied (748 during a
  search), 226 requests dropped as stale after advance. The same game setup with `--llm off`: 19 decisions, lost
  at ply 38 (2.08 points per move). The mock worker's values are heuristics, so these two games compare plumbing,
  not strength.
- (b) `llm-search` with sandboxed `claude:claude-opus-5-5:xhigh` on the pilot game after 22 plies (Black to play;
  canonical symmetry 2, so every job was posed in a flipped frame): 30 s code-only warm-up, then 420 s at 16 threads
  with W=8 and at most 16 sessions. 231 events, 16 sessions, 16 accepted, 0 failed, all 16 applied during the search;
  4.08 USD (median 0.235 USD and 82 s per session, 36-261 s). Root evaluation after 129 s: E7 0.60, E6 0.28, others
  at most 0.04, Black winrate 0.10. The refute of the search's top move H7 (queued after 30 s) answered with the
  capture at E7 (White 0.88); H7's Q fell from 0.355 to 0.237 and it received no further visits. Root table
  before / after: H7 1.25M visits, q 0.368 (2.2M simulations) / J3 8.8M visits, q 0.341, H7 7.3M, 0.245, D1 4.8M,
  0.331, root q 0.247 (27.9M simulations).

Known limits at this node (all addressed by `move47::mcts-calib`, next section): v1's minimum root visits and
root prior noise needed a change in the engine's root selection; a prior floor for unconventional and scout moves
stood in. In smoke (b) the most-visited move at the end (J3) had no LLM evaluation of its own: the LLM's values
were far below the playouts' (White 0.68-0.95 after every evaluated Black move), so each evaluation lowered that
move's Q with `lam` = 0.5, and the session cap left 216 requests queued (E7's own child among them). Requests
dropped by the queue cap or as stale were not asked again in the same tree, and staleness after `advance` was
judged from the event's recorded path only.

Tests (no model): `python3 -m pytest -q tests/test_mcts_llm.py tests/test_mcts_llm_play.py -p no:cacheprovider`
(about 20 s): frame mapping for a position with canonical symmetry 2, events from a search turning into jobs
applied during the search, the DAG cache in another orientation (no session), symmetric nodes sharing one job,
duplicate events, stale requests dropped after `advance`, rate limit / overload / exception with backoff, W
halved and raised again, failure classes from session logs, refute and lessons, job and queue caps; the play loop
against a fake arena (the new root keeps its exact visit count, per-move records, learner calls), resume after a
crash from the saved tree, the code-only ablation, `--learn` without and with `mcts.hl`, the runner's `mcts`
adapter command and a full runner game against `random` with the mock worker.

## MCTS v2 online learning (`mcts/hl/`, node `move47::mcts-hl`)

MISSION.md section 5, Heuristic Learning. After every decision the learner refits what the engine
reads at its next search: (a) the policy weights shared by the tree prior and the playout policy,
(b) a value model, (c) the mixing weights `lam` and `beta`. The targets come only from our own
search (visit distributions and backed-up Q of well-visited nodes) and our own game results.
Nothing from KataGo enters.

```python
from mcts.hl import OnlineLearner
learner = OnlineLearner(run_dir, base=None)          # base: Weights / path, default default-v1; resumes
eng = MCTS(board, weights=learner.provider, learner=learner)    # provider.get() -> current version
r = eng.search(time_s=30, threads=32)                # the engine calls learner.observe(...) per node
learner.update()                                     # refit + gate: a new version, or why not
eng.advance(r["best_move"]); eng.advance(reply)      # the tree is kept; the next search uses the new version
learner.observe_external(position, "llm", priors, value)   # an LLM evaluation of a node arrived (M8)
learner.observe_game(+1, "B")                        # our result (+1 / -1, or "B+3.5", "W+R"), our colour
```

| part | design |
|---|---|
| samples | Every node of the root's subtree with at least `observe_min_visits` (256) visits after each search: position, visit distribution, q. Additive change in `mcts/tree.py`: a sample also carries `n`, `key`, the playout-only `q_playout` and the external part `q_ext` / `n_ext`. `_observe` passes these only to a learner whose `observe` takes `**kwargs`; plain 4-argument hooks are unchanged. The ring buffer holds 30 000 node keys, and the latest observation of a node replaces the older one. The held-out split is a fixed hash of the node key (20%), so a position is on the same side in every update, game and process. |
| (a) policy | Linear softmax over the legal moves (the tree's edge set), logit = w·f / T. f is the 1148 features of FEATURES.md with ladders on. Expert iteration: cross-entropy to the visit distribution, with sample weight `min(8, sqrt(n / 256))`. Two L2 terms: 1e-3 toward the current version (smooth steps) and 1e-3 toward the base version (`l2_base`, the anchor). L-BFGS (numpy only), warm-started from the current version, at most `fit_time` seconds. Each fit trains on a uniform subset of at most 16 000 of the buffer's training nodes. |
| gate | The candidate becomes the next version only if all three hold: (1) its weighted cross-entropy on the held-out nodes is lower by more than 1e-4 nats; (2) it keeps every tactical guard; (3) its cross-entropy on the regression positions is at most 0.02 nats above its parent's and 0.05 above the base's. Otherwise the old version stays, and `update()` says why. The `top` guards are also training rows (one-hot on the guard move, weight 8). If a guard is still lost, the fit is redone with the anchors 8x and then 64x heavier. |
| options, off | `playout_temp="match"` refits the playout temperature to keep default-v1's playout entropy. `censor=True` fits below the root only over the visited moves, because progressive widening gives a never-admitted move zero visits whatever its merit. Both lost or showed nothing in the A/Bs below. The prior temperature is absorbed by w. |
| (b) value | Logistic regression on 9 cheap inputs: mean result, mean score and score z-value of 16 playouts with the base weights; the area score now; the stage; own and opponent stones in atari. Fitted to the training nodes' playout-only q (soft labels) and to the game results of finished games (weight 0.5). On held-out nodes it is compared with the short playout estimate (the same 16 playouts). Stored in `state.json`. Not wired into the engine (below). |
| (c) lam, beta | From nodes with an external evaluation of source `llm`. At `observe_external` the learner records the external value and priors, the current version's priors, and a playout estimate of the node (32 playouts, or the caller's `q_playout`). When the node is observed again with at least 2x its visits (and at least 256), the learner pairs that evaluation with the deeper result: the playout-only deep q and the final visit distribution. `lam` is a closed-form least-squares fit of `(1-lam)·v_llm + lam·z` against the deep q. `beta` is a grid maximum-likelihood fit of `(1-beta)·p_learned + beta·p_llm` against the visit distribution. Both are shrunk toward 0.5 with 10 pseudo-pairs, clipped to [0.1, 0.9], and written as `params.lam/beta` once 20 pairs exist. |
| persistence | In the run dir: `state.json` (current version, counters, value model, last mix fit), `weights-vNNN.json`, `samples.jsonl`, `external.jsonl`, `games.jsonl`, `value-inputs.jsonl` and `updates.jsonl` (one line per update). v000 is the base. Every accepted version is a normal weight file with an `hl` block: parent version, digest and file, sample counts, train / held-out / regression metrics, guards, reason. Writes are atomic and serialised by a file lock. The provider re-reads `state.json` when another process has advanced the run, and `OnlineLearner(run_dir)` resumes from it. |
| threads | The learner caps numpy's OpenBLAS pool at 1 thread (`blas_threads`, process-wide). Without the cap, one update kept on average 30 cores busy, with up to 65 threads running (busy-waiting). With it, the update uses 1.6 cores, and the value inputs' playouts use `threads` threads. An update takes 2.4 and 2.5 s on average in the two final runs (max 4.9 s) with a 30 000-node buffer. |

**Regression set** (`mcts/regression/`, tracked, 0.25 MB):
- `guards.json` holds 9 hand-written tactical positions. Kind `top` (one of the moves must stay among the k = 3 highest priors): capture 4 stones, capture 1 stone, capture 2 on the edge, save a group in atari, extend a stone out of atari (black and white to play). Kind `avoid` (the move must stay out of the top 5): a 7-stone self-atari, a 3-stone self-atari on the edge, filling an own eye. default-v1 ranks every `top` move first.
- `positions.json` holds 150 positions from 6 code-only self-play games with default-v1 (0.3 s/move), each with the root visit distribution of a fresh 200 000-simulation search (`hl-regression-build`).
- `heldout-selfplay.json` holds 300 held-out nodes (at least 1000 visits) of the run that produced the shipped weights (`hl-export-heldout`).
- `mcts/weights/hl-selfplay-20261007.json` is that run's last version, hl-v217. Tests check that it keeps every guard and beats default-v1 on the held-out nodes: cross-entropy 2.463 vs 2.888, top-1 0.34 vs 0.27. On the regression positions it is level with default-v1 (2.682 vs 2.682).

```bash
python3 -m mcts learn-selfplay --run <dir outside Chandra> --games 8 --time 1.0 --threads 16 [--base FILE] [--hl KEY=VALUE]
python3 -m mcts weights-ab --a FILE --b FILE --games 40 --time 1.0 --threads 8 --procs 2 [--run DIR] [--a-value-model STATE]
python3 -m mcts hl-report --run DIR [--every 25] [--json]     # every version: held-out CE, regression CE, guards, reuse
python3 -m mcts hl-guards --weights FILE                       # guards + regression CE of one weight file
python3 -m mcts hl-export-heldout --run DIR                    # -> mcts/regression/heldout-selfplay.json
python3 -m mcts hl-regression-build                            # -> mcts/regression/positions.json
```

**Measured** (host anta, 2026-10-07; code only, 9x9, komi 7.5; other users' load 15 to 30 threads; run
dirs under `runs/move47/hl-20261007/`).

*(i) Online learning, final defaults.* Two runs with
`learn-selfplay --games 8 --time 1.0 --threads 16 --hl fit_time=4`, seeds 4 and 5. One tree per
game, and an update after every decision. Every version is evaluated on its run's final held-out
nodes (6023 and 5901, never trained on) and on the regression positions:

| run | version | held-out CE | held-out top-1 | regression CE | guards |
|---|---|---|---|---|---|
| seed 4 | default-v1 | 2.887 | 0.264 | 2.682 | pass |
| seed 4 | hl-v050 | 2.695 | 0.285 | 2.587 | pass |
| seed 4 | hl-v100 | 2.642 | 0.297 | 2.620 | pass |
| seed 4 | hl-v150 | 2.578 | 0.306 | 2.639 | pass |
| seed 4 | hl-v217 (last) | 2.429 | 0.341 | 2.682 | pass |
| seed 5 | default-v1 | 2.832 | 0.278 | 2.682 | pass |
| seed 5 | hl-v100 | 2.619 | 0.299 | 2.601 | pass |
| seed 5 | hl-v173 (last) | 2.455 | 0.336 | 2.649 | pass |

Seed 4 ran 551 updates and accepted 217; seed 5 ran 526 and accepted 173.

*(ii) A/B against default-v1, code-only MCTS.* Both sides get the same time per move; colours
alternate; a side resigns below 3% after move 40. Each engine keeps its own tree through the game.
Win rates are for A, with Wilson 95% intervals.

| A | how A was made | games | s/move | threads | A wins | win rate | 95% CI |
|---|---|---|---|---|---|---|---|
| hl-v217 (seed 4) | online, final defaults | 40 | 1.0 | 8 x 2 procs | 19 | 0.475 | 0.329-0.625 |
| hl-v173 (seed 5) | online, final defaults | 40 | 1.0 | 8 x 2 | 24 | 0.600 | 0.446-0.737 |
| both, pooled | | 80 | 1.0 | | 43 | 0.538 | 0.429-0.643 |
| hl-v334 (learn-final) | online, played-out games, no base anchor | 60 | 1.0 | 8 x 4 | 21 | 0.350 | 0.242-0.476 |
| hl-v070 (learn-keep) | online, no anchor, newest-12k training window | 40 | 0.5 | 8 x 2 | 23 | 0.575 | 0.422-0.715 |
| hl-v084 (learn-match) | as learn-keep, playout temperature refit | 40 | 0.5 | 8 x 2 | 14 | 0.350 | 0.221-0.505 |
| learn-final's buffer, one fit | anchored to default-v1 | 40 | 1.0 | 8 x 2 | 16 | 0.400 | 0.263-0.554 |
| same, under 45 stones | diagnostic | 40 | 1.0 | 8 x 2 | 22 | 0.550 | 0.398-0.693 |
| same, censored targets | diagnostic | 40 | 1.0 | 8 x 2 | 20 | 0.500 | 0.352-0.648 |
| 4 default-v1 self-play games, one fit | anchored to default-v1 | 40 | 1.0 | 8 x 2 | 26 | 0.650 | 0.495-0.779 |
| default-v1 + value hook | value model as an external value | 40 | 0.5 | 8 x 2 | 5 | 0.125 | 0.055-0.261 |

How the rows set the defaults:
- **Without the base anchor, the versions drift.** learn-final kept improving on its own held-out nodes (CE 2.263 → 1.647, top-1 0.36 → 0.61). Its regression CE rose at the same time (2.68 → 3.44), and its last version lost (0.35, interval below 0.5). Refitting toward the previous version alone has no fixed point, and the targets come from the drifted versions' own searches.
- **With the anchor, the drift stops.** The regression CE stays at or below default-v1's. The final online versions are level with default-v1 (pooled 0.54).
- **The playout-temperature refit lost** (0.35), so it is off.
- **Censoring showed no gain** (0.50 vs 0.40, inside each other's intervals), so it is off.
- **Learn-selfplay resigns again** (3%, after move 40). A run whose games were played out to the end gave endgame-heavy data, and no fit on such data beat 0.55.
- **The training subset is uniform.** The first round trained on the newest 12 000 nodes and gated on held-out nodes from the whole buffer. After game 3 that stalled acceptance at 2-4 versions per game.
- The diagnostic one-off fits are kept with their scripts in the run dir's `scripts/`; they are not tracked.

*(iii) Tree reuse plus learning.* In the two final runs a new weights version was picked up
between consecutive moves 213 and 170 times. Every time, the tree was kept: the search started
from the reused root with on average 391 000 and 302 000 visits. 543 of 551 and 518 of 526 searches
started from a reused root; the rest are game starts.

*Value model (b).* Mean squared error on the held-out nodes (vs their deep q), against the short
playout estimate from the same 16 playouts. Seed 4: 0.025 vs 0.050. Seed 5: 0.020 vs 0.024. Against
the game results: 0.108 vs 0.187 and 0.122 vs 0.149. So it predicts the deep q better than the
short estimate. It is not wired in. The only route into the engine without a C change is an
external value (`on_expand` → `set_external`), which the engine mixes at weight `1 - lam` like an
LLM value. Through that route it lost 5 of 40 games against the same engine without it.

*lam / beta (c).* Code-only runs have no external evaluations: 0 pairs, so the defaults (0.5 / 0.5)
stay and no version carries `params.lam/beta`. The fit is tested on synthetic data. Through the
learner and the engine it recovers lam 0.8 and beta 0.2; called directly, lam 0.3 and beta 0.75.

Tests: `python3 -m pytest -q tests/test_mcts_hl.py -p no:cacheprovider` (24 tests, about 18 s):
- the interface (five methods, provider, extras from the tree, SGF result strings);
- a new version is picked up between moves while the tree is kept;
- learning lowers held-out CE and writes a versioned file;
- the gate rejects a worse fit, a fit that loses a guard, and a fit that is worse on a regression set;
- the base anchor bounds drift: repeated updates converge to the one-shot anchored fit, and without the anchor they keep moving;
- the playout-temperature refit;
- state persists and resumes in another process, and the provider sees that process's version;
- the ring buffer;
- lam / beta recovery;
- the value fit and the value hook;
- censored targets;
- the regression files;
- the shipped weights against the guards and the held-out nodes;
- the gradient against finite differences;
- the CLI (learn-selfplay, hl-report, weights-ab, hl-guards).

Not done here:
- [HOLE] lam / beta have not been fitted on real LLM evaluations; that needs the M8 play loop's `observe_external` calls.
- [HOLE] The online learner is not shown to make play stronger. Its versions predict their own search better, but at 8 games of 1 s/move they are level with default-v1. One step of expert iteration from default-v1's own self-play did better (0.65, borderline).
- [FUTURE] A value-model slot in the C leaf evaluation. Refits during a long search (MISSION.md section 5 says "periodically during search"; here only after decisions). A/Bs at the mission's time control and against the KataGo ladder (M9).
- The regression positions come from default-v1's own searches, so they favour default-v1. They proved a useful brake on drift, not a strength measure.

## MCTS v2 model values: root breadth, stand-ins, calibration, decision (node `move47::mcts-calib`)

MISSION.md section 5, node `move47::mcts-calib` (M8b). The mcts-llm smoke chose a root move without
a model value, because every model value pulled its move's Q down. This node makes model values
enter the search on the same footing for every move, puts them on the playout scale, and lets the
decision fall on an evaluated move.

| part | where | what |
|---|---|---|
| root breadth | `csrc/tree.c` select_edge, `MCTS.set_root_breadth` | v1's minimum root visits, scaled for millions of simulations: a root move the model proposed ("candidate": llm / more edges) is selected first while its visits are below max(`root_min_floor` 64, `root_min_frac` 1% of the root's visits); unconventional and scout moves ("explore") below max(32, 0.5%). The service sets the classes from the DAG's LLM edges whenever the root gets an evaluation; `advance` / `set_root` clear them; they are saved with the tree. Replaces the 0.05 prior floor of mcts-llm (`root_explore_prior`, now 0 = off). |
| root noise | select_edge | v1 semantics: root priors p -> (1 - x) p + x / moves. `MCTSConfig.root_noise` 0 (code paths as before); `play` and `llm-search` pass `--root-noise` 0.25 (v1's value). |
| re-armable hooks | `MCTS.rearm(key)` | clears the node's hooked flag: it fires again on its next visit (if within `hook_depth` or at `n_thr` visits). The service records the nodes of requests dropped by the queue cap, as stale, or whose result arrived stale, and re-arms them once the queue has a quarter free and the node is in the root's subtree; a re-fired event is then taken as new (from the DAG if it holds the evaluation). |
| subtree query | `MCTS.in_subtree(key)`, `subtree_mask()` | exact reachability from the current root through any move order (`mc_tree_reach`, safe during a search). One mark per root is reused: positives stay valid until the root moves, nodes created after the mark were created by simulations from this root, negatives are re-checked on a mark older than 2 s. The service uses it whenever a request's recorded path does not run through the root (after `advance`, transpositions, truncated paths). |
| `searching` | `MCTS.searching` | public; the service's `searching` reads it (the caller's flag still works). |
| stand-in values | select_edge, `MCTS.standin_value`, `root_stats` | a child without an external value (nx = 0) is compared through a stand-in X: the mean external value of its evaluated siblings (side to move at the children), else the negated value of its parent (its own, backed up, or its own stand-in: recursively the nearest evaluated ancestor). Q = (1 - lam) X + lam Q_playout for every sibling; the parent's own FPU uses the same footing. `MCTSConfig.standin` = "siblings" (default) / "ancestor" / "off". Only selection (and the reported q) uses it; nothing is backed up. `root_stats` reports q (as selection sees it), q_raw, q_playout, v_ext (the move's own model value, mover's winrate), evaluated, standin, breadth. |
| priority | `LLMService.boost`, `tick` | every 5 s the 3 most-visited root moves without a model value get class TOP (above scouts / refute / lessons, below the root's own expand), creating the request if it was never raised, was dropped or failed; a root child with under 0.2% of the root's visits ranks with the deeper nodes. |
| decision | `mcts/decide.py` | rules: `most_visits_evaluated` (the most-visited move has its own model value), `evaluated_among_top` (it has none: the most-visited move that has one among the top 4 with at least 20% of the leader's visits), `most_visits_unevaluated` (none of them has one), `most_visits` (`--decide visits`, code-only). While the leader waits for its value and a request for it can still run, the decision boosts it and searches on in chunks for at most `--decide-extend` (120 s; a tenth of the move time per chunk in `play`). Each move record has `decision` = {real, rule, lead, extension (resolved / changed / time / no_request), extended_s}. |
| calibration | `hl/mix.py fit_calib`, `OnlineLearner.fit_calibration`, `MCTS.set_calibration` | model values enter the tree as sigmoid(a logit(v) + b). The learner fits (a, b) by logistic regression with soft labels: model value of a node (`observe_external`) against that node's playout Q after a deeper search (its sample's q_playout, at least `calib_min_visits` 1024 visits, observed after the evaluation), with a ridge toward the identity worth `calib_n0` = 10 pairs; a in [0.05, 4]. `update()` writes params `calib_a` / `calib_b` (with lam / beta, lam now fitted on the calibrated values) once 5 pairs exist; the engine picks them up with the weights and `set_calibration` re-calibrates the values already in the tree (each node's own value and the path sums of its one-time backup, exactly). `llm-search --calib online` refits it every `--calib-every` 60 s from an observe-only learner in `<run>/hl`. |
| races | `llm.py` | a request leaves the running set only after its results are applied (also on the DAG-cache path), an inbox event counts as busy until triaged, and insert + cap-drop in `_enqueue` are one locked step (ranked by the visits seen when last ranked), so `wait_idle()` means applied and the queue never shows more than `queue_cap`. |

```bash
python3 -m mcts llm-search --sgf game.sgf --upto 22 --run <dir> --worker <Opus 5.5 xhigh spec, as above> \
    --wrap "$PWD/bin/worker-sandbox {jobdir}" --time 720 --warmup 30 --threads 16 --llm-workers 16 \
    --max-llm-jobs 118 --n-thr 200000 --calib-every 60 --decide-extend 180 --drain 600
python3 -m mcts llm-search ... --llm off          # the code-only control (same engine settings and chunks)
```

**Smoke** (2026-10-07, run dir `runs/move47/mcts-calib-20261007/` next to the Chandra checkout, scripts
`smoke-opus.sh`, `smoke-control.sh`, summary `summarize.py`): the pilot game after 22 plies (Black to play),
the position of mcts-llm smoke (b); 30 s code-only warm-up, then 720 s of search at 16 threads with sandboxed
Opus 5.5 xhigh (the worker spec of the section above), W=16, cap 118 sessions, n_thr 200000, calibration refit every 60 s, decision
extension up to 180 s; the code-only control ran concurrently with the same engine settings for 900 s.

| time (s) | sessions / cost | root moves with own value | calib a, b | top root moves: visits, q (* = stand-in), own model value (Black's winrate) |
|---|---|---|---|---|
| 0 (warm-up) | 0 | 0 | 1, 0 | H7 2.14M 0.403; D2 16k 0.402; E6 9k 0.384 |
| 121 | 23 / 1.57 USD | 4 | 0.78, -0.16 | H7 9.31M 0.318 v0.198; B8 214k 0.319 v0.284; E6, D8, G8, E7 102k each (1% minimum) 0.276-0.311* |
| 242 | 38 / 7.05 | 11 | 0.65, -0.30 | H7 17.3M 0.343 v0.304; B8 312k 0.350 v0.354; E6 187k 0.336 v0.304; E7 187k 0.298* |
| 371 | 53 / 11.35 | 16 | 0.60, -0.29 | H7 19.3M 0.357 v0.320; B2 1.71M 0.396 v0.400; B8 1.47M 0.303 v0.367 |
| 624 | 81 / 23.92 | 26 | 0.50, -0.22 | H7 25.3M 0.371 v0.345; B2 6.74M 0.343 v0.413; B8 1.47M 0.317 v0.385 |
| 893 (decision) | 104 / 32.52 | 35 | 0.47, -0.20 | H7 27.4M 0.366 v0.352; B2 6.74M 0.355 v0.417; E1 6.22M 0.344 v0.390; E3 3.08M 0.386 v0.417; B8 1.47M 0.318 v0.390; E7 475k 0.296 v0.267 |

- Decision: H7 by `most_visits_evaluated` (H7's own model value: White 0.85, calibrated to 0.352 for Black);
  no extension was needed: the boost kept the most-visited root moves evaluated (35 boosts). The 12 most-visited
  root moves all had their own value; 35 root moves in all. The root's evaluation: E7 0.55, E6 0.28, Black 0.12
  (mcts-llm: E7 0.60, E6 0.28, 0.10); E7 got its value this time (White 0.93) and its 1% minimum (475k visits).
- Sessions: 104 (103 expand, 1 refute), 104 accepted, 0 failed, 43.21 USD with the 16 sessions that finished
  after the decision (no new sessions after it; they finished in the drain, the last after 844 s); median 117 s
  and 0.31 USD per session. 139 requests for deeper nodes were still queued at the decision. Wall time to the
  decision 893 s for 720 s of search (the pause between 60 s chunks grew from 0.5 s to 15-25 s after about
  4 minutes, when about 19M simulations had filled the 20M-node tree, so eviction most likely ran at each chunk
  start; not measured separately); 45.3M simulations.
- Calibration learned on the run's 52 (model value, deeper playout Q) pairs: a = 0.468, b = -0.203 (unshrunk
  0.303, -0.060), squared error against the deeper playout Q 0.0490 with the identity, 0.0039 with the map. The
  model's values after Black moves (White 0.76-0.95) enter as 0.58-0.75. lam / beta kept their defaults: 19
  matched pairs with a deeper search of at least twice the visits (20 needed).
- Control (code only, 900 s, 65.4M simulations): H7 55.9M visits, q 0.394; D2 6.7M 0.353; C7 1.5M 0.353. Same
  move as the hybrid.
- mcts-llm smoke (b) for comparison (W=8, cap 16 sessions, no calibration, no stand-in): J3, a move without a
  model value (8.8M visits, q 0.341, prior 0.001), most visited at the end; 216 requests still queued, E7's child
  among them.

Tests (no model): `tests/test_mcts_calib.py` (17: root breadth and its persistence, root noise, re-arm, exact
subtree query incl. during a search and another move order, `searching`, stand-in values and their sign, the
lam = 0 sign check that unevaluated moves do not win by default, the decision rules and the bounded extension,
the calibration fit on synthetic data, the learner writing calib params and the engine applying them, exact
re-calibration of values in the tree, the service's root breadth, boost, re-arming of dropped requests, exact
subtree in the service) and the two race tests in `tests/test_mcts_llm.py`.

Limits: the calibration target is the deeper search's playout Q, so it puts model values on the playout scale
rather than judging which is right, and lam fitted against the same target leans toward the playouts [HOLE];
a stand-in is used for selection only (nothing is backed up with it); re-calibration corrects each value's
one-time backup exactly, while values a simulation carried up from an evaluated leaf keep their old map; the
decision thresholds (top 4, 20% share, extension 120 s) are not tuned.

## Offline judge and the code-only ablation (node `move47::mcts-ablation`)

MISSION.md section 5, node `move47::mcts-ablation` (M9a): measurement tools and a small code-only baseline. The
full system (model + MCTS + learned heuristics) is measured later, in `move47::mcts-strength`.

**Offline judge** `scripts/judge_position.py`: grades given moves of an SGF position with the strong net through
kgservice (`bin/kg-client`; a live backend is needed, e.g. from `scripts/arena_up.sh`). Per visit count it prints
JSON: KataGo's best move and lead (side to move), the top moves, and for each graded move its rank in KataGo's
list, its policy prior and rank, and the points lost (best lead minus the lead after the move, from a search of the
child position with a quarter of the visits, at least 100; `gotree.judge.judge_root`). Measurement only: its
output never enters a search, prompt, memory or weights.

```bash
python3 scripts/judge_position.py --sgf game.sgf --upto 22 --moves H7,E6,C2 --visits 1600,20000 \
    [--path-root <dir: print paths relative to it>] [--out FILE]
```

**Ablation driver** `scripts/ablation_play.py --run <dir outside Chandra> --plan plan.json`: parallel game
streams, each a list of segments (one arena run per segment: arena, opponent, games, optional colour), every game
exactly `mcts play --llm off --learn` (mcts.play's parser, Player and play_games), but all streams share one
`OnlineLearner` in `<run>/hl` with update() serialised. Separate `mcts play --learn` processes cannot share one
learner directory: each process numbers new versions from its own memory, so two processes can write the same
`weights-vNNN.json` (reported to the owner of `mcts/hl`). `--dry-run` prints each segment's settings. Report:
`scripts/ablation_report.py <run> [--format md|json] [--path-root DIR] [--out-dir DIR]` (per opponent: W-L,
Elo with a 95% interval from goarena.rating over the rated games, review point loss per move, blunders, match
rate, seconds and simulations per move, the weights version per game; the v1 pilot and the ply-22 judge for
comparison).

**Measured** (2026-10-07, host anta; run dir `runs/move47/mcts-ablation-20261007/` with `plan.json` and
`launch.sh`; evidence `results/move47/paper_move47/evidence/mcts-ablation-20261007/` and `.../judge-ply22/`).
Code-only MCTS v2 with online learning, 30 s/move, 16 search threads per game, two parallel streams (lv7 x6 then
k1-full as Black; lv8 x6 then k1-full as White), one shared learner; arenas: `ladder` (lv7/lv8, b10c128 referee
and reviewer) and `kata1` (k1-full, strong-net reviewer); adjudication on in both. 14 games, 2 h 23 min wall.

| opponent | W-L | Elo, 95% CI | point loss / move (reviewer) | blunders (>= 5) | match rate |
|---|---|---|---|---|---|
| lv7 (1850) + lv8 (2064), pooled | 1-11 | 1596 [1320, 1872] | | | |
| lv7 | 1-5 | | 1.607 over 212 moves (b10c128) | 20 | 0.259 |
| lv8 | 0-6 | | 2.992 over 127 moves (b10c128) | 26 | 0.197 |
| k1-full | 0-2 (B 3.877, W 1.008 per move) | | 2.377 over 44 moves (kata1) | 4 | 0.318 |
| v1 pilot vs k1-full (Opus 5.5 xhigh / gotree, 737 s and 10.77 USD per move) | 0-1 | | 1.214 over 19 moves (kata1) | 0 | 0.263 |

- The Elo is the arena's own fit (goarena.rating, prior centred on the opponents' mean Elo, sd 350) over the 12 rated
  games; with one win it still leans on that prior, and the tiers' own calibration errors (lv7 +-89, lv8 +-107) are
  not propagated.
- The learner accepted 157 of 383 updates (default-v1 -> hl-v157; every game's first and last version are in the
  report). On the run's final held-out nodes: cross-entropy 2.583 -> 2.277, top-1 0.33 -> 0.41; regression CE
  2.682 -> 2.595; guards pass. The one win came at hl-v119..hl-v137; 12 games say nothing about a trend.
- 87 of 383 moves searched longer than 31 s (up to 59 s): the eviction pause at the 20M-node cap counts in the
  move's search time.

Tests (no GPU, no model): `tests/test_judge_position.py` (the judge on `tests/fake_katago.py`: output fields, loss =
best lead minus lead after, illegal and bad moves), `tests/test_ablation_driver.py` (two streams against two
in-process arenas share one learner: one update sequence over both streams' decisions, colours, tokens kept out
of the segment metadata; the report reads the run back), `tests/test_arena_profiles.py` (above).

## MCTS v2: learning from model reasoning plus search (node `move47::mcts-llm-hl`)

MISSION.md section 5, principle paragraph: we do not train an MCTS from scratch. The model proposes
candidates, values and lessons; the search tests them over millions of simulations; the learner distils what
the combined search agrees on into explicit heuristics (weights, and readable rules the model writes) that guide
the next searches, game after game. The code-only learner of `move47::mcts-hl` is kept as the ablation.

```bash
# hybrid self-play with the full loop (no arena needed): model expansion, learning, a heuristic job per decision
python3 -m mcts hybrid-selfplay --run <dir outside Chandra> --games 3 --max-plies 18 \
    --start empty --start game.sgf:16 --time-per-move 210 --threads 20 --llm-workers 16 \
    --worker <Opus 5.5 xhigh spec, as above> --wrap "$PWD/bin/worker-sandbox {jobdir}" \
    --learn --heuristics [--hl-dir <shared learning state>] [--hl KEY=VALUE] [--max-cost USD]
# the same loop in arena games and on one position
python3 -m mcts play ... --learn --heuristics
python3 -m mcts llm-search ... --heuristics            # one heuristic job after the decision
python3 -m mcts hl-hybrid-report --run <dir> --code-search 200     # the evidence tables below
python3 -m mcts hl-book --dir <dir>/hl                              # the heuristics book as markdown
```

| part | where | what |
|---|---|---|
| hybrid targets | `hl/learner.py` (e), `tree.py` | samples observed while the model service feeds the search carry `hy` (and `xp` when the node itself has model priors); with `hybrid` on (default) the held-out split used by every gate keeps only hybrid samples once there are `min_heldout`. Play loops with the model on add a **test split** (`test_frac` 0.1, a second independent hash of the node key) that no fit and no gate ever sees; reports measure on it. `hybrid=False` (or `--llm off`) is the code-only path. |
| distillation | `hl/learner.py` (f) | at nodes the model evaluated (`observe_external`, the latest per node) the prior is also fitted to the model's candidate priors, as a second CE term with relative weight λ; λ is chosen from `distill_grid` (0, 0.1, 0.3, 1, 3) every `distill_every` (5) updates by held-out CE on the hybrid visit targets (so the model's knowledge only enters as far as it helps predict what the combined search concludes). `model_agreement()` reports the learned prior against the model's priors at held-out (or test) evaluated nodes: CE, top-1, mass on the model's moves, rank of its top move. The model's calibrated values are also soft labels of the value model (b) (`ext_value_weight`). |
| rule language | `gotree/heurdsl.py` | colour-relative 5x5 / 3x3 patterns with wildcards (own, opponent, empty, off-board, not-own, not-opponent, any stone, on-board, anything), matched in all 8 orientations, plus conditions: captures, liberties after the move, atari, self-atari, escape, ladder capture, failing ladder escape, an adjacent own / opponent chain with given liberties and size, line, distance to the last move. Pure Python (it runs in the worker sandbox); strict: unknown fields or conditions, bad characters, a misplaced move cell, weights outside ±[0.05, 3], fewer than 2 constrained cells (counting 2 per condition), or matching more than 20% of the legal moves of the job's surprise positions are refused with a message the worker can act on. Nothing a model writes is executed. |
| rules in the prior | `mcts/rules.py`, `csrc/rules.c`, `weights.py`, `features.py`, `tree.py` | FEATURES.md section "Model-written rules": compiled masks and bounds, added to the tree priors at expansion only; a weight file carries its rules; `move_logits` / guards / regression metrics use them too. |
| heuristic job | `gotree/jobs.py` kind `heuristic`, `gotree/gtree.py`, `hl/heuristics.py` | after each decision (or every `--heuristics-every`), `HeuristicLoop.after_decision` takes the well-visited nodes (at least `--heuristic-min-visits`, 2048) of the decision's search and ranks them by KL(final visits ‖ learned prior) and, at nodes the model evaluated, KL(visits ‖ model prior), weighted by sqrt(visits / 20 000), one per canonical position; the top 6 become surprises S1..S6: position card, the moves by visits with winrate, learned prior and rank, model prior and rank, the book rules matching them, the learned prior's and the model's preferred moves, the main line. With them the job gets the lessons that apply (L1 shapes near the preferred moves, L2 principles) and the book (active rules with weight now / proposed, held-out gain, hits and provenance; the last 12 rejected proposals with their reasons; the adjustable tactical weights). Tools: `gtree card/window/try/ladder --pos S2`, `gtree rule-test rules.json` (where each rule matches in every surprise, the preferred moves starred, the share of legal moves), `gtree submit`. Output: up to 4 rules (name, readable text, pattern, conditions, weight, rationale, evidence, lessons cited) and 6 nudges (feature or rule, delta ≤ 1, rationale). |
| gate | `OnlineLearner.consider` | nudges: the nudged weights against the current ones on the held-out hybrid targets (no refit); kept if CE falls by more than 1e-4 nats and guards and regression set pass; an accepted nudge also shifts its feature's anchor. Rules: refused without a fit if they duplicate a book rule or repeat a rejected one, if the book is full (48), if they match more than 20% of the legal moves of 600 training positions, or nothing in them. Otherwise the current weights plus the rule, with only the rule's weight fitted (from the model's weight; all others frozen; same training objective incl. distillation), against the current weights on the held-out targets: kept if the gain exceeds 1e-4 nats, the lower end of a 90% bootstrap interval (over searches once there are 5, else over nodes) is above 0, the rule matches at least 5 held-out positions from 2 searches, the tactical guards hold and the regression set does not get worse (the mcts-hl tolerances). Several kept rules from one job are fitted together and kept together if that is no worse than the best one alone. An accepted rule's model weight becomes its anchor; the next `update()` refits all weights jointly. |
| book | `hl/book.py` | `heuristics-book.json` (+ `book/book-vNNN.json` per change, `heuristics-book.md`): each rule with its text, pattern, conditions, the model's rationale, provenance (job id, decision label, surprise ids and positions, lessons cited), weight history (proposed, then each refit that moved it), held-out effect at acceptance (CE without / with, gain and interval, gain at the model's own weight), hit counts in the learner's samples (positions, moves, top-move hits, visit share of matched moves, held-out positions); every proposal with status and reason; accepted nudges; lessons -> rules. The other direction is in the lesson memory (`memory.db`, table `lesson_rules`). |
| play loop | `play.py`, `llm.py` | `--learn` with the model on puts the learner in hybrid mode; `--heuristics` builds the loop: the job is queued on the same service (priority of root breadth, kept across new roots and games like `abstract`), runs like any session, and its validated answer is gated by a background thread while the next search runs (update and gate never interleave: one fit lock). The learning state (`<run>/hl` or `--hl-dir`) carries across moves, games and runs; `hybrid-selfplay` plays both sides with one tree per game. Records: `moves.jsonl` (per decision: the heuristic request with its surprises, the update with held-out CE, λ and model agreement, the session cost), `heuristics.jsonl` (requests and gate reports), `hl/proposals.jsonl`, `llm-jobs.jsonl` (kind `heuristic`). |
| several processes | `hl/learner.py` | one learner dir may be shared by several processes (e.g. `--hl-dir`): a version is committed under the file lock after re-reading `state.json`; if another process committed a version while this fit ran, the candidate is dropped as superseded (it was gated against an older parent) instead of overwriting; version files are created exclusively (`os.link`, never replaced); every state save first adopts the newer state on disk; writers of the book are serialised by `.gate.lock`. |
| usage limits | `llm.py`, `play.py` | a session's `rate_limit_event` (status rejected, `resetsAt`) and "session limit" texts classify as rate limits with their reset time, so dispatching pauses until the reset; `hybrid-selfplay` waits before a decision while the service is paused for a limit (`--wait-for-model`, 6 h) instead of searching without model input, and records `model_input` / `waited_for_model_s` per decision. |
| move time | `tree.py` | `search(time_s)` counts from its entry, so an eviction at the start of a search is part of the move's time; a mid-search eviction runs only if the remaining time exceeds 1.5x the last eviction's duration, otherwise the search goes on without storing new leaves (frozen) until the deadline and the next search evicts first. The result reports `gc_s` and `wall_s`. (Ablation run: 87 of 383 moves at 30 s took longer than 31 s, up to 59 s.) |

**Evidence** (2026-10-07, run dir `runs/move47/mcts-llm-hl-20261007/` next to the Chandra checkout: launch scripts
`run-hybrid.sh` (game 0) and `run-hybrid2.sh` (games 1-2), `rollback_modelless.py`, `bench_book.py`; the report
`hybrid/hl-hybrid-report.{md,json}` from `python3 -m mcts hl-hybrid-report --run hybrid --code-search 200`).
Hybrid self-play, 3 games of 18 decisions from the empty board, the pilot game after 16 plies and the
`mcts bench` midgame after 10 moves; 210 s of search per decision at 20 threads (median 12.5M, 19.2M and 18.8M
simulations per decision in games 0, 1, 2), sandboxed Opus 5.5 xhigh with W=16, a heuristic job after every
decision, one learning state for all three games. Sessions: 1 124 in the run (974 expand, 51 refute, 48 lessons,
51 heuristic jobs: median 255 s, 0.90 USD on average), 526.76 USD; with the 2-decision smoke (7.57 USD) and a first
attempt stopped after 5 decisions to fix a gate rule (38.59 USD, plus at most about 5 USD of sessions killed in
flight) 572.92 USD logged.

The workers' account hit its five-hour limit during game 0 (10:52): g0p16-g0p18 and six decisions of a first game 1
ran without any model session. The learning state was rolled back to the last decision with model input
(`hybrid/aborted-modelless/MANIFEST.json`: versions hl-v023-v025, 9 updates and the samples of those decisions
moved there; the three model-less decisions stay in game 0's record), the usage-limit handling above was added,
and games 1-2 were played from the rolled-back state (6 code files changed between the two parts, listed in
`code-sha256.txt` / `code-sha256-part2.txt`; the gate's logic did not change). When the new account's window ran
out at 14:19, the service paused until its reset and the loop waited 377 s before g2p9 instead of searching
without the model. In all, 51 decisions had model input.

*Proposals.* 48 heuristic jobs (12, 18 and 18 in games 0, 1, 2) proposed 114 rules and 31 nudges; 10 rules and
5 nudges were kept (game 0: 4 of 27 rules, 3 of 6 nudges; game 1: 3 of 44, 1 of 12; game 2: 3 of 43, 1 of 13).
Rejections: 104 rules whose held-out gain or its interval was too small, 2 with too few held-out matches (left
re-proposable), 1 repeat of a rejected rule, 26 nudges without held-out gain. No rule failed the guards or the
regression set; the validator at submit time refused over-broad rules, so none reached the gate. 13 links from
11 lessons to rules (the abstract jobs wrote 153 lessons).

| rule (job, decision) | the model's text | weight: proposed -> now | held-out gain at acceptance (90% CI) |
|---|---|---|---|
| R4 descend-past-parallel-pair-when-short-of-libs (g0p10) | when your two-stone line runs beside an opponent two-stone line toward the edge and your chain has two or three liberties, descend to the second line just past the end of their line to win the liberty race | +1.00 -> +0.70 | +0.0063 (+0.0012 .. +0.0119) |
| R5 extend-at-head-of-own-two-vs-contact (g1p1) | extend at the head of your two-stone line when an opponent stone already touches that point; otherwise they hane at the head of your two stones (cites L17, G18) | +0.90 -> +0.56 | +0.0024 (+0.0005 .. +0.0046) |
| R6 save-lone-armpit-stone (g1p8) | extending your lone 2-liberty stone out of the armpit of the opponent's connected bend is usually slow and heavy (cites G57, L59, L62) | -1.00 -> -0.85 | +0.0025 (+0.0002 .. +0.0046) |
| R9 slow-capture-of-abandoned-edge-stones (g2p16) | capturing 1-3 opponent edge stones they left in atari while playing elsewhere is usually slow; take the vital or big point first | -1.00 -> -0.71 | +0.0013 (+0.0004 .. +0.0022) |
| R1, R2 (g0p2, g0p3) | the third-line knight's move from a lone opponent stone in open space | +0.60 -> +0.64, +1.00 -> +0.34 | +0.0021, +0.0006 |
| R3 atari-on-runaway-lone-stone (g0p5) | ataris on a lone two-liberty stone that escapes the ladder usually just help it run | **-0.60 -> +0.57** | +0.0006 |
| R10 fill-own-knight-link-gap-in-centre (g2p18) | fill the gap of your own knight's-move link before they wedge | **+0.60 -> -0.14** | +0.0003 |

R3 and R10 kept their place as features but with the opposite sign: the search does not support what their
text says, and the book and the report flag it. At the model's own weight (no fit), 5 of the 10 kept rules
improved the held-out CE and 5 made it worse; the gate keeps a rule for what it identifies, with the weight the
data supports. The full book: `hybrid/hl/heuristics-book.md`.

*Prediction of the hybrid search on the test split* (3 391 nodes and 69 model evaluations whose keys no fit and no
gate ever used; paired differences with 95% cluster-bootstrap intervals over the 51 searches):

| weights | test CE | test top-1 | CE to the model's priors | top-1 vs model | mass on the model's moves | regression CE | guards |
|---|---|---|---|---|---|---|---|
| default-v1 (start) | 2.985 | 0.338 | 3.314 | 0.174 | 0.282 | 2.682 | pass |
| hl-v022 (end of game 0's model input) | 2.850 | 0.364 | 2.961 | 0.290 | 0.410 | 2.693 | pass |
| hl-v044 (end of game 1) | 2.619 | 0.408 | 2.927 | 0.203 | 0.433 | 2.640 | pass |
| hl-v065 (final: 10 rules, 5 nudges, online refits) | 2.581 | 0.419 | 2.898 | 0.217 | 0.451 | 2.655 | pass |
| refit on the final data with the rules | 2.580 | 0.411 | 2.780 | 0.304 | 0.469 | 2.677 | pass |
| the same refit without the rules | 2.592 | 0.410 | 2.822 | 0.304 | 0.458 | 2.660 | pass |
| the same refit without distillation | 2.580 | 0.416 | 2.900 | 0.188 | 0.452 | 2.655 | pass |

- final vs default-v1: +0.404 nats [+0.366, +0.445] on the hybrid targets; +0.416 [+0.333, +0.495] toward the model's priors.
- the book's rules: refit with vs without them +0.012 [+0.007, +0.018]; final vs the refit without rules +0.011 [+0.004, +0.018].
- distillation (λ chosen 11 times: 0 nine times, 0.1 twice; the final λ 0.1): +0.00002 [-0.0025, +0.0026] on the hybrid
  targets, +0.120 [+0.049, +0.209] toward the model's priors at test nodes the model evaluated.
- the online gate: 51 updates, 27 policy refits accepted (2, 11, 14 in games 0, 1, 2), 21 refused by the regression
  set (13, 7, 1: game 0's hybrid refits moved the prior away from the code-only regression targets by 0.02-0.11
  nats; later most refits passed and the regression CE ended below default-v1's), 3 without held-out gain.

*Code-only search on held-out positions* (200 test nodes with at least 20 000 visits, 100 000 simulations, 16 threads,
no model): agreement of the most-visited move with the hybrid search's: default-v1 0.425 (95% 0.359-0.494), final
0.425, the refit without rules 0.415, the refit with rules 0.460; differences +0.000 [-0.075, +0.075] (final vs
default-v1) and +0.045 [-0.025, +0.115] (refit with vs without rules). The learned heuristics predict the hybrid
search much better, but at this sample size they do not measurably change which move a code-only search picks.

*Cost of the rules in the hot loop* (`bench_book.py`, the 9x9 midgame, 16 threads, median of 5 interleaved 5 s runs):
the final book (10 rules) 92 234 vs 94 468 simulations/s without its rules (-2.4%); 17.9 vs 12.4 µs per expansion
(expansions 5.8% vs 4.1% of the threads' time). With the 4-rule book of game 0: -1.0%.

Tests (no model): `python3 -m pytest -q tests/test_mcts_llm_hl.py -p no:cacheprovider` (18, about 50 s): the rule
language (patterns in all orientations and both colours, conditions equal to the C features incl. ladders, the C and
Python matchers agree on random rules and positions); refusal of malformed, unsafe (unknown fields, code), over-broad
and out-of-range proposals at submit; the gate (a predictive rule kept with its book entry, provenance, weight
history, effect, hits, lesson links and markdown; a useless, an over-broad, an unseen and a guard-breaking rule
refused; nudges; too little evidence stays re-proposable); distillation (λ chosen by held-out fit raises agreement
with the model's priors); rules in the tree priors and not in playouts; `gtree rule-test / card --pos / submit`; the
heuristic loop with lesson links; `hybrid-selfplay` and the arena loop with a mock worker and the report; two
processes on one learner dir (an unbroken version chain, superseded fits dropped); usage-limit reset parsing and
the wait; a full tree does not stretch a move.

Not done here:
- [HOLE] Whether the learned heuristics make the system stronger is not shown: the test split measures prediction of
  the hybrid search (from the same 3 games), and code-only search with them agrees with the hybrid choices no more
  often (200 positions). Strength is node `move47::mcts-strength`.
- [HOLE] The code-only regression set refused 13 of game 0's 15 hybrid refits; the trade-off is visible (the
  unrefused refit of the final data has regression CE 2.677 vs 2.655) but a regression set built from hybrid
  searches does not exist yet.
- [HOLE] Distillation chose λ = 0 nine times of eleven: the model's priors at evaluated nodes do not help predict
  the hybrid search's visits beyond the visits themselves; they only raise agreement with the model.
- Two of ten kept rules work against their own text (R3, R10); the gate accepts a rule as a feature whatever its
  fitted sign and only flags it.
- [FUTURE] Rules only in the tree prior: a rule feature in playouts, retiring rules whose weight stays near 0, and
  sharing one learning state between concurrent runs beyond the version commit (each process fits on its own
  samples).

## Full-system strength (node `move47::mcts-strength`)

MISSION.md section 5, node `move47::mcts-strength` (M9): the full system (model reasoning + MCTS + heuristic
learning) in rated and strong arena games, against the code-only ablation and v1. Every game is what
`mcts play --learn --heuristics` plays with the model on.

```bash
MOVE_TIMEOUT=25200 scripts/arena_up.sh --profile ladder; MOVE_TIMEOUT=25200 scripts/arena_up.sh --profile kata1
python3 scripts/strength_play.py --run <dir outside Chandra> --plan plan.json [--dry-run]
python3 scripts/strength_report.py <run> [--out-dir DIR] [--path-root DIR] [--format md|json]
```

| part | what |
|---|---|
| driver `scripts/strength_play.py` | parallel game streams (threads), each a list of segments (one arena run per opponent); one `OnlineLearner` (`<run>/hl`, hybrid mode, `update()` serialised; heuristic gates serialised by its fit lock), one DAG and one lesson memory for all streams; per stream its own model service (W sessions) and heuristic loop; decision labels `<stream><segment>g<game>p<ply>` (`Player(label_prefix=)`), so book provenance and session costs stay per game |
| model waits | `play_games(wait_for_model_s=)` (`mcts play --wait-for-model`, 6 h): before each decision the game waits while the service is paused for a usage limit; with more than `hold_after_s` (600 s) of pause left the driver pauses the segment's arena run (`hold`, admin API; the arena counts no idle time while paused) and makes it active again before the search; a run found paused when a segment (re)starts is resumed; `play_decision` retries a move refused with `run_paused` |
| budget | before every decision and new game: the cost of all sessions in `<run>/*/llm-jobs.jsonl` against `budget.max_cost_usd` minus `stop_margin_usd` (stop; the game stays active), and `game_reserve_usd` (no new game); `<run>/control.json` overrides these or stops the run |
| teardown | commands run when every stream has ended (done or stopped by the budget): e.g. the report, then `arena_down.sh` for both profiles |
| report `scripts/strength_report.py` | per opponent W-L, Elo with 95% CI (pooled rated games, `goarena.rating` as in the ablation report), review point loss per move and reviewer, blunders, match rate, search / wall seconds, model sessions and USD per move (sessions attributed to the decision they were requested under), decision rules, decisions without model input, model waits; per game cost and heuristics-book growth (rules and nudges proposed / accepted / rejected, weights first -> last); the code-only ablation and v1 pilot for comparison |

Tests (no GPU, no model): `tests/test_strength_driver.py` (two streams with the mock worker against two
in-process arenas share learner, DAG and memory; labels and per-stream session logs; the report; a stop from
`control.json` before a new game; the budget sum; arena hold / resume), `tests/test_mcts_llm_play.py` (the wait
for the model with the hold, `should_stop`, labels incl. the first decision of a game),
`tests/test_arena_profiles.py` (`MOVE_TIMEOUT`).
