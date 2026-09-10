/** Exercise the real CLI boundary with hermetic executables, never an API. */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test, type TestContext } from "node:test";
import { fileURLToPath } from "node:url";
import { CodexJobRunner, CodexWorkerRunner, jobPrompt, workerPrompt } from "../src/agents.js";
import { codexDefaults } from "../src/codex.js";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import { buildRunners } from "../src/main.js";
import { runtimeDir } from "../src/runtime.js";
import { runWave } from "../src/scheduler.js";
import type { WorkerTask } from "../src/types.js";
import {
  adjudicateCandidate, buildValidatorRunner, checkIsolation, CodexValidatorRunner,
  judgePrompt, refuterPrompt, SdkValidatorRunner, type ContextPack,
} from "../src/validator.js";

const P = "arxiv-9999.12345";
const MODEL = "gpt-6-astra";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function env(t: TestContext, key: string, value: string): void {
  const old = process.env[key];
  process.env[key] = value;
  t.after(() => {
    if (old === undefined) delete process.env[key];
    else process.env[key] = old;
  });
}

function fixture(t: TestContext, body = 'printf "FAKE OK" > "$final"') {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-codex-test-"));
  const repo = path.join(root, "repo");
  const runtime = path.join(root, "runtime");
  const bin = path.join(root, "fake codex"); // spaces must survive spawn arguments
  fs.mkdirSync(repo);
  env(t, "CHANDRA_RUNTIME", runtime);
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const writeFake = (action: string) => fs.writeFileSync(bin, [
    "#!/usr/bin/env bash",
    "set -eu",
    'capture_dir=$(dirname "$0")',
    'printf "%s\\n" "$@" >> "$capture_dir/argv.txt"',
    // cat reaches EOF only if the runner closes stdin after writing the prompt.
    'cat > "$capture_dir/stdin.txt"',
    'env | grep "^CHANDRA_ROLE=" > "$capture_dir/env.txt"',
    'pwd > "$capture_dir/cwd.txt"',
    'final=""',
    'while [ "$#" -gt 0 ]; do',
    '  if [ "$1" = "-o" ]; then final=$2; shift; fi',
    "  shift",
    "done",
    'printf "stdout transcript\\n"',
    'printf "stderr transcript\\n" >&2',
    action,
    "",
  ].join("\n"), { mode: 0o755 });
  writeFake(body);
  const read = (file: string) => fs.readFileSync(path.join(root, file), "utf-8");
  const node = {
    id: `${P}::node/with spaces`, paper: P, status: "hypothesis" as const,
    summary: "boundary term", predecessors: [], openObligations: [], depth: 0,
  };
  const task: WorkerTask = { wave: 2, node, packet: [node], paper: P, repoRoot: repo };
  const pack: ContextPack = { dir: path.join(root, "pack"), manifest: {} };
  fs.mkdirSync(pack.dir);
  fs.writeFileSync(path.join(pack.dir, "MANIFEST.json"), "{}");
  return { root, repo, runtime, bin, task, pack, read, writeFake };
}

