"""knowledge_database — round-trip, promotion (latest-status wins), predecessor
walk, and the §0 rejection that a `solid` node MUST cite verifier evidence."""
from __future__ import annotations

import pytest

from _common.ledgers import knowledge_database as kdb
from factories import valid_knowledge_row, write_evidence

PAPER = "arxiv-0000.00000"


def test_hypothesis_roundtrip(tmp_path):
    kdb.append_row(valid_knowledge_row(), repo_root=tmp_path)
    rows = kdb.read_entries(tmp_path, PAPER)
    assert len(rows) == 1 and rows[0]["status"] == "hypothesis"


def test_promotion_latest_status_wins(tmp_path):
    ev = write_evidence(tmp_path)  # solid evidence must resolve (admission gate)
    kdb.append_row(valid_knowledge_row(status="hypothesis"), repo_root=tmp_path)
    kdb.append_row(valid_knowledge_row(status="solid", evidence=ev),
                   repo_root=tmp_path)
    rows = kdb.read_entries(tmp_path, PAPER)
    current = kdb.latest_status(rows, PAPER, "n1")
    assert current["status"] == "solid"


def test_predecessor_walk(tmp_path):
    ev = write_evidence(tmp_path)
    kdb.append_row(valid_knowledge_row(node_id="n0", status="solid", evidence=ev),
                   repo_root=tmp_path)
    kdb.append_row(valid_knowledge_row(node_id="n1", predecessors=["n0"]), repo_root=tmp_path)
    assert kdb.predecessors_of(PAPER, "n1", repo_root=tmp_path) == ["n0"]


def test_append_batch_dedups_and_force(tmp_path):
    ev = write_evidence(tmp_path)
    rows = [valid_knowledge_row(node_id="a"),
            valid_knowledge_row(node_id="b", status="solid", evidence=ev)]
    first = kdb.append_batch(rows, repo_root=tmp_path)
    assert first == {"appended": 2, "skipped": 0, "papers": [PAPER]}
    again = kdb.append_batch(rows, repo_root=tmp_path)          # identical latest rows -> skipped
    assert again["appended"] == 0 and again["skipped"] == 2
    forced = kdb.append_batch(rows, repo_root=tmp_path, force=True)
    assert forced["appended"] == 2


def test_node_seq_numbers_records_under_node(tmp_path):
    ev = write_evidence(tmp_path)
    kdb.append_row(valid_knowledge_row(node_id="x", status="hypothesis"), repo_root=tmp_path)
    kdb.append_row(valid_knowledge_row(node_id="x", status="solid", evidence=ev), repo_root=tmp_path)
    kdb.append_row(valid_knowledge_row(node_id="y"), repo_root=tmp_path)
    recs = kdb.node_records(PAPER, "x", repo_root=tmp_path)
    assert [r["node_seq"] for r in recs] == [1, 2]            # numbered 1,2 under node x
    assert kdb.node_records(PAPER, "y", repo_root=tmp_path)[0]["node_seq"] == 1


def test_legacy_layout_keeps_working_without_split_brain(tmp_path):
    # a consumer still on `knowledge-database/` reads AND appends there until
    # it migrates; the canonical results/ledgers/ home is used for fresh repos
    legacy = tmp_path / "knowledge-database" / f"paper_{PAPER}"
    legacy.mkdir(parents=True)
    kdb.append_row(valid_knowledge_row(node_id="legacy-n"), repo_root=tmp_path)
    assert (legacy / "nodes.jsonl").exists()
    assert not (tmp_path / "results" / "ledgers" / "knowledge").exists()
    rows = kdb.read_entries(tmp_path, PAPER)
    assert [r["node_id"] for r in rows] == ["legacy-n"]


def test_append_rejects_solid_without_evidence(tmp_path):
    with pytest.raises(ValueError) as ei:
        kdb.append_row(valid_knowledge_row(status="solid"), repo_root=tmp_path)
    assert "§0" in str(ei.value)


@pytest.mark.parametrize("row,needle", [
    (valid_knowledge_row(domain="bogus"),            "domain="),
    (valid_knowledge_row(status="bogus"),            "status="),
    (valid_knowledge_row(status="solid"),            "§0"),                          # solid w/o evidence
    (valid_knowledge_row(concept_advance="yes"),     "concept_advance must be a bool"),
])
def test_validate_rejects(row, needle):
    with pytest.raises(ValueError) as ei:
        kdb.validate(row)
    assert needle in str(ei.value)
