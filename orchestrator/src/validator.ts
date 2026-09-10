/** Process-isolated adversarial validation (stage-2 gate, v2).
 *
 * The refuter and judge run with cwd set to
 * a context-pack directory containing ONLY the allowlisted files (kernel,
 * admission contract, stage spec, the claim, the candidate evidence). The
 * defender's transcript, the rest of the repo, and other nodes' work are not
 * copied into the pack. Filesystem reach also depends on the runner's sandbox;
 * cwd alone is not an access-control boundary.
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
import { runCodexExec, type CodexOptions } from "./codex.js";
import type { Journal } from "./journal.js";
import type { Ledgers } from "./ledger.js";
import { loadMissionSpec, parseModelSpec, type MissionSpec } from "./missionspec.js";
import { runtimeDir } from "./runtime.js";

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
  /** Text backends report their full output before parsing. Legacy scripted
   * runners may omit captureRaw; their returned verdict is retained as JSON. */
  judge(pack: ContextPack, claim: string, findings: string,
        captureRaw?: (raw: string) => void): Promise<JudgeVerdict>;
}

/** Shared judge parser: malformed output fails closed for either backend. */
export function parseJudgeVerdict(raw: string): JudgeVerdict {
  const m = raw.match(/\{[\s\S]*\}/);
  if (!m) return { verdict: "reject", reasons: `unparseable judge output: ${raw.slice(0, 200)}` };
  try {
    const parsed = JSON.parse(m[0]) as { verdict?: unknown; reasons?: unknown };
    if (typeof parsed.reasons !== "string" || !parsed.reasons.trim()) {
      return { verdict: "reject", reasons: "judge gave no reasons" };
    }
    return {
      verdict: parsed.verdict === "admit" ? "admit" : "reject",
      reasons: parsed.reasons,
    };
  } catch {
    return { verdict: "reject", reasons: `unparseable judge JSON: ${raw.slice(0, 200)}` };
  }
}

export function refuterPrompt(claim: string): string {
  return [
    `You are an adversarial REFUTER. This directory is your ENTIRE context`,
    `(see MANIFEST.json). Read CLAIM.md and the evidence, then try HARD to`,
    `refute the claim: "${claim}". Check the validation gates in`,
    `pipelines/2-work/spec.md (evidence-type match, units/regimes,`,
    `approximation obligations, protocol completeness). Your final message:`,
    `your findings — every weakness found, or a statement of what you tried`,
    `and why refutation failed. Never say "looks good" without listing the`,
    `specific refutation attempts that failed.`,
  ].join("\n");
}

export function judgePrompt(claim: string, findings: string): string {
  return [
    `You are the admission JUDGE. This directory is your entire context.`,
    `Claim: "${claim}". The independent refuter reported:\n---\n${findings}\n---`,
    `Weigh the refutation against the evidence and the validation gates in`,
    `pipelines/2-work/spec.md. Your final message must be EXACTLY one JSON`,
    `object: {"verdict": "admit"|"reject", "reasons": "<one paragraph>"}.`,
  ].join("\n");
}

const ALWAYS_PACKED = [
  "alignment.md",
  "_common/contracts/research_admission_contract.md",
  "pipelines/2-work/spec.md",
];

function sha256(buf: Buffer): string {
  return crypto.createHash("sha256").update(buf).digest("hex");
}

/** Stable JSON object ordering; array order remains part of the submission. */
function canonicalJson(value: unknown): string {
  return JSON.stringify(value, (_key, current: unknown) =>
    current !== null && typeof current === "object" && !Array.isArray(current)
      ? Object.fromEntries(Object.entries(current).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
      : current);
}

export class ValidationBindingError extends Error {
  override name = "ValidationBindingError";
}

function checkBinding(candidate: CandidateSubmission): void {
  if (candidate.resultRow.paper !== candidate.paper) {
    throw new ValidationBindingError("resultRow.paper does not match the candidate paper");
  }
  if (candidate.resultRow.claim !== candidate.claim) {
    throw new ValidationBindingError("resultRow.claim does not match the candidate claim");
  }
  const nodes = candidate.resultRow.node_ids;
  if (!Array.isArray(nodes) || nodes.length === 0 || !nodes.includes(candidate.node)) {
    throw new ValidationBindingError("resultRow.node_ids must be a non-empty array containing the candidate node");
  }
}

/** Resolve the entire evidence list before creating or copying into a pack. */
function evidenceInputs(repoRoot: string, evidencePaths: string[]): string[] {
  const root = fs.realpathSync(repoRoot);
  return evidencePaths.map(rel => {
    if (typeof rel !== "string" || !rel || path.isAbsolute(rel) || path.win32.isAbsolute(rel)
        || rel.split(/[\\/]/).includes("..")) {
      throw new ValidationBindingError(`evidence path must be relative without '..' segments: ${rel}`);
    }
    let resolved: string;
    try {
      resolved = fs.realpathSync(path.join(root, rel));
    } catch (e) {
      throw new ValidationBindingError(`context-pack input missing: ${rel}: ${(e as Error).message}`);
    }
    const relative = path.relative(root, resolved);
    if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
      throw new ValidationBindingError(`evidence path escapes the repository: ${rel}`);
    }
    if (!fs.statSync(resolved).isFile()) {
      throw new ValidationBindingError(`context-pack evidence must be a file: ${rel}`);
    }
    return resolved;
  });
}

