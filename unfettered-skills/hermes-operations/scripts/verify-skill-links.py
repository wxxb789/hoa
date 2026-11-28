#!/usr/bin/env python3
"""Static checks for a skill directory: frontmatter, prompt-budget description, links, anchors.

Run after any restructure of a skill (splitting, merging case files, renaming references):

    python3 scripts/verify-skill-links.py ~/.hermes/skills/devops/hermes-cron
    python3 scripts/verify-skill-links.py ~/.hermes/skills/devops/hermes-*

Checks, per skill:
  1. SKILL.md has frontmatter; `name` matches the directory; `description` <= 60 chars (the
     system-prompt index clips at that width, so a longer one loses its trigger).
  2. Every `references/x`, `scripts/x`, `templates/x` named in backticks exists on disk.
  3. Every `cases.md#anchor` pointer resolves to a `## heading` slug in that skill's cases.md.
  4. No dated case files (`references/YYYY-*.md`): history belongs in `cases.md`.

Stdlib only, so it runs under the bare toolchain interpreter. Exit 1 when anything fails.
"""
from __future__ import annotations

import glob
import os
import re
import sys

BUDGET = 60
SUPPORT = ("references", "scripts", "templates", "assets")


def slug(text: str) -> str:
    """GitHub-style heading anchor: lowercase, drop punctuation, spaces to hyphens."""
    text = text.lower().replace("`", "")
    text = re.sub(r"[^a-z0-9 \-_]", "", text)
    return re.sub(r"\s+", "-", text.strip())


def frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML-subset reader for the two fields that matter here."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        km = re.match(r"^(name|description|version|author|license):\s*(.*)$", line)
        if km:
            out[km.group(1)] = km.group(2).strip().strip("'\"")
    return out


def check(skill_dir: str) -> list[str]:
    problems: list[str] = []
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_md):
        return [f"{skill_dir}: no SKILL.md"]
    text = open(skill_md, encoding="utf-8").read()
    meta = frontmatter(text)
    if not meta:
        problems.append("SKILL.md: missing frontmatter")
    else:
        if meta.get("name") != os.path.basename(os.path.normpath(skill_dir)):
            problems.append(f"frontmatter name {meta.get('name')!r} != directory name")
        desc = meta.get("description", "")
        if len(desc) > BUDGET:
            problems.append(f"description is {len(desc)} chars (> {BUDGET}) — the index clips it")

    have = {os.path.basename(p) for d in SUPPORT
            for p in glob.glob(os.path.join(skill_dir, d, "*"))}
    for ref in sorted(set(re.findall(r"`(?:references|scripts|templates|assets)/([A-Za-z0-9._-]+)`", text))):
        if ref not in have:
            problems.append(f"SKILL.md points at missing support file {ref}")

    cases = os.path.join(skill_dir, "references", "cases.md")
    anchors = set()
    if os.path.exists(cases):
        anchors = {slug(h) for h in re.findall(r"^## (.+)$", open(cases, encoding="utf-8").read(), re.M)}
    for md in glob.glob(os.path.join(skill_dir, "**", "*.md"), recursive=True):
        body = open(md, encoding="utf-8").read()
        rel = os.path.relpath(md, skill_dir)
        for anchor in sorted(set(re.findall(r"cases\.md#([a-z0-9-]+)", body))):
            if anchor not in anchors:
                problems.append(f"{rel}: dangling cases.md#{anchor}")
        for ref in sorted(set(re.findall(r"`(?:references|scripts|templates)/([A-Za-z0-9._-]+)`", body))):
            if ref not in have:
                problems.append(f"{rel}: points at missing support file {ref}")

    for dated in sorted(glob.glob(os.path.join(skill_dir, "references", "[12][0-9][0-9][0-9]-*.md"))):
        problems.append(f"{os.path.basename(dated)}: dated case file — merge into references/cases.md")
    return problems


def main(argv: list[str]) -> int:
    targets: list[str] = []
    hermes_root = os.path.expanduser(os.environ.get("HERMES_ROOT", os.environ.get("HERMES_HOME", "~/.hermes")))
    for arg in argv or [os.path.join(hermes_root, "skills/devops/hermes-*")]:
        targets.extend(sorted(glob.glob(os.path.expanduser(arg))) or [arg])
    failures = 0
    for target in targets:
        problems = check(target)
        print(f"{'OK  ' if not problems else 'FAIL'} {os.path.basename(os.path.normpath(target))}")
        for p in problems:
            print("      -", p)
        failures += bool(problems)
    print(f"\n{len(targets)} skill(s), {failures} with problems")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
