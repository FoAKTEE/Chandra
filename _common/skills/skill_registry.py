"""skill_registry — skills as verified methodology source (schema-as-code).

A skill is one directory `.claude/skills/<name>/` holding a `SKILL.md`
(YAML frontmatter + markdown body) and optional supporting files. Claude Code
loads project skills natively (name + description at session start, the body
on invocation); other clients — the Codex GPT worker, the orchestrator's SDK
sessions — load them through `briefing` / the rendered index. Either way a
skill is a tool, and the repo's tool-promotion doctrine applies: it enters
methodology source only through a gate.

    The agent proposes a skill; the validator admits it.

Gates (`validate`, run by `promote`/`harvest` before anything is copied):
  * frontmatter parses; `name` is kebab-case (<=64 chars) and EQUALS the
    directory name; `description` is present (<=1024 chars); unknown keys
    warn (`--strict` makes warnings fatal, like the commit gate).
  * the body is non-empty; every backticked repo path (`_common/...`,
    `pipelines/...`, ...) and every relative link / `${CLAUDE_SKILL_DIR}/...`
    reference RESOLVES — a skill pointing at a deleted file is spec drift and
    is rejected, not shipped.
  * a required `## Verify` section carries ONE fenced bash block; with
    `--exec` (always on for promotion) it is RUN from the repo root and must
    exit 0 — the closed-loop rule applied to documentation.

USAGE
    python _common/skill_registry.py list [--root R] [--json]
    python _common/skill_registry.py validate [--root R] [--exec] [--strict] [NAME ...]
    python _common/skill_registry.py admit NAME ... [--root R]    # execute Verify and receipt installed skills
    python _common/skill_registry.py render-index [--root R] [--out PATH]
    python _common/skill_registry.py briefing [--root R]          # <available-skills> block for SessionStart hooks
    python _common/skill_registry.py new NAME --description D [--body-file F] [--root R]
    python _common/skill_registry.py promote DRAFT_DIR ... [--root R] [--force] [--dry-run]
    python _common/skill_registry.py harvest DRAFTS_ROOT [--root R] [--force]   # promote every draft under a dir

SELF-IMPROVEMENT LOOP
    Workers that discover a reusable procedure draft it OUTSIDE the repo at
    `$CHANDRA_RUNTIME/<mission>/skills/<name>/SKILL.md` (ungated scratch).
    After each wave the orchestrator runs `harvest` on that directory: drafts
    that pass the gate land in `.claude/skills/`, the index is re-rendered,
    and the wave commit carries them; rejected drafts stay in the runtime dir
    with their errors reported. Nothing is hand-copied into `.claude/skills/`.

No third-party dependencies: the frontmatter parser is a deliberate YAML
subset (scalars, `>`/`|` block scalars, `[a, b]` and `- item` lists, one
level of nesting) — enough for every field Claude Code documents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILLS_DIR = ".claude/skills"
SKILL_FILE = "SKILL.md"
INDEX_FILE = "INDEX.md"
ADMITTED_FILE = "admitted.json"

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_MAX = 64
DESCRIPTION_MAX = 1024
DESCRIPTION_WARN = 600
BODY_LINE_WARN = 500
BODY_CHARS_WARN = 20000
VERIFY_TIMEOUT_S = 300

# Frontmatter keys Claude Code documents (code.claude.com/docs/en/skills).
# Unknown keys are a WARNING (the spec grows), never silently accepted.
KNOWN_KEYS = {
    "name", "description", "argument-hint", "arguments", "user-invocable",
    "disable-model-invocation", "allowed-tools", "disallowed-tools", "model",
    "effort", "context", "agent", "paths", "hooks", "license", "version",
    "metadata",
}
BOOL_KEYS = {"user-invocable", "disable-model-invocation"}
EFFORT_VALUES = {"low", "medium", "high", "xhigh", "max", "ultracode", "auto"}

_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_SKILL_DIR_REF_RE = re.compile(r"\$\{CLAUDE_SKILL_DIR\}/([^\s`\"')]+)")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_PATH_EXTS = (".md", ".py", ".sh", ".ts", ".js", ".json", ".jsonl", ".tex", ".toml", ".yaml", ".yml", ".txt", ".csv")


class SkillError(ValueError):
    """A skill that fails the registry's shape rules."""


# --- frontmatter (YAML subset) ------------------------------------------------

_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")


def _scalar(raw: str) -> Any:
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    return v


