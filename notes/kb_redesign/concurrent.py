"""P11: parallel appends to one ledger with no lock corrupt the hash chain. Run from the repo root: python3 notes/kb_redesign/concurrent.py"""
import json, os, subprocess, sys, tempfile
from multiprocessing import Process
from pathlib import Path
ROOT = "/data/haiyangw/harness/Chandra"; sys.path.insert(0, ROOT)
from _common.ledgers import error_database as edb, ledger_common as lc
os.environ["CHANDRA_ROLE"] = "worker"
def worker(tmp, w):
    for i in range(25):
        edb.append_row({"paper": "P", "task_id": f"w{w}", "iteration": i, "stage": "implementation", "domain": "software",
                        "change_type": "structural", "change_summary": f"w{w} i{i}", "node_id": "P::n",
                        "metric": {"name": "tests_failed", "value": 0, "threshold": 0, "pass": True}, "pass_fail": "pass",
                        "wall_clock_seconds": 1}, repo_root=tmp)
for run in range(3):
    tmp = Path(tempfile.mkdtemp(prefix="kb-conc-", dir="/tmp")); subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    ps = [Process(target=worker, args=(tmp, w)) for w in range(4)]
    [p.start() for p in ps]; [p.join() for p in ps]
    rows = lc.read_jsonl(tmp, "error", "P", "trials.jsonl")
    print(f"run {run}: rows={len(rows)} verify={lc.verify_all_chains(tmp)}")
