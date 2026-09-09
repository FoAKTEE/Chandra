"""Skill LOADING for every client — Claude Code loads `.claude/skills/*`
natively; Codex workers and SDK sessions do not. Two paths close that gap:

  * `AGENTS.md` at the repo root — read automatically by Codex-style agents;
    it points at the kernel, the admission contract, and the generated skills
    index. Every path it names must exist (drift is a rejection).
  * `.claude/inject_infra.sh --with-skills` (or CHANDRA_INJECT_SKILLS=1) —
    appends the `<available-skills>` briefing to the session-start block for
    clients that support hooks but not skills. Off by default so Claude Code,
    which already lists skills, is not charged twice.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _common.skills import skill_registry as sr

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "AGENTS.md"
HOOK = REPO_ROOT / ".claude" / "inject_infra.sh"


def run_hook(*args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(["bash", str(HOOK), *args], capture_output=True, text=True,
                          cwd=str(REPO_ROOT), timeout=60,
                          env={**os.environ, **(env or {})})
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_agents_md_exists_and_points_at_real_files() -> None:
    assert AGENTS.is_file()
    text = AGENTS.read_text(encoding="utf-8")
    for must in ("alignment.md", "research_admission_contract.md", ".claude/skills/INDEX.md",
                 "CHANDRA_ROLE", "skill_registry.py"):
        assert must in text, f"AGENTS.md must mention {must}"
    assert sr.check_references(text, REPO_ROOT, REPO_ROOT) == []


def test_hook_default_has_kernel_but_no_skills_block() -> None:
    out = run_hook()
    assert "<session-start-briefing" in out
    assert "The verifier admits" in out
    assert "<available-skills" not in out


def test_hook_with_skills_flag_lists_every_shipped_skill() -> None:
    out = run_hook("--with-skills")
    assert "<available-skills" in out
    for s in sr.list_skills(REPO_ROOT):
        assert f"- {s.name} — " in out
    # env-var form for clients that cannot pass flags
    assert "<available-skills" in run_hook(env={"CHANDRA_INJECT_SKILLS": "1"})
