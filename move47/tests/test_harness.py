"""Harness tests: Dojo with the mock model, and the runner's relaunch loop."""
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
from harness.arena_client import ArenaClient
from harness.dojo.agent import Dojo, DojoConfig
from harness.dojo.llm import make_llm

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def arena_url(tmp_path):
    tiers = {k: v for k, v in load_tiers(ROOT / "config/tiers-9x9.json").items() if v.kind in ("random", "greedy")}
    arena = Arena(Store(str(tmp_path / "h.db")), ArenaSettings(tiers=tiers, review_visits=0), None, seed=3)
    httpd = serve(arena, "127.0.0.1", 0, "adm")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    arena.stop()


def _run(url, games):
    out = ArenaClient(url, admin_token="adm").create_run(name="t", target_games=games)
    return out["run"]


@pytest.mark.parametrize("mode", ["episodic", "single"])
def test_dojo_mock_campaign(arena_url, tmp_path, mode):
    run = _run(arena_url, 4)
    client = ArenaClient(arena_url, token=run["token"])
    cfg = DojoConfig(consolidate_every=2, context_mode=mode, compact_chars=20_000)
    Dojo(make_llm("mock", "mock", seed=1), client, tmp_path, cfg, log=lambda m: None).run()
    st = client.status()["summary"]
    assert st["games_played"] == 4 and st["status"] == "complete"
    mem = tmp_path / "dojo"
    assert len(list((mem / "reviews").glob("*.md"))) == 4
    assert len((mem / "journal.md").read_text().splitlines()) == 4
    assert json.loads((mem / "state.json").read_text())["last_consolidation"] == 4
    assert (mem / "plan.md").read_text().strip()
    # in episodic mode the per-call context must not grow with the number of games
    if mode == "episodic":
        sizes = [json.loads(l)["context_chars"] for l in (mem / "usage.jsonl").read_text().splitlines()
                 if json.loads(l)["phase"] == "play"]
        assert max(sizes) < 20_000


def test_dojo_resumes_active_game(arena_url, tmp_path):
    run = _run(arena_url, 2)
    client = ArenaClient(arena_url, token=run["token"])
    client.new_game("random", "black")
    client.play("E5")
    Dojo(make_llm("mock", "mock"), client, tmp_path, DojoConfig(), log=lambda m: None).run()
    games = client.games()["games"]
    assert len(games) == 2 and games[0]["moves_count"] > 2


def test_runner_relaunches_fake_cli(arena_url, tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    p = subprocess.run([sys.executable, "-m", "harness.runner", "--harness", "claude-code",
                        "--claude-bin", str(ROOT / "tests/fake_cli_agent.py"), "--arena", arena_url,
                        "--admin-token", "adm", "--games", "3", "--run-dir", str(tmp_path / "run"),
                        "--model", "fake"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert "run complete: 3/3" in p.stdout, p.stdout + p.stderr
    state = json.loads((tmp_path / "run/logs/state.json").read_text())
    assert len(state["sessions"]) == 3 and all(s["session_id"] for s in state["sessions"])
    assert (tmp_path / "run/workspace/TASK.md").exists()
    assert not (tmp_path / "run/workspace/logs").exists()


def test_runner_generic_command_adapter(arena_url, tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    tpl = f"{sys.executable} {ROOT / 'tests/fake_cli_agent.py'} --prompt {{prompt}} --model {{model}}"
    p = subprocess.run([sys.executable, "-m", "harness.runner", "--harness", "cmd", "--cmd", tpl, "--arena", arena_url,
                        "--admin-token", "adm", "--games", "2", "--run-dir", str(tmp_path / "run"), "--model", "m1"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert "run complete: 2/2" in p.stdout, p.stdout + p.stderr
    assert (tmp_path / "run/workspace/AGENTS.md").exists()