/** Copy exactly the allowlisted files into a fresh pack dir. */
export function buildContextPack(repoRoot: string, candidate: CandidateSubmission,
                                 candidateHash = sha256(Buffer.from(canonicalJson(candidate)))): ContextPack {
  const evidence = evidenceInputs(repoRoot, candidate.evidencePaths);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chandra-pack-"));
  const manifest: Record<string, string> = {};
  const put = (rel: string, content: Buffer) => {
    const dest = path.join(dir, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, content);
    manifest[path.normalize(rel)] = sha256(content);
  };
  try {
    for (const rel of ALWAYS_PACKED) {
      const src = path.join(repoRoot, rel);
      if (!fs.existsSync(src)) throw new Error(`context-pack input missing: ${rel}`);
      put(rel, fs.readFileSync(src));
    }
    candidate.evidencePaths.forEach((rel, i) => put(rel, fs.readFileSync(evidence[i])));
    put("CLAIM.md", Buffer.from(
      `# Candidate under validation\n\nnode: ${candidate.node}\npaper: ${candidate.paper}\n` +
      `candidateHash: ${candidateHash}\n\n` +
      `## Claim\n\n${candidate.claim}\n\n## Proposed result row\n\n` +
      "```json\n" + JSON.stringify(candidate.resultRow, null, 2) + "\n```\n"));
    fs.writeFileSync(path.join(dir, "MANIFEST.json"), JSON.stringify(manifest, null, 2));
    return { dir, manifest };
  } catch (e) {
    fs.rmSync(dir, { recursive: true, force: true });
    throw e;
  }
}

/** Mechanical isolation audit: every file in the pack dir must be in the
 * manifest with a matching hash — a smuggled or tampered file fails. */
export function checkIsolation(pack: ContextPack): { ok: boolean; violations: string[] } {
  const violations: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const abs = path.join(dir, entry.name);
      const rel = path.relative(pack.dir, abs);
      if (entry.isDirectory()) {
        if (!Object.keys(pack.manifest).some(file => file.startsWith(`${rel}${path.sep}`))) {
          violations.push(`unmanifested directory: ${rel}`);
        }
        walk(abs);
      } else if (!entry.isFile()) {
        violations.push(`non-regular pack file: ${rel}`);
      } else if (rel === "MANIFEST.json") {
        if (fs.readFileSync(abs, "utf-8") !== JSON.stringify(pack.manifest, null, 2)) {
          violations.push("manifest changed: MANIFEST.json");
        }
      } else {
        const expected = pack.manifest[rel];
        if (!expected) violations.push(`unmanifested file: ${rel}`);
        else if (sha256(fs.readFileSync(abs)) !== expected) violations.push(`hash mismatch: ${rel}`);
      }
    }
  };
  try {
    if (!fs.lstatSync(pack.dir).isDirectory()) violations.push("pack directory replaced");
    else walk(pack.dir);
    for (const rel of ["MANIFEST.json", ...Object.keys(pack.manifest)]) {
      if (!fs.existsSync(path.join(pack.dir, rel))) violations.push(`missing manifest file: ${rel}`);
    }
  } catch (e) {
    violations.push(`pack audit failed: ${(e as Error).message}`);
  }
  return { ok: violations.length === 0, violations };
}

export type ValidationOutcome = "admitted" | "gate_rejected" | "rejected";

