"""Tamper-evident ledgers (v3 R4): every append carries
row_hash = sha256(prev_row_hash + canonical(row)); editing, dropping, or
reordering any hashed row breaks verification. "Never delete a row" is now a
check, not an honor rule."""
from __future__ import annotations

import json

from _common.ledgers import knowledge_database as kdb
from _common.ledgers import ledger_common as lc
from factories import valid_knowledge_row

PAPER = "arxiv-0000.00000"


def _ledger(tmp_path):
    return tmp_path / "results" / "ledgers" / "knowledge" / f"paper_{PAPER}"


def test_appends_chain_and_verify_clean(tmp_path):
    kdb.append_row(valid_knowledge_row(node_id="a"), repo_root=tmp_path)
    kdb.append_row(valid_knowledge_row(node_id="b"), repo_root=tmp_path)
    rows = kdb.read_entries(tmp_path, PAPER)
    assert all(len(r["row_hash"]) == 64 for r in rows)
    v = lc.verify_chain(_ledger(tmp_path), "nodes.jsonl")
    assert v == {"ok": True, "rows": 2, "hashed": 2, "break_at": None}


def test_edited_row_breaks_the_chain(tmp_path):
    kdb.append_row(valid_knowledge_row(node_id="a"), repo_root=tmp_path)
    kdb.append_row(valid_knowledge_row(node_id="b"), repo_root=tmp_path)
    f = _ledger(tmp_path) / "nodes.jsonl"
    lines = f.read_text().splitlines()
    forged = json.loads(lines[0])
    forged["summary"] = "FORGED"
    f.write_text("\n".join([json.dumps(forged), lines[1]]) + "\n")
    v = lc.verify_chain(_ledger(tmp_path), "nodes.jsonl")
    assert v["ok"] is False and v["break_at"] == 0
    assert "hash mismatch" in v["reason"]


def test_dropped_row_breaks_the_chain(tmp_path):
    for nid in ("a", "b", "c"):
        kdb.append_row(valid_knowledge_row(node_id=nid), repo_root=tmp_path)
    f = _ledger(tmp_path) / "nodes.jsonl"
    lines = f.read_text().splitlines()
    f.write_text("\n".join([lines[0], lines[2]]) + "\n")   # delete the middle row
    assert lc.verify_chain(_ledger(tmp_path), "nodes.jsonl")["ok"] is False


def test_legacy_unhashed_prefix_is_tolerated_then_enforced(tmp_path):
    d = _ledger(tmp_path)
    d.mkdir(parents=True)
    legacy = valid_knowledge_row(node_id="old")
    (d / "nodes.jsonl").write_text(json.dumps(legacy) + "\n")   # pre-chain history
    kdb.append_row(valid_knowledge_row(node_id="new"), repo_root=tmp_path)
    v = lc.verify_chain(d, "nodes.jsonl")
    assert v["ok"] is True and v["hashed"] == 1 and v["rows"] == 2
    assert lc.verify_all_chains(tmp_path)["ok"] is True


def test_verify_all_chains_reports_the_breaking_ledger(tmp_path):
    kdb.append_row(valid_knowledge_row(node_id="a"), repo_root=tmp_path)
    f = _ledger(tmp_path) / "nodes.jsonl"
    row = json.loads(f.read_text())
    row["status"] = "solid"                                     # forge a promotion
    f.write_text(json.dumps(row) + "\n")
    report = lc.verify_all_chains(tmp_path)
    assert report["ok"] is False
    assert report["breaks"][0]["db"] == "knowledge"
