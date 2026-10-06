"""Tests for the tree-search harness (no LLM, no KataGo needed)."""
import threading
from pathlib import Path

import pytest

from gotree.dag import DAG
from gotree.jobs import InvalidResult, Job, validate
from gotree.memory import Memory, local_pattern
from gotree.perception import benson_alive, chains, ladder_captured, position_card
from gotree.position import IllegalMove, Position, coord, point, sym_maps
from gotree.search import Search, SearchConfig
from gotree.workers import APIWorker, CLIWorker, MockWorker

ROOT = Path(__file__).resolve().parent.parent
G2 = ROOT / "data/alphago-leesedol-2016-g2.sgf"


def play(pos, *moves):
    for m in moves:
        pos = pos.play(None if m == "pass" else point(m, pos.size))
    return pos


# ------------------------------------------------------------------ position
def test_ko_and_suicide():
    p = play(Position.empty(9), "D4", "E4", "C5", "F5", "D6", "E6", "J1", "D5", "E5")
    assert p.cells[point("D5", 9)] == "." and p.ko == point("D5", 9)
    with pytest.raises(IllegalMove) as e:
        p.play(point("D5", 9))
    assert e.value.code == "ko"
    q = play(Position.empty(9), "A2", "J9", "B1")
    with pytest.raises(IllegalMove) as e:
        q.play(point("A1", 9))
    assert e.value.code == "suicide"


def test_symmetry_and_transpositions():
    a = play(Position.empty(9), "C3", "G7", "C7")
    b = play(Position.empty(9), "C7", "G7", "C3")          # different order, same position
    assert a.key == b.key
    for s in range(8):
        assert a.transformed(s).key == a.key               # all orientations share one node
    fwd, inv = sym_maps(9)
    for s in range(8):
        assert all(inv[s][fwd[s][p]] == p for p in range(81))


def test_dag_merges_transpositions_and_backs_up(tmp_path):
    dag = DAG(str(tmp_path / "d.db"))
    root, can, _ = dag.ensure(Position.empty(9))
    e1 = dag.add_edge(root, point("C3", 9), 0.5, "llm")
    e2 = dag.add_edge(root, point("G7", 9), 0.5, "llm")     # symmetric to C3 on an empty board
    assert e1.child == e2.child
    dag.backup([(root, point("C3", 9))], e1.child, 0.25)
    n = dag.node(e1.child)
    assert n["n"] == 1 and abs(n["w"] - 0.25) < 1e-9
    r = dag.node(root)
    assert r["n"] == 1 and abs(r["w"] - 0.75) < 1e-9       # value flips perspective
    st = {c["move"]: c for c in dag.child_stats(root)}
    assert abs(st[point("C3", 9)]["q"] - 0.75) < 1e-9
    assert abs(st[point("G7", 9)]["q"] - 0.75) < 1e-9       # shared through the transposition


# ------------------------------------------------------------------ perception
def _setup(black, white, to="X", size=9):
    cells = ["."] * (size * size)
    for c in black:
        cells[point(c, size)] = "X"
    for c in white:
        cells[point(c, size)] = "O"
    return Position(size, "".join(cells), to)


def test_ladder_reader():
    # textbook ladder: White D4 (2 liberties) against Black D5, C4, E3 runs to the edge both ways
    assert ladder_captured(_setup(["D5", "C4", "E3"], ["D4"]), point("D4", 9)) is True
    # a breaker on only one path does not help (Black chooses the other direction) ...
    assert ladder_captured(_setup(["D5", "C4", "E3"], ["D4", "B2"]), point("D4", 9)) is True
    # ... breakers on both paths do
    assert ladder_captured(_setup(["D5", "C4", "E3"], ["D4", "G7", "B2"]), point("D4", 9)) is False
    # 3+ liberties: not a ladder question
    assert ladder_captured(play(Position.empty(9), "E5"), point("E5", 9)) is None


