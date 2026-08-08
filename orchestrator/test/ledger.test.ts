/** Integration: the TS bridge against the REAL Python ledger CLIs (with the
 * executable admission gate) in a temp repo-root. Requires python3. */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { Ledgers } from "../src/ledger.js";

const P = "arxiv-0000.00000";
// compiled location is orchestrator/dist/test/ -> methodology repo root is 3 up
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function tmpRoot(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-ledger-"));
  // the CLIs live in the methodology repo; ledgers land under the tmp root
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(dir, "_common"));
  return dir;
}

test("knowledge append/query round-trip through the gated CLI", async () => {
  const root = tmpRoot();
  const ledgers = new Ledgers(root);
  await ledgers.appendKnowledge({
    paper: P, node_id: "n1", task_id: "t1", domain: "symbolic",
    status: "hypothesis", summary: "toy node",
  });
  const rows = await ledgers.knowledge(P);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].node_id, "n1");
});

test("the admission gate REJECTS through the bridge (free-text solid evidence)", async () => {
  const root = tmpRoot();
  const ledgers = new Ledgers(root);
  await assert.rejects(
    ledgers.appendKnowledge({
      paper: P, node_id: "n1", task_id: "t1", domain: "symbolic",
      status: "solid", summary: "toy node", evidence: "trust me",
    }),
    /free-text evidence is not admissible/);
  assert.deepEqual(await ledgers.knowledge(P), []); // nothing landed
});

test("snapshot reflects per-node status and obligations", async () => {
  const root = tmpRoot();
  const ledgers = new Ledgers(root);
  await ledgers.appendKnowledge({
    paper: P, node_id: "n1", task_id: "t1", domain: "symbolic",
    status: "hypothesis", summary: "toy node",
  });
  const snap = await ledgers.snapshot(P);
  assert.equal(snap.statusByNode["n1"], "hypothesis");
  assert.deepEqual(snap.resultsByNode, {});
});
