"""Play goarena games with the code-only MCTS engine, keeping one tree per game.

After our move and the opponent's reply the engine advances twice, so the new root keeps its
whole subtree and statistics (the tree is never reset during a game).  When the arena's move list
is not a continuation of the tree's (a resync, a game resumed by another process) the tree jumps
to the arena's position with set_root(), still keeping everything it has.  Board fetching and move
submission reuse gotree.play's helpers, which survive engine outages and transport errors.

The LLM expansion (M8) attaches through MCTS.on_expand / set_external; this module adds nothing
LLM-specific.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from gotree.play import _call, current_board, play_decision
from gotree.position import IllegalMove, point

from .board import Board, board_from_moves
from .tree import MCTS, MCTSConfig


def _points(moves: list[str], size: int) -> list[Optional[int]]:
    return [None if m.lower() == "pass" else point(m, size) for m in moves]


def board_from_arena(resp: dict, komi: float) -> tuple[Board, list[int], list[Optional[int]]]:
    size = len(resp["board_rows"])
    pts = _points(list(resp.get("moves") or []), size)
    b, hist = board_from_moves(size, pts, komi)
    rows = "".join(resp["board_rows"])
    if b.cells != rows:      # handicap stones or an unknown server: trust the board
        d = {"size": size, "cells": rows, "to_play": "X" if resp["to_play"] == "B" else "O", "komi": komi}
        b, hist = Board.from_dict(d), []
    return b, hist, pts


class ArenaPlayer:
    """Keeps the engine of the current game in step with the arena's move list."""

    def __init__(self, config: MCTSConfig, time_s: float, threads: int, weights=None, sims: Optional[int] = None):
        self.cfg, self.time_s, self.threads, self.weights, self.sims = config, time_s, threads, weights, sims
        self.eng: Optional[MCTS] = None
        self.known: list[Optional[int]] = []      # moves the tree's root has followed

    def new_game(self) -> None:
        if self.eng is not None:
            self.eng.close()
        self.eng, self.known = None, []

    def sync(self, resp: dict, komi: float) -> str:
        b, hist, pts = board_from_arena(resp, komi)
        if self.eng is None:
            self.eng = MCTS(b, history=hist, config=self.cfg, weights=self.weights)
            self.known = pts
            return "new"
        if pts[:len(self.known)] == self.known:
            try:
                for p in pts[len(self.known):]:
                    self.eng.advance(p)
                if self.eng.root_board.key == b.key:
                    self.known = pts
                    return "advanced"
            except IllegalMove:
                pass
        self.eng.set_root(b, hist)
        self.known = pts
        return "set_root"

    def decide(self) -> dict:
        r = self.eng.search(time_s=self.time_s, sims=self.sims, threads=self.threads)
        r["decision"] = {"real": r["best"] or "pass"}
        r["candidates"] = [{"real": m["coord"], "n": m["n"]} for m in r["moves"]]
        return r


def play_games(client, opponent: str, games: int, config: Optional[MCTSConfig] = None, time_s: float = 10.0,
               threads: int = 16, weights=None, color: Optional[str] = None, run_dir: Optional[Path] = None,
               sims: Optional[int] = None, log: Callable[[str], None] = print,
               sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    player = ArenaPlayer(config or MCTSConfig(), time_s, threads, weights, sims)
    results = []
    for _ in range(games):
        st = client.status()
        if not st.get("ok"):
            raise RuntimeError(st)
        s = st["summary"]
        if s["games_played"] >= s["target_games"]:
            log("run complete")
            break
        if st.get("active_game"):
            r = current_board(client, st["active_game"]["game_no"], log, sleep)
        else:
            r = _call(client.new_game, opponent, color)
            if not r.get("game"):
                ag = _call(client.status).get("active_game")
                if not ag:
                    raise RuntimeError(r)
                r = current_board(client, ag["game_no"], log, sleep)
        komi, game_no = r["game"]["komi"], r["game"]["game_no"]
        log(f"game #{game_no} vs {r['game']['opponent']} as {r['game']['agent_color']}")
        player.new_game()
        while not r.get("game_over"):
            before = list(r.get("moves") or [])
            how = player.sync(r, komi)
            t0 = time.time()
            summ = player.decide()
            mv = summ["decision"]["real"]
            log(f"  move {len(before) + 1}: {mv} ({how}) {summ['sims']} sims {time.time() - t0:.1f}s "
                f"root_n {summ['root_n']} q {summ['q']:.3f} nodes {summ['nodes']}")
            if run_dir:
                with open(Path(run_dir) / "moves.jsonl", "a") as f:
                    f.write(json.dumps({"game": game_no, "ply": len(before) + 1, "move": mv, "sync": how,
                                        **{k: v for k, v in summ.items() if k not in ("moves", "candidates")},
                                        "top": summ["moves"][:5]}, default=str) + "\n")
                player.eng.save(Path(run_dir) / f"game{game_no}-tree.npz")
            r = play_decision(client, summ, before, game_no, log, sleep)
        log(f"  result: {r['result']['result']} ({r['result']['winner']})")
        results.append({"game": game_no, **r["result"]})
        player.new_game()
    return results
