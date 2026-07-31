#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# python scripts/pii_gate.py --target report.md --kind introspects --content-file report-source.md
"""Permit artifact writes only to ignored or outside-worktree locations."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from safety import output_is_safe


def arguments() -> argparse.Namespace:
    """Parse requested artifact inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--kind", default="introspects")
    parser.add_argument("--content-file", type=Path)
    return parser.parse_args()


def redirect(kind: str) -> Path:
    """Choose the platform state-directory redirect without creating it."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "hoa"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "hoa"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "hoa"
    return base / kind / timestamp


def redact(text: str) -> str:
    """Remove path-, secret-, and session-shaped values from chat-safe text."""
    text = re.sub(r"(?i)(session[_-]?id\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?<!\w)[A-Za-z]:[\\/][^\s\"']+", "[ABSOLUTE_PATH]", text)
    return re.sub(r"(?<!\w)/(?:[^\s/]+/)+[^\s/]+", "[ABSOLUTE_PATH]", text)


def main() -> int:
    """Refuse unsafe writes or write supplied content to an approved target."""
    args = arguments()
    target = args.target.resolve()
    permitted, reason = output_is_safe(target)
    if not permitted:
        payload = {
            "decision": "refuse",
            "redirect": redact(str(redirect(args.kind) / target.name)),
            "reason": reason,
        }
        print(json.dumps(payload))
        return 1
    if args.content_file is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args.content_file.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps({"decision": "written", "target": redact(target.name)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
