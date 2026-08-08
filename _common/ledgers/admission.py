"""admission — executable admission checks for the append-only ledgers.

"The agent proposes; the verifier admits." Before this module the admitting
step checked only row SHAPE; every semantic gate (does the evidence exist?
did the verifier actually run? do the cited dependencies exist?) was prose
the appending agent self-administered. This module makes those gates
executable at append time. It owns no schema and no CLI; the ledger modules
call into it from `append_row`.

Gates:
  * verification execution — a row carrying `verification.command` has the
    command RUN at append; exit 0 is required for admission (a certifying
    command that fails belongs in error-database, not here). The observed
    outcome (exit code, output sha256, output tail, duration) is recorded on
    the row, so the ledger carries what the verifier SAW, not what the agent
    claimed.
  * evidence resolution — evidence naming an existing file is content-
    addressed into `evidence_sha256`. Strict statuses (result `checked`,
    knowledge `solid`) REQUIRE evidence in one of three verifiable forms:
    an existing artifact file, a git commit citation that resolves in this
    repo, or a passing `verification.command` run.
  * dependency existence — `::`-namespaced dependencies must resolve to a
    knowledge-ledger node; a `solid` node's predecessors must themselves be
    `solid` (no solid chain on non-solid support).

Escape hatches are explicit keyword/CLI flags and are recorded on the row in
`admission_flags`, so a bypass is visible in the ledger instead of silent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTPUT_TAIL_CHARS = 2000
DEFAULT_TIMEOUT_S = 300

# --- delegation policy ---------------------------------------------------------
# When `<repo-root>/.delegation-policy` contains `strict`, research rows are
# appended ONLY by delegated agents: the process must carry CHANDRA_ROLE in
# ROLE_ENV_ALLOWED (the orchestrator injects it into spawned worker/validator/
# observer sessions). The launching/orchestrating agent has no role marker, so
# its inline appends are REJECTED — orchestrators orchestrate; workers work.
# `human-override` is the deliberate, visible escape hatch. Whatever role is
# present is recorded on the row as `actor_role` (provenance, never silent).

ROLE_ENV_VAR = "CHANDRA_ROLE"
ROLE_ENV_ALLOWED = ("worker", "validator", "observer", "human-override")
POLICY_FILE = ".delegation-policy"


def delegation_policy(repo_root: str | Path) -> str:
    p = Path(repo_root) / POLICY_FILE
    if not p.is_file():
        return "off"
    return p.read_text(encoding="utf-8").strip().lower() or "off"


def check_actor_role(row: dict[str, Any], repo_root: str | Path) -> None:
    """Record actor_role; under strict delegation, reject non-delegated appends."""
    role = os.environ.get(ROLE_ENV_VAR, "").strip()
    if role:
        row["actor_role"] = role
    if delegation_policy(repo_root) != "strict":
        return
    if role not in ROLE_ENV_ALLOWED:
        raise AdmissionError(
            f"delegation policy is strict: research rows are appended by worker agents, "
            f"not the orchestrating session ({ROLE_ENV_VAR}={role or 'unset'!r}; allowed: "
            f"{ROLE_ENV_ALLOWED}). Spawn a worker (orchestrator wave or sub-agent with "
            f"{ROLE_ENV_VAR}=worker) — or set {ROLE_ENV_VAR}=human-override deliberately; "
            "the role is recorded on the row either way")

_PATH_SUFFIXES = (".txt", ".log", ".md", ".json", ".jsonl", ".csv", ".wl",
                  ".nb", ".py", ".jl", ".cpp", ".pdf", ".png", ".html")
_COMMIT_RE = re.compile(r"(?:commit\s+)?([0-9a-f]{7,40})", re.IGNORECASE)


class AdmissionError(ValueError):
    """A row that fails an executable admission gate. Subclasses ValueError so
    existing rejection handling (and tests) treat it like a schema violation."""


# --- primitives ---------------------------------------------------------------

def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def run_verification(spec: Any, repo_root: str | Path) -> dict[str, Any]:
    """Execute a row's `verification` object: {command, timeout_s?, cwd?}.

    Returns the observed outcome record; raises AdmissionError on a malformed
    spec or a timeout. Does NOT judge the exit code — callers gate on it so
    the rejection message can say which row rule was violated.
    """
    if not isinstance(spec, dict) or not isinstance(spec.get("command"), str) or not spec["command"].strip():
        raise AdmissionError("verification must be an object {command, timeout_s?, cwd?} with a non-empty command")
    root = Path(repo_root)
    cwd = root / spec["cwd"] if spec.get("cwd") else root
    timeout = spec.get("timeout_s", DEFAULT_TIMEOUT_S)
    started = datetime.now(timezone.utc)

    def _limits():  # POSIX resource cap: a verifier cannot burn unbounded CPU
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (int(timeout) + 5, int(timeout) + 5))
        except Exception:
            pass

    try:
        proc = subprocess.run(spec["command"], shell=True, cwd=str(cwd),
                              capture_output=True, text=True, timeout=timeout,
                              preexec_fn=_limits)
    except subprocess.TimeoutExpired:
        raise AdmissionError(f"verification command timed out after {timeout}s: {spec['command']!r}")
    combined = (proc.stdout or "") + (proc.stderr or "")
    return {
        "command": spec["command"],
        "exit_code": proc.returncode,
        "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
        "output_sha256": hashlib.sha256(combined.encode("utf-8", "replace")).hexdigest(),
        "output_tail": combined[-OUTPUT_TAIL_CHARS:],
        "ran_at": started.isoformat(timespec="seconds"),
    }


def evidence_path(evidence: Any, repo_root: str | Path) -> Path | None:
    """Resolve evidence to an existing file under repo_root, if it names one.
    Accepts a path string or an object carrying a `path` key."""
    if isinstance(evidence, dict):
        evidence = evidence.get("path")
    if not isinstance(evidence, str) or not evidence.strip():
        return None
    p = Path(repo_root) / evidence
    return p if p.is_file() else None


def is_commit_citation(evidence: Any, repo_root: str | Path) -> bool:
    """True iff evidence is a commit citation that resolves in this repo."""
    if not isinstance(evidence, str):
        return False
    m = _COMMIT_RE.fullmatch(evidence.strip())
    if not m:
        return False
    try:
        subprocess.check_call(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"{m.group(1)}^{{commit}}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _flag(row: dict[str, Any], flag: str) -> None:
    flags = row.setdefault("admission_flags", [])
    if flag not in flags:
        flags.append(flag)


# --- knowledge-ledger lookup (raw file scan; no import cycle with the ledger) --

def _latest_non_amended(rows: list[dict[str, Any]], node_id: str) -> dict[str, Any] | None:
    hit: dict[str, Any] | None = None
    for r in rows:
        if r.get("node_id") == node_id and r.get("status") != "amended":
            hit = r
    return hit


def find_knowledge_node(node_id: str, repo_root: str | Path,
                        paper_hint: str | None = None) -> dict[str, Any] | None:
    """Latest non-amended knowledge row for `node_id`, searching the hinted
    paper's ledger first, then every knowledge ledger in both layouts
    (covers cross-paper `PAPER::node` and `_shared::` ids)."""
    root = Path(repo_root)
    from . import ledger_common as _lc  # safe: ledger_common imports nothing from ledgers
    files: list[Path] = []
    if paper_hint:
        files.append(_lc.db_dir(root, "knowledge", paper_hint) / "nodes.jsonl")
    files.extend(d / "nodes.jsonl" for _, d in _lc.iter_paper_dirs(root, "knowledge")
                 if d / "nodes.jsonl" not in files)
    for f in files:
        if not f.is_file():
            continue
        rows = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        hit = _latest_non_amended(rows, node_id)
        if hit is not None:
            return hit
    return None


# --- the two gates -------------------------------------------------------------

def _execute_if_present(row: dict[str, Any], root: Path, *, skip_exec: bool) -> dict[str, Any] | None:
    """Run row['verification'] when present and require exit 0. Returns the
    observed outcome (the caller records it on the row) or None."""
    spec = row.get("verification")
    if spec is None:
        return None
    if skip_exec:
        _flag(row, "skip_exec")
        return None
    outcome = run_verification(spec, root)
    if outcome["exit_code"] != 0:
        tail = outcome["output_tail"].strip().splitlines()[-1:] or [""]
        raise AdmissionError(
            f"verification command failed (exit {outcome['exit_code']}): {tail[0]!r} — "
            "a row whose certifying command fails is not admissible; log the trial in error-database instead")
    return outcome


def check_result_admission(row: dict[str, Any], repo_root: str | Path | None, *,
                           skip_exec: bool = False,
                           allow_missing_deps: bool = False) -> dict[str, Any]:
    """Executable stage-4 admission. Mutates and returns the row."""
    root = Path(repo_root) if repo_root else Path.cwd()
    check_actor_role(row, root)
    executed = _execute_if_present(row, root, skip_exec=skip_exec)
    if executed is not None:
        row["verifier_result"]["execution"] = executed
        if row["verifier_result"].get("verdict") == "fail":
            raise AdmissionError(
                "verification command passed (exit 0) but claimed verdict is 'fail' — reconcile before appending")

    ep = evidence_path(row.get("evidence"), root)
    if ep is not None:
        row["evidence_sha256"] = sha256_file(ep)

    if row["status"] == "checked":
        if row["verifier_result"].get("verdict") != "pass":
            raise AdmissionError("status='checked' requires verifier_result.verdict='pass'")
        verifiable = (executed is not None or "evidence_sha256" in row
                      or is_commit_citation(row.get("evidence"), root))
        if not verifiable:
            raise AdmissionError(
                "status='checked' requires verifiable evidence: an existing artifact file "
                "(content-hashed), a resolvable git commit citation, or a passing "
                "`verification.command` executed at append (closed-loop admission)")

    missing = [d for d in row.get("dependencies", [])
               if isinstance(d, str) and "::" in d
               and find_knowledge_node(d, root, paper_hint=row.get("paper")) is None]
    if missing:
        if allow_missing_deps:
            _flag(row, "allow_missing_deps")
        else:
            raise AdmissionError(
                f"dependencies not found in knowledge-database: {missing}; "
                "append the nodes first or pass --allow-missing-deps")
    return row


def check_knowledge_admission(row: dict[str, Any], repo_root: str | Path | None, *,
                              skip_exec: bool = False,
                              allow_missing_deps: bool = False) -> dict[str, Any]:
    """Executable knowledge-node admission. Mutates and returns the row."""
    root = Path(repo_root) if repo_root else Path.cwd()
    check_actor_role(row, root)
    executed = _execute_if_present(row, root, skip_exec=skip_exec)
    if executed is not None:
        row["verification_run"] = executed

    ev = row.get("evidence")
    ep = evidence_path(ev, root)
    if ep is not None:
        row["evidence_sha256"] = sha256_file(ep)

    if row["status"] == "solid":
        verifiable = (executed is not None or "evidence_sha256" in row
                      or is_commit_citation(ev, root))
        if not verifiable:
            raise AdmissionError(
                "status='solid' requires verifiable evidence: an existing file (content-hashed), "
                "a resolvable git commit citation, or a passing `verification.command` — "
                "free-text evidence is not admissible")
        for pred in row.get("predecessors", []):
            prow = find_knowledge_node(pred, root, paper_hint=row.get("paper"))
            if prow is None:
                if allow_missing_deps:
                    _flag(row, "allow_missing_deps")
                    continue
                raise AdmissionError(
                    f"solid node {row.get('node_id')!r} cites unknown predecessor {pred!r}; "
                    "append the predecessor first or pass --allow-missing-deps")
            if prow.get("status") != "solid":
                raise AdmissionError(
                    f"solid node cannot rest on non-solid predecessor {pred!r} "
                    f"(status={prow.get('status')!r}); promote the predecessor first "
                    "or keep this node 'preliminary'")
    return row
