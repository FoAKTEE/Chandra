/** Committed ledger inventory: anchors chain tails and the unhashed prefix.
 * Build only after wave jobs settle. Node has no built-in flock: callers must
 * also keep external writers quiescent until the wave commit completes. Each
 * ledger's counts, hashes and byte digests come from ONE read, never a query
 * followed by an independent head read. This is not a repository-wide lock. */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { pathToFileURL } from "node:url";
import { TextDecoder } from "node:util";

export const CHECKPOINT_PATH = "results/ledgers/CHECKPOINT.json";
// Contract parity is checked against `python3 _common/contract.py manifest`.
export const LEDGER_FILES = {
  claim: "entries.jsonl", error: "trials.jsonl", knowledge: "nodes.jsonl", result: "results.jsonl",
} as const;

export interface LedgerCheckpoint {
  db: string;
  paper: string;
  path: string;                         // repository-relative, in either layout
  rows: number;
  hashed: number;
  head: string | null;
  legacyPrefixRows: number;
  legacyPrefixSha256: string | null;
  bytes: number;
  fileSha256: string;
}

export interface Checkpoint {
  version: 1;
  createdAt: string;
  ledgers: LedgerCheckpoint[];
  previous?: { sha: string; path: string };
}

export interface CheckpointViolation {
  type: "tail_deleted" | "ledger_missing" | "legacy_prefix_changed" | "torn";
  db: string;
  paper: string;
  path: string;
  torn?: true;
}

export interface CheckpointDiff {
  ok: boolean;
  violations: CheckpointViolation[];
  advanced: LedgerCheckpoint[];
  added: LedgerCheckpoint[];
}

export class CheckpointError extends Error {
  constructor(message: string, readonly violations: CheckpointViolation[] = []) {
    super(message);
    this.name = "CheckpointError";
  }
}

type LedgerLocation = Pick<LedgerCheckpoint, "db" | "paper" | "path">;
const sha256 = (data: Buffer) => createHash("sha256").update(data).digest("hex");
const identity = (ledger: LedgerLocation) => JSON.stringify([ledger.db, ledger.paper, ledger.path]);
// Local read provenance is deliberately excluded from the portable manifest.
const roots = new WeakMap<Checkpoint, string>();

function violation(type: CheckpointViolation["type"], ledger: LedgerLocation): CheckpointViolation {
  return { type, db: ledger.db, paper: ledger.paper, path: ledger.path, ...(type === "torn" ? { torn: true as const } : {}) };
}

function torn(ledger: LedgerLocation): never {
  throw new CheckpointError(`torn: ${ledger.path}`, [violation("torn", ledger)]);
}

/** Inspect bytes once. The hash list permits checking an earlier head at its
 * exact hashed-row index; the last hash and counts alone cannot prove that. */
function readLedger(repoRoot: string, location: LedgerLocation): { ledger: LedgerCheckpoint; hashes: string[] } {
  const data = fs.readFileSync(path.resolve(repoRoot, location.path));
  if (data.length && data[data.length - 1] !== 10) torn(location);
  let rows = 0;
  let legacyPrefixRows = 0;
  let prefixEnd = data.length;
  const hashes: string[] = [];
  const decoder = new TextDecoder("utf-8", { fatal: true });
  for (let start = 0; start < data.length;) {
    const end = data.indexOf(10, start) + 1;
    const line = data.subarray(start, end);
    let row: Record<string, unknown>;
    try {
      const text = decoder.decode(line);
      if (!text.trim()) { start = end; continue; }
      // Python's JSON writer allows NaN/Infinity/-Infinity. We only inspect
      // row_hash: mask complete nonfinite value tokens for JSON.parse, never
      // quoted strings or numeric substrings. Digests use untouched bytes.
      row = JSON.parse(text.replace(/"(?:[^"\\]|\\[\s\S])*"|([:\[,]\s*)(?:-Infinity|Infinity|NaN)(?=\s*[,}\]])/g,
        (token, prefix: string | undefined) => prefix === undefined ? token : `${prefix}0`));
      if (!row || typeof row !== "object" || Array.isArray(row)) throw new Error("expected a JSON object");
    } catch (error) {
      // Like the Python reader, a malformed final line is an incomplete tail.
      if (end === data.length) torn(location);
      throw new CheckpointError(`${location.path}: invalid row at byte ${start}: ${(error as Error).message}`);
    }
    rows++;
    if (row.row_hash == null) {
      if (hashes.length) throw new CheckpointError(`${location.path}: unhashed row after hashed history`);
      legacyPrefixRows++;
    } else {
      if (typeof row.row_hash !== "string") throw new CheckpointError(`${location.path}: invalid row_hash`);
      if (!hashes.length) prefixEnd = start;
      hashes.push(row.row_hash);
    }
    start = end;
  }
  return {
    ledger: {
      ...location, rows, hashed: hashes.length, head: hashes.at(-1) ?? null,
      legacyPrefixRows, legacyPrefixSha256: legacyPrefixRows ? sha256(data.subarray(0, prefixEnd)) : null,
      bytes: data.length, fileSha256: sha256(data),
    },
    hashes,
  };
}

