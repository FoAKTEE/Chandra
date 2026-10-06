"""HTTP API (stdlib only).

Three audiences, three auth scopes:
  /api/agent/*   Bearer <run token>   -- the agent under test (via `goban`)
  /api/admin/*   Bearer <admin token> -- the operator / campaign runner
  /api/*         public read-only     -- the website (optionally gated by a viewer token)
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from .arena import Arena, ArenaError

log = logging.getLogger("goarena.http")


def rules_text(arena: Arena, run: dict) -> str:
    s = arena.s
    cfg = run["config"]
    size, komi = cfg.get("size", s.size), cfg.get("komi", s.komi)
    cap = int(s.move_cap_factor * size * size)
    return f"""ARENA RULES
- Board {size}x{size}. Chinese rules: area scoring (stones + surrounded empty points), komi {komi:g} for White.
- Captures as usual. Suicide is illegal. Positional superko: you may not recreate any earlier board position (this covers ko).
- Coordinates: columns {''.join('ABCDEFGHJKLMNOPQRST'[:size])} (no I), rows 1-{size} from the bottom; e.g. `goban play C3`. Also `pass` and `resign`.
- The game ends after two consecutive passes (or resignation). The referee then removes dead stones and counts area.
  Pass only when nothing useful is left: if you pass early the opponent keeps playing and unsettled areas count for nobody.
