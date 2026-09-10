/** Binding regressions use scripted reviewers and the real gated Python ledgers. */
import assert from "node:assert/strict";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test, type TestContext } from "node:test";
import { fileURLToPath } from "node:url";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import * as validator from "../src/validator.js";
import type { CandidateSubmission, ContextPack, ValidatorRunner } from "../src/validator.js";

const P = "arxiv-0000.00000";
const Q = "arxiv-0000.00001";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const WORK_ROOT = path.join(os.tmpdir(), "chandra", "work", "validator-binding");
const FINDINGS = "Checked boundary assumptions, units, and the stated regime. ".repeat(30) + "END OF FULL FINDINGS";

function fixture(t: TestContext) {
  fs.mkdirSync(WORK_ROOT, { recursive: true });
  const root = fs.mkdtempSync(path.join(WORK_ROOT, "case-"));
  const repoRoot = path.join(root, "repo");
  const packRoot = path.join(root, "packs");
  fs.mkdirSync(repoRoot);
  fs.mkdirSync(packRoot);
  const oldRuntime = process.env.CHANDRA_RUNTIME;
  const oldTmp = process.env.TMPDIR;
  process.env.CHANDRA_RUNTIME = path.join(root, "runtime");
  process.env.TMPDIR = packRoot;
  t.after(() => {
    if (oldRuntime === undefined) delete process.env.CHANDRA_RUNTIME;
    else process.env.CHANDRA_RUNTIME = oldRuntime;
    if (oldTmp === undefined) delete process.env.TMPDIR;
    else process.env.TMPDIR = oldTmp;
    fs.rmSync(root, { recursive: true, force: true });
  });
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(repoRoot, "_common"));
  for (const rel of ["alignment.md", "pipelines/2-work/spec.md"]) {
    fs.mkdirSync(path.dirname(path.join(repoRoot, rel)), { recursive: true });
    fs.copyFileSync(path.join(REPO_ROOT, rel), path.join(repoRoot, rel));
  }
  fs.writeFileSync(path.join(repoRoot, ".delegation-policy"), "strict\n");
  fs.mkdirSync(path.join(repoRoot, "artifacts"));
  fs.writeFileSync(path.join(repoRoot, "artifacts/out.txt"), "residual 1e-9 PASS\n");
  return {
    root, repoRoot, packRoot,
    ledgers: new Ledgers(repoRoot, "validator"),
    journal: new Journal(path.join(root, "journal.jsonl")),
  };
}

function candidate(): CandidateSubmission {
  return {
    paper: P, node: "P::n1", wave: 1, claim: "the boundary term vanishes",
    evidencePaths: ["artifacts/out.txt"],
    resultRow: {
      paper: P, result_id: "r-n1", name: "boundary term", working_context: "toy",
      claim: "the boundary term vanishes", node_ids: ["P::n1"],
      evidence_type: "symbolic_derivation", evidence: "artifacts/out.txt",
      verifier_result: { verdict: "pass" }, dependencies: [], assumptions: [],
      status: "checked", provenance: "binding-test", open_obligations: [],
    },
  };
}

function scripted(raw = '{"verdict":"admit","reasons":"evidence holds"}'): ValidatorRunner {
  return {
    name: "scripted-binding",
    async refute() { return { findings: FINDINGS }; },
    async judge(_pack, _claim, findings, captureRaw?: (output: string) => void) {
      assert.equal(findings, FINDINGS);
      captureRaw?.(raw);
      return validator.parseJudgeVerdict(raw);
    },
  };
}

async function bindingFailure(t: TestContext, change: (c: CandidateSubmission) => void) {
  const f = fixture(t);
  const c = candidate();
  change(c);
  const runner = scripted();
  const refute = t.mock.method(runner, "refute");
  await assert.rejects(validator.adjudicateCandidate(c, { ...f, runner }),
    { name: "ValidationBindingError" });
  assert.equal(refute.mock.callCount(), 0, "binding must fail before review");
  assert.deepEqual(fs.readdirSync(f.packRoot), [], "binding must fail before building a pack");
  assert.deepEqual(await f.ledgers.results(P), []);
  assert.deepEqual(await f.ledgers.results(Q), []);
  assert.deepEqual(await f.ledgers.claims(P), []);
  assert.deepEqual(f.journal.read(), []);
}

