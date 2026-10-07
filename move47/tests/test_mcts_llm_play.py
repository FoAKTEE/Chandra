"""MCTS v2 arena play loop with the LLM service (mcts/play.py) and the runner's mcts adapter (no model)."""
import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from goarena.arena import Arena, ArenaSettings
from goarena.opponents import load_tiers
from goarena.server import serve
from goarena.store import Store
from gotree.dag import DAG
from gotree.memory import Memory
from gotree.position import Position, coord, point
from gotree.workers import MockWorker
from harness.arena_client import ArenaClient
from harness.runner import ADAPTERS
from mcts.decide import RULES
from mcts.llm import LLMConfig, LLMService
from mcts.play import Player, make_learner, play_games
from mcts.tree import MCTSConfig

ROOT = Path(__file__).resolve().parent.parent


class FakeArena:
    """Agent-scope arena client, 9x9, we are Black.  The opponent's reply comes from `reply_fn(moves)`;
    the game ends (as an adjudicated loss) after `max_plies` plies.  `crash_on_play=k` raises on the
    k-th play call, like a process that dies while submitting."""

    def __init__(self, reply_fn, max_plies=8, crash_on_play=None):
        self.reply_fn, self.max_plies, self.crash_on_play = reply_fn, max_plies, crash_on_play
        self.moves, self.over, self.started, self.plays = [], None, False, 0

    def _end_check(self):
        if len(self.moves) >= self.max_plies:
            self.over = {"result": "W+", "winner": "opponent", "end_reason": "adjudicated", "margin": None}

    def view(self, **extra):
        pos = Position.from_moves(9, [("X" if i % 2 == 0 else "O", None if m == "pass" else point(m, 9))
                                      for i, m in enumerate(self.moves)], 7.5)
        out = {"ok": True, "game": {"id": 1, "game_no": 1, "opponent": "fake", "agent_color": "B", "size": 9,
                                    "komi": 7.5, "status": "finished" if self.over else "active",
                                    "moves_count": len(self.moves)},
               "to_play": "B" if len(self.moves) % 2 == 0 else "W",
               "board_rows": [pos.cells[i * 9:(i + 1) * 9] for i in range(9)], "moves": list(self.moves),
               "game_over": bool(self.over)}
        if self.over:
            out["result"] = dict(self.over)
        out.update(extra)
        return out

    def status(self):
        active = {"id": 1, "game_no": 1, "opponent": "fake", "agent_color": "B",
                  "moves_count": len(self.moves)} if self.started and not self.over else None
        return {"ok": True, "summary": {"games_played": 1 if self.over else 0, "target_games": 1},
                "active_game": active}

    def new_game(self, opponent, color=None):
        self.started = True
        return self.view()

    def board(self):
        if self.over:
            return {"ok": False, "error": {"code": "no_active_game", "message": "No game in progress."}}
        return self.view()

    def play(self, move, retries=5):
        self.plays += 1
        if self.crash_on_play and self.plays == self.crash_on_play:
            raise RuntimeError("simulated crash while submitting")
        self.moves.append(move)
        self._end_check()
        if not self.over:
            self.moves.append(self.reply_fn(list(self.moves)))
            self._end_check()
        return self.view(your_move=move)

    def game(self, game_no):
        v = self.view()
        v["game"].update(self.over or {})
        return {"ok": True, "game": v["game"], "moves": [{"ply": i + 1, "coord": m} for i, m in enumerate(self.moves)]}


def tree_reply(holder, log):
    """Reply with the most-visited answer in our own tree; remember that node's visit count."""
    def reply(moves):
        eng = holder["player"].eng
        ours = point(moves[-1], 9)
        child = next(c for c in eng.children(eng.root) if c["move"] == ours)
        gch = [c for c in eng.children(child["child"]) if c["child"] >= 0 and c["n"] > 0] if child["child"] >= 0 else []
        if not gch:
            pos = Position.from_moves(9, [("X" if i % 2 == 0 else "O", point(m, 9)) for i, m in enumerate(moves)])
            log.append(None)
            return coord(next(p for p in pos.legal_moves() if p is not None), 9)
        best = max(gch, key=lambda c: c["n"])
        log.append(int(eng.a.n[best["child"]]))
        return coord(best["move"], 9)
    return reply


class FakeLearner:
    def __init__(self):
        self.calls = {"observe": 0, "observe_external": 0, "update": 0, "observe_game": []}
        self.provider = None

    def observe(self, position, visit_distribution, q, depth, **kw):
        self.calls["observe"] += 1

    def observe_external(self, position, source, priors, value):
        self.calls["observe_external"] += 1

    def update(self):
        self.calls["update"] += 1

    def observe_game(self, result, our_color):
        self.calls["observe_game"].append((result, our_color))


