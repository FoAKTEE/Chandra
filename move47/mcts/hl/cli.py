"""Subcommands of python3 -m mcts for the online learner (registered by mcts/cli.py):

    learn-selfplay       code-only self-play with online learning (one reused tree per game)
    weights-ab           two weight files play each other (colours alternate), win rate + 95% CI
    hl-report            every version of a learner run dir: held-out CE, regression CE, guards
    hl-guards            one weight file against the tactical guards and the regression positions
    hl-export-heldout    a sample of a run's held-out nodes, for the tracked learned-weights test
    hl-regression-build  regenerate mcts/regression/positions.json (code-only self-play, deep searches)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _kv(items, target: str) -> dict:
    out = {}
    for kv in items or []:
        k, _, v = kv.partition("=")
        if target == "learner":
            from .learner import DEFAULTS
            if k not in DEFAULTS:
                sys.exit(f"unknown learner option {k!r} (one of {', '.join(DEFAULTS)})")
            cur = DEFAULTS[k]
        else:
            from ..tree import MCTSConfig
            if not hasattr(MCTSConfig(), k):
                sys.exit(f"unknown config key {k!r}")
            cur = getattr(MCTSConfig(), k)
        if isinstance(cur, bool):
            out[k] = v.lower() in ("1", "true", "yes")
        elif cur is None:
            out[k] = v
        else:
            out[k] = type(cur)(v)
    return out


def cmd_learn_selfplay(a) -> int:
    from ..cli import _run_dir
    from .selfplay import learn_selfplay
    run = _run_dir(a.run)
    res = learn_selfplay(run, a.games, a.time, a.threads, base=a.base, update_every=a.update_every,
                         max_moves=a.max_moves, resign=a.resign, seed=a.seed, config=_kv(a.set, "config"),
                         learner_cfg=_kv(a.hl, "learner"))
    print(json.dumps(res))
    return 0


def cmd_weights_ab(a) -> int:
    from ..cli import _run_dir
    from .selfplay import weights_ab
    run = _run_dir(a.run) if a.run else None
    s = weights_ab(Path(a.a), Path(a.b), a.games, a.time, a.threads, procs=a.procs, seed=a.seed, run=run,
                   max_moves=a.max_moves, resign=a.resign, a_value_model=a.a_value_model)
    print(json.dumps(s))
    lo, hi = s["ci95"]
    print(f"A {s['a_version']} vs B {s['b_version']}: A won {s['a_wins']}/{s['games']} "
          f"({s['a_winrate']:.3f}, 95% CI {lo:.3f}-{hi:.3f}); {a.time}s/move, {a.threads} threads x {a.procs} procs")
    return 0


def cmd_report(a) -> int:
    from .selfplay import report, report_markdown
    r = report(Path(a.run))
    print(json.dumps(r, default=float) if a.json else report_markdown(r, a.every))
    return 0


def cmd_guards(a) -> int:
    from ..weights import Weights, load_default
    from .regression import check_guards, regression_metrics
    w = Weights.load(a.weights) if a.weights else load_default()
    g = check_guards(w)
    print(json.dumps({"version": w.version, "guards": g, "regression": regression_metrics(w)}, indent=1))
    return 0 if g["passed"] else 1


def cmd_regression_build(a) -> int:
    from .regression import POSITIONS_PATH, build_positions
    out = Path(a.out) if a.out else POSITIONS_PATH
    print(json.dumps(build_positions(out, a.games, a.per_game, a.move_time, a.deep_sims, a.threads, a.seed)))
    return 0


def cmd_export_heldout(a) -> int:
    from .regression import HELDOUT_PATH, export_heldout
    print(json.dumps(export_heldout(Path(a.run), Path(a.out) if a.out else HELDOUT_PATH, a.n, a.min_visits, a.seed)))
    return 0


def register(sub) -> None:
    p = sub.add_parser("learn-selfplay", help="code-only self-play with online Heuristic Learning")
    p.add_argument("--run", required=True, help="learner run dir (outside Chandra); resumes if it exists")
    p.add_argument("--games", type=int, default=1)
    p.add_argument("--time", type=float, default=1.0, help="seconds per move")
    p.add_argument("--threads", type=int, default=16)
    p.add_argument("--base", default=None, help="starting weights (default default-v1; ignored on resume)")
    p.add_argument("--update-every", type=int, default=1, help="refit after every N decisions")
    p.add_argument("--max-moves", type=int, default=200)
    p.add_argument("--resign", type=float, default=0.03,
                   help="resign below this root winrate after move 40 (0: play every game out)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--set", action="append", metavar="KEY=VALUE", help="MCTSConfig field")
    p.add_argument("--hl", action="append", metavar="KEY=VALUE", help="OnlineLearner option (mcts.hl.DEFAULTS)")
    p.set_defaults(fn=cmd_learn_selfplay)

    p = sub.add_parser("weights-ab", help="A/B two weight files in code-only MCTS games (colours alternate)")
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.add_argument("--games", type=int, default=40)
    p.add_argument("--time", type=float, default=0.5, help="seconds per move (both sides)")
    p.add_argument("--threads", type=int, default=8, help="search threads per process")
    p.add_argument("--procs", type=int, default=1, help="games played in parallel")
    p.add_argument("--max-moves", type=int, default=200)
    p.add_argument("--resign", type=float, default=0.03)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--run", default=None, help="write games.jsonl, SGFs and summary.json here (outside Chandra)")
    p.add_argument("--a-value-model", default=None,
                   help="give engine A the learned value model (a learner state.json) through the on_expand hook")
    p.set_defaults(fn=cmd_weights_ab)

    p = sub.add_parser("hl-report", help="versions of a learner run dir: held-out / regression CE, guards")
    p.add_argument("--run", required=True)
    p.add_argument("--every", type=int, default=1, help="show every k-th version")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("hl-guards", help="check a weight file against the tactical guards and regression set")
    p.add_argument("--weights", default=None)
    p.set_defaults(fn=cmd_guards)

    p = sub.add_parser("hl-export-heldout", help="write a sample of a run's held-out nodes (regression format)")
    p.add_argument("--run", required=True)
    p.add_argument("--out", default=None, help="default: mcts/regression/heldout-selfplay.json")
    p.add_argument("--n", type=int, default=300)
    p.add_argument("--min-visits", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_export_heldout)

    p = sub.add_parser("hl-regression-build", help="regenerate the regression positions (code-only self-play)")
    p.add_argument("--out", default=None, help="default: mcts/regression/positions.json")
    p.add_argument("--games", type=int, default=6)
    p.add_argument("--per-game", type=int, default=25)
    p.add_argument("--move-time", type=float, default=0.3)
    p.add_argument("--deep-sims", type=int, default=200_000)
    p.add_argument("--threads", type=int, default=16)
    p.add_argument("--seed", type=int, default=1000)
    p.set_defaults(fn=cmd_regression_build)
