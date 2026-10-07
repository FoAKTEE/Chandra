"""MCTS v2 tree: tactics, thread safety, transpositions, reuse, eviction, persistence, superko, hooks."""
import queue
import threading
import time

import numpy as np
import pytest

from gotree.position import IllegalMove, Position, point
from mcts.board import Board, board_from_moves
from mcts.features import move_priors
from mcts.tree import FL_EXT, MCTS, MCTSConfig, ST_EXPANDED
from mcts.weights import FileWeights, Weights, default_weights


def mk(rows, to_play="X"):
    return Board.from_position(Position(9, "".join(r.replace(" ", "") for r in rows), to_play))


def cfg(**kw):
    kw.setdefault("max_nodes", 200_000)
    return MCTSConfig(**kw)


CAPTURE = [". . . . . . . . .",
           ". . . . . . . . .",
           ". . X X X . . . .",
           ". X O O O X . . .",
           ". . X X O X . . .",
           ". . . . . . . . .",
           ". . . . . . . . .",
           ". . . . . . . . .",
           ". . . . . . . . ."]
SAVE = [". . . . . . . . .",
        ". . . . . . . . .",
        ". . . O O . . . .",
        ". . O X X O . . .",
        ". . O X X O . . .",
        ". . . O . . X . .",
        ". . . . . X X . .",
        ". . . . . . . . .",
        ". . . . . . . . ."]
SELF_ATARI = [". . . . . . X . .",
              ". . O O O . X . .",
              ". O X X X O X . .",
              ". O X . X O X . .",          # D6 would connect 7 black stones into one liberty (D4)
              ". . O X O . X . .",
              ". . . . . . X . .",
              "X X X X X X X . .",
              ". . . . . . . . .",
              ". . . . . . . . ."]


def _search(board, sims=2000, threads=1, seed=0, **kw):
    eng = MCTS(board, config=cfg(seed=seed, **kw))
    r = eng.search(sims=sims, threads=threads)
    return eng, r


@pytest.mark.parametrize("seed", [0, 1])
def test_finds_one_move_capture(seed):
    eng, r = _search(mk(CAPTURE), seed=seed)
    assert r["best"] == "E4"


@pytest.mark.parametrize("seed", [0, 1])
def test_saves_group_in_atari(seed):
    eng, r = _search(mk(SAVE), seed=seed)
    assert r["best"] == "E4"


@pytest.mark.parametrize("seed", [0, 1])
def test_does_not_self_atari(seed):
    b = mk(SELF_ATARI)
    eng, r = _search(b, sims=3000, seed=seed)
    assert r["best"] != "D6" and r["q"] > 0.7
    d6 = next(m for m in r["moves"] if m["coord"] == "D6")
    assert d6["n"] <= 5
    nb = b.played(r["best_move"])                  # the chosen move keeps at least two liberties
    p = r["best_move"]
    assert p is None or len(nb.to_position().chain(p)[1]) >= 2


def test_single_thread_search_is_deterministic():
    a = _search(mk(SAVE), sims=800, seed=3)[1]
    b = _search(mk(SAVE), sims=800, seed=3)[1]
    assert [(m["coord"], m["n"]) for m in a["moves"]] == [(m["coord"], m["n"]) for m in b["moves"]]


def _check_visit_invariants(eng, exact=True):
    """Visits into a node through edges equal its visits (>= after eviction: a transposed node keeps
    the visits that came through parents that were evicted)."""
    a, nn, ne = eng.a, eng.n_nodes, eng.n_edges
    assert (a.vl[:nn] == 0).all()                         # no virtual loss left behind
    ch, en = a.e_child[:ne], a.e_n[:ne]
    # edges of expanded nodes only (the pool holds no garbage before a gc)
    into = np.bincount(ch[ch >= 0], weights=en[ch >= 0], minlength=nn)
    others = np.arange(nn) != eng.root
    got, n = into[others].astype(np.int64), a.n[:nn][others].astype(np.int64)
    assert np.array_equal(got, n) if exact else (got <= n).all()
    return into


