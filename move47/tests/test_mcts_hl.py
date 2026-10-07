"""Online Heuristic Learning (mcts/hl): the learner's interface, the gate, persistence across
processes, lam / beta recovery, the value model, the regression set and tactical guards."""
import inspect
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from mcts.board import Board
from mcts.features import feature_index, move_priors
from mcts.hl import DEFAULTS, OnlineLearner
from mcts.hl import learner as learner_mod
from mcts.hl.data import heldout
from mcts.hl.fit import PolicySet, fit_policy
from mcts.hl.mix import fit_beta, fit_lam
from mcts.hl.regression import (GUARDS_PATH, POSITIONS_PATH, check_guards, guard_board, load_guards, load_positions,
                                regression_metrics)
from mcts.hl.value import FEATURES, ValueModel, fit_value, value_inputs
from mcts.policy import Policy
from mcts.tree import MCTS, MCTSConfig
from mcts.weights import Weights, default_weights, load_default

ROOT = Path(__file__).resolve().parent.parent
# unit tests run without the tracked regression positions (a path that does not exist); the
# regression gate has its own test with a synthetic set
FAST = dict(min_train=20, min_heldout=5, fit_time=5.0, value=False, max_iter=60,
            regression_path=str(ROOT / "tests" / "no-such-regression-set.json"))


def random_positions(n, seed=0, max_ply=40):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        b = Board(9)
        for _ in range(int(rng.integers(0, max_ply))):
            mv = b.legal_moves()
            if not mv:
                break
            b.play(int(rng.choice(mv)))
        out.append(b)
    return out


def teacher():
    """A policy that differs from default-v1 in a learnable way (prefers the third line)."""
    w = default_weights().w.copy()
    idx = feature_index()
    w[idx["line:3"]] += 2.0
    w[idx["line:2"]] -= 1.5
    w[idx["line:5+"]] -= 1.0
    return Weights(w, "teacher")


def feed(learner, boards, w, n=1000):
    for b in boards:
        learner.observe(b, move_priors(b, w), 0.5, 1, n=n, key=b.key)


# ------------------------------------------------------------------ interface
def test_interface_contract(tmp_path):
    L = OnlineLearner(tmp_path / "run", **FAST)
    assert set(inspect.signature(OnlineLearner).parameters) >= {"run_dir", "base"}
    for name, params in {"observe": ["position", "visit_distribution", "q", "depth"],
                         "observe_external": ["position", "source", "priors", "value"],
                         "observe_game": ["result", "our_color"], "update": []}.items():
        got = [p for p in inspect.signature(getattr(L, name)).parameters if p != "extra"]
        assert got == params, name
    w = L.provider.get()
    assert isinstance(w, Weights) and w.version == "default-v1"
    # the engine drives the learner through its hooks
    eng = MCTS(Board(9), config=MCTSConfig(max_nodes=200_000, observe_min_visits=100), weights=L.provider, learner=L)
    eng.search(sims=3000, threads=2)
    assert len(L.samples) > 0
    s = next(iter(L.samples.values()))
    assert s.depth == 0 and s.n >= 3000 and s.qp is not None          # the extras arrived (n, key, q_playout)
    assert L.observe_external(eng.root_board, "llm", {"E5": 0.6, "pass": 0.1}, 0.55)["recorded"]
    L.observe_game(+1, "B")
    L.observe_game("B+3.5", "W")                                      # an SGF result string, from our side
    L.observe_game("W+R", "W")
    assert [L.games[i] for i in range(3)] == [(1.0, "X"), (-1.0, "O"), (1.0, "O")]
    u = L.update()
    assert {"version", "accepted", "reason", "time_s", "policy", "mix", "file"} <= set(u)
    assert u["accepted"] is False and "not enough" in u["reason"] and L.game == 3
    assert (tmp_path / "run" / "weights-v000.json").exists() and (tmp_path / "run" / "state.json").exists()
    assert set(DEFAULTS) >= set(FAST)
    from mcts.hl.data import limit_blas_threads
    assert limit_blas_threads(1) >= 0                                  # the BLAS pool cap never raises
    with pytest.raises(TypeError):
        OnlineLearner(tmp_path / "x", nonsense=1)


