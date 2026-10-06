"""Long-term memory above the position DAG: the "joseki book" of the system.

Three layers (see TREE.md §4):
  L0  position DAG (dag.py)            exact, episodic: what was searched
  L1  shape lessons (this file)        local, keyed by a canonical pattern
                                        around a point; transfer across games
  L2  concept DAG (this file)          global principles linked by
                                        generalizes / refines / contradicts

Pattern keys are colour-relative ('M' = side to move, 'T' = opponent) and
canonical under the 8 symmetries of the local window, so a lesson learned
as Black in the lower left also fires as White in the upper right.
Writes are prediction-error gated (only surprising search results become
lessons) — the abstraction step that keeps memory small.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from typing import Iterable, Optional

from .position import EMPTY, Position, coord, point

SCHEMA = """
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,             -- local | global
    pattern TEXT,                    -- canonical local pattern (local lessons)
    pattern_coarse TEXT,             -- smaller window, for fuzzy matches
    phase TEXT,                      -- opening | middlegame | endgame | any
    size INTEGER,
    text TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '[]',   -- [{"key":..,"move":..,"note":..}]
    support INTEGER NOT NULL DEFAULT 1,
    hits INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active', -- active | retired
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS lessons_pattern ON lessons(pattern);
CREATE INDEX IF NOT EXISTS lessons_coarse ON lessons(pattern_coarse);
CREATE TABLE IF NOT EXISTS lesson_links (
    parent INTEGER NOT NULL,
    child INTEGER NOT NULL,
    rel TEXT NOT NULL,               -- generalizes | refines | contradicts | example_of
    PRIMARY KEY (parent, child, rel)
);
"""


def local_pattern(pos: Position, p: int, radius: int) -> str:
    """Canonical colour-relative window around p ('#' = off board)."""
    s = pos.size
    y0, x0 = divmod(p, s)
    me = pos.to_play
    k = 2 * radius + 1
    grid = []
    for dy in range(-radius, radius + 1):
        row = []
        for dx in range(-radius, radius + 1):
            y, x = y0 + dy, x0 + dx
            if not (0 <= y < s and 0 <= x < s):
                row.append("#")
            else:
                c = pos.cells[y * s + x]
                row.append("." if c == EMPTY else ("M" if c == me else "T"))
        grid.append(row)
    best = None
    for t in range(8):
        g = [[""] * k for _ in range(k)]
        for y in range(k):
            for x in range(k):
                xx, yy = x, y
                if t & 4:
                    xx, yy = yy, xx
                if t & 1:
                    xx = k - 1 - xx
                if t & 2:
                    yy = k - 1 - yy
                g[yy][xx] = grid[y][x]
        sig = "/".join("".join(r) for r in g)
        if best is None or sig < best:
            best = sig
    return f"r{radius}:{best}"


class Memory:
    def __init__(self, path: str, readonly: bool = False):
        uri = f"file:{path}?mode=ro" if readonly else f"file:{path}"
        self.db = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        if not readonly:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.db.execute(sql, args).lastrowid or 0

    # ------------------------------------------------------------ writes
    def add_local(self, pos: Position, at: int, text: str, evidence: dict) -> int:
        pat, coarse = local_pattern(pos, at, 3), local_pattern(pos, at, 2)
        same = self.q("SELECT * FROM lessons WHERE pattern=? AND status='active'", (pat,))
        now = time.time()
        if same:  # same shape: merge evidence, keep the newer wording
            l = same[0]
            ev = json.loads(l["evidence"])[-9:] + [evidence]
            self.x("UPDATE lessons SET text=?, evidence=?, support=support+1, updated=? WHERE id=?",
                   (text[:800], json.dumps(ev), now, l["id"]))
            return l["id"]
        return self.x("INSERT INTO lessons (scope,pattern,pattern_coarse,phase,size,text,evidence,created,updated) "
                      "VALUES ('local',?,?,?,?,?,?,?,?)",
                      (pat, coarse, pos.phase(), pos.size, text[:800], json.dumps([evidence]), now, now))

    def add_global(self, text: str, phase: str = "any", size: Optional[int] = None,
                   evidence: Optional[dict] = None) -> int:
        now = time.time()
        return self.x("INSERT INTO lessons (scope,phase,size,text,evidence,created,updated) VALUES ('global',?,?,?,?,?,?)",
                      (phase, size, text[:800], json.dumps([evidence] if evidence else []), now, now))

    # A stored link (parent, child, rel) reads "child <rel> parent":
    #   specializes  the child is a special case of the parent (the parent generalizes it)
    #   refines      the child sharpens the parent
    #   example_of   the child is a concrete instance of the parent
    #   contradicts  the child disagrees with the parent (both stay; the link warns readers)
    RELS = ("specializes", "refines", "example_of", "contradicts")

    def _active(self, i: int) -> bool:
        return bool(self.q("SELECT 1 FROM lessons WHERE id=? AND status='active'", (i,)))

    def link(self, parent: int, child: int, rel: str) -> bool:
        if rel not in self.RELS:
            raise ValueError(f"bad relation {rel}")
        if parent == child or not (self._active(parent) and self._active(child)):
            return False
        self.x("INSERT OR IGNORE INTO lesson_links (parent, child, rel) VALUES (?,?,?)", (parent, child, rel))
        return True

    def relate(self, new_id: int, other_id: int, rel: str) -> bool:
        """Relation as an LLM states it: `new <rel> other`, rel in generalizes|refines|contradicts|example_of."""
        if rel == "generalizes":
            return self.link(new_id, other_id, "specializes")
        if rel in ("refines", "contradicts", "example_of"):
            return self.link(other_id, new_id, rel)
        return False

    def retire(self, lesson_id: int) -> None:
        self.x("UPDATE lessons SET status='retired', updated=? WHERE id=?", (time.time(), lesson_id))

    # ------------------------------------------------------------ reads
    def for_points(self, pos: Position, points: Iterable[int], limit: int = 8) -> list[tuple[int, dict, str]]:
        """Local lessons whose pattern matches around the given points.
        Returns [(point, lesson, 'exact'|'similar')]."""
        out, seen = [], set()
        for p in points:
            if p is None:
                continue
            exact = local_pattern(pos, p, 3)
            for l in self.q("SELECT * FROM lessons WHERE pattern=? AND status='active' ORDER BY support DESC LIMIT 3",
                            (exact,)):
                if l["id"] not in seen:
                    seen.add(l["id"])
                    out.append((p, l, "exact"))
            coarse = local_pattern(pos, p, 2)
            for l in self.q("SELECT * FROM lessons WHERE pattern_coarse=? AND status='active' "
                            "ORDER BY support DESC LIMIT 2", (coarse,)):
                if l["id"] not in seen:
                    seen.add(l["id"])
                    out.append((p, l, "similar"))
            if len(out) >= limit:
                break
        if out:
            with self.lock:
                for _, l, _ in out:
                    self.db.execute("UPDATE lessons SET hits=hits+1 WHERE id=?", (l["id"],))
        return out[:limit]

    def global_lessons(self, pos: Position, limit: int = 8) -> list[dict]:
        return self.q("SELECT * FROM lessons WHERE scope='global' AND status='active' AND (phase IN (?, 'any')) "
                      "AND (size IS NULL OR size=?) ORDER BY support DESC, updated DESC LIMIT ?",
                      (pos.phase(), pos.size, limit))

    def search(self, query: str, limit: int = 10) -> list[dict]:
        words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
        rows = self.q("SELECT * FROM lessons WHERE status='active'")
        scored = []
        for r in rows:
            t = r["text"].lower()
            s = sum(t.count(w) for w in words)
            if s:
                scored.append((s, r))
        scored.sort(key=lambda x: (-x[0], -x[1]["support"]))
        return [r for _, r in scored[:limit]]

    def briefing(self, pos: Position, points: Iterable[int], budget_chars: int = 2500) -> str:
        """Memory section for a job prompt, within a character budget."""
        parts = []
        loc = self.for_points(pos, points)
        if loc:
            parts.append("Shape lessons that match this position (from earlier searches):")
            for p, l, kind in loc:
                parts.append(f"  [L{l['id']}] near {coord(p, pos.size)} ({kind} shape, seen {l['support']}x): {l['text']}")
        gl = self.global_lessons(pos)
        if gl:
            parts.append("Principles (concept memory):")
            for l in gl:
                parts.append(f"  [G{l['id']}] {l['text']}")
        txt = "\n".join(parts)
        return txt[:budget_chars] if txt else "(no stored lessons apply yet)"

    def listing(self, limit: int = 300) -> str:
        """All active lessons with ids, support and existing links (for consolidation jobs)."""
        rows = self.q("SELECT * FROM lessons WHERE status='active' ORDER BY support DESC, id LIMIT ?", (limit,))
        scope = {r["id"]: r["scope"] for r in self.q("SELECT id, scope FROM lessons")}
        tag_of = lambda i: f"{'G' if scope.get(i) == 'global' else 'L'}{i}"  # noqa: E731
        by_child: dict[int, list[str]] = {}
        for l in self.q("SELECT * FROM lesson_links"):
            by_child.setdefault(l["child"], []).append(f"this {l['rel'].replace('_', ' ')} {tag_of(l['parent'])}")
        out = []
        for r in rows:
            tag = tag_of(r["id"])
            extra = f" ({'; '.join(by_child[r['id']])})" if r["id"] in by_child else ""
            out.append(f"[{tag}] support={r['support']} hits={r['hits']} phase={r['phase']}: {r['text']}{extra}")
        return "\n".join(out) or "(no lessons)"

    def apply_consolidation(self, res: dict) -> list[str]:
        def num(tag: str) -> Optional[int]:
            try:
                return int(tag[1:])
            except (ValueError, IndexError):
                return None
        notes = []
        for m in res.get("merge", []):
            keep = num(m["keep"])
            if keep is None:
                continue
            if m.get("text"):
                self.x("UPDATE lessons SET text=?, updated=? WHERE id=?", (m["text"], time.time(), keep))
            for t in m["retire"]:
                i = num(t)
                if i is not None and i != keep:
                    sup = self.q("SELECT support FROM lessons WHERE id=?", (i,))
                    self.x("UPDATE lessons SET support=support+? WHERE id=?", (sup[0]["support"] if sup else 0, keep))
                    self.retire(i)
                    self.x("UPDATE OR IGNORE lesson_links SET parent=? WHERE parent=?", (keep, i))
                    self.x("UPDATE OR IGNORE lesson_links SET child=? WHERE child=?", (keep, i))
                    self.x("DELETE FROM lesson_links WHERE parent=? OR child=?", (i, i))   # leftovers (duplicates)
                    self.x("DELETE FROM lesson_links WHERE parent=child")
                    notes.append(f"merged {t} into {m['keep']}")
        for c in res.get("concepts", []):
            cid = self.add_global(c["text"], "any")
            for ch in c["children"]:
                i = num(ch)
                if i is not None:
                    self.link(cid, i, "specializes")
            notes.append(f"concept G{cid} over {', '.join(c['children'])}")
        for c in res.get("contradictions", []):
            a, b = num(c["a"]), num(c["b"])
            if a is not None and b is not None and self.link(a, b, "contradicts"):
                notes.append(f"{c['b']} contradicts {c['a']}")
        for t in res.get("retire", []):
            i = num(t)
            if i is not None:
                self.retire(i)
                notes.append(f"retired {t}")
        return notes

    def export_markdown(self) -> str:
        """Readable dump: the concept DAG as a forest (shared children repeat under each parent),
        then any lesson not reachable from a root (cycles), then the shape lessons."""
        rows = {r["id"]: r for r in self.q("SELECT * FROM lessons WHERE status='active'")}
        links = [l for l in self.q("SELECT * FROM lesson_links") if l["parent"] in rows and l["child"] in rows
                 and l["parent"] != l["child"]]
        children: dict[int, list[tuple[int, str]]] = {}
        has_parent: set[int] = set()
        for l in links:
            children.setdefault(l["parent"], []).append((l["child"], l["rel"]))
            has_parent.add(l["child"])
        out = ["# Lessons", "", "## Concepts (child lines read: this <relation> its parent)"]
        shown: set[int] = set()

        def tag(i: int) -> str:
            return f"{'G' if rows[i]['scope'] == 'global' else 'L'}{i}"

        def walk(i: int, depth: int, rel: str, path: frozenset) -> None:
            shown.add(i)
            r = rows[i]
            out.append(f"{'  ' * depth}- [{tag(i)}]{' (' + rel.replace('_', ' ') + ')' if rel else ''} {r['text']}")
            for c, rl in children.get(i, []):
                if c in path:
                    out.append(f"{'  ' * (depth + 1)}- [{tag(c)}] ({rl}) … (cycle)")
                    continue
                walk(c, depth + 1, rl, path | {c})

        for i, r in rows.items():
            if r["scope"] == "global" and i not in has_parent:
                walk(i, 0, "", frozenset({i}))
        for i, r in rows.items():  # globals only reachable through cycles or local parents
            if r["scope"] == "global" and i not in shown:
                walk(i, 0, "", frozenset({i}))
        out += ["", "## Shape lessons"]
        for i, r in rows.items():
            if r["scope"] == "local":
                out.append(f"- [{tag(i)}] (support {r['support']}, {r['phase']}) {r['text']}")
        return "\n".join(out) + "\n"


def parse_point(text: str, size: int) -> Optional[int]:
    try:
        return point(text, size)
    except Exception:
        return None
