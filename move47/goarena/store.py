"""SQLite persistence.  The database is the single source of truth: an
arena restart rebuilds active games by replaying their stored moves."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    harness TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',      -- active | paused | complete | abandoned
    target_games INTEGER NOT NULL DEFAULT 200,
    config TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    game_no INTEGER NOT NULL,
    opponent TEXT NOT NULL,
    opponent_elo REAL NOT NULL DEFAULT 0,
    agent_color TEXT NOT NULL,                 -- B | W
    size INTEGER NOT NULL,
    komi REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',      -- active | finished
    result TEXT,                               -- SGF RE, e.g. B+3.5, W+R
    winner TEXT,                               -- agent | opponent
    end_reason TEXT,                           -- score | resign | move_cap | timeout | illegal_limit | adjudicated | abandoned
    margin REAL,
    agent_score REAL,                          -- 1 win, 0 loss
    moves_count INTEGER NOT NULL DEFAULT 0,
    illegal_count INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    last_activity REAL NOT NULL,
    ended_at REAL,
    sgf TEXT,
    scoring TEXT,
    review TEXT,
    review_summary TEXT,
    UNIQUE(run_id, game_no)
);
CREATE INDEX IF NOT EXISTS games_run ON games(run_id, game_no);
CREATE TABLE IF NOT EXISTS moves (
    game_id INTEGER NOT NULL REFERENCES games(id),
    ply INTEGER NOT NULL,
    color TEXT NOT NULL,
    coord TEXT NOT NULL,
    actor TEXT NOT NULL,                       -- agent | opponent
    ts REAL NOT NULL,
    think_ms INTEGER,
    captured INTEGER NOT NULL DEFAULT 0,
    info TEXT,
    PRIMARY KEY (game_id, ply)
);
CREATE TABLE IF NOT EXISTS illegal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id),
    ply INTEGER NOT NULL,
    coord TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id, id);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    # -- helpers -----------------------------------------------------------
    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def q1(self, sql: str, args: tuple = ()) -> Optional[dict]:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self.db.execute(sql, args)
            return cur.lastrowid or 0

    def tx(self):
        return _Tx(self)

    # -- runs --------------------------------------------------------------
    def create_run(self, run_id: str, name: str, token: str, *, model: str = "", harness: str = "",
                   reasoning: str = "", context: str = "", notes: str = "", target_games: int = 200,
                   config: Optional[dict] = None) -> dict:
        self.x("INSERT INTO runs (id,name,model,harness,reasoning,context,notes,token,target_games,config,created_at)"
               " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (run_id, name, model, harness, reasoning, context, notes, token, target_games,
                json.dumps(config or {}), time.time()))
        return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> Optional[dict]:
        r = self.q1("SELECT * FROM runs WHERE id=?", (run_id,))
        if r:
            r["config"] = json.loads(r["config"] or "{}")
        return r

    def run_by_token(self, token: str) -> Optional[dict]:
        r = self.q1("SELECT * FROM runs WHERE token=?", (token,))
        if r:
            r["config"] = json.loads(r["config"] or "{}")
        return r

    def list_runs(self) -> list[dict]:
        rows = self.q("SELECT * FROM runs ORDER BY created_at")
        for r in rows:
            r["config"] = json.loads(r["config"] or "{}")
        return rows

    def set_run_status(self, run_id: str, status: str) -> None:
        fin = time.time() if status in ("complete", "abandoned") else None
        self.x("UPDATE runs SET status=?, finished_at=COALESCE(?, finished_at) WHERE id=?", (status, fin, run_id))

    # -- games -------------------------------------------------------------
    def active_game(self, run_id: str) -> Optional[dict]:
        return self.q1("SELECT * FROM games WHERE run_id=? AND status='active' ORDER BY id DESC LIMIT 1", (run_id,))

    def all_active_games(self) -> list[dict]:
        return self.q("SELECT * FROM games WHERE status='active'")

    def finished_games(self, run_id: str) -> list[dict]:
        return self.q("SELECT * FROM games WHERE run_id=? AND status='finished' ORDER BY game_no", (run_id,))

    def game(self, game_id: int) -> Optional[dict]:
        return self.q1("SELECT * FROM games WHERE id=?", (game_id,))

    def game_moves(self, game_id: int) -> list[dict]:
        return self.q("SELECT * FROM moves WHERE game_id=? ORDER BY ply", (game_id,))

    def game_illegal(self, game_id: int) -> list[dict]:
        return self.q("SELECT ply, coord, code, message, ts FROM illegal WHERE game_id=? ORDER BY id", (game_id,))

    def next_game_no(self, run_id: str) -> int:
        r = self.q1("SELECT COALESCE(MAX(game_no),0) AS n FROM games WHERE run_id=?", (run_id,))
        return int(r["n"]) + 1 if r else 1

    def event(self, run_id: str, kind: str, data: Any) -> None:
        self.x("INSERT INTO events (run_id, ts, kind, data) VALUES (?,?,?,?)",
               (run_id, time.time(), kind, json.dumps(data)))

    def events_since(self, after_id: int, limit: int = 500, run_id: Optional[str] = None) -> list[dict]:
        if run_id:
            rows = self.q("SELECT * FROM events WHERE id>? AND run_id=? ORDER BY id LIMIT ?", (after_id, run_id, limit))
        else:
            rows = self.q("SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (after_id, limit))
        for r in rows:
            r["data"] = json.loads(r["data"])
        return rows


class _Tx:
    def __init__(self, store: Store):
        self.s = store

    def __enter__(self):
        self.s._lock.acquire()
        self.s.db.execute("BEGIN")
        return self.s

    def __exit__(self, et, ev, tb):
        try:
            self.s.db.execute("ROLLBACK" if et else "COMMIT")
        finally:
            self.s._lock.release()
        return False
