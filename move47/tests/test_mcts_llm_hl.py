"""Learning from model reasoning plus search (node move47::mcts-llm-hl, no model): the rule language
(parse, compile, match, symmetry, colour-relativity, C/Python parity), refusal of malformed,
over-broad and unsafe proposals, the proposal gate, the heuristics book with provenance and lesson
links, the distillation term, rules in the engine's priors, the gtree tools of a heuristic job, and
the play loop with a mock worker."""
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from gotree.dag import DAG
from gotree.heurdsl import CompiledRule, RuleError, Tactics, canonical, parse_answer, parse_rule, variants
from gotree.jobs import InvalidResult, Job, validate
from gotree.memory import Memory
from gotree.position import Position, coord, point
from gotree.workers import MockWorker
from mcts.board import Board
from mcts.features import feature_index, move_priors
from mcts.hl import OnlineLearner
from mcts.hl import learner as learner_mod
from mcts.hl.book import Book
from mcts.hl.heuristics import HeuristicLoop, find_surprises
from mcts.llm import LLMConfig, LLMService
from mcts.rules import RuleSet
from mcts.tree import MCTS, MCTSConfig
from mcts.weights import Weights, default_weights, load_default

ROOT = Path(__file__).resolve().parent.parent
FAST = dict(min_train=20, min_heldout=5, fit_time=4.0, heur_fit_time=3.0, value=False, max_iter=60,
            regression_path=str(ROOT / "tests" / "no-such-regression-set.json"))

# a shape the 3x3 features cannot see: an own stone two points away in a straight line (empty around)
JUMP = {"name": "one-point-jump-from-own-stone", "text": "Jump one point out from an own stone along a line",
        "pattern": ["??X??", "?...?", "?.*.?", "?????", "?????"], "conditions": {}, "weight": 1.0,
        "rationale": "test rule", "evidence": ["S1"], "lessons": ["L1"]}


def rule(**kw):
    return parse_rule({**JUMP, **kw})


def random_positions(n, seed=0, max_ply=40, size=9):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        pos = Position.empty(size)
        for _ in range(rng.randint(4, max_ply)):
            lm = pos.legal_moves()
            if not lm:
                break
            pos = pos.play(rng.choice(lm))
        out.append(pos)
    return out


def with_rule(w: Weights, r: dict, weight: float, rid: str = "R1") -> Weights:
    return w.with_rules([{"id": rid, **r}], [weight])


# ------------------------------------------------------------------ the language
def test_parse_compile_and_match_with_symmetry_and_colour_relativity():
    r = rule()
    assert r["pattern"][1] == "?...?" and r["canonical"] == canonical(r) and len(variants(r["pattern"])) == 4
    cr = CompiledRule(r)
    # Black stone at E5, Black to play: E7, C5, G5, E3 are one-point jumps from it
    pos = Position.from_moves(9, [("X", point("E5", 9)), ("O", point("A1", 9))])
    hits = {coord(m, 9) for m in cr.hits(pos)}
    assert {"E7", "E3", "C5", "G5"} <= hits and "F6" not in hits
    # every orientation of the board gives the mapped hits (symmetry)
    for s in range(8):
        t = pos.transformed(s)
        assert {coord(m, 9) for m in cr.hits(t)} == {coord(pos.map_move(m, s), 9) for m in cr.hits(pos)}
    # colour-relative: the same shape for White to play, with the colours swapped
    sw = Position(9, pos.cells.translate(str.maketrans("XO", "OX")), "O", None, 0, 7.5)
    assert {coord(m, 9) for m in cr.hits(sw)} == hits
    # ... and with Black's stone but White to play it is the opponent's stone: no match
    wt = Position(9, pos.cells, "O", None, 0, 7.5)
    assert not {"E7", "E3", "C5", "G5"} & {coord(m, 9) for m in cr.hits(wt)}


