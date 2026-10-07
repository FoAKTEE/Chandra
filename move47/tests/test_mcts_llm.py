"""MCTS v2 asynchronous LLM expansion service (mcts/llm.py) with fake and mock workers (no model)."""
import json
import threading
import time

import pytest

from gotree.dag import DAG
from gotree.jobs import validate
from gotree.memory import Memory
from gotree.position import Position, coord, point, sym_maps
from gotree.workers import JobResult, MockWorker, Worker
from mcts.board import Board, board_from_moves
from mcts.cli import MIDGAME_9
from mcts.llm import FL_EXT, LLMConfig, LLMService, canonical_of, classify_failure
from mcts.tree import MCTS, MCTSConfig


def cfg(**kw):
    base = dict(max_nodes=300_000, n_thr=10**9, hook_depth=1, beta=0.5, lam=0.5)
    base.update(kw)
    return MCTSConfig(**base)


def lcfg(**kw):
    base = dict(workers=4, dispatch_delay_s=0.0, refute=False, scouts=True, poll_s=0.02)
    base.update(kw)
    return LLMConfig(**base)


class FrameWorker(Worker):
    """Answers expand jobs in the job's (canonical) frame: the first legal point of the job board
    (row-major) gets prior 0.9, the last one 0.1, value 0.8.  Other kinds go to MockWorker."""
    name = "frame"

    def __init__(self, delay=0.0):
        self.jobs, self.delay, self.mock = [], delay, MockWorker()
        self.lock = threading.Lock()

    def run(self, job):
        with self.lock:
            self.jobs.append(job)
        if self.delay:
            time.sleep(self.delay)
        if job.kind not in ("expand", "more", "refute"):
            return self.mock.run(job)
        legal = [p for p in job.pos.legal_moves() if p is not None]
        s = job.pos.size
        raw = {"candidates": [{"move": coord(legal[0], s), "prior": 0.9, "why": "first"},
                              {"move": coord(legal[-1], s), "prior": 0.1, "why": "last"}],
               "value": {"winrate": 0.8, "confidence": "low", "why": "fake"}}
        return JobResult(True, validate(job, raw), worker=self.name,
                         usage={"input": 100, "output": 20, "cost_usd": 0.25})


class Learner:
    def __init__(self):
        self.ext = []

    def observe_external(self, position, source, priors, value):
        self.ext.append((position, source, dict(priors), value))


def service(tmp_path, worker, **kw):
    learner = kw.pop("learner", None)
    dag, mem = DAG(str(tmp_path / "dag.db")), Memory(str(tmp_path / "memory.db"))
    logs = []
    svc = LLMService(worker, dag, mem, lcfg(**kw), learner=learner, log=logs.append,
                     record=tmp_path / "llm-jobs.jsonl", jobs_dir=tmp_path / "jobs")
    svc.logs = logs
    return svc


def asymmetric_position():
    """A 9x9 position whose canonical form is NOT its own orientation (s != 0)."""
    for moves in (["C3", "D7", "G4"], ["B2", "E7", "H5", "C6"], ["G7", "C4", "E3"]):
        b, h = board_from_moves(9, [point(m, 9) for m in moves])
        _, can, s = canonical_of(b)
        if s != 0 and all(can.cells != can.transformed(t).cells for t in range(1, 8)):
            return b, h
    raise AssertionError("no asymmetric test position")


