/** Job-type unification (v3): the four stages are JOB KINDS under ONE
 * scheduler — the pipeline table is documentation of these kinds, not a
 * workflow a human walks. Readiness is computed from the ledgers:
 *
 *   decompose     — the paper has a source mirror but an empty mission DAG
 *   work-packet   — ready frontier chains (the stage-2 unit; see scheduler)
 *   acquire       — an open obligation owned by "0-acquire" (missing external
 *                   dependency / escalation)
 *   write-refresh — the living-paper cadence probe says a render is owed, or
 *                   the mission is complete and no final render exists yet
 *
 * Outcomes are measured per kind from ledger/filesystem diffs — never from
 * the job agent's own claims. */
import * as fs from "node:fs";
import * as path from "node:path";
import type { Journal } from "./journal.js";
import type { Ledgers } from "./ledger.js";
import type { Mission, MissionNode, WorkerReport } from "./types.js";
import type { ClaimRow } from "./types.js";
import { extractPackets } from "./scheduler.js";

export type JobKind = "work-packet" | "decompose" | "acquire" | "write-refresh";

export interface Job {
  kind: JobKind;
  id: string;
  packet?: MissionNode[];
  obligation?: ClaimRow;
}

export interface JobBudgets {
  workPackets: number;
  decompose: number;
  acquire: number;
  write: number;
}

export const DEFAULT_JOB_BUDGETS: JobBudgets = { workPackets: 4, decompose: 1, acquire: 1, write: 1 };

export interface JobContext {
  repoRoot: string;
  paper: string;
  wave: number;
}

/** Non-packet job executor (decompose / acquire / write). */
export interface JobRunner {
  readonly name: string;
  run(job: Job, ctx: JobContext): Promise<{ detail: string; windowsUsed: number }>;
}

export interface ReadinessProbes {
  /** is a living-paper render owed? default: loop_policy paper-refresh CLI */
  refreshDue(paper: string): Promise<boolean>;
}

export function sourceMirrorDir(repoRoot: string, paper: string): string {
  return path.join(repoRoot, "ref-paper", paper);
}

/** The paper's GENERATION_LOG under whichever project dir holds it; falls
 * back to the default `results/mission/...` home for first renders. */
export function generationLog(repoRoot: string, paper: string): string {
  const base = path.join(repoRoot, "results");
  if (fs.existsSync(base)) {
    for (const proj of fs.readdirSync(base)) {
      const p = path.join(base, proj, `paper_${paper}`, "paper", "GENERATION_LOG");
      if (fs.existsSync(p)) return p;
    }
  }
  return path.join(base, "mission", `paper_${paper}`, "paper", "GENERATION_LOG");
}

export async function readyJobs(deps: {
  repoRoot: string;
  paper: string;
  mission: Mission;
  ledgers: Ledgers;
  probes: ReadinessProbes;
  packetSize: number;
  budgets?: JobBudgets;
  missionComplete: boolean;
  wave: number;
}): Promise<Job[]> {
  const { repoRoot, paper, mission, ledgers, probes, packetSize } = deps;
  const budgets = deps.budgets ?? DEFAULT_JOB_BUDGETS;
  const jobs: Job[] = [];

  // decompose: mirror exists, mission DAG empty — nothing else can be ready
  if (mission.size === 0) {
    if (fs.existsSync(sourceMirrorDir(repoRoot, paper))) {
      jobs.push({ kind: "decompose", id: `decompose:${paper}` });
    }
    return jobs.slice(0, budgets.decompose);
  }

  // acquire: open obligations explicitly owned by stage 0
  const claims = await ledgers.claims(paper);
  const acquireObligations = claims.filter(c =>
    c.kind === "obligation" && c.status === "open" && c.owner === "0-acquire");
  for (const o of acquireObligations.slice(0, budgets.acquire)) {
    jobs.push({ kind: "acquire", id: `acquire:${o.entry_id}`, obligation: o });
  }

  // work packets: the stage-2 unit
  if (!deps.missionComplete) {
    for (const packet of extractPackets(mission, packetSize).slice(0, budgets.workPackets)) {
      jobs.push({ kind: "work-packet", id: `packet:${packet.map(n => n.id).join("+")}`, packet });
    }
  }

  // write-refresh: cadence render, or the terminal render on completion
  const terminalRenderMissing = deps.missionComplete && !fs.existsSync(generationLog(repoRoot, paper));
  if (terminalRenderMissing || await probes.refreshDue(paper)) {
    jobs.push({ kind: "write-refresh", id: `write:${paper}:w${deps.wave}` });
  }
  return jobs;
}