def test_benson_two_eyes():
    rows = ["XXXXX....",
            "X.X.X....",
            "XXXXX....",
            "........."] + ["........."] * 5
    pos = Position(9, "".join(rows), "O")
    alive = benson_alive(pos, "X")
    assert point("A9", 9) in alive and point("E7", 9) in alive
    assert not benson_alive(Position(9, "".join(rows).replace("X.X.X", "X.XXX"), "O"), "X")


def test_position_card_mentions_atari():
    pos = Position.from_sgf(G2.read_text(), upto=36)
    card = position_card(pos)
    assert "IN ATARI" in card and "To play: Black" in card and len(chains(pos)) == 26


def test_local_pattern_is_colour_and_symmetry_invariant():
    a = play(Position.empty(9), "C3", "D4")               # White to move
    b = play(Position.empty(9), "G7", "F6")               # mirror image
    assert local_pattern(a, point("C4", 9), 2) == local_pattern(b, point("G6", 9), 2)


# ------------------------------------------------------------------ jobs
def test_validation_rejects_illegal_and_normalises():
    pos = play(Position.empty(9), "E5")
    job = Job("expand", pos.key, pos, {"k": 4})
    r = validate(job, {"candidates": [{"move": "E5", "prior": 0.9}, {"move": "C3", "prior": 2},
                                      {"move": "D4", "prior": 2}],
                       "value": {"winrate": 0.4, "confidence": "high", "why": "x"}})
    assert [coord(c["move"], 9) for c in r["candidates"]] == ["C3", "D4"]
    assert abs(sum(c["prior"] for c in r["candidates"]) - 1) < 1e-9 and r["warnings"]
    with pytest.raises(InvalidResult):
        validate(job, {"candidates": [], "value": {"winrate": 2}})


# ------------------------------------------------------------------ search
def _search(tmp_path, worker=None, **cfg):
    dag, mem = DAG(str(tmp_path / "dag.db")), Memory(str(tmp_path / "mem.db"))
    return Search(dag, mem, {"default": worker or MockWorker(seed=3)},
                  SearchConfig(log_every=0, **cfg), log=lambda m: None)


def test_search_runs_and_reuses_tree(tmp_path):
    s = _search(tmp_path, budget=60, workers=4)
    pos = play(Position.empty(9), "E5", "C5")
    out = s.run(pos, "t1")
    assert out["decision"]["real"] != "pass" and out["jobs"] >= 50 and out["failed"] == 0
    assert all(v == 0 for v in s.pending.values()) and not s.vloss       # no leaked virtual loss
    before = s.dag.node(pos.key)["n"]
    s.run(pos, "t2")                                                # same position again: tree reuse
    assert s.dag.node(pos.key)["n"] > before
    assert s.mem.export_markdown().count("[G") >= 1                        # abstract wrote lessons


def test_probe_target_tracking_on_move37(tmp_path):
    from gotree.probe import run_probe
    s = _search(tmp_path, budget=40, workers=4)
    rep = run_probe(str(G2), 37, s, recall=True, out_dir=tmp_path)
    assert rep["target_real"] == "P10" and rep["to_play"] == "B"
    assert rep["decision"]["real"] and rep["discovery_curve"]
    assert (tmp_path / "probe-alphago-leesedol-2016-g2-37.json").exists()


def test_cli_worker_protocol(tmp_path):
    """Full job-directory protocol with a fake Claude Code binary."""
    dag_path, mem_path = str(tmp_path / "dag.db"), str(tmp_path / "mem.db")
    w = CLIWorker("claude", "fake", tmp_path, dag_path, mem_path,
                  binary=str(ROOT / "tests/fake_tree_agent.py"), timeout=120)
    s = Search(DAG(dag_path), Memory(mem_path), {"default": w}, SearchConfig(budget=6, workers=2, log_every=0,
                                                                              root_scouts=False), log=lambda m: None)
    out = s.run(play(Position.empty(9), "E5"), "cli")
    assert out["failed"] == 0 and out["jobs"] >= 6
    assert s.dag.q1("SELECT COUNT(*) AS n FROM evals WHERE kind='try_end'")["n"] >= 1   # gtree try lines ingested
    assert out["usage"]["cost_usd"] > 0


