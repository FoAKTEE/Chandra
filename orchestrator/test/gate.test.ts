/** The ported circuit breaker: component-wise progress, verified-only
 * statuses, streak arithmetic, and the decision ladder. */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEFAULT_BUDGETS, GATE_PROGRESS_STATUSES, advanceGate, decideGate,
  type GateSignal, type GateState,
} from "../src/gate.js";

const sig = (solid = 0, admitted = 0, discharged = 0): GateSignal =>
  ({ solidNodes: solid, admittedResults: admitted, dischargedObligations: discharged });

test("progress is component-wise: a demotion plus admissions is NOT a stall", () => {
  const prev: GateState = { lastWave: 1, lastProgress: [1, 0, 0], noProgressStreak: 3 };
  // solid dropped 1->0, admitted rose 0->5 (old lexicographic compare stalled here)
  const next = advanceGate(prev, 2, sig(0, 5, 0));
  assert.equal(next.noProgressStreak, 0);
});

test("no counter increased -> streak increments", () => {
  const prev: GateState = { lastWave: 1, lastProgress: [2, 3, 1], noProgressStreak: 2 };
  const next = advanceGate(prev, 2, sig(2, 3, 1));
  assert.equal(next.noProgressStreak, 3);
});

test("first observation is a baseline, not a stall", () => {
  const next = advanceGate(null, 1, sig(0, 0, 0));
  assert.equal(next.noProgressStreak, 0);
});

test("verified-only statuses feed the gate", () => {
  for (const s of ["checked", "conditional", "approximate", "empirical", "existence_only"]) {
    assert.ok(GATE_PROGRESS_STATUSES.has(s), s);
  }
  for (const s of ["refuted", "conjectural", "unchecked"]) {
    assert.ok(!GATE_PROGRESS_STATUSES.has(s), `${s} must not reset the breaker`);
  }
});

test("decision ladder: no_progress halts at the limit; time budget beats it", () => {
  const stalled: GateState = { lastWave: 9, lastProgress: [0, 0, 0], noProgressStreak: 8 };
  assert.equal(decideGate(stalled, DEFAULT_BUDGETS).decision, "halt:no_progress");
  const ok: GateState = { ...stalled, noProgressStreak: 2 };
  assert.equal(decideGate(ok, DEFAULT_BUDGETS).decision, "continue");
  const timed = decideGate(ok, {
    noProgressLimit: 8, maxWallSeconds: 60,
    startedAt: new Date(Date.now() - 120_000).toISOString(),
  });
  assert.equal(timed.decision, "halt:time_budget");
});

test("unparseable startedAt disables the time budget loudly, not silently", () => {
  const state: GateState = { lastWave: 1, lastProgress: [0, 0, 0], noProgressStreak: 0 };
  const d = decideGate(state, { noProgressLimit: 8, maxWallSeconds: 60, startedAt: "{UNFILLED}" });
  assert.equal(d.decision, "continue"); // budget skipped but run continues, warning emitted
});
