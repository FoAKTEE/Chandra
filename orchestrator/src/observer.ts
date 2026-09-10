/** Observer memory agent — owns the three-note hierarchy after every wave.
 *
 * Contracts (notes/multi_timescale_tracking_template.md), enforced in CODE:
 *  - iteration note  : FULL REWRITE, contains only the current wave;
 *  - nodal note      : FULL REWRITE, contains only the last N waves (default 10);
 *  - research state  : the one long-memory note, HARD-CAPPED at 10240 bytes (10KB).
 *    Before pruning, exact prior bytes are archived in the mission runtime.
 *    Generated blocks remain intact or become whole render-command pointers.
 *    A prune that still exceeds the cap is an error, not a warning. */
import * as fs from "node:fs";
import * as path from "node:path";
import type { Journal } from "./journal.js";
import { Ledgers } from "./ledger.js";
import { runtimeDir } from "./runtime.js";
import type { WavePlan, WaveResult } from "./scheduler.js";

export const RESEARCH_STATE_CAP_BYTES = 10240;
export const NODAL_WINDOW = 10;

export interface NotesLayout {
  repoRoot: string;
  iterationNote: string;
  nodalNote: string;
  researchState: string;
}

export function notesLayout(repoRoot: string, mission: string): NotesLayout {
  const base = path.join(repoRoot, "progress", mission);
  return {
    repoRoot,
    iterationNote: path.join(base, "loop_notes", "current_iter.md"),
    nodalNote: path.join(base, "nodal_note.md"),
    researchState: path.join(base, "RESEARCH_STATE.md"),
  };
}

export interface WaveSummary {
  runId?: string;
  wave: number;
  scheduled: string[];
  admitted: number;
  rejected: number;
  failed: number;
  noProgress: number;
}

/** Rewrites prose to fit its byte budget; generated blocks are kept outside
 * the runner by the memory pass. */
export interface ObserverRunner {
  readonly name: string;
  pruneResearchState(content: string, maxBytes: number): Promise<string>;
}

export class TruncatingObserver implements ObserverRunner {
  readonly name = "truncating-observer";
  async pruneResearchState(content: string, maxBytes: number): Promise<string> {
    const lines = content.match(/[^\n]*\n|[^\n]+$/g) ?? [];
    const kept: string[] = [];
    let used = 0;
    for (const line of lines) {
      const cost = Buffer.byteLength(line, "utf-8");
      if (used + cost > maxBytes) break;
      kept.push(line);
      used += cost;
    }
    return kept.join("");
  }
}