def test_engine_picks_up_a_new_version_between_moves_while_keeping_the_tree(tmp_path):
    L = OnlineLearner(tmp_path / "run", **FAST)
    eng = MCTS(Board(9), config=MCTSConfig(max_nodes=300_000), weights=L.provider, learner=L)
    r1 = eng.search(sims=2000, threads=2)
    assert r1["weights"] == "default-v1"
    feed(L, random_positions(150, seed=1), teacher())
    assert L.update()["accepted"]
    eng.advance(r1["best_move"])
    kept = int(eng.a.n[eng.root])
    r2 = eng.search(sims=1000, threads=2)
    assert kept > 0 and r2["root_n"] == kept + 1000                  # the subtree was kept
    assert r2["weights"] == "hl-v001" and r2["weights_refreshed"]     # and the new version applies


# ------------------------------------------------------------------ learning and the gate
def test_learning_lowers_heldout_ce_and_writes_a_version(tmp_path):
    L = OnlineLearner(tmp_path / "run", **FAST)
    feed(L, random_positions(240, seed=2), teacher())
    u = L.update()
    assert u["accepted"], u["reason"]
    ho = u["policy"]["heldout"]
    assert ho["candidate"]["ce"] < ho["parent"]["ce"] - 0.01
    d = json.loads((tmp_path / "run" / "weights-v001.json").read_text())
    assert d["version"] == "hl-v001" and d["hl"]["parent"]["version"] == "default-v1"
    assert d["hl"]["parent"]["digest"] == load_default().digest and d["hl"]["samples"]["train"] > 0
    assert Weights.load(tmp_path / "run" / "weights-v001.json").digest == L.current.digest
    idx = feature_index()
    assert L.current.w[idx["line:3"]] > load_default().w[idx["line:3"]]     # moved toward the teacher
    assert u["checks"]["guards"]["passed"]


def test_playout_temperature_keeps_the_base_playout_entropy(tmp_path):
    boards = random_positions(200, seed=13)
    L = OnlineLearner(tmp_path / "match", playout_temp="match", **FAST)
    feed(L, boards, teacher())
    assert L.update()["accepted"]
    T = L.current.params["playout_temperature"]
    tr = sorted(L.split()[0], key=lambda s: s.sid)
    ps = L._policy_set(tr[-400:])
    assert ps.playout_entropy(L.current.w, T) == pytest.approx(ps.playout_entropy(load_default().w, 1.0), abs=5e-3)
    assert ps.playout_entropy(L.current.w, 1.0) != pytest.approx(ps.playout_entropy(load_default().w, 1.0), abs=1e-2)
    K = OnlineLearner(tmp_path / "keep", **FAST)                       # the default keeps the temperature
    feed(K, boards, teacher())
    assert K.update()["accepted"] and K.current.params["playout_temperature"] == 1.0


def test_gate_rejects_a_worse_fit(tmp_path, monkeypatch):
    L = OnlineLearner(tmp_path / "run", **FAST)
    feed(L, random_positions(120, seed=3), teacher())
    rng = np.random.default_rng(0)

    def worse(data, w_prev, *a, **k):
        return w_prev + rng.normal(0, 3.0, len(w_prev)), {"iters": 0, "reason": "test", "time_s": 0.0}

    monkeypatch.setattr(learner_mod, "fit_policy", worse)
    u = L.update()
    assert not u["accepted"] and "did not improve" in u["reason"]
    assert u["version"] == "default-v1" and L.provider.get().version == "default-v1"
    assert not (tmp_path / "run" / "weights-v001.json").exists()
    assert json.loads((tmp_path / "run" / "updates.jsonl").read_text().splitlines()[-1])["accepted"] is False


