/** Observer memory contracts, mechanically enforced: iteration note = current
 * wave only; nodal note = last 10 waves; research state hard-capped at 2KB. */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import { runtimeDir } from "../src/runtime.js";
import {
  NODAL_WINDOW, RESEARCH_STATE_CAP_BYTES, TruncatingObserver, notesLayout,
  runObserver, waveHistory, writeIterationNote, writeNodalNote,
  type ObserverRunner, type WaveSummary,
} from "../src/observer.js";
import type { WavePlan, WaveResult } from "../src/scheduler.js";
import type { Message, MissionNode } from "../src/types.js";

const P = "arxiv-0000.00000";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const WORK = "/tmp/chandra/work/memory-preservation";

function node(id: string): MissionNode {
  return { id, paper: P, status: "hypothesis", summary: id, predecessors: [], openObligations: [], depth: 0 };
}

function plan(wave: number, ids: string[]): WavePlan {
  return { wave, ready: ids, scheduled: ids.map(node), packets: ids.map(id => [node(id)]) };
}

function result(ids: string[]): WaveResult {
  return {
    reports: ids.map(id => ({
      node: id, outcome: "admitted" as const, detail: "ok",
      startedAt: "t0", finishedAt: "t1", windowsUsed: 1,
    })),
    admitted: ids.length, rejected: 0, failed: 0, noProgress: 0, windowsUsed: ids.length,
  };
}

function tmpLayout() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-obs-"));
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(dir, "_common"));
  return { dir, layout: notesLayout(dir, `paper_${P}`) };
}

test("iteration note is a FULL REWRITE — holds exactly the current wave", () => {
  const { layout } = tmpLayout();
  writeIterationNote(layout, plan(1, ["a"]), result(["a"]));
  writeIterationNote(layout, plan(2, ["b"]), result(["b"]));
  const text = fs.readFileSync(layout.iterationNote, "utf-8");
  assert.match(text, /Current wave — 2/);
  assert.match(text, /- b: \*\*admitted\*\*/);
  assert.ok(!text.includes("wave — 1") && !text.includes("- a:"), "wave 1 must be gone");
});

test(`nodal note keeps only the last ${NODAL_WINDOW} waves`, () => {
  const { layout } = tmpLayout();
  const history: WaveSummary[] = Array.from({ length: 12 }, (_, i) => ({
    wave: i + 1, scheduled: ["x"], admitted: 1, rejected: 0, failed: 0, noProgress: 0,
  }));
  writeNodalNote(layout, history);
  const text = fs.readFileSync(layout.nodalNote, "utf-8");
  assert.match(text, /waves 3–12/);
  assert.match(text, /^\| 3 \|/m);
  assert.match(text, /^\| 12 \|/m);
  assert.ok(!/^\| 1 \|/m.test(text) && !/^\| 2 \|/m.test(text), "waves 1-2 must be pruned");
});

test("research state over the 10KB cap is pruned to <= cap and journaled; scaffold created when missing", async () => {
  const { dir, layout } = tmpLayout();
  const journal = new Journal(path.join(dir, "journal.jsonl"));
  // first run: no research state -> scaffold, under cap, no prune
  const first = await runObserver({
    layout, plan: plan(1, ["a"]), result: result(["a"]), history: [],
    journal, runner: new TruncatingObserver(), paper: P,
  });
  assert.equal(first.pruned, false);
  assert.ok(first.researchStateBytes <= RESEARCH_STATE_CAP_BYTES);

  // bloat it past the cap -> observer prunes mechanically
  fs.appendFileSync(layout.researchState,
    "\n## Bloat\n" + "detail line\n".repeat(Math.ceil(RESEARCH_STATE_CAP_BYTES / 12) + 200));
  const second = await runObserver({
    layout, plan: plan(2, ["b"]), result: result(["b"]), history: [],
    journal, runner: new TruncatingObserver(), paper: P,
  });
  assert.equal(second.pruned, true);
  assert.ok(second.researchStateBytes <= RESEARCH_STATE_CAP_BYTES,
    `still ${second.researchStateBytes} bytes`);
  const text = fs.readFileSync(layout.researchState, "utf-8");
  assert.match(text, /pruned by observer — full text archived at/);
  const archived = journal.read().map(e => e.msg).find(m => m.type === "note_archived");
  assert.ok(archived?.type === "note_archived" && text.includes(archived.path));
  const events = journal.ofType("memory_pruned");
  assert.equal(events.length, 2);
  assert.ok(events[1].researchStateBytes <= RESEARCH_STATE_CAP_BYTES);
});

