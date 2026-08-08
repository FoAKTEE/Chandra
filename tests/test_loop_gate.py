"""loop_gate — the progress-aware circuit breaker.

The decision ladder and streak arithmetic are pure functions, so these are exact
table tests: every halt reason, the priority order between them, the streak
transitions, and the `main()` exit-code contract (0=continue, 1=halt) with its
gate-state file IO. progress_signal is checked against real seeded ledgers.
"""
from __future__ import annotations

from datetime import datetime, timezone

from _common.ledgers import knowledge_database as kdb
from _common.ledgers import result_database as rdb
from _common.loop import loop_gate as lg
from factories import valid_knowledge_row, valid_result_row, write_evidence

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
PAPER = "arxiv-0000.00000"


def sig(solid=0, admitted=0, discharged=0, pass_rows=0, total=0, max_iter=None):
    return {"solid_nodes": solid, "admitted_results": admitted,
            "discharged_results": discharged, "pass_rows": pass_rows,
            "total_trials": total, "max_ledger_iteration": max_iter}


def state(**over):
    s = {"active": True, "iteration": 5, "max_iterations": 1000,
         "no_progress_limit": 8, "stuck_counter_limit": 3, "max_wall_seconds": 0}
    s.update(over)
    return s


# --- decision ladder (evaluate is pure) --------------------------------------

def test_inactive_short_circuits_even_over_max():
    d = lg.evaluate(state(active=False, iteration=9999), sig(), 99, 99, now=NOW)
    assert d["decision"] == "halt:inactive"


def test_halt_max_iterations():
    d = lg.evaluate(state(iteration=1000, max_iterations=1000), sig(), 0, 0, now=NOW)
    assert d["decision"] == "halt:max_iterations"


def test_halt_time_budget():
    s = state(max_wall_seconds=10, started_at="2026-01-01T11:59:00+00:00")  # 60s before NOW
    d = lg.evaluate(s, sig(), 0, 0, now=NOW)
    assert d["decision"] == "halt:time_budget"


def test_halt_stuck_counter():
    d = lg.evaluate(state(), sig(), 0, 3, now=NOW)
    assert d["decision"] == "halt:stuck_counter"


def test_halt_no_progress():
    d = lg.evaluate(state(), sig(), 8, 0, now=NOW)
    assert d["decision"] == "halt:no_progress"


def test_continue_with_headroom():
    d = lg.evaluate(state(), sig(solid=1, admitted=1), 0, 0, now=NOW)
    assert d["decision"] == "continue"


def test_stuck_counter_beats_no_progress():
    # both breakers tripped; the earlier ladder rung (stuck) must win
    d = lg.evaluate(state(), sig(), 8, 3, now=NOW)
    assert d["decision"] == "halt:stuck_counter"


# --- streak transitions (advance_streaks is pure) ----------------------------

def test_streak_baseline_is_zero():
    assert lg.advance_streaks(state(iteration=5), sig(), {}) == (0, 0)


def test_streak_progress_resets_no_progress():
    gs = {"last_iteration": 4, "last_progress": [0, 0, 0],
          "no_progress_streak": 3, "stuck_streak": 0}
    assert lg.advance_streaks(state(iteration=5), sig(solid=1), gs) == (0, 0)


def test_streak_no_progress_increments():
    gs = {"last_iteration": 4, "last_progress": [0, 0, 0],
          "no_progress_streak": 3, "stuck_streak": 0}
    assert lg.advance_streaks(state(iteration=5), sig(), gs) == (4, 0)


def test_streak_stuck_increments_on_repeat_iteration():
    gs = {"last_iteration": 5, "last_progress": [0, 0, 0],
          "no_progress_streak": 2, "stuck_streak": 1}
    assert lg.advance_streaks(state(iteration=5), sig(), gs) == (2, 2)


def test_streak_counter_regression_resets():
    gs = {"last_iteration": 9, "last_progress": [0, 0, 0],
          "no_progress_streak": 2, "stuck_streak": 1}
    assert lg.advance_streaks(state(iteration=2), sig(), gs) == (0, 0)


def test_streak_progress_is_component_wise_not_lexicographic():
    # solid dropped 1->0 (a demotion) while admitted rose 0->5: genuine
    # progress. The old lexicographic tuple compare scored this as a stall.
    gs = {"last_iteration": 4, "last_progress": [1, 0, 0],
          "no_progress_streak": 3, "stuck_streak": 0}
    assert lg.advance_streaks(state(iteration=5), sig(solid=0, admitted=5), gs) == (0, 0)


# --- decide() = advance + evaluate + new gate state --------------------------

def test_decide_persists_streaks_and_history():
    d, ngs = lg.decide(state(iteration=5), sig(solid=1, admitted=1), {}, now=NOW)
    assert d["decision"] == "continue"
    assert ngs["last_iteration"] == 5
    assert ngs["last_progress"] == [1, 1, 0]
    assert ngs["last_decision"] == "continue"
    assert len(ngs["history"]) == 1


# --- progress_signal reads the live ledgers ----------------------------------

def test_progress_signal_counts_real_ledgers(tmp_path):
    ev = write_evidence(tmp_path)  # admission gate: checked/solid evidence must resolve
    rdb.append_row(valid_result_row(status="checked", open_obligations=[], evidence=ev),
                   repo_root=tmp_path)
    kdb.append_row(valid_knowledge_row(status="solid", evidence=ev), repo_root=tmp_path)
    s = lg.progress_signal(tmp_path)
    assert s["solid_nodes"] == 1
    assert s["admitted_results"] == 1
    assert s["discharged_results"] == 1


def test_refuted_and_conjectural_do_not_feed_the_gate(tmp_path):
    # Report-visible, but appending them must not reset the no-progress
    # breaker — otherwise refuting your own junk keeps the loop alive.
    write_evidence(tmp_path)
    rdb.append_row(valid_result_row(result_id="r-ref", status="refuted",
                                    open_obligations=[]), repo_root=tmp_path)
    rdb.append_row(valid_result_row(result_id="r-conj", status="conjectural",
                                    open_obligations=["prove it"]), repo_root=tmp_path)
    s = lg.progress_signal(tmp_path)
    assert s["admitted_results"] == 0
    assert s["discharged_results"] == 0


# --- main() exit-code contract + gate-state IO -------------------------------

def test_main_status_continue_on_empty_repo(tmp_path):
    assert lg.main(["status", "--repo-root", str(tmp_path)]) == 0


def test_main_decide_inactive_halts_and_writes_gate_state(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "ralph-loop.local.md").write_text(
        "---\nactive: false\niteration: 3\nmax_iterations: 1000\n---\n", encoding="utf-8")
    rc = lg.main(["decide", "--repo-root", str(tmp_path)])
    assert rc == 1  # any halt:* exits non-zero
    assert (claude / "loop_gate_state.json").exists()


def test_main_reset_clears_gate_state(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    gs = claude / "loop_gate_state.json"
    gs.write_text("{}", encoding="utf-8")
    assert lg.main(["reset", "--repo-root", str(tmp_path)]) == 0
    assert not gs.exists()
