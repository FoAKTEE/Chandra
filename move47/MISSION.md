# move47 — mission design and DAG

Source brief: `progress/prompt/init.md` (Move47 workspace). Reference design: go-bench v0.02
(`PROMPT.md`, `TREE.md`). User steer (2026-10-05): **let real KataGo play our Claude Opus 5.5
xhigh + tree harness.** This file, the knowledge ledger `results/ledgers/knowledge/paper_move47/`
and init.md are the upstream-dependency ledger; node status lives in the ledger, not here.

## 0. Ground truth that overrides init.md

Measured on the host (anta) on 2026-10-05:

| item | init.md says | measured |
|---|---|---|
| hardware threads | 256 | 144; the 70% cap is ~100 busy threads |
| user CPU quota | 10-CPU cgroup on user-1012.slice | none (user-1000.slice CPUQuota=infinity) |
| other load | — | a separate campaign of the same user keeps ~86 threads busy |
| GPUs | 4-GPU cap | 2x A100 80GB, only inside Slurm partition `preempt` |
| Slurm limits | 2 h, <=2 CPU/GPU | 1 h MaxTime, preemptible (CANCEL), 4 schedulable CPUs total |

Consequences: every agent works within **4 CPU threads** on the login host; GPU work runs only as
Slurm jobs of 1 GPU + 2 CPUs, at most 2 at once (mission-wide); any long-lived GPU service must
survive job turnover every hour and preemption at any time.

## 1. Architecture

```
 login host (persistent)                                  Slurm preempt (GPU, rolling 1 h jobs)
 ┌──────────────────────────────────────────────┐        ┌─────────────────────────────────┐
 │ gotree play (tree harness) ──HTTP──► goarena │        │ kg backend job N                │
 │   │  fresh `claude -p` per search job        │        │  katago analysis (tf3, A100)    │
 │   │  model claude-opus-5-5, effort xhigh     │        │  TCP 127.0.0.1:<port>, ids      │
 │   │  bwrap: engines/ judge/ ref-code hidden  │        │  namespaced per connection      │
 │   ▼                                          │        └──────────────▲──────────────────┘
 │ run dir OUTSIDE Chandra (no hooks/CLAUDE.md)  │                       │ rendezvous file
 │ goarena serve ── KATAGO_BIN = kg client shim ─┼─── reconnect+resend ──┘ engines/run/backends/
 │ kg keepalive: keeps one backend alive, submits successor before the 1 h limit │
 └──────────────────────────────────────────────┘
```

Firewall (TREE.md hard constraint 1) is unchanged: KataGo is opponent, referee, post-game
reviewer and offline judge. Nothing it computes reaches a worker; the arena hides reviews of a
running run; worker sessions cannot read engines/, judge/, ref-code/ or progress/.

## 2. Decisions

- **Engine:** KataGo v1.18.2 CUDA 12.8 / cuDNN 9.8 prebuilt; net kata1-tf3-b11c768-s11003M-d5973M-7gres.
- **Board:** 9x9, Chinese rules, komi 7.5 (TREE.md: 19x19 full games are not affordable).
- **"Real KataGo" ladder** (`config/tiers-9x9-kata1.json`, strong net, uncalibrated, not rated):
  `k1-p` raw policy (1 visit, temperature 0), `k1-64` 64 visits, `k1-full` 1600 visits.
  The calibrated b10c128 ladder stays in `config/tiers-9x9.json` for later Elo work.
- **Adjudication** (arena option, off by default, on for the pilot): if the KataGo opponent's own
  search gives the agent winrate < 1% and lead < -20 for 4 consecutive opponent moves after ply 30,
  the game ends as an agent loss, reason `adjudicated`. Saves cost in decided games; leaks nothing.
- **Worker:** `claude:claude-opus-5-5:xhigh`; `--setting-sources ""`, `--strict-mcp-config`,
  web tools disallowed; `--bare` is not usable (it requires an API key, the account uses OAuth).
