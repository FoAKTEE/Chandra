"""LLM-guided tree search over the position DAG.

This is AlphaGo's search with the networks replaced by LLM workers:
  * selection   PUCT over admitted edges, virtual loss for parallel workers;
  * expansion   an `expand` job returns priors (policy) and a winrate (value)
                in one call, like the joint policy/value network;
  * widening    progressive widening: a node admits k0 + c·N^α children and
                asks for `more` candidates when it runs out;
  * breadth     at the root every LLM candidate AND every "unconventional"
                candidate gets a minimum number of visits, plus prior noise —
                the mechanism that gives a low-prior move like AlphaGo's
                move 37 a chance to prove itself;
  * self-play   `rollout` jobs: an LLM plays a d-move line for both sides and
                evaluates its end; the line is inserted and backed up;
  * critic      `refute` jobs attack the moves the search currently likes;
  * reuse       the DAG persists, so the next move's search starts from
                everything already learned (and transpositions are shared).
KataGo is never consulted here.
"""
from __future__ import annotations

import json
import math
import random
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from . import heuristics
from .dag import DAG
from .jobs import Job, describe_known
from .memory import Memory
from .position import Position, coord, sym_maps
from .workers import JobResult, Worker


@dataclass
class SearchConfig:
    budget: int = 200               # LLM jobs per decision
    workers: int = 8                # jobs in flight
    time_limit: float = 0           # seconds per decision, 0 = none
    c_puct: float = 1.5
    fpu: float = 0.15               # first-play urgency reduction
    k_root: int = 10                # candidates asked for at the root
    k_node: int = 6                 # candidates asked for elsewhere
    u_root: int = 4                 # unconventional candidates at the root
    u_node: int = 1
    unconv_prior: float = 0.03
    pw_k0: int = 3                  # progressive widening: admitted = k0 + c * N^alpha
    pw_c: float = 1.0
    pw_alpha: float = 0.5
    max_more: int = 3               # 'more' requests per node
    root_min_visits: int = 2        # forced breadth at the root (LLM candidates)
    root_min_visits_explore: int = 1  # ... and for unconventional / regional-scout candidates
    root_scouts: bool = True        # ask for the best move in each of 9 board regions at the root
    root_noise: float = 0.25        # mix uniform prior noise at the root
    rollout_frac: float = 0.25      # share of leaf jobs that are LLM self-play rollouts
    rollout_depth: int = 8
    refute_frac: float = 0.10       # share of jobs that are critic jobs on the top root moves
    rollout_prior: float = 0.02
    try_prior: float = 0.02
    max_depth: int = 60
    decide: str = "visits"          # visits | llm
    abstract: bool = True           # write lessons after each decision
    early_stop: bool = True
    log_every: int = 25
    seed: int = 0


@dataclass
class Plan:
    kind: str
    key: str
    path: list = field(default_factory=list)   # [(node_key, move)] from root to the job node's parent
    params: dict = field(default_factory=dict)


