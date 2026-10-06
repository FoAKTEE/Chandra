"""Worker isolation: clean Claude Code flags in CLIWorker, and the bwrap launcher bin/worker-sandbox.

The canaries run the sandbox with plain commands instead of claude (no model, no network use)."""
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from gotree.dag import DAG
from gotree.jobs import Job
from gotree.memory import Memory
from gotree.position import Position, point
from gotree.search import Search, SearchConfig
from gotree.workers import CLAUDE_CLEAN_FLAGS, CLIWorker, _cli_usage, make_worker

MOVE47 = Path(__file__).resolve().parent.parent
CHANDRA = MOVE47.parent
WORKSPACE = CHANDRA.parent
SANDBOX = MOVE47 / "bin" / "worker-sandbox"
PROTECTED = [MOVE47 / "engines", MOVE47 / "engines" / "run", MOVE47 / "engines" / "run" / "backends",
             MOVE47 / "judge", MOVE47 / "logs", MOVE47 / "gtp_logs", CHANDRA / "ref-code", WORKSPACE / "ref-code",
             WORKSPACE / "progress", WORKSPACE / "runs" / "move47" / "arena", CHANDRA / ".git",
             CHANDRA / "results", MOVE47 / "data", MOVE47 / "TREE.md", MOVE47 / "gotree" / "probe.py",
             MOVE47 / "gotree" / "judge.py", Path.home() / ".claude" / "projects", Path.home() / ".ssh",
             Path("/run/user") / str(os.getuid()), Path("/run/munge")]
SPEC = "claude:claude-opus-5-5:xhigh"


def _flag_value(cmd, flag):
    return cmd[cmd.index(flag) + 1]


# ------------------------------------------------------------------ CLIWorker command construction
def test_clean_flags_are_added_to_claude_commands(tmp_path):
    w = make_worker(SPEC, run_dir=tmp_path, dag_path="d", mem_path="m")
    assert isinstance(w, CLIWorker) and w.clean
    cmd = w.command("PROMPT", tmp_path / "jd")
    assert cmd[:3] == ["claude", "-p", "PROMPT"]
    assert _flag_value(cmd, "--model") == "claude-opus-5-5" and _flag_value(cmd, "--effort") == "xhigh"
    assert "--dangerously-skip-permissions" in cmd
    i = cmd.index("--setting-sources")
    assert cmd[i:i + len(CLAUDE_CLEAN_FLAGS)] == list(CLAUDE_CLEAN_FLAGS)
    assert _flag_value(cmd, "--setting-sources") == ""                       # no user/project/local settings
    assert "--strict-mcp-config" in cmd and "--disable-slash-commands" in cmd
    assert "--no-session-persistence" in cmd
    assert _flag_value(cmd, "--tools") == "Bash,Read,Write,Edit"
    assert {"WebFetch", "WebSearch"} <= set(_flag_value(cmd, "--disallowed-tools").split(","))
    assert json.loads(_flag_value(cmd, "--settings")) == {"autoMemoryEnabled": False}


def test_clean_flags_can_be_switched_off_and_extra_args_appended(tmp_path):
    w = make_worker(SPEC, run_dir=tmp_path, dag_path="d", mem_path="m", clean=False,
                    claude_args=["--max-budget-usd", "5"])
    cmd = w.command("P", tmp_path)
    assert not any(f in cmd for f in ("--setting-sources", "--strict-mcp-config", "--tools", "--settings"))
    assert cmd[-2:] == ["--max-budget-usd", "5"]
    w2 = make_worker(SPEC, run_dir=tmp_path, dag_path="d", mem_path="m", claude_args=["--max-budget-usd", "5"])
    assert w2.command("P", tmp_path)[-2:] == ["--max-budget-usd", "5"]      # after the clean flags


def test_codex_commands_are_untouched(tmp_path):
    a = make_worker("codex:gpt-6.1-sol:high", run_dir=tmp_path, dag_path="d", mem_path="m",
                    claude_args=["--max-budget-usd", "5"])
    b = make_worker("codex:gpt-6.1-sol:high", run_dir=tmp_path, dag_path="d", mem_path="m", clean=False)
    ca, cb = a.command("P", tmp_path), b.command("P", tmp_path)
    assert ca == cb == ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox",
                        "--skip-git-repo-check", "-C", str(tmp_path), "-m", "gpt-6.1-sol",
                        "-c", "model_reasoning_effort=high", "P"]