def _inline_list(raw: str) -> list[Any]:
    inner = raw.strip()[1:-1]
    return [_scalar(x) for x in inner.split(",") if x.strip()]


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md into (frontmatter dict, body). Raises SkillError when
    the file does not start with a `---` block."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        raise SkillError("missing frontmatter: file must start with a '---' line")
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise SkillError("unterminated frontmatter: no closing '---' line")
    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:])
    fm: dict[str, Any] = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = _KEY_RE.match(line)
        if not m:
            raise SkillError(f"frontmatter line {i + 2} is not `key: value`: {line!r}")
        key, raw = m.group(1), m.group(2).strip()
        # collect the indented continuation block, if any
        block: list[str] = []
        j = i + 1
        while j < len(fm_lines) and (not fm_lines[j].strip() or fm_lines[j][0] in " \t"):
            block.append(fm_lines[j])
            j += 1
        while block and not block[-1].strip():
            block.pop()
        if raw in (">", "|", ">-", "|-", ">+", "|+"):
            stripped = [b.strip() for b in block]
            if raw.startswith(">"):
                paras: list[str] = []
                cur: list[str] = []
                for s in stripped:
                    if s:
                        cur.append(s)
                    elif cur:
                        paras.append(" ".join(cur))
                        cur = []
                if cur:
                    paras.append(" ".join(cur))
                fm[key] = "\n".join(paras)
            else:
                fm[key] = "\n".join(stripped)
        elif raw.startswith("[") and raw.endswith("]"):
            fm[key] = _inline_list(raw)
        elif raw:
            fm[key] = _scalar(raw)
        elif block and all(b.strip().startswith("- ") for b in block if b.strip()):
            fm[key] = [_scalar(b.strip()[2:]) for b in block if b.strip()]
        elif block:
            nested: dict[str, Any] = {}
            for b in block:
                mm = _KEY_RE.match(b.strip())
                if mm and mm.group(2).strip():
                    nested[mm.group(1)] = _scalar(mm.group(2))
            fm[key] = nested if nested else "\n".join(block)
        else:
            fm[key] = ""
        i = j if block else i + 1
    return fm, body


# --- validation --------------------------------------------------------------

@dataclass
class SkillReport:
    name: str
    path: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    verify_command: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "path": self.path, "ok": self.ok,
                "errors": self.errors, "warnings": self.warnings,
                "description": self.frontmatter.get("description", "")}


def _looks_like_path(token: str) -> bool:
    if not token or any(c in token for c in " <>{}*$|\"'") or token.startswith(("http://", "https://")):
        return False
    return "/" in token or token.endswith(_PATH_EXTS)


def _clean_path(token: str) -> str:
    token = token.split("#", 1)[0]
    token = re.sub(r":\d+(?:-\d+)?$", "", token)   # file.py:12 / file.py:12-40
    return token.rstrip("/").strip()


def check_references(body: str, skill_dir: Path, repo_root: Path) -> list[str]:
    """Every referenced path must resolve: repo-relative code spans against
    the repo root (only when the first path segment is a real top-level entry
    of the repo, so consumer paths like results/... are skipped when absent),
    relative markdown links and ${CLAUDE_SKILL_DIR} references against the
    skill directory."""
    errors: list[str] = []
    top = {p.name for p in repo_root.iterdir()} if repo_root.is_dir() else set()
    seen: set[str] = set()
    for tok in _CODE_SPAN_RE.findall(body):
        tok = tok.strip()
        if not _looks_like_path(tok):
            continue
        rel = _clean_path(tok)
        first = rel.split("/", 1)[0]
        if first not in top or rel in seen:
            continue
        seen.add(rel)
        if not (repo_root / rel).exists():
            errors.append(f"dangling repo reference `{rel}` (no such file under {repo_root})")
    for rel in _MD_LINK_RE.findall(body):
        if "://" in rel or rel.startswith(("#", "/", "mailto:")):
            continue
        rel = _clean_path(rel)
        if rel and rel not in seen and not (skill_dir / rel).exists() and not (repo_root / rel).exists():
            seen.add(rel)
            errors.append(f"dangling link `{rel}` (not under the skill dir or the repo root)")
    for rel in _SKILL_DIR_REF_RE.findall(body):
        rel = _clean_path(rel)
        if rel and rel not in seen and not (skill_dir / rel).exists():
            seen.add(rel)
            errors.append(f"dangling ${{CLAUDE_SKILL_DIR}} reference `{rel}`")
    return errors