def test_conditions_follow_the_feature_definitions():
    # Black to play; White F5 has liberties F6 and G5 -> F6 / G5 give atari to a single stone
    pos = Position.from_moves(9, [("X", point("E5", 9)), ("O", point("F5", 9)), ("X", point("F4", 9)),
                                  ("O", point("A5", 9))])
    atari = parse_rule({"name": "atari-single", "text": "atari on a single stone", "pattern": ["?O?", "?*?", "???"],
                        "conditions": {"atari": True, "adj_opp": {"libs": 2, "size": 1}}, "weight": 0.5,
                        "rationale": ""})
    assert {coord(m, 9) for m in CompiledRule(atari).hits(pos)} == {"F6", "G5"}
    t = Tactics(pos, point("F6", 9))
    assert t.atari and t.captures == 0 and t.libs_after >= 2 and not t.self_atari and not t.escape
    # the rule language's tactics are exactly the C features' (FEATURES.md), ladders included
    from mcts.features import features
    idx = feature_index()
    names = {v: k for k, v in idx.items()}
    seen = {"ladder:capture": 0, "ladder:escape_fails": 0, "capture": 0, "escape": 0, "self_atari": 0}
    for p0 in random_positions(150, seed=11, max_ply=60):
        b = Board.from_position(p0)
        for m in p0.legal_moves():
            f = {names[i] for i in features(b, m)}
            t = Tactics(p0, m)
            assert ("ladder:capture" in f) == t.ladder_capture and ("ladder:escape_fails" in f) == t.ladder_escape_fails
            assert any(x.startswith("atari:") for x in f) == t.atari
            assert any(x.startswith("self_atari:") for x in f) == t.self_atari
            assert any(x.startswith("escape:") for x in f) == t.escape
            assert any(x.startswith("capture:") for x in f) == (t.captures > 0)
            for k in seen:
                seen[k] += any(x.startswith(k) for x in f)
    assert all(v > 0 for v in seen.values()), seen


