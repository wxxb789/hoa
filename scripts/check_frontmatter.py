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

Layout: every curated skill lives at `skills/<category>/<name>/SKILL.md`; the
category allowlist is exact, category and package directories must be real
directories, every package candidate needs a regular `SKILL.md`, names must be
unique across categories, and a misplaced `SKILL.md` (root, flat, or deeper)
is an error even when valid packages exist.

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
import skill_paths

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
CATEGORIES = ("engineering", "productivity", "research-writing", "skill-authoring", "hermes")
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


def _alias(path: Path) -> bool:
    """A symlink or NTFS junction that a discovery client may follow."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def layout_findings() -> tuple[list[str], list[Path]]:
    """Curated-layout diagnostics plus the package directories to inspect."""
    findings: list[str] = []
    if not SKILLS.is_dir():
        return [f"{SKILLS}: missing skills directory"], []
    if _alias(SKILLS):
        return [f"{SKILLS}: skills directory must be a real directory, not a symlink"], []
    for entry in sorted(SKILLS.iterdir()):
        if _alias(entry):
            if entry.name in CATEGORIES:
                findings.append(f"{entry}: category directory must be a real directory, "
                                f"not a symlink")
            else:
                findings.append(f"{entry}: unknown skill category; "
                                f"expected one of {', '.join(CATEGORIES)}")
            continue
        if not entry.is_dir():
            continue
        if entry.name not in CATEGORIES:
            findings.append(f"{entry}: unknown skill category; "
                            f"expected one of {', '.join(CATEGORIES)}")
            continue
        for package in sorted(entry.iterdir()):
            if _alias(package):
                findings.append(f"{package}: skill package must be a real directory, "
                                f"not a symlink")
    packages = skill_paths.skill_dirs(SKILLS)
    if not packages:
        findings.append(f"{SKILLS}: no skill packages found")
    names: dict[str, list[Path]] = {}
    for package in packages:
        names.setdefault(package.name, []).append(package)
    for name in sorted(names):
        if len(names[name]) > 1:
            paths = ", ".join(path.as_posix() for path in names[name])
            findings.append(f"duplicate skill directory name {name!r}: {paths}")
    for skill_md in sorted(SKILLS.rglob("SKILL.md")):
        parts = skill_md.relative_to(SKILLS).parts
        if len(parts) == 3 and parts[0] in CATEGORIES:
            continue
        findings.append(f"{skill_md}: misplaced SKILL.md; a skill lives at "
                        f"skills/<category>/<name>/SKILL.md")
    return findings, packages


def main(argv=None) -> int:
    if not SKILLS.is_dir():
        print(f"check_frontmatter: no skills directory at {SKILLS}", file=sys.stderr)
        return 1
    findings, packages = layout_findings()
    skills = 0
    for package in packages:
        skill_md = package / "SKILL.md"
        if _alias(skill_md):
            findings.append(f"{skill_md}: must be a regular file")
            continue
        if not skill_md.is_file():
            findings.append(f"{skill_md}: missing")
            continue
        skills += 1
        findings.extend(check_skill(skill_md))
    for finding in findings:
        print(finding)
    if findings:
        print(f"check_frontmatter: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print(f"check_frontmatter: {skills} skills OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