def _check_child_keys(eng, limit=400):
    """Every linked child is the position its edge's move leads to (checked breadth first)."""
    a, todo, seen, checked = eng.a, [(eng.root, eng.root_board)], {eng.root}, 0
    while todo and checked < limit:
        i, b = todo.pop(0)
        for c in eng.children(i):
            if c["child"] < 0:
                continue
            nb = b.played(c["move"])
            assert int(a.key[c["child"]]) == nb.key
            checked += 1
            if c["child"] not in seen:
                seen.add(c["child"])
                todo.append((c["child"], nb))
    return checked


def test_visit_totals_equal_simulations_with_threads():
    eng = MCTS(Board(9), config=cfg())
    r1 = eng.search(sims=6000, threads=8)
    assert r1["sims"] == 6000 and eng.a.n[eng.root] == 6000
    assert sum(c["n"] for c in eng.children(eng.root)) == 6000
    r2 = eng.search(sims=3000, threads=8)
    assert r2["sims"] == 3000 and eng.a.n[eng.root] == 9000 and r2["root_n"] == 9000
    _check_visit_invariants(eng)
    assert _check_child_keys(eng) >= 400


def test_transpositions_share_nodes():
    eng = MCTS(Board(9), config=cfg())
    a, _ = board_from_moves(9, [point(c, 9) for c in "C3 G7 C7".split()])
    b, _ = board_from_moves(9, [point(c, 9) for c in "C7 G7 C3".split()])
    assert eng._node_for(a) == eng._node_for(b)
    eng2 = MCTS(Board(5, 0.5), config=cfg())
    eng2.search(sims=20000, threads=4)
    into = _check_visit_invariants(eng2)
    ch = eng2.a.e_child[:eng2.n_edges]
    indeg = np.bincount(ch[ch >= 0], minlength=eng2.n_nodes)
    assert (indeg >= 2).sum() > 10                        # positions reached by several move orders
    assert into.sum() > 0 and _check_child_keys(eng2) >= 400


def _snapshot(eng, root):
    mark = np.zeros(eng.n_nodes, np.uint8)
    from mcts._lib import lib
    lib.mc_tree_mark(eng._t, root, mark.ctypes.data)
    a, snap = eng.a, {}
    for i in np.flatnonzero(mark):
        e0, ne = int(a.estart[i]), int(a.nedges[i]) if a.state[i] == ST_EXPANDED else 0
        edges = [(int(a.e_move[e]), float(a.e_prior[e]), int(a.e_n[e]),
                  int(a.key[a.e_child[e]]) if a.e_child[e] >= 0 else None) for e in range(e0, e0 + ne)]
        snap[int(a.key[i])] = (int(a.n[i]), float(a.w[i]), int(a.nx[i]), float(a.wx[i]), int(a.state[i]), edges)
    return snap


def test_advance_keeps_subtree_statistics_exactly():
    eng = MCTS(Board(9), config=cfg(max_nodes=100_000))
    eng.search(sims=8000, threads=4)
    best = eng.best_move()
    child = next(c["child"] for c in eng.children(eng.root) if c["move"] == best)
    before = _snapshot(eng, child)
    eng.advance(best)
    assert eng.root == child and eng.a.n[eng.root] == before[int(eng.a.key[child])][0]
    assert _snapshot(eng, eng.root) == before
    info = eng.gc(low_water=0.0)                           # evict everything outside the subtree
    assert info["evicted"] > 0 and info["after"] == len(before)
    assert _snapshot(eng, eng.root) == before              # compaction keeps every statistic
    r = eng.search(sims=2000, threads=4)                   # and the tree keeps working
    assert r["root_n"] == before[int(eng.a.key[eng.root])][0] + 2000
    _check_visit_invariants(eng, exact=False)
    # the opponent's reply: also a node we already had, or a new one
    eng.advance(eng.best_move())
    assert eng.a.n[eng.root] > 0


