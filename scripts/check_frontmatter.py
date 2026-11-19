#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml>=6"]
# ///
"""Check every custom skill's SKILL.md frontmatter.

One implementation of the rule CI used to inline: the file starts with YAML
frontmatter, `name` is a non-empty string equal to the skill directory, and
`description` is a non-empty string. Catalog fields (areas, targets, version,
optional summaries) go through the shared parser, so this command and the
index generator agree on what a valid skill is.

Visibility: `disable-model-invocation` (kebab-case only) must be a YAML boolean,
and it must agree with `agents/openai.yaml` `policy.allow_implicit_invocation`:
a hidden skill ships that key as `false`, and a `false` key needs the flag.
A model-visible description over 350 characters is an error: every host lists visible
descriptions in one shared, size-limited catalog. A hidden skill is not listed, so only
the 1024-character agentskills spec cap applies to it.

Usage:
    uv run scripts/check_frontmatter.py

Exit codes: 0 every skill is valid, 1 at least one finding.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# Keep the check read-only, including helper import caches.
sys.dont_write_bytecode = True
import generate_index as gi

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
HIDDEN = "disable-model-invocation"
DESCRIPTION_MAX = 1024
VISIBLE_DESCRIPTION_MAX = 350


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


def _visibility(skill_md: Path, data: dict) -> list[str]:
    findings = []
    for key in data:
        if (isinstance(key, str) and key != HIDDEN
                and re.sub(r"[-_]", "", key).lower() == HIDDEN.replace("-", "")):
            findings.append(f"{skill_md}: {key!r} is misspelled; hosts read only "
                            f"{HIDDEN!r} (DSH drops the skill)")
    hidden = data.get(HIDDEN)
    if HIDDEN in data and not isinstance(hidden, bool):
        findings.append(f"{skill_md}: {HIDDEN} must be a YAML boolean, got {hidden!r}")
    path = skill_md.parent / "agents" / "openai.yaml"
    implicit = None
    if path.is_file():
        try:
            openai = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            return findings + [f"{path}: invalid YAML ({error})"]
        policy = openai.get("policy") if isinstance(openai, dict) else None
        implicit = policy.get("allow_implicit_invocation") if isinstance(policy, dict) else None
        if implicit is not None and not isinstance(implicit, bool):
            return findings + [f"{path}: policy.allow_implicit_invocation must be a boolean, "
                               f"got {implicit!r}"]
    if hidden is True and implicit is not False:
        findings.append(f"{skill_md}: {HIDDEN}: true needs agents/openai.yaml with "
                        f"policy.allow_implicit_invocation: false (Codex ignores the flag)")
    elif implicit is False and hidden is not True:
        findings.append(f"{skill_md}: agents/openai.yaml sets "
                        f"policy.allow_implicit_invocation: false; add {HIDDEN}: true")
    return findings


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
    description = data.get("description")
    cap = DESCRIPTION_MAX if data.get(HIDDEN) is True else VISIBLE_DESCRIPTION_MAX
    if isinstance(description, str) and len(description) > cap:
        kind = "hidden" if cap == DESCRIPTION_MAX else "model-visible"
        findings.append(f"{skill_md}: description is {len(description)} characters; "
                        f"cap for a {kind} skill is {cap}")
    findings.extend(_visibility(skill_md, data))
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
