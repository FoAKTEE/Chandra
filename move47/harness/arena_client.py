"""Minimal HTTP client for the arena (agent scope + admin scope)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Optional


class ArenaClient:
    def __init__(self, url: str, token: str = "", admin_token: str = "", timeout: float = 900):
        self.url, self.token, self.admin_token, self.timeout = url.rstrip("/"), token, admin_token, timeout

    def _req(self, method: str, path: str, body: Optional[dict] = None, admin: bool = False,
             raw: bool = False, retries: int = 5):
        tok = self.admin_token if admin else self.token
        data = json.dumps(body).encode() if body is not None else None
        delay = 1.0
        for attempt in range(retries):
            req = urllib.request.Request(self.url + path, data=data, method=method,
                                         headers={"Authorization": f"Bearer {tok}",
                                                  "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    payload = r.read().decode()
                break
            except urllib.error.HTTPError as e:
                payload = e.read().decode()
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if attempt == retries - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        return payload if raw else json.loads(payload)

    # agent scope
    def rules(self):
        return self._req("GET", "/api/agent/rules")

    def opponents(self):
        return self._req("GET", "/api/agent/opponents")

    def status(self):
        return self._req("GET", "/api/agent/status")

    def board(self):
        return self._req("GET", "/api/agent/board")

    def new_game(self, opponent: str, color: Optional[str] = None):
        return self._req("POST", "/api/agent/new", {"opponent": opponent, "color": color})

    def play(self, move: str, retries: int = 5):
        """retries=1: a transport failure raises at once instead of resending the move (the first
        request may have been played; gotree.play then fetches the board)."""
        return self._req("POST", "/api/agent/play", {"move": move}, retries=retries)

    def resign(self):
        return self._req("POST", "/api/agent/resign", {})

    def games(self, limit: int = 50):
        return self._req("GET", f"/api/agent/games?limit={limit}")

    def game(self, game_no: int):
        return self._req("GET", f"/api/agent/games/{game_no}")

    # admin scope
    def create_run(self, **kw):
        return self._req("POST", "/api/admin/runs", kw, admin=True)

    def admin_runs(self):
        return self._req("GET", "/api/admin/runs", admin=True)

    def set_status(self, run_id: str, status: str):
        return self._req("POST", f"/api/admin/runs/{run_id}/status", {"status": status}, admin=True)
