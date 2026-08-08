"""Smoke + rejection checks for the commit-msg gate (_common/hooks/commit-msg).

The gate is the promoted, enforceable form of progress/COMMIT_TEMPLATE.md. Per the
repo's tool-promotion doctrine, a promoted tool ships with a tests/ smoke +
rejection check; this self-hosts the gate on the §0 closed-loop rule.

Each case writes a message to a temp file and runs the hook standalone:
exit 0 = admit, exit 1 = reject.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "_common" / "hooks" / "commit-msg"


def run_gate(tmp_path: Path, message: str, strict: bool = False) -> int:
    """Run the gate against `message`; return its exit code."""
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(message)
    env = {"COMMIT_GATE_STRICT": "1"} if strict else None
    proc = subprocess.run(
        ["bash", str(HOOK), str(msg_file)],
        capture_output=True,
        text=True,
        env=({**__import__("os").environ, **env} if env else None),
    )
    return proc.returncode


def test_hook_exists_and_executable() -> None:
    assert HOOK.is_file(), f"missing gate script: {HOOK}"


# --- ADMIT cases -------------------------------------------------------------

ADMIT = [
    # subject-only, core CC types
    "feat(F7): reproduce the combined-spin spiral",
    "fix(F6,source): stop double-raising the force index",
    "perf(metric): memoize lindblad_locations",
    "docs(checkpoint): re-anchor on the open node",
    "revert(F6): undo the phase-strip change",
    # repo taxonomy
    "diag(F6,forcing): localize the scramble upstream of VoP",
    "exp(F6,metric): re-run full BigFloat metric, m=1..14",
    "chore(data): prune unused F6 spiral intermediates",
    # methodology-repo process types (this repo's own dominant style)
    "infra: doubly-link error + knowledge ledgers to the giant DAG",
    "notes: record minus-minus source-slot proof",
    # breaking change, properly paired
    (
        "diag(F6)!: disprove the excision premise\n"
        "\n"
        "- finding: indicial roots {0,2} are regular [SOLID]\n"
        "\n"
        "BREAKING CHANGE: overturns the excision-based approach in iters 296-299\n"
    ),
    # full typed body with tagged claims
    (
        "fix(F6,bvp): fix the calibrated genuine-operator spiral\n"
        "\n"
        "- finding: per-mode phase-strip destroyed the phase lock [SOLID]\n"
        "- change: remove the phase-strip via F6_FREF=0\n"
        "- result: median 0.16, p95 0.95 inside colorbar [PRELIMINARY]\n"
    ),
]


@pytest.mark.parametrize("message", ADMIT)
def test_admits_valid(tmp_path: Path, message: str) -> None:
    assert run_gate(tmp_path, message) == 0, f"gate wrongly REJECTED:\n{message}"


# --- REJECT cases (title grammar is the hard gate) ---------------------------

REJECT = [
    "reproduce the combined-spin spiral",          # no type
    "Reproduce F7 spiral",                          # capitalized, no type token
    "wip: half-done thing",                         # unknown type
    "feat reproduce spiral",                        # missing colon
    "feat():  empty scope is malformed",            # empty scope -> () fails [^)]+
    "F7: not a real type",                          # scope-looking token, not a type
    "intermediate update",                          # legacy bare message
]


@pytest.mark.parametrize("message", REJECT)
def test_rejects_bad_title(tmp_path: Path, message: str) -> None:
    assert run_gate(tmp_path, message) == 1, f"gate wrongly ADMITTED:\n{message}"


# --- pass-through cases ------------------------------------------------------

def test_passes_through_merge(tmp_path: Path) -> None:
    assert run_gate(tmp_path, "Merge branch 'feature' into master") == 0


def test_passes_through_empty(tmp_path: Path) -> None:
    assert run_gate(tmp_path, "\n\n# only comments here\n") == 0


# --- strict mode escalates warnings to errors --------------------------------

def test_strict_mode_rejects_untagged_finding(tmp_path: Path) -> None:
    msg = (
        "diag(F6): a finding with no claim tag\n"
        "\n"
        "- finding: this finding has no [TAG]\n"
    )
    assert run_gate(tmp_path, msg) == 0           # advisory by default
    assert run_gate(tmp_path, msg, strict=True) == 1  # blocked under strict
