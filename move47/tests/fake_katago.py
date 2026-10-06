#!/usr/bin/env python3
"""Fake KataGo analysis engine for the kgservice tests (no GPU, no network).

Speaks the analysis protocol on stdio: one response per analyzeTurn, optional isDuringSearch
partials, policy/ownership on request, query_version / terminate actions, errors with ids.
Values are deterministic functions of the position, so tests can tell answers apart.
Environment:
  FAKE_KATAGO_DELAY     seconds of "search" per turn (default 0.05)
  FAKE_KATAGO_PARTIALS  isDuringSearch partials per turn (default 0)
  FAKE_KATAGO_STARTUP   seconds before the engine reads stdin (default 0)
  FAKE_KATAGO_TAG       echoed in every response as "fakeEngine"
  FAKE_KATAGO_QUERYLOG  append every received query line to this file
"""
import hashlib
import json
import os
import queue
import sys
import threading
import time

COLS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
DELAY = float(os.environ.get("FAKE_KATAGO_DELAY", "0.05"))
PARTIALS = int(os.environ.get("FAKE_KATAGO_PARTIALS", "0"))
TAG = os.environ.get("FAKE_KATAGO_TAG")
QLOG = os.environ.get("FAKE_KATAGO_QUERYLOG")

out_lock = threading.Lock()
terminated = set()


def emit(obj):
    if TAG and "id" in obj:
        obj["fakeEngine"] = TAG
    with out_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def coord(x, y, size):
    return f"{COLS[x]}{y + 1}"


def respond(q, t, partial):
    size = int(q.get("boardXSize", 19))
    moves = q.get("moves", [])[:t]
    occupied = {}
    for col, mv in [(s[0], s[1]) for s in q.get("initialStones", [])] + [(m[0], m[1]) for m in moves]:
        if str(mv).lower() != "pass":
            occupied[str(mv).upper()] = col
    h = int(hashlib.sha1(json.dumps([size, moves, q.get("initialStones", [])]).encode()).hexdigest(), 16)
    first = q.get("initialPlayer", "B")
    player = first if t % 2 == 0 else ("W" if first == "B" else "B")
    visits = int(q.get("maxVisits", 100))
    wr = 0.3 + (h % 400) / 1000.0
    lead = ((h >> 12) % 200 - 100) / 10.0
    empties = [coord(x, y, size) for y in range(size) for x in range(size) if coord(x, y, size) not in occupied]
    k = h % max(1, len(empties))
    cands = (empties[k:] + empties[:k])[:5] or ["pass"]
    infos = [{"move": m, "order": i, "visits": max(1, visits // (2 ** i)), "winrate": round(wr - 0.01 * i, 4),
              "scoreLead": round(lead - 0.5 * i, 2), "prior": round(0.5 / (i + 1), 4), "pv": [m]}
             for i, m in enumerate(cands)]
    r = {"id": q["id"], "isDuringSearch": partial, "turnNumber": t, "moveInfos": infos,
         "rootInfo": {"visits": visits if not partial else max(1, visits // 2), "winrate": wr, "scoreLead": lead,
                      "currentPlayer": player, "thisHash": "%040x" % h}}
    if q.get("includePolicy"):
        pol = [-1.0] * (size * size) + [0.001]
        for i, m in enumerate(cands):
            if m != "pass":
                x, y = COLS.index(m[0]), int(m[1:]) - 1
                pol[(size - 1 - y) * size + x] = round(0.5 / (i + 1), 4)
        r["policy"] = pol
    if q.get("includeOwnership"):
        own = [0.0] * (size * size)
        for m, col in occupied.items():
            x, y = COLS.index(m[0]), int(m[1:]) - 1
            if x < size and y < size:
                own[(size - 1 - y) * size + x] = 0.9 if col == "B" else -0.9
        r["ownership"] = own
    return r


def analyze(q):
    turns = q.get("analyzeTurns") or [len(q.get("moves", []))]
    for t in turns:
        if q["id"] in terminated:
            emit({"id": q["id"], "turnNumber": t, "isDuringSearch": False, "noResults": True})
            continue
        for _ in range(PARTIALS):
            time.sleep(DELAY / (PARTIALS + 1))
            emit(respond(q, t, True))
        time.sleep(DELAY / (PARTIALS + 1) if PARTIALS else DELAY)
        emit(respond(q, t, False))


def validate(q):
    n = len(q.get("moves", []))
    for t in q.get("analyzeTurns") or []:
        if not isinstance(t, int) or not 0 <= t <= n:
            return "analyzeTurns", f"invalid turn {t!r}"
    if not isinstance(q.get("boardXSize", 19), int):
        return "boardXSize", "must be an integer"
    return None


def main():
    args = sys.argv[1:]
    if args and args[0] == "version":
        print("KataGo v1.18.2 (fake)")
        return 0
    if not args or args[0] != "analysis":
        print("fake_katago: only `analysis` is supported", file=sys.stderr)
        return 2
    time.sleep(float(os.environ.get("FAKE_KATAGO_STARTUP", "0")))
    print("Started, ready to begin handling requests", file=sys.stderr, flush=True)
    work = queue.Queue()

    def worker():
        while True:
            q = work.get()
            if q is None:
                return
            try:
                analyze(q)
            except (BrokenPipeError, OSError):
                os._exit(0)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
    for th in threads:
        th.start()
    for line in sys.stdin:
        if not line.strip():
            continue
        if QLOG:
            with open(QLOG, "a") as f:
                f.write(line if line.endswith("\n") else line + "\n")
        try:
            q = json.loads(line)
        except ValueError as e:
            emit({"error": f"Could not parse json: {e}"})
            continue
        qid = q.get("id")
        if not isinstance(qid, str):
            emit({"error": "Request did not specify a string id"})
            continue
        action = q.get("action")
        if action == "query_version":
            emit({"id": qid, "action": "query_version", "version": "1.18.2-fake", "git_hash": "fake"})
        elif action == "terminate":
            terminated.add(q.get("terminateId"))
            emit({"id": qid, "action": "terminate", "terminateId": q.get("terminateId")})
        elif action:
            emit({"id": qid, "error": f"unknown action {action}"})
        else:
            bad = validate(q)
            if bad:
                emit({"id": qid, "field": bad[0], "error": bad[1]})
            else:
                work.put(q)
    for _ in threads:
        work.put(None)
    for th in threads:
        th.join()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        os._exit(0)
