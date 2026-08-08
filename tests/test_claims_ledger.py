"""claims_database — the structured-first home for the stage-1 decomposition
artifacts (claims / obligations / assumptions as records; claims.md,
obligations.md, assumptions.md as GENERATED views), with settling references
checked to exist at append (executable cross-links into the other ledgers)."""
from __future__ import annotations

import pytest

from _common.ledgers import claims_database as cdb
from _common.ledgers import knowledge_database as kdb
from _common.ledgers import result_database as rdb
from factories import (valid_assumption_row, valid_claim_row, valid_knowledge_row,
                       valid_obligation_row, valid_result_row, write_evidence)

PAPER = "arxiv-0000.00000"


def test_roundtrip_all_three_kinds(tmp_path):
    cdb.append_row(valid_claim_row(), repo_root=tmp_path)
    cdb.append_row(valid_obligation_row(), repo_root=tmp_path)
    cdb.append_row(valid_assumption_row(), repo_root=tmp_path)
    assert len(cdb.query(PAPER, repo_root=tmp_path)) == 3
    assert [r["entry_id"] for r in cdb.query(PAPER, kind="obligation", repo_root=tmp_path)] == ["o1"]
    summary = tmp_path / "results" / "ledgers" / "claim" / f"paper_{PAPER}" / "summary.csv"
    assert summary.exists()


def test_amend_by_reappend_latest_wins(tmp_path):
    cdb.append_row(valid_claim_row(status="open"), repo_root=tmp_path)
    cdb.append_row(valid_claim_row(status="in_progress"), repo_root=tmp_path)
    assert len(cdb.read_entries(tmp_path, PAPER)) == 2      # append-only on disk
    latest = cdb.query(PAPER, entry_id="c1", repo_root=tmp_path)
    assert len(latest) == 1 and latest[0]["status"] == "in_progress"


def test_append_batch_dedups(tmp_path):
    rows = [valid_claim_row(), valid_obligation_row()]
    assert cdb.append_batch(rows, repo_root=tmp_path)["appended"] == 2
    again = cdb.append_batch(rows, repo_root=tmp_path)
    assert again["appended"] == 0 and again["skipped"] == 2


@pytest.mark.parametrize("row,needle", [
    (valid_claim_row(kind="bogus"),                        "kind="),
    (valid_claim_row(status="discharged"),                 "status="),           # obligation-only status
    (valid_claim_row(needed_evidence_type=None),           "needed_evidence_type"),
    (valid_obligation_row(status="discharged"),            "requires discharged_by"),
    (valid_assumption_row(status="relaxed"),               "requires reduction_obligation"),
])
def test_validate_rejects(row, needle):
    with pytest.raises(ValueError) as ei:
        cdb.validate(row)
    assert needle in str(ei.value)


def test_admitted_claim_requires_existing_result(tmp_path):
    with pytest.raises(ValueError) as ei:
        cdb.append_row(valid_claim_row(status="admitted", result_ref="r1"),
                       repo_root=tmp_path)
    assert "not found in result-database" in str(ei.value)
    write_evidence(tmp_path)
    rdb.append_row(valid_result_row(), repo_root=tmp_path)  # result r1 now exists
    written = cdb.append_row(valid_claim_row(status="admitted", result_ref="r1"),
                             repo_root=tmp_path)
    assert written["status"] == "admitted"


def test_admitted_claim_cannot_cite_refuted_result(tmp_path):
    write_evidence(tmp_path)
    rdb.append_row(valid_result_row(result_id="r9", status="refuted"), repo_root=tmp_path)
    with pytest.raises(ValueError) as ei:
        cdb.append_row(valid_claim_row(status="admitted", result_ref="r9"),
                       repo_root=tmp_path)
    assert "has status 'refuted'" in str(ei.value)


def test_discharged_obligation_accepts_knowledge_node(tmp_path):
    kdb.append_row(valid_knowledge_row(node_id="P0::n1"), repo_root=tmp_path)
    written = cdb.append_row(valid_obligation_row(status="discharged",
                                                  discharged_by="P0::n1"),
                             repo_root=tmp_path)
    assert written["status"] == "discharged"
    with pytest.raises(ValueError):
        cdb.append_row(valid_obligation_row(entry_id="o2", status="discharged",
                                            discharged_by="nowhere"),
                       repo_root=tmp_path)


def test_relaxed_assumption_requires_reduction_obligation_entry(tmp_path):
    with pytest.raises(ValueError) as ei:
        cdb.append_row(valid_assumption_row(status="relaxed",
                                            reduction_obligation="o1"),
                       repo_root=tmp_path)
    assert "matches no obligation entry" in str(ei.value)
    cdb.append_row(valid_obligation_row(), repo_root=tmp_path)
    written = cdb.append_row(valid_assumption_row(status="relaxed",
                                                  reduction_obligation="o1"),
                             repo_root=tmp_path)
    assert written["status"] == "relaxed"


def test_render_md_is_a_generated_view(tmp_path):
    cdb.append_row(valid_claim_row(), repo_root=tmp_path)
    md = cdb.render_md(PAPER, "claim", repo_root=tmp_path)
    assert "GENERATED" in md and "DO NOT EDIT" in md
    assert "c1" in md and "symbolic_derivation" in md


def test_render_views_writes_all_three_files(tmp_path):
    cdb.append_row(valid_claim_row(), repo_root=tmp_path)
    cdb.append_row(valid_obligation_row(), repo_root=tmp_path)
    cdb.append_row(valid_assumption_row(), repo_root=tmp_path)
    out = tmp_path / "reformulate" / "proj" / f"paper_{PAPER}"
    written = cdb.render_views(PAPER, out, repo_root=tmp_path)
    assert sorted(written) == ["assumption", "claim", "obligation"]
    for path in written.values():
        assert "DO NOT EDIT" in open(path).read()
