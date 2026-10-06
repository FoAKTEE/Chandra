"""Run the Dojo harness for one run.

  GOARENA_URL=... GOARENA_TOKEN=... python -m harness.dojo --workspace runs/x \
      --provider anthropic --model claude-opus-5-5 --effort high
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from ..arena_client import ArenaClient
from .agent import Dojo, DojoConfig
from .llm import make_llm


def main(argv=None):
    p = argparse.ArgumentParser(prog="dojo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workspace", required=True)
    p.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "mock"])
    p.add_argument("--model", required=True)
    p.add_argument("--effort", default="", help="anthropic: adaptive thinking effort; openai: reasoning_effort")
    p.add_argument("--max-tokens", type=int, default=16000)
    p.add_argument("--base-url", default="")
    p.add_argument("--extra", default="", help="JSON merged into every request body")
    p.add_argument("--memory", default="full", choices=["full", "journal", "none"])
    p.add_argument("--no-reflect", action="store_true")
    p.add_argument("--consolidate-every", type=int, default=10)
    p.add_argument("--window", type=int, default=6)
    p.add_argument("--full-boards", type=int, default=1)
    p.add_argument("--playbook-chars", type=int, default=6000)
    p.add_argument("--context", default="episodic", choices=["episodic", "single"])
    p.add_argument("--compact-chars", type=int, default=600_000)
    p.add_argument("--python-tool", action="store_true")
    p.add_argument("--stop-after", type=int, default=None, help="play at most N games in this process")
    p.add_argument("--seed", type=int, default=0, help="mock provider only")
    a = p.parse_args(argv)

    url, token = os.environ.get("GOARENA_URL", "http://127.0.0.1:8765"), os.environ.get("GOARENA_TOKEN", "")
    if not token:
        sys.exit("GOARENA_TOKEN is not set")
    kw = dict(max_tokens=a.max_tokens, effort=a.effort, extra=json.loads(a.extra) if a.extra else None)
    if a.provider == "mock":
        kw["seed"] = a.seed
    else:
        kw["base_url"] = a.base_url
    llm = make_llm(a.provider, a.model, **kw)
    cfg = DojoConfig(memory=a.memory, reflect=not a.no_reflect, consolidate_every=a.consolidate_every,
                     window=a.window, full_boards=a.full_boards, playbook_chars=a.playbook_chars,
                     context_mode=a.context, compact_chars=a.compact_chars, python_tool=a.python_tool,
                     stop_after_games=a.stop_after)
    ws = Path(a.workspace)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "dojo").mkdir(exist_ok=True)
    (ws / "dojo" / "config.json").write_text(json.dumps({**vars(a), "started": time.time()}, indent=2))

    def log(msg: str) -> None:
        print(f"[dojo {time.strftime('%H:%M:%S')}] {msg}", flush=True)

    Dojo(llm, ArenaClient(url, token), ws, cfg, log=log).run()


if __name__ == "__main__":
    main()
