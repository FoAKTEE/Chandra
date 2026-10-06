"""Dojo: a harness built for long-horizon learning across many games.

Design (see DESIGN.md §5):
  * Episodic context: every game is played in a fresh context, so context
    length is O(1) in the number of games played (the failure mode suspected
    in the chess run was a context that kept growing with notes).
  * In-game window: only the last few turns are kept verbatim, older board
    dumps are elided, and the agent carries a running `plan` forward.
  * Structured long-term memory: a size-bounded playbook edited through
    explicit add/update/delete operations, a journal, per-opponent notes and
    a training plan.  All are plain files in the workspace.
  * Post-game reflection in a separate context, engine-free.
  * Periodic consolidation ("coach" step) that rewrites playbook and plan
    from the evidence (results over time, journal, reviews).
  * Every piece can be switched off for ablations.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from goarena.board import BLACK, WHITE, Board, coord_to_point

from ..arena_client import ArenaClient
from . import prompts as P
from .llm import LLM, LLMResponse, ToolSpec
from .memory import Memory


@dataclass
class DojoConfig:
    memory: str = "full"            # full | journal | none
    reflect: bool = True
    consolidate_every: int = 10     # 0 = never
    window: int = 6                 # in-game exchanges kept verbatim
    full_boards: int = 1            # how many recent tool results keep their full board
    playbook_chars: int = 6000
    max_steps_per_game: int = 600
    max_nudges: int = 5
    reflect_steps: int = 12
    context_mode: str = "episodic"  # episodic | single
    compact_chars: int = 600_000    # single mode: compact when the transcript exceeds this
    python_tool: bool = False
    stop_after_games: Optional[int] = None
    games_target: int = 200
    rating_window: int = 50


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


T_NEW = ToolSpec("new_game", "Start a new game against the chosen opponent.", _obj({
    "opponent": {"type": "string", "description": "opponent tier name, see status"},
    "color": {"type": "string", "enum": ["black", "white", "random"],
              "description": "optional; by default colours alternate"}}, ["opponent"]))
T_PLAY = ToolSpec("play", "Play your move in the current game. Returns the opponent's reply and the new board.", _obj({
    "move": {"type": "string", "description": "coordinate like D4 (columns skip I), or 'pass'"},
    "plan": {"type": "string", "description": "optional: replace your running plan for this game (kept across turns)"}},
    ["move"]))
T_BOARD = ToolSpec("board", "Show the current board.", _obj({}, []))
T_RESIGN = ToolSpec("resign", "Resign the current game.", _obj({}, []))
T_READ = ToolSpec("read_memory", "Read one of your memory files: playbook, plan, opponents, journal, or a game number "
                  "to read that game's review.", _obj({"name": {"type": "string"}}, ["name"]))
T_SEARCH = ToolSpec("search_memory", "Keyword search over your journal, opponent notes and game reviews.",
                    _obj({"query": {"type": "string"}}, ["query"]))
T_RECORD = ToolSpec("game_record", "Show a finished game's moves and final position.",
                    _obj({"game_no": {"type": "integer"}}, ["game_no"]))
T_STATUS = ToolSpec("status", "Show run progress and results per opponent.", _obj({}, []))
T_PY = ToolSpec("python", "Run a short Python 3 script in your scratch directory (30 s limit, no network). "
                "Use it for helper code (board bookkeeping, statistics). Never for a Go engine or search.",
                _obj({"code": {"type": "string"}}, ["code"]))
T_BOARD_AT = ToolSpec("board_at", "Show the board of the game under review after a given move number "
                      "(0 = empty board).", _obj({"ply": {"type": "integer"}}, ["ply"]))
T_SUBMIT = ToolSpec("submit_review", "Submit your review of the game (call exactly once).", _obj({
    "review": {"type": "string"},
    "journal_line": {"type": "string"},
    "playbook_edits": {"type": "array", "items": _obj({
        "op": {"type": "string", "enum": ["add", "update", "delete"]},
        "id": {"type": "integer", "description": "item id for update/delete (the N in [PN])"},
        "text": {"type": "string"}}, ["op"])},
    "opponent_note": {"type": "string"}}, ["review", "journal_line", "playbook_edits"]))
T_REWRITE = ToolSpec("rewrite_playbook", "Replace your playbook and training plan.", _obj({
    "items": {"type": "array", "items": {"type": "string"}},
    "plan": {"type": "string"}}, ["items", "plan"]))
T_SUMMARY = ToolSpec("write_summary", "Store the summary that replaces your context.",
                     _obj({"summary": {"type": "string"}}, ["summary"]))


class Dojo:
    def __init__(self, llm: LLM, client: ArenaClient, workspace: Path, cfg: DojoConfig,
                 log: Callable[[str], None] = print):
        self.llm, self.client, self.cfg, self.ws = llm, client, cfg, workspace
        self.mem = Memory(workspace, playbook_chars=cfg.playbook_chars)
        self.log = log
        self.rules = ""
        self.single_messages: list[dict] = []   # single-context mode only
        (workspace / "dojo" / "scratch").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ helpers
    def _complete(self, phase: str, game_no: Optional[int], system: str, messages: list[dict],
                  tools: list[ToolSpec]) -> LLMResponse:
        resp = self.llm.complete(system, messages, tools)
        self.mem.log("usage.jsonl", {"phase": phase, "game_no": game_no, "model": self.llm.model,
                                     "usage": resp.usage, "latency_s": round(resp.latency_s, 2),
                                     "context_chars": len(system) + len(json.dumps(messages, default=str))})
        self.mem.log(f"transcripts/{(game_no or 0):04d}-{phase}.jsonl",
                     {"request_tail": messages[-1] if messages else None, "text": resp.text,
                      "tool_calls": resp.tool_calls, "stop": resp.stop_reason})
        return resp

    def _mem_block(self) -> dict:
        if self.cfg.memory == "none":
            return {"playbook": "(memory disabled)", "plan": "(memory disabled)", "opponents": "(memory disabled)"}
        if self.cfg.memory == "journal":
            return {"playbook": "(playbook disabled)", "plan": "(plan disabled)", "opponents": "(disabled)"}
        return {"playbook": self.mem.playbook_text(), "plan": self.mem.plan(), "opponents": self.mem.opponents()}

    def _journal(self) -> str:
        return "(memory disabled)" if self.cfg.memory == "none" else self.mem.journal()

    @staticmethod
    def _user(text: str = "", results: Optional[list[dict]] = None) -> dict:
        content = list(results or [])
        if text:
            content.append({"type": "text", "text": text})
        return {"role": "user", "content": content}

    def _run_python(self, code: str) -> str:
        try:
            p = subprocess.run([sys.executable, "-I", "-c", code], cwd=self.ws / "dojo" / "scratch",
                               capture_output=True, text=True, timeout=30)
            out = (p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr else ""))
        except subprocess.TimeoutExpired:
            out = "timed out after 30 s"
        return out[:8000] or "(no output)"

    # ---------------------------------------------------------------- main
    def run(self) -> None:
        self.rules = self.client.rules()["text"]
        played_here = 0
        while True:
            st = self.client.status()
            if not st.get("ok"):
                raise RuntimeError(f"arena status failed: {st}")
            summ = st["summary"]
            self.cfg.games_target = summ["target_games"]
            self._catch_up()
            if summ["games_played"] >= summ["target_games"] or summ["status"] in ("complete", "abandoned"):
                if not st.get("active_game"):
                    self.log(f"run finished: {summ['games_played']} games")
                    return
            if summ["status"] == "paused":
                self.log("run paused by operator; waiting")
                time.sleep(60)
                continue
            if self.cfg.stop_after_games is not None and played_here >= self.cfg.stop_after_games:
                return
            game_no = self.play_game(st)
            played_here += 1
            if game_no is not None:
                self._after_game(game_no)

    def _after_game(self, game_no: int) -> None:
        if self.cfg.reflect and self.cfg.memory == "full":
            self.reflect(game_no)
        elif self.cfg.memory in ("full", "journal"):
            self._plain_journal(game_no)
        st = self.mem.state()
        st.setdefault("games_reflected", []).append(game_no)
        self.mem.save_state(st)
        if self.cfg.memory == "full" and self.cfg.consolidate_every and \
                game_no - st.get("last_consolidation", 0) >= self.cfg.consolidate_every:
            self.consolidate(game_no)

    def _catch_up(self) -> None:
        """After a crash: reflect on recent finished games the harness has not processed."""
        done = set(self.mem.state().get("games_reflected", []))
        for g in self.client.games(limit=5).get("games", []):
            if g["game_no"] not in done:
                self.log(f"catching up on game #{g['game_no']}")
                self._after_game(g["game_no"])

    def _plain_journal(self, game_no: int) -> None:
        g = self.client.game(game_no)["game"]
        self.mem.add_journal(game_no, g["opponent"], g["agent_color"], g["result"],
                             "won" if g["winner"] == "agent" else "lost", g["end_reason"])

    # ------------------------------------------------------------ playing
    def play_game(self, status: dict) -> Optional[int]:
        cfg = self.cfg
        system = P.PLAY_SYSTEM.format(games=cfg.games_target, window=cfg.rating_window, rules=self.rules,
                                      **self._mem_block())
        tools = [T_NEW, T_PLAY, T_BOARD, T_RESIGN, T_STATUS, T_RECORD]
        if cfg.memory != "none":
            tools += [T_READ, T_SEARCH]
        if cfg.python_tool:
            tools.append(T_PY)
        g = {"no": None, "opponent": "?", "color": "?", "moves": [], "plan": "(none yet)", "plans": [],
             "over": False}
        if status.get("active_game"):
            b = self.client.board()
            self._absorb(g, b)
            intro = P.PLAY_RESUME.format(board=b["text"])
        else:
            intro = P.PLAY_START.format(next_no=status["summary"]["games_played"] + 1, games=cfg.games_target,
                                        status=status["text"], journal=self._journal())
        exchanges: list[tuple[dict, dict]] = []
        nudges = 0
        for step in range(cfg.max_steps_per_game):
            msgs = self._build_messages(intro, g, exchanges)
            resp = self._complete("play", g["no"], system, msgs, tools)
            amsg = resp.as_message()
            if not resp.tool_calls:
                nudges += 1
                if g["over"]:
                    break
                if nudges > cfg.max_nudges:
                    self.log("model stopped calling tools; resigning the game to keep the run moving")
                    if g["no"] is not None:
                        r = self.client.resign()
                        self._absorb(g, r)
                    break
                exchanges.append((amsg, self._user(P.NUDGE if g["no"] else "Call `new_game` to start the game.")))
                continue
            nudges = 0
            results = []
            for tc in resp.tool_calls:
                out, is_err = self._exec_play_tool(g, tc)
                results.append({"type": "tool_result", "id": tc["id"], "content": out, "is_error": is_err})
            exchanges.append((amsg, self._user(results=results)))
            if g["over"]:
                break
        if g["no"] is not None and not g["over"]:
            self.log(f"step limit reached in game #{g['no']}; resigning")
            self._absorb(g, self.client.resign())
        if g["no"] is not None:
            self.mem.log(f"transcripts/{g['no']:04d}-plans.jsonl", {"plans": g["plans"]})
        if cfg.context_mode == "single":
            self.single_messages += [self._user(intro)] + [m for ex in exchanges for m in ex]
        return g["no"]

    def _absorb(self, g: dict, r: dict) -> None:
        if not r.get("game"):
            return
        gm = r["game"]
        g["no"] = gm["game_no"]
        g["opponent"] = gm["opponent"]
        g["color"] = "Black (X)" if gm["agent_color"] == "B" else "White (O)"
        g["moves"] = r.get("moves", g["moves"])
        if r.get("game_over"):
            g["over"] = True

    def _exec_play_tool(self, g: dict, tc: dict) -> tuple[str, bool]:
        name, a = tc["name"], tc.get("args") or {}
        try:
            if name == "new_game":
                if g["no"] is not None:  # one game per episode; the next one starts after the review
                    return ("A game is already in progress — finish it first." if not g["over"] else
                            "This game is over. The next game starts after your review."), True
                r = self.client.new_game(str(a.get("opponent", "")), a.get("color"))
                self._absorb(g, r)
                return r["text"], not r.get("ok", False)
            if name == "play":
                if a.get("plan"):
                    g["plan"] = str(a["plan"])[:1500]
                    g["plans"].append({"move": len(g["moves"]) + 1, "plan": g["plan"]})
                r = self.client.play(str(a.get("move", "")))
                self._absorb(g, r)
                return r["text"], not r.get("ok", False)
            if name == "board":
                r = self.client.board()
                self._absorb(g, r)
                return r["text"], not r.get("ok", False)
            if name == "resign":
                r = self.client.resign()
                self._absorb(g, r)
                return r["text"], not r.get("ok", False)
            if name == "status":
                return self.client.status()["text"], False
            if name == "game_record":
                r = self.client.game(int(a.get("game_no", 0)))
                return r.get("text", json.dumps(r)), not r.get("ok", False)
            if name == "read_memory":
                return self.mem.read(str(a.get("name", ""))), False
            if name == "search_memory":
                return self.mem.search(str(a.get("query", ""))), False
            if name == "python" and self.cfg.python_tool:
                return self._run_python(str(a.get("code", ""))), False
            return f"unknown tool {name}", True
        except Exception as e:  # keep the loop alive; the model sees the error
            return f"tool error: {e}", True

    def _build_messages(self, intro: str, g: dict, exchanges: list[tuple[dict, dict]]) -> list[dict]:
        cfg = self.cfg
        ctx = intro
        if g["no"] is not None:
            mv = " ".join(f"{i + 1}.{m}" for i, m in enumerate(g["moves"])) or "(none)"
            ctx += "\n\n" + P.GAME_CONTEXT.format(game_no=g["no"], opponent=g["opponent"], color=g["color"],
                                                   moves=mv, plan=g["plan"])
        if cfg.context_mode == "single":
            return self._single_messages(ctx, exchanges)
        kept = exchanges[-cfg.window:] if cfg.window > 0 else exchanges
        msgs = [self._user(ctx + ("\n\n(Older turns of this game were dropped; the move list above is complete.)"
                                  if len(kept) < len(exchanges) else ""))]
        n = len(kept)
        for i, (a, u) in enumerate(kept):
            msgs.append(a)
            if i < n - cfg.full_boards:
                u = self._elide(u)
            msgs.append(u)
        return msgs

    @staticmethod
    def _elide(u: dict) -> dict:
        content = []
        for c in u["content"]:
            if c["type"] == "tool_result" and "Game #" in c["content"]:
                head = c["content"].split("Game #")[0].strip()
                c = dict(c, content=(head + "\n" if head else "") + "[board omitted — superseded by a later board]")
            content.append(c)
        return {"role": "user", "content": content}

    # single-context ablation: one transcript across games, compacted when large
    def _single_messages(self, ctx: str, exchanges: list[tuple[dict, dict]]) -> list[dict]:
        msgs = list(self.single_messages) + [self._user(ctx)]
        for a, u in exchanges:
            msgs += [a, u]
        if len(json.dumps(msgs, default=str)) > self.cfg.compact_chars:
            resp = self._complete("compact", None, P.COMPACT_SYSTEM, msgs + [self._user(
                "Summarise now with write_summary.")], [T_SUMMARY])
            summary = next((tc["args"].get("summary", "") for tc in resp.tool_calls if tc["name"] == "write_summary"),
                           resp.text)
            self.single_messages = [self._user("Summary of everything so far:\n" + summary),
                                    {"role": "assistant", "content": [{"type": "text", "text": "Understood."}],
                                     "raw": None}]
            exchanges.clear()
            msgs = list(self.single_messages) + [self._user(ctx)]
        return msgs

    # --------------------------------------------------------- reflection
    def reflect(self, game_no: int) -> None:
        rec = self.client.game(game_no)
        if not rec.get("ok"):
            return
        gm = rec["game"]
        moves = rec["moves"]
        b = Board(gm["size"], gm["komi"])
        boards = [b.render()]
        for m in moves:
            b.play(coord_to_point(m["coord"], gm["size"]), BLACK if m["color"] == "B" else WHITE)
            boards.append(b.render())
        plans_file = self.mem.root / "transcripts" / f"{game_no:04d}-plans.jsonl"
        plans = "(none)"
        if plans_file.exists():
            lines = plans_file.read_text().strip().splitlines()
            if lines:
                ps = json.loads(lines[-1]).get("plans", [])
                plans = "\n".join(f"{p['move']}: {p['plan']}" for p in ps) or "(none)"
        status = self.client.status()
        vs = status["summary"]["per_tier"].get(gm["opponent"], {})
        scoring = ""
        sc = rec.get("scoring")
        if sc:
            scoring = (f"Score: Black {sc['black_area']} vs White {sc['white_area']} + komi {sc['komi']}; "
                       f"dead stones removed: {', '.join(sc.get('dead_coords', [])) or 'none'}.")
        used = sum(len(i["text"]) + 8 for i in self.mem.playbook())
        system = P.REFLECT_SYSTEM.format(games=self.cfg.games_target, budget=self.cfg.playbook_chars, used=used,
                                         playbook=self.mem.playbook_text(), plan=self.mem.plan(),
                                         opponents=self.mem.opponents())
        user = P.REFLECT_USER.format(
            game_no=game_no, opponent=gm["opponent"], color="Black (X)" if gm["agent_color"] == "B" else "White (O)",
            result=gm["result"], outcome="WON" if gm["winner"] == "agent" else "LOST", reason=gm["end_reason"],
            scoring=scoring, illegal=", ".join(f"{i['coord']} ({i['code']})" for i in rec.get("illegal", [])) or "none",
            moves=" ".join(f"{m['ply']}.{m['color']}{m['coord']}" for m in moves), final_board=boards[-1],
            plans=plans, vs_record=f"{vs.get('wins', 0)}/{vs.get('games', 0)} won" if vs else "first game",
            status=status["text"])
        msgs = [self._user(user)]
        tools = [T_BOARD_AT, T_READ, T_SEARCH, T_SUBMIT]
        for _ in range(self.cfg.reflect_steps):
            resp = self._complete("reflect", game_no, system, msgs, tools)
            msgs.append(resp.as_message())
            results = []
            submitted = None
            for tc in resp.tool_calls:
                a = tc.get("args") or {}
                err = False
                try:
                    if tc["name"] == "board_at":
                        ply = max(0, min(len(moves), int(str(a.get("ply", 0)).strip())))
                        last = f" (last move {ply}.{moves[ply - 1]['color']}{moves[ply - 1]['coord']})" if ply else ""
                        out = f"After move {ply}{last}:\n{boards[ply]}"
                    elif tc["name"] == "read_memory":
                        out = self.mem.read(str(a.get("name", "")))
                    elif tc["name"] == "search_memory":
                        out = self.mem.search(str(a.get("query", "")))
                    elif tc["name"] == "submit_review":
                        submitted = a
                        out = "saved"
                    else:
                        out, err = f"unknown tool {tc['name']}", True
                except Exception as e:
                    out, err = f"tool error: {e}", True
                results.append({"type": "tool_result", "id": tc["id"], "content": out, "is_error": err})
            if submitted is not None:
                self._save_review(game_no, gm, submitted)
                return
            msgs.append(self._user("Call submit_review when you are ready." if not results else "", results))
        self.log(f"reflection on game #{game_no} did not submit; writing a plain journal line")
        self._plain_journal(game_no)

    def _save_review(self, game_no: int, gm: dict, a: dict) -> None:
        outcome = "won" if gm["winner"] == "agent" else "lost"
        self.mem.save_review(game_no, f"# Game {game_no} vs {gm['opponent']} — {gm['result']} ({outcome})\n\n"
                                      f"{a.get('review', '').strip()}\n")
        self.mem.add_journal(game_no, gm["opponent"], gm["agent_color"], gm["result"], outcome,
                             str(a.get("journal_line", "")))
        if a.get("opponent_note"):
            self.mem.add_opponent_note(game_no, gm["opponent"], str(a["opponent_note"]))
        edits = a.get("playbook_edits") or []
        if isinstance(edits, str):
            try:
                edits = json.loads(edits)
            except json.JSONDecodeError:
                edits = [{"op": "add", "text": edits}]
        if isinstance(edits, dict):
            edits = [edits]
        edits = [e if isinstance(e, dict) else {"op": "add", "text": str(e)} for e in edits]
        notes = self.mem.apply_edits(edits, game_no)
        self.mem.log("memory_ops.jsonl", {"game_no": game_no, "phase": "reflect", "ops": notes})

    # ------------------------------------------------------- consolidation
    def consolidate(self, game_no: int) -> None:
        status = self.client.status()
        games = self.client.games(limit=200).get("games", [])
        results = " ".join(f"#{g['game_no']}:{g['opponent']}:{'W' if g['winner'] == 'agent' else 'L'}" for g in games)
        system = P.CONSOLIDATE_SYSTEM.format(games=self.cfg.games_target, window=self.cfg.rating_window,
                                             budget=self.cfg.playbook_chars)
        user = P.CONSOLIDATE_USER.format(played=status["summary"]["games_played"], games=self.cfg.games_target,
                                         status=status["text"], results=results or "(none)",
                                         playbook=self.mem.playbook_text(), plan=self.mem.plan(),
                                         journal=self.mem.journal(tail=60),
                                         reviews=self.mem.recent_reviews(self.cfg.consolidate_every))
        msgs = [self._user(user)]
        tools = [T_READ, T_SEARCH, T_REWRITE]
        for _ in range(8):
            resp = self._complete("consolidate", game_no, system, msgs, tools)
            msgs.append(resp.as_message())
            results_ = []
            done = None
            for tc in resp.tool_calls:
                a = tc.get("args") or {}
                err = False
                try:
                    if tc["name"] == "rewrite_playbook":
                        done = a
                        out = "saved"
                    elif tc["name"] == "read_memory":
                        out = self.mem.read(str(a.get("name", "")))
                    elif tc["name"] == "search_memory":
                        out = self.mem.search(str(a.get("query", "")))
                    else:
                        out, err = f"unknown tool {tc['name']}", True
                except Exception as e:
                    out, err = f"tool error: {e}", True
                results_.append({"type": "tool_result", "id": tc["id"], "content": out, "is_error": err})
            if done is not None:
                items = done.get("items") or []
                if isinstance(items, str):
                    items = [l.strip("-• ").strip() for l in items.splitlines() if l.strip()]
                notes = self.mem.replace_playbook([str(i) for i in items], game_no)
                self.mem.set_plan(str(done.get("plan", "")))
                self.mem.log("memory_ops.jsonl", {"game_no": game_no, "phase": "consolidate", "ops": notes})
                break
            msgs.append(self._user("Call rewrite_playbook when ready." if not results_ else "", results_))
        st = self.mem.state()
        st["last_consolidation"] = game_no
        self.mem.save_state(st)