def test_wrap_prefixes_the_sandbox_with_the_job_dir(tmp_path):
    jd = tmp_path / "jobs" / "000001-expand-abcdef"
    w = make_worker(SPEC, run_dir=tmp_path, dag_path="d", mem_path="m", wrap=f"{SANDBOX} {{jobdir}}")
    cmd = w.command("P", jd)
    assert cmd[:3] == [str(SANDBOX), str(jd), "claude"]
    assert "--strict-mcp-config" in cmd


def test_gotree_cli_options_reach_the_worker(tmp_path):
    import argparse
    from gotree.__main__ import _build, _common
    p = argparse.ArgumentParser()
    _common(p)
    a = p.parse_args(["--run", str(tmp_path / "run"), "--worker", SPEC, "--wrap", "sbx {jobdir}",
                      "--claude-args", "--max-budget-usd 5"])
    search, _ = _build(a)
    w = search.workers["default"]
    assert w.clean and w.wrap == "sbx {jobdir}" and w.extra == ["--max-budget-usd", "5"]
    a = p.parse_args(["--run", str(tmp_path / "run2"), "--worker", SPEC, "--no-claude-clean"])
    assert not _build(a)[0].workers["default"].clean


def test_clean_session_environment(tmp_path, monkeypatch):
    """A clean claude session does not inherit the parent session's or Slurm's variables."""
    fake = tmp_path / "envdump"
    fake.write_text("#!/bin/sh\nenv > env.txt\n")
    fake.chmod(0o755)
    for k, v in {"CLAUDECODE": "1", "CLAUDE_CODE_MESSAGING_TOKEN": "s3cret", "CLAUDE_EFFORT": "low",
                 "SLURM_JOB_ID": "7", "KGSERVICE_RUN_DIR": "/x", "GOARENA_ADMIN_TOKEN": "adm", "KEEP_ME": "1"}.items():
        monkeypatch.setenv(k, v)
    pos = Position.empty(9)
    for clean in (True, False):
        run = tmp_path / f"run-{clean}"
        w = CLIWorker("claude", "m", run, str(run / "d.db"), str(run / "m.db"), binary=str(fake), clean=clean)
        assert not w.run(Job("recall", pos.key, pos, {})).ok          # the fake never submits
        env = dict(line.split("=", 1) for line in next(run.glob("jobs/*/env.txt")).read_text().splitlines()
                   if "=" in line)
        assert "GOARENA_ADMIN_TOKEN" not in env and env["KEEP_ME"] == "1"
        dropped = ("CLAUDECODE", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_EFFORT", "SLURM_JOB_ID", "KGSERVICE_RUN_DIR")
        if clean:
            assert not any(k in env for k in dropped)
            assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1" and env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        else:
            assert all(k in env for k in dropped)


def test_cli_usage_counts_cache_writes(tmp_path):
    f = tmp_path / "session.jsonl"
    f.write_text(json.dumps({"type": "system", "subtype": "init"}) + "\n" + json.dumps(
        {"type": "result", "total_cost_usd": 0.3, "usage": {"input_tokens": 14, "output_tokens": 9415,
                                                            "cache_read_input_tokens": 62184,
                                                            "cache_creation_input_tokens": 14392}}) + "\n")
    assert _cli_usage(f) == {"input": 14, "output": 9415, "cache_read": 62184, "cache_write": 14392, "cost_usd": 0.3}


# ------------------------------------------------------------------ sandbox canary
def _bwrap_works() -> bool:
    if not shutil.which("bwrap"):
        return False
    return subprocess.run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-pid",
                           "true"], capture_output=True).returncode == 0


needs_bwrap = pytest.mark.skipif(not _bwrap_works(), reason="unprivileged bwrap not available")

