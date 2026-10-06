"""GPU-side backend: one KataGo analysis process shared by many TCP clients.

Wire protocol (JSON lines over TCP, 127.0.0.1 only):
  client -> backend  first line {"kgservice": "hello", "token": T, "model": basename, "proto": 1}
  backend -> client  {"kgservice": "welcome", "backend": id, "draining": bool, "deadline": t}
                     or {"kgservice": "error", "error": ...} and close
  afterwards         client sends KataGo queries, backend sends KataGo responses, plus the
                     control line {"kgservice": "draining", ...} when the job nears its end.
Query ids are rewritten to "c<conn>:<id>" on the way in and restored on the way out, so
clients with colliding ids never see each other's answers.  When a client disconnects its
unfinished queries are terminated in KataGo.
"""
from __future__ import annotations

import argparse
import hmac
import itertools
import json
import os
import queue
import secrets
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .common import (DEFAULT_CONFIG, DEFAULT_MODEL, PROTO, ROOT, Log, ensure_private_dir,
                     model_key, parse_slurm_time, run_dir, write_json_private)

READY_ID = "__kgs_ready"
TERM_PREFIX = "__kgs_term:"
AUTH_TIMEOUT = 10.0
MAX_OUTQ = 20000          # responses queued for one slow client before it is dropped

log = Log("backend")


def is_final(msg: dict) -> bool:
    """A response that completes one turn (or the whole query, for errors)."""
    return "error" in msg or (not msg.get("isDuringSearch") and "warning" not in msg)


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":")) + "\n"


class Conn:
    def __init__(self, server: "Backend", sock: socket.socket, cid: int):
        self.server, self.sock, self.cid = server, sock, cid
        self.prefix = f"c{cid}:"
        self.outq: "queue.Queue[Optional[str]]" = queue.Queue()
        self.outstanding: dict[str, int] = {}     # rewritten id -> final responses still due
        self.closed = False
        self.authed = False

    def start(self) -> None:
        threading.Thread(target=self._reader, daemon=True, name=f"conn{self.cid}-r").start()
        threading.Thread(target=self._writer, daemon=True, name=f"conn{self.cid}-w").start()

    def send(self, obj: dict) -> None:
        if self.closed:
            return
        if self.outq.qsize() > MAX_OUTQ:
            log(f"c{self.cid}: client not reading ({MAX_OUTQ} lines queued), dropping it")
            self.close(hard=True)
            return
        self.outq.put(dumps(obj))

    def close(self, hard: bool = False) -> None:
        if not self.closed:
            self.closed = True
            self.outq.put(None)
        if hard:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _writer(self) -> None:
        while True:
            item = self.outq.get()
            if item is None:
                break
            try:
                self.sock.sendall(item.encode())
            except OSError:
                break
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def _reader(self) -> None:
        f = self.sock.makefile("rb")
        try:
            self.sock.settimeout(AUTH_TIMEOUT)
            if not self._auth(f.readline(65536)):
                return
            self.sock.settimeout(None)
            while not self.closed:
                raw = f.readline()
                if not raw:
                    break
                if raw.strip():
                    self.server.on_client_line(self, raw)
        except (OSError, ValueError):
            pass
        finally:
            self.server.on_conn_closed(self)

    def _auth(self, raw: bytes) -> bool:
        try:
            hello = json.loads(raw)
        except ValueError:
            hello = None
        srv = self.server
        tok = hello.get("token") if isinstance(hello, dict) else None
        if not (isinstance(hello, dict) and hello.get("kgservice") == "hello" and isinstance(tok, str)
                and hmac.compare_digest(tok.encode(), srv.token.encode())):
            log(f"c{self.cid}: authentication failed")
            self.send({"kgservice": "error", "error": "authentication failed"})
            self.close()
            return False
        if hello.get("model") not in (None, srv.model_key):
            self.send({"kgservice": "error", "error": f"model mismatch: backend serves {srv.model_key}"})
            self.close()
            return False
        self.authed = True
        srv.register(self)
        self.send({"kgservice": "welcome", "proto": PROTO, "backend": srv.id, "model": srv.model_key,
                   "draining": srv.draining, "deadline": srv.deadline})
        log(f"c{self.cid}: client connected ({hello.get('client', '?')})")
        return True


