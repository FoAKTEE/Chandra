/** Observer memory agent — owns the three-note hierarchy after every wave.
 *
 * Contracts (notes/multi_timescale_tracking_template.md), enforced in CODE:
 *  - iteration note  : FULL REWRITE, contains only the current wave;
 *  - nodal note      : FULL REWRITE, contains only the last N waves (default 10);
 *  - research state  : the one long-memory note, HARD-CAPPED at 10240 bytes (10KB).
 *    If it exceeds the cap the observer PRUNES it (deletions are safe: the
 *    note is committed, so anything removed is recoverable from git history).
 *    A prune that still exceeds the cap is an error, not a warning. */
import * as fs from "node:fs";
import * as path from "node:path";
import type { Journal } from "./journal.js";
import type { WavePlan, WaveResult } from "./scheduler.js";

export const RESEARCH_STATE_CAP_BYTES = 10240;
export const NODAL_WINDOW = 10;

export interface NotesLayout {
  iterationNote: string;
  nodalNote: string;
  researchState: string;
}

export function notesLayout(repoRoot: string, mission: string): NotesLayout {
  const base = path.join(repoRoot, "progress", mission);
  return {
    iterationNote: path.join(base, "loop_notes", "current_iter.md"),
    nodalNote: path.join(base, "nodal_note.md"),
    researchState: path.join(base, "RESEARCH_STATE.md"),
  };
}

export interface WaveSummary {
  wave: number;
  scheduled: string[];
  admitted: number;
  rejected: number;
  failed: number;
  noProgress: number;
}

/** Rewrites long-memory prose to fit the cap. The SDK observer asks a model
 * to simplify; the deterministic pruner cuts whole lines from the tail. */
export interface ObserverRunner {
  readonly name: string;
  pruneResearchState(content: string, maxBytes: number): Promise<string>;
}

export class TruncatingObserver implements ObserverRunner {
  readonly name = "truncating-observer";
  async pruneResearchState(content: string, maxBytes: number): Promise<string> {
    const marker = "\n> [pruned by observer — full text in git history]\n";
    const budget = maxBytes - Buffer.byteLength(marker, "utf-8");
    const lines = content.split("\n");
    const kept: string[] = [];
    let used = 0;
    for (const line of lines) {
      const cost = Buffer.byteLength(line + "\n", "utf-8");
      if (used + cost > budget) break;
      kept.push(line);
      used += cost;
    }
    return kept.join("\n") + marker;
  }
}

export class SdkObserverRunner implements ObserverRunner {
  readonly name = "sdk-observer";
  constructor(private opts: { model?: string } = {}) {}
  async pruneResearchState(content: string, maxBytes: number): Promise<string> {
    const { query } = await import("@anthropic-ai/claude-agent-sdk");
    let out = "";
    const q = query({
      prompt: [
        `Rewrite this research-state note to AT MOST ${maxBytes} bytes (UTF-8)`,
        `while keeping the mission through-line: mission/phase, ledger pointers,`,
        `open questions, and next steps. Delete or compress anything restorable`,
        `from the ledgers or git history (tables -> pointers, prose -> bullets).`,
        `Reply with ONLY the rewritten note.`,
        `---`,
        content,
      ].join("\n"),
      options: {
        maxTurns: 4,
        ...(this.opts.model ? { model: this.opts.model } : {}),
        allowedTools: [],
        settingSources: [],
      },
    });
    for await (const message of q) {
      const m = message as { type: string; result?: string };
      if (m.type === "result") out = m.result ?? "";
    }
    return out;
  }
}

function write(filePath: string, content: string): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, "utf-8");
}

/** Iteration note: the whole file IS the current wave. */
export function writeIterationNote(layout: NotesLayout, plan: WavePlan, result: WaveResult): void {
  const lines = [
    `# Current wave — ${plan.wave}`,
    ``,
    `Full-rewrite note: this file holds exactly one wave; history is in git log.`,
    ``,
    `## Scheduled nodes (ready frontier)`,
    ...plan.scheduled.map(n => `- ${n.id} (depth ${n.depth}${n.openObligations.length ? `, obligations: ${n.openObligations.join(", ")}` : ""})`),
    ``,
    `## Outcomes (ledger-diff, not worker claims)`,
    ...result.reports.map(r => `- ${r.node}: **${r.outcome}** — ${r.detail.slice(0, 160)}`),
    ``,
    `## Totals`,
    `admitted=${result.admitted} rejected=${result.rejected} failed=${result.failed} no_progress=${result.noProgress} windows_used=${result.windowsUsed}`,
    ``,
  ];
  write(layout.iterationNote, lines.join("\n"));
}