class ScriptedLLM:
    """Fake LLM for the API worker: reads a line with try_moves, then submits."""
    model = "scripted"

    def __init__(self):
        self.step = 0

    def complete(self, system, messages, tools):
        from harness.dojo.llm import LLMResponse
        names = {t.name for t in tools}
        assert "submit" in names and "try_moves" in names
        self.step += 1
        if self.step % 2 == 1:
            return LLMResponse("", [{"id": f"t{self.step}", "name": "try_moves", "args": {"moves": ["C3", "D4"]}}],
                               {"input": 10, "output": 5})
        if "rollout" in system and "SELF-PLAY JOB" in system:
            ans = {"moves": ["C3"], "value_at_end": {"winrate": 0.5, "confidence": "low", "why": "x"}}
        elif "MEMORY JOB" in system:
            ans = {"lessons": [{"scope": "global", "text": "x"}]}
        else:
            ans = {"candidates": [{"move": "C3", "prior": 0.6}, {"move": "G7", "prior": 0.3}],
                   "value": {"winrate": 0.55, "confidence": "low", "why": "x"}}
        return LLMResponse("", [{"id": f"s{self.step}", "name": "submit", "args": ans}], {"input": 10, "output": 5})


def test_api_worker_tool_loop(tmp_path):
    s = _search(tmp_path, worker=APIWorker(ScriptedLLM()), budget=8, workers=1, root_scouts=False)
    out = s.run(play(Position.empty(9), "E5"), "api")
    assert out["failed"] == 0 and {c["real"] for c in out["candidates"]} >= {"C3"}


def test_play_arena_game(tmp_path):
    from goarena.arena import Arena, ArenaSettings
    from goarena.opponents import load_tiers
    from goarena.server import serve
    from goarena.store import Store
    from gotree.play import play_games
    from harness.arena_client import ArenaClient
    tiers = {k: v for k, v in load_tiers(ROOT / "config/tiers-9x9.json").items() if v.kind == "random"}
    arena = Arena(Store(str(tmp_path / "a.db")), ArenaSettings(tiers=tiers, review_visits=0), None, seed=1)
    httpd = serve(arena, "127.0.0.1", 0, "adm")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    run = ArenaClient(url, admin_token="adm").create_run(name="tree", target_games=1)["run"]
    s = _search(tmp_path, budget=4, workers=2, abstract=False, root_scouts=False)
    res = play_games(ArenaClient(url, token=run["token"]), s, "random", 1, "black", log=lambda m: None)
    assert len(res) == 1 and res[0]["result"]
    httpd.shutdown()
    arena.stop()


def test_consolidation_builds_concept_dag(tmp_path):
    mem = Memory(str(tmp_path / "m.db"))
    pos = play(Position.empty(9), "C3")
    a = mem.add_global("attack weak groups from the side you want to build on")
    b = mem.add_global("attack weak groups from the side where you want to build")   # duplicate
    c = mem.add_local(pos, point("D4", 9), "a diagonal attachment here is usually slow", {"key": "k"})
    res = validate(Job("consolidate", "-", pos), {"merge": [{"keep": f"G{a}", "retire": [f"G{b}"], "text": "merged"}],
                                                  "concepts": [{"text": "use attacks to gain", "children": [f"G{a}", f"L{c}"]}],
                                                  "contradictions": [], "retire": []})
    notes = mem.apply_consolidation(res)
    assert any("merged" in n for n in notes) and any("concept" in n for n in notes)
    md = mem.export_markdown()
    assert "use attacks to gain" in md and "  - [G" in md and "merged" in md
    assert mem.q("SELECT status FROM lessons WHERE id=?", (b,))[0]["status"] == "retired"


def test_prior_check_with_mock():
    from gotree.probe import prior_check
    out = prior_check(str(G2), 37, MockWorker(seed=1), samples=2)
    assert out["target_real"] == "P10" and len(out["samples"]) == 2 and out["proposed_rate"] is not None


