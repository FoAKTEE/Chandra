/** Drafts stay in runtime storage; only the Python registry gate admits skills. */
import { execFile } from "node:child_process";
import { mkdir, rename } from "node:fs/promises";
import * as path from "node:path";
import { promisify } from "node:util";
import { runtimeDir } from "./runtime.js";

const execFileP = promisify(execFile);

/** Mirrors the skill registry's harvest JSON report. */
export interface HarvestReport {
  promoted: { name: string; source: string; path: string }[];
  rejected: { name: string; source: string; errors: string[] }[];
}

export function skillDraftsDir(repoRoot: string, paper: string): string {
  return path.join(runtimeDir(repoRoot, `paper_${paper}`), "skills");
}

/** Harvest through the gate, then move admitted drafts out of the next sweep.
 * Two-argument callers archive as wave 1; the mission loop supplies its wave. */
export async function harvestSkillDrafts(repoRoot: string, draftsDir: string,
                                         wave = 1): Promise<HarvestReport> {
  const root = path.resolve(repoRoot);
  const drafts = path.resolve(draftsDir);
  let stdout: string;
  try {
    ({ stdout } = await execFileP("python3", [
      path.join(root, "_common", "skill_registry.py"), "harvest", drafts, "--root", root,
    ], { cwd: root, maxBuffer: 16 * 1024 * 1024 }));
  } catch (err) {
    const e = err as { stderr?: string; message?: string };
    const tail = (e.stderr || e.message || String(err)).trim().split("\n").slice(-3).join(" | ");
    throw new Error(`skill harvest failed: ${tail}`);
  }
  const report = JSON.parse(stdout) as HarvestReport;
  if (!report || !Array.isArray(report.promoted) || !Array.isArray(report.rejected)) {
    throw new Error("invalid skill harvest report: expected promoted and rejected arrays");
  }
  if (report.promoted.length > 0) {
    const archive = path.join(drafts, ".promoted");
    await mkdir(archive, { recursive: true });
    for (const skill of report.promoted) {
      await rename(skill.source, path.join(archive, `${skill.name}-w${wave}`));
    }
  }
  return report;
}
