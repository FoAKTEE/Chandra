#!/usr/bin/env bash
# inject_infra.sh — cross-client reference implementation
#
# Emits the ~2KB alignment kernel + the research admission contract as a
# <session-start-briefing>. Everything else is POINTED TO, not inlined —
# agents Read contracts/specs/templates when their stage needs them
# (progressive disclosure; the old 60KB firehose is gone).
#
# Wired into .claude/settings.json as the SessionStart hook, and also usable
# as a manual bootstrap for clients that do not support hooks.

set -u

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$(cd "$(dirname "$0")/.." && pwd)")"

emit_file() {
    local label="$1" path="$2"
    printf '\n----- BEGIN %s (%s) -----\n' "$label" "$path"
    if [ -f "$path" ]; then
        cat "$path"
    else
        printf '(missing: %s)\n' "$path"
    fi
    printf '\n----- END %s -----\n' "$label"
}

printf '<session-start-briefing enforcement="MANDATORY">\n'
printf '\n=== CHANDRA INFRA (source of truth: %s) ===\n' "$REPO_ROOT"

emit_file "alignment.md (kernel)" "$REPO_ROOT/alignment.md"
emit_file "_common/contracts/research_admission_contract.md" "$REPO_ROOT/_common/contracts/research_admission_contract.md"

printf '\nRead on demand (do NOT inline): INDEX.md · _common/contracts/ · notes/ · pipelines/*/spec.md\n'
printf '\n=== END CHANDRA INFRA ===\n'
printf '</session-start-briefing>\n'
