"""Command line: python3 -m mcts {build,bestmove,selfplay,bench,weights,arena,play,llm-search} (run from move47/)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]       # the Chandra checkout (move47/ lives in it)

# A constructed 9x9 middle game (30 moves written by hand; no engine involved), for benchmarks.
MIDGAME_9 = "E5 C4 D3 C3 D4 C6 D6 C7 G4 D7 E7 D8 E8 G6 F6 G7 F7 G3 H4 F3 E3 F4 G5 H6 H3 G2 H2 F2 E2 J5".split()


def _run_dir(path: str | None) -> Path | None:
    if not path:
        return None
    p = Path(path).resolve()
    if p == REPO or REPO in p.parents:
        sys.exit(f"--run-dir must be outside the Chandra tree ({REPO})")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _config(a):
    from .tree import MCTSConfig
    cfg = MCTSConfig()
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        if not hasattr(cfg, k):
            sys.exit(f"unknown config key {k!r}")
        cur = getattr(cfg, k)
        setattr(cfg, k, (v.lower() in ("1", "true", "yes")) if isinstance(cur, bool) else type(cur)(v))
    if a.max_nodes:
        cfg.max_nodes = a.max_nodes
    cfg.seed = a.seed
    return cfg


def cmd_build(a) -> int:
    from ._lib import build
    print(build(force=a.force, verbose=True))
    return 0


def cmd_weights(a) -> int:
    from .weights import DEFAULT_PATH, default_weights
    w = default_weights()
    if a.write_default:
        print(w.save(DEFAULT_PATH))
    else:
        print(json.dumps(w.to_json(), indent=1))
    return 0


def cmd_bestmove(a) -> int:
    from .board import board_from_sgf
    from .tree import MCTS
    b, hist, moves = board_from_sgf(Path(a.sgf).read_text(), a.upto)
    eng = MCTS(b, history=hist, config=_config(a), weights=a.weights)
    r = eng.search(time_s=a.time, sims=a.sims, threads=a.threads)
    print(f"position after {len(moves)} moves, {b.to_play} to play; {r['sims']} sims in {r['time_s']:.1f}s "
          f"({r['sims_per_s']:.0f}/s, {r['threads']} threads), {r['nodes']} nodes, "
          f"root winrate {r['q']:.3f}, stop: {r['stop_reason']}")
    print(eng.table(a.top))
    print(f"best: {r['best']}")
    if a.json:
        print(json.dumps({k: v for k, v in r.items() if k != "moves"} | {"moves": r["moves"][:a.top]}))
    return 0


def cmd_selfplay(a) -> int:
    from goarena.sgf import write_sgf
    from .board import Board
    from .tree import MCTS
    run = _run_dir(a.run_dir)
    for g in range(a.games):
        cfg = _config(a)
        cfg.seed = a.seed + g
        eng = MCTS(Board(a.size, a.komi), config=cfg, weights=a.weights)
        played, t0 = [], time.time()
        max_moves = a.max_moves or 3 * a.size * a.size
        while not eng.root_board.terminal and len(played) < max_moves:
            r = eng.search(time_s=a.time, sims=a.sims, threads=a.threads)
            mv = r["best_move"]
            color = eng.root_board.to_play
            print(f"game {g + 1} ply {len(played) + 1:3d} {'B' if color == 'X' else 'W'} {r['best']:>4}  "
                  f"sims {r['sims']:7d} ({r['sims_per_s']:6.0f}/s)  q {r['q']:.3f}  root_n {r['root_n']:8d}  "
                  f"nodes {r['nodes']}", flush=True)
            played.append((1 if color == "X" else 2, mv))
            eng.advance(mv)
            if run and a.save_tree:
                eng.save(run / f"game{g + 1}-tree.npz")
        score = eng.root_board.score()
        res = "B+%g" % score if score > 0 else "W+%g" % -score if score < 0 else "0"
        print(f"game {g + 1}: {res} (Tromp-Taylor, {'finished' if eng.root_board.terminal else 'move cap'}) "
              f"after {len(played)} moves, {time.time() - t0:.0f}s; tree {eng.n_nodes} nodes, {eng.gc_runs} gc")
        if run:
            (run / f"game{g + 1}.sgf").write_text(write_sgf(a.size, a.komi, played, black="mcts", white="mcts",
                                                            result=res, event="mcts selfplay (code only)"))
        eng.close()
    return 0


def cmd_bench(a) -> int:
    from .board import Board, board_from_moves
    from .tree import MCTS
    positions = {"empty": (Board(9, 7.5), []), "midgame": board_from_moves(9, MIDGAME_9)}
    rows = []
    for name in a.positions.split(","):
        b, hist = positions[name]
        for T in [int(x) for x in a.threads.split(",")]:
            load0 = os.getloadavg()[0]
            cfg = _config(a)
            eng = MCTS(b, history=hist, config=cfg, weights=a.weights)
            r = eng.search(time_s=a.time, threads=T)
            row = {"position": name, "threads": T, "sims_per_s": round(r["sims_per_s"]),
                   "playouts_per_s": round(r["playouts_per_s"]), "sims": r["sims"], "nodes": r["nodes"],
                   "depth_mean": round(r["depth_mean"], 1), "best": r["best"], "load_before": round(load0, 1),
                   "playout_frac": round(r["playout_frac"], 3), "expand_frac": round(r["expand_frac"], 3)}
            rows.append(row)
            print(json.dumps(row), flush=True)
            eng.close()
    print("\n| position | threads | sims/s | nodes | time in playouts | in expansions | load before |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['position']} | {r['threads']} | {r['sims_per_s']} | {r['nodes']} | {r['playout_frac']:.0%} | "
              f"{r['expand_frac']:.0%} | {r['load_before']} |")
    return 0


def cmd_arena(a) -> int:
    from harness.arena_client import ArenaClient
    from .arena import play_games
    token = a.token or os.environ.get("GOARENA_TOKEN", "")
    client = ArenaClient(a.url, token)
    run = _run_dir(a.run_dir)
    res = play_games(client, a.opponent, a.games, config=_config(a), time_s=a.time, threads=a.threads,
                     weights=a.weights, color=a.color, run_dir=run, sims=a.sims)
    print(json.dumps(res))
    return 0


def _register_llm(sub) -> None:
    """`play` and `llm-search`: MCTS v2 with asynchronous LLM expansion (mcts/play.py, mcts/llm.py)."""
    from .play import add_parsers
    add_parsers(sub)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m mcts", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, time_default=10.0, threads=(int, 16)):
        p.add_argument("--time", type=float, default=time_default, help="seconds per search")
        p.add_argument("--sims", type=int, default=None, help="simulations per search (with or instead of --time)")
        p.add_argument("--threads", type=threads[0], default=threads[1],
                       help="search threads" + (" (comma-separated list)" if threads[0] is str else ""))
        p.add_argument("--weights", default=None, help="weight file (default: mcts/weights/default-v1.json)")
        p.add_argument("--max-nodes", type=int, default=0)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--set", action="append", metavar="KEY=VALUE", help="MCTSConfig field")

    p = sub.add_parser("build", help="compile the C core")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("weights", help="print (or --write-default) the hand-written default weights")
    p.add_argument("--write-default", action="store_true")
    p.set_defaults(fn=cmd_weights)

    p = sub.add_parser("bestmove", help="search one position from an SGF and print the root table")
    p.add_argument("--sgf", required=True)
    p.add_argument("--upto", type=int, default=None, help="use the first N moves")
    p.add_argument("--top", type=int, default=12)
    p.add_argument("--json", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_bestmove)

    p = sub.add_parser("selfplay", help="code-only self-play with one reused tree per game")
    p.add_argument("--size", type=int, default=9)
    p.add_argument("--komi", type=float, default=7.5)
    p.add_argument("--games", type=int, default=1)
    p.add_argument("--max-moves", type=int, default=0)
    p.add_argument("--run-dir", default=None, help="write SGFs (and --save-tree trees) here; outside Chandra")
    p.add_argument("--save-tree", action="store_true")
    common(p, 1.0)
    p.set_defaults(fn=cmd_selfplay)

    p = sub.add_parser("bench", help="simulations per second on 9x9 positions")
    p.add_argument("--positions", default="empty,midgame")
    common(p, 5.0, (str, "1,8,16,32"))
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("arena", help="play goarena games (code-only engine), keeping the tree across moves")
    p.add_argument("--url", required=True)
    p.add_argument("--token", default="", help="agent token (default: $GOARENA_TOKEN)")
    p.add_argument("--opponent", required=True)
    p.add_argument("--games", type=int, default=1)
    p.add_argument("--color", default=None, choices=[None, "B", "W"])
    p.add_argument("--run-dir", default=None)
    common(p)
    p.set_defaults(fn=cmd_arena)

    _register_llm(sub)

    a = ap.parse_args(argv)
    return a.fn(a)
