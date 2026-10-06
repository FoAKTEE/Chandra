"""Thread-safe client for the KataGo JSON analysis engine.

One KataGo process serves every opponent tier, the referee and the reviewer.
Queries are written to stdin as JSON lines; responses are matched by id.
All values returned by `analyze()` are normalised to BLACK's perspective
(the config uses reportAnalysisWinratesAs = BLACK).
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional

from .board import BLACK, Board, point_to_coord

log = logging.getLogger("goarena.katago")


@dataclass
class KataGoConfig:
    binary: str
    model: str
    config: str
    extra_args: tuple[str, ...] = ()


class KataGoError(RuntimeError):
    pass


class KataGo:
    def __init__(self, cfg: KataGoConfig):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._events: dict[str, threading.Event] = {}
        self._ids = itertools.count(1)
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stderr_tail: list[str] = []
        self.start()

    # -- process management ----------------------------------------------
    def start(self) -> None:
        for path in (self.cfg.binary, self.cfg.model, self.cfg.config):
            if not os.path.exists(path):
                raise KataGoError(f"KataGo file not found: {path}")
        cmd = [self.cfg.binary, "analysis", "-config", self.cfg.config, "-model", self.cfg.model,
               "-override-config", "reportAnalysisWinratesAs=BLACK", *self.cfg.extra_args]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, bufsize=1)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

    def _stderr_loop(self) -> None:
        assert self._proc and self._proc.stderr
        for line in self._proc.stderr:
            self._stderr_tail = (self._stderr_tail + [line.rstrip()])[-50:]

    def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            qid = msg.get("id")
            if qid is None:
                continue
            if msg.get("isDuringSearch"):
                continue
            if "warning" in msg and "error" not in msg:
                # e.g. an ignored query field: informational, the real answer follows
                log.warning("KataGo warning for %s: %s (%s)", qid, msg.get("warning"), msg.get("field"))
                continue
            with self._lock:
                if qid in self._pending:
                    bucket = self._pending[qid]
                    if "error" in msg:
                        bucket["error"] = msg["error"]
                        self._events[qid].set()
                        continue
                    bucket["responses"][msg.get("turnNumber", -1)] = msg
                    if len(bucket["responses"]) >= bucket["expected"]:
                        self._events[qid].set()
        # process died: wake everybody up
        with self._lock:
            for qid, ev in self._events.items():
                self._pending[qid]["error"] = "KataGo process exited: " + " | ".join(self._stderr_tail[-5:])
                ev.set()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()  # type: ignore[union-attr]
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()

    # -- queries -----------------------------------------------------------
    def query(self, payload: dict, expected: int = 1, timeout: float = 600.0) -> dict[int, dict]:
        if not self.alive():
            self.start()
        qid = f"q{next(self._ids)}"
        payload = dict(payload, id=qid)
        ev = threading.Event()
        with self._lock:
            self._pending[qid] = {"responses": {}, "expected": expected}
            self._events[qid] = ev
            assert self._proc and self._proc.stdin
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
        ok = ev.wait(timeout)
        with self._lock:
            bucket = self._pending.pop(qid)
            self._events.pop(qid, None)
        if not ok:
            raise KataGoError(f"KataGo query {qid} timed out")
        if "error" in bucket:
            raise KataGoError(str(bucket["error"]))
        return bucket["responses"]

    @staticmethod
    def _moves(board: Board) -> list[list[str]]:
        return [["B" if m.color == BLACK else "W", point_to_coord(m.point, board.size)] for m in board.moves]

    def analyze(self, board: Board, visits: int, *, policy: bool = False, ownership: bool = False,
                analyze_turns: Optional[list[int]] = None, priority: int = 0,
                override_settings: Optional[dict] = None) -> dict | dict[int, dict]:
        payload = {
            "moves": self._moves(board),
            "rules": "chinese",
            "komi": board.komi,
            "boardXSize": board.size,
            "boardYSize": board.size,
            "maxVisits": max(1, int(visits)),
            "includePolicy": policy,
            "includeOwnership": ownership,
            "priority": priority,
        }
        if override_settings:
            payload["overrideSettings"] = dict(override_settings)
        if analyze_turns is not None:
            payload["analyzeTurns"] = analyze_turns
            return self.query(payload, expected=len(analyze_turns))
        res = self.query(payload)
        return next(iter(res.values()))