/** Nodal note: the last NODAL_WINDOW waves, nothing older. */
export function writeNodalNote(layout: NotesLayout, history: WaveSummary[]): void {
  const window = history.slice(-NODAL_WINDOW);
  const first = window[0]?.wave ?? 0;
  const last = window[window.length - 1]?.wave ?? 0;
  const lines = [
    `# Nodal note — waves ${first}–${last}`,
    ``,
    `Full-rewrite note: keeps only the last ${NODAL_WINDOW} waves; history in git log.`,
    ``,
    `| wave | scheduled | admitted | rejected | failed | no_progress |`,
    `|---|---|---|---|---|---|`,
    ...window.map(w => `| ${w.wave} | ${w.scheduled.length} | ${w.admitted} | ${w.rejected} | ${w.failed} | ${w.noProgress} |`),
    ``,
  ];
  write(layout.nodalNote, lines.join("\n"));
}

export function researchStateScaffold(paper: string): string {
  return [
    `# Research state — ${paper}`,
    ``,
    `Long-memory note, HARD CAP ${RESEARCH_STATE_CAP_BYTES} bytes (observer-enforced;`,
    `pruned detail is in git history). Canonical state lives in the ledgers:`,
    ``,
    `- results: \`result-database/paper_${paper}/results.jsonl\` (render-md / render-state)`,
    `- nodes/DAG: \`knowledge-database/paper_${paper}/nodes.jsonl\``,
    `- claims/obligations/assumptions: \`claim-database/paper_${paper}/entries.jsonl\``,
    `- trials: \`error-database/paper_${paper}/trials.jsonl\``,
    ``,
    `## Mission`,
    `(fill: goal, phase, branch)`,
    ``,
    `## Open questions for the human`,
    `(none yet)`,
    ``,
    `## Next steps`,
    `(scheduler-owned: the ready frontier is computed, not planned here)`,
    ``,
  ].join("\n");
}

export interface ObserverReport {
  researchStateBytes: number;
  pruned: boolean;
}

/** Post-wave memory pass: rewrite the two snapshot notes, enforce the cap. */
export async function runObserver(deps: {
  layout: NotesLayout;
  plan: WavePlan;
  result: WaveResult;
  history: WaveSummary[];
  journal: Journal;
  runner: ObserverRunner;
  paper: string;
}): Promise<ObserverReport> {
  const { layout, plan, result, history, journal, runner, paper } = deps;
  writeIterationNote(layout, plan, result);
  writeNodalNote(layout, history);

  if (!fs.existsSync(layout.researchState)) {
    write(layout.researchState, researchStateScaffold(paper));
  }
  let content = fs.readFileSync(layout.researchState, "utf-8");
  let pruned = false;
  if (Buffer.byteLength(content, "utf-8") > RESEARCH_STATE_CAP_BYTES) {
    content = await runner.pruneResearchState(content, RESEARCH_STATE_CAP_BYTES);
    const bytes = Buffer.byteLength(content, "utf-8");
    if (bytes > RESEARCH_STATE_CAP_BYTES) {
      throw new Error(
        `observer prune failed: research state still ${bytes} bytes > cap ${RESEARCH_STATE_CAP_BYTES}`);
    }
    write(layout.researchState, content);
    pruned = true;
  }
  const researchStateBytes = Buffer.byteLength(content, "utf-8");
  journal.append({ type: "memory_pruned", wave: plan.wave, researchStateBytes });
  return { researchStateBytes, pruned };
}

/** Wave summaries reconstructed from the journal (for the nodal window). */
export function waveHistory(journal: Journal): WaveSummary[] {
  const planned = new Map(journal.ofType("wave_planned").map(m => [m.wave, m.scheduled]));
  return journal.ofType("wave_finished").map(m => ({
    wave: m.wave,
    scheduled: planned.get(m.wave) ?? [],
    admitted: m.admitted,
    rejected: m.rejected,
    failed: m.failed,
    noProgress: m.noProgress,
  }));
}