def test_gate_rejects_a_fit_that_loses_a_tactical_guard(tmp_path, monkeypatch):
    L = OnlineLearner(tmp_path / "run", **FAST)
    feed(L, random_positions(120, seed=4), teacher())
    real = learner_mod.fit_policy

    def no_captures(data, w_prev, *a, **k):     # a good fit, except that captures become unattractive
        w, info = real(data, w_prev, *a, **k)
        w = w.copy()
        for f in ("capture:1", "capture:2", "capture:3-5", "capture:6+"):
            w[feature_index()[f]] = -5.0
        return w, info

    monkeypatch.setattr(learner_mod, "fit_policy", no_captures)
    u = L.update()
    assert not u["accepted"] and "tactical guard" in u["reason"] and "capture-4-stones" in u["reason"]
    assert len(u["policy"]["attempts"]) == 3 and u["version"] == "default-v1"


def test_base_anchor_bounds_the_drift_of_repeated_updates(tmp_path):
    """L2 toward the parent alone is a proximal iteration: repeated refits on the same data keep
    moving the weights.  With the base anchor they converge to the one-shot fit anchored to the base."""
    boards = random_positions(200, seed=17)
    base = load_default()

    def run(l2_base):
        L = OnlineLearner(tmp_path / f"a{l2_base:g}", **{**FAST, "l2_base": l2_base, "min_gain": -1.0, "l2": 1e-2})
        feed(L, boards, teacher())
        d = []
        for _ in range(6):
            L.update()
            d.append(float(np.linalg.norm(L.current.w - base.w)))
        return L, d

    La, da = run(1e-2)
    _, dn = run(0.0)
    assert dn[-1] > dn[2] + 0.1 and dn[-1] > 1.2 * da[-1]          # unanchored: still drifting, and further
    tr = sorted(La.split()[0], key=lambda s: s.sid)
    ps = La._policy_set(tr, La._anchors(), La.cfg["guard_weight"])
    one_shot, _ = fit_policy(ps, base.w, 1e-2, max_iter=300)
    assert np.linalg.norm(La.current.w - one_shot) < 0.25 * np.linalg.norm(one_shot - base.w)


def test_gate_rejects_a_fit_that_is_worse_on_the_regression_set(tmp_path):
    from mcts.hl.regression import FORMAT
    w = load_default()
    pos = []
    for i, b in enumerate(random_positions(40, seed=14)):            # targets: default-v1's own priors
        pos.append({"id": f"p{i}", "board": b.to_dict(), "pi": {b.coord(m): p for m, p in move_priors(b, w).items()},
                    "n": 1})
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"format": FORMAT, "kind": "positions", "positions": pos}))
    L = OnlineLearner(tmp_path / "run", **{**FAST, "regression_path": str(reg)})
    feed(L, random_positions(200, seed=15), teacher())
    u = L.update()
    assert not u["accepted"] and "regression-set CE rose" in u["reason"]
    r = u["checks"]["regression"]
    assert r["candidate"]["ce"] > r["parent"]["ce"] + L.cfg["reg_tol"] and u["policy"]["gain"] > 0
    assert u["version"] == "default-v1"


# ------------------------------------------------------------------ persistence
def test_state_persists_and_resumes_in_another_process(tmp_path):
    run = tmp_path / "run"
    L = OnlineLearner(run, **FAST)
    feed(L, random_positions(150, seed=5), teacher())
    assert L.update()["accepted"]
    L.observe_game(-1, "W")
    n, sid, digest = len(L.samples), L.next_sid, L.current.digest
    code = f"""
import json, sys
sys.path[:0] = [{str(ROOT)!r}, {str(ROOT / "tests")!r}]
from mcts.hl import OnlineLearner
from test_mcts_hl import FAST, feed, random_positions, teacher
L = OnlineLearner({str(run)!r}, **FAST)
before = dict(version=L.current.version, digest=L.current.digest, samples=len(L.samples), sid=L.next_sid, game=L.game,
              games=dict(L.games))
feed(L, random_positions(150, seed=6), teacher())
u = L.update()
L.close()
print(json.dumps(dict(before=before, accepted=u["accepted"], version=u["version"])))
"""
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    b = out["before"]
    assert b["version"] == "hl-v001" and b["digest"] == digest and b["samples"] == n and b["sid"] == sid
    assert b["game"] == 1 and b["games"] == {"0": [-1.0, "O"]}
    assert out["accepted"] and out["version"] == "hl-v002"
    # this process's provider sees the version the other process wrote
    assert L.provider.get().version == "hl-v002" and L.version_no == 2
    L2 = OnlineLearner(run, **FAST)
    keys = {b.key for b in random_positions(150, seed=5)} | {b.key for b in random_positions(150, seed=6)}
    assert len(L2.samples) == len(keys) and L2.current.version == "hl-v002"


