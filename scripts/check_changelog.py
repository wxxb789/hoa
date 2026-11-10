#!/usr/bin/env python3
"""Require a CHANGELOG.md entry whenever VERSION changed in this increment.

The comparison is the merge base of `--base` and `HEAD` against the working
tree, so the check works in CI and before committing. It only enforces one
rule: a changed VERSION must come with a changed CHANGELOG.md.

Usage:
    python scripts/check_changelog.py --base origin/main

Exit codes: 0 rule satisfied, 1 VERSION changed without a changelog entry,
2 git could not answer (unknown base or not a repository).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Keep the check read-only, including helper import caches.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
TRACKED = ("VERSION", "CHANGELOG.md")


def _git(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _detail(result: subprocess.CompletedProcess) -> str:
    return result.stderr.strip() or result.stdout.strip() or f"git exited {result.returncode}"


def changed_paths(base: str) -> set[str]:
    """Files among TRACKED that differ from the merge base of base and HEAD."""
    result = _git("merge-base", base, "HEAD")
    if result.returncode:
        raise ValueError(f"cannot resolve {base} against HEAD ({_detail(result)}); "
                         "fetch the base ref first")
    merge_base = result.stdout.strip()
    result = _git("diff", "--name-only", merge_base, "--", *TRACKED)
    if result.returncode:
        raise ValueError(f"cannot diff against {base} ({_detail(result)})")
    return set(result.stdout.splitlines())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main",
                        help="git ref of the base branch (default: origin/main)")
    args = parser.parse_args(argv)

    try:
        changed = changed_paths(args.base)
    except ValueError as error:
        print(f"check_changelog: {error}", file=sys.stderr)
        return 2

    version_changed = "VERSION" in changed
    changelog_changed = "CHANGELOG.md" in changed
    if version_changed and not changelog_changed:
        print("check_changelog: VERSION changed but CHANGELOG.md did not; "
              "add a changelog entry for this increment", file=sys.stderr)
        return 1
    if version_changed:
        print("check_changelog: VERSION and CHANGELOG.md both changed")
    else:
        print("check_changelog: VERSION unchanged; no changelog entry required")
    return 0


if __name__ == "__main__":
    sys.exit(main())
