---
name: skill-load
description: Load this repo's skills into ANY agent client — Claude Code (native), the Codex CLI worker (AGENTS.md + the generated index), Agent SDK sessions, or hook-capable clients (the SessionStart briefing) — and put the skill list into a worker's context pack. Use when starting a session or worker outside Claude Code, when writing a worker prompt, or when asking "which skills exist / how do I load one".
---

# skill-load — the same skills, loaded in every client

Skills live in `.claude/skills/<name>/SKILL.md`; the registry renders them into
`.claude/skills/INDEX.md` (generated) and a compact `<available-skills>` briefing.
Kernel §5: a sub-agent gets an explicit context pack — the skill list is part of it.

## When to use

- A worker will run in the Codex CLI, an Agent SDK session, or any client without native skills.
- You are composing a worker prompt and must name the skills it should read.
- You want the current list: `python3 _common/skill_registry.py list --root .`

## Steps

1. **Claude Code** — nothing to do. Project skills load by name + description at session
   start and by body on invocation (`/<name>` or auto-match). Start the session in the repo
   root (a session started in a parent directory sees them as directory-scoped skills).
2. **Codex CLI worker** — `AGENTS.md` at the repo root is read automatically; it points at the
   kernel, the admission contract, and `.claude/skills/INDEX.md`. In the prompt, still name
   the two or three skills the task needs as absolute paths to their `SKILL.md`
   (`codex-gpt6-max` shows the prompt shape). The orchestrator's codex runners prepend that
   pointer to every worker/job prompt.
3. **Hook-capable clients** — use `bash .claude/inject_infra.sh --with-skills` (or set
   `CHANDRA_INJECT_SKILLS=1`) as the SessionStart command: it emits the kernel, the admission
   contract, and the `<available-skills>` block. Leave it off for Claude Code, which already
   lists the skills.
4. **Any prompt / context pack** — paste the output of
   `python3 _common/skill_registry.py briefing --root .`; the worker then reads a skill's
   `SKILL.md` when its description matches the task.
5. **Keep the list true** — discovery (`list`, `briefing`, `render-index`, `harvest`) shows only skills
   whose bytes match their receipt in `.claude/skills/admitted.json`; after editing an installed skill
   run `python3 _common/skill_registry.py admit <name> --root .` (Verify executed, receipt rewritten);
   `list --json` names anything unadmitted and why; after any promotion run `python3 _common/skill_registry.py render-index --root .`;
   in CI run `python3 _common/skill_registry.py validate --exec --root .` (also executed by
   `tests/test_skill_registry.py`), so a skill that points at a deleted file fails the build.

## Verify

```bash
python3 _common/skill_registry.py briefing --root . | grep -q '^<available-skills' \
  && bash .claude/inject_infra.sh --with-skills | grep -q '<available-skills' \
  && grep -q 'INDEX.md' AGENTS.md
```
