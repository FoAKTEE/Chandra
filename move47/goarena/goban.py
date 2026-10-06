#!/usr/bin/env python3
"""goban — the command-line tool the agent uses to play in the arena.

Talks to the arena over HTTP.  Configuration comes from the environment:
  GOARENA_URL    e.g. http://127.0.0.1:8765
  GOARENA_TOKEN  the run token given to this agent

Stdlib only, so it can be dropped into any sandbox.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

HELP = """\
goban — play Go in the arena

  goban rules                         show the rules of this arena
  goban opponents                     list opponents you can choose
  goban status                        run progress, results per opponent, rating
  goban new --opponent NAME [--color black|white|random]
                                      start a game (default colour alternates)
  goban board                         show the current game
  goban play COORD                    play a move, e.g. `goban play D4`; also `pass`
  goban resign                        resign the current game
  goban games [--limit N]             list your finished games
  goban show N [--sgf]                show finished game #N (moves, or SGF)

Add --json to any command for machine-readable output.
Exit codes: 0 ok (including game over), 2 illegal move / rejected request, 1 cannot reach the arena.
"""


def _call(method: str, path: str, body: dict | None = None, raw: bool = False):
    url = os.environ.get("GOARENA_URL", "http://127.0.0.1:8765").rstrip("/") + path
    token = os.environ.get("GOARENA_TOKEN", "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            payload = resp.read().decode()
    except urllib.error.HTTPError as e:
        payload = e.read().decode()
    except urllib.error.URLError as e:
        print(f"ERROR: cannot reach the arena at {url}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    if raw:
        return payload
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        print(payload)
        sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0
    p = argparse.ArgumentParser(prog="goban", add_help=False)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("rules")
    sub.add_parser("opponents")
    sub.add_parser("status")
    sub.add_parser("board")
    n = sub.add_parser("new")
    n.add_argument("--opponent", "-o", required=False)
    n.add_argument("--color", "-c", default=None)
    pl = sub.add_parser("play")
    pl.add_argument("move")
    sub.add_parser("pass")
    sub.add_parser("resign")
    g = sub.add_parser("games")
    g.add_argument("--limit", type=int, default=50)
    s = sub.add_parser("show")
    s.add_argument("game_no", type=int)
    s.add_argument("--sgf", action="store_true")
    try:
        a = p.parse_args(argv)
    except SystemExit:
        print(HELP)
        return 1

    if a.cmd == "rules":
        r = _call("GET", "/api/agent/rules")
    elif a.cmd == "opponents":
        r = _call("GET", "/api/agent/opponents")
    elif a.cmd == "status":
        r = _call("GET", "/api/agent/status")
    elif a.cmd == "board":
        r = _call("GET", "/api/agent/board")
    elif a.cmd == "new":
        r = _call("POST", "/api/agent/new", {"opponent": a.opponent, "color": a.color})
    elif a.cmd == "play":
        r = _call("POST", "/api/agent/play", {"move": a.move})
    elif a.cmd == "pass":
        r = _call("POST", "/api/agent/play", {"move": "pass"})
    elif a.cmd == "resign":
        r = _call("POST", "/api/agent/resign", {})
    elif a.cmd == "games":
        r = _call("GET", f"/api/agent/games?limit={a.limit}")
    elif a.cmd == "show":
        if a.sgf:
            print(_call("GET", f"/api/agent/games/{a.game_no}?format=sgf", raw=True), end="")
            return 0
        r = _call("GET", f"/api/agent/games/{a.game_no}")
    else:
        print(HELP)
        return 1

    if as_json:
        print(json.dumps(r, indent=2))
    else:
        print(r.get("text") or json.dumps(r, indent=2))
    return 0 if r.get("ok", False) else 2


if __name__ == "__main__":
    sys.exit(main())
