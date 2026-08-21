#!/usr/bin/env python3
"""GitHub provider - simplified.

All functions, no class. Duck typing for provider interface.
"""

from __future__ import annotations

import json
import re
from typing import Any

from cli_exec import CommandError, gh_exec


NAME = "github"
AUTH_REMEDY = "gh auth login"


def detect(remote_url: str) -> bool:
    """Check if URL is a GitHub URL."""
    return bool(re.search(r"(?:^|[/@])github\.com[/:]", remote_url))


def parse_remote(remote_url: str) -> dict[str, Any]:
    """Parse GitHub remote URL. Returns repo info dict.

    Supports:
    - https://github.com/<owner>/<repo>.git
    - git@github.com:<owner>/<repo>.git
    - https://github.com/<owner>/<repo>
    """
    patterns = [
        r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
        r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$",
    ]

    for pat in patterns:
        m = re.match(pat, remote_url)
        if m:
            owner, repo = m.groups()
            return {
                "provider": NAME,
                "remote_url": remote_url,
                "owner": owner,
                "repo": repo,
                "project": None,
                "organization_url": None,
            }

    raise ValueError(f"Could not parse GitHub remote URL: {remote_url}")


def _repo_arg(repo_info: dict) -> list[str]:
    """Common -R argument for repo specification."""
    return ["-R", f"{repo_info['owner']}/{repo_info['repo']}"]


def check_auth(*, debug: bool = False) -> tuple[bool, dict | None]:
    """Return (is_authenticated, user_dict | None)."""
    try:
        gh_exec(["auth", "status"], debug=debug, check=True)
    except CommandError:
        return False, None
    # Try to fetch user info — non-fatal if it fails
    try:
        cp = gh_exec(["api", "user", "--jq", "{login, name}"], debug=debug, check=True)
        try:
            data = json.loads(cp.stdout) if cp.stdout.strip() else None
        except json.JSONDecodeError:
            data = None
        return True, data
    except CommandError:
        return True, None


def get_default_branch(repo_info: dict, *, debug: bool = False) -> str | None:
    """Get the default branch from GitHub."""
    try:
        cp = gh_exec(
            [
                "repo", "view",
                *_repo_arg(repo_info),
                "--json", "defaultBranchRef",
                "--jq", ".defaultBranchRef.name",
            ],
            debug=debug,
            check=True,
        )
        return cp.stdout.strip() or None
    except CommandError:
        return None


def list_active_prs(
    repo_info: dict,
    source_branch: str,
    *,
    debug: bool = False,
) -> list[dict[str, Any]]:
    """List open PRs for the given source branch."""
    try:
        cp = gh_exec(
            [
                "pr", "list",
                *_repo_arg(repo_info),
                "--head", source_branch,
                "--state", "open",
                "--json", "number,title,url,state,headRefName,baseRefName",
            ],
            debug=debug,
            check=True,
        )
        return json.loads(cp.stdout) if cp.stdout.strip() else []
    except (CommandError, json.JSONDecodeError):
        return []