export function buildCheckpoint(repoRoot: string): Checkpoint {
  const root = path.resolve(repoRoot);
  const ledgers: LedgerCheckpoint[] = [];
  for (const [db, filename] of Object.entries(LEDGER_FILES)) {
    for (const base of [`results/ledgers/${db}`, `${db}-database`]) {
      const directory = path.join(root, base);
      if (!fs.existsSync(directory)) continue;
      for (const paperDir of fs.readdirSync(directory)) {
        if (!paperDir.startsWith("paper_") || !fs.statSync(path.join(directory, paperDir)).isDirectory()) continue;
        const rel = `${base}/${paperDir}/${filename}`;
        if (fs.existsSync(path.join(root, rel))) {
          ledgers.push(readLedger(root, { db, paper: paperDir.slice(6), path: rel }).ledger);
        }
      }
    }
  }
  const key = (ledger: LedgerCheckpoint) => `${ledger.db}\0${ledger.paper}\0${ledger.path}`;
  ledgers.sort((a, b) => key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0);
  const checkpoint: Checkpoint = { version: 1, createdAt: new Date().toISOString(), ledgers };
  roots.set(checkpoint, root);
  return checkpoint;
}

/** Verify against actual file rows, including the previous head's position.
 * A built current checkpoint retains its root out of band; for a deserialized
 * current checkpoint, run from its repository root. The readback is separate
 * from building either checkpoint and derives every checked field together. */
export function verifyAgainst(previous: Checkpoint, current: Checkpoint): CheckpointDiff {
  const root = roots.get(current) ?? process.cwd();
  const before = new Map(previous.ledgers.map(ledger => [identity(ledger), ledger]));
  const now = new Set(current.ledgers.map(identity));
  const diff: CheckpointDiff = { ok: true, violations: [], advanced: [], added: [] };
  for (const old of previous.ledgers) {
    if (!now.has(identity(old))) {
      diff.violations.push(violation("ledger_missing", old));
    }
  }
  for (const next of current.ledgers) {
    let read: ReturnType<typeof readLedger>;
    try {
      read = readLedger(root, next);
    } catch (error) {
      if (error instanceof CheckpointError && error.violations.length) {
        diff.violations.push(...error.violations);
      } else if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        diff.violations.push(violation("ledger_missing", next));
      } else throw error;
      continue;
    }
    const old = before.get(identity(next));
    if (!old) {
      diff.added.push(next);
      continue;
    }
    const start = diff.violations.length;
    if (next.rows < old.rows || next.hashed < old.hashed || read.ledger.rows < old.rows || read.ledger.hashed < old.hashed ||
        (old.head !== null && read.hashes[old.hashed - 1] !== old.head)) {
      diff.violations.push(violation("tail_deleted", next));
    }
    if ([next, read.ledger].some(ledger => ledger.legacyPrefixRows !== old.legacyPrefixRows ||
      ledger.legacyPrefixSha256 !== old.legacyPrefixSha256)) {
      diff.violations.push(violation("legacy_prefix_changed", next));
    }
    if (diff.violations.length === start && (next.rows > old.rows || next.hashed > old.hashed)) diff.advanced.push(next);
  }
  diff.ok = diff.violations.length === 0;
  return diff;
}

export function serializeCheckpoint(checkpoint: Checkpoint): string {
  return JSON.stringify(checkpoint, (_key, value: unknown) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
    }
    return value;
  }, 2) + "\n";
}

/** Only absence at HEAD means a first checkpoint. Never trust the worktree
 * copy or treat a malformed committed manifest / git failure as absence. */
export function readCommittedCheckpoint(repoRoot: string): Checkpoint | undefined {
  const git = (...args: string[]) => execFileSync("git", ["-C", repoRoot, ...args],
    { encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"], maxBuffer: 16 * 1024 * 1024 });
  let source: string;
  try {
    source = git("show", `HEAD:${CHECKPOINT_PATH}`);
  } catch (error) {
    try {
      git("rev-parse", "--verify", "HEAD");
    } catch {
      // An unborn branch has a symbolic HEAD but no branch ref. A detached,
      // corrupt or unreadable HEAD must still fail closed.
      const branch = git("symbolic-ref", "--quiet", "HEAD").trim();
      try { git("show-ref", "--verify", "--quiet", branch); }
      catch (refError) {
        if ((refError as { status?: number }).status === 1) return undefined;
        throw refError;
      }
      throw error;
    }
    if (!git("ls-tree", "--name-only", "HEAD", "--", CHECKPOINT_PATH).trim()) return undefined;
    throw error;
  }
  try {
    const checkpoint = JSON.parse(source) as Checkpoint;
    if (checkpoint.version !== 1 || !Array.isArray(checkpoint.ledgers)) throw new Error("expected checkpoint version 1 and ledgers");
    return checkpoint;
  } catch (error) {
    throw new CheckpointError(`HEAD:${CHECKPOINT_PATH}: ${(error as Error).message}`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const [command, repoRoot = process.cwd()] = process.argv.slice(2);
  try {
    if (command === "build") process.stdout.write(serializeCheckpoint(buildCheckpoint(repoRoot)));
    else if (command === "verify") {
      const previous = readCommittedCheckpoint(repoRoot);
      const current = buildCheckpoint(repoRoot);
      const diff: CheckpointDiff = previous ? verifyAgainst(previous, current)
        : { ok: true, violations: [], advanced: [], added: current.ledgers };
      process.stdout.write(JSON.stringify(diff, null, 2) + "\n");
      process.exitCode = diff.ok ? 0 : 1;
    } else throw new Error("usage: checkpoint.js build|verify [repoRoot]");
  } catch (error) {
    if (command === "verify" && error instanceof CheckpointError && error.violations.length) {
      process.stdout.write(JSON.stringify({ ok: false, violations: error.violations, advanced: [], added: [] }, null, 2) + "\n");
    } else process.stderr.write(`${(error as Error).message}\n`);
    process.exitCode = 1;
  }
}