class SettledPlayer(Player):
    """Lets the (instant) mock service finish its queue before each search, so that every root has its
    LLM evaluation when the decision is made (in a real game the search takes minutes)."""

    def decide(self):
        if self.service is not None:
            self.service.wait_idle(10)
        return super().decide()


def make_service(run, worker=None, learner=None, **kw):
    cfg = LLMConfig(workers=2, dispatch_delay_s=0.0, poll_s=0.02, refute_after_s=0.0, **kw)
    return LLMService(worker or MockWorker(), DAG(str(run / "dag.db")), Memory(str(run / "memory.db")), cfg,
                      learner=learner, log=lambda m: None, record=run / "llm-jobs.jsonl", jobs_dir=run / "jobs").start()


def records(run):
    return [json.loads(x) for x in (run / "moves.jsonl").read_text().splitlines()]


def test_play_loop_keeps_the_tree_across_moves_and_records_each_move(tmp_path):
    holder, replies, logs = {}, [], []
    arena = FakeArena(tree_reply(holder, replies), max_plies=8)
    learner = FakeLearner()
    svc = make_service(tmp_path, learner=learner)
    player = SettledPlayer(tmp_path, MCTSConfig(max_nodes=300_000, n_thr=400), None, 2, sims=1500, learner=learner,
                           service=svc, save_every=0, log=logs.append)
    holder["player"] = player
    res = play_games(arena, "fake", 1, player, record=tmp_path / "moves.jsonl", log=logs.append,
                     sleep=lambda s: None)
    svc.wait_idle(20)
    svc.close()
    assert res == [{"game": 1, "result": "W+", "winner": "opponent", "end_reason": "adjudicated", "margin": None}]
    rec = records(tmp_path)
    assert [r["ply"] for r in rec] == [1, 3, 5, 7] and rec[0]["sync"] == "new"
    assert all(r["sync"] == "advanced" for r in rec[1:])            # one tree per game, never reset
    for r, n in zip(rec[1:], replies):                              # the new root keeps its statistics exactly
        assert n is not None and n > 0 and r["root_n_start"] == n
    assert all(r["root_n"] >= r["root_n_start"] + 1500 for r in rec)
    for r in rec:
        top, rule = r["root_table"][0], r["decision"]["rule"]
        assert top["n"] == max(x["n"] for x in r["root_table"]) and rule in RULES
        if rule == "evaluated_among_top":           # the leader had no model value: an evaluated top candidate
            chosen = next(x for x in r["root_table"] if x["move"] == r["move"])
            assert chosen["evaluated"] and not top["evaluated"]
        else:
            assert r["move"] == top["move"]
        assert {"prior", "prior_learned", "llm_prior", "pv"} <= set(r["root_table"][0]) and r["weights"] == "default-v1"
        assert {"launched", "ok", "failed", "cache_hits", "cost_usd", "applied", "queue", "running"} <= set(r["llm"])
    assert sum(r["llm"]["launched"] for r in rec) >= 4 and rec[-1]["llm_root"]["evaluated"]
    jobs = [json.loads(x) for x in (tmp_path / "llm-jobs.jsonl").read_text().splitlines()]
    assert {"expand", "abstract"} <= {j["kind"] for j in jobs}      # lessons after decisions
    assert learner.calls["update"] == 4 and learner.calls["observe_game"] == [("W+", "B")]
    assert learner.calls["observe"] > 0 and learner.calls["observe_external"] > 0


def test_a_restarted_process_resumes_the_game_from_the_saved_tree(tmp_path):
    holder, replies = {}, []
    arena = FakeArena(tree_reply(holder, replies), max_plies=10, crash_on_play=3)
    cfg = MCTSConfig(max_nodes=300_000)
    svc = make_service(tmp_path)
    player = Player(tmp_path, cfg, None, 2, sims=1500, service=svc, save_every=1, log=lambda m: None)
    holder["player"] = player
    with pytest.raises(RuntimeError, match="simulated crash"):
        play_games(arena, "fake", 1, player, record=tmp_path / "moves.jsonl", log=lambda m: None)
    svc.wait_idle(10)
    svc.close()
    player.close()
    side = json.loads((tmp_path / "game1-tree.json").read_text())
    assert (tmp_path / "game1-tree.npz").exists() and len(side["known"]) == 2 and not side["finished"]
    assert len(records(tmp_path)) == 2 and len(arena.moves) == 4

    arena.crash_on_play = None
    logs = []
    svc2 = make_service(tmp_path)
    player2 = Player(tmp_path, cfg, None, 2, sims=1500, service=svc2, save_every=1, log=logs.append)
    holder["player"] = player2
    play_games(arena, "fake", 1, player2, record=tmp_path / "moves.jsonl", log=logs.append)
    svc2.close()
    rec = records(tmp_path)
    assert [r["ply"] for r in rec] == [1, 3, 5, 7, 9]
    assert rec[2]["sync"] == "resumed+advanced" and rec[2]["root_n_start"] == replies[1] > 0
    assert any("resumed the tree of game 1" in x for x in logs)
    assert json.loads((tmp_path / "game1-tree.json").read_text())["finished"]
    # the DAG of the first process was reused: positions it evaluated cost no second job
    jobs = [json.loads(x) for x in (tmp_path / "llm-jobs.jsonl").read_text().splitlines()]
    expands = [j["dag_key"] for j in jobs if j["kind"] == "expand"]
    assert len(expands) == len(set(expands))