- **Pilot:** 1 game vs `k1-full`; budget 32 jobs/move, 8 in flight, 1500 s per decision,
  900 s per job, arena move timeout 3600 s. Scale only after the pilot's cost per move is measured.

## 3. DAG (paper `move47`)

| node | task | preds | done when (verification) |
|---|---|---|---|
| `move47::engine` | M0 | — | pinned fetch passes; GPU jobs 2336/2337/2338 completed (commit 1c5f49c) |
| `move47::import` | M1 | — | go-bench v0.02 under move47/ with PROVENANCE.md and exec bits; 49/49 tests pass |
| `move47::kg-service` | M2 | engine | backend/client/keepalive; fake-engine tests for reconnect+resend and id namespacing; real GPU smoke across a forced backend kill |
| `move47::arena-gpu` | M3 | import, kg-service | kata1 tiers + adjudication with tests; arena on the login host through the service; a mock-worker game vs `k1-p` ends with referee score and review |
| `move47::worker-sandbox` | M4 | import | sandbox canary (session cannot list engines/); one real Opus 5.5 xhigh expand job accepted; audit_run.py clean |
| `move47::pilot-game` | M5 | arena-gpu, worker-sandbox | one full 9x9 game vs `k1-full`: SGF, result, per-move jobs/time/cost, per-move point loss from the review |
| `move47::stage0-prior` | T0a | worker-sandbox | `gotree prior` on G2#37 with Opus xhigh, 10 samples [FUTURE] |
| `move47::stage0-values` | T0b | worker-sandbox, kg-service | `gotree judge-values` vs GPU KataGo [FUTURE] |
| `move47::probe-37` | T2 | stage0-prior, stage0-values | budget scan 200→1000→5000 jobs with ablations [FUTURE] |
| `move47::arena-campaign` | T1 | pilot-game | multi-game campaign, Elo vs ladders, Dojo / Claude Code baselines [FUTURE] |

Waves (maximal topological scheduling): **W1** import ∥ kg-service ∥ ledger bootstrap ·
**W2** arena-gpu ∥ worker-sandbox · **W3** pilot-game · later T0a ∥ T0b, then T2, T1.

## 4. Process

- Workers propose (code, tests, evidence, draft commit message); the orchestrator re-runs the
  verification and commits — one commit per node or finer, tests with the code, grammar of
  `_common/contracts/commit_template.md`, claims tagged `[SOLID|PRELIMINARY|HOLE|FUTURE]` with a real
  `verify:` object, no tool or model attribution.
- Ledger rows are appended only by delegated workers (`CHANDRA_ROLE=worker`) through the gated CLI.
- Never tracked: engines, nets, run dirs, logs, judge output, build trees.
- Two repos, every stage: the commit lands in Chandra (branch GUI_VSC, pushed to
  origin FoAKTEE/Chandra) and is mirrored one-to-one in the outer Move47 repo (pushed to origin
  FoAKTEE/Move47 main) as a submodule bump with the same message, the stage's author time and a
  `Refs: Chandra <hash>` trailer. Both repos run the same gate (`_common/hooks`, strict).
- Commit messages never mention the assistant or its vendor by name and carry no co-author or
  attribution trailers; the model under test is named "Opus 5.5".

## 5. MCTS v2: large reusable tree, LLM plus learned heuristics (user steer 2026-10-07)

User steer: no per-game limit on compute or API cost; switch to an MCTS design; consecutive moves
reuse the tree and keep updating its weights in the Heuristic Learning sense; a large tree is fine.

Why: v1 is PUCT in which every simulation is one LLM session, so a move gets about 32 simulations
(pilot: the chosen move had 8 to 25 root visits; lost at 1.21 points per move). v2 decouples
simulations from LLM calls, as AlphaGo did with its policy network.

