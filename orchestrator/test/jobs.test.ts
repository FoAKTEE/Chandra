/** Job-type unification: readiness computed from ledgers/filesystem, outcomes
 * measured by diffs, and the full lifecycle (decompose -> work -> terminal
 * write -> halt) driven by ONE scheduler. Real Python ledgers underneath. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { buildMission } from "../src/dag.js";
import { generationLog, readyJobs, type Job, type JobRunner } from "../src/jobs.js";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import { runMissionLoop } from "../src/main.js";
import { TruncatingObserver } from "../src/observer.js";
import type { WorkerRunner } from "../src/scheduler.js";
import type { WorkerTask } from "../src/types.js";

const P = "arxiv-7777.77777";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function jobsRepo(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-jobs-"));
  process.env.CHANDRA_RUNTIME = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-jrt-"));
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(dir, "_common"));
  fs.mkdirSync(path.join(dir, "ref-paper", P), { recursive: true });
  fs.writeFileSync(path.join(dir, "ref-paper", P, "main.tex"), "\\begin{document}toy\\end{document}");
  for (const args of [["init", "-q"], ["config", "user.email", "j@t"], ["config", "user.name", "j"],
                      ["add", "-A"], ["commit", "-q", "-m", "chore(fixture): seed"]]) {
    execFileSync("git", ["-C", dir, ...args]);
  }
  return dir;
}

const noRefresh = { async refreshDue() { return false; } };

test("readiness: empty mission + source mirror -> exactly one decompose job", async () => {
  const repo = jobsRepo();
  const jobs = await readyJobs({
    repoRoot: repo, paper: P, mission: buildMission(P, [], []),
    ledgers: new Ledgers(repo), probes: noRefresh, packetSize: 4,
    missionComplete: false, wave: 1,
  });
  assert.deepEqual(jobs.map(j => j.kind), ["decompose"]);
});

test("readiness: acquire job appears for an open obligation owned by 0-acquire", async () => {
  const repo = jobsRepo();
  const ledgers = new Ledgers(repo, "human-override");
  await ledgers.appendKnowledge({ paper: P, node_id: "n1", task_id: "t", domain: "symbolic",
                                  status: "hypothesis", summary: "n1" });
  await ledgers.appendClaimEntry({ paper: P, entry_id: "need-src", kind: "obligation",
                                   status: "open", statement: "missing external theorem",
                                   owner: "0-acquire", node_ids: ["n1"] });
  const know = await ledgers.knowledge(P);
  const jobs = await readyJobs({
    repoRoot: repo, paper: P, mission: buildMission(P, know, await ledgers.claims(P)),
    ledgers: new Ledgers(repo), probes: noRefresh, packetSize: 4,
    missionComplete: false, wave: 1,
  });
  assert.deepEqual(jobs.map(j => j.kind).sort(), ["acquire", "work-packet"]);
});

test("full lifecycle under one scheduler: decompose -> work -> terminal write -> halt", async () => {
  const repo = jobsRepo();
  const worker = new Ledgers(repo, "worker");

  // stub DECOMPOSE: reads the mirror, appends a 2-node chain through the gate
  const decompose: JobRunner = {
    name: "stub-decompose",
    async run(_job: Job) {
      for (const [id, preds] of [["d1", []], ["d2", ["d1"]]] as const) {
        await worker.appendKnowledge({ paper: P, node_id: id, task_id: `t-${id}`,
          domain: "symbolic", status: "hypothesis", summary: `node ${id}`, predecessors: preds });
      }
      return { detail: "decomposed 2 nodes", windowsUsed: 1 };
    },
  };
  // stub WORK: promotes every leased node to solid with real evidence
  const work: WorkerRunner = {
    name: "stub-work",
    async runWorker(task: WorkerTask) {
      for (const n of task.packet) {
        const rel = path.join("artifacts", `${n.id}.txt`);
        fs.mkdirSync(path.join(repo, "artifacts"), { recursive: true });
        fs.writeFileSync(path.join(repo, rel), `residual 1e-9 PASS for ${n.id}\n`);
        await worker.appendKnowledge({ paper: P, node_id: n.id, task_id: `t-${n.id}`,
          domain: "symbolic", status: "solid", summary: `node ${n.id}`,
          evidence: rel, predecessors: n.predecessors });
      }
      return { detail: "chain done", windowsUsed: 1 };
    },
  };
  // stub WRITE: renders the terminal paper log
  const write: JobRunner = {
    name: "stub-write",
    async run() {
      const log = generationLog(repo, P);
      fs.mkdirSync(path.dirname(log), { recursive: true });
      fs.appendFileSync(log, `${new Date().toISOString()} iter=final 2 solid nodes\n`);
      return { detail: "rendered", windowsUsed: 1 };
    },
  };

  const lines: string[] = [];
  const code = await runMissionLoop({
    repoRoot: repo, paper: P, maxWorkers: 2, maxWaves: 8,
    runner: work, observerRunner: new TruncatingObserver(),
    jobRunners: { decompose, "write-refresh": write },
    probes: noRefresh,
    log: l => lines.push(l),
  });
  assert.equal(code, 0, `exit ${code}; log:\n${lines.join("\n")}`);

  const journal = new Journal(path.join(process.env.CHANDRA_RUNTIME!, `paper_${P}`, "journal.jsonl"));
  const assigned = journal.ofType("task_assigned").map(m => m.node);
  assert.ok(assigned.some(id => id.startsWith("decompose:")), "decompose job ran");
  assert.ok(assigned.some(id => id.startsWith("packet:")), "work packets ran");
  assert.ok(assigned.some(id => id.startsWith("write:")), "terminal write ran");
  const done = journal.ofType("worker_done");
  assert.ok(done.some(m => m.report.node.startsWith("decompose:") && m.report.outcome === "admitted"),
    "decompose outcome measured from the ledger diff");
  assert.ok(done.some(m => m.report.node.startsWith("write:") && m.report.outcome === "admitted"),
    "write outcome measured from GENERATION_LOG appearing");
  const halt = journal.ofType("halt");
  assert.equal(halt[halt.length - 1].reason, "mission_complete");
  assert.ok(fs.existsSync(generationLog(repo, P)), "terminal render exists");
});
