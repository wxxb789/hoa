#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# ─── How to run ───
# python scripts/validate_skill.py path/to/SKILL.md
"""Validate the portable structural contract of a SKILL.md file."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

FRONTMATTER_DELIMITER: Final = "---"
REQUIRED_FIELDS: Final = ("name", "description")


def frontmatter_lines(lines: list[str]) -> list[str] | None:
    """Return frontmatter lines when the document starts with a closed YAML block."""
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER_DELIMITER:
            return lines[1:index]
    return None


def errors_for(path: Path) -> list[str]:
    """Return all structural errors found in one skill document."""
    errors: list[str] = []
    if path.name != "SKILL.md":
        errors.append("file must be named SKILL.md")
    if not path.is_file():
        return [*errors, "file does not exist"]

    lines = path.read_text(encoding="utf-8").splitlines()
    frontmatter = frontmatter_lines(lines)
    if frontmatter is None:
        return [*errors, "missing closed YAML frontmatter at file start"]

    fields: dict[str, str] = {}
    empty_fields: set[str] = set()
    for line in frontmatter:
        key, separator, value = line.partition(":")
        normalized_key = key.strip()
        if separator and normalized_key in REQUIRED_FIELDS:
            if value.strip():
                fields[normalized_key] = value.strip()
            else:
                empty_fields.add(normalized_key)
    for field in REQUIRED_FIELDS:
        if field in empty_fields:
            errors.append(f"empty frontmatter field: {field}")
        if field not in fields:
            errors.append(f"missing non-empty frontmatter field: {field}")

    body_start = len(frontmatter) + 2
    body = lines[body_start:]
    in_fenced_code_block = False
    has_heading = False
    for line in body:
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fenced_code_block = not in_fenced_code_block
        elif not in_fenced_code_block and line.startswith("# "):
            has_heading = True
    if not has_heading:
        errors.append("body must contain a level-one heading")
    if len(lines) > 500:
        errors.append("SKILL.md exceeds 500 lines")
    return errors


def main(arguments: list[str]) -> int:
    """Print machine-readable validation results."""
    if len(arguments) != 1:
        print(json.dumps({"valid": False, "errors": ["expected one SKILL.md path"]}))
        return 2
    path = Path(arguments[0])
    errors = errors_for(path)
    print(json.dumps({"path": str(path), "valid": not errors, "errors": errors}))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
