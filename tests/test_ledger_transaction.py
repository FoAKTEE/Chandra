"""P11/P17: serialized, durable ledger writes and coordinated readers."""
from __future__ import annotations

from contextlib import contextmanager
import csv
import fcntl
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import shlex
import stat
import subprocess
import sys
import time

import pytest

from _common.ledgers import admission as adm
from _common.ledgers import claims_database as cdb
from _common.ledgers import error_database as edb
from _common.ledgers import knowledge_database as kdb
from _common.ledgers import ledger_common as lc
from _common.ledgers import result_database as rdb
from factories import (valid_claim_row, valid_error_pass_row,
                       valid_knowledge_row, valid_result_row)

ROOT = Path(__file__).resolve().parents[1]
CTX = mp.get_context("fork")
DATABASES = {"knowledge": kdb, "error": edb, "result": rdb, "claim": cdb}
INCOMPLETE = "incomplete tail (crash mid-write)"


def _row(db, index=0):
    fields = {"paper": "P", "git_commit": "test", "timestamp": "test"}
    if db == "knowledge":
        return valid_knowledge_row(**fields, node_id="P::shared", summary="shared node", notes=str(index))
    if db == "error":
        return valid_error_pass_row(**fields, node_id="P::shared", iteration=index)
    if db == "result":
        return valid_result_row(**fields, result_id=f"r{index}", status="unchecked")
    return valid_claim_row(**fields, entry_id=f"c{index}")


