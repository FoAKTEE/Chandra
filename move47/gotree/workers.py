"""Worker backends.  A worker turns one Job into one validated result, in a
fresh context every time.

  mock     offline heuristics (tests, plumbing, cost-free dry runs)
  api      Anthropic / OpenAI-compatible API with a small tool loop
  claude   a fresh Claude Code session per job (`claude -p`, job directory + gtree tool)
  codex    a fresh Codex session per job (`codex exec`)
"""
from __future__ import annotations

import json
import os
import random
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import heuristics
from .jobs import SCHEMAS, TOOLS_API, InvalidResult, Job, validate
from .perception import ladder_captured, short_card, window
from .position import IllegalMove, Position, coord, point

REPO = Path(__file__).resolve().parent.parent


@dataclass
class JobResult:
    ok: bool
    result: Optional[dict] = None
    error: str = ""
    tries: list[dict] = field(default_factory=list)   # [{"moves":[int], "winrate":float|None, "note":str}]
    usage: dict = field(default_factory=dict)
    worker: str = ""
    seconds: float = 0.0


class Worker:
    name = "base"

    def run(self, job: Job) -> JobResult:  # pragma: no cover
        raise NotImplementedError


# ------------------------------------------------------------------ helpers shared by api + gtree
def apply_line(pos: Position, moves: list[str]) -> tuple[Position, list[int], str]:
    """Play a sequence of coordinates from pos.  Returns (final, points, report)."""
    cur, pts, rep = pos, [], []
    for i, m in enumerate(moves):
        try:
            p = point(m, pos.size)
            nxt = cur.play(p)
        except IllegalMove as e:
            rep.append(f"move {i + 1} ({m}) is illegal: {e.message}; stopped there.")
            break
        cap = sum(1 for a, b in zip(cur.cells, nxt.cells) if a != "." and b == ".")
        if cap:
            rep.append(f"move {i + 1} {m} captures {cap} stone(s)")
        pts.append(p)
        cur = nxt
        if cur.terminal:
            rep.append("two passes: the game ends here")
            break
    return cur, pts, "\n".join(rep)


def tool_try(pos: Position, moves: list[str]) -> tuple[str, list[int]]:
    final, pts, rep = apply_line(pos, moves)
    seq = " ".join(coord(p, pos.size) for p in pts)
    return (f"Sequence played: {seq or '(nothing)'}\n{rep}\n" + short_card(final, title=f"After {len(pts)} move(s)")), pts


def tool_ladder(pos: Position, at: str) -> str:
    p = point(at, pos.size)
    if p is None or pos.cells[p] == ".":
        return f"There is no stone at {at}."
    r = ladder_captured(pos, p)
    _, libs = pos.chain(p)
    if r is None:
        return f"The chain at {at} has {len(libs)} liberties; ladders only apply with 1-2 liberties."
    return f"Chain at {at} ({len(libs)} liberties): " + ("CAN be captured in a ladder." if r else "escapes the ladder.")