export function reviewPath(repoRoot: string, paper: string, node: string, wave: number): string {
  const safeNode = node.replace(/[^A-Za-z0-9_.-]/g, "_");
  return path.join(runtimeDir(repoRoot, `paper_${paper}`, "validation"), `${safeNode}-w${wave}.json`);
}

interface ValidationReview {
  candidateHash: string;
  candidate: CandidateSubmission;
  manifest: Record<string, string>;
  refuterFindings: string | null;
  judgeRawOutput: string | null;
  judgeOutputSource: "raw" | "structured" | null;
  verdict: JudgeVerdict | null;
  appendedRow: Record<string, unknown> | null;
  rejectionObligation: Record<string, unknown> | null;
  outcome: ValidationOutcome | null;
  error: string | null;
  startedAt: string;
  refutedAt: string | null;
  judgedAt: string | null;
  finishedAt: string | null;
}

/** Refuter -> judge -> ledger. The only write paths are the gated appends. */
export async function adjudicateCandidate(candidate: CandidateSubmission, deps: {
  repoRoot: string;
  ledgers: Ledgers;
  journal: Journal;
  /** Omit to select refuter and judge independently from mission.json. */
  runner?: ValidatorRunner;
}): Promise<{ outcome: ValidationOutcome; detail: string }> {
  const frozen = structuredClone(candidate);
  const candidateHash = sha256(Buffer.from(canonicalJson(frozen)));
  const startedAt = new Date().toISOString();
  checkBinding(frozen);
  const { repoRoot, ledgers, journal } = deps;
  const runner = deps.runner ?? buildValidatorRunner(loadMissionSpec(repoRoot));
  const pack = buildContextPack(repoRoot, frozen, candidateHash);
  const review: ValidationReview = {
    candidateHash, candidate: frozen, manifest: structuredClone(pack.manifest),
    refuterFindings: null, judgeRawOutput: null, judgeOutputSource: null, verdict: null,
    appendedRow: null, rejectionObligation: null, outcome: null, error: null,
    startedAt, refutedAt: null, judgedAt: null, finishedAt: null,
  };
  const file = reviewPath(repoRoot, frozen.paper, frozen.node, frozen.wave);
  const audit = (phase: string): void => {
    const iso = checkIsolation(pack);
    if (!iso.ok) {
      const detail = `pack_tampered after ${phase}: ${iso.violations.join("; ")}`;
      journal.append({ type: "halt", reason: detail, wave: frozen.wave });
      throw new Error(detail);
    }
  };
  try {
    audit("construction");

    // 1. the refuter MUST run first and must return non-empty findings
    let refutation: RefuterReport;
    try {
      // Reviewers receive their own manifest copies; the audit's baseline stays private.
      refutation = await runner.refute(structuredClone(pack), frozen.claim);
      review.refuterFindings = refutation.findings;
    } finally {
      review.refutedAt = new Date().toISOString();
      audit("refuter");
    }
    if (!refutation.findings.trim()) {
      throw new Error("refuter returned empty findings — refutation attempt is mandatory");
    }
    // 2. the judge sees pack + findings, never the defender
    try {
      const judgment = await runner.judge(structuredClone(pack), frozen.claim, refutation.findings, raw => {
        review.judgeRawOutput = raw;
        review.judgeOutputSource = "raw";
      });
      if (review.judgeRawOutput === null) {
        review.judgeRawOutput = JSON.stringify(judgment);
        review.judgeOutputSource = "structured";
      }
      review.verdict = parseJudgeVerdict(review.judgeRawOutput);
    } finally {
      review.judgedAt = new Date().toISOString();
      audit("judge");
    }
    const verdict = review.verdict;
    journal.append({
      type: "validation_verdict", wave: frozen.wave, node: frozen.node,
      verdict: verdict.verdict, refuterFindings: refutation.findings.slice(0, 500),
      candidateHash, reviewPath: file,
    });

    if (verdict.verdict === "admit") {
      // 3a. admission = the gated append; the gate can still refuse.
      try {
        await ledgers.appendResult(frozen.resultRow);
        review.appendedRow = frozen.resultRow;
        review.outcome = "admitted";
        return { outcome: "admitted", detail: verdict.reasons };
      } catch (e) {
        review.outcome = "gate_rejected";
        review.error = (e as Error).message;
        return { outcome: "gate_rejected", detail: review.error };
      }
    }
    // 3b. rejection = an open repair obligation on the node (claim ledger)
    review.rejectionObligation = {
      paper: frozen.paper,
      entry_id: `repair-${frozen.node.replace(/[^A-Za-z0-9_:-]/g, "_")}-w${frozen.wave}`,
      kind: "obligation",
      status: "open",
      statement: `validation rejected: ${verdict.reasons}`.slice(0, 500),
      node_ids: [frozen.node],
      blocking: true,
    };
    await ledgers.appendClaimEntry(review.rejectionObligation);
    review.outcome = "rejected";
    return { outcome: "rejected", detail: verdict.reasons };
  } catch (e) {
    review.error = (e as Error).message;
    throw e;
  } finally {
    review.finishedAt = new Date().toISOString();
    fs.writeFileSync(file, JSON.stringify(review, null, 2) + "\n");
    fs.rmSync(pack.dir, { recursive: true, force: true });
  }
}

