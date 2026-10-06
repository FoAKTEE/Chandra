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
