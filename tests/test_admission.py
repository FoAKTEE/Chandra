"""admission — the executable admission gate ("the agent proposes; the verifier
admits" as code, not prose): verification commands actually RUN at append,
evidence must resolve to something checkable, cited dependencies must exist,
and every bypass is recorded on the row instead of passing silently."""
from __future__ import annotations

import pytest

from _common.ledgers import error_database as edb
from _common.ledgers import knowledge_database as kdb
from _common.ledgers import result_database as rdb
from factories import (valid_error_pass_row, valid_knowledge_row,
                       valid_result_row, write_evidence)

PAPER = "arxiv-0000.00000"


def strict_policy(root):
    (root / ".delegation-policy").write_text("strict\n")


# --- result ledger: checked rows need verifiable evidence ----------------------

def test_checked_without_verifiable_evidence_rejected(tmp_path):
    # factory evidence path is NOT materialized -> nothing checkable exists
    with pytest.raises(ValueError) as ei:
        rdb.append_row(valid_result_row(), repo_root=tmp_path)
    assert "verifiable evidence" in str(ei.value)
    assert not (tmp_path / "results" / "ledgers" / "result").exists()  # rejected = not appended


def test_checked_artifact_evidence_is_content_hashed(tmp_path):
    write_evidence(tmp_path)
    written = rdb.append_row(valid_result_row(), repo_root=tmp_path)
    assert len(written["evidence_sha256"]) == 64


def test_checked_requires_pass_verdict(tmp_path):
    write_evidence(tmp_path)
    with pytest.raises(ValueError) as ei:
        rdb.append_row(valid_result_row(verifier_result={"verdict": "partial"}),
                       repo_root=tmp_path)
    assert "verdict='pass'" in str(ei.value)


# --- verification commands are executed, not trusted ---------------------------

def test_passing_verification_command_recorded_on_row(tmp_path):
    row = valid_result_row(evidence="inline certificate",
                           verification={"command": "echo verified"})
    written = rdb.append_row(row, repo_root=tmp_path)
    execution = written["verifier_result"]["execution"]
    assert execution["exit_code"] == 0
    assert len(execution["output_sha256"]) == 64
    assert "verified" in execution["output_tail"]


def test_failing_verification_command_rejects_row(tmp_path):
    row = valid_result_row(evidence="inline certificate",
                           verification={"command": "echo boom >&2; exit 3"})
    with pytest.raises(ValueError) as ei:
        rdb.append_row(row, repo_root=tmp_path)
    assert "verification command failed (exit 3)" in str(ei.value)
    assert not (tmp_path / "results" / "ledgers" / "result").exists()


def test_skip_exec_bypass_is_visible_on_row(tmp_path):
    write_evidence(tmp_path)
    row = valid_result_row(verification={"command": "exit 1"})
    written = rdb.append_row(row, repo_root=tmp_path, skip_exec=True)
    assert written["admission_flags"] == ["skip_exec"]
    assert "execution" not in written["verifier_result"]


# --- dependency existence -------------------------------------------------------

def test_missing_namespaced_dependency_rejected(tmp_path):
    write_evidence(tmp_path)
    with pytest.raises(ValueError) as ei:
        rdb.append_row(valid_result_row(dependencies=["P0::ghost"]), repo_root=tmp_path)
    assert "not found in knowledge-database" in str(ei.value)


def test_present_namespaced_dependency_admits(tmp_path):
    kdb.append_row(valid_knowledge_row(node_id="P0::n1"), repo_root=tmp_path)
    write_evidence(tmp_path)
    written = rdb.append_row(valid_result_row(dependencies=["P0::n1"]), repo_root=tmp_path)
    assert "admission_flags" not in written


def test_missing_dependency_bypass_is_visible(tmp_path):
    write_evidence(tmp_path)
    written = rdb.append_row(valid_result_row(dependencies=["P0::ghost"]),
                             repo_root=tmp_path, allow_missing_deps=True)
    assert written["admission_flags"] == ["allow_missing_deps"]


# --- knowledge ledger: solid means verifiable, on solid support ------------------

