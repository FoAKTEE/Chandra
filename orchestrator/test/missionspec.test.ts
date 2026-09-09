/** Mission spine + human control channel: mission.json defaults, PAUSE halts
 * between waves, STEER.md reaches worker prompts. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { CodexJobRunner, CodexWorkerRunner, NoopWorkerRunner, SdkJobRunner, SdkWorkerRunner, workerPrompt } from "../src/agents.js";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import { buildRunners, runMissionLoop } from "../src/main.js";
import { loadMissionSpec, parseModelSpec, readHumanSignals } from "../src/missionspec.js";
import { SdkObserverRunner, TruncatingObserver } from "../src/observer.js";
import type { MissionNode } from "../src/types.js";
import { buildValidatorRunner, CodexValidatorRunner, SdkValidatorRunner } from "../src/validator.js";

const P = "arxiv-5555.55555";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

for (const [model, expected] of [
  [undefined, { runner: "sdk", model: undefined }],
  ["claude-x", { runner: "sdk", model: "claude-x" }],
  ["codex:gpt-6-astra", { runner: "codex", model: "gpt-6-astra" }],
] as const) {
  test(`parseModelSpec selects the runner for ${model}`, () => {
    assert.deepEqual(parseModelSpec(model), expected);
  });
}

test("parseModelSpec rejects an empty codex model", () => {
  assert.throws(() => parseModelSpec("codex:"), /must specify a model/);
  assert.throws(() => parseModelSpec("codex:  "), /must specify a model/);
});

test("buildRunners selects worker and jobs independently and keeps the observer on SDK", () => {
  const selected = buildRunners({ paper: P, models: { worker: "codex:x", jobs: "codex:y" } }, false);
  assert.ok(selected.runner instanceof CodexWorkerRunner);
  assert.ok(selected.observerRunner instanceof SdkObserverRunner);
  for (const kind of ["decompose", "acquire", "write-refresh"] as const) {
    assert.ok(selected.jobRunners?.[kind] instanceof CodexJobRunner);
  }
  const workerOnly = buildRunners({ paper: P, models: { worker: "codex:x" } }, false);
  assert.ok(workerOnly.runner instanceof CodexWorkerRunner);
  assert.ok(workerOnly.jobRunners?.decompose instanceof SdkJobRunner);
  const jobsOnly = buildRunners({ paper: P, models: { jobs: "codex:x" } }, false);
  assert.ok(jobsOnly.runner instanceof SdkWorkerRunner);
  assert.ok(jobsOnly.jobRunners?.decompose instanceof CodexJobRunner);
});

test("buildRunners preserves SDK defaults and dry-run runner selection", () => {
  for (const spec of [null, { paper: P }]) {
    const selected = buildRunners(spec, false);
    assert.ok(selected.runner instanceof SdkWorkerRunner);
    assert.ok(selected.observerRunner instanceof SdkObserverRunner);
    for (const job of Object.values(selected.jobRunners!)) assert.ok(job instanceof SdkJobRunner);
  }
  const dry = buildRunners({ paper: P, models: { worker: "codex:x", jobs: "codex:x" } }, true);
  assert.ok(dry.runner instanceof NoopWorkerRunner);
  assert.ok(dry.observerRunner instanceof TruncatingObserver);
  assert.equal(dry.jobRunners, undefined);
});

test("validator factory selects SDK, Codex, or mixed per-role runners without spawning", () => {
  assert.ok(buildValidatorRunner(null) instanceof SdkValidatorRunner);
  assert.ok(buildValidatorRunner({ paper: P, models: { refuter: "codex:x", judge: "codex:y" } })
    instanceof CodexValidatorRunner);
  assert.equal(buildValidatorRunner({ paper: P, models: { refuter: "codex:x" } }).name, "mixed-validator");
  assert.equal(buildValidatorRunner({ paper: P, models: { judge: "codex:y" } }).name, "mixed-validator");
});

test("mission.json preserves codex models and CLI options", t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-codex-spec-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const spec = { paper: P, models: { worker: "codex:gpt-6-astra", refuter: "codex:gpt-6-astra" },
    codex: { effort: "max", sandbox: "danger-full-access", bin: "/tmp/custom-codex", timeoutSeconds: 90 } };
  fs.writeFileSync(path.join(dir, "mission.json"), JSON.stringify(spec));
  assert.deepEqual(loadMissionSpec(dir), spec);
});

test("mission.json loads and validates; absent file -> null", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-spec-"));
  assert.equal(loadMissionSpec(dir), null);
  fs.writeFileSync(path.join(dir, "mission.json"),
    JSON.stringify({ paper: P, maxWorkers: 2, models: { refuter: "other-model" } }));
  const spec = loadMissionSpec(dir)!;
  assert.equal(spec.paper, P);
  assert.equal(spec.models?.refuter, "other-model");
  fs.writeFileSync(path.join(dir, "mission.json"), JSON.stringify({ maxWorkers: 2 }));
  assert.throws(() => loadMissionSpec(dir), /must set "paper"/);
});

test("STEER.md text is injected into the worker prompt", () => {
  const node: MissionNode = { id: "n1", paper: P, status: "hypothesis", summary: "n1",
                              predecessors: [], openObligations: [], depth: 0 };
  const prompt = workerPrompt({ wave: 1, node, packet: [node], paper: P,
                                repoRoot: "/x", steer: "prioritize the boundary-term check" });
  assert.match(prompt, /HUMAN STEER NOTE/);
  assert.match(prompt, /prioritize the boundary-term check/);
  const bare = workerPrompt({ wave: 1, node, packet: [node], paper: P, repoRoot: "/x" });
  assert.ok(!bare.includes("HUMAN STEER NOTE"));
});

test("PAUSE halts the mission between waves, resumable by deleting the file", async () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-pause-"));
  process.env.CHANDRA_RUNTIME = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-prt-"));
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(repo, "_common"));
  for (const args of [["init", "-q"], ["config", "user.email", "p@t"], ["config", "user.name", "p"],
                      ["add", "-A"], ["commit", "-q", "-m", "chore(fixture): seed"]]) {
    execFileSync("git", ["-C", repo, ...args]);
  }
  const ledgers = new Ledgers(repo, "human-override");
  await ledgers.appendKnowledge({ paper: P, node_id: "n1", task_id: "t", domain: "symbolic",
                                  status: "hypothesis", summary: "n1" });
  const missionDir = path.join(repo, "progress", "orchestrator", `paper_${P}`);
  fs.mkdirSync(missionDir, { recursive: true });
  fs.writeFileSync(path.join(missionDir, "PAUSE"), "");
  assert.equal(readHumanSignals(missionDir).paused, true);

  const code = await runMissionLoop({
    repoRoot: repo, paper: P, maxWorkers: 1, maxWaves: 3,
    runner: { name: "never", async runWorker() { throw new Error("must not run while paused"); } },
    observerRunner: new TruncatingObserver(),
    probes: { async refreshDue() { return false; } },
    log: () => {},
  });
  assert.equal(code, 7);
  const journal = new Journal(path.join(process.env.CHANDRA_RUNTIME!, `paper_${P}`, "journal.jsonl"));
  const halt = journal.ofType("halt");
  assert.match(halt[0].reason, /human_pause/);
});
