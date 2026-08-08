/** Conformance gate against the Python contract manifest — the single source
 * of truth. Any hand-mirrored constant that drifts fails HERE, not in prod. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { DIGEST_WINDOW_THRESHOLD } from "../src/digest.js";
import { GATE_PROGRESS_STATUSES } from "../src/gate.js";
import { NODAL_WINDOW, RESEARCH_STATE_CAP_BYTES } from "../src/observer.js";
import { DEFAULT_PACKET_SIZE } from "../src/scheduler.js";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

interface Manifest {
  delegation: { env_var: string; allowed_roles: string[]; policy_file: string };
  ledgers: Record<string, { dir: string; legacy_dir: string; file: string }>;
  result: { gate_progress_statuses: string[] };
  notes: { research_state_cap_bytes: number; nodal_window: number };
  cadence: { digest_window_threshold: number; default_packet_size: number };
}

const m: Manifest = JSON.parse(execFileSync(
  "python3", [path.join(REPO_ROOT, "_common/contract.py"), "manifest"],
  { encoding: "utf-8" }));

test("gate progress statuses match the Python contract", () => {
  assert.deepEqual([...GATE_PROGRESS_STATUSES].sort(), [...m.result.gate_progress_statuses].sort());
});

test("delegation policy names match the Python contract", () => {
  assert.equal(m.delegation.env_var, "CHANDRA_ROLE");
  assert.equal(m.delegation.policy_file, ".delegation-policy");
  assert.deepEqual([...m.delegation.allowed_roles].sort(),
    ["human-override", "observer", "validator", "worker"]);
});

test("note caps and cadences match the Python contract", () => {
  assert.equal(RESEARCH_STATE_CAP_BYTES, m.notes.research_state_cap_bytes);
  assert.equal(NODAL_WINDOW, m.notes.nodal_window);
  assert.equal(DIGEST_WINDOW_THRESHOLD, m.cadence.digest_window_threshold);
  assert.equal(DEFAULT_PACKET_SIZE, m.cadence.default_packet_size);
});

test("ledger layout matches the Python contract", () => {
  assert.equal(m.ledgers.result.dir, "results/ledgers/result");
  assert.equal(m.ledgers.result.legacy_dir, "result-database");
  assert.equal(m.ledgers.knowledge.file, "nodes.jsonl");
  assert.equal(m.ledgers.claim.file, "entries.jsonl");
  assert.equal(m.ledgers.error.file, "trials.jsonl");
});