def test_solid_free_text_evidence_rejected(tmp_path):
    with pytest.raises(ValueError) as ei:
        kdb.append_row(valid_knowledge_row(status="solid", evidence="trust me"),
                       repo_root=tmp_path)
    assert "free-text evidence is not admissible" in str(ei.value)


def test_solid_on_nonsolid_predecessor_rejected(tmp_path):
    kdb.append_row(valid_knowledge_row(node_id="n0"), repo_root=tmp_path)  # hypothesis
    ev = write_evidence(tmp_path)
    with pytest.raises(ValueError) as ei:
        kdb.append_row(valid_knowledge_row(node_id="n1", status="solid",
                                           evidence=ev, predecessors=["n0"]),
                       repo_root=tmp_path)
    assert "non-solid predecessor" in str(ei.value)


def test_solid_chain_on_solid_predecessor_admits(tmp_path):
    ev = write_evidence(tmp_path)
    kdb.append_row(valid_knowledge_row(node_id="n0", status="solid", evidence=ev),
                   repo_root=tmp_path)
    written = kdb.append_row(valid_knowledge_row(node_id="n1", status="solid",
                                                 evidence=ev, predecessors=["n0"]),
                             repo_root=tmp_path)
    assert len(written["evidence_sha256"]) == 64


def test_solid_unknown_predecessor_rejected_then_bypass_visible(tmp_path):
    ev = write_evidence(tmp_path)
    row = valid_knowledge_row(status="solid", evidence=ev, predecessors=["ghost"])
    with pytest.raises(ValueError) as ei:
        kdb.append_row(dict(row), repo_root=tmp_path)
    assert "unknown predecessor" in str(ei.value)
    written = kdb.append_row(dict(row), repo_root=tmp_path, allow_missing_deps=True)
    assert written["admission_flags"] == ["allow_missing_deps"]


def test_solid_via_passing_verification_command(tmp_path):
    row = valid_knowledge_row(status="solid", evidence="certified by command",
                              verification={"command": "true"})
    written = kdb.append_row(row, repo_root=tmp_path)
    assert written["verification_run"]["exit_code"] == 0


# --- delegation policy (kernel §6): orchestrators orchestrate, workers work ----

def test_strict_policy_rejects_roleless_appends_on_all_ledgers(tmp_path, monkeypatch):
    monkeypatch.delenv("CHANDRA_ROLE", raising=False)
    strict_policy(tmp_path)
    write_evidence(tmp_path)
    for append, row in [(rdb.append_row, valid_result_row()),
                        (kdb.append_row, valid_knowledge_row()),
                        (edb.append_row, valid_error_pass_row())]:
        with pytest.raises(ValueError) as ei:
            append(row, repo_root=tmp_path)
        assert "delegation policy is strict" in str(ei.value)
    assert not (tmp_path / "results" / "ledgers" / "result").exists()


def test_strict_policy_worker_role_admits_and_is_recorded(tmp_path, monkeypatch):
    strict_policy(tmp_path)
    monkeypatch.setenv("CHANDRA_ROLE", "worker")
    write_evidence(tmp_path)
    written = rdb.append_row(valid_result_row(), repo_root=tmp_path)
    assert written["actor_role"] == "worker"


def test_strict_policy_orchestrator_role_rejected_but_override_visible(tmp_path, monkeypatch):
    strict_policy(tmp_path)
    write_evidence(tmp_path)
    monkeypatch.setenv("CHANDRA_ROLE", "orchestrator")
    with pytest.raises(ValueError) as ei:
        rdb.append_row(valid_result_row(), repo_root=tmp_path)
    assert "delegation policy is strict" in str(ei.value)
    monkeypatch.setenv("CHANDRA_ROLE", "human-override")
    written = rdb.append_row(valid_result_row(), repo_root=tmp_path)
    assert written["actor_role"] == "human-override"   # bypass visible on the row


def test_no_policy_records_role_but_never_rejects(tmp_path, monkeypatch):
    monkeypatch.setenv("CHANDRA_ROLE", "worker")
    write_evidence(tmp_path)
    written = rdb.append_row(valid_result_row(), repo_root=tmp_path)
    assert written["actor_role"] == "worker"