def test_ring_buffer_keeps_the_latest_observation_per_node_and_its_capacity(tmp_path):
    L = OnlineLearner(tmp_path / "run", capacity=50, **FAST)
    boards = random_positions(80, seed=7)
    feed(L, boards, load_default(), n=300)
    assert len(L.samples) == 50
    b = boards[-1]
    L.observe(b, {"E5": 1.0}, 0.9, 0, n=5000, key=b.key)
    assert len(L.samples) == 50 and L.samples[b.key].n == 5000 and list(L.samples)[-1] == b.key
    L.close()
    assert len(OnlineLearner(tmp_path / "run", capacity=50, **FAST).samples) == 50


# ------------------------------------------------------------------ lam / beta
def test_fit_lam_and_beta_recover_the_true_mix():
    rng = np.random.default_rng(0)
    n = 3000
    v, z = rng.uniform(0, 1, n), rng.uniform(0, 1, n)
    t = 0.7 * v + 0.3 * z + rng.normal(0, 0.05, n)
    lam = fit_lam(v, z, t)
    assert lam["raw"] == pytest.approx(0.3, abs=0.02) and lam["lam"] == pytest.approx(0.3, abs=0.02)
    pl = [rng.dirichlet(np.ones(12)) for _ in range(400)]
    pe = [rng.dirichlet(0.3 * np.ones(12)) for _ in range(400)]
    pi = [0.25 * a + 0.75 * b for a, b in zip(pl, pe)]
    beta = fit_beta(pl, pe, pi)
    assert beta["raw"] == pytest.approx(0.75, abs=0.01) and beta["beta"] == pytest.approx(0.75, abs=0.02)
    # few pairs: shrunk toward 0.5; extreme truths: clipped to [0.1, 0.9]
    few = fit_lam(v[:5], z[:5], z[:5])
    assert few["raw"] == pytest.approx(1.0) and few["lam"] == pytest.approx((5 * 1.0 + 10 * 0.5) / 15)
    assert fit_lam(v, z, z)["lam"] == 0.9 and fit_lam(v, z, v)["lam"] == 0.1
    assert fit_lam([], [], [])["status"] == "default"


def test_learner_fits_lam_beta_from_external_evaluations_and_the_engine_applies_them(tmp_path):
    rng = np.random.default_rng(1)
    # the calibration of external values is off here: lam is recovered on the raw values (with it on,
    # lam is fitted on the calibrated values; tests/test_mcts_calib.py)
    L = OnlineLearner(tmp_path / "run", mix_min_pairs=20, calib=False, **FAST)
    u0 = L.update()
    assert u0["mix"]["lam"]["status"] == "default" and "lam" not in L.current.params   # no external data yet
    w = load_default()
    for b in random_positions(60, seed=8):
        pl = move_priors(b, w)
        moves = list(pl)
        pe = dict(zip(moves, rng.dirichlet(0.3 * np.ones(len(moves)))))
        v, z = float(rng.uniform(0.1, 0.9)), float(rng.uniform(0.1, 0.9))
        L.observe_external(b, "llm", pe, v, q_playout=z, n=64)
        pi = {m: 0.8 * pl[m] + 0.2 * pe[m] for m in moves}                 # true beta 0.2
        L.observe(b, pi, 0.5, 2, n=4096, key=b.key, q_playout=0.2 * v + 0.8 * z)   # true lam 0.8
    u = L.update()
    lam, beta = u["mix"]["lam"], u["mix"]["beta"]
    assert lam["status"] == beta["status"] == "fitted" and lam["pairs"] == beta["pairs"] == 60
    assert lam["raw"] == pytest.approx(0.8, abs=0.02) and beta["raw"] == pytest.approx(0.2, abs=0.02)
    assert lam["lam"] == pytest.approx((60 * lam["raw"] + 5) / 70, abs=1e-6)
    assert u["accepted"] and L.current.params["lam"] == pytest.approx(lam["lam"], abs=1e-4)
    eng = MCTS(Board(9), config=MCTSConfig(max_nodes=100_000), weights=L.provider)
    eng.search(sims=200, threads=1)
    assert eng.cfg.lam == pytest.approx(lam["lam"], abs=1e-4) and eng.cfg.beta == pytest.approx(beta["beta"], abs=1e-4)


