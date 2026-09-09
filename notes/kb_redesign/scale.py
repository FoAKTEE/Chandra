"""Measure append / query / transitive-walk / trial-append cost at exactly N pre-existing rows.
Each N uses a FRESH throwaway repo (an earlier version accumulated rows across sizes and mislabeled them).
Run from the repo root: python3 notes/kb_redesign/scale.py [N ...]   (default 100 500 2000)"""
import os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from _common.ledgers import knowledge_database as kdb, error_database as edb, ledger_common as lc
os.environ["CHANDRA_ROLE"] = "worker"
P = "arxiv-1111.11111"
def node(i): return {"paper": P, "node_id": f"{P}::n{i}", "task_id": f"t{i}", "domain": "software", "status": "hypothesis",
                     "summary": f"node {i}", "predecessors": [f"{P}::n{i-1}"] if i else []}
def trial(i): return {"paper": P, "task_id": f"t{i%50}", "iteration": i, "stage": "implementation", "domain": "software",
                      "change_type": "structural", "change_summary": f"trial {i}", "node_id": f"{P}::n{i%50}",
                      "metric": {"name": "tests_failed", "value": 0, "threshold": 0, "pass": True}, "pass_fail": "pass", "wall_clock_seconds": 1}
sizes = [int(a) for a in sys.argv[1:]] or [100, 500, 2000]
print("N_existing  append_1(ms)  query(ms)  preds_transitive(ms)  trial_append(ms)  nodes_kB  chain_ok")
for N in sizes:
    tmp = Path(tempfile.mkdtemp(prefix="kb-scale-", dir="/tmp")); subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    kdb.append_batch([node(i) for i in range(N)], repo_root=tmp, force=True)      # gated, sequential, untimed
    edb.append_batch([trial(i) for i in range(N)], repo_root=tmp)
    t0 = time.perf_counter(); kdb.append_row(node(N), repo_root=tmp); t1 = time.perf_counter()
    kdb.query(P, repo_root=tmp); t2 = time.perf_counter()
    kdb.predecessors_of(P, f"{P}::n{N}", transitive=True, repo_root=tmp); t3 = time.perf_counter()
    edb.append_row(trial(N), repo_root=tmp); t4 = time.perf_counter()
    kb = (tmp / "results/ledgers/knowledge" / f"paper_{P}" / "nodes.jsonl").stat().st_size / 1024
    ok = lc.verify_all_chains(tmp)["ok"]
    print(f"{N:>10}  {1000*(t1-t0):>11.1f}  {1000*(t2-t1):>9.1f}  {1000*(t3-t2):>20.1f}  {1000*(t4-t3):>16.1f}  {kb:>7.0f}  {ok}")
    shutil.rmtree(tmp)
