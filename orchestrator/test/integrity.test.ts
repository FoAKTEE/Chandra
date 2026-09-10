/** Fail-closed mission decisions against real ledger CLIs in disposable repos. */
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { test, type TestContext } from "node:test";
import { fileURLToPath } from "node:url";
import { DEFAULT_BUDGETS } from "../src/gate.js";
import { generationLog, sourceMirrorDir } from "../src/jobs.js";
import { Journal } from "../src/journal.js";
import { LedgerError, Ledgers } from "../src/ledger.js";
import { runMissionLoop, type MissionLoopDeps } from "../src/main.js";
import { TruncatingObserver } from "../src/observer.js";

const P = "integrity";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const WORK = "/tmp/chandra/work/integrity-before-decisions";

function setEnv(t: TestContext, key: string, value: string | undefined): void {
  const previous = process.env[key];
  if (value === undefined) delete process.env[key];
  else process.env[key] = value;
  t.after(() => {
    if (previous === undefined) delete process.env[key];
    else process.env[key] = previous;
  });
}

function toyRepo(t: TestContext) {
  fs.mkdirSync(WORK, { recursive: true });
  const scratch = fs.mkdtempSync(path.join(WORK, "fixture-"));
  const repo = path.join(scratch, "repo");
  const runtime = path.join(scratch, "runtime");
  fs.mkdirSync(repo);
  setEnv(t, "CHANDRA_RUNTIME", runtime);
  setEnv(t, "CHANDRA_PYTHON", undefined);
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(repo, "_common"));
  fs.mkdirSync(path.join(repo, ".claude", "skills"), { recursive: true });
  for (const rel of ["alignment.md", "pipelines/2-work/spec.md"]) {
    const dest = path.join(repo, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(path.join(REPO_ROOT, rel), dest);
  }
  fs.writeFileSync(path.join(repo, ".delegation-policy"), "strict\n");
  for (const args of [["init", "-q"], ["config", "user.email", "fixture@test"],
    ["config", "user.name", "fixture"], ["add", "-A"],
    ["commit", "-q", "-m", "chore(fixture): seed integrity repo"]]) {
    execFileSync("git", ["-C", repo, ...args]);
  }
  t.after(() => fs.rmSync(scratch, { recursive: true, force: true }));
  return {
    repo,
    ledgers: new Ledgers(repo, "worker"),
    journal: new Journal(path.join(runtime, `paper_${P}`, "journal.jsonl")),
  };
}

function ledgerFile(repo: string, db: string, filename: string): string {
  const dir = path.join(repo, "results", "ledgers", db, `paper_${P}`);
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, filename);
}

async function seedNode(repo: string, status: "solid" | "hypothesis" = "solid",
                        predecessors: string[] = []): Promise<void> {
  fs.writeFileSync(path.join(repo, "evidence.txt"), "fixture evidence\n");
  await new Ledgers(repo, "worker").appendKnowledge({
    paper: P, node_id: "n1", task_id: "t1", domain: "software", status,
    summary: "original summary", predecessors, evidence: "evidence.txt",
  });
  const rendered = generationLog(repo, P);
  fs.mkdirSync(path.dirname(rendered), { recursive: true });
  fs.writeFileSync(rendered, "final render exists\n");
}

function tamperKnowledge(repo: string): void {
  const file = ledgerFile(repo, "knowledge", "nodes.jsonl");
  const rows = fs.readFileSync(file, "utf-8").trim().split("\n").map(line => JSON.parse(line));
  rows[0].summary = "edited without rehashing";
  fs.writeFileSync(file, rows.map(row => JSON.stringify(row)).join("\n") + "\n");
}

function tearClaims(repo: string): void {
  fs.appendFileSync(ledgerFile(repo, "claim", "entries.jsonl"), '{"entry_id":');
}

function run(repo: string, overrides: Partial<MissionLoopDeps> = {}): Promise<number> {
  return runMissionLoop({
    repoRoot: repo, paper: P, maxWorkers: 1, maxWaves: 1,
    runner: { name: "noop", async runWorker() { return { detail: "", windowsUsed: 1 }; } },
    observerRunner: new TruncatingObserver(),
    probes: { async refreshDue() { return false; } }, log: () => {},
    ...overrides,
  });
}

function assertIntegrityHalt(journal: Journal, reason: RegExp): void {
  const halts = journal.ofType("halt");
  assert.equal(halts.length, 1);
  assert.match(halts[0].reason, reason);
  assert.ok(!halts.some(h => h.reason === "mission_complete"));
}

