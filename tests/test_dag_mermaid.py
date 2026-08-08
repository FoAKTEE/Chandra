"""dag_mermaid — the promoted DAG tooling: single render, the one-giant merged
DAG, paper auto-discovery, and the cross-paper duplicate detector that seeds the
strongest-math reformulation pass. Renders are pure (return Mermaid markdown),
so these assert on the text directly."""
from __future__ import annotations

import pytest

from _common.ledgers import error_database as edb
from _common.ledgers import knowledge_database as kdb
from _common.visualization import dag_mermaid as dm
from factories import (valid_error_fail_row, valid_error_pass_row,
                       valid_knowledge_row, write_evidence)

P1 = "arxiv-1111.11111"
P2 = "arxiv-2222.22222"


def seed(tmp):
    ev = write_evidence(tmp)  # solid rows must carry resolvable evidence (admission gate)
    # P1: n1 -> n2; n1 carries eq:shared + summary "master equation"
    kdb.append_row(valid_knowledge_row(paper=P1, node_id="P1::n1", status="solid", evidence=ev,
                   equation_labels=["eq:shared"], summary="master equation"), repo_root=tmp)
    kdb.append_row(valid_knowledge_row(paper=P1, node_id="P1::n2", predecessors=["P1::n1"],
                   summary="langevin equation"), repo_root=tmp)
    # P2: m1 duplicates n1 (shared eq label + same summary); m2 duplicates n2 by summary only
    kdb.append_row(valid_knowledge_row(paper=P2, node_id="P2::m1", status="solid", evidence=ev,
                   equation_labels=["eq:shared"], summary="Master equation"), repo_root=tmp)
    kdb.append_row(valid_knowledge_row(paper=P2, node_id="P2::m2", summary="Langevin equation"),
                   repo_root=tmp)


def test_discover_papers(tmp_path):
    seed(tmp_path)
    assert dm.discover_papers(tmp_path) == [P1, P2]


def test_render_single_is_mermaid(tmp_path):
    seed(tmp_path)
    md = dm.render_single(P1, repo_root=tmp_path)
    assert "```mermaid" in md and "flowchart TD" in md
    assert dm._safe("P1::n1") in md and dm._safe("P1::n2") in md
    assert "-->" in md                      # in-scope predecessor edge is solid
    assert "classDef solid" in md


def test_render_single_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        dm.render_single("never-seen", repo_root=tmp_path)


def test_merge_is_one_giant_dag(tmp_path):
    seed(tmp_path)
    md = dm.render_merge([P1, P2], repo_root=tmp_path)
    assert "MERGED equation DAG" in md
    assert f"{dm._safe(P1)}_sg" in md and f"{dm._safe(P2)}_sg" in md   # one subgraph per paper
    for nid in ("P1::n1", "P1::n2", "P2::m1", "P2::m2"):
        assert dm._safe(nid) in md


def test_duplicates_detects_cross_paper(tmp_path):
    seed(tmp_path)
    dups = dm.find_duplicates([P1, P2], repo_root=tmp_path)
    assert {d["reason"] for d in dups} == {"shared_equation_label", "matching_summary"}
    for d in dups:                          # every reported cluster spans >= 2 papers
        assert len({n["paper"] for n in d["nodes"]}) >= 2


def test_main_merge_to_stdout(tmp_path, capsys):
    seed(tmp_path)
    rc = dm.main(["merge", "--repo-root", str(tmp_path)])   # --papers omitted -> auto-discover
    assert rc == 0
    assert "```mermaid" in capsys.readouterr().out


def test_main_merge_no_papers_returns_1(tmp_path):
    assert dm.main(["merge", "--repo-root", str(tmp_path)]) == 1   # empty repo


# --- doubly-linked ledgers: error + knowledge as numbered lists under a node ---

def seed_with_trials(tmp):
    ev = write_evidence(tmp)
    kdb.append_row(valid_knowledge_row(paper=P1, node_id="P1::n1", status="solid", evidence=ev,
                   summary="master equation"), repo_root=tmp)
    kdb.append_row(valid_knowledge_row(paper=P1, node_id="P1::n1", status="preliminary",
                   summary="master equation v2"), repo_root=tmp)   # 2nd knowledge record under n1
    edb.append_row(valid_error_fail_row(paper=P1, node_id="P1::n1"), repo_root=tmp)
    edb.append_row(valid_error_pass_row(paper=P1, node_id="P1::n1"), repo_root=tmp)


def test_node_view_is_doubly_linked(tmp_path):
    seed_with_trials(tmp_path)
    v = dm.node_view(P1, "P1::n1", repo_root=tmp_path)
    assert v["status"] == "preliminary"                            # latest knowledge status
    assert [k["node_seq"] for k in v["knowledge"]] == [1, 2]       # 2 knowledge records under the node
    assert [e["node_seq"] for e in v["errors"]] == [1, 2]          # 2 trials under the node


def test_node_progress_counts(tmp_path):
    seed_with_trials(tmp_path)
    prog = {p["node_id"]: p for p in dm.node_progress([P1], repo_root=tmp_path)}
    n1 = prog["P1::n1"]
    assert (n1["n_knowledge"], n1["n_trials"], n1["pass"], n1["fail"]) == (2, 2, 1, 1)
    assert n1["status"] == "preliminary"


def test_render_badge_shows_progress(tmp_path):
    seed_with_trials(tmp_path)
    md = dm.render_single(P1, repo_root=tmp_path)
    assert "k2" in md and "t2✗1" in md     # 2 knowledge records · 2 trials (1 failed), on the DAG node
