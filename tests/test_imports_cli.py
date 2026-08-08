"""Import + CLI smoke over every shipped module — the "wrapper CLIs / grouped
CLIs" the refactor commit (1438aae) claims to have verified.

Covers both the grouped package modules (`_common.ledgers.*`, etc.) AND the flat
compatibility shims (`_common.result_database`, etc.), and asserts the shims
re-export the SAME `main` object — so the back-compat layer is provably faithful,
not just present.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

PACKAGE_MODULES = [
    "_common.ledgers.ledger_common",
    "_common.ledgers.admission",
    "_common.ledgers.error_database",
    "_common.ledgers.knowledge_database",
    "_common.ledgers.result_database",
    "_common.ledgers.claims_database",
    "_common.loop.loop_gate",
    "_common.loop.loop_policy",
    "_common.visualization.dag_mermaid",
    "_common.visualization.dashboard",
    "_common.quality.code_quality",
]

FLAT_SHIMS = [
    "_common.ledger_common",
    "_common.error_database",
    "_common.knowledge_database",
    "_common.result_database",
    "_common.claims_database",
    "_common.loop_gate",
    "_common.loop_policy",
    "_common.code_quality",
]

# (flat shim, grouped module) pairs that both expose a `main` CLI entry point.
SHIM_MAIN_PAIRS = [
    ("_common.error_database", "_common.ledgers.error_database"),
    ("_common.knowledge_database", "_common.ledgers.knowledge_database"),
    ("_common.result_database", "_common.ledgers.result_database"),
    ("_common.claims_database", "_common.ledgers.claims_database"),
    ("_common.loop_gate", "_common.loop.loop_gate"),
    ("_common.loop_policy", "_common.loop.loop_policy"),
    ("_common.code_quality", "_common.quality.code_quality"),
]

# Executable scripts (grouped + flat + the two stage pipelines) that must answer --help.
CLI_SCRIPTS = [
    "_common/ledgers/error_database.py",
    "_common/ledgers/knowledge_database.py",
    "_common/ledgers/result_database.py",
    "_common/ledgers/claims_database.py",
    "_common/claims_database.py",
    "_common/loop/loop_gate.py",
    "_common/loop/loop_policy.py",
    "_common/visualization/dag_mermaid.py",
    "_common/visualization/dashboard.py",
    "_common/quality/code_quality.py",
    "_common/error_database.py",
    "_common/knowledge_database.py",
    "_common/result_database.py",
    "_common/loop_gate.py",
    "_common/contract.py",
]

# Ledger CLIs whose `schema` subcommand should print a non-empty spec.
SCHEMA_CLIS = [
    "_common/ledgers/error_database.py",
    "_common/ledgers/knowledge_database.py",
    "_common/ledgers/result_database.py",
    "_common/ledgers/claims_database.py",
]


@pytest.mark.parametrize("module", PACKAGE_MODULES + FLAT_SHIMS)
def test_module_imports(module):
    importlib.import_module(module)


@pytest.mark.parametrize("flat,grouped", SHIM_MAIN_PAIRS)
def test_flat_shim_reexports_same_main(flat, grouped):
    fm = importlib.import_module(flat)
    gm = importlib.import_module(grouped)
    assert fm.main is gm.main, f"{flat}.main is not {grouped}.main"


def test_ledger_common_shim_reexports():
    flat = importlib.import_module("_common.ledger_common")
    grouped = importlib.import_module("_common.ledgers.ledger_common")
    assert flat.utc_now_iso is grouped.utc_now_iso


@pytest.mark.parametrize("script", CLI_SCRIPTS)
def test_cli_help_exits_zero(script):
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / script), "--help"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "usage" in r.stdout.lower()


@pytest.mark.parametrize("script", SCHEMA_CLIS)
def test_ledger_schema_subcommand(script):
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / script), "schema"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip(), "schema output is empty"
