/** CLI entry: `plan` prints the ready frontier; `run` executes waves until the
 * mission completes or the gate halts. Light self-prompting: the orchestrator
 * holds only the journal tail + frontier — worker transcripts never enter it. */
import * as path from "node:path";
import { NoopWorkerRunner, SdkJobRunner, SdkWorkerRunner } from "./agents.js";
import { buildMission, missionComplete, readyFrontier } from "./dag.js";
import { DEFAULT_JOB_BUDGETS, cliProbes, readyJobs, runJobs,
         type JobBudgets, type JobKind, type JobRunner, type ReadinessProbes } from "./jobs.js";
import { maybeEmitDigest } from "./digest.js";
import { DEFAULT_BUDGETS, advanceGate, decideGate, gateSignal, type GateState } from "./gate.js";
import { commitGateInstalled, commitWave, isGitRepo } from "./gitops.js";
import { Journal } from "./journal.js";
import { Ledgers } from "./ledger.js";
import { loadMissionSpec, readHumanSignals } from "./missionspec.js";
import { SdkObserverRunner, TruncatingObserver, notesLayout, runObserver, waveHistory } from "./observer.js";
import { runtimeDir } from "./runtime.js";
import { runWave, tallyReports } from "./scheduler.js";

interface Args {
  cmd: string;
  repoRoot: string;
  paper: string;
  maxWorkers: number;
  maxWaves: number;
  dryRun: boolean;
}

function parseArgs(argv: string[]): Args {
  const [cmd = "plan"] = argv;
  const get = (flag: string, dflt?: string): string | undefined => {
    const i = argv.indexOf(flag);
    return i >= 0 ? argv[i + 1] : dflt;
  };
  const repoRoot = path.resolve(get("--repo-root", process.cwd())!);
  const spec = loadMissionSpec(repoRoot);      // mission.json = committed defaults
  const paper = get("--paper") ?? spec?.paper;
  if (!paper) throw new Error("--paper is required (or set it in mission.json)");
  return {
    cmd, repoRoot, paper,
    maxWorkers: Number(get("--max-workers", String(spec?.maxWorkers ?? 4))),
    maxWaves: Number(get("--max-waves", String(spec?.maxWaves ?? 100))),
    dryRun: argv.includes("--dry-run"),
  };
}

export async function main(argv: string[]): Promise<number> {
  const args = parseArgs(argv);
  const ledgers = new Ledgers(args.repoRoot);
  const mission = buildMission(args.paper,
    await ledgers.knowledge(args.paper), await ledgers.claims(args.paper));

  if (args.cmd === "plan") {
    const ready = readyFrontier(mission);
    process.stdout.write(JSON.stringify({
      paper: args.paper,
      nodes: mission.size,
      solid: [...mission.values()].filter(n => n.status === "solid").length,
      complete: missionComplete(mission),
      readyFrontier: ready.map(n => ({ id: n.id, depth: n.depth, obligations: n.openObligations.length })),
      parallelism: Math.min(ready.length, args.maxWorkers),
    }, null, 2) + "\n");
    return 0;
  }

  if (args.cmd !== "run") throw new Error(`unknown command ${args.cmd}`);

  const spec = loadMissionSpec(args.repoRoot);
  return runMissionLoop({
    repoRoot: args.repoRoot, paper: args.paper,
    maxWorkers: args.maxWorkers, maxWaves: args.maxWaves,
    packetSize: spec?.packetSize,
    digestThreshold: spec?.digestThreshold,
    runner: args.dryRun ? new NoopWorkerRunner()
      : new SdkWorkerRunner({ model: spec?.models?.worker }),
    observerRunner: args.dryRun ? new TruncatingObserver()
      : new SdkObserverRunner({ model: spec?.models?.observer }),
    jobRunners: args.dryRun ? undefined : {
      decompose: new SdkJobRunner({ model: spec?.models?.jobs }),
      acquire: new SdkJobRunner({ model: spec?.models?.jobs }),
      "write-refresh": new SdkJobRunner({ model: spec?.models?.jobs }),
    },
    dryRun: args.dryRun,
  });
}