/** Kind-specific outcome measurement — ledger/filesystem diffs only. */
export async function measureJobOutcome(job: Job, deps: {
  repoRoot: string;
  paper: string;
  ledgers: Ledgers;
  missionSizeBefore: number;
  logExistedBefore: boolean;
}): Promise<WorkerReport["outcome"]> {
  const { repoRoot, paper, ledgers } = deps;
  if (job.kind === "decompose") {
    const know = await ledgers.knowledge(paper);
    return know.length > deps.missionSizeBefore ? "admitted" : "no_progress";
  }
  if (job.kind === "acquire") {
    const claims = await ledgers.claims(paper);
    const now = claims.find(c => c.entry_id === job.obligation?.entry_id);
    return now && now.status !== "open" ? "admitted" : "no_progress";
  }
  if (job.kind === "write-refresh") {
    const exists = fs.existsSync(generationLog(repoRoot, paper));
    return exists && !deps.logExistedBefore ? "admitted"
      : exists ? "promoted" : "no_progress";
  }
  return "no_progress"; // work-packet outcomes are measured per node by runWave
}

/** Default probes backed by the Python CLIs. */
export function cliProbes(repoRoot: string): ReadinessProbes {
  return {
    async refreshDue(paper: string): Promise<boolean> {
      const { execFile } = await import("node:child_process");
      const { promisify } = await import("node:util");
      try {
        const { stdout } = await promisify(execFile)("python3",
          [path.join(repoRoot, "_common/loop_policy.py"), "paper-refresh", "--paper", paper],
          { cwd: repoRoot });
        return Boolean(JSON.parse(stdout).due);
      } catch {
        return false;
      }
    },
  };
}

/** Run every non-packet job of a wave concurrently; outcomes journaled like
 * worker reports (node = job id). */
export async function runJobs(jobs: Job[], deps: {
  repoRoot: string;
  paper: string;
  wave: number;
  ledgers: Ledgers;
  journal: Journal;
  runners: Partial<Record<Exclude<JobKind, "work-packet">, JobRunner>>;
}): Promise<WorkerReport[]> {
  const { repoRoot, paper, wave, ledgers, journal } = deps;
  const missionSizeBefore = (await ledgers.knowledge(paper)).length;
  const logExistedBefore = fs.existsSync(generationLog(repoRoot, paper));
  return Promise.all(jobs.map(async (job): Promise<WorkerReport> => {
    const runner = deps.runners[job.kind as Exclude<JobKind, "work-packet">];
    journal.append({ type: "task_assigned", wave, node: job.id, runner: runner?.name ?? "none" });
    const startedAt = new Date().toISOString();
    let detail = "";
    let windowsUsed = 1;
    let outcome: WorkerReport["outcome"];
    if (!runner) {
      outcome = "failed";
      detail = `no runner configured for job kind ${job.kind}`;
    } else {
      try {
        const r = await runner.run(job, { repoRoot, paper, wave });
        detail = r.detail;
        windowsUsed = r.windowsUsed;
        outcome = await measureJobOutcome(job, { repoRoot, paper, ledgers, missionSizeBefore, logExistedBefore });
      } catch (e) {
        outcome = "failed";
        detail = `job crashed: ${(e as Error).message}`;
      }
    }
    const report: WorkerReport = {
      node: job.id, outcome, detail,
      startedAt, finishedAt: new Date().toISOString(), windowsUsed,
    };
    journal.append({ type: "worker_done", wave, report });
    return report;
  }));
}