- **Simulations (code, fast).** PUCT with progressive widening over a transposition-aware tree,
  virtual loss, many threads. Leaf value `V = (1-lam)*v_llm + lam*z_playout`; a node without an LLM
  value uses the playout result and the learned value head. Playouts run to the end of the game
  with a learned feature-weighted softmax policy and area scoring. Target: at least 10k
  simulations per second on 9x9.
- **LLM expansion (async, the expensive part).** A node is queued for an Opus 5.5 xhigh `expand`
  job once its visits reach `n_thr` (the root and its children always); priority by visits; up to
  `W` sessions in flight (default 16, backing off on rate limits). The result adds candidates,
  including unconventional ones, with priors and a value; until it arrives the node uses the
  learned priors. v1's root breadth (scouts, unconventional quota, minimum visits, noise) stays.
- **Reuse.** One tree per game, never reset: after our move and the reply the new root keeps its
  whole subtree and statistics. The DAG (L0) keeps LLM evaluations across games.
- **Heuristic Learning (L3, online).** After every decision, and periodically during search, refit
  (a) policy weights, shared by the prior and the playout policy, over one feature set
  (colour-relative 3x3 pattern, capture, atari, self-atari, escape, ladder, distance to the last
  move, line) to the visit distributions of well-visited nodes; (b) value weights to the
  backed-up Q of well-visited nodes and to finished game results; (c) the mixing weights `lam`
  (LLM value vs playout) and `beta` (LLM prior vs learned prior) from each source's error against
  the deeper search's own Q. Weights are versioned files with a regression set. Targets come
  only from our own search and game results, never from KataGo.
- **Decision.** Most visits at the root; time per move configurable (default 30 min); no cost cap;
  cost and time logged per move.
- **Ablations by config.** `llm=off` (code MCTS plus learning), `playouts=off` (`lam=0`, LLM values
  only), `hl=off` (fixed weights).
- **CPU.** Simulation threads count against the 70% rule (about 100 of 144 threads); default 32,
  re-checked against host load at start. GPUs stay reserved for KataGo.

| node | task | preds | done when (verification) |
|---|---|---|---|
| `move47::mcts-engine` | M6 | import | compiled fast board, features and weighted playouts; Python tree with PUCT, widening, transpositions, reuse, virtual loss and threads; mock LLM hook; tests (rules agree with gotree.position, tactics, reuse keeps statistics); measured simulations per second on 9x9 |
| `move47::mcts-hl` | M7 | mcts-engine | online learning of policy, value, `lam`, `beta`; versioned weight store; regression set; tests show learned weights predict held-out search targets better than the initial ones |
| `move47::mcts-llm` | M8 | mcts-engine, worker-sandbox | async expansion queue with sandboxed Opus xhigh workers, prior and value blending, rate-limit backoff, arena play loop that keeps the tree; mock tests and a small real smoke |
| `move47::mcts-calib` | M8b | mcts-llm, mcts-hl | root breadth in the engine (minimum visits for model-proposed and unconventional root moves, prior noise), re-armable expansion hooks, a root-subtree query; root moves without a model value no longer win by default (stand-in value from the parent's evaluation, and the decision only on an evaluated move); model values calibrated to the playout scale online; an Opus smoke on the integration-smoke position decides on an evaluated move |
| `move47::mcts-strength` | M9 | mcts-calib, arena-gpu | code-only and hybrid MCTS against k1-p and the calibrated ladder; time and cost per move |
| `move47::mcts-game` | M10 | mcts-strength | one full 9x9 game against k1-full with no cost cap, tree and weights carried across moves; report and review like the pilot |

Waves: **W4** mcts-engine with the ledger update · **W5** mcts-hl and mcts-llm · **W5b** mcts-calib
(added 2026-10-07: the mcts-llm smoke chose a move with no model evaluation, because model values sat
below the playouts) · **W6** mcts-strength · **W7** mcts-game.
