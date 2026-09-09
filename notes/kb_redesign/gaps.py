"""Demonstrate four design gaps in a throwaway repo: cross-paper readiness, silent claim replacement, undetected tail truncation, orphan trial anchors. Run from the repo root: python3 notes/kb_redesign/gaps.py"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT = "/data/haiyangw/harness/Chandra"; sys.path.insert(0, ROOT)
from _common.ledgers import knowledge_database as kdb, result_database as rdb, ledger_common as lc
os.environ["CHANDRA_ROLE"] = "worker"
tmp = Path(tempfile.mkdtemp(prefix="kb-gaps-", dir="/tmp")); subprocess.run(["git", "init", "-q", str(tmp)], check=True)
os.symlink(f"{ROOT}/_common", tmp / "_common")
# 1. cross-paper predecessor: _shared::base is solid in paper _shared; P::top depends on it
(tmp / "ev.txt").write_text("ok\n")
kdb.append_row({"paper": "_shared", "node_id": "_shared::base", "task_id": "t", "domain": "software", "status": "solid", "summary": "shared base", "evidence": "ev.txt"}, repo_root=tmp)
kdb.append_row({"paper": "P", "node_id": "P::top", "task_id": "t", "domain": "software", "status": "hypothesis", "summary": "needs shared base", "predecessors": ["_shared::base"]}, repo_root=tmp)
js = f"""
import {{ buildMission, readyFrontier }} from "{ROOT}/orchestrator/dist/src/dag.js";
import {{ Ledgers }} from "{ROOT}/orchestrator/dist/src/ledger.js";
const l = new Ledgers("{tmp}");
const m = buildMission("P", await l.knowledge("P"), await l.claims("P"));
console.log(JSON.stringify({{ready: readyFrontier(m).map(n => n.id), nodes: [...m.keys()]}}));
"""
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, cwd=ROOT)
print("1. cross-paper readiness ->", r.stdout.strip() or r.stderr.strip()[-200:])
# 2. same result_id, different claim, silently replaces
base = {"paper": "P", "result_id": "r1", "name": "n", "working_context": "c", "claim": "A holds", "evidence_type": "exact_proof",
        "evidence": "ev.txt", "verifier_result": {"verdict": "pass"}, "dependencies": [], "assumptions": [], "status": "checked",
        "provenance": "x", "open_obligations": []}
rdb.append_row(dict(base), repo_root=tmp)
rdb.append_row({**base, "claim": "A does NOT hold", "status": "refuted"}, repo_root=tmp)
print("2. latest r1 claim ->", rdb.query("P", repo_root=tmp)[0]["claim"], "| history rows:", len(rdb.query("P", latest_only=False, repo_root=tmp)), "| no supersedes link, no warning")
# 3. tail truncation: drop the last row of a chained file
f = tmp / "results/ledgers/result/paper_P/results.jsonl"
lines = f.read_text().splitlines(); f.write_text("\n".join(lines[:-1]) + "\n")
print("3. after deleting the last row, verify-chains ->", lc.verify_all_chains(tmp))
# 4. orphan trial anchor: a trial under a node that does not exist is accepted
from _common.ledgers import error_database as edb
edb.append_row({"paper": "P", "task_id": "t", "iteration": 1, "stage": "implementation", "domain": "software", "change_type": "structural",
                "change_summary": "x", "metric": {"name": "tests_failed", "value": 0, "threshold": 0, "pass": True}, "pass_fail": "pass",
                "wall_clock_seconds": 1, "node_id": "P::does-not-exist"}, repo_root=tmp)
from _common.visualization import dag_mermaid as dm
print("4. orphan trial accepted; progress shows ->", [p for p in dm.node_progress(["P"], repo_root=tmp) if p["node_id"] == "P::does-not-exist"])