class Search:
    def __init__(self, dag: DAG, memory: Memory, workers: dict[str, Worker], cfg: SearchConfig,
                 log: Callable[[str], None] = print):
        self.dag, self.mem, self.cfg, self.log = dag, memory, cfg, log
        self.workers = workers
        self.rng = random.Random(cfg.seed)
        self.pending: dict[str, int] = {}
        self.vloss: dict[tuple, int] = {}
        self.usage = {"input": 0, "output": 0, "cache_read": 0, "cost_usd": 0.0, "jobs": 0, "failed": 0}
        self.scouted: set = set()
        self.total_usage: dict = {}
        self.max_inc = 1
        self.more_count: dict[str, int] = {}

    def worker_for(self, kind: str) -> Worker:
        return self.workers.get(kind) or self.workers["default"]

    # ================================================================ public
    def run(self, pos_real: Position, label: str = "", target_real: Optional[int] = None,
            on_progress: Optional[Callable[[dict], None]] = None) -> dict:
        cfg = self.cfg
        self.usage = {"input": 0, "output": 0, "cache_read": 0, "cost_usd": 0.0, "jobs": 0, "failed": 0}
        self.max_inc = 1
        root, root_pos, s_root = self.dag.ensure(pos_real)
        self.root, self.s_root = root, s_root
        root_id = self.dag.x("INSERT INTO roots (key,label,real_sym,created) VALUES (?,?,?,?)",
                             (root, label, s_root, time.time()))
        target_c = None if target_real is None else sym_maps(pos_real.size)[0][s_root][target_real]
        t0, launched, idle = time.time(), 0, 0
        inflight: dict[Future, tuple[Plan, Job]] = {}
        curve = []
        with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
            while True:
                time_up = cfg.time_limit and time.time() - t0 > cfg.time_limit
                while len(inflight) < cfg.workers and launched < cfg.budget and not time_up:
                    plan = self._select()
                    if plan is None:
                        idle += 1
                        break
                    if plan.kind == "terminal":
                        idle += 1
                        if idle > 5000:
                            break
                        continue
                    job = self._make_job(plan)
                    fut = ex.submit(self.worker_for(plan.kind).run, job)
                    inflight[fut] = (plan, job)
                    launched += 1
                if not inflight:
                    break
                done, _ = wait(list(inflight), timeout=5, return_when=FIRST_COMPLETED)
                for f in done:
                    plan, job = inflight.pop(f)
                    try:
                        res = f.result()
                    except Exception as e:  # worker crashed
                        res = JobResult(False, error=f"worker exception: {e}")
                    n0 = self.dag.node(root)["n"]
                    self._integrate(plan, job, res)
                    self.max_inc = max(self.max_inc, self.dag.node(root)["n"] - n0)
                    finished = self.usage["jobs"]
                    if cfg.log_every and finished % cfg.log_every == 0:
                        self.log(self._progress_line(root, finished, target_c))
                    if target_c is not None or on_progress:
                        snap = self._target_snapshot(root, target_c) if target_c is not None else {}
                        snap.update(jobs=finished, seconds=round(time.time() - t0, 1))
                        curve.append(snap)
                        if on_progress:
                            on_progress(snap)
                if cfg.early_stop and not inflight and launched >= cfg.budget:
                    break
                if cfg.early_stop and self._decided_early(root, cfg.budget - launched):
                    self.log(f"early stop: the leading move cannot be overtaken ({launched} jobs launched)")
                    launched = cfg.budget
        decision = self._decide(root, root_pos)
        summary = self.summary(root, pos_real.size, s_root, target_c)
        summary.update(label=label, decision=decision, jobs=self.usage["jobs"], failed=self.usage["failed"],
                       usage=dict(self.usage), seconds=round(time.time() - t0, 1), curve=curve,
                       target_real=None if target_real is None else coord(target_real, pos_real.size))
        if cfg.abstract:
            self._abstract(root, root_pos, summary)
        for k, v in self.usage.items():
            self.total_usage[k] = self.total_usage.get(k, 0) + v
        self.dag.x("UPDATE roots SET finished=?, jobs=?, decision=?, decision_real=?, summary=? WHERE id=?",
                   (time.time(), self.usage["jobs"], -1 if decision["move_c"] is None else decision["move_c"],
                    decision["real"], json.dumps(summary), root_id))
        return summary

    # ================================================================ selection
    def _admitted(self, node: dict, edges: list[dict], is_root: bool) -> list[dict]:
        cfg = self.cfg
        if is_root:  # every LLM / unconventional / critic candidate is admitted at the root
            return [e for e in edges if e["source"] in ("llm", "unconventional", "refute", "more", "pool", "scout")
                    or e["n"] > 0] or edges
        k = int(cfg.pw_k0 + cfg.pw_c * (node["n"] ** cfg.pw_alpha))
        ordered = sorted(edges, key=lambda e: (-e["prior"], -e["n"]))
        visited = [e for e in ordered if e["n"] > 0]
        rest = [e for e in ordered if e["n"] == 0]
        adm = visited + rest
        return adm[:max(k, len(visited))]

    def _wants_more(self, node: dict, edges: list[dict], is_root: bool) -> bool:
        cfg = self.cfg
        if node["exhausted"] or self.more_count.get(node["key"], 0) >= cfg.max_more or self.pending.get(node["key"]):
            return False
        k = int(cfg.pw_k0 + cfg.pw_c * (node["n"] ** cfg.pw_alpha))
        if is_root:
            # at the root, ask for more once the existing candidates are all well explored
            adm = self._admitted(node, edges, True)
            k = len(edges) + 1 if adm and min(e["n"] for e in adm) >= \
                2 * cfg.root_min_visits + self.more_count.get(node["key"], 0) else 0
        return k > len(edges)

    def _select(self) -> Optional[Plan]:
        cfg = self.cfg
        root = self.root
        rnode = self.dag.node(root)
        assert rnode is not None
        if rnode["terminal"] is not None:
            return None
        if rnode["expansions"] == 0:
            if self.pending.get(root):
                return None
            return self._plan("expand", root, [], is_root=True)
        # regional scouts: guarantee that every part of the board is considered at least once
        if cfg.root_scouts:
            for name, pts in regions(self.dag.position(root).size):
                if (root, name) not in self.scouted:
                    self.scouted.add((root, name))
                    return self._plan("more", root, [], is_root=True, region=(name, pts))
        # critic jobs on the leading root moves
        if self.rng.random() < cfg.refute_frac:
            st = sorted([e for e in self.dag.child_stats(root) if e["n"] > 0], key=lambda e: -e["n"])[:2]
            if st:
                e = self.rng.choice(st)
                cnode = self.dag.node(e["child"])
                if cnode and not self.pending.get(e["child"]) and cnode["terminal"] is None:
                    return self._plan("refute", e["child"], [(root, e["move"])])
        key, path, depth = root, [], 0
        visited = {root}
        while True:
            node = self.dag.node(key)
            if node["terminal"] is not None:
                self.dag.backup(path, key, node["terminal"])
                return Plan("terminal", key, path)
            if node["expansions"] == 0:
                if self.pending.get(key):
                    return None
                kind = "rollout" if (path and self.rng.random() < cfg.rollout_frac) else "expand"
                return self._plan(kind, key, path)
            edges = self.dag.child_stats(key)
            is_root = key == root
            if self._wants_more(node, edges, is_root) and depth < 6:
                return self._plan("more", key, path, is_root=is_root, edges=edges)
            adm = [e for e in self._admitted(node, edges, is_root) if e["child"] not in visited]
            if not adm:
                if not self.pending.get(key) and not node["exhausted"] and self.more_count.get(key, 0) < cfg.max_more:
                    return self._plan("more", key, path, is_root=is_root, edges=edges)
                return None
            e = self._puct(node, adm, is_root)
            if e is None:
                return None
            path = path + [(key, e["move"])]
            key = e["child"]
            visited.add(key)
            depth += 1
            if depth >= cfg.max_depth:
                cn = self.dag.node(key)
                if cn["terminal"] is None and cn["expansions"] == 0:
                    return self._plan("expand", key, path) if not self.pending.get(key) else None
                v = cn["terminal"] if cn["terminal"] is not None else (
                    cn["w"] / cn["n"] if cn["n"] else (cn["static_value"] if cn["static_value"] is not None else 0.5))
                self.dag.backup(path, key, v)
                return Plan("terminal", key, path)

    def _puct(self, node: dict, adm: list[dict], is_root: bool) -> Optional[dict]:
        cfg = self.cfg
        if is_root and cfg.root_min_visits:
            def need(e):
                return cfg.root_min_visits_explore if e["source"] in ("unconventional", "scout") else cfg.root_min_visits
            under = [e for e in adm if e["n"] + self.vloss.get((node["key"], e["move"]), 0) < need(e)
                     and not self.pending.get(e["child"])]
            if under:
                return min(under, key=lambda e: (e["n"], -e["prior"]))
        parent_q = node["w"] / node["n"] if node["n"] else 0.5
        ntot = sum(e["n"] + self.vloss.get((node["key"], e["move"]), 0) for e in adm)
        tot_prior = sum(e["prior"] for e in adm) or 1.0
        best, best_s = None, -1e9
        for e in adm:
            vl = self.vloss.get((node["key"], e["move"]), 0)
            if self.pending.get(e["child"]) and e["n"] == 0:
                continue
            prior = e["prior"] / tot_prior
            if is_root and cfg.root_noise:
                prior = (1 - cfg.root_noise) * prior + cfg.root_noise / len(adm)
            q = e["q"] if e["q"] is not None else parent_q - cfg.fpu
            if vl:
                q = (q * e["n"]) / (e["n"] + vl) if e["n"] else q - 0.2
            u = cfg.c_puct * prior * math.sqrt(ntot + 1) / (1 + e["n"] + vl)
            s = q + u
            if s > best_s:
                best, best_s = e, s
        return best

    def _plan(self, kind: str, key: str, path: list, is_root: bool = False, edges: Optional[list] = None,
              region: Optional[tuple] = None) -> Plan:
        cfg = self.cfg
        params: dict = {}
        if kind in ("expand", "refute"):
            params = {"k": cfg.k_root if is_root else cfg.k_node, "u": cfg.u_root if is_root else cfg.u_node}
        elif kind == "more":
            edges = edges if edges is not None else self.dag.child_stats(key)
            pos = self.dag.position(key)
            params = {"k": cfg.k_root if is_root else cfg.k_node, "u": cfg.u_root if is_root else cfg.u_node,
                      "exclude": ", ".join(coord(e["move"], pos.size) for e in edges),
                      "exclude_points": [e["move"] for e in edges]}
            if region is not None:
                params.update(k=3, u=1, region=region[0], region_points=list(region[1]))
            else:
                self.more_count[key] = self.more_count.get(key, 0) + 1
        elif kind == "rollout":
            params = {"d": cfg.rollout_depth}
        self.pending[key] = self.pending.get(key, 0) + 1
        for k, m in path:  # virtual loss along the path while the job is in flight
            self.vloss[(k, m)] = self.vloss.get((k, m), 0) + 1
        return Plan(kind, key, path, params)

    def _decided_early(self, root: str, remaining: int) -> bool:
        st = sorted(self.dag.child_stats(root), key=lambda e: -e["n"])
        if len(st) < 2 or remaining <= 0:
            return False
        # a job can add several root visits (backed-up `gtree try` lines), so bound by the largest jump seen
        return st[0]["n"] - st[1]["n"] > remaining * max(1, self.max_inc) + sum(self.vloss.values())

    # ================================================================ jobs
    def _make_job(self, plan: Plan) -> Job:
        pos = self.dag.position(plan.key)
        pts = [p for p, _ in heuristics.score_moves(pos)[:6]]
        memory = self.mem.briefing(pos, [p for p in pts if p is not None])
        known = describe_known(self.dag, plan.key, pos) if plan.kind in ("more", "refute") else ""
        params = dict(plan.params, title=f"Position {plan.key[:8]}")
        job = Job(plan.kind, plan.key, pos, params, memory=memory, known=known)
        job.id = self.dag.x("INSERT INTO jobs (kind,key,root,status,worker,created,started) VALUES (?,?,?,?,?,?,?)",
                            (plan.kind, plan.key, self.root, "running", self.worker_for(plan.kind).name,
                             time.time(), time.time()))
        return job

    def _release(self, plan: Plan) -> None:
        self.pending[plan.key] = max(0, self.pending.get(plan.key, 1) - 1)
        for k, m in plan.path:
            c = self.vloss.get((k, m), 0) - 1
            if c > 0:
                self.vloss[(k, m)] = c
            else:
                self.vloss.pop((k, m), None)

    def _integrate(self, plan: Plan, job: Job, res: JobResult) -> None:
        self._release(plan)
        self.usage["jobs"] += 1
        for k in ("input", "output", "cache_read"):
            self.usage[k] += int(res.usage.get(k, 0) or 0)
        self.usage["cost_usd"] += float(res.usage.get("cost_usd", 0) or 0)
        self.dag.x("UPDATE jobs SET status=?, finished=?, result=?, error=?, usage=? WHERE id=?",
                   ("done" if res.ok else "failed", time.time(), json.dumps(res.result) if res.result else None,
                    res.error[:2000], json.dumps(res.usage), job.id))
        if not res.ok:
            self.usage["failed"] += 1
            self.log(f"job {job.id} ({plan.kind}) failed: {res.error[:200]}")
            return
        r = res.result or {}
        key = plan.key
        if plan.kind in ("expand", "more", "refute"):
            existing = self.dag.child_stats(key)
            mass = 1.0
            if plan.kind == "more" and existing:
                mass = max(0.1, 1.0 - sum(e["prior"] for e in existing))
            tot = sum(c["prior"] for c in r["candidates"]) or 1.0
            src = {"expand": "llm", "more": "more", "refute": "refute"}[plan.kind]
            if plan.params.get("region"):
                src = "scout"
            for c in r["candidates"]:
                pr = c["prior"] if plan.kind == "expand" else mass * c["prior"] / tot
                if plan.kind == "refute":
                    pr = max(pr, 0.15)
                self.dag.add_edge(key, c["move"], pr, src, c["why"])
            for u in r["unconventional"]:
                self.dag.add_edge(key, u["move"], self.cfg.unconv_prior, "unconventional", u["why"])
            if plan.kind == "more" and not plan.params.get("region") and not r["candidates"] and not r["unconventional"]:
                self.dag.mark_exhausted(key)
            v = r["value"]
            score_b = None
            pos = self.dag.position(key)
            if v.get("score_lead") is not None:
                score_b = v["score_lead"] if pos.to_play == "X" else -v["score_lead"]
            self.dag.set_static(key, v["winrate"], score_b, v["confidence"], v["why"], r.get("plan", ""),
                                worker=res.worker, job_id=job.id)
            self.dag.backup(plan.path, key, v["winrate"], score_b)
        elif plan.kind == "rollout":
            self._insert_line(plan, key, r["moves"], r["value_at_end"]["winrate"], res, job, "rollout")
        for t in res.tries:  # the worker's own reading becomes shared tree knowledge
            moves = [m for m in t.get("moves", []) if m is None or isinstance(m, int)]
            if moves:
                self._insert_line(plan, key, moves, t.get("winrate"), res, job, "try")

    def _insert_line(self, plan: Plan, start: str, moves: list, winrate_start: Optional[float], res: JobResult,
                     job: Job, source: str) -> None:
        pos = self.dag.position(start)
        n = pos.size * pos.size
        fwd_all = sym_maps(pos.size)[0]
        F = list(range(n))
        cur, ext = start, []
        prior = self.cfg.rollout_prior if source == "rollout" else self.cfg.try_prior
        for m in moves:
            mm = None if m is None else F[m]
            try:
                e = self.dag.add_edge(cur, mm, prior, source)
            except Exception:
                break
            ext.append((cur, mm))
            f = fwd_all[e.child_sym]
            F = [f[F[p]] for p in range(n)]
            cur = e.child
        if winrate_start is None:
            return
        end_pos = self.dag.position(cur)
        v_end = winrate_start if end_pos.to_play == pos.to_play else 1.0 - winrate_start
        self.dag.add_eval(cur, "rollout_end" if source == "rollout" else "try_end", v_end, worker=res.worker,
                          job_id=job.id)
        self.dag.backup(plan.path + ext, cur, v_end)

    # ================================================================ decision
    def _decide(self, root: str, root_pos: Position) -> dict:
        st = self.dag.child_stats(root)
        fwd, inv = sym_maps(root_pos.size)
        if not st:
            return {"move_c": None, "real": "pass", "rule": "no candidates"}
        best = max(st, key=lambda e: (e["n"], e["q"] if e["q"] is not None else -1, e["prior"]))
        out = {"move_c": best["move"], "rule": "most visited", "n": best["n"], "q": best["q"]}
        if self.cfg.decide == "llm":
            ctx = self._summary_text(root, root_pos)
            job = Job("decide", root, root_pos, {"most_visited": coord(best["move"], root_pos.size),
                                                  "title": "Root position"}, context=ctx)
            job.id = self.dag.x("INSERT INTO jobs (kind,key,root,status,created,started) VALUES (?,?,?,?,?,?)",
                                ("decide", root, root, "running", time.time(), time.time()))
            res = self.worker_for("decide").run(job)
            self.dag.x("UPDATE jobs SET status=?, finished=?, result=?, error=? WHERE id=?",
                       ("done" if res.ok else "failed", time.time(), json.dumps(res.result), res.error, job.id))
            if res.ok and res.result and res.result["move"] != best["move"]:
                out = {"move_c": res.result["move"], "rule": "llm override", "why": res.result["why"]}
            elif res.ok and res.result:
                out["why"] = res.result["why"]
        mv = out["move_c"]
        out["real"] = coord(None if mv is None else inv[self.s_root][mv], root_pos.size)
        out["canonical"] = coord(mv, root_pos.size)
        return out

    # ================================================================ memory
    def _abstract(self, root: str, root_pos: Position, summary: dict) -> None:
        if summary["decision"]["move_c"] is None and not summary["candidates"]:
            return
        ctx = self._summary_text(root, root_pos, surprises=True)
        job = Job("abstract", root, root_pos, {"chosen": summary["decision"].get("canonical", "pass"),
                                               "title": "Root position"},
                  memory=self.mem.briefing(root_pos, [m for m in [summary["decision"]["move_c"]] if m is not None]),
                  context=ctx)
        job.id = self.dag.x("INSERT INTO jobs (kind,key,root,status,created,started) VALUES (?,?,?,?,?,?)",
                            ("abstract", root, root, "running", time.time(), time.time()))
        res = self.worker_for("abstract").run(job)
        self.dag.x("UPDATE jobs SET status=?, finished=?, result=?, error=? WHERE id=?",
                   ("done" if res.ok else "failed", time.time(), json.dumps(res.result), res.error, job.id))
        if not res.ok or not res.result:
            return
        for l in res.result["lessons"]:
            ev = {"key": root, "move": summary["decision"].get("canonical")}
            if l["scope"] == "local" and l["at"] is not None:
                lid = self.mem.add_local(root_pos, l["at"], l["text"], ev)
            else:
                lid = self.mem.add_global(l["text"], root_pos.phase(), root_pos.size, ev)
            for rel in l["relates_to"]:
                try:
                    other = int(str(rel["id"]).lstrip("GgLl"))
                except ValueError:
                    continue
                self.mem.relate(lid, other, str(rel.get("rel", "")))   # ignores unknown / missing ids

    # ================================================================ reporting
    def _frame_to_real_maps(self, size: int):
        _, inv = sym_maps(size)
        return list(inv[self.s_root])  # root canonical frame -> real

    def _pv_frame(self, child_key: str, child_sym: int, size: int, max_len: int = 8) -> list[str]:
        """Principal variation below a root child, in the ROOT's canonical frame."""
        return self._pv_real(child_key, child_sym, list(range(size * size)), size, max_len)

    def _pv_real(self, child_key: str, child_sym: int, to_real_parent: list, size: int, max_len: int = 8) -> list[str]:
        _, inv = sym_maps(size)
        to_real = [to_real_parent[inv[child_sym][p]] for p in range(size * size)]
        out = []
        for key, mv, s in self.dag.principal_variation(child_key, max_len):
            out.append(coord(None if mv is None else to_real[mv], size))
            to_real = [to_real[inv[s][p]] for p in range(size * size)]
        return out

    def summary(self, root: str, size: int, s_root: int, target_c: Optional[int] = None, top: int = 12) -> dict:
        to_real = self._frame_to_real_maps(size)
        node = self.dag.node(root)
        st = sorted(self.dag.child_stats(root), key=lambda e: (-e["n"], -(e["q"] or 0), -e["prior"]))
        cands = []
        for i, e in enumerate(st[:top]):
            real = coord(None if e["move"] is None else to_real[e["move"]], size)
            cands.append({"rank": i + 1, "move_c": e["move"], "real": real, "n": e["n"],
                          "q": None if e["q"] is None else round(e["q"], 3), "prior": round(e["prior"], 3),
                          "source": e["source"], "why": e["why"][:200],
                          "pv": [real] + self._pv_real(e["child"], e["child_sym"], to_real, size)})
        out = {"root": root, "root_n": node["n"], "root_value": (node["w"] / node["n"]) if node["n"] else None,
               "candidates": cands, "num_root_moves": len(st), "dag": self.dag.stats()}
        if target_c is not None:
            out["target"] = self._target_snapshot(root, target_c)
        return out

    def _target_snapshot(self, root: str, target_c: int) -> dict:
        st = sorted(self.dag.child_stats(root), key=lambda e: (-e["n"], -(e["q"] or 0), -e["prior"]))
        for i, e in enumerate(st):
            if e["move"] == target_c:
                return {"in_tree": True, "rank": i + 1, "n": e["n"], "q": e["q"], "prior": e["prior"],
                        "source": e["source"], "of": len(st)}
        return {"in_tree": False, "rank": None, "of": len(st)}

    def _progress_line(self, root: str, jobs: int, target_c: Optional[int]) -> str:
        pos = self.dag.position(root)
        to_real = self._frame_to_real_maps(pos.size)
        st = sorted(self.dag.child_stats(root), key=lambda e: -e["n"])[:5]
        parts = []
        for e in st:
            q = "-" if e["q"] is None else f"{e['q']:.2f}"
            parts.append(f"{coord(None if e['move'] is None else to_real[e['move']], pos.size)} n={e['n']} q={q}")
        txt = "  ".join(parts)
        t = ""
        if target_c is not None:
            s = self._target_snapshot(root, target_c)
            t = f" | target: {'rank ' + str(s['rank']) + ' n=' + str(s['n']) if s['in_tree'] else 'not in tree'}"
        return f"[{jobs} jobs] {txt}{t}"

    def _summary_text(self, root: str, pos: Position, surprises: bool = False) -> str:
        st = sorted(self.dag.child_stats(root), key=lambda e: (-e["n"], -(e["q"] or 0)))
        node = self.dag.node(root)
        lines = [f"Search: {node['n']} visits at this position; backed-up winrate for the side to move "
                 f"{(node['w'] / node['n']) if node['n'] else 0.5:.2f}."]
        lines.append("Candidates (n = visits, q = backed-up winrate for the mover, prior = initial belief):")
        prior_rank = {e["move"]: i + 1 for i, e in enumerate(sorted(st, key=lambda e: -e["prior"]))}
        for i, e in enumerate(st[:12]):
            pv = self._pv_frame(e["child"], e["child_sym"], pos.size, 6)
            q = "—" if e["q"] is None else f"{e['q']:.2f}"
            lines.append(f"  {i + 1:>2}. {coord(e['move'], pos.size):<5} n={e['n']:<4} q={q:<5} prior={e['prior']:.2f} "
                         f"(prior rank {prior_rank.get(e['move'])}) [{e['source']}] {e['why'][:120]}"
                         + (f"\n      line: {coord(e['move'], pos.size)} {' '.join(pv)}" if pv else ""))
        if surprises:
            sur = [e for e in st if e["n"] >= 2 and e["q"] is not None and prior_rank.get(e["move"], 99) >= 4
                   and st and e["n"] >= 0.5 * st[0]["n"]]
            bad = [e for e in st if prior_rank.get(e["move"], 99) <= 2 and e["q"] is not None and st[0]["q"] is not None
                   and e["q"] < st[0]["q"] - 0.1]
            if sur or bad:
                lines.append("SURPRISES:")
                for e in sur:
                    lines.append(f"  {coord(e['move'], pos.size)} had a low prior (rank {prior_rank.get(e['move'])}) "
                                 f"but the search rates it highly (q={e['q']:.2f}, n={e['n']}).")
                for e in bad:
                    lines.append(f"  {coord(e['move'], pos.size)} looked best at first (prior rank "
                                 f"{prior_rank.get(e['move'])}) but scored worse after search (q={e['q']:.2f}).")
        return "\n".join(lines)


def regions(size: int) -> list[tuple[str, list[int]]]:
    """Nine regions (corners, sides, centre) in the presented frame."""
    if size < 13:
        return []
    cuts = [0, size // 3, size - size // 3, size]
    names = [["upper-left corner", "top side", "upper-right corner"],
             ["left side", "centre", "right side"],
             ["lower-left corner", "bottom side", "lower-right corner"]]
    out = []
    for i in range(3):
        for j in range(3):
            pts = [y * size + x for y in range(cuts[i], cuts[i + 1]) for x in range(cuts[j], cuts[j + 1])]
            c0, c1 = coord(pts[0], size), coord(pts[-1], size)
            out.append((f"the {names[i][j]} (from {c0} to {c1})", pts))
    return out


def config_from_dict(d: dict) -> SearchConfig:
    cfg = SearchConfig()
    for k, v in d.items():
        if hasattr(cfg, k):
            setattr(cfg, k, type(getattr(cfg, k))(v))
    return cfg


def config_dict(cfg: SearchConfig) -> dict:
    return asdict(cfg)
