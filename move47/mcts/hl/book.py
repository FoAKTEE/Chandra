"""The heuristics book (node move47::mcts-llm-hl): the readable, versioned record of every
model-written rule and weight nudge, accepted or not.

Files in the learner's run dir (one learning state per run dir, shareable across runs):

    heuristics-book.json     the current book (format move47-heuristics-book/1)
    heuristics-book.md       the same, rendered for a person
    book/book-vNNN.json      every earlier version (one per change)

Entries:

    rules      accepted rules, id R<n>: name, text, the rule itself (pattern, conditions), the model's
               rationale, provenance (heuristic job id, decision label, surprise ids and positions,
               lessons cited), weight history (proposed by the model, then every refit), the held-out
               effect at acceptance (CE of the refit with vs without the rule, with a cluster-bootstrap
               interval; and with the model's weight as proposed, no refit), hit counts in the learner's
               samples
    proposals  every proposed rule or nudge, id P<n>: status accepted / rejected, the reason, the
               measurements, the job it came from
    nudges     accepted nudges: feature or rule, delta, the model's rationale, held-out effect
    lessons    lesson id -> rule ids (the other direction lives in the lesson memory, table
               lesson_rules, written by mcts.hl.heuristics)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

FORMAT = "move47-heuristics-book/1"


def _now() -> float:
    return round(time.time(), 1)


class Book:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.path = self.dir / "heuristics-book.json"
        if self.path.exists():
            self.d = json.loads(self.path.read_text())
            if self.d.get("format") != FORMAT:
                raise ValueError(f"{self.path}: not a heuristics book")
        else:
            self.d = {"format": FORMAT, "version": 0, "created": _now(), "updated": _now(), "rules": [],
                      "proposals": [], "nudges": [], "lessons": {}, "jobs": []}

    # ------------------------------------------------------------------ queries
    @property
    def version(self) -> int:
        return int(self.d["version"])

    def rules(self, status: str = "active") -> list[dict]:
        return [r for r in self.d["rules"] if status is None or r.get("status") == status]

    def rule(self, rid: str) -> Optional[dict]:
        return next((r for r in self.d["rules"] if r["id"] == rid), None)

    def by_canonical(self, canonical: str) -> Optional[dict]:
        return next((r for r in self.d["rules"] if r.get("canonical") == canonical), None)

    def rejected_like(self, canonical: str) -> Optional[dict]:
        return next((p for p in reversed(self.d["proposals"]) if p["kind"] == "rule" and p["status"] == "rejected"
                     and not p.get("retry_ok") and (p.get("rule") or {}).get("canonical") == canonical), None)

    def next_id(self, prefix: str) -> str:
        key = {"R": "rules", "P": "proposals"}[prefix]
        return f"{prefix}{len(self.d[key]) + 1}"

    # ------------------------------------------------------------------ changes
    def add_proposal(self, entry: dict) -> str:
        pid = self.next_id("P")
        self.d["proposals"].append({"id": pid, "t": _now(), **entry})
        return pid

    def add_rule(self, rule: dict, w0: float, w: float, prov: dict, effect: dict, hits: dict, version: str,
                 proposal: str) -> str:
        rid = self.next_id("R")
        self.d["rules"].append({
            "id": rid, "status": "active", "name": rule["name"], "text": rule["text"],
            "pattern": rule["pattern"], "conditions": rule.get("conditions") or {}, "canonical": rule["canonical"],
            "rationale": rule.get("rationale", ""), "evidence": rule.get("evidence") or [],
            "lessons": rule.get("lessons") or [], "provenance": prov, "proposal": proposal,
            "weight_history": [{"t": _now(), "version": "proposed", "w": round(float(w0), 4), "by": "model"},
                               {"t": _now(), "version": version, "w": round(float(w), 4), "by": "refit at acceptance"}],
            "heldout_effect": effect, "hits": hits, "accepted_in": version, "created": _now()})
        for lid in rule.get("lessons") or []:
            self.d["lessons"].setdefault(lid, [])
            if rid not in self.d["lessons"][lid]:
                self.d["lessons"][lid].append(rid)
        return rid

    def add_nudge(self, nudge: dict, prov: dict, effect: dict, version: str, proposal: str) -> None:
        self.d["nudges"].append({"t": _now(), "feature": nudge["feature"], "delta": nudge["delta"],
                                 "rationale": nudge.get("rationale", ""), "evidence": nudge.get("evidence") or [],
                                 "provenance": prov, "heldout_effect": effect, "version": version,
                                 "proposal": proposal})

    def note_weights(self, weights, by: str = "refit", min_change: float = 0.01) -> int:
        """Append each active rule's weight in `weights` to its history when it moved."""
        n = 0
        w_of = {r["id"]: float(x) for r, x in zip(weights.rules, weights.w_rules)}
        for r in self.rules():
            if r["id"] not in w_of:
                continue
            last = r["weight_history"][-1]["w"] if r["weight_history"] else None
            if last is None or abs(w_of[r["id"]] - last) >= min_change:
                r["weight_history"].append({"t": _now(), "version": weights.version, "w": round(w_of[r["id"]], 4),
                                            "by": by})
                n += 1
        return n

    def set_hits(self, hits: dict) -> None:
        for r in self.rules():
            if r["id"] in hits:
                r["hits"] = hits[r["id"]]

    def note_job(self, job: dict) -> None:
        self.d["jobs"].append({"t": _now(), **job})

    def save(self) -> int:
        """Write a new version (current file, snapshot, markdown)."""
        self.d["version"] = self.version + 1
        self.d["updated"] = _now()
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "book").mkdir(exist_ok=True)
        txt = json.dumps(self.d, indent=1, default=float) + "\n"
        for p in (self.dir / "book" / f"book-v{self.version:03d}.json", self.path):
            tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
            tmp.write_text(txt)
            os.replace(tmp, p)
        md = self.dir / "heuristics-book.md"
        tmp = md.with_name(f".{md.name}.tmp{os.getpid()}")
        tmp.write_text(self.markdown())
        os.replace(tmp, md)
        return self.version

    # ------------------------------------------------------------------ views
    def markdown(self) -> str:
        from gotree.heurdsl import describe
        d = self.d
        act = self.rules()
        acc = sum(1 for p in d["proposals"] if p["status"] == "accepted")
        rej = sum(1 for p in d["proposals"] if p["status"] == "rejected")
        out = [f"# Heuristics book (version {d['version']})", "",
               f"{len(act)} active rules; {len(d['proposals'])} proposals from {len(d['jobs'])} heuristic jobs: "
               f"{acc} accepted, {rej} rejected. Rules are written by the model (heuristic jobs), checked by the "
               "rule language (gotree/heurdsl.py), and kept only when the learner's prior with the rule predicts "
               "held-out hybrid-search visit distributions better than without it, the tactical guards hold "
               "and the regression set does not get worse.", ""]
        out += ["## Rules", ""]
        if not act:
            out.append("(none yet)")
        for r in act:
            wh = r["weight_history"]
            eff = r.get("heldout_effect") or {}
            prov = r.get("provenance") or {}
            hits = r.get("hits") or {}
            out += [f"### {r['id']} {r['name']}", "",
                    f"{r['text']}", "",
                    "```", "\n".join(_grid(r["pattern"])), "```",
                    f"- rule: `{describe(r)}`",
                    f"- weight: {wh[-1]['w']:+.3f} now; proposed {wh[0]['w']:+.3f} by the model; history: "
                    + ", ".join(f"{h['version']} {h['w']:+.3f}" for h in wh[1:])
                    + ("  \n  **The learned weight has the opposite sign to the model's proposal: the search does "
                       "not support the direction the rule's text states; the rule stays only as a feature.**"
                       if wh[0]["w"] * wh[-1]["w"] < 0 else ""),
                    f"- held-out effect at acceptance: CE {eff.get('ce_before', float('nan')):.4f} without, "
                    f"{eff.get('ce_with', float('nan')):.4f} with the rule at its fitted weight "
                    f"{eff.get('w_fitted', float('nan')):+.3f} (gain {eff.get('gain', 0):+.5f} nats, 90% CI "
                    f"{_ci(eff.get('ci90'))} over {eff.get('ci_over', 'searches')}); at the model's weight "
                    f"{eff.get('w_proposed', float('nan')):+.3f}: gain {eff.get('gain_as_proposed', 0):+.5f}; held-out "
                    f"positions matched {eff.get('heldout_positions', '-')} from {eff.get('heldout_searches', '-')} searches",
                    f"- hits: {json.dumps(hits)}",
                    f"- rationale (model): {r.get('rationale') or '-'}",
                    f"- provenance: heuristic job {prov.get('job_id')} after decision {prov.get('label')}, "
                    f"surprises {', '.join(r.get('evidence') or []) or '-'}, lessons {', '.join(r.get('lessons') or []) or '-'};"
                    f" proposal {r.get('proposal')}, accepted in {r.get('accepted_in')}", ""]
        if d["nudges"]:
            out += ["## Accepted weight nudges", ""]
            for n in d["nudges"]:
                e = n.get("heldout_effect") or {}
                out.append(f"- {n['feature']} {n['delta']:+.2f} (job {(n.get('provenance') or {}).get('job_id')}, "
                           f"{n['version']}): held-out gain {e.get('gain', 0):+.5f}. {n.get('rationale', '')}")
            out.append("")
        if d["lessons"]:
            out += ["## Lessons behind accepted rules", ""]
            for lid, rids in d["lessons"].items():
                out.append(f"- {lid} -> {', '.join(rids)}")
            out.append("")
        out += ["## Proposals", "", "| id | job | kind | name / feature | status | reason |", "|---|---|---|---|---|---|"]
        for p in d["proposals"]:
            nm = (p.get("rule") or {}).get("name") or (p.get("nudge") or {}).get("feature", "")
            reason = str(p.get("reason", "")).replace("|", "/")
            out.append(f"| {p['id']} | {p.get('job_id')} | {p['kind']} | {nm} | {p['status']} | {reason} |")
        out.append("")
        return "\n".join(out)


def _grid(pattern: list[str]) -> list[str]:
    if all(ch == "?" for ch in pattern[0] + pattern[4] + "".join(r[0] + r[4] for r in pattern)):
        pattern = [r[1:4] for r in pattern[1:4]]
    return [" ".join(r) for r in pattern]


def _ci(ci) -> str:
    if not ci:
        return "-"
    return f"{ci[0]:+.5f} .. {ci[1]:+.5f}"
