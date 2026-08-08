import assert from "node:assert/strict";
import { test } from "node:test";
import { buildMission, missionComplete, readyFrontier } from "../src/dag.js";
import type { ClaimRow, KnowledgeRow } from "../src/types.js";

const P = "arxiv-0000.00000";
const row = (node_id: string, status: KnowledgeRow["status"],
             predecessors: string[] = []): KnowledgeRow =>
  ({ paper: P, node_id, status, predecessors, summary: node_id });

test("ready frontier: only nodes whose predecessors are ALL solid", () => {
  const mission = buildMission(P, [
    row("a", "solid"),
    row("b", "hypothesis", ["a"]),
    row("c", "hypothesis", ["b"]),          // blocked: b not solid
    row("d", "hypothesis"),                  // independent root
  ], []);
  const ready = readyFrontier(mission).map(n => n.id);
  assert.deepEqual(ready, ["d", "b"]);       // depth order: d(0) before b(1)
});

test("missing predecessor blocks readiness (waits for acquisition)", () => {
  const mission = buildMission(P, [row("x", "hypothesis", ["ghost"])], []);
  assert.deepEqual(readyFrontier(mission), []);
});

test("amended rows are skipped; latest row wins", () => {
  const mission = buildMission(P, [
    row("n", "hypothesis"),
    row("n", "solid"),
    { ...row("n", "amended"), notes: "correction pointer" },
  ], []);
  assert.equal(mission.get("n")!.status, "solid");
});

test("cycles never become ready and do not hang", () => {
  const mission = buildMission(P, [
    row("p", "hypothesis", ["q"]),
    row("q", "hypothesis", ["p"]),
    row("r", "hypothesis"),
  ], []);
  assert.deepEqual(readyFrontier(mission).map(n => n.id), ["r"]);
});

test("open obligations attach to their nodes from the claim ledger", () => {
  const claims: ClaimRow[] = [
    { paper: P, entry_id: "o1", kind: "obligation", status: "open", node_ids: ["a"] },
    { paper: P, entry_id: "o2", kind: "obligation", status: "discharged", node_ids: ["a"] },
  ];
  const mission = buildMission(P, [row("a", "hypothesis")], claims);
  assert.deepEqual(mission.get("a")!.openObligations, ["o1"]);
});

test("missionComplete only when every node is solid (and mission non-empty)", () => {
  assert.equal(missionComplete(buildMission(P, [], [])), false);
  assert.equal(missionComplete(buildMission(P, [row("a", "solid")], [])), true);
  assert.equal(missionComplete(buildMission(P, [row("a", "solid"), row("b", "future")], [])), false);
});
