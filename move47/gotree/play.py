"""Play arena games with the tree-search harness.

Each of our turns: rebuild the frozen position from the arena's move list,
run the search (the DAG persists across moves and games, so the subtree
explored on the previous move is reused), play the decision.

A move is only ever submitted on the position it was searched for.  When the
arena does not take it for a reason other than an illegal-move rejection
(`resync` after an engine outage, HTTP 503 `engine_unavailable`, a paused run,
a server error, a lost connection or timeout), the move may or may not have been
played, so the board is fetched again (with backoff): a changed position is
searched again, an unchanged one gets the same move again.  Only a genuine
illegal-move rejection falls back to the next candidate.
"""
from __future__ import annotations

import http.client
import json
import time
from pathlib import Path
from typing import Callable, Optional

from harness.arena_client import ArenaClient

from .position import Position, coord, point
from .search import Search

# goarena.board.IllegalMove codes; the arena's illegal-move reply also carries `illegal_attempts`
ILLEGAL_CODES = frozenset({"bad_coordinate", "occupied", "suicide", "superko", "wrong_turn"})
# urllib's URLError, connection resets, socket timeouts (all OSError), a non-JSON body (ValueError)
TRANSPORT_ERRORS = (OSError, ValueError, http.client.HTTPException)
BACKOFF = (5.0, 60.0)      # first and longest pause between attempts, seconds
MAX_WAIT = 7200.0          # give up after this long without a usable board (the engine service waits up to 1 h)


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


def _code(r: dict) -> str:
    return str((r.get("error") or {}).get("code") or "")


def _is_illegal(r: dict) -> bool:
    return "illegal_attempts" in r or _code(r) in ILLEGAL_CODES


def _call(fn, *args, **kw) -> dict:
    """One arena call; a transport failure becomes an error reply instead of an exception."""
    try:
        return fn(*args, **kw)
    except TRANSPORT_ERRORS as e:
        return {"ok": False, "error": {"code": "transport", "message": f"{type(e).__name__}: {e}"}}


def _finished(g: dict) -> dict:
    """A game-over reply built from the arena's game record (the game ended while we were not looking)."""
    game = g["game"]
    return {"ok": True, "game_over": True, "game": game, "moves": [m["coord"] for m in g.get("moves") or []],
            "result": {k: game.get(k) for k in ("result", "winner", "end_reason", "margin")}}


def current_board(client: ArenaClient, game_no: int, log: Callable[[str], None] = print,
                  sleep: Callable[[float], None] = time.sleep, max_wait: float = MAX_WAIT) -> dict:
    """The arena's position for game `game_no` with us to move, or a game-over reply.  Waits out
    engine outages (HTTP 503), server errors and transport failures with exponential backoff."""
    delay, waited = BACKOFF[0], 0.0
    while True:
        r = _call(client.board)
        if r.get("ok") and r.get("game"):
            return r
        code = _code(r)
        if code == "no_active_game":
            g = _call(client.game, game_no)
            if (g.get("game") or {}).get("status") == "finished":
                return _finished(g)
        elif code == "unauthorized":
            raise RuntimeError(f"arena refused the board request: {r.get('error')}")
        if waited >= max_wait:
            raise RuntimeError(f"no usable board after {waited:.0f}s: {r.get('error')}")
        log(f"  board unavailable ({code or r.get('error')}); retrying in {delay:.0f}s")
        sleep(delay)
        waited += delay
        delay = min(delay * 2, BACKOFF[1])


def play_decision(client: ArenaClient, summ: dict, before: list, game_no: int,
                  log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
                  max_wait: float = MAX_WAIT) -> dict:
    """Submit the search's decision for the position with move list `before`.  Returns the reply to
    continue from: the position after the opponent's answer, a finished game, or the current board
    when the position is no longer `before` (the caller searches it again)."""
    first = summ["decision"]["real"]
    order = [first] + [c["real"] for c in summ["candidates"] if c["real"] != first]
    if "pass" not in order:
        order.append("pass")
    i, delay, waited = 0, BACKOFF[0], 0.0
    while True:
        mv = order[i]
        r = _call(client.play, mv, retries=1)   # never resend a POST blindly: it may have been played
        if r.get("ok") or r.get("game_over"):
            return r
        if _is_illegal(r):
            if i + 1 >= len(order):
                raise RuntimeError(f"the arena rejected every candidate including pass: {r.get('error')}")
            log(f"  arena rejected {mv} as illegal ({_code(r)}); trying {order[i + 1]}")
            i += 1
            continue
        log(f"  arena did not take {mv} ({_code(r) or r.get('error')}); fetching the board again")
        cur = current_board(client, game_no, log, sleep, max_wait)
        if cur.get("game_over"):
            return cur
        if list(cur.get("moves") or []) != list(before):
            log(f"  the position changed ({len(before)} -> {len(cur.get('moves') or [])} moves); searching again")
            return cur
        if waited >= max_wait:
            raise RuntimeError(f"{mv} not accepted after {waited:.0f}s: {r.get('error')}")
        log(f"  same position, {mv} was not played; submitting it again in {delay:.0f}s")
        sleep(delay)
        waited += delay
        delay = min(delay * 2, BACKOFF[1])


def play_games(client: ArenaClient, search: Search, opponent: str, games: int, color: Optional[str] = None,
               log: Callable[[str], None] = print, record: Optional[Path] = None,
               sleep: Callable[[float], None] = time.sleep) -> list[dict]:
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
            if not r.get("game"):  # e.g. 503 while the opponent's first move (we are White) was pending
                ag = _call(client.status).get("active_game")
                if not ag:
                    raise RuntimeError(r)
                r = current_board(client, ag["game_no"], log, sleep)
        komi = r["game"]["komi"]
        game_no = r["game"]["game_no"]
        log(f"game #{game_no} vs {r['game']['opponent']} as {r['game']['agent_color']}")
        while not r.get("game_over"):
            pos = position_from_arena(r, komi)
            before = list(r.get("moves") or [])
            t0 = time.time()
            summ = search.run(pos, label=f"game{game_no}-move{len(before) + 1}")
            mv = summ["decision"]["real"]
            log(f"  move {len(before) + 1}: {mv} after {summ['jobs']} jobs, {time.time() - t0:.0f}s "
                f"(top: {', '.join(c['real'] + '/' + str(c['n']) for c in summ['candidates'][:4])})")
            if record:
                with open(record, "a") as f:
                    f.write(json.dumps({"game": game_no, "ply": len(before) + 1, "move": mv,
                                        "summary": summ}, default=str) + "\n")
            r = play_decision(client, summ, before, game_no, log, sleep)
        log(f"  result: {r['result']['result']} ({r['result']['winner']})")
        results.append({"game": game_no, **r["result"]})
    return results


__all__ = ["play_games", "play_decision", "current_board", "position_from_arena", "coord"]
