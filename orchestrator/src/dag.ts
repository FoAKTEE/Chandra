/** Mission DAG: built from the knowledge + claim ledgers, never from prose.
 * A node is READY when it is not yet solid and every predecessor is solid —
 * priority IS topology; there is no separate priority function. */
import type { ClaimRow, KnowledgeRow, Mission, MissionNode } from "./types.js";

/** Latest non-amended row per node_id, in append order (last wins). */
export function latestPerNode(rows: KnowledgeRow[]): Map<string, KnowledgeRow> {
  const by = new Map<string, KnowledgeRow>();
  for (const r of rows) {
    if (r.status === "amended" || !r.node_id) continue;
    by.set(r.node_id, r);
  }
  return by;
}

export function buildMission(paper: string, knowledge: KnowledgeRow[],
                             claims: ClaimRow[]): Mission {
  const latest = latestPerNode(knowledge);
  const mission: Mission = new Map();
  for (const [id, row] of latest) {
    mission.set(id, {
      id,
      paper,
      status: row.status,
      summary: row.summary ?? "",
      predecessors: row.predecessors ?? [],
      openObligations: [],
      depth: -1,
    });
  }
  for (const c of claims) {
    if (c.kind !== "obligation" || c.status !== "open") continue;
    for (const nid of c.node_ids ?? []) {
      mission.get(nid)?.openObligations.push(c.entry_id);
    }
  }
  assignDepths(mission);
  return mission;
}

/** Depth = longest predecessor chain; -1 marks nodes on (or behind) a cycle. */
function assignDepths(mission: Mission): void {
  const visiting = new Set<string>();
  const depth = (id: string): number => {
    const node = mission.get(id);
    if (!node) return 0; // unknown predecessor: treated as depth-0 external
    if (node.depth >= 0) return node.depth;
    if (visiting.has(id)) return -1_000_000; // cycle sentinel
    visiting.add(id);
    let d = 0;
    for (const p of node.predecessors) {
      const pd = depth(p);
      if (pd < -1) { d = -1_000_001; break; }
      d = Math.max(d, pd + 1);
    }
    visiting.delete(id);
    node.depth = d < 0 ? -1 : d;
    return d < 0 ? -1_000_000 : d;
  };
  for (const id of mission.keys()) depth(id);
}

/** Ready frontier in deterministic topological order (depth, then id).
 * A missing predecessor (not in the mission) counts as NOT solid — the node
 * waits until acquisition/decomposition lands it. Cycle nodes never ready. */
export function readyFrontier(mission: Mission): MissionNode[] {
  const ready: MissionNode[] = [];
  for (const node of mission.values()) {
    if (node.status === "solid" || node.depth < 0) continue;
    const blocked = node.predecessors.some(p => mission.get(p)?.status !== "solid");
    if (!blocked) ready.push(node);
  }
  return ready.sort((a, b) => a.depth - b.depth || a.id.localeCompare(b.id));
}

/** True when every node is solid — the mission's terminal condition. */
export function missionComplete(mission: Mission): boolean {
  if (mission.size === 0) return false;
  for (const n of mission.values()) if (n.status !== "solid") return false;
  return true;
}
