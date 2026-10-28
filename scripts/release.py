#!/usr/bin/env python3
"""Publish the tested main revision and its unified version tag from GitHub CI.

Usage: python scripts/release.py [--part patch|minor|major]
An untagged VERSION is published as-is. Subsequent main pushes bump patch;
workflow_dispatch may select a different increment. This entry point writes
Git refs and is deliberately unavailable outside a trusted main CI event.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ReleaseError(Exception):
    pass


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=ROOT, check=check, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("git", *args, check=check)


def tag_commit(tag: str) -> str | None:
    ref = f"refs/tags/{tag}"
    exists = git("show-ref", "--verify", "--quiet", ref, check=False)
    if exists.returncode == 1:
        return None
    if exists.returncode:
        raise ReleaseError(f"cannot inspect tag {tag}: {exists.stderr.strip()}")
    target = git("rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
    if target.returncode:
        raise ReleaseError(f"tag collision: {tag} does not point to a commit")
    return target.stdout.strip()


def version_command(*args: str) -> None:
    run(sys.executable, str(ROOT / "scripts" / "version.py"), *args)


def publish(part: str) -> None:
    event = os.environ.get("GITHUB_EVENT_NAME")
    tested = os.environ.get("GITHUB_SHA", "")
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or event not in ("push", "workflow_dispatch")
        or re.fullmatch(r"[0-9a-f]{40}", tested) is None
    ):
        raise ReleaseError("requires a GitHub Actions main push/workflow_dispatch event and its full tested SHA")
    if event == "push" and part != "patch":
        raise ReleaseError("main pushes must use patch; minor/major require workflow_dispatch")
    head = git("rev-parse", "HEAD").stdout.strip()
    if head != tested:
        raise ReleaseError(f"checkout HEAD {head} does not match tested GITHUB_SHA {tested}")

    # No force refspecs: an existing tag must never be replaced, even locally.
    git(
        "fetch", "--atomic", "--no-tags", "origin",
        "refs/heads/main:refs/remotes/origin/main", "refs/tags/*:refs/tags/*",
    )
    current_main = git("rev-parse", "refs/remotes/origin/main").stdout.strip()
    if current_main != tested:
        print(f"Skipped stale tested head {tested}; origin/main is now {current_main}")
        return

    paths = ["VERSION", "index.md", "index.zh-CN.md"]
    paths.extend(str(path.relative_to(ROOT).as_posix()) for path in sorted((ROOT / "skills").glob("*/SKILL.md")))
    dirty = git("status", "--porcelain", "--untracked-files=all", "--", *paths).stdout
    if dirty:
        raise ReleaseError("release-owned paths have uncommitted changes; refusing to include them")
    version_command("check")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    tag = f"v{version}"
    previous = tag_commit(tag)
    if previous is not None:
        ancestor = git("merge-base", "--is-ancestor", previous, head, check=False)
        if ancestor.returncode == 1:
            raise ReleaseError(f"tag collision: {tag} is outside the tested main history")
        if ancestor.returncode:
            raise ReleaseError(f"cannot establish history for {tag}: {ancestor.stderr.strip()}")
        if previous == head and event == "push":
            print(f"No release needed: {tag} already published at tested HEAD {head}")
            return
        version_command("bump", part)
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        tag = f"v{version}"
        if tag_commit(tag) is not None:
            raise ReleaseError(f"tag collision: {tag} already exists; refusing to overwrite it")
        version_command("check")

    git("add", "--", *paths)
    changed = git("diff", "--cached", "--quiet", "--", *paths, check=False)
    if changed.returncode == 1:
        # --only leaves any unrelated staged work out of the release commit.
        git(
            "-c", "user.name=github-actions[bot]",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "--only", "-m", f"chore: release {tag}", "--", *paths,
        )
    elif changed.returncode:
        raise ReleaseError(f"cannot inspect release changes: {changed.stderr.strip()}")
    git("tag", tag)
    # Normal atomic push honors branch protection and rejects branch/tag races.
    # Never split this into two pushes: a rejected branch must not publish a tag.
    git("push", "--atomic", "origin", "HEAD:refs/heads/main", f"refs/tags/{tag}:refs/tags/{tag}")
    print(f"Published {tag} at {git('rev-parse', 'HEAD').stdout.strip()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", choices=("patch", "minor", "major"), default="patch")
    args = parser.parse_args(argv)
    try:
        publish(args.part)
    except ReleaseError as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        print(f"release: command failed: {detail}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
