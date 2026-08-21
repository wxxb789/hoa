#!/usr/bin/env python3
"""Git operations - simplified.

All git operations as simple functions, returning plain types.
"""

from __future__ import annotations

from cli_exec import CommandError, run_command

import subprocess


class GitError(CommandError):
    """Raised when a git command fails."""


def _run(
    args: list[str],
    *,
    cwd: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git command."""
    try:
        cp = run_command(
            ["git", *args],
            cwd=cwd,
            check=False,
            env={"LC_ALL": "C"},  # cli_exec.run_command merges this into os.environ
        )
    except CommandError as e:
        raise GitError(str(e), returncode=e.returncode, stderr=e.stderr) from e

    if check and cp.returncode != 0:
        err = (cp.stderr or cp.stdout or "").strip()
        raise GitError(
            f"git {args[0]} failed: {err}" if err else f"git {args[0]} failed",
            returncode=cp.returncode,
            stderr=cp.stderr or "",
        )
    return cp


# -----------------------------------------------------------------------------
# Query
# -----------------------------------------------------------------------------


def git_root(*, cwd: str | None = None) -> str:
    """Get the repository root path."""
    return _run(["rev-parse", "--show-toplevel"], cwd=cwd).stdout.strip()


def current_branch(*, cwd: str | None = None) -> str:
    """Get the current branch name."""
    return _run(["branch", "--show-current"], cwd=cwd).stdout.strip()


def remote_origin_url(*, cwd: str | None = None) -> str:
    """Get the origin remote URL."""
    return _run(["remote", "get-url", "origin"], cwd=cwd).stdout.strip()


def status_porcelain(*, cwd: str | None = None) -> list[str]:
    """Get git status in porcelain format."""
    cp = _run(["status", "--porcelain"], cwd=cwd, check=False)
    if cp.returncode != 0:
        return []
    return [line for line in cp.stdout.splitlines() if line.strip()]


def recent_commits(*, count: int = 5, cwd: str | None = None) -> list[str]:
    """Get recent commit messages (one line each)."""
    cp = _run(["log", "--oneline", f"-{count}"], cwd=cwd, check=False)
    if cp.returncode != 0:
        return []
    return [line for line in cp.stdout.splitlines() if line.strip()]


def create_branch(branch: str, *, cwd: str | None = None) -> None:
    """Create and checkout a new branch."""
    _run(["checkout", "-b", branch], cwd=cwd)


def checkout(branch: str, *, cwd: str | None = None) -> None:
    """Checkout an existing branch."""
    _run(["checkout", branch], cwd=cwd)


def head_sha(*, cwd: str | None = None) -> str:
    """Get the current HEAD SHA."""
    return _run(["rev-parse", "HEAD"], cwd=cwd).stdout.strip()


def is_detached_head(*, cwd: str | None = None) -> bool:
    """Return True if HEAD is detached."""
    cp = _run(["symbolic-ref", "-q", "HEAD"], cwd=cwd, check=False)
    return cp.returncode != 0


def is_ancestor(maybe_ancestor: str, of: str = "HEAD", *, cwd: str | None = None) -> bool:
    """Return True if maybe_ancestor is reachable from `of`."""
    cp = _run(["merge-base", "--is-ancestor", maybe_ancestor, of], cwd=cwd, check=False)
    if cp.returncode == 0:
        return True
    if cp.returncode == 1:
        return False
    # Other returncodes mean error — treat as False, do not crash
    return False


def diff_stat(*, cwd: str | None = None) -> dict:
    """Diff stats vs HEAD. Returns {files, insertions, deletions}."""
    cp = _run(["diff", "--shortstat", "HEAD"], cwd=cwd, check=False)
    out = (cp.stdout or "").strip()
    if not out:
        return {"files": 0, "insertions": 0, "deletions": 0}
    # Example: " 3 files changed, 25 insertions(+), 12 deletions(-)"
    import re as _re
    files = _re.search(r"(\d+) files? changed", out)
    ins = _re.search(r"(\d+) insertions?\(\+\)", out)
    dels = _re.search(r"(\d+) deletions?\(-\)", out)
    return {
        "files": int(files.group(1)) if files else 0,
        "insertions": int(ins.group(1)) if ins else 0,
        "deletions": int(dels.group(1)) if dels else 0,
    }


def _split_porcelain(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (staged, unstaged, untracked) lists of paths."""
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    for line in lines:
        if len(line) < 3:
            continue
        x, y, path = line[0], line[1], line[3:].strip()
        # Strip rename arrows "old -> new" — take the new path
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if x == "?" and y == "?":
            untracked.append(path)
            continue
        if x.strip() and x != "?":
            staged.append(path)
        if y.strip() and y != "?":
            unstaged.append(path)
    return staged, unstaged, untracked
# -----------------------------------------------------------------------------
# Write
# -----------------------------------------------------------------------------


def commit(
    message: str,
    *,
    stage_all_first: bool = False,
    amend: bool = False,
    cwd: str | None = None,
) -> str:
    """Create a commit. Returns the commit SHA.

    If `amend` is True, uses --amend; if `message` is empty, also uses --no-edit.
    """
    if stage_all_first:
        _run(["add", "-A"], cwd=cwd)

    args = ["commit"]
    if amend:
        args.append("--amend")
        if not message.strip():
            args.append("--no-edit")
        else:
            args += ["-m", message.rstrip("\n") + "\n"]
    else:
        if not message.strip():
            raise GitError("commit message is empty")
        args += ["-m", message.rstrip("\n") + "\n"]

    cp = _run(args, cwd=cwd, check=False)
    if cp.returncode != 0:
        combined = (cp.stderr + cp.stdout).lower()
        if "nothing to commit" in combined:
            raise GitError(
                "nothing to commit — working tree is clean or pre-commit hook reverted changes",
                returncode=cp.returncode,
                stderr=cp.stderr or "",
            )
        err = (cp.stderr or cp.stdout or "").strip()
        raise GitError(
            f"git commit failed: {err}" if err else "git commit failed",
            returncode=cp.returncode,
            stderr=cp.stderr or "",
        )

    return head_sha(cwd=cwd)


def commit_with_paths(
    message: str,
    paths: list[str],
    *,
    amend: bool = False,
    cwd: str | None = None,
) -> str:
    """Stage specific paths then commit. Returns SHA."""
    if not paths:
        raise GitError("commit_with_paths: paths must not be empty")
    _run(["add", "--", *paths], cwd=cwd)
    return commit(message, stage_all_first=False, amend=amend, cwd=cwd)


def push(
    *,
    branch: str | None = None,
    set_upstream: bool = True,
    force_with_lease: bool = False,
    remote: str = "origin",
    cwd: str | None = None,
) -> str:
    """Push the current branch to remote. Returns the branch name."""
    if branch is None:
        branch = current_branch(cwd=cwd)

    args = ["push"]
    if force_with_lease:
        args.append("--force-with-lease")
    if set_upstream:
        args.extend(["-u", remote, branch])
    else:
        args.extend([remote, branch])

    cp = _run(args, cwd=cwd, check=False)
    if cp.returncode != 0:
        err = (cp.stderr or cp.stdout or "").strip()
        raise GitError(
            f"git push failed: {err}",
            returncode=cp.returncode,
            stderr=cp.stderr or "",
        )

    return branch
