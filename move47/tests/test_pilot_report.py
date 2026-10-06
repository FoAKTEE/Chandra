"""scripts/pilot_report.py and scripts/pilot_guard.py on a synthetic run dir and an in-process arena
(random opponent, no model, no engine)."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pilot_guard  # noqa: E402
import pilot_report  # noqa: E402

VIEWER, ADMIN = "vtok-do-not-print-41", "atok-do-not-print-42"


@pytest.fixture
def arena(tmp_path):
    from goarena.arena import Arena, ArenaSettings
    from goarena.opponents import load_tiers
    from goarena.server import serve
    from goarena.store import Store
    tiers = {k: v for k, v in load_tiers(ROOT / "config/tiers-9x9.json").items() if v.kind == "random"}
    ar = Arena(Store(str(tmp_path / "a.db")), ArenaSettings(tiers=tiers, review_visits=0), None, seed=1)
    httpd = serve(ar, "127.0.0.1", 0, ADMIN, VIEWER)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    adir = tmp_path / "arena"
    adir.mkdir()
    (adir / "viewer.token").write_text(VIEWER + "\n")
    (adir / "admin.token").write_text(ADMIN + "\n")
    yield ar, f"http://127.0.0.1:{httpd.server_address[1]}", adir
    httpd.shutdown()
    ar.stop()


def _session(jd: Path, cost: float, cw: int) -> None:
    jd.mkdir(parents=True)
    lines = [{"type": "system", "subtype": "init"},
             {"type": "result", "total_cost_usd": cost,
              "usage": {"input_tokens": 10, "output_tokens": 500, "cache_read_input_tokens": 4000,
                        "cache_creation_input_tokens": cw}}]
    (jd / "session.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def make_run(tmp_path: Path, run_id: str, plays: list[str], t0: float, model: str = "m") -> Path:
    """Runner layout: two finished searches (our plies 1 and 3) and one still running (ply 5)."""
    from gotree.dag import DAG
    run = tmp_path / "pilot"
    (run / "logs").mkdir(parents=True)
    (run / "logs" / "run.json").write_text(json.dumps({"id": run_id, "name": "synthetic pilot",
                                                       "model": model, "harness": "tree"}))
    tree = run / "workspace" / "tree"
    tree.mkdir(parents=True)
    dag = DAG(str(tree / "dag.db"))
    jid = 0
    for i, (ply, mv) in enumerate([(1, plays[0]), (3, plays[1]), (5, None)]):
        start = t0 + 100 * i
        summ = None if mv is None else json.dumps({"seconds": 50.0, "decision": {"real": mv, "rule": "most visited"},
                                                   "candidates": [{"real": mv, "n": 3, "q": 0.55, "prior": 0.4,
                                                                   "source": "llm"},
                                                                  {"real": "J9", "n": 1, "q": 0.4, "prior": 0.1,
                                                                   "source": "unconventional"}]})
        dag.x("INSERT INTO roots (key,label,real_sym,created,finished,jobs,decision,decision_real,summary) "
              "VALUES (?,?,?,?,?,?,?,?,?)", (f"k{i}", f"game1-move{ply}", 0, start,
                                              None if mv is None else start + 60, 3, 0, mv, summ))
        for kind, status in [("expand", "done"), ("rollout", "failed" if i == 0 else "done"),
                             ("abstract", "done" if mv else "running")]:
            jid += 1
            dag.x("INSERT INTO jobs (kind,key,root,status,worker,created,started,finished,error) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (kind, f"k{i}", f"k{i}", status, "claude", start + jid, start + jid,
                                                  None if status == "running" else start + jid + 5,
                                                  "session ended (rc=1) without an accepted answer"
                                                  if status == "failed" else ""))
            if status != "running":
                _session(tree / "jobs" / f"{jid:06d}-{kind}-abc123", 0.25, 1000)
            else:
                (tree / "jobs" / f"{jid:06d}-{kind}-abc123").mkdir(parents=True)
    return run


def _play_two(url: str, run: dict) -> list[str]:
    from harness.arena_client import ArenaClient
    c = ArenaClient(url, token=run["token"])
    r = c.new_game("random")
    played = []
    for _ in range(2):
        rows = "".join(r["board_rows"])
        mv = "D4" if rows[5 * 9 + 3] == "." else "F6" if rows[3 * 9 + 5] == "." else "C7"
        r = c.play(mv)
        assert r["ok"], r
        played.append(mv)
    return played


def test_partial_report_mid_game_then_review_after_the_game(tmp_path, arena):
    ar, url, adir = arena
    from harness.arena_client import ArenaClient
    run = ArenaClient(url, admin_token=ADMIN).create_run(name="synthetic pilot", target_games=1)["run"]
    played = _play_two(url, run)
    rd = make_run(tmp_path, run["id"], played, time.time() - 1000)

    rep = pilot_report.build(rd, url, pilot_report.read_token(adir))
    t = rep["totals"]
    assert t["searches"] == 3 and t["searches_finished"] == 2 and t["job_dirs"] == 9
    assert t["cost_usd"] == pytest.approx(8 * 0.25) and t["jobs_without_cost"] == 1 and t["jobs_failed"] == 1
    assert t["tokens"]["cache_write"] == 8000
    s1 = rep["searches"][0]
    assert (s1["jobs_ok"], s1["jobs_failed"], s1["cost_usd"]) == (2, 1, 0.75) and s1["decision"] == played[0]
    assert rep["searches"][2]["jobs_running"] == 1 and rep["searches"][2]["decision"] is None
    (g,) = rep["games"]
    assert g["our_color"] == "B" and g["status"] == "active" and g["moves"] == 4
    assert [(m["ply"], m["played"], m["accepted"]) for m in g["our_moves"]] == \
        [(1, played[0], True), (3, played[1], True), (5, None, None)]
    assert g["our_moves"][0]["reply"] and g["our_moves"][0]["reply_seconds"] is not None
    assert g["review"] is None and "in progress" in g["review_note"] and g["sgf"].startswith("(;")
    md = pilot_report.markdown(rep)
    assert "we are Black" in md and f"| 1 | {played[0]} | {played[0]} | 2/1/0 |" in md and "(searching)" in md
    assert VIEWER not in json.dumps(rep, default=str) + md and ADMIN not in md

    # finished game with a (synthetic) engine review: per-move point loss of our moves
    ArenaClient(url, token=run["token"]).resign()
    gid = g["id"]
    review = [{"ply": i + 1, "color": "B" if i % 2 == 0 else "W", "move": m["coord"], "best": "E5", "top3": ["E5"],
               "matched": False, "loss": 1.5 * (i + 1), "raw_loss": 1.5, "wr_loss": 0.01, "lead_before": 0,
               "lead_after": -1} for i, m in enumerate(ar.store.game_moves(gid))]
    from goarena.referee import summarize_review
    ar.store.x("UPDATE games SET review=?, review_summary=? WHERE id=?",
               (json.dumps(review), json.dumps(summarize_review(review, "B", 9)), gid))
    rep = pilot_report.build(rd, url, pilot_report.read_token(adir))
    (g,) = rep["games"]
    assert g["status"] == "finished" and g["end_reason"] == "resign" and g["winner"] == "opponent"
    assert [x["loss"] for x in g["review"]["our_loss"]] == [1.5, 4.5]
    assert [m["review"]["loss"] for m in g["our_moves"][:2]] == [1.5, 4.5]
    assert "KataGo review" in pilot_report.markdown(rep)


def test_cli_prints_json_and_markdown_without_tokens(tmp_path, arena):
    _, url, adir = arena
    from harness.arena_client import ArenaClient
    run = ArenaClient(url, admin_token=ADMIN).create_run(name="cli", target_games=1)["run"]
    rd = make_run(tmp_path, run["id"], _play_two(url, run), time.time() - 1000)
    out = subprocess.run([sys.executable, str(ROOT / "scripts/pilot_report.py"), str(rd), "--arena", url,
                          "--arena-dir", str(adir), "--format", "json"], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)["games"][0]["our_color"] == "B"
    both = subprocess.run([sys.executable, str(ROOT / "scripts/pilot_report.py"), str(rd), "--arena", url,
                           "--arena-dir", str(adir)], capture_output=True, text=True, check=True).stdout
    assert "# Pilot report: synthetic pilot" in both and VIEWER not in both and ADMIN not in both
    local = subprocess.run([sys.executable, str(ROOT / "scripts/pilot_report.py"), str(rd), "--arena", "",
                            "--format", "md"], capture_output=True, text=True, check=True).stdout
    assert "arena: not queried" in local and "| 3 |" in local


def test_model_label_and_path_root_rename_the_model_and_relativize_paths_only_when_asked(tmp_path, arena):
    _, url, adir = arena
    from harness.arena_client import ArenaClient
    model = "vendor-model-9-9"
    run = ArenaClient(url, admin_token=ADMIN).create_run(name="labelled", model=model, target_games=1)["run"]
    rd = make_run(tmp_path, run["id"], _play_two(url, run), time.time() - 1000, model=model)
    rep = pilot_report.build(rd, url, pilot_report.read_token(adir))
    assert pilot_report.relabel(rep) is rep and "display" not in rep               # default: unchanged
    plain = json.dumps(rep, default=str) + pilot_report.markdown(rep)
    assert model in plain and str(tmp_path) in plain
    assert rep["arena"]["summary"]["model"] == model and \
        any((e.get("data") or {}).get("model") == model for e in rep["arena"]["events"])

    lab = pilot_report.relabel(rep, "Model 9", str(tmp_path))
    assert lab is not rep and rep["run"]["model"] == model                           # the input is not modified
    assert lab["run"]["model"] == "Model 9" and lab["arena"]["summary"]["model"] == "Model 9"
    assert (lab["run_dir"], lab["tree_dir"]) == ("pilot", "pilot/workspace/tree")
    assert lab["display"] == {"model_label": "Model 9", "paths": "relative to --path-root"}
    md = pilot_report.markdown(lab)
    for text in (json.dumps(lab, default=str), md):
        assert model not in text and str(tmp_path) not in text and VIEWER not in text and ADMIN not in text
    assert "(model Model 9, harness tree)" in md and "- display: model named by its label" in md
    assert lab["totals"] == rep["totals"] and lab["games"][0]["sgf"] == rep["games"][0]["sgf"]   # numbers kept
    only_paths = pilot_report.relabel(rep, path_root=str(tmp_path))
    assert only_paths["run"]["model"] == model and only_paths["display"]["model_label"] is None

    out = subprocess.run([sys.executable, str(ROOT / "scripts/pilot_report.py"), str(rd), "--arena", url,
                          "--arena-dir", str(adir), "--model-label", "Model 9", "--path-root", str(tmp_path)],
                         capture_output=True, text=True, check=True).stdout
    assert model not in out and str(tmp_path) not in out and "(model Model 9, harness tree)" in out


def test_guard_pauses_the_run_and_stops_the_runner_group_above_the_cap(tmp_path, arena):
    ar, url, adir = arena
    from harness.arena_client import ArenaClient
    run = ArenaClient(url, admin_token=ADMIN).create_run(name="guarded", target_games=1)["run"]
    rd = make_run(tmp_path, run["id"], _play_two(url, run), time.time() - 1000)   # 2.00 USD spent
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "harness.runner"],
                             start_new_session=True)
    try:
        (rd / "runner.pid").write_text(f"{child.pid}\n")
        assert pilot_guard.main([str(rd), "--max-usd", "50", "--interval", "0.05", "--match", "nothing-matches",
                                 "--arena", url, "--arena-dir", str(adir)]) == 0      # under the cap, "runner" gone
        assert pilot_guard.main([str(rd), "--max-usd", "1.5", "--interval", "0.05", "--grace", "10",
                                 "--arena", url, "--arena-dir", str(adir)]) == 3
        assert child.wait(timeout=10) is not None
        assert ar.store.get_run(run["id"])["status"] == "paused"
        assert ar.store.active_game(run["id"]) is not None                # the game is kept, not forfeited
    finally:
        if child.poll() is None:
            child.kill()
