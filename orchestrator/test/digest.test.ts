/** Human digest cadence: routine updates only after 5 completed context
 * windows; the counter resets on emission. Ledger content via the real CLIs. */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { maybeEmitDigest, windowsSinceLastDigest } from "../src/digest.js";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import type { WorkerReport } from "../src/types.js";

const P = "arxiv-0000.00000";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function tmpRepo(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-digest-"));
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(dir, "_common"));
  return dir;
}

function report(node: string, windowsUsed: number): WorkerReport {
  return { node, outcome: "no_progress", detail: "", startedAt: "t", finishedAt: "t", windowsUsed };
}

function seedJournal(journal: Journal, wave: number, windows: number[]): void {
  journal.append({ type: "wave_planned", wave, ready: ["x"], scheduled: ["x"] });
  for (const w of windows) {
    journal.append({ type: "worker_done", wave, report: report("x", w) });
  }
  journal.append({ type: "wave_finished", wave, admitted: 0, rejected: 0, failed: 0, noProgress: windows.length });
}

test("windows accumulate across waves and reset at the last digest", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-digest-"));
  const journal = new Journal(path.join(dir, "j.jsonl"));
  seedJournal(journal, 1, [1, 1]);
  seedJournal(journal, 2, [2]);
  assert.equal(windowsSinceLastDigest(journal), 4);
  journal.append({ type: "digest_emitted", wave: 2, afterWindows: 4, path: "x" });
  assert.equal(windowsSinceLastDigest(journal), 0);
  seedJournal(journal, 3, [1]);
  assert.equal(windowsSinceLastDigest(journal), 1);
});

test("no digest below the 5-window threshold; digest emitted at/after it", async () => {
  const repo = tmpRepo();
  const ledgers = new Ledgers(repo);
  await ledgers.appendKnowledge({
    paper: P, node_id: "n1", task_id: "t1", domain: "symbolic",
    status: "hypothesis", summary: "toy",
  });
  const missionDir = path.join(repo, "progress", "m");
  const journal = new Journal(path.join(missionDir, "journal.jsonl"));

  seedJournal(journal, 1, [1, 1, 1]);        // 3 windows: below threshold
  const early = await maybeEmitDigest({ journal, ledgers, paper: P, missionDir, wave: 1 });
  assert.deepEqual({ emitted: early.emitted, windows: early.windows }, { emitted: false, windows: 3 });
  assert.ok(!fs.existsSync(path.join(missionDir, "HUMAN_DIGEST.md")));

  seedJournal(journal, 2, [1, 1]);           // now 5
  const due = await maybeEmitDigest({ journal, ledgers, paper: P, missionDir, wave: 2 });
  assert.equal(due.emitted, true);
  const text = fs.readFileSync(due.path!, "utf-8");
  assert.match(text, /Human digest — arxiv-0000.00000/);
  assert.match(text, /nodes: 1 known, 0 solid/);
  assert.match(text, /Recent waves/);
  // counter reset: immediately after emission nothing is owed
  assert.equal(windowsSinceLastDigest(journal), 0);
});