PROBE = r"""
import json, os, subprocess, sys
out = {"paths": {}, "slurm": {}}
for p in json.loads(sys.argv[1]):
    try:
        out["paths"][p] = sorted(os.listdir(p)) if os.path.isdir(p) else open(p).read()[:200]
    except OSError as e:
        out["paths"][p] = f"ERR {e.__class__.__name__}"
for t in ("srun", "sbatch", "salloc"):
    try:
        r = subprocess.run([t, "--version"], capture_output=True, text=True, timeout=20)
        out["slurm"][t] = r.returncode
    except OSError as e:
        out["slurm"][t] = f"ERR {e.__class__.__name__}"
def sh(*a):
    r = subprocess.run(list(a), capture_output=True, text=True, timeout=60)
    return {"rc": r.returncode, "out": r.stdout, "err": r.stderr[-500:]}
out["gtree_card"] = sh("gtree", "card")
out["gtree_known"] = sh("gtree", "known")
out["gtree_lessons"] = sh("gtree", "lessons", "corner")
from gotree.dag import DAG
out["nodes"] = DAG(os.environ["GTREE_DAG"], readonly=True).q1("SELECT COUNT(*) AS n FROM nodes")["n"]
open("written-inside.txt", "w").write("ok")
for p in (os.environ["GTREE_DAG"], os.path.dirname(sys.modules["gotree.dag"].__file__) + "/x.txt"):
    try:
        open(p, "a").write("x")
        out.setdefault("writable", []).append(p)
    except OSError:
        pass
out["env"] = sorted(os.environ)
out["pids"] = sorted(int(d) for d in os.listdir("/proc") if d.isdigit())
out["claude_json_keys"] = sorted(json.load(open(os.path.expanduser("~/.claude.json")))) \
    if os.path.exists(os.path.expanduser("~/.claude.json")) else None
out["credentials"] = os.path.exists(os.path.expanduser("~/.claude/.credentials.json"))
print(json.dumps(out))
"""


@pytest.fixture()
def live_run(tmp_path, monkeypatch):
    """A run directory with a WAL-mode DAG held open by a writer, a lesson memory, the gtree launcher and one job."""
    run = tmp_path / "run"
    dag_path, mem_path = str(run / "dag.db"), str(run / "memory.db")
    run.mkdir()
    dag, mem = DAG(dag_path), Memory(mem_path)
    pos = Position.empty(9).play(point("E5", 9))
    key, can, _ = dag.ensure(pos)
    for mv in ("C3", "G3", "C7"):
        dag.add_edge(key, point(mv, 9), 0.3, "llm", why="canary edge")
    mem.add_global("canary lesson: take the corner before the side")
    CLIWorker("claude", "m", run, dag_path, mem_path)                   # writes run/bin/gtree
    jd = run / "jobs" / "000001-expand-canary"
    jd.mkdir(parents=True)
    job = Job("expand", key, can, {})
    (jd / "job.json").write_text(json.dumps(job.to_json()))
    (jd / "JOB.md").write_text(job.prompt())
    kg = tmp_path / "kg-rendezvous"                                      # a stand-in rendezvous dir with a secret
    kg.mkdir()
    (kg / "backend-1.json").write_text('{"token": "kg-secret"}')
    env = dict(os.environ, GTREE_JOB=str(jd), GTREE_DAG=dag_path, GTREE_MEM=mem_path,
               PATH=f"{run / 'bin'}{os.pathsep}{os.environ['PATH']}", PYTHONPATH=str(MOVE47),
               GOARENA_ADMIN_TOKEN="adm-secret", CLAUDE_CODE_MESSAGING_TOKEN="msg-secret", SLURM_JOB_ID="1",
               KGSERVICE_RUN_DIR=str(kg))
    yield {"run": run, "jd": jd, "dag": dag, "mem": mem, "env": env, "kg": kg, "key": key}
    dag.db.close()
    mem.db.close()