def verify_block(body: str) -> tuple[str | None, str | None]:
    """(command, error): exactly one shell block across the required Verify section(s)."""
    found_section = in_verify = False
    closing: re.Pattern[str] | None = None
    command_lines: list[str] | None = None
    blocks: list[tuple[str, list[str]]] = []
    for line in body.splitlines():
        if closing is not None:
            if closing.fullmatch(line):
                closing = None
                command_lines = None
            elif command_lines is not None:
                command_lines.append(line)
            continue
        fence = _FENCE_RE.match(line)
        if fence:
            marker, language = fence.groups()
            if marker[0] == "`" and "`" in language:
                continue
            closing = re.compile(rf" {{0,3}}{marker[0]}{{{len(marker)},}}[ \t]*")
            if in_verify:
                command_lines = []
                blocks.append((language.strip(), command_lines))
            continue
        heading = re.match(r"^ {0,3}(#{1,2})[ \t]+(.*)", line)
        if heading:
            in_verify = heading[1] == "##" and re.match(r"Verify\b", heading[2]) is not None
            found_section |= in_verify
    if not found_section:
        return None, "Verify section is required"
    if len(blocks) > 1:
        return None, f"Verify section must contain exactly one fenced block (found {len(blocks)})"
    if not blocks or command_lines is not None:
        return None, "Verify section has no fenced bash block"
    language, lines = blocks[0]
    command = "\n".join(lines).strip()
    if language not in ("bash", "sh", "shell", "") or not command:
        return None, "Verify section has no fenced bash block"
    return command, None


