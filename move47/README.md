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
sessions in flight at exit).

| part | design |
|---|---|
| hook | `on_expand` only appends the event to an inbox (O(1)); it fires when a node reaches `n_thr` visits and for every node within `hook_depth` (1) of the root. |
| triage | One dispatcher thread. Each node's canonical position gives its DAG key and the symmetry `s` (canonical = real.transformed(s)). One request per (kind, DAG key): engine nodes with the same canonical position (symmetric moves, transpositions) follow the first request and all receive its result. A node whose DAG key already has an LLM evaluation is served from the DAG at once, without a session (also across moves, games and runs that share the DAG). |
| queue | Priority classes: the root's expand; root breadth (scouts, refute) and lessons; the root's children; deeper nodes. Within a class, by the node's current visits (read when a slot frees). Non-root requests wait `dispatch_delay_s` (2 s) after a new root so that the code search ranks the children first. Cap `queue_cap` (256): the lowest priority is dropped. After `advance`, requests whose recorded path does not pass through the new root are dropped. |
| jobs | Built like v1 `_make_job`: position card of the canonical position, memory briefing, `known` for more/refute. Root expand k=10 candidates + u=4 unconventional, other nodes 6 + 1. Root breadth at every new root: v1 `regions()` scouts (v1 defines none below 13x13, so none on 9x9), a refute of the most-visited root move after `refute_after_s` (60 s), and an `abstract` job after each decision. |
| results | Written to the DAG exactly as v1 writes them (edges with prior and source; unconventional at prior 0.03; scouts mass-scaled; refute at least 0.15; `set_static` value). The engine receives the union of all LLM edges of the DAG key, mapped back with `inv[s]` to the real frame, plus the job's value: `set_external(key, priors, value, source="llm", position=board)`. At the root, unconventional and scout moves get at least `root_explore_prior` (0.05), in place of v1's minimum root visits. A supplied learner gets `observe_external(position, source, priors, value)` for every applied evaluation. |
| failures | Classified from the JobResult and the job's `session.jsonl` / `session.err` (error results, API-retry events, "API Error" texts only, never the model's own text): rate limit (429, usage limit, with its reset time), overload (529/503), timeout, invalid answer, no answer, exception. Rate limits and overload, and 3 other failures in a row, pause dispatching for 30 s doubling to 30 min (or until a usage-limit reset, at most 6 h) and halve the sessions in flight (floor 1); every 2 successes add one back. A request gets at most 2 sessions after ordinary failures and 6 after rate limits. The search never waits and nothing raises into it. |
| accounting | `<run>/llm-jobs.jsonl`: one line per session (kind, DAG key, failure class, seconds, tokens and cost from `_cli_usage`, priors applied). Each move record carries the service's counters since the previous move. |

**Play loop.** One tree per game: after our move and the reply the engine advances twice and
`new_root()` re-ranks the queue; a move list that does not continue the tree's jumps with
`set_root` (still keeping the tree). Decision: most visits. Board fetches and submissions use
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

Known limits: v1's minimum root visits and root prior noise need a change in the engine's root selection
(`mcts/tree.py`); here a prior floor for unconventional and scout moves stands in. In smoke (b) the most-visited
move at the end (J3) had no LLM evaluation of its own: the LLM's values were far below the playouts' (White
0.68-0.95 after every evaluated Black move), so each evaluation lowered that move's Q with `lam` = 0.5, and the
session cap left 216 requests queued (E7's own child among them). A decision rule or a calibrated `lam` (M7)
must handle unevaluated root moves. Requests dropped by the queue cap or as stale are not asked again in the same
tree (the engine fires a node's hook once). Staleness after `advance` is judged from the event's recorded path, so
a node reachable from the new root only by another move order is dropped too.

Tests (no model): `python3 -m pytest -q tests/test_mcts_llm.py tests/test_mcts_llm_play.py -p no:cacheprovider`
(about 20 s): frame mapping for a position with canonical symmetry 2, events from a search turning into jobs
applied during the search, the DAG cache in another orientation (no session), symmetric nodes sharing one job,
duplicate events, stale requests dropped after `advance`, rate limit / overload / exception with backoff, W
halved and raised again, failure classes from session logs, refute and lessons, job and queue caps; the play loop
against a fake arena (the new root keeps its exact visit count, per-move records, learner calls), resume after a
crash from the saved tree, the code-only ablation, `--learn` without and with `mcts.hl`, the runner's `mcts`
adapter command and a full runner game against `random` with the mock worker.
