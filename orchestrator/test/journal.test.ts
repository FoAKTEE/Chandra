import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { Journal } from "../src/journal.js";

test("journal append/read round-trip preserves order and types", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-journal-"));
  const j = new Journal(path.join(dir, "deep", "journal.jsonl")); // mkdir -p
  j.append({ type: "wave_planned", wave: 1, ready: ["a"], scheduled: ["a"] });
  j.append({ type: "halt", reason: "test", wave: 1 });
  const entries = j.read();
  assert.equal(entries.length, 2);
  assert.equal(entries[0].msg.type, "wave_planned");
  assert.equal(j.ofType("halt")[0].reason, "test");
  assert.ok(entries[0].at <= entries[1].at);
});
