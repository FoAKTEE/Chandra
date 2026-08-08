"""loop_gate — progress-aware termination gate for the Ralph loop.

The Stop-hook guard (`.claude/ralph_stop_guard.sh`) used to force the loop to
continue on a single condition: `iteration < max_iterations` (default 1000).
That has no notion of PROGRESS, so a stuck loop — parameter-tweak spinning, a
never-advancing counter, or wall-clock runaway — would burn the whole budget
before anyone noticed. This module is the graceful circuit breaker.

It mirrors the milestone-gated supervisor pattern (see
`ref-code/ai-supervisor-worker-workflow`): autonomy continues only while real
progress is being made; when progress stalls the loop HALTS and writes a human
gate (`.claude/HUMAN_REVIEW_REQUIRED.md`) instead of looping forever.

DECISIONS (priority order)
    halt:inactive        — loop state has active=false (clean, no human gate)
    halt:max_iterations  — iteration >= max_iterations
    halt:time_budget     — wall clock exceeded max_wall_seconds (if set)
    halt:stuck_counter   — the iteration counter has not advanced for
                           stuck_counter_limit consecutive checks (the agent
                           is not even iterating)
    halt:no_progress     — no new SOLID node, admitted/classified result, or
                           discharged result for no_progress_limit consecutive
                           iterations (the loop is spinning without producing
                           verified results)
    continue             — otherwise

PROGRESS SIGNAL is `(solid_nodes, admitted_results, discharged_results)`
aggregated across every paper in the knowledge + result ledgers. Error-ledger
`pass` rows remain visible as activity, but they do not reset the no-progress
breaker unless they are promoted into an admitted/classified result row.

USAGE
    python _common/loop_gate.py decide  [--repo-root R] [--state-file F]
                                        [--gate-state F] [--write-gate]
    python _common/loop_gate.py status  [--repo-root R] ...   # read-only, no mutation
    python _common/loop_gate.py reset    [--gate-state F]      # clear streak state

`decide` mutates the gate-state file and exits 0 when the verdict is `continue`,
1 on any `halt:*`. `status` is a pure read used by the GUI / a human.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _common.ledgers import ledger_common as lc
from _common.ledgers import result_database as rdb

# Defaults (overridable per consumer via loop-state frontmatter).
DEFAULT_NO_PROGRESS_LIMIT = 8      # iterations without admitted/solid progress
DEFAULT_STUCK_COUNTER_LIMIT = 3    # stop-hook fires at an unchanged iteration counter
DEFAULT_MAX_ITERATIONS = 1000
DEFAULT_HISTORY_CAP = 200          # bounded decision log kept for observability / GUI

STATE_FILE = ".claude/ralph-loop.local.md"  # legacy v1 driver state (module kept as the gate library)
GATE_STATE_FILE = ".claude/loop_gate_state.json"
HUMAN_GATE_FILE = ".claude/HUMAN_REVIEW_REQUIRED.md"

# halt reasons that warrant surfacing to a human (vs. a clean, expected stop)
HUMAN_GATE_DECISIONS = {"halt:max_iterations", "halt:time_budget",
                        "halt:stuck_counter", "halt:no_progress"}


# --- loop-state frontmatter --------------------------------------------------

def _coerce(value: str) -> Any:
    v = value.strip().strip('"').strip("'")
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if v.lstrip("-").isdigit():
        return int(v)
    return v


def parse_loop_state(path: str | Path) -> dict[str, Any]:
    """Parse the live loop-state frontmatter. The file may contain more than one
    `---` block (doc frontmatter + live state); we pick the block carrying the
    live keys (`iteration` + `max_iterations`), falling back to a merge of all
    blocks so callers still get something usable."""
    p = Path(path)
    if not p.exists():
        return {}
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            if current is None:
                current = {}
            else:
                blocks.append(current)
                current = None
            continue
        if current is None:
            continue
        if ":" in line and not line.lstrip().startswith("#"):
            key, _, val = line.partition(":")
            key = key.strip()
            if key and " " not in key:
                current[key] = _coerce(val)
    if current:
        blocks.append(current)
    for b in blocks:
        if "iteration" in b and "max_iterations" in b:
            return b
    merged: dict[str, Any] = {}
    for b in blocks:
        merged.update(b)
    return merged


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- progress signal from the ledgers ---------------------------------------

def progress_signal(repo_root: str | Path | None) -> dict[str, int]:
    """Aggregate verified progress across every paper under repo_root.

    `pass_rows` is retained as activity telemetry for the dashboard, not as a
    progress-gate input.
    """
    root = Path(repo_root) if repo_root else Path.cwd()
    solid = admitted = discharged = pass_rows = total_trials = 0
    max_iter = -1

    for paper, _ in lc.iter_paper_dirs(root, "knowledge"):
        nodes = lc.read_jsonl(root, "knowledge", paper, "nodes.jsonl")
        for r in lc.latest_per_node(nodes):
            if r.get("status") == "solid":
                solid += 1

    for paper, _ in lc.iter_paper_dirs(root, "error"):
        trials = lc.read_jsonl(root, "error", paper, "trials.jsonl")
        total_trials += len(trials)
        for r in trials:
            if r.get("pass_fail") == "pass":
                pass_rows += 1
        mi = lc.max_iteration(trials)
        if mi is not None and mi > max_iter:
            max_iter = mi

    if True:
        for paper, _ in lc.iter_paper_dirs(root, "result"):
            results = rdb.latest_per_result(lc.read_jsonl(root, "result", paper, "results.jsonl"))
            for r in results:
                # Gate progress = VERIFIED forward motion only. `refuted` and
                # `conjectural` stay report-visible (rdb.PROGRESS_STATUSES) but
                # must not keep a stalling loop alive.
                if r.get("status") in rdb.GATE_PROGRESS_STATUSES:
                    admitted += 1
                    if not (r.get("open_obligations") or []):
                        discharged += 1
                it = r.get("iteration")
                if isinstance(it, int) and it > max_iter:
                    max_iter = it

    return {"solid_nodes": solid, "pass_rows": pass_rows,
            "admitted_results": admitted,
            "discharged_results": discharged,
            "total_trials": total_trials,
            "max_ledger_iteration": max_iter if max_iter >= 0 else None}


# --- the gate decision (pure) ------------------------------------------------

def _budgets(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "active": state.get("active", True),
        "iteration": int(state.get("iteration", 0) or 0),
        "max_iterations": int(state.get("max_iterations", DEFAULT_MAX_ITERATIONS) or DEFAULT_MAX_ITERATIONS),
        "no_progress_limit": int(state.get("no_progress_limit", DEFAULT_NO_PROGRESS_LIMIT) or DEFAULT_NO_PROGRESS_LIMIT),
        "stuck_limit": int(state.get("stuck_counter_limit", DEFAULT_STUCK_COUNTER_LIMIT) or DEFAULT_STUCK_COUNTER_LIMIT),
        "max_wall_seconds": int(state.get("max_wall_seconds", 0) or 0),
    }


def advance_streaks(state: dict[str, Any], signal: dict[str, int],
                    gate_state: dict[str, Any]) -> tuple[int, int]:
    """Advance (no_progress, stuck) from the iteration transition since the last
    check. Pure; does not evaluate the ladder."""
    iteration = _budgets(state)["iteration"]
    progress = (signal["solid_nodes"], signal["admitted_results"], signal["discharged_results"])
    raw_last = gate_state.get("last_progress")
    last_progress = tuple(raw_last) if isinstance(raw_last, list) and len(raw_last) == len(progress) \
        else tuple([-1] * len(progress))
    last_iteration = gate_state.get("last_iteration")
    no_progress_streak = int(gate_state.get("no_progress_streak", 0) or 0)
    stuck_streak = int(gate_state.get("stuck_streak", 0) or 0)
    if last_iteration is None or iteration < last_iteration:
        return 0, 0                                    # baseline / counter reset
    if iteration > last_iteration:                     # a genuine new iteration
        # COMPONENT-WISE: any counter increasing is progress. A lexicographic
        # tuple compare would score (solid -1, admitted +5) as a stall.
        advanced = any(p > l for p, l in zip(progress, last_progress))
        return (0 if advanced else no_progress_streak + 1), 0
    return no_progress_streak, stuck_streak + 1         # fired without advancing


def evaluate(state: dict[str, Any], signal: dict[str, int],
             no_progress_streak: int, stuck_streak: int, *, now: datetime) -> dict[str, Any]:
    """Run the decision ladder against the given streak values. Read-only: the
    Stop hook passes freshly-advanced streaks; the dashboard passes the persisted
    streaks for a consistent live snapshot."""
    b = _budgets(state)
    iteration, max_iterations = b["iteration"], b["max_iterations"]
    no_progress_limit, stuck_limit = b["no_progress_limit"], b["stuck_limit"]

    def verdict(decision: str, reason: str) -> dict[str, Any]:
        return {"decision": decision, "reason": reason,
                "iteration": iteration, "max_iterations": max_iterations,
                "no_progress_streak": no_progress_streak, "no_progress_limit": no_progress_limit,
                "stuck_streak": stuck_streak, "stuck_counter_limit": stuck_limit,
                "signal": signal}

    if b["active"] is False:
        return verdict("halt:inactive", "loop state has active=false; stopping as directed")
    if iteration >= max_iterations:
        return verdict("halt:max_iterations",
                       f"iteration {iteration} reached max_iterations {max_iterations}")
    if b["max_wall_seconds"] > 0:
        started = _parse_ts(state.get("started_at"))
        if started is None:
            # A wall-clock budget with an unparseable started_at would be
            # silently disabled — surface it instead of skipping.
            print(f"loop_gate: WARNING max_wall_seconds={b['max_wall_seconds']} set but "
                  f"started_at={state.get('started_at')!r} is unparseable; time budget NOT enforced",
                  file=sys.stderr)
        elif (now - started).total_seconds() >= b["max_wall_seconds"]:
            elapsed = int((now - started).total_seconds())
            return verdict("halt:time_budget",
                           f"wall clock {elapsed}s exceeded max_wall_seconds {b['max_wall_seconds']}")
    if stuck_streak >= stuck_limit:
        return verdict("halt:stuck_counter",
                       f"iteration counter stuck at {iteration} for {stuck_streak} stop-hook "
                       f"fires (limit {stuck_limit}); the loop is not advancing")
    if no_progress_streak >= no_progress_limit:
        return verdict("halt:no_progress",
                       f"no new solid node, admitted result, or discharged result for "
                       f"{no_progress_streak} iterations (limit {no_progress_limit}); "
                       "loop is spinning without verified progress")
    return verdict("continue",
                   f"iteration {iteration}/{max_iterations}; "
                   f"progress solid={signal['solid_nodes']} "
                   f"results={signal['admitted_results']} "
                   f"discharged={signal['discharged_results']}; "
                   f"no_progress {no_progress_streak}/{no_progress_limit}, "
                   f"stuck {stuck_streak}/{stuck_limit}")


def decide(state: dict[str, Any], signal: dict[str, int],
           gate_state: dict[str, Any], *, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """Advance the streaks, evaluate the ladder, and return (decision,
    new_gate_state). The mutating path the Stop hook uses."""
    no_progress_streak, stuck_streak = advance_streaks(state, signal, gate_state)
    d = evaluate(state, signal, no_progress_streak, stuck_streak, now=now)
    iteration = _budgets(state)["iteration"]
    new_gate_state = dict(gate_state)
    new_gate_state.update({
        "last_progress": [signal["solid_nodes"], signal["admitted_results"],
                          signal["discharged_results"]],
        "last_iteration": iteration,
        "no_progress_streak": no_progress_streak,
        "stuck_streak": stuck_streak,
        "signal": signal,
    })
    history = list(gate_state.get("history") or [])
    history.append({
        "ts": now.isoformat(timespec="seconds"),
        "iteration": iteration,
        "decision": d["decision"],
        "solid_nodes": signal["solid_nodes"],
        "admitted_results": signal["admitted_results"],
        "discharged_results": signal["discharged_results"],
        "pass_rows": signal["pass_rows"],
        "no_progress_streak": no_progress_streak,
        "stuck_streak": stuck_streak,
    })
    new_gate_state["history"] = history[-DEFAULT_HISTORY_CAP:]
    new_gate_state["last_decision"] = d["decision"]
    return d, new_gate_state


# --- human gate --------------------------------------------------------------

def human_gate_text(decision: dict[str, Any], signal: dict[str, int]) -> str:
    d = decision["decision"]
    advice = {
        "halt:no_progress": (
            "The loop produced no new solid node, admitted/classified result, or discharged "
            f"result for {decision['no_progress_streak']} iterations. Pass rows alone are "
            "activity, not verified progress. This is the parameter-tweak / stall circuit "
            "breaker (alignment.md §0). Before resuming: pick a structurally "
            "different approach (`python _common/loop_policy.py check-pivot ...`), run "
            "`pipelines/0-acquire/spec.md` to acquire missing sources, or make a human "
            "scope/scientific decision."),
        "halt:stuck_counter": (
            f"The iteration counter sat at {decision['iteration']} across "
            f"{decision['stuck_streak']} stop-hook fires — the loop is not advancing the "
            "counter in `.claude/ralph-loop.local.md`. Check the loop driver / VERIFY step."),
        "halt:time_budget": (
            "The wall-clock budget (`max_wall_seconds`) was exhausted. Review what consumed "
            "the time and either raise the budget or narrow the remaining work."),
        "halt:max_iterations": (
            f"The loop hit max_iterations ({decision['max_iterations']}) without asserting "
            "completion. Review the accepted-results log and decide whether to raise the cap, "
            "re-scope, or accept partial results."),
    }.get(d, "The loop halted and needs human review.")
    return (
        "# HUMAN REVIEW REQUIRED\n\n"
        f"The Ralph loop progress gate halted the loop: **{d}**.\n\n"
        f"> {decision['reason']}\n\n"
        "## Diagnosis\n\n"
        f"- iteration: {decision['iteration']} / {decision['max_iterations']}\n"
        f"- no-progress streak: {decision['no_progress_streak']} / {decision['no_progress_limit']}\n"
        f"- stuck-counter streak: {decision['stuck_streak']} / {decision['stuck_counter_limit']}\n"
        f"- progress signal: solid_nodes={signal['solid_nodes']}, "
        f"admitted_results={signal['admitted_results']}, "
        f"discharged_results={signal['discharged_results']}, "
        f"pass_rows(activity)={signal['pass_rows']}, total_trials={signal['total_trials']}\n\n"
        "## What to do\n\n"
        f"{advice}\n\n"
        "When resolved, delete this file and set `active: true` (and clear the streak with "
        "`python _common/loop_gate.py reset`) to resume, or set `active: false` to stop.\n")


# --- IO + CLI ----------------------------------------------------------------

def _load_gate_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_gate_state(path: Path, state: dict[str, Any]) -> None:
    # Atomic: a crash mid-write must not truncate the file (a corrupt state
    # file silently zeroes the streaks on the next load).
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _resolve(repo_root: str | Path | None, rel: str, override: str | Path | None) -> Path:
    if override:
        return Path(override)
    root = Path(repo_root) if repo_root else Path.cwd()
    return root / rel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="loop_gate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("decide", "status"):
        sp = sub.add_parser(name, help="evaluate the gate" + ("" if name == "decide" else " (read-only)"))
        sp.add_argument("--repo-root", type=Path, default=None)
        sp.add_argument("--state-file", type=Path, default=None,
                        help=f"loop state frontmatter (default: <repo>/{STATE_FILE})")
        sp.add_argument("--gate-state", type=Path, default=None,
                        help=f"gate streak-state json (default: <repo>/{GATE_STATE_FILE})")
        if name == "decide":
            sp.add_argument("--write-gate", action="store_true",
                            help=f"write <repo>/{HUMAN_GATE_FILE} on a circuit-breaker halt")
            sp.add_argument("--gate-file", type=Path, default=None)

    rs = sub.add_parser("reset", help="clear the gate streak-state")
    rs.add_argument("--repo-root", type=Path, default=None)
    rs.add_argument("--gate-state", type=Path, default=None)

    args = ap.parse_args(argv)

    if args.cmd == "reset":
        gate_state_path = _resolve(args.repo_root, GATE_STATE_FILE, args.gate_state)
        if gate_state_path.exists():
            gate_state_path.unlink()
        print(json.dumps({"reset": True, "gate_state": str(gate_state_path)}))
        return 0

    state_path = _resolve(args.repo_root, STATE_FILE, args.state_file)
    gate_state_path = _resolve(args.repo_root, GATE_STATE_FILE, args.gate_state)
    state = parse_loop_state(state_path)
    signal = progress_signal(args.repo_root)
    gate_state = _load_gate_state(gate_state_path)
    now = datetime.now(timezone.utc)

    decision, new_gate_state = decide(state, signal, gate_state, now=now)

    if args.cmd == "decide":
        _save_gate_state(gate_state_path, new_gate_state)
        if getattr(args, "write_gate", False) and decision["decision"] in HUMAN_GATE_DECISIONS:
            gate_file = _resolve(args.repo_root, HUMAN_GATE_FILE, getattr(args, "gate_file", None))
            gate_file.parent.mkdir(parents=True, exist_ok=True)
            gate_file.write_text(human_gate_text(decision, signal), encoding="utf-8")
            decision["human_gate_written"] = str(gate_file)
        print(json.dumps(decision, indent=2))
        return 0 if decision["decision"] == "continue" else 1

    # status: read-only, do not persist
    print(json.dumps({
        "decision": decision,
        "gate_state": {k: v for k, v in new_gate_state.items() if k != "history"},
        "state_file": str(state_path),
        "loop_active": state.get("active"),
    }, indent=2))
    return 0 if decision["decision"] == "continue" else 1


if __name__ == "__main__":
    raise SystemExit(main())
