/** Bridge to the Python ledgers — the ONLY write path into research memory.
 * The orchestrator never parses agent prose into state; it queries these CLIs
 * (which run the executable admission gate on append) and diffs their output. */
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import * as path from "node:path";
import type { ClaimRow, KnowledgeRow, ResultRow } from "./types.js";

const execFileP = promisify(execFile);

export class LedgerError extends Error {
  constructor(message: string, readonly stdout?: string, readonly code?: number | string) { super(message); }
}

export interface PreflightReport {
  ok: boolean;
  breaks: unknown[];
  unreadable: string[];
}

/** Roles the delegation policy accepts on appends (kernel §6). */
export type ActorRole = "worker" | "validator" | "observer" | "human-override";

async function runCli(repoRoot: string, script: string, args: string[],
                       stdin?: string, role?: ActorRole): Promise<string> {
  const scriptPath = path.join(repoRoot, script);
  // Bound each channel, including a partially buffered query whose final
  // line can itself be several MiB long.
  const tail = (s: string) => s.trim().split("\n").slice(-3).join(" | ").slice(-2000);
  try {
    const child = execFileP(process.env.CHANDRA_PYTHON ?? "python3", [scriptPath, ...args], {
      cwd: repoRoot,
      maxBuffer: 16 * 1024 * 1024,
      env: role ? { ...process.env, CHANDRA_ROLE: role } : process.env,
    });
    if (stdin !== undefined) {
      child.child.stdin?.write(stdin);
      child.child.stdin?.end();
    }
    const { stdout, stderr } = await child;
    // The recovering Python reader may return a complete prefix with exit 0.
    // That is not a complete ledger read for mission decisions.
    if (args[0] === "query" && stderr.includes("incomplete tail (crash mid-write)")) {
      throw new LedgerError(`${script} query failed: incomplete ledger read` +
        `; stderr: ${tail(stderr)}; stdout: ${tail(stdout)}`, stdout);
    }
    return stdout;
  } catch (err: unknown) {
    if (err instanceof LedgerError) throw err;
    const e = err as { stderr?: string; stdout?: string; message?: string; code?: number | string };
    const detail = e.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER"
      ? "output exceeded 16 MiB" : tail(e.message ?? "CLI error");
    throw new LedgerError(
      `${script} ${args[0]} failed: ${detail}` +
      `; stderr: ${tail(e.stderr ?? "")}; stdout: ${tail(e.stdout ?? "")}`, e.stdout, e.code);
  }
}

function parseRows<T>(stdout: string, what: string): T[] {
  try {
    const parsed = JSON.parse(stdout);
    if (!Array.isArray(parsed)) throw new Error("not an array");
    return parsed as T[];
  } catch (e) {
    throw new LedgerError(`unparseable ${what} query output: ${(e as Error).message}`);
  }
}

export class Ledgers {
  /** `role` stamps appends with CHANDRA_ROLE for the delegation policy
   * (kernel §6). Queries never need it; the orchestrator's own Ledgers is
   * roleless on purpose — orchestrators read, workers write. */
  constructor(readonly repoRoot: string, readonly role?: ActorRole) {}

  async knowledge(paper: string): Promise<KnowledgeRow[]> {
    const out = await runCli(this.repoRoot, "_common/knowledge_database.py",
      ["query", "--paper", paper, "--repo-root", this.repoRoot]);
    return parseRows<KnowledgeRow>(out, "knowledge");
  }

  async claims(paper: string): Promise<ClaimRow[]> {
    const out = await runCli(this.repoRoot, "_common/claims_database.py",
      ["query", "--paper", paper, "--repo-root", this.repoRoot]);
    return parseRows<ClaimRow>(out, "claims");
  }

  async results(paper: string): Promise<ResultRow[]> {
    const out = await runCli(this.repoRoot, "_common/result_database.py",
      ["query", "--paper", paper, "--repo-root", this.repoRoot]);
    return parseRows<ResultRow>(out, "results");
  }

