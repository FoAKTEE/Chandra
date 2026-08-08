"""Path bootstrap for the infra test suite.

The `_common` package is imported by its fully-qualified path; put the repo root
on `sys.path` so `from _common.ledgers import ...` resolves regardless of the
directory pytest is invoked from. Ledger tests write only under `tmp_path`, so
the real `*-database/` ledgers are never touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
