"""Full-system driver scripts/strength_play.py (two streams with the model service, one shared learner, DAG and
memory; budget stop; teardown) and its report scripts/strength_report.py, against two in-process arenas with
the random tier and the mock worker (no GPU, no model)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness.arena_client import ArenaClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ablation_driver import two_arenas  # noqa: E402,F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent
HL_FAST = ["--hl", "min_train=20", "--hl", "min_heldout=5", "--hl", "fit_time=2", "--hl", "heur_fit_time=2",
           "--hl", "value=false", "--hl", "max_iter=40",
           "--hl", f"regression_path={ROOT / 'tests' / 'no-such-regression-set.json'}"]


def _plan(arenas, tmp_path, **kw):
    plan = {"name": "full system test", "time_per_move": 0, "threads": 2, "llm_workers": 2, "worker": "mock",
            "wrap": "", "seed": 1, "save_every": 0, "wait_for_model_h": 0.01, "drain_s": 60,
            "budget": {"max_cost_usd": 3000, "stop_margin_usd": 40, "game_reserve_usd": 250},
            "arenas": arenas,
            "play_args": ["--sims", "300", "--max-nodes", "300000", "--n-thr", "200", "--decide-extend", "1",
                          "--heuristic-min-visits", "64", "--heuristic-surprises", "3", *HL_FAST],
            "streams": {"A": [{"arena": "ladder", "opponent": "random", "games": 1}],
                        "B": [{"arena": "kata1", "opponent": "random", "games": 1, "color": "W"}]},
            "teardown": [["bash", "-c", f"echo down > {tmp_path / 'teardown.txt'}"]]}
    plan.update(kw)
    return plan


def _drive(plan, tmp_path, run):
    pf = tmp_path / "plan.json"
    pf.write_text(json.dumps(plan))
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, str(ROOT / "scripts/strength_play.py"), "--run", str(run), "--plan", str(pf)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500)


def _jsonl(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def test_strength_driver_two_streams_with_the_model_share_learner_dag_and_memory(two_arenas, tmp_path):
    run = tmp_path / "run"
    p = _drive(_plan(two_arenas, tmp_path), tmp_path, run)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    n_dec, labels = 0, []
    for stream, arena, color in (("A", "ladder", "B"), ("B", "kata1", "W")):
        seg = run / stream / f"00-{arena}-random"
        meta = json.loads((seg / "arena.json").read_text())
        assert oct((seg / "agent.token").stat().st_mode & 0o777) == "0o600" and "token" not in json.dumps(meta)
        cl = ArenaClient(two_arenas[arena]["url"], token=(seg / "agent.token").read_text().strip())
        assert cl.status()["summary"]["games_played"] == 1 and cl.games()["games"][0]["agent_color"] == color
        recs = _jsonl(seg / "moves.jsonl")
        assert recs and all(r["label"].startswith(f"{stream}0g1p") for r in recs)
        assert all(r["model_input"] and r["waited_for_model_s"] == 0.0 and r["llm"] is not None for r in recs)
        assert all(r["heuristic"]["requested"] for r in recs if r["root_n"] >= 64)
        cfg = json.loads((seg / "config.json").read_text())
        assert cfg["llm"]["workers"] == 2 and cfg["threads"] == 2 and cfg["decide"]["rule"] == "evaluated"
        jobs = _jsonl(run / stream / "llm-jobs.jsonl")              # the stream's own service
        assert {"expand", "abstract", "heuristic"} <= {j["kind"] for j in jobs}
        assert all(j["root"].startswith(f"{stream}0g1p") for j in jobs)
        assert (run / stream / "heuristics.jsonl").exists()
        n_dec += len(recs)
        labels += [r["label"] for r in recs]
    # one learner, one DAG, one memory for both streams
    assert not any((run / s / n).exists() for s in "AB" for n in ("dag.db", "memory.db", "hl"))
    assert (run / "dag.db").exists() and (run / "memory.db").exists()
    hl = run / "hl"
    ups = _jsonl(hl / "updates.jsonl")
    assert len(ups) == n_dec and [u["update"] for u in ups] == list(range(1, n_dec + 1))
    assert len(_jsonl(hl / "games.jsonl")) == 2
    props = _jsonl(hl / "proposals.jsonl") if (hl / "proposals.jsonl").exists() else []
    assert {x["label"][:4] for x in props} <= {"A0g1", "B0g1"}
    assert (tmp_path / "teardown.txt").read_text().strip() == "down"
    assert "budget" not in (run / "driver.log").read_text()

    # the report reads it back (arenas, records, learner, book)
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import strength_report as R
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    rep = R.relabel(R.build(run, start_state=None), str(tmp_path))
    rows = {(r["arena"], r["opponent"]): r for r in rep["rows"]}
    assert set(rows) == {("ladder", "random"), ("kata1", "random")}
    assert sum(r["decisions"] for r in rows.values()) == n_dec
    assert all(r["usd_per_move"] == 0.0 and r["sessions_per_move"] > 0 for r in rows.values())
    assert rows[("ladder", "random")]["elo"]["games"] == 1 and rows[("kata1", "random")]["elo"] is None
    assert sum(sum(r["decision_rules"].values()) for r in rows.values()) == n_dec
    assert rep["learning"]["updates"] == n_dec and len(rep["games"]) == 2
    assert all(g["cost_usd"] == 0.0 and g["decisions"] > 0 for g in rep["games"])
    assert rep["totals"]["decisions"] == n_dec and rep["totals"]["model_input_decisions"] == n_dec
    assert rep["run_dir"] == "run" and str(tmp_path) not in json.dumps(rep)
    md = R.markdown(rep)
    assert "## Heuristics book" in md and "## Games" in md and "| random (" in md


def test_strength_driver_stops_before_a_new_game_when_asked(two_arenas, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "control.json").write_text(json.dumps({"stop": True, "reason": "test stop"}))
    p = _drive(_plan(two_arenas, tmp_path), tmp_path, run)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    log = (run / "driver.log").read_text()
    assert "stop requested in control.json (test stop)" in log
    for stream, arena in (("A", "ladder"), ("B", "kata1")):
        seg = run / stream / f"00-{arena}-random"
        cl = ArenaClient(two_arenas[arena]["url"], token=(seg / "agent.token").read_text().strip())
        assert cl.status()["summary"]["games_played"] == 0 and not cl.status().get("active_game")
        assert not (seg / "moves.jsonl").exists()
    assert (tmp_path / "teardown.txt").exists()       # a clean stop still tears down


def test_budget_counts_every_streams_sessions_and_reads_control(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import strength_play as S
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    for s, costs in (("A", [1.5, None, 2.0]), ("B", [10.0])):
        (tmp_path / s).mkdir()
        (tmp_path / s / "llm-jobs.jsonl").write_text("".join(
            json.dumps({"usage": None if c is None else {"cost_usd": c}}) + "\n" for c in costs) + "not json\n")
    assert S.session_cost(tmp_path) == pytest.approx(13.5)
    said = []
    b = S.Budget(tmp_path, {"budget": {"max_cost_usd": 60, "stop_margin_usd": 5, "game_reserve_usd": 50}}, said.append)
    assert b.check(False) is None and "a new game needs 50 USD" in b.check(True)
    (tmp_path / "control.json").write_text(json.dumps({"max_cost_usd": 18}))
    assert "13.50 USD spent, cap 18 USD" in b.check(False)
    (tmp_path / "control.json").write_text(json.dumps({"max_cost_usd": 1000, "game_reserve_usd": 0}))
    assert b.check(True) is None
    assert len(said) == 2                                # each new reason is logged once


def test_hold_pauses_the_arena_run_and_a_paused_run_is_resumed_before_play(two_arenas, tmp_path):
    """While a game waits for the model the driver pauses its arena run (the arena counts no idle time then and
    refuses moves with run_paused); hold(False), or resume_if_paused when a segment (re)starts, makes it active."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import strength_play as S
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    arena = two_arenas["ladder"]
    seg = tmp_path / "seg"
    seg.mkdir()
    run_id, token = S.ensure_run(seg, arena, {"arena": "ladder", "opponent": "random", "games": 1}, "A",
                                 _plan(two_arenas, tmp_path))
    client = ArenaClient(arena["url"], token)
    assert client.new_game("random", "B")["ok"]
    logs = []
    hold = S.arena_hold(arena, run_id, logs.append)
    assert not S.resume_if_paused(client, hold, logs.append)            # active: nothing to do
    hold(True)
    assert client.status()["summary"]["status"] == "paused"
    r = client.play("E5", retries=1)
    assert not r.get("ok") and r["error"]["code"] == "run_paused"
    assert S.resume_if_paused(client, hold, logs.append)
    assert client.status()["summary"]["status"] == "active" and client.play("E5")["ok"]
    assert any("set paused" in x for x in logs) and any("set active" in x for x in logs)
    bad = S.arena_hold({"url": arena["url"], "dir": str(tmp_path / "nowhere")}, run_id, logs.append)
    bad(True)                                                          # errors are logged, never raised
    assert "could not set paused" in logs[-1]
