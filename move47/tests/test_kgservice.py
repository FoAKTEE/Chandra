"""kgservice: backend / client / keepalive against a fake KataGo (no GPU, no Slurm, ~20 s)."""
from __future__ import annotations

import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from kgservice.common import job_name, model_key, read_backends, write_json_private
from kgservice.keepalive import Keepalive, clean_stale, decide, parse_squeue

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "tests" / "fake_katago.py"
CLIENT = ROOT / "bin" / "kg-client"
MOVES = [["B", "E5"], ["W", "C3"], ["B", "G7"], ["W", "C7"], ["B", "G3"], ["W", "E3"], ["B", "E7"], ["W", "D7"]]


def wait_for(pred, timeout=15.0, what="condition"):
    t_end = time.time() + timeout
    while time.time() < t_end:
        v = pred()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def q9(qid, nmoves=2, visits=10, **kw):
    return {"id": qid, "moves": MOVES[:nmoves], "rules": "chinese", "komi": 7.5, "boardXSize": 9,
            "boardYSize": 9, "maxVisits": visits, **kw}


class FakeBackend:
    def __init__(self, svc, tag, proc, qlog):
        self.svc, self.tag, self.proc, self.qlog = svc, tag, proc, qlog
        self.info = wait_for(lambda: next((b for b in read_backends(svc.run) if b.get("pid") == proc.pid), None),
                             what=f"backend {tag} rendezvous")
        self.id = self.info["id"]

    def queries(self) -> list[dict]:
        """Analysis queries the fake engine received (the backend's readiness probe excluded)."""
        try:
            lines = self.qlog.read_text().splitlines()
        except FileNotFoundError:
            return []
        return [q for q in map(json.loads, filter(str.strip, lines)) if "action" not in q]

    def rendezvous(self):
        return next((b for b in read_backends(self.svc.run) if b["id"] == self.id), None)


