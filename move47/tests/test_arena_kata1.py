"""Real-KataGo ladder (config/tiers-9x9-kata1.json), adjudication, and the arena on a kgservice
client that has to wait for its first backend.  No GPU: stub engines and tests/fake_katago.py."""
from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from goarena import __main__ as cli
from goarena.arena import Arena, ArenaSettings
from goarena.board import BLACK, Board, coord_to_point, point_to_coord
from goarena.katago import KataGo, KataGoConfig, KataGoError
from goarena.opponents import KataGoOpponent, TierSpec, _candidate_moves, load_tiers
from goarena.server import rules_text, serve
from goarena.store import Store

ROOT = Path(__file__).resolve().parent.parent
KATA1 = ROOT / "config" / "tiers-9x9-kata1.json"
FAKE = ROOT / "tests" / "fake_katago.py"
CLIENT = ROOT / "bin" / "kg-client"
HOPELESS = (0.005, -25.0)        # agent's (winrate, score lead): inside the default MISSION thresholds
BEHIND = (0.30, -5.0)            # agent behind but alive: breaks a streak, does not make KataGo resign


class StubEngine:
    """Stands in for goarena.katago.KataGo.  Values are reported from BLACK's point of view like the
    real engine (reportAnalysisWinratesAs=BLACK); `script(ply)` gives the AGENT's (winrate, lead)
    for the opponent move about to be played at `ply`."""

    def __init__(self, agent_color="B", script=lambda ply: BEHIND, policy=None):
        self.agent_color, self.script, self.policy = agent_color, script, policy
        self.calls: list[dict] = []

    def analyze(self, board, visits, *, policy=False, ownership=False, analyze_turns=None, priority=0,
                override_settings=None):
        self.calls.append({"visits": visits, "policy": policy, "override": override_settings})
        wr, lead = self.script(len(board.moves) + 1)
        if self.agent_color == "W":
            wr, lead = 1.0 - wr, -lead
        cands = _candidate_moves(board, board.to_play)
        res = {"rootInfo": {"winrate": wr, "scoreLead": lead, "visits": visits},
               "moveInfos": [{"move": point_to_coord(cands[0], board.size) if cands else "pass",
                              "visits": visits, "order": 0}]}
        if policy:
            res["policy"] = list(self.policy) if self.policy else [0.01] * (board.size ** 2 + 1)
        if ownership:
            res["ownership"] = [0.0] * board.size ** 2
        return res


