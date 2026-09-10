---
name: skill-write
description: Write a new loadable skill (SKILL.md) for this repo, or turn a procedure you just repeated into one, and land it through the skill registry gate — draft, validate, promote. Use when a worker or session discovers a reusable recipe, when the user asks to "make this a skill", or after any wave that produced a procedure worth keeping.
---

# skill-write — skills are auto-written, then admitted

A skill is a tool. Tools are promoted into methodology source only after a gate
(`_common/contracts/progress_principles.md` § tool promotion); for skills the gate is
`python _common/skill_registry.py validate --exec`. Nothing is hand-copied into
`.claude/skills/`.

## When to write one

- You performed the same non-obvious procedure twice, or once with a verifier you had to discover.
- A node's success criterion needed a recipe no existing skill states (`python _common/skill_registry.py list`).
- A worker's report names a "skill suggestion" (the worker prompt asks for one).

Do not write a skill for a one-off, for what `alignment.md` already binds, or for prose that
merely restates a spec — point at the spec instead.

## Steps

1. **Draft outside the gate.** In a mission: `${CHANDRA_RUNTIME}/<mission>/skills/<name>/SKILL.md`.
   In a direct session: `python _common/skill_registry.py new <name> --description "<trigger sentence>"`
   (scaffolds `${CHANDRA_RUNTIME:-/tmp/chandra}/skills/drafts/<name>/SKILL.md` and prints the
   promote command; `--dest` overrides). Name = kebab-case, ≤64 chars, equals the directory.
   A draft is never discoverable until promoted: `list`, `briefing`, and the index show only
   skills with a matching receipt in `.claude/skills/admitted.json`.
2. **Fill the contract.** Frontmatter: `name`, `description` (what it does AND when to use it — this
   is what triggers auto-loading; put the trigger phrases in), optional `disable-model-invocation: true`
   for opt-in skills, `user-invocable: false` for background knowledge. Body sections, in order:
   `## When to use`, `## Steps` (imperative, with the exact commands), `## Verify` (exactly ONE fenced
   bash block that exits 0 when the skill's claim holds — a real check, not `true`; read your own
   text only through `${CLAUDE_SKILL_DIR}`, never `.claude/skills/<name>/`, or the gate rejects it), optional
   `## Companion files`. Reference repo files by backticked repo-relative path (validated) and
   supporting files by relative link; keep the body under ~500 lines, move reference material
   into supporting files next to `SKILL.md`. Live data may be injected with `!`command``.
3. **Validate until green.** `python _common/skill_registry.py validate --exec --root . <name>`.
   Errors are the gate (name/dir mismatch, missing description, dangling references, failing
   Verify); warnings are advisory (`--strict` promotes them).
4. **Promote.** Drafts land with `python _common/skill_registry.py promote <draft-dir> --root .`
   (or `harvest <drafts-root>` for a whole batch): the candidate's Verify block runs against the
   candidate's bytes, a receipt (hashes of SKILL.md and every support file) is written to
   `.claude/skills/admitted.json`, and the index is re-rendered. Editing an installed skill
   invalidates its receipt; re-admit it with `python _common/skill_registry.py admit <name> --root .`.
5. **Commit** one skill per commit: `infra(skills): add <name> — <gist>` with a `verify:` object
   quoting the validate output. No tool attribution.

## Verify

```bash
python3 _common/skill_registry.py validate --root . skill-write \
  && python3 _common/skill_registry.py --help | grep -q admit \
  && python3 _common/skill_registry.py list --root . --json | grep -q '"name": "skill-write"'
```
