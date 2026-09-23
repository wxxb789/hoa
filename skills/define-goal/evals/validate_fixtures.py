#!/usr/bin/env python3
"""Offline schema check for the define-goal judge fixtures.

cardinality.json / domain-transfer.json are graded by an LLM judge in a fresh
context; this script only validates their structure so a malformed fixture
fails in CI instead of producing a silently ungradeable judge run.

Run: python evals/validate_fixtures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent

REQUIRED_TOP = {"purpose", "procedure", "cases"}
REQUIRED_CASE = {"id", "prompt", "expected_mode", "must_hold", "must_not_hold"}


def validate(name: str) -> list[str]:
    errors: list[str] = []
    path = FIXTURES / name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{name}: unreadable or invalid JSON: {exc}"]

    missing = REQUIRED_TOP - data.keys()
    if missing:
        errors.append(f"{name}: missing top-level keys: {sorted(missing)}")
        return errors
    if not isinstance(data["cases"], list) or not data["cases"]:
        return [f"{name}: cases must be a non-empty list"]

    seen_ids: set[str] = set()
    for i, case in enumerate(data["cases"]):
        where = f"{name}: case[{i}]"
        missing = REQUIRED_CASE - case.keys()
        if missing:
            errors.append(f"{where}: missing keys: {sorted(missing)}")
            continue
        cid = case["id"]
        if cid in seen_ids:
            errors.append(f"{where}: duplicate id {cid!r}")
        seen_ids.add(cid)
        for field in ("prompt", "expected_mode"):
            if not isinstance(case[field], str) or not case[field].strip():
                errors.append(f"{where}: {field} must be a non-empty string")
        for field in ("must_hold", "must_not_hold"):
            value = case[field]
            if (not isinstance(value, list) or not value
                    or not all(isinstance(item, str) and item.strip() for item in value)):
                errors.append(f"{where}: {field} must be a non-empty list of non-empty strings")
    return errors


def main() -> int:
    errors = [e for name in ("cardinality.json", "domain-transfer.json")
              for e in validate(name)]
    if errors:
        for error in errors:
            print(f"validate_fixtures: {error}", file=sys.stderr)
        return 1
    print("PASS: define-goal fixtures are structurally valid "
          "(ids unique, rubric fields non-empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
