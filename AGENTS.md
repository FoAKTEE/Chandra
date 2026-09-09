# AGENTS.md — Chandra, for any coding agent

This repo is a methodology for verified, agent-driven research and it runs its
own methodology on itself. One invariant binds every agent that works here,
whatever client it runs in (Claude Code, Codex CLI, an Agent SDK session):

    The agent proposes; the verifier admits.

## Read first, in this order

1. `alignment.md` — the always-on kernel (§0 verifier admits · §1 fact-driven ·
   §2 no tweak-loops · §3 stall → acquire · §4 source discipline · §5 context
   injection · §6 delegation-only). Binding.
2. `_common/contracts/research_admission_contract.md` — what an admitted result is.
3. `.claude/skills/INDEX.md` — the generated index of loadable skills. Load a
   skill by reading `.claude/skills/<name>/SKILL.md` when its description
   matches your task; start with `chandra-orient`, which maps every moment of
   the loop to a skill. `INDEX.md` wins when any doc disagrees with another.

## Rules that bind every agent

- **Progress is a gated ledger append.** Results, nodes, claims, and trials
  enter memory only through `python3 _common/<db>_database.py append …`
  (`result`, `knowledge`, `claims`, `error`), which RUNS the row's verification
  command, hashes evidence, and resolves dependencies. Under
  `.delegation-policy: strict` the process must carry `CHANDRA_ROLE=worker`
  (or `validator` / `observer` for those roles). Markdown views are rendered
  (`render-md`, `render-state`, `render-index`), never hand-edited.
- **No parameter-tweak loops.** Three cycles of one idea ⇒
  `python3 _common/loop_policy.py crash-triage`; switch approach or escalate.
  Every trial, pass or fail, lands in the error ledger with expected /
  observed / root_cause / fix_hypothesis.
- **Verify before claiming.** `python3 -m pytest`; `cd orchestrator && npm test`;
  skills: `python3 _common/skill_registry.py validate --exec`. Paste the
  verifier output; never summarize it from memory.
- **Commits.** One commit per DAG node (or finer); tests before/with the code
  they verify; the title grammar of `_common/contracts/commit_template.md`,
  enforced by the gate installed with `bash _common/hooks/install.sh`; no tool
  or model attribution of any kind; never commit large datasets or mirrors.
- **Skills are auto-written, then admitted.** A reusable procedure you
  discovered becomes a draft skill (`skill-write`), lands only through
  `python3 _common/skill_registry.py promote` (validated, Verify executed),
  and ships in its own `infra(skills):` commit.

## Loading skills outside Claude Code

`python3 _common/skill_registry.py briefing` prints the compact
`<available-skills>` block; `bash .claude/inject_infra.sh --with-skills` emits
the whole session-start briefing (kernel + contract + skills) for clients that
support hooks but not skills. Codex-style agents read this file automatically.
