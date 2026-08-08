import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { buildMission } from "../src/dag.js";
import { Journal } from "../src/journal.js";
import type { LedgerSnapshot } from "../src/ledger.js";
import { planWave, runWave, type WorkerRunner } from "../src/scheduler.js";
import type { KnowledgeRow, WorkerTask } from "../src/types.js";

const P = "arxiv-0000.00000";
const row = (node_id: string, status: KnowledgeRow["status"],
             predecessors: string[] = []): KnowledgeRow =>
  ({ paper: P, node_id, status, predecessors, summary: node_id });

function tmpJournal(): Journal {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-orch-"));
  return new Journal(path.join(dir, "journal.jsonl"));
}

/** Fake ledgers driven by mutable snapshots — lets a test script what the
 * ledger diff shows without touching Python. */
class FakeLedgers {
  constructor(public snapshots: LedgerSnapshot[]) {}
  async snapshot(): Promise<LedgerSnapshot> {
    return this.snapshots.length > 1 ? this.snapshots.shift()! : this.snapshots[0];
  }
}

const emptySnap = (): LedgerSnapshot =>
  ({ statusByNode: {}, resultsByNode: {}, openObligationsByNode: {} });

test("planWave schedules the whole frontier up to maxWorkers", () => {
  const mission = buildMission(P, [row("a", "hypothesis"), row("b", "hypothesis"),
                                   row("c", "hypothesis")], []);
  const plan = planWave(1, mission, 2);
  assert.deepEqual(plan.ready, ["a", "b", "c"]);
  assert.equal(plan.scheduled.length, 2);
});

test("runWave launches ALL scheduled workers concurrently (no serial path)", async () => {
  const mission = buildMission(P, [row("a", "hypothesis"), row("b", "hypothesis"),
                                   row("c", "hypothesis")], []);
  const plan = planWave(1, mission, 3);
  let inFlight = 0;
  let peak = 0;
  const runner: WorkerRunner = {
    name: "concurrency-probe",
    async runWorker(_task: WorkerTask) {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise(r => setTimeout(r, 20)); // hold the slot open
      inFlight -= 1;
      return { detail: "ok", windowsUsed: 1 };
    },
  };
  const result = await runWave(plan, {
    ledgers: new FakeLedgers([emptySnap()]) as never,
    journal: tmpJournal(), runner, paper: P, repoRoot: "/nonexistent",
  });
  assert.equal(peak, 3, `expected 3 overlapping workers, saw peak=${peak}`);
  assert.equal(result.reports.length, 3);
});

test("outcomes come from PER-NODE ledger diffs, not worker claims", async () => {
  const mission = buildMission(P, [row("a", "hypothesis"), row("b", "hypothesis"),
                                   row("c", "hypothesis"), row("d", "hypothesis")], []);
  const plan = planWave(1, mission, 4);
  const before = emptySnap();
  before.statusByNode = { a: "hypothesis", b: "hypothesis", c: "hypothesis", d: "hypothesis" };
  const after: LedgerSnapshot = {
    statusByNode: { a: "solid", b: "preliminary", c: "hypothesis", d: "hypothesis" },
    resultsByNode: {},
    openObligationsByNode: { d: 1 },        // validator filed a repair obligation on d
  };
  const runner: WorkerRunner = {
    name: "liar",
    // Every worker CLAIMS success; only the ledger knows the truth.
    async runWorker() { return { detail: "I totally solved it", windowsUsed: 1 }; },
  };
  const result = await runWave(plan, {
    ledgers: new FakeLedgers([before, after]) as never,
    journal: tmpJournal(), runner, paper: P, repoRoot: "/nonexistent",
  });
  const byNode = Object.fromEntries(result.reports.map(r => [r.node, r.outcome]));
  assert.equal(byNode.a, "admitted");       // hypothesis -> solid
  assert.equal(byNode.b, "promoted");       // hypothesis -> preliminary
  assert.equal(byNode.c, "no_progress");    // unchanged despite the claim
  assert.equal(byNode.d, "rejected");       // new open obligation
});

test("a crashing worker is reported failed and does not sink the wave", async () => {
  const mission = buildMission(P, [row("a", "hypothesis"), row("b", "hypothesis")], []);
  const plan = planWave(1, mission, 2);
  const runner: WorkerRunner = {
    name: "half-crash",
    async runWorker(task: WorkerTask) {
      if (task.node.id === "a") throw new Error("boom");
      return { detail: "ok", windowsUsed: 1 };
    },
  };
  const journal = tmpJournal();
  const result = await runWave(plan, {
    ledgers: new FakeLedgers([emptySnap()]) as never,
    journal, runner, paper: P, repoRoot: "/nonexistent",
  });
  assert.equal(result.failed, 1);
  assert.equal(result.reports.length, 2);
  const done = journal.ofType("worker_done");
  assert.equal(done.length, 2);             // both outcomes journaled
});

test("packets: a pure chain is leased whole, up to packetSize", () => {
  const mission = buildMission(P, [
    row("c1", "hypothesis"),
    row("c2", "hypothesis", ["c1"]),
    row("c3", "hypothesis", ["c2"]),
    row("c4", "hypothesis", ["c3"]),
    row("c5", "hypothesis", ["c4"]),
  ], []);
  const plan = planWave(1, mission, 4, 4);
  assert.equal(plan.packets.length, 1);
  assert.deepEqual(plan.packets[0].map(n => n.id), ["c1", "c2", "c3", "c4"]); // size-capped
});

test("packets: a branch point ends the lease — branches stay parallel", () => {
  const mission = buildMission(P, [
    row("a", "hypothesis"),
    row("b", "hypothesis", ["a"]),
    row("c", "hypothesis", ["a"]),
    row("d", "hypothesis", ["b", "c"]),
  ], []);
  const plan = planWave(1, mission, 4, 8);
  assert.equal(plan.packets.length, 1);
  assert.deepEqual(plan.packets[0].map(n => n.id), ["a"]); // b,c ambiguous -> next wave
  // after a is solid, b and c become TWO parallel packets
  const later = buildMission(P, [
    row("a", "solid"),
    row("b", "hypothesis", ["a"]),
    row("c", "hypothesis", ["a"]),
    row("d", "hypothesis", ["b", "c"]),
  ], []);
  const plan2 = planWave(2, later, 4, 8);
  assert.deepEqual(plan2.packets.map(p => p.map(n => n.id)), [["b"], ["c"]]);
});

test("packets: two independent chains are leased to two parallel workers", () => {
  const mission = buildMission(P, [
    row("x1", "hypothesis"), row("x2", "hypothesis", ["x1"]),
    row("y1", "hypothesis"), row("y2", "hypothesis", ["y1"]),
  ], []);
  const plan = planWave(1, mission, 4, 4);
  assert.deepEqual(plan.packets.map(p => p.map(n => n.id)).sort(),
    [["x1", "x2"], ["y1", "y2"]]);
});
