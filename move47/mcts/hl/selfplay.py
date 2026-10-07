"""Code-only evidence for the online learner: self-play with learning, a weights A/B, a report.

learn_selfplay   one tree per game, reused across moves (advance), weights from the learner's
                 provider (a new version applies at the next search), learner.update() after every
                 `update_every` decisions, observe_game() at the end of each game.  moves.jsonl
                 logs per move the weights version the search used, whether it was new, and the
                 root visits kept from the previous move (tree reuse).
weights_ab       two engines with fixed weight files play each other, colours alternating, the
                 same time per move; each keeps its own tree across the game.  Win rate with a
                 Wilson 95% interval.
report           every version of a learner run dir on the run's final held-out nodes and on the
                 tracked regression positions, the guards, and the tree-reuse / version-change log.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from ..board import Board
from ..tree import MCTS, MCTSConfig
from ..weights import Weights
from .learner import OnlineLearner
from .regression import check_guards, regression_metrics


def _result_black(eng: MCTS, resigned_by: Optional[str]) -> tuple[float, str]:
    if resigned_by is not None:
        return (-1.0 if resigned_by == "X" else 1.0), f"{'W' if resigned_by == 'X' else 'B'}+R"
    sc = eng.root_board.score()
    if sc > 0:
        return 1.0, f"B+{sc:g}"
    if sc < 0:
        return -1.0, f"W+{-sc:g}"
    return 0.0, "0"


def _sgf(moves: list, result: str, black: str, white: str, event: str) -> str:
    from goarena.sgf import write_sgf
    return write_sgf(9, 7.5, moves, black=black, white=white, result=result, event=event)


def learn_selfplay(run: Path, games: int, time_s: float, threads: int, base=None, update_every: int = 1,
                   max_moves: int = 200, resign: float = 0.03, resign_after: int = 40, seed: int = 0,
                   config: Optional[dict] = None, learner_cfg: Optional[dict] = None,
                   log: Callable[[str], None] = print) -> dict:
    run = Path(run)
    run.mkdir(parents=True, exist_ok=True)
    (run / "games").mkdir(exist_ok=True)
    lcfg = {"threads": min(threads, 16), **(learner_cfg or {})}
    learner = OnlineLearner(run, base=base, **lcfg)
    log(f"learner {'resumed' if learner.resumed else 'started'} in {run}: version {learner.current.version}, "
        f"{len(learner.samples)} samples, game {learner.game}")
    ecfg = {"max_nodes": 3_000_000, "observe_min_visits": 256, "observe_max_samples": 400, **(config or {})}
    summary = []
    for gi in range(games):
        g = learner.game
        cfg = MCTSConfig.from_dict({**ecfg, "threads": threads, "seed": seed * 1000 + g})
        eng = MCTS(Board(9, 7.5), config=cfg, weights=learner.provider, learner=learner)
        played, resigned_by, t_game = [], None, time.time()
        prev_version = None
        while not eng.root_board.terminal and len(played) < max_moves:
            ply = len(played) + 1
            reused = int(eng.a.n[eng.root])
            nodes_before = eng.n_nodes
            r = eng.search(time_s=time_s, threads=threads)
            color = eng.root_board.to_play
            row = {"game": g, "ply": ply, "color": "B" if color == "X" else "W", "move": r["best"],
                   "weights": r["weights"], "weights_refreshed": r["weights_refreshed"],
                   "version_changed": prev_version is not None and r["weights"] != prev_version,
                   "reused_root_n": reused, "nodes_before": nodes_before, "root_n": r["root_n"], "sims": r["sims"],
                   "sims_per_s": round(r["sims_per_s"]), "q": round(r["q"], 4), "nodes": r["nodes"]}
            prev_version = r["weights"]
            if resign > 0 and ply >= resign_after and r["q"] < resign:
                resigned_by = color
                row["resign"] = True
            else:
                played.append((1 if color == "X" else 2, r["best_move"]))
                eng.advance(r["best_move"])
            if ply % update_every == 0 or resigned_by:
                u = learner.update()
                p = u.get("policy") or {}
                row["update"] = {"accepted": u["accepted"], "version": u["version"], "reason": u["reason"],
                                 "time_s": u["time_s"], "train_n": u["train_n"], "heldout_n": u["heldout_n"],
                                 "heldout_ce": None if not p else [p["heldout"]["parent"]["ce"],
                                                                   p["heldout"]["candidate"]["ce"]]}
            with open(run / "moves.jsonl", "a") as f:
                f.write(json.dumps(row) + "\n")
            up = row.get("update")
            ce = up and up["heldout_ce"]
            log(f"g{g} {ply:3d} {row['color']} {r['best']:>4} sims {r['sims']:6d} q {r['q']:.3f} reused {reused:7d} "
                f"w {r['weights']}{'*' if row['version_changed'] else ''}"
                + (f" | upd {'ACC' if up['accepted'] else 'rej'} -> {up['version']}"
                   + (f" ho {ce[0]:.4f}->{ce[1]:.4f}" if ce else f" ({up['reason'][:40]})")
                   + f" {up['time_s']:.1f}s" if up else ""))
            if resigned_by:
                break
        res, res_str = _result_black(eng, resigned_by)
        learner.observe_game(res, "B")      # one engine plays both colours: label from black's side
        (run / "games" / f"g{g:03d}.sgf").write_text(
            _sgf(played, res_str, "mcts-hl", "mcts-hl", "learn-selfplay (code only)"))
        info = {"game": g, "result": res_str, "moves": len(played), "time_s": round(time.time() - t_game),
                "version_end": learner.current.version, "nodes": eng.n_nodes}
        summary.append(info)
        with open(run / "games.log.jsonl", "a") as f:
            f.write(json.dumps(info) + "\n")
        log(f"game {g}: {res_str} after {len(played)} moves, {info['time_s']}s, weights now {learner.current.version}")
        eng.close()
    learner.close()
    return {"games": summary, "version": learner.current.version, "accepted": learner.accepted,
            "updates": learner.updates}


# ------------------------------------------------------------------ A/B
def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval of a proportion k / n (a draw counts half)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def ab_game(wa: Weights, wb: Weights, a_black: bool, time_s: float, threads: int, seed: int, max_moves: int = 200,
            resign: float = 0.03, resign_after: int = 40, max_nodes: int = 3_000_000, a_value=None) -> dict:
    """One game, A against B.  `a_value` (a value.ValueModel) gives engine A a ValueHook."""
    cfg = lambda s: MCTSConfig(max_nodes=max_nodes, threads=threads, seed=s)   # noqa: E731
    hook = None
    if a_value is not None:
        from ..policy import Policy
        from .value import ValueHook
        hook = ValueHook(a_value, Policy(wa), seed=seed)
    ea = MCTS(Board(9, 7.5), config=cfg(seed), weights=wa, on_expand=hook)
    if hook is not None:
        hook.engine = ea
    eb = MCTS(Board(9, 7.5), config=cfg(seed + 1), weights=wb)
    played, resigned_by, t0 = [], None, time.time()
    sims = {"A": [], "B": []}
    while not ea.root_board.terminal and len(played) < max_moves:
        color = ea.root_board.to_play
        a_moves = (color == "X") == a_black
        eng = ea if a_moves else eb
        r = eng.search(time_s=time_s, threads=threads)
        sims["A" if a_moves else "B"].append(r["sims"])
        if len(played) + 1 >= resign_after and r["q"] < resign:
            resigned_by = color
            break
        played.append((1 if color == "X" else 2, r["best_move"]))
        ea.advance(r["best_move"])
        eb.advance(r["best_move"])
    res, res_str = _result_black(ea, resigned_by)
    a_res = res if a_black else -res
    out = {"seed": seed, "a_color": "B" if a_black else "W", "result": res_str, "a_score": a_res,
           "moves": len(played), "time_s": round(time.time() - t0, 1),
           "sims_a": int(np.mean(sims["A"])) if sims["A"] else 0, "sims_b": int(np.mean(sims["B"])) if sims["B"] else 0,
           "value_hook": None if hook is None else {"calls": hook.calls, "seconds": round(hook.seconds, 2)},
           "sgf": _sgf(played, res_str, wa.version if a_black else wb.version, wb.version if a_black else wa.version,
                       "weights-ab (code only)")}
    ea.close()
    eb.close()
    return out


def _ab_worker(args) -> list[dict]:
    a_path, b_path, idx, time_s, threads, seed, max_moves, resign, a_value_path = args
    from .data import limit_blas_threads
    limit_blas_threads(1)
    wa, wb = Weights.load(a_path), Weights.load(b_path)
    av = None
    if a_value_path:
        from .value import load_value_model
        av = load_value_model(a_value_path)
    return [dict(ab_game(wa, wb, i % 2 == 0, time_s, threads, seed + 2 * i, max_moves, resign, a_value=av), game=i)
            for i in idx]


def weights_ab(a: Path, b: Path, games: int, time_s: float, threads: int, procs: int = 1, seed: int = 0,
               run: Optional[Path] = None, max_moves: int = 200, resign: float = 0.03,
               a_value_model: Optional[Path] = None, log: Callable[[str], None] = print) -> dict:
    """A vs B; game i has A as black iff i is even.  `procs` processes play in parallel, each with
    `threads` search threads.  `a_value_model` (a learner's state.json or a model JSON) gives
    engine A the value model through a ValueHook."""
    from .data import limit_blas_threads
    limit_blas_threads(1)
    wa, wb = Weights.load(a), Weights.load(b)
    av = None
    if a_value_model:
        from .value import load_value_model
        av = load_value_model(a_value_model)
    t0 = time.time()
    if procs <= 1:
        rows = []
        for i in range(games):
            g = dict(ab_game(wa, wb, i % 2 == 0, time_s, threads, seed + 2 * i, max_moves, resign, a_value=av), game=i)
            rows.append(g)
            log(f"game {i}: A ({wa.version}) {g['a_color']} {g['result']} -> A {'won' if g['a_score'] > 0 else 'lost'}"
                f" ({g['moves']} moves, {g['time_s']}s)")
    else:
        import concurrent.futures as cf
        import multiprocessing as mp
        chunks = [list(range(p, games, procs)) for p in range(procs)]
        with cf.ProcessPoolExecutor(max_workers=procs, mp_context=mp.get_context("spawn")) as ex:
            futs = [ex.submit(_ab_worker, (str(a), str(b), c, time_s, threads, seed, max_moves, resign,
                                           str(a_value_model) if a_value_model else None))
                    for c in chunks if c]
            rows = []
            for f in cf.as_completed(futs):
                for g in f.result():
                    rows.append(g)
                    log(f"game {g['game']}: A {g['a_color']} {g['result']} -> A "
                        f"{'won' if g['a_score'] > 0 else 'lost'} ({g['moves']} moves)")
        rows.sort(key=lambda g: g["game"])
    wins = sum(1 for g in rows if g["a_score"] > 0)
    draws = sum(1 for g in rows if g["a_score"] == 0)
    n = len(rows)
    lo, hi = wilson(wins + 0.5 * draws, n)
    by = {c: {"games": sum(1 for g in rows if g["a_color"] == c),
              "a_wins": sum(1 for g in rows if g["a_color"] == c and g["a_score"] > 0)} for c in ("B", "W")}
    summ = {"a": str(a), "b": str(b), "a_version": wa.version, "b_version": wb.version, "a_digest": wa.digest,
            "b_digest": wb.digest, "games": n, "a_wins": wins, "draws": draws,
            "a_winrate": (wins + 0.5 * draws) / n if n else None, "ci95": [lo, hi], "by_a_color": by,
            "time_per_move": time_s, "threads": threads, "procs": procs, "seed": seed,
            "a_value_model": None if av is None else {"source": str(a_value_model), "version": av.version},
            "resigned": sum(1 for g in rows if g["result"].endswith("+R")),
            "mean_moves": float(np.mean([g["moves"] for g in rows])) if rows else 0,
            "mean_sims_a": float(np.mean([g["sims_a"] for g in rows])) if rows else 0,
            "mean_sims_b": float(np.mean([g["sims_b"] for g in rows])) if rows else 0,
            "wall_s": round(time.time() - t0)}
    if run:
        run = Path(run)
        (run / "sgf").mkdir(parents=True, exist_ok=True)
        with open(run / "games.jsonl", "w") as f:
            for g in rows:
                f.write(json.dumps({k: v for k, v in g.items() if k != "sgf"}) + "\n")
                (run / "sgf" / f"ab{g['game']:03d}.sgf").write_text(g["sgf"])
        (run / "summary.json").write_text(json.dumps(summ, indent=1) + "\n")
    return summ


# ------------------------------------------------------------------ report
def report(run: Path) -> dict:
    """Every version of a learner run dir on the final held-out nodes and the regression set."""
    run = Path(run)
    learner = OnlineLearner(run)
    _, ho = learner.split()
    rows = []
    for p in learner.versions():
        d = json.loads(p.read_text())
        w = Weights.from_json(d)
        hl = d.get("hl", {})
        m = learner.evaluate(w, ho)
        reg = regression_metrics(w)
        g = check_guards(w)
        rows.append({"file": p.name, "version": w.version, "parent": (hl.get("parent") or {}).get("version"),
                     "digest": w.digest, "samples_at_fit": (hl.get("samples") or {}).get("total"),
                     "heldout_ce": m and m["ce"], "heldout_kl": m and m["kl_mean"], "heldout_top1": m and m["top1"],
                     "regression_ce": reg and reg["ce"], "regression_top1": reg and reg["top1"],
                     "guards": g["passed"], "lam": w.params.get("lam"), "beta": w.params.get("beta")})
    moves = [json.loads(ln) for ln in open(run / "moves.jsonl")] if (run / "moves.jsonl").exists() else []
    changes = [m for m in moves if m.get("version_changed")]
    reuse = {"moves": len(moves), "version_changes_between_moves": len(changes),
             "changes_with_reused_tree": sum(1 for m in changes if m["reused_root_n"] > 0),
             "moves_with_reused_tree": sum(1 for m in moves if m["reused_root_n"] > 0),
             "mean_reused_root_n": float(np.mean([m["reused_root_n"] for m in moves])) if moves else 0}
    ups = [json.loads(ln) for ln in open(run / "updates.jsonl")] if (run / "updates.jsonl").exists() else []
    value = next((u["value"] for u in reversed(ups) if (u.get("value") or {}).get("status") == "fitted"), None)
    mix = ups[-1]["mix"] if ups else None
    return {"run": str(run), "heldout_n": len(ho), "samples": len(learner.samples), "versions": rows, "reuse": reuse,
            "updates": len(ups), "accepted": sum(1 for u in ups if u["accepted"]),
            "update_time_s": {"mean": float(np.mean([u["time_s"] for u in ups])) if ups else None,
                              "max": float(np.max([u["time_s"] for u in ups])) if ups else None},
            "value": value, "mix": mix}


def report_markdown(r: dict, every: int = 1) -> str:
    vs = r["versions"]
    keep = [v for i, v in enumerate(vs) if i % every == 0 or i == len(vs) - 1]
    out = [f"run {r['run']}: {r['samples']} samples, final held-out nodes {r['heldout_n']}, "
           f"{r['updates']} updates, {r['accepted']} accepted",
           "", "| version | parent | samples at fit | held-out CE | held-out top-1 | regression CE | regression top-1 "
           "| guards |", "|---|---|---|---|---|---|---|---|"]
    for v in keep:
        f = lambda x: "-" if x is None else f"{x:.4f}"   # noqa: E731
        out.append(f"| {v['version']} | {v['parent'] or '-'} | {v['samples_at_fit'] or '-'} | {f(v['heldout_ce'])} | "
                   f"{f(v['heldout_top1'])} | {f(v['regression_ce'])} | {f(v['regression_top1'])} | "
                   f"{'pass' if v['guards'] else 'FAIL'} |")
    out.append("")
    out.append("tree reuse: " + json.dumps(r["reuse"]))
    out.append("update time: " + json.dumps(r["update_time_s"]))
    out.append("value model: " + json.dumps(r["value"]))
    out.append("mix: " + json.dumps(r["mix"]))
    return "\n".join(out)
