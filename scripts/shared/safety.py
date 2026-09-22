"""Fail-closed output-location safety for hoa skills.

The AGENT supplies the target path; this module only VALIDATES it - it never
auto-discovers, auto-redirects, or writes. A path is safe only when it is
outside every git worktree OR git-ignored inside its worktree. Anything that
cannot be proven safe (git missing, ambiguous git error, or a repository git
could not resolve) is REFUSED.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _git_env() -> dict[str, str]:
    """Run git with EVERY GIT_* variable stripped.

    git needs none of them to run rev-parse / check-ignore inside a repo, and
    any of them can subvert the gate: GIT_DIR / GIT_WORK_TREE / GIT_CEILING_*
    redirect discovery to mask a real worktree, and GIT_CONFIG_COUNT/KEY/VALUE
    or GIT_CONFIG_GLOBAL/SYSTEM inject config (e.g. core.excludesFile) that can
    force a tracked path to look ignored. Removing them all keeps it fail-closed.
    """
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _nearest_existing(path: Path) -> Path:
    """Return the nearest existing DIRECTORY (git -C needs a dir, not a file)."""
    try:
        probe = path if path.is_dir() else path.parent
        while not probe.is_dir() and probe != probe.parent:
            probe = probe.parent
        return probe
    except OSError:
        return path.parent


def _has_git_marker(directory: Path) -> bool:
    """True if any ancestor holds a .git marker git itself could not resolve.

    Uses os.path.lexists (not .exists), so a DANGLING .git symlink - which
    .exists() reports as absent because it follows the link - still counts as a
    marker and forces a refusal, closing a fail-open path.
    """
    probe = directory
    while True:
        try:
            if os.path.lexists(probe / ".git"):
                return True
        except OSError:
            return True
        if probe == probe.parent:
            return False
        probe = probe.parent


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=False, env=_git_env())
    except (OSError, ValueError):
        return None


def output_is_safe(target: Path) -> tuple[bool, str]:
    """Return (safe, reason). Fails closed on any inability to prove safety."""
    try:
        resolved = target.expanduser().resolve()
    except (OSError, RuntimeError):
        return (False, "path-resolution-error")
    probe = _nearest_existing(resolved)
    top = _run_git(["git", "-C", str(probe), "rev-parse", "--show-toplevel"])
    if top is None:
        return (False, "git-unavailable")
    if top.returncode == 0:
        toplevel = top.stdout.strip()
        ignored = _run_git(["git", "-C", toplevel, "check-ignore", "-q", "--", str(resolved)])
        if ignored is None:
            return (False, "git-unavailable")
        if ignored.returncode == 0:
            return (True, "git-ignored")
        if ignored.returncode == 1:
            return (False, "tracked-or-unignored-worktree-path")
        return (False, "git-check-ignore-error")
    stderr = (top.stderr or "").lower()
    if ("not a git repository" in stderr or "not a work tree" in stderr) and not _has_git_marker(probe):
        return (True, "outside-worktree")
    return (False, "git-error")