/** Real SDK validators: two fresh sessions with cwd = the pack dir. */
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
    const findings = await this.session(pack.dir, refuterPrompt(claim), this.opts.refuterModel);
    return { findings };
  }

  async judge(pack: ContextPack, claim: string, findings: string,
              captureRaw?: (raw: string) => void): Promise<JudgeVerdict> {
    const raw = await this.session(pack.dir, judgePrompt(claim, findings), this.opts.judgeModel);
    captureRaw?.(raw);
    return parseJudgeVerdict(raw);
  }
}

/** CLI validators default to read-only. If bwrap fails on the host, callers
 * must explicitly set codex.sandbox; with danger-full-access the isolation
 * rests on cwd + prompt only, not a filesystem boundary. */
export class CodexValidatorRunner implements ValidatorRunner {
  readonly name = "codex-validator";
  constructor(private opts: CodexOptions & {
    model?: string; refuterModel?: string; judgeModel?: string;
  } = {}) {}

  private async session(pack: ContextPack, role: "refuter" | "judge", prompt: string,
                        captureRaw?: (raw: string) => void): Promise<string> {
    // Logs must stay outside the manifest-audited context pack.
    const outputDir = runtimeDir(pack.dir, "codex");
    const id = `${path.basename(pack.dir)}-${role}`.replace(/[^A-Za-z0-9_.-]/g, "_");
    const finalPath = path.join(outputDir, `${id}.final.md`);
    // Even an early invocation failure must not capture a previous judge's text.
    if (captureRaw) fs.writeFileSync(finalPath, "");
    try {
      const result = await runCodexExec({
        ...this.opts,
        model: (role === "refuter" ? this.opts.refuterModel : this.opts.judgeModel) ?? this.opts.model,
        prompt, cwd: pack.dir, role: "validator", outputDir, id,
      });
      return result.finalMessage;
    } catch (e) {
      // A failed process can still have produced an auditable final message.
      try { captureRaw?.(fs.readFileSync(finalPath, "utf-8")); } catch { /* preserve the process error */ }
      throw e;
    }
  }

  async refute(pack: ContextPack, claim: string): Promise<RefuterReport> {
    return { findings: await this.session(pack, "refuter", refuterPrompt(claim)) };
  }

  async judge(pack: ContextPack, claim: string, findings: string,
              captureRaw?: (raw: string) => void): Promise<JudgeVerdict> {
    const raw = await this.session(pack, "judge", judgePrompt(claim, findings), captureRaw);
    captureRaw?.(raw);
    return parseJudgeVerdict(raw);
  }
}

/** A mission may mix model families even between refutation and judgment. */
export function buildValidatorRunner(spec: MissionSpec | null): ValidatorRunner {
  const refuter = parseModelSpec(spec?.models?.refuter);
  const judge = parseModelSpec(spec?.models?.judge);
  const models = { refuterModel: refuter.model, judgeModel: judge.model };
  const sdk = new SdkValidatorRunner(models);
  const codex = new CodexValidatorRunner({ ...spec?.codex, ...models });
  if (refuter.runner === "sdk" && judge.runner === "sdk") return sdk;
  if (refuter.runner === "codex" && judge.runner === "codex") return codex;
  return {
    name: "mixed-validator",
    refute: (pack, claim) => (refuter.runner === "codex" ? codex : sdk).refute(pack, claim),
    judge: (pack, claim, findings, captureRaw) =>
      (judge.runner === "codex" ? codex : sdk).judge(pack, claim, findings, captureRaw),
  };
}
