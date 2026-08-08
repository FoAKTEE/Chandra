#!/usr/bin/env python3
"""Compatibility wrapper for `_common.ledgers.error_database`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common.ledgers.error_database import *  # noqa: F401,F403
from _common.ledgers.error_database import main


if __name__ == "__main__":
    raise SystemExit(main())