def run_verify(command: str, skill_dir: Path, repo_root: Path) -> str | None:
    """Run the Verify block from the repo root; None on exit 0, else the error."""
    env = {**os.environ, "CLAUDE_SKILL_DIR": str(skill_dir), "CLAUDE_SKILL_CANDIDATE": "1",
           "CLAUDE_PROJECT_DIR": str(repo_root), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        proc = subprocess.run(["bash", "-e", "-c", command], cwd=str(repo_root), env=env,
                              capture_output=True, text=True, timeout=VERIFY_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"Verify block timed out after {VERIFY_TIMEOUT_S}s"
    if proc.returncode != 0:
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-3:]
        return f"Verify block failed (exit {proc.returncode}): {' | '.join(tail) or command}"
    return None


def validate_skill(skill_dir: str | Path, *, repo_root: str | Path | None = None,
                   execute: bool = False, strict: bool = False) -> SkillReport:
    """Run every gate on one skill directory. Never raises for a bad skill —
    the report carries the errors so a batch can report them all."""
    d = Path(skill_dir).resolve()
    root = Path(repo_root).resolve() if repo_root else Path.cwd()
    rep = SkillReport(name=d.name, path=str(d))
    f = d / SKILL_FILE
    if not f.is_file():
        rep.errors.append(f"missing {SKILL_FILE}")
        rep.ok = False
        return rep
    try:
        fm, body = parse_frontmatter(f.read_text(encoding="utf-8"))
    except SkillError as e:
        rep.errors.append(str(e))
        rep.ok = False
        return rep
    rep.frontmatter = fm

    name = fm.get("name")
    if not isinstance(name, str) or not name:
        rep.errors.append("frontmatter `name` is required")
    else:
        if not NAME_RE.match(name):
            rep.errors.append(f"name {name!r} is not kebab-case (lowercase letters, digits, single hyphens)")
        if len(name) > NAME_MAX:
            rep.errors.append(f"name is {len(name)} chars (max {NAME_MAX})")
        if name != d.name:
            rep.errors.append(f"name {name!r} does not match its directory {d.name!r}")

    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        rep.errors.append("frontmatter `description` is required (it is what triggers the skill)")
    else:
        if len(desc) > DESCRIPTION_MAX:
            rep.errors.append(f"description is {len(desc)} chars (max {DESCRIPTION_MAX})")
        elif len(desc) > DESCRIPTION_WARN:
            rep.warnings.append(f"description is {len(desc)} chars (>{DESCRIPTION_WARN}; listings may truncate)")

    for key in fm:
        if key not in KNOWN_KEYS:
            rep.warnings.append(f"unknown frontmatter key `{key}` (known: {', '.join(sorted(KNOWN_KEYS))})")
    for key in BOOL_KEYS & fm.keys():
        if not isinstance(fm[key], bool):
            rep.warnings.append(f"`{key}` should be true/false, got {fm[key]!r}")
    if "context" in fm and fm["context"] != "fork":
        rep.errors.append(f"`context` must be 'fork' when present, got {fm['context']!r}")
    if "effort" in fm and str(fm["effort"]) not in EFFORT_VALUES:
        rep.warnings.append(f"`effort` {fm['effort']!r} not in {sorted(EFFORT_VALUES)}")

    if not body.strip():
        rep.errors.append("body is empty — a skill with no instructions admits nothing")
    else:
        n_lines = body.count("\n") + 1
        if n_lines > BODY_LINE_WARN:
            rep.warnings.append(f"body is {n_lines} lines (>{BODY_LINE_WARN}); move reference material to a supporting file")
        if len(body) > BODY_CHARS_WARN:
            rep.warnings.append(f"body is {len(body)} chars (>{BODY_CHARS_WARN}); progressive disclosure wants a lean SKILL.md")
        rep.errors.extend(check_references(body, d, root))
    cmd, err = verify_block(body)
    if err:
        rep.errors.append(err)
    rep.verify_command = cmd
    if cmd and re.search(rf"\.claude/skills/{re.escape(d.name)}(?=/|['\"]|$)", cmd):
        rep.errors.append("Verify block reads the installed skill instead of ${CLAUDE_SKILL_DIR}")
    elif cmd and execute:
        failure = run_verify(cmd, d, root)
        if failure:
            rep.errors.append(failure)

    rep.ok = not rep.errors and not (strict and rep.warnings)
    return rep


# --- registry ------------------------------------------------------------------

@dataclass
class SkillInfo:
    name: str
    path: str            # repo-relative path to SKILL.md
    description: str
    frontmatter: dict[str, Any]
    parse_error: str | None = None
    admitted: bool = False
    reason: str | None = None

    @property
    def invocation(self) -> str:
        fm = self.frontmatter
        if fm.get("user-invocable") is False:
            return "model-only"
        if fm.get("disable-model-invocation") is True:
            return f"/{self.name} (user-only)"
        return f"/{self.name} or auto"


def skills_root(repo_root: str | Path | None) -> Path:
    return (Path(repo_root).resolve() if repo_root else Path.cwd()) / SKILLS_DIR


def _skill_hashes(skill_dir: Path) -> dict[str, Any]:
    files = {}
    pending = [(skill_dir, {skill_dir.resolve()})]
    while pending:
        directory, ancestors = pending.pop()
        for path in sorted(directory.iterdir()):
            if path.is_dir():
                resolved = path.resolve()
                if resolved in ancestors:
                    raise SkillError(f"cyclic supporting directory: {path}")
                pending.append((path, ancestors | {resolved}))
            elif path.is_file() and path != skill_dir / SKILL_FILE:
                files[path.relative_to(skill_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"sha256": hashlib.sha256((skill_dir / SKILL_FILE).read_bytes()).hexdigest(), "files": files}


def _read_receipts(repo_root: Path) -> dict[str, Any]:
    path = repo_root / SKILLS_DIR / ADMITTED_FILE
    receipts = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(receipts, dict):
        raise SkillError(f"{path} must contain an object of admission receipts")
    return receipts


def _write_receipt(repo_root: Path, name: str, receipt: dict[str, Any]) -> None:
    path = repo_root / SKILLS_DIR / ADMITTED_FILE
    receipts = _read_receipts(repo_root)
    receipts[name] = receipt
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".admitted-", suffix=".tmp", delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(json.dumps(receipts, indent=2, sort_keys=True) + "\n")
            f.flush()
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def _admission_reason(skill_dir: Path, receipt: Any) -> str | None:
    if not isinstance(receipt, dict):
        return "no admission receipt"
    try:
        current = _skill_hashes(skill_dir)
    except (OSError, SkillError) as e:
        return f"cannot read admitted skill files: {e}"
    if current["sha256"] != receipt.get("sha256"):
        return "SKILL.md hash does not match admission receipt"
    if current["files"] != receipt.get("files"):
        return "supporting file hashes do not match admission receipt"
    return None


def list_skills(repo_root: str | Path | None = None, *, include_unadmitted: bool = False) -> list[SkillInfo]:
    """Discover only admitted bytes; include rejected directories for `list --json`."""
    root = Path(repo_root).resolve() if repo_root else Path.cwd()
    base = root / SKILLS_DIR
    out: list[SkillInfo] = []
    if not base.is_dir():
        return out
    receipts = _read_receipts(root)
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        f = d / SKILL_FILE
        if not f.is_file():
            if include_unadmitted:
                out.append(SkillInfo(d.name, str(f.relative_to(root)), "", {},
                                     reason=f"missing {SKILL_FILE}"))
            continue
        try:
            fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
            info = SkillInfo(d.name, str(f.relative_to(root)), str(fm.get("description", "")).strip(), fm)
        except SkillError as e:
            info = SkillInfo(d.name, str(f.relative_to(root)), "(unparseable frontmatter)", {}, str(e))
        info.reason = info.parse_error or _admission_reason(d, receipts.get(d.name))
        info.admitted = info.reason is None
        if info.admitted or include_unadmitted:
            out.append(info)
    return out


def render_index(repo_root: str | Path | None = None, out: str | Path | None = None) -> str:
    """The skills index — a GENERATED view over `.claude/skills/`, like every
    other markdown artifact in this repo. Re-rendered on every promotion."""
    skills = list_skills(repo_root)
    lines = [
        "# Skills index",
        "",
        "**GENERATED by `python _common/skill_registry.py render-index` — do not hand-edit.**",
        f"{len(skills)} skills under `{SKILLS_DIR}/`. Load one by reading its `SKILL.md`;",
        "Claude Code auto-loads name + description at session start. Validate with",
        "`python _common/skill_registry.py validate --exec`.",
        "",
        "| skill | invoke | description |",
        "|---|---|---|",
    ]
    for s in skills:
        desc = " ".join(s.description.split())
        lines.append(f"| [`{s.name}`]({s.name}/SKILL.md) | {s.invocation} | {desc} |")
    lines.append("")
    text = "\n".join(lines)
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return text


def briefing(repo_root: str | Path | None = None) -> str:
    """Compact `<available-skills>` block for SessionStart hooks and for
    clients without native skill loading (Codex workers, SDK sessions)."""
    skills = list_skills(repo_root)
    lines = [f'<available-skills count="{len(skills)}" root="{SKILLS_DIR}">']
    for s in skills:
        desc = " ".join(s.description.split())
        lines.append(f"- {s.name} — {desc} ({s.path})")
    lines.append("Load a skill by reading its SKILL.md when its description matches the task; "
                 "draft new ones with `python _common/skill_registry.py new`, land them with `promote`.")
    lines.append("</available-skills>")
    return "\n".join(lines) + "\n"


# --- authoring: new + promote ---------------------------------------------------

SKILL_TEMPLATE = """---
name: {name}
description: {description}
---

# {name}

## When to use

{when}

## Steps

1. State the goal in one sentence and the verifier that will admit it.
2. Do the work; paste the verifier output, never a summary of it.

## Verify

```bash
test -f "${{CLAUDE_SKILL_DIR:-.}}/SKILL.md"
```
"""


def new_skill(repo_root: str | Path | None, name: str, description: str, *,
              body: str | None = None, dest_dir: str | Path | None = None) -> Path:
    """Scaffold runtime `skills/drafts/<name>/SKILL.md` (or `dest_dir/<name>/`). Refuses
    to overwrite. The scaffold validates as-is; replace the Verify block with
    the skill's real closed-loop check."""
    if not NAME_RE.match(name) or len(name) > NAME_MAX:
        raise SkillError(f"name {name!r} must be kebab-case, <= {NAME_MAX} chars")
    if not description.strip():
        raise SkillError("description is required")
    base = (Path(dest_dir).resolve() if dest_dir else
            Path(os.environ.get("CHANDRA_RUNTIME") or "/tmp/chandra").resolve() / "skills" / "drafts")
    d = base / name
    if d.exists():
        raise SkillError(f"skill directory already exists: {d}")
    d.mkdir(parents=True)
    if body is None:
        text = SKILL_TEMPLATE.format(name=name, description=description.strip(),
                                     when="Describe the trigger: the task shape, the stage, the signal.")
    else:
        text = f"---\nname: {name}\ndescription: {description.strip()}\n---\n\n{body.rstrip()}\n"
    (d / SKILL_FILE).write_text(text, encoding="utf-8")
    return d


def _verified_receipt(skill_dir: Path, repo_root: Path) -> tuple[SkillReport, dict[str, Any] | None]:
    try:
        before = _skill_hashes(skill_dir) if (skill_dir / SKILL_FILE).is_file() else None
    except (OSError, SkillError) as e:
        return SkillReport(skill_dir.name, str(skill_dir), ok=False, errors=[str(e)]), None
    rep = validate_skill(skill_dir, repo_root=repo_root, execute=True)
    if not rep.ok:
        return rep, None
    if _admission_reason(skill_dir, before):
        rep.errors.append("skill files changed during verification")
        rep.ok = False
        return rep, None
    return rep, {**before, "admitted_at": datetime.now(timezone.utc).isoformat(), "verify": rep.verify_command}


def admit(names: list[str], *, repo_root: str | Path | None = None) -> list[SkillReport]:
    """Execute Verify and write receipts for already-installed skills."""
    root = Path(repo_root).resolve() if repo_root else Path.cwd()
    reports = []
    for name in names:
        rep, receipt = _verified_receipt(root / SKILLS_DIR / name, root)
        reports.append(rep)
        if receipt is not None:
            _write_receipt(root, name, receipt)
    if any(r.ok for r in reports):
        render_index(root, out=root / SKILLS_DIR / INDEX_FILE)
    return reports


def promote(draft_dirs: list[str | Path], *, repo_root: str | Path | None = None,
            force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Admit drafts into `.claude/skills/`: each is validated WITH its Verify
    block executed; valid drafts are copied whole (supporting files included),
    then the index is re-rendered. Returns {promoted: [...], rejected: [...]}."""
    root = Path(repo_root).resolve() if repo_root else Path.cwd()
    dest_root = root / SKILLS_DIR
    report: dict[str, Any] = {"promoted": [], "rejected": []}
    for src in draft_dirs:
        src = Path(src).resolve()
        rep, receipt = _verified_receipt(src, root)
        if not rep.ok:
            report["rejected"].append({"name": src.name, "source": str(src), "errors": rep.errors})
            continue
        dest = dest_root / src.name
        if dest.exists() and not force:
            report["rejected"].append({"name": src.name, "source": str(src),
                                       "errors": [f"destination exists: {dest} (use --force to replace)"]})
            continue
        if not dry_run:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            reason = _admission_reason(dest, receipt)
            if reason:
                report["rejected"].append({"name": src.name, "source": str(src), "errors": [reason]})
                continue
            _write_receipt(root, src.name, receipt)
        report["promoted"].append({"name": src.name, "source": str(src), "path": str(dest.relative_to(root))})
    if report["promoted"] and not dry_run:
        render_index(root, out=dest_root / INDEX_FILE)
    return report


def harvest(drafts_root: str | Path, *, repo_root: str | Path | None = None,
            force: bool = False) -> dict[str, Any]:
    """Promote every `<drafts_root>/<name>/SKILL.md` — the per-wave sweep of the
    runtime skill drafts. A missing or empty drafts dir is a clean no-op."""
    base = Path(drafts_root)
    if not base.is_dir():
        return {"promoted": [], "rejected": []}
    drafts = sorted(p for p in base.iterdir() if p.is_dir() and (p / SKILL_FILE).is_file())
    if not drafts:
        return {"promoted": [], "rejected": []}
    return promote(drafts, repo_root=repo_root, force=force)


# --- CLI -----------------------------------------------------------------------

def _print_reports(reports: list[SkillReport]) -> None:
    for r in reports:
        mark = "✓" if r.ok else "✗"
        print(f"{mark} {r.name}")
        for e in r.errors:
            print(f"    error:   {e}")
        for w in r.warnings:
            print(f"    warning: {w}")
    bad = sum(1 for r in reports if not r.ok)
    print(f"{len(reports)} skills checked, {len(reports) - bad} ok, {bad} rejected")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="skill_registry",
                                 description="skills as verified methodology source: list, validate, index, scaffold, promote")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list skills under .claude/skills")
    ls.add_argument("--root", type=Path, default=None)
    ls.add_argument("--json", action="store_true")

    va = sub.add_parser("validate", help="run the gates on every (or the named) skills; exit 1 on any rejection")
    va.add_argument("names", nargs="*", help="installed skill names or draft directories")
    va.add_argument("--root", type=Path, default=None)
    va.add_argument("--exec", action="store_true", help="also RUN each skill's `## Verify` block from the repo root")
    va.add_argument("--strict", action="store_true", help="warnings are errors")

    ad = sub.add_parser("admit", help="execute Verify and receipt already-installed skills; exit 1 on rejection")
    ad.add_argument("names", nargs="+")
    ad.add_argument("--root", type=Path, default=None)

    ri = sub.add_parser("render-index", help=f"render the GENERATED skills index (default: {SKILLS_DIR}/{INDEX_FILE})")
    ri.add_argument("--root", type=Path, default=None)
    ri.add_argument("--out", type=Path, default=None, help="output path ('-' = stdout)")

    br = sub.add_parser("briefing", help="print the <available-skills> block for SessionStart hooks / non-Claude clients")
    br.add_argument("--root", type=Path, default=None)

    nw = sub.add_parser("new", help="scaffold a skill directory (refuses to overwrite)")
    nw.add_argument("name")
    nw.add_argument("--description", required=True)
    nw.add_argument("--body-file", type=Path, default=None, help="markdown body to use instead of the template")
    nw.add_argument("--root", type=Path, default=None)
    nw.add_argument("--dest", type=Path, default=None,
                    help="draft location (default: ${CHANDRA_RUNTIME:-/tmp/chandra}/skills/drafts)")

    pr = sub.add_parser("promote", help="validate (with Verify executed) and copy drafts into .claude/skills; exit 1 if any rejected")
    pr.add_argument("drafts", nargs="+", type=Path)
    pr.add_argument("--root", type=Path, default=None)
    pr.add_argument("--force", action="store_true")
    pr.add_argument("--dry-run", action="store_true")

    hv = sub.add_parser("harvest", help="promote every draft under DRAFTS_ROOT (per-wave sweep; rejected drafts are reported, exit 0)")
    hv.add_argument("drafts_root", type=Path)
    hv.add_argument("--root", type=Path, default=None)
    hv.add_argument("--force", action="store_true")

    args = ap.parse_args(argv)
    root = args.root.resolve() if getattr(args, "root", None) else Path.cwd()

    if args.cmd == "list":
        skills = list_skills(root, include_unadmitted=args.json)
        if args.json:
            print(json.dumps([{"name": s.name, "path": s.path, "description": s.description,
                               "invocation": s.invocation, "parse_error": s.parse_error,
                               "admitted": s.admitted, "reason": s.reason} for s in skills], indent=2))
        else:
            for s in skills:
                print(f"{s.name:<32} {s.invocation:<24} {' '.join(s.description.split())[:80]}")
            print(f"{len(skills)} skills under {SKILLS_DIR}/")
        return 0

    if args.cmd in ("validate", "admit"):
        base = root / SKILLS_DIR
        dirs = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        if args.names:
            dirs = [d for d in dirs if d.name in set(args.names)]
            missing = set(args.names) - {d.name for d in dirs}
            if args.cmd == "validate":
                for name in sorted(missing):
                    draft = Path(name).resolve()
                    if draft.is_dir():
                        dirs.append(draft)
                        missing.remove(name)
            if missing:
                print(f"no such skill(s): {sorted(missing)}", file=sys.stderr)
                return 1
        reports = (admit([d.name for d in dirs], repo_root=root) if args.cmd == "admit" else
                   [validate_skill(d, repo_root=root, execute=args.exec, strict=args.strict) for d in dirs])
        _print_reports(reports)
        return 0 if all(r.ok for r in reports) else 1

    if args.cmd == "render-index":
        out = None if (args.out and str(args.out) == "-") else (args.out or root / SKILLS_DIR / INDEX_FILE)
        text = render_index(root, out=out)
        if out is None:
            sys.stdout.write(text)
        else:
            print(json.dumps({"rendered": True, "path": str(out)}))
        return 0

    if args.cmd == "briefing":
        sys.stdout.write(briefing(root))
        return 0

    if args.cmd == "new":
        body = args.body_file.read_text(encoding="utf-8") if args.body_file else None
        try:
            d = new_skill(root, args.name, args.description, body=body, dest_dir=args.dest)
        except SkillError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        command = shlex.join(["python3", str(Path(__file__).resolve()), "promote", str(d), "--root", str(root)])
        print(json.dumps({"created": str(d), "promote": command}))
        return 0

    if args.cmd == "promote":
        report = promote(args.drafts, repo_root=root, force=args.force, dry_run=args.dry_run)
        print(json.dumps(report, indent=2))
        return 0 if not report["rejected"] else 1

    if args.cmd == "harvest":
        report = harvest(args.drafts_root, repo_root=root, force=args.force)
        print(json.dumps(report, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
