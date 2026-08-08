"""Compatibility wrapper for `_common.ledgers.ledger_common`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common.ledgers.ledger_common import *  # noqa: F401,F403
