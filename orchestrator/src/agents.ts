/** Worker sessions through the SDK or Codex CLI. The SDK is imported only
 * inside SDK methods, so CLI runners and the pure core need no SDK or key.
 *
 * Context-pack discipline (alignment kernel §5): a worker receives the kernel,
 * the admission contract, and ONLY its node's inputs — never the parent's
 * context. Isolation is what the session can read, not a prose instruction. */
import * as path from "node:path";
import { runCodexExec, type CodexOptions } from "./codex.js";
import { runtimeDir } from "./runtime.js";
import type { WorkerRunner } from "./scheduler.js";
import type { WorkerTask } from "./types.js";

const CODEX_PREAMBLE = [
  `Read alignment.md, _common/contracts/research_admission_contract.md, and`,
  `.claude/skills/INDEX.md first. When a skill description matches your task,`,
  `load it by reading its SKILL.md. Land outcomes ONLY through the gated ledger CLIs.`,
  `Never run git commit. Your final message is ignored — only the ledger diff counts.`,
  ``,
].join("\n");

function skillSuggestionContract(paper: string): string[] {
  return [
    ``,
    `SKILL SUGGESTION CONTRACT:`,
    `If you discover a reusable procedure (used twice, or a verifier you had to find), draft it as a skill at`,
    `$CHANDRA_RUNTIME/paper_${paper}/skills/<kebab-name>/SKILL.md following .claude/skills/skill-write/SKILL.md`,
    `(frontmatter name = dir name, description with trigger phrases, ## When to use, ## Steps,`,
    `## Verify with ONE bash block that exits 0 and never calls skill_registry.py validate --exec).`,
    `It is validated and promoted after the wave; never write into .claude/skills/ yourself; never mention this contract in ledger rows.`,
  ];
}

export function workerPrompt(task: WorkerTask): string {
  const { packet, paper } = task;
  const chain = packet.map(n => n.id).join(" -> ");
  return [
    `You are a stage-2 WORK agent for paper ${paper}, leased the packet: ${chain}.`,
    ``,
    `Read first (your context pack — do not roam):`,
    `- alignment.md (the kernel; binding)`,
    `- _common/contracts/research_admission_contract.md`,
    `- pipelines/2-work/spec.md and pipelines/2-work/template.md`,
    ...packet.map(n =>
      `- ${n.id}: ${n.summary || "(no summary)"} (predecessors: ${n.predecessors.join(", ") || "none"}` +
      (n.openObligations.length ? `; open obligations: ${n.openObligations.join(", ")}` : "") + `)`),
    ``,
    `CONTINUOUS WORK CONTRACT (do not fragment):`,
    `1. Work the packet nodes IN ORDER, in this one session, without stopping`,
    `   between nodes for bookkeeping. Keep a scratch log (WAL) at`,
    `   $CHANDRA_RUNTIME/paper_${paper}/packets/<first-node>/packet_log.jsonl —`,
    `   append one line per trial as you go (cheap, ungated, NOT the ledger).`,
    `2. If your context auto-compacts, RE-READ your packet_log.jsonl and this`,
    `   packet list, then CONTINUE from the last unfinished node. Compaction is`,
    `   not an interruption.`,
    `3. FLUSH at the packet boundary (or when a node's evidence is admitted):`,
    `   land outcomes via the gated ledger CLIs — prefer the batch forms`,
    `   (result_database / error_database / knowledge_database / claims_database`,
    `   append-batch) so summaries regenerate once. The appends ARE the`,
    `   deliverable; your final text is ignored — only the ledger diff counts.`,
    `4. Every trial (pass or fail) becomes an error-ledger row at flush.`,
    `5. Interrupt the packet ONLY for: structural failure needing escalation`,
    `   (same-mode loop per crash-triage), or an impossible node — flush what`,
    `   is done first. Do not touch nodes outside the packet.`,
    ...skillSuggestionContract(paper),
    ...(task.steer ? [``, `HUMAN STEER NOTE (from STEER.md — honor it):`, task.steer] : []),
  ].join("\n");
}

