"""Evidence for learning from model reasoning plus search (node move47::mcts-llm-hl).

    python3 -m mcts hl-hybrid-report --run <run dir> [--hl-dir DIR] [--code-search 200 --code-sims 100000]

Everything is measured on the learner's TEST split: node keys selected by a hash independent of the
held-out split (``test_frac``), never trained on and never used by any gate (the held-out split
chose the distillation weight and gated every version and rule, so it is not an unbiased measure):

  * the heuristics book: proposals made / accepted / rejected, the reasons, accepted rules;
  * every weights version: CE and top-1 against the test nodes' hybrid-search visit distributions,
    and agreement with the model's own priors at the test nodes the model evaluated;
  * ablation refits on the final training data: without the book's rules, without distillation;
  * paired differences with cluster-bootstrap 95% intervals (clusters: the search a node came from);
  * code-only search on test nodes (fixed simulations, no model) with the base, the final weights
    without rules and the final weights: agreement of its most-visited move with the hybrid search's.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from ..weights import Weights
from .fit import fit_policy
from .learner import OnlineLearner
from .regression import check_guards, regression_metrics


def _boot(diff: np.ndarray, w: np.ndarray, clusters: list, reps: int = 2000, seed: int = 1) -> list:
    uniq = {k: i for i, k in enumerate(dict.fromkeys(clusters))}
    cid = np.array([uniq[k] for k in clusters])
    W = np.bincount(cid, weights=w, minlength=len(uniq))
    D = np.bincount(cid, weights=w * diff, minlength=len(uniq))
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(uniq), size=(reps, len(uniq)))
    g = D[pick].sum(1) / np.maximum(W[pick].sum(1), 1e-12)
    return [float(np.quantile(g, 0.025)), float(np.quantile(g, 0.975))]


def _wilson(k: float, n: int, z: float = 1.96) -> list:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [float(max(0.0, c - h)), float(min(1.0, c + h))]


def book_summary(learner: OnlineLearner) -> dict:
    d = learner.book.d
    props = d["proposals"]

    def cat(reason: str) -> str:
        r = reason.lower()
        for key, name in (("not enough samples", "not enough samples yet"), ("over-broad", "over-broad"),
                          ("matches no legal", "matches nothing in training"), ("duplicate", "duplicate"),
                          ("rejected proposal", "repeat of a rejected rule"), ("tactical guard", "guard lost"),
                          ("regression-set", "regression set"), ("held-out positions", "too few held-out matches"),
                          ("gain", "no held-out gain"), ("did not improve", "no held-out gain"),
                          ("not an adjustable", "unknown weight"), ("better rule", "a better rule was kept"),
                          ("book is full", "book full")):
            if key in r:
                return name
        return "other"
    rej = [p for p in props if p["status"] == "rejected"]
    out = {"jobs": len(d["jobs"]), "proposals": len(props),
           "rules_proposed": sum(1 for p in props if p["kind"] == "rule"),
           "rules_accepted": sum(1 for p in props if p["kind"] == "rule" and p["status"] == "accepted"),
           "nudges_proposed": sum(1 for p in props if p["kind"] == "nudge"),
           "nudges_accepted": sum(1 for p in props if p["kind"] == "nudge" and p["status"] == "accepted"),
           "rejection_reasons": dict(Counter(cat(p["reason"]) for p in rej).most_common()),
           "rules": [{"id": r["id"], "name": r["name"], "text": r["text"], "pattern": r["pattern"],
                      "conditions": r["conditions"], "rationale": r["rationale"], "lessons": r.get("lessons"),
                      "job_id": (r.get("provenance") or {}).get("job_id"),
                      "label": (r.get("provenance") or {}).get("label"),
                      "w_proposed": r["weight_history"][0]["w"], "w_now": r["weight_history"][-1]["w"],
                      "sign_flipped": r["weight_history"][0]["w"] * r["weight_history"][-1]["w"] < 0,
                      "effect": r.get("heldout_effect"), "hits": r.get("hits")} for r in learner.book.rules()],
           "nudges": d["nudges"],
           "per_job": [{k: j.get(k) for k in ("job_id", "label", "rules", "nudges", "accepted")} for j in d["jobs"]]}
    return out


def versions_on_test(learner: OnlineLearner, every: int = 1, log: Callable = print) -> list[dict]:
    test = learner.test_split()
    recs = learner.test_records()
    rows = []
    files = learner.versions()
    for i, p in enumerate(files):
        if i % every and i != len(files) - 1:
            continue
        d = json.loads(p.read_text())
        w = Weights.from_json(d)
        m = learner.evaluate(w, test) if test else None
        a = learner.model_agreement(w, recs) if recs else None
        hl = d.get("hl") or {}
        reg = regression_metrics(w, learner._reg_path)
        rows.append({"file": p.name, "version": w.version, "role": hl.get("role", "base" if i == 0 else "update"),
                     "rules": len(w.rules), "test_ce": m and m["ce"], "test_top1": m and m["top1"],
                     "regression_ce": reg and reg["ce"],
                     "agree_ce": a and a["ce"], "agree_top1": a and a["top1"], "agree_mass": a and a["mass_on_model_moves"],
                     "created": hl.get("created")})
    return rows


def ablations(learner: OnlineLearner, log: Callable = print) -> dict:
    """Final weights against refits on the final training data without the book's rules and without
    distillation (same anchors, same time), and the base; all on the test split, paired."""
    cfg = learner.cfg
    final = learner.current_weights()
    T = float(final.params.get("prior_temperature", 1.0))
    tr, _ = learner.split()
    if len(tr) > cfg["max_train"]:
        rng = np.random.default_rng(99)
        tr = [tr[i] for i in np.sort(rng.choice(len(tr), cfg["max_train"], replace=False))]
    test = learner.test_split()
    recs = learner.test_records()
    anchors = learner._anchors() if (cfg["guards"] and cfg["guard_anchor"]) else []
    aw = float(cfg["guard_weight"])
    l2p, l2b = float(cfg["l2"]), float(cfg["l2_base"])
    lam = float(learner.distill_state.get("lam") or 0.0)
    d_tr = learner._distill_rows(learner._distill_records()[0]) if lam > 0 else None

    def refit(rules, lam_, d_):
        start = np.concatenate([final.w, final.w_rules[:len(rules)]]) if rules else final.w.copy()
        center = (l2p * start + l2b * learner._anchor_full(rules)) / (l2p + l2b)
        ps = learner._policy_set(tr, anchors, aw, rules=rules, distill=d_, lam=lam_)
        w, info = fit_policy(ps, center, l2p + l2b, T, cfg["max_iter"], cfg["fit_time"] * 2, start=start)
        return learner._weights_from(w, final, "ablation", rules=rules)
    variants = {"base": learner.base, "final": final}
    t0 = time.time()
    variants["refit_with_rules"] = refit(final.rules, lam, d_tr)
    variants["refit_no_rules"] = refit([], lam, d_tr)
    variants["refit_no_distill"] = refit(final.rules, 0.0, None)
    log(f"ablation refits: {time.time() - t0:.0f}s")
    out: dict = {"lam": lam, "train_n": len(tr), "test_n": len(test), "test_records": len(recs), "variants": {}}
    ce = {}
    if not test:
        return out, variants
    for name, w in variants.items():
        ps = learner._policy_set(test, rules=w.rules)
        ce[name] = (ps.per_sample_ce(w.full, T), ps.sw)
        m = ps.metrics(w.full, T)
        a = learner.model_agreement(w, recs) if recs else None
        reg = regression_metrics(w, learner._reg_path)
        g = check_guards(w, learner._guards)
        out["variants"][name] = {"rules": len(w.rules), "test_ce": m["ce"], "test_top1": m["top1"],
                                 "agree_ce": a and a["ce"], "agree_top1": a and a["top1"],
                                 "agree_mass": a and a["mass_on_model_moves"],
                                 "agree_top3": a and a["model_top_in_top3"],
                                 "regression_ce": reg and reg["ce"], "guards": g["passed"]}
    rows = [s for s in test if learner._rows_of(s)[1] is not None]
    clusters = [(s.game, s.dec) for s in rows]
    out["paired"] = {}
    for a_, b_ in (("final", "base"), ("final", "refit_no_rules"), ("refit_with_rules", "refit_no_rules"),
                   ("refit_with_rules", "refit_no_distill")):
        da, w = ce[a_]
        db, _ = ce[b_]
        diff = db - da                      # > 0: a predicts the hybrid search better
        out["paired"][f"{a_} vs {b_}"] = {"gain": float(w @ diff), "ci95": _boot(diff, w, clusters),
                                          "clusters": len(set(clusters))}
    if recs:
        out["agree_paired"] = {}
        for a_, b_ in (("final", "base"), ("refit_with_rules", "refit_no_distill")):
            ra = _per_record_ce(learner, variants[a_], recs)
            rb = _per_record_ce(learner, variants[b_], recs)
            diff = rb - ra
            out["agree_paired"][f"{a_} vs {b_}"] = {"gain": float(diff.mean()),
                                                    "ci95": _boot(diff, np.ones(len(diff)),
                                                                  [(e.get("game", 0), e.get("dec", i))
                                                                   for i, (_, e) in enumerate(recs)])}
    return out, variants


def _per_record_ce(learner, w, recs) -> np.ndarray:
    from .fit import PolicySet
    from .._lib import N_FEATURES
    rows = learner._distill_rows(recs)
    ps = PolicySet([learner._with_rules(k, r, bd, w.rules) for k, r, bd, _ in rows], [t for *_, t in rows],
                   [1.0] * len(rows), nfeat=N_FEATURES + len(w.rules))
    return ps.per_sample_ce(w.full, float(w.params.get("prior_temperature", 1.0)))


def code_search_agreement(learner: OnlineLearner, variants: dict, n: int = 200, sims: int = 100_000,
                          threads: int = 8, min_visits: int = 20_000, seed: int = 5,
                          log: Callable = print) -> dict:
    """Code-only search (no model, fixed simulations) on test nodes of the hybrid searches: how often
    its most-visited move is the hybrid search's most-visited move, per weights variant."""
    from ..tree import MCTS, MCTSConfig
    from .data import as_board
    test = [s for s in learner.test_split() if s.n >= min_visits and len(s.pi) >= 2]
    rng = np.random.default_rng(seed)
    if len(test) > n:
        test = [test[i] for i in np.sort(rng.choice(len(test), n, replace=False))]
    names = [k for k in ("base", "final", "refit_no_rules", "refit_with_rules") if k in variants]
    hits = {k: [] for k in names}
    t0 = time.time()
    for i, s in enumerate(test):
        b = as_board(s.board)
        target = max(s.pi.items(), key=lambda kv: kv[1])[0]
        for k in names:
            eng = MCTS(b, config=MCTSConfig(max_nodes=1_500_000, threads=threads, seed=seed + i), weights=variants[k])
            r = eng.search(sims=sims, threads=threads)
            best = -1 if r["best_move"] is None else int(r["best_move"])
            hits[k].append(int(best == int(target)))
            eng.close()
        if (i + 1) % 25 == 0:
            log(f"code-only search agreement: {i + 1}/{len(test)} positions, "
                + ", ".join(f"{k} {np.mean(v):.3f}" for k, v in hits.items()) + f" ({time.time() - t0:.0f}s)")
    out = {"positions": len(test), "sims": sims, "threads": threads, "min_visits": min_visits, "variants": {}}
    for k, v in hits.items():
        out["variants"][k] = {"agree": float(np.mean(v)) if v else None, "ci95": _wilson(sum(v), len(v))}
    for a_, b_ in (("final", "base"), ("refit_with_rules", "base"), ("refit_with_rules", "refit_no_rules")):
        if a_ in hits and b_ in hits and hits[a_]:
            d = np.array(hits[a_]) - np.array(hits[b_])
            bs = np.random.default_rng(3).integers(0, len(d), size=(2000, len(d)))
            out[f"{a_} - {b_}"] = {"diff": float(d.mean()), "ci95": [float(np.quantile(d[bs].mean(1), 0.025)),
                                                                     float(np.quantile(d[bs].mean(1), 0.975))],
                                   "a_only": int((d > 0).sum()), "b_only": int((d < 0).sum())}
    return out


