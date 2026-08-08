/** Ephemeral runtime home for agent diaries — OUTSIDE the repo, by contract.
 *
 * Worker scratch (packet WALs), validation packs, debug artifacts, and the
 * orchestrator journal are operational diaries, not research memory: the
 * durable record is the ledgers (+ the three committed notes). Diaries live
 * under /tmp so the consumer repo stays clean; a mission's diaries persist
 * for the machine session, which is exactly their useful lifetime.
 *
 * Default: /tmp/chandra/<repo-basename>-<sha8-of-abs-path>/…
 * Override with CHANDRA_RUNTIME (tests set it to keep runs hermetic). */
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export function runtimeRoot(repoRoot: string): string {
  const override = process.env.CHANDRA_RUNTIME;
  if (override && override.trim()) return override;
  const abs = path.resolve(repoRoot);
  const hash = crypto.createHash("sha256").update(abs).digest("hex").slice(0, 8);
  return path.join(os.tmpdir(), "chandra", `${path.basename(abs)}-${hash}`);
}

/** A subdirectory of the mission's runtime home, created on demand. */
export function runtimeDir(repoRoot: string, ...parts: string[]): string {
  const dir = path.join(runtimeRoot(repoRoot), ...parts);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}
