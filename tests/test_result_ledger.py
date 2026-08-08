"""result_database — round-trip, latest-per-result collapse, query filters, and
the short-run REJECTION checks (the validator is the stage-4 admission gate, so
these are the tests that matter most for "the verifier admits")."""
from __future__ import annotations

import pytest

from _common.ledgers import result_database as rdb
from factories import valid_result_row, write_evidence

PAPER = "arxiv-0000.00000"


def test_append_roundtrip_autofills_and_writes_summary(tmp_path):
    write_evidence(tmp_path)  # checked rows must carry resolvable evidence
    written = rdb.append_row(valid_result_row(), repo_root=tmp_path)
    assert written["timestamp"] and written["git_commit"]  # auto-filled
    rows = rdb.read_entries(tmp_path, PAPER)
    assert len(rows) == 1 and rows[0]["result_id"] == "r1"
    summary = tmp_path / "results" / "ledgers" / "result" / f"paper_{PAPER}" / "summary.csv"
    assert summary.exists() and summary.read_text().strip()


def test_latest_per_result_collapses_history(tmp_path):
    # Correct a result by appending a new row with the same result_id.
    write_evidence(tmp_path)
    rdb.append_row(valid_result_row(status="conditional", open_obligations=["close X"]),
                   repo_root=tmp_path)
    rdb.append_row(valid_result_row(status="checked", open_obligations=[]),
                   repo_root=tmp_path)
    history = rdb.read_entries(tmp_path, PAPER)
    assert len(history) == 2  # append-only: nothing is overwritten on disk
    latest = rdb.latest_per_result(history)
    assert len(latest) == 1 and latest[0]["status"] == "checked"


def test_query_filters_by_status_and_id(tmp_path):
    write_evidence(tmp_path)
    rdb.append_row(valid_result_row(result_id="r1", status="checked"), repo_root=tmp_path)
    rdb.append_row(valid_result_row(result_id="r2", status="refuted"), repo_root=tmp_path)
    assert {r["result_id"] for r in rdb.query(PAPER, repo_root=tmp_path)} == {"r1", "r2"}
    refuted = rdb.query(PAPER, status="refuted", repo_root=tmp_path)
    assert [r["result_id"] for r in refuted] == ["r2"]


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r.pop("claim"),                                  "missing required"),
    (lambda r: r.update(status="bogus"),                        "status="),
    (lambda r: r.update(evidence_type="bogus"),                 "evidence_type="),
    (lambda r: r.update(verifier_result=["nope"]),              "verifier_result must be an object"),
    (lambda r: r.update(verifier_result={"verdict": "bogus"}),  "verdict="),
    (lambda r: r.update(dependencies="not-a-list"),             "dependencies must be a list"),
    (lambda r: r.update(open_obligations=["still open"]),       "open_obligations=[]"),
])
def test_validate_rejects(mutate, needle):
    row = valid_result_row()  # default status='checked'
    mutate(row)
    with pytest.raises(ValueError) as ei:
        rdb.validate(row)
    assert needle in str(ei.value)


def test_render_html_requires_rows(tmp_path):
    with pytest.raises(ValueError):
        rdb.render_html("never-seen", repo_root=tmp_path)


def test_render_md_and_render_state_are_generated_views(tmp_path):
    write_evidence(tmp_path)
    rdb.append_row(valid_result_row(), repo_root=tmp_path)
    md = rdb.render_md(PAPER, repo_root=tmp_path)
    assert "GENERATED" in md and "DO NOT EDIT" in md    # never hand-authored
    assert "r1" in md and "## checked (1)" in md
    block = rdb.render_state(PAPER, repo_root=tmp_path)
    assert block.startswith("<!-- BEGIN GENERATED: accepted-results")
    assert f"<!-- END GENERATED: accepted-results paper_{PAPER} -->" in block
    assert "`r1` 1 + 1 = 2" in block