test("binding (a): another paper's result throws before any append", async t => {
  await bindingFailure(t, c => { c.resultRow.paper = Q; });
});

test("binding (b): an opposite result claim throws before any append", async t => {
  await bindingFailure(t, c => { c.resultRow.claim = "the boundary term does not vanish"; });
});

for (const [label, nodes] of [
  ["unrelated", ["P::other"]], ["missing", undefined], ["empty", []], ["not an array", "P::n1"],
] as const) {
  test(`binding (c): ${label} node_ids throws before any append`, async t => {
    await bindingFailure(t, c => {
      if (nodes === undefined) delete c.resultRow.node_ids;
      else c.resultRow.node_ids = nodes;
    });
  });
}

test("binding (d): judge-time mutation cannot change the row admitted to the ledger", async t => {
  const f = fixture(t);
  const c = candidate();
  const frozen = structuredClone(c);
  const runner = scripted();
  runner.judge = async () => {
    c.paper = Q;
    c.node = "Q::other";
    c.wave = 99;
    c.claim = "the opposite claim";
    c.resultRow.paper = Q;
    c.resultRow.claim = c.claim;
    (c.resultRow.node_ids as string[]).push("Q::other");
    (c.resultRow.verifier_result as Record<string, unknown>).detail = "changed after review";
    return { verdict: "admit", reasons: "evidence holds" };
  };
  const result = await validator.adjudicateCandidate(c, { ...f, runner });
  assert.equal(result.outcome, "admitted");
  const rows = await f.ledgers.results(P);
  assert.equal(rows.length, 1, "the reviewed paper must receive the frozen row");
  assert.deepEqual(Object.fromEntries(Object.keys(frozen.resultRow).map(key => [key, rows[0][key]])),
    frozen.resultRow, "the gate may enrich the row, but every submitted field must match");
  assert.deepEqual(await f.ledgers.results(Q), []);
  assert.equal(f.journal.ofType("validation_verdict")[0].node, frozen.node);
});

for (const kind of ["parent traversal", "symlink escape", "absolute path"] as const) {
  test(`binding (e): ${kind} fails before copying any evidence`, async t => {
    const f = fixture(t);
    const outside = path.join(f.root, "outside.txt");
    fs.writeFileSync(outside, "outside sentinel\n");
    const c = candidate();
    let badPath: string;
    if (kind === "symlink escape") {
      fs.symlinkSync(outside, path.join(f.repoRoot, "artifacts/link.txt"));
      badPath = "artifacts/link.txt";
    } else {
      badPath = kind === "parent traversal" ? "../outside.txt" : outside;
      // The old path.join implementation prepends repoRoot even to an absolute input.
      if (kind === "absolute path") {
        const oldSource = path.join(f.repoRoot, badPath);
        fs.mkdirSync(path.dirname(oldSource), { recursive: true });
        fs.writeFileSync(oldSource, "absolute path must still be rejected\n");
      }
    }
    c.evidencePaths.push(badPath); // validate the whole list before copying its valid first entry
    const runner = scripted();
    const refute = t.mock.method(runner, "refute");
    await assert.rejects(validator.adjudicateCandidate(c, { ...f, runner }),
      { name: "ValidationBindingError" });
    assert.deepEqual(fs.readdirSync(f.packRoot), [], "no pack or escaped copy may remain");
    assert.equal(fs.readFileSync(outside, "utf-8"), "outside sentinel\n");
    assert.equal(refute.mock.callCount(), 0);
    assert.deepEqual(await f.ledgers.results(P), []);
  });
}

