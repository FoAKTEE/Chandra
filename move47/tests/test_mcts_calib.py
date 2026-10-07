"""MCTS v2 model values (node move47::mcts-calib), no model: root breadth and root noise in the
engine, re-armable hooks, the exact root-subtree query, the `searching` property, stand-in values
for nodes without a model value (sign), the decision rule with its bounded extension, the
calibration of model values (fit, learner, engine) and the service's root breadth, boost and
re-arming of dropped requests."""
import json
import threading
import time

import numpy as np
import pytest

from gotree.dag import DAG
from gotree.jobs import validate
from gotree.memory import Memory
from gotree.position import coord, point
from gotree.workers import JobResult, MockWorker, Worker
from mcts.board import Board, board_from_moves
from mcts.cli import MIDGAME_9
from mcts.decide import DecideConfig, choose, decide
from mcts.features import move_priors
from mcts.hl import OnlineLearner
from mcts.hl.mix import A_LO, apply_calib, fit_calib
from mcts.llm import CLS_TOP, FL_EXT, LLMConfig, LLMService, Target, canonical_of, to_real
from mcts.tree import FL_EVCHILD, MCTS, MCTSConfig, apply_calibration
from mcts.weights import load_default

from test_mcts_hl import FAST, random_positions


def cfg(**kw):
    kw.setdefault("max_nodes", 300_000)
    return MCTSConfig(**kw)


def midgame():
    return board_from_moves(9, MIDGAME_9)


# ================================================================== engine: root breadth and noise
def test_root_breadth_gives_model_moves_their_minimum_visits(tmp_path):
    b, h = midgame()
    plain = MCTS(b, history=h, config=cfg(seed=1))
    plain.search(sims=200, threads=1)
    low = [c["move"] for c in sorted(plain.children(plain.root), key=lambda c: c["prior"]) if c["move"] is not None][:2]
    plain.search(sims=19800, threads=1)
    n_plain = {c["move"]: c["n"] for c in plain.children(plain.root)}

    eng = MCTS(b, history=h, config=cfg(seed=1))
    eng.search(sims=200, threads=1)
    assert eng.set_root_breadth({low[0]: "candidate", coord(low[1], 9): "explore"}) == 2
    assert eng.root_breadth == {low[0]: "candidate", low[1]: "explore"}
    eng.search(sims=19800, threads=4)
    got = {c["move"]: c["n"] for c in eng.children(eng.root)}
    N = int(eng.a.n[eng.root])
    need_c, need_x = max(64, 0.01 * N), max(32, 0.005 * N)       # defaults: 1% / 0.5% of the root's visits
    assert got[low[0]] >= 0.95 * need_c > n_plain[low[0]] + 50
    assert got[low[1]] >= 0.95 * need_x > n_plain[low[1]] + 25
    rows = {m["move"]: m for m in eng.root_stats()}
    assert rows[low[0]]["breadth"] == "candidate" and rows[low[1]]["breadth"] == "explore"
    # persisted with the tree; cleared when the root moves
    re = MCTS.load(eng.save(tmp_path / "t.npz"))
    assert re.root_breadth == eng.root_breadth
    eng.advance(eng.best_move())
    assert eng.root_breadth == {}