test("CodexWorkerRunner sends the whole prompt and EOF, role, model and defaults; keeps runtime artifacts", async t => {
  const f = fixture(t);
  env(t, "CODEX_BIN", f.bin);
  env(t, "CHANDRA_ROLE", "observer");
  const result = await new CodexWorkerRunner({ model: MODEL }).runWorker(f.task);
  const dir = runtimeDir(f.repo, `paper_${P}`, "codex");
  const safeId = `w2-${f.task.node.id}`.replace(/[^A-Za-z0-9_.-]/g, "_");
  assert.deepEqual(f.read("argv.txt").trim().split("\n"), [
    "exec", "-m", MODEL, "-c", 'model_reasoning_effort="max"', "-s", "danger-full-access",
    "--skip-git-repo-check", "-o", path.join(dir, `${safeId}.final.md`), "-",
  ]);
  const prompt = f.read("stdin.txt");
  assert.ok(prompt.endsWith(workerPrompt(f.task)));
  assert.ok(prompt.includes(f.task.node.id));
  assert.match(prompt, /alignment\.md/);
  assert.match(prompt, /research_admission_contract\.md/);
  assert.match(prompt, /\.claude\/skills\/INDEX\.md/);
  assert.match(prompt, /reading its SKILL\.md/);
  assert.match(prompt, /Never run git commit/);
  assert.match(prompt, /only the ledger diff counts/);
  assert.equal(f.read("env.txt").trim(), "CHANDRA_ROLE=worker");
  assert.equal(f.read("cwd.txt").trim(), f.repo);
  assert.deepEqual(result, { detail: `codex model=${MODEL} exit=0 tail=FAKE OK`, windowsUsed: 1 });
  assert.equal(fs.readFileSync(path.join(dir, `${safeId}.final.md`), "utf-8"), "FAKE OK");
  const log = fs.readFileSync(path.join(dir, `${safeId}.log`), "utf-8");
  assert.match(log, /stdout transcript/);
  assert.match(log, /stderr transcript/);
  assert.deepEqual(fs.readdirSync(f.repo), [], "diaries stay outside the repo");
  assert.equal(codexDefaults("worker").timeoutSeconds, 3600);
});

test("CodexWorkerRunner rejects a nonzero exit with the last 300 log characters", async t => {
  const f = fixture(t, 'printf "%0600d" 0; printf "FAILURE TAIL" >&2; exit 3');
  await assert.rejects(new CodexWorkerRunner({ bin: f.bin, model: MODEL }).runWorker(f.task), e => {
    assert.ok(e instanceof Error);
    assert.match(e.message, /exit=3/);
    assert.ok(e.message.endsWith("0".repeat(288) + "FAILURE TAIL"));
    assert.equal(e.message.split("tail=")[1].length, 300);
    return true;
  });
});

for (const ignoresTerm of [false, true]) {
  test(`CodexWorkerRunner timeout rejects in under 3s (ignores SIGTERM: ${ignoresTerm})`, async t => {
    const f = fixture(t, `${ignoresTerm ? "trap '' TERM\n" : ""}sleep 30 &\nwait`);
    const started = Date.now();
    await assert.rejects(
      new CodexWorkerRunner({ bin: f.bin, model: MODEL, timeoutSeconds: 1 }).runWorker(f.task),
      /timed out after 1s/);
    assert.ok(Date.now() - started < 3000, `timeout took ${Date.now() - started}ms`);
  });
}

test("CodexWorkerRunner handles spawn failure and early stdin closure", async t => {
  const f = fixture(t);
  await assert.rejects(
    new CodexWorkerRunner({ bin: path.join(f.root, "missing") }).runWorker(f.task),
    /failed to spawn.*ENOENT/);
  fs.writeFileSync(f.bin, "#!/usr/bin/env bash\nprintf 'early exit' >&2\nexit 3\n");
  await assert.rejects(
    new CodexWorkerRunner({ bin: f.bin }).runWorker({ ...f.task, steer: "x".repeat(1_000_000) }),
    /exit=3.*early exit/);
});

test("Codex final prose cannot admit a node, and CLI failures reach the scheduler", async t => {
  const f = fixture(t);
  const ledgers = { async snapshot() {
    return { statusByNode: {}, resultsByNode: {}, openObligationsByNode: {} };
  } } as unknown as Ledgers;
  const journal = new Journal(path.join(f.runtime, "journal.jsonl"));
  const plan = { wave: 2, ready: [f.task.node.id], scheduled: f.task.packet, packets: [f.task.packet] };
  const deps = { ledgers, journal, paper: P, repoRoot: f.repo,
                 runner: new CodexWorkerRunner({ bin: f.bin, model: MODEL }) };
  const successful = await runWave(plan, deps);
  assert.equal(successful.noProgress, 1);
  assert.equal(successful.admitted, 0);
  f.writeFake("exit 3");
  const failed = await runWave(plan, deps);
  assert.equal(failed.failed, 1);
  assert.match(failed.reports[0].detail, /exit=3/);
});

