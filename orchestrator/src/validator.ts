/** Process-isolated adversarial validation (stage-2 gate, v2).
 *
 * Isolation is PHYSICAL, not prose: the refuter and judge run with cwd set to
 * a context-pack directory containing ONLY the allowlisted files (kernel,
 * admission contract, stage spec, the claim, the candidate evidence). The
 * defender's transcript, the rest of the repo, and other nodes' work are not
 * in the pack, so they cannot be read — no "do not look at X" instructions.
 *
 * Sequence is enforced in code: the refuter MUST run first and produce
 * findings; the judge sees the pack + findings; an admit verdict is executed
 * by the ORCHESTRATOR as a gated ledger append (the admission gate still runs
 * the verification command), and a reject verdict lands as an open repair
 * obligation on the node — so verdicts, like all progress, are ledger rows. */
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { Journal } from "./journal.js";
import type { Ledgers } from "./ledger.js";

export interface CandidateSubmission {
  paper: string;
  node: string;
  wave: number;
  /** the claim being advanced, plain language */
  claim: string;
  /** proposed result-ledger row (verdict claimed by the defender) */
  resultRow: Record<string, unknown>;
  /** repo-root-relative evidence files to copy into the pack */
  evidencePaths: string[];
}

export interface ContextPack {
  dir: string;
  /** repo-root-relative -> sha256 of every file in the pack */
  manifest: Record<string, string>;
}

export interface RefuterReport {
  findings: string;
}

export interface JudgeVerdict {
  verdict: "admit" | "reject";
  reasons: string;
}

export interface ValidatorRunner {
  readonly name: string;
  refute(pack: ContextPack, claim: string): Promise<RefuterReport>;
  judge(pack: ContextPack, claim: string, findings: string): Promise<JudgeVerdict>;
}

const ALWAYS_PACKED = [
  "alignment.md",
  "_common/contracts/research_admission_contract.md",
  "pipelines/2-work/spec.md",
];

function sha256(buf: Buffer): string {
  return crypto.createHash("sha256").update(buf).digest("hex");
}

/** Copy exactly the allowlisted files into a fresh pack dir. */
export function buildContextPack(repoRoot: string, candidate: CandidateSubmission): ContextPack {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-pack-"));
  const manifest: Record<string, string> = {};
  const put = (rel: string, content: Buffer) => {
    const dest = path.join(dir, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, content);
    manifest[rel] = sha256(content);
  };
  for (const rel of [...ALWAYS_PACKED, ...candidate.evidencePaths]) {
    const src = path.join(repoRoot, rel);
    if (!fs.existsSync(src)) throw new Error(`context-pack input missing: ${rel}`);
    put(rel, fs.readFileSync(src));
  }
  put("CLAIM.md", Buffer.from(
    `# Candidate under validation\n\nnode: ${candidate.node}\npaper: ${candidate.paper}\n\n` +
    `## Claim\n\n${candidate.claim}\n\n## Proposed result row\n\n` +
    "```json\n" + JSON.stringify(candidate.resultRow, null, 2) + "\n```\n"));
  fs.writeFileSync(path.join(dir, "MANIFEST.json"), JSON.stringify(manifest, null, 2));
  return { dir, manifest };
}

/** Mechanical isolation audit: every file in the pack dir must be in the
 * manifest with a matching hash — a smuggled or tampered file fails. */
export function checkIsolation(pack: ContextPack): { ok: boolean; violations: string[] } {
  const violations: string[] = [];
  const walk = (d: string): string[] =>
    fs.readdirSync(d, { withFileTypes: true }).flatMap(e =>
      e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]);
  for (const abs of walk(pack.dir)) {
    const rel = path.relative(pack.dir, abs);
    if (rel === "MANIFEST.json") continue;
    const expected = pack.manifest[rel];
    if (!expected) { violations.push(`unmanifested file: ${rel}`); continue; }
    if (sha256(fs.readFileSync(abs)) !== expected) violations.push(`hash mismatch: ${rel}`);
  }
  for (const rel of Object.keys(pack.manifest)) {
    if (!fs.existsSync(path.join(pack.dir, rel))) violations.push(`missing manifest file: ${rel}`);
  }
  return { ok: violations.length === 0, violations };
}

export type ValidationOutcome = "admitted" | "gate_rejected" | "rejected";

