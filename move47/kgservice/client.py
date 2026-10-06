"""Client shim: a drop-in `KATAGO_BIN` for goarena that talks to kgservice backends.

Invoked exactly like KataGo (`analysis -config C -model M -override-config ...`), it speaks
KataGo's JSON lines on stdin/stdout.  It connects to a live backend serving the same model
(basename match; -config is ignored), preferring non-draining backends with the latest
deadline, and keeps an in-flight table.  When the backend dies it reconnects to another one
(waiting up to $KGSERVICE_WAIT seconds, default 3600, polling the rendezvous dir) and resends
only unfinished queries -- for analyzeTurns only the turns not yet answered.  Responses are
deduplicated by (id, turnNumber).  When a backend announces draining, new and resent queries
go to a fresh backend while queries already running on the draining one finish there.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from typing import Optional

from .common import PROTO, Log, backend_alive, model_key, read_backends, run_dir

log = Log("client")
CONNECT_TIMEOUT = 10.0
RETRY_BAD = 10.0


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":")) + "\n"


class UsageError(Exception):
    pass


def parse_overrides(specs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in specs:
        for part in spec.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def config_value(path: str, key: str) -> Optional[str]:
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return None
    val = None
    for line in lines:
        line = line.split("#", 1)[0]
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip() == key:
                val = v.strip()
    return val


def parse_args(argv: list[str]) -> dict:
    if not argv or argv[0] != "analysis":
        raise UsageError("usage: kg-client analysis -config C -model M [-override-config K=V,...]")
    a = {"model": None, "config": None, "overrides": []}
    i = 1
    while i < len(argv):
        flag = argv[i]
        if flag in ("-model", "-config", "-override-config", "-analysis-threads"):
            if i + 1 >= len(argv):
                raise UsageError(f"{flag} needs a value")
            val = argv[i + 1]
            if flag == "-override-config":
                a["overrides"].append(val)
            elif flag != "-analysis-threads":
                a[flag[1:]] = val
            i += 2
        elif flag == "-quit-without-waiting":
            i += 1
        else:
            raise UsageError(f"unsupported argument {flag!r}")
    if not a["model"]:
        raise UsageError("-model is required (backends are matched by model basename)")
    ov = parse_overrides(a["overrides"])
    persp = ov.get("reportAnalysisWinratesAs")
    if persp is None and a["config"]:
        persp = config_value(a["config"], "reportAnalysisWinratesAs")
    if (persp or "BLACK").upper() != "BLACK":
        raise UsageError(f"reportAnalysisWinratesAs={persp} requested, but kgservice backends report "
                         "winrates as BLACK only; refusing to run")
    a["query_defaults"] = {}
    if "maxVisits" in ov:
        a["query_defaults"]["maxVisits"] = int(ov.pop("maxVisits"))
    ignored = sorted(k for k in ov if k != "reportAnalysisWinratesAs")
    if ignored:
        log(f"note: -override-config keys {ignored} are not forwarded (the backend's config applies)")
    return a


class Query:
    __slots__ = ("qid", "payload", "turns", "done", "warned", "conn", "since", "sent")

    def __init__(self, qid: str, payload: dict):
        self.qid, self.payload = qid, payload
        turns = payload.get("analyzeTurns") if not payload.get("action") else None
        self.turns: Optional[set] = set(turns) if isinstance(turns, list) and turns else None
        self.done: set = set()        # turn numbers already forwarded (None = the single answer)
        self.warned: set = set()
        self.conn: Optional["BConn"] = None
        self.since = time.time()       # unassigned since
        self.sent = False              # sent to some backend at least once

    def resend_payload(self) -> dict:
        if self.turns is not None and self.done:
            return dict(self.payload, analyzeTurns=[t for t in self.payload["analyzeTurns"] if t in self.turns])
        return self.payload

    def accept(self, msg: dict) -> tuple[bool, bool]:
        """-> (forward to the caller?, query finished?)"""
        if "error" in msg:
            return True, True
        if "warning" in msg:
            key = (msg.get("field"), str(msg.get("warning")))
            fwd = key not in self.warned
            self.warned.add(key)
            return fwd, False
        t = msg.get("turnNumber")
        if msg.get("isDuringSearch"):
            return (t not in self.done and (self.turns is None or t in self.turns)), False
        if self.turns is None:
            if self.done:
                return False, True
            self.done.add(t)
            return True, True
        if t not in self.turns:
            return False, False
        self.turns.discard(t)
        self.done.add(t)
        return True, not self.turns


class BConn:
    """One authenticated connection to a backend."""

    def __init__(self, client: "Client", info: dict):
        self.client, self.info, self.id = client, info, info["id"]
        self.draining = False
        self.dead = False
        self.wlock = threading.Lock()
        self.sock = socket.create_connection((info["host"], int(info["port"])), timeout=CONNECT_TIMEOUT)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.f = self.sock.makefile("rb")
            self.sock.sendall(dumps({"kgservice": "hello", "proto": PROTO, "token": info.get("token"),
                                     "model": client.model, "client": f"kg-client pid {os.getpid()}"}).encode())
            welcome = json.loads(self.f.readline(65536) or b"null")
            if not isinstance(welcome, dict) or welcome.get("kgservice") != "welcome":
                err = welcome.get("error") if isinstance(welcome, dict) else "connection closed"
                raise ConnectionError(f"backend refused: {err}")
            self.draining = bool(welcome.get("draining"))
            self.sock.settimeout(None)
        except BaseException:
            self.sock.close()
            raise
        threading.Thread(target=self._reader, daemon=True, name=f"{self.id}-r").start()

    def send(self, obj: dict) -> bool:
        if self.dead:
            return False
        try:
            with self.wlock:
                self.sock.sendall(dumps(obj).encode())
            return True
        except OSError as e:
            self.client.on_conn_dead(self, f"send failed: {e}")
            return False

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def _reader(self) -> None:
        reason = "connection closed by backend"
        try:
            for raw in self.f:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if "kgservice" in msg:
                    self.client.on_control(self, msg)
                else:
                    self.client.on_response(self, msg)
        except (OSError, ValueError) as e:
            reason = f"read failed: {e}"
        self.client.on_conn_dead(self, reason)


class Client:
    def __init__(self, model: str, rdir=None, wait: float = 3600.0, poll: float = 1.0,
                 query_defaults: Optional[dict] = None, stdout=None):
        self.model = model_key(model)
        self.run_dir = rdir or run_dir()
        self.wait, self.poll = wait, poll
        self.query_defaults = query_defaults or {}
        self.out = stdout or sys.stdout
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.out_lock = threading.Lock()
        self.inflight: dict[str, Query] = {}
        self.active: Optional[BConn] = None
        self.conns: set[BConn] = set()
        self.bad: dict[str, float] = {}
        self.stopping = False
        self.n_resent = 0

    # -- output ------------------------------------------------------------
    def emit(self, msg: dict) -> None:
        data = dumps(msg)
        with self.out_lock:
            try:
                self.out.write(data)
                self.out.flush()
            except (OSError, ValueError):
                os._exit(1)        # the caller is gone

    # -- events from connections --------------------------------------------
    def on_response(self, conn: BConn, msg: dict) -> None:
        qid = msg.get("id")
        fwd = False
        with self.lock:
            q = self.inflight.get(qid) if isinstance(qid, str) else None
            if q is None:
                fwd = qid is None and "error" in msg
            else:
                fwd, fin = q.accept(msg)
                if fin:
                    del self.inflight[qid]
                    self.cond.notify_all()
        if fwd:
            self.emit(msg)

    def on_control(self, conn: BConn, msg: dict) -> None:
        if msg.get("kgservice") == "draining":
            with self.lock:
                conn.draining = True
                self.cond.notify_all()
            log(f"backend {conn.id} is draining")

    def on_conn_dead(self, conn: BConn, reason: str) -> None:
        with self.lock:
            if conn.dead:
                return
            conn.dead = True
            self.conns.discard(conn)
            now = time.time()
            moved = [q for q in self.inflight.values() if q.conn is conn]
            for q in moved:
                q.conn, q.since = None, now
            if self.active is conn:
                self.active = None
            self.cond.notify_all()
        conn.close()
        if not self.stopping:
            log(f"lost backend {conn.id} ({reason}); {len(moved)} unfinished queries to resend")

    # -- stdin ----------------------------------------------------------------
    def on_stdin_line(self, raw: bytes) -> None:
        if not raw.strip():
            return
        try:
            obj = json.loads(raw)
        except ValueError as e:
            self.emit({"error": f"Could not parse json: {e}"})
            return
        if not isinstance(obj, dict) or not isinstance(obj.get("id"), str):
            self.emit({"id": obj.get("id") if isinstance(obj, dict) else None,
                       "error": "kgservice: query must be an object with a string id"})
            return
        if not obj.get("action"):
            for k, v in self.query_defaults.items():
                obj.setdefault(k, v)
        q = Query(obj["id"], obj)
        with self.lock:
            self.inflight[q.qid] = q
            conn = self.active if self.active is not None and not self.active.dead else None
            q.conn = conn
            q.sent = conn is not None
            if conn is None:
                self.cond.notify_all()
        if conn is not None:
            conn.send(q.payload)

    # -- backend selection ----------------------------------------------------
    def _candidates(self, non_draining_only: bool) -> list[dict]:
        now = time.time()
        cur = self.active.id if self.active is not None else None
        out = []
        for info in read_backends(self.run_dir):
            if info.get("model") != self.model or info["id"] == cur or not backend_alive(info):
                continue
            if self.bad.get(info["id"], 0.0) > now:
                continue
            if info.get("deadline") and info["deadline"] < now:
                continue
            if non_draining_only and info.get("draining"):
                continue
            if not info.get("port") or not info.get("host"):
                continue
            out.append(info)
        out.sort(key=lambda i: (bool(i.get("draining")), -(i.get("deadline") or float("inf"))))
        return out

    def _connect_best(self, non_draining_only: bool) -> Optional[BConn]:
        for info in self._candidates(non_draining_only):
            try:
                conn = BConn(self, info)
            except (OSError, ValueError, ConnectionError) as e:
                self.bad[info["id"]] = time.time() + RETRY_BAD
                log(f"cannot use backend {info['id']}: {e}")
                continue
            if conn.draining and non_draining_only:
                conn.dead = True
                conn.close()
                continue
            return conn
        return None

    def _dispatch_unassigned(self) -> None:
        with self.lock:
            conn = self.active
            if conn is None or conn.dead:
                return
            qs = [q for q in self.inflight.values() if q.conn is None]
            resent = sum(1 for q in qs if q.sent)
            for q in qs:
                q.conn, q.sent = conn, True
        for q in qs:
            p = q.resend_payload()
            if q.turns is not None and q.done:
                log(f"query {q.qid}: resending {len(p['analyzeTurns'])} of {len(q.payload['analyzeTurns'])} turns")
            conn.send(p)
        if qs:
            self.n_resent += resent
            log(f"sent {len(qs) - resent} new and resent {resent} unfinished queries to {conn.id}")

    def _expire_unassigned(self) -> None:
        now = time.time()
        with self.lock:
            if self.active is not None:
                return
            expired = [q for q in self.inflight.values() if q.conn is None and now - q.since > self.wait]
            for q in expired:
                del self.inflight[q.qid]
            if expired:
                self.cond.notify_all()
        for q in expired:
            self.emit({"id": q.qid, "error": f"kgservice: no live backend for model {self.model} "
                                              f"within {self.wait:g}s"})
        if expired:
            log(f"failed {len(expired)} queries: no backend within {self.wait:g}s")

    def _retire_idle(self) -> None:
        with self.lock:
            busy = {id(q.conn) for q in self.inflight.values() if q.conn is not None}
            idle = [c for c in self.conns if c is not self.active and id(c) not in busy]
            for c in idle:
                self.conns.discard(c)
                c.dead = True
        for c in idle:
            c.close()
            log(f"closed drained connection to {c.id}")

    def _manager(self) -> None:
        while not self.stopping:
            self._retire_idle()
            with self.lock:              # active died: fall back to a still-open draining connection
                if self.active is None:
                    spare = [c for c in self.conns if not c.dead]
                    if spare:
                        self.active = spare[0]
                        log(f"using still-open connection to {spare[0].id} while looking for another backend")
            with self.lock:
                if self.active is not None and self.active.dead:
                    self.active = None
                act = self.active
            if act is None or act.draining:
                conn = self._connect_best(non_draining_only=act is not None)
                if conn is not None:
                    with self.lock:
                        if conn.dead:            # hung up right after the handshake
                            self.bad[conn.id] = time.time() + RETRY_BAD
                            continue
                        old, self.active = self.active, conn
                        self.conns.add(conn)
                    dl = conn.info.get("deadline")
                    log(f"using backend {conn.id} (port {conn.info.get('port')}, "
                        f"{'draining, ' if conn.draining else ''}"
                        f"{'%.0fs left' % (dl - time.time()) if dl else 'no deadline'})"
                        + (f"; {old.id} keeps its in-flight queries" if old is not None else ""))
            self._dispatch_unassigned()
            self._expire_unassigned()
            with self.lock:
                if self.stopping:
                    break
                need = self.active is None or self.active.draining
                self.cond.wait(self.poll if need else 5.0)

    # -- main -----------------------------------------------------------------
    def run(self, stdin) -> int:
        threading.Thread(target=self._manager, daemon=True, name="manager").start()
        for raw in stdin:
            self.on_stdin_line(raw)
        with self.lock:              # stdin closed: like KataGo, finish what is in flight
            while self.inflight:
                self.cond.wait(1.0)
            self.stopping = True
            self.cond.notify_all()
            conns = list(self.conns)
        for c in conns:
            c.dead = True
            c.close()
        return 0


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "version":
        print("kgservice client: KataGo analysis protocol over kgservice backends")
        return 0
    try:
        a = parse_args(argv)
    except (UsageError, ValueError) as e:
        print(f"kg-client: {e}", file=sys.stderr, flush=True)
        return 2
    wait = float(os.environ.get("KGSERVICE_WAIT", "3600"))
    poll = float(os.environ.get("KGSERVICE_POLL", "1.0"))
    c = Client(a["model"], wait=wait, poll=poll, query_defaults=a["query_defaults"])
    log(f"model {c.model}; rendezvous {c.run_dir}; wait {wait:g}s")
    return c.run(sys.stdin.buffer)