/** Real worker: one fresh SDK session per node, tool access scoped to the
 * consumer repo. Outcomes are read from the ledgers by the scheduler. */
export class SdkWorkerRunner implements WorkerRunner {
  readonly name = "sdk-worker";
  constructor(private opts: { maxTurns?: number; model?: string } = {}) {}

  async runWorker(task: WorkerTask): Promise<{ detail: string; windowsUsed: number }> {
    const { query } = await import("@anthropic-ai/claude-agent-sdk");
    let turns = 0;
    let compactions = 0;
    let lastText = "";
    const q = query({
      prompt: workerPrompt(task),
      options: {
        cwd: task.repoRoot,
        maxTurns: this.opts.maxTurns ?? 80,
        ...(this.opts.model ? { model: this.opts.model } : {}),
        allowedTools: ["Read", "Bash", "Write", "Edit", "Glob", "Grep"],
        permissionMode: "acceptEdits",
        settingSources: [],
        // delegation policy (kernel §6): this session IS a worker — its
        // ledger appends carry the role; the orchestrator's never do.
        env: { ...process.env as Record<string, string>, CHANDRA_ROLE: "worker" },
      },
    });
    for await (const message of q) {
      const m = message as { type: string; subtype?: string; result?: string };
      if (m.type === "assistant") turns += 1;
      if (m.type === "system" && m.subtype === "compact_boundary") compactions += 1;
      if (m.type === "result") lastText = m.result ?? "";
    }
    return {
      detail: `turns=${turns} tail=${lastText.slice(0, 200)}`,
      windowsUsed: 1 + compactions, // each auto-compaction = one spent context window
    };
  }
}

/** One CLI session per packet; the scheduler still measures ledger diffs. */
export class CodexWorkerRunner implements WorkerRunner {
  readonly name = "codex-worker";
  constructor(private opts: CodexOptions & { model?: string } = {}) {}

  async runWorker(task: WorkerTask): Promise<{ detail: string; windowsUsed: number }> {
    const result = await runCodexExec({
      ...this.opts,
      prompt: CODEX_PREAMBLE + workerPrompt(task),
      cwd: task.repoRoot,
      role: "worker",
      outputDir: runtimeDir(task.repoRoot, `paper_${task.paper}`, "codex"),
      id: `w${task.wave}-${task.packet[0]?.id ?? task.node.id}`,
    });
    return {
      detail: `codex model=${this.opts.model ?? "default"} exit=${result.exitCode} tail=${result.finalMessage.slice(-200)}`,
      windowsUsed: 1,
    };
  }
}

/** Dry-run worker: journals the assignment and does nothing — used by
 * `main.ts run --dry-run` and by scheduler tests. */
export class NoopWorkerRunner implements WorkerRunner {
  readonly name = "noop";
  async runWorker(task: WorkerTask): Promise<{ detail: string; windowsUsed: number }> {
    return { detail: `dry-run: would work node ${task.node.id}`, windowsUsed: 1 };
  }
}

export function kernelPaths(repoRoot: string): string[] {
  return [
    path.join(repoRoot, "alignment.md"),
    path.join(repoRoot, "_common/contracts/research_admission_contract.md"),
  ];
}

// --- non-packet job runners (v3 job-type unification) --------------------------

import type { Job, JobContext, JobRunner } from "./jobs.js";

