#!/usr/bin/env python3
"""Compatibility wrapper for `_common.loop.loop_gate`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common.loop.loop_gate import *  # noqa: F401,F403
from _common.loop.loop_gate import main


if __name__ == "__main__":
    raise SystemExit(main())