class RawClient:
    """bin/kg-client driven over raw stdio, recording every line it prints."""

    def __init__(self, svc, env=None):
        self.p = subprocess.Popen([str(CLIENT), "analysis", "-config", str(svc.cfg), "-model", str(svc.model),
                                   "-override-config", "reportAnalysisWinratesAs=BLACK"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, bufsize=1, env=dict(svc.env, **(env or {})))
        self.msgs: list[dict] = []
        self.log: list[str] = []
        self.lock = threading.Lock()
        threading.Thread(target=self._read, args=(self.p.stdout, True), daemon=True).start()
        threading.Thread(target=self._read, args=(self.p.stderr, False), daemon=True).start()
        svc.clients.append(self)

    def _read(self, stream, is_out):
        for line in stream:
            with self.lock:
                if is_out:
                    self.msgs.append(json.loads(line))
                else:
                    self.log.append(line.rstrip())

    def send(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def finals(self, qid):
        with self.lock:
            return [m for m in self.msgs if m.get("id") == qid and not m.get("isDuringSearch")]

    def partials(self, qid):
        with self.lock:
            return [m for m in self.msgs if m.get("id") == qid and m.get("isDuringSearch")]

    def wait_finals(self, qid, n=1, timeout=15.0):
        return wait_for(lambda: len(self.finals(qid)) >= n and self.finals(qid), timeout, f"{n} answers to {qid}")

    def wait_log(self, text, timeout=15.0):
        def hit():
            with self.lock:
                return any(text in x for x in self.log)
        return wait_for(hit, timeout, f"client log line {text!r}")

    def close(self):
        if self.p.poll() is None:
            self.p.stdin.close()
        return self.p.wait(15)


class Svc:
    def __init__(self, tmp: Path):
        self.tmp, self.run = tmp, tmp / "run"
        self.model, self.cfg = tmp / "fake-net.bin.gz", tmp / "fake.cfg"
        self.model.write_bytes(b"not a real net")
        # The client must override this with BLACK, as goarena does.
        self.cfg.write_text("reportAnalysisWinratesAs = SIDETOMOVE\n")
        self.env = dict(os.environ, KGSERVICE_RUN_DIR=str(self.run), KGSERVICE_POLL="0.05", KGSERVICE_WAIT="20",
                        PYTHONPATH=str(ROOT))
        self.env.pop("KGSERVICE_LOG", None)
        self.backends: list[FakeBackend] = []
        self.clients: list[RawClient] = []

    def start_backend(self, tag, delay=0.05, partials=0, deadline_in=None) -> FakeBackend:
        qlog = self.tmp / f"queries-{tag}.jsonl"
        env = dict(self.env, FAKE_KATAGO_TAG=tag, FAKE_KATAGO_DELAY=str(delay),
                   FAKE_KATAGO_PARTIALS=str(partials), FAKE_KATAGO_QUERYLOG=str(qlog))
        cmd = [sys.executable, "-m", "kgservice", "backend", "--model", str(self.model), "--config", str(self.cfg),
               "--katago", str(FAKE)]
        if deadline_in is not None:
            cmd += ["--deadline-epoch", str(time.time() + deadline_in)]
        err = open(self.tmp / f"backend-{tag}.err", "w")
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=err)
        b = FakeBackend(self, tag, p, qlog)
        self.backends.append(b)
        return b

    def cleanup(self):
        for c in self.clients:
            if c.p.poll() is None:
                c.p.kill()
                c.p.wait()
        for b in self.backends:
            if b.proc.poll() is None:
                b.proc.kill()
                b.proc.wait()
            try:
                os.kill(b.info["engine_pid"], signal.SIGKILL)
            except (OSError, TypeError, KeyError):
                pass


@pytest.fixture
def svc(tmp_path, monkeypatch):
    s = Svc(tmp_path)
    for k in ("KGSERVICE_RUN_DIR", "KGSERVICE_POLL", "KGSERVICE_WAIT"):
        monkeypatch.setenv(k, s.env[k])       # goarena's KataGo spawns the client with os.environ
    monkeypatch.delenv("KGSERVICE_LOG", raising=False)
    yield s
    s.cleanup()


def goarena_katago(svc):
    from goarena.katago import KataGo, KataGoConfig
    return KataGo(KataGoConfig(binary=str(CLIENT), model=str(svc.model), config=str(svc.cfg)))


# (a) ------------------------------------------------------------------------------------------
def test_goarena_katago_end_to_end(svc):
    from goarena.board import Board
    from goarena.referee import review_moves, score_final
    a = svc.start_backend("A")
    kg = goarena_katago(svc)
    try:
        b = Board(9, 7.5)
        for mv in ("E5", "C3", "G7"):
            b.play_coord(mv)
        r = kg.analyze(b, 50, policy=True, ownership=True)
        assert r["rootInfo"]["visits"] == 50 and r["turnNumber"] == 3 and r["fakeEngine"] == "A"
        assert len(r["policy"]) == 82 and len(r["ownership"]) == 81
        rs = kg.analyze(b, 10, analyze_turns=[0, 1, 2, 3], priority=-10)
        assert sorted(rs) == [0, 1, 2, 3]
        rows = review_moves([(m.color, m.point) for m in b.moves], 9, 7.5, kg, visits=10)
        assert [row["ply"] for row in rows] == [1, 2, 3]
        assert score_final(b, kg, visits=10)["method"] == "area+katago-dead-stones"
    finally:
        kg.close()
    assert kg._proc.returncode == 0                       # clean exit when stdin closes
    sent = a.queries()
    assert sent and all(q["id"].startswith("c1:q") for q in sent)
    assert {q["priority"] for q in sent if "priority" in q} == {0, -10}
    assert all(q.get("id") != "c1:q1" or q["includePolicy"] for q in sent)


# (b) ------------------------------------------------------------------------------------------
def test_backend_killed_mid_query_resends_exactly_once(svc):
    a = svc.start_backend("A", delay=1.0, deadline_in=3000)    # preferred: later deadline
    b = svc.start_backend("B", delay=0.05, deadline_in=2000)
    c = RawClient(svc)
    c.send(q9("q1"))
    wait_for(lambda: any(q["id"].endswith(":q1") for q in a.queries()), what="q1 at A")
    a.proc.kill()
    a.proc.wait()
    (r,) = c.wait_finals("q1")
    assert r["fakeEngine"] == "B" and r["rootInfo"]["visits"] == 10
    time.sleep(1.2)                       # longer than A's search: nothing else may show up
    assert len(c.finals("q1")) == 1
    c.send(q9("q2"))
    assert c.wait_finals("q2")[0]["fakeEngine"] == "B"
    assert [q["id"] for q in b.queries()] == ["c1:q1", "c1:q2"]
    c.wait_log("resent 1 unfinished")
    assert c.close() == 0


def test_goarena_katago_survives_backend_kill(svc):
    from goarena.board import Board
    a = svc.start_backend("A", delay=0.5, deadline_in=3000)
    svc.start_backend("B", delay=0.02, deadline_in=2000)
    kg = goarena_katago(svc)
    out = {}
    try:
        b = Board(9, 7.5)
        for mv in ("E5", "C3", "G7", "C7"):
            b.play_coord(mv)
        th = threading.Thread(target=lambda: out.update(res=kg.analyze(b, 20, analyze_turns=[0, 1, 2, 3, 4])))
        th.start()
        wait_for(lambda: a.queries(), what="query at A")
        time.sleep(0.7)                   # A answers turn 0, then dies during turn 1
        a.proc.kill()
        a.proc.wait()
        th.join(20)
        res = out["res"]
        assert sorted(res) == [0, 1, 2, 3, 4]
        assert {r["fakeEngine"] for r in res.values()} == {"A", "B"}
        assert kg.analyze(b, 5)["fakeEngine"] == "B"
    finally:
        kg.close()


# (c) ------------------------------------------------------------------------------------------
def test_colliding_ids_on_one_backend(svc):
    a = svc.start_backend("A", delay=0.3, partials=1)
    c1, c2 = RawClient(svc), RawClient(svc)
    c1.send(q9("q1", nmoves=1, visits=11))
    c2.send(q9("q1", nmoves=3, visits=22))
    c1.send(q9("t", nmoves=3, visits=5, analyzeTurns=[0, 1]))
    c2.send(q9("t", nmoves=3, visits=6, analyzeTurns=[2, 3]))
    (r1,), (r2,) = c1.wait_finals("q1"), c2.wait_finals("q1")
    assert (r1["rootInfo"]["visits"], r1["turnNumber"]) == (11, 1)
    assert (r2["rootInfo"]["visits"], r2["turnNumber"]) == (22, 3)
    t1, t2 = c1.wait_finals("t", 2), c2.wait_finals("t", 2)
    assert sorted(m["turnNumber"] for m in t1) == [0, 1] and {m["rootInfo"]["visits"] for m in t1} == {5}
    assert sorted(m["turnNumber"] for m in t2) == [2, 3] and {m["rootInfo"]["visits"] for m in t2} == {6}
    assert c1.partials("q1") and all(m["rootInfo"]["visits"] <= 11 for m in c1.partials("q1"))
    time.sleep(0.4)
    assert len(c1.finals("q1")) == len(c2.finals("q1")) == 1 and len(c1.finals("t")) == len(c2.finals("t")) == 2
    ids = sorted(q["id"] for q in a.queries())
    assert ids == ["c1:q1", "c1:t", "c2:q1", "c2:t"]
    assert c1.close() == 0 and c2.close() == 0


# (d) ------------------------------------------------------------------------------------------
def _handshake(info, first_line: dict | str):
    s = socket.create_connection((info["host"], info["port"]), timeout=5)
    line = first_line if isinstance(first_line, str) else json.dumps(first_line)
    s.sendall((line + "\n").encode())
    f = s.makefile("rb")
    reply = json.loads(f.readline())
    rest = f.readline() if reply.get("kgservice") == "error" else None   # refused: backend hangs up
    s.close()
    return reply, rest


def test_token_required(svc):
    a = svc.start_backend("A")
    info = a.info
    path = Path(info["_path"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(svc.run.stat().st_mode) == 0o700
    model = model_key(svc.model)
    for bad in ({"kgservice": "hello", "token": "0" * 64, "model": model},
                {"kgservice": "hello", "model": model},
                q9("sneak")):
        reply, rest = _handshake(info, bad)
        assert reply == {"kgservice": "error", "error": "authentication failed"} and rest == b""
    reply, _ = _handshake(info, {"kgservice": "hello", "token": info["token"], "model": "other.bin.gz"})
    assert "model mismatch" in reply["error"]
    reply, _ = _handshake(info, {"kgservice": "hello", "token": info["token"], "model": model})
    assert reply["kgservice"] == "welcome" and reply["backend"] == a.id
    assert not any(q.get("id", "").endswith("sneak") for q in a.queries())
    # a client holding a wrong token gets nothing from this backend and fails the query after the wait
    rv = {k: v for k, v in info.items() if not k.startswith("_")}
    write_json_private(path, dict(rv, token="f" * 64))
    c = RawClient(svc, env={"KGSERVICE_WAIT": "1"})
    c.send(q9("q1"))
    (r,) = c.wait_finals("q1")
    assert "no live backend" in r["error"]
    c.wait_log("authentication failed")
    assert not a.queries()
    assert c.close() == 0


# (e) ------------------------------------------------------------------------------------------
def test_draining_moves_client_without_losing_queries(svc):
    a = svc.start_backend("A", delay=0.8, deadline_in=3000)
    b = svc.start_backend("B", delay=0.05, deadline_in=2000)
    c = RawClient(svc)
    c.send(q9("q1"))
    wait_for(lambda: any(q["id"] == "c1:q1" for q in a.queries()), what="q1 at A")
    a.proc.send_signal(signal.SIGUSR1)
    wait_for(lambda: (a.rendezvous() or {}).get("draining"), what="A draining flag")
    c.wait_log(f"using backend {b.id}")
    c.send(q9("q2"))
    assert c.wait_finals("q2")[0]["fakeEngine"] == "B"
    assert c.wait_finals("q1")[0]["fakeEngine"] == "A"       # in-flight work finishes on A
    assert "q1" not in [q["id"].split(":", 1)[1] for q in b.queries()]
    c.wait_log(f"closed drained connection to {a.id}")
    a.proc.send_signal(signal.SIGTERM)
    assert a.proc.wait(10) == 0 and a.rendezvous() is None
    # the only backend drains: keep using it until a fresh one appears, then move
    b.proc.send_signal(signal.SIGUSR1)
    wait_for(lambda: (b.rendezvous() or {}).get("draining"), what="B draining flag")
    c.wait_log(f"backend {b.id} is draining")
    c.send(q9("q3"))
    assert c.wait_finals("q3")[0]["fakeEngine"] == "B"
    cc = svc.start_backend("C", delay=0.05, deadline_in=2500)
    c.wait_log(f"using backend {cc.id}")
    c.send(q9("q4"))
    assert c.wait_finals("q4")[0]["fakeEngine"] == "C"
    time.sleep(0.3)
    assert [len(c.finals(q)) for q in ("q1", "q2", "q3", "q4")] == [1, 1, 1, 1]
    assert c.close() == 0


# (f) ------------------------------------------------------------------------------------------
def test_analyze_turns_failover_between_turns(svc):
    a = svc.start_backend("A", delay=0.3, partials=1, deadline_in=3000)
    b = svc.start_backend("B", delay=0.02, deadline_in=2000)
    c = RawClient(svc)
    turns = list(range(8))
    c.send(q9("r1", nmoves=7, analyzeTurns=turns, includePolicy=True))
    c.wait_finals("r1", 2)
    a.proc.kill()
    a.proc.wait()
    c.wait_finals("r1", 8)
    time.sleep(0.4)
    finals = c.finals("r1")
    assert sorted(m["turnNumber"] for m in finals) == turns              # each turn exactly once
    from_a = {m["turnNumber"] for m in finals if m["fakeEngine"] == "A"}
    from_b = {m["turnNumber"] for m in finals if m["fakeEngine"] == "B"}
    assert len(from_a) >= 2 and from_b
    (resent,) = b.queries()
    assert set(resent["analyzeTurns"]) == from_b and not from_a & set(resent["analyzeTurns"])
    c.wait_log(f"query r1: resending {len(from_b)} of 8 turns")
    assert c.close() == 0


def test_engine_exit_stops_backend(svc):
    a = svc.start_backend("A")
    os.kill(a.info["engine_pid"], signal.SIGKILL)
    assert a.proc.wait(10) == 1 and a.rendezvous() is None


def test_client_waits_for_first_backend(svc):
    c = RawClient(svc)
    c.send(q9("q1"))
    time.sleep(0.3)
    assert not c.finals("q1")
    svc.start_backend("A")
    assert c.wait_finals("q1")[0]["fakeEngine"] == "A"
    assert c.close() == 0


def test_client_refuses_non_black_perspective(svc):
    base = [str(CLIENT), "analysis", "-config", str(svc.cfg), "-model", str(svc.model)]
    for extra in (["-override-config", "reportAnalysisWinratesAs=SIDETOMOVE"], []):
        r = subprocess.run(base + extra, input="", capture_output=True, text=True, env=svc.env, timeout=20)
        assert r.returncode == 2 and "BLACK" in r.stderr


# (g) ------------------------------------------------------------------------------------------
class FakeSlurm:
    def __init__(self):
        self.jobs: list[dict] = []
        self.submitted: list[tuple[str, str]] = []
        self.fail = False

    def squeue(self):
        if self.fail:
            raise RuntimeError("slurmctld down")
        return [dict(j) for j in self.jobs]

    def sbatch(self, model, config):
        self.submitted.append((model, config))
        jid = str(9000 + len(self.submitted))
        self.jobs.append({"id": jid, "name": job_name(model), "state": "PENDING", "start": None, "end": None})
        return jid

    def scancel(self, ids):
        self.jobs = [j for j in self.jobs if j["id"] not in ids]


def test_parse_squeue():
    out = ("2401|kgb-kata1-net|RUNNING|2026-10-05T18:00:00|2026-10-05T19:00:00\n"
           "2402|kgb-kata1-net|PENDING|N/A|N/A\n")
    j1, j2 = parse_squeue(out)
    assert j1["id"] == "2401" and j1["state"] == "RUNNING" and j1["end"] - j1["start"] == 3600
    assert j2["start"] is None and j2["state"] == "PENDING"
    assert job_name("engines/models/kata1-net.bin.gz") == "kgb-kata1-net"


def test_decide_rules():
    now = 10_000.0
    bk = lambda **kw: dict({"id": "kgb-1", "slurm_job_id": "1", "deadline": now + 3000, "draining": False}, **kw)
    job = lambda jid, state, start=None: {"id": jid, "name": "kgb-x", "state": state, "start": start, "end": None}
    assert decide(now, [bk()], [job("1", "RUNNING", now - 600)], 600, 2)[0] == "ok"
    assert decide(now, [], [], 600, 2)[0] == "submit"
    assert decide(now, [bk(deadline=now + 500)], [job("1", "RUNNING", now - 3100)], 600, 2)[0] == "submit"
    assert decide(now, [bk(draining=True)], [job("1", "RUNNING")], 600, 2)[0] == "submit"
    assert decide(now, [bk(deadline=now + 500)], [job("1", "RUNNING"), job("2", "PENDING")], 600, 2)[0] == "wait"
    # running but not serving yet (engine loading) counts as starting ...
    assert decide(now, [bk(deadline=now + 500)], [job("1", "RUNNING"), job("2", "RUNNING", now - 30)], 600, 2)[0] == "wait"
    # ... until the start grace is over; then the job only occupies a slot
    assert decide(now, [bk(deadline=now + 500)], [job("1", "RUNNING"), job("2", "RUNNING", now - 900)], 600, 2)[0] == "full"
    assert decide(now, [], [job("1", "RUNNING", now - 900), job("2", "RUNNING", now - 900)], 600, 3)[0] == "submit"
    assert decide(now, [], [job("1", "COMPLETED")], 600, 1)[0] == "submit"


def test_keepalive_cycle_with_injected_slurm(tmp_path):
    rdir = tmp_path / "run"
    rdir.mkdir()
    model = "engines/models/kata1-net.bin.gz"
    clock = [100_000.0]
    sl = FakeSlurm()
    ka = Keepalive(model, "cfg", sl, rdir=rdir, lead=600, max_jobs=2, start_grace=600, clock=lambda: clock[0])

    def rendezvous(jid, deadline, draining=False, pid=None):
        write_json_private(rdir / f"kgb-{jid}.json", {
            "id": f"kgb-{jid}", "model": model_key(model), "slurm_job_id": jid, "pid": pid or os.getpid(),
            "hostname": socket.gethostname(), "deadline": deadline, "draining": draining, "host": "127.0.0.1",
            "port": 1, "token": "t"})

    assert ka.tick()["action"] == "submit" and sl.submitted == [(model, "cfg")]
    assert ka.tick()["action"] == "wait"                        # pending: never a duplicate
    sl.jobs[0].update(state="RUNNING", start=clock[0])
    clock[0] += 20
    assert ka.tick()["action"] == "wait"                        # running, engine still loading
    rendezvous("9001", clock[0] + 3580)
    assert ka.tick()["action"] == "ok"
    clock[0] += 3000                                            # 580 s left < lead
    r = ka.tick()
    assert r["action"] == "submit" and r["job"] == "9002" and len(sl.submitted) == 2
    assert ka.tick()["action"] == "wait"
    sl.jobs[1].update(state="RUNNING", start=clock[0] - 700)    # stuck: running, never served
    clock[0] += 100
    assert ka.tick()["action"] == "full"                        # max-jobs respected
    # job 9001 ends: its rendezvous is stale; 9002 is cancelled; a dead-pid file is stale too
    sl.jobs = []
    dead = subprocess.Popen(["true"])
    dead.wait()
    rendezvous("7777", clock[0] + 3000, pid=dead.pid)
    os.utime(rdir / "kgb-9001.json", (0, 0))
    r = ka.tick()
    assert sorted(r["removed"]) == ["kgb-7777 (process gone)", "kgb-9001 (job finished)"]
    assert r["action"] == "submit" and not list(rdir.glob("*.json"))
    clock[0] += 10
    sl.jobs = []                                                # sbatch accepted but not visible yet
    assert ka.tick()["action"] == "wait"                        # min gap between submissions
    sl.fail = True
    clock[0] += 120
    assert ka.tick()["action"] == "wait" and len(sl.submitted) == 3
    # a draining backend with lots of time left still triggers a successor
    sl.fail = False
    rendezvous("9100", clock[0] + 3000, draining=True)
    sl.jobs = [{"id": "9100", "name": job_name(model), "state": "RUNNING", "start": clock[0], "end": None}]
    assert ka.tick()["action"] == "submit"


def test_clean_stale_keeps_live_and_unknown(tmp_path):
    rdir = tmp_path / "run"
    rdir.mkdir()
    write_json_private(rdir / "kgb-1.json", {"id": "kgb-1", "pid": os.getpid(), "hostname": socket.gethostname(),
                                             "slurm_job_id": "1"})
    os.utime(rdir / "kgb-1.json", (0, 0))
    assert clean_stale(rdir, None, time.time()) == []                       # squeue failed: keep
    assert clean_stale(rdir, [{"id": "1", "state": "RUNNING"}], time.time()) == []
    assert clean_stale(rdir, [], time.time()) == ["kgb-1 (job finished)"]
