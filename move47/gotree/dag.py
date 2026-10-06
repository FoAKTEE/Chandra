"""The position DAG: the explicit, persistent 'cognitive state' of the search.

Nodes are canonical frozen positions; edges are moves (in the parent's
canonical frame).  Transpositions merge automatically because the node key
ignores move order.  Statistics follow the usual graph-MCTS convention:
  * node.n / node.w  — visits and summed value from the node's side-to-move
    perspective (value = win probability in [0, 1]);
  * edge.n           — how often the search went through this edge
    (used for exploration);
  * Q(s, a)          — taken from the child node (1 - child mean), so all
    information about a position is shared by every path that reaches it.

One process (the search orchestrator) writes; any number of readers
(workers' `gtree` tool, the website, analysis scripts) may read concurrently.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

from .position import Position

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    key TEXT PRIMARY KEY,
    pos TEXT NOT NULL,               -- canonical Position as JSON
    n INTEGER NOT NULL DEFAULT 0,
    w REAL NOT NULL DEFAULT 0,       -- summed value, side-to-move perspective
    score_sum REAL NOT NULL DEFAULT 0,  -- summed score estimate (Black minus White), for display
    score_n INTEGER NOT NULL DEFAULT 0,
    static_value REAL,               -- LLM's own (unsearched) evaluation
    static_conf TEXT,
    static_note TEXT,
    plan TEXT,                       -- LLM's plan for the side to move
    expansions INTEGER NOT NULL DEFAULT 0,
    exhausted INTEGER NOT NULL DEFAULT 0,   -- LLM said it has no more candidates
    terminal REAL,                   -- exact value if the game is over here
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    parent TEXT NOT NULL,
    move INTEGER NOT NULL,           -- point in the parent's canonical frame, -1 = pass
    child TEXT NOT NULL,
    child_sym INTEGER NOT NULL,      -- symmetry mapping (parent frame after the move) -> child canonical frame
    prior REAL NOT NULL DEFAULT 0,
    n INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'llm',  -- llm | unconventional | refute | rollout | pool | game | try
    why TEXT,
    added REAL NOT NULL,
    PRIMARY KEY (parent, move)
);
CREATE INDEX IF NOT EXISTS edges_child ON edges(child);
CREATE TABLE IF NOT EXISTS evals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    kind TEXT NOT NULL,              -- static | rollout_end | terminal
    value REAL,
    score REAL,
    conf TEXT,
    worker TEXT,
    job_id INTEGER,
    note TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS evals_key ON evals(key);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    root TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    worker TEXT,
    created REAL NOT NULL,
    started REAL,
    finished REAL,
    result TEXT,
    error TEXT,
    usage TEXT
);
CREATE TABLE IF NOT EXISTS roots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    label TEXT,
    real_sym INTEGER NOT NULL,       -- real orientation -> canonical
    created REAL NOT NULL,
    finished REAL,
    jobs INTEGER NOT NULL DEFAULT 0,
    decision INTEGER,                -- chosen move, canonical frame (-1 pass)
    decision_real TEXT,              -- chosen move as a real-board coordinate
    summary TEXT
);
"""


# when the same move is proposed by several job types, keep the most "deliberate" source
_RANK = {"rollout": 0, "try": 0, "game": 1, "pool": 1, "unconventional": 2, "scout": 2, "more": 3, "refute": 3, "llm": 3}


@dataclass
class Edge:
    parent: str
    move: Optional[int]
    child: str
    child_sym: int
    prior: float
    n: int
    source: str
    why: str


