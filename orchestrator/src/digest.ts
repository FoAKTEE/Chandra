/** Human digest cadence: the human is updated only after 5 CONSECUTIVE
 * completed context windows (a window = one worker session completing or
 * auto-compacting, counted in WorkerReport.windowsUsed). Circuit breakers
 * still interrupt immediately — this cadence only paces routine updates. */
import * as fs from "node:fs";
import * as path from "node:path";
import type { Journal } from "./journal.js";
import type { Ledgers } from "./ledger.js";
import { waveHistory } from "./observer.js";

export const DIGEST_WINDOW_THRESHOLD = 5;

/** Context windows spent since the last digest (whole journal if none). */
export function windowsSinceLastDigest(journal: Journal): number {
  const entries = journal.read();
  let lastDigest = -1;
  entries.forEach((e, i) => { if (e.msg.type === "digest_emitted") lastDigest = i; });
  let windows = 0;
  for (let i = lastDigest + 1; i < entries.length; i++) {
    const m = entries[i].msg;
    if (m.type === "worker_done") windows += m.report.windowsUsed;
  }
  return windows;
}

export interface DigestDeps {
  journal: Journal;
  ledgers: Ledgers;
  paper: string;
  /** progress/<mission> directory the digest lands in */
  missionDir: string;
  wave: number;
  threshold?: number;
}

export async function composeDigest(deps: DigestDeps): Promise<string> {
  const { journal, ledgers, paper } = deps;
  const know = await ledgers.knowledge(paper);
  const results = await ledgers.results(paper);
  const claims = await ledgers.claims(paper);
  const solid = know.filter(r => r.status === "solid").length;
  const openObligations = claims.filter(c => c.kind === "obligation" && c.status === "open");
  const recent = waveHistory(journal).slice(-5);
  return [
    `# Human digest — ${paper} (wave ${deps.wave})`,
    ``,
    `Routine update after ${windowsSinceLastDigest(journal)} completed context windows`,
    `(cadence: every ${deps.threshold ?? DIGEST_WINDOW_THRESHOLD}). Breakers interrupt immediately regardless.`,
    ``,
    `## Mission state (from the ledgers)`,
    `- nodes: ${know.length} known, ${solid} solid`,
    `- results: ${results.length} rows (latest per id)`,
    `- open obligations: ${openObligations.length}`,
    ...openObligations.slice(0, 10).map(o => `  - [${o.entry_id}] ${String(o.statement ?? "").slice(0, 120)}`),
    ``,
    `## Recent waves`,
    `| wave | scheduled | admitted | rejected | failed | no_progress |`,
    `|---|---|---|---|---|---|`,
    ...recent.map(w => `| ${w.wave} | ${w.scheduled.length} | ${w.admitted} | ${w.rejected} | ${w.failed} | ${w.noProgress} |`),
    ``,
    `Full detail: the ledgers + \`progress/.../journal.jsonl\` (nothing in this file is canonical).`,
    ``,
  ].join("\n");
}

export async function maybeEmitDigest(deps: DigestDeps):
    Promise<{ emitted: boolean; windows: number; path?: string }> {
  const threshold = deps.threshold ?? DIGEST_WINDOW_THRESHOLD;
  const windows = windowsSinceLastDigest(deps.journal);
  if (windows < threshold) return { emitted: false, windows };
  const digestPath = path.join(deps.missionDir, "HUMAN_DIGEST.md");
  fs.mkdirSync(deps.missionDir, { recursive: true });
  fs.writeFileSync(digestPath, await composeDigest(deps), "utf-8");
  deps.journal.append({
    type: "digest_emitted", wave: deps.wave, afterWindows: windows, path: digestPath,
  });
  return { emitted: true, windows, path: digestPath };
}
