/** Mission spine + human control channel: mission.json defaults, PAUSE halts
 * between waves, STEER.md reaches worker prompts. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { workerPrompt } from "../src/agents.js";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import { runMissionLoop } from "../src/main.js";
import { loadMissionSpec, readHumanSignals } from "../src/missionspec.js";
import { TruncatingObserver } from "../src/observer.js";
import type { MissionNode } from "../src/types.js";

const P = "arxiv-5555.55555";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

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