def test_root_expand_job_is_mapped_back_from_the_canonical_frame(tmp_path):
    b, h = asymmetric_position()
    dkey, can, s = canonical_of(b)
    assert s != 0
    worker, learner = FrameWorker(), Learner()
    svc = service(tmp_path, worker, learner=learner)
    eng = MCTS(b, history=h, config=cfg(hook_depth=0))
    svc.attach(eng)
    svc.start()
    assert svc.wait_idle(20)
    job = worker.jobs[0]
    assert job.kind == "expand" and job.key == dkey and job.pos.cells == can.cells and job.params["u"] == 4
    c_first = [p for p in job.pos.legal_moves() if p is not None][0]
    real = sym_maps(9)[1][s][c_first]
    # independent check of the frame mapping: playing the real move then rotating = the canonical move
    pos = b.to_position()
    assert pos.play(real).transformed(s).cells == can.play(c_first).cells
    ch = {c["move"]: c for c in eng.children(eng.root)}
    assert eng.a.flags[eng.root] & FL_EXT
    assert ch[real]["prior"] == pytest.approx(0.5 * ch[real]["prior_learned"] + 0.5 * 0.9, abs=1e-5)
    assert eng.a.nx[eng.root] == 1 and eng.a.vext[eng.root] == pytest.approx(2 * 0.8 - 1)
    # written to the DAG as gotree v1 does; one record line with usage
    node = svc.dag.node(dkey)
    assert node["static_value"] == pytest.approx(0.8) and node["expansions"] == 1
    legal = [p for p in job.pos.legal_moves() if p is not None]
    assert {e.move: e.source for e in svc.dag.edges(dkey)} == {legal[0]: "llm", legal[-1]: "llm"}
    rec = [json.loads(x) for x in (tmp_path / "llm-jobs.jsonl").read_text().splitlines()]
    assert rec[0]["ok"] and rec[0]["applied"] == 1 and rec[0]["usage"]["cost_usd"] == 0.25
    st = svc.stats()
    assert st["launched"] == 1 and st["ok"] == 1 and st["applied"] == 1 and st["cost_usd"] == 0.25
    # the learner saw the evaluation in the real frame
    assert learner.ext and learner.ext[0][1] == "llm" and learner.ext[0][2][real] == pytest.approx(0.9)
    assert learner.ext[0][3] == pytest.approx(0.8) and learner.ext[0][0].key == b.key
    assert svc.root_llm_priors()[real] == pytest.approx(0.9)
    svc.close()


def test_events_from_a_search_become_jobs_applied_mid_search(tmp_path):
    b, h = board_from_moves(9, MIDGAME_9)
    worker = FrameWorker(delay=0.01)
    svc = service(tmp_path, worker)
    eng = MCTS(b, history=h, config=cfg(n_thr=300))
    svc.attach(eng)
    svc.start()
    svc.searching = True
    r = eng.search(sims=6000, threads=2)
    svc.searching = False
    assert svc.wait_idle(30)
    st = svc.stats()
    assert r["events"] > 10 and st["events"] >= r["events"] - 1
    assert st["launched"] == len(worker.jobs) >= 5 and st["failed"] == 0
    assert st["applied"] >= st["ok"] and st["applied_mid_search"] >= 1
    kinds = {j.kind for j in worker.jobs}
    assert kinds == {"expand"}                        # 9x9: v1 regions() has no scouts below 13x13
    # every engine node whose canonical position was evaluated carries the external result
    evaluated = {j.key for j in worker.jobs}
    nodes = [k for k, d in svc._seen.items() if d in evaluated]
    assert len(nodes) >= len(evaluated)
    for k in nodes:
        i = eng.find(k)
        assert i >= 0 and eng.a.flags[i] & FL_EXT and eng.a.nx[i] >= 1
    svc.close()


def test_dag_cache_hit_in_another_orientation_needs_no_model_call(tmp_path):
    b, h = asymmetric_position()
    w1 = FrameWorker()
    svc1 = service(tmp_path, w1)
    eng1 = MCTS(b, history=h, config=cfg(hook_depth=0))
    svc1.attach(eng1)
    svc1.start()
    assert svc1.wait_idle(20) and len(w1.jobs) == 1
    svc1.close()
    dkey, can, s = canonical_of(b)
    c_first = [p for p in can.legal_moves() if p is not None][0]
    # the same position mirrored: same DAG key, another symmetry
    t = 1
    b2 = Board.from_position(b.to_position().transformed(t))
    dkey2, _, s2 = canonical_of(b2)
    assert dkey2 == dkey and s2 != s
    w2 = FrameWorker()
    svc2 = service(tmp_path, w2)
    eng2 = MCTS(b2, config=cfg(hook_depth=0))
    svc2.attach(eng2)
    svc2.start()
    assert svc2.wait_idle(10)
    assert w2.jobs == [] and svc2.stats()["cache_hits"] == 1 and svc2.stats()["launched"] == 0
    real2 = sym_maps(9)[1][s2][c_first]
    assert b2.to_position().play(real2).transformed(s2).cells == can.play(c_first).cells
    ch = {c["move"]: c for c in eng2.children(eng2.root)}
    assert ch[real2]["prior"] == pytest.approx(0.5 * ch[real2]["prior_learned"] + 0.5 * 0.9, abs=1e-5)
    assert eng2.a.nx[eng2.root] == 1
    svc2.close()


