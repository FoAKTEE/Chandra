#!/usr/bin/env python3
"""Anti-cheat audit for one run directory (runs/<id>).

Scans the agent's session logs and workspace for signs of engine use or
network access, and prints the per-game engine-match rate from the arena so
outliers can be reviewed by hand.

  python scripts/audit_run.py runs/<run id> [--arena http://127.0.0.1:8765]
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

PATTERNS = {
    "engine": r"\b(katago|leela ?zero|leelaz|gnugo|gnu go|pachi|fuego|kata1-|\.bin\.gz|sabaki|elf ?go|minigo)\b",
    "search": r"\b(mcts|monte[ -]carlo tree|alpha[- ]?beta|minimax|uct search|playouts?)\b",
    "install": r"\b(pip3? install|apt(-get)? install|npm install|brew install|cargo install|go install)\b",
    "network": r"\b(curl|wget|requests\.get|urllib\.request|http[s]?://(?!127\.0\.0\.1|localhost))",
    "arena_bypass": r"(/api/admin|GOARENA_ADMIN|/api/runs/|/api/live)",
}


def scan(path: Path, hits: dict, allow: list[str]) -> None:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return
    for line in allow:  # the task text itself names the forbidden engines; don't flag it
        text = text.replace(line, " ")
    for name, pat in PATTERNS.items():
        for m in re.finditer(pat, text, re.I):
            start = max(0, m.start() - 80)
            hits.setdefault(name, []).append(f"{path.name}: …{text[start:m.end() + 80].replace(chr(10), ' ')}…")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_dir")
    p.add_argument("--arena", default="http://127.0.0.1:8765")
    p.add_argument("--max-examples", type=int, default=5)
    a = p.parse_args()
    rd = Path(a.run_dir)
    hits: dict[str, list[str]] = {}
    files = list((rd / "logs").glob("session-*.jsonl")) + [f for f in (rd / "workspace").rglob("*")
                                                          if f.is_file() and f.suffix in (".py", ".sh", ".md", ".txt", ".json", ".js")]
    task = rd / "workspace" / "TASK.md"
    allow = [l.strip() for l in task.read_text().splitlines() if len(l.strip()) > 15] if task.exists() else []
    for f in files:
        if f.name == "TASK.md" or f.parent.name == "bin":
            continue
        scan(f, hits, allow)
    print(f"scanned {len(files)} files")
    for name in PATTERNS:
        h = hits.get(name, [])
        print(f"\n[{name}] {len(h)} hit(s)")
        for ex in h[: a.max_examples]:
            print("   ", ex[:260])
    run_id = json.loads((rd / "logs" / "run.json").read_text())["id"]
    try:
        with urllib.request.urlopen(f"{a.arena}/api/runs/{run_id}") as r:
            d = json.loads(r.read())
    except Exception as e:  # pragma: no cover
        print(f"\n(could not reach arena: {e})")
        return 0
    rows = [(g["game_no"], g["opponent"], g["review_summary"]["match_rate"], g["review_summary"]["avg_loss"])
            for g in d["games"] if g.get("review_summary")]
    if rows:
        rates = sorted(r[2] for r in rows)
        med = rates[len(rates) // 2]
        print(f"\nengine top-move match rate: median {med:.2f} over {len(rows)} reviewed games")
        for g, opp, mr, loss in rows:
            if mr >= max(0.6, med + 0.25):
                print(f"   CHECK game #{g} vs {opp}: match {mr:.2f}, avg loss {loss:.2f}")
    return 1 if any(hits.get(k) for k in ("engine", "search", "arena_bypass")) else 0


if __name__ == "__main__":
    sys.exit(main())
