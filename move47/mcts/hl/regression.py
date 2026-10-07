"""The regression set every learned weight version is checked against (tracked in mcts/regression/).

* ``guards.json``: hand-written tactical positions.  A guard of kind ``top`` passes when one of
  its moves is among the k highest priors of the weights (the tree's prior: ladders on, the
  version's prior temperature); kind ``avoid`` passes when none of its moves is in the top k.
  A version that fails a guard is never accepted (the learner's gate); default-v1 passes all.
* ``positions.json``: positions from code-only self-play (default-v1 weights) with a deep root
  search's visit distribution as the target; ``python3 -m mcts hl-regression-build`` regenerates
  it.  It is never trained on; the learner reports every candidate's cross-entropy on it and
  refuses one that is worse than its parent by more than a tolerance.
"""
from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

from gotree.position import Position, point

from ..board import Board, board_from_moves
from ..features import move_priors
from ..weights import Weights
from .data import heldout, norm_dist, policy_rows, target_vector
from .fit import PolicySet

DIR = Path(__file__).resolve().parent.parent / "regression"
GUARDS_PATH = DIR / "guards.json"
POSITIONS_PATH = DIR / "positions.json"
FORMAT = "move47-mcts-regression/1"


def guard_board(g: dict) -> Board:
    if "rows" in g:
        cells = "".join(r.replace(" ", "") for r in g["rows"])
        size = int(round(len(cells) ** 0.5))
        return Board.from_position(Position(size, cells, g.get("to_play", "X"), None, 0, g.get("komi", 7.5),
                                            g.get("last")))
    return board_from_moves(g.get("size", 9), g["moves_played"], g.get("komi", 7.5))[0]


@lru_cache(maxsize=4)
def _load_guards(path: str) -> tuple:
    d = json.loads(Path(path).read_text())
    if d.get("format") != FORMAT:
        raise ValueError(f"{path}: not a regression file")
    return tuple(d["guards"])


def load_guards(path: Optional[Path] = None) -> list[dict]:
    return list(_load_guards(str(path or GUARDS_PATH)))


def check_guards(weights: Weights, guards: Optional[list[dict]] = None) -> dict:
    """Every guard's rank of its moves under `weights`; passed iff all guards pass."""
    guards = load_guards() if guards is None else guards
    T = float(weights.params.get("prior_temperature", 1.0))
    out, fails = [], []
    for g in guards:
        b = guard_board(g)
        pri = move_priors(b, weights, temperature=T, ladders=True)
        order = sorted(pri, key=lambda m: -pri[m])
        rank = {m: i + 1 for i, m in enumerate(order)}
        pts = [point(m, b.size) for m in g["moves"]]
        ranks = [rank.get(p) for p in pts]
        k = int(g["k"])
        if g["kind"] == "top":
            ok = any(r is not None and r <= k for r in ranks)
        elif g["kind"] == "avoid":
            ok = all(r is None or r > k for r in ranks)
        else:
            raise ValueError(f"guard {g['name']}: unknown kind {g['kind']!r}")
        res = {"name": g["name"], "kind": g["kind"], "k": k, "moves": g["moves"], "ranks": ranks, "ok": ok}
        out.append(res)
        if not ok:
            fails.append(g["name"])
    return {"passed": not fails, "failures": fails, "guards": out}


# ------------------------------------------------------------------ regression positions
@lru_cache(maxsize=4)
def _load_positions(path: str) -> tuple:
    p = Path(path)
    if not p.exists():
        return ()
    d = json.loads(p.read_text())
    if d.get("format") != FORMAT:
        raise ValueError(f"{path}: not a regression file")
    return tuple(d["positions"])


def load_positions(path: Optional[Path] = None) -> list[dict]:
    return list(_load_positions(str(path or POSITIONS_PATH)))


@lru_cache(maxsize=4)
def _regression_set(path: str) -> Optional[PolicySet]:
    pos = _load_positions(path)
    rows, tgts, ws = [], [], []
    for e in pos:
        b = Board.from_dict(e["board"])
        r = policy_rows(b)
        t = target_vector(r, norm_dist(e["pi"], b.size))
        if t is None:
            continue
        rows.append(r)
        tgts.append(t)
        ws.append(1.0)
    return PolicySet(rows, tgts, ws) if rows else None


def regression_metrics(weights: Weights, path: Optional[Path] = None) -> Optional[dict]:
    """Cross-entropy etc. of the weights' priors against the regression set's deep-search targets."""
    ps = _regression_set(str(path or POSITIONS_PATH))
    if ps is None:
        return None
    return ps.metrics(weights.w, float(weights.params.get("prior_temperature", 1.0)))


