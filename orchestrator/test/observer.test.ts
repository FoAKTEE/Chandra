/** Observer memory contracts, mechanically enforced: iteration note = current
 * wave only; nodal note = last 10 waves; research state hard-capped at 2KB. */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { Journal } from "../src/journal.js";
import {
  NODAL_WINDOW, RESEARCH_STATE_CAP_BYTES, TruncatingObserver, notesLayout,
  runObserver, waveHistory, writeIterationNote, writeNodalNote,
  type ObserverRunner, type WaveSummary,
} from "../src/observer.js";
import type { WavePlan, WaveResult } from "../src/scheduler.js";
import type { MissionNode } from "../src/types.js";

const P = "arxiv-0000.00000";

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
  assert.match(text, /pruned by observer — full text in git history/);
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
