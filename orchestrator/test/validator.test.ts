/** Adversarial validation: physical context-pack isolation, mandatory
 * refuter-first sequence, and verdicts landing ONLY as gated ledger rows.
 * Uses the real Python ledger CLIs in a tmp repo-root. */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import {
  adjudicateCandidate, buildContextPack, checkIsolation,
  type CandidateSubmission, type ContextPack, type ValidatorRunner,
} from "../src/validator.js";

const P = "arxiv-0000.00000";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function tmpRepo(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-val-"));
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(dir, "_common"));
  // pack inputs that live in the methodology repo
  for (const rel of ["alignment.md", "pipelines/2-work/spec.md"]) {
    const dest = path.join(dir, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(path.join(REPO_ROOT, rel), dest);
  }
  fs.mkdirSync(path.join(dir, "artifacts"));
  fs.writeFileSync(path.join(dir, "artifacts/out.txt"), "residual 1e-9 PASS\n");
  return dir;
}

function candidate(over: Partial<CandidateSubmission> = {}): CandidateSubmission {
  return {
    paper: P, node: "P::n1", wave: 1,
    claim: "the boundary term vanishes",
    evidencePaths: ["artifacts/out.txt"],
    resultRow: {
      paper: P, result_id: "r-n1", name: "boundary term",
      working_context: "toy", claim: "the boundary term vanishes",
      evidence_type: "symbolic_derivation", evidence: "artifacts/out.txt",
      verifier_result: { verdict: "pass" }, dependencies: [], assumptions: [],
      status: "checked", provenance: "validator-test", open_obligations: [],
    },
    ...over,
  };
}

function journalIn(dir: string): Journal {
  return new Journal(path.join(dir, "journal.jsonl"));
}

const scripted = (verdict: "admit" | "reject", findings = "tried units, regimes, protocol — no hole found"): ValidatorRunner => ({
  name: "scripted",
  async refute() { return { findings }; },
  async judge(_pack: ContextPack, _claim: string, f: string) {
    assert.ok(f.length > 0, "judge must receive the refuter findings");
    return { verdict, reasons: verdict === "admit" ? "evidence holds" : "gate 4 violated" };
  },
});

test("context pack contains ONLY allowlisted files, hashed; isolation audit catches smuggling", () => {
  const repo = tmpRepo();
  const pack = buildContextPack(repo, candidate());
  try {
    assert.ok(pack.manifest["CLAIM.md"] && pack.manifest["artifacts/out.txt"]
              && pack.manifest["alignment.md"]);
    // nothing else from the repo leaked in
    assert.ok(!fs.existsSync(path.join(pack.dir, "_common", "ledgers")));
    assert.ok(checkIsolation(pack).ok);
    fs.writeFileSync(path.join(pack.dir, "DEFENDER_TRANSCRIPT.md"), "smuggled");
    const audit = checkIsolation(pack);
    assert.equal(audit.ok, false);
    assert.match(audit.violations.join(";"), /unmanifested file: DEFENDER_TRANSCRIPT.md/);
  } finally {
    fs.rmSync(pack.dir, { recursive: true, force: true });
  }
});

test("admit verdict lands as a GATED result append (and the gate can still refuse)", async () => {
  const repo = tmpRepo();
  const ledgers = new Ledgers(repo);
  const r = await adjudicateCandidate(candidate(), {
    repoRoot: repo, ledgers, journal: journalIn(repo), runner: scripted("admit"),
  });
  assert.equal(r.outcome, "admitted");
  const rows = await ledgers.results(P);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].result_id, "r-n1");

  // same flow, but evidence that the executable gate rejects
  const bad = candidate({ node: "P::n2" });
  bad.resultRow = { ...bad.resultRow, result_id: "r-n2", evidence: "ghost/missing.txt" };
  const r2 = await adjudicateCandidate(bad, {
    repoRoot: repo, ledgers, journal: journalIn(repo), runner: scripted("admit"),
  });
  assert.equal(r2.outcome, "gate_rejected");
  assert.match(r2.detail, /verifiable evidence/);
  assert.equal((await ledgers.results(P)).length, 1); // nothing new landed
});

test("reject verdict lands as an open blocking repair obligation on the node", async () => {
  const repo = tmpRepo();
  const ledgers = new Ledgers(repo);
  const journal = journalIn(repo);
  const r = await adjudicateCandidate(candidate(), {
    repoRoot: repo, ledgers, journal, runner: scripted("reject"),
  });
  assert.equal(r.outcome, "rejected");
  const claims = await ledgers.claims(P);
  assert.equal(claims.length, 1);
  assert.equal(claims[0].kind, "obligation");
  assert.equal(claims[0].status, "open");
  assert.deepEqual(claims[0].node_ids, ["P::n1"]);
  assert.match(String(claims[0].statement), /validation rejected/);
  const verdicts = journal.ofType("validation_verdict");
  assert.equal(verdicts.length, 1);
  assert.equal(verdicts[0].verdict, "reject");
});

test("the refuter is mandatory: empty findings abort before any judge/ledger action", async () => {
  const repo = tmpRepo();
  const ledgers = new Ledgers(repo);
  let judgeCalled = false;
  const lazy: ValidatorRunner = {
    name: "lazy",
    async refute() { return { findings: "   " }; },
    async judge() { judgeCalled = true; return { verdict: "admit", reasons: "" }; },
  };
  await assert.rejects(
    adjudicateCandidate(candidate(), {
      repoRoot: repo, ledgers, journal: journalIn(repo), runner: lazy,
    }),
    /refutation attempt is mandatory/);
  assert.equal(judgeCalled, false);
  assert.deepEqual(await ledgers.results(P), []);
});