interface PreflightReport { ok: boolean; breaks: unknown[]; unreadable: string[] }
type PreflightEvent = Omit<PreflightReport, "breaks"> & { type: "preflight"; wave: number; breaks: number };
// The cast lets these regression tests compile against the pre-change bridge.
function preflight(ledgers: Ledgers): Promise<PreflightReport> {
  return (ledgers as Ledgers & { preflight(paper: string): Promise<PreflightReport> }).preflight(P);
}
function preflights(journal: Journal): PreflightEvent[] {
  return journal.read().map(e => e.msg).filter(m => String(m.type) === "preflight") as unknown as PreflightEvent[];
}

test("tampered all-solid ledger halts before mission completion or scheduling", async t => {
  const { repo, journal } = toyRepo(t);
  await seedNode(repo);
  tamperKnowledge(repo);
  assert.equal(await run(repo), 8);
  assertIntegrityHalt(journal, /ledger_tampered:.*hash mismatch/);
  assert.deepEqual(journal.ofType("wave_planned"), []);
  assert.deepEqual(journal.ofType("task_assigned"), []);
  assert.equal(preflights(journal)[0].breaks, 1);
});

test("plan exits 8 and prints the chain report for an all-solid tampered ledger", async t => {
  const { repo } = toyRepo(t);
  await seedNode(repo);
  tamperKnowledge(repo);
  const result = spawnSync(process.execPath,
    [path.join(REPO_ROOT, "orchestrator/dist/src/main.js"), "plan", "--repo-root", repo, "--paper", P],
    { encoding: "utf-8" });
  assert.equal(result.status, 8, result.stderr);
  const report = JSON.parse(result.stdout).preflight;
  assert.equal(report.ok, false);
  assert.equal(report.breaks.length, 1);
  assert.deepEqual(report.unreadable, []);
});

test("torn claims halt with exit 9 and preserve the CLI diagnostic in the journal", async t => {
  const { repo, journal } = toyRepo(t);
  await seedNode(repo);
  tearClaims(repo);
  assert.equal(await run(repo), 9);
  assertIntegrityHalt(journal, /ledger_unreadable:.*claims_database.py query.*(JSON|incomplete tail)/);
  assert.match(preflights(journal)[0].unreadable.join("\n"), /claims_database.py query.*(JSON|incomplete tail)/);
  assert.deepEqual(journal.ofType("task_assigned"), []);
});

test("valid claims over 16 MiB halt with an explicit bridge buffer diagnostic", async t => {
  const { repo, ledgers, journal } = toyRepo(t);
  await seedNode(repo);
  for (let i = 0; i < 2; i++) {
    await ledgers.appendClaimEntry({
      paper: P, entry_id: `large-${i}`, kind: "obligation", status: "open",
      statement: "large valid obligation", notes: "n".repeat(9 * 1024 * 1024),
    });
  }
  assert.ok(fs.statSync(ledgerFile(repo, "claim", "entries.jsonl")).size > 16 * 1024 * 1024);
  assert.equal((await ledgers.verifyChains()).ok, true, "the failure is transport, not tampering");
  assert.equal(await run(repo), 9);
  assertIntegrityHalt(journal, /ledger_unreadable:.*claims_database.py query.*output exceeded 16 MiB/);
  assert.deepEqual(journal.ofType("task_assigned"), []);
});

test("missing CHANDRA_PYTHON executable halts with exit 9 instead of completion", async t => {
  const { repo, journal } = toyRepo(t);
  await seedNode(repo);
  setEnv(t, "CHANDRA_PYTHON", path.join(repo, "nonexistent-python"));
  assert.equal(await run(repo), 9);
  assertIntegrityHalt(journal, /ledger_unreadable:.*nonexistent-python.*ENOENT/);
  assert.deepEqual(journal.ofType("task_assigned"), []);
});

test("an empty CHANDRA_PYTHON setting rejects with a CLI-named LedgerError", async t => {
  const { ledgers } = toyRepo(t);
  setEnv(t, "CHANDRA_PYTHON", "");
  await assert.rejects(ledgers.claims(P), (err: unknown) =>
    err instanceof LedgerError && /claims_database.py query/.test(err.message));
});

test("empty ledgers pass preflight and still schedule a decompose job", async t => {
  const { repo, journal, ledgers } = toyRepo(t);
  fs.mkdirSync(sourceMirrorDir(repo, P), { recursive: true });
  assert.deepEqual(await ledgers.claims(P), []);
  const ran: string[] = [];
  assert.equal(await run(repo, {
    dryRun: true,
    jobRunners: { decompose: { name: "decompose", async run(job) {
      ran.push(job.kind);
      return { detail: "fixture decompose", windowsUsed: 1 };
    } } },
  }), 0);
  assert.deepEqual(ran, ["decompose"]);
  assert.ok(preflights(journal).length >= 3, "startup, wave and terminal boundaries are verified");
  assert.ok(preflights(journal).every(p => p.ok && p.breaks === 0 && p.unreadable.length === 0));
  const messages = journal.read().map(e => String(e.msg.type));
  assert.ok(messages.indexOf("preflight") < messages.indexOf("task_assigned"));
});