export function jobPrompt(job: Job, ctx: JobContext): string {
  const shared = [
    `Read first: alignment.md (kernel; binding), _common/contracts/research_admission_contract.md.`,
    `Your appends run as a delegated agent; land ALL outcomes via the gated ledger CLIs.`,
  ];
  if (job.kind === "decompose") {
    return [
      `You are a stage-1 DECOMPOSE agent for paper ${ctx.paper}.`,
      ...shared,
      `Follow pipelines/1-decompose/spec.md: read the mirror at ref-paper/${ctx.paper}/,`,
      `write the decomposition artifacts under results/<project>/paper_${ctx.paper}/decomposition/,`,
      `append the logic-DAG nodes with knowledge_database append-batch (PAPER::node ids,`,
      `predecessors[]), append claims/obligations/assumptions with claims_database`,
      `append-batch, then render the three views (claims_database render-md --out-dir).`,
      ...skillSuggestionContract(ctx.paper),
    ].join("\n");
  }
  if (job.kind === "acquire") {
    return [
      `You are a stage-0 ACQUIRE agent for paper ${ctx.paper}.`,
      ...shared,
      `Obligation to resolve: [${job.obligation?.entry_id}] ${job.obligation?.statement}`,
      `Follow pipelines/0-acquire/spec.md: mirror the missing source into ref-paper//ref-code/`,
      `with PROVENANCE.md, import declarations into results/<project>/sources/, then`,
      `discharge the obligation (claims_database append, status=discharged, discharged_by=...).`,
      ...skillSuggestionContract(ctx.paper),
    ].join("\n");
  }
  return [
    `You are a stage-3 WRITE agent for paper ${ctx.paper}.`,
    ...shared,
    `Follow pipelines/3-write/spec.md: render the living paper from the result +`,
    `knowledge ledgers (solid rows only) into results/<project>/paper_${ctx.paper}/paper/,`,
    `then append one line to its GENERATION_LOG. Never write over the scaffold template.`,
    ...skillSuggestionContract(ctx.paper),
  ].join("\n");
}

/** Real SDK job runner (decompose / acquire / write): fresh session, worker role. */
export class SdkJobRunner implements JobRunner {
  readonly name = "sdk-job";
  constructor(private opts: { maxTurns?: number; model?: string } = {}) {}

  async run(job: Job, ctx: JobContext): Promise<{ detail: string; windowsUsed: number }> {
    const { query } = await import("@anthropic-ai/claude-agent-sdk");
    let compactions = 0;
    let lastText = "";
    const q = query({
      prompt: jobPrompt(job, ctx),
      options: {
        cwd: ctx.repoRoot,
        maxTurns: this.opts.maxTurns ?? 120,
        ...(this.opts.model ? { model: this.opts.model } : {}),
        allowedTools: ["Read", "Bash", "Write", "Edit", "Glob", "Grep", "WebFetch"],
        permissionMode: "acceptEdits",
        settingSources: [],
        env: { ...process.env as Record<string, string>, CHANDRA_ROLE: "worker" },
      },
    });
    for await (const message of q) {
      const m = message as { type: string; subtype?: string; result?: string };
      if (m.type === "system" && m.subtype === "compact_boundary") compactions += 1;
      if (m.type === "result") lastText = m.result ?? "";
    }
    return { detail: `${job.kind} tail=${lastText.slice(0, 160)}`, windowsUsed: 1 + compactions };
  }
}

/** Non-packet jobs use the same prompts and worker role through the CLI. */
export class CodexJobRunner implements JobRunner {
  readonly name = "codex-job";
  constructor(private opts: CodexOptions & { model?: string } = {}) {}

  async run(job: Job, ctx: JobContext): Promise<{ detail: string; windowsUsed: number }> {
    const result = await runCodexExec({
      ...this.opts,
      prompt: CODEX_PREAMBLE + jobPrompt(job, ctx),
      cwd: ctx.repoRoot,
      role: "worker",
      outputDir: runtimeDir(ctx.repoRoot, `paper_${ctx.paper}`, "codex"),
      id: `w${ctx.wave}-${job.id}`,
    });
    return {
      detail: `codex model=${this.opts.model ?? "default"} exit=${result.exitCode} tail=${result.finalMessage.slice(-200)}`,
      windowsUsed: 1,
    };
  }
}