test("a prune that still exceeds the cap is a hard error, not a warning", async () => {
  const { dir, layout } = tmpLayout();
  fs.mkdirSync(path.dirname(layout.researchState), { recursive: true });
  fs.writeFileSync(layout.researchState, "x".repeat(RESEARCH_STATE_CAP_BYTES * 2));
  const defiant: ObserverRunner = {
    name: "defiant",
    async pruneResearchState(content: string) { return content; }, // refuses to shrink
  };
  await assert.rejects(
    runObserver({
      layout, plan: plan(1, ["a"]), result: result(["a"]), history: [],
      journal: new Journal(path.join(dir, "journal.jsonl")), runner: defiant, paper: P,
    }),
    /observer prune failed/);
});

test("waveHistory reconstructs summaries from the journal", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-obs-"));
  const journal = new Journal(path.join(dir, "journal.jsonl"));
  journal.append({ type: "wave_planned", wave: 1, ready: ["a", "b"], scheduled: ["a", "b"] });
  journal.append({ type: "wave_finished", wave: 1, admitted: 1, rejected: 1, failed: 0, noProgress: 0 });
  const history = waveHistory(journal);
  assert.deepEqual(history, [{
    wave: 1, scheduled: ["a", "b"], admitted: 1, rejected: 1, failed: 0, noProgress: 0,
  }]);
});

function memoryFixture(t: import("node:test").TestContext) {
  fs.mkdirSync(WORK, { recursive: true });
  const dir = fs.mkdtempSync(path.join(WORK, "observer-"));
  const previous = process.env.CHANDRA_RUNTIME;
  process.env.CHANDRA_RUNTIME = path.join(dir, "runtime");
  t.after(() => {
    if (previous === undefined) delete process.env.CHANDRA_RUNTIME;
    else process.env.CHANDRA_RUNTIME = previous;
    fs.rmSync(dir, { recursive: true, force: true });
  });
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(dir, "_common"));
  const layout = notesLayout(dir, `paper_${P}`);
  fs.mkdirSync(path.dirname(layout.researchState), { recursive: true });
  const journal = new Journal(path.join(runtimeDir(dir, `paper_${P}`), "journal.jsonl"));
  const observe = (wave = 1, runner: ObserverRunner = new TruncatingObserver()) => runObserver({
    layout, plan: plan(wave, []), result: result([]), history: [], journal, runner, paper: P,
  });
  return { dir, layout, journal, observe };
}

interface ArchiveEvent { type: "note_archived"; wave: number; path: string; bytes: number }
function archives(journal: Journal): ArchiveEvent[] {
  return journal.read().map(e => e.msg).filter(m => String(m.type) === "note_archived") as unknown as ArchiveEvent[];
}

for (const largeBlock of [false, true]) {
  test(`memory: archive exact pre-prune bytes and ${largeBlock ? "replace an oversized block whole" : "prune prose before a generated block"}`, async t => {
    const { dir, layout, journal, observe } = memoryFixture(t);
    const command = `python _common/knowledge_database.py render-md --paper ${P}`;
    const block = `<!-- BEGIN GENERATED: node-view (${command}) -->\r\n` +
      "| derived fact |\r\n".repeat(largeBlock ? 1200 : 60) +
      "<!-- END GENERATED: node-view -->\r\n";
    const original = Buffer.from("# Research state\r\n## Mission\r\n" +
      "Uncommitted through-line: α → β\r\n".repeat(600) + block + "Never committed tail.\r\n");
    fs.writeFileSync(layout.researchState, original);
    const report = await observe();
    const text = fs.readFileSync(layout.researchState, "utf-8");
    if (largeBlock) {
      assert.ok(!text.includes("<!-- BEGIN GENERATED: node-view"));
      assert.ok(!text.includes("<!-- END GENERATED: node-view"));
      assert.ok(text.split("\n").some(line => line.startsWith("> ") && line.includes(command)),
        "the whole block must be replaced by its render-command pointer");
    } else {
      assert.ok(text.includes(block), "generated bytes must survive while prose can be pruned");
    }
    const saved = archives(journal);
    assert.equal(saved.length, 1, "archive must be journaled");
    assert.equal(saved[0].wave, 1);
    assert.equal(saved[0].bytes, original.length);
    assert.equal(path.dirname(saved[0].path), path.join(runtimeDir(dir, `paper_${P}`), "notes"));
    assert.match(path.basename(saved[0].path), /^RESEARCH_STATE\.w1\..+\.md$/);
    assert.deepEqual(fs.readFileSync(saved[0].path), original, "archive is byte-exact, including UTF-8 and CRLF");
    assert.ok(text.includes(saved[0].path), "footer names the recoverable archive");
    assert.ok(!text.includes("in git history"));
    assert.ok(report.pruned && report.researchStateBytes <= RESEARCH_STATE_CAP_BYTES);
  });
}