def _join(processes, timeout=20):
    deadline = time.monotonic() + timeout
    try:
        for process in processes:
            process.join(max(0, deadline - time.monotonic()))
        assert all(p.exitcode == 0 for p in processes), [p.exitcode for p in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(3)


def _concurrent_writer(root, worker, barrier):
    os.environ["CHANDRA_ROLE"] = "worker"
    for index in range(25):
        for db, module in DATABASES.items():
            barrier.wait(timeout=15)
            module.append_row(_row(db, worker * 25 + index), repo_root=root)


@pytest.mark.parametrize("run", range(5))
def test_four_writers_four_ledgers(tmp_path, run):
    barrier = CTX.Barrier(4)
    processes = [CTX.Process(target=_concurrent_writer, args=(tmp_path, w, barrier))
                 for w in range(4)]
    for process in processes:
        process.start()
    _join(processes)
    report = lc.verify_all_chains(tmp_path)
    assert report["ok"], (run, report)
    for db, module in DATABASES.items():
        rows = module.read_entries(tmp_path, "P")
        assert len(rows) == 100, (run, db, len(rows))
        if db in ("knowledge", "error"):
            assert [row["node_seq"] for row in rows] == list(range(1, 101)), (run, db)
        with (lc.db_dir(tmp_path, db, "P") / "summary.csv").open() as stream:
            assert len(list(csv.DictReader(stream))) == 100


@pytest.mark.parametrize("db", DATABASES)
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("tail", [b'{"paper":', b'{bad json}\n', b'{"paper":"P"}'])
def test_incomplete_tail_read_report_and_repair(tmp_path, capsys, db, legacy, tail):
    if legacy:
        (tmp_path / f"{db}-database" / "paper_P").mkdir(parents=True)
    module = DATABASES[db]
    module.append_row(_row(db), repo_root=tmp_path)
    directory = lc.db_dir(tmp_path, db, "P")
    path = directory / lc.LEDGER_FILENAMES[db]
    prefix = path.read_bytes()
    path.write_bytes(prefix + tail)
    assert len(module.read_entries(tmp_path, "P")) == 1
    warning = capsys.readouterr().err
    assert "incomplete tail" in warning and len(warning.splitlines()) == 1
    result = subprocess.run(
        [sys.executable, str(ROOT / "_common/contract.py"), "verify-chains",
         "--repo-root", str(tmp_path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["breaks"][0]["reason"] == INCOMPLETE
    module.append_row(_row(db, 1), repo_root=tmp_path)
    assert "truncat" in capsys.readouterr().err.lower()
    assert path.read_bytes().startswith(prefix)
    rows = module.read_entries(tmp_path, "P")
    assert len(rows) == 2
    if db in ("knowledge", "error"):
        assert [r["node_seq"] for r in rows] == [1, 2]
    assert lc.verify_all_chains(tmp_path)["ok"]
    assert (tmp_path / "results/ledgers/.lock").is_file()


@contextmanager
def _native_lock(root):
    """Use the specified OS lock even when probing the unpatched baseline."""
    path = root / "results/ledgers/.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _read_probe(root, operation, started, result):
    started.set()
    try:
        if operation == "rows":
            value = len(kdb.read_entries(root, "P"))
        elif operation == "chain":
            value = lc.verify_all_chains(root)
        else:
            value = [paper for paper, _ in lc.iter_paper_dirs(root, "knowledge")]
        result.put(value)
    except Exception as exc:
        result.put(str(exc))


@pytest.mark.parametrize("operation", ["rows", "chain", "inventory"])
def test_readers_wait_for_complete_write(tmp_path, operation):
    kdb.append_row(_row("knowledge"), repo_root=tmp_path)
    kdb.append_row(_row("knowledge", 1), repo_root=tmp_path)
    path = lc.db_dir(tmp_path, "knowledge", "P") / "nodes.jsonl"
    complete = path.read_bytes()
    started, result = CTX.Event(), CTX.Queue()
    with _native_lock(tmp_path):
        path.write_bytes(complete[:-20])
        process = CTX.Process(target=_read_probe, args=(tmp_path, operation, started, result))
        process.start()
        assert started.wait(3)
        try:
            premature = result.get(timeout=0.15)
        except queue.Empty:
            premature = None
        path.write_bytes(complete)
    _join([process])
    assert premature is None, f"reader ran during exclusive write: {premature}"
    value = result.get(timeout=2)
    assert value == {"rows": 2, "chain": {"ok": True, "breaks": []},
                     "inventory": ["P"]}[operation]


def _command(code):
    return shlex.join([sys.executable, "-c", code])


def _await_file(path, timeout=5):
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(str(path))
        time.sleep(0.01)


def _candidate(root, verified, finished, output):
    original = adm.run_verification

    def observe(spec, repo_root):
        outcome = original(spec, repo_root)
        verified.set()
        return outcome

    adm.run_verification = observe
    code = ("from pathlib import Path; import time\n"
            "Path('started').touch()\n"
            "while not Path('release-verifier').exists(): time.sleep(0.01)\n")
    try:
        kdb.append_row(valid_knowledge_row(
            paper="P", node_id="P::child", status="solid", evidence="command",
            predecessors=["Q::base"], verification={"command": _command(code), "timeout_s": 5}),
            repo_root=root)
        output.put("admitted")
    except adm.AdmissionError as exc:
        output.put(str(exc))
    finally:
        finished.set()


def _demoter(root, verified, finished, output):
    # The fallback lets the baseline fail for its missing transaction boundary,
    # rather than failing at import before exercising the race.
    try:
        from _common.ledgers.txn import ledger_lock
    except ModuleNotFoundError:
        ledger_lock = _native_lock
    _await_file(root / "started")
    with ledger_lock(root):
        (root / "release-verifier").touch()
        assert verified.wait(5), "verification must finish outside the writer lock"
        completed_under_lock = finished.wait(0.15)
        kdb.append_row(valid_knowledge_row(paper="Q", node_id="Q::base"), repo_root=root)
    output.put(completed_under_lock)


def test_cross_paper_demotion_revalidated_after_verification(tmp_path):
    (tmp_path / "evidence.txt").write_text("verified")
    kdb.append_row(valid_knowledge_row(paper="Q", node_id="Q::base", status="solid",
                                        evidence="evidence.txt"), repo_root=tmp_path)
    verified, finished = CTX.Event(), CTX.Event()
    candidate_result, demoter_result = CTX.Queue(), CTX.Queue()
    processes = [CTX.Process(target=_candidate, args=(tmp_path, verified, finished, candidate_result)),
                 CTX.Process(target=_demoter, args=(tmp_path, verified, finished, demoter_result))]
    for process in processes:
        process.start()
    _join(processes, timeout=12)
    assert demoter_result.get(timeout=2) is False, "candidate committed while B held the repository lock"
    assert "non-solid predecessor" in candidate_result.get(timeout=2)
    assert kdb.read_entries(tmp_path, "P") == []
    assert lc.verify_all_chains(tmp_path)["ok"]


@pytest.mark.parametrize("db", ["knowledge", "result"])
@pytest.mark.parametrize("action", ["append", "read"])
def test_verifiers_before_batch_lock_and_only_once(tmp_path, monkeypatch, db, action):
    monkeypatch.setenv("CHANDRA_LOCK_TIMEOUT_S", "1")
    module = DATABASES[db]
    target = f"results/ledgers/{db}/paper_P/{lc.LEDGER_FILENAMES[db]}"
    code = (f"import sys; sys.path.insert(0, {str(ROOT)!r})\n"
            "from pathlib import Path\n"
            f"assert not Path({target!r}).exists(), 'batch verifier observed an earlier batch write'\n"
            "with Path('runs').open('a') as stream: stream.write('run\\n')\n")
    if action == "append":
        code += ("from _common.ledgers import error_database as edb\n"
                 f"edb.append_row({_row('error')!r}, repo_root=Path.cwd())\n")
    else:
        code += ("from _common.ledgers.txn import read_lock\n"
                 "with read_lock(Path.cwd()): pass\n")
    rows = [_row(db, i) for i in range(2)]
    for row in rows:
        row["verification"] = {"command": _command(code), "timeout_s": 4}
    assert module.append_batch(rows, repo_root=tmp_path)["appended"] == 2
    assert (tmp_path / "runs").read_text().splitlines() == ["run", "run"]
    for row in module.read_entries(tmp_path, "P"):
        execution = row["verification_run"] if db == "knowledge" else row["verifier_result"]["execution"]
        assert execution["exit_code"] == 0
    # Single-row entry points must also execute before their own lock.
    single = _row(db, 2)
    single["verification"] = {"command": _command(code.replace(
        f"assert not Path({target!r}).exists(), 'batch verifier observed an earlier batch write'\n", "")),
        "timeout_s": 4}
    module.append_row(single, repo_root=tmp_path)
    assert len((tmp_path / "runs").read_text().splitlines()) == 3
    if action == "append":
        assert len(edb.read_entries(tmp_path, "P")) == 3


@pytest.mark.parametrize("db", ["knowledge", "result"])
def test_batch_verifies_all_first_but_keeps_admitted_prefix_on_failure(tmp_path, db):
    rows = [_row(db, i) for i in range(3)]
    rows[1]["verification"] = {"command": "exit 3"}
    rows[2]["verification"] = {"command": _command("from pathlib import Path; Path('third-ran').touch()")}
    with pytest.raises(adm.AdmissionError, match="verification command failed"):
        DATABASES[db].append_batch(rows, repo_root=tmp_path)
    assert (tmp_path / "third-ran").exists()
    assert len(DATABASES[db].read_entries(tmp_path, "P")) == 1
    with (lc.db_dir(tmp_path, db, "P") / "summary.csv").open() as stream:
        assert len(list(csv.DictReader(stream))) == 1


@pytest.mark.parametrize("db", ["knowledge", "result"])
def test_batch_verifier_startup_error_keeps_prefix_and_runs_later_verifiers(tmp_path, db):
    rows = [_row(db, i) for i in range(3)]
    rows[1]["verification"] = {"command": "true", "cwd": "missing-directory"}
    rows[2]["verification"] = {"command": _command("from pathlib import Path; Path('third-ran').touch()")}
    with pytest.raises(FileNotFoundError):
        DATABASES[db].append_batch(rows, repo_root=tmp_path)
    assert len(DATABASES[db].read_entries(tmp_path, "P")) == 1
    assert (tmp_path / "third-ran").exists()
    assert lc.verify_all_chains(tmp_path)["ok"]


def test_result_batch_nonobject_row_keeps_prefix(tmp_path):
    third = _row("result", 2)
    third["verification"] = {"command": _command("from pathlib import Path; Path('third-ran').touch()")}
    with pytest.raises(TypeError):
        rdb.append_batch([_row("result"), None, third], repo_root=tmp_path)
    assert len(rdb.read_entries(tmp_path, "P")) == 1
    assert (tmp_path / "third-ran").exists()


def test_verifier_under_an_external_lock_is_rejected_before_execution(tmp_path):
    from _common.ledgers.txn import ledger_lock
    row = _row("knowledge")
    row["verification"] = {"command": _command("from pathlib import Path; Path('ran').touch()")}
    with ledger_lock(tmp_path):
        with pytest.raises(adm.AdmissionError, match="verification.*outside.*lock"):
            kdb.append_row(row, repo_root=tmp_path)
    assert not (tmp_path / "ran").exists()


def _hold_lock(root, ready, release):
    from _common.ledgers.txn import ledger_lock
    with ledger_lock(root):
        ready.set()
        assert release.wait(5)


def test_reentrant_batch_and_lock_timeout(tmp_path, monkeypatch):
    from _common.ledgers.txn import LedgerLockTimeout, ledger_lock, read_lock
    with ledger_lock(tmp_path):
        with ledger_lock(tmp_path), read_lock(tmp_path):
            for db, module in DATABASES.items():
                assert module.append_batch([_row(db, i) for i in range(2)], repo_root=tmp_path)["appended"] == 2
    ready, release = CTX.Event(), CTX.Event()
    process = CTX.Process(target=_hold_lock, args=(tmp_path, ready, release))
    process.start()
    try:
        assert ready.wait(3)
        monkeypatch.setenv("CHANDRA_LOCK_TIMEOUT_S", "1")
        start = time.monotonic()
        with pytest.raises(LedgerLockTimeout, match=r"results/ledgers/\.lock"):
            with ledger_lock(tmp_path):
                pytest.fail("entered contended lock")
        assert 0.9 <= time.monotonic() - start < 3
    finally:
        release.set()
        _join([process])
    with ledger_lock(tmp_path):
        assert lc.verify_all_chains(tmp_path)["ok"]


def test_append_is_one_write_and_fsyncs_file_and_new_directory(tmp_path, monkeypatch):
    calls = []
    original_write, original_fsync = os.write, os.fsync

    def write(fd, data):
        calls.append(("write", data))
        return original_write(fd, data)

    def fsync(fd):
        calls.append(("fsync", "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"))
        return original_fsync(fd)

    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "fsync", fsync)
    edb.append_row(_row("error"), repo_root=tmp_path)
    writes = [data for operation, data in calls if operation == "write"]
    assert len(writes) == 1 and writes[0].endswith(b"\n")
    assert json.loads(writes[0])["node_seq"] == 1
    assert calls[-2:] == [("fsync", "file"), ("fsync", "dir")]
    calls.clear()
    edb.append_row(_row("error", 1), repo_root=tmp_path)
    assert [item for item in calls if item[0] == "fsync"] == [("fsync", "file")]


def test_manifest_declares_repository_lock():
    from _common.contract import manifest
    assert manifest()["lock"] == {"path": "results/ledgers/.lock",
                                   "timeout_env": "CHANDRA_LOCK_TIMEOUT_S"}


def test_bare_and_package_imports_share_reentrant_lock(tmp_path):
    code = (f"import sys; sys.path.insert(0, {str(ROOT / '_common/ledgers')!r})\n"
            "import ledger_common\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "from _common.ledgers.txn import ledger_lock\n"
            f"with ledger_lock({str(tmp_path)!r}):\n"
            f"    with ledger_common.ledger_lock({str(tmp_path)!r}): pass\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, timeout=3,
                            env={**os.environ, "CHANDRA_LOCK_TIMEOUT_S": "0.2"})
    assert result.returncode == 0, result.stderr


def test_existing_readable_lock_supports_read_only_readers(tmp_path):
    from _common.ledgers.txn import read_lock
    kdb.append_row(_row("knowledge"), repo_root=tmp_path)
    path = tmp_path / "results/ledgers/.lock"
    path.chmod(0o444)
    try:
        with read_lock(tmp_path):
            assert len(kdb.read_entries(tmp_path, "P")) == 1
    finally:
        path.chmod(0o644)


@pytest.mark.parametrize("legacy", [False, True])
def test_first_append_syncs_new_directory_ancestors(tmp_path, monkeypatch, legacy):
    if legacy:
        (tmp_path / "error-database/paper_P").mkdir(parents=True)
    synced = set()
    original = os.fsync

    def record(fd):
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            synced.add((info.st_dev, info.st_ino))
        return original(fd)

    monkeypatch.setattr(os, "fsync", record)
    edb.append_row(_row("error"), repo_root=tmp_path)
    directory = lc.db_dir(tmp_path, "error", "P")
    for parent in [directory, *directory.parents]:
        info = parent.stat()
        assert (info.st_dev, info.st_ino) in synced, f"directory entry not durable: {parent}"
        if parent == tmp_path:
            break


def test_forked_context_does_not_close_reused_child_descriptor(tmp_path):
    code = (f"import os, sys; sys.path.insert(0, {str(ROOT)!r})\n"
            "from _common.ledgers.txn import ledger_lock\n"
            f"with ledger_lock({str(tmp_path)!r}):\n"
            "    child = os.fork()\n"
            "    if child == 0:\n"
            f"        fd = os.open({str(tmp_path / 'child-file')!r}, os.O_WRONLY | os.O_CREAT, 0o600)\n"
            "if child == 0:\n"
            "    try: os.write(fd, b'child still owns this fd')\n"
            "    except OSError: os._exit(1)\n"
            "    os.close(fd)\n"
            "    os._exit(0)\n"
            "_, status = os.waitpid(child, 0)\n"
            "assert status == 0, status\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=3)
    assert result.returncode == 0, result.stderr
