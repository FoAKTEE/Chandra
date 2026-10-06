"""gotree — LLM tree search over a persistent position DAG.

  python -m gotree probe  --sgf data/alphago-leesedol-2016-g2.sgf --move 37 --worker claude:opus:high
  python -m gotree search --sgf game.sgf --upto 120 --worker api:anthropic:claude-opus-5-5:high
  python -m gotree play   --arena http://127.0.0.1:8765 --opponent lv5 --games 2 --worker codex:gpt-6.1-sol:high
  python -m gotree judge  --run runs/tree-xyz --katago-bin engines/katago ...
  python -m gotree lessons --run runs/tree-xyz          # print the memory as a tree
  python -m gotree heurtest --run runs/tree-xyz         # HL loop: how well do the code heuristics predict search?

Worker specs: mock | api:<anthropic|openai>:<model>[:effort] | claude:<model>[:effort] | codex:<model>[:effort]
Per-kind overrides: --worker-for rollout=codex:gpt-6.1-sol --worker-for abstract=claude:opus:high
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .dag import DAG
from .memory import Memory
from .search import Search, SearchConfig, config_dict
from .workers import make_worker

REPO = Path(__file__).resolve().parent.parent


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--run", default="", help="run directory (DAG, memory, job dirs); default runs/tree-<time>")
    p.add_argument("--memory", default="", help="lesson memory file to use (default <run>/memory.db); share it "
                                                "between runs to transfer what was learned")
    p.add_argument("--worker", default="mock")
    p.add_argument("--worker-for", action="append", default=[], metavar="KIND=SPEC")
    p.add_argument("--budget", type=int, default=200)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--time-limit", type=float, default=0)
    p.add_argument("--job-timeout", type=float, default=1800)
    p.add_argument("--wrap", default="", help="prefix for CLI workers, e.g. a sandbox; {jobdir} is substituted")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a SearchConfig field")
    p.add_argument("--seed", type=int, default=0)


def _build(a) -> tuple[Search, Path]:
    run = Path(a.run or (REPO / "runs" / f"tree-{time.strftime('%Y%m%d-%H%M%S')}")).resolve()
    run.mkdir(parents=True, exist_ok=True)
    dag_path = str(run / "dag.db")
    mem_path = a.memory or str(run / "memory.db")
    dag, mem = DAG(dag_path), Memory(mem_path)
    cfg = SearchConfig(budget=a.budget, workers=a.workers, time_limit=a.time_limit, seed=a.seed)
    for kv in a.set:
        k, v = kv.split("=", 1)
        if not hasattr(cfg, k):
            sys.exit(f"unknown config field {k}")
        cur = getattr(cfg, k)
        setattr(cfg, k, (v.lower() in ("1", "true", "yes")) if isinstance(cur, bool) else type(cur)(v))

    def mk(spec: str):
        return make_worker(spec, run_dir=run, dag_path=dag_path, mem_path=mem_path, memory=mem, seed=a.seed,
                           timeout=a.job_timeout, wrap=a.wrap)

    workers = {"default": mk(a.worker)}
    for kv in a.worker_for:
        k, spec = kv.split("=", 1)
        workers[k] = mk(spec)
    (run / "config.json").write_text(json.dumps({"argv": sys.argv, "search": config_dict(cfg),
                                                 "workers": {k: w.name for k, w in workers.items()}}, indent=2))

    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(run / "log.txt", "a") as f:
            f.write(line + "\n")

    return Search(dag, mem, workers, cfg, log=log), run


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="gotree", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("probe", help="can the search find a specific famous move?")
    _common(pr)
    pr.add_argument("--sgf", default=str(REPO / "data/alphago-leesedol-2016-g2.sgf"))
    pr.add_argument("--move", type=int, default=37)
    pr.add_argument("--no-recall", action="store_true")
    pr.add_argument("--judge", action="store_true", help="grade with KataGo afterwards (offline)")
    _engine(pr)

    se = sub.add_parser("search", help="search one position from an SGF")
    _common(se)
    se.add_argument("--sgf", required=True)
    se.add_argument("--upto", type=int, default=None, help="position after this many moves (default: all)")

    pl = sub.add_parser("play", help="play arena games with the tree harness")
    _common(pl)
    pl.add_argument("--arena", default=os.environ.get("GOARENA_URL", "http://127.0.0.1:8765"))
    pl.add_argument("--token", default=os.environ.get("GOARENA_TOKEN", ""))
    pl.add_argument("--opponent", default="lv3")
    pl.add_argument("--games", type=int, default=1)
    pl.add_argument("--color", default=None)

    ju = sub.add_parser("judge", help="offline KataGo grading of every decision in a run")
    ju.add_argument("--run", required=True)
    ju.add_argument("--visits", type=int, default=800)
    _engine(ju)

    pc = sub.add_parser("prior", help="cheap pre-check: is the target ever proposed as a candidate?")
    _common(pc)
    pc.add_argument("--sgf", default=str(REPO / "data/alphago-leesedol-2016-g2.sgf"))
    pc.add_argument("--move", type=int, default=37)
    pc.add_argument("--samples", type=int, default=5)

    co = sub.add_parser("consolidate", help="reorganise the lesson memory into a concept tree (one LLM job)")
    _common(co)

    jv = sub.add_parser("judge-values", help="offline: how good are the LLM's static winrates vs KataGo?")
    jv.add_argument("--run", required=True)
    jv.add_argument("--n", type=int, default=100)
    jv.add_argument("--visits", type=int, default=400)
    _engine(jv)

    le = sub.add_parser("lessons", help="print the lesson memory")
    le.add_argument("--run", default="")
    le.add_argument("--memory", default="")

    ht = sub.add_parser("heurtest", help="Heuristic-Learning loop: score the code heuristics against the DAG")
    ht.add_argument("--run", required=True)
    ht.add_argument("--min-visits", type=int, default=6)

    a = p.parse_args(argv)
    if a.cmd == "probe":
        from .probe import render_report, run_probe
        search, run = _build(a)
        rep = run_probe(a.sgf, a.move, search, recall=not a.no_recall, out_dir=run)
        if a.judge:
            from .judge import judge_root
            from .probe import load_target
            kg = _katago(a)
            pos, target, _ = load_target(a.sgf, a.move)
            from .position import point
            rep["judge"] = judge_root(kg, pos, {"target": target, "decision": point(rep["decision"]["real"], pos.size)})
            kg.close()
            jd = _judge_dir(run)
            (jd / "probe-judge.json").write_text(json.dumps(rep["judge"], indent=2))
        print(render_report(rep))
        print(f"\nrun directory: {run}")
    elif a.cmd == "search":
        from .position import Position
        search, run = _build(a)
        pos = Position.from_sgf(Path(a.sgf).read_text(), upto=a.upto)
        out = search.run(pos, label=f"{Path(a.sgf).stem}@{a.upto}")
        print(json.dumps({k: out[k] for k in ("decision", "jobs", "usage")}, indent=2, default=str))
        for c in out["candidates"][:10]:
            print(f"{c['rank']:>2}. {c['real']:<5} n={c['n']:<4} q={c['q']} prior={c['prior']} [{c['source']}] "
                  f"pv: {' '.join(c['pv'][:8])}")
    elif a.cmd == "play":
        from harness.arena_client import ArenaClient
        from .play import play_games
        if not a.token:
            sys.exit("--token / GOARENA_TOKEN required")
        search, run = _build(a)
        res = play_games(ArenaClient(a.arena, token=a.token), search, a.opponent, a.games, a.color,
                         log=search.log, record=run / "moves.jsonl")
        print(json.dumps(res, indent=2))
    elif a.cmd == "judge":
        from .judge import judge_dag
        kg = _katago(a)
        out = judge_dag(str(Path(a.run) / "dag.db"), kg, a.visits)
        kg.close()
        f = _judge_dir(Path(a.run)) / "judge.json"
        f.write_text(json.dumps(out, indent=2))
        for r in out:
            d = r["graded"].get("decision", {})
            print(f"{r['label']}: played {r['decision']} (loss {d.get('loss')} pts, engine rank {d.get('engine_rank')}); "
                  f"engine best {r['engine_best']}")
        print(f"wrote {f}")
    elif a.cmd == "prior":
        from .probe import prior_check
        search, run = _build(a)
        out = prior_check(a.sgf, a.move, search.worker_for("expand"), a.samples)
        (run / "prior-check.json").write_text(json.dumps(out, indent=2))
        print(f"target {out['target_real']}: proposed in {out['proposed_rate']} of samples")
        for x in out["samples"]:
            print("  " + (f"rank={x['rank']} unconventional={x['unconventional']} winrate={x['winrate']:.2f} "
                          f"cands={' '.join(x['candidates'][:10])} | unconv={' '.join(x['unconventional_moves'])}"
                          if x.get("ok") else f"failed: {x['error'][:120]}"))
    elif a.cmd == "consolidate":
        from .jobs import Job
        from .position import Position
        search, run = _build(a)
        job = Job("consolidate", "-", Position.empty(19), {}, context=search.mem.listing())
        res = search.worker_for("consolidate").run(job)
        if not res.ok:
            sys.exit(f"consolidation failed: {res.error}")
        for n in search.mem.apply_consolidation(res.result):
            print(n)
    elif a.cmd == "judge-values":
        from .judge import judge_values
        kg = _katago(a)
        out = judge_values(str(Path(a.run) / "dag.db"), kg, a.n, a.visits)
        kg.close()
        (_judge_dir(Path(a.run)) / "judge-values.json").write_text(json.dumps(out, indent=2))
        print(json.dumps(out, indent=2))
    elif a.cmd == "lessons":
        path = a.memory or str(Path(a.run) / "memory.db")
        print(Memory(path, readonly=True).export_markdown())
    elif a.cmd == "heurtest":
        from .hl import heurtest
        print(json.dumps(heurtest(str(Path(a.run) / "dag.db"), a.min_visits), indent=2))


def _judge_dir(run: Path) -> Path:
    """Judge output lives OUTSIDE the run directory (which workers can read), in judge/<run name>/.
    Hide judge/ and engines/ from worker sandboxes (see TREE.md §9)."""
    d = REPO / "judge" / Path(run).resolve().name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _engine(p: argparse.ArgumentParser) -> None:
    p.add_argument("--katago-bin", default=os.environ.get("KATAGO_BIN", str(REPO / "engines/katago")))
    p.add_argument("--katago-model", default=os.environ.get(
        "KATAGO_MODEL", str(REPO / "engines/models/g170e-b10c128-s1141046784-d204142634.bin.gz")))
    p.add_argument("--katago-config", default=os.environ.get("KATAGO_CONFIG", str(REPO / "engines/configs/analysis.cfg")))


def _katago(a):
    from goarena.katago import KataGo, KataGoConfig
    return KataGo(KataGoConfig(binary=a.katago_bin, model=a.katago_model, config=a.katago_config))


if __name__ == "__main__":
    main()
