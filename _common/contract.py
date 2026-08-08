#!/usr/bin/env python3
"""contract — the machine-readable methodology contract (single source of truth).

The enforcement core is Python; the runtime is TypeScript. Every constant they
must agree on (enums, ledger paths, role policy, note caps, cadences) is
emitted HERE, from the live Python modules — the TS side asserts conformance
in its test suite, so a mirrored constant cannot drift silently.

USAGE
    python _common/contract.py manifest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common.ledgers import admission, claims_database, error_database  # noqa: E402
from _common.ledgers import ledger_common  # noqa: E402
from _common.ledgers import knowledge_database, result_database  # noqa: E402
from _common.loop import loop_gate, loop_policy  # noqa: E402

LEDGER_FILES = {
    "error": "trials.jsonl",
    "result": "results.jsonl",
    "knowledge": "nodes.jsonl",
    "claim": "entries.jsonl",
}


def manifest() -> dict:
    return {
        "contract_version": 1,
        "delegation": {
            "env_var": admission.ROLE_ENV_VAR,
            "allowed_roles": list(admission.ROLE_ENV_ALLOWED),
            "policy_file": admission.POLICY_FILE,
        },
        "ledgers": {
            db: {
                "dir": f"results/ledgers/{db}",
                "legacy_dir": f"{db}-database",
                "file": fname,
            } for db, fname in LEDGER_FILES.items()
        },
        "result": {
            "statuses": list(result_database.STATUSES),
            "progress_statuses": list(result_database.PROGRESS_STATUSES),
            "gate_progress_statuses": list(result_database.GATE_PROGRESS_STATUSES),
            "evidence_types": list(result_database.EVIDENCE_TYPES),
            "verdicts": list(result_database.VERDICTS),
        },
        "knowledge": {
            "statuses": list(knowledge_database.STATUSES),
            "exist_statuses": list(knowledge_database.EXIST_STATUSES),
            "domains": list(knowledge_database.DOMAINS),
        },
        "claims": {
            "kinds": list(claims_database.KINDS),
            "statuses_by_kind": {k: list(v) for k, v in claims_database.STATUSES_BY_KIND.items()},
        },
        "error": {
            "pass_fail": ["pass", "fail", "crash", "partial", "amended"],
        },
        "runtime": {
            "env_var": "CHANDRA_RUNTIME",
            "default_prefix": "/tmp/chandra",
        },
        "notes": {
            "research_state_cap_bytes": 10240,
            "nodal_window": 10,
        },
        "cadence": {
            "digest_window_threshold": 5,
            "paper_refresh_every": loop_policy.PAPER_REFRESH_EVERY,
            "no_progress_limit": loop_gate.DEFAULT_NO_PROGRESS_LIMIT,
            "default_packet_size": 4,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args[:1] in (["--help"], ["-h"]):
        print("usage: contract.py manifest | verify-chains [--repo-root R]\n\nEmit the machine-readable methodology contract as JSON.")
        return 0
    if args[:1] == ["manifest"] or not args:
        print(json.dumps(manifest(), indent=2))
        return 0
    if args[:1] == ["verify-chains"]:
        root = args[args.index("--repo-root") + 1] if "--repo-root" in args else "."
        report = ledger_common.verify_all_chains(root)
        print(json.dumps(report))
        return 0 if report["ok"] else 1
    print("usage: contract.py manifest | verify-chains [--repo-root R]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
