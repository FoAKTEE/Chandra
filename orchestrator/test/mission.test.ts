/** END-TO-END SELF-HOSTING FIXTURE: a 3-node toy mission driven through the
 * whole v2 loop — topological waves with enforced parallelism, isolated
 * adversarial validation (one candidate deliberately rejected, repaired, then
 * admitted), gated ledger appends, observer notes, digest cadence, and halt
 * on mission completion. Headless: stub workers + scripted validators; the
 * Python ledger CLIs (with the executable admission gate) are REAL.
 *
 * DAG:  n1 (root)  n2 (root)  ->  n3 (needs both solid)
 * Script: wave 1 works n1+n2 in parallel — n1 admits, n2 is REJECTED by the
 * validator (repair obligation filed); wave 2 repairs n2 (discharges the
 * obligation, admits); wave 3 admits n3; wave 4 detects completion. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { Journal } from "../src/journal.js";
import { Ledgers } from "../src/ledger.js";
import { runMissionLoop } from "../src/main.js";
import { RESEARCH_STATE_CAP_BYTES, TruncatingObserver } from "../src/observer.js";
import type { WorkerRunner } from "../src/scheduler.js";
import type { WorkerTask } from "../src/types.js";
import { adjudicateCandidate, type ValidatorRunner } from "../src/validator.js";

const P = "arxiv-9999.99999";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

let RUNTIME_HOME = "";

function toyRepo(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-mission-"));
  // hermetic runtime home: diaries live OUTSIDE the repo, like production
  RUNTIME_HOME = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-runtime-"));
  process.env.CHANDRA_RUNTIME = RUNTIME_HOME;
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(dir, "_common"));
  for (const rel of ["alignment.md", "pipelines/2-work/spec.md"]) {
    const dest = path.join(dir, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(path.join(REPO_ROOT, rel), dest);
  }
  // the fixture mission runs under the STRICT delegation policy (kernel §6)
  fs.writeFileSync(path.join(dir, ".delegation-policy"), "strict\n");
  // substage-commit enforcement: missions run in a git repo
  for (const args of [["init", "-q"], ["config", "user.email", "fixture@test"],
                      ["config", "user.name", "fixture"],
                      ["add", "-A"], ["commit", "-q", "-m", "chore(fixture): seed toy mission repo"]]) {
    execFileSync("git", ["-C", dir, ...args]);
  }
  return dir;
}

async function seedDag(repoRoot: string): Promise<void> {
  // mission seeding is a deliberate human act — visible override role
  const ledgers = new Ledgers(repoRoot, "human-override");
  const node = (node_id: string, predecessors: string[]) => ({
    paper: P, node_id, task_id: `t-${node_id}`, domain: "symbolic",
    status: "hypothesis", summary: `toy node ${node_id}`, predecessors,
  });
  await ledgers.appendKnowledge(node("n1", []));
  await ledgers.appendKnowledge(node("n2", []));
  await ledgers.appendKnowledge(node("n3", ["n1", "n2"]));
}

/** Validator script: reject n2's FIRST candidate, admit everything else. */
function scriptedValidator(rejectOnce: Set<string>): ValidatorRunner {
  return {
    name: "scripted-validator",
    async refute(_pack, claim) {
      return { findings: `attempted refutation of "${claim}": checked evidence-type match, units, protocol` };
    },
    async judge(_pack, claim, findings) {
      assert.ok(findings.length > 0);
      const node = claim.match(/node (\S+)/)?.[1] ?? "";
      if (rejectOnce.has(node)) {
        rejectOnce.delete(node);
        return { verdict: "reject", reasons: `evidence for ${node} does not cover the stated regime` };
      }
      return { verdict: "admit", reasons: "evidence holds under refutation" };
    },
  };
}

/** Stub stage-2 worker: writes real evidence, runs the real validation
 * adjudication, and on admit promotes the node through the real gate. */
