"""Offline judge scripts/judge_position.py on the fake engine (no GPU)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "tests" / "fake_katago.py"


def _judge(tmp_path, *extra):
    sgf = tmp_path / "g.sgf"
    sgf.write_text("(;GM[1]FF[4]SZ[9]KM[7.5]RU[Chinese];B[ee];W[cf];B[ce];W[be])")
    out = tmp_path / "j.json"
    p = subprocess.run([sys.executable, str(ROOT / "scripts/judge_position.py"), "--sgf", str(sgf), "--upto", "4",
                        "--katago-bin", str(FAKE), "--model", str(FAKE), "--config", str(FAKE),
                        "--path-root", str(tmp_path), "--out", str(out), *extra],
                       cwd=tmp_path, capture_output=True, text=True, timeout=120)
    return p, out


def test_judge_position_on_the_fake_engine(tmp_path):
    p, out = _judge(tmp_path, "--moves", "D5,G3,pass", "--visits", "50,200")
    assert p.returncode == 0, p.stderr
    d = json.loads(out.read_text())
    assert d == json.loads(p.stdout)
    assert d["sgf"] == "g.sgf" and d["upto"] == 4 and d["to_play"] == "B" and d["moves"] == ["D5", "G3", "pass"]
    assert [r["visits"] for r in d["results"]] == [50, 200] and [r["child_visits"] for r in d["results"]] == [100, 100]
    for r in d["results"]:
        assert r["engine_best"] and isinstance(r["engine_lead"], float) and set(r["graded"]) == {"D5", "G3", "pass"}
        for g in r["graded"].values():
            assert {"engine_rank", "loss", "lead_after", "engine_policy_rank"} <= set(g)
            assert g["loss"] == pytest.approx(r["engine_lead"] - g["lead_after"], abs=0.011)
        best = r["engine_top"][0]["move"]
        assert r["engine_best"] == best


def test_judge_position_rejects_illegal_and_bad_moves(tmp_path):
    p, _ = _judge(tmp_path, "--moves", "E5", "--visits", "50")      # occupied
    assert p.returncode != 0 and "not legal" in p.stderr
    p, _ = _judge(tmp_path, "--moves", "Z9", "--visits", "50")
    assert p.returncode != 0 and "bad move" in p.stderr