for (const kind of ["decompose", "acquire", "write-refresh"] as const) {
  test(`CodexJobRunner reuses the ${kind} prompt and worker role`, async t => {
    const f = fixture(t);
    const job = { kind, id: `${kind}:${P}` };
    const ctx = { repoRoot: f.repo, paper: P, wave: 4 };
    const runner = new CodexJobRunner({ bin: f.bin, model: MODEL });
    const result = await runner.run(job, ctx);
    assert.ok(f.read("stdin.txt").endsWith(jobPrompt(job, ctx)));
    assert.ok(f.read("stdin.txt").includes(P));
    if (kind === "decompose") assert.match(f.read("stdin.txt"), /DECOMPOSE/);
    assert.equal(f.read("env.txt").trim(), "CHANDRA_ROLE=worker");
    assert.equal(f.read("cwd.txt").trim(), f.repo);
    assert.match(result.detail, /FAKE OK/);
    assert.equal(result.windowsUsed, 1);
    const artifacts = fs.readdirSync(runtimeDir(f.repo, `paper_${P}`, "codex"));
    assert.ok(artifacts.some(p => p.endsWith(".log")));
    assert.ok(artifacts.some(p => p.endsWith(".final.md")));
    assert.ok(artifacts.every(p => /^[A-Za-z0-9_.-]+$/.test(p)));
  });
}

test("buildRunners forwards mission codex options and reports the final message tail", async t => {
  const f = fixture(t, 'printf "%0250d" 0 > "$final"; printf "END" >> "$final"');
  env(t, "CODEX_BIN", path.join(f.root, "must-not-run"));
  const selected = buildRunners({
    paper: P, models: { worker: "codex:x", jobs: "codex:y" },
    codex: { bin: f.bin, effort: "high", sandbox: "workspace-write", timeoutSeconds: 2 },
  }, false);
  const worker = await selected.runner.runWorker(f.task);
  assert.equal(worker.detail, `codex model=x exit=0 tail=${"0".repeat(197)}END`);
  const args = f.read("argv.txt").trim().split("\n");
  assert.equal(args[args.indexOf("-m") + 1], "x");
  assert.equal(args[args.indexOf("-c") + 1], 'model_reasoning_effort="high"');
  assert.equal(args[args.indexOf("-s") + 1], "workspace-write");
  const job = await selected.jobRunners!.decompose!.run(
    { kind: "decompose", id: "decompose:P" }, { repoRoot: f.repo, paper: P, wave: 2 });
  assert.match(job.detail, /codex model=y/);
});

test("CodexValidatorRunner uses shared prompts, separate models, pack cwd and read-only sandbox", async t => {
  const f = fixture(t);
  const runner = new CodexValidatorRunner({ bin: f.bin, refuterModel: "refute-model", judgeModel: MODEL });
  assert.deepEqual(await runner.refute(f.pack, "boundary = 0"), { findings: "FAKE OK" });
  assert.equal(f.read("stdin.txt"), refuterPrompt("boundary = 0"));
  assert.match(f.read("argv.txt"), /-m\nrefute-model\n/);
  f.writeFake('printf \'{"verdict":"admit","reasons":"checks hold"}\' > "$final"');
  assert.deepEqual(await runner.judge(f.pack, "boundary = 0", "attempted units check"),
    { verdict: "admit", reasons: "checks hold" });
  assert.equal(f.read("stdin.txt"), judgePrompt("boundary = 0", "attempted units check"));
  assert.match(f.read("argv.txt"), /-m\ngpt-6-astra\n/);
  assert.match(f.read("argv.txt"), /-s\nread-only\n/);
  assert.equal(f.read("cwd.txt").trim(), f.pack.dir);
  assert.equal(f.read("env.txt").trim(), "CHANDRA_ROLE=validator");
  assert.ok(checkIsolation(f.pack).ok, "transcripts must not contaminate the pack");
  // Reusing a pack cannot admit using a previous invocation's final JSON.
  f.writeFake("exit 0");
  assert.equal((await runner.judge(f.pack, "boundary = 0", "check again")).verdict, "reject");
});

