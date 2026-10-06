# Pilot 2026-10-05: GPU backend during the game

Arena game 24 (run `opus-5-5-xhigh---gotree-2e3a`) ran 19:17:05 to 23:10:36 PDT, which is 02:17:05 to 06:10:36
UTC on 2026-10-06 (the SGF `DT` is that UTC date). The engine review finished at 23:10:55. All times below are PDT.
Every backend was 1 A100 80GB and 2 CPUs in the Slurm partition `preempt` (1 h limit, PreemptMode CANCEL).

Sources: `sacct -X` for the job times and states; the backend logs `Chandra/move47/logs/kg-backend-<job>.out`;
the client log `runs/move47/arena/kg-client.log`; `runs/move47/arena/keepalive.log`; the arena.db `moves`
timestamps, which say which backend answered each opponent move. Paths are relative to the Move47 workspace root.

## Backend jobs

| job | submitted | start | end | elapsed | sacct state | how it ended | queries served |
|---|---|---|---|---|---|---|---|
| 2349 | 19:11:23 | 19:11:23 | 20:11:28 | 01:00:05 | TIMEOUT | time-limit drain: drain signal 20:05:59, client gone 20:06:04, ended at the 1 h limit | 5 (opponent plies 2-10) |
| 2350 | 20:01:27 | 20:01:27 | 21:01:28 | 01:00:01 | TIMEOUT | time-limit drain (drain 20:55:58) | 3 (plies 12-16) |
| 2351 | 20:51:32 | 20:51:32 | 21:51:58 | 01:00:26 | TIMEOUT | time-limit drain (drain 21:46:29) | 2 (plies 18-20) |
| 2352 | 21:41:36 | 21:41:36 | 22:15:19 | 00:33:43 | PREEMPTED | preemption, no drain; 0 queries in flight | 3 (plies 22-26) |
| 2354 | 22:15:39 | 22:17:18 | 23:11:16 | 00:53:58 | CANCELLED by 1000 | pending 99 s until a GPU freed; cancelled by the post-game teardown | 7 (plies 28-38 and the review) |
| 2355 | 23:07:44 | 23:07:44 | 23:11:16 | 00:03:32 | CANCELLED by 1000 | successor, submitted with 574 s left on 2354; cancelled by the teardown | 0 |

The served counts add up to 20: 19 opponent moves and 1 review query (all 39 positions, 1600 visits).
Job 2352 was preempted by job 2353 of another user (partition `long`, 1 GPU). That job started at 22:15:20 and
ended at 22:17:18, the moment 2354 started. The keepalive submitted 2354 at 22:15:39 on its next 30 s check.
Jobs 2346-2348 (18:36-18:55) served the earlier smoke runs and played no part in this game.

## Client switches (kg-client pid 2522420)

| time | event |
|---|---|
| 19:11:31 | connected to kgb-2349 |
| 20:05:59 | kgb-2349 draining; new queries go to kgb-2350; drained connection closed 20:06:04 |
| 20:55:58 | kgb-2350 draining; new queries go to kgb-2351; drained connection closed 20:56:03 |
| 21:46:29 | kgb-2351 draining; new queries go to kgb-2352; drained connection closed 21:46:34 |
| 22:15:19 | lost kgb-2352 (connection closed by the backend): 0 unfinished queries to resend |
| 22:17:27 | connected to kgb-2354 after 128 s without a backend. No query was due in that gap: our search for ply 27 ran from 22:10:42 to 22:20:41 |
| 23:11:16 | lost kgb-2354, then kgb-2355, at teardown with 0 unfinished queries each, after the game end (23:10:36) and the review (23:10:55) |

**Queries resent: 0.** All three connection losses reported 0 unfinished queries to resend. Every backend logged
"terminated 0 unfinished queries" when its client left. The drain handovers let in-flight queries finish on the
old backend. KataGo's replies came 0.21-1.08 s after our moves (column `reply` in report.md).

## Notes

- Game end, from `runs/move47/arena/arena.log`: adjudicated after ply 38. Our (ply, winrate, lead) on the last four
  opponent moves were (38, 0.0002, -26.25), (36, 0.0002, -26.2), (34, 0.0002, -25.77) and (32, 0.0001, -23.2). The
  rule is winrate < 0.01 and lead < -20 on 4 consecutive opponent moves after ply 30.
- Cost: job 192 (refute, move 11) was killed at the 900 s job timeout (20:00:47-20:15:47, rc=-9) before its session
  wrote a result event. Its spend is therefore missing from the 204.67 USD total, and it is the one job without a
  cost line.
