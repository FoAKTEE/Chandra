"""gotree.play submits a move only on the position it was searched for (no model, no engine).

A fake agent-scope arena client injects the replies the real arena gives after an engine outage
(`resync`, HTTP 503 `engine_unavailable`) and transport failures; only a genuine illegal-move
rejection may fall back to the next candidate."""
import socket
import threading
import urllib.error

import pytest

from gotree.play import BACKOFF, current_board, play_decision, play_games
from gotree.position import Position, point
from harness.arena_client import ArenaClient

UNAVAILABLE = {"ok": False, "error": {"code": "engine_unavailable", "message": "the opponent engine is unavailable"},
               "text": "ERROR (engine_unavailable)"}


class FakeArena:
    """We are Black on 9x9; the opponent answers with `replies` in order.  `faults[name]` holds
    callables that replace the next call of that name (they may change the server state)."""

    def __init__(self, replies=(), moves=(), illegal=()):
        self.moves, self.replies, self.illegal = list(moves), list(replies), set(illegal)
        self.faults = {"play": [], "board": []}
        self.calls = []
        self.over = None

    # server-side helpers
    def apply(self, mv):
        self.moves.append(mv)
        self._two_passes()

    def reply(self):
        self.moves.append(self.replies.pop(0))
        self._two_passes()

    def _two_passes(self):
        if self.moves[-2:] == ["pass", "pass"]:
            self.over = {"result": "W+7.5", "winner": "opponent", "end_reason": "score", "margin": 7.5}

    def view(self, **extra):
        pos = Position.from_moves(9, [("X" if i % 2 == 0 else "O", None if m == "pass" else point(m, 9))
                                      for i, m in enumerate(self.moves)], 7.5)
        out = {"ok": True, "game": {"id": 1, "game_no": 1, "opponent": "k1-full", "agent_color": "B", "size": 9,
                                    "komi": 7.5, "status": "finished" if self.over else "active",
                                    "moves_count": len(self.moves), "illegal_count": 0},
               "to_play": "B" if len(self.moves) % 2 == 0 else "W",
               "board_rows": [pos.cells[i * 9:(i + 1) * 9] for i in range(9)],
               "moves": list(self.moves), "game_over": bool(self.over)}
        if self.over:
            out["result"] = dict(self.over)
        out.update(extra)
        return out

    # agent-scope client API
    def status(self):
        self.calls.append(("status", None))
        active = None if self.over else {"id": 1, "game_no": 1, "opponent": "k1-full", "agent_color": "B",
                                         "moves_count": len(self.moves)}
        return {"ok": True, "summary": {"games_played": 1 if self.over else 0, "target_games": 1},
                "active_game": active}

    def board(self):
        self.calls.append(("board", None))
        if self.faults["board"]:
            return self.faults["board"].pop(0)()
        if self.over:
            return {"ok": False, "error": {"code": "no_active_game", "message": "No game in progress."}}
        if len(self.moves) % 2 == 1:   # the opponent's delayed reply is generated now (Arena.board_view)
            self.reply()
            if self.over:
                return self.view()
        return self.view()

    def play(self, move, retries=5):
        self.calls.append(("play", move))
        if self.faults["play"]:
            return self.faults["play"].pop(0)(move)
        if len(self.moves) % 2 == 1 and not self.over:   # Arena.play: the opponent's reply was interrupted
            self.reply()
            return self.view(ok=False, error={"code": "resync", "message": "the opponent's reply was delayed"})
        if move in self.illegal:
            return self.view(ok=False, error={"code": "occupied", "message": f"{move} is occupied"},
                             illegal_attempts=1, illegal_limit=10)
        self.apply(move)
        if not self.over:
            self.reply()
        return self.view(your_move=move, opponent_move=self.moves[-1])

    def game(self, game_no):
        self.calls.append(("game", game_no))
        v = self.view()
        v["game"].update(self.over or {})
        return {"ok": True, "game": v["game"], "moves": [{"ply": i + 1, "coord": m} for i, m in enumerate(self.moves)]}

    def plays(self):
        return [a for k, a in self.calls if k == "play"]


def summ(*cands):
    return {"decision": {"real": cands[0]}, "candidates": [{"real": c, "n": 4 - i} for i, c in enumerate(cands)]}