def build_positions(out: Path, games: int = 6, per_game: int = 25, move_time: float = 0.3, deep_sims: int = 200_000,
                    threads: int = 16, seed: int = 1000, weights: Optional[Weights] = None, max_nodes: int = 3_000_000,
                    log=print) -> dict:
    """Code-only self-play (weights, default default-v1) at `move_time` per move; from each game
    `per_game` positions at random plies get a fresh deep search of `deep_sims` simulations, whose
    root visit distribution is the target."""
    from ..tree import MCTS, MCTSConfig
    from ..weights import load_default
    w = weights or load_default()
    rng = np.random.default_rng(seed)
    entries = []
    t0 = time.time()
    for g in range(games):
        cfg = MCTSConfig(max_nodes=max_nodes, threads=threads, seed=seed + g)
        eng = MCTS(Board(9, 7.5), config=cfg, weights=w)
        boards: list[tuple[Board, list[int]]] = []
        while not eng.root_board.terminal and len(eng.moves) < 150:
            boards.append((eng.root_board.copy(), list(eng.history)))
            r = eng.search(time_s=move_time, threads=threads)
            eng.advance(r["best_move"])
        eng.close()
        cand = [i for i in range(len(boards)) if not boards[i][0].terminal]
        pick = sorted(rng.choice(cand, size=min(per_game, len(cand)), replace=False).tolist())
        for ply in pick:
            b, hist = boards[ply]
            deep = MCTS(b, history=hist, config=MCTSConfig(max_nodes=max_nodes, threads=threads, seed=seed + 7 * ply),
                        weights=w)
            r = deep.search(sims=deep_sims, threads=threads)
            ch = deep.children(deep.root)
            tot = sum(c["n"] for c in ch)
            pi = {("pass" if c["move"] is None else b.coord(c["move"])): round(c["n"] / tot, 5) for c in ch
                  if c["n"] / tot >= 1e-4}
            entries.append({"id": f"g{g + 1}p{ply + 1}", "board": b.to_dict(), "pi": pi, "q": round(r["q"], 4),
                            "n": int(r["root_n"]), "heldout_split": heldout(b.key, 0.2)})
            deep.close()
        log(f"regression game {g + 1}/{games}: {len(boards)} plies, {len(pick)} positions, {time.time() - t0:.0f}s")
    doc = {"format": FORMAT, "kind": "positions", "created": time.strftime("%Y-%m-%d"),
           "generator": {"games": games, "per_game": per_game, "move_time": move_time, "deep_sims": deep_sims,
                         "threads": threads, "seed": seed, "weights": w.version, "weights_digest": w.digest},
           "positions": entries}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    _load_positions.cache_clear()
    _regression_set.cache_clear()
    return {"positions": len(entries), "bytes": out.stat().st_size, "time_s": time.time() - t0}


def export_heldout(run: Path, out: Path, n: int = 300, min_visits: int = 1000, seed: int = 0) -> dict:
    """A sample of a learner run's held-out nodes (never trained on) with at least `min_visits`
    visits, written in the regression format; tests check learned weights against it."""
    from .learner import OnlineLearner
    L = OnlineLearner(run)
    _, ho = L.split()
    ho = [s for s in ho if s.n >= min_visits]
    rng = np.random.default_rng(seed)
    pick = sorted(rng.choice(len(ho), size=min(n, len(ho)), replace=False).tolist()) if ho else []
    entries = []
    for i in pick:
        s = ho[i]
        b = Board.from_dict(s.board)
        entries.append({"id": f"{s.key:016x}", "board": s.board, "n": s.n, "depth": s.depth, "game": s.game,
                        "pi": {("pass" if m < 0 else b.coord(m)): round(p, 5) for m, p in s.pi.items() if p >= 1e-4},
                        "q": None if s.q is None else round(s.q, 4)})
    st = json.loads((Path(run) / "state.json").read_text())
    doc = {"format": FORMAT, "kind": "heldout", "created": time.strftime("%Y-%m-%d"),
           "source": {"run": Path(run).name, "current": st["current_version"], "current_digest": st["current_digest"],
                      "games": st["game"], "min_visits": min_visits, "heldout_frac": L.cfg["heldout_frac"]},
           "positions": entries}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    return {"positions": len(entries), "bytes": out.stat().st_size}


HELDOUT_PATH = DIR / "heldout-selfplay.json"

__all__ = ["GUARDS_PATH", "POSITIONS_PATH", "check_guards", "load_guards", "load_positions", "regression_metrics",
           "build_positions", "guard_board"]
