"""Provider-neutral LLM layer for the Dojo harness.

Neutral message format (what the harness builds):
  {"role": "user", "content": [ {"type": "text", "text": ...},
                                {"type": "tool_result", "id": ..., "content": str, "is_error": bool} ]}
  {"role": "assistant", "content": [ {"type": "text", "text": ...},
                                     {"type": "tool_call", "id": ..., "name": ..., "args": {...}} ],
   "raw": <provider-native content, replayed verbatim (keeps thinking blocks)>}

Providers: anthropic (Messages API), openai (Chat Completions, any compatible
endpoint), mock (offline scripted player used by tests).
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import requests


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON schema


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict]           # [{"id","name","args"}]
    usage: dict = field(default_factory=dict)
    stop_reason: str = ""
    raw_assistant: Any = None        # provider-native content to replay
    latency_s: float = 0.0

    def as_message(self) -> dict:
        content: list[dict] = []
        if self.text:
            content.append({"type": "text", "text": self.text})
        for tc in self.tool_calls:
            content.append({"type": "tool_call", "id": tc["id"], "name": tc["name"], "args": tc["args"]})
        raw = self.raw_assistant
        if not content:  # empty turn (e.g. truncated output): APIs reject empty assistant messages
            content = [{"type": "text", "text": "(no output)"}]
            raw = None
        elif isinstance(raw, list) and not any(b.get("type") in ("text", "tool_use") for b in raw):
            raw = None
        return {"role": "assistant", "content": content, "raw": raw}


class LLMError(RuntimeError):
    pass


class LLM:
    provider = "base"

    def __init__(self, model: str, max_tokens: int = 16000, effort: str = "", extra: Optional[dict] = None,
                 timeout: float = 600.0, max_retries: int = 8):
        self.model, self.max_tokens, self.effort = model, max_tokens, effort
        self.extra = extra or {}
        self.timeout, self.max_retries = timeout, max_retries

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        raise NotImplementedError

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        delay = 2.0
        last = ""
        for attempt in range(self.max_retries):
            try:
                r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                last = str(e)
            else:
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}: {r.text[:500]}"
                if r.status_code not in (408, 409, 429, 500, 502, 503, 504, 529):
                    raise LLMError(last)
            time.sleep(delay)
            delay = min(delay * 2, 120)
        raise LLMError(f"giving up after {self.max_retries} attempts: {last}")


# ---------------------------------------------------------------------------
class AnthropicLLM(LLM):
    provider = "anthropic"

    def __init__(self, *a, base_url: str = "", api_key: str = "", **kw):
        super().__init__(*a, **kw)
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")

    def _convert(self, messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            if m["role"] == "assistant":
                if m.get("raw") is not None:
                    out.append({"role": "assistant", "content": m["raw"]})
                    continue
                blocks = []
                for c in m["content"]:
                    if c["type"] == "text":
                        blocks.append({"type": "text", "text": c["text"]})
                    elif c["type"] == "tool_call":
                        blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]})
                out.append({"role": "assistant", "content": blocks})
            else:
                blocks = []
                for c in m["content"]:
                    if c["type"] == "text":
                        blocks.append({"type": "text", "text": c["text"]})
                    elif c["type"] == "tool_result":
                        blocks.append({"type": "tool_result", "tool_use_id": c["id"], "content": c["content"],
                                       "is_error": bool(c.get("is_error"))})
                if out and out[-1]["role"] == "user":   # merge consecutive user turns
                    out[-1] = {"role": "user", "content": list(out[-1]["content"]) + blocks}
                else:
                    out.append({"role": "user", "content": blocks})
        # cache the conversation prefix up to the last user turn
        if out and out[-1]["role"] == "user" and out[-1]["content"]:
            out[-1]["content"][-1] = dict(out[-1]["content"][-1], cache_control={"type": "ephemeral"})
        return out

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": self._convert(messages),
        }
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                             for t in tools]
        if self.effort:
            body["thinking"] = {"type": "adaptive"}
            body["output_config"] = {"effort": self.effort}
        body.update(self.extra)
        t0 = time.time()
        data = self._post(f"{self.base_url}/v1/messages",
                          {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                           "content-type": "application/json"}, body)
        text, calls = [], []
        for b in data.get("content", []):
            if b["type"] == "text":
                text.append(b["text"])
            elif b["type"] == "tool_use":
                calls.append({"id": b["id"], "name": b["name"], "args": b.get("input") or {}})
        u = data.get("usage", {})
        return LLMResponse("\n".join(text), calls, {
            "input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
            "cache_read": u.get("cache_read_input_tokens", 0), "cache_write": u.get("cache_creation_input_tokens", 0)},
            data.get("stop_reason", ""), data.get("content"), time.time() - t0)


# ---------------------------------------------------------------------------
class OpenAILLM(LLM):
    """OpenAI Chat Completions (also works with OpenAI-compatible servers)."""
    provider = "openai"

    def __init__(self, *a, base_url: str = "", api_key: str = "", **kw):
        super().__init__(*a, **kw)
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not set")

    def _convert(self, system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(
                    c["text"] for c in m["content"] if c["type"] == "text") or None}
                tcs = [{"id": c["id"], "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                       for c in m["content"] if c["type"] == "tool_call"]
                if tcs:
                    msg["tool_calls"] = tcs
                out.append(msg)
            else:
                texts = [c["text"] for c in m["content"] if c["type"] == "text"]
                for c in m["content"]:
                    if c["type"] == "tool_result":
                        out.append({"role": "tool", "tool_call_id": c["id"], "content": c["content"]})
                if texts:
                    out.append({"role": "user", "content": "\n\n".join(texts)})
        return out

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        body: dict[str, Any] = {"model": self.model, "messages": self._convert(system, messages),
                                "max_completion_tokens": self.max_tokens}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.parameters}} for t in tools]
        if self.effort:
            body["reasoning_effort"] = self.effort
        body.update(self.extra)
        t0 = time.time()
        data = self._post(f"{self.base_url}/chat/completions",
                          {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, body)
        ch = data["choices"][0]
        msg = ch["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc["function"].get("arguments")}
            calls.append({"id": tc["id"], "name": tc["function"]["name"], "args": args})
        u = data.get("usage", {})
        return LLMResponse(msg.get("content") or "", calls, {
            "input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0),
            "cache_read": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
            "reasoning": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)},
            ch.get("finish_reason", ""), None, time.time() - t0)


# ---------------------------------------------------------------------------
_ROW_RE = re.compile(r"^\s*(\d+)([ .XO+()]+)(\d+)\s*$")


def parse_board_text(text: str) -> Optional[tuple[list[str], str, str]]:
    """Recover (rows, my_colour, to_play) from the arena's board text.
    Used by the mock player only."""
    for block in reversed(text.split("Game #")[1:]):
        last = "Game #" + block
        me = "B" if "you are Black" in last else "W"
        rows = []
        for line in last.splitlines():
            m = _ROW_RE.match(line)
            if m and m.group(1) == m.group(3):
                cells = m.group(2).replace("(", " ").replace(")", " ")
                rows.append("".join(ch for ch in cells if ch in ".XO+").replace("+", "."))
        if rows:
            tp = "B" if "Black (X) to play" in last else "W"
            return rows, me, tp
    return None


class MockLLM(LLM):
    """Offline stand-in for an LLM so the whole harness can be exercised
    without API keys.  Plays with a one-ply tactical heuristic and writes
    template reviews.  Its strength is meaningless; it tests plumbing."""
    provider = "mock"

    def __init__(self, *a, seed: int = 0, **kw):
        super().__init__(*a, **kw)
        self.rng = random.Random(seed)
        self.calls = 0

    def _id(self) -> str:
        return "call_" + uuid.uuid4().hex[:12]

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        from goarena.board import BLACK, WHITE, Board, point_to_coord
        from goarena.opponents import GreedyOpponent, TierSpec
        self.calls += 1
        names = {t.name for t in tools}
        last_user = messages[-1] if messages else {"content": []}
        last_text = "\n".join(c.get("text") or c.get("content") or "" for c in last_user["content"])
        usage = {"input": len(system) // 4 + sum(len(json.dumps(m["content"])) for m in messages) // 4, "output": 40}

        def call(name, args, text=""):
            tc = {"id": self._id(), "name": name, "args": args}
            return LLMResponse(text, [tc], usage, "tool_use", None)

        if "submit_review" in names:
            res = "won" if "you WON" in json.dumps(messages[:1]) else "lost"
            return call("submit_review", {
                "review": f"Mock review: I {res}. Key lesson: keep groups connected and count liberties.",
                "journal_line": f"{res}; keep groups connected",
                "playbook_edits": [{"op": "add", "text": f"(mock lesson {self.calls}) Count liberties before attacking."}],
                "opponent_note": "mock note"})
        if "rewrite_playbook" in names:
            return call("rewrite_playbook", {"items": ["Count liberties before attacking.",
                                                       "Keep stones connected; avoid self-atari."],
                                             "plan": "Play the weakest opponent until winning 80%, then move up."})
        if "play" in names:
            if "GAME OVER" in last_text:
                return LLMResponse("Game finished.", [], usage, "end_turn", None)
            parsed = parse_board_text(last_text)
            if "new_game" in names and (parsed is None or "No game in progress" in last_text or "Start the next game" in last_text):
                # naive curriculum: weakest opponent where the score is still below 70%
                opp = "random"
                for m in re.finditer(r"^\s+(\S+)\s+\((?:~-?\d+ Elo)[^)]*\): (?:(\d+)/(\d+) won|not played)",
                                     last_text, re.M):
                    w, n = int(m.group(2) or 0), int(m.group(3) or 0)
                    opp = m.group(1)
                    if n < 3 or w / n < 0.7:
                        break
                return call("new_game", {"opponent": opp}, "Starting a game.")
            if parsed is None:
                return call("board", {})
            rows, me, tp = parsed
            size = len(rows)
            b = Board(size)
            for y, row in enumerate(rows):
                for x, ch in enumerate(row):
                    if ch in "XO":
                        b.cells[y * size + x] = BLACK if ch == "X" else WHITE
            b.to_play = BLACK if tp == "B" else WHITE
            if "ILLEGAL MOVE" in last_text:
                return call("play", {"move": "pass"})
            dec = GreedyOpponent(TierSpec("m", "m", "greedy"), self.rng).genmove(b, {})
            return call("play", {"move": point_to_coord(dec.point, size),
                                 "plan": "mock plan: capture when possible"})
        return LLMResponse("ok", [], usage, "end_turn", None)


def make_llm(provider: str, model: str, **kw) -> LLM:
    provider = provider.lower()
    if provider == "anthropic":
        return AnthropicLLM(model, **kw)
    if provider in ("openai", "openai-compatible"):
        return OpenAILLM(model, **kw)
    if provider == "mock":
        kw.pop("base_url", None)
        kw.pop("api_key", None)
        return MockLLM(model, **kw)
    raise LLMError(f"unknown provider {provider}")