test("memory: never-committed through-line survives even when pruning fails", async t => {
  const { dir, layout, journal, observe } = memoryFixture(t);
  const original = Buffer.from("working context\n".repeat(1200) + "NEVER-COMMITTED through-line: preserve this exact tail\n");
  fs.writeFileSync(layout.researchState, original);
  assert.ok(!fs.existsSync(path.join(dir, ".git")), "there is no git history to recover from");
  await assert.rejects(observe(3, { name: "defiant", async pruneResearchState(content) { return content; } }),
    /observer prune failed/);
  const saved = archives(journal);
  assert.equal(saved.length, 1, "archive must exist before even a failing prune");
  assert.deepEqual(fs.readFileSync(saved[0].path), original);
  assert.deepEqual(fs.readFileSync(layout.researchState), original, "failed pruning must not overwrite the note");
});

test("memory: observer refreshes the accepted-results block after a gated append", async t => {
  const { dir, layout, observe } = memoryFixture(t);
  await observe();
  const first = fs.readFileSync(layout.researchState, "utf-8");
  const ledgers = new Ledgers(dir, "worker");
  await ledgers.appendResult({
    paper: P, result_id: "fresh-memory-result", name: "refresh fixture", working_context: "toy",
    claim: "an explicitly unverified claim", evidence_type: "conjecture", evidence: "pending",
    verifier_result: { verdict: "classified" }, dependencies: [], assumptions: [],
    status: "conjectural", provenance: "memory fixture", open_obligations: [],
  });
  await observe(2);
  const text = fs.readFileSync(layout.researchState, "utf-8");
  assert.ok(text.includes("`fresh-memory-result`"), "new result_id must appear without a manual render");
  assert.ok(!first.includes("fresh-memory-result"));
  const begin = text.indexOf("<!-- BEGIN GENERATED: accepted-results");
  const end = text.indexOf("<!-- END GENERATED: accepted-results");
  assert.ok(begin > text.indexOf("## Mission") && end > begin && end < text.indexOf("## Open questions"));
  assert.equal(text.match(/<!-- BEGIN GENERATED: accepted-results/g)?.length, 1);
  for (const db of ["result", "knowledge", "claim", "error"]) {
    assert.ok(text.includes(`results/ledgers/${db}/paper_${P}/`), `canonical ${db} ledger pointer`);
  }
});

test("memory: repeated wave numbers retain each run's own plan and nodal run id", t => {
  const { layout, journal } = memoryFixture(t);
  for (const [runId, scheduled] of [["run-a", ["a"]], ["run-b", ["b", "c"]]] as const) {
    journal.append({ type: "run_started", runId, startedAt: new Date().toISOString(), resumedFromWave: 0 } as unknown as Message);
    journal.append({ type: "wave_planned", wave: 1, ready: [...scheduled], scheduled: [...scheduled] });
    journal.append({ type: "wave_finished", wave: 1, admitted: 0, rejected: 0, failed: 0, noProgress: 1 });
  }
  const history = waveHistory(journal) as (WaveSummary & { runId?: string })[];
  assert.deepEqual(history.map(w => [w.runId, w.wave, w.scheduled]),
    [["run-a", 1, ["a"]], ["run-b", 1, ["b", "c"]]]);
  writeNodalNote(layout, history);
  const text = fs.readFileSync(layout.nodalNote, "utf-8");
  assert.ok(text.includes("run-a") && text.includes("run-b"));
});