def create_pr(
    repo_info: dict,
    *,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
    draft: bool = False,
    labels: list[str] | None = None,
    reviewers: list[str] | None = None,
    closes_issues: list[int] | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Create a new pull request. Returns result dict.

    ``closes_issues`` auto-appends ``Closes #N`` lines to the description for
    any issue numbers not already referenced by Closes/Fixes/Resolves keywords.
    """
    # Auto-append "Closes #N" lines if not already in description
    if closes_issues:
        import re as _re
        existing_refs: set[int] = set()
        for kw in ("Closes", "Fixes", "Resolves"):
            for m in _re.finditer(rf"\b{kw}\s+#(\d+)", description or "", _re.IGNORECASE):
                existing_refs.add(int(m.group(1)))
        new_refs = [n for n in closes_issues if n not in existing_refs]
        if new_refs:
            description = (description or "").rstrip() + "\n\nCloses " + ", ".join(f"#{n}" for n in new_refs)

    args = [
        "pr", "create",
        *_repo_arg(repo_info),
        "--head", source_branch,
        "--base", target_branch,
        "--title", title,
        "--body", description,
    ]

    if draft:
        args.append("--draft")

    for label in (labels or []):
        args += ["--label", label]

    for reviewer in (reviewers or []):
        args += ["--reviewer", reviewer]

    try:
        cp = gh_exec(args, debug=debug, check=True, timeout_sec=300)
        pr_url = cp.stdout.strip()

        # Extract PR number from URL
        pr_number = None
        if pr_url:
            m = re.search(r"/pull/(\d+)$", pr_url)
            if m:
                pr_number = int(m.group(1))

        if pr_number is None:
            return {"ok": False, "error": f"Could not extract PR number from output: {pr_url}"}

        return {
            "ok": True,
            "pr_id": str(pr_number),
            "pr_url": pr_url,
        }

    except CommandError as e:
        return {"ok": False, "error": str(e)}


def get_pr_status(
    repo_info: dict,
    pr_id: str,
    *,
    debug: bool = False,
) -> dict[str, Any] | None:
    """Get the current status of a PR."""
    try:
        cp = gh_exec(
            [
                "pr", "view", pr_id,
                *_repo_arg(repo_info),
                "--json", "number,title,url,state,headRefName,baseRefName,mergeable,mergeStateStatus,isDraft,reviewDecision",
            ],
            debug=debug,
            check=True,
        )
        return json.loads(cp.stdout) if cp.stdout.strip() else None
    except (CommandError, json.JSONDecodeError):
        return None


def _edit_pr(
    repo_info: dict,
    pr_id: str,
    items: list[str],
    flag: str,
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    """Add items to a PR via gh pr edit. Returns (ok, err)."""
    if not items:
        return True, ""
    args = ["pr", "edit", pr_id, *_repo_arg(repo_info)]
    for item in items:
        args += [flag, item]
    try:
        gh_exec(args, debug=debug, check=True)
        return True, ""
    except CommandError as e:
        return False, str(e)


def add_labels(
    repo_info: dict,
    pr_id: str,
    labels: list[str],
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    """Add labels to a PR."""
    return _edit_pr(repo_info, pr_id, labels, "--add-label", debug=debug)


def add_reviewers(
    repo_info: dict,
    pr_id: str,
    reviewers: list[str],
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    """Add reviewers to a PR."""
    return _edit_pr(repo_info, pr_id, reviewers, "--add-reviewer", debug=debug)


def set_auto_complete(
    repo_info: dict,
    pr_id: str,
    *,
    squash: bool = False,                          # deprecated alias
    merge_method: str | None = None,               # "squash" | "merge" | "rebase"
    delete_source_branch: bool = False,
    debug: bool = False,
) -> tuple[bool, str]:
    """Enable auto-merge (GitHub equivalent of auto-complete).

    ``merge_method`` takes precedence over the deprecated ``squash`` flag.
    """
    # Resolve merge method — merge_method wins; fall back to squash flag
    if merge_method is None:
        merge_method = "squash" if squash else "merge"
    if merge_method not in ("squash", "merge", "rebase"):
        return False, f"invalid merge_method: {merge_method!r}; expected squash|merge|rebase"
    flag_map = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}
    args = ["pr", "merge", pr_id, *_repo_arg(repo_info), "--auto", flag_map[merge_method]]
    if delete_source_branch:
        args.append("--delete-branch")
    try:
        gh_exec(args, debug=debug, check=True, timeout_sec=300)
        return True, ""
    except CommandError as e:
        return False, str(e)


def update_pr(
    repo_info: dict,
    pr_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    debug: bool = False,
) -> tuple[bool, str]:
    """Edit a PR's title and body."""
    if title is None and description is None:
        return True, ""
    args = ["pr", "edit", pr_id, *_repo_arg(repo_info)]
    if title is not None:
        args += ["--title", title]
    if description is not None:
        args += ["--body", description]
    try:
        gh_exec(args, debug=debug, check=True, timeout_sec=300)
        return True, ""
    except CommandError as e:
        return False, str(e)


def set_draft(repo_info: dict, pr_id: str, draft: bool, *, debug: bool = False) -> tuple[bool, str]:
    """Toggle PR draft state. draft=False -> mark ready; draft=True -> mark draft (gh 2.40+)."""
    args = ["pr", "ready", pr_id, *_repo_arg(repo_info)]
    if draft:
        # `gh pr ready --undo` marks a PR as draft (requires gh >= 2.40)
        args.append("--undo")
    try:
        gh_exec(args, debug=debug, check=True)
        return True, ""
    except CommandError as e:
        return False, str(e)
