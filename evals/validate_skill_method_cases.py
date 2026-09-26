#!/usr/bin/env python3
"""Validate the reusable skill-method scenarios before they are judged by an agent.

This checks the fixture contract only. It does not grade skill behavior.
Run: python evals/validate_skill_method_cases.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "evals" / "skill-method-cases.json"
REQUIRED = {"id", "skill", "prompt", "expected_mode", "must_hold", "must_not_hold"}


def validate() -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(CASES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"unreadable or invalid fixture: {exc}"]
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list) or not data["cases"]:
        return ["fixture must contain a non-empty cases array"]

    seen: set[str] = set()
    for index, case in enumerate(data["cases"]):
        where = f"case[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{where}: expected object")
            continue
        missing = REQUIRED - case.keys()
        if missing:
            errors.append(f"{where}: missing fields {sorted(missing)}")
            continue
        for key in ("id", "skill", "prompt", "expected_mode"):
            if not isinstance(case[key], str) or not case[key].strip():
                errors.append(f"{where}: {key} must be a non-empty string")
        identifier = case["id"]
        if isinstance(identifier, str):
            if identifier in seen:
                errors.append(f"{where}: duplicate id {identifier!r}")
            seen.add(identifier)
        skill = case["skill"]
        if isinstance(skill, str):
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill) or not (
                ROOT / "skills" / skill / "SKILL.md"
            ).is_file():
                errors.append(f"{where}: unknown skill {skill!r}")
        for key in ("must_hold", "must_not_hold"):
            value = case[key]
            if not isinstance(value, list) or not value or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                errors.append(f"{where}: {key} must be a non-empty list of non-empty strings")
        files = case.get("setup_files", [])
        if not isinstance(files, list):
            errors.append(f"{where}: setup_files must be an array")
            continue
        setup_paths: set[str] = set()
        for file in files:
            if not isinstance(file, dict) or not isinstance(file.get("content"), str):
                errors.append(f"{where}: each setup file needs path and string content")
                continue
            path = file.get("path")
            if not isinstance(path, str) or not path:
                errors.append(f"{where}: setup path must stay inside a disposable workspace")
                continue
            posix, windows = PurePosixPath(path), PureWindowsPath(path)
            parts = path.split("/")
            canonical = posix.as_posix().casefold()
            if ("\\" in path or ":" in path or posix.is_absolute() or windows.drive
                    or any(part in ("", ".", "..") for part in parts)
                    or canonical in setup_paths):
                errors.append(f"{where}: setup path must be unique and stay inside a disposable workspace")
            setup_paths.add(canonical)
    return errors


def main() -> int:
    errors = validate()
    for error in errors:
        print(f"skill-method cases: {error}", file=sys.stderr)
    if errors:
        return 1
    print("PASS: skill-method cases have valid rubrics, skill targets, and safe setup paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