def test_symmetric_nodes_share_one_job_and_duplicate_events_are_ignored(tmp_path):
    worker = FrameWorker()
    svc = service(tmp_path, worker)
    eng = MCTS(Board(9), config=cfg())                 # empty board: the root's children come in symmetric classes
    events = []
    svc.attach(eng)
    hook = eng.on_expand
    eng.on_expand = lambda ev: (events.append(ev), hook(ev))
    svc.pause()
    svc.start()
    eng.search(sims=3000, threads=2)
    assert svc.wait_idle(10, queue_too=False)
    q = svc.queued()
    keys = [k for r in q for k in r["keys"]]
    assert len(q) == len({r["dag_key"] for r in q}) and len(keys) == len(set(keys))
    assert any(len(r["keys"]) >= 2 for r in q)         # e.g. the four 3-3 points share one request
    n_req = len(q)
    for ev in events[:5]:                              # the same events again: nothing new
        svc.on_expand(ev)
    assert svc.wait_idle(10, queue_too=False) and len(svc.queued()) == n_req
    svc.resume()
    assert svc.wait_idle(30)
    st = svc.stats()
    assert len(worker.jobs) == n_req == st["launched"] and st["followers"] >= len(keys) - n_req
    assert st["applied"] == len(keys)                  # every node got its canonical position's result
    for k in keys:
        i = eng.find(k)
        assert i >= 0 and eng.a.flags[i] & FL_EXT
    svc.close()


def test_requests_outside_the_new_root_are_dropped_after_advance(tmp_path):
    b, h = board_from_moves(9, MIDGAME_9)
    svc = service(tmp_path, FrameWorker())
    eng = MCTS(b, history=h, config=cfg(n_thr=150))
    svc.attach(eng)
    svc.pause()
    svc.start()
    eng.search(sims=8000, threads=2)
    assert svc.wait_idle(10, queue_too=False)
    before = svc.queued()
    assert len(before) > 5
    best = eng.best_move()
    eng.advance(best)
    reply = max(eng.children(eng.root), key=lambda c: c["n"])["move"]
    eng.advance(reply)
    new_root = int(eng.a.key[eng.root])
    svc.new_root()
    after = svc.queued()
    st = svc.stats()
    assert st["stale_dropped"] > 0 and len(after) < len(before)
    root_req = [r for r in after if new_root in r["keys"]]
    assert root_req and root_req[0]["cls"] == 0 and root_req[0]["kind"] == "expand"
    assert all(min(r["depths"]) >= 0 for r in after)
    svc.resume()
    assert svc.wait_idle(30)
    assert eng.a.flags[eng.root] & FL_EXT              # the new root got its evaluation
    svc.close()


class FlakyWorker(FrameWorker):
    """1st call: rate limit in the error text; 2nd: overload only in the session log; 3rd: exception."""
    name = "flaky"

    def __init__(self, jobs_dir):
        super().__init__()
        self.jobs_dir, self.calls, self.times = jobs_dir, 0, []

    def run(self, job):
        with self.lock:
            self.calls += 1
            n = self.calls
            self.times.append(time.time())
        if n == 1:
            return JobResult(False, error="session ended (rc=1) without an accepted answer: API Error: 429 "
                                          '{"type":"error","error":{"type":"rate_limit_error"}}', worker=self.name)
        if n == 2:
            jd = self.jobs_dir / f"{job.id:06d}-{job.kind}-abcdef"
            jd.mkdir(parents=True)
            (jd / "session.jsonl").write_text(json.dumps({"type": "system", "subtype": "init"}) + "\n" + json.dumps(
                {"type": "result", "is_error": True, "result": "API Error: 529 Overloaded", "total_cost_usd": 0.01,
                 "usage": {"input_tokens": 7, "output_tokens": 1}}) + "\n")
            return JobResult(False, error="session ended (rc=1) without an accepted answer", worker=self.name)
        if n == 3:
            raise RuntimeError("worker blew up")
        return super().run(job)


