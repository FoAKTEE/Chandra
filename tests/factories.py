"""Schema-valid ledger rows for the infra tests.

Each builder returns a FRESH dict so a test can mutate one field to construct a
rejection case without disturbing other tests. `**over` overrides any field.
The defaults here are, by construction, the minimal rows that pass each
ledger's `validate()` — if a ledger schema tightens, these break first.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def write_evidence(root: str | Path, rel: str = "artifacts/out.txt",
                   content: str = "verifier output\n") -> str:
    """Materialize an evidence artifact under a tmp repo root so rows pass the
    executable admission gate (checked/solid evidence must resolve to a real
    file, a commit, or a passing verification run). Returns the relative path."""
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return rel


def valid_result_row(**over: Any) -> dict[str, Any]:
    """A `result_database` row in the terminal `checked` state (no open obligations)."""
    row: dict[str, Any] = {
        "paper": "arxiv-0000.00000",
        "result_id": "r1",
        "name": "unit-test result",
        "working_context": {"model": "toy", "units": "SI"},
        "claim": "1 + 1 = 2",
        "evidence_type": "exact_proof",
        "evidence": "artifacts/out.txt",
        "verifier_result": {"verdict": "pass"},
        "dependencies": [],
        "assumptions": [],
        "status": "checked",
        "provenance": "stage4-test",
        "open_obligations": [],
    }
    row.update(over)
    return row


def valid_error_pass_row(**over: Any) -> dict[str, Any]:
    """An `error_database` trial row with pass_fail='pass' (no on-fail fields needed)."""
    row: dict[str, Any] = {
        "paper": "arxiv-0000.00000",
        "task_id": "t1",
        "iteration": 1,
        "stage": "validation",
        "domain": "symbolic",
        "change_type": "structural",
        "change_summary": "exercise the validator",
        "metric": {"name": "residual", "value": 0.0, "threshold": 1e-6, "pass": True},
        "pass_fail": "pass",
        "wall_clock_seconds": 1.0,
    }
    row.update(over)
    return row


def valid_error_fail_row(**over: Any) -> dict[str, Any]:
    """A pass row promoted to a failure: carries the §0 required-on-fail fields
    and a real symbolic failure_mode."""
    row = valid_error_pass_row(
        pass_fail="fail",
        metric={"name": "residual", "value": 1.0, "threshold": 1e-6, "pass": False},
        expected="paper claim X holds",
        observed="residual 1.0 > 1e-6 (artifacts/run.log)",
        root_cause="FullSimplify left a non-zero residual (artifacts/run.log)",
        fix_hypothesis="supply the missing positivity assumption",
        failure_mode="nonsimplification",
    )
    row.update(over)
    return row


def valid_knowledge_row(**over: Any) -> dict[str, Any]:
    """A `knowledge_database` node in the `hypothesis` state (no evidence required)."""
    row: dict[str, Any] = {
        "paper": "arxiv-0000.00000",
        "node_id": "n1",
        "task_id": "t1",
        "domain": "symbolic",
        "status": "hypothesis",
        "summary": "a candidate node",
    }
    row.update(over)
    return row


def valid_claim_row(**over: Any) -> dict[str, Any]:
    """A `claims_database` claim entry in the `open` state."""
    row: dict[str, Any] = {
        "paper": "arxiv-0000.00000",
        "entry_id": "c1",
        "kind": "claim",
        "statement": "energy is conserved in the toy model",
        "status": "open",
        "needed_evidence_type": "symbolic_derivation",
    }
    row.update(over)
    return row


def valid_obligation_row(**over: Any) -> dict[str, Any]:
    """A `claims_database` obligation entry in the `open` state."""
    row: dict[str, Any] = {
        "paper": "arxiv-0000.00000",
        "entry_id": "o1",
        "kind": "obligation",
        "statement": "check the boundary term vanishes",
        "status": "open",
    }
    row.update(over)
    return row


def valid_assumption_row(**over: Any) -> dict[str, Any]:
    """A `claims_database` assumption entry in the `active` state."""
    row: dict[str, Any] = {
        "paper": "arxiv-0000.00000",
        "entry_id": "a1",
        "kind": "assumption",
        "statement": "spherical symmetry of the background",
        "status": "active",
        "scope": "background metric",
    }
    row.update(over)
    return row
