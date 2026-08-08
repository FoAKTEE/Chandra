"""error_database — round-trip for pass + fail rows, and the §0 rejection checks
that force failed trials to carry diagnosis (expected/observed/root_cause/
fix_hypothesis/failure_mode) and a domain-legal failure_mode."""
from __future__ import annotations

import pytest

from _common.ledgers import error_database as edb
from factories import valid_error_fail_row, valid_error_pass_row

PAPER = "arxiv-0000.00000"


def test_pass_row_roundtrip(tmp_path):
    edb.append_row(valid_error_pass_row(), repo_root=tmp_path)
    rows = edb.read_entries(tmp_path, PAPER)
    assert len(rows) == 1 and rows[0]["pass_fail"] == "pass"
    assert (tmp_path / "results" / "ledgers" / "error" / f"paper_{PAPER}" / "trials.jsonl").exists()


def test_fail_row_roundtrip(tmp_path):
    edb.append_row(valid_error_fail_row(), repo_root=tmp_path)
    rows = edb.read_entries(tmp_path, PAPER)
    assert rows[0]["failure_mode"] == "nonsimplification"


def test_node_seq_numbers_trials_under_node(tmp_path):
    edb.append_row(valid_error_pass_row(node_id="x"), repo_root=tmp_path)
    edb.append_row(valid_error_fail_row(node_id="x"), repo_root=tmp_path)
    edb.append_row(valid_error_pass_row(), repo_root=tmp_path)        # no node_id -> no node_seq
    trials = edb.node_trials(PAPER, "x", repo_root=tmp_path)
    assert [t["node_seq"] for t in trials] == [1, 2]
    anon = [t for t in edb.read_entries(tmp_path, PAPER) if "node_id" not in t]
    assert anon and "node_seq" not in anon[0]


@pytest.mark.parametrize("row,needle", [
    (valid_error_pass_row(pass_fail="bogus"),              "pass_fail="),
    (valid_error_pass_row(domain="bogus"),                 "domain="),
    (valid_error_pass_row(metric={"name": "x"}),           "metric missing key"),
    (valid_error_pass_row(pass_fail="fail"),               "§0"),                 # fail w/o diagnosis
    (valid_error_fail_row(failure_mode="not_a_real_mode"), "failure_mode="),      # off-taxonomy tag
])
def test_validate_rejects(row, needle):
    with pytest.raises(ValueError) as ei:
        edb.validate(row)
    assert needle in str(ei.value)