# ------------------------------------------------------------------ value model
def test_value_model_fit_and_inputs():
    rng = np.random.default_rng(2)
    X = np.column_stack([np.ones(4000), rng.normal(size=(4000, len(FEATURES) - 1))])
    true = rng.normal(size=len(FEATURES))
    t = 1 / (1 + np.exp(-X @ true))
    c = fit_value(X, t, l2=0.0)
    assert np.allclose(c, true, atol=0.05)
    vm = ValueModel(c, 8, "v")
    assert ValueModel.from_json(json.loads(json.dumps(vm.to_json()))).coef == pytest.approx(vm.coef, abs=1e-6)
    b = random_positions(1, seed=9, max_ply=30)[0]
    x = value_inputs(b, Policy(load_default()), k=8, seed=1)
    assert x.shape == (len(FEATURES),) and x[0] == 1.0 and -1 <= x[1] <= 1
    assert 0 <= vm.predict(b, Policy(load_default())) <= 1


def test_value_hook_feeds_the_engine_through_set_external():
    from mcts.hl.value import ValueHook
    vm = ValueModel(np.array([0.0, 2.0, 0, 0, 0, 0, 0, 0, 0]), k=4)
    hook = ValueHook(vm, Policy(load_default()))
    eng = MCTS(Board(9), config=MCTSConfig(max_nodes=100_000, n_thr=50), on_expand=hook)
    hook.engine = eng
    eng.search(sims=1500, threads=2)
    assert hook.calls > 5 and eng.a.nx[eng.root] >= 1
    assert all(v["source"] == "value" for v in eng._ext_info.values())


def test_value_model_is_fitted_to_q_and_game_results(tmp_path):
    L = OnlineLearner(tmp_path / "run", min_train=20, min_heldout=5, value=True, value_min=50, value_k=4, threads=2)
    rng = np.random.default_rng(3)
    for b in random_positions(120, seed=10):
        L.observe(b, {None: 1.0}, float(rng.uniform(0.2, 0.8)), 1, n=500, key=b.key)
    L.observe_game(1, "B")
    u = L.update()
    v = u["value"]
    assert v["status"] == "fitted" and v["labelled"] == 120 and v["heldout_q"]["n"] > 0
    assert {"mse_model", "mse_playouts", "mse_const"} <= set(v["heldout_q"])
    assert json.loads((tmp_path / "run" / "state.json").read_text())["value_model"]["features"] == list(FEATURES)


# ------------------------------------------------------------------ regression set and guards
def test_guards_hold_for_default_and_fail_for_broken_tactics():
    guards = load_guards()
    kinds = {g["kind"] for g in guards}
    names = " ".join(g["name"] for g in guards)
    assert kinds == {"top", "avoid"} and "capture" in names and "escape" in names and "self-atari" in names
    assert check_guards(load_default())["passed"]
    w = load_default().w.copy()
    idx = feature_index()
    for f in ("self_atari:size1", "self_atari:size2-3", "self_atari:size4+"):
        w[idx[f]] = 8.0
    res = check_guards(Weights(w, "self-atari-lover"))
    assert not res["passed"] and "no-self-atari-7-stones" in res["failures"]
    for g in guards:                                      # every guard move is legal on its 9x9 board
        b = guard_board(g)
        assert b.size == 9 and all(b.is_legal(m) for m in g["moves"])


