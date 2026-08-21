#!/usr/bin/env python3
"""State management - simplified.

Just load/save with plain dicts. No dataclasses.
State is stored in the repo's git dir (worktree-safe via `git rev-parse --git-path`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import git


STATE_FILENAME = "commit-push-pr-state.json"


def get_path(*, repo_root: str | None = None) -> Path:
    """Get the path to the state file.

    Uses `git rev-parse --git-path` so the file lives in the correct git dir
    for both the main checkout (`.git/<name>`) and linked worktrees
    (`.git/worktrees/<wt>/<name>`).
    """
    if repo_root is None:
        repo_root = git.git_root()
    try:
        cp = git._run(["rev-parse", "--git-path", STATE_FILENAME], cwd=repo_root)
        rel = cp.stdout.strip()
    except git.GitError:
        # Fallback to .git/<name> if rev-parse fails (e.g., not a git repo)
        rel = f".git/{STATE_FILENAME}"
    p = Path(rel)
    if p.is_absolute():
        return p
    return Path(repo_root) / p


def load(*, repo_root: str | None = None) -> dict[str, Any] | None:
    """Load state from disk. Returns None if not found or corrupt.

    On JSON corruption, the bad file is renamed to `<name>.corrupt` and a
    warning is written to stderr so it doesn't keep poisoning subsequent runs.
    """
    path = get_path(repo_root=repo_root)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError):
        return None
    except json.JSONDecodeError:
        sys.stderr.write(f"[state] corrupt state at {path}; renaming to .corrupt\n")
        try:
            path.rename(path.with_suffix(path.suffix + ".corrupt"))
        except OSError:
            pass
        return None


def save(state: dict[str, Any], *, repo_root: str | None = None) -> Path:
    """Save state to disk. Returns path."""
    path = get_path(repo_root=repo_root)
    path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def clear(*, repo_root: str | None = None) -> None:
    """Delete the state file if it exists."""
    try:
        get_path(repo_root=repo_root).unlink(missing_ok=True)
    except OSError:
        pass


def new_state(
    *,
    provider: str,
    remote_url: str,
    branch: str,
    head_at_start: str | None = None,
) -> dict[str, Any]:
    """Create a fresh state dict.

    `head_at_start` is the HEAD sha captured before apply begins; used later to
    detect stale state (HEAD moved out from under us).
    """
    return {
        "provider": provider,
        "remote_url": remote_url,
        "branch": branch,
        "head_at_start": head_at_start,
        "done": {},
        "artifacts": {},
    }