  /** Append via the gated CLI. Used by stubs/tests and the observer; real
   * workers run the CLIs themselves inside their own sessions. */
  async appendKnowledge(row: Record<string, unknown>): Promise<string> {
    return runCli(this.repoRoot, "_common/knowledge_database.py",
      ["append", "--repo-root", this.repoRoot], JSON.stringify(row), this.role);
  }

  async appendResult(row: Record<string, unknown>): Promise<string> {
    return runCli(this.repoRoot, "_common/result_database.py",
      ["append", "--repo-root", this.repoRoot], JSON.stringify(row), this.role);
  }

  async appendClaimEntry(row: Record<string, unknown>): Promise<string> {
    return runCli(this.repoRoot, "_common/claims_database.py",
      ["append", "--repo-root", this.repoRoot], JSON.stringify(row), this.role);
  }

  /** Tamper-evidence: walk every ledger's hash chain (R4). */
  async verifyChains(): Promise<{ ok: boolean; breaks: unknown[] }> {
    let out: string;
    try {
      out = await runCli(this.repoRoot, "_common/contract.py",
        ["verify-chains", "--repo-root", this.repoRoot]);
    } catch (e) {
      // A broken chain is an ordinary report on stdout. An unavailable CLI
      // or an invalid report is a read failure, not evidence of tampering.
      if (e instanceof LedgerError && e.code === 1 && e.stdout) {
        try {
          const report = JSON.parse(e.stdout);
          if (report?.ok === false && Array.isArray(report.breaks)) return report;
        } catch { /* preserve the original CLI diagnostic below */ }
      }
      throw e;
    }
    try {
      const report = JSON.parse(out);
      if (typeof report?.ok !== "boolean" || !Array.isArray(report.breaks)) {
        throw new Error("expected ok and breaks");
      }
      return report;
    } catch (e) {
      throw new LedgerError(`unparseable _common/contract.py verify-chains output: ${(e as Error).message}`);
    }
  }

  /** Check integrity and readability before any mission decision. Missing
   * ledger files are valid empty arrays returned by the Python readers. */
  async preflight(paper: string): Promise<PreflightReport> {
    const [chains, ...reads] = await Promise.allSettled([
      this.verifyChains(), this.knowledge(paper), this.results(paper), this.claims(paper),
    ] as const);
    const unreadable: string[] = [];
    const labels = ["verify-chains", "knowledge", "results", "claims"];
    [chains, ...reads].forEach((result, i) => {
      if (result.status === "rejected") {
        const message = result.reason instanceof Error ? result.reason.message : String(result.reason);
        unreadable.push(`${labels[i]}: ${message}`);
      }
    });
    return {
      ok: chains.status === "fulfilled" && chains.value.ok && unreadable.length === 0,
      breaks: chains.status === "fulfilled" ? chains.value.breaks : [],
      unreadable,
    };
  }

  /** Per-node ledger snapshot used to derive worker outcomes by DIFF. */
  async snapshot(paper: string): Promise<LedgerSnapshot> {
    const [know, res, cls] = await Promise.all([
      this.knowledge(paper), this.results(paper), this.claims(paper)]);
    const statusByNode: Record<string, string> = {};
    for (const r of know) statusByNode[r.node_id] = r.status;
    const resultsByNode: Record<string, number> = {};
    for (const r of res) {
      for (const nid of (r.node_ids as string[] | undefined) ?? []) {
        resultsByNode[nid] = (resultsByNode[nid] ?? 0) + 1;
      }
    }
    const openObligationsByNode: Record<string, number> = {};
    for (const c of cls) {
      if (c.kind !== "obligation" || c.status !== "open") continue;
      for (const nid of c.node_ids ?? []) {
        openObligationsByNode[nid] = (openObligationsByNode[nid] ?? 0) + 1;
      }
    }
    return { statusByNode, resultsByNode, openObligationsByNode };
  }
}

export interface LedgerSnapshot {
  statusByNode: Record<string, string>;
  resultsByNode: Record<string, number>;
  openObligationsByNode: Record<string, number>;
}