def test_regression_positions_file():
    assert GUARDS_PATH.stat().st_size < 50_000
    if not POSITIONS_PATH.exists():
        pytest.skip("regression positions not generated")
    assert POSITIONS_PATH.stat().st_size < 1_000_000
    doc = json.loads(POSITIONS_PATH.read_text())
    pos = load_positions()
    assert doc["generator"]["weights"] == "default-v1" and len(pos) >= 100
    for e in pos:
        assert sum(e["pi"].values()) == pytest.approx(1.0, abs=0.01) and e["n"] >= 100_000
        assert Board.from_dict(e["board"]).key is not None
    m = regression_metrics(load_default())
    assert m["n"] == len(pos) and 0 < m["ce"] < 6


def test_export_heldout_writes_the_regression_format(tmp_path):
    from mcts.hl.regression import export_heldout
    L = OnlineLearner(tmp_path / "run", **FAST)
    feed(L, random_positions(200, seed=16), teacher(), n=2000)
    L.close()
    r = export_heldout(tmp_path / "run", tmp_path / "ho.json", n=20, min_visits=1000)
    doc = json.loads((tmp_path / "ho.json").read_text())
    assert r["positions"] == len(doc["positions"]) > 0 and doc["kind"] == "heldout"
    assert all(heldout(int(e["id"], 16), 0.2) for e in doc["positions"])           # held-out nodes only
    assert regression_metrics(load_default(), tmp_path / "ho.json")["n"] == r["positions"]


def tracked_learned_weights():
    return sorted((ROOT / "mcts" / "weights").glob("hl-*.json"))


@pytest.mark.parametrize("path", tracked_learned_weights(), ids=lambda p: p.name)
def test_tracked_learned_weights_keep_the_guards_and_beat_default_on_held_out_search_targets(path):
    """The shipped learned weights keep every tactical guard and predict the held-out nodes of the
    run that produced them (search targets never trained on) better than default-v1."""
    from mcts.hl.regression import HELDOUT_PATH
    w = Weights.load(path)
    assert check_guards(w)["passed"]
    m, m0 = regression_metrics(w, HELDOUT_PATH), regression_metrics(load_default(), HELDOUT_PATH)
    assert m["n"] >= 200 and m["ce"] < m0["ce"] - 0.1


# ------------------------------------------------------------------ engine extras and the CLI
def test_tree_samples_carry_the_playout_and_external_parts():
    eng = MCTS(Board(9), config=MCTSConfig(max_nodes=100_000, observe_min_visits=200))
    eng.search(sims=2000, threads=2)
    eng.set_external(eng.a.key[eng.root], value=0.9)
    s = eng.samples()[0]
    assert s["n_ext"] == 1 and s["q_ext"] == pytest.approx(0.9, abs=1e-6)
    assert s["q_playout"] == pytest.approx((1 + eng.a.w[eng.root] / eng.a.n[eng.root]) / 2)
    got = []
    eng.learner = lambda position, visit_distribution, q, depth: got.append(depth)    # a plain 4-argument hook
    eng.search(sims=200, threads=1)
    assert got


def test_fit_policy_gradient_matches_finite_differences():
    boards = random_positions(12, seed=11)
    from mcts.hl.data import policy_rows, target_vector
    rows = [policy_rows(b) for b in boards]
    t = teacher()
    tg = [target_vector(r, {(-1 if m is None else m): p for m, p in move_priors(b, t).items()})
          for r, b in zip(rows, boards)]
    ps = PolicySet(rows, tg, np.arange(1, 13))
    w0 = load_default().w
    w = w0 + np.random.default_rng(0).normal(0, 0.2, len(w0))
    f, g = ps.loss_grad(w, w0, 1e-3, 1.3)
    for i in np.flatnonzero(g)[:8]:
        e = np.zeros_like(w)
        e[i] = 1e-6
        num = (ps.loss_grad(w + e, w0, 1e-3, 1.3)[0] - ps.loss_grad(w - e, w0, 1e-3, 1.3)[0]) / 2e-6
        assert g[i] == pytest.approx(num, rel=1e-4, abs=1e-8)
    wn, info = fit_policy(ps, w0, 1e-4)
    assert ps.metrics(wn)["ce"] < ps.metrics(w0)["ce"] and info["f"] < info["f0"]


