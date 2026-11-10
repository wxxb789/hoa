#!/usr/bin/env python3
"""Check every custom skill's SKILL.md frontmatter.

One implementation of the rule CI used to inline: the file starts with YAML
frontmatter, `name` is a non-empty string equal to the skill directory, and
`description` is a non-empty string. Catalog fields (areas, targets, version,
optional summaries) go through the shared parser, so this command and the
index generator agree on what a valid skill is.

Usage:
    python scripts/check_frontmatter.py

Exit codes: 0 every skill is valid, 1 at least one finding.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

# Keep the check read-only, including helper import caches.
sys.dont_write_bytecode = True
import generate_index as gi

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"


def _frontmatter(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError("missing frontmatter opening ---")
    end = 0
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == "---":
            end = index
            break
    if not end:
        raise ValueError("missing frontmatter closing ---")
    return "".join(lines[1:end])


def check_skill(skill_md: Path) -> list[str]:
    name = skill_md.parent.name
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as error:
        return [f"{skill_md}: cannot read ({error})"]
    try:
        frontmatter = _frontmatter(text)
    except ValueError as error:
        return [f"{skill_md}: {error}"]
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError as error:
        return [f"{skill_md}: invalid YAML frontmatter ({error})"]
    if not isinstance(data, dict):
        return [f"{skill_md}: frontmatter must be a YAML mapping"]
    findings = []
    for key in ("name", "description"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            findings.append(f"{skill_md}: {key} must be a non-empty string")
    if isinstance(data.get("name"), str) and data["name"].strip() != name:
        findings.append(f"{skill_md}: name {data['name']!r} does not match directory {name!r}")
    try:
        gi.parse_skill_metadata(skill_md)
    except ValueError as error:
        findings.append(str(error))
    return findings


def main(argv=None) -> int:
    skills = sorted(path for path in SKILLS.iterdir() if path.is_dir())
    if not skills:
        print(f"check_frontmatter: no skills found in {SKILLS}", file=sys.stderr)
        return 1
    findings = []
    for skill in skills:
        skill_md = skill / "SKILL.md"
        if not skill_md.is_file():
            findings.append(f"{skill_md}: missing")
            continue
        findings.extend(check_skill(skill_md))
    for finding in findings:
        print(finding)
    if findings:
        print(f"check_frontmatter: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print(f"check_frontmatter: {len(skills)} skills OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
