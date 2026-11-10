#!/usr/bin/env python3
"""Install this repository's skills into a host skills directory.

The host side is a directory of skill entries (the shape `npx skills` and the
agent runtimes use): `<root>/<name>` should be a symlink to `skills/<name>`
here, or a byte-identical real directory copy. The script never writes in
`--check` mode, never deletes anything, and only creates symlinks in `--link`
mode; a real directory is never replaced.

A host entry is installed when it is either a symlink whose resolved target is
the repository's skill directory or a real directory with the same file set,
file bytes and internal symlink targets. Host entries that do not match a
repository skill are ignored.

Usage:
    python scripts/install_host_skills.py --root <host-skills-dir> --check
    python scripts/install_host_skills.py --root <host-skills-dir> --link

Exit codes: 0 all skills installed (or `--link` needed no change), 1 findings
or refusals (each named on stdout), 2 usage or repository-state error.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

# Keep --check read-only, including helper import caches.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"


def repo_skills(skills_root: Path) -> list[Path]:
    """Every non-hidden skill directory, sorted by name."""
    skills = []
    for entry in sorted(skills_root.iterdir()):
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        if not (entry / "SKILL.md").is_file():
            raise ValueError(f"skill directory without SKILL.md: {entry}")
        skills.append(entry)
    if not skills:
        raise ValueError(f"no skills found in {skills_root}")
    return skills


def _tree(root: Path) -> dict[str, tuple[str, str]]:
    """Relative path -> (kind, content); symlinks compare by target, files by bytes."""
    entries = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries[relative] = ("link", os.readlink(path))
        elif path.is_file():
            entries[relative] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
        elif path.is_dir():
            entries[relative] = ("dir", "")
    return entries


def _difference(host: Path, repo: Path) -> str:
    """Name the first few differences, relative to the repository skill."""
    left, right = _tree(host), _tree(repo)
    missing = sorted(set(right) - set(left))
    extra = sorted(set(left) - set(right))
    changed = sorted(key for key in set(left) & set(right) if left[key] != right[key])
    parts = []
    if missing:
        parts.append("missing " + ", ".join(missing[:3]))
    if extra:
        parts.append("extra " + ", ".join(extra[:3]))
    if changed:
        parts.append("changed " + ", ".join(changed[:3]))
    return "; ".join(parts) or "tree differs"


def _same_link(entry: Path, repo: Path) -> bool:
    return os.path.realpath(entry) == os.path.realpath(repo)


def _inspect(entry: Path, repo: Path) -> tuple[str, str]:
    """Classify one host entry: ok, absent, drifted, wrong link or blocked path."""
    if entry.is_symlink():
        if _same_link(entry, repo):
            return "ok", ""
        return "wrong", os.readlink(entry)
    if entry.is_dir():
        if _tree(entry) == _tree(repo):
            return "ok", ""
        return "drifted", _difference(entry, repo)
    if entry.exists():
        return "blocked", "not a directory or symlink"
    return "absent", ""


def _replace_link(entry: Path, repo: Path) -> None:
    """Point entry at repo without ever following an existing symlink."""
    staging = entry.with_name(f".{entry.name}.install-{os.getpid()}")
    if staging.is_symlink() or staging.exists():
        staging.unlink()
    os.symlink(str(repo.resolve()), staging)
    try:
        os.replace(staging, entry)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


def check(root: Path, skills: list[Path]) -> int:
    findings = []
    for repo in skills:
        state, detail = _inspect(root / repo.name, repo)
        if state == "absent":
            findings.append(f"absent: {repo.name}")
        elif state == "drifted":
            findings.append(f"drifted: {repo.name} ({detail})")
        elif state in ("wrong", "blocked"):
            findings.append(f"wrongly linked: {repo.name} -> {detail}")
    for finding in findings:
        print(finding)
    if findings:
        print(f"install_host_skills: {len(findings)} of {len(skills)} skills "
              f"are not installed at {root}", file=sys.stderr)
        return 1
    print(f"install_host_skills: all {len(skills)} skills installed at {root}")
    return 0


def link(root: Path, skills: list[Path]) -> int:
    linked = relinked = refused = 0
    for repo in skills:
        entry = root / repo.name
        state, detail = _inspect(entry, repo)
        if state == "ok":
            continue
        if state == "absent":
            _replace_link(entry, repo)
            print(f"linked: {repo.name}")
            linked += 1
        elif state == "wrong":
            _replace_link(entry, repo)
            print(f"relinked: {repo.name} (was -> {detail})")
            relinked += 1
        elif state == "drifted":
            print(f"refused: {repo.name}: real directory at {entry} differs from "
                  f"{repo} ({detail}); replace it yourself")
            refused += 1
        else:
            print(f"refused: {repo.name}: {entry} is not a directory or symlink; "
                  f"left untouched")
            refused += 1
    if refused:
        print(f"install_host_skills: linked {linked}, relinked {relinked}, "
              f"refused {refused} at {root}", file=sys.stderr)
        return 1
    if not linked and not relinked:
        print(f"install_host_skills: nothing to do; all {len(skills)} skills "
              f"installed at {root}")
        return 0
    print(f"install_host_skills: linked {linked}, relinked {relinked} at {root}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path,
                        help="host skills directory to inspect or link into")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="read-only verification; exit 1 on any finding")
    mode.add_argument("--link", action="store_true",
                      help="create missing symlinks; never delete or replace a directory")
    args = parser.parse_args(argv)

    root = args.root.expanduser()
    if not root.exists():
        print(f"install_host_skills: root does not exist: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"install_host_skills: root is not a directory: {root}", file=sys.stderr)
        return 2
    try:
        skills = repo_skills(SKILLS)
    except (OSError, ValueError) as error:
        print(f"install_host_skills: {error}", file=sys.stderr)
        return 2
    return check(root, skills) if args.check else link(root, skills)


if __name__ == "__main__":
    sys.exit(main())
