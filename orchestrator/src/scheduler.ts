/** Wave scheduler. The parallelization rule is ENFORCED HERE, in code:
 * every ready node (up to maxWorkers) is launched in the same Promise.all —
 * there is no serial code path when the frontier has more than one node.
 * Worker outcomes are derived from LEDGER DIFFS, never from agent prose. */
import { missionComplete, readyFrontier } from "./dag.js";
import type { Journal } from "./journal.js";
import type { Ledgers } from "./ledger.js";
import type { Mission, MissionNode, WorkerReport, WorkerTask } from "./types.js";

export interface WorkerRunner {
  readonly name: string;
  /** Do the node's work (spawn an SDK session, run a stub, …). The runner's
   * return detail is advisory; the OUTCOME is computed from the ledger diff. */
  runWorker(task: WorkerTask): Promise<{ detail: string; windowsUsed: number }>;
}

export interface WavePlan {
  wave: number;
  ready: string[];
  /** flat view of every scheduled node (journal/back-compat) */
  scheduled: MissionNode[];
  /** the actual unit of assignment: one worker per PACKET (a chain worked
   * continuously in one session), not per node */
  packets: MissionNode[][];
}

export const DEFAULT_PACKET_SIZE = 4;

/** Lease packets: each frontier root extends along its UNAMBIGUOUS successor
 * chain — a candidate joins only when all its predecessors are solid or
 * already in the chain, and only when it is the unique such continuation
 * (branch points stay on the frontier for parallel waves). Interior packet
 * nodes are never re-planned; the reasoning stays warm across the chain. */
export function extractPackets(mission: Mission, packetSize: number): MissionNode[][] {
  const ready = readyFrontier(mission);
  const solid = new Set([...mission.values()].filter(n => n.status === "solid").map(n => n.id));
  const assigned = new Set<string>();
  const packets: MissionNode[][] = [];
  for (const root of ready) {
    if (assigned.has(root.id)) continue;
    const chain = [root];
    assigned.add(root.id);
    while (chain.length < Math.max(1, packetSize)) {
      const inChain = new Set(chain.map(n => n.id));
      const candidates = [...mission.values()].filter(n =>
        n.status !== "solid" && n.depth >= 0 && !assigned.has(n.id)
        && n.predecessors.length > 0
        && n.predecessors.some(p => inChain.has(p))
        && n.predecessors.every(p => solid.has(p) || inChain.has(p)))
        .sort((a, b) => a.id.localeCompare(b.id));
      if (candidates.length !== 1) break;   // none, or a branch point: stop the lease
      chain.push(candidates[0]);
      assigned.add(candidates[0].id);
    }
    packets.push(chain);
  }
  return packets;
}

export function planWave(wave: number, mission: Mission, maxWorkers: number,
                         packetSize: number = DEFAULT_PACKET_SIZE): WavePlan {
  const ready = readyFrontier(mission);
  const packets = extractPackets(mission, packetSize).slice(0, Math.max(1, maxWorkers));
  return {
    wave,
    ready: ready.map(n => n.id),
    scheduled: packets.flat(),
    packets,
  };
}

export interface WaveResult {
  reports: WorkerReport[];
  admitted: number;
  rejected: number;
  failed: number;
  noProgress: number;
  windowsUsed: number;
}

export async function runWave(plan: WavePlan, deps: {
  ledgers: Ledgers;
  journal: Journal;
  runner: WorkerRunner;
  paper: string;
  repoRoot: string;
  /** main appends a merged wave_finished when other job kinds ran too */
  journalWaveFinished?: boolean;
  /** human STEER.md text, injected into worker prompts */
  steer?: string;
}): Promise<WaveResult> {
  const { ledgers, journal, runner, paper, repoRoot } = deps;
  const before = await ledgers.snapshot(paper);

  // ONE Promise.all over the whole packet set — parallel by construction;
  // within a packet the worker runs the chain continuously in one session.
  const reports = (await Promise.all(plan.packets.map(async (packet): Promise<WorkerReport[]> => {
    journal.append({ type: "task_assigned", wave: plan.wave, node: `packet:${packet.map(n => n.id).join("+")}`, runner: runner.name });
    const startedAt = new Date().toISOString();
    let detail = "";
    let windowsUsed = 1;
    let crashed = false;
    try {
      const r = await runner.runWorker({ wave: plan.wave, node: packet[0], packet, paper, repoRoot, steer: deps.steer });
      detail = r.detail;
      windowsUsed = r.windowsUsed;
    } catch (e) {
      crashed = true;
      detail = `worker crashed: ${(e as Error).message}`;
    }
    const finishedAt = new Date().toISOString();
    // one report per node; windows accounted once, on the packet anchor
    return packet.map((node, i) => ({
      node: node.id, outcome: (crashed ? "failed" : "no_progress") as WorkerReport["outcome"],
      detail, startedAt, finishedAt, windowsUsed: i === 0 ? windowsUsed : 0,
    }));
  }))).flat();

  // Outcome = PER-NODE ledger diff, so parallel workers cannot claim each
  // other's progress.
  const after = await ledgers.snapshot(paper);
  for (const rep of reports) {
    if (rep.outcome !== "failed") {
      const was = before.statusByNode[rep.node];
      const now = after.statusByNode[rep.node];
      const newResults = (after.resultsByNode[rep.node] ?? 0) > (before.resultsByNode[rep.node] ?? 0);
      const newObligations = (after.openObligationsByNode[rep.node] ?? 0) > (before.openObligationsByNode[rep.node] ?? 0);
      if (was !== "solid" && now === "solid") rep.outcome = "admitted";
      else if (now !== was || newResults) rep.outcome = "promoted";
      else if (newObligations) rep.outcome = "rejected"; // validator filed a repair obligation
      else rep.outcome = "no_progress";
    }
    journal.append({ type: "worker_done", wave: plan.wave, report: rep });
  }

  const count = (o: string) => reports.filter(r => r.outcome === o).length;
  const result: WaveResult = {
    reports,
    admitted: count("admitted"),
    rejected: count("rejected"),
    failed: count("failed"),
    noProgress: count("no_progress"),
    windowsUsed: reports.reduce((s, r) => s + r.windowsUsed, 0),
  };
  if (deps.journalWaveFinished !== false) {
    journal.append({
      type: "wave_finished", wave: plan.wave,
      admitted: result.admitted, rejected: result.rejected,
      failed: result.failed, noProgress: result.noProgress,
    });
  }
  return result;
}

/** Aggregate a report list into wave totals (packets + other job kinds). */
export function tallyReports(reports: WorkerReport[]): WaveResult {
  const count = (o: string) => reports.filter(r => r.outcome === o).length;
  return {
    reports,
    admitted: count("admitted"),
    rejected: count("rejected"),
    failed: count("failed"),
    noProgress: count("no_progress"),
    windowsUsed: reports.reduce((s, r) => s + r.windowsUsed, 0),
  };
}

export { missionComplete };
