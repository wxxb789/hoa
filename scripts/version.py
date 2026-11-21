#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml>=6"]
# ///
"""Per-skill revision gate.

Usage:
    uv run scripts/version.py check-revisions   # PR gate: changed skills bump metadata.revision

Each skill's `SKILL.md` carries `metadata.revision`, an integer string counting
that skill's own iterations: a pull request bumps it only for the skill
packages it changes. A new skill starts at "1"; a deleted skill is ignored.
A file moved between skills counts as a change to both. A pure package move
between categories (`skills/<name>/` to `skills/<category>/<name>/`, or between
categories) is not a change and keeps the skill's old revision; the move is
recognized only when the package's files are byte-identical to the base tree and
nothing is unstaged or untracked under the destination.
The gate reads origin/main from the local repository; fetch it first.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

sys.dont_write_bytecode = True
import skill_metadata as sm
import skill_paths

ROOT = Path(__file__).resolve().parent.parent


def _git(*arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], text=True,
                            encoding="utf-8", capture_output=True)
    if result.returncode:
        detail = result.stderr.strip() or f"git exited {result.returncode}"
        raise ValueError(f"git {' '.join(arguments)} failed ({detail}); "
                         "fetch origin main and retry")
    return result.stdout


def _nul(output: str) -> list[str]:
    """Split a `-z` Git list into its non-empty records."""
    return [item for item in output.split("\0") if item]


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _base_manifests(base: str) -> dict[str, tuple[str, str]]:
    """Base tree `skills/` manifests: name → (package prefix, blob object ID)."""
    manifests: dict[str, tuple[str, str]] = {}
    output = _git("ls-tree", "-r", "-z", base, "--", "skills/")
    for record in _nul(output):
        meta, path = record.split("\t", 1)
        _mode, _kind, object_id = meta.split(" ")
        parts = path.split("/")
        if parts[0] != "skills" or parts[-1] != "SKILL.md" or len(parts) not in (3, 4):
            continue
        prefix = "/".join(parts[:-1])
        name = parts[-2]
        previous = manifests.setdefault(name, (prefix, object_id))
        if previous[0] != prefix:
            raise ValueError(f"git ls-tree {base}: ambiguous skill name {name!r}: "
                             f"{previous[0]} and {prefix}")
    return manifests


def _base_revision(base: str, manifest_object: str) -> int:
    """A skill's revision at base; a base that predates metadata.revision is 0."""
    text = _git("cat-file", "blob", manifest_object)
    # Not catalog_metadata: it rejects the retired `version` key a base may still carry.
    frontmatter, _ = sm._frontmatter(text, Path(f"{base[:12]}:SKILL.md"))
    metadata = (yaml.safe_load(frontmatter) or {}).get("metadata") or {}
    return int(metadata.get("revision", 0))


def _current_packages() -> dict[str, str]:
    """Worktree packages: leaf skill name → staged-path prefix."""
    packages: dict[str, str] = {}
    skills = ROOT / "skills"
    if not skills.is_dir():
        return packages
    for path in skill_paths.skill_dirs(skills):
        if not (path / "SKILL.md").is_file():
            continue
        prefix = path.relative_to(ROOT).as_posix()
        previous = packages.setdefault(path.name, prefix)
        if previous != prefix:
            raise ValueError(f"{skills}: ambiguous skill name {path.name!r}: "
                             f"{previous} and {prefix}")
    return packages


def _changed_names(paths: list[str], *packages: dict[str, str]) -> set[str]:
    """Skill names owning any of the changed paths, on either side of the diff."""
    names = set()
    for path in paths:
        for mapping in packages:
            names.update(name for name, prefix in mapping.items() if _matches(path, prefix))
    return names


def _tree_files(base: str, prefix: str) -> dict[str, tuple[str, str]]:
    """A base package's relative file map of `(mode, object ID)`."""
    files = {}
    output = _git("ls-tree", "-r", "-z", base, "--", prefix + "/")
    for record in _nul(output):
        meta, path = record.split("\t", 1)
        mode, _kind, object_id = meta.split(" ")
        if _matches(path, prefix):
            files[path[len(prefix) + 1:]] = (mode, object_id)
    return files


def _index_files(prefix: str) -> dict[str, tuple[str, str]]:
    """A destination package's stage-0 file map; empty when unmerged or unlisted."""
    files = {}
    output = _git("ls-files", "--stage", "-z", "--", prefix + "/")
    for record in _nul(output):
        meta, path = record.split("\t", 1)
        mode, object_id, stage = meta.split(" ")
        if stage != "0" or not _matches(path, prefix):
            return {}
        files[path[len(prefix) + 1:]] = (mode, object_id)
    return files


def _pure_move(base: str, base_prefix: str, prefix: str, untracked: list[str]) -> bool:
    """True when `prefix` is an exact, clean relocation of the base package."""
    if _tree_files(base, base_prefix) != _index_files(prefix):
        return False
    if _nul(_git("diff", "--name-only", "-z", "--", prefix + "/")):
        return False
    return not any(_matches(path, prefix) for path in untracked)


def check_revisions() -> list[str]:
    """Require every skill changed since the merge base to raise its revision."""
    base = _git("merge-base", "HEAD", "origin/main").strip()
    base_manifests = _base_manifests(base)
    base_packages = {name: prefix for name, (prefix, _object) in base_manifests.items()}
    current_packages = _current_packages()
    diff_paths = _nul(_git("diff", "--name-only", "-z", "--no-renames", base, "--", "skills/"))
    untracked = _nul(_git("ls-files", "--others", "--exclude-standard", "-z", "--", "skills/"))
    changed = _changed_names([*diff_paths, *untracked], base_packages, current_packages)
    findings = []
    checked = []
    for name, prefix in sorted(current_packages.items()):
        skill_md = ROOT / prefix / "SKILL.md"
        current = int(sm.catalog_metadata(skill_md.read_text(encoding="utf-8"),
                                          skill_md)["revision"])
        if name not in base_packages:
            checked.append(name)
            if current != 1:
                findings.append(f"{prefix}/SKILL.md: new skill must start at "
                                f"metadata.revision \"1\", got \"{current}\"")
            continue
        base_prefix = base_packages[name]
        if base_prefix == prefix:
            if name not in changed:
                continue
            checked.append(name)
        else:
            if _pure_move(base, base_prefix, prefix, untracked):
                continue
            checked.append(name)
        before = _base_revision(base, base_manifests[name][1])
        if current <= before:
            findings.append(f"{prefix}/SKILL.md: changed since {base[:12]} but metadata.revision "
                            f"\"{current}\" is not above the base's \"{before}\"; "
                            f"set it to \"{before + 1}\"")
    if findings:
        raise ValueError("\n".join(findings))
    return checked


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-revisions",
                        help="fail unless every changed skill raises metadata.revision")
    parser.parse_args(argv)
    try:
        names = check_revisions()
    except (OSError, ValueError) as error:
        print(f"version: {error}", file=sys.stderr)
        return 1
    print(f"check-revisions: {len(names)} changed skill(s) OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