test("validator factory dispatches mixed families independently without calling the other SDK role", async t => {
  const f = fixture(t, 'printf \'{"verdict":"admit","reasons":"checked"}\' > "$final"');
  const refute = t.mock.method(SdkValidatorRunner.prototype, "refute", async () => ({ findings: "SDK refutation" }));
  const judge = t.mock.method(SdkValidatorRunner.prototype, "judge", async () => ({ verdict: "reject" as const, reasons: "SDK judgment" }));
  const sdkJudge = buildValidatorRunner({ paper: P, models: { refuter: `codex:${MODEL}` },
    codex: { bin: f.bin, sandbox: "danger-full-access" } });
  await sdkJudge.refute(f.pack, "claim");
  assert.equal(refute.mock.callCount(), 0);
  assert.match(f.read("argv.txt"), /-s\ndanger-full-access\n/);
  assert.equal((await sdkJudge.judge(f.pack, "claim", "findings")).verdict, "reject");
  assert.equal(judge.mock.callCount(), 1);
  const sdkRefuter = buildValidatorRunner({ paper: P, models: { judge: `codex:${MODEL}` }, codex: { bin: f.bin } });
  assert.deepEqual(await sdkRefuter.refute(f.pack, "claim"), { findings: "SDK refutation" });
  assert.equal((await sdkRefuter.judge(f.pack, "claim", "findings")).verdict, "admit");
  assert.equal(refute.mock.callCount(), 1);
  assert.equal(judge.mock.callCount(), 1);
});

test("adjudicateCandidate selects validators from mission.json and still executes the ledger gate", async t => {
  const f = fixture(t, [
    'if grep -q "admission JUDGE" "$capture_dir/stdin.txt"; then',
    '  printf \'{"verdict":"admit","reasons":"checks hold"}\' > "$final"',
    "else",
    '  printf "Tried the boundary and units checks" > "$final"',
    "fi",
  ].join("\n"));
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(f.repo, "_common"));
  for (const rel of ["alignment.md", "pipelines/2-work/spec.md"]) {
    fs.mkdirSync(path.dirname(path.join(f.repo, rel)), { recursive: true });
    fs.copyFileSync(path.join(REPO_ROOT, rel), path.join(f.repo, rel));
  }
  fs.writeFileSync(path.join(f.repo, "mission.json"), JSON.stringify({ paper: P,
    models: { refuter: "codex:refute-model", judge: `codex:${MODEL}` }, codex: { bin: f.bin } }));
  fs.writeFileSync(path.join(f.repo, ".delegation-policy"), "strict\n");
  fs.writeFileSync(path.join(f.repo, "evidence.txt"), "verified boundary = 0\n");
  const ledgers = new Ledgers(f.repo, "validator");
  const candidate = {
    paper: P, node: "P::n1", wave: 1, claim: "boundary = 0", evidencePaths: ["evidence.txt"],
    resultRow: { paper: P, result_id: "r1", name: "boundary", working_context: "toy",
      claim: "boundary = 0", evidence_type: "symbolic_derivation", evidence: "evidence.txt",
      verifier_result: { verdict: "pass" }, dependencies: [], assumptions: [], status: "checked",
      provenance: "validator-test", open_obligations: [], verification: { command: "true" },
      node_ids: ["P::n1"] },
  };
  const deps = { repoRoot: f.repo, ledgers, journal: new Journal(path.join(f.runtime, "validation.jsonl")) };
  assert.equal((await adjudicateCandidate(candidate, deps)).outcome, "admitted");
  assert.equal((await ledgers.results(P)).length, 1);
  candidate.resultRow.result_id = "r2";
  candidate.resultRow.verification.command = "false";
  assert.equal((await adjudicateCandidate(candidate, deps)).outcome, "gate_rejected");
  assert.equal((await ledgers.results(P)).length, 1);
});
