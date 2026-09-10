/** Mission memory regressions against real ledger CLIs and disposable git repos. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { test, type TestContext } from "node:test";
import { fileURLToPath } from "node:url";
import { DEFAULT_BUDGETS } from "../src/gate.js";
import { generationLog } from "../src/jobs.js";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import { runMissionLoop, type MissionLoopDeps } from "../src/main.js";
import { TruncatingObserver, waveHistory } from "../src/observer.js";
import { runtimeDir } from "../src/runtime.js";

const P = "memory";
const WORK = "/tmp/chandra/work/memory-preservation";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function toyRepo(t: TestContext) {
  fs.mkdirSync(WORK, { recursive: true });
  const scratch = fs.mkdtempSync(path.join(WORK, "mission-"));
  const repo = path.join(scratch, "repo");
  fs.mkdirSync(repo);
  const previousRuntime = process.env.CHANDRA_RUNTIME;
  process.env.CHANDRA_RUNTIME = path.join(scratch, "runtime");
  t.after(() => {
    if (previousRuntime === undefined) delete process.env.CHANDRA_RUNTIME;
    else process.env.CHANDRA_RUNTIME = previousRuntime;
    fs.rmSync(scratch, { recursive: true, force: true });
  });
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(repo, "_common"));
  fs.mkdirSync(path.join(repo, ".claude", "skills"), { recursive: true });
  for (const rel of ["alignment.md", "pipelines/2-work/spec.md"]) {
    const dest = path.join(repo, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(path.join(REPO_ROOT, rel), dest);
  }
  fs.writeFileSync(path.join(repo, ".delegation-policy"), "strict\n");
  for (const args of [["init", "-q"], ["config", "user.email", "fixture@test"],
    ["config", "user.name", "fixture"], ["add", "-A"],
    ["commit", "-q", "-m", "chore(fixture): seed memory repo"]]) {
    execFileSync("git", ["-C", repo, ...args]);
  }
  return {
    repo, ledgers: new Ledgers(repo, "worker"),
    journal: new Journal(path.join(runtimeDir(repo, `paper_${P}`), "journal.jsonl")),
    missionDir: path.join(repo, "progress", "orchestrator", `paper_${P}`),
  };
}

async function seed(repo: string, status: "solid" | "hypothesis" = "hypothesis", predecessors: string[] = []) {
  fs.writeFileSync(path.join(repo, "evidence.txt"), "fixture evidence\n");
  await new Ledgers(repo, "worker").appendKnowledge({
    paper: P, node_id: `${P}::n1`, task_id: "memory-node", domain: "software", status,
    summary: "memory fixture", predecessors, evidence: "evidence.txt",
  });
  const rendered = generationLog(repo, P);
  fs.mkdirSync(path.dirname(rendered), { recursive: true });
  fs.writeFileSync(rendered, "final render exists\n");
}

function run(repo: string, overrides: Partial<MissionLoopDeps> = {}) {
  return runMissionLoop({
    repoRoot: repo, paper: P, maxWorkers: 1, maxWaves: 1, digestThreshold: 100,
    runner: { name: "noop", async runWorker() { return { detail: "no progress", windowsUsed: 1 }; } },
    observerRunner: new TruncatingObserver(),
    probes: { async refreshDue() { return false; } }, log: () => {}, ...overrides,
  });
}

interface RunStarted { type: "run_started"; runId: string; startedAt: string; resumedFromWave: number }
function starts(journal: Journal): RunStarted[] {
  return journal.read().map(e => e.msg).filter(m => String(m.type) === "run_started") as unknown as RunStarted[];
}

function assertFinal(journal: Journal, expected: { ok: boolean; breaks: number; unreadable: number }) {
  const events = journal.ofType("digest_emitted") as { final?: boolean; path: string }[];
  assert.equal(events.length, 1, "terminal exit emits exactly one digest below the routine threshold");
  assert.equal(events[0].final, true);
  const text = fs.readFileSync(events[0].path, "utf-8");
  assert.match(text, /Final update/);
  assert.ok(text.includes(`Preflight: ok=${expected.ok}; breaks=${expected.breaks}; unreadable=${expected.unreadable}`));
  assert.ok(text.includes(starts(journal)[0].runId), "digest must identify the run");
  assert.ok(text.includes(`\`${journal.filePath}\``) && fs.existsSync(journal.filePath));
  const messages = journal.read().map(e => e.msg.type);
  assert.ok(messages.lastIndexOf("preflight") < messages.lastIndexOf("digest_emitted"));
  return text;
}

test("memory: resume continues wave numbers, run history and the gate streak with maxWaves per run", async t => {
  const { repo, journal, missionDir } = toyRepo(t);
  await seed(repo);
  const previous = DEFAULT_BUDGETS.noProgressLimit;
  DEFAULT_BUDGETS.noProgressLimit = 1;
  t.after(() => { DEFAULT_BUDGETS.noProgressLimit = previous; });
  assert.equal(await run(repo), 2);
  assert.equal(await run(repo), 4, "the carried no-progress streak must halt the second invocation");
  const runs = starts(journal);
  assert.equal(runs.length, 2);
  assert.deepEqual(runs.map(r => r.resumedFromWave), [0, 1]);
  assert.notEqual(runs[0].runId, runs[1].runId);
  assert.ok(runs.every(r => Number.isFinite(Date.parse(r.startedAt))));
  assert.deepEqual(journal.ofType("wave_finished").map(w => w.wave), [1, 2]);
  const history = waveHistory(journal) as { runId?: string; wave: number }[];
  assert.deepEqual(history.map(w => [w.runId, w.wave]), [[runs[0].runId, 1], [runs[1].runId, 2]]);
  assert.deepEqual(journal.ofType("gate_decision").map(g => g.noProgressStreak), [0, 1]);
  const nodal = fs.readFileSync(path.join(missionDir, "nodal_note.md"), "utf-8");
  assert.ok(runs.every(r => nodal.includes(r.runId)));
});

test("memory review: a legacy wave-number reset cannot erase the last gate streak", async t => {
  const { repo, journal } = toyRepo(t);
  await seed(repo);
  journal.append({ type: "mission_loaded", paper: P, nodes: 1, solid: 0 });
  journal.append({ type: "wave_finished", wave: 9, admitted: 0, rejected: 0, failed: 0, noProgress: 1 });
  journal.append({ type: "gate_decision", wave: 9, decision: "halt:no_progress", noProgressStreak: 8 });
  // An older runtime restarted at wave 1, then stopped before the gate pass.
  journal.append({ type: "mission_loaded", paper: P, nodes: 1, solid: 0 });
  journal.append({ type: "wave_finished", wave: 1, admitted: 0, rejected: 0, failed: 0, noProgress: 1 });
  assert.equal(await run(repo), 4, "legacy numbering must not bypass the restored breaker");
  assert.equal(starts(journal).at(-1)!.resumedFromWave, 1);
  assert.equal(journal.ofType("wave_finished").at(-1)!.wave, 2);
  assert.equal(journal.ofType("gate_decision").at(-1)!.noProgressStreak, 9);
});

for (const terminal of ["mission_complete", "gate_halt", "no_ready_jobs", "pause", "max_waves", "zero_waves"] as const) {
  test(`memory: ${terminal} emits a final digest after terminal preflight`, async t => {
    const { repo, journal, missionDir } = toyRepo(t);
    await seed(repo, terminal === "mission_complete" ? "solid" : "hypothesis",
      terminal === "no_ready_jobs" ? [`${P}::missing`] : []);
    if (terminal === "pause") {
      fs.mkdirSync(missionDir, { recursive: true });
      fs.writeFileSync(path.join(missionDir, "PAUSE"), "pause\n");
    }
    if (terminal === "gate_halt") {
      const previous = DEFAULT_BUDGETS.noProgressLimit;
      DEFAULT_BUDGETS.noProgressLimit = 0;
      t.after(() => { DEFAULT_BUDGETS.noProgressLimit = previous; });
    }
    const expectedCode = { mission_complete: 0, gate_halt: 4, no_ready_jobs: 3, pause: 7, max_waves: 2, zero_waves: 2 }[terminal];
    assert.equal(await run(repo, { maxWaves: terminal === "zero_waves" ? 0 : 1 }), expectedCode);
    const text = assertFinal(journal, { ok: true, breaks: 0, unreadable: 0 });
    assert.match(text, /nodes: 1 known/);
  });
}

for (const failure of ["breaks", "unreadable"] as const) {
  test(`memory: integrity halt (${failure}) finalizes without claiming healthy ledger state`, async t => {
    const { repo, journal } = toyRepo(t);
    await seed(repo);
    const code = await run(repo, {
      digestThreshold: 1,
      runner: { name: "corrupt", async runWorker() {
        if (failure === "breaks") {
          const file = path.join(repo, "results", "ledgers", "knowledge", `paper_${P}`, "nodes.jsonl");
          const row = JSON.parse(fs.readFileSync(file, "utf-8"));
          row.summary = "tampered without rehashing";
          fs.writeFileSync(file, JSON.stringify(row) + "\n");
        } else {
          const dir = path.join(repo, "results", "ledgers", "claim", `paper_${P}`);
          fs.mkdirSync(dir, { recursive: true });
          fs.writeFileSync(path.join(dir, "entries.jsonl"), '{"entry_id":');
        }
        return { detail: "corrupt fixture", windowsUsed: 1 };
      } },
    });
    assert.equal(code, failure === "breaks" ? 8 : 9);
    const preflight = journal.ofType("preflight").at(-1)!;
    const text = assertFinal(journal, { ok: false, breaks: preflight.breaks, unreadable: preflight.unreadable.length });
    assert.match(text, /Mission state unavailable/);
    assert.ok(!text.includes("nodes: 1 known"));
    assert.match(journal.ofType("halt").at(-1)!.reason, /ledger_(tampered|unreadable)/);
  });
}
