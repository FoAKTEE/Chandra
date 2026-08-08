/** Git substage-commit enforcement (progress principles, mechanical).
 *
 * Every wave that changes zone-1 state (results/, progress/) is COMMITTED by
 * the orchestrator before the next wave may start; a failed commit (e.g. the
 * commit-msg gate rejects) HALTS the mission. Consumers must run missions in
 * a git repo; the commit-msg gate should be installed
 * (`bash _common/hooks/install.sh`) — preflight warns when it is not. */
import { execFileSync } from "node:child_process";

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
}

/** Stage everything (diaries live outside the repo by contract) and commit
 * with a gate-compliant message. Nothing staged -> clean no-op. A rejected
 * or failed commit THROWS — the mission loop halts on it. */
export function commitWave(repoRoot: string, paper: string, wave: number,
                           summary: string): WaveCommit {
  git(repoRoot, ["add", "-A"]);
  try {
    git(repoRoot, ["diff", "--cached", "--quiet"]);
    return { committed: false };               // nothing to commit this wave
  } catch {
    /* staged changes exist */
  }
  const title = `notes(wave): paper_${paper} wave ${wave}`;
  try {
    git(repoRoot, ["commit", "-m", `${title}\n\n- result: ${summary}\n`]);
  } catch (e) {
    throw new Error(
      `wave ${wave} commit REJECTED (substage-commit enforcement): ` +
      `${(e as { stderr?: string }).stderr ?? (e as Error).message}`.slice(0, 400));
  }
  return { committed: true, sha: git(repoRoot, ["rev-parse", "--short", "HEAD"]).trim() };
}
