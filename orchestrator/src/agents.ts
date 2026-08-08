/** SDK-touching layer: spawns real Claude Agent SDK sessions. Kept thin and
 * imported dynamically so the pure core (dag/scheduler/journal/ledger) tests
 * run without the SDK or an API key.
 *
 * Context-pack discipline (alignment kernel §5): a worker receives the kernel,
 * the admission contract, and ONLY its node's inputs — never the parent's
 * context. Isolation is what the session can read, not a prose instruction. */
import * as path from "node:path";
import type { WorkerRunner } from "./scheduler.js";
import type { WorkerTask } from "./types.js";

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

function jobPrompt(job: Job, ctx: JobContext): string {
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
    ].join("\n");
  }
  return [
    `You are a stage-3 WRITE agent for paper ${ctx.paper}.`,
    ...shared,
    `Follow pipelines/3-write/spec.md: render the living paper from the result +`,
    `knowledge ledgers (solid rows only) into results/<project>/paper_${ctx.paper}/paper/,`,
    `then append one line to its GENERATION_LOG. Never write over the scaffold template.`,
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
