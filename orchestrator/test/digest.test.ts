/** Human digest cadence: routine updates only after 5 completed context
 * windows; the counter resets on emission. Ledger content via the real CLIs. */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { composeDigest, maybeEmitDigest, windowsSinceLastDigest } from "../src/digest.js";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import type { Message, WorkerReport } from "../src/types.js";

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

function memoryDigest(t: import("node:test").TestContext) {
  const work = "/tmp/chandra/work/memory-preservation";
  fs.mkdirSync(work, { recursive: true });
  const repo = fs.mkdtempSync(path.join(work, "digest-"));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(repo, "_common"));
  const journal = new Journal(path.join(repo, "runtime", `paper_${P}`, "journal.jsonl"));
  journal.append({ type: "run_started", runId: "digest-run", startedAt: new Date().toISOString(), resumedFromWave: 0 } as unknown as Message);
  return { journal, ledgers: new Ledgers(repo), paper: P, missionDir: path.join(repo, "progress"), wave: 1 };
}

test("memory: digest names the actual journal path, current run and latest preflight", async t => {
  const deps = memoryDigest(t);
  deps.journal.append({ type: "preflight", wave: 0, ok: false, breaks: 2, unreadable: ["old failure"] });
  deps.journal.append({ type: "preflight", wave: 1, ok: true, breaks: 0, unreadable: [] });
  const text = await composeDigest(deps);
  assert.ok(text.includes(`\`${deps.journal.filePath}\``), "footer must name the existing runtime journal");
  assert.ok(fs.existsSync(deps.journal.filePath));
  assert.ok(text.includes("digest-run"));
  assert.match(text, /Preflight: ok=true; breaks=0; unreadable=0/);
  assert.ok(!text.includes("old failure"), "only the latest preflight describes this digest");
});

test("memory: final digest bypasses the window threshold and journals final=true", async t => {
  const deps = { ...memoryDigest(t), final: true };
  deps.journal.append({ type: "preflight", wave: 1, ok: true, breaks: 0, unreadable: [] });
  const emitted = await maybeEmitDigest(deps);
  assert.equal(emitted.emitted, true, "a zero-window terminal run still needs its final digest");
  const event = deps.journal.ofType("digest_emitted")[0] as { final?: boolean; afterWindows: number };
  assert.equal(event.final, true);
  assert.equal(event.afterWindows, 0);
  assert.match(fs.readFileSync(emitted.path!, "utf-8"), /Final update/);
});

for (const unreadable of [[], ["claims_database.py query: torn tail"]]) {
  test(`memory: failed preflight (${unreadable.length ? "unreadable" : "breaks"}) produces a diagnostic digest without querying bad ledgers`, async t => {
    const deps = memoryDigest(t);
    deps.journal.append({ type: "preflight", wave: 1, ok: false, breaks: 1, unreadable });
    deps.ledgers.knowledge = deps.ledgers.results = deps.ledgers.claims = async () => {
      assert.fail("an unhealthy preflight must suppress ledger-derived mission claims");
    };
    const text = await composeDigest(deps);
    assert.match(text, new RegExp(`Preflight: ok=false; breaks=1; unreadable=${unreadable.length}`));
    assert.match(text, /Mission state unavailable/);
    assert.ok(!text.includes("nodes: 0 known"));
    if (unreadable.length) assert.ok(text.includes(unreadable[0]));
  });
}