function stubWorker(repoRoot: string, validator: ValidatorRunner): WorkerRunner {
  const ledgers = new Ledgers(repoRoot, "worker");   // delegated role: appends admissible
  return {
    name: "stub-worker",
    async runWorker(task: WorkerTask) {
      // continuous packet contract: work every leased node in order,
      // in this one invocation; stop the chain on a rejection
      let detail = "";
      for (const n of task.packet) {
        const out = await this.workNode!(task, n.id);
        detail += `${n.id}:${out} `;
        if (out !== "admitted") break;
      }
      return { detail: detail.trim(), windowsUsed: 2 };
    },
    async workNode(task: WorkerTask, node: string): Promise<string> {
      const evidenceRel = path.join("artifacts", `${node}.txt`);
      const evidenceAbs = path.join(repoRoot, evidenceRel);
      fs.mkdirSync(path.dirname(evidenceAbs), { recursive: true });
      fs.writeFileSync(evidenceAbs, `verifier output for ${node}: residual 1e-9 PASS\n`);

      const verdict = await adjudicateCandidate({
        paper: P, node, wave: task.wave,
        claim: `node ${node} reproduces its target equation`,
        evidencePaths: [evidenceRel],
        resultRow: {
          paper: P, result_id: `r-${node}-w${task.wave}`, name: `toy result ${node}`,
          working_context: "toy model", claim: `node ${node} reproduces its target equation`,
          evidence_type: "symbolic_derivation", evidence: evidenceRel,
          verifier_result: { verdict: "pass" }, dependencies: [], assumptions: [],
          status: "checked", provenance: "mission-fixture", open_obligations: [],
          node_ids: [node],
        },
      }, {
        repoRoot, ledgers, journal: new Journal(path.join(RUNTIME_HOME, "validation.jsonl")),
        runner: validator,
      });

      if (verdict.outcome === "admitted") {
        // repair path: discharge the wave-1 obligation before promotion
        const open = (await ledgers.claims(P)).filter(
          c => c.kind === "obligation" && c.status === "open" && (c.node_ids ?? []).includes(node));
        for (const o of open) {
          await ledgers.appendClaimEntry({
            paper: P, entry_id: o.entry_id, kind: "obligation", status: "discharged",
            statement: o.statement, node_ids: o.node_ids,
            discharged_by: `r-${node}-w${task.wave}`,
          });
        }
        await ledgers.appendKnowledge({
          paper: P, node_id: node, task_id: `t-${node}`, domain: "symbolic",
          status: "solid", summary: `toy node ${node}`, evidence: evidenceRel,
          predecessors: node === "n3" ? ["n1", "n2"] : [],
        });
      }
      return verdict.outcome;
    },
  } as WorkerRunner & { workNode(task: WorkerTask, node: string): Promise<string> };
}