for (const kind of ["refuter adds a file", "judge changes evidence", "refuter rewrites the manifest"] as const) {
  test(`binding (f): ${kind} aborts with pack_tampered, without a verdict`, async t => {
    const f = fixture(t);
    const runner = scripted();
    if (kind === "judge changes evidence") {
      runner.judge = async pack => {
        fs.appendFileSync(path.join(pack.dir, "artifacts/out.txt"), "changed\n");
        return { verdict: "admit", reasons: "evidence holds" };
      };
    } else {
      runner.refute = async pack => {
        if (kind === "refuter adds a file") {
          fs.writeFileSync(path.join(pack.dir, "extra.txt"), "unreviewed input\n");
        } else {
          const content = "forged evidence\n";
          fs.writeFileSync(path.join(pack.dir, "artifacts/out.txt"), content);
          pack.manifest["artifacts/out.txt"] = crypto.createHash("sha256").update(content).digest("hex");
          fs.writeFileSync(path.join(pack.dir, "MANIFEST.json"), JSON.stringify(pack.manifest, null, 2));
        }
        return { findings: FINDINGS };
      };
    }
    const judge = t.mock.method(runner, "judge");
    await assert.rejects(validator.adjudicateCandidate(candidate(), { ...f, runner }), /pack_tampered/);
    if (kind !== "judge changes evidence") assert.equal(judge.mock.callCount(), 0);
    assert.ok(f.journal.read().some(entry => JSON.stringify(entry.msg).includes("pack_tampered")));
    assert.deepEqual(f.journal.ofType("validation_verdict"), []);
    assert.deepEqual(await f.ledgers.results(P), []);
    assert.deepEqual(await f.ledgers.claims(P), []);
    assert.deepEqual(fs.readdirSync(f.packRoot), []);
  });
}

for (const [label, reasons] of [
  ["missing", undefined], ["null", null], ["number", 7], ["object", {}], ["empty", ""], ["blank", " \n\t "],
] as const) {
  test(`binding (g): ${label} judge reasons fail closed with the specified reason`, () => {
    assert.deepEqual(validator.parseJudgeVerdict(JSON.stringify({ verdict: "admit", reasons })),
      { verdict: "reject", reasons: "judge gave no reasons" });
  });
}

test("binding (g): an admit without reasons creates a repair obligation instead of a result", async t => {
  const f = fixture(t);
  const outcome = await validator.adjudicateCandidate(candidate(), {
    ...f, runner: scripted('{"verdict":"admit"}'),
  });
  assert.deepEqual(outcome, { outcome: "rejected", detail: "judge gave no reasons" });
  assert.deepEqual(await f.ledgers.results(P), []);
  assert.equal((await f.ledgers.claims(P))[0].statement, "validation rejected: judge gave no reasons");
});

interface RetainedReview {
  candidateHash: string;
  candidate: CandidateSubmission;
  manifest: Record<string, string>;
  refuterFindings: string;
  judgeRawOutput: string;
  verdict: { verdict: "admit" | "reject"; reasons: string };
  appendedRow: Record<string, unknown> | null;
  rejectionObligation: Record<string, unknown> | null;
  startedAt: string;
  refutedAt: string;
  judgedAt: string;
  finishedAt: string;
}

for (const verdict of ["admit", "reject"] as const) {
  test(`binding (h): ${verdict} retains the full review, candidate hash, row, and journal link`, async t => {
    const f = fixture(t);
    const c = candidate();
    c.node = "P::node/with spaces";
    c.resultRow.node_ids = [c.node];
    const raw = `Judge transcript before JSON\n${JSON.stringify({ verdict, reasons: "checked the complete findings" })}\nEND OF RAW OUTPUT`;
    const runner = scripted(raw);
    let originalPack: ContextPack | undefined;
    let claimText = "";
    runner.refute = async pack => {
      originalPack = structuredClone(pack);
      claimText = fs.readFileSync(path.join(pack.dir, "CLAIM.md"), "utf-8");
      return { findings: FINDINGS };
    };
    const outcome = await validator.adjudicateCandidate(c, { ...f, runner });
    assert.equal(outcome.outcome, verdict === "admit" ? "admitted" : "rejected");
    const expectedPath = path.join(f.root, "runtime", `paper_${P}`, "validation", "P__node_with_spaces-w1.json");
    assert.ok(fs.existsSync(expectedPath), "the full review must survive pack deletion");
    // Resolve the new export only after exercising retention, so the old code fails on behavior.
    const exported = validator as typeof validator & {
      reviewPath: (repoRoot: string, paper: string, node: string, wave: number) => string;
    };
    assert.equal(exported.reviewPath(f.repoRoot, P, c.node, c.wave), expectedPath);
    const review = JSON.parse(fs.readFileSync(expectedPath, "utf-8")) as RetainedReview;
    assert.match(review.candidateHash, /^[a-f0-9]{64}$/);
    assert.ok(claimText.includes(`candidateHash: ${review.candidateHash}`));
    assert.deepEqual(review.candidate, c);
    assert.deepEqual(review.manifest, originalPack!.manifest);
    assert.equal(review.refuterFindings, FINDINGS);
    assert.ok(review.refuterFindings.length > 500);
    assert.equal(review.judgeRawOutput, raw);
    assert.deepEqual(review.verdict, validator.parseJudgeVerdict(raw));
    assert.equal(fs.existsSync(originalPack!.dir), false);
    const times = [review.startedAt, review.refutedAt, review.judgedAt, review.finishedAt].map(Date.parse);
    assert.ok(times.every(Number.isFinite));
    assert.deepEqual(times, [...times].sort((a, b) => a - b));
    if (verdict === "admit") {
      assert.deepEqual(review.appendedRow, c.resultRow);
      assert.equal(review.rejectionObligation, null);
      const [row] = await f.ledgers.results(P);
      for (const [key, value] of Object.entries(review.appendedRow!)) assert.deepEqual(row[key], value);
    } else {
      assert.equal(review.appendedRow, null);
      const [obligation] = await f.ledgers.claims(P);
      assert.ok(review.rejectionObligation);
      for (const [key, value] of Object.entries(review.rejectionObligation)) assert.deepEqual(obligation[key], value);
    }
    const [message] = f.journal.ofType("validation_verdict") as unknown as { candidateHash: string; reviewPath: string }[];
    assert.equal(message.candidateHash, review.candidateHash);
    assert.equal(message.reviewPath, expectedPath);
  });
}