export class SdkObserverRunner implements ObserverRunner {
  readonly name = "sdk-observer";
  constructor(private opts: { model?: string } = {}) {}
  async pruneResearchState(content: string, maxBytes: number): Promise<string> {
    if (maxBytes === 0) return "";
    const { query } = await import("@anthropic-ai/claude-agent-sdk");
    let out = "";
    const q = query({
      prompt: [
        `Rewrite this research-state note to AT MOST ${maxBytes} bytes (UTF-8)`,
        `while keeping the mission through-line: mission/phase, ledger pointers,`,
        `open questions, and next steps. Delete or compress anything restorable`,
        `from the ledgers or archived note (tables -> pointers, prose -> bullets).`,
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

interface NotePart { text: string; generated?: string; command?: string }

/** Preserve exact spans, including line endings. Broken marker pairs fail
 * closed instead of turning part of a generated table into prunable prose. */
function noteParts(content: string): NotePart[] {
  const parts: NotePart[] = [];
  const markers = /^[ \t]*<!-- (BEGIN|END) GENERATED: ([^\r\n]*?) -->[ \t]*(?:\r?\n|$)/gm;
  let cursor = 0;
  let open: { start: number; label: string } | undefined;
  for (const match of content.matchAll(markers)) {
    const start = match.index!;
    if (match[1] === "BEGIN") {
      if (open) throw new Error("observer prune failed: nested generated block");
      if (start > cursor) parts.push({ text: content.slice(cursor, start) });
      open = { start, label: match[2] };
    } else {
      if (!open || !(open.label === match[2] || open.label.startsWith(match[2] + " "))) {
        throw new Error("observer prune failed: unmatched generated block marker");
      }
      cursor = start + match[0].length;
      parts.push({ text: content.slice(open.start, cursor), generated: match[2],
        command: open.label.match(/\(([^()]*\brender[\w-]*\b[^()]*)\)/)?.[1] });
      open = undefined;
    }
  }
  if (open) throw new Error("observer prune failed: missing generated block END marker");
  if (cursor < content.length) parts.push({ text: content.slice(cursor) });
  return parts;
}

function blockPointer(part: NotePart): string {
  if (!part.command) throw new Error(`observer prune failed: no render command for ${part.generated}`);
  return `> [generated: ${part.generated}; restore with \`${part.command}\`]\n`;
}

function refreshAcceptedResults(content: string, block: string, paper: string): string {
  const parts = noteParts(content);
  const name = `accepted-results paper_${paper}`;
  const existing = parts.find(p => p.generated === name);
  if (existing) {
    existing.text = block;
    return parts.map(p => p.text).join("");
  }
  // A previous cap pass may have replaced the whole block with its pointer.
  for (const part of parts.filter(p => !p.generated)) {
    for (const pointer of part.text.matchAll(/^> \[generated: [^\r\n]+(?:\r?\n|$)/gm)) {
      if (!pointer[0].startsWith(`> [generated: ${name};`)) continue;
      part.text = part.text.slice(0, pointer.index!) + block + part.text.slice(pointer.index! + pointer[0].length);
      return parts.map(p => p.text).join("");
    }
  }
  let at = content.length;
  let offset = 0;
  let mission = false;
  sections: for (const part of parts) {
    if (!part.generated) for (const heading of part.text.matchAll(/^## ([^\r\n]+)\r?$/gm)) {
      if (mission) { at = offset + heading.index!; break sections; }
      if (heading[1].trim() === "Mission") mission = true;
    }
    offset += part.text.length;
  }
  return content.slice(0, at) + "\n" + block + "\n" + content.slice(at);
}

async function pruneNote(content: string, maxBytes: number, runner: ObserverRunner): Promise<string> {
  const parts = noteParts(content);
  const bytes = () => parts.reduce((n, p) => n + Buffer.byteLength(p.text), 0);
  // Remove/compress non-generated prose first, from the tail. Runners never
  // receive generated bytes, so even an SDK rewrite cannot split a block.
  for (let i = parts.length - 1; i >= 0 && bytes() > maxBytes; i--) {
    const part = parts[i];
    if (part.generated) continue;
    const budget = Math.max(0, Buffer.byteLength(part.text) - (bytes() - maxBytes));
    const beforeBlock = Boolean(parts[i + 1]?.generated);
    let pruned = await runner.pruneResearchState(part.text, Math.max(0, budget - (beforeBlock ? 1 : 0)));
    if (beforeBlock && pruned && !pruned.endsWith("\n")) pruned += "\n";
    if (Buffer.byteLength(pruned) > budget || /^[ \t]*<!-- (?:BEGIN|END) GENERATED:/m.test(pruned)) {
      throw new Error(`observer prune failed: prose exceeds ${budget} bytes or introduces generated markers`);
    }
    part.text = pruned;
  }
  for (let i = parts.length - 1; i >= 0 && bytes() > maxBytes; i--) {
    if (parts[i].generated) parts[i].text = blockPointer(parts[i]);
  }
  const pruned = parts.map(p => p.text).join("");
  if (Buffer.byteLength(pruned) > maxBytes) {
    throw new Error(`observer prune failed: research state still ${Buffer.byteLength(pruned)} bytes > cap ${maxBytes}`);
  }
  return pruned;
}

/** Iteration note: the whole file IS the current wave. */
export function writeIterationNote(layout: NotesLayout, plan: WavePlan, result: WaveResult): void {
  const lines = [
    `# Current wave — ${plan.wave}`,
    ``,
    `Full-rewrite note: this file holds exactly one wave; wave history is in the runtime journal.`,
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
    `Full-rewrite note: keeps only the last ${NODAL_WINDOW} waves; history is in the runtime journal.`,
    ``,
    `| wave | scheduled | admitted | rejected | failed | no_progress | run |`,
    `|---|---|---|---|---|---|---|`,
    ...window.map(w => `| ${w.wave} | ${w.scheduled.length} | ${w.admitted} | ${w.rejected} | ${w.failed} | ${w.noProgress} | ${w.runId ?? "legacy"} |`),
    ``,
  ];
  write(layout.nodalNote, lines.join("\n"));
}

export function researchStateScaffold(paper: string): string {
  return [
    `# Research state — ${paper}`,
    ``,
    `Long-memory note, HARD CAP ${RESEARCH_STATE_CAP_BYTES} bytes (observer-enforced;`,
    `prior bytes are archived before pruning). Canonical state lives in the ledgers:`,
    ``,
    `- results: \`results/ledgers/result/paper_${paper}/results.jsonl\` (render-md / render-state)`,
    `- nodes/DAG: \`results/ledgers/knowledge/paper_${paper}/nodes.jsonl\``,
    `- claims/obligations/assumptions: \`results/ledgers/claim/paper_${paper}/entries.jsonl\``,
    `- trials: \`results/ledgers/error/paper_${paper}/trials.jsonl\``,
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
  const original = fs.readFileSync(layout.researchState);
  let content = refreshAcceptedResults(original.toString("utf-8"),
    await new Ledgers(layout.repoRoot).renderState(paper), paper);
  let pruned = false;
  if (original.length > RESEARCH_STATE_CAP_BYTES || Buffer.byteLength(content) > RESEARCH_STATE_CAP_BYTES) {
    const archive = path.join(runtimeDir(layout.repoRoot, `paper_${paper}`, "notes"),
      `RESEARCH_STATE.w${plan.wave}.${new Date().toISOString()}.md`);
    // Archive the input file, before either regenerated views or pruning can
    // replace bytes that may never have reached a commit.
    const fd = fs.openSync(archive, "wx");
    try { fs.writeFileSync(fd, original); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    journal.append({ type: "note_archived", wave: plan.wave, path: archive, bytes: original.length });
    const footer = `\n> [pruned by observer — full text archived at \`${archive}\`]\n`;
    content = await pruneNote(content, RESEARCH_STATE_CAP_BYTES - Buffer.byteLength(footer), runner) + footer;
    pruned = true;
  }
  write(layout.researchState, content);
  const researchStateBytes = Buffer.byteLength(content, "utf-8");
  journal.append({ type: "memory_pruned", wave: plan.wave, researchStateBytes });
  return { researchStateBytes, pruned };
}

/** Wave summaries reconstructed from the journal (for the nodal window). */
export function waveHistory(journal: Journal): WaveSummary[] {
  const planned = new Map<string, string[]>();
  const history: WaveSummary[] = [];
  let runId: string | undefined;
  let started = false;
  for (const [index, { msg: m }] of journal.read().entries()) {
    if (m.type === "run_started") { runId = m.runId; started = true; }
    if (m.type === "mission_loaded") {
      if (!started) runId = `legacy-${index}`;
      started = false;
    }
    if (m.type === "wave_planned") planned.set(JSON.stringify([runId, m.wave]), m.scheduled);
    if (m.type === "wave_finished") history.push({
      ...(runId ? { runId } : {}), wave: m.wave,
      scheduled: planned.get(JSON.stringify([runId, m.wave])) ?? [],
      admitted: m.admitted, rejected: m.rejected, failed: m.failed, noProgress: m.noProgress,
    });
  }
  return history;
}
