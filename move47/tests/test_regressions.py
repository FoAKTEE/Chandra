"""Regression tests for issues found in code review."""
import json
import os
import threading
import time
import urllib.request

import pytest

from goarena.arena import Arena, ArenaError, ArenaSettings
from goarena.board import Board, IllegalMove, coord_to_point
from goarena.opponents import load_tiers
from goarena.server import serve
from goarena.store import Store
from harness.dojo.memory import Memory

ROOT = os.path.dirname(os.path.dirname(__file__))


def make_arena(tmp_path, **kw):
    tiers = {k: v for k, v in load_tiers(os.path.join(ROOT, "config/tiers-9x9.json")).items() if v.kind == "random"}
    return Arena(Store(str(tmp_path / "r.db")), ArenaSettings(tiers=tiers, review_visits=0, **kw), None, seed=5)


def test_unicode_digits_are_bad_coordinates():
    with pytest.raises(IllegalMove) as e:
        coord_to_point("A²", 9)
    assert e.value.code == "bad_coordinate"


def test_legality_check_does_not_touch_live_board():
    b = Board(9)
    before = b.cells[:]
    b.legal_moves()
    assert b.cells == before


def test_pause_resume_resets_move_clock(tmp_path):
    a = make_arena(tmp_path, move_timeout_s=0.5)
    run = a.create_run("p")
    a.new_game(run, "random", "black")
    a.set_run_status(run["id"], "paused")
    time.sleep(0.8)
    a.set_run_status(run["id"], "active")
    r = a.play(run, "E5")  # must not be forfeited for time spent paused
    assert r["ok"] and not r["game_over"]
    a.stop()


def test_timeout_only_counts_on_agents_turn(tmp_path):
    a = make_arena(tmp_path, move_timeout_s=0.2)
    run = a.create_run("t")
    g = a.new_game(run, "random", "black")["game"]
    board = a.boards[g["id"]]
    board.play(coord_to_point("E5", 9))  # simulate: agent moved, opponent reply interrupted
    time.sleep(0.4)
    assert a._maybe_timeout(a.store.get_run(run["id"])) is False
    a.stop()


def test_interrupted_opponent_reply_resyncs(tmp_path):
    a = make_arena(tmp_path)
    run = a.create_run("s")
    g = a.new_game(run, "random", "black")["game"]
    board = a.boards[g["id"]]
    mv = board.play(coord_to_point("E5", 9))
    a._record_move(run, a.store.game(g["id"]), board, mv, "agent", 0)
    r = a.play(run, "D4")
    assert not r["ok"] and r["error"]["code"] == "resync"
    assert r["game"]["moves_count"] == 2 and r["game"]["illegal_count"] == 0
    empty = next(f"{'ABCDEFGHJ'[x]}{9 - y}" for y, row in enumerate(r["board_rows"]) for x, c in enumerate(row)
                 if c == "." and (x, y) != (4, 4))
    assert a.play(run, empty)["ok"]  # the agent is back on move and normal play continues
    a.stop()


def test_bad_board_size_rejected(tmp_path):
    a = make_arena(tmp_path)
    with pytest.raises(ArenaError):
        a.create_run("x", config={"size": 21})
    a.stop()


def test_public_api_hides_engine_review_for_live_runs(tmp_path):
    a = make_arena(tmp_path)
    run = a.create_run("v")
    a.new_game(run, "random", "black")
    a.play(run, "resign")
    gid = a.store.finished_games(run["id"])[0]["id"]
    a.store.x("UPDATE games SET review=?, review_summary=? WHERE id=?",
              (json.dumps([{"ply": 1, "best": "E5"}]), json.dumps({"avg_loss": 1.0, "match_rate": 0.5}), gid))
    httpd = serve(a, "127.0.0.1", 0, "adm", viewer_token="")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(path, tok=""):
        req = urllib.request.Request(url + path, headers={"Authorization": f"Bearer {tok}"} if tok else {})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    assert get(f"/api/games/{gid}")["review"] is None
    assert get(f"/api/runs/{run['id']}")["games"][0]["review_summary"] is None
    assert get(f"/api/games/{gid}", "adm")["review"][0]["best"] == "E5"
    a.set_run_status(run["id"], "complete")
    assert get(f"/api/games/{gid}")["review"][0]["best"] == "E5"
    httpd.shutdown()
    a.stop()


def test_memory_tolerates_malformed_edits_and_is_idempotent(tmp_path):
    m = Memory(tmp_path, playbook_chars=200)
    notes = m.apply_edits(["plain string lesson", {"op": "update", "id": "P99", "text": "x"}, 42], 1)
    assert any("added" in n for n in notes)
    m.add_journal(3, "lv1", "B", "B+5", "won", "first")
    m.add_journal(3, "lv1", "B", "B+5", "won", "again")
    assert m.journal().count("#3 ") == 1
    m.apply_edits([{"op": "add", "text": "y" * 150}, {"op": "add", "text": "z" * 150}], 2)
    assert sum(len(i["text"]) + 8 for i in m.playbook()) <= 200