def run_summary(run: Path) -> dict:
    moves = [json.loads(x) for x in (run / "moves.jsonl").read_text().splitlines()] if (run / "moves.jsonl").exists() \
        else []
    jobs = [json.loads(x) for x in (run / "llm-jobs.jsonl").read_text().splitlines()] if \
        (run / "llm-jobs.jsonl").exists() else []
    cost = lambda js: round(sum(float((j.get("usage") or {}).get("cost_usd") or 0) for j in js), 2)  # noqa: E731
    by_kind = {}
    for j in jobs:
        k = by_kind.setdefault(j["kind"], {"sessions": 0, "ok": 0, "cost_usd": 0.0, "seconds": []})
        k["sessions"] += 1
        k["ok"] += int(bool(j.get("ok")))
        k["cost_usd"] += float((j.get("usage") or {}).get("cost_usd") or 0)
        k["seconds"].append(j.get("seconds") or 0)
    for k in by_kind.values():
        k["cost_usd"] = round(k["cost_usd"], 2)
        k["median_s"] = float(np.median(k.pop("seconds"))) if k["sessions"] else None
    ups = [json.loads(x) for x in (run / "hl" / "updates.jsonl").read_text().splitlines()] if \
        (run / "hl" / "updates.jsonl").exists() else []
    gate = {"updates": len(ups), "policy_refits_accepted": sum(1 for u in ups if u["reason"].startswith("held-out CE improved")),
            "refused_regression": sum(1 for u in ups if "regression-set" in u["reason"]),
            "refused_no_gain": sum(1 for u in ups if "did not improve" in u["reason"]),
            "refused_guards": sum(1 for u in ups if "tactical guard" in u["reason"]),
            "not_enough_samples": sum(1 for u in ups if "not enough samples" in u["reason"]),
            "lam_chosen": [u["distill"]["lam"] for u in ups if (u.get("distill") or {}).get("selection")]}
    return {"decisions": len(moves), "games": sorted({m["game"] for m in moves}), "update_gate": gate,
            "sims_median": float(np.median([m["sims"] for m in moves])) if moves else None,
            "seconds_median": float(np.median([m["seconds"] for m in moves])) if moves else None,
            "cost_total_usd": cost(jobs), "cost_by_kind": by_kind,
            "cost_per_decision_median": float(np.median([m["llm"]["cost_usd"] for m in moves if m.get("llm")]))
            if moves else None,
            "versions_used": sorted({m["weights"] for m in moves})}