test("claims rejects malformed JSON with LedgerError instead of returning an empty array", async t => {
  const { repo, ledgers } = toyRepo(t);
  tearClaims(repo);
  await assert.rejects(ledgers.claims(P), (err: unknown) =>
    err instanceof LedgerError && /claims_database.py query.*(JSON|incomplete tail)/.test(err.message));
});

test("CLI errors retain the last lines of both stderr and stdout", async t => {
  const { repo, ledgers } = toyRepo(t);
  fs.unlinkSync(path.join(repo, "_common")); // replace only the fixture's symlink
  fs.mkdirSync(path.join(repo, "_common"));
  fs.writeFileSync(path.join(repo, "_common/knowledge_database.py"),
    'import sys\nprint("stdout diagnostic")\nprint("stderr diagnostic", file=sys.stderr)\nsys.exit(1)\n');
  await assert.rejects(ledgers.knowledge(P), (err: unknown) => {
    assert.ok(err instanceof LedgerError);
    assert.match(err.message, /stderr diagnostic/);
    assert.match(err.message, /stdout diagnostic/);
    return true;
  });
});

test("a successful query that warns of an incomplete tail is an unreadable ledger", async t => {
  const { repo, ledgers } = toyRepo(t);
  fs.unlinkSync(path.join(repo, "_common"));
  fs.mkdirSync(path.join(repo, "_common"));
  fs.writeFileSync(path.join(repo, "_common/claims_database.py"),
    'import sys\nprint("[]")\nprint("warning: incomplete tail (crash mid-write): ignoring final line", file=sys.stderr)\n');
  await assert.rejects(ledgers.claims(P), (err: unknown) =>
    err instanceof LedgerError && /claims_database.py query.*incomplete tail/.test(err.message));
});

test("verifyChains preserves the structured report from a failing CLI's stdout", async t => {
  const { repo, ledgers } = toyRepo(t);
  await seedNode(repo);
  tamperKnowledge(repo);
  const cli = spawnSync("python3", [path.join(repo, "_common/contract.py"),
    "verify-chains", "--repo-root", repo], { encoding: "utf-8" });
  assert.equal(cli.status, 1);
  assert.deepEqual(await ledgers.verifyChains(), JSON.parse(cli.stdout));
});

for (const failure of ["buffer", "exit_2"] as const) {
  test(`chain report cannot hide a verifier ${failure} failure`, async t => {
    const { repo, ledgers } = toyRepo(t);
    fs.unlinkSync(path.join(repo, "_common"));
    fs.mkdirSync(path.join(repo, "_common"));
    for (const script of ["knowledge_database.py", "result_database.py", "claims_database.py"]) {
      fs.writeFileSync(path.join(repo, "_common", script), 'print("[]")\n');
    }
    fs.writeFileSync(path.join(repo, "_common/contract.py"),
      'import json, sys\nprint(json.dumps({"ok": False, "breaks": [{"reason": "hash mismatch"}]}), flush=True)\n' +
      (failure === "buffer" ? 'sys.stderr.write("e" * (17 * 1024 * 1024))\nsys.stderr.flush()\nsys.exit(1)\n'
        : 'print("verifier cleanup failure", file=sys.stderr)\nsys.exit(2)\n'));
    const report = await preflight(ledgers);
    assert.equal(report.ok, false);
    assert.match(report.unreadable.join("\n"), failure === "buffer"
      ? /contract.py verify-chains.*output exceeded 16 MiB/ : /verifier cleanup failure/);
    assert.deepEqual(report.breaks, []);
  });
}

test("preflight collects chain and all three read failures without throwing", async t => {
  const { ledgers } = toyRepo(t);
  ledgers.verifyChains = async () => { throw new LedgerError("chain CLI missing"); };
  ledgers.knowledge = async () => { throw new LedgerError("knowledge unreadable"); };
  ledgers.results = async () => { throw new LedgerError("results unreadable"); };
  ledgers.claims = async () => { throw new LedgerError("claims unreadable"); };
  const report = await preflight(ledgers);
  assert.equal(report.ok, false);
  assert.deepEqual(report.breaks, []);
  for (const diagnostic of ["chain CLI missing", "knowledge unreadable", "results unreadable", "claims unreadable"]) {
    assert.ok(report.unreadable.some(s => s.includes(diagnostic)), diagnostic);
  }
  assert.equal(report.unreadable.length, 4);
});

