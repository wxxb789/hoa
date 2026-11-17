#!/usr/bin/env python3
"""Project VERSION and per-skill revision gates.

Usage:
    python scripts/version.py bump              # patch by default; prints the new VERSION
    python scripts/version.py bump minor        # or major; resets lower components
    python scripts/version.py check-bump        # PR gate: VERSION is origin/main's patch + 1
    python scripts/version.py check-revisions   # PR gate: changed skills bump metadata.revision

VERSION is the only project version and is never copied into skills. Each
skills/<name>/SKILL.md carries `metadata.revision`, an integer string counting
that skill's own iterations: a pull request bumps it only for the skill
directories it changes. A new skill starts at "1"; a deleted skill is ignored.
A file moved between skills counts as a change to both.
Both gates read origin/main from the local repository; fetch it first.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.dont_write_bytecode = True
import skill_metadata as sm

ROOT = Path(__file__).resolve().parent.parent
VERSION = ROOT / "VERSION"
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def _parse(value: str, source: str) -> tuple[int, int, int]:
    if SEMVER.fullmatch(value) is None:
        raise ValueError(f"invalid stable numeric version {value!r} in {source}")
    major, minor, patch = (int(part) for part in value.split("."))
    return major, minor, patch


def _git(*arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], text=True,
                            encoding="utf-8", capture_output=True)
    if result.returncode:
        detail = result.stderr.strip() or f"git exited {result.returncode}"
        raise ValueError(f"git {' '.join(arguments)} failed ({detail}); "
                         "fetch origin main and retry")
    return result.stdout


def bump(part: str) -> str:
    text = VERSION.read_text(encoding="utf-8")
    components = list(_parse(text.strip(), "VERSION"))
    index = ("major", "minor", "patch").index(part)
    components[index] += 1
    components[index + 1:] = [0] * (2 - index)
    release = ".".join(str(value) for value in components)
    VERSION.write_bytes((release + "\n").encode("utf-8"))
    return release


def check_bump() -> str:
    """Require VERSION to be exactly origin/main's patch plus one."""
    current = VERSION.read_text(encoding="utf-8").strip()
    base = _git("show", "origin/main:VERSION").strip()
    major, minor, patch = _parse(base, "origin/main:VERSION")
    expected = f"{major}.{minor}.{patch + 1}"
    _parse(current, "VERSION")
    if current != expected:
        raise ValueError(f"VERSION is {current}, origin/main is {base}: every pull request "
                         f"bumps the patch exactly once (expected {expected}); "
                         "rebase onto origin/main and run python scripts/version.py bump")
    return current


def _base_revision(base: str, relative: str) -> int | None:
    """The skill's revision at base; None when the skill did not exist there."""
    try:
        text = _git("show", f"{base}:{relative}")
    except ValueError:
        return None
    # Not catalog_metadata: it rejects the retired `version` key a base may still carry.
    frontmatter, _ = sm._frontmatter(text, Path(f"{base[:12]}:{relative}"))
    metadata = (yaml.safe_load(frontmatter) or {}).get("metadata") or {}
    # A base that predates metadata.revision counts as revision 0.
    return int(metadata.get("revision", 0))


def check_revisions() -> list[str]:
    """Require every skill changed since the merge base to raise its revision."""
    base = _git("merge-base", "HEAD", "origin/main").strip()
    paths = _git("diff", "--name-only", "--no-renames", base, "--", "skills/").splitlines()
    paths += _git("ls-files", "--others", "--exclude-standard", "--", "skills/").splitlines()
    names = sorted({path.split("/")[1] for path in paths if path.count("/") >= 2})
    names = [name for name in names if (ROOT / "skills" / name / "SKILL.md").is_file()]
    findings = []
    for name in names:
        relative = f"skills/{name}/SKILL.md"
        skill_md = ROOT / relative
        current = int(sm.catalog_metadata(skill_md.read_text(encoding="utf-8"),
                                          skill_md)["revision"])
        before = _base_revision(base, relative)
        if before is None and current != 1:
            findings.append(f"{relative}: new skill must start at metadata.revision \"1\", "
                            f"got \"{current}\"")
        elif before is not None and current <= before:
            findings.append(f"{relative}: changed since {base[:12]} but metadata.revision "
                            f"\"{current}\" is not above the base's \"{before}\"; "
                            f"set it to \"{before + 1}\"")
    if findings:
        raise ValueError("\n".join(findings))
    return names


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    bump_parser = commands.add_parser("bump", help="increment VERSION")
    bump_parser.add_argument("part", choices=("patch", "minor", "major"), nargs="?",
                             default="patch")
    commands.add_parser("check-bump", help="fail unless VERSION is origin/main's patch + 1")
    commands.add_parser("check-revisions",
                        help="fail unless every changed skill raises metadata.revision")
    args = parser.parse_args(argv)
    try:
        if args.command == "bump":
            print(bump(args.part))
        elif args.command == "check-bump":
            print(check_bump())
        else:
            names = check_revisions()
            print(f"check-revisions: {len(names)} changed skill(s) OK")
    except (OSError, ValueError) as error:
        print(f"version: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
