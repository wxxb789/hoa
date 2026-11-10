#!/usr/bin/env python3
"""Manage one stable version for the repository's flat custom skills.

Usage:
    python scripts/version.py check       # read-only mirror and index check
    python scripts/version.py sync        # mirror VERSION and regenerate indexes
    python scripts/version.py bump        # patch by default; prints new version
    python scripts/version.py bump minor  # or major; resets lower components
    python scripts/version.py check-bump  # PR guard: exactly one patch above origin/main
    python scripts/version.py check-merge # merge guard: the remote's patch + 1, tag unused
    python scripts/version.py check-merge --offline  # local check only; warns

Only skills/<name>/SKILL.md metadata.version scalars, the two generated indexes,
and VERSION are writable. Library versions and ref/ are independent. Every input
is validated before staging writes; each replacement is atomic and VERSION
is replaced last. Handled write failures roll back completed replacements.
Temporary write staging stays under .tmp-artifacts/version-write/. A process
kill or concurrent writer is not a multi-file transaction: run check before
using or publishing an interrupted tree. Only the check commands run Git:
check-bump reads origin/main:VERSION from the local repository, check-merge reads
the remote's real main via git ls-remote and verifies the version claim there.
"""
from __future__ import annotations

import argparse
import os
import stat
import subprocess
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




def _marker() -> tuple[Path, bytes, str, str]:
    marker = ROOT / "VERSION"
    _safe_path(marker)
    original = marker.read_bytes()
    text = original.decode("utf-8")
    newline = "\r\n" if text.endswith("\r\n") else "\n" if text.endswith("\n") else ""
    current = text[:-len(newline)] if newline else text
    sm.validate_version(current, marker)
    return marker, original, current, newline


def _prepare(part: str | None) -> tuple[str, list[tuple[Path, bytes | None, bytes]]]:
    marker, original, current, newline = _marker()
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


def _git(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _git_detail(result: subprocess.CompletedProcess) -> str:
    return result.stderr.strip() or result.stdout.strip() or f"git exited {result.returncode}"


def _git_main_version() -> str:
    result = _git("show", "origin/main:VERSION")
    if result.returncode:
        raise ValueError(f"cannot read origin/main:VERSION from git ({_git_detail(result)}); "
                         "fetch origin main before checking the bump")
    base = result.stdout.strip()
    sm.validate_version(base, Path("origin/main:VERSION"))
    return base


def _next_patch(version: str) -> str:
    components = [int(value) for value in version.split(".")]
    components[2] += 1
    return ".".join(str(value) for value in components)


def _require_patch_claim(current: str, base: str) -> None:
    """Require current to be exactly base's patch plus one."""
    expected = _next_patch(base)
    fix = "run python scripts/version.py bump"
    if current == expected:
        return
    current_parts = tuple(int(value) for value in current.split("."))
    base_parts = tuple(int(value) for value in base.split("."))
    if current_parts < base_parts:
        raise ValueError(f"VERSION {current} is older than origin/main's {base}; "
                         f"rebase onto origin/main and {fix} (expected {expected})")
    if current_parts[:2] != base_parts[:2]:
        raise ValueError(f"VERSION {current} is not a patch over origin/main's {base}: "
                         f"patch only; {fix} (expected {expected})")
    if current == base:
        raise ValueError(f"VERSION {current} is unchanged from origin/main; every pull "
                         f"request must bump the patch: {fix}")
    raise ValueError(f"VERSION {current} is not exactly one patch above origin/main's "
                     f"{base}; {fix} (expected {expected})")


def _remote_refs(*arguments: str) -> dict[str, str]:
    result = _git("ls-remote", *arguments)
    if result.returncode:
        raise ValueError(f"cannot query origin ({_git_detail(result)}); "
                         "check the origin remote and network access")
    refs = {}
    for line in result.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if name:
            refs[name] = sha
    return refs


def _remote_main() -> tuple[str, str]:
    """Return remote main's commit and VERSION, refusing a stale local origin/main."""
    remote = _remote_refs("--heads", "origin", "refs/heads/main").get("refs/heads/main")
    if remote is None:
        raise ValueError("origin has no refs/heads/main; cannot check the version claim")
    local = _git("rev-parse", "--verify", "refs/remotes/origin/main")
    local = local.stdout.strip() if local.returncode == 0 else "missing"
    if local != remote:
        raise ValueError(f"origin/main is stale locally ({local} != {remote}); "
                         "run: git fetch origin main")
    result = _git("show", f"{remote}:VERSION")
    if result.returncode:
        # The matching local ref usually has the object; fetch it when it does not.
        for fetch in (("fetch", "--no-tags", "origin", remote),
                      ("fetch", "--no-tags", "origin", "main")):
            if _git(*fetch).returncode == 0:
                result = _git("show", f"{remote}:VERSION")
                if result.returncode == 0:
                    break
    if result.returncode:
        raise ValueError(f"cannot read {remote}:VERSION from git ({_git_detail(result)}); "
                         "fetch origin main and retry")
    base = result.stdout.strip()
    sm.validate_version(base, Path(f"{remote}:VERSION"))
    return remote, base


def _remote_tag(version: str) -> tuple[str, str] | None:
    tag = f"v{version}"
    full = f"refs/tags/{tag}"
    refs = _remote_refs("--tags", "origin", f"{full}*")
    if full not in refs:
        return None
    return tag, refs.get(f"{full}^{{}}", refs[full])


def check_bump() -> None:
    """Require VERSION to be exactly origin/main's patch plus one."""
    base = _git_main_version()
    current = _marker()[2]
    _require_patch_claim(current, base)
    print(current)


def check_merge(offline: bool = False) -> None:
    """Require VERSION to be the free patch above origin's real main."""
    current = _marker()[2]
    if offline:
        print("check-merge: offline, stale-ref and tag collisions are not verified",
              file=sys.stderr)
        check_bump()
        return
    _, base = _remote_main()
    _require_patch_claim(current, base)
    released = _remote_tag(current)
    if released is not None:
        tag, commit = released
        raise ValueError(f"tag {tag} already exists on origin at {commit}; VERSION {current} "
                         "is already released: every pull request must bump the patch")
    print(current)


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
    commands.add_parser("check-bump",
                        help="fail unless VERSION is exactly origin/main's patch + 1")
    merge = commands.add_parser(
        "check-merge",
        help="fail unless VERSION is the free patch above origin's real main")
    merge.add_argument("--offline", action="store_true",
                       help="skip the remote reads; stale refs and tags are not verified")
    bump = commands.add_parser("bump", help="increment VERSION and sync mirrors/indexes")
    bump.add_argument("part", choices=("patch", "minor", "major"), nargs="?",
                      default="patch")
    args = parser.parse_args(argv)
    try:
        if args.command == "check-bump":
            check_bump()
            return 0
        if args.command == "check-merge":
            check_merge(args.offline)
            return 0
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
