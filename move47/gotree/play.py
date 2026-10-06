"""Play arena games with the tree-search harness.

Each of our turns: rebuild the frozen position from the arena's move list,
run the search (the DAG persists across moves and games, so the subtree
explored on the previous move is reused), play the decision.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from harness.arena_client import ArenaClient

from .position import Position, coord, point
from .search import Search


def position_from_arena(resp: dict, komi: float) -> Position:
    size = len(resp["board_rows"])
    moves = resp.get("moves") or []
    seq = []
    for i, m in enumerate(moves):
        seq.append(("X" if i % 2 == 0 else "O", None if m.lower() == "pass" else point(m, size)))
    pos = Position.from_moves(size, seq, komi)
    rows = "".join(resp["board_rows"])
    if pos.cells != rows:  # e.g. handicap stones or a server we do not know: trust the board
        pos = Position(size, rows, "X" if resp["to_play"] == "B" else "O", None, 0, komi)
    return pos


def play_games(client: ArenaClient, search: Search, opponent: str, games: int, color: Optional[str] = None,
               log: Callable[[str], None] = print, record: Optional[Path] = None) -> list[dict]:
    results = []
    for _ in range(games):
        st = client.status()
        if not st.get("ok"):
            raise RuntimeError(st)
        s = st["summary"]
        if s["games_played"] >= s["target_games"]:
            log("run complete")
            break
        r = client.board() if st.get("active_game") else client.new_game(opponent, color)
        if not r.get("ok", True) and not r.get("game"):
            raise RuntimeError(r)
        komi = r["game"]["komi"]
        game_no = r["game"]["game_no"]
        log(f"game #{game_no} vs {r['game']['opponent']} as {r['game']['agent_color']}")
        while not r.get("game_over"):
            pos = position_from_arena(r, komi)
            t0 = time.time()
            summ = search.run(pos, label=f"game{game_no}-move{len(r.get('moves') or []) + 1}")
            mv = summ["decision"]["real"]
            log(f"  move {len(r.get('moves') or []) + 1}: {mv} after {summ['jobs']} jobs, {time.time() - t0:.0f}s "
                f"(top: {', '.join(c['real'] + '/' + str(c['n']) for c in summ['candidates'][:4])})")
            if record:
                with open(record, "a") as f:
                    f.write(json.dumps({"game": game_no, "ply": len(r.get("moves") or []) + 1, "move": mv,
                                        "summary": summ}, default=str) + "\n")
            r2 = client.play(mv)
            if not r2.get("ok"):
                log(f"  arena rejected {mv}: {r2.get('error')}; trying the next candidates")
                for c in summ["candidates"][1:]:
                    r2 = client.play(c["real"])
                    if r2.get("ok"):
                        break
                else:
                    r2 = client.play("pass")
            r = r2
        log(f"  result: {r['result']['result']} ({r['result']['winner']})")
        results.append({"game": game_no, **r["result"]})
    return results


__all__ = ["play_games", "position_from_arena", "coord"]