def test_root_noise_spreads_visits_to_low_prior_moves():
    b, h = midgame()

    def low_half(noise):
        eng = MCTS(b, history=h, config=cfg(seed=2, root_noise=noise))
        eng.search(sims=8000, threads=1)
        ch = sorted(eng.children(eng.root), key=lambda c: c["prior"])
        return sum(c["n"] for c in ch[:len(ch) // 2])
    assert low_half(0.25) > 3 * low_half(0.0)


# ================================================================== engine: hooks, subtree, searching
def test_rearm_fires_the_hook_again():
    """Re-armed nodes fire again on their next visit (and only those): the root's children are
    hooked once each; half of them are re-armed; after more search, exactly the re-armed children
    that were visited again have a second event."""
    events = []
    eng = MCTS(Board(9), config=cfg(n_thr=10**9, hook_depth=1), on_expand=events.append)
    eng.search(sims=3000, threads=2)
    keys = [e.key for e in events]
    assert len(keys) == len(set(keys)) == 82              # once per node: root + 81 children
    ch = [c for c in eng.children(eng.root) if c["child"] >= 0]
    rearmed = {int(eng.a.key[c["child"]]) for c in ch[::2]}
    assert all(eng.rearm(k) for k in rearmed) and not eng.rearm(0x1234567)
    n0 = {int(eng.a.key[c["child"]]): int(eng.a.n[c["child"]]) for c in ch}
    eng.search(sims=6000, threads=2)
    visited = {k for k in n0 if int(eng.a.n[eng.find(k)]) > n0[k]}
    count = {k: [e.key for e in events].count(k) for k in n0}
    assert visited & rearmed
    assert {k for k in n0 if count[k] == 2} == visited & rearmed
    assert all(count[k] == 1 for k in n0 if k not in rearmed or k not in visited)


def test_searching_property():
    eng = MCTS(Board(9), config=cfg())
    seen = []
    assert not eng.searching
    eng.search(sims=4000, threads=2, stop=lambda: seen.append(eng.searching) or False)
    assert seen and all(seen) and not eng.searching


def _reachable(eng):
    """Independent reachability: breadth first over children()."""
    seen, todo = {eng.root}, [eng.root]
    while todo:
        i = todo.pop()
        for c in eng.children(i):
            if c["child"] >= 0 and c["child"] not in seen:
                seen.add(c["child"])
                todo.append(c["child"])
    return seen


def test_in_subtree_is_exact_for_any_move_order():
    events = []
    eng = MCTS(Board(9), config=cfg(n_thr=20, hook_depth=1, seed=7), on_expand=events.append)
    eng.search(sims=40000, threads=1)                     # one thread: the same tree every run
    eng.advance(eng.best_move())
    reach = _reachable(eng)
    rk = int(eng.a.key[eng.root])
    other_order = 0
    for ev in {e.key: e for e in events}.values():
        exp = eng.find(ev.key) in reach
        assert eng.in_subtree(ev.key, max_age=0) == exp
        if exp and rk not in ev.path:
            other_order += 1                              # its recorded path alone would have dropped it
    assert other_order > 0
    assert not eng.in_subtree(0xDEADBEEF)
    # safe and consistent during a search (positives stay positive)
    pos = [k for k in {e.key for e in events} if eng.in_subtree(k)][:200]
    stop, bad = [], []

    def poll():
        while not stop:
            bad.extend(k for k in pos if not eng.in_subtree(k, max_age=0.01))
    th = threading.Thread(target=poll)
    th.start()
    eng.search(sims=30000, threads=4)
    stop.append(1)
    th.join()
    assert not bad
    assert (eng.a.vl[:eng.n_nodes] == 0).all()


# ================================================================== engine: stand-in values
def test_standin_values_are_sign_correct():
    b, h = midgame()
    eng = MCTS(b, history=h, config=cfg(seed=3, lam=0.5))
    eng.search(sims=6000, threads=1)
    ch = sorted(eng.children(eng.root), key=lambda c: -c["n"])
    A, B = ch[0], ch[1]
    assert eng.standin_value(eng.root) is None             # no model value anywhere yet
    eng.set_external(b.played(A["move"]).key, value=0.9)   # the child's side wins: bad for the root's mover
    assert eng.a.flags[eng.root] & FL_EVCHILD
    assert eng.standin_value(eng.root) == pytest.approx(0.8)   # siblings' mean, side to move at the children
    rows = {m["move"]: m for m in eng.root_stats()}
    a, bb = rows[A["move"]], rows[B["move"]]
    assert a["evaluated"] and not a["standin"] and a["v_ext"] == pytest.approx(0.1, abs=1e-6)
    assert a["q"] == pytest.approx(0.5 * 0.1 + 0.5 * a["q_playout"], abs=1e-6)
    assert not bb["evaluated"] and bb["standin"] and bb["q_raw"] == pytest.approx(bb["q_playout"])
    assert bb["q"] == pytest.approx(0.5 * 0.1 + 0.5 * bb["q_playout"], abs=1e-6)   # the same footing
    # ancestor: an evaluated root, no evaluated child: the children inherit the root's value
    eng2 = MCTS(b, history=h, config=cfg(seed=3, standin="ancestor"))
    eng2.search(sims=3000, threads=1)
    eng2.set_external(eng2.a.key[eng2.root], value=0.2)     # the root's mover is losing
    assert eng2.standin_value(eng2.root) == pytest.approx(0.6)  # -(2 * 0.2 - 1) for the children's side
    m = eng2.root_stats()[0]
    assert m["standin"] and m["q"] == pytest.approx(0.5 * 0.2 + 0.5 * m["q_playout"], abs=1e-6)
    # off: as before
    eng3 = MCTS(b, history=h, config=cfg(seed=3, standin="off"))
    eng3.search(sims=3000, threads=1)
    eng3.set_external(eng3.a.key[eng3.root], value=0.2)
    assert eng3.standin_value(eng3.root) is None and not any(m["standin"] for m in eng3.root_stats())


@pytest.mark.parametrize("seed", [4, 5])
def test_unevaluated_root_moves_do_not_win_by_default(seed):
    """lam = 0 (model values only): four root moves get pessimistic model values, the best of them
    0.3 for the mover.  Without a stand-in the unevaluated moves keep their playout Q and take every
    new visit; with it they stand at the evaluated siblings' mean (0.16 for the mover), so the best
    evaluated move takes the search (a stand-in with the wrong sign would make them 0.84)."""
    b, h = midgame()

    def run(mode):
        eng = MCTS(b, history=h, config=cfg(seed=seed, standin=mode, lam=0.0))
        eng.search(sims=4000, threads=1)
        top = [c["move"] for c in sorted(eng.children(eng.root), key=lambda c: -c["n"])[:4]]
        n0 = {c["move"]: c["n"] for c in eng.children(eng.root)}
        for m, v in zip(top, (0.95, 0.9, 0.8, 0.7)):
            eng.set_external(b.played(m).key, value=v)
        eng.search(sims=20000, threads=2)
        new = {c["move"]: c["n"] - n0[c["move"]] for c in eng.children(eng.root)}
        return new[top[3]] / 20000, sum(v for m, v in new.items() if m not in top) / 20000, eng.best_move() == top[3]
    best_off, rest_off, _ = run("off")
    best_sib, rest_sib, decided = run("siblings")
    assert rest_off > 0.95 and best_off < 0.01
    assert best_sib > 0.9 and rest_sib < 0.05 and decided


# ================================================================== decision rule
class StubEngine:
    def __init__(self, rows):
        self.rows = rows
        self.root_board = Board(9)

    def root_stats(self, top=None, pv_len=10):
        out = [{"move": point(c, 9), "coord": c, "n": n, "q": 0.5, "v_ext": 0.4 if ev else None, "evaluated": ev}
               for c, n, ev in sorted(self.rows, key=lambda r: -r[1])]
        return out[:top] if top else out

    def best_move(self):
        return self.root_stats()[0]["move"]


class StubService:
    def __init__(self, pending=1):
        self.pending, self.calls = pending, []

    def boost(self, moves):
        self.calls.append(list(moves))
        return self.pending


def test_decision_rule_picks_an_evaluated_top_candidate():
    c = DecideConfig(top=4, min_share=0.2)
    d = choose(StubEngine([("E5", 1000, True), ("D4", 900, False)]), c)
    assert d["rule"] == "most_visits_evaluated" and d["coord"] == "E5" and d["waiting"] == []
    d = choose(StubEngine([("E5", 1000, False), ("D4", 600, False), ("C3", 300, True), ("B2", 100, True)]), c)
    assert d["rule"] == "evaluated_among_top" and d["coord"] == "C3" and d["lead"] == "E5"
    assert d["waiting"] == [point("E5", 9), point("D4", 9)]
    d = choose(StubEngine([("E5", 1000, False), ("D4", 600, False), ("B2", 100, True)]), c)
    assert d["rule"] == "most_visits_unevaluated" and d["coord"] == "E5"        # B2 is below the share
    d = choose(StubEngine([("E5", 1000, False), ("D4", 600, True)]), DecideConfig(rule="visits"))
    assert d["rule"] == "most_visits" and d["coord"] == "E5"


def test_decision_extension_waits_for_the_leaders_value_within_its_bound():
    eng = StubEngine([("E5", 1000, False), ("D4", 600, True)])
    svc, chunks = StubService(), []

    def search(t):                                     # the leader's value arrives after two chunks
        chunks.append(t)
        if len(chunks) == 2:
            eng.rows[0] = ("E5", 1100, True)
    d = decide(eng, DecideConfig(extend_s=30, chunk_s=0.01), svc, search)
    assert d["rule"] == "most_visits_evaluated" and d["coord"] == "E5" and d["extension"] == "resolved"
    assert len(chunks) == 2 and svc.calls[0] == [point("E5", 9)] and d["boosted"] == ["E5"]
    # nothing can still evaluate it: no extension
    eng = StubEngine([("E5", 1000, False), ("D4", 600, True)])
    d = decide(eng, DecideConfig(extend_s=30), StubService(pending=0), lambda t: pytest.fail("searched"))
    assert d["rule"] == "evaluated_among_top" and d["coord"] == "D4" and d["extension"] == "no_request"
    # the bound holds when the value never comes
    t0 = time.monotonic()
    d = decide(StubEngine([("E5", 1000, False), ("D4", 600, True)]), DecideConfig(extend_s=0.3, chunk_s=0.05),
               StubService(), lambda t: time.sleep(t))
    assert d["extension"] == "time" and d["coord"] == "D4" and 0.3 <= time.monotonic() - t0 < 1.0


# ================================================================== calibration
def test_fit_calib_recovers_a_known_miscalibration_and_stays_near_identity_with_little_data():
    rng = np.random.default_rng(0)
    v = rng.uniform(0.03, 0.97, 3000)
    t = np.clip(apply_calib(v, 0.4, 0.3) + rng.normal(0, 0.03, len(v)), 0, 1)
    c = fit_calib(v, t)
    assert c["status"] == "fitted" and c["a"] == pytest.approx(0.4, abs=0.03) and c["b"] == pytest.approx(0.3, abs=0.04)
    assert c["mse_fit"] < c["mse_identity"] / 10
    few = fit_calib(v[:3], t[:3])                         # three pairs: mostly the identity
    assert abs(few["a"] - 1) < abs(few["raw_a"] - 1) and abs(few["b"]) < abs(few["raw_b"])
    assert fit_calib([], [])["status"] == "default"
    assert fit_calib(v, 1 - v, n0=0)["a"] == A_LO       # monotone: never a decreasing map
    for x in (0.001, 0.02, 0.3, 0.5, 0.9, 0.999):          # the engine applies the same map
        assert apply_calibration(x, 0.4, 0.3) == pytest.approx(float(apply_calib(x, 0.4, 0.3)), abs=1e-9)
    assert apply_calibration(0.37, 1.0, 0.0) == 0.37


def test_engine_recalibrates_the_values_already_in_the_tree():
    b, h = midgame()
    eng = MCTS(b, history=h, config=cfg(seed=5))
    eng.search(sims=3000, threads=1)
    ch = sorted(eng.children(eng.root), key=lambda c: -c["n"])
    k1, k2 = b.played(ch[0]["move"]).key, b.played(ch[1]["move"]).key
    wx0, nx0 = float(eng.a.wx[eng.root]), int(eng.a.nx[eng.root])
    eng.set_external(k1, value=0.8)                       # identity map: enters as 0.8
    i1 = eng.find(k1)
    assert eng.a.vext[i1] == pytest.approx(0.6) and eng.a.wx[eng.root] == pytest.approx(wx0 - 0.6)
    assert eng.set_calibration(0.5, -0.2) == 1
    new = apply_calibration(0.8, 0.5, -0.2)
    assert eng.a.vext[i1] == pytest.approx(2 * new - 1, abs=1e-6) and eng.a.wx[i1] == pytest.approx(2 * new - 1)
    assert eng.a.wx[eng.root] == pytest.approx(wx0 - (2 * new - 1)) and eng.a.nx[eng.root] == nx0 + 1
    eng.set_external(k2, value=0.8)                       # a new value enters calibrated
    assert eng.a.vext[eng.find(k2)] == pytest.approx(2 * new - 1, abs=1e-6)
    assert eng._ext_info[k1]["value_raw"] == 0.8 and eng._ext_info[k1]["value"] == pytest.approx(new)
    with pytest.raises(ValueError):
        eng.set_calibration(-1.0, 0.0)


def test_learner_fits_the_calibration_and_the_engine_applies_it(tmp_path):
    rng = np.random.default_rng(3)
    L = OnlineLearner(tmp_path / "run", mix_min_pairs=20, calib_min_pairs=10, **FAST)
    assert L.fit_calibration()["status"] == "default"
    w = load_default()
    for b in random_positions(120, seed=12):
        v = float(rng.uniform(0.05, 0.95))
        t = float(apply_calib(v, 0.5, -0.4))              # the model is overconfident and too optimistic
        L.observe_external(b, "llm", None, v, q_playout=0.5, n=64)
        pl = move_priors(b, w)
        L.observe(b, pl, t, 1, n=4096, key=b.key, q_playout=t)
    cal = L.fit_calibration()
    assert cal["status"] == "fitted" and cal["pairs"] == 120
    assert cal["a"] == pytest.approx(0.5, abs=0.06) and cal["b"] == pytest.approx(-0.4, abs=0.06)
    u = L.update()
    assert u["mix"]["calib"]["status"] == "fitted" and u["mix"]["lam"].get("on") == "calibrated values"
    assert L.current.params["calib_a"] == pytest.approx(cal["a"], abs=1e-3)
    assert L.current.params["calib_b"] == pytest.approx(cal["b"], abs=1e-3)
    eng = MCTS(Board(9), config=cfg(max_nodes=100_000), weights=L.provider)
    eng.search(sims=200, threads=1)
    assert eng.cfg.calib_a == pytest.approx(cal["a"], abs=1e-3) and eng.cfg.calib_b == pytest.approx(cal["b"], abs=1e-3)
    assert eng.calibrate(0.9) == pytest.approx(float(apply_calib(0.9, eng.cfg.calib_a, eng.cfg.calib_b)))
    # persisted: a new learner on the same run dir resumes the version with the map
    assert OnlineLearner(tmp_path / "run", **FAST).current.params["calib_a"] == L.current.params["calib_a"]


# ================================================================== service
class BreadthWorker(Worker):
    """expand: the first legal point 0.9, the last 0.1, one unconventional (the middle legal point);
    value 0.8.  Other kinds: MockWorker."""
    name = "breadth"

    def __init__(self, delay=0.0):
        self.jobs, self.delay, self.mock, self.lock = [], delay, MockWorker(), threading.Lock()

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
               "unconventional": [{"move": coord(legal[len(legal) // 2], s), "why": "middle"}],
               "value": {"winrate": 0.8, "confidence": "low", "why": "fake"}}
        return JobResult(True, validate(job, raw), worker=self.name, usage={"cost_usd": 0.25})


def service(tmp_path, worker, **kw):
    base = dict(workers=4, dispatch_delay_s=0.0, refute=False, poll_s=0.02)
    base.update(kw)
    tmp_path.mkdir(parents=True, exist_ok=True)
    return LLMService(worker, DAG(str(tmp_path / "dag.db")), Memory(str(tmp_path / "memory.db")), LLMConfig(**base),
                      log=lambda m: None, record=tmp_path / "llm-jobs.jsonl", jobs_dir=tmp_path / "jobs")


def test_service_sets_root_breadth_from_the_models_proposals(tmp_path):
    b, h = midgame()
    svc = service(tmp_path, BreadthWorker())
    eng = MCTS(b, history=h, config=cfg(hook_depth=0, n_thr=10**9))
    svc.attach(eng)
    svc.start()
    assert svc.wait_idle(20)
    dkey, can, s = canonical_of(b)
    legal = [p for p in can.legal_moves() if p is not None]
    want = {to_real(legal[0], s, 9): "candidate", to_real(legal[-1], s, 9): "candidate",
            to_real(legal[len(legal) // 2], s, 9): "explore"}
    assert eng.root_breadth == want and svc.stats()["root_breadth_sets"] >= 1
    eng.search(sims=6000, threads=2)
    n = {c["move"]: c["n"] for c in eng.children(eng.root)}
    for m, k in want.items():
        assert n[m] >= (64 if k == "candidate" else 32) - 2
    svc.close()


def test_boost_gives_the_most_visited_unevaluated_root_moves_top_priority(tmp_path):
    b, h = midgame()
    worker = BreadthWorker()
    svc = service(tmp_path, worker, boost_top=2, boost_every_s=0.0)
    eng = MCTS(b, history=h, config=cfg(hook_depth=0, n_thr=10**9))   # only the root raises a request itself
    svc.attach(eng)
    svc.start()
    assert svc.wait_idle(20) and len(worker.jobs) == 1
    eng.search(sims=4000, threads=2)
    top2 = svc.top_unevaluated(2)
    assert len(top2) == 2
    svc.pause()
    svc._tick_t = 0.0
    svc.tick()
    q = svc.queued()
    keys = {b.played(m).key for m in top2}
    assert {k for r in q for k in r["keys"]} == keys and all(r["cls"] == CLS_TOP for r in q)
    svc.resume()
    assert svc.wait_idle(20)
    for k in keys:
        assert eng.ext_value(eng.find(k)) == pytest.approx(0.8)
    assert svc.stats()["boosted"] == 2
    assert svc.boost(top2) == 2 and len(worker.jobs) == 3   # evaluated now: nothing new to ask
    svc.close()


def test_dropped_requests_are_rearmed_and_asked_again(tmp_path):
    """Requests dropped by the queue cap re-arm their nodes' hooks once the queue has room (the
    engine then fires on the node's next visit: test_rearm_fires_the_hook_again), and the service
    takes such a repeated event as new: it asks again and the node gets its evaluation.  A repeated
    event of a node that was not dropped is still ignored."""
    b, h = midgame()
    worker = BreadthWorker()
    svc = service(tmp_path, worker, queue_cap=6, workers=2, rearm_every_s=0.0)
    eng = MCTS(b, history=h, config=cfg(n_thr=150))
    svc.attach(eng)
    events, hook = {}, eng.on_expand
    eng.on_expand = lambda ev: (events.setdefault(ev.key, ev), hook(ev))
    svc.pause()
    svc.start()
    eng.search(sims=8000, threads=2)
    assert svc.wait_idle(10, queue_too=False)
    st = svc.stats()
    assert st["cap_dropped"] > 0 and st["dropped"] == len(svc._dropped) > 0
    dropped = set(svc._dropped)
    assert all(eng.a.flags[eng.find(k)] & 1 for k in dropped)        # hooked: they would never fire again
    svc.resume()                                         # the queue drains; dropped nodes are re-armed
    t_end = time.time() + 20
    while time.time() < t_end and svc.stats()["rearmed"] < 5:
        time.sleep(0.05)
    assert svc.stats()["rearmed"] >= 5 and svc.wait_idle(30)
    rearmed = dropped - set(svc._dropped)
    assert len(rearmed) >= 5 and not any(eng.a.flags[eng.find(k)] & 1 for k in rearmed)
    jobs0 = len(worker.jobs)
    done = next(k for k in events if eng.a.flags[eng.find(k)] & FL_EXT and k not in dropped)
    svc.cfg.queue_cap = 10_000
    for k in rearmed | {done}:                           # what their next visit would send
        svc.on_expand(events[k])
    assert svc.wait_idle(30)
    for k in rearmed:
        assert eng.a.flags[eng.find(k)] & FL_EXT       # asked again and evaluated
    assert len(worker.jobs) - jobs0 <= len(rearmed)      # nothing for the node that was not dropped
    svc.close()


def test_service_keeps_requests_reachable_by_another_move_order(tmp_path):
    svc = service(tmp_path, BreadthWorker())
    eng = MCTS(Board(9), config=cfg())
    svc.attach(eng)
    eng.search(sims=6000, threads=2)
    old = int(eng.a.key[eng.root])
    ch = sorted(eng.children(eng.root), key=lambda c: -c["n"])
    sib_key = int(eng.a.key[ch[1]["child"]])
    eng.advance(ch[0]["move"])
    svc.new_root()
    gc = max(eng.children(eng.root), key=lambda c: c["n"])
    k = int(eng.a.key[gc["child"]])
    b = eng.root_board.played(gc["move"])
    assert svc._in_subtree(Target(k, b, [old, 12345, k], 0, 2))    # path misses the new root: still reachable
    assert not svc._in_subtree(Target(sib_key, b, [old, sib_key], 0, 1))
    svc.close()