# ------------------------------------------------------------------ mock
class MockWorker(Worker):
    """No LLM: priors from code heuristics, value from the influence sketch."""
    name = "mock"

    def __init__(self, seed: int = 0, delay: float = 0.0):
        self.rng = random.Random(seed)
        self.delay = delay

    def run(self, job: Job) -> JobResult:
        t0 = time.time()
        if self.delay:
            time.sleep(self.delay)
        pos = job.pos
        k = job.kind
        raw: dict[str, Any]
        if k in ("expand", "more", "refute"):
            excl = set(job.params.get("exclude_points", []))
            region = set(job.params.get("region_points") or [])
            pool = heuristics.priors(pos, 400 if region else job.params.get("k", 8) + len(excl))
            pri = [(p, w) for p, w in pool if p not in excl and (not region or p in region)]
            pri = pri[: job.params.get("k", 8)]
            legal = [p for p in pos.legal_moves() if p not in excl and p not in {q for q, _ in pri}]
            unconv = self.rng.sample(legal, min(job.params.get("u", 2), len(legal))) if legal else []
            v = heuristics.value(pos)
            raw = {"candidates": [{"move": coord(p, pos.size), "prior": w, "why": "heuristic"} for p, w in pri],
                   "unconventional": [{"move": coord(p, pos.size), "why": "random exploration"} for p in unconv],
                   "value": {"winrate": v, "score_lead": 0, "confidence": "low", "why": "influence sketch"},
                   "plan": "mock"}
        elif k == "rollout":
            cur, line = pos, []
            for _ in range(job.params.get("d", 8)):
                pri = heuristics.priors(cur, 4)
                p = self.rng.choices([q for q, _ in pri], weights=[w for _, w in pri])[0]
                line.append(coord(p, pos.size))
                cur = cur.play(p)
                if cur.terminal:
                    break
            v_end = heuristics.value(cur)
            v_start = v_end if cur.to_play == pos.to_play else 1 - v_end
            raw = {"moves": line, "value_at_end": {"winrate": v_start, "confidence": "low", "why": "mock"}}
        elif k == "decide":
            raw = {"move": job.params.get("most_visited", "pass"), "why": "most visited"}
        elif k == "abstract":
            mv = job.params.get("chosen", "pass")
            raw = {"lessons": [{"scope": "local", "at": mv, "text": f"(mock) the search preferred {mv} in this shape"},
                               {"scope": "global", "text": "(mock) keep groups connected before attacking"}]}
            if mv == "pass":
                raw["lessons"] = raw["lessons"][1:]
        elif k == "recall":
            raw = {"recognized": False}
        elif k == "consolidate":
            ids = re.findall(r"\[([GL]\d+)\]", job.context)
            raw = {"merge": [], "concepts": [{"text": "(mock) concept over the first lessons", "children": ids[:2]}]
                   if len(ids) >= 2 else []}
        else:
            return JobResult(False, error=f"unknown kind {k}", worker=self.name)
        try:
            res = validate(job, raw)
        except InvalidResult as e:
            return JobResult(False, error=str(e), worker=self.name)
        return JobResult(True, res, worker=self.name, seconds=time.time() - t0,
                         usage={"input": len(job.prompt()) // 4, "output": 200})


# ------------------------------------------------------------------ API
class APIWorker(Worker):
    """Direct API calls (Anthropic Messages or OpenAI-compatible) with a tool loop."""

    def __init__(self, llm, max_steps: int = 12, memory=None):
        self.llm = llm
        self.max_steps = max_steps
        self.memory = memory
        self.name = f"api:{llm.model}"

    def run(self, job: Job) -> JobResult:
        from harness.dojo.llm import ToolSpec
        t0 = time.time()
        pos = job.pos
        tools = [
            ToolSpec("try_moves", "Play a sequence of moves from the job position (alternating colours, starting "
                     "with the side to move) and see the resulting board.",
                     {"type": "object", "properties": {"moves": {"type": "array", "items": {"type": "string"}},
                                                       "winrate_for_side_to_move_now": {"type": "number"}},
                      "required": ["moves"]}),
            ToolSpec("window", "Zoomed view around a point.", {"type": "object", "properties": {
                "center": {"type": "string"}, "radius": {"type": "integer"}}, "required": ["center"]}),
            ToolSpec("ladder", "Does the chain at this point die in a ladder?", {"type": "object", "properties": {
                "point": {"type": "string"}}, "required": ["point"]}),
            ToolSpec("lessons", "Search stored lessons by keywords.", {"type": "object", "properties": {
                "query": {"type": "string"}}, "required": ["query"]}),
            ToolSpec("submit", "Submit the final answer (validated; fix and resubmit if it reports errors).",
                     SCHEMAS[job.kind]),
        ]
        system = job.prompt(tools=TOOLS_API)
        msgs: list[dict] = [{"role": "user", "content": [{"type": "text", "text": "Do the job described in the system prompt."}]}]
        usage = {"input": 0, "output": 0, "cache_read": 0, "calls": 0}
        tries: list[dict] = []
        for _ in range(self.max_steps):
            resp = self.llm.complete(system, msgs, tools)
            usage["calls"] += 1
            for k2 in ("input", "output", "cache_read"):
                usage[k2] += int(resp.usage.get(k2, 0) or 0)
            msgs.append(resp.as_message())
            if not resp.tool_calls:
                raw = _json_from_text(resp.text)
                if raw is not None:
                    try:
                        return JobResult(True, validate(job, raw), tries=tries, usage=usage, worker=self.name,
                                         seconds=time.time() - t0)
                    except InvalidResult as e:
                        msgs.append({"role": "user", "content": [{"type": "text", "text": f"Invalid answer: {e}. "
                                                                  "Call submit with a corrected answer."}]})
                        continue
                msgs.append({"role": "user", "content": [{"type": "text", "text": "Call the submit tool with your answer."}]})
                continue
            results = []
            done = None
            for tc in resp.tool_calls:
                a = tc.get("args") or {}
                err = False
                try:
                    if tc["name"] == "try_moves":
                        out, pts = tool_try(pos, [str(m) for m in a.get("moves", [])][:40])
                        wr = a.get("winrate_for_side_to_move_now")
                        tries.append({"moves": pts, "winrate": float(wr) if isinstance(wr, (int, float)) else None,
                                      "note": ""})
                    elif tc["name"] == "window":
                        out = window(pos, point(str(a.get("center")), pos.size), int(a.get("radius", 4)))
                    elif tc["name"] == "ladder":
                        out = tool_ladder(pos, str(a.get("point", "")))
                    elif tc["name"] == "lessons":
                        rows = self.memory.search(str(a.get("query", ""))) if self.memory else []
                        out = "\n".join(f"[{'G' if r['scope'] == 'global' else 'L'}{r['id']}] {r['text']}" for r in rows) \
                            or "(no matches)"
                    elif tc["name"] == "submit":
                        try:
                            done = validate(job, a)
                            out = "OK"
                        except InvalidResult as e:
                            out, err = f"INVALID: {e}", True
                    else:
                        out, err = f"unknown tool {tc['name']}", True
                except Exception as e:  # keep the loop alive
                    out, err = f"tool error: {e}", True
                results.append({"type": "tool_result", "id": tc["id"], "content": out, "is_error": err})
            if done is not None:
                return JobResult(True, done, tries=tries, usage=usage, worker=self.name, seconds=time.time() - t0)
            msgs.append({"role": "user", "content": results})
        return JobResult(False, error="no valid answer within the step limit", tries=tries, usage=usage,
                         worker=self.name, seconds=time.time() - t0)


def _json_from_text(text: str) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    cand = m.group(1) if m else None
    if cand is None:
        i, j = text.find("{"), text.rfind("}")
        cand = text[i:j + 1] if i >= 0 and j > i else None
    if cand is None:
        return None
    try:
        return json.loads(cand)
    except json.JSONDecodeError:
        return None


# ------------------------------------------------------------------ CLI agents
# Every Claude Code worker session starts clean (checked on Claude Code 2.1.290 against the
# stream-json system/init event; README "Worker sessions and sandbox"):
CLAUDE_CLEAN_FLAGS = (
    "--setting-sources", "",             # no user/project/local settings: hooks, enabled plugins, model and effort defaults
    "--strict-mcp-config",               # no MCP servers: user, project, plugin, claude.ai connectors
    "--tools", "Bash,Read,Write,Edit",   # built-in tools limited to what the job protocol needs (no web, agents, cron)
    "--disallowed-tools", "WebFetch,WebSearch",
    "--disable-slash-commands",          # no skills: user, plugin, bundled
    "--no-session-persistence",          # no transcript under ~/.claude/projects (session.jsonl keeps the stream)
    "--settings", '{"autoMemoryEnabled": false}',   # no auto-memory read or written
)
# Variables a worker must not inherit: arena / engine secrets; for clean claude sessions also the parent
# Claude Code session's own variables when gotree runs inside one (messaging-socket token, effort, nesting
# markers), the KataGo service's and Slurm's.
_SECRET_ENV = ("GOARENA_TOKEN", "GOARENA_ADMIN_TOKEN", "KATAGO_BIN", "KATAGO_MODEL")
_DROP_ENV = ("CLAUDECODE", "CLAUDE_EFFORT", "CLAUDE_PID", "CLAUDE_PLUGIN_DATA", "AI_AGENT")
_DROP_ENV_PREFIXES = ("CLAUDE_CODE_", "CODEX_COMPANION_", "KGSERVICE_", "SLURM_")


class CLIWorker(Worker):
    """One fresh Claude Code / Codex session per job, run inside a job directory
    that contains JOB.md, job.json and the `gtree` tool on PATH.

    clean=True (default) adds CLAUDE_CLEAN_FLAGS to claude sessions and strips the parent
    session's variables from their environment; codex sessions are unaffected."""

    def __init__(self, agent: str, model: str, run_dir: Path, dag_path: str, mem_path: str, *, effort: str = "",
                 timeout: float = 1800, binary: str = "", wrap: str = "", extra: Optional[list[str]] = None,
                 clean: bool = True):
        assert agent in ("claude", "codex")
        self.agent, self.model, self.effort = agent, model, effort
        self.clean = clean
        self.run_dir = Path(run_dir)
        self.dag_path, self.mem_path = dag_path, mem_path
        self.timeout, self.wrap, self.extra = timeout, wrap, extra or []
        self.binary = binary or agent
        self.name = f"{agent}:{model or 'default'}"
        bindir = self.run_dir / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        launcher = bindir / "gtree"
        launcher.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -m gotree.gtree \"$@\"\n")
        launcher.chmod(0o755)

    def command(self, prompt: str, jd: Path) -> list[str]:
        if self.agent == "claude":
            cmd = [self.binary, "-p", prompt, "--output-format", "stream-json", "--verbose",
                   "--dangerously-skip-permissions"]
            if self.model:
                cmd += ["--model", self.model]
            if self.effort:
                cmd += ["--effort", self.effort]
            if self.clean:
                cmd += list(CLAUDE_CLEAN_FLAGS)
        else:
            cmd = [self.binary, "exec", "--json", "--dangerously-bypass-approvals-and-sandbox",
                   "--skip-git-repo-check", "-C", str(jd)]
            if self.model:
                cmd += ["-m", self.model]
            if self.effort:
                cmd += ["-c", f"model_reasoning_effort={self.effort}"]
            cmd += [prompt]
        cmd += self.extra
        if self.wrap:
            cmd = shlex.split(self.wrap.format(jobdir=jd)) + cmd
        return cmd

    def run(self, job: Job) -> JobResult:
        t0 = time.time()
        import uuid
        jd = self.run_dir / "jobs" / f"{job.id:06d}-{job.kind}-{uuid.uuid4().hex[:6]}"
        jd.mkdir(parents=True, exist_ok=True)
        (jd / "job.json").write_text(json.dumps(job.to_json()))
        (jd / "JOB.md").write_text(job.prompt())
        for f in ("result.json", "tries.jsonl", "accepted.json"):
            (jd / f).unlink(missing_ok=True)
        prompt = ("Read JOB.md in this directory and do the job it describes. Use the gtree tool to read "
                  "variations. Finish by writing your JSON answer to result.json and running "
                  "`gtree submit result.json` until it prints OK. Do not do anything else.")
        env = dict(os.environ, GTREE_JOB=str(jd), GTREE_DAG=self.dag_path, GTREE_MEM=self.mem_path,
                   PATH=f"{self.run_dir / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
                   PYTHONPATH=f"{REPO}{os.pathsep}{os.environ.get('PYTHONPATH', '')}")
        for k in _SECRET_ENV:
            env.pop(k, None)
        if self.agent == "claude" and self.clean:
            for k in list(env):
                if k in _DROP_ENV or k.startswith(_DROP_ENV_PREFIXES):
                    del env[k]
            env.update(CLAUDE_CODE_DISABLE_AUTO_MEMORY="1", CLAUDE_CODE_DISABLE_CLAUDE_MDS="1")
        try:
            with open(jd / "session.jsonl", "w") as fo, open(jd / "session.err", "w") as fe:
                rc = subprocess.run(self.command(prompt, jd), cwd=jd, env=env, stdout=fo, stderr=fe,
                                    stdin=subprocess.DEVNULL, timeout=self.timeout).returncode
        except subprocess.TimeoutExpired:
            rc = -9
        except FileNotFoundError as e:
            return JobResult(False, error=f"cannot start {self.agent}: {e}", worker=self.name)
        tries = []
        tf = jd / "tries.jsonl"
        if tf.exists():
            for line in tf.read_text().splitlines():
                try:
                    tries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        usage = _cli_usage(jd / "session.jsonl")
        rf = jd / "accepted.json"
        if not rf.exists():
            return JobResult(False, error=f"session ended (rc={rc}) without an accepted answer", tries=tries,
                             usage=usage, worker=self.name, seconds=time.time() - t0)
        try:
            res = validate(job, json.loads(rf.read_text()))
        except (InvalidResult, json.JSONDecodeError) as e:
            return JobResult(False, error=f"invalid answer: {e}", tries=tries, usage=usage, worker=self.name)
        return JobResult(True, res, tries=tries, usage=usage, worker=self.name, seconds=time.time() - t0)


def _cli_usage(path: Path) -> dict:
    """Best-effort token accounting from Claude Code stream-json / Codex JSONL."""
    u = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0}
    try:
        for line in path.read_text(errors="ignore").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "result":           # Claude Code final message
                us = d.get("usage") or {}
                u["input"] += int(us.get("input_tokens", 0) or 0)
                u["output"] += int(us.get("output_tokens", 0) or 0)
                u["cache_read"] += int(us.get("cache_read_input_tokens", 0) or 0)
                u["cache_write"] += int(us.get("cache_creation_input_tokens", 0) or 0)
                u["cost_usd"] += float(d.get("total_cost_usd", 0) or 0)
            elif d.get("type") == "turn.completed":  # Codex
                us = d.get("usage") or {}
                u["input"] += int(us.get("input_tokens", 0) or 0)
                u["output"] += int(us.get("output_tokens", 0) or 0)
                u["cache_read"] += int(us.get("cached_input_tokens", 0) or 0)
    except OSError:
        pass
    return u


def make_worker(spec: str, *, run_dir: Path, dag_path: str, mem_path: str, memory=None, seed: int = 0,
                timeout: float = 1800, wrap: str = "", clean: bool = True,
                claude_args: Optional[list[str]] = None) -> Worker:
    """spec examples: mock | api:anthropic:claude-opus-5-5:high | api:openai:gpt-6.1-sol |
    claude:opus:high | codex:gpt-6.1-sol:high"""
    parts = spec.split(":")
    kind = parts[0]
    if kind == "mock":
        return MockWorker(seed=seed)
    if kind == "api":
        from harness.dojo.llm import make_llm
        provider, model = parts[1], parts[2]
        effort = parts[3] if len(parts) > 3 else ""
        return APIWorker(make_llm(provider, model, effort=effort), memory=memory)
    if kind in ("claude", "codex"):
        model = parts[1] if len(parts) > 1 else ""
        effort = parts[2] if len(parts) > 2 else ""
        return CLIWorker(kind, model, run_dir, dag_path, mem_path, effort=effort, timeout=timeout, wrap=wrap,
                         clean=clean, extra=list(claude_args or []) if kind == "claude" else None)
    raise ValueError(f"unknown worker spec {spec}")
