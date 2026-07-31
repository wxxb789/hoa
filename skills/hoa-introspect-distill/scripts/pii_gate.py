#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# ─── How to run ───
# python scripts/pii_gate.py path/to/proposed-rule-or-config
"""Prove whether a non-skill output path is safe to write without tracking it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from safety import output_is_safe


def main(arguments: list[str]) -> int:
    """Print a refusal/allow decision and never write or stage the target."""
    if len(arguments) != 1:
        print(json.dumps({"allowed": False, "reason": "expected one target path"}))
        return 2
    allowed, reason = output_is_safe(Path(arguments[0]))
    print(json.dumps({"allowed": allowed, "reason": reason}))
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