# ------------------------------------------------------------------ regressions from code review
def test_summary_lines_are_legal_in_the_root_frame(tmp_path):
    s = _search(tmp_path, budget=60, workers=4)
    pos = Position.from_sgf(G2.read_text(), upto=36)
    out = s.run(pos, "pv")
    can = s.dag.position(s.root)
    st = s.dag.child_stats(s.root)
    for e in st:
        cur = can.play(e["move"])
        for c in s._pv_frame(e["child"], e["child_sym"], can.size):
            cur = cur.play(point(c, can.size))          # raises if the line mixes frames
    for c in out["candidates"]:                          # real coordinates are legal on the real board
        assert pos.is_legal(point(c["real"], pos.size))
        nxt = pos.play(point(c["real"], pos.size))
        assert any(e["child"] == nxt.key for e in st)


def test_empty_regional_scout_does_not_exhaust_the_root(tmp_path):
    from gotree.search import Plan
    from gotree.workers import JobResult
    s = _search(tmp_path, budget=1, workers=1)
    pos = Position.from_sgf(G2.read_text(), upto=36)
    s.run(pos, "x")
    plan = Plan("more", s.root, [], {"region": "upper-left corner", "k": 3, "u": 1})
    s.pending[s.root] = 1
    job = Job("more", s.root, s.dag.position(s.root), plan.params)
    s._integrate(plan, job, JobResult(True, {"candidates": [], "unconventional": [],
                                             "value": {"winrate": 0.5, "score_lead": None, "confidence": "low",
                                                       "why": ""}, "plan": ""}))
    assert s.dag.node(s.root)["exhausted"] == 0


def test_draw_value_and_handicap_setup_and_empty_moves():
    p = Position(5, "XX..." * 2 + "....." + "OO..." * 2, "O", None, 2, 0.0)
    assert p.area_score() == 0 and p.terminal_value() == 0.5
    assert Position(p.size, p.cells, "X", None, 2, 0.0).terminal_value() == 0.5
    h = Position.from_sgf("(;SZ[9]KM[0.5]HA[2]AB[cc][gg];W[ee])")
    assert h.stones() == 3 and h.to_play == "X"
    job = Job("decide", h.key, h, {})
    with pytest.raises(InvalidResult):
        validate(job, {"move": "", "why": "x"})


def test_cli_worker_ignores_stale_answers(tmp_path):
    w = CLIWorker("claude", "", tmp_path, str(tmp_path / "d.db"), str(tmp_path / "m.db"), binary="/bin/true")
    pos = play(Position.empty(9), "E5")
    job = Job("recall", pos.key, pos, {})
    (tmp_path / "jobs" / "000000-recall").mkdir(parents=True)
    (tmp_path / "jobs" / "000000-recall" / "accepted.json").write_text('{"recognized": true}')
    assert not w.run(job).ok


def test_lesson_export_shows_every_active_lesson(tmp_path):
    mem = Memory(str(tmp_path / "m.db"))
    a, b = mem.add_global("alpha"), mem.add_global("beta")
    assert not mem.link(a, a, "refines")                     # no self links
    mem.relate(a, b, "contradicts")
    mem.relate(b, a, "contradicts")                          # a 2-cycle
    md = mem.export_markdown()
    assert "alpha" in md and "beta" in md
    assert mem.relate(a, 999, "refines") is False            # unknown ids are ignored


def test_usage_is_per_decision(tmp_path):
    s = _search(tmp_path, budget=10, workers=2, root_scouts=False, early_stop=False)
    a = s.run(play(Position.empty(9), "E5"), "a")
    b = s.run(play(Position.empty(9), "E5", "C3"), "b")
    assert a["jobs"] == 10 and b["jobs"] == 10 and s.total_usage["jobs"] == 20


def test_judge_rebuilds_ko_for_katago():
    from gotree.judge import _ko_setup
    p = play(Position.empty(9), "D4", "E4", "C5", "F5", "D6", "E6", "J1", "D5", "E5")
    before, mv = _ko_setup(p)
    after = before.play(mv)
    assert after.cells == p.cells and after.ko == p.ko