class Backend:
    def __init__(self, a: argparse.Namespace):
        self.model, self.config, self.katago = a.model, a.config, a.katago
        self.model_key = model_key(a.model)
        self.overrides = list(a.override or [])
        self.run_dir = Path(a.run_dir) if a.run_dir else run_dir()
        self.ready_timeout = a.ready_timeout
        self.job_id = os.environ.get("SLURM_JOB_ID") or None
        self.id = f"kgb-{self.job_id}" if self.job_id else f"kgb-local-{os.getpid()}"
        self.rv_path = self.run_dir / f"{self.id}.json"
        self.token = secrets.token_hex(32)
        self.deadline: Optional[float] = a.deadline_epoch
        self.start_time = time.time()
        self.lock = threading.Lock()
        self.kg_lock = threading.Lock()
        self.conns: dict[int, Conn] = {}           # authenticated connections
        self.all_conns: set[Conn] = set()
        self.cid_seq = itertools.count(1)
        self.ready = threading.Event()
        self.engine_version = None
        self.proc: Optional[subprocess.Popen] = None
        self.listener: Optional[socket.socket] = None
        self.port = None
        self.draining = False
        self.stopping = False
        self.engine_exited = False
        self._flag_drain = False
        self._flag_stop: Optional[str] = None
        self.n_queries = 0

    # -- engine ------------------------------------------------------------
    def start_engine(self) -> None:
        overrides = ",".join(["reportAnalysisWinratesAs=BLACK", *self.overrides])
        cmd = [self.katago, "analysis", "-config", self.config, "-model", self.model,
               "-override-config", overrides]
        log(f"starting engine: {' '.join(cmd)}")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self._engine_reader, daemon=True, name="engine-r").start()
        self.kg_send({"id": READY_ID, "action": "query_version"})

    def kg_send(self, obj: dict) -> bool:
        line = json.dumps(obj) + "\n"
        with self.kg_lock:
            try:
                assert self.proc and self.proc.stdin
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
                return True
            except (OSError, ValueError, AssertionError):
                return False

    def _engine_reader(self) -> None:
        assert self.proc and self.proc.stdout
        for raw in self.proc.stdout:
            if raw.strip():
                self.on_engine_line(raw)
        self.engine_exited = True
        if not self.stopping:
            log(f"engine exited (rc={self.proc.wait()})")

    def on_engine_line(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            log(f"non-JSON line from engine: {raw.strip()[:200]}")
            return
        if not isinstance(msg, dict):
            return
        rid = msg.get("id")
        if rid == READY_ID:
            self.engine_version = msg.get("version")
            self.ready.set()
            return
        if not isinstance(rid, str) or not rid.startswith("c") or ":" not in rid:
            if not (isinstance(rid, str) and rid.startswith(TERM_PREFIX)):
                log(f"engine message without a routable id: {raw.strip()[:300]}")
            return
        head, orig = rid.split(":", 1)
        try:
            cid = int(head[1:])
        except ValueError:
            return
        with self.lock:
            conn = self.conns.get(cid)
            if conn is not None and is_final(msg):
                n = conn.outstanding.get(rid)
                if n is not None:
                    if "error" in msg or n <= 1:
                        del conn.outstanding[rid]
                    else:
                        conn.outstanding[rid] = n - 1
        if conn is None:
            return
        msg["id"] = orig
        tid = msg.get("terminateId")
        if isinstance(tid, str) and tid.startswith(conn.prefix):
            msg["terminateId"] = tid[len(conn.prefix):]
        conn.send(msg)

    # -- clients -----------------------------------------------------------
    def register(self, conn: Conn) -> None:
        with self.lock:
            self.conns[conn.cid] = conn

    def on_client_line(self, conn: Conn, raw: bytes) -> None:
        try:
            obj = json.loads(raw)
        except ValueError as e:
            conn.send({"error": f"Could not parse json: {e}"})
            return
        if not isinstance(obj, dict):
            conn.send({"error": "Request is not a JSON object"})
            return
        if "kgservice" in obj:
            if obj.get("kgservice") == "ping":
                conn.send({"kgservice": "pong", "draining": self.draining, "deadline": self.deadline})
            return
        qid = obj.get("id")
        if not isinstance(qid, str):
            conn.send({"id": qid, "error": "kgservice: query id must be a string"})
            return
        action = obj.get("action")
        if action == "terminate_all":    # must not touch other clients' queries
            with self.lock:
                mine = list(conn.outstanding)
            for rid in mine:
                self.kg_send({"id": TERM_PREFIX + rid, "action": "terminate", "terminateId": rid})
            conn.send({"id": qid, "action": "terminate_all"})
            return
        rid = conn.prefix + qid
        obj["id"] = rid
        if action == "terminate" and isinstance(obj.get("terminateId"), str):
            obj["terminateId"] = conn.prefix + obj["terminateId"]
        turns = obj.get("analyzeTurns")
        expected = len(set(turns)) if (not action and isinstance(turns, list) and turns) else 1
        with self.lock:
            conn.outstanding[rid] = expected
            self.n_queries += 1
        if not self.kg_send(obj):
            # engine gone (shutdown under way): hang up so the client resends elsewhere
            log(f"c{conn.cid}: engine not accepting queries; closing the connection")
            conn.close(hard=True)

    def on_conn_closed(self, conn: Conn) -> None:
        with self.lock:
            self.conns.pop(conn.cid, None)
            self.all_conns.discard(conn)
            pending = list(conn.outstanding)
            conn.outstanding.clear()
        conn.close()
        if not conn.authed:
            return
        for rid in pending:
            self.kg_send({"id": TERM_PREFIX + rid, "action": "terminate", "terminateId": rid})
        log(f"c{conn.cid}: client disconnected; terminated {len(pending)} unfinished queries")

    def _accept_loop(self) -> None:
        assert self.listener
        while not self.stopping:
            try:
                sock, _ = self.listener.accept()
            except OSError:
                break
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn = Conn(self, sock, next(self.cid_seq))
            with self.lock:
                self.all_conns.add(conn)
            conn.start()

    # -- lifecycle ---------------------------------------------------------
    def rendezvous(self) -> dict:
        return {"id": self.id, "proto": PROTO, "host": "127.0.0.1", "port": self.port, "token": self.token,
                "model": self.model_key, "model_path": os.path.abspath(self.model),
                "config": os.path.abspath(self.config), "pid": os.getpid(),
                "engine_pid": self.proc.pid if self.proc else None, "engine_version": self.engine_version,
                "hostname": socket.gethostname(), "slurm_job_id": self.job_id,
                "start_time": self.start_time, "deadline": self.deadline, "draining": self.draining}

    def write_rendezvous(self) -> None:
        ensure_private_dir(self.run_dir)
        write_json_private(self.rv_path, self.rendezvous())

    def drain(self) -> None:
        self.draining = True
        if not self.stopping and self.port:
            self.write_rendezvous()
        with self.lock:
            conns = list(self.conns.values())
        for c in conns:
            c.send({"kgservice": "draining", "backend": self.id, "deadline": self.deadline})
        log(f"draining: told {len(conns)} clients; still serving until the job ends")

    def shutdown(self, reason: str) -> None:
        self.stopping = True
        try:
            self.rv_path.unlink()
        except FileNotFoundError:
            pass
        if self.listener:
            try:
                self.listener.close()
            except OSError:
                pass
        with self.lock:
            conns = list(self.all_conns)
        for c in conns:
            c.close(hard=True)
        if self.proc and self.proc.poll() is None:
            try:
                assert self.proc.stdin
                self.proc.stdin.close()
            except (OSError, AssertionError):
                pass
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        log(f"stopped ({reason}); served {self.n_queries} queries")

    def _on_signal(self, signum, _frame) -> None:
        if signum == signal.SIGUSR1:
            self._flag_drain = True
        else:
            self._flag_stop = signal.Signals(signum).name

    def run(self) -> int:
        for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGUSR1):
            signal.signal(s, self._on_signal)
        if self.deadline is None:
            self.deadline = slurm_deadline()
        self.start_engine()
        t0 = time.time()
        while not self.ready.wait(0.2):
            if self._flag_stop or self.engine_exited or time.time() - t0 > self.ready_timeout:
                why = self._flag_stop or ("engine exited during startup" if self.engine_exited else "startup timeout")
                self.shutdown(why)
                return 0 if self._flag_stop else 1
        log(f"engine ready after {time.time() - t0:.1f}s (KataGo {self.engine_version})")
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(64)
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True, name="accept").start()
        self.write_rendezvous()
        log(f"serving {self.model_key} on 127.0.0.1:{self.port} as {self.id}; rendezvous {self.rv_path}; "
            f"deadline {time.strftime('%H:%M:%S', time.localtime(self.deadline)) if self.deadline else 'none'}")
        rc = 0
        while True:
            if self._flag_drain and not self.draining:
                log("SIGUSR1: job end approaching")
                self.drain()
            if self._flag_stop:
                reason = self._flag_stop
                break
            if self.engine_exited:
                reason, rc = "engine exited", 1
                break
            time.sleep(0.2)
        self.shutdown(reason)
        return rc


def slurm_deadline() -> Optional[float]:
    """End time of the enclosing Slurm job (None outside Slurm)."""
    v = os.environ.get("SLURM_JOB_END_TIME", "")
    if v.isdigit():
        return float(v)
    jid = os.environ.get("SLURM_JOB_ID")
    if not jid:
        return None
    try:
        out = subprocess.run(["squeue", "-h", "-j", jid, "-o", "%e"], capture_output=True, text=True,
                             timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_slurm_time(out)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kgservice backend", description=__doc__.split("\n")[0])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--katago", default=os.environ.get("KGSERVICE_KATAGO", str(ROOT / "engines/katago")))
    ap.add_argument("--run-dir", default=None, help="rendezvous dir (default engines/run/backends)")
    ap.add_argument("--override", action="append", help="extra KataGo -override-config KEY=VALUE")
    ap.add_argument("--deadline-epoch", type=float, default=None, help="default: the Slurm job's end time")
    ap.add_argument("--ready-timeout", type=float, default=600.0)
    a = ap.parse_args(argv)
    for o in a.override or []:
        if o.split("=", 1)[0].strip() == "reportAnalysisWinratesAs":
            ap.error("reportAnalysisWinratesAs is fixed to BLACK")
    return Backend(a).run()
