#!/usr/bin/env python3
"""Manage one stable version for the repository's flat custom skills.

Usage:
    python scripts/version.py check       # read-only mirror and index check
    python scripts/version.py sync        # mirror VERSION and regenerate indexes
    python scripts/version.py bump        # patch by default; prints new version
    python scripts/version.py bump minor  # or major; resets lower components

Only skills/<name>/SKILL.md metadata.version scalars, the two generated indexes,
and VERSION are writable. Library versions and ref/ are independent. Every input
is validated before staging writes; each replacement is atomic and VERSION
is replaced last. Handled write failures roll back completed replacements.
Temporary write staging stays under .tmp-artifacts/version-write/. A process
kill or concurrent writer is not a multi-file transaction: run check before
using or publishing an interrupted tree. No Git commands are run by this script.
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile
from pathlib import Path

# A read-only check must not create an import cache beside the generator.
sys.dont_write_bytecode = True
import generate_index as gi
import skill_metadata as sm

ROOT = Path(__file__).resolve().parent.parent
INDEXES = (("en", "index.md"), ("zh", "index.zh-CN.md"))


def _safe_path(path: Path, *, directory=False, missing=False) -> None:
    """Reject links/reparse points in every component of a repository target."""
    relative = path.relative_to(ROOT)
    if ".." in relative.parts:
        raise ValueError(f"target escapes repository: {path}")
    current = ROOT
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if missing:
                return
            raise ValueError(f"missing target: {current}") from None
        reparse = getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(info.st_mode) or reparse:
            raise ValueError(f"symlink/reparse target is not allowed: {current}")
        expected_directory = current != path or directory
        if expected_directory and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"expected directory: {current}")
        if not expected_directory and not stat.S_ISREG(info.st_mode):
            raise ValueError(f"expected regular file: {current}")
    if not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError(f"target escapes repository: {path}")


def _custom_skills() -> list[Path]:
    skills = ROOT / "skills"
    _safe_path(skills, directory=True)
    targets = []
    for entry in sorted(skills.iterdir()):
        is_directory = entry.is_dir()
        _safe_path(entry, directory=is_directory)
        if is_directory:
            target = entry / "SKILL.md"
            _safe_path(target)
            targets.append(target)
    if not targets:
        raise ValueError(f"no flat custom skills found in {skills}")
    return targets




def _prepare(part: str | None) -> tuple[str, list[tuple[Path, bytes | None, bytes]]]:
    marker = ROOT / "VERSION"
    _safe_path(marker)
    original = marker.read_bytes()
    text = original.decode("utf-8")
    newline = "\r\n" if text.endswith("\r\n") else "\n" if text.endswith("\n") else ""
    current = text[:-len(newline)] if newline else text
    sm.validate_version(current, marker)
    release = current
    if part is not None:
        components = [int(value) for value in current.split(".")]
        index = ("major", "minor", "patch").index(part)
        components[index] += 1
        components[index + 1:] = [0] * (2 - index)
        release = ".".join(str(value) for value in components)

    plans = []
    for target in _custom_skills():
        before = target.read_bytes()
        gi.parse_skill_metadata(target)
        after = sm.replace_version(before.decode("utf-8"), release, target).encode("utf-8")
        plans.append((target, before, after))
    for _, filename in INDEXES:
        _safe_path(ROOT / filename, missing=True)

    # Collect and render before touching disk so invalid library metadata, notes,
    # or duplicate catalog names cannot leave partly updated custom skills.
    rows = gi.collect()
    for row in rows:
        if row["type"] == "skill":
            row["version"] = release
    _safe_path(ROOT / ".tmp-artifacts" / "version-write", directory=True, missing=True)
    for lang, filename in INDEXES:
        target = ROOT / filename
        before = target.read_bytes() if target.exists() else None
        rendered = gi.render(rows, lang)
        if before is not None and b"\r\n" in before:
            rendered = rendered.replace("\n", "\r\n")
        plans.append((target, before, rendered.encode("utf-8")))
    plans.append((marker, original, (release + newline).encode("utf-8")))
    return release, plans


def _stage(target: Path, content: bytes, staging: Path) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=".version-", suffix=".tmp",
                                        dir=staging)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            staged.chmod(stat.S_IMODE(target.stat().st_mode))
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def _expect_content(target: Path, expected: bytes | None, phase="update conflict") -> None:
    """Refuse to replace or roll back bytes changed by another writer."""
    try:
        _safe_path(target, missing=True)
    except ValueError as error:
        raise RuntimeError(f"{phase}: {error}") from error
    try:
        actual = target.read_bytes()
    except FileNotFoundError:
        actual = None
    if actual != expected:
        raise RuntimeError(f"{phase}: concurrent change in {target}; preserving current target")


def _apply(plans: list[tuple[Path, bytes | None, bytes]]) -> None:
    changes = [plan for plan in plans if plan[1] != plan[2]]
    if not changes:
        return
    folder = ROOT / ".tmp-artifacts" / "version-write"
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="update-", dir=folder) as directory:
        staging = Path(directory)
        staged = []
        applied = []
        try:
            for target, before, after in changes:
                staged.append((_stage(target, after, staging), target, before, after))
            for target, before, _ in plans:
                _expect_content(target, before)
            for temporary, target, before, after in staged:
                _expect_content(target, before)
                os.replace(temporary, target)
                applied.append((target, before, after))
        except BaseException as error:
            failures = []
            for target, before, after in reversed(applied):
                try:
                    if before is None:
                        _expect_content(target, after, "rollback conflict")
                        target.unlink()
                    else:
                        rollback = _stage(target, before, staging)
                        _expect_content(target, after, "rollback conflict")
                        os.replace(rollback, target)
                except (OSError, ValueError, RuntimeError) as rollback_error:
                    failures.append(f"{target}: {rollback_error}")
            if failures:
                raise RuntimeError(f"update failed ({error}); rollback failed: "
                                   + "; ".join(failures)
                                   + "; run version.py check before using this tree") from error
            raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="read-only version mirror and index check")
    commands.add_parser("sync", help="mirror VERSION and regenerate indexes")
    bump = commands.add_parser("bump", help="increment VERSION and sync mirrors/indexes")
    bump.add_argument("part", choices=("patch", "minor", "major"), nargs="?",
                      default="patch")
    args = parser.parse_args(argv)
    try:
        release, plans = _prepare(args.part if args.command == "bump" else None)
        if args.command == "check":
            drift = [str(target.relative_to(ROOT)) for target, before, after in plans
                     if before != after]
            if drift:
                raise ValueError("version/index drift in " + ", ".join(drift)
                                 + "; run python scripts/version.py sync")
        else:
            _apply(plans)
            print(release)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"version: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
