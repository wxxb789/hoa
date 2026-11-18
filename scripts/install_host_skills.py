#!/usr/bin/env python3
"""Install this repository's skills into a host skills directory.

The host side is a directory of skill entries (the shape `npx skills` and the
agent runtimes use). An entry is either flat (`<root>/<name>`) or categorized
(`<root>/<category>/<name>`); exactly one category level is searched. It should
be a symlink to `skills/<name>` here, or a byte-identical real directory copy
(`__pycache__` directories and `*.pyc` files are ignored on both sides).
The script never writes in `--check` mode, never deletes anything, and only
creates symlinks in `--link` mode; a real directory is never replaced.

Two or more entries for one skill are reported as `ambiguous`, never as
installed, and `--link` refuses to choose between them. A missing skill is
linked flat at `<root>/<name>`, or at `<root>/<category>/<name>` when
`--category` is given; existing categorized entries are still recognized.
A wrong symlink is relinked where it already is, so `--link` never adds a
second entry for one skill.

Host entries that do not match a repository skill are ignored, except names in
`scripts/retired_skills.toml`: `--check` reports each one still installed and
never removes it.

`--check` also verifies the `../<sibling>/` closure of every installed skill
(references found by `check_skill_links.py`). For an entry `<dir>/<parent>`
the lexical sibling is `<dir>/<sibling>` (Windows, and tools that normalize the
path first) and the physical sibling is `realpath(<dir>/<parent>)/../<sibling>`
(POSIX `open()` after following a symlink). Both must exist and hold the same
skill: same realpath or byte-identical trees. A missing lexical sibling is a
`missing closure`; a missing or different physical one is a `split closure`.

Usage:
    python scripts/install_host_skills.py --root <host-skills-dir> --check
    python scripts/install_host_skills.py --root <host-skills-dir> --link [--category <dir>]

Exit codes: 0 all skills installed (or `--link` needed no change), 1 findings
or refusals (each named on stdout), 2 usage or repository-state error.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tomllib
from pathlib import Path

# Keep --check read-only, including helper import caches.
sys.dont_write_bytecode = True

import check_skill_links as links

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
RETIRED = ROOT / "scripts" / "retired_skills.toml"


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
    """Relative path -> (kind, content); symlinks compare by target, files by bytes.

    `__pycache__` directories and `*.pyc` files are bytecode caches a copy installer
    never carries, so they are left out on both sides.
    """
    entries = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in relative.split("/") or path.suffix == ".pyc":
            continue
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
    """Classify one host entry: ok, drifted, wrong link or blocked path."""
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


def host_entries(root: Path, name: str) -> list[Path]:
    """Every host entry for one skill: `<root>/<name>` plus one category level.

    A category is a real directory directly under the root. Hidden directories
    and directories that are themselves skills (`SKILL.md`) are not categories,
    and deeper nesting is never searched.
    """
    entries = []
    flat = root / name
    if flat.is_symlink() or flat.exists():
        entries.append(flat)
    for category in sorted(root.iterdir()):
        if category.name.startswith(".") or category.is_symlink():
            continue
        if not category.is_dir() or (category / "SKILL.md").is_file():
            continue
        entry = category / name
        if entry.is_symlink() or entry.exists():
            entries.append(entry)
    return entries


def _locate(root: Path, repo: Path) -> tuple[str, str, list[Path]]:
    """Classify a skill across the host; competing entries are ambiguous."""
    entries = host_entries(root, repo.name)
    if not entries:
        return "absent", "", []
    if len(entries) > 1:
        return "ambiguous", ", ".join(str(entry) for entry in entries), entries
    state, detail = _inspect(entries[0], repo)
    return state, detail, entries


def retired_names(path: Path, skills: list[Path]) -> dict[str, tuple[str, str]]:
    """Retired name -> (replacement, reason) from the registry; absent file is empty."""
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            table = tomllib.load(handle).get("retired", {})
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: invalid TOML ({error})") from error
    current = {repo.name for repo in skills}
    retired = {}
    for name, entry in table.items():
        if name in current:
            raise ValueError(f"{path}: retired.{name} is a current skill")
        fields = entry if isinstance(entry, dict) else {}
        values = [fields.get(key) for key in ("replacement", "reason")]
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError(f"{path}: retired.{name} needs non-empty replacement and reason, "
                             f"got {entry!r}")
        retired[name] = (values[0].strip(), values[1].strip())
    return retired


def _closure(entry: Path, name: str) -> list[str]:
    """Closure findings for one installed entry, lexical and physical both computed."""
    findings = []
    physical_dir = Path(os.path.realpath(entry)).parent
    for sibling in sorted(links.siblings(entry)):
        lexical = entry.parent / sibling
        physical = physical_dir / sibling
        if not (lexical / "SKILL.md").is_file():
            findings.append(f"missing closure: {name} -> ../{sibling}/ "
                            f"not installed at {lexical}")
        elif not (physical / "SKILL.md").is_file():
            findings.append(f"split closure: {name} -> ../{sibling}/ "
                            f"physical {physical} missing (lexical {lexical} exists)")
        elif (os.path.realpath(lexical) != os.path.realpath(physical)
              and _tree(lexical) != _tree(physical)):
            findings.append(f"split closure: {name} -> ../{sibling}/ lexical {lexical} "
                            f"and physical {physical} differ "
                            f"({_difference(lexical, physical)})")
    return findings


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


def check(root: Path, skills: list[Path],
          retired: dict[str, tuple[str, str]] | None = None) -> int:
    findings = []
    flagged = set()
    for repo in skills:
        state, detail, entries = _locate(root, repo)
        skill_findings = []
        if state == "absent":
            skill_findings.append(f"absent: {repo.name}")
        elif state == "ambiguous":
            skill_findings.append(f"ambiguous: {repo.name} ({detail})")
        elif state == "drifted":
            skill_findings.append(f"drifted: {repo.name} ({detail})")
        elif state in ("wrong", "blocked"):
            skill_findings.append(f"wrongly linked: {repo.name} -> {detail}")
        if state in ("ok", "drifted"):
            skill_findings.extend(_closure(entries[0], repo.name))
        if skill_findings:
            flagged.add(repo.name)
            findings.extend(skill_findings)
    stale = [f"retired: {name} at {entry} (replaced by {replacement}: {reason})"
             for name, (replacement, reason) in sorted((retired or {}).items())
             for entry in host_entries(root, name)]
    findings.extend(stale)
    for finding in findings:
        print(finding)
    if findings:
        print(f"install_host_skills: {len(flagged)} of {len(skills)} skills "
              f"need attention, {len(stale)} retired entries installed at {root}",
              file=sys.stderr)
        return 1
    print(f"install_host_skills: all {len(skills)} skills installed at {root}")
    return 0


def link(root: Path, skills: list[Path], category: str | None = None) -> int:
    linked = relinked = refused = 0
    for repo in skills:
        state, detail, entries = _locate(root, repo)
        if state == "ok":
            continue
        if state == "ambiguous":
            print(f"refused: {repo.name}: {len(entries)} entries for one skill "
                  f"({detail}); remove the extra one yourself")
            refused += 1
            continue
        if state == "absent":
            entry = root / (category or ".") / repo.name
            entry.parent.mkdir(parents=True, exist_ok=True)
            _replace_link(entry, repo)
            print(f"linked: {repo.name} -> {entry.relative_to(root).as_posix()}")
            linked += 1
        elif state == "wrong":
            _replace_link(entries[0], repo)
            print(f"relinked: {repo.name} (was -> {detail})")
            relinked += 1
        elif state == "drifted":
            print(f"refused: {repo.name}: real directory at {entries[0]} differs from "
                  f"{repo} ({detail}); replace it yourself")
            refused += 1
        else:
            print(f"refused: {repo.name}: {entries[0]} is not a directory or symlink; "
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
    parser.add_argument("--category", default=None,
                        help="category directory for new links, relative to --root "
                             "(default: link flat at the root)")
    args = parser.parse_args(argv)

    root = args.root.expanduser()
    if not root.exists():
        print(f"install_host_skills: root does not exist: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"install_host_skills: root is not a directory: {root}", file=sys.stderr)
        return 2
    if args.category is not None:
        category = Path(args.category)
        if category.is_absolute() or ".." in category.parts:
            print(f"install_host_skills: --category must stay inside --root: "
                  f"{args.category}", file=sys.stderr)
            return 2
    try:
        skills = repo_skills(SKILLS)
        if args.check:
            return check(root, skills, retired_names(RETIRED, skills))
        return link(root, skills, args.category)
    except (OSError, ValueError) as error:
        print(f"install_host_skills: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
