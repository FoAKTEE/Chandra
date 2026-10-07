"""Model-written heuristics in the play loop (node move47::mcts-llm-hl).

After a decision, ``HeuristicLoop.after_decision(eng, label)``:

  1. finds the search's surprises: well-visited nodes of the root's subtree where the final visit
     distribution (what model priors, model values and millions of playouts concluded together)
     disagrees most with the learned prior, KL(visits || prior), and at nodes the model evaluated
     also with the model's own priors;
  2. builds a ``heuristic`` job (gotree.jobs) for the same sandboxed workers: the surprise positions
     with the moves the search, the learned prior and the model preferred (visits, winrates, the
     main line, the book rules that match), the lessons that apply (L1 / L2 memory), and the current
     heuristics book (rules with weights, held-out effect, hit counts, provenance; recent
     rejections with their reasons; the adjustable feature weights);
  3. queues it on the LLM service (mcts/llm.py), which runs it like any other session without
     blocking the search.

When the answer arrives (validated by the rule language, gotree/heurdsl.py), a background thread
gates it with ``OnlineLearner.consider`` (refit with vs without each rule on held-out hybrid
targets, guards, regression set), records everything in the heuristics book, and links the
lessons a kept rule cites both ways (book -> lesson ids; memory table ``lesson_rules`` -> rule
ids).  The next search picks up the new weights version (rules included) from the learner's
provider; the tree is kept.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from gotree.perception import position_card
from gotree.position import coord

from ..features import TACTICAL, move_priors

FLOOR_LEARNED = 1e-4
FLOOR_MODEL = 1e-3


def _kl(pi: dict, p: dict, floor: float) -> float:
    return float(sum(v * np.log(v / max(p.get(m, 0.0), floor)) for m, v in pi.items() if v > 0))


def _rank(p: dict, m) -> Optional[int]:
    if m not in p:
        return None
    v = p[m]
    return 1 + sum(1 for x in p.values() if x > v)


def find_surprises(eng, weights, svc=None, k: int = 6, min_visits: int = 2048, max_nodes: int = 400,
                   n_ref: float = 20_000.0) -> list[dict]:
    """The k most surprising well-visited nodes of the engine's current root subtree (one per
    canonical position), each with what the search, the learned prior and the model preferred."""
    from ..llm import canonical_of, to_real
    samples = eng.samples(min_visits=min_visits, max_samples=max_nodes)
    T = float(weights.params.get("prior_temperature", 1.0))
    cands = []
    for s in samples:
        b = s["position"]
        pi = {m: v for m, v in s["visit_distribution"].items() if v > 0}
        if not pi or b.terminal:
            continue
        pl = move_priors(b, weights, temperature=T)
        kl_l = _kl(pi, pl, FLOOR_LEARNED)
        pm, kl_m, dkey = {}, None, None
        if svc is not None:
            dkey, _, sym = canonical_of(b)
            raw = svc.llm_priors(dkey)
            if raw:
                pm = {to_real(m, sym, b.size): float(v) for m, v in raw.items()}
                z = sum(pm.values())
                pm = {m: v / z for m, v in pm.items()} if z > 0 else {}
                kl_m = _kl(pi, pm, FLOOR_MODEL) if pm else None
        w = min(1.0, (s["n"] / n_ref) ** 0.5)
        score = w * max(kl_l, kl_m or 0.0)
        cands.append({"sample": s, "pi": pi, "pl": pl, "pm": pm, "kl_learned": kl_l, "kl_model": kl_m,
                      "score": score, "dkey": dkey or b.to_position().key})
    cands.sort(key=lambda c: -c["score"])
    out, seen = [], set()
    for c in cands:
        if c["dkey"] in seen:
            continue
        seen.add(c["dkey"])
        out.append(c)
        if len(out) >= k:
            break
    for i, c in enumerate(out):
        c["id"] = f"S{i + 1}"
        s = c["sample"]
        b = s["position"]
        node = eng.find(s["key"])
        ch = {x["move"]: x for x in eng.children(node)} if node >= 0 else {}
        top = sorted(c["pi"].items(), key=lambda kv: -kv[1])
        c["preferred"] = [coord(m, b.size) for m, v in top[:3] if v >= 0.1 or m == top[0][0]]
        best = top[0][0]
        c["pv"] = [coord(m, b.size) for m in ([best] + (eng.pv(ch[best]["child"], 8) if best in ch and
                                                         ch[best]["child"] >= 0 else []))]
        c["children"] = ch
    return out


def _rules_matching(weights, board, moves) -> dict:
    rs = weights.ruleset if weights.rules else None
    if rs is None:
        return {}
    from ..board import to_point
    out = {}
    for m in moves:
        hit = rs.matches(board, m)
        if hit:
            out[m] = [weights.rules[j]["id"] for j in hit]
    return out


def surprise_text(c: dict, weights) -> str:
    s, b = c["sample"], c["sample"]["position"]
    size = b.size
    me = "Black" if b.to_play == "X" else "White"
    pi, pl, pm, ch = c["pi"], c["pl"], c["pm"], c["children"]
    top = sorted(pi.items(), key=lambda kv: -kv[1])[:6]
    best = top[0][0]
    why = [f"the learned prior gives the search's top move {coord(best, size)} rank {_rank(pl, best)} "
           f"({pl.get(best, 0):.3f})"]
    if pm:
        r = _rank(pm, best)
        why.append(f"the model {'did not propose it' if r is None else f'ranked it {r} ({pm[best]:.2f})'}")
    q = s["q"]
    lines = [f"{c['id']}: {s['depth']} plies below the decision's root, {me} to play, {s['n']} visits, search "
             f"winrate for {me} {q:.2f}" if q is not None else f"{c['id']}: {me} to play",
             f"  surprise: KL(visits || learned prior) {c['kl_learned']:.2f}"
             + (f", KL(visits || model prior) {c['kl_model']:.2f}" if c["kl_model"] is not None else
                ", the model did not evaluate this node") + "; " + "; ".join(why),
             position_card(b.to_position(), title=f"{c['id']} ({me} to play)")]
    rules = _rules_matching(weights, b, [m for m, _ in top] + sorted(pl, key=lambda m: -pl[m])[:3])
    lines.append(f"  {'move':<5} {'visits':>9} {'share':>6} {'winrate':>8} {'learned prior (rank)':>21} "
                 f"{'model prior (rank)':>19}  rules")
    shown = set()
    for m, v in top:
        x = ch.get(m) or {}
        wr = x.get("q")
        shown.add(m)
        lines.append(f"  {coord(m, size):<5} {x.get('n', 0):>9} {v:>6.3f} "
                     f"{'-' if wr is None else f'{wr:.3f}':>8} {pl.get(m, 0):>12.4f} ({_rank(pl, m)})"
                     f"{'' if m not in pm else f'{pm[m]:>12.3f} ({_rank(pm, m)})':>19}  {' '.join(rules.get(m, []))}")
    lp = sorted(pl, key=lambda m: -pl[m])[:3]
    lines.append("  learned prior preferred: " + ", ".join(
        f"{coord(m, size)} {pl[m]:.3f} (search share {pi.get(m, 0):.3f}{'; rules ' + ' '.join(rules[m]) if m in rules else ''})"
        for m in lp))
    if pm:
        mp = sorted(pm, key=lambda m: -pm[m])[:3]
        lines.append("  model preferred: " + ", ".join(f"{coord(m, size)} {pm[m]:.2f} (search share "
                                                         f"{pi.get(m, 0):.3f})" for m in mp))
    lines.append("  main line of the search: " + " ".join(c["pv"]))
    return "\n".join(lines)


def book_text(learner, weights, rejected: int = 12) -> tuple[str, list[str]]:
    """The heuristics book as the job sees it, and the adjustable weights (nudge targets)."""
    book = learner.book
    w_of = {r["id"]: float(x) for r, x in zip(weights.rules, weights.w_rules)}
    lines = []
    act = book.rules()
    if act:
        lines.append(f"Rules in the book ({len(act)}; weight now / as proposed; held-out gain at acceptance; hits in "
                     "the learner's samples):")
        from gotree.heurdsl import describe
        for r in act:
            eff = r.get("heldout_effect") or {}
            h = r.get("hits") or {}
            lines.append(f"  {r['id']} {r['name']}: {r['text']}\n      {describe(r)}\n      weight "
                         f"{w_of.get(r['id'], r['weight_history'][-1]['w']):+.2f} / {r['weight_history'][0]['w']:+.2f}; "
                         f"gain {eff.get('gain', 0):+.4f}; positions {h.get('positions', 0)}, top-move hits "
                         f"{h.get('top', 0)}; from job {(r.get('provenance') or {}).get('job_id')}")
    else:
        lines.append("Rules in the book: none yet.")
    rej = [p for p in book.d["proposals"] if p["status"] == "rejected"][-rejected:]
    if rej:
        from gotree.heurdsl import describe
        lines.append("Recently rejected proposals (do not resubmit them unchanged):")
        for p in rej:
            if p["kind"] == "rule":
                lines.append(f"  {p['id']} rule {p['rule'].get('name')}: {describe(p['rule'])} -> {p['reason'][:200]}"
                             + (" (too little evidence yet: it may be proposed again)" if p.get("retry_ok") else ""))
            else:
                lines.append(f"  {p['id']} nudge {p['nudge'].get('feature')} {p['nudge'].get('delta'):+.2f} -> "
                             f"{p['reason'][:160]}")
    from ..features import feature_index
    idx = feature_index()
    targets = [f for f in TACTICAL if f not in ("pass", "pass:after_pass", "eye_fill")] + [r["id"] for r in act]
    lines.append("Adjustable weights (feature: current weight); rule ids above can be nudged too:")
    lines.append("  " + ", ".join(f"{f} {weights.w[idx[f]]:+.2f}" for f in targets if f in idx))
    lines.append("Feature definitions: capture:k = the move captures k stones; escape:sizeS:libsL = it saves an own "
                 "chain in atari (size S) leaving L liberties; atari:sizeS = it puts an opponent chain of size S in "
                 "atari; self_atari:sizeS = its own chain is left with one liberty; ladder:capture / "
                 "ladder:escape_fails; dist_last:d / dist_last2:d = distance to the opponent's last move / to our "
                 "own previous move (d = dx + dy + max(dx, dy)); line:L = line of the move. Every legal move also "
                 "has one 3x3 shape feature (learned, not adjustable here).")
    return "\n".join(lines), targets


def memory_text(mem, surprises: list[dict], budget: int = 3000) -> str:
    if mem is None:
        return ""
    parts, seen = [], set()
    for c in surprises:
        pos = c["sample"]["position"].to_position()
        pts = [m for m, _ in sorted(c["pi"].items(), key=lambda kv: -kv[1])[:3] if m is not None]
        for p, l, kind in mem.for_points(pos, pts, limit=4):
            if l["id"] in seen:
                continue
            seen.add(l["id"])
            parts.append(f"  [L{l['id']}] ({kind} shape near {c['id']} {coord(p, pos.size)}, seen {l['support']}x) "
                         f"{l['text']}")
    if surprises:
        pos = surprises[0]["sample"]["position"].to_position()
        for l in mem.global_lessons(pos, limit=8):
            if l["id"] not in seen:
                seen.add(l["id"])
                parts.append(f"  [G{l['id']}] {l['text']}")
    txt = "\n".join(parts)
    return txt[:budget] if txt else "(no stored lessons apply yet)"


class HeuristicLoop:
    """Heuristic jobs after decisions and their gating, for one learner and one LLM service."""

    def __init__(self, learner, service, every: int = 1, k: int = 6, min_visits: int = 2048,
                 log: Callable[[str], None] = print, record: Optional[Path] = None):
        self.learner, self.svc = learner, service
        self.every, self.k, self.min_visits = max(1, int(every)), int(k), int(min_visits)
        self.log = log
        self.record = Path(record) if record else None
        self.decisions = 0
        self.ctr = {"requested": 0, "skipped": 0, "results": 0, "processed": 0, "errors": 0, "rules_proposed": 0,
                    "rules_accepted": 0, "nudges_proposed": 0, "nudges_accepted": 0}
        self._q: "queue.Queue" = queue.Queue()
        self._busy = 0
        self._lock = threading.Lock()
        self._stop = False
        service.on_heuristic = self._on_result
        self._thread = threading.Thread(target=self._work, name="heuristic-gate", daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- after a decision
    def after_decision(self, eng, label: str) -> dict:
        self.decisions += 1
        if self.decisions % self.every:
            return {"requested": False, "reason": f"every {self.every} decisions"}
        try:
            w = self.learner.current_weights()
            sur = find_surprises(eng, w, self.svc, self.k, self.min_visits)
        except Exception as e:
            self.log(f"heuristics: surprises failed: {e!r}\n{traceback.format_exc()}")
            return {"requested": False, "reason": repr(e)}
        if not sur:
            self.ctr["skipped"] += 1
            return {"requested": False, "reason": "no node with enough visits"}
        bt, targets = book_text(self.learner, w)
        ctx = [f"Decision {label}: {int(eng.a.n[eng.root])} visits at the root; the {len(sur)} most surprising of the "
               f"well-visited nodes (at least {self.min_visits} visits) of the search below it. Learned prior: weights "
               f"{w.version} ({len(w.rules)} book rules). Model prior: the candidates the model workers proposed at "
               f"that node (only where it evaluated the node). Coordinates as printed on each board."]
        ctx += [surprise_text(c, w) for c in sur]
        mem = memory_text(getattr(self.svc, "mem", None), sur)
        params = {"surprises": [{"id": c["id"], "position": c["sample"]["position"].to_position().to_dict(),
                                 "preferred": c["preferred"]} for c in sur],
                  "targets": targets, "book_text": bt, "title": f"heuristics after {label}",
                  "weights_version": w.version}
        ok = self.svc.request_heuristic(params, "\n\n".join(ctx), mem, label)
        info = {"requested": bool(ok), "label": label, "weights": w.version, "surprises": [
            {"id": c["id"], "depth": c["sample"]["depth"], "n": c["sample"]["n"], "kl_learned": round(c["kl_learned"], 3),
             "kl_model": None if c["kl_model"] is None else round(c["kl_model"], 3), "preferred": c["preferred"]}
            for c in sur]}
        if ok:
            self.ctr["requested"] += 1
        self._write({"t": round(time.time(), 1), "event": "request", **info})
        return info

    # ---------------------------------------------------------------- results
    def _on_result(self, result: dict, job, request, usage: Optional[dict] = None) -> None:
        with self._lock:
            self._busy += 1
            self.ctr["results"] += 1
        self._q.put((result, {"job_id": job.id, "label": request.tag, "dag_key": job.key,
                              "surprises": [{"id": x["id"], "position": x["position"], "preferred": x["preferred"]}
                                            for x in job.params.get("surprises") or []],
                              "worker": getattr(self.svc.worker, "name", ""),
                              "cost_usd": (usage or {}).get("cost_usd")}))

    def _work(self) -> None:
        while not self._stop:
            try:
                result, prov = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                rep = self.learner.consider(result, prov)
                self._link_lessons(rep)
                nr = sum(1 for r in rep.get("rules", []))
                ar = sum(1 for r in rep.get("rules", []) if r["status"] == "accepted")
                nn = len(rep.get("nudges", []))
                an = sum(1 for r in rep.get("nudges", []) if r["status"] == "accepted")
                self.ctr.update(processed=self.ctr["processed"] + 1, rules_proposed=self.ctr["rules_proposed"] + nr,
                                rules_accepted=self.ctr["rules_accepted"] + ar,
                                nudges_proposed=self.ctr["nudges_proposed"] + nn,
                                nudges_accepted=self.ctr["nudges_accepted"] + an)
                self.log(f"heuristics: job {prov.get('job_id')} ({prov.get('label')}): rules {ar}/{nr} accepted, "
                         f"nudges {an}/{nn}" + (f"; new version {rep['version']}" if rep.get("accepted") else "")
                         + "".join(f"\n    {r['status']}: {r['name']}: {r['reason'][:160]}"
                                   for r in rep.get("rules", []) + rep.get("nudges", [])))
                self._write({"t": round(time.time(), 1), "event": "gated", **{k: v for k, v in rep.items()}})
            except Exception as e:
                self.ctr["errors"] += 1
                self.log(f"heuristics: gating job {prov.get('job_id')} failed: {e!r}\n{traceback.format_exc()}")
            finally:
                with self._lock:
                    self._busy -= 1

    def _link_lessons(self, rep: dict) -> int:
        """Accepted rules that cite lessons: lesson -> rule in the lesson memory (the book holds the
        other direction)."""
        mem = getattr(self.svc, "mem", None)
        acc = [r for r in rep.get("rules", []) if r["status"] == "accepted" and r.get("rule_id")]
        if mem is None or not acc:
            return 0
        mem.x("CREATE TABLE IF NOT EXISTS lesson_rules (lesson INTEGER NOT NULL, rule TEXT NOT NULL, book TEXT NOT NULL, "
              "ts REAL NOT NULL, PRIMARY KEY (lesson, rule, book))")
        book = self.learner.book
        n = 0
        for r in acc:
            br = book.rule(r["rule_id"]) or {}
            for lid in br.get("lessons") or []:
                try:
                    num = int(str(lid)[1:])
                except ValueError:
                    continue
                mem.x("INSERT OR IGNORE INTO lesson_rules (lesson, rule, book, ts) VALUES (?,?,?,?)",
                      (num, r["rule_id"], str(book.path), time.time()))
                n += 1
        return n

    def _write(self, rec: dict) -> None:
        if self.record is not None:
            with open(self.record, "a") as f:
                f.write(json.dumps(rec, default=float) + "\n")

    # ---------------------------------------------------------------- control
    def wait_idle(self, timeout: float = 60.0) -> bool:
        t_end = time.time() + timeout
        while time.time() < t_end:
            with self._lock:
                if self._busy == 0 and self._q.empty():
                    return True
            time.sleep(0.05)
        return False

    def stats(self) -> dict:
        return dict(self.ctr)

    def close(self, wait_s: float = 0.0) -> None:
        if wait_s > 0:
            self.wait_idle(wait_s)
        self._stop = True
        self._thread.join(timeout=5)