- Illegal move attempts are rejected and counted. More than {s.max_illegal_per_game} in one game forfeits that game.
- If you do not move for {s.move_timeout_s / 60:.0f} minutes the game is forfeited (timeout).
- A game is capped at {cap} moves; then it is scored as it stands.
- Opponents never learn: each game they play from scratch. You choose the opponent for each game.
- The run consists of {run['target_games']} games. Your rating uses your last {s.rating_window} games against rated opponents."""


class Handler(BaseHTTPRequestHandler):
    arena: Arena
    admin_token: str = ""
    viewer_token: str = ""
    web_root: Optional[Path] = None
    server_version = "goarena/0.1"

    # quiet default logging
    def log_message(self, fmt, *args):  # noqa: N802
        log.debug("%s - %s", self.address_string(), fmt % args)

    # -- plumbing ----------------------------------------------------------
    def _send(self, status: int, body, ctype: str = "application/json") -> None:
        data = body if isinstance(body, (bytes, bytearray)) else (
            json.dumps(body, default=str).encode() if ctype == "application/json" else str(body).encode())
        self.send_response(status)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _err(self, status: int, code: str, message: str) -> None:
        self._send(status, {"ok": False, "error": {"code": code, "message": message},
                            "text": f"ERROR ({code}): {message}"})

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            raise ArenaError("bad_json", "request body is not valid JSON")

    def _bearer(self) -> str:
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    def _run(self) -> dict:
        tok = self._bearer()
        run = self.arena.store.run_by_token(tok) if tok else None
        if not run:
            raise ArenaError("unauthorized", "missing or invalid run token (GOARENA_TOKEN)", 401)
        return run

    def _admin(self) -> None:
        if not self.admin_token or self._bearer() != self.admin_token:
            raise ArenaError("unauthorized", "admin token required", 401)

    def _privileged(self, qs: dict) -> bool:
        """True when the caller proved it is the operator or a keyed viewer.  Only privileged
        callers see engine analysis of runs that are still in progress, because the agent
        itself can reach the public API and must not get engine feedback."""
        tok = self._bearer() or qs.get("key", [""])[0]
        return bool(tok) and tok in {t for t in (self.viewer_token, self.admin_token) if t}

    def _viewer(self, qs: dict) -> None:
        if self.viewer_token and self._bearer() != self.viewer_token and \
                qs.get("key", [""])[0] != self.viewer_token and self._bearer() != self.admin_token:
            raise ArenaError("unauthorized", "viewer token required", 401)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        path = url.path.rstrip("/") or "/"
        try:
            for m, pat, fn in ROUTES:
                if m != method:
                    continue
                mt = re.fullmatch(pat, path)
                if mt:
                    return fn(self, qs, *mt.groups())
            if method == "GET" and not path.startswith("/api"):
                return self._static(path)
            raise ArenaError("not_found", f"no route for {method} {path}", 404)
        except ArenaError as e:
            self._err(e.status, e.code, e.message)
        except Exception as e:  # pragma: no cover
            log.error("handler error: %s\n%s", e, traceback.format_exc())
            self._err(500, "internal", str(e))

    def _static(self, path: str) -> None:
        if not self.web_root:
            raise ArenaError("not_found", "no website configured", 404)
        rel = "index.html" if path == "/" else path.lstrip("/")
        f = (self.web_root / rel).resolve()
        if not str(f).startswith(str(self.web_root.resolve())) or not f.is_file():
            f = self.web_root / "index.html"
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        self._send(200, f.read_bytes(), ctype)


# ---------------------------------------------------------------- routes
def r_health(h: Handler, qs):
    h._send(200, {"ok": True, "katago": bool(h.arena.kg and h.arena.kg.alive()), "time": time.time()})


# agent ---------------------------------------------------------------------
def r_rules(h: Handler, qs):
    run = h._run()
    h._send(200, {"ok": True, "text": rules_text(h.arena, run)})


def r_opponents(h: Handler, qs):
    h._send(200, h.arena.opponents_view(h._run()))


def r_status(h: Handler, qs):
    h._send(200, h.arena.status(h._run()))


def r_board(h: Handler, qs):
    h._send(200, h.arena.board_view(h._run()))


def r_new(h: Handler, qs):
    run = h._run()
    b = h._body()
    if not b.get("opponent"):
        raise ArenaError("missing_opponent", "choose an opponent: goban new --opponent NAME (see `goban opponents`)")
    h._send(200, h.arena.new_game(run, str(b["opponent"]), b.get("color")))


def r_play(h: Handler, qs):
    run = h._run()
    b = h._body()
    if not b.get("move"):
        raise ArenaError("missing_move", "give a move, e.g. `goban play D4`, `goban play pass`")
    h._send(200, h.arena.play(run, str(b["move"])))


def r_resign(h: Handler, qs):
    h._send(200, h.arena.play(h._run(), "resign"))


def r_agent_games(h: Handler, qs):
    h._send(200, h.arena.games_view(h._run(), int(qs.get("limit", ["50"])[0])))


def r_agent_game(h: Handler, qs, game_no):
    run = h._run()
    out = h.arena.game_view(run, game_no=int(game_no))
    if qs.get("format", [""])[0] == "sgf":
        return h._send(200, out["sgf"], "application/x-go-sgf")
    h._send(200, out)


# public --------------------------------------------------------------------
ENGINE_FIELDS = ("avg_point_loss", "engine_match_rate")


def _hide_engine(run: dict, privileged: bool) -> bool:
    return not privileged and run["status"] in ("active", "paused")


def _public_summary(arena: Arena, run: dict, privileged: bool = False) -> dict:
    s = arena.run_summary(run)
    if _hide_engine(run, privileged):
        for k in ENGINE_FIELDS:
            s[k] = None
        s["engine_hidden"] = True
    g = arena.store.active_game(run["id"])
    s["live"] = None
    if g:
        s["live"] = {"game_id": g["id"], "game_no": g["game_no"], "opponent": g["opponent"],
                     "moves": g["moves_count"]}
    return s


def r_leaderboard(h: Handler, qs):
    h._viewer(qs)
    priv = h._privileged(qs)
    runs = [_public_summary(h.arena, r, priv) for r in h.arena.store.list_runs()]
    h._send(200, {"ok": True, "runs": runs, "tiers": [t.public() for t in h.arena.s.tiers.values()],
                  "rating_window": h.arena.s.rating_window})


def r_run(h: Handler, qs, run_id):
    h._viewer(qs)
    run = h.arena.store.get_run(run_id)
    if not run:
        raise ArenaError("not_found", "no such run", 404)
    d = h.arena.run_detail(run)
    d["summary"]["live"] = _public_summary(h.arena, run)["live"]
    if _hide_engine(run, h._privileged(qs)):
        for k in ENGINE_FIELDS:
            d["summary"][k] = None
        for g in d["games"]:
            g["review_summary"] = None
        d["engine_hidden"] = True
    h._send(200, {"ok": True, **d})


def r_game(h: Handler, qs, gid):
    h._viewer(qs)
    out = h.arena.game_view(None, game_id=int(gid), include_review=True)
    if qs.get("format", [""])[0] == "sgf":
        return h._send(200, out["sgf"], "application/x-go-sgf")
    run = h.arena.store.get_run(out["game"]["run_id"])
    if run and _hide_engine(run, h._privileged(qs)):
        out["review"], out["review_summary"], out["engine_hidden"] = None, None, True
    h._send(200, out)


def r_live(h: Handler, qs):
    h._viewer(qs)
    out = []
    for g in h.arena.store.all_active_games():
        run = h.arena.store.get_run(g["run_id"])
        b = h.arena.boards.get(g["id"])
        if not b or not run:
            continue
        moves = h.arena.store.game_moves(g["id"])
        out.append({"run_id": run["id"], "run_name": run["name"], "model": run["model"],
                    "game": {k: g[k] for k in ("id", "game_no", "opponent", "agent_color", "moves_count",
                                               "illegal_count", "started_at", "last_activity")},
                    "board_rows": b.to_rows(), "to_play": "B" if b.to_play == 1 else "W",
                    "moves": [f"{m['color']}{m['coord']}" for m in moves[-12:]]})
    h._send(200, {"ok": True, "games": out})


def r_events(h: Handler, qs):
    h._viewer(qs)
    after = int(qs.get("after", ["0"])[0])
    run = qs.get("run", [None])[0]
    evs = h.arena.store.events_since(after, run_id=run)
    if not h._privileged(qs):
        evs = [e for e in evs if e["kind"] != "review_done"]
    h._send(200, {"ok": True, "events": evs})


def r_tiers(h: Handler, qs):
    h._viewer(qs)
    h._send(200, {"ok": True, "tiers": [t.public() for t in h.arena.s.tiers.values()]})


# admin ---------------------------------------------------------------------
def r_admin_create(h: Handler, qs):
    h._admin()
    b = h._body()
    if not b.get("name"):
        raise ArenaError("missing_name", "name is required")
    run = h.arena.create_run(b["name"], model=b.get("model", ""), harness=b.get("harness", ""),
                             reasoning=b.get("reasoning", ""), context=b.get("context", ""),
                             notes=b.get("notes", ""), target_games=int(b.get("target_games", 200)),
                             config=b.get("config") or {}, run_id=b.get("id"))
    h._send(200, {"ok": True, "run": run})


def r_admin_runs(h: Handler, qs):
    h._admin()
    h._send(200, {"ok": True, "runs": h.arena.store.list_runs()})


def r_admin_run_status(h: Handler, qs, run_id):
    h._admin()
    st = h._body().get("status")
    if st not in ("active", "paused", "complete", "abandoned"):
        raise ArenaError("bad_status", "status must be active|paused|complete|abandoned")
    if not h.arena.store.get_run(run_id):
        raise ArenaError("not_found", "no such run", 404)
    h.arena.set_run_status(run_id, st)
    h._send(200, {"ok": True, "run": h.arena.store.get_run(run_id)})


def r_admin_review(h: Handler, qs, gid):
    h._admin()
    h._send(200, {"ok": True, "summary": h.arena.review_game(int(gid))})


ROUTES: list[tuple[str, str, Callable]] = [
    ("GET", r"/healthz", r_health),
    ("GET", r"/api/agent/rules", r_rules),
    ("GET", r"/api/agent/opponents", r_opponents),
    ("GET", r"/api/agent/status", r_status),
    ("GET", r"/api/agent/board", r_board),
    ("POST", r"/api/agent/new", r_new),
    ("POST", r"/api/agent/play", r_play),
    ("POST", r"/api/agent/resign", r_resign),
    ("GET", r"/api/agent/games", r_agent_games),
    ("GET", r"/api/agent/games/(\d+)", r_agent_game),
    ("GET", r"/api/leaderboard", r_leaderboard),
    ("GET", r"/api/runs/([\w\-]+)", r_run),
    ("GET", r"/api/games/(\d+)", r_game),
    ("GET", r"/api/live", r_live),
    ("GET", r"/api/events", r_events),
    ("GET", r"/api/tiers", r_tiers),
    ("POST", r"/api/admin/runs", r_admin_create),
    ("GET", r"/api/admin/runs", r_admin_runs),
    ("POST", r"/api/admin/runs/([\w\-]+)/status", r_admin_run_status),
    ("POST", r"/api/admin/games/(\d+)/review", r_admin_review),
]


def serve(arena: Arena, host: str, port: int, admin_token: str, viewer_token: str = "",
          web_root: Optional[str] = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {
        "arena": arena, "admin_token": admin_token, "viewer_token": viewer_token,
        "web_root": Path(web_root) if web_root else None})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd
