#!/usr/bin/env python3
"""Check every `../<name>/` reference that leaves a skill directory.

A parent chains to a sibling skill with a path relative to its own file, e.g.
`Read ../<child>/SKILL.md`. Each such reference in a skill's `SKILL.md` or
`references/**/*.md` is resolved lexically against the file that holds it:

- a path that stays inside the skill is ignored, unless it lands on a missing
  `<name>/` while `skills/<name>` is a skill: that sibling link was written
  with too few `../` for its own file's depth (`../../<name>/` from
  `references/`, `../../../<name>/` from `references/phases/`) -- an error;
- a path that lands in `skills/<name>/` must name an existing sibling skill and,
  unless it carries a `<placeholder>` or glob, an existing file or directory
  there (`#anchor` stripped) — otherwise an error;
- a path that climbs above `skills/` is not a sibling link and is ignored.

Usage:
    python scripts/check_skill_links.py

Exit codes: 0 every sibling reference resolves, 1 at least one error.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

# `../` runs that start a path token (not `x/../`, not the tail of `...`), then a
# name segment and its trailing slash. The rest stops at Markdown/quote delimiters.
REFERENCE = re.compile(
    r"(?<![\w./-])((?:\.\./)+)([A-Za-z0-9][A-Za-z0-9._-]*)/([^\s)\]`'\"#]*)")
PLACEHOLDER = re.compile(r"[<>*]|\.\.\.")


@dataclass(frozen=True)
class Reference:
    source: Path   # file holding the reference
    line: int
    text: str      # the reference as written
    scope: str     # "sibling" or "skill-relative" (sibling written from the skill dir)
    name: str      # sibling skill name
    rest: str      # path inside the sibling, anchor stripped


def skill_files(skill_dir: Path) -> list[Path]:
    """The files whose `../` references count: SKILL.md and references/**/*.md."""
    files = [skill_dir / "SKILL.md"] if (skill_dir / "SKILL.md").is_file() else []
    references = skill_dir / "references"
    if references.is_dir():
        files.extend(sorted(path for path in references.rglob("*.md") if path.is_file()))
    return files


def references(skill_dir: Path) -> list[Reference]:
    """Every `../` reference that leaves `skill_dir`, resolved lexically."""
    found = []
    for path in skill_files(skill_dir):
        depth = len(path.relative_to(skill_dir).parts) - 1
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for match in REFERENCE.finditer(line):
                ups = match.group(1).count("../")
                name = match.group(2)
                if ups <= depth:
                    if (not (path.parents[ups] / name).exists()
                            and (skill_dir.parent / name / "SKILL.md").is_file()):
                        found.append(Reference(
                            source=path, line=number, text=match.group(0).rstrip(".,;:"),
                            scope="skill-relative", name=name, rest=match.group(3).rstrip(".,;:")))
                    continue
                if ups == depth + 1:
                    found.append(Reference(
                        source=path, line=number, text=match.group(0).rstrip(".,;:"),
                        scope="sibling", name=name, rest=match.group(3).rstrip(".,;:")))
    return found


def siblings(skill_dir: Path) -> set[str]:
    """Names of the sibling skills `skill_dir` references through `../`."""
    return {ref.name for ref in references(skill_dir) if ref.scope == "sibling"}


def check(skills_root: Path) -> list[str]:
    """Return the errors for every skill under skills_root."""
    errors = []
    for skill_dir in sorted(path for path in skills_root.iterdir()
                            if path.is_dir() and not path.name.startswith(".")):
        for ref in references(skill_dir):
            where = f"{ref.source.relative_to(skills_root.parent).as_posix()}:{ref.line}"
            if ref.scope == "skill-relative":
                errors.append(f"{where}: {ref.text} resolves inside the skill; paths are relative "
                              f"to the file holding them, so the sibling is "
                              f"{'../' * (len(ref.source.relative_to(skill_dir).parts))}{ref.name}/")
                continue
            sibling = skills_root / ref.name
            if not (sibling / "SKILL.md").is_file():
                errors.append(f"{where}: {ref.text} names no sibling skill "
                              f"(expected skills/{ref.name}/SKILL.md)")
                continue
            if ref.rest and not PLACEHOLDER.search(ref.rest):
                target = sibling.joinpath(*PurePosixPath(ref.rest).parts)
                if not target.exists():
                    errors.append(f"{where}: {ref.text} does not exist in skills/{ref.name}/ "
                                  f"(got {ref.rest!r})")
    return errors


def main(argv=None) -> int:
    if not SKILLS.is_dir():
        print(f"check_skill_links: no skills directory at {SKILLS}", file=sys.stderr)
        return 1
    errors = check(SKILLS)
    for error in errors:
        print(error)
    if errors:
        print(f"check_skill_links: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print("check_skill_links: sibling references OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
