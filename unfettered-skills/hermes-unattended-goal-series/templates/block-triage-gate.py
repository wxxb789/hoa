#!/usr/bin/env python3
"""Condition gate for a cron *agent* job: silent unless the watched series is blocked.

Cron contract (job created with --script <this>.py):
  * print {"wakeAgent": false} and exit 0  -> the agent turn is skipped, zero model calls
  * print a compact digest and exit 0      -> the agent wakes with the block in hand
A non-zero exit is a cron failure incident, not an alert: BOTH branches exit 0.

Copy and patch:
  * the task root / record name / owner unit (or keep the env overrides and set them in a wrapper,
    see hermes-cron: the `script` field carries a bare filename only)
  * the record headings, if the series writes its block record in another shape
  * RE_ALERT_SECONDS -- it is the woken lane's retry budget, not a display preference

Test recipe (fixture dir, never the live record): point SERIES_TASK / TRIAGE_STATE / OWNER_UNIT at a
scratch path and assert on stdout text, not on exit code:
    no record                                    -> {"wakeAgent": false}
    fresh record                                 -> digest
    same record again                            -> {"wakeAgent": false}
    same record + window elapsed + unit INACTIVE -> digest   (override OWNER_UNIT: a running unit
                                                              legitimately suppresses this branch)
    changed record content                       -> digest
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import time

HOME = pathlib.Path(os.path.expanduser("~"))
TASK = pathlib.Path(os.environ.get("SERIES_TASK", HOME / "claw/tasks/<date>/<slug>"))
RECORD = pathlib.Path(os.environ.get("SERIES_RECORD", TASK / "BLOCKED.md"))
STATE = pathlib.Path(
    os.environ.get("TRIAGE_STATE", HOME / ".hermes/cache/series-triage-state.json")
)
UNIT = os.environ.get("OWNER_UNIT", "")
RE_ALERT_SECONDS = int(os.environ.get("TRIAGE_WINDOW_SECONDS", 6 * 3600))
SILENT = '{"wakeAgent": false}'


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE)  # atomic: a half-written state file would re-alert or mute forever


def unit_active() -> bool:
    """Whether the unit that owns the work is running: a live owner means a stale record."""
    if not UNIT:
        return False
    return subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", UNIT],
        capture_output=True,
    ).returncode == 0


def digest(record: str) -> str:
    return hashlib.sha256(record.encode("utf-8", "replace")).hexdigest()[:16]


def field(text: str, label: str) -> str:
    """Read one `**Label:** value` line; absent labels are empty, not an error."""
    m = re.search(rf"^\*\*{label}:\*\*\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def parse(record: str) -> dict:
    head = re.search(
        r"^#\s*BLOCKED\s*[—-]\s*goal\s*(\S+?),\s*stage\s*(\S+)", record, re.MULTILINE
    )
    return {
        "goal": head.group(1) if head else "?",
        "stage": head.group(2) if head else "?",
        "reason": field(record, "Reason")[:400],
        "when": field(record, "When"),
        "log": field(record, "Log").strip("`"),
    }


def main() -> int:
    # 1. no record -> silent (a resolved block must go quiet without anyone clearing state)
    if not RECORD.exists():
        print(SILENT)
        return 0

    text = RECORD.read_text(encoding="utf-8", errors="replace")
    sig = digest(text)
    last = load_state()
    same = last.get("hash") == sig
    fresh = (time.time() - float(last.get("woken_at") or 0)) < RE_ALERT_SECONDS
    live = unit_active()

    # 2. same block inside the window -> silent; 3. live owner -> the record is already consumed
    if same and (fresh or live):
        print(SILENT)
        return 0

    info = parse(text)
    save_state({"hash": sig, "woken_at": time.time()})
    print("the watched series is BLOCKED -- triage this block, do not report it")
    print(f"- goal {info['goal']} / stage {info['stage']}, blocked at: {info['when']}")
    print(f"- reason: {info['reason']}")
    print(f"- record: {RECORD}")
    print(f"- log: {info['log']}")
    print(f"- owner unit active: {str(live).lower()}")
    print(f"- block hash (dedupe key): {sig}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
