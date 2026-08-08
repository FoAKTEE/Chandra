/** Bridge to the Python ledgers — the ONLY write path into research memory.
 * The orchestrator never parses agent prose into state; it queries these CLIs
 * (which run the executable admission gate on append) and diffs their output. */
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import * as path from "node:path";
import type { ClaimRow, KnowledgeRow, ResultRow } from "./types.js";

const execFileP = promisify(execFile);

export class LedgerError extends Error {}

/** Roles the delegation policy accepts on appends (kernel §6). */
export type ActorRole = "worker" | "validator" | "observer" | "human-override";

async function runCli(repoRoot: string, script: string, args: string[],
                       stdin?: string, role?: ActorRole): Promise<string> {
  const scriptPath = path.join(repoRoot, script);
  const child = execFileP("python3", [scriptPath, ...args], {
    cwd: repoRoot,
    maxBuffer: 16 * 1024 * 1024,
    env: role ? { ...process.env, CHANDRA_ROLE: role } : process.env,
  });
  if (stdin !== undefined) {
    child.child.stdin?.write(stdin);
    child.child.stdin?.end();
  }
  try {
    const { stdout } = await child;
    return stdout;
  } catch (err: unknown) {
    const e = err as { stderr?: string; message?: string };
    throw new LedgerError(
      `${script} ${args[0]} failed: ${(e.stderr || e.message || "").trim().split("\n").slice(-3).join(" | ")}`);
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
    // tolerate a mission with no claim ledger yet
    try {
      const out = await runCli(this.repoRoot, "_common/claims_database.py",
        ["query", "--paper", paper, "--repo-root", this.repoRoot]);
      return parseRows<ClaimRow>(out, "claims");
    } catch (e) {
      if (e instanceof LedgerError) return [];
      throw e;
    }
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
    try {
      const out = await runCli(this.repoRoot, "_common/contract.py",
        ["verify-chains", "--repo-root", this.repoRoot]);
      return JSON.parse(out);
    } catch (e) {
      // exit 1 = broken chain; the report is on stdout inside the error
      const msg = (e as Error).message;
      const m = msg.match(/\{.*\}/s);
      if (m) { try { return JSON.parse(m[0]); } catch { /* fall through */ } }
      return { ok: false, breaks: [{ reason: msg.slice(0, 200) }] };
    }
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
