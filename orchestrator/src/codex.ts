/** Codex CLI boundary. No SDK dependency: prompts go through a CLOSED stdin
 * pipe, and both output streams go straight to the runtime transcript. */
import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

export interface CodexOptions {
  effort?: "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
  sandbox?: "read-only" | "workspace-write" | "danger-full-access";
  bin?: string;
  timeoutSeconds?: number;
}

export type CodexRole = "worker" | "validator";

/** Resolve the environment at invocation time (including CODEX_BIN). */
export function codexDefaults(role: CodexRole): Required<CodexOptions> {
  return {
    effort: "max",
    sandbox: role === "validator" ? "read-only" : "danger-full-access",
    bin: process.env.CODEX_BIN ?? "codex",
    timeoutSeconds: 3600,
  };
}

export interface CodexExecOptions extends CodexOptions {
  model?: string;
  prompt: string;
  cwd: string;
  role: CodexRole;
  outputDir: string;
  /** Wave + packet anchor / job id; sanitized before use as a filename. */
  id: string;
}

export interface CodexExecResult {
  exitCode: number;
  finalMessage: string;
  logPath: string;
}

/** Read only enough bytes for the requested UTF-8 tail, even for hour-long logs. */
function logTail(logPath: string, chars: number): string {
  const fd = fs.openSync(logPath, "r");
  try {
    const size = fs.fstatSync(fd).size;
    const buf = Buffer.alloc(Math.min(size, chars * 4));
    fs.readSync(fd, buf, 0, buf.length, size - buf.length);
    return buf.toString("utf-8").slice(-chars);
  } finally {
    fs.closeSync(fd);
  }
}

/** Nonzero exits and timeouts reject, so the scheduler records a failure.
 * On POSIX, kill the process group as well: a shell/tool child must not keep
 * working after the leased session times out. */
export async function runCodexExec(opts: CodexExecOptions): Promise<CodexExecResult> {
  const defaults = codexDefaults(opts.role);
  const bin = opts.bin ?? defaults.bin;
  const effort = opts.effort ?? defaults.effort;
  const sandbox = opts.sandbox ?? defaults.sandbox;
  const timeoutSeconds = opts.timeoutSeconds ?? defaults.timeoutSeconds;
  if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0) {
    throw new Error("codex timeoutSeconds must be a positive finite number");
  }
  const dir = path.resolve(opts.outputDir);
  fs.mkdirSync(dir, { recursive: true });
  const safeId = opts.id.replace(/[^A-Za-z0-9_.-]/g, "_");
  const logPath = path.join(dir, `${safeId}.log`);
  const finalPath = path.join(dir, `${safeId}.final.md`);
  // A retried wave must never read a previous invocation's final message.
  fs.writeFileSync(finalPath, "");
  const logFd = fs.openSync(logPath, "w");
  try {
    return await new Promise<CodexExecResult>((resolve, reject) => {
      const grouped = process.platform !== "win32";
      const child = spawn(bin, [
        "exec", ...(opts.model ? ["-m", opts.model] : []),
        "-c", `model_reasoning_effort="${effort}"`,
        "-s", sandbox, "--skip-git-repo-check", "-o", finalPath, "-",
      ], {
        cwd: opts.cwd,
        env: { ...process.env, CHANDRA_ROLE: opts.role },
        detached: grouped,
        stdio: ["pipe", logFd, logFd],
      });
      let settled = false;
      let timedOut = false;
      let stdinError: Error | undefined;
      let killTimer: ReturnType<typeof setTimeout> | undefined;
      const signal = (sig: NodeJS.Signals) => {
        try {
          if (grouped && child.pid) process.kill(-child.pid, sig);
          else child.kill(sig);
        } catch (e) {
          // ESRCH means the child/group already exited.
          if ((e as NodeJS.ErrnoException).code !== "ESRCH") stdinError = e as Error;
        }
      };
      const finish = (error?: Error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (killTimer) clearTimeout(killTimer);
        if (error) { reject(error); return; }
        try {
          resolve({ exitCode: 0, finalMessage: fs.readFileSync(finalPath, "utf-8"), logPath });
        } catch (e) {
          reject(e);
        }
      };
      const failure = (reason: string): Error => {
        let tail = "";
        try { tail = logTail(logPath, 300); } catch { /* diagnostics are best-effort */ }
        return new Error(`codex ${reason}; log=${logPath} tail=${tail}`);
      };
      const timer = setTimeout(() => {
        timedOut = true;
        signal("SIGTERM");
        // Keep the grace timer even if the parent exits first: its tools may
        // still be alive. Reject after SIGKILL without waiting on their pipes.
        killTimer = setTimeout(() => {
          signal("SIGKILL");
          finish(failure(`timed out after ${timeoutSeconds}s`));
        }, 500);
      }, timeoutSeconds * 1000);
      child.once("error", e => finish(failure(`failed to spawn ${bin}: ${e.message}`)));
      child.once("close", (code, sig) => {
        if (timedOut) return;
        if (code !== 0) finish(failure(`exit=${code ?? sig}`));
        else if (stdinError) finish(failure(`stdin failed: ${stdinError.message}`));
        else finish();
      });
      // Early exits can close stdin before the entire prompt is written.
      // Preserve the exit/log diagnostic rather than throwing an EPIPE event.
      child.stdin!.on("error", e => { stdinError = e; });
      child.stdin!.end(opts.prompt);
    });
  } finally {
    fs.closeSync(logFd);
  }
}
