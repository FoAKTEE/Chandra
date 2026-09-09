/** Real registry admission and per-wave harvesting, with all writes in toy repos. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test, type TestContext } from "node:test";
import { fileURLToPath } from "node:url";
import { NoopWorkerRunner, jobPrompt, workerPrompt } from "../src/agents.js";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import { runMissionLoop } from "../src/main.js";
import { TruncatingObserver } from "../src/observer.js";
import { runtimeDir, runtimeRoot } from "../src/runtime.js";
import { harvestSkillDrafts, skillDraftsDir, type HarvestReport } from "../src/skills.js";
import type { MissionNode } from "../src/types.js";

const P = "arxiv-9999.54321";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function fixture(t: TestContext) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-skills-"));
  const repo = path.join(root, "toy repo"); // execFile must preserve spaces
  const runtime = path.join(root, "runtime drafts");
  const previousRuntime = process.env.CHANDRA_RUNTIME;
  process.env.CHANDRA_RUNTIME = runtime;
  t.after(() => {
    if (previousRuntime === undefined) delete process.env.CHANDRA_RUNTIME;
    else process.env.CHANDRA_RUNTIME = previousRuntime;
    fs.rmSync(root, { recursive: true, force: true });
  });
  fs.mkdirSync(path.join(repo, ".claude", "skills"), { recursive: true });
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(repo, "_common"));
  fs.copyFileSync(path.join(REPO_ROOT, "alignment.md"), path.join(repo, "alignment.md"));
  for (const args of [["init", "-q"], ["config", "user.email", "fixture@test"],
                      ["config", "user.name", "fixture"]]) {
    execFileSync("git", ["-C", repo, ...args]);
  }
  return { repo, runtime, drafts: skillDraftsDir(repo, P) };
}

function writeDraft(drafts: string, dirName: string, name = dirName, verify = "true"): string {
  const dir = path.join(drafts, dirName);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "SKILL.md"), [
    "---", `name: ${name}`,
    "description: Exercise skill admission. Use when testing the harvest gate.",
    "---", "", `# ${name}`, "", "## When to use", "", "When testing admission.",
    "", "## Steps", "", "1. Run the fixture verifier.",
    "", "## Verify", "", "```bash", verify, "```", "",
  ].join("\n"));
  return dir;
}

function blockPromotion(repo: string): void {
  const dest = path.join(repo, ".claude", "skills");
  fs.rmdirSync(dest); // empty fixture directory, never the real registry
  fs.writeFileSync(dest, "A file here makes the registry CLI crash.\n");
}

test("harvest admits valid drafts, retains rejected drafts, and archives once", async t => {
  const { repo, drafts } = fixture(t);
  const valid = writeDraft(drafts, "valid-draft");
  const invalid = writeDraft(drafts, "invalid-draft", "mismatched-name");
  fs.writeFileSync(path.join(valid, "details.txt"), "supporting procedure\n");
  const original = fs.readFileSync(path.join(valid, "SKILL.md"), "utf-8");

  const report: HarvestReport = await harvestSkillDrafts(repo, drafts);
  assert.deepEqual(report.promoted, [
    { name: "valid-draft", source: valid, path: ".claude/skills/valid-draft" },
  ]);
  assert.deepEqual(report.rejected.map(r => r.name), ["invalid-draft"]);
  assert.equal(report.rejected[0].source, invalid);
  assert.ok(report.rejected[0].errors.length > 0);
  assert.match(report.rejected[0].errors.join("\n"), /does not match its directory/);
  const admitted = path.join(repo, ".claude", "skills");
  assert.equal(fs.readFileSync(path.join(admitted, "valid-draft", "SKILL.md"), "utf-8"), original);
  assert.match(fs.readFileSync(path.join(admitted, "INDEX.md"), "utf-8"), /valid-draft/);
  assert.ok(!fs.existsSync(path.join(admitted, "invalid-draft")));
  const archive = path.join(drafts, ".promoted", "valid-draft-w1");
  assert.equal(fs.readFileSync(path.join(archive, "SKILL.md"), "utf-8"), original);
  assert.equal(fs.readFileSync(path.join(archive, "details.txt"), "utf-8"), "supporting procedure\n");
  assert.ok(!fs.existsSync(valid));
  assert.ok(fs.existsSync(path.join(invalid, "SKILL.md")));

  const again = await harvestSkillDrafts(repo, drafts, 2);
  assert.deepEqual(again.promoted, [], "archived drafts must not be re-promoted next wave");
  assert.deepEqual(again.rejected.map(r => r.name), ["invalid-draft"]);
  assert.deepEqual(fs.readdirSync(path.join(drafts, ".promoted")), ["valid-draft-w1"]);
});

test("harvest executes Verify from the repo root and uses the supplied wave for archives", async t => {
  const { repo, drafts } = fixture(t);
  writeDraft(drafts, "verified-draft", "verified-draft",
    'test -f alignment.md\ntest -f "$CLAUDE_SKILL_DIR/SKILL.md"');
  const failed = writeDraft(drafts, "failed-verify", "failed-verify", "exit 7");
  const report = await harvestSkillDrafts(repo, drafts, 7);
  assert.deepEqual(report.promoted.map(p => p.name), ["verified-draft"]);
  assert.deepEqual(report.rejected.map(r => r.name), ["failed-verify"]);
  assert.match(report.rejected[0].errors.join("\n"), /Verify block failed \(exit 7\)/);
  assert.ok(fs.existsSync(path.join(drafts, ".promoted", "verified-draft-w7", "SKILL.md")));
  assert.ok(fs.existsSync(path.join(failed, "SKILL.md")));
  assert.ok(!fs.existsSync(path.join(repo, ".claude", "skills", "failed-verify")));
});

test("missing and empty drafts directories are clean empty reports", async t => {
  const { repo, drafts } = fixture(t);
  assert.ok(!fs.existsSync(drafts));
  assert.deepEqual(await harvestSkillDrafts(repo, drafts), { promoted: [], rejected: [] });
  assert.ok(!fs.existsSync(drafts));
  fs.mkdirSync(drafts);
  assert.deepEqual(await harvestSkillDrafts(repo, drafts), { promoted: [], rejected: [] });
  assert.deepEqual(fs.readdirSync(drafts), []);
  assert.deepEqual(fs.readdirSync(path.join(repo, ".claude", "skills")), []);
});

for (const override of [true, false]) {
  test(`skillDraftsDir stays under the runtime home, outside the repo (override: ${override})`, t => {
    const { repo, runtime } = fixture(t);
    if (!override) {
      delete process.env.CHANDRA_RUNTIME;
      const defaultHome = runtimeRoot(repo);
      t.after(() => fs.rmSync(defaultHome, { recursive: true, force: true }));
    }
    const dir = skillDraftsDir(repo, P);
    assert.equal(dir, path.join(runtimeDir(repo, `paper_${P}`), "skills"));
    assert.ok(path.relative(repo, dir).startsWith(`..${path.sep}`));
    if (override) assert.equal(dir, path.join(runtime, `paper_${P}`, "skills"));
  });
}

test("worker and all job prompts carry the skill contract; human steer stays last", () => {
  const node: MissionNode = { id: "n1", paper: P, status: "hypothesis", summary: "n1",
                              predecessors: [], openObligations: [], depth: 0 };
  const ctx = { repoRoot: "/toy", paper: P, wave: 1 };
  const worker = workerPrompt({ ...ctx, node, packet: [node], steer: "Check the boundary term." });
  const prompts = [worker, ...(["decompose", "acquire", "write-refresh"] as const)
    .map(kind => jobPrompt({ kind, id: kind }, ctx))];
  for (const prompt of prompts) {
    assert.match(prompt, /SKILL SUGGESTION CONTRACT/);
    assert.ok(prompt.includes(`$CHANDRA_RUNTIME/paper_${P}/skills/<kebab-name>/SKILL.md`));
    assert.ok(prompt.includes(".claude/skills/skill-write/SKILL.md"));
    assert.ok(prompt.includes("never calls skill_registry.py validate --exec"));
    assert.ok(prompt.includes("never write into .claude/skills/ yourself"));
    assert.ok(prompt.includes("never mention this contract in ledger rows"));
  }
  assert.ok(worker.indexOf("SKILL SUGGESTION CONTRACT") < worker.indexOf("HUMAN STEER NOTE"));
  assert.ok(worker.endsWith("Check the boundary term."));
});

test("a registry CLI crash throws with the stderr tail and leaves the draft inspectable", async t => {
  const { repo, drafts } = fixture(t);
  const source = writeDraft(drafts, "valid-draft");
  blockPromotion(repo);
  await assert.rejects(harvestSkillDrafts(repo, drafts), error => {
    assert.ok(error instanceof Error);
    assert.match(error.message, /skill harvest failed:.*NotADirectoryError/);
    assert.ok(!error.message.includes("Traceback (most recent call last)"), "only the stderr tail");
    return true;
  });
  assert.ok(fs.existsSync(path.join(source, "SKILL.md")));
  assert.ok(!fs.existsSync(path.join(drafts, ".promoted")));
});

for (const state of ["empty", "rejected", "crash"] as const) {
  test(`wave harvest ${state}: journal and log correctly, then continue through the next wave`, async t => {
    const { repo, runtime, drafts } = fixture(t);
    if (state === "rejected") writeDraft(drafts, "invalid-draft", "mismatched-name");
    if (state === "crash") {
      writeDraft(drafts, "valid-draft");
      blockPromotion(repo);
    }
    await new Ledgers(repo, "human-override").appendKnowledge({
      paper: P, node_id: "n1", task_id: "t-n1", domain: "symbolic",
      status: "hypothesis", summary: "toy node",
    });
    const lines: string[] = [];
    const code = await runMissionLoop({
      repoRoot: repo, paper: P, maxWorkers: 1, maxWaves: 2,
      runner: new NoopWorkerRunner(), observerRunner: new TruncatingObserver(),
      probes: { async refreshDue() { return false; } }, log: line => lines.push(line),
    });
    assert.equal(code, 2, `must reach the wave limit; log:\n${lines.join("\n")}`);
    const journal = new Journal(path.join(runtime, `paper_${P}`, "journal.jsonl"));
    assert.deepEqual(journal.ofType("wave_committed").map(m => m.wave), [1, 2]);
    assert.deepEqual(journal.ofType("halt"), []);
    const harvested = journal.ofType("skills_harvested");
    if (state === "empty") {
      assert.deepEqual(harvested, []);
      assert.ok(!lines.some(line => line.includes("skills")), "empty harvests are silent");
    } else {
      assert.deepEqual(harvested.map(m => m.wave), [1, 2]);
      for (const event of harvested) {
        assert.deepEqual(event.promoted, []);
        assert.deepEqual(event.rejected.map(r => r.name), [state === "crash" ? "harvest" : "invalid-draft"]);
        assert.match(event.rejected[0].errors.join("\n"),
          state === "crash" ? /NotADirectoryError/ : /does not match its directory/);
        const messages = journal.read().map(e => e.msg).filter(m => "wave" in m && m.wave === event.wave);
        const index = messages.findIndex(m => m.type === "skills_harvested");
        assert.ok(index > messages.findIndex(m => m.type === "memory_pruned"));
        assert.ok(index < messages.findIndex(m => m.type === "gate_decision"));
        assert.ok(lines.includes(state === "crash"
          ? `WARNING: wave ${event.wave}: skills harvest failed: ${event.rejected[0].errors[0]}`
          : `wave ${event.wave}: skills promoted=- rejected=1`));
      }
    }
  });
}