def test_eviction_rule_and_full_tree():
    eng = MCTS(Board(9), config=cfg(max_nodes=4000, max_edges=4000 * 40))
    r = eng.search(sims=20000, threads=4)                  # far more simulations than nodes
    assert r["sims"] == 20000 and eng.a.n[eng.root] == 20000
    assert eng.n_nodes <= 4000 and (r["frozen"] or r["gc_rounds"] > 0)
    eng.advance(eng.best_move())
    eng.advance(eng.best_move())
    keep = _snapshot(eng, eng.root)
    a = eng.a
    outside = {int(a.key[i]): int(a.n[i]) for i in range(eng.n_nodes) if int(a.key[i]) not in keep}
    info = eng.gc(low_water=0.5)
    assert info["reachable"] == len(keep) and _snapshot(eng, eng.root) == keep
    assert eng.n_nodes <= max(len(keep), int(0.5 * 4000)) and info["evicted"] > 0
    kept = {int(a.key[i]) for i in range(eng.n_nodes)} - set(keep)
    evicted = set(outside) - kept
    assert evicted and min((outside[k] for k in kept), default=10**9) >= max(outside[k] for k in evicted)
    r = eng.search(sims=3000, threads=4)
    assert r["sims"] == 3000


def test_save_load_round_trip(tmp_path):
    eng = MCTS(Board(9), config=cfg(max_nodes=100_000))
    eng.search(sims=3000, threads=4)
    eng.advance(eng.best_move())
    eng.search(sims=1000, threads=4)
    stats = eng.root_stats()
    p = eng.save(tmp_path / "run" / "tree.npz")
    re = MCTS.load(p)
    assert re.root_board == eng.root_board and re.history == eng.history and re.moves == eng.moves
    assert re.root_stats() == stats and re.n_nodes == eng.n_nodes
    for name in ("key", "n", "w", "nx", "wx", "estart", "nedges", "state"):
        assert np.array_equal(getattr(re.a, name)[:re.n_nodes], getattr(eng.a, name)[:eng.n_nodes])
    for name in ("e_move", "e_prior", "e_child", "e_n"):
        assert np.array_equal(getattr(re.a, name)[:re.n_edges], getattr(eng.a, name)[:eng.n_edges])
    key = int(eng.a.key[eng.n_nodes // 2])
    assert re.find(key) == eng.find(key) == eng.n_nodes // 2       # the transposition table is rebuilt
    r = re.search(sims=1000, threads=2)                            # resume mid-game
    assert r["root_n"] == int(eng.a.n[eng.root]) + 1000


def test_positional_superko_in_tree():
    b = Board(9).play("E5").play("D5")
    m = point("E4", 9)
    repeat = b.played(m).stone_hash
    eng = MCTS(b, history=[repeat], config=cfg())          # pretend that position occurred before
    r = eng.search(sims=3000, threads=2)
    assert next(c["n"] for c in eng.children(eng.root) if c["move"] == m) == 0
    assert r["superko_skips"] > 0
    with pytest.raises(IllegalMove) as e:
        eng.advance(m)
    assert e.value.code == "superko"


def test_expansion_hook_and_external_results():
    events = []
    eng = MCTS(mk(SAVE), config=cfg(n_thr=50, hook_depth=1, beta=0.5, lam=0.5), on_expand=events.append)
    eng.search(sims=2000, threads=4)
    assert events and events[0].depth == 0 and events[0].key == eng.a.key[eng.root]
    assert any(e.depth == 1 for e in events) and any(e.depth >= 2 and e.n + 1 >= 50 for e in events)
    assert all(e.board.key == e.key for e in events) and len({e.key for e in events}) == len(events)
    assert all(e.path[-1] == e.key and e.path[0] == events[0].key for e in events)
    root = events[0]
    before = {c["move"]: (c["n"], c["prior_learned"]) for c in eng.children(eng.root)}
    target = point("G7", 9)                               # an unremarkable move gets the external prior
    res = eng.set_external(root.key_hex, priors={"G7": 0.7, "C4": 0.3, "Z9": 1.0}, value=0.8, source="mock")
    assert res["applied"] and res["matched"] == 2
    ch = eng.children(eng.root)
    assert eng.a.flags[eng.root] & FL_EXT                  # merged in place; the node admits every move
    assert sum(c["prior"] for c in ch) == pytest.approx(1.0, abs=1e-5)
    g7 = next(c for c in ch if c["move"] == target)
    assert g7["prior"] == pytest.approx(0.5 * before[target][1] + 0.5 * 0.7, abs=1e-6)
    assert {c["move"]: (c["n"], c["prior_learned"]) for c in ch} == before       # statistics kept
    a = eng.a
    assert a.nx[eng.root] == 1 and a.wx[eng.root] == pytest.approx(0.6) and a.vext[eng.root] == pytest.approx(0.6)
    qp = a.w[eng.root] / a.n[eng.root]
    assert eng.node_q(eng.root) == pytest.approx(0.5 * 0.6 + 0.5 * qp)
    deep = next(e for e in events if e.depth >= 2)
    eng.set_external(deep.key, value=0.25)
    for k in deep.path[:-1]:                              # backed up through the recorded ancestors
        assert a.nx[eng.find(k)] >= 1
    # a node the tree does not have yet: pending until it exists
    far, _ = board_from_moves(9, [point(c, 9) for c in "A1 J9 A9".split()])
    assert eng.set_external(far.key, value=0.9)["pending"]
    eng.set_root(far, [])
    eng.search(sims=10, threads=1)
    assert eng.a.nx[eng.root] == 1 and far.key not in eng._ext_pending


def test_external_results_arrive_during_search():
    q: "queue.Queue" = queue.Queue()
    eng = MCTS(Board(9), config=cfg(n_thr=20), on_expand=q.put)   # the hook only queues
    done = []

    def mock_llm():
        while True:
            ev = q.get()
            if ev is None:
                return
            time.sleep(0.001)
            moves = ev.board.legal_moves()[:3]
            done.append(eng.set_external(ev.key, priors={m: 1.0 for m in moves}, value=0.5, position=ev.board))

    th = threading.Thread(target=mock_llm)
    th.start()
    r = eng.search(sims=5000, threads=4)
    q.put(None)
    th.join()
    assert r["sims"] == 5000 and r["events"] > 10 and done
    assert sum(1 for d in done if d.get("applied")) >= 1
    _check_visit_invariants(eng)


def test_learner_receives_samples():
    got = []

    class Learner:
        def observe(self, position, visit_distribution, q, depth):
            got.append((position, visit_distribution, q, depth))

    eng = MCTS(Board(9), config=cfg(observe_min_visits=200), learner=Learner())
    eng.search(sims=4000, threads=4)
    assert got and got[0][3] == 0 and got[0][0] == eng.root_board
    for pos, dist, q, depth in got:
        assert isinstance(pos, Board) and abs(sum(dist.values()) - 1) < 1e-9 and 0 <= q <= 1 and depth >= 0


def test_weights_provider_is_picked_up_between_searches(tmp_path):
    p = default_weights().save(tmp_path / "w.json")
    eng = MCTS(Board(9), config=cfg(), weights=FileWeights(p))
    r = eng.search(sims=200, threads=2)
    assert r["weights"] == "default-v1"
    w = default_weights().w.copy()
    from mcts.features import feature_index
    w[feature_index()["line:1"]] = 6.0                       # the learner prefers the first line now
    new = Weights(w, "learned-v2")
    new.save(p)
    far, _ = board_from_moves(9, [point("E5", 9)])
    eng.set_root(far, [Board(9).stone_hash])                 # a position the tree has not expanded
    r = eng.search(sims=50, threads=1)
    assert r["weights"] == "learned-v2" and r["weights_refreshed"]
    pri = move_priors(far, new)
    for c in eng.children(eng.root):
        assert c["prior_learned"] == pytest.approx(pri[c["move"]], rel=1e-4, abs=1e-6)


def test_stop_conditions():
    eng = MCTS(Board(9), config=cfg())
    t0 = time.monotonic()
    r = eng.search(time_s=30, threads=2, stop=lambda: time.monotonic() - t0 > 0.3)
    assert r["stop_reason"] == "stop" and time.monotonic() - t0 < 5
    threading.Timer(0.3, eng.stop).start()
    r = eng.search(time_s=30, threads=2)
    assert r["stop_reason"] == "stop" and r["time_s"] < 5
    r = eng.search(time_s=0.3, threads=2)
    assert r["stop_reason"] == "time" and r["sims"] > 0
