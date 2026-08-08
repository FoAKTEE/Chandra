/** Shared types: ledger row shapes (the Python schemas are canonical — these
 * mirror only the fields the orchestrator reads) and the typed agent-to-agent
 * message vocabulary persisted to the journal. */

export type NodeStatus =
  | "hypothesis" | "preliminary" | "solid" | "blocking" | "future" | "amended";

export interface KnowledgeRow {
  paper: string;
  node_id: string;
  status: NodeStatus;
  summary?: string;
  predecessors?: string[];
  timestamp?: string;
  [k: string]: unknown;
}

export interface ClaimRow {
  paper: string;
  entry_id: string;
  kind: "claim" | "obligation" | "assumption";
  status: string;
  statement?: string;
  node_ids?: string[];
  [k: string]: unknown;
}

export interface ResultRow {
  paper: string;
  result_id: string;
  status: string;
  claim?: string;
  node_ids?: string[];
  [k: string]: unknown;
}

/** One node of the mission DAG, collapsed to its latest non-amended state. */
export interface MissionNode {
  id: string;
  paper: string;
  status: NodeStatus;
  summary: string;
  predecessors: string[];
  /** open obligations attached to this node (claim ledger, kind=obligation) */
  openObligations: string[];
  /** topological depth (0 = no predecessors); -1 when on a cycle */
  depth: number;
}

export type Mission = Map<string, MissionNode>;

/** Outcome of one worker, derived from LEDGER DIFF, never from agent prose. */
export type WorkerOutcome = "admitted" | "promoted" | "rejected" | "failed" | "no_progress";

export interface WorkerTask {
  wave: number;
  /** first node of the packet (the packet's id/anchor) */
  node: MissionNode;
  /** the full leased packet: a chain worked IN ORDER, continuously, in one
   * session (compacting as needed) — the fix for scattered per-node work */
  packet: MissionNode[];
  paper: string;
  repoRoot: string;
  /** free-text human guidance from progress/<mission>/STEER.md, if present */
  steer?: string;
}

export interface WorkerReport {
  node: string;
  outcome: WorkerOutcome;
  detail: string;
  startedAt: string;
  finishedAt: string;
  /** context-window accounting for the digest cadence (phase 4) */
  windowsUsed: number;
}

/** Typed agent-to-agent messages; one JSONL line each in the journal. */
export type Message =
  | { type: "mission_loaded"; paper: string; nodes: number; solid: number }
  | { type: "wave_planned"; wave: number; ready: string[]; scheduled: string[] }
  | { type: "task_assigned"; wave: number; node: string; runner: string }
  | { type: "worker_done"; wave: number; report: WorkerReport }
  | { type: "wave_finished"; wave: number; admitted: number; rejected: number; failed: number; noProgress: number }
  | { type: "validation_verdict"; wave: number; node: string; verdict: "admit" | "reject"; refuterFindings: string }
  | { type: "memory_pruned"; wave: number; researchStateBytes: number }
  | { type: "digest_emitted"; afterWindows: number; wave: number; path: string }
  | { type: "wave_committed"; wave: number; sha: string }
  | { type: "gate_decision"; wave: number; decision: string; noProgressStreak: number }
  | { type: "halt"; reason: string; wave: number };

export interface JournalEntry {
  at: string;
  msg: Message;
}