export interface MissionLoopDeps {
  repoRoot: string;
  paper: string;
  maxWorkers: number;
  maxWaves: number;
  runner: import("./scheduler.js").WorkerRunner;
  observerRunner: import("./observer.js").ObserverRunner;
  dryRun?: boolean;
  digestThreshold?: number;
  /** initial packet size (adaptive: doubles when packets finish in one
   * window, halves when they need >3) */
  packetSize?: number;
  /** runners for the non-packet job kinds (default: SDK job runner) */
  jobRunners?: Partial<Record<Exclude<JobKind, "work-packet">, JobRunner>>;
  probes?: ReadinessProbes;
  jobBudgets?: JobBudgets;
  log?: (line: string) => void;
}

/** The wave loop, dependency-injected so fixtures can run it headless. */
export async function runMissionLoop(deps: MissionLoopDeps): Promise<number> {
  const { repoRoot, paper, maxWorkers, maxWaves, runner, observerRunner } = deps;
  const log = deps.log ?? ((line: string) => process.stdout.write(line + "\n"));
  // substage-commit enforcement: a mission runs in a git repo, or not at all
  if (!isGitRepo(repoRoot)) {
    throw new Error(`substage-commit enforcement: ${repoRoot} is not a git repo — ` +
                    `git init + bash _common/hooks/install.sh first`);
  }
  if (!commitGateInstalled(repoRoot)) {
    log("WARNING: commit-msg gate not installed (bash _common/hooks/install.sh) — wave commits will be un-gated");
  }
  const ledgers = new Ledgers(repoRoot);
  // committed deliverables (three notes + digest) live under progress/;
  // the journal is an operational diary and lives OUTSIDE the repo.
  const missionDir = path.join(repoRoot, "progress", "orchestrator", `paper_${paper}`);
  const journal = new Journal(path.join(
    runtimeDir(repoRoot, `paper_${paper}`), "journal.jsonl"));
  const layout = notesLayout(repoRoot, path.join("orchestrator", `paper_${paper}`));
  let gateState: GateState | null = null;
  let packetSize = deps.packetSize ?? 4;

  const initial = buildMission(paper, await ledgers.knowledge(paper), await ledgers.claims(paper));
  journal.append({
    type: "mission_loaded", paper, nodes: initial.size,
    solid: [...initial.values()].filter(n => n.status === "solid").length,
  });

  const probes = deps.probes ?? cliProbes(repoRoot);
  const jobRunners = {
    decompose: deps.jobRunners?.decompose ?? new SdkJobRunner(),
    acquire: deps.jobRunners?.acquire ?? new SdkJobRunner(),
    "write-refresh": deps.jobRunners?.["write-refresh"] ?? new SdkJobRunner(),
  };

  for (let wave = 1; wave <= maxWaves; wave++) {
    // human control channel: PAUSE halts gracefully; STEER.md reaches prompts
    const signals = readHumanSignals(missionDir);
    if (signals.paused) {
      journal.append({ type: "halt", reason: "human_pause (delete progress/.../PAUSE to resume)", wave });
      log("halt: human pause");
      return 7;
    }
    const current = buildMission(paper,
      await ledgers.knowledge(paper), await ledgers.claims(paper));
    const complete = missionComplete(current);
    const jobs = await readyJobs({
      repoRoot, paper, mission: current, ledgers, probes, packetSize,
      budgets: { ...(deps.jobBudgets ?? DEFAULT_JOB_BUDGETS), workPackets: maxWorkers },
      missionComplete: complete, wave,
    });
    if (jobs.length === 0) {
      if (complete) {
        journal.append({ type: "halt", reason: "mission_complete", wave });
        log("mission complete");
        return 0;
      }
      journal.append({ type: "halt", reason: "no_ready_jobs (cycle, missing predecessors, or nothing to do)", wave });
      log("halt: no ready jobs");
      return 3;
    }
    const packets = jobs.filter(j => j.kind === "work-packet").map(j => j.packet!);
    const others = jobs.filter(j => j.kind !== "work-packet");
    const ready = readyFrontier(current);
    const plan: import("./scheduler.js").WavePlan = {
      wave, ready: ready.map(n => n.id), scheduled: packets.flat(), packets,
    };
    journal.append({ type: "wave_planned", wave, ready: jobs.map(j => j.id), scheduled: plan.scheduled.map(n => n.id) });

    const [packetResult, jobReports] = await Promise.all([
      runWave(plan, { ledgers, journal, runner, paper, repoRoot, journalWaveFinished: false, steer: signals.steer ?? undefined }),
      runJobs(others, { repoRoot, paper, wave, ledgers, journal, runners: jobRunners }),
    ]);
    const result = tallyReports([...packetResult.reports, ...jobReports]);
    journal.append({
      type: "wave_finished", wave,
      admitted: result.admitted, rejected: result.rejected,
      failed: result.failed, noProgress: result.noProgress,
    });
    log(`wave ${wave}: packets=${plan.packets.length} jobs=${others.map(j => j.kind).join(",") || "-"} admitted=${result.admitted} promoted=${reportsPromoted(result)} rejected=${result.rejected} failed=${result.failed} no_progress=${result.noProgress}`);
    // adaptive work quantum: grow when packets finish within one window,
    // shrink when they burn many (telemetry we already collect)
    const packetWindows = result.reports.filter(r => r.windowsUsed > 0).map(r => r.windowsUsed);
    const maxWindows = Math.max(0, ...packetWindows);
    if (maxWindows > 3) packetSize = Math.max(1, Math.floor(packetSize / 2));
    else if (maxWindows <= 1 && result.failed === 0) packetSize = Math.min(8, packetSize * 2);

    // observer memory pass (three-note cadence + 10KB cap)
    await runObserver({
      layout, plan, result, history: waveHistory(journal),
      journal, runner: observerRunner, paper,
    });
    // circuit breaker (component-wise progress; verified statuses only)
    gateState = advanceGate(gateState, wave, await gateSignal(ledgers, paper));
    const decision = decideGate(gateState, DEFAULT_BUDGETS);
    journal.append({ type: "gate_decision", wave, decision: decision.decision, noProgressStreak: gateState.noProgressStreak });
    if (decision.decision !== "continue") {
      journal.append({ type: "halt", reason: decision.reason, wave });
      log(`halt: ${decision.reason}`);
      return 4;
    }
    // human digest only after N completed context windows (default 5)
    await maybeEmitDigest({ journal, ledgers, paper, missionDir, wave, threshold: deps.digestThreshold });
    // tamper-evidence: a broken ledger hash chain halts the mission COLD
    const chains = await ledgers.verifyChains();
    if (!chains.ok) {
      const reason = `ledger_tampered: ${JSON.stringify(chains.breaks).slice(0, 300)}`;
      journal.append({ type: "halt", reason, wave });
      log(`halt: ${reason}`);
      return 8;
    }
    // substage-commit enforcement: zone-1 changes are committed EVERY wave;
    // a rejected commit halts the mission rather than piling up dirty state.
    try {
      const wc = commitWave(repoRoot, paper, wave,
        `admitted=${result.admitted} rejected=${result.rejected} failed=${result.failed} no_progress=${result.noProgress}`);
      if (wc.committed) journal.append({ type: "wave_committed", wave, sha: wc.sha! });
    } catch (e) {
      journal.append({ type: "halt", reason: (e as Error).message, wave });
      log(`halt: ${(e as Error).message}`);
      return 6;
    }
    if (deps.dryRun) return 0; // one planning wave is enough in dry-run mode
  }
  return 2;
}

function reportsPromoted(r: { reports: { outcome: string }[] }): number {
  return r.reports.filter(x => x.outcome === "promoted").length;
}

const isDirectRun = process.argv[1] && import.meta.url.endsWith(path.basename(process.argv[1]));
if (isDirectRun) {
  main(process.argv.slice(2)).then(
    code => process.exit(code),
    err => { console.error(err.message); process.exit(1); });
}