test("toy mission end-to-end: parallel frontier, reject->repair->admit, notes, digest, completion", async () => {
  const repo = toyRepo();
  const ledgers = new Ledgers(repo);   // roleless: read-only orchestrator view
  await seedDag(repo);

  // delegation policy: the ORCHESTRATING context cannot append work itself
  await assert.rejects(
    ledgers.appendKnowledge({
      paper: P, node_id: "n1", task_id: "t-n1", domain: "symbolic",
      status: "preliminary", summary: "inline work attempt",
    }),
    /delegation policy is strict/);

  const validator = scriptedValidator(new Set(["n2"]));
  const lines: string[] = [];

  const code = await runMissionLoop({
    repoRoot: repo, paper: P, maxWorkers: 4, maxWaves: 6,
    runner: stubWorker(repo, validator),
    observerRunner: new TruncatingObserver(),
    probes: { async refreshDue() { return false; } },
    jobRunners: {
      "write-refresh": {                     // terminal render after completion
        name: "stub-write",
        async run() {
          const log = path.join(repo, "results", "mission", `paper_${P}`, "paper", "GENERATION_LOG");
          fs.mkdirSync(path.dirname(log), { recursive: true });
          fs.appendFileSync(log, "final render\n");
          return { detail: "rendered", windowsUsed: 1 };
        },
      },
    },
    log: line => lines.push(line),
  });
  assert.equal(code, 0, `exit ${code}; log:\n${lines.join("\n")}`);

  // --- journal: the whole story, typed -----------------------------------
  // the journal is an operational diary: it lives in the runtime home, not the repo
  const journal = new Journal(path.join(RUNTIME_HOME, `paper_${P}`, "journal.jsonl"));
  assert.ok(!fs.existsSync(path.join(repo, "progress", "orchestrator", `paper_${P}`, "journal.jsonl")),
    "no diary files inside the repo");
  const planned = journal.ofType("wave_planned");
  assert.deepEqual(planned[0].scheduled.sort(), ["n1", "n2"], "wave 1 must schedule BOTH roots in parallel");
  // packet semantics: wave 2 leases the repaired node AND its unlocked
  // successor as ONE continuous chain — no per-node fragmentation
  assert.deepEqual(planned[1].scheduled, ["n2", "n3"], "wave 2 works the n2->n3 chain in one packet");
  const halt = journal.ofType("halt");
  assert.equal(halt[halt.length - 1].reason, "mission_complete");
  assert.equal(halt[halt.length - 1].wave, 4, "wave 3 is the terminal render; wave 4 halts");

  // --- outcomes were ledger-diff-derived ----------------------------------
  const done = journal.ofType("worker_done").map(m => [m.report.node, m.report.outcome, m.wave]);
  assert.deepEqual(done.filter(d => d[2] === 1).map(d => `${d[0]}:${d[1]}`).sort(),
    ["n1:admitted", "n2:rejected"]);
  assert.ok(done.some(d => d[0] === "n2" && d[1] === "admitted" && d[2] === 2));
  assert.ok(done.some(d => d[0] === "n3" && d[1] === "admitted" && d[2] === 2),
    "n3 admitted in the SAME wave as n2 (same packet, same session)");

  // --- ledgers: everything went through the executable gate ---------------
  const know = await ledgers.knowledge(P);
  assert.deepEqual(know.filter(r => r.status === "solid").map(r => r.node_id).sort(), ["n1", "n2", "n3"]);
  // every worked row carries its actor role (provenance, kernel §6)
  assert.ok(know.filter(r => r.status === "solid").every(r => r.actor_role === "worker"));
  assert.ok(know.filter(r => r.node_id === "n2").every(r => "evidence_sha256" in r || r.status !== "solid"));
  const claims = await ledgers.claims(P);
  const repair = claims.find(c => (c.node_ids ?? []).includes("n2"));
  assert.ok(repair && repair.status === "discharged", "repair obligation must end discharged");
  assert.equal((await ledgers.results(P)).length, 3);

  // --- observer notes ------------------------------------------------------
  const missionDir = path.join(repo, "progress", "orchestrator", `paper_${P}`);
  const iterNote = fs.readFileSync(path.join(missionDir, "loop_notes", "current_iter.md"), "utf-8");
  assert.match(iterNote, /Current wave — 3/);          // only the final wave (terminal render)
  assert.ok(!iterNote.includes("wave — 1"));
  const nodal = fs.readFileSync(path.join(missionDir, "nodal_note.md"), "utf-8");
  assert.match(nodal, /^\| 1 \|/m);
  assert.match(nodal, /^\| 3 \|/m);
  const rs = path.join(missionDir, "RESEARCH_STATE.md");
  assert.ok(fs.statSync(rs).size <= RESEARCH_STATE_CAP_BYTES);

  // --- digest cadence: 2 windows/worker -> 4 after wave 1, 6 after wave 2 --
  const digests = journal.ofType("digest_emitted");
  assert.equal(digests.length, 1, "exactly one digest in this run");
  assert.equal(digests[0].wave, 2);
  assert.ok(digests[0].afterWindows >= 5);
  assert.match(fs.readFileSync(digests[0].path, "utf-8"), /Human digest/);

  // --- gate stayed green the whole run -------------------------------------
  for (const g of journal.ofType("gate_decision")) {
    assert.equal(g.decision, "continue");
  }

  // --- substage-commit enforcement: one commit per changing wave, tree clean --
  const commits = journal.ofType("wave_committed");
  assert.ok(commits.length >= 2, `expected >=2 wave commits, got ${commits.length}`);
  const gitLog = execFileSync("git", ["-C", repo, "log", "--format=%s"], { encoding: "utf-8" });
  assert.match(gitLog, /notes\(wave\): paper_arxiv-9999.99999 wave 1/);
  const dirty = execFileSync("git", ["-C", repo, "status", "--porcelain"], { encoding: "utf-8" });
  assert.equal(dirty.trim(), "", "working tree must be clean after the mission");
});

test("a mission refuses to start outside a git repo (enforcement, not advice)", async () => {
  const bare = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-nogit-"));
  process.env.CHANDRA_RUNTIME = path.join(bare, ".runtime");
  fs.symlinkSync(path.join(REPO_ROOT, "_common"), path.join(bare, "_common"));
  await assert.rejects(
    runMissionLoop({
      repoRoot: bare, paper: P, maxWorkers: 1, maxWaves: 1,
      runner: { name: "noop", async runWorker() { return { detail: "", windowsUsed: 1 }; } },
      observerRunner: new TruncatingObserver(),
      log: () => {},
    }),
    /not a git repo/);
});
