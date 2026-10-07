# Offline judge: pilot position after 22 plies (2026-10-07)

Position: the v1 pilot game (Opus 5.5 xhigh / gotree vs k1-full) after 22 plies, Black to play
(`runs/move47/mcts-calib-20261007/pilot-game.sgf`, sha256 in `summary.json`). Graded moves: H7 (the MCTS v2 decision of
the mcts-calib smoke, both with the model and code-only), E6 (v1's actual move 23), C2 (the earlier ad-hoc run's best).
Judge: strong net kata1-tf3-b11c768 on an A100 through kgservice, `gotree.judge.judge_root` (loss = best lead minus the
lead after the move, from a search of the child position with a quarter of the visits).

```bash
cd Chandra/move47
python3 scripts/judge_position.py --sgf ../../runs/move47/mcts-calib-20261007/pilot-game.sgf --upto 22 \
    --moves H7,E6,C2 --visits 1600,20000 --path-root ../.. --out judge-run1.json
```

| visits | source | engine best (Black lead) | H7 rank / loss | E6 rank / loss | C2 rank / loss |
|---|---|---|---|---|---|
| 20000 | earlier ad-hoc run | C2 | 4 / 1.69 | 13 / 2.91 | best |
| 20000 | run 1 | C2 (-16.69) | 3 / 1.76 | 15 / 2.89 | 1 / 0.00 |
| 20000 | run 2 | G8 (-16.69) | 3 / 1.99 | 15 / 2.95 | 2 / -0.02 |
| 20000 | run 3 | G8 (-16.68) | 3 / 2.10 | 15 / 2.97 | 2 / -0.05 |
| 1600 | earlier ad-hoc run | | - / 2.73 | - / 3.86 | |
| 1600 | run 1 | G8 (-15.92) | 3 / 2.53 | 14 / 3.68 | 2 / 0.84 |
| 1600 | run 2 | G8 (-16.76) | 3 / 1.38 | 14 / 2.88 | 2 / -0.41 |
| 1600 | run 3 | G8 (-16.74) | 3 / 1.68 | 15 / 2.91 | 2 / -0.09 |

Reproduced: at 20000 visits H7 loses 1.76-2.10 points (ad-hoc 1.69) and E6 2.89-2.97 (ad-hoc 2.91), so the MCTS v2
choice is about 0.9-1.1 points better than v1's move; C2 and G8 are tied for best (within 0.05 points), which is why
the best move flips between runs. Ranks differ by one or two places from the ad-hoc run (H7 3 vs 4, E6 15 vs 13).
Runs 2 and 3 followed run 1 on the same backend within a minute and reused its NN cache (0.1-1.5 s per query), so they
are not independent cold searches; 1600 visits is noisy (H7 1.38-2.53).

Files: `judge-run{1,2,3}.json` (raw tool output), `summary.json` (the table above as data).
Firewall: offline measurement only; nothing here enters a search, prompt, memory or weights.