def run(fa, s, before, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return play_decision(fa, s, list(before), 1, log=lambda m: None, sleep=sleeps.append)


def test_illegal_rejection_falls_back_to_the_next_candidate():
    fa = FakeArena(replies=["E5"], illegal={"D4"})
    r = run(fa, summ("D4", "C3", "G7"), [])
    assert fa.plays() == ["D4", "C3"] and r["ok"] and r["moves"] == ["C3", "E5"]


def test_engine_unavailable_after_our_move_waits_for_the_reply_and_returns_the_new_position():
    fa = FakeArena(replies=["E5"])
    fa.faults["play"].append(lambda mv: (fa.apply(mv), UNAVAILABLE)[1])   # move kept, reply pending
    fa.faults["board"].append(lambda: UNAVAILABLE)                          # engine still down
    sleeps = []
    r = run(fa, summ("D4", "C3"), [], sleeps)
    assert fa.plays() == ["D4"]                         # C3 was never sent
    assert r["ok"] and r["moves"] == ["D4", "E5"] and fa.moves == ["D4", "E5"]
    assert sleeps == [BACKOFF[0]]


def test_resync_reply_is_searched_again_not_answered_with_the_next_candidate():
    # our earlier C3 was kept but its reply was lost; the arena does not play D4 and shows the new position
    fa = FakeArena(replies=["E5"], moves=["C3"])
    r = run(fa, summ("D4", "C3", "G7"), [])
    assert fa.plays() == ["D4"] and fa.moves == ["C3", "E5"]
    assert r["ok"] and r["moves"] == ["C3", "E5"] and not r.get("game_over")


def test_reply_lost_in_transport_after_the_move_was_played_is_not_resent():
    fa = FakeArena(replies=["E5"])

    def played_then_reset(mv):
        fa.apply(mv)
        fa.reply()
        raise ConnectionResetError("connection reset by peer")
    fa.faults["play"].append(played_then_reset)
    r = run(fa, summ("D4", "C3"), [])
    assert fa.plays() == ["D4"] and fa.moves == ["D4", "E5"] and r["moves"] == ["D4", "E5"]


def test_move_that_never_arrived_is_resent_on_the_unchanged_position():
    fa = FakeArena(replies=["E5"])

    def refused(*_):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))
    fa.faults["play"].append(refused)          # arena restarting: nothing was played
    fa.faults["board"].append(refused)         # ... and the board is not reachable yet either
    sleeps = []
    r = run(fa, summ("D4", "C3"), [], sleeps)
    assert fa.plays() == ["D4", "D4"] and fa.moves == ["D4", "E5"] and r["ok"]
    assert sleeps == [BACKOFF[0], BACKOFF[0]]  # one wait for the board, one before resending


def test_game_that_ended_while_the_reply_was_lost_is_reported_over():
    fa = FakeArena(replies=["pass"], moves=["D4", "E5"])

    def ended_then_timeout(mv):
        fa.apply(mv)
        fa.reply()                              # pass, pass: the game is scored
        assert fa.over
        raise TimeoutError("timed out")
    fa.faults["play"].append(ended_then_timeout)
    r = run(fa, summ("pass", "C3"), ["D4", "E5"])
    assert fa.plays() == ["pass"] and r["game_over"] and r["result"]["winner"] == "opponent"
    assert r["result"]["end_reason"] == "score"


def test_current_board_gives_up_after_max_wait_and_stops_on_bad_token():
    fa = FakeArena()
    fa.faults["board"].extend([lambda: UNAVAILABLE] * 50)
    sleeps = []
    with pytest.raises(RuntimeError, match="no usable board"):
        current_board(fa, 1, log=lambda m: None, sleep=sleeps.append, max_wait=100)
    assert sleeps[:3] == [5.0, 10.0, 20.0] and sum(sleeps) >= 100 and max(sleeps) <= BACKOFF[1]
    fa.faults["board"] = [lambda: {"ok": False, "error": {"code": "unauthorized"}}]
    with pytest.raises(RuntimeError, match="refused"):
        current_board(fa, 1, log=lambda m: None, sleep=sleeps.append)


class StubSearch:
    def __init__(self, decisions):
        self.decisions, self.positions = list(decisions), []

    def run(self, pos, label=""):
        self.positions.append(label)
        d = self.decisions.pop(0)
        return {"decision": {"real": d}, "candidates": summ(d, "A1")["candidates"], "jobs": 1}


def test_play_games_survives_an_outage_at_start_and_searches_each_new_position():
    fa = FakeArena(replies=["E5", "pass"], moves=["D4"])    # resumed game, reply to D4 pending
    fa.faults["board"].append(lambda: UNAVAILABLE)
    fa.faults["play"].append(lambda mv: (fa.apply(mv), UNAVAILABLE)[1])   # C3 kept, reply delayed
    st = StubSearch(["C3", "pass"])
    res = play_games(fa, st, "k1-full", 1, log=lambda m: None, sleep=lambda s: None)
    assert st.positions == ["game1-move3", "game1-move5"]   # the search ran on each position once
    assert fa.moves == ["D4", "E5", "C3", "pass", "pass"] and fa.plays() == ["C3", "pass"]
    assert res == [{"game": 1, "result": "W+7.5", "winner": "opponent", "end_reason": "score", "margin": 7.5}]


def test_arena_client_play_with_one_try_does_not_resend_after_a_dropped_connection():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    seen = []

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            seen.append(c.recv(65536))
            c.close()                           # request read, connection dropped without a reply
    threading.Thread(target=serve, daemon=True).start()
    client = ArenaClient(f"http://127.0.0.1:{srv.getsockname()[1]}", token="t", timeout=5)
    with pytest.raises(OSError):
        client.play("D4", retries=1)
    srv.close()
    assert len(seen) == 1 and b"/api/agent/play" in seen[0]