def http(url, method, path, tok="", body=None, raw=False):
    """-> (status, parsed JSON or raw text)"""
    req = urllib.request.Request(url + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status, data = resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        status, data = e.code, e.read().decode()
    return status, (data if raw else json.loads(data))


def start_http(arena):
    httpd = serve(arena, "127.0.0.1", 0, "adm", "view")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


# ---------------------------------------------------------------------------------- the ladder
def test_kata1_ladder_file():
    tiers = load_tiers(KATA1)
    assert list(tiers) == ["random", "greedy", "k1-p", "k1-64", "k1-full"]
    assert not any(t.counts_for_rating for t in tiers.values())
    assert {n: (t.kind, t.visits, t.temperature, t.random_prob) for n, t in tiers.items() if n.startswith("k1-")} \
        == {"k1-p": ("katago", 1, 0.0, 0.0), "k1-64": ("katago", 64, 0.0, 0.0), "k1-full": ("katago", 1600, 0.0, 0.0)}
    assert all(t.public()["elo"] is None for n, t in tiers.items() if n.startswith("k1-"))   # uncalibrated
    assert tiers["k1-p"].root_symmetries == 8
    assert json.loads(KATA1.read_text())["_model"] == "kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz"


def test_k1p_plays_the_policy_argmax_deterministically():
    b = Board(9, 7.5)
    b.play(coord_to_point("E5", 9))
    pol = [0.001] * 82
    pol[coord_to_point("E5", 9)] = 0.9            # occupied: never chosen
    pol[coord_to_point("C3", 9)] = 0.30
    pol[coord_to_point("G7", 9)] = 0.29
    spec = load_tiers(KATA1)["k1-p"]
    picks = set()
    for seed in range(30):
        eng = StubEngine(policy=pol)
        dec = KataGoOpponent(spec, eng, random.Random(seed)).genmove(b, {})
        picks.add(point_to_coord(dec.point, 9))
        assert eng.calls == [{"visits": 1, "policy": True, "override": {"rootNumSymmetriesToSample": 8}}]
    assert picks == {"C3"}
    # the same position with temperature 1 samples (so the check above can tell argmax from sampling)
    hot = TierSpec("hot", "hot", "katago", visits=1, temperature=1.0)
    hot_picks = {point_to_coord(KataGoOpponent(hot, StubEngine(policy=pol), random.Random(s)).genmove(b, {}).point, 9)
                 for s in range(30)}
    assert len(hot_picks) > 1


@pytest.mark.parametrize("name,visits", [("k1-64", 64), ("k1-full", 1600)])
def test_k1_search_tiers_play_the_engines_best_move(name, visits):
    b = Board(9, 7.5)
    eng = StubEngine()
    dec = KataGoOpponent(load_tiers(KATA1)[name], eng, random.Random(3)).genmove(b, {})
    assert eng.calls == [{"visits": visits, "policy": False, "override": None}]
    assert dec.point == _candidate_moves(b, BLACK)[0] and not dec.resign


def test_katago_client_skips_engine_warnings(tmp_path):
    """An engine `warning` line (e.g. an unused overrideSettings key) precedes the real answer;
    it must not be taken as the answer."""
    eng = tmp_path / "warn_engine.py"
    eng.write_text(
        "#!" + sys.executable + "\nimport json, sys\n"
        "for line in sys.stdin:\n"
        "    q = json.loads(line)\n"
        "    print(json.dumps({'id': q['id'], 'field': 'overrideSettings', 'warning': 'unused key'}), flush=True)\n"
        "    print(json.dumps({'id': q['id'], 'turnNumber': len(q['moves']), 'moveInfos': [],\n"
        "                      'rootInfo': {'winrate': 0.4, 'scoreLead': -1.0, 'visits': q['maxVisits']}}), flush=True)\n")
    eng.chmod(0o755)
    (tmp_path / "m.bin.gz").write_bytes(b"x")
    (tmp_path / "c.cfg").write_text("")
    kg = KataGo(KataGoConfig(binary=str(eng), model=str(tmp_path / "m.bin.gz"), config=str(tmp_path / "c.cfg")))
    try:
        r = kg.analyze(Board(9, 7.5), 7, override_settings={"rootNumSymmetriesToSample": 8})
        assert r["rootInfo"]["visits"] == 7 and "warning" not in r
    finally:
        kg.close()


# ------------------------------------------------------------------------------- adjudication
def adj_arena(tmp_path, engine, db="adj.db", **kw):
    tiers = {"k1": TierSpec("k1", "k1", "katago", visits=64, counts_for_rating=False)}
    return Arena(Store(str(tmp_path / db)), ArenaSettings(tiers=tiers, review_visits=0, referee_visits=10, **kw),
                 engine, seed=11)


ON = dict(adjudicate_winrate=0.01, adjudicate_lead=20.0, adjudicate_moves=4, adjudicate_after=30)


def play_out(arena, run, rng, max_plies=80):
    """Random agent (never passes) until the game ends or max_plies are on the board."""
    r = arena.board_view(run)
    while not r.get("game_over") and len(r["moves"]) < max_plies:
        board = arena.boards[r["game"]["id"]]
        cands = _candidate_moves(board, board.to_play)
        r = arena.play(run, point_to_coord(rng.choice(cands), 9) if cands else "pass")
        assert r["ok"], r
    return r


@pytest.mark.parametrize("agent_color,expect_ply", [("B", 38), ("W", 37)])
def test_adjudication_fires_after_n_consecutive_hopeless_moves_past_ply_p(tmp_path, agent_color, expect_ply):
    a = adj_arena(tmp_path, StubEngine(agent_color, lambda ply: HOPELESS), **ON)
    run = a.create_run("adj", target_games=1)
    a.new_game(run, "k1", agent_color)
    r = play_out(a, run, random.Random(1))
    assert r["game_over"] and r["result"]["end_reason"] == "adjudicated"
    # hopeless from the first move, but only opponent moves after ply 30 count: 4 of them end it
    assert len(r["moves"]) == expect_ply
    g = a.store.finished_games(run["id"])[0]
    assert (g["end_reason"], g["winner"], g["agent_score"], g["margin"]) == ("adjudicated", "opponent", 0.0, None)
    assert g["result"] == ("W+" if agent_color == "B" else "B+")
    assert "end_reason=adjudicated" in g["sgf"] and f"RE[{g['result']}]" in g["sgf"]
    assert "You LOST (adjudicated)" in r["text"]
    blob = json.dumps(r)
    assert "winrate" not in blob and "score_lead" not in blob and "0.005" not in blob   # nothing engine-side leaks
    a.stop()


def test_adjudication_streak_resets_on_a_good_move(tmp_path):
    # opponent plies 32, 34 hopeless; 36 merely behind (reset); 38..44 hopeless -> adjudicated at 44, not 38
    a = adj_arena(tmp_path, StubEngine("B", lambda ply: BEHIND if ply == 36 else HOPELESS), **ON)
    run = a.create_run("reset", target_games=1)
    a.new_game(run, "k1", "B")
    r = play_out(a, run, random.Random(2))
    assert r["result"]["end_reason"] == "adjudicated" and len(r["moves"]) == 44
    a.stop()


@pytest.mark.parametrize("script,settings", [
    (lambda ply: HOPELESS, {}),                                         # off by default
    (lambda ply: (0.001, -10.0), ON),                                   # winrate low, lead not low enough
    (lambda ply: (0.05, -40.0), ON),                                    # lead low, winrate not low enough
    (lambda ply: HOPELESS if ply % 4 else BEHIND, ON),                  # never 4 in a row (agent Black)
])
def test_adjudication_does_not_fire(tmp_path, script, settings):
    a = adj_arena(tmp_path, StubEngine("B", script), **settings)
    assert a.s.adjudication_on == bool(settings)
    run = a.create_run("no", target_games=1)
    a.new_game(run, "k1", "B")
    r = play_out(a, run, random.Random(3), max_plies=60)
    assert not r.get("game_over") and len(r["moves"]) == 60
    a.stop()


def test_adjudication_streak_survives_an_arena_restart(tmp_path):
    eng = StubEngine("B", lambda ply: HOPELESS)
    a = adj_arena(tmp_path, eng, **ON)
    run = a.create_run("restart", target_games=1)
    a.new_game(run, "k1", "B")
    r = play_out(a, run, random.Random(4), max_plies=34)          # opponent plies 32, 34 counted
    assert not r["game_over"]
    a.stop()
    b = adj_arena(tmp_path, eng, **ON)                             # same DB: the game is restored
    r = play_out(b, b.store.get_run(run["id"]), random.Random(5))
    assert r["result"]["end_reason"] == "adjudicated" and len(r["moves"]) == 38
    b.stop()


def test_adjudication_reason_is_shown_and_engine_values_stay_hidden(tmp_path):
    a = adj_arena(tmp_path, StubEngine("B", lambda ply: HOPELESS), **ON)
    httpd, url = start_http(a)

    def call(method, path, tok, body=None, raw=False):
        return http(url, method, path, tok, body, raw)[1]

    try:
        run = call("POST", "/api/admin/runs", "adm", {"name": "show", "target_games": 2})["run"]
        tok = run["token"]
        assert "Adjudication: after move 30" in call("GET", "/api/agent/rules", tok)["text"]
        r = call("POST", "/api/agent/new", tok, {"opponent": "k1", "color": "black"})
        rng, seen = random.Random(6), []
        while not r.get("game_over"):
            board = a.boards[r["game"]["id"]]
            r = call("POST", "/api/agent/play", tok, {"move": point_to_coord(rng.choice(_candidate_moves(board, BLACK)), 9)})
            seen.append(r)
        assert r["result"]["end_reason"] == "adjudicated"
        games = call("GET", "/api/agent/games", tok)
        assert games["games"][0]["end_reason"] == "adjudicated" and "adjudicated" in games["text"]
        show = call("GET", "/api/agent/games/1", tok)
        assert show["game"]["end_reason"] == "adjudicated" and show["game"]["result"] == "W+"
        sgf = call("GET", "/api/agent/games/1?format=sgf", tok, raw=True)
        assert "RE[W+]" in sgf and "end_reason=adjudicated" in sgf
        pub = call("GET", f"/api/games/{show['game']['id']}", "view")
        assert pub["game"]["end_reason"] == "adjudicated"
        for blob in [json.dumps(x) for x in seen + [games, show, pub, call("GET", "/api/agent/status", tok)]] + [sgf]:
            assert "winrate" not in blob and "score_lead" not in blob and "scoreLead" not in blob
        # the rule is only announced when it is on
        assert "Adjudication" not in rules_text(adj_arena(tmp_path, None, db="off.db"), a.store.get_run(run["id"]))
    finally:
        httpd.shutdown()
        a.stop()


def test_serve_flags_configure_adjudication():
    a = cli.build_parser().parse_args(["serve", "--tiers", str(KATA1), "--adjudicate-winrate", "0.01",
                                       "--adjudicate-lead", "20", "--adjudicate-moves", "4",
                                       "--adjudicate-after", "30"])
    s = cli._settings(a)
    assert s.adjudication_on and (s.adjudicate_winrate, s.adjudicate_lead, s.adjudicate_moves,
                                  s.adjudicate_after) == (0.01, 20.0, 4, 30)
    assert not cli._settings(cli.build_parser().parse_args(["serve", "--tiers", str(KATA1)])).adjudication_on
    assert not cli._settings(cli.build_parser().parse_args(["review", "--tiers", str(KATA1)])).adjudication_on


# ------------------------------------------------- arena through kg-client, backend arrives late
def test_engine_outage_answers_503_and_the_board_resyncs(tmp_path):
    class Flaky(StubEngine):
        down = False

        def analyze(self, board, visits, **kw):
            if self.down:
                raise KataGoError("KataGo query q9 timed out")
            return super().analyze(board, visits, **kw)

    eng = Flaky("B")
    a = adj_arena(tmp_path, eng)
    httpd, url = start_http(a)
    try:
        tok = a.create_run("outage", target_games=1)["token"]
        assert http(url, "POST", "/api/agent/new", tok, {"opponent": "k1", "color": "black"})[1]["ok"]
        eng.down = True
        st, r = http(url, "POST", "/api/agent/play", tok, {"move": "E5"})
        assert st == 503 and r["error"]["code"] == "engine_unavailable" and "goban board" in r["text"]
        assert a.store.active_game(a.store.list_runs()[0]["id"])["moves_count"] == 1    # the agent's move stands
        eng.down = False
        st, r = http(url, "GET", "/api/agent/board", tok)
        assert st == 200 and r["ok"] and len(r["moves"]) == 2 and r["to_play"] == "B"   # reply generated now
    finally:
        httpd.shutdown()
        a.stop()


def test_arena_waits_for_a_late_kgservice_backend(tmp_path, monkeypatch):
    """Like a pending Slurm job at arena start: the arena starts and serves while kg-client has no
    backend; the opponent's first move completes once a backend registers."""
    run_dir, model, cfg = tmp_path / "run", tmp_path / "fake-net.bin.gz", tmp_path / "fake.cfg"
    model.write_bytes(b"not a real net")
    cfg.write_text("reportAnalysisWinratesAs = SIDETOMOVE\n")
    for k, v in {"KGSERVICE_RUN_DIR": str(run_dir), "KGSERVICE_POLL": "0.05", "KGSERVICE_WAIT": "60"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KGSERVICE_LOG", raising=False)
    kg = KataGo(KataGoConfig(binary=str(CLIENT), model=str(model), config=str(cfg)))
    a = Arena(Store(str(tmp_path / "late.db")), ArenaSettings(tiers=load_tiers(KATA1), review_visits=0,
                                                             referee_visits=10, **ON), kg, seed=3)
    httpd, url = start_http(a)
    backend, qlog, out = None, tmp_path / "queries.jsonl", {}

    def post(path, body, tok):
        return http(url, "POST", path, tok, body)[1]

    try:
        tok = a.create_run("late", target_games=1)["token"]
        th = threading.Thread(target=lambda: out.update(r=post("/api/agent/new", {"opponent": "k1-p",
                                                                                  "color": "white"}, tok)))
        th.start()                                   # the opponent (Black) moves first: blocks on the engine
        time.sleep(1.5)
        assert th.is_alive() and "r" not in out
        with urllib.request.urlopen(url + "/healthz", timeout=5) as resp:   # still serving meanwhile
            assert json.loads(resp.read())["ok"]
        env = dict(os.environ, PYTHONPATH=str(ROOT), FAKE_KATAGO_DELAY="0.02", FAKE_KATAGO_QUERYLOG=str(qlog))
        backend = subprocess.Popen([sys.executable, "-m", "kgservice", "backend", "--model", str(model),
                                    "--config", str(cfg), "--katago", str(FAKE)], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        th.join(45)
        r = out["r"]
        assert r["ok"] and r["opponent_move"] and r["game"]["moves_count"] == 1
        board = a.boards[r["game"]["id"]]
        r2 = post("/api/agent/play", {"move": point_to_coord(_candidate_moves(board, board.to_play)[0], 9)}, tok)
        assert r2["ok"] and r2["opponent_move"] and r2["game"]["moves_count"] == 3
        sent = [json.loads(x) for x in qlog.read_text().splitlines() if x.strip()]
        sent = [q for q in sent if "action" not in q]
        assert sent[0]["maxVisits"] == 1 and sent[0]["includePolicy"]
        assert sent[0]["overrideSettings"] == {"rootNumSymmetriesToSample": 8}    # forwarded by kgservice
    finally:
        kg.close()
        httpd.shutdown()
        a.stop()
        if backend is not None:
            infos = [json.loads(p.read_text()) for p in run_dir.glob("*.json")]
            backend.kill()
            backend.wait()
            for info in infos:
                try:
                    os.kill(int(info.get("engine_pid")), signal.SIGKILL)
                except (OSError, TypeError, ValueError):
                    pass
