/** Circuit breaker, ported from _common/loop/loop_gate.py with the two audit
 * bugs fixed at the source:
 *  - progress comparison is COMPONENT-WISE (any counter increased), not a
 *    lexicographic tuple compare;
 *  - only VERIFIED statuses feed the gate — refuted/conjectural/unchecked
 *    rows stay report-visible but cannot reset the no-progress breaker. */
import type { Ledgers } from "./ledger.js";

/** Mirrors result_database.GATE_PROGRESS_STATUSES. */
export const GATE_PROGRESS_STATUSES = new Set(
  ["checked", "conditional", "approximate", "empirical", "existence_only"]);

export interface GateSignal {
  solidNodes: number;
  admittedResults: number;
  dischargedObligations: number;
}

export interface GateState {
  lastWave: number;
  lastProgress: [number, number, number];
  noProgressStreak: number;
}

export interface GateBudgets {
  noProgressLimit: number;
  maxWallSeconds: number;
  startedAt?: string;
}

export const DEFAULT_BUDGETS: GateBudgets = { noProgressLimit: 8, maxWallSeconds: 0 };

export async function gateSignal(ledgers: Ledgers, paper: string): Promise<GateSignal> {
  const [know, results, claims] = await Promise.all([
    ledgers.knowledge(paper), ledgers.results(paper), ledgers.claims(paper)]);
  return {
    solidNodes: know.filter(r => r.status === "solid").length,
    admittedResults: results.filter(r => GATE_PROGRESS_STATUSES.has(String(r.status))).length,
    dischargedObligations: claims.filter(c => c.kind === "obligation" && c.status === "discharged").length,
  };
}

export function advanceGate(prev: GateState | null, wave: number,
                            signal: GateSignal): GateState {
  const progress: [number, number, number] =
    [signal.solidNodes, signal.admittedResults, signal.dischargedObligations];
  if (prev === null || wave <= prev.lastWave) {
    return { lastWave: wave, lastProgress: progress, noProgressStreak: 0 };
  }
  // component-wise: ANY counter increasing is progress
  const advanced = progress.some((p, i) => p > prev.lastProgress[i]);
  return {
    lastWave: wave,
    lastProgress: progress,
    noProgressStreak: advanced ? 0 : prev.noProgressStreak + 1,
  };
}

export type GateDecision =
  | { decision: "continue"; reason: string }
  | { decision: "halt:no_progress" | "halt:time_budget"; reason: string };

export function decideGate(state: GateState, budgets: GateBudgets,
                           now: Date = new Date()): GateDecision {
  if (budgets.maxWallSeconds > 0 && budgets.startedAt) {
    const started = Date.parse(budgets.startedAt);
    if (Number.isNaN(started)) {
      // surfaced, not silently skipped (python gate warns the same way)
      process.stderr.write(`gate: WARNING unparseable startedAt=${budgets.startedAt}; time budget NOT enforced\n`);
    } else if ((now.getTime() - started) / 1000 >= budgets.maxWallSeconds) {
      return { decision: "halt:time_budget", reason: `wall clock exceeded ${budgets.maxWallSeconds}s` };
    }
  }
  if (state.noProgressStreak >= budgets.noProgressLimit) {
    return {
      decision: "halt:no_progress",
      reason: `no new solid node, verified result, or discharged obligation for ` +
              `${state.noProgressStreak} waves (limit ${budgets.noProgressLimit})`,
    };
  }
  return { decision: "continue", reason: `no_progress ${state.noProgressStreak}/${budgets.noProgressLimit}` };
}