def test_censored_targets_keep_only_visited_moves_below_the_root(tmp_path):
    from mcts.hl.data import censor_rows, policy_rows, target_vector
    b = random_positions(1, seed=18, max_ply=12)[0]
    rows = policy_rows(b)
    moves = [int(m) for m in rows.moves[:3]]
    t = target_vector(rows, {moves[0]: 0.5, moves[1]: 0.3, moves[2]: 0.2})
    r2, t2 = censor_rows(rows, t)
    assert [int(m) for m in r2.moves] == moves and t2.sum() == pytest.approx(1.0) and r2.nf.sum() == len(r2.fi)
    st = np.concatenate([[0], np.cumsum(rows.nf)])
    assert list(r2.fi) == list(rows.fi[:st[3]])                       # the visited moves' features, unchanged
    L = OnlineLearner(tmp_path / "run", censor=True, **FAST)
    L.observe(b, {moves[0]: 0.7, moves[1]: 0.3}, 0.5, 2, n=500, key=b.key)
    L.observe(Board(9), {"E5": 0.6, "D4": 0.4}, 0.5, 0, n=500)
    deep, root = L.samples[b.key], L.samples[Board(9).key]
    assert len(L._rows_of(deep)[0].moves) == 2 and len(L._rows_of(root)[0].moves) == 82   # the root keeps all


def test_heldout_split_is_fixed_by_node_key():
    keys = [b.key for b in random_positions(400, seed=12)]
    share = np.mean([heldout(k, 0.2) for k in keys])
    assert 0.1 < share < 0.3 and [heldout(k, 0.2) for k in keys] == [heldout(k, 0.2) for k in keys]


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "mcts", *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=600)


def test_cli_learn_selfplay_report_and_ab(tmp_path):
    run = tmp_path / "hl"
    r = run_cli("learn-selfplay", "--run", str(run), "--games", "1", "--time", "0.15", "--threads", "2",
                "--max-moves", "12", "--set", "max_nodes=300000", "--set", "observe_min_visits=64",
                "--hl", "min_train=10", "--hl", "min_heldout=3", "--hl", "value=false")
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res["updates"] == 12 and (run / "games" / "g000.sgf").exists()
    moves = [json.loads(ln) for ln in (run / "moves.jsonl").read_text().splitlines()]
    assert len(moves) == 12 and sum(m["reused_root_n"] > 0 for m in moves) >= 10      # one tree per game
    r = run_cli("hl-report", "--run", str(run), "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["versions"][0]["version"] == "default-v1" and rep["reuse"]["moves"] == 12
    r = run_cli("weights-ab", "--a", str(run / "weights-v000.json"), "--b", str(ROOT / "mcts/weights/default-v1.json"),
                "--games", "2", "--time", "0.05", "--threads", "2", "--max-moves", "10", "--run", str(tmp_path / "ab"))
    assert r.returncode == 0, r.stderr
    s = json.loads(next(ln for ln in r.stdout.splitlines() if ln.startswith("{")))
    assert s["games"] == 2 and s["by_a_color"]["B"]["games"] == 1 and 0 <= s["ci95"][0] <= s["ci95"][1] <= 1
    assert (tmp_path / "ab" / "summary.json").exists()
    r = run_cli("learn-selfplay", "--run", str(ROOT / "runs-hl-x"), "--games", "1")
    assert r.returncode != 0 and "outside the Chandra tree" in r.stderr
    r = run_cli("hl-guards")
    assert r.returncode == 0 and json.loads(r.stdout)["guards"]["passed"]