class DAG:
    def __init__(self, path: str, readonly: bool = False):
        self.path = path
        uri = f"file:{path}?mode=ro" if readonly else f"file:{path}"
        self.db = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        if not readonly:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.executescript(SCHEMA)
        self._pos_cache: dict[str, Position] = {}

    # ------------------------------------------------------------ basics
    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def q1(self, sql: str, args: tuple = ()) -> Optional[dict]:
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.db.execute(sql, args).lastrowid or 0

    # ------------------------------------------------------------ nodes
    def ensure(self, pos: Position) -> tuple[str, Position, int]:
        """Insert (if new) the canonical form of pos.  Returns (key, canonical, s)."""
        can, s = pos.canonical()
        key = can.raw_key
        with self.lock:
            if key not in self._pos_cache:
                row = self.db.execute("SELECT key FROM nodes WHERE key=?", (key,)).fetchone()
                if row is None:
                    now = time.time()
                    term = can.terminal_value() if can.terminal else None
                    d = can.to_dict()
                    d["last"] = None
                    self.db.execute("INSERT INTO nodes (key,pos,terminal,created,updated) VALUES (?,?,?,?,?)",
                                    (key, json.dumps(d), term, now, now))
                self._pos_cache[key] = Position.from_dict({**can.to_dict(), "last": None})
        return key, self._pos_cache[key], s

    def position(self, key: str) -> Position:
        if key not in self._pos_cache:
            row = self.q1("SELECT pos FROM nodes WHERE key=?", (key,))
            if row is None:
                raise KeyError(key)
            self._pos_cache[key] = Position.from_dict(json.loads(row["pos"]))
        return self._pos_cache[key]

    def node(self, key: str) -> Optional[dict]:
        return self.q1("SELECT * FROM nodes WHERE key=?", (key,))

    def set_static(self, key: str, value: Optional[float], score: Optional[float], conf: str, note: str,
                   plan: str = "", worker: str = "", job_id: Optional[int] = None) -> None:
        now = time.time()
        with self.lock:
            self.db.execute("UPDATE nodes SET static_value=COALESCE(?, static_value), static_conf=?, static_note=?,"
                            " plan=CASE WHEN ?<>'' THEN ? ELSE plan END, expansions=expansions+1, updated=? WHERE key=?",
                            (value, conf, note[:2000], plan, plan[:1500], now, key))
            self.db.execute("INSERT INTO evals (key,kind,value,score,conf,worker,job_id,note,ts) VALUES (?,?,?,?,?,?,?,?,?)",
                            (key, "static", value, score, conf, worker, job_id, note[:2000], now))

    def add_eval(self, key: str, kind: str, value: Optional[float], score: Optional[float] = None, conf: str = "",
                 worker: str = "", job_id: Optional[int] = None, note: str = "") -> None:
        self.x("INSERT INTO evals (key,kind,value,score,conf,worker,job_id,note,ts) VALUES (?,?,?,?,?,?,?,?,?)",
               (key, kind, value, score, conf, worker, job_id, note[:2000], time.time()))

    def mark_exhausted(self, key: str) -> None:
        self.x("UPDATE nodes SET exhausted=1 WHERE key=?", (key,))

    # ------------------------------------------------------------ edges
    def add_edge(self, parent_key: str, move: Optional[int], prior: float, source: str, why: str = "",
                 keep_higher_prior: bool = True) -> Edge:
        """Add (or update) parent --move--> child.  Computes the child."""
        ppos = self.position(parent_key)
        mv = -1 if move is None else move
        with self.lock:
            row = self.db.execute("SELECT * FROM edges WHERE parent=? AND move=?", (parent_key, mv)).fetchone()
            if row:
                if keep_higher_prior and prior > row["prior"]:
                    src = source if _RANK.get(source, 0) >= _RANK.get(row["source"], 0) else row["source"]
                    self.db.execute("UPDATE edges SET prior=?, source=?, why=COALESCE(NULLIF(?,''), why) "
                                    "WHERE parent=? AND move=?", (prior, src, why[:600], parent_key, mv))
                elif _RANK.get(source, 0) > _RANK.get(row["source"], 0):  # an LLM proposal upgrades a rollout edge
                    self.db.execute("UPDATE edges SET source=?, why=COALESCE(NULLIF(?,''), why) WHERE parent=? AND move=?",
                                    (source, why[:600], parent_key, mv))
                elif why and not row["why"]:
                    self.db.execute("UPDATE edges SET why=? WHERE parent=? AND move=?", (why[:600], parent_key, mv))
                return self.edge(parent_key, move)  # type: ignore[return-value]
            child_pos = ppos.play(move)
            ckey, _, s = self.ensure(child_pos)
            self.db.execute("INSERT INTO edges (parent,move,child,child_sym,prior,source,why,added) VALUES (?,?,?,?,?,?,?,?)",
                            (parent_key, mv, ckey, s, prior, source, why[:600], time.time()))
        return self.edge(parent_key, move)  # type: ignore[return-value]

    def edge(self, parent_key: str, move: Optional[int]) -> Optional[Edge]:
        r = self.q1("SELECT * FROM edges WHERE parent=? AND move=?", (parent_key, -1 if move is None else move))
        return self._edge(r) if r else None

    @staticmethod
    def _edge(r: dict) -> Edge:
        return Edge(r["parent"], None if r["move"] < 0 else r["move"], r["child"], r["child_sym"], r["prior"],
                    r["n"], r["source"], r["why"] or "")

    def edges(self, key: str) -> list[Edge]:
        return [self._edge(r) for r in self.q("SELECT * FROM edges WHERE parent=? ORDER BY prior DESC, move", (key,))]

    def normalize_priors(self, key: str) -> None:
        rows = self.q("SELECT move, prior FROM edges WHERE parent=?", (key,))
        tot = sum(r["prior"] for r in rows)
        if tot > 0:
            with self.lock:
                for r in rows:
                    self.db.execute("UPDATE edges SET prior=? WHERE parent=? AND move=?", (r["prior"] / tot, key, r["move"]))

    # ------------------------------------------------------------ backup
    def backup(self, path: list[tuple[str, Optional[int]]], leaf_key: str, value: float,
               score: Optional[float] = None) -> None:
        """path: [(node_key, move_taken_from_it), ...] from root to the leaf's parent.
        value: from the leaf's side-to-move perspective."""
        keys = [k for k, _ in path] + [leaf_key]
        now = time.time()
        with self.lock:
            self.db.execute("BEGIN")
            try:
                v = value
                for i in range(len(keys) - 1, -1, -1):
                    k = keys[i]
                    if score is None:
                        self.db.execute("UPDATE nodes SET n=n+1, w=w+?, updated=? WHERE key=?", (v, now, k))
                    else:
                        self.db.execute("UPDATE nodes SET n=n+1, w=w+?, score_sum=score_sum+?, score_n=score_n+1,"
                                        " updated=? WHERE key=?", (v, score, now, k))
                    if i < len(keys) - 1:
                        mv = path[i][1]
                        self.db.execute("UPDATE edges SET n=n+1 WHERE parent=? AND move=?",
                                        (k, -1 if mv is None else mv))
                    v = 1.0 - v
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------ views
    def child_stats(self, key: str) -> list[dict]:
        """Edges of key joined with child node stats, Q from the parent's view."""
        rows = self.q("SELECT e.*, c.n AS cn, c.w AS cw, c.static_value AS cstatic, c.terminal AS cterm, "
                      "c.score_sum AS cscore, c.score_n AS cscore_n "
                      "FROM edges e JOIN nodes c ON c.key=e.child WHERE e.parent=?", (key,))
        out = []
        for r in rows:
            q = None
            if r["cterm"] is not None:
                q = 1.0 - r["cterm"]
            elif r["cn"]:
                q = 1.0 - r["cw"] / r["cn"]
            out.append({"move": None if r["move"] < 0 else r["move"], "child": r["child"], "child_sym": r["child_sym"],
                        "prior": r["prior"], "n": r["n"], "child_n": r["cn"], "q": q, "source": r["source"],
                        "why": r["why"] or "", "static_child": r["cstatic"],
                        "score": (r["cscore"] / r["cscore_n"]) if r["cscore_n"] else None})
        return out

    def principal_variation(self, key: str, max_len: int = 12) -> list[tuple[str, Optional[int], int]]:
        """[(node_key, move_in_that_frame, child_sym)] following most-visited edges."""
        pv, seen = [], set()
        while key not in seen and len(pv) < max_len:
            seen.add(key)
            st = [c for c in self.child_stats(key) if c["n"] > 0]
            if not st:
                break
            best = max(st, key=lambda c: (c["n"], c["q"] or 0))
            pv.append((key, best["move"], best["child_sym"]))
            key = best["child"]
        return pv

    def stats(self) -> dict:
        r = self.q1("SELECT (SELECT COUNT(*) FROM nodes) AS nodes, (SELECT COUNT(*) FROM edges) AS edges, "
                    "(SELECT COUNT(*) FROM evals) AS evals, (SELECT COUNT(*) FROM jobs) AS jobs")
        return r or {}
