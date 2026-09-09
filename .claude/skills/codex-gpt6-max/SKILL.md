---
name: codex-gpt6-max
description: Delegate a substantial implementation, derivation-check, review, or research task to a Codex GPT-6 (gpt-6-astra, reasoning effort max) worker, non-interactively from this session — a prompt file in, a transcript log and final memo out. Use whenever the policy says "GPT-6 max as worker", when handing a DAG node to a worker agent, or when a second-model pass (cross-model refutation, independent review) is wanted.
---

# codex-gpt6-max — GPT-6 (max reasoning) as the worker

Kernel §6: the launching session ORCHESTRATES; workers do the work. This skill is
the one-file way to lease a task to a GPT-6 worker and get evidence back.

## When to use

- A DAG node or packet needs implementation, a derivation check, or a proof programme.
- A cross-model pass is wanted: refuter/judge on a different model than the defender.
- A review of a plan, a diff, or a paper section by an independent model.

Not for one-line lookups this session can do faster itself.

## Steps

1. **Write the prompt file** under `${CHANDRA_RUNTIME:-/tmp/chandra}/codex/<task>.prompt.md`.
   Structure it as an operator's contract, not a chat (XML blocks keep it stable):
   `<task>` (the concrete job + every file to read as an absolute path), `<output_contract>`
   (what "done" is: files written, the verification command, the memo shape),
   `<constraints>` (touch only the named paths; never run `git add`/`git commit`; no
   attribution of any tool in files or messages), `<verification_loop>` (the exact command
   that must exit 0 before finishing; paste its tail in the final message).
   For Chandra work the prompt must name `alignment.md` and
   `_common/contracts/research_admission_contract.md` as required reading, and set the
   role: appends run with `CHANDRA_ROLE=worker`.
2. **Start it** (returns immediately; runs in the background):
   ```bash
   bash .claude/skills/codex-gpt6-max/run_codex_max.sh <task> <prompt-file> [danger-full-access|workspace-write|read-only] [cwd]
   ```
   `CODEX_MODEL` (default `gpt-6-astra`) and `CODEX_EFFORT` (default `max`) are env overrides.
   Independent tasks may run in parallel — give each disjoint files to touch.
3. **Wait, bounded** — never an unbounded sleep:
   ```bash
   bash .claude/skills/codex-gpt6-max/wait_codex.sh <task> 3600 30   # prints the final memo
   ```
   The log is `${CHANDRA_RUNTIME:-/tmp/chandra}/codex/<task>.log`; it ends with `# done`.
4. **Verify before trusting**: run the task's verification command yourself (test suite,
   `python3 _common/skill_registry.py validate --exec`, the admission gate). The worker's
   prose is not evidence; the ledger diff and the command output are.
5. **Land it**: review the diff, then commit per DAG node with a gate-compliant message.
   Attribute nothing to a tool in commits, papers, or notes.

## Host notes

- Codex's bubblewrap sandbox fails on this host (`bwrap: loopback: Failed RTM_NEWADDR`), so
  `read-only`/`workspace-write` cannot run shell commands; use `danger-full-access` and
  bound the worker by naming the paths it may write. Check the log for `bwrap` before
  trusting a memo.
- `codex exec` blocks forever on an open non-tty stdin: the script always feeds the prompt
  with `- < file`. Do not call codex by hand without that redirection.
- The transcript header records the model and effort actually used — copy them into the
  memo header when the memo is folded into a record.

## Verify

```bash
bash -n "${CLAUDE_SKILL_DIR}/run_codex_max.sh" && bash -n "${CLAUDE_SKILL_DIR}/wait_codex.sh" && { command -v codex >/dev/null || echo "note: codex CLI not on PATH (npm i -g @openai/codex)"; }
```
