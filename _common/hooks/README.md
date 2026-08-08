# Git hooks (tracked) — the commit-message gate

`.git/hooks/` is not version-controlled, so the methodology's git hooks live here
and are activated per-clone by pointing `core.hooksPath` at this directory.

## Install (once per clone)

```bash
bash _common/hooks/install.sh
```

Idempotent. Sets `core.hooksPath = _common/hooks` and `commit.template = .gitmessage`.
Undo with `git config --unset core.hooksPath` (and `--unset commit.template`).

## `commit-msg` — the gate

Enforces the title grammar of [`_common/contracts/commit_template.md`](../contracts/commit_template.md),
the promoted/tracked form of the old `progress/COMMIT_TEMPLATE.md` (`progress/` is
gitignored, so the template could not be enforced from there).

- **Hard error → commit rejected:** the title must match
  `^(<type>)(\(<scope>\))?(!)?: <summary>$` with
  `type ∈ {feat,fix,perf,refactor,docs,test,build,ci,style,revert,diag,exp,chore,infra,notes}`.
- **Warnings (advisory):** missing blank line after subject; unknown body object
  kind (`- why|finding|change|run|result|verify|caveat|next|files:`); a
  `finding`/`result` object with no `[SOLID|PRELIMINARY|HOLE|FUTURE]` claim tag;
  `!` without a `BREAKING CHANGE:` footer (or vice-versa).
- `Merge`/`Revert`/`fixup!`/`squash!`/`amend!` and empty messages are passed through.

Knobs:
- `COMMIT_GATE_STRICT=1 git commit …` — escalate every warning to a hard error.
- `git commit --no-verify …` — bypass the gate for one commit.

Standalone (used by the test suite):

```bash
_common/hooks/commit-msg path/to/message.txt   # exit 0 = admit, 1 = reject
```

## Self-test

```bash
python3 -m pytest tests/test_commit_msg_gate.py -q
```
