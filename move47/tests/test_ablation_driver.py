"""Ablation driver scripts/ablation_play.py (two game streams sharing one online learner) and its report
scripts/ablation_report.py, against two in-process arenas with the random tier (no GPU, no model)."""
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

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def two_arenas(tmp_path):
    tiers = {k: v for k, v in load_tiers(ROOT / "config/tiers-9x9.json").items() if v.kind == "random"}
    out, stops = {}, []
    for name in ("ladder", "kata1"):
        ar = Arena(Store(str(tmp_path / f"{name}.db")), ArenaSettings(tiers=tiers, review_visits=0), None, seed=3)
        httpd = serve(ar, "127.0.0.1", 0, "adm")
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        d = tmp_path / f"arena-{name}"
        d.mkdir()
        (d / "admin.token").write_text("adm\n")
        out[name] = {"url": f"http://127.0.0.1:{httpd.server_address[1]}", "dir": str(d)}
        stops.append((httpd, ar))
    yield out
    for httpd, ar in stops:
        httpd.shutdown()
        ar.stop()


def test_ablation_driver_two_streams_share_one_learner(two_arenas, tmp_path):
    plan = {"time_per_move": 0, "threads": 2, "seed": 1, "arenas": two_arenas,
            "play_args": ["--sims", "300", "--max-nodes", "300000"],
            "streams": {"A": [{"arena": "ladder", "opponent": "random", "games": 1}],
                        "B": [{"arena": "kata1", "opponent": "random", "games": 1, "color": "W"}]}}
    pf, run = tmp_path / "plan.json", tmp_path / "run"
    pf.write_text(json.dumps(plan))
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    p = subprocess.run([sys.executable, str(ROOT / "scripts/ablation_play.py"), "--run", str(run), "--plan", str(pf)],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    n_dec = 0
    for stream, arena, color in (("A", "ladder", "B"), ("B", "kata1", "W")):
        seg = run / stream / f"00-{arena}-random"
        meta = json.loads((seg / "arena.json").read_text())
        assert oct((seg / "agent.token").stat().st_mode & 0o777) == "0o600"
        assert "token" not in json.dumps(meta)
        st = ArenaClient(two_arenas[arena]["url"], token=(seg / "agent.token").read_text().strip()).status()
        assert st["summary"]["games_played"] == 1 == st["summary"]["target_games"]
        games = ArenaClient(two_arenas[arena]["url"], token=(seg / "agent.token").read_text().strip()).games()
        assert games["games"][0]["agent_color"] == color
        recs = [json.loads(x) for x in (seg / "moves.jsonl").read_text().splitlines()]
        assert recs and all(r["weights"] for r in recs) and recs[0]["sync"] == "new"
        assert all(r["decision"]["rule"] == "most_visits" for r in recs)
        cfg = json.loads((seg / "config.json").read_text())
        assert cfg["llm"] is None and cfg["engine"]["root_noise"] == 0.25 and cfg["threads"] == 2
        n_dec += len(recs)
    hl = run / "hl"
    ups = [json.loads(x) for x in (hl / "updates.jsonl").read_text().splitlines()]
    assert len(ups) == n_dec                                  # one shared learner saw every decision of both streams
    assert [u["update"] for u in ups] == list(range(1, n_dec + 1))     # one update sequence, serialised
    assert len((hl / "games.jsonl").read_text().splitlines()) == 2
    st = json.loads((hl / "state.json").read_text())
    assert st["updates"] == n_dec and (hl / st["current"]).exists()
    # the report reads the same run back from the arenas
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import ablation_report as R
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    rep = R.relabel(R.build(run), str(tmp_path))
    rows = {(r["arena"], r["opponent"]): r for r in rep["rows"]}
    assert set(rows) == {("ladder", "random"), ("kata1", "random")}
    assert sum(r["decisions"] for r in rows.values()) == n_dec and all(r["games"] == 1 for r in rows.values())
    assert rows[("ladder", "random")]["rated"] and rows[("ladder", "random")]["elo"]["games"] == 1
    assert not rows[("kata1", "random")]["rated"] and rows[("kata1", "random")]["elo"] is None
    assert rep["elo_pooled_rated"]["games"] == 1 and rep["learning"]["updates"] == n_dec
    assert rep["run_dir"] == "run" and str(tmp_path) not in json.dumps(rep)
    md = R.markdown(rep)
    assert "| random (" in md and "## Learning" in md and "## Games" in md
