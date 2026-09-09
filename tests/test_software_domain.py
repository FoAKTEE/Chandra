"""The `software` domain — Chandra runs its own methodology on itself.

A self-hosted mission (the methodology repo optimizing the methodology repo)
lands software work through the same ledgers as a paper reproduction: trials
in the error ledger, converged nodes in the knowledge ledger, loop policy
recipes for the no-tweak-loop rule. That needs a domain whose failure modes,
metrics, and evidence paths describe software work — and the three modules
that each carry a DOMAINS enum must agree on it (drift killer).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from _common import contract
from _common.ledgers import error_database as edb
from _common.ledgers import knowledge_database as kdb
from _common.loop import loop_policy as lp
from factories import valid_error_fail_row, valid_error_pass_row, valid_knowledge_row

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_domain_enums_agree_across_modules() -> None:
    assert edb.DOMAINS == kdb.DOMAINS == lp.DOMAINS
    assert "software" in edb.DOMAINS


def test_software_reference_tables_are_complete() -> None:
    tags = edb.FAILURE_MODES_BY_DOMAIN["software"]
    assert tags == edb.FAILURE_MODES_SOFTWARE
    assert set(tags) == set(edb.FAILURE_MODE_MEANINGS["software"])
    assert "uncategorized_software" in tags
    assert edb.METRIC_NAMES_BY_DOMAIN["software"]
    assert edb.RECOMMENDED_RUNTIME_METADATA["software"]
    assert edb.EVIDENCE_PATH_TEMPLATES["software"]["files"]
    assert lp.SIMPLIFICATION_RECIPES["software"]["actions"]
    assert lp.CRASH_PIVOT_HINTS["software"]


def test_software_pass_row_validates() -> None:
    edb.validate(valid_error_pass_row(
        domain="software",
        metric={"name": "tests_failed", "value": 0, "threshold": 0, "pass": True}))


def test_software_fail_row_requires_a_software_tag() -> None:
    edb.validate(valid_error_fail_row(domain="software", failure_mode="test_failure"))
    with pytest.raises(ValueError, match="uncategorized_software"):
        # a symbolic tag on a software row is a schema violation
        edb.validate(valid_error_fail_row(domain="software", failure_mode="nonsimplification"))


def test_software_knowledge_row_validates() -> None:
    kdb.validate(valid_knowledge_row(domain="software"))


@pytest.mark.parametrize("script", [
    "_common/ledgers/error_database.py",
    "_common/loop/loop_policy.py",
])
def test_describe_domain_cli_knows_software(script: str) -> None:
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / script), "describe-domain", "--domain", "software"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "software" in r.stdout
    assert "uncategorized_software" in r.stdout or "pivot" in r.stdout


def test_contract_manifest_lists_software() -> None:
    assert "software" in contract.manifest()["knowledge"]["domains"]
