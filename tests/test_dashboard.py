"""Mission-dashboard renderer (`_common/visualization/dashboard.py`).

Pins the GUI contract: the dashboard is a rendered VIEW over the four ledgers
(never a write path), self-contained (no external URLs), escapes ledger text
(rows are agent-authored → untrusted), and its DAG layout respects topology.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from factories import (valid_claim_row, valid_error_fail_row, valid_error_pass_row,
                       valid_knowledge_row, valid_obligation_row, valid_result_row,
                       write_evidence)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from _common.ledgers import claims_database as cdb
from _common.ledgers import error_database as edb
from _common.ledgers import knowledge_database as kdb
from _common.ledgers import result_database as rdb
from _common.visualization import dashboard

PAPER = "arxiv-0000.00000"


@pytest.fixture()
def mission(tmp_path):
    """A minimal but fully-linked mission: 3-node chain, one result, one open
    obligation, one pass + one fail trial."""
    ev = write_evidence(tmp_path)
    kdb.append_row(valid_knowledge_row(node_id=f"{PAPER}::a", status="solid",
                                       evidence=ev), repo_root=tmp_path)
    kdb.append_row(valid_knowledge_row(node_id=f"{PAPER}::b", status="preliminary",
                                       predecessors=[f"{PAPER}::a"]), repo_root=tmp_path)
    kdb.append_row(valid_knowledge_row(node_id=f"{PAPER}::c", status="hypothesis",
                                       predecessors=[f"{PAPER}::b"]), repo_root=tmp_path)
    rdb.append_row(valid_result_row(result_id="r1", evidence=ev,
                                    dependencies=[f"{PAPER}::a"]), repo_root=tmp_path)
    cdb.append_row(valid_obligation_row(node_ids=[f"{PAPER}::b"]), repo_root=tmp_path)
    cdb.append_row(valid_claim_row(node_ids=[f"{PAPER}::c"]), repo_root=tmp_path)
    edb.append_row(valid_error_pass_row(node_id=f"{PAPER}::a"), repo_root=tmp_path)
    edb.append_row(valid_error_fail_row(node_id=f"{PAPER}::b"), repo_root=tmp_path)
    return tmp_path


def test_render_writes_default_path(mission):
    out = dashboard.render(PAPER, repo_root=mission)
    assert out == mission / "results" / "views" / "dashboard" / f"paper_{PAPER}.html"
    html = out.read_text(encoding="utf-8")
    for marker in (f"{PAPER}::a", f"{PAPER}::b", f"{PAPER}::c",
                   "Mission DAG", "Solid nodes", "dashboard-data"):
        assert marker in html


def test_chain_badges_and_kpis(mission):
    html = dashboard.render(PAPER, repo_root=mission).read_text(encoding="utf-8")
    # every ledger written above has an intact hash chain
    for db in ("knowledge", "result", "claim", "error"):
        assert f"✓ {db} chain" in html
    # KPI arithmetic: 1 solid of 3 nodes; 0/1 obligations discharged
    assert "1<span class='den'> / 3</span>" in html
    assert "0<span class='den'> / 1</span>" in html


def test_dag_svg_topology(mission):
    html = dashboard.render(PAPER, repo_root=mission).read_text(encoding="utf-8")
    # edges follow the predecessor chain a -> b -> c
    assert re.search(r'data-a="[^"]*::a" data-b="[^"]*::b"', html)
    assert re.search(r'data-a="[^"]*::b" data-b="[^"]*::c"', html)
    # deeper nodes sit strictly further right (translate x grows with depth)
    xs = {m.group(2): float(m.group(3)) for m in re.finditer(
        r'data-node="([^"]*::)?([abc])"[^>]*translate\(([\d.]+)', html)}
    assert xs["a"] < xs["b"] < xs["c"]


def test_dag_layout_reports_cycles():
    nodes = [{"node_id": "x", "predecessors": ["y"], "status": "hypothesis"},
             {"node_id": "y", "predecessors": ["x"], "status": "hypothesis"},
             {"node_id": "z", "predecessors": [], "status": "solid"}]
    lay = dashboard.dag_layout(nodes)
    assert set(lay["cyclic"]) == {"x", "y"}
    assert "z" in lay["pos"]


def test_untrusted_ledger_text_is_escaped(mission):
    kdb.append_row(valid_knowledge_row(
        node_id=f"{PAPER}::evil", status="hypothesis",
        summary='<script>alert(1)</script>'), repo_root=mission)
    html = dashboard.render(PAPER, repo_root=mission).read_text(encoding="utf-8")
    # table/SVG render must escape it; the JSON island must break "</script>"
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_self_contained_no_external_requests(mission):
    html = dashboard.render(PAPER, repo_root=mission).read_text(encoding="utf-8")
    assert not re.search(r'\b(?:src|href)\s*=\s*"(?:https?:)?//', html)
    assert "@import" not in html


def test_render_empty_repo_still_renders(tmp_path):
    out = dashboard.render("never-seen", repo_root=tmp_path)
    html = out.read_text(encoding="utf-8")
    assert "No DAG yet" in html
    assert "no ledgers yet" in html


def test_cli_render(mission):
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "_common/visualization/dashboard.py"),
         "render", "--paper", PAPER, "--repo-root", str(mission)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["rendered"] is True
    assert Path(payload["path"]).is_file()


def test_cli_paper_defaults_from_mission_json(mission):
    (mission / "mission.json").write_text(json.dumps({"paper": PAPER}))
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "_common/visualization/dashboard.py"),
         "render", "--repo-root", str(mission)],
        capture_output=True, text=True, timeout=60, cwd=mission)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["paper"] == PAPER
