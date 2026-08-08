#!/usr/bin/env bash
# install.sh — activate the tracked git hooks for this clone.
#
# Git hooks under .git/hooks are NOT version-controlled, so the gate lives in the
# tracked _common/hooks/ directory and is activated by pointing core.hooksPath at
# it. Run this once per clone (it is idempotent):
#
#   bash _common/hooks/install.sh
#
# This wires:
#   - core.hooksPath  -> _common/hooks      (runs the commit-msg gate)
#   - commit.template -> .gitmessage        (offers the skeleton in the editor)
#
# Undo with:  git config --unset core.hooksPath && git config --unset commit.template

set -u

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    printf 'install.sh: not inside a git work tree\n' >&2
    exit 1
}
cd "$REPO_ROOT" || exit 1

chmod +x _common/hooks/commit-msg 2>/dev/null || true

git config core.hooksPath _common/hooks
printf 'set core.hooksPath = %s\n' "$(git config --get core.hooksPath)"

if [ -f .gitmessage ]; then
    git config commit.template .gitmessage
    printf 'set commit.template = %s\n' "$(git config --get commit.template)"
fi

printf 'commit-msg gate active. Spec: _common/contracts/commit_template.md\n'
printf 'Bypass a single commit with: git commit --no-verify\n'
