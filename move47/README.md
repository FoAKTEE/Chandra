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