test("candidate hashes ignore object key order and bind nested submission fields", t => {
  const f = fixture(t);
  const first = candidate();
  first.resultRow.verifier_result = { verdict: "pass", detail: "nested order" };
  const reordered = Object.fromEntries(Object.entries(first).reverse()) as unknown as CandidateSubmission;
  reordered.resultRow = Object.fromEntries(Object.entries(first.resultRow).reverse());
  reordered.resultRow.verifier_result = { detail: "nested order", verdict: "pass" };
  const changed = structuredClone(first);
  (changed.resultRow.verifier_result as Record<string, unknown>).detail = "different input";
  const hashes = [first, reordered, changed].map(c => {
    const pack = validator.buildContextPack(f.repoRoot, c);
    try {
      const claim = fs.readFileSync(path.join(pack.dir, "CLAIM.md"), "utf-8");
      const hash = claim.match(/^candidateHash: ([a-f0-9]{64})$/m)?.[1];
      assert.ok(hash, "CLAIM.md must identify the complete candidate by hash");
      return hash;
    } finally {
      fs.rmSync(pack.dir, { recursive: true, force: true });
    }
  });
  assert.equal(hashes[0], hashes[1]);
  assert.notEqual(hashes[0], hashes[2]);
});

test("a failed judge process retains its already-written raw output without admitting", async t => {
  const f = fixture(t);
  const raw = 'Judge wrote this before exiting\n{"verdict":"admit","reasons":"checks complete"}\n';
  const bin = path.join(f.root, "scripted judge");
  fs.writeFileSync(bin, [
    "#!/usr/bin/env bash", "set -eu", 'final=""',
    'while [ "$#" -gt 0 ]; do',
    '  if [ "$1" = "-o" ]; then final=$2; shift; fi',
    "  shift", "done", "cat >/dev/null",
    'cat > "$final" <<\'JUDGE_OUTPUT\'', raw.trimEnd(), "JUDGE_OUTPUT", "exit 3", "",
  ].join("\n"), { mode: 0o755 });
  const cli = new validator.CodexValidatorRunner({ bin });
  const runner = scripted();
  runner.judge = cli.judge.bind(cli);
  await assert.rejects(validator.adjudicateCandidate(candidate(), { ...f, runner }), /exit=3/);
  const file = path.join(f.root, "runtime", `paper_${P}`, "validation", "P__n1-w1.json");
  assert.ok(fs.existsSync(file), "failed adjudications must retain their review");
  const review = JSON.parse(fs.readFileSync(file, "utf-8"));
  assert.equal(review.judgeRawOutput, raw, "already-written judge output must survive a process failure");
  assert.equal(review.refuterFindings, FINDINGS);
  assert.match(review.error, /exit=3/);
  assert.equal(review.outcome, null);
  assert.equal(review.verdict, null);
  assert.deepEqual(f.journal.ofType("validation_verdict"), []);
  assert.deepEqual(await f.ledgers.results(P), []);
  assert.deepEqual(await f.ledgers.claims(P), []);
  assert.deepEqual(fs.readdirSync(f.packRoot), []);
});
