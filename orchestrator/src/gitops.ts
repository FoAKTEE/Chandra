/** Git substage-commit enforcement (progress principles, mechanical).
 *
 * Every wave that changes zone-1 state (results/, progress/) is COMMITTED by
 * the orchestrator before the next wave may start; a failed commit (e.g. the
 * commit-msg gate rejects) HALTS the mission. Consumers must run missions in
 * a git repo; the commit-msg gate should be installed
 * (`bash _common/hooks/install.sh`) — preflight warns when it is not. */
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { buildCheckpoint, CHECKPOINT_PATH, CheckpointError, readCommittedCheckpoint,
  serializeCheckpoint, verifyAgainst } from "./checkpoint.js";

function git(repoRoot: string, args: string[]): string {
  return execFileSync("git", ["-C", repoRoot, ...args],
    { encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] });
}

export function isGitRepo(repoRoot: string): boolean {
  try {
    git(repoRoot, ["rev-parse", "--git-dir"]);
    return true;
  } catch {
    return false;
  }
}

export function commitGateInstalled(repoRoot: string): boolean {
  try {
    return git(repoRoot, ["config", "core.hooksPath"]).trim().length > 0;
  } catch {
    return false;
  }
}

export interface WaveCommit {
  committed: boolean;
  sha?: string;
  checkpoint?: { path: string; ledgers: number; advanced: number; added: number };
}

/** After all wave jobs settle, verify the ledgers against HEAD's checkpoint,
 * then stage everything (diaries live outside the repo) and commit with a
 * gate-compliant message. A rejected checkpoint or commit halts the mission. */
export function commitWave(repoRoot: string, paper: string, wave: number,
                           summary: string): WaveCommit {
  let current;
  let checkpoint: NonNullable<WaveCommit["checkpoint"]>;
  try {
    const previous = readCommittedCheckpoint(repoRoot);
    current = buildCheckpoint(repoRoot);
    const diff = previous ? verifyAgainst(previous, current)
      : { ok: true, violations: [], advanced: [], added: current.ledgers };
    if (!diff.ok) throw new CheckpointError(JSON.stringify(diff.violations), diff.violations);
    if (previous) current.previous = { sha: git(repoRoot, ["rev-parse", "--short", "HEAD"]).trim(), path: CHECKPOINT_PATH };
    checkpoint = { path: CHECKPOINT_PATH, ledgers: current.ledgers.length, advanced: diff.advanced.length, added: diff.added.length };
  } catch (error) {
    const detail = error instanceof CheckpointError && error.violations.length
      ? JSON.stringify(error.violations) : (error as Error).message;
    throw new Error(`wave ${wave} checkpoint REJECTED: ${detail}`);
  }

  const checkpointFile = path.join(repoRoot, CHECKPOINT_PATH);
  const previousFile = fs.existsSync(checkpointFile) ? fs.readFileSync(checkpointFile) : undefined;
  // Preserve staged/unstaged distinctions, including an untracked checkpoint,
  // if staging or the commit hook fails. --git-path also supports worktrees.
  const indexFile = path.resolve(repoRoot, git(repoRoot, ["rev-parse", "--git-path", "index"]).trim());
  const previousIndex = fs.existsSync(indexFile) ? fs.readFileSync(indexFile) : undefined;
  const title = `notes(wave): paper_${paper} wave ${wave}`;
  try {
    fs.mkdirSync(path.dirname(checkpointFile), { recursive: true });
    fs.writeFileSync(checkpointFile, serializeCheckpoint(current));
    git(repoRoot, ["add", "-A"]);
    // The trust anchor must reach HEAD even under consumer *.json ignores.
    git(repoRoot, ["add", "--force", "--", CHECKPOINT_PATH]);
    try {
      git(repoRoot, ["diff", "--cached", "--quiet"]);
      return { committed: false, checkpoint };
    } catch { /* staged changes exist */ }
    git(repoRoot, ["commit", "-m", `${title}\n\n- result: ${summary}\n`]);
  } catch (e) {
    if (previousFile === undefined) fs.rmSync(checkpointFile, { force: true });
    else fs.writeFileSync(checkpointFile, previousFile);
    if (previousIndex === undefined) fs.rmSync(indexFile, { force: true });
    else fs.writeFileSync(indexFile, previousIndex);
    throw new Error(
      `wave ${wave} commit REJECTED (substage-commit enforcement): ` +
      `${(e as { stderr?: string }).stderr ?? (e as Error).message}`.slice(0, 400));
  }
  return { committed: true, sha: git(repoRoot, ["rev-parse", "--short", "HEAD"]).trim(), checkpoint };
}
