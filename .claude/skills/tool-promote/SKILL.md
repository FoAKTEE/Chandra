---
name: tool-promote
description: Promote a reusable run-local tool into a grouped _common package with a flat CLI shim, registered import/help coverage, and smoke plus rejection tests. Load for "promote this tool", "make this reusable", "add a shared CLI", or an ad hoc procedure that should become a verified skill.
---

# tool-promote — admit reusable mechanics as tested shared infrastructure

## When to use

- A run-local script solves a recurring problem beyond the current mission.
- Multiple procedures duplicate mechanics that belong in shared infrastructure.
- A reusable operational recipe should become a loadable, verified skill.

## Steps

1. Read Tool promotion in `_common/contracts/progress_principles.md`,
   `_common/README.md`, `tests/README.md`, and `tests/test_imports_cli.py`.
   Identify the reusable behavior, input/output contract, and actual rejection boundary.
   Keep unrelated run artifacts out of the promotion; preserve the user's authorized scope.
   Keep scratch in `${CHANDRA_RUNTIME}/<mission>/`, per `INDEX.md`; the progress-folder
   scratch sentence in the promotion prose is stale.
2. Search existing packages before adding a tool. Put the implementation in an existing
   suitable group: `_common/ledgers/`, `_common/loop/`, `_common/visualization/`,
   `_common/quality/`, or `_common/skills/`. Add a new group only for a distinct shared domain.
   Use the layout `_common/<group>/<tool>.py` plus `_common/<tool>.py` for the flat shim.
   Prefer `_common.<group>.<tool>` for internal imports; keep historical callers working.
3. Implement a CLI entry point `main(argv=None)` returning an integer exit status.
   Use real argument parsing and descriptive help. Make top-level `--help` and each
   subcommand's `--help` exit 0 without running a mission or mutating artifacts.
   Reject malformed input with a nonzero exit and an actionable diagnostic; validate
   before mutation. Keep import-time behavior free of mission execution and data writes.
   For direct grouped-script execution, follow the repo-root import bootstrap in
   `_common/loop/loop_policy.py` instead of depending on the caller's working directory.
4. Model the flat wrapper on `_common/loop_gate.py`. This is the existing pattern;
   replace the imported module with the promoted implementation when creating its shim:
   ```python
   import sys
   from pathlib import Path

   sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
   from _common.loop.loop_gate import *
   from _common.loop.loop_gate import main

   if __name__ == "__main__":
       raise SystemExit(main())
   ```
   Re-export the SAME `main` object. Do not copy logic, translate arguments, or implement
   a second dispatcher in the shim. Keep any required public compatibility exports.
5. Add the new tool to all four registrations in `tests/test_imports_cli.py`:

   | List | Entry to add for a grouped tool with a shim |
   |---|---|
   | `PACKAGE_MODULES` | `_common.<group>.<tool>` |
   | `FLAT_SHIMS` | `_common.<tool>` |
   | `SHIM_MAIN_PAIRS` | `("_common.<tool>", "_common.<group>.<tool>")` |
   | `CLI_SCRIPTS` | Both `_common/<group>/<tool>.py` and `_common/<tool>.py` |

   If it is a ledger with a schema subcommand, also add its grouped CLI to `SCHEMA_CLIS`.
   Update the infrastructure layout and test coverage pointers for the new behavior
   when those files are within the assignment's edit scope.
6. Add `tests/test_<tool>.py` with at least a meaningful smoke and rejection case.
   Exercise a valid invocation and assert its observable result, not just exit 0.
   Exercise an invalid input or violated contract and assert rejection before changes land.
   Put all fixtures/output under pytest's `tmp_path`; use no network or real ledgers.
   Test import/main identity through the shared registration and add subcommand-help
   coverage for the entry points this tool introduces. Do not weaken existing checks.
7. Run the real CLIs and tests from the repo root after filling in the tool identifiers:
   ```bash
   tool_group='<group>'
   tool_name='<tool>'
   python3 "_common/$tool_group/$tool_name.py" --help
   python3 "_common/$tool_name.py" --help
   # For each actual subcommand, set tool_subcommand to its implemented name:
   python3 "_common/$tool_group/$tool_name.py" "$tool_subcommand" --help
   python3 "_common/$tool_name.py" "$tool_subcommand" --help
   python3 -m pytest tests/test_imports_cli.py "tests/test_$tool_name.py" -q
   python3 -m pytest
   ```
   The final full suite is the shared-infrastructure admission check from `_common/README.md`.
   Use current tests, not that README's obsolete stage-adapter `init`/`check-isolation` recipe.
   Fix every failure; do not present a script copied into a package as an admitted tool.
8. Treat skills as tools too. Read `.claude/skills/skill-write/SKILL.md` and use
   `_common/skills/skill_registry.py` through its flat `_common/skill_registry.py` CLI.
   Set `skill_name`, `skill_description`, and an external `skill_drafts` directory;
   scaffold, fill the real procedure and a bounded Verify block, then admit it:
   ```bash
   python3 _common/skill_registry.py new "$skill_name" --description "$skill_description" --dest "$skill_drafts" --root .
   # Edit the draft's SKILL.md before promotion.
   python3 _common/skill_registry.py promote "$skill_drafts/$skill_name" --root . --dry-run
   python3 _common/skill_registry.py promote "$skill_drafts/$skill_name" --root .
   python3 _common/skill_registry.py validate --exec --root . "$skill_name"
   ```
   Promotion executes Verify before copying and refreshes the generated index.
   A rejected draft stays outside methodology source. Resolve collisions deliberately;
   do not use replacement flags to erase another skill's work.
9. Land one node (or finer) in an `infra(<scope>): <imperative summary>` commit;
   use `infra(skills): ...` for a promoted skill. Include the smoke/rejection evidence
   and exact verification output in typed body objects. Commit tests before/with code.
   Apply `.claude/skills/commit-gated/SKILL.md`; include no tool/model attribution.
   Under a no-commit worker assignment, hand the verified diff and message to the landing owner.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
for script in _common/loop_gate.py _common/loop/loop_gate.py _common/skill_registry.py _common/skills/skill_registry.py; do
  python3 "$script" --help >/dev/null
done
for subcommand in new promote validate; do
  python3 _common/skill_registry.py "$subcommand" --help >/dev/null
done
python3 - <<'PY'
import ast
import importlib
from pathlib import Path
tree = ast.parse(Path('tests/test_imports_cli.py').read_text())
names = {'PACKAGE_MODULES', 'FLAT_SHIMS', 'SHIM_MAIN_PAIRS', 'CLI_SCRIPTS'}
lists = {target.id: ast.literal_eval(node.value)
         for node in tree.body if isinstance(node, ast.Assign)
         for target in node.targets if isinstance(target, ast.Name) and target.id in names}
assert set(lists) == names
for flat, grouped in [('_common.loop_gate', '_common.loop.loop_gate'),
                      ('_common.skill_registry', '_common.skills.skill_registry')]:
    assert flat in lists['FLAT_SHIMS'] and grouped in lists['PACKAGE_MODULES']
    assert (flat, grouped) in lists['SHIM_MAIN_PAIRS']
    assert importlib.import_module(flat).main is importlib.import_module(grouped).main
    for module in [flat, grouped]:
        assert module.replace('.', '/') + '.py' in lists['CLI_SCRIPTS']
for file in ['_common/README.md', 'tests/README.md', 'tests/test_loop_gate.py', 'tests/test_skill_registry.py']:
    assert Path(file).is_file(), file
PY
```

## Companion files

- `_common/contracts/progress_principles.md`
- `alignment.md`