def report(run: Path, hl_dir: Optional[Path] = None, code_n: int = 0, code_sims: int = 100_000, threads: int = 8,
           every: int = 1, log: Callable = print) -> dict:
    run = Path(run)
    learner = OnlineLearner.resume(hl_dir or run / "hl")
    out = {"run": str(run), "hl": str(learner.run_dir), "samples": len(learner.samples),
           "test_split": {"frac": learner.cfg["test_frac"], "nodes": len(learner.test_split()),
                          "records": len(learner.test_records())},
           "summary": run_summary(run), "book": book_summary(learner)}
    log("versions on the test split ...")
    out["versions"] = versions_on_test(learner, every, log)
    log("ablation refits ...")
    out["ablations"], variants = ablations(learner, log)
    if code_n > 0:
        log("code-only search agreement ...")
        out["code_search"] = code_search_agreement(learner, variants, code_n, code_sims, threads, log=log)
    return out


def markdown(r: dict) -> str:
    f = lambda x, d=4: "-" if x is None else f"{x:.{d}f}"   # noqa: E731
    b = r["book"]
    lines = [f"# mcts-llm-hl evidence: {r['run']}", "",
             f"decisions {r['summary']['decisions']}, games {r['summary']['games']}, sessions cost "
             f"{r['summary']['cost_total_usd']} USD; samples {r['samples']}; test split: {r['test_split']}", "",
             "## Proposals", "",
             f"jobs {b['jobs']}; rules proposed {b['rules_proposed']}, accepted {b['rules_accepted']}; nudges proposed "
             f"{b['nudges_proposed']}, accepted {b['nudges_accepted']}", "",
             "rejection reasons: " + json.dumps(b["rejection_reasons"]), "", "## Versions on the test split", "",
             "| version | role | rules | test CE | test top-1 | agreement CE | agreement top-1 | mass on model moves | "
             "regression CE |", "|---|---|---|---|---|---|---|---|---|"]
    for v in r["versions"]:
        lines.append(f"| {v['version']} | {v['role']} | {v['rules']} | {f(v['test_ce'])} | {f(v['test_top1'], 3)} | "
                     f"{f(v['agree_ce'])} | {f(v['agree_top1'], 3)} | {f(v['agree_mass'], 3)} | "
                     f"{f(v.get('regression_ce'))} |")
    a = r["ablations"]
    lines += ["", "update gate: " + json.dumps(r["summary"].get("update_gate")), "",
              "## Ablations (test split)", "", "| variant | rules | test CE | test top-1 | agreement CE | "
              "agreement top-1 | model top move in learned top 3 | regression CE | guards |",
              "|---|---|---|---|---|---|---|---|---|"]
    for k, v in a["variants"].items():
        lines.append(f"| {k} | {v['rules']} | {f(v['test_ce'])} | {f(v['test_top1'], 3)} | {f(v['agree_ce'])} | "
                     f"{f(v['agree_top1'], 3)} | {f(v['agree_top3'], 3)} | {f(v.get('regression_ce'))} | "
                     f"{'pass' if v.get('guards') else 'FAIL'} |")
    lines += ["", "paired CE gains (nats, > 0 = the first predicts the hybrid search better; 95% cluster bootstrap):"]
    for k, v in a["paired"].items():
        lines.append(f"- {k}: {v['gain']:+.5f} [{v['ci95'][0]:+.5f}, {v['ci95'][1]:+.5f}] ({v['clusters']} searches)")
    for k, v in (a.get("agree_paired") or {}).items():
        lines.append(f"- agreement with the model's priors, {k}: {v['gain']:+.4f} [{v['ci95'][0]:+.4f}, {v['ci95'][1]:+.4f}]")
    if r.get("code_search"):
        c = r["code_search"]
        lines += ["", f"## Code-only search on test nodes ({c['positions']} positions, {c['sims']} simulations)", ""]
        for k, v in c["variants"].items():
            lines.append(f"- {k}: agrees with the hybrid search's top move {f(v['agree'], 3)} "
                         f"(95% {f(v['ci95'][0], 3)}-{f(v['ci95'][1], 3)})")
        for k in ("final - base", "refit_with_rules - base", "refit_with_rules - refit_no_rules"):
            if k in c:
                lines.append(f"- {k}: {c[k]['diff']:+.3f} [{c[k]['ci95'][0]:+.3f}, {c[k]['ci95'][1]:+.3f}] "
                             f"({c[k]['a_only']} vs {c[k]['b_only']} positions)")
    lines += ["", "## Accepted rules", ""]
    for x in b["rules"]:
        e = x.get("effect") or {}
        lines.append(f"- {x['id']} {x['name']} (job {x['job_id']}, {x['label']}): {x['text']} pattern {x['pattern']} "
                     f"conditions {x['conditions']}; weight {x['w_proposed']:+.2f} -> {x['w_now']:+.2f}"
                     + (" (SIGN FLIPPED: the search does not support the direction the model proposed)"
                        if x.get("sign_flipped") else "") + "; gain "
                     f"{(e.get('gain') or 0):+.5f}; hits {x['hits']}. Rationale: {x['rationale']}")
    return "\n".join(lines) + "\n"
