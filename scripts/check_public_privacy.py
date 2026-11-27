#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml>=6"]
# ///
"""Repo-wide public privacy gate for curated surfaces.

Reuses the deterministic sensitive-content signatures from `check_unfettered.py`
(private keys, tokens, corporate feeds, home paths, emails, private IPs) and
applies them across the public repository (`skills/`, `docs/`, `prompts/`,
`rules/`, `scripts/`, `src/`, `paseo-plugins/`, `evals/`, top-level files).

Known synthetic fixtures (under `evals/tasks/`, `test_*.py`, `*.test.ts*`) and
clearly synthetic placeholder usernames (`ExampleUser`, `operator`, `ops`,
`...`) are exempted so real leaks fail CI without breaking test suites.

Usage:
    uv run scripts/check_public_privacy.py
    uv run scripts/check_public_privacy.py --base origin/main

Exit codes: 0 clean, 1 findings or git error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from check_unfettered import CheckError, git, scan_line  # noqa: E402

ROOT_DEFAULT = Path(__file__).resolve().parent.parent

# Synthetic fixture paths and test suites that intentionally construct dummy
# addresses or home paths to test redaction/isolation logic.
_EXEMPT_PATH_RE = re.compile(
    r"^(?:"
    r"ref/|"
    r"unfettered-skills/|"
    r"evals/tasks/|"
    r".*/tests?/|"
    r"(?:.*/)?test_[^/]+\.py$|"
    r".*\.test\.[tj]sx?$"
    r")"
)

# Legacy evals/results/ snapshots are exempted from the full worktree scan,
# but newly introduced blobs under evals/results/ ARE scanned by --base.
_WORKTREE_ONLY_EXEMPT_RE = re.compile(r"^evals/results/")

# Clearly synthetic home-path placeholders (e.g. ExampleUser, ..., <trial>/home).
_SYNTHETIC_HOME_RE = re.compile(
    rb"(?:"
    rb"(?i:[A-Za-z]:[\\/]+Users[\\/]+(?:ExampleUser|\.\.\.)(?=$|[\\/\s\"'<>`]))"
    rb"|"
    rb"<trial>/home/"
    rb")"
)


def _is_exempt_path(rel: str, *, include_results: bool = False) -> bool:
    if _EXEMPT_PATH_RE.match(rel) is not None:
        return True
    if not include_results and _WORKTREE_ONLY_EXEMPT_RE.match(rel) is not None:
        return True
    return False


def _scan_bytes(rel: str, data: bytes) -> list[str]:
    findings: list[str] = []
    for lineno, line in enumerate(data.split(b"\n"), start=1):
        for rule, start, end in scan_line(line):
            if rule == "home-path":
                # Check a small window around the match for synthetic placeholders.
                window = line[max(0, start - 8):min(len(line), end + 8)]
                if _SYNTHETIC_HOME_RE.search(window):
                    continue
            findings.append(f"{rel}:{lineno}: {rule}")
    return findings


def scan_worktree(root: Path) -> list[str]:
    out = git(root, "ls-files", "-z").stdout
    rels = [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]
    findings: list[str] = []
    for rel in sorted(rels):
        if _is_exempt_path(rel):
            continue
        path = root / rel
        if not path.is_file():
            continue
        findings.extend(_scan_bytes(rel, path.read_bytes()))
    return findings


def scan_introduced_blobs(root: Path, base: str, head: str = "HEAD") -> list[str]:
    """Scan every blob introduced in commits `base..head` (catches intermediate leaks)."""
    rev = git(root, "rev-list", "--objects", f"{base}..{head}").stdout
    findings: list[str] = []
    seen: set[str] = set()
    for raw in rev.splitlines():
        parts = raw.split(b" ", 1)
        if len(parts) != 2:
            continue
        oid = parts[0].decode("ascii", "replace")
        rel = parts[1].decode("utf-8", "surrogateescape")
        if oid in seen or _is_exempt_path(rel, include_results=True):
            continue
        seen.add(oid)
        kind = git(root, "cat-file", "-t", oid, check=False).stdout.strip()
        if kind != b"blob":
            continue
        data = git(root, "cat-file", "blob", oid).stdout
        findings.extend(_scan_bytes(f"{rel}@{oid[:8]}", data))
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT_DEFAULT)
    ap.add_argument("--base", metavar="REV",
                    help="also scan all blobs introduced in REV..HEAD")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    try:
        findings = scan_worktree(root)
        if args.base:
            findings.extend(scan_introduced_blobs(root, args.base))
    except CheckError as error:
        print(f"check_public_privacy: error: {error}", file=sys.stderr)
        return 1
    for item in findings:
        print(item)
    if findings:
        print(f"check_public_privacy: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print("check_public_privacy: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
