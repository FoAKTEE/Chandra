"""Revision admission, validated batch replay, and retirement regressions."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from _common import contract
from _common.ledgers import admission as adm, ledger_common as lc
from _common.ledgers import claims_database as cdb, error_database as edb
from _common.ledgers import knowledge_database as kdb, result_database as rdb
from factories import (valid_claim_row, valid_error_pass_row, valid_knowledge_row,
                       valid_obligation_row, valid_result_row, write_evidence)

PAPER = "arxiv-0000.00000"
ROOT = Path(__file__).resolve().parents[1]
MODULES = {"result": rdb, "claim": cdb, "knowledge": kdb, "error": edb}
IDS = {"result": "result_id", "claim": "entry_id", "knowledge": "node_id", "error": "request_id"}
FACTORIES = {"result": valid_result_row, "claim": valid_claim_row,
             "knowledge": valid_knowledge_row, "error": valid_error_pass_row}
CHANGES = {
    "result": {"claim": "1 + 1 != 2", "evidence_type": "symbolic_derivation",
               "working_context": {"model": "different"}, "assumptions": ["A"],
               "dependencies": ["source-A"], "evidence": "artifacts/other.txt"},
    "claim": {"kind": "obligation", "statement": "a different proposition",
              "needed_evidence_type": "exact_proof", "scope": "another regime"},
    "knowledge": {"summary": "a different node", "predecessors": ["base"],
                  "domain": "proof", "equation_labels": ["eq:new"]},
}


def seed(db, **over):
    if db == "error":
        over.setdefault("request_id", "trial-1")
    if db == "result":
        over.setdefault("status", "conditional")
    return FACTORIES[db](**over)


@pytest.mark.parametrize("db,field,value", [
    (db, field, value) for db, changes in CHANGES.items() for field, value in changes.items()
])
def test_semantic_transition_matrix(tmp_path, db, field, value):
    module = MODULES[db]
    write_evidence(tmp_path)
    write_evidence(tmp_path, "artifacts/other.txt")
    original = seed(db)
    module.append_row(deepcopy(original), repo_root=tmp_path)
    promoted = {**original, "status": {"result": "checked", "claim": "in_progress", "knowledge": "solid"}[db]}
    if db == "knowledge":
        promoted["evidence"] = "artifacts/out.txt"
    module.append_row(deepcopy(promoted), repo_root=tmp_path)
    # Promotions AND demotions preserve the proposition and remain unlinked.
    current = module.append_row(deepcopy(original), repo_root=tmp_path)
    changed = {**original, field: value}
    with pytest.raises(ValueError, match=field):
        module.append_row(deepcopy(changed), repo_root=tmp_path)
    assert len(module.read_entries(tmp_path, PAPER)) == 3
    linked = module.append_row({**changed, "supersedes": current["row_hash"]}, repo_root=tmp_path)
    history = module.query(PAPER, latest_only=False, repo_root=tmp_path)
    assert history[-1]["supersedes"] == current["row_hash"]
    assert module.query(PAPER, repo_root=tmp_path)[0]["row_hash"] == linked["row_hash"]
    assert lc.verify_all_chains(tmp_path)["ok"]


@pytest.mark.parametrize("db", MODULES)
@pytest.mark.parametrize("target", ["bogus", "other_id", "other_paper", "other_ledger"])
def test_supersedes_must_resolve_in_same_ledger_paper_and_id(tmp_path, db, target):
    module = MODULES[db]
    original = seed(db)
    prior = module.append_row(deepcopy(original), repo_root=tmp_path)
    target_hash = "0" * 64
    if target == "other_id":
        target_hash = module.append_row(seed(db, **{IDS[db]: "other"}), repo_root=tmp_path)["row_hash"]
    elif target == "other_paper":
        target_hash = module.append_row(seed(db, paper="elsewhere"), repo_root=tmp_path)["row_hash"]
    elif target == "other_ledger":
        other = "claim" if db != "claim" else "knowledge"
        target_hash = MODULES[other].append_row(seed(other), repo_root=tmp_path)["row_hash"]
    with pytest.raises(ValueError, match="supersedes"):
        module.append_row({**original, "supersedes": target_hash}, repo_root=tmp_path)
    # A valid link is admitted even when the semantic payload is unchanged.
    written = module.append_row({**original, "supersedes": prior["row_hash"]}, repo_root=tmp_path)
    assert written["supersedes"] == prior["row_hash"]


@pytest.mark.parametrize("db", MODULES)
@pytest.mark.parametrize("value", [None, 42])
def test_supersedes_shape_is_validated(tmp_path, db, value):
    with pytest.raises(ValueError, match="supersedes"):
        MODULES[db].append_row(seed(db, supersedes=value), repo_root=tmp_path)


@pytest.mark.parametrize("db", MODULES)
def test_superseded_history_is_marked_in_rendered_views(tmp_path, db):
    module = MODULES[db]
    first = module.append_row(seed(db), repo_root=tmp_path)
    second = module.append_row(seed(db, supersedes=first["row_hash"]), repo_root=tmp_path)
    summary = (lc.db_dir(tmp_path, db, PAPER) / "summary.csv").read_text()
    assert "superseded" in summary and first["row_hash"] in summary
    if db == "claim":
        rendered = cdb.render_md(PAPER, "claim", repo_root=tmp_path, latest_only=False)
    elif db == "error":
        rendered = module.render_html(PAPER, repo_root=tmp_path).read_text()
    else:
        rendered = module.render_html(PAPER, repo_root=tmp_path, latest_only=False).read_text()
    assert "superseded" in rendered
    assert first["row_hash"] in rendered and second["row_hash"] in rendered
    if db == "result":
        assert "superseded" in module.render_md(PAPER, latest_only=False, repo_root=tmp_path)


def test_real_promotions_and_legacy_amended_replay(tmp_path):
    # Replay the real payloads, using the existing explicit skip-exec escape:
    # this tests identity compatibility, not historical verifier reproducibility.
    # Resolve original commit citations read-only through the source git dir.
    git_dir = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--absolute-git-dir"], text=True).strip()
    (tmp_path / ".git").write_text(f"gitdir: {git_dir}\n")
    source = kdb.read_entries(ROOT, "self")
    latest = {}
    promotions = 0
    for source_row in source:
        row = {k: deepcopy(v) for k, v in source_row.items()
               if k not in {"row_hash", "timestamp", "actor_role", "verification_run", "evidence_sha256"}}
        previous = latest.get(row["node_id"])
        promotions += bool(previous and previous["status"] == "hypothesis" and row["status"] == "solid")
        latest[row["node_id"]] = kdb.append_row(row, repo_root=tmp_path, skip_exec=True)
    assert promotions >= 14  # all 14 original transitions, plus later repo work
    assert len(kdb.read_entries(tmp_path, "self")) == len(source)
    current = latest[source[0]["node_id"]]
    amended = {**current, "status": "amended", "summary": "legacy correction pointer"}
    kdb.append_row(amended, repo_root=tmp_path, skip_exec=True)
    active = kdb.query("self", node_id=current["node_id"], repo_root=tmp_path)
    assert active[0]["status"] == current["status"]
    # Amendment text never becomes the semantic baseline of the active node.
    changed = {**current, "summary": "unlinked new meaning"}
    changed.pop("supersedes", None)
    with pytest.raises(ValueError, match="summary"):
        kdb.append_row(changed, repo_root=tmp_path, skip_exec=True)


def test_retirement_removes_active_node_but_preserves_cli_history(tmp_path):
    original = seed("knowledge", status="future")
    kdb.append_row(deepcopy(original), repo_root=tmp_path)
    retired = kdb.append_row({**original, "status": "retired"}, repo_root=tmp_path)
    kdb.append_row({**original, "status": "amended"}, repo_root=tmp_path)
    cli = [sys.executable, str(ROOT / "_common/knowledge_database.py"), "query", "--paper", PAPER, "--repo-root", str(tmp_path)]
    assert json.loads(subprocess.check_output(cli, text=True)) == []
    history = json.loads(subprocess.check_output([*cli, "--with-history"], text=True))
    assert history[1]["row_hash"] == retired["row_hash"]
    assert kdb.latest_status(history, PAPER, "n1")["status"] == "retired"
    assert adm.find_knowledge_node("n1", tmp_path)["status"] == "retired"


@pytest.mark.parametrize("dependent_paper", [PAPER, "other"])
def test_retiring_with_dependents_requires_recorded_flag(tmp_path, dependent_paper):
    parent = seed("knowledge", node_id="P::parent")
    child = seed("knowledge", paper=dependent_paper, node_id="Q::child", predecessors=["P::parent"])
    kdb.append_batch([parent, child], repo_root=tmp_path)
    with pytest.raises(ValueError, match="Q::child"):
        kdb.append_row({**parent, "status": "retired"}, repo_root=tmp_path)
    command = [sys.executable, str(ROOT / "_common/knowledge_database.py"), "append", "--repo-root", str(tmp_path), "--allow-dependents"]
    proc = subprocess.run(command, input=json.dumps({**parent, "status": "retired"}), text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    assert "allow_dependents" in kdb.read_entries(tmp_path, PAPER)[-1]["admission_flags"]
    kdb.append_row({**child, "status": "retired"}, repo_root=tmp_path)
    # Only the latest dependent matters; retired dependents do not require a bypass.
    written = kdb.append_row({**parent, "status": "retired"}, repo_root=tmp_path)
    assert "allow_dependents" not in written.get("admission_flags", [])


@pytest.mark.parametrize("db", ["result", "error"])
def test_batch_replay_counts_and_partial_prefix_recovery(tmp_path, db):
    module = MODULES[db]
    first = seed(db, verification={"command": "true"}) if db == "result" else seed(db)
    second = seed(db, **{IDS[db]: "second"})
    invalid = {**second}
    invalid.pop("paper")
    with pytest.raises(ValueError, match="paper"):
        module.append_batch([deepcopy(first), invalid], repo_root=tmp_path)
    report = module.append_batch([deepcopy(first), second], repo_root=tmp_path)
    assert (report["appended"], report.get("replayed"), report["of"]) == (1, 1, 2)
    assert len(module.read_entries(tmp_path, PAPER)) == 2


def test_trial_request_conflict_and_explicit_single_row_revision(tmp_path):
    row = seed("error")
    first = edb.append_row(deepcopy(row), repo_root=tmp_path)
    changed = {**row, "change_summary": "corrected observation"}
    with pytest.raises(ValueError, match="request_id"):
        edb.append_batch([deepcopy(changed)], repo_root=tmp_path)
    with pytest.raises(ValueError, match="supersedes"):
        edb.append_row(deepcopy(changed), repo_root=tmp_path)
    linked = {**changed, "supersedes": first["row_hash"]}
    edb.append_row(deepcopy(linked), repo_root=tmp_path)
    assert edb.append_batch([row, linked], repo_root=tmp_path)["replayed"] == 2
    # Rows without request identity are still distinct trials.
    assert edb.append_batch([valid_error_pass_row(), valid_error_pass_row()], repo_root=tmp_path)["appended"] == 2


@pytest.mark.parametrize("value", [None, 7, ""])
def test_request_id_is_optional_but_must_be_a_nonempty_string(tmp_path, value):
    with pytest.raises(ValueError, match="request_id"):
        edb.append_batch([seed("error", request_id=value)], repo_root=tmp_path)


@pytest.mark.parametrize("db,missing", [("knowledge", "domain"), ("claim", "needed_evidence_type")])
def test_batch_schema_validation_precedes_dedup(tmp_path, db, missing):
    module = MODULES[db]
    row = seed(db)
    module.append_batch([deepcopy(row)], repo_root=tmp_path)
    row.pop(missing)
    with pytest.raises(ValueError, match=missing):
        module.append_batch([row], repo_root=tmp_path)


@pytest.mark.parametrize("db", ["knowledge", "claim"])
def test_batch_gate_validation_precedes_dedup(tmp_path, db):
    module = MODULES[db]
    if db == "knowledge":
        row = seed(db)
        module.append_batch([deepcopy(row)], repo_root=tmp_path)
        row["verification"] = {"command": "exit 9"}
        match = "verification command failed"
    else:
        row = seed(db, status="admitted", result_ref="missing")
        module.append_batch([deepcopy(row)], repo_root=tmp_path, allow_missing_refs=True)
        match = "result_ref"
    with pytest.raises(ValueError, match=match):
        module.append_batch([row], repo_root=tmp_path)


@pytest.mark.parametrize("force", [False, True])
def test_batch_changed_predecessors_need_lineage_even_with_force(tmp_path, force):
    row = seed("knowledge", predecessors=[])
    first = kdb.append_row(deepcopy(row), repo_root=tmp_path)
    changed = {**row, "predecessors": ["parent"]}
    with pytest.raises(ValueError, match="predecessors"):
        kdb.append_batch([deepcopy(changed)], repo_root=tmp_path, force=force)
    assert kdb.append_batch([{**changed, "supersedes": first["row_hash"]}], repo_root=tmp_path, force=force)["appended"] == 1


@pytest.mark.parametrize("field,value", [("owner", "0-acquire"), ("node_ids", ["P::n"]), ("blocking", True)])
def test_claim_routing_changes_append_without_supersedes(tmp_path, field, value):
    row = valid_obligation_row()
    cdb.append_batch([deepcopy(row)], repo_root=tmp_path)
    assert cdb.append_batch([{**row, field: value}], repo_root=tmp_path)["appended"] == 1
    latest = cdb.query(PAPER, repo_root=tmp_path)[0]
    assert latest[field] == value and "supersedes" not in latest


def test_manifest_exposes_revision_contract_and_retired_schema():
    revisions = contract.manifest().get("revisions")
    assert revisions and revisions["supersedes_field"] == "supersedes"
    for db, changes in CHANGES.items():
        assert set(revisions["semantic_keys"][db]) == set(changes)
    assert revisions["retired_status"] == "retired"
    assert "retired" in kdb.NONEXIST_STATUSES
    assert "retired" in kdb._schema_text()


@pytest.mark.parametrize("db", MODULES)
def test_replay_repairs_summary_after_durable_append_failure(tmp_path, monkeypatch, db):
    module = MODULES[db]
    regenerate = module.regenerate_summary

    def fail_summary(_directory):
        raise OSError("summary publication failed")

    row = seed(db)
    monkeypatch.setattr(module, "regenerate_summary", fail_summary)
    with pytest.raises(OSError, match="summary publication failed"):
        module.append_row(deepcopy(row), repo_root=tmp_path)
    assert len(module.read_entries(tmp_path, PAPER)) == 1  # durable prefix survived
    monkeypatch.setattr(module, "regenerate_summary", regenerate)
    report = module.append_batch([row], repo_root=tmp_path)
    assert report["appended"] == 0
    assert report["replayed" if db in ("error", "result") else "skipped"] == 1
    assert (lc.db_dir(tmp_path, db, PAPER) / "summary.csv").is_file()
    assert len(module.read_entries(tmp_path, PAPER)) == 1


def test_semantic_comparison_distinguishes_json_booleans_and_numbers(tmp_path):
    row = seed("result", working_context={"control": True})
    first = rdb.append_row(deepcopy(row), repo_root=tmp_path)
    changed = {**row, "working_context": {"control": 1}}
    with pytest.raises(ValueError, match="working_context"):
        rdb.append_row(deepcopy(changed), repo_root=tmp_path)
    rdb.append_row({**changed, "supersedes": first["row_hash"]}, repo_root=tmp_path)


def test_trial_replay_distinguishes_json_booleans_and_numbers(tmp_path):
    row = seed("error", parameter_regime={"control": True})
    edb.append_batch([deepcopy(row)], repo_root=tmp_path)
    with pytest.raises(ValueError, match="request_id"):
        edb.append_batch([{**row, "parameter_regime": {"control": 1}}], repo_root=tmp_path)