test("memory review: insert accepted results outside generated headings", async t => {
  const { layout, observe } = memoryFixture(t);
  const outer = `<!-- BEGIN GENERATED: result-log (python _common/result_database.py render-md --paper ${P}) -->\n` +
    "# Results\n## conjectural\n| Claim | Status |\n| existing | conjectural |\n<!-- END GENERATED: result-log -->\n";
  fs.writeFileSync(layout.researchState, "# Research state\n## Mission\nPreserve the existing view.\n" + outer + "\n## Next steps\nContinue.\n");
  await observe();
  const text = fs.readFileSync(layout.researchState, "utf-8");
  assert.ok(text.includes("<!-- BEGIN GENERATED: accepted-results"), "the accepted-results view must be inserted");
  assert.ok(text.includes(outer), "headings inside another generated block cannot receive an insertion");
  await observe(2);
});

async function appendMemoryResult(dir: string, resultId: string, claim: string) {
  await new Ledgers(dir, "worker").appendResult({
    paper: P, result_id: resultId, name: "review fixture", working_context: "toy", claim,
    evidence_type: "conjecture", evidence: "pending", verifier_result: { verdict: "classified" },
    dependencies: [], assumptions: [], status: "conjectural", provenance: "memory fixture", open_obligations: [],
  });
}

test("memory review: inline marker examples in results survive repeated refreshes", async t => {
  const { dir, layout, observe } = memoryFixture(t);
  await appendMemoryResult(dir, "inline-memory-result",
    "The `<!-- BEGIN GENERATED: example -->` and `<!-- END GENERATED: example -->` markers form a pair.");
  await observe();
  assert.ok(fs.readFileSync(layout.researchState, "utf-8").includes("`inline-memory-result`"));
  await observe(2);
  assert.ok(fs.readFileSync(layout.researchState, "utf-8").includes("`inline-memory-result`"));
});

test("memory review: accepted-results pointer at EOF refreshes without a trailing newline", async t => {
  const { dir, layout, observe } = memoryFixture(t);
  await appendMemoryResult(dir, "eof-memory-result", "Refresh this result.");
  fs.writeFileSync(layout.researchState, "# Research state\n## Mission\nPreserve the view.\n" +
    `> [generated: accepted-results paper_${P}; restore with \`python _common/result_database.py render-state --paper ${P}\`]`);
  await observe();
  const text = fs.readFileSync(layout.researchState, "utf-8");
  assert.ok(text.includes("`eof-memory-result`"));
  assert.ok(text.includes(`<!-- END GENERATED: accepted-results paper_${P} -->`));
});

test("memory review: an incomplete result ledger cannot refresh an apparently healthy note", async t => {
  const { dir, layout, observe } = memoryFixture(t);
  await appendMemoryResult(dir, "complete-memory-result", "One complete row before a torn write.");
  const original = "# Research state\n## Mission\nOriginal context must survive a failed read.\n";
  fs.writeFileSync(layout.researchState, original);
  fs.appendFileSync(path.join(dir, "results", "ledgers", "result", `paper_${P}`, "results.jsonl"), '{"result_id":');
  await assert.rejects(observe(), /incomplete ledger read/);
  assert.equal(fs.readFileSync(layout.researchState, "utf-8"), original);
});

test("memory review: prose rewrites without a newline cannot swallow a block boundary", async t => {
  const { layout, observe } = memoryFixture(t);
  const block = `<!-- BEGIN GENERATED: node-view (python _common/knowledge_database.py render-md --paper ${P}) -->\n` +
    "| preserved |\n<!-- END GENERATED: node-view -->\n";
  fs.writeFileSync(layout.researchState, "# Research state\n## Mission\n" + "context\n".repeat(2000) + block);
  await observe(1, { name: "newline-free", async pruneResearchState(_content, bytes) { return "saved".slice(0, bytes); } });
  const text = fs.readFileSync(layout.researchState, "utf-8");
  assert.ok(text.includes(block));
  assert.match(text, /^<!-- BEGIN GENERATED: node-view /m, "generated markers must stay on their own lines");
  await observe(2);
});
