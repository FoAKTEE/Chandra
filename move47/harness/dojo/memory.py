"""Dojo long-term memory: plain files in the workspace so humans (and other
harnesses) can inspect them.

  dojo/playbook.json   curated principles, hard size budget (always in context)
  dojo/plan.md         current training plan / curriculum (always in context)
  dojo/opponents.md    notes about opponent tiers (always in context, bounded)
  dojo/journal.md      one line per game (tail in context)
  dojo/reviews/NNNN.md full post-game reviews (searchable, never bulk-loaded)
  dojo/state.json      harness bookkeeping
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional


class Memory:
    def __init__(self, root: Path, playbook_chars: int = 6000, opponents_chars: int = 2500,
                 plan_chars: int = 1500, journal_tail: int = 30):
        self.root = root / "dojo"
        (self.root / "reviews").mkdir(parents=True, exist_ok=True)
        (self.root / "transcripts").mkdir(parents=True, exist_ok=True)
        self.playbook_chars, self.opponents_chars = playbook_chars, opponents_chars
        self.plan_chars, self.journal_tail = plan_chars, journal_tail

    # -- state -------------------------------------------------------------
    def state(self) -> dict:
        p = self.root / "state.json"
        return json.loads(p.read_text()) if p.exists() else {"games_reflected": [], "last_consolidation": 0,
                                                              "next_item_id": 1}

    def save_state(self, st: dict) -> None:
        tmp = self.root / "state.json.tmp"
        tmp.write_text(json.dumps(st, indent=2))
        tmp.replace(self.root / "state.json")

    # -- playbook ----------------------------------------------------------
    def playbook(self) -> list[dict]:
        p = self.root / "playbook.json"
        return json.loads(p.read_text()) if p.exists() else []

    def save_playbook(self, items: list[dict]) -> None:
        (self.root / "playbook.json").write_text(json.dumps(items, indent=2, ensure_ascii=False))
        md = "# Playbook\n\n" + "\n".join(f"- [P{i['id']}] {i['text']}" for i in items) + "\n"
        (self.root / "playbook.md").write_text(md)

    def playbook_text(self) -> str:
        items = self.playbook()
        if not items:
            return "(empty — you have not written any lessons yet)"
        return "\n".join(f"[P{i['id']}] {i['text']}" for i in items)

    def apply_edits(self, edits: list[dict], game_no: Optional[int] = None) -> list[str]:
        """Apply add/update/delete edits.  Returns human-readable notes,
        including budget enforcement messages."""
        st = self.state()
        items = self.playbook()
        notes = []
        by_id = {i["id"]: i for i in items}
        for e in edits or []:
            if not isinstance(e, dict):
                e = {"op": "add", "text": str(e)}
            op = str(e.get("op") or "").lower()
            iid = e.get("id")
            if isinstance(iid, str):
                iid = int(re.sub(r"\D", "", iid) or 0)
            text = str(e.get("text") or "").strip()
            if op == "add" and text:
                item = {"id": st["next_item_id"], "text": text[:600], "added_game": game_no, "updated_game": game_no}
                st["next_item_id"] += 1
                items.append(item)
                by_id[item["id"]] = item
                notes.append(f"added P{item['id']}")
            elif op == "update" and iid in by_id and text:
                by_id[iid]["text"] = text[:600]
                by_id[iid]["updated_game"] = game_no
                notes.append(f"updated P{iid}")
            elif op == "delete" and iid in by_id:
                items = [i for i in items if i["id"] != iid]
                by_id.pop(iid)
                notes.append(f"deleted P{iid}")
            else:
                notes.append(f"ignored edit {e!r}")
        # budget: drop the least recently touched items until we fit
        def size(its):
            return sum(len(i["text"]) + 8 for i in its)
        while items and size(items) > self.playbook_chars:
            victim = min(items, key=lambda i: (i.get("updated_game") or 0, i["id"]))
            items.remove(victim)
            notes.append(f"budget: dropped P{victim['id']} (least recently updated)")
        self.save_playbook(items)
        self.save_state(st)
        return notes

    def replace_playbook(self, texts: list[str], game_no: Optional[int]) -> list[str]:
        st = self.state()
        items = []
        for t in texts:
            t = (t or "").strip()
            if t:
                items.append({"id": st["next_item_id"], "text": t[:600], "added_game": game_no, "updated_game": game_no})
                st["next_item_id"] += 1
        self.save_state(st)
        self.save_playbook(items)
        return self.apply_edits([], game_no)  # enforces the size budget

    # -- small text files ----------------------------------------------------
    def _read(self, name: str) -> str:
        p = self.root / name
        return p.read_text() if p.exists() else ""

    def plan(self) -> str:
        return self._read("plan.md").strip() or "(no plan yet)"

    def set_plan(self, text: str) -> None:
        (self.root / "plan.md").write_text(text.strip()[: self.plan_chars] + "\n")

    def opponents(self) -> str:
        return self._read("opponents.md").strip() or "(no notes yet)"

    def add_opponent_note(self, game_no: int, opponent: str, note: str) -> None:
        if not note.strip():
            return
        lines = [l for l in self._read("opponents.md").splitlines() if l.strip()]
        lines.append(f"- [{opponent}, game {game_no}] {note.strip()[:300]}")
        while lines and sum(len(l) + 1 for l in lines) > self.opponents_chars:
            lines.pop(0)
        (self.root / "opponents.md").write_text("\n".join(lines) + "\n")

    def journal(self, tail: Optional[int] = None) -> str:
        lines = [l for l in self._read("journal.md").splitlines() if l.strip()]
        n = self.journal_tail if tail is None else tail
        return "\n".join(lines[-n:]) if lines else "(empty)"

    def add_journal(self, game_no: int, opponent: str, color: str, result: str, outcome: str, line: str) -> None:
        # idempotent: re-processing a game after a crash replaces its line instead of duplicating it
        lines = [l for l in self._read("journal.md").splitlines() if l.strip() and not l.startswith(f"#{game_no} ")]
        lines.append(f"#{game_no} vs {opponent} as {color}: {result} ({outcome}) — {str(line).strip()[:240]}")
        (self.root / "journal.md").write_text("\n".join(lines) + "\n")

    def save_review(self, game_no: int, text: str) -> Path:
        p = self.root / "reviews" / f"{game_no:04d}.md"
        p.write_text(text)
        return p

    def recent_reviews(self, k: int, max_chars: int = 1500) -> str:
        files = sorted((self.root / "reviews").glob("*.md"))[-k:]
        return "\n\n".join(f"### Review {f.stem}\n{f.read_text()[:max_chars]}" for f in files) or "(none)"

    def search(self, query: str, limit: int = 8) -> str:
        words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
        if not words:
            return "(empty query)"
        hits = []
        files = [self.root / "journal.md", self.root / "opponents.md"] + sorted((self.root / "reviews").glob("*.md"))
        for f in files:
            if not f.exists():
                continue
            for para in re.split(r"\n\s*\n|\n(?=#)", f.read_text()):
                score = sum(para.lower().count(w) for w in words)
                if score:
                    hits.append((score, f.name, para.strip()[:500]))
        hits.sort(key=lambda h: -h[0])
        return "\n\n".join(f"[{name}] {para}" for _, name, para in hits[:limit]) or "(no matches)"

    def read(self, name: str) -> str:
        name = name.strip().lstrip("/")
        allowed = {"playbook": "playbook.md", "plan": "plan.md", "opponents": "opponents.md", "journal": "journal.md"}
        if name in allowed:
            return self._read(allowed[name]) or "(empty)"
        m = re.fullmatch(r"(?:reviews?/)?(\d+)(?:\.md)?", name)
        if m:
            return self._read(f"reviews/{int(m.group(1)):04d}.md") or "(no such review)"
        return "unknown memory file; use playbook, plan, opponents, journal or a game number for its review"

    def log(self, name: str, record: dict) -> None:
        record = dict(record, ts=time.time())
        with open(self.root / name, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
