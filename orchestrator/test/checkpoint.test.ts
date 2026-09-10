/** Wave checkpoints against real gated, hash-chained Python ledger appends. */
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { test, type TestContext } from "node:test";
import { fileURLToPath } from "node:url";
import { buildCheckpoint, CheckpointError, LEDGER_FILES, serializeCheckpoint, verifyAgainst,
  type Checkpoint, type LedgerCheckpoint } from "../src/checkpoint.js";
import { commitWave } from "../src/gitops.js";
import { Ledgers } from "../src/ledger.js";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const WORK = "/tmp/chandra/work/checkpoint-manifest";
const P = "checkpoint";
const CHECKPOINT = "results/ledgers/CHECKPOINT.json";
const FILES = { claim: "entries.jsonl", error: "trials.jsonl", knowledge: "nodes.jsonl", result: "results.jsonl" };
const LEGACY_PREFIX = Buffer.from('{ "paper": "checkpoint", "node_id": "old", "task_id": "old", ' +
  '"domain": "symbolic", "status": "hypothesis", "summary": "legacy alpha é" }\r\n');

function git(repo: string, ...args: string[]): string {
  return execFileSync("git", ["-C", repo, ...args], { encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

function file(repo: string, db: keyof typeof FILES, paper = P, legacy = false): string {
  return path.join(repo, legacy ? `${db}-database` : `results/ledgers/${db}`, `paper_${paper}`, FILES[db]);
}

function fixture(t: TestContext, initialCommit = true): string {
  fs.mkdirSync(WORK, { recursive: true });
  const repo = fs.mkdtempSync(path.join(WORK, "repo-"));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(repo, "_common"));
  fs.writeFileSync(path.join(repo, ".delegation-policy"), "strict\n");
  for (const args of [["init", "-q"], ["config", "user.email", "fixture@test"],
    ["config", "user.name", "fixture"], ["config", "commit.gpgsign", "false"],
    ["config", "core.hooksPath", ".git/hooks"]]) git(repo, ...args);
  if (initialCommit) {
    git(repo, "add", "-A");
    git(repo, "commit", "-q", "-m", "chore(fixture): seed checkpoint repo");
  }
  fs.copyFileSync(path.join(REPO_ROOT, "_common/hooks/commit-msg"), path.join(repo, ".git/hooks/commit-msg"));
  fs.chmodSync(path.join(repo, ".git/hooks/commit-msg"), 0o755);
  fs.mkdirSync(path.dirname(file(repo, "knowledge")), { recursive: true });
  fs.writeFileSync(file(repo, "knowledge"), LEGACY_PREFIX);
  execFileSync("python3", ["-c", `
import sys
sys.path.insert(0, "tests")
from factories import (valid_knowledge_row, valid_result_row, valid_claim_row,
                       valid_error_pass_row, write_evidence)
from _common.ledgers import knowledge_database as k, result_database as r
from _common.ledgers import claims_database as c, error_database as e
root, paper = sys.argv[1:]
write_evidence(root)
for node in ("n1", "n2"):
    k.append_row(valid_knowledge_row(paper=paper, node_id=node), repo_root=root)
r.append_row(valid_result_row(paper=paper), repo_root=root)
c.append_row(valid_claim_row(paper=paper), repo_root=root)
e.append_row(valid_error_pass_row(paper=paper), repo_root=root)
`, repo, P], { cwd: REPO_ROOT, env: { ...process.env, CHANDRA_ROLE: "worker" }, stdio: "pipe" });
  return repo;
}

const sha256 = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
const readCheckpoint = (repo: string): Checkpoint => JSON.parse(fs.readFileSync(path.join(repo, CHECKPOINT), "utf-8"));

/** Independent expected inventory for the four known fixture files. */
function fixtureInventory(repo: string): LedgerCheckpoint[] {
  return Object.entries(FILES).map(([db, filename]) => {
    const rel = `results/ledgers/${db}/paper_${P}/${filename}`;
    const data = fs.readFileSync(path.join(repo, rel));
    const rows = data.toString("utf-8").trim().split("\n").map(line => JSON.parse(line));
    const hashed = rows.filter(row => row.row_hash != null);
    return {
      db, paper: P, path: rel, rows: rows.length, hashed: hashed.length,
      head: hashed.at(-1)?.row_hash ?? null,
      legacyPrefixRows: db === "knowledge" ? 1 : 0,
      legacyPrefixSha256: db === "knowledge" ? sha256(LEGACY_PREFIX) : null,
      bytes: data.length, fileSha256: sha256(data),
    };
  });
}

/** Commit the trust anchor independently of the feature under test. */
function seedCheckpoint(repo: string): void {
  fs.writeFileSync(path.join(repo, CHECKPOINT), JSON.stringify({
    version: 1, createdAt: "2026-01-01T00:00:00.000Z", ledgers: fixtureInventory(repo),
  }, null, 2) + "\n");
  git(repo, "add", "-A");
  git(repo, "commit", "-q", "-m", "notes(fixture): establish trusted checkpoint");
}

async function appendNode(repo: string, node = "n3", paper = P): Promise<void> {
  await new Ledgers(repo, "worker").appendKnowledge({
    paper, node_id: node, task_id: node, domain: "symbolic", status: "hypothesis", summary: node,
  });
}

function deleteTail(repo: string): void {
  const ledger = file(repo, "knowledge");
  const data = fs.readFileSync(ledger);
  fs.writeFileSync(ledger, data.subarray(0, data.lastIndexOf(10, data.length - 2) + 1));
}

test("first and second waves write deterministic inventories and link the committed predecessor", async t => {
  const repo = fixture(t);
  const first = commitWave(repo, P, 1, "initial ledgers");
  assert.ok(fs.existsSync(path.join(repo, CHECKPOINT)), "first wave must write a checkpoint");
  assert.deepEqual(first.checkpoint, { path: CHECKPOINT, ledgers: 4, advanced: 0, added: 4 });
  const initial = readCheckpoint(repo);
  assert.equal(initial.version, 1);
  assert.ok(Number.isFinite(Date.parse(initial.createdAt)));
  assert.equal(initial.previous, undefined);
  assert.deepEqual(initial.ledgers, fixtureInventory(repo));
  const raw = fs.readFileSync(path.join(repo, CHECKPOINT), "utf-8");
  assert.equal(raw, serializeCheckpoint(initial));
  assert.equal(raw, JSON.stringify(initial, null, 2) + "\n");
  for (const object of [initial, ...initial.ledgers]) {
    assert.deepEqual(Object.keys(object), Object.keys(object).sort());
  }
  assert.equal(git(repo, "show", `HEAD:${CHECKPOINT}`), raw.trim());
  await appendNode(repo);
  const second = commitWave(repo, P, 2, "one append");
  assert.deepEqual(second.checkpoint, { path: CHECKPOINT, ledgers: 4, advanced: 1, added: 0 });
  const next = readCheckpoint(repo);
  assert.deepEqual(next.previous, { sha: first.sha, path: CHECKPOINT });
  assert.deepEqual(Object.keys(next.previous!), ["path", "sha"]);
  assert.deepEqual(next.ledgers, fixtureInventory(repo));
  assert.equal(git(repo, "status", "--porcelain"), "");
});

test("an unborn HEAD admits its first wave checkpoint", t => {
  const repo = fixture(t, false);
  assert.equal(commitWave(repo, P, 1, "first commit").committed, true);
  assert.equal(readCheckpoint(repo).previous, undefined);
  assert.deepEqual(readCheckpoint(repo).ledgers, fixtureInventory(repo));
  assert.equal(git(repo, "rev-list", "--count", "HEAD"), "1");
});

test("consumer JSON ignore rules cannot omit the committed checkpoint anchor", t => {
  const repo = fixture(t);
  fs.writeFileSync(path.join(repo, ".gitignore"), "*.json\n");
  assert.equal(commitWave(repo, P, 1, "must commit anchor").committed, true);
  assert.equal(git(repo, "ls-files", CHECKPOINT), CHECKPOINT);
  assert.deepEqual(JSON.parse(git(repo, "show", `HEAD:${CHECKPOINT}`)), readCheckpoint(repo));
  deleteTail(repo);
  assert.throws(() => commitWave(repo, P, 2, "deleted tail"), /checkpoint REJECTED:.*tail_deleted/);
});

test("complete Python-admitted nonfinite metrics remain buildable with exact byte digests", async t => {
  const repo = fixture(t);
  const before = buildCheckpoint(repo);
  execFileSync("python3", ["-c", `
import sys
sys.path.insert(0, "tests")
from factories import valid_error_fail_row
from _common.ledgers import error_database as e
root, paper = sys.argv[1:]
for i, value in enumerate((float("nan"), float("inf"), float("-inf")), 2):
    e.append_row(valid_error_fail_row(
        paper=paper, iteration=i, domain="numerical", failure_mode="nan_inf_propagation",
        metric={"name": "nonfinite", "value": value, "threshold": 0, "pass": False},
        change_summary='record NaN, Infinity and -Infinity in a complete trial'), repo_root=root)
`, repo, P], { cwd: REPO_ROOT, env: { ...process.env, CHANDRA_ROLE: "worker" }, stdio: "pipe" });
  assert.equal((await new Ledgers(repo).verifyChains()).ok, true);
  const after = buildCheckpoint(repo);
  const ledger = after.ledgers.find(l => l.db === "error")!;
  const data = fs.readFileSync(file(repo, "error"));
  assert.equal(ledger.rows, 4);
  assert.equal(ledger.hashed, 4);
  assert.equal(ledger.head, data.toString("utf-8").trim().split("\n").at(-1)!.match(/"row_hash"\s*:\s*"([a-f0-9]{64})"/)![1]);
  assert.equal(ledger.bytes, data.length);
  assert.equal(ledger.fileSha256, sha256(data));
  assert.equal(verifyAgainst(before, after).ok, true);
  assert.equal(commitWave(repo, P, 1, "nonfinite trial records").committed, true);
});

for (const token of ["-NaN", "1Infinity", "1eInfinity", "Infinity.0"]) {
  test(`malformed numeric token ${token} remains a torn row`, async t => {
    const repo = fixture(t);
    const ledger = file(repo, "error");
    const source = fs.readFileSync(ledger, "utf-8");
    const corrupted = source.replace(/"value"\s*:\s*0(?:\.0)?/, `"value": ${token}`);
    assert.notEqual(corrupted, source);
    fs.writeFileSync(ledger, corrupted);
    const chain = await new Ledgers(repo).verifyChains();
    assert.equal(chain.ok, false);
    assert.match(JSON.stringify(chain.breaks), /incomplete tail/);
    assert.throws(() => buildCheckpoint(repo), error => {
      assert.ok(error instanceof CheckpointError);
      assert.equal(error.violations[0].type, "torn");
      assert.match(error.violations[0].path, /trials.jsonl$/);
      return true;
    });
  });
}

const corruptions: { type: string; db: keyof typeof FILES; chainOk: boolean; mutate(repo: string): void }[] = [
  { type: "tail_deleted", db: "knowledge", chainOk: true, mutate: deleteTail },
  { type: "ledger_missing", db: "result", chainOk: true, mutate: repo => fs.unlinkSync(file(repo, "result")) },
  { type: "legacy_prefix_changed", db: "knowledge", chainOk: true, mutate(repo) {
    const data = fs.readFileSync(file(repo, "knowledge"));
    data[data.indexOf("alpha")] = "A".charCodeAt(0);
    fs.writeFileSync(file(repo, "knowledge"), data);
  } },
  { type: "torn", db: "claim", chainOk: false, mutate: repo => fs.appendFileSync(file(repo, "claim"), '{"entry_id":') },
];
for (const corruption of corruptions) {
  test(`commitWave rejects ${corruption.type} without replacing the checkpoint or staging`, async t => {
    const repo = fixture(t);
    seedCheckpoint(repo);
    corruption.mutate(repo);
    const before = fs.readFileSync(path.join(repo, CHECKPOINT));
    const head = git(repo, "rev-parse", "HEAD");
    const status = git(repo, "status", "--porcelain");
    const chain = await new Ledgers(repo).verifyChains();
    assert.equal(chain.ok, corruption.chainOk, JSON.stringify(chain));
    assert.throws(() => commitWave(repo, P, 2, "must be refused"),
      new RegExp(`wave 2 checkpoint REJECTED:.*${corruption.type}.*${FILES[corruption.db]}`));
    assert.equal(git(repo, "rev-parse", "HEAD"), head);
    assert.deepEqual(fs.readFileSync(path.join(repo, CHECKPOINT)), before);
    assert.equal(git(repo, "status", "--porcelain"), status);
  });
}

for (const present of [false, true]) {
  test(`rejecting commit-msg hook restores checkpoint ${present ? "content" : "absence"} and staging for retry`, async t => {
    const repo = fixture(t);
    if (present) seedCheckpoint(repo);
    await appendNode(repo);
    // Preserve unrelated staged and unstaged changes as well as checkpoint state.
    fs.writeFileSync(path.join(repo, "staged.txt"), "staged\n");
    git(repo, "add", "staged.txt");
    fs.appendFileSync(path.join(repo, "staged.txt"), "unstaged\n");
    const before = present ? fs.readFileSync(path.join(repo, CHECKPOINT)) : undefined;
    const head = git(repo, "rev-parse", "HEAD");
    const status = git(repo, "status", "--porcelain");
    const index = git(repo, "ls-files", "--stage");
    const hook = path.join(repo, ".git/hooks/commit-msg");
    fs.writeFileSync(hook, `#!/bin/sh\nif test -f ${CHECKPOINT}; then\n` +
      `  cp ${CHECKPOINT} .git/checkpoint-seen.json\nfi\nexit 1\n`, { mode: 0o755 });
    assert.throws(() => commitWave(repo, P, 2, "hook rejects"), /wave 2 commit REJECTED/);
    const captured = path.join(repo, ".git/checkpoint-seen.json");
    assert.ok(fs.existsSync(captured), "hook must observe the newly written checkpoint before rejecting");
    const seen: Checkpoint = JSON.parse(fs.readFileSync(captured, "utf-8"));
    assert.equal(seen.ledgers.find(l => l.db === "knowledge")!.hashed, 3,
      "hook must observe this wave's checkpoint, not the old manifest");
    assert.equal(git(repo, "rev-parse", "HEAD"), head);
    if (before) assert.deepEqual(fs.readFileSync(path.join(repo, CHECKPOINT)), before);
    else assert.equal(fs.existsSync(path.join(repo, CHECKPOINT)), false);
    assert.equal(git(repo, "status", "--porcelain"), status);
    assert.equal(git(repo, "ls-files", "--stage"), index);
    fs.copyFileSync(path.join(REPO_ROOT, "_common/hooks/commit-msg"), hook);
    assert.equal(commitWave(repo, P, 2, "retry").committed, true);
    assert.equal(git(repo, "status", "--porcelain"), "");
  });
}

for (const workingCopy of ["forged", "deleted"]) {
  test(`a ${workingCopy} working checkpoint cannot replace HEAD as the trust anchor`, t => {
    const repo = fixture(t);
    seedCheckpoint(repo);
    deleteTail(repo);
    if (workingCopy === "forged") {
      fs.writeFileSync(path.join(repo, CHECKPOINT), JSON.stringify({ ...readCheckpoint(repo), ledgers: fixtureInventory(repo) }));
    } else fs.unlinkSync(path.join(repo, CHECKPOINT));
    const before = git(repo, "status", "--porcelain");
    assert.throws(() => commitWave(repo, P, 2, "must use HEAD"), /checkpoint REJECTED:.*tail_deleted/);
    assert.equal(git(repo, "status", "--porcelain"), before);
  });
}

test("equal counts and a previous head moved to a later index cannot hide replaced history", async t => {
  const repo = fixture(t);
  seedCheckpoint(repo);
  const original = fs.readFileSync(file(repo, "knowledge"), "utf-8").trim().split("\n").at(-1)!;
  deleteTail(repo);
  await appendNode(repo, "replacement");
  assert.equal((await new Ledgers(repo).verifyChains()).ok, true, "replacement is a valid chain with the same counts");
  assert.throws(() => commitWave(repo, P, 2, "same counts"), /checkpoint REJECTED:.*tail_deleted/);
  fs.appendFileSync(file(repo, "knowledge"), original + "\n");
  const previous: Checkpoint = JSON.parse(git(repo, "show", `HEAD:${CHECKPOINT}`));
  const current = buildCheckpoint(repo);
  assert.equal(current.ledgers.find(l => l.db === "knowledge")!.head, previous.ledgers.find(l => l.db === "knowledge")!.head);
  const diff = verifyAgainst(previous, current);
  assert.equal(diff.ok, false);
  assert.deepEqual(diff.violations.map(v => v.type), ["tail_deleted"]);
});

test("two builds around an append each describe one consistent byte snapshot", async t => {
  const repo = fixture(t);
  const first = buildCheckpoint(repo);
  const before = fs.readFileSync(file(repo, "knowledge"));
  await appendNode(repo);
  const second = buildCheckpoint(repo);
  const after = fs.readFileSync(file(repo, "knowledge"));
  for (const [checkpoint, bytes] of [[first, before], [second, after]] as const) {
    const ledger = checkpoint.ledgers.find(l => l.db === "knowledge")!;
    const rows = bytes.toString("utf-8").trim().split("\n").map(line => JSON.parse(line));
    assert.equal(ledger.rows, rows.length);
    const hashes = rows.filter(row => row.row_hash != null);
    assert.equal(ledger.hashed, hashes.length);
    assert.equal(ledger.head, hashes[ledger.hashed - 1].row_hash);
    assert.equal(ledger.legacyPrefixRows, 1);
    assert.equal(ledger.legacyPrefixSha256, sha256(LEGACY_PREFIX));
    assert.equal(ledger.bytes, bytes.length);
    assert.equal(ledger.fileSha256, sha256(bytes));
  }
  const diff = verifyAgainst(first, second);
  assert.equal(diff.ok, true);
  assert.deepEqual(diff.violations, []);
  assert.deepEqual(diff.added, []);
  assert.deepEqual(diff.advanced.map(l => l.db), ["knowledge"]);
});

test("direct verification reports a newly added ledger that became torn after its build", async t => {
  const repo = fixture(t);
  const before = buildCheckpoint(repo);
  await appendNode(repo, "new-node", "new-paper");
  const after = buildCheckpoint(repo);
  fs.appendFileSync(file(repo, "knowledge", "new-paper"), '{"node_id":');
  const diff = verifyAgainst(before, after);
  assert.equal(diff.ok, false);
  assert.deepEqual(diff.violations, [{ type: "torn", db: "knowledge", paper: "new-paper",
    path: "results/ledgers/knowledge/paper_new-paper/nodes.jsonl", torn: true }]);
  assert.deepEqual(diff.added, []);
});

test("inventory includes both layouts without shadowing, new papers, empty files and legacy-only prefixes", async t => {
  const repo = fixture(t);
  const before = buildCheckpoint(repo);
  for (const db of Object.keys(FILES) as (keyof typeof FILES)[]) {
    const legacy = file(repo, db, P, true);
    fs.mkdirSync(path.dirname(legacy), { recursive: true });
    fs.copyFileSync(file(repo, db), legacy);
  }
  const onlyLegacy = file(repo, "knowledge", "legacy-only", true);
  fs.mkdirSync(path.dirname(onlyLegacy), { recursive: true });
  fs.writeFileSync(onlyLegacy, LEGACY_PREFIX);
  const empty = file(repo, "result", "empty");
  fs.mkdirSync(path.dirname(empty), { recursive: true });
  fs.writeFileSync(empty, "");
  await appendNode(repo, "another", "new-paper");
  const after = buildCheckpoint(repo);
  assert.equal(after.ledgers.length, 11);
  const order = after.ledgers.map(l => `${l.db}\0${l.paper}\0${l.path}`);
  assert.deepEqual(order, [...order].sort());
  const legacy = after.ledgers.find(l => l.paper === "legacy-only")!;
  assert.equal(legacy.rows, 1);
  assert.equal(legacy.hashed, 0);
  assert.equal(legacy.head, null);
  assert.equal(legacy.legacyPrefixRows, 1);
  assert.equal(legacy.legacyPrefixSha256, sha256(LEGACY_PREFIX));
  const blank = after.ledgers.find(l => l.paper === "empty")!;
  assert.equal(blank.rows, 0);
  assert.equal(blank.head, null);
  assert.equal(blank.legacyPrefixSha256, null);
  assert.equal(blank.fileSha256, sha256(Buffer.alloc(0)));
  const diff = verifyAgainst(before, after);
  assert.equal(diff.ok, true);
  assert.equal(diff.added.length, 7);
  assert.deepEqual(diff.advanced, []);
});

test("an unterminated valid JSON row is torn and cannot build even a first checkpoint", t => {
  const repo = fixture(t);
  const claim = file(repo, "claim");
  fs.truncateSync(claim, fs.statSync(claim).size - 1);
  assert.throws(() => buildCheckpoint(repo), error => {
    assert.ok(error instanceof CheckpointError);
    assert.match(error.message, /entries.jsonl/);
    assert.equal(error.violations[0].type, "torn");
    assert.equal(error.violations[0].torn, true);
    return true;
  });
  assert.throws(() => commitWave(repo, P, 1, "incomplete"), /checkpoint REJECTED:.*torn/);
  assert.equal(fs.existsSync(path.join(repo, CHECKPOINT)), false);
});

test("checkpoint ledger filenames match the executable contract manifest", () => {
  const manifest = JSON.parse(execFileSync("python3", ["_common/contract.py", "manifest"],
    { cwd: REPO_ROOT, encoding: "utf-8" }));
  assert.deepEqual(LEDGER_FILES, Object.fromEntries(Object.entries(manifest.ledgers)
    .map(([db, value]) => [db, (value as { file: string }).file])));
});

test("CLI build prints a checkpoint; verify uses HEAD and exits 0 clean or 1 after tail deletion", t => {
  const repo = fixture(t);
  seedCheckpoint(repo);
  const cli = (command: string) => spawnSync(process.execPath,
    [path.join(REPO_ROOT, "orchestrator/dist/src/checkpoint.js"), command, repo], { encoding: "utf-8" });
  const clean = cli("verify");
  assert.equal(clean.status, 0, clean.stderr);
  assert.equal(JSON.parse(clean.stdout).ok, true);
  const built = cli("build");
  assert.equal(built.status, 0, built.stderr);
  assert.deepEqual(JSON.parse(built.stdout).ledgers, fixtureInventory(repo));
  deleteTail(repo);
  const deleted = cli("verify");
  assert.equal(deleted.status, 1, deleted.stderr);
  assert.equal(JSON.parse(deleted.stdout).ok, false);
  assert.match(deleted.stdout, /tail_deleted/);
  fs.appendFileSync(file(repo, "claim"), '{"broken":');
  const torn = cli("verify");
  assert.equal(torn.status, 1);
  const violation = JSON.parse(torn.stdout).violations[0];
  assert.equal(violation.type, "torn");
  assert.equal(violation.torn, true);
  assert.match(violation.path, /entries.jsonl$/);
});
