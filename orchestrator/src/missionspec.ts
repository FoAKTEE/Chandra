/** Mission spine (v3 R3): one committed `mission.json` at the consumer repo
 * root owns the run configuration — papers, budgets, packet size, per-role
 * models, cadences — instead of scattering it across CLI flags, template
 * frontmatter, and env vars. CLI flags still override for one-off runs.
 *
 * Human control channel, read BETWEEN waves:
 *   progress/<mission>/PAUSE    — graceful halt (resume by deleting the file)
 *   progress/<mission>/STEER.md — free-text guidance injected into the next
 *                                 wave's job/worker prompts (committed, so
 *                                 steering history lives in git) */
import * as fs from "node:fs";
import * as path from "node:path";

export interface MissionSpec {
  paper: string;
  maxWorkers?: number;
  maxWaves?: number;
  packetSize?: number;
  digestThreshold?: number;
  noProgressLimit?: number;
  maxWallSeconds?: number;
  models?: {
    worker?: string;
    refuter?: string;   // cross-model refutation: set this to a DIFFERENT model
    judge?: string;
    observer?: string;
    jobs?: string;
  };
}

export function loadMissionSpec(repoRoot: string): MissionSpec | null {
  const p = path.join(repoRoot, "mission.json");
  if (!fs.existsSync(p)) return null;
  const spec = JSON.parse(fs.readFileSync(p, "utf-8")) as MissionSpec;
  if (!spec.paper) throw new Error("mission.json must set \"paper\"");
  return spec;
}

export interface HumanSignals {
  paused: boolean;
  steer: string | null;
}

/** Read the between-waves control files. */
export function readHumanSignals(missionDir: string): HumanSignals {
  const pauseFile = path.join(missionDir, "PAUSE");
  const steerFile = path.join(missionDir, "STEER.md");
  return {
    paused: fs.existsSync(pauseFile),
    steer: fs.existsSync(steerFile) ? fs.readFileSync(steerFile, "utf-8").trim() || null : null,
  };
}
