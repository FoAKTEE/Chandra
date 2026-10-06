"""End-to-end tests of the arena over HTTP, without KataGo (fast)."""
import json
import os
import random
import threading
import urllib.request

import pytest

from goarena.arena import Arena, ArenaSettings
from goarena.board import BLACK, WHITE, Board, point_to_coord
from goarena.opponents import GreedyOpponent, TierSpec, load_tiers
from goarena.server import serve
from goarena.store import Store

ROOT = os.path.dirname(os.path.dirname(__file__))


@pytest.fixture()
def arena_server(tmp_path):
    tiers = {k: v for k, v in load_tiers(os.path.join(ROOT, "config/tiers-9x9.json")).items()
             if v.kind in ("random", "greedy")}
    st = Store(str(tmp_path / "t.db"))
    arena = Arena(st, ArenaSettings(tiers=tiers, max_illegal_per_game=3, review_visits=0), None, seed=7)
    httpd = serve(arena, "127.0.0.1", 0, "adm")
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield arena, f"http://127.0.0.1:{port}"
    httpd.shutdown()
    arena.stop()


def call(url, method, path, token, body=None):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Authorization": f"Bearer {token}",
                                                         "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def board_from_rows(rows, to_play):
    size = len(rows)
    b = Board(size)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in "XO":
                b.cells[y * size + x] = BLACK if ch == "X" else WHITE
    b.to_play = BLACK if to_play == "B" else WHITE
    return b


def test_full_campaign(arena_server):
    arena, url = arena_server
    run = call(url, "POST", "/api/admin/runs", "adm", {"name": "t", "target_games": 4})["run"]
    tok = run["token"]
    assert call(url, "GET", "/api/agent/board", tok)["error"]["code"] == "no_active_game"
    bot = GreedyOpponent(TierSpec("x", "x", "greedy"), random.Random(1))
    for g in range(4):
        r = call(url, "POST", "/api/agent/new", tok, {"opponent": "random" if g % 2 else "greedy"})
        assert r["ok"], r
        # second new game while one is active must fail
        assert call(url, "POST", "/api/agent/new", tok, {"opponent": "random"})["error"]["code"] == "game_in_progress"
        n = 0
        while not r.get("game_over"):
            b = board_from_rows(r["board_rows"], r["to_play"])
            dec = bot.genmove(b, {})
            r = call(url, "POST", "/api/agent/play", tok, {"move": point_to_coord(dec.point, 9)})
            n += 1
            assert r["ok"] or r["error"]["code"] == "superko", r  # our reconstructed board lacks ko history
            if not r["ok"]:
                r = call(url, "POST", "/api/agent/play", tok, {"move": "pass"})
            assert n < 400
        assert r["result"]["result"]
    st = call(url, "GET", "/api/agent/status", tok)
    assert st["summary"]["games_played"] == 4
    # run is complete now
    assert call(url, "POST", "/api/agent/new", tok, {"opponent": "random"})["error"]["code"] == "run_finished"
    lb = call(url, "GET", "/api/leaderboard", "")
    assert lb["runs"][0]["games_played"] == 4
    g1 = call(url, "GET", "/api/agent/games/1", tok)
    assert g1["sgf"].startswith("(;GM[1]")


def test_illegal_limit_and_resign(arena_server):
    arena, url = arena_server
    tok = call(url, "POST", "/api/admin/runs", "adm", {"name": "t2", "target_games": 5})["run"]["token"]
    r = call(url, "POST", "/api/agent/new", tok, {"opponent": "random", "color": "black"})
    assert r["game"]["agent_color"] == "B"
    r = call(url, "POST", "/api/agent/play", tok, {"move": "E5"})
    for i in range(3):
        r = call(url, "POST", "/api/agent/play", tok, {"move": "E5"})
        assert not r["ok"] and r["error"]["code"] == "occupied"
    r = call(url, "POST", "/api/agent/play", tok, {"move": "Z1"})
    assert r["game_over"] and r["result"]["end_reason"] == "illegal_limit"
    r = call(url, "POST", "/api/agent/new", tok, {"opponent": "random"})
    r = call(url, "POST", "/api/agent/resign", tok, {})
    assert r["game_over"] and r["result"]["winner"] == "opponent"
    games = call(url, "GET", "/api/agent/games", tok)["games"]
    assert [g["end_reason"] for g in games] == ["illegal_limit", "resign"]


def test_auth(arena_server):
    arena, url = arena_server
    assert call(url, "GET", "/api/agent/status", "nope")["error"]["code"] == "unauthorized"
    assert call(url, "POST", "/api/admin/runs", "nope", {"name": "x"})["error"]["code"] == "unauthorized"


def test_restart_restores_active_game(tmp_path):
    tiers = {k: v for k, v in load_tiers(os.path.join(ROOT, "config/tiers-9x9.json")).items() if v.kind == "random"}
    st = Store(str(tmp_path / "r.db"))
    a1 = Arena(st, ArenaSettings(tiers=tiers, review_visits=0), None, seed=1)
    run = a1.create_run("restart")
    a1.new_game(run, "random", "black")
    a1.play(run, "C3")
    a1.stop()
    a2 = Arena(Store(str(tmp_path / "r.db")), ArenaSettings(tiers=tiers, review_visits=0), None, seed=2)
    v = a2.board_view(run)
    assert v["game"]["moves_count"] == 2 and v["board_rows"][6][2] == "X"