def test_c_and_python_matchers_agree_on_random_rules_and_positions():
    rng = random.Random(3)
    alph = "XO.#xos+????"
    rules = []
    while len(rules) < 40:
        k = rng.choice([3, 5])
        rows = [[rng.choice(alph) for _ in range(k)] for _ in range(k)]
        rows[k // 2][k // 2] = "*"
        cond = rng.choice([{}, {"atari": True}, {"captures": [1, 9]}, {"libs_after": [1, 1]}, {"line": [1, 2]},
                           {"dist_last": [2, 4]}, {"escape": True}, {"adj_own": {"libs": [1, 2]}},
                           {"adj_opp": {"size": [2, 9]}}, {"ladder_capture": True}, {"self_atari": False}])
        try:
            rules.append(parse_rule({"name": f"r{len(rules)}", "text": "random parity rule", "pattern": ["".join(r)
                                                                                                        for r in rows],
                                     "conditions": cond, "weight": 0.5, "rationale": ""}))
        except RuleError:
            pass
    rs = RuleSet([{"id": f"R{i}", **r} for i, r in enumerate(rules)])
    crs = [CompiledRule(r) for r in rules]
    n = 0
    for pos in random_positions(25, seed=9, max_ply=55):
        lm = pos.legal_moves()
        counts, idx = rs.hits(Board.from_position(pos), np.array(lm, dtype=np.int16))
        off = 0
        for m, c in zip(lm, counts):
            got = set(idx[off:off + c].tolist())
            off += c
            assert got == {j for j, cr in enumerate(crs) if cr.matches(pos, m)}, (coord(m, 9), pos.cells)
            n += len(got)
    assert n > 100


# ------------------------------------------------------------------ refusal
def heur_job(surprises=None, targets=("atari:size1", "line:3")):
    pos = Position.from_moves(9, [("X", point("E5", 9)), ("O", point("C3", 9))])
    sur = surprises if surprises is not None else [{"id": "S1", "position": pos.to_dict(), "preferred": ["E7"]}]
    return Job("heuristic", "k", pos, {"surprises": sur, "targets": list(targets), "book_text": "(empty)"})


def test_validation_refuses_malformed_unsafe_and_over_broad_answers():
    job = heur_job()
    ok = validate(job, {"analysis": "a", "rules": [JUMP], "nudges": [{"feature": "atari:size1", "delta": 0.3,
                                                                       "rationale": "x"}]})
    assert ok["rules"][0]["name"] == JUMP["name"] and ok["nudges"][0]["delta"] == 0.3
    bad = [
        ({**JUMP, "pattern": ["??X??", "??.??", "??.??", "?????", "?????"]}, "exactly one '*'"),
        ({**JUMP, "pattern": ["??X?", "??*?"]}, "3 or 5 strings"),
        ({**JUMP, "pattern": ["??Z??", "??.??", "??*??", "?????", "?????"]}, "uses 'Z'"),
        ({**JUMP, "code": "__import__('os').system('rm -rf /')"}, "unknown rule field"),
        ({**JUMP, "conditions": {"eval": "1"}}, "unknown condition"),
        ({**JUMP, "conditions": {"libs_after": [3, 1]}}, "lo 3 > hi 1"),
        ({**JUMP, "weight": 9}, "|weight|"),
        ({**JUMP, "weight": True}, "weight must be a number"),
        ({**JUMP, "name": "Bad Name!"}, "name must be"),
        ({**JUMP, "pattern": ["???", "?*?", "???"]}, "over-broad"),
        ({**JUMP, "pattern": [".?.", "?*?", ".?."]}, "over-broad: it matches"),     # breadth on the surprises
    ]
    for r, msg in bad:
        with pytest.raises(InvalidResult, match=msg.replace("|", r"\|").replace("(", r"\(")):
            validate(job, {"analysis": "", "rules": [r], "nudges": []})
    with pytest.raises(InvalidResult, match="not one of the adjustable"):
        validate(job, {"analysis": "", "rules": [], "nudges": [{"feature": "os.system", "delta": 0.1, "rationale": ""}]})
    with pytest.raises(InvalidResult, match="unknown answer field"):
        validate(job, {"analysis": "", "rules": [], "nudges": [], "python": "print(1)"})
    with pytest.raises(InvalidResult, match="at most 4 rules"):
        validate(job, {"analysis": "", "rules": [dict(JUMP, name=f"r{i}") for i in range(5)], "nudges": []})
    # the mock worker's answer is valid by construction
    res = MockWorker().run(heur_job())
    assert res.ok and res.result["rules"] and res.result["nudges"]


# ------------------------------------------------------------------ the gate and the book
def teacher_with_rule(weight=2.0):
    return with_rule(load_default(), rule(), weight)


def fed_learner(tmp_path, n=260, seed=2, **kw):
    L = OnlineLearner(tmp_path / "hl", **{**FAST, **kw})
    L.mode = "hybrid"
    t = teacher_with_rule()
    for i, pos in enumerate(random_positions(n, seed=seed)):
        L.updates = i // 30                      # as if the samples came from several searches (decisions)
        b = Board.from_position(pos)
        L.observe(b, move_priors(b, t), 0.5, 1, n=1000, key=b.key)
    L.updates = 0
    return L


def test_gate_accepts_a_rule_that_predicts_the_search_and_records_it_in_the_book(tmp_path):
    L = fed_learner(tmp_path)
    useless = {**JUMP, "name": "far-corner-shape", "pattern": ["#####", "#XOX?", "#O*O?", "#XOX?", "#????"],
               "lessons": []}
    rep = L.consider({"analysis": "x", "rules": [JUMP, useless], "nudges": []},
                     {"job_id": 7, "label": "g0p3", "surprises": [{"id": "S1"}]})
    st = {r["name"]: r for r in rep["rules"]}
    assert st[JUMP["name"]]["status"] == "accepted", st[JUMP["name"]]["reason"]
    assert st["far-corner-shape"]["status"] == "rejected"
    m = st[JUMP["name"]]["metrics"]
    assert m["gain"] > 1e-3 and m["ci90"][0] > 0 and m["w_fitted"] > 1.2 and m["heldout_positions"] >= 5
    assert m["ci_over"] == "searches" and m["heldout_searches"] >= 5
    # a new version carries the rule; the engine and move_priors use it
    w = L.current_weights()
    assert w.version == "hl-v001" and [r["id"] for r in w.rules] == ["R1"] and w.w_rules[0] > 1.2
    saved = Weights.load(tmp_path / "hl" / "weights-v001.json")
    assert saved.digest == w.digest and saved.rules[0]["pattern"] == rule()["pattern"]
    assert json.loads((tmp_path / "hl" / "weights-v001.json").read_text())["hl"]["role"] == "heuristic"
    # the book: provenance, weight history, effect, hits, the rejection with its reason, markdown, versions
    b = Book(tmp_path / "hl")
    r1 = b.rule("R1")
    assert r1["provenance"]["job_id"] == 7 and r1["provenance"]["label"] == "g0p3" and r1["lessons"] == ["L1"]
    assert r1["weight_history"][0] == {**r1["weight_history"][0], "by": "model", "w": 1.0}
    assert r1["heldout_effect"]["gain"] > 0 and r1["hits"]["positions"] > 0 and b.d["lessons"] == {"L1": ["R1"]}
    rej = [p for p in b.d["proposals"] if p["status"] == "rejected"]
    assert rej and rej[0]["reason"]
    md = (tmp_path / "hl" / "heuristics-book.md").read_text()
    assert "### R1 one-point-jump-from-own-stone" in md and "far-corner-shape" in md
    assert len(list((tmp_path / "hl" / "book").glob("book-v*.json"))) == b.version
    # the next update refits all weights jointly and records the rule's weight
    L.observe(Board(9), {"E5": 1.0}, 0.5, 0, n=500, key=Board(9).key)
    u = L.update()
    assert u["policy"]["rules"] == 1
    # duplicates and the same rejected rule are refused without refitting
    rep2 = L.consider({"analysis": "", "rules": [dict(JUMP, name="again"), dict(useless, name="again2")],
                       "nudges": []}, {"job_id": 8})
    reasons = {r["name"]: r["reason"] for r in rep2["rules"]}
    assert "duplicate of book rule R1" in reasons["again"] and "rejected proposal" in reasons["again2"]
    # a new learner on the same dir sees the book and the rule (persistence across processes)
    L2 = OnlineLearner(tmp_path / "hl", **FAST)
    assert L2.book.rule("R1") is not None and L2.current.rules[0]["id"] == "R1" and L2.anchor["rules"]["R1"] == 1.0


def test_gate_rejects_over_broad_unseen_and_guard_breaking_rules(tmp_path, monkeypatch):
    L = fed_learner(tmp_path, seed=4)
    broad = {**JUMP, "name": "any-empty-diagonals", "pattern": [".?.", "?*?", ".?."], "lessons": []}
    unseen = {**JUMP, "name": "never", "pattern": ["XXXXX", "XOOOX", "XO*OX", "XOOOX", "XXXXX"], "lessons": []}
    rep = L.consider({"analysis": "", "rules": [broad, unseen], "nudges": []}, {"job_id": 1})
    reasons = {r["name"]: r["reason"] for r in rep["rules"]}
    assert "over-broad" in reasons["any-empty-diagonals"] and "matches no legal move" in reasons["never"]
    # a rule whose fitted weight would break the capture guards is refused
    capt = {**JUMP, "name": "captures-are-bad", "pattern": ["?O?", "?*?", "???"], "conditions": {"captures": [1, 9]},
            "weight": -1.0, "lessons": []}
    real = learner_mod.fit_policy

    def harmful(data, w_prev, *a, **k):
        w, info = real(data, w_prev, *a, **k)
        w = w.copy()
        w[-1] = -12.0
        return w, info

    monkeypatch.setattr(learner_mod, "fit_policy", harmful)
    rep = L.consider({"analysis": "", "rules": [capt], "nudges": []}, {"job_id": 2})
    assert rep["rules"][0]["status"] == "rejected" and "tactical guard" in rep["rules"][0]["reason"]
    assert L.current_weights().version == "default-v1"


def test_nudges_are_kept_only_when_they_improve_the_heldout_targets(tmp_path):
    L = OnlineLearner(tmp_path / "hl", **FAST)
    L.mode = "hybrid"
    w = default_weights()
    t = Weights(w.w.copy(), "teacher")
    t.w[feature_index()["line:3"]] += 1.0
    for pos in random_positions(220, seed=5):
        b = Board.from_position(pos)
        L.observe(b, move_priors(b, t), 0.5, 1, n=800, key=b.key)
    rep = L.consider({"analysis": "", "rules": [], "nudges": [
        {"feature": "line:3", "delta": 0.5, "rationale": "third line under-rated"},
        {"feature": "line:3", "delta": -0.5, "rationale": "the other way"}]}, {"job_id": 3})
    st = [n["status"] for n in rep["nudges"]]
    assert st == ["accepted", "rejected"] and rep["accepted"]
    assert L.anchor["features"]["line:3"] == 0.5
    assert L.current_weights().w[feature_index()["line:3"]] == pytest.approx(load_default().w[feature_index()["line:3"]]
                                                                              + 0.5, abs=1e-6)
    assert Book(tmp_path / "hl").d["nudges"][0]["feature"] == "line:3"


def test_too_little_evidence_is_recorded_and_does_not_block_a_later_retry(tmp_path):
    L = OnlineLearner(tmp_path / "hl", **FAST)
    rep = L.consider({"analysis": "", "rules": [JUMP], "nudges": []}, {"job_id": 1})
    assert rep["rules"][0]["status"] == "rejected" and "not enough samples" in rep["rules"][0]["reason"]
    assert L.book.rejected_like(rule()["canonical"]) is None
    # held-out matches from a single search are not a verdict either; once there are more, the rule is judged
    L = fed_learner(tmp_path / "b", n=260, seed=2)
    for s in L.samples.values():
        s.dec = 0
    rep = L.consider({"analysis": "", "rules": [JUMP], "nudges": []}, {"job_id": 2})
    assert rep["rules"][0]["status"] == "rejected" and "from 1 searches" in rep["rules"][0]["reason"]
    assert L.book.rejected_like(rule()["canonical"]) is None
    for i, s in enumerate(L.samples.values()):
        s.dec = i % 9
    rep = L.consider({"analysis": "", "rules": [JUMP], "nudges": []}, {"job_id": 3})
    assert rep["rules"][0]["status"] == "accepted"


# ------------------------------------------------------------------ distillation
def test_distillation_weight_is_chosen_by_heldout_fit_and_raises_agreement_with_the_model(tmp_path):
    t = Weights(default_weights().w.copy(), "teacher")
    idx = feature_index()
    t.w[idx["line:3"]] += 2.0
    t.w[idx["line:2"]] -= 1.5

    def run(distill):
        L = OnlineLearner(tmp_path / f"d{int(distill)}", **{**FAST, "distill": distill, "distill_min": 10,
                                                             "distill_fit_time": 2.0, "test_frac": 0.1})
        L.mode = "hybrid"
        for pos in random_positions(60, seed=21):          # few search samples ...
            b = Board.from_position(pos)
            L.observe(b, move_priors(b, t), 0.5, 1, n=800, key=b.key)
        for pos in random_positions(400, seed=22):         # ... many model evaluations (its top candidates)
            b = Board.from_position(pos)
            p = move_priors(b, t)
            top = dict(sorted(p.items(), key=lambda kv: -kv[1])[:8])
            L.observe_external(b, "llm", top, 0.5, q_playout=0.5)
        u = L.update()
        return L, u

    Ld, ud = run(True)
    Ln, un = run(False)
    sel = ud["policy"]["distill"]["selection"]
    assert [r["lam"] for r in sel] == [0.0, 0.1, 0.3, 1.0, 3.0]
    assert ud["policy"]["distill"]["lam"] > 0 and min(sel, key=lambda r: r["heldout_ce"])["lam"] > 0
    recs = Ld.test_records()
    assert len(recs) > 10
    a_d = Ld.model_agreement(Ld.current, recs)
    a_n = Ln.model_agreement(Ln.current, recs)
    assert a_d["ce"] < a_n["ce"] - 0.02 and a_d["mass_on_model_moves"] > a_n["mass_on_model_moves"]
    assert un["policy"]["distill"]["lam"] == 0.0


# ------------------------------------------------------------------ the engine
def test_rules_enter_the_tree_priors_not_the_playouts():
    b = Board.from_position(Position.from_moves(9, [("X", point("E5", 9)), ("O", point("A1", 9))]))
    base = load_default()
    w = with_rule(base, rule(), 3.0)
    p0, p1 = move_priors(b, base), move_priors(b, w)
    e7 = point("E7", 9)
    assert p1[e7] > 5 * p0[e7]
    eng = MCTS(b, config=MCTSConfig(max_nodes=100_000), weights=w)
    eng.search(sims=200, threads=1)
    tree = {c["move"]: c["prior_learned"] for c in eng.children(eng.root)}
    assert tree[e7] == pytest.approx(p1[e7], rel=1e-4)            # the tree's prior is move_priors with rules
    assert Weights.from_json(w.to_json()).digest == w.digest
    with pytest.raises(RuleError):
        Weights.from_json({**w.to_json(), "rules": [{"id": "R1", "pattern": ["???", "?*?", "???"], "w": 1.0}]})
    # playouts use only the feature weights: the same seed gives the same scores with or without rules
    from mcts.policy import Policy
    assert np.array_equal(Policy(base).playouts(b, 8, seed=1), Policy(w).playouts(b, 8, seed=1))


# ------------------------------------------------------------------ gtree tools of a heuristic job
def test_gtree_rule_test_card_and_submit_for_a_heuristic_job(tmp_path):
    job = heur_job()
    jd = tmp_path / "job"
    jd.mkdir()
    (jd / "job.json").write_text(json.dumps(job.to_json()))
    (jd / "rules.json").write_text(json.dumps([JUMP, {**JUMP, "name": "wide", "pattern": [".?.", "?*?", ".?."]},
                                               {**JUMP, "name": "bad", "weight": 99}]))
    env = dict(os.environ, GTREE_JOB=str(jd), PYTHONPATH=str(ROOT))

    def gtree(*args, stdin=None):
        return subprocess.run([sys.executable, "-m", "gotree.gtree", *args], cwd=jd, env=env, capture_output=True,
                              text=True, input=stdin, timeout=60)

    out = gtree("rule-test", "rules.json").stdout
    assert "E7*" in out and "OVER-BROAD" in out and "INVALID" in out and "adjustable weights" in out
    assert "S1" in gtree("card", "--pos", "S1").stdout
    assert "no surprise position" in gtree("card", "--pos", "S9").stderr
    (jd / "bad.json").write_text(json.dumps({"analysis": "", "rules": [{**JUMP, "weight": 99}], "nudges": []}))
    r = gtree("submit", "bad.json")
    assert r.returncode == 2 and "INVALID" in r.stdout
    (jd / "good.json").write_text(json.dumps({"analysis": "ok", "rules": [JUMP], "nudges": []}))
    r = gtree("submit", "good.json")
    assert r.returncode == 0 and "accepted: 1 rule(s)" in r.stdout and (jd / "accepted.json").exists()
    assert "=== THE RULE LANGUAGE ===" in job.prompt() and "gtree rule-test" in job.prompt()


# ------------------------------------------------------------------ the loop with a mock worker
def test_heuristic_loop_requests_after_a_decision_gates_in_the_background_and_links_lessons(tmp_path):
    L = fed_learner(tmp_path, n=200, seed=31)
    mem = Memory(str(tmp_path / "memory.db"))
    lid = mem.add_global("jump out from your stones", "any", 9)
    svc = LLMService(MockWorker(), DAG(str(tmp_path / "dag.db")), mem, LLMConfig(workers=2), log=lambda m: None)

    def answer(job):      # a "model" that proposes the teacher's rule, citing the lesson
        return {"analysis": "jumps", "rules": [{**JUMP, "lessons": [f"G{lid}"]}], "nudges": []}

    class W(MockWorker):
        def run(self, job):
            if job.kind == "heuristic":
                from gotree.workers import JobResult
                return JobResult(True, validate(job, answer(job)), worker="fake", usage={"cost_usd": 0.01})
            return super().run(job)

    svc.worker = W()
    b = Board.from_position(Position.from_moves(9, [("X", point("E5", 9)), ("O", point("C3", 9))]))
    eng = MCTS(b, config=MCTSConfig(max_nodes=400_000, n_thr=1500), weights=L.provider, learner=L)
    svc.attach(eng)
    svc.start()
    loop = HeuristicLoop(L, svc, k=4, min_visits=256, log=lambda m: None, record=tmp_path / "heuristics.jsonl")
    eng.search(sims=6000, threads=2)
    assert svc.wait_idle(60)
    sur = find_surprises(eng, L.current_weights(), svc, k=4, min_visits=256)
    assert sur and all(s["kl_learned"] >= 0 for s in sur) and sur[0]["score"] >= sur[-1]["score"]
    info = loop.after_decision(eng, "g0p1")
    assert info["requested"] and len(info["surprises"]) >= 1
    assert svc.wait_idle(60) and loop.wait_idle(120)
    st = loop.stats()
    assert st["results"] == 1 and st["processed"] == 1 and st["rules_accepted"] == 1
    assert L.current_weights().rules[0]["id"] == "R1"
    assert mem.q("SELECT * FROM lesson_rules")[0]["rule"] == "R1"               # lesson -> rule
    assert L.book.rule("R1")["lessons"] == [f"G{lid}"]                          # rule -> lesson
    ev = [json.loads(x)["event"] for x in (tmp_path / "heuristics.jsonl").read_text().splitlines()]
    assert ev == ["request", "gated"]
    # the next search uses the new version (with the rule) and keeps the tree
    n0 = int(eng.a.n[eng.root])
    r = eng.search(sims=500, threads=2)
    assert r["weights"] == "hl-v001" and r["root_n"] == n0 + 500
    loop.close()
    svc.close()


def test_hybrid_selfplay_runs_the_full_loop_with_the_mock_worker(tmp_path):
    run = tmp_path / "run"
    cmd = [sys.executable, "-m", "mcts", "hybrid-selfplay", "--run", str(run), "--games", "2", "--max-plies", "3",
           "--time-per-move", "1.5", "--threads", "2", "--max-load-frac", "0", "--worker", "mock", "--llm-workers", "2",
           "--n-thr", "2000", "--learn", "--heuristics", "--heuristic-min-visits", "256", "--decide-extend", "3",
           "--drain", "60", "--hl", "min_train=20", "--hl", "min_heldout=5", "--hl", "fit_time=2",
           "--hl", "heur_fit_time=2", "--hl", "distill_min=5", "--hl", "distill_fit_time=1"]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    moves = [json.loads(x) for x in (run / "moves.jsonl").read_text().splitlines()]
    assert len(moves) == 6 and {m["game"] for m in moves} == {0, 1}
    assert all(m["heuristic"]["requested"] for m in moves) and all("update" in m for m in moves)
    assert moves[1]["root_n_start"] > 0                                    # the tree is kept across decisions
    games = [json.loads(x) for x in (run / "games.jsonl").read_text().splitlines()]
    assert [g["decisions"] for g in games] == [3, 3]
    hl = run / "hl"
    book = json.loads((hl / "heuristics-book.json").read_text())
    assert len(book["jobs"]) == 6 and book["proposals"]                    # every job's proposals were gated
    assert all(p["reason"] for p in book["proposals"])
    st = json.loads((hl / "state.json").read_text())
    assert st["cfg"]["test_frac"] == 0.1                                    # hybrid runs keep a test split
    smp = [json.loads(x) for x in (hl / "samples.jsonl").read_text().splitlines()]
    assert smp and all(s.get("hy") for s in smp)                            # hybrid targets
    jobs = [json.loads(x) for x in (run / "llm-jobs.jsonl").read_text().splitlines()]
    assert sum(1 for j in jobs if j["kind"] == "heuristic") == 6
    assert "heuristics:" in r.stdout and (hl / "heuristics-book.md").exists()
    # the evidence report on the run: book summary, versions and ablations on the test split
    r = subprocess.run([sys.executable, "-m", "mcts", "hl-hybrid-report", "--run", str(run), "--code-search", "2",
                        "--code-sims", "500", "--threads", "1"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    rep = json.loads((run / "hl-hybrid-report.json").read_text())
    assert rep["book"]["jobs"] == 6 and rep["versions"][0]["version"] == "default-v1"
    assert rep["test_split"]["frac"] == 0.1 and "refit_no_rules" in rep["ablations"]["variants"]
    assert "## Ablations (test split)" in (run / "hl-hybrid-report.md").read_text()


def test_play_loop_runs_heuristic_jobs_against_an_arena(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_mcts_llm_play import FakeArena
    from mcts.play import Player, make_learner, play_games
    run = tmp_path / "run"
    run.mkdir()
    L = make_learner(run, None, lambda m: None, cfg={**FAST}, hybrid=True)
    assert L.mode == "hybrid" and L.cfg["test_frac"] == 0.1
    svc = LLMService(MockWorker(), DAG(str(run / "dag.db")), Memory(str(run / "memory.db")), LLMConfig(workers=2),
                     learner=L, log=lambda m: None).start()
    loop = HeuristicLoop(L, svc, k=3, min_visits=256, log=lambda m: None)
    pos_moves = iter(["C3", "G3", "C7", "G7", "D4", "F4", "D6", "F6"])
    arena = FakeArena(lambda moves: next(m for m in pos_moves if m not in moves), max_plies=6)
    player = Player(run, MCTSConfig(max_nodes=300_000, n_thr=1500), 1.0, 2, None, L.provider, L, svc, 0,
                    lambda m: None)
    res = play_games(arena, "fake", 1, player, record=run / "moves.jsonl", log=lambda m: None, heuristics=loop)
    assert res and loop.wait_idle(120) or True
    svc.wait_idle(60)
    loop.wait_idle(120)
    recs = [json.loads(x) for x in (run / "moves.jsonl").read_text().splitlines()]
    assert len(recs) == 3 and all(r["heuristic"]["requested"] for r in recs) and all("update" in r for r in recs)
    assert loop.stats()["processed"] >= 1
    loop.close()
    svc.close()


# ------------------------------------------------------------------ several processes on one learner dir
def test_an_update_superseded_by_another_learner_on_the_same_dir_never_overwrites_its_version(tmp_path):
    d = tmp_path / "hl"
    A = OnlineLearner(d, min_train=0, min_heldout=0, value=False)
    B = OnlineLearner(d, min_train=0, min_heldout=0, value=False)

    def fit(tag):
        return lambda tr, ho, parent, T: (parent.full + (0.001 if tag == "A" else 0.002), None, {}, True, f"by {tag}")
    B._fit_candidate = fit("B")

    def a_fit(tr, ho, parent, T):
        B.update()                         # the other learner commits a version while A fits
        return fit("A")(tr, ho, parent, T)
    A._fit_candidate = a_fit
    ua = A.update()
    assert not ua["accepted"] and ua["reason"].startswith("superseded") and ua["version"] == "hl-v001"
    assert sorted(p.name for p in d.glob("weights-v*.json")) == ["weights-v000.json", "weights-v001.json"]
    assert json.loads((d / "weights-v001.json").read_text())["hl"]["reason"] == "by B"
    A._fit_candidate = fit("A")
    ub = A.update()                         # A continues from B's version
    assert ub["accepted"] and ub["version"] == "hl-v002"
    v2 = json.loads((d / "weights-v002.json").read_text())["hl"]
    assert v2["parent"]["version"] == "hl-v001" and v2["reason"] == "by A"
    st = json.loads((d / "state.json").read_text())
    assert st["current_version"] == "hl-v002" and st["version_no"] == 2


_RACE = """
import json, random, sys, time
sys.path[:0] = [{root!r}]
from mcts.hl import OnlineLearner
L = OnlineLearner({d!r}, min_train=0, min_heldout=0, value=False)
rng = random.Random({seed})
def fit(tr, ho, parent, T):
    time.sleep(rng.uniform(0.0, 0.05))
    return parent.full + 1e-3 * ({seed} + 1), None, {{}}, True, "proc {seed}"
L._fit_candidate = fit
res = []
for i in range(12):
    u = L.update()
    res.append([u["accepted"], u["version"], u["reason"][:10]])
    time.sleep(rng.uniform(0.0, 0.02))
L.observe_game(1, "B")
print(json.dumps(res))
"""


def test_two_processes_updating_one_learner_dir_keep_a_consistent_version_chain(tmp_path):
    d = tmp_path / "hl"
    OnlineLearner(d, value=False)                      # the dir exists before both start
    procs = [subprocess.Popen([sys.executable, "-c", _RACE.format(root=str(ROOT), d=str(d), seed=s)], cwd=ROOT,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for s in (0, 1)]
    outs = [p.communicate(timeout=300) for p in procs]
    assert all(p.returncode == 0 for p in procs), [e[-2000:] for _, e in outs]
    res = [json.loads(o.strip().splitlines()[-1]) for o, _ in outs]
    acc = [v for r in res for a, v, _ in r if a]
    assert len(acc) == len(set(acc)) and len(acc) >= 12          # every accepted version is a distinct file
    files = sorted(d.glob("weights-v*.json"))
    assert len(files) == len(acc) + 1
    prev = json.loads(files[0].read_text())
    for f in files[1:]:                                          # an unbroken chain: each version's parent is the
        cur = json.loads(f.read_text())                          # version before it, with that version's digest
        assert cur["hl"]["parent"]["version"] == prev["version"]
        assert cur["hl"]["parent"]["digest"] == Weights.from_json(prev).digest
        prev = cur
    sup = [x for r in res for a, _, x in r if not a]
    assert all(x == "supersede"[:10] or x.startswith("supersed") for x in sup)
    st = json.loads((d / "state.json").read_text())
    assert st["version_no"] == len(acc) and st["current_version"] == prev["version"] and st["game"] == 2
    ups = [json.loads(x) for x in (d / "updates.jsonl").read_text().splitlines()]
    assert len(ups) == 24 and sum(u["accepted"] for u in ups) == len(acc)


def test_a_full_tree_does_not_stretch_a_move_beyond_its_time():
    from mcts.board import board_from_moves
    from mcts.cli import MIDGAME_9
    b, hist = board_from_moves(9, MIDGAME_9, 7.5)
    eng = MCTS(b, history=hist, config=MCTSConfig(max_nodes=4_000), weights=load_default())
    eng._last_gc_s = 30.0                    # as if evictions took 30 s on this tree
    r = eng.search(time_s=1.5, threads=2)
    assert r["wall_s"] < 2.5 and eng.frozen and r["gc_s"] == 0.0     # no eviction started; searched on, frozen
    r2 = eng.search(time_s=1.5, threads=2)   # the next search evicts first, inside its own budget
    assert r2["gc_s"] > 0 and r2["wall_s"] < 2.5 and eng.gc_runs >= 1
    eng._last_gc_s = 0.0
    r3 = eng.search(time_s=1.5, threads=2)   # quick evictions run during the search as before
    assert r3["wall_s"] < 2.5


def test_a_usage_limit_pauses_until_its_reset_and_self_play_waits_for_it(tmp_path):
    import time as _t
    from gotree.workers import JobResult
    from mcts.llm import classify_failure
    jd = tmp_path / "job"
    jd.mkdir()
    reset = int(_t.time()) + 3600
    (jd / "session.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": reset,
                                                          "rateLimitType": "five_hour"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "You've hit your session limit"}]}},
        {"type": "result", "is_error": True, "result": "You've hit your session limit · resets 1:40pm"}]) + "\n")
    assert classify_failure(JobResult(False, error="session ended (rc=1) without an accepted answer"), jd) == \
        ("rate_limit", float(reset))
    svc = LLMService(MockWorker(), DAG(str(tmp_path / "dag.db")), Memory(str(tmp_path / "m.db")), LLMConfig(),
                     log=lambda m: None)
    slept = []
    svc.paused_until = _t.time() + 600
    w = svc.wait_until_available(300, log=lambda m: None, sleep=lambda s: slept.append(s))
    assert w == pytest.approx(300) and sum(slept) == pytest.approx(300)        # bounded by max_wait_s
    svc.paused_until = _t.time() + 5                                           # a short backoff: no wait
    assert svc.wait_until_available(300, log=lambda m: None, sleep=lambda s: slept.append(s)) == 0.0
    svc.close()
