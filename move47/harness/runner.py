"""Campaign runner: one run = one (model, harness) pair playing N games.

The runner is the same for every harness, so differences in results come
from the harness, not the supervision:
  1. registers the run with the arena (or resumes an existing one),
  2. prepares an isolated workspace (TASK.md, `goban`, nothing else),
  3. launches agent sessions and relaunches them whenever they exit before
     all games are played (with a fixed "continue" prompt),
  4. stops on completion, on budget limits, or when sessions stop making
     progress.

  python -m harness.runner --harness claude-code --model opus --name "Opus 5.5 / Claude Code" \
      --arena http://127.0.0.1:8765 --admin-token $GOARENA_ADMIN_TOKEN --games 200
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .arena_client import ArenaClient
from .task import CONTINUE_PROMPT, FIRST_PROMPT, render_task

REPO = Path(__file__).resolve().parent.parent
SESSION_RE = re.compile(r'"(?:session_id|thread_id|conversation_id)"\s*:\s*"([0-9A-Za-z_\-]{8,})"')


# --------------------------------------------------------------- adapters
class Adapter:
    name = "base"
    pointer_files: tuple[str, ...] = ()

    def __init__(self, a: argparse.Namespace):
        self.a = a

    def command(self, ws: Path, first: bool, session_id: Optional[str]) -> list[str]:
        raise NotImplementedError


class ClaudeCodeAdapter(Adapter):
    name = "claude-code"
    pointer_files = ("CLAUDE.md",)

    def command(self, ws, first, session_id):
        prompt = FIRST_PROMPT if first else CONTINUE_PROMPT
        cmd = [self.a.claude_bin, "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"]
        if self.a.model:
            cmd += ["--model", self.a.model]
        if self.a.reasoning:
            cmd += ["--effort", self.a.reasoning]
        if not first and self.a.resume_mode == "resume" and session_id:
            cmd += ["--resume", session_id]
        return cmd + self.a.extra


class CodexAdapter(Adapter):
    name = "codex"
    pointer_files = ("AGENTS.md",)

    def command(self, ws, first, session_id):
        prompt = FIRST_PROMPT if first else CONTINUE_PROMPT
        opts = ["--json", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "-C", str(ws)]
        if self.a.model:
            opts += ["-m", self.a.model]
        if self.a.reasoning:
            opts += ["-c", f"model_reasoning_effort={self.a.reasoning}"]
        if not first and self.a.resume_mode == "resume" and session_id:
            return [self.a.codex_bin, "exec", *opts, *self.a.extra, "resume", session_id, prompt]
        return [self.a.codex_bin, "exec", *opts, *self.a.extra, prompt]


class DojoAdapter(Adapter):
    name = "dojo"

    def command(self, ws, first, session_id):
        cmd = [sys.executable, "-m", "harness.dojo", "--workspace", str(ws), "--provider", self.a.provider,
               "--model", self.a.model]
        if self.a.reasoning:
            cmd += ["--effort", self.a.reasoning]
        return cmd + self.a.extra


class TreeAdapter(Adapter):
    """The LLM tree-search harness (gotree): per move, many fresh worker sessions
    expand a shared position DAG.  Worker backend via --tree-worker."""
    name = "tree"

    def command(self, ws, first, session_id):
        cmd = [sys.executable, "-m", "gotree", "play", "--run", str(ws / "tree"), "--arena", self.a.arena,
               "--opponent", self.a.tree_opponent, "--games", str(self.a.games), "--worker", self.a.tree_worker]
        return cmd + self.a.extra


class MCTSAdapter(Adapter):
    """MCTS v2 (`python3 -m mcts play`): one reusable tree per game, simulations in code, asynchronous
    LLM expansion with --tree-worker sessions (`-- --llm off` for the code-only ablation).  The run
    state (tree checkpoints, DAG, memory, job dirs) lives in <workspace>/mcts, so a relaunch resumes
    the game from the last saved tree.  Extra args after -- go to `mcts play`."""
    name = "mcts"

    def command(self, ws, first, session_id):
        cmd = [sys.executable, "-m", "mcts", "play", "--run", str(ws / "mcts"), "--arena", self.a.arena,
               "--opponent", self.a.tree_opponent, "--games", str(self.a.games), "--worker", self.a.tree_worker]
        return cmd + self.a.extra


class CommandAdapter(Adapter):
    """Any other CLI agent (Gemini CLI, OpenHands, Aider, an in-house agent ...).
    --cmd is a template; placeholders: {prompt} {model} {reasoning} {workspace}
    {session_id}; --cmd-resume (optional) is used for relaunches when a session
    id was captured."""
    name = "cmd"
    pointer_files = ("AGENTS.md",)

    def command(self, ws, first, session_id):
        if not self.a.cmd:
            raise SystemExit("--harness cmd needs --cmd '<template>'")
        tpl = self.a.cmd_resume if (not first and session_id and self.a.cmd_resume) else self.a.cmd
        vals = {"prompt": FIRST_PROMPT if first else CONTINUE_PROMPT, "model": self.a.model,
                "reasoning": self.a.reasoning, "workspace": str(ws), "session_id": session_id or ""}
        return [part.format(**vals) for part in shlex.split(tpl)] + self.a.extra


ADAPTERS = {c.name: c for c in (ClaudeCodeAdapter, CodexAdapter, DojoAdapter, TreeAdapter, MCTSAdapter,
                                CommandAdapter)}


# ---------------------------------------------------------------- runner
def prepare_workspace(ws: Path, adapter: Adapter, games: int, window: int) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "bin").mkdir(exist_ok=True)
    (ws / "notes").mkdir(exist_ok=True)
    task = render_task(games, window)
    (ws / "TASK.md").write_text(task)
    for f in adapter.pointer_files:
        p = ws / f
        if not p.exists():
            p.write_text("Your task is described in TASK.md. Read it before doing anything else.\n")
    goban = ws / "bin" / "goban"
    shutil.copy(REPO / "goarena" / "goban.py", goban)
    goban.chmod(0o755)


def progress(client: ArenaClient, patience: float = 1800) -> tuple[int, int, int, str]:
    """Run progress; waits (up to `patience` seconds) while the arena is unreachable."""
    t0, delay = time.time(), 5.0
    while True:
        try:
            st = client.status()
            s = st["summary"]
            ag = st.get("active_game") or {}
            return s["games_played"], s["target_games"], ag.get("moves_count", 0), s["status"]
        except Exception as e:  # arena down / restarting
            if time.time() - t0 > patience:
                raise
            print(f"arena unreachable ({e}); retrying in {delay:.0f}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 120)


def main(argv=None):
    p = argparse.ArgumentParser(prog="runner", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--harness", required=True, choices=sorted(ADAPTERS))
    p.add_argument("--arena", default=os.environ.get("GOARENA_URL", "http://127.0.0.1:8765"))
    p.add_argument("--admin-token", default=os.environ.get("GOARENA_ADMIN_TOKEN", ""))
    p.add_argument("--name", default="")
    p.add_argument("--model", default="")
    p.add_argument("--provider", default="anthropic", help="dojo only: anthropic | openai | mock")
    p.add_argument("--reasoning", default="", help="effort / reasoning level passed to the harness")
    p.add_argument("--context", default="", help="context window label shown on the leaderboard")
    p.add_argument("--notes", default="")
    p.add_argument("--games", type=int, default=200)
    p.add_argument("--rating-window", type=int, default=50)
    p.add_argument("--run-id", default="", help="resume an existing run instead of creating one")
    p.add_argument("--run-config", default="", help='arena run config JSON, e.g. {"opponents": [...]}')
    p.add_argument("--run-dir", default="", help="default: runs/<run id>; the agent only sees <run-dir>/workspace")
    p.add_argument("--max-sessions", type=int, default=1000)
    p.add_argument("--session-timeout", type=float, default=6 * 3600)
    p.add_argument("--max-hours", type=float, default=0, help="stop the whole run after this many hours (0 = no limit)")
    p.add_argument("--stall-sessions", type=int, default=3, help="stop after N consecutive sessions without progress")
    p.add_argument("--resume-mode", default="fresh", choices=["fresh", "resume"],
                   help="claude-code/codex: start each relaunch fresh or resume the previous session")
    p.add_argument("--wrap", default="", help="prefix command, e.g. a docker run line; {workspace} is substituted")
    p.add_argument("--claude-bin", default="claude")
    p.add_argument("--codex-bin", default="codex")
    p.add_argument("--tree-worker", default="mock", help="--harness tree / mcts: worker spec, e.g. claude:opus:high")
    p.add_argument("--tree-opponent", default="lv3", help="--harness tree / mcts: opponent tier to play")
    p.add_argument("--cmd", default="", help="--harness cmd: command template, e.g. \"gemini -p {prompt} -m {model} --yolo\"")
    p.add_argument("--cmd-resume", default="", help="--harness cmd: template for relaunches with {session_id}")
    p.add_argument("extra", nargs=argparse.REMAINDER, help="after --, extra args for the harness command")
    a = p.parse_args(argv)
    a.extra = [x for x in a.extra if x != "--"]
    adapter = ADAPTERS[a.harness](a)

    admin = ArenaClient(a.arena, admin_token=a.admin_token)
    if a.run_id:
        runs = {r["id"]: r for r in admin.admin_runs()["runs"]}
        if a.run_id not in runs:
            sys.exit(f"no run {a.run_id}")
        run = runs[a.run_id]
    else:
        name = a.name or f"{a.model or a.provider} / {a.harness}"
        out = admin.create_run(name=name, model=a.model, harness=a.harness, reasoning=a.reasoning,
                               context=a.context, notes=a.notes, target_games=a.games,
                               config=json.loads(a.run_config) if a.run_config else {})
        if not out.get("ok"):
            sys.exit(f"could not create run: {out}")
        run = out["run"]
    run_dir = Path(a.run_dir or (REPO / "runs" / run["id"])).resolve()
    ws, logs = run_dir / "workspace", run_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    prepare_workspace(ws, adapter, run["target_games"], a.rating_window)
    state_f = logs / "state.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {"run_id": run["id"], "sessions": []}
    (logs / "run.json").write_text(json.dumps({k: run[k] for k in ("id", "name", "model", "harness")}, indent=2))

    client = ArenaClient(a.arena, token=run["token"])
    env = dict(os.environ, GOARENA_URL=a.arena, GOARENA_TOKEN=run["token"],
               PATH=f"{ws / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
               PYTHONPATH=f"{REPO}{os.pathsep}{os.environ.get('PYTHONPATH', '')}")
    env.pop("GOARENA_ADMIN_TOKEN", None)
    t_start = time.time()
    stalled = 0
    print(f"run {run['id']} ({run['name']}) workspace={ws} logs={logs}", flush=True)
    while len(state["sessions"]) < a.max_sessions:
        played, target, moves, status = progress(client)
        if played >= target or status in ("complete", "abandoned"):
            print(f"run complete: {played}/{target} games", flush=True)
            break
        if a.max_hours and time.time() - t_start > a.max_hours * 3600:
            print("time budget exhausted", flush=True)
            break
        if status == "paused":  # operator pause: wait, don't burn sessions
            time.sleep(30)
            continue
        n = len(state["sessions"]) + 1
        first = n == 1
        last_sid = next((s.get("session_id") for s in reversed(state["sessions"]) if s.get("session_id")), None)
        cmd = adapter.command(ws, first, last_sid)
        if a.wrap:
            cmd = shlex.split(a.wrap.format(workspace=ws)) + cmd
        log_out = logs / f"session-{n:04d}.jsonl"
        log_err = logs / f"session-{n:04d}.err"
        print(f"session {n}: {' '.join(shlex.quote(c) for c in cmd)[:300]}", flush=True)
        t0 = time.time()
        with open(log_out, "w") as fo, open(log_err, "w") as fe:
            proc = subprocess.Popen(cmd, cwd=ws if a.harness not in ("dojo", "tree", "mcts") else REPO, env=env, stdout=fo, stderr=fe,
                                    stdin=subprocess.DEVNULL)
            try:
                rc = proc.wait(timeout=a.session_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = -9
        sid = None
        try:
            m = SESSION_RE.search(log_out.read_text(errors="ignore")[:200_000])
            sid = m.group(1) if m else None
        except OSError:
            pass
        played2, _, moves2, _ = progress(client)
        made = (played2 > played) or (moves2 != moves)
        state["sessions"].append({"n": n, "rc": rc, "seconds": round(time.time() - t0), "session_id": sid,
                                  "games_before": played, "games_after": played2})
        state_f.write_text(json.dumps(state, indent=2))
        print(f"session {n} exited rc={rc} after {time.time() - t0:.0f}s; games {played} -> {played2}", flush=True)
        stalled = 0 if made else stalled + 1
        if stalled >= a.stall_sessions:
            print(f"no progress in {stalled} consecutive sessions; stopping (see {log_err})", flush=True)
            break
    played, target, _, status = progress(client)
    print(json.dumps(client.status()["summary"], indent=2))


if __name__ == "__main__":
    main()
