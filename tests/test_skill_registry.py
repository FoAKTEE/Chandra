"""Smoke + rejection checks for the skill registry (_common/skills/skill_registry.py).

Skills are methodology source like any other tool, so they self-host on §0:
a SKILL.md is ADMITTED into `.claude/skills/` only when the validator passes —
frontmatter shape, name/dir agreement, dangling repo references, and an
executed `## Verify` command. Auto-written drafts land
through `promote`, never by hand-copy. Every test writes under `tmp_path`.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
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
    drafts = [write_skill(tmp_path, name, where="drafts")
              for name in ("ledger-append", "dag-render")]
    assert not sr.promote(drafts, repo_root=root)["rejected"]
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

def test_new_scaffold_validates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHANDRA_RUNTIME", str(tmp_path / "runtime"))
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


# --- candidate binding and admission receipts ---------------------------------

@pytest.mark.parametrize(("extra", "count"), [
    ("\n```bash\nexit 1\n```\n", 2),
    ("\n```bash\nexit 1\n```\n\n```bash\nexit 2\n```\n", 3),
    ("\n```python\nraise SystemExit(1)\n```\n", 2),
    ("\n## Verify\n\n```bash\nexit 1\n```\n", 2),
    ("\n```bash\n## A shell comment, not a new section\nexit 7\n```\n", 2),
    ("\n~~~bash\nexit 7\n~~~~\n", 2),
])
def test_multiple_verify_blocks_reject(tmp_path: Path, extra: str, count: int) -> None:
    root = repo(tmp_path)
    d = write_skill(tmp_path, "two-blocks", GOOD.format(name="two-blocks") + extra, where="drafts")
    rep = sr.validate_skill(d, repo_root=root, execute=True)
    assert not rep.ok, "only the first Verify block was checked"
    assert f"Verify section must contain exactly one fenced block (found {count})" in rep.errors
    assert not sr.promote([d], repo_root=root)["promoted"]


@pytest.mark.parametrize("command", ["validate", "promote"])
def test_missing_verify_rejects_validate_and_promote(tmp_path: Path, command: str) -> None:
    root = repo(tmp_path)
    text = GOOD.format(name="no-verify").split("\n## Verify", 1)[0]
    d = write_skill(root if command == "validate" else tmp_path, "no-verify", text,
                    where=".claude/skills" if command == "validate" else "drafts")
    args = ["validate", "--exec", "no-verify"] if command == "validate" else ["promote", str(d)]
    r = run_cli(*args, "--root", str(root))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Verify section is required" in r.stdout
    assert not (root / ".claude/skills/admitted.json").exists()
    if command == "promote":
        assert not (root / ".claude/skills/no-verify").exists()


@pytest.mark.parametrize("execute", [False, True])
@pytest.mark.parametrize("command", [
    "cat .claude/skills/ledger-append/SKILL.md >/dev/null",
    "python3 -c \"from pathlib import Path; (Path('.claude/skills/ledger-append') / 'SKILL.md').read_text()\"",
])
def test_installed_self_read_rejects(tmp_path: Path, execute: bool, command: str) -> None:
    root = repo(tmp_path)
    write_skill(root, "ledger-append")
    text = GOOD.format(name="ledger-append").replace(
        "python3 _common/result_database.py --help >/dev/null",
        command)
    d = write_skill(tmp_path, "ledger-append", text, where="drafts")
    rep = sr.validate_skill(d, repo_root=root, execute=execute)
    assert not rep.ok
    assert "Verify block reads the installed skill instead of ${CLAUDE_SKILL_DIR}" in rep.errors


def test_result_example_is_checked_in_candidate(tmp_path: Path) -> None:
    installed = REPO_ROOT / ".claude/skills/ledger-result-admit"
    d = tmp_path / "drafts/ledger-result-admit"
    shutil.copytree(installed, d)
    f = d / "SKILL.md"
    original = f.read_text()
    assert '"status": "checked"' in original
    f.write_text(original.replace('"status": "checked"', '"status": "impossible_status"', 1))
    rep = sr.validate_skill(d, repo_root=REPO_ROOT, execute=True)
    assert not rep.ok, "the installed example was validated instead of the candidate"
    assert any("Verify block failed" in e and "impossible_status" in e for e in rep.errors), rep.errors
    r = run_cli("validate", str(d), "--exec", "--root", str(REPO_ROOT))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Verify block failed" in r.stdout and "impossible_status" in r.stdout
    assert (installed / "SKILL.md").read_text() == original


def test_verify_receives_candidate_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    monkeypatch.setenv("CLAUDE_SKILL_CANDIDATE", "0")
    monkeypatch.setenv("CLAUDE_SKILL_DIR", "/missing")
    text = GOOD.format(name="candidate-env").replace(
        "python3 _common/result_database.py --help >/dev/null",
        'test "$CLAUDE_SKILL_CANDIDATE" = 1\n'
        'test -f "$CLAUDE_SKILL_DIR/SKILL.md"\n'
        'test "$PWD" = "$CLAUDE_PROJECT_DIR"')
    d = write_skill(tmp_path, "candidate-env", text, where="drafts with spaces")
    rep = sr.validate_skill(d, repo_root=root, execute=True)
    assert rep.ok, rep.errors


@pytest.mark.parametrize("surface", ["list_skills", "briefing", "render-index", "list", "json"])
def test_unpromoted_scaffold_is_not_discoverable(tmp_path: Path, surface: str) -> None:
    root = repo(tmp_path)
    sr.new_skill(root, "unpromoted-skill", "Use when testing admission.",
                 dest_dir=root / ".claude/skills")
    if surface == "list_skills":
        assert sr.list_skills(root) == []
    elif surface == "briefing":
        assert "unpromoted-skill" not in sr.briefing(root)
    else:
        args = ["list", "--json"] if surface == "json" else [surface]
        if surface == "render-index":
            args += ["--out", "-"]
        r = run_cli(*args, "--root", str(root))
        assert r.returncode == 0, r.stderr
        if surface == "json":
            row, = json.loads(r.stdout)
            assert row["name"] == "unpromoted-skill"
            assert row["admitted"] is False
            assert "receipt" in row["reason"]
        else:
            assert "unpromoted-skill" not in r.stdout


def test_promote_writes_receipt_for_candidate_and_support_files(tmp_path: Path) -> None:
    root = repo(tmp_path)
    d = write_skill(tmp_path, "receipted-skill", where="drafts")
    (d / "scripts").mkdir()
    (d / "scripts/check.py").write_bytes(b"print('verified')\r\n")
    (d / "reference.md").write_text("# Supporting reference\n")
    write_skill(root, "unpromoted-skill")
    report = sr.promote([d], repo_root=root)
    assert not report["rejected"]
    receipts = json.loads((root / ".claude/skills/admitted.json").read_text())
    receipt = receipts["receipted-skill"]
    assert set(receipts) == {"receipted-skill"}
    assert set(receipt) == {"sha256", "files", "admitted_at", "verify"}
    assert receipt["sha256"] == hashlib.sha256((d / "SKILL.md").read_bytes()).hexdigest()
    assert receipt["files"] == {rel: hashlib.sha256((d / rel).read_bytes()).hexdigest()
                                for rel in ("reference.md", "scripts/check.py")}
    assert datetime.fromisoformat(receipt["admitted_at"]).tzinfo is not None
    assert receipt["verify"] == "python3 _common/result_database.py --help >/dev/null"
    assert [s.name for s in sr.list_skills(root)] == ["receipted-skill"]
    assert "receipted-skill" in sr.briefing(root)
    assert "unpromoted-skill" not in (root / ".claude/skills/INDEX.md").read_text()
    rows = json.loads(run_cli("list", "--root", str(root), "--json").stdout)
    assert {s["name"]: s["admitted"] for s in rows} == {
        "receipted-skill": True, "unpromoted-skill": False}


def test_edited_skill_requires_executed_readmission(tmp_path: Path) -> None:
    root = repo(tmp_path)
    d = write_skill(tmp_path, "edited-skill", where="drafts")
    assert not sr.promote([d], repo_root=root)["rejected"]
    installed = root / ".claude/skills/edited-skill/SKILL.md"
    installed.write_text(installed.read_text() + "\nRevised instructions.\n")
    assert sr.list_skills(root) == []
    assert "edited-skill" not in sr.briefing(root)
    assert "edited-skill" not in sr.render_index(root)
    row, = json.loads(run_cli("list", "--root", str(root), "--json").stdout)
    assert row["admitted"] is False and "hash" in row["reason"]
    admitted = run_cli("admit", "edited-skill", "--root", str(root))
    assert admitted.returncode == 0, admitted.stdout + admitted.stderr
    assert [s.name for s in sr.list_skills(root)] == ["edited-skill"]
    receipts_file = root / ".claude/skills/admitted.json"
    receipts = receipts_file.read_bytes()
    receipt = json.loads(receipts)["edited-skill"]
    assert receipt["sha256"] == hashlib.sha256(installed.read_bytes()).hexdigest()
    installed.write_text(installed.read_text().replace(
        "python3 _common/result_database.py --help >/dev/null", "exit 7"))
    rejected = run_cli("admit", "edited-skill", "--root", str(root))
    assert rejected.returncode == 1
    assert "Verify block failed (exit 7)" in rejected.stdout
    assert receipts_file.read_bytes() == receipts
    assert sr.list_skills(root) == []


def test_admit_checks_each_installed_skill_without_copying(tmp_path: Path) -> None:
    root = repo(tmp_path)
    good = write_skill(root, "good-skill")
    write_skill(root, "bad-skill", GOOD.format(name="bad-skill").replace(
        "python3 _common/result_database.py --help >/dev/null", "exit 7"))
    before = (good / "SKILL.md").read_bytes()
    r = run_cli("admit", "good-skill", "bad-skill", "--root", str(root))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Verify block failed (exit 7)" in r.stdout
    assert [s.name for s in sr.list_skills(root)] == ["good-skill"]
    assert (good / "SKILL.md").read_bytes() == before
    assert set(json.loads((root / ".claude/skills/admitted.json").read_text())) == {"good-skill"}
    missing = run_cli("admit", "no-such-skill", "--root", str(root))
    assert missing.returncode == 1 and "no such skill" in missing.stderr


def test_new_defaults_to_runtime_drafts_and_prints_promote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    runtime = tmp_path / "runtime with spaces"
    monkeypatch.setenv("CHANDRA_RUNTIME", str(runtime))
    r = run_cli("new", "runtime-draft", "--description", "Use to test draft location.", "--root", str(root))
    assert r.returncode == 0, r.stderr
    created = json.loads(r.stdout)
    d = runtime / "skills/drafts/runtime-draft"
    assert Path(created["created"]) == d
    assert (d / "SKILL.md").is_file()
    assert not (root / ".claude/skills/runtime-draft").exists()
    args = shlex.split(created["promote"])
    assert args[2:] == ["promote", str(d), "--root", str(root)]


def test_printed_promote_command_works_outside_repository(tmp_path: Path) -> None:
    root = repo(tmp_path)
    r = run_cli("new", "portable-draft", "--description", "Use to test the printed command.",
                "--dest", str(tmp_path / "drafts with spaces"), "--root", str(root), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    command = shlex.split(json.loads(r.stdout)["promote"])
    p = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stdout + p.stderr
    assert [s.name for s in sr.list_skills(root)] == ["portable-draft"]


@pytest.mark.parametrize("target", ["SKILL.md", "reference.md"])
def test_verify_cannot_change_the_candidate_it_admits(tmp_path: Path, target: str) -> None:
    root = repo(tmp_path)
    text = GOOD.format(name="mutating-skill").replace(
        "python3 _common/result_database.py --help >/dev/null",
        f'printf "\\nchanged\\n" >> "$CLAUDE_SKILL_DIR/{target}"')
    d = write_skill(tmp_path, "mutating-skill", text, where="drafts")
    (d / "reference.md").write_text("Original support file.\n")
    report = sr.promote([d], repo_root=root)
    assert not report["promoted"], "the receipt must describe the bytes that were checked"
    assert any("changed during verification" in e for e in report["rejected"][0]["errors"])
    assert not (root / ".claude/skills/admitted.json").exists()


def test_changed_support_file_invalidates_admission(tmp_path: Path) -> None:
    root = repo(tmp_path)
    d = write_skill(tmp_path, "support-skill", where="drafts")
    (d / "reference.md").write_text("Verified support.\n")
    assert not sr.promote([d], repo_root=root)["rejected"]
    (root / ".claude/skills/support-skill/reference.md").write_text("Unverified support.\n")
    assert sr.list_skills(root) == []
    row, = json.loads(run_cli("list", "--root", str(root), "--json").stdout)
    assert row["admitted"] is False and "support" in row["reason"]


def test_example_verify_heading_does_not_satisfy_required_section(tmp_path: Path) -> None:
    root = repo(tmp_path)
    text = GOOD.format(name="example-only")
    before, example = text.split("\n## Verify", 1)
    d = write_skill(tmp_path, "example-only", before + "\n````markdown\n## Verify" + example + "````\n",
                    where="drafts")
    rep = sr.validate_skill(d, repo_root=root, execute=True)
    assert not rep.ok, "a heading inside an example is not a Verify section"
    assert "Verify section is required" in rep.errors


def test_symlinked_support_is_hashed_and_changes_invalidate_admission(tmp_path: Path) -> None:
    root = repo(tmp_path)
    text = GOOD.format(name="linked-skill").replace(
        "python3 _common/result_database.py --help >/dev/null",
        'bash "$CLAUDE_SKILL_DIR/scripts/check.sh"')
    d = write_skill(tmp_path, "linked-skill", text, where="drafts")
    (d / "scripts").mkdir()
    (d / "scripts/check.sh").write_text("true\n")
    assert not sr.promote([d], repo_root=root)["rejected"]
    installed = root / ".claude/skills/linked-skill"
    support = installed / "scripts"
    external = tmp_path / "external-support"
    support.rename(external)
    support.symlink_to(external, target_is_directory=True)
    assert [s.name for s in sr.list_skills(root)] == ["linked-skill"]
    (external / "check.sh").write_text("exit 7\n")
    assert not sr.validate_skill(installed, repo_root=root, execute=True).ok
    assert sr.list_skills(root) == []
    row, = json.loads(run_cli("list", "--root", str(root), "--json").stdout)
    assert row["admitted"] is False and "support" in row["reason"]


def test_missing_skill_file_is_reported_as_unadmitted(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".claude/skills/incomplete-skill").mkdir()
    r = run_cli("list", "--root", str(root), "--json")
    assert r.returncode == 0, r.stderr
    row, = json.loads(r.stdout)
    assert row["name"] == "incomplete-skill"
    assert row["admitted"] is False and "missing SKILL.md" in row["reason"]
    assert sr.list_skills(root) == []


def test_python_verifier_does_not_modify_candidate_with_bytecode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    text = GOOD.format(name="python-skill").replace(
        "python3 _common/result_database.py --help >/dev/null",
        'python3 "$CLAUDE_SKILL_DIR/scripts/check.py"')
    d = write_skill(tmp_path, "python-skill", text, where="drafts")
    (d / "scripts").mkdir()
    (d / "scripts/helper.py").write_text("EXPECTED = 1\n")
    (d / "scripts/check.py").write_text("import helper\nassert helper.EXPECTED == 1\n")
    report = sr.promote([d], repo_root=root)
    assert not report["rejected"], report
    assert not list(d.rglob("*.pyc")), "verification must not add interpreter artifacts to the candidate"
    assert [s.name for s in sr.list_skills(root)] == ["python-skill"]


def test_cli_validates_external_draft_before_admission(tmp_path: Path) -> None:
    root = repo(tmp_path)
    d = write_skill(tmp_path, "external-draft", where="runtime drafts")
    r = run_cli("validate", str(d), "--exec", "--root", str(root), cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 skills checked, 1 ok, 0 rejected" in r.stdout
    assert sr.list_skills(root) == []