test("plan exits 9 and prints unreadable diagnostics when Python is unavailable", async t => {
  const { repo } = toyRepo(t);
  await seedNode(repo);
  setEnv(t, "CHANDRA_PYTHON", path.join(repo, "nonexistent-python"));
  const result = spawnSync(process.execPath,
    [path.join(REPO_ROOT, "orchestrator/dist/src/main.js"), "plan", "--repo-root", repo, "--paper", P],
    { encoding: "utf-8" });
  assert.equal(result.status, 9, result.stderr);
  const report = JSON.parse(result.stdout).preflight;
  assert.equal(report.ok, false);
  assert.match(report.unreadable.join("\n"), /nonexistent-python.*ENOENT/);
});

for (const terminal of ["mission_complete", "no_ready_jobs"] as const) {
  test(`${terminal} rechecks ledgers after readiness probes`, async t => {
    const { repo, journal } = toyRepo(t);
    await seedNode(repo, terminal === "mission_complete" ? "solid" : "hypothesis",
      terminal === "no_ready_jobs" ? ["missing"] : []);
    assert.equal(await run(repo, { probes: { async refreshDue() { tearClaims(repo); return false; } } }), 9);
    assertIntegrityHalt(journal, /ledger_unreadable:.*claims_database.py query.*(JSON|incomplete tail)/);
    assert.deepEqual(journal.ofType("task_assigned"), []);
  });
}

for (const terminal of ["human_pause", "zero_waves"] as const) {
  test(`${terminal} cannot bypass integrity verification`, async t => {
    const { repo, journal } = toyRepo(t);
    await seedNode(repo);
    tamperKnowledge(repo);
    if (terminal === "human_pause") {
      const dir = path.join(repo, "progress", "orchestrator", `paper_${P}`);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "PAUSE"), "pause\n");
    }
    assert.equal(await run(repo, { maxWaves: terminal === "zero_waves" ? 0 : 1 }), 8);
    assertIntegrityHalt(journal, /ledger_tampered:/);
  });
}

for (const boundary of ["digest", "gate_halt"] as const) {
  test(`${boundary} checks corruption introduced by a worker before publishing a decision`, async t => {
    const { repo, journal } = toyRepo(t);
    await seedNode(repo, "hypothesis");
    if (boundary === "gate_halt") {
      const oldLimit = DEFAULT_BUDGETS.noProgressLimit;
      DEFAULT_BUDGETS.noProgressLimit = 0;
      t.after(() => { DEFAULT_BUDGETS.noProgressLimit = oldLimit; });
    }
    assert.equal(await run(repo, {
      digestThreshold: 1,
      runner: { name: "tamper", async runWorker() {
        tamperKnowledge(repo);
        return { detail: "tamper", windowsUsed: 1 };
      } },
    }), 8);
    assertIntegrityHalt(journal, /ledger_tampered:/);
    const digests = journal.ofType("digest_emitted");
    assert.equal(digests.length, 1, "only the final diagnostic digest may be emitted");
    assert.equal((digests[0] as typeof digests[number] & { final?: boolean }).final, true);
    const digest = fs.readFileSync(digests[0].path, "utf-8");
    assert.match(digest, /Preflight: ok=false; breaks=1; unreadable=0/);
    assert.ok(!digest.includes("nodes: 1 known"), "a broken ledger cannot supply healthy mission state");
  });
}

for (const boundary of ["dry_run", "max_waves", "next_wave", "commit_failure"] as const) {
  test(`${boundary} rechecks ledgers after a commit hook corrupts claims`, async t => {
    const { repo, journal } = toyRepo(t);
    await seedNode(repo, "hypothesis");
    const hook = boundary === "commit_failure" ? "pre-commit" : "post-commit";
    const claimsDir = `results/ledgers/claim/paper_${P}`;
    fs.writeFileSync(path.join(repo, ".git/hooks", hook),
      `#!/bin/sh\nmkdir -p ${claimsDir}\nprintf '%s' '{"entry_id":' > ${claimsDir}/entries.jsonl\n` +
      (boundary === "commit_failure" ? "exit 1\n" : ""), { mode: 0o755 });
    assert.equal(await run(repo, {
      dryRun: boundary === "dry_run", maxWaves: boundary === "next_wave" ? 2 : 1,
    }), 9);
    assertIntegrityHalt(journal, /ledger_unreadable:.*claims_database.py query.*(JSON|incomplete tail)/);
    assert.ok(journal.ofType("task_assigned").every(m => m.wave === 1));
  });
}