/** Refuter -> judge -> ledger. The only write paths are the gated appends. */
export async function adjudicateCandidate(candidate: CandidateSubmission, deps: {
  repoRoot: string;
  ledgers: Ledgers;
  journal: Journal;
  runner: ValidatorRunner;
}): Promise<{ outcome: ValidationOutcome; detail: string }> {
  const { repoRoot, ledgers, journal, runner } = deps;
  const pack = buildContextPack(repoRoot, candidate);
  try {
    const iso = checkIsolation(pack);
    if (!iso.ok) throw new Error(`context pack failed isolation audit: ${iso.violations.join("; ")}`);

    // 1. the refuter MUST run first and must return non-empty findings
    const refutation = await runner.refute(pack, candidate.claim);
    if (!refutation.findings.trim()) {
      throw new Error("refuter returned empty findings — refutation attempt is mandatory");
    }
    // 2. the judge sees pack + findings, never the defender
    const verdict = await runner.judge(pack, candidate.claim, refutation.findings);
    journal.append({
      type: "validation_verdict", wave: candidate.wave, node: candidate.node,
      verdict: verdict.verdict, refuterFindings: refutation.findings.slice(0, 500),
    });

    if (verdict.verdict === "admit") {
      // 3a. admission = the gated append; the gate can still refuse.
      try {
        await ledgers.appendResult(candidate.resultRow);
        return { outcome: "admitted", detail: verdict.reasons };
      } catch (e) {
        return { outcome: "gate_rejected", detail: (e as Error).message };
      }
    }
    // 3b. rejection = an open repair obligation on the node (claim ledger)
    await ledgers.appendClaimEntry({
      paper: candidate.paper,
      entry_id: `repair-${candidate.node.replace(/[^A-Za-z0-9_:-]/g, "_")}-w${candidate.wave}`,
      kind: "obligation",
      status: "open",
      statement: `validation rejected: ${verdict.reasons}`.slice(0, 500),
      node_ids: [candidate.node],
      blocking: true,
    });
    return { outcome: "rejected", detail: verdict.reasons };
  } finally {
    fs.rmSync(pack.dir, { recursive: true, force: true });
  }
}

/** Real SDK validators: two fresh sessions with cwd = the pack dir and
 * read-only tools — they physically cannot reach the repo or the defender. */
export class SdkValidatorRunner implements ValidatorRunner {
  readonly name = "sdk-validator";
  constructor(private opts: { maxTurns?: number; refuterModel?: string; judgeModel?: string } = {}) {}

  private async session(cwd: string, prompt: string, model?: string): Promise<string> {
    const { query } = await import("@anthropic-ai/claude-agent-sdk");
    let out = "";
    const q = query({
      prompt,
      options: {
        cwd,
        maxTurns: this.opts.maxTurns ?? 30,
        ...(model ? { model } : {}),
        allowedTools: ["Read", "Grep", "Glob", "Bash"],
        permissionMode: "default",
        settingSources: [],
        env: { ...process.env as Record<string, string>, CHANDRA_ROLE: "validator" },
      },
    });
    for await (const message of q) {
      const m = message as { type: string; result?: string };
      if (m.type === "result") out = m.result ?? "";
    }
    return out;
  }

  async refute(pack: ContextPack, claim: string): Promise<RefuterReport> {
    const findings = await this.session(pack.dir, [
      `You are an adversarial REFUTER. This directory is your ENTIRE context`,
      `(see MANIFEST.json). Read CLAIM.md and the evidence, then try HARD to`,
      `refute the claim: "${claim}". Check the validation gates in`,
      `pipelines/2-work/spec.md (evidence-type match, units/regimes,`,
      `approximation obligations, protocol completeness). Your final message:`,
      `your findings — every weakness found, or a statement of what you tried`,
      `and why refutation failed. Never say "looks good" without listing the`,
      `specific refutation attempts that failed.`,
    ].join("\n"), this.opts.refuterModel);
    return { findings };
  }

  async judge(pack: ContextPack, claim: string, findings: string): Promise<JudgeVerdict> {
    const raw = await this.session(pack.dir, [
      `You are the admission JUDGE. This directory is your entire context.`,
      `Claim: "${claim}". The independent refuter reported:\n---\n${findings}\n---`,
      `Weigh the refutation against the evidence and the validation gates in`,
      `pipelines/2-work/spec.md. Your final message must be EXACTLY one JSON`,
      `object: {"verdict": "admit"|"reject", "reasons": "<one paragraph>"}.`,
    ].join("\n"), this.opts.judgeModel);
    const m = raw.match(/\{[\s\S]*\}/);
    if (!m) return { verdict: "reject", reasons: `unparseable judge output: ${raw.slice(0, 200)}` };
    try {
      const parsed = JSON.parse(m[0]) as JudgeVerdict;
      return parsed.verdict === "admit"
        ? { verdict: "admit", reasons: parsed.reasons ?? "" }
        : { verdict: "reject", reasons: parsed.reasons ?? "" };
    } catch {
      return { verdict: "reject", reasons: `unparseable judge JSON: ${raw.slice(0, 200)}` };
    }
  }
}
