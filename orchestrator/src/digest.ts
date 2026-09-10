/** Routine human digests follow completed context windows, counted in
 * WorkerReport.windowsUsed (default threshold: 5). Every terminal exit
 * emits a final digest, including diagnostics when integrity checks fail. */
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
  final?: boolean;
}

export async function composeDigest(deps: DigestDeps): Promise<string> {
  const { journal, ledgers, paper } = deps;
  const preflight = journal.ofType("preflight").at(-1);
  const run = journal.ofType("run_started").at(-1);
  let state: string[];
  if (preflight && !preflight.ok) {
    // Terminal integrity failures must remain reportable even when Python or
    // a ledger is unreadable. Never render corrupt data as healthy counters.
    state = ["Mission state unavailable: the latest preflight failed.",
      ...preflight.unreadable.map(reason => `- ${reason}`)];
  } else {
    const [know, results, claims] = await Promise.all([
      ledgers.knowledge(paper), ledgers.results(paper), ledgers.claims(paper),
    ]);
    const solid = know.filter(r => r.status === "solid").length;
    const openObligations = claims.filter(c => c.kind === "obligation" && c.status === "open");
    state = [
      `- nodes: ${know.length} known, ${solid} solid`,
      `- results: ${results.length} rows (latest per id)`,
      `- open obligations: ${openObligations.length}`,
      ...openObligations.slice(0, 10).map(o => `  - [${o.entry_id}] ${String(o.statement ?? "").slice(0, 120)}`),
    ];
  }
  const recent = waveHistory(journal).slice(-5);
  return [
    `# Human digest — ${paper} (wave ${deps.wave})`,
    ``,
    `Run: ${run?.runId ?? "legacy (not recorded)"}`,
    preflight ? `Preflight: ok=${preflight.ok}; breaks=${preflight.breaks}; unreadable=${preflight.unreadable.length}`
      : `Preflight: not recorded`,
    ``,
    `${deps.final ? "Final" : "Routine"} update after ${windowsSinceLastDigest(journal)} completed context windows`,
    `(cadence: every ${deps.threshold ?? DIGEST_WINDOW_THRESHOLD}). Breakers interrupt immediately regardless.`,
    ``,
    `## Mission state (from the ledgers)`,
    ...state,
    ``,
    `## Recent waves`,
    `| wave | scheduled | admitted | rejected | failed | no_progress | run |`,
    `|---|---|---|---|---|---|---|`,
    ...recent.map(w => `| ${w.wave} | ${w.scheduled.length} | ${w.admitted} | ${w.rejected} | ${w.failed} | ${w.noProgress} | ${w.runId ?? "legacy"} |`),
    ``,
    `Full detail: the ledgers + \`${journal.filePath}\` (nothing in this file is canonical).`,
    ``,
  ].join("\n");
}

export async function maybeEmitDigest(deps: DigestDeps):
    Promise<{ emitted: boolean; windows: number; path?: string }> {
  const threshold = deps.threshold ?? DIGEST_WINDOW_THRESHOLD;
  const windows = windowsSinceLastDigest(deps.journal);
  if (!deps.final && windows < threshold) return { emitted: false, windows };
  const digestPath = path.join(deps.missionDir, "HUMAN_DIGEST.md");
  fs.mkdirSync(deps.missionDir, { recursive: true });
  fs.writeFileSync(digestPath, await composeDigest(deps), "utf-8");
  deps.journal.append({
    type: "digest_emitted", wave: deps.wave, afterWindows: windows, path: digestPath,
    ...(deps.final ? { final: true as const } : {}),
  });
  return { emitted: true, windows, path: digestPath };
}
