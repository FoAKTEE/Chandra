"""MCTS v2 command line and the code-only arena player (in-process arena, random opponent)."""
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
from mcts.arena import play_games
from mcts.tree import MCTS, MCTSConfig

ROOT = Path(__file__).resolve().parent.parent


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "mcts", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=300)


def test_bestmove_prints_root_table(tmp_path):
    sgf = tmp_path / "g.sgf"
    sgf.write_text("(;GM[1]FF[4]SZ[9]KM[7.5];B[ee];W[cc];B[gc];W[dg];B[ce])")
    r = run("bestmove", "--sgf", str(sgf), "--upto", "4", "--sims", "400", "--threads", "2", "--max-nodes", "50000")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "position after 4 moves, X to play; 400 sims" in out and "best:" in out
    assert out.splitlines()[1].split() == ["move", "visits", "winrate", "prior", "pv"]


def test_selfplay_smoke_writes_sgf_and_resumable_tree(tmp_path):
    r = run("selfplay", "--size", "5", "--komi", "0.5", "--sims", "60", "--threads", "2", "--games", "1",
            "--max-nodes", "100000", "--run-dir", str(tmp_path), "--save-tree")
    assert r.returncode == 0, r.stderr
    assert "game 1:" in r.stdout and (tmp_path / "game1.sgf").read_text().startswith("(;GM[1]")
    eng = MCTS.load(tmp_path / "game1-tree.npz")
    assert eng.root_board.size == 5 and eng.moves and eng.n_nodes > 0


def test_run_dir_inside_the_repo_is_refused():
    r = run("selfplay", "--size", "5", "--sims", "5", "--run-dir", str(ROOT / "runs-x"))
    assert r.returncode != 0 and "outside the Chandra tree" in r.stderr
    assert not (ROOT / "runs-x").exists()


@pytest.fixture()
def arena(tmp_path):
    tiers = {k: v for k, v in load_tiers(str(ROOT / "config/tiers-9x9.json")).items() if v.kind == "random"}
    st = Store(str(tmp_path / "a.db"))
    ar = Arena(st, ArenaSettings(tiers=tiers, max_illegal_per_game=3, review_visits=0), None, seed=3)
    httpd = serve(ar, "127.0.0.1", 0, "adm")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield ar, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    ar.stop()


def test_arena_game_keeps_the_tree_across_moves(arena, tmp_path):
    _, url = arena
    admin = ArenaClient(url, admin_token="adm")
    tok = admin.create_run(name="mcts", target_games=1)["run"]["token"]
    logs = []
    res = play_games(ArenaClient(url, tok), "random", 1, config=MCTSConfig(max_nodes=300_000), time_s=None,
                     sims=150, threads=2, color="B", run_dir=tmp_path, log=logs.append)
    assert len(res) == 1 and res[0]["winner"] == "agent" and res[0]["result"].startswith("B+")
    moves = [ln for ln in logs if ln.strip().startswith("move ")]
    assert moves and sum("(advanced)" in ln for ln in moves) == len(moves) - 1     # one tree per game
    assert (tmp_path / "moves.jsonl").exists() and list(tmp_path.glob("game*-tree.npz"))