def test_rate_limits_back_off_lower_w_retry_and_never_crash_the_search(tmp_path):
    b, h = board_from_moves(9, MIDGAME_9)
    worker = FlakyWorker(tmp_path / "jobs")
    svc = service(tmp_path, worker, workers=4, backoff_base=0.3, backoff_max=0.6, fail_streak_backoff=1,
                  ramp_up_after=2, max_attempts=3)
    eng = MCTS(b, history=h, config=cfg(hook_depth=0))
    svc.attach(eng)
    svc.start()
    r = eng.search(sims=3000, threads=2)               # runs while the service fails
    assert r["sims"] == 3000
    t_end = time.time() + 20
    while time.time() < t_end and svc.stats()["ok"] < 1:
        time.sleep(0.05)
    st = svc.stats()
    assert st["rate_limited"] == 1 and st["overloaded"] == 1 and st["failed"] == 3 and st["ok"] == 1
    assert st["retried"] == 3 and st["cost_usd"] == pytest.approx(0.26)   # the overloaded session's cost counted
    assert worker.times[1] - worker.times[0] >= 0.29 and worker.times[2] - worker.times[1] >= 0.59
    rec = [json.loads(x) for x in (tmp_path / "llm-jobs.jsonl").read_text().splitlines()]
    assert [x["fail_class"] for x in rec] == ["rate_limit", "overloaded", "exception", None]
    assert rec[0]["w_cur"] == 2 and rec[1]["w_cur"] == 1 and rec[2]["w_cur"] == 1   # W halved, floor 1
    assert eng.a.flags[eng.root] & FL_EXT
    # successes raise W again
    eng.search(sims=3000, threads=2)
    svc.cfg.ramp_up_after = 1
    eng.cfg.n_thr = 200
    eng.search(sims=6000, threads=2)
    assert svc.wait_idle(30)
    assert svc.stats()["ok"] >= 3 and svc.stats()["w_cur"] >= 2
    svc.close()


def test_failure_classes_from_session_logs(tmp_path):
    jd = tmp_path / "job"
    jd.mkdir()
    (jd / "session.jsonl").write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "API Error: Claude AI usage limit reached|1760000000"}]}}) + "\n")
    assert classify_failure(JobResult(False, error="session ended (rc=1)"), jd) == ("rate_limit", 1760000000.0)
    (jd / "session.jsonl").write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "the 429 tokens of reading say D4 is rate-limited by ko"}]}}) + "\n")
    assert classify_failure(JobResult(False, error="session ended (rc=0) without an accepted answer"), jd)[0] == \
        "no_answer"                                     # the model's own text is not an API error
    assert classify_failure(JobResult(False, error="session ended (rc=-9) without an accepted answer"), None)[0] == \
        "timeout"
    assert classify_failure(JobResult(False, error="invalid answer: x"), None)[0] == "invalid"
    assert classify_failure(JobResult(False, error="cannot start claude: no such file"), None)[0] == "start_failed"


def test_refute_of_the_top_move_and_lessons_after_a_decision(tmp_path):
    b, h = board_from_moves(9, MIDGAME_9)
    svc = service(tmp_path, MockWorker(), refute=True, refute_after_s=0.0)
    eng = MCTS(b, history=h, config=cfg(hook_depth=0))
    svc.attach(eng)
    svc.start()
    assert svc.wait_idle(10)                           # the root's expand first
    svc._tick_t = 0.0

    def stop():
        svc.tick()
        return False
    r = eng.search(time_s=1.5, threads=2, stop=stop)    # tick() is rate-limited to once a second
    assert svc.wait_idle(20)
    assert svc.request_abstract(r["moves"], r["best_move"], r["q"], r["root_n"], label="t1")
    assert svc.wait_idle(20)
    rec = [json.loads(x) for x in (tmp_path / "llm-jobs.jsonl").read_text().splitlines()]
    assert [x["kind"] for x in rec] == ["expand", "refute", "abstract"] and all(x["ok"] for x in rec)
    assert rec[2]["lessons"] >= 1
    assert svc.mem.q("SELECT COUNT(*) AS n FROM lessons")[0]["n"] >= 1
    refuted = svc.dag.q("SELECT key FROM mcts_tags WHERE kind='refute'")
    assert len(refuted) == 1
    assert any(e.source == "refute" for e in svc.dag.edges(refuted[0]["key"]))
    child = [c for c in eng.children(eng.root) if canonical_of(b.played(c["move"]))[0] == refuted[0]["key"]]
    assert child and eng.a.flags[child[0]["child"]] & FL_EXT   # the refute's answers reached that move's node
    # the abstract job's context is in the canonical frame and lists the LLM priors
    job = svc.dag.q1("SELECT * FROM jobs WHERE kind='abstract'")
    assert job["status"] == "done"
    svc.close()


def test_job_cap_and_queue_cap(tmp_path):
    b, h = board_from_moves(9, MIDGAME_9)
    worker = FrameWorker()
    svc = service(tmp_path, worker, max_jobs=3, queue_cap=5, workers=2)
    eng = MCTS(b, history=h, config=cfg(n_thr=100))
    svc.attach(eng)
    svc.start()
    eng.search(sims=6000, threads=2)
    assert svc.wait_idle(20)
    st = svc.stats()
    assert len(worker.jobs) == 3 == st["launched"] and st["queue"] <= 5 and st["cap_dropped"] > 0
    svc.close()