def test_code_only_ablation_has_no_llm_fields(tmp_path):
    holder, replies = {}, []
    arena = FakeArena(tree_reply(holder, replies), max_plies=4)
    player = Player(tmp_path, MCTSConfig(max_nodes=200_000), None, 2, sims=500, service=None, save_every=0,
                    log=lambda m: None)
    holder["player"] = player
    play_games(arena, "fake", 1, player, record=tmp_path / "moves.jsonl", log=lambda m: None)
    rec = records(tmp_path)
    assert len(rec) == 2 and rec[0]["llm"] is None and "llm_prior" not in rec[0]["root_table"][0]
    assert rec[1]["sync"] == "advanced" and rec[1]["root_n_start"] == replies[0]
    assert not (tmp_path / "dag.db").exists()


def test_learn_without_the_hl_module_exits_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "mcts.hl", None)
    with pytest.raises(SystemExit, match="--learn needs mcts.hl.OnlineLearner"):
        make_learner(tmp_path, None, print)


def test_learn_builds_the_learner_from_the_hl_module(tmp_path, monkeypatch):
    import types

    class OnlineLearner(FakeLearner):
        def __init__(self, run_dir=None, weights=None):
            super().__init__()
            self.run_dir, self.provider = run_dir, object()
    monkeypatch.setitem(sys.modules, "mcts.hl", types.SimpleNamespace(OnlineLearner=OnlineLearner))
    lr = make_learner(tmp_path, None, print)
    assert isinstance(lr, OnlineLearner) and lr.run_dir == tmp_path / "hl"


def test_runner_mcts_adapter_command(tmp_path):
    a = argparse.Namespace(arena="http://127.0.0.1:9", tree_opponent="k1-p", games=3,
                           tree_worker="claude:claude-opus-5-5:xhigh", extra=["--llm-workers", "8", "--learn"])
    cmd = ADAPTERS["mcts"](a).command(tmp_path / "ws", True, None)
    assert cmd == [sys.executable, "-m", "mcts", "play", "--run", str(tmp_path / "ws" / "mcts"), "--arena",
                   "http://127.0.0.1:9", "--opponent", "k1-p", "--games", "3", "--worker",
                   "claude:claude-opus-5-5:xhigh", "--llm-workers", "8", "--learn"]
    assert ADAPTERS["mcts"](a).command(tmp_path / "ws", False, "sid") == cmd      # relaunch = same command


@pytest.fixture()
def arena_url(tmp_path):
    tiers = {k: v for k, v in load_tiers(ROOT / "config/tiers-9x9.json").items() if v.kind == "random"}
    ar = Arena(Store(str(tmp_path / "h.db")), ArenaSettings(tiers=tiers, review_visits=0), None, seed=5)
    httpd = serve(ar, "127.0.0.1", 0, "adm")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    ar.stop()


def test_runner_plays_a_game_with_the_mcts_harness(arena_url, tmp_path):
    run_dir = tmp_path / "run"
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    p = subprocess.run([sys.executable, "-m", "harness.runner", "--harness", "mcts", "--tree-worker", "mock",
                        "--tree-opponent", "random", "--arena", arena_url, "--admin-token", "adm", "--games", "1",
                        "--run-dir", str(run_dir), "--", "--sims", "200", "--time-per-move", "0", "--threads", "2",
                        "--max-nodes", "300000", "--max-load-frac", "0", "--llm-workers", "2", "--save-every", "10"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert "run complete: 1/1" in p.stdout, p.stdout + p.stderr
    ws = run_dir / "workspace" / "mcts"
    rec = records(ws)
    assert rec and all(r["sync"] in ("new", "advanced") for r in rec) and rec[0]["sync"] == "new"
    assert (ws / "dag.db").exists() and (ws / "llm-jobs.jsonl").exists() and (ws / "config.json").exists()
    assert "llm totals" in (ws / "log.txt").read_text()
    cfg = json.loads((ws / "config.json").read_text())
    assert cfg["worker"] == "mock" and cfg["llm"]["workers"] == 2 and cfg["engine"]["n_thr"] == 100_000