@needs_bwrap
def test_sandbox_canary(live_run):
    jd, env, dag = live_run["jd"], live_run["env"], live_run["dag"]
    dag.add_edge(live_run["key"], point("G7", 9), 0.1, "llm", why="written while the reader runs")
    wal = Path(env["GTREE_DAG"] + "-wal")
    assert wal.exists() and wal.stat().st_size > 0                      # the newest rows live only in the WAL
    n_host = dag.q1("SELECT COUNT(*) AS n FROM nodes")["n"]
    paths = [str(p) for p in PROTECTED] + [str(live_run["kg"])]
    r = subprocess.run([sys.executable, str(SANDBOX), str(jd), "python3", "-c", PROBE, json.dumps(paths)],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    for p, seen in out["paths"].items():                                # masked: absent or empty
        assert seen in ([], "") or str(seen).startswith("ERR"), (p, seen)
    assert "kg-secret" not in r.stdout
    for t, rc in out["slurm"].items():                                  # Slurm submission does not work
        assert rc != 0, t
    assert out["gtree_card"]["rc"] == 0 and "To play" in out["gtree_card"]["out"]
    known = out["gtree_known"]
    assert known["rc"] == 0 and "G7" in known["out"] and "C3" in known["out"], known
    assert "canary lesson" in out["gtree_lessons"]["out"]
    assert out["nodes"] == n_host
    assert (jd / "written-inside.txt").read_text() == "ok"              # the job dir is writable
    assert "writable" not in out, out.get("writable")                   # code and databases are not
    for k in ("GOARENA_ADMIN_TOKEN", "CLAUDE_CODE_MESSAGING_TOKEN", "SLURM_JOB_ID", "KGSERVICE_RUN_DIR"):
        assert k not in out["env"]
    assert {"GTREE_JOB", "GTREE_DAG", "GTREE_MEM", "PYTHONPATH", "HOME"} <= set(out["env"])
    assert len(out["pids"]) < 10                                        # own pid namespace: no host processes
    if out["claude_json_keys"] is not None:
        assert "projects" not in out["claude_json_keys"]
    if (Path.home() / ".claude" / ".credentials.json").exists():
        assert out["credentials"]                                       # OAuth login stays usable
    with sqlite3.connect(env["GTREE_DAG"]) as c:                        # the writer is unaffected
        assert c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == n_host


@needs_bwrap
def test_sandbox_runs_the_job_protocol(live_run):
    """The fake Claude Code agent completes real jobs through the sandbox (gtree try / submit inside it)."""
    run = live_run["run"]
    fake = run / "bin" / "fake-claude"                                  # tests/ is masked inside the sandbox
    shutil.copy(MOVE47 / "tests" / "fake_tree_agent.py", fake)
    fake.chmod(0o755)
    w = CLIWorker("claude", "fake", run, str(run / "dag.db"), str(run / "memory.db"), binary=str(fake),
                  timeout=120, wrap=f"{sys.executable} {SANDBOX} {{jobdir}}")
    assert w.command("P", run / "jobs" / "x")[:3] == [sys.executable, str(SANDBOX), str(run / "jobs" / "x")]
    s = Search(live_run["dag"], live_run["mem"], {"default": w},
               SearchConfig(budget=4, workers=2, log_every=0, root_scouts=False, abstract=False), log=lambda m: None)
    out = s.run(Position.empty(9).play(point("D4", 9)), "sandboxed")
    errs = [p.read_text()[-300:] for p in run.glob("jobs/*/session.err") if p.read_text().strip()]
    assert out["failed"] == 0 and out["jobs"] >= 4, errs
    assert s.dag.q1("SELECT COUNT(*) AS n FROM evals WHERE kind='try_end'")["n"] >= 1


def test_sandbox_refuses_protected_job_dirs(tmp_path):
    env = dict(os.environ)
    env.pop("GTREE_DAG", None)
    env.pop("GTREE_MEM", None)
    r = subprocess.run([sys.executable, str(SANDBOX), "--print", str(MOVE47 / "engines"), "true"],
                       env=env, capture_output=True, text=True)
    if (MOVE47 / "engines").is_dir():
        assert r.returncode != 0 and "protected" in r.stderr
    jd = tmp_path / "jd"
    jd.mkdir()
    r = subprocess.run([sys.executable, str(SANDBOX), "--print", str(jd), "true"],
                       env=dict(env, GTREE_DAG=str(MOVE47 / "judge" / "dag.db")), capture_output=True, text=True)
    assert r.returncode != 0 and "protected" in r.stderr
    r = subprocess.run([sys.executable, str(SANDBOX), "--print", str(jd), "claude", "-p", "x"],
                       env=env, capture_output=True, text=True)
    argv = json.loads(r.stdout)
    assert argv[:5] == ["bwrap", "--ro-bind", "/", "/", "--dev"] and argv[-4:] == ["--", "claude", "-p", "x"]
    assert ["--tmpfs", str(WORKSPACE)] == argv[argv.index(str(WORKSPACE)) - 1:argv.index(str(WORKSPACE)) + 1]
    assert ["--bind", str(jd), str(jd)] == argv[argv.index("--chdir") - 3:argv.index("--chdir")]
    assert "--clearenv" in argv and "--unshare-pid" in argv
    assert shlex.join(argv)                                              # printable
