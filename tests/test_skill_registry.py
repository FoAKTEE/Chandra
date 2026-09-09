"""Smoke + rejection checks for the skill registry (_common/skills/skill_registry.py).

Skills are methodology source like any other tool, so they self-host on §0:
a SKILL.md is ADMITTED into `.claude/skills/` only when the validator passes —
frontmatter shape, name/dir agreement, dangling repo references, and (when the
skill declares one) an executed `## Verify` command. Auto-written drafts land
through `promote`, never by hand-copy. Every test writes under `tmp_path`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from _common.skills import skill_registry as sr

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- fixtures ----------------------------------------------------------------

GOOD = """---
name: {name}
description: Explain how to append a gated result row. Use when a worker has evidence and needs the ledger append.
---

# {name}

## When to use

After evidence exists for one node.

## Steps

1. Read `_common/contracts/research_admission_contract.md`.
2. Run `python3 _common/result_database.py append --repo-root .`.

## Verify

```bash
python3 _common/result_database.py --help >/dev/null
```
"""


def repo(tmp_path: Path) -> Path:
    """A fake repo root with the referenced files present."""
    root = tmp_path / "repo"
    (root / "_common" / "contracts").mkdir(parents=True)
    (root / "_common" / "contracts" / "research_admission_contract.md").write_text("# contract\n")
    (root / "_common" / "result_database.py").write_text("import sys\nprint('usage: x')\n")
    (root / ".claude" / "skills").mkdir(parents=True)
    return root


def write_skill(root: Path, name: str, text: str | None = None, where: str = ".claude/skills") -> Path:
    d = root / where / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(text if text is not None else GOOD.format(name=name))
    return d


# --- frontmatter parser -------------------------------------------------------

def test_parse_frontmatter_scalars_lists_and_block_scalars() -> None:
    text = (
        "---\n"
        "name: demo-skill\n"
        "description: >\n"
        "  Folded description line one,\n"
        "  line two.\n"
        "allowed-tools: Bash Read\n"
        "arguments: [paper, node]\n"
        "paths:\n"
        "  - \"*.ts\"\n"
        "  - src/**\n"
        "disable-model-invocation: true\n"
        "---\n"
        "\n# body\n"
    )
    fm, body = sr.parse_frontmatter(text)
    assert fm["name"] == "demo-skill"
    assert fm["description"] == "Folded description line one, line two."
    assert fm["allowed-tools"] == "Bash Read"
    assert fm["arguments"] == ["paper", "node"]
    assert fm["paths"] == ["*.ts", "src/**"]
    assert fm["disable-model-invocation"] is True
    assert body.strip() == "# body"


def test_parse_frontmatter_missing_is_error() -> None:
    with pytest.raises(sr.SkillError, match="frontmatter"):
        sr.parse_frontmatter("# no frontmatter\n")


# --- validation: admit + reject cases -----------------------------------------

def test_valid_skill_admits(tmp_path: Path) -> None:
    root = repo(tmp_path)
    d = write_skill(root, "ledger-append")
    rep = sr.validate_skill(d, repo_root=root)
    assert rep.ok, rep.errors
    assert rep.name == "ledger-append"


def test_name_must_match_directory(tmp_path: Path) -> None:
    root = repo(tmp_path)
    d = write_skill(root, "ledger-append", GOOD.format(name="other-name"))
    rep = sr.validate_skill(d, repo_root=root)
    assert not rep.ok
    assert any("directory" in e for e in rep.errors)


@pytest.mark.parametrize("bad", ["Ledger_Append", "ledger append", "-ledger", "a" * 65])
def test_name_charset_and_length(tmp_path: Path, bad: str) -> None:
    root = repo(tmp_path)
    d = write_skill(root, "ledger-append", GOOD.format(name=bad))
    rep = sr.validate_skill(d, repo_root=root)
    assert not rep.ok
    assert any("name" in e for e in rep.errors)


def test_description_required(tmp_path: Path) -> None:
    root = repo(tmp_path)
    text = GOOD.format(name="ledger-append").replace(
        "description: Explain how to append a gated result row. Use when a worker has evidence and needs the ledger append.\n", "")
    d = write_skill(root, "ledger-append", text)
    rep = sr.validate_skill(d, repo_root=root)
    assert not rep.ok
    assert any("description" in e for e in rep.errors)


def test_unknown_frontmatter_key_warns_not_errors(tmp_path: Path) -> None:
    root = repo(tmp_path)
    text = GOOD.format(name="ledger-append").replace("---\n\n# ", "colour: blue\n---\n\n# ", 1)
    d = write_skill(root, "ledger-append", text)
    rep = sr.validate_skill(d, repo_root=root)
    assert rep.ok
    assert any("colour" in w for w in rep.warnings)
    strict = sr.validate_skill(d, repo_root=root, strict=True)
    assert not strict.ok


def test_dangling_repo_reference_rejects(tmp_path: Path) -> None:
    root = repo(tmp_path)
    text = GOOD.format(name="ledger-append").replace(
        "`_common/contracts/research_admission_contract.md`", "`_common/contracts/does_not_exist.md`")
    d = write_skill(root, "ledger-append", text)
    rep = sr.validate_skill(d, repo_root=root)
    assert not rep.ok
    assert any("does_not_exist.md" in e for e in rep.errors)


def test_dangling_local_reference_rejects(tmp_path: Path) -> None:
    root = repo(tmp_path)
    text = GOOD.format(name="ledger-append") + "\nSee [details](reference.md) and `${CLAUDE_SKILL_DIR}/scripts/run.sh`.\n"
    d = write_skill(root, "ledger-append", text)
    rep = sr.validate_skill(d, repo_root=root)
    assert not rep.ok
    assert any("reference.md" in e for e in rep.errors)
    assert any("scripts/run.sh" in e for e in rep.errors)
    (d / "reference.md").write_text("x\n")
    (d / "scripts").mkdir()
    (d / "scripts" / "run.sh").write_text("true\n")
    assert sr.validate_skill(d, repo_root=root).ok


def test_empty_body_rejects_and_huge_body_warns(tmp_path: Path) -> None:
    root = repo(tmp_path)
    head = GOOD.format(name="ledger-append").split("\n\n# ", 1)[0] + "\n"
    d = write_skill(root, "ledger-append", head)
    assert not sr.validate_skill(d, repo_root=root).ok
    big = GOOD.format(name="ledger-append") + ("filler line\n" * (sr.BODY_LINE_WARN + 5))
    d = write_skill(root, "ledger-append", big)
    rep = sr.validate_skill(d, repo_root=root)
    assert rep.ok and any("lines" in w for w in rep.warnings)


def test_verify_block_is_executed_when_requested(tmp_path: Path) -> None:
    root = repo(tmp_path)
    d = write_skill(root, "ledger-append")
    assert sr.validate_skill(d, repo_root=root, execute=True).ok
    failing = GOOD.format(name="ledger-append").replace(
        "python3 _common/result_database.py --help >/dev/null", "exit 3")
    d = write_skill(root, "ledger-append", failing)
    rep = sr.validate_skill(d, repo_root=root, execute=True)
    assert not rep.ok
    assert any("Verify" in e and "exit 3" in e for e in rep.errors)
    # without --exec the block is only checked for shape
    assert sr.validate_skill(d, repo_root=root).ok


# --- registry: list / index / briefing ---------------------------------------

def test_list_index_and_briefing(tmp_path: Path) -> None:
    root = repo(tmp_path)
    write_skill(root, "ledger-append")
    write_skill(root, "dag-render")
    names = [s.name for s in sr.list_skills(root)]
    assert names == ["dag-render", "ledger-append"]
    md = sr.render_index(root)
    assert "dag-render" in md and "ledger-append" in md and "GENERATED" in md
    out = sr.render_index(root, out=root / ".claude" / "skills" / "INDEX.md")
    assert (root / ".claude" / "skills" / "INDEX.md").read_text() == out
    brief = sr.briefing(root)
    assert brief.startswith("<available-skills")
    assert ".claude/skills/dag-render/SKILL.md" in brief


# --- new + promote -------------------------------------------------------------

def test_new_scaffold_validates(tmp_path: Path) -> None:
    root = repo(tmp_path)
    d = sr.new_skill(root, "fresh-skill", "Scaffolded skill. Use when testing the scaffold.")
    assert (d / "SKILL.md").is_file()
    rep = sr.validate_skill(d, repo_root=root, execute=True)
    assert rep.ok, rep.errors
    with pytest.raises(sr.SkillError, match="exists"):
        sr.new_skill(root, "fresh-skill", "again")


def test_promote_admits_valid_and_rejects_invalid_drafts(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = tmp_path / "drafts"
    good = write_skill(drafts, "good-draft", where=".")
    bad = write_skill(drafts, "bad-draft", GOOD.format(name="mismatch"), where=".")
    report = sr.promote([good, bad], repo_root=root)
    assert [p["name"] for p in report["promoted"]] == ["good-draft"]
    assert [r["name"] for r in report["rejected"]] == ["bad-draft"]
    assert (root / ".claude" / "skills" / "good-draft" / "SKILL.md").is_file()
    assert not (root / ".claude" / "skills" / "bad-draft").exists()
    # the index is a rendered view, refreshed on promotion
    assert "good-draft" in (root / ".claude" / "skills" / "INDEX.md").read_text()
    # promoting again refuses to overwrite unless forced
    again = sr.promote([good], repo_root=root)
    assert again["rejected"] and "exists" in again["rejected"][0]["errors"][0]
    forced = sr.promote([good], repo_root=root, force=True)
    assert forced["promoted"]


def test_harvest_promotes_every_draft_under_a_dir(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = tmp_path / "runtime" / "skills"
    write_skill(drafts, "alpha-skill", where=".")
    write_skill(drafts, "beta-skill", where=".")
    (drafts / "not-a-skill").mkdir()
    report = sr.harvest(drafts, repo_root=root)
    assert sorted(p["name"] for p in report["promoted"]) == ["alpha-skill", "beta-skill"]
    # an emptied draft dir is a clean no-op
    assert sr.harvest(tmp_path / "missing", repo_root=root) == {"promoted": [], "rejected": []}


# --- CLI ------------------------------------------------------------------------

def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "_common" / "skills" / "skill_registry.py"), *args],
        capture_output=True, text=True, timeout=120, cwd=str(cwd) if cwd else None)


def test_cli_validate_exit_codes(tmp_path: Path) -> None:
    root = repo(tmp_path)
    write_skill(root, "ledger-append")
    r = run_cli("validate", "--root", str(root))
    assert r.returncode == 0, r.stderr
    write_skill(root, "broken-one", GOOD.format(name="nope"))
    r = run_cli("validate", "--root", str(root))
    assert r.returncode == 1
    assert "broken-one" in r.stdout
    r = run_cli("list", "--root", str(root), "--json")
    assert [s["name"] for s in json.loads(r.stdout)] == ["broken-one", "ledger-append"]


def test_shipped_skills_validate() -> None:
    """Self-hosting: every skill shipped in this repo passes its own gate,
    including the executed Verify blocks."""
    r = run_cli("validate", "--exec", "--root", str(REPO_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
