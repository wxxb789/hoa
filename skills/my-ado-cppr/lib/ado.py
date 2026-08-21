#!/usr/bin/env python3
"""Azure DevOps provider - simplified.

All functions, no class. Duck typing for provider interface.
"""

from __future__ import annotations

import json
import re
from typing import Any

from cli_exec import CommandError, az_exec


NAME = "ado"
AUTH_REMEDY = "az login"
LABELS_UNSUPPORTED = (
    "ADO labels require REST API call (PATCH /pullRequests/{id}/labels); "
    "not yet wired in this skill. Add manually in the PR web UI."
)


def detect(remote_url: str) -> bool:
    """Check if URL is an Azure DevOps URL."""
    return bool(re.search(
        r"(?:dev\.azure\.com|ssh\.dev\.azure\.com|[^.]+\.visualstudio\.com)[/:]",
        remote_url,
    ))


def parse_remote(remote_url: str) -> dict[str, Any]:
    """Parse Azure DevOps remote URL. Returns repo info dict.

    Supports:
    - https://dev.azure.com/<org>/<project>/_git/<repo>
    - https://<user>@dev.azure.com/<org>/<project>/_git/<repo>
    - git@ssh.dev.azure.com:v3/<org>/<project>/<repo>
    - https://<org>.visualstudio.com/<project>/_git/<repo>
    """
    patterns = [
        r"https://(?:[^@]+@)?dev\.azure\.com/([^/]+)/([^/]+)/_git/([^/]+?)(?:\.git)?$",
        r"git@ssh\.dev\.azure\.com:v3/([^/]+)/([^/]+)/([^/]+?)(?:\.git)?$",
        # Old-style visualstudio.com URLs, with optional /DefaultCollection/ segment
        r"https://([^.]+)\.visualstudio\.com/(?:DefaultCollection/)?([^/]+)/_git/([^/]+?)(?:\.git)?$",
    ]

    for pat in patterns:
        m = re.match(pat, remote_url)
        if m:
            org, project, repo = m.groups()
            return {
                "provider": NAME,
                "remote_url": remote_url,
                "owner": org,
                "repo": repo,
                "project": project,
                "organization_url": f"https://dev.azure.com/{org}",
            }

    raise ValueError(f"Could not parse Azure DevOps remote URL: {remote_url}")


def _org_args(repo_info: dict) -> list[str]:
    """Args for commands that only accept --organization (not --project).

    Used by: pr show, pr update, pr set-vote, pr work-item add.
    """
    return ["--organization", repo_info.get("organization_url", "")]


def _orgproj_args(repo_info: dict) -> list[str]:
    """Common args for --organization and --project.

    Only for commands that accept both flags (repos show, pr list, pr create).
    """
    return [*_org_args(repo_info), "--project", repo_info.get("project", "")]


def check_auth(*, debug: bool = False) -> tuple[bool, dict | None]:
    """Return (is_authenticated, account_dict | None).

    account_dict has at least: id, name, tenantId (from `az account show`).
    """
    try:
        cp = az_exec(["account", "show", "-o", "json"], debug=debug, check=True)
        try:
            data = json.loads(cp.stdout) if cp.stdout.strip() else {}
        except json.JSONDecodeError:
            data = {}
        return True, (data or None)
    except CommandError:
        return False, None


def get_default_branch(repo_info: dict, *, debug: bool = False) -> str | None:
    """Get the default branch from Azure DevOps."""
    try:
        cp = az_exec(
            [
                "repos", "show",
                "--repository", repo_info["repo"],
                *_orgproj_args(repo_info),
                "--query", "defaultBranch",
                "-o", "tsv",
            ],
            debug=debug,
            check=True,
        )
        branch = cp.stdout.strip()
        branch = branch.removeprefix("refs/heads/")
        return branch or None
    except CommandError:
        return None


def list_active_prs(
    repo_info: dict,
    source_branch: str,
    *,
    debug: bool = False,
) -> list[dict[str, Any]]:
    """List active PRs for the given source branch."""
    try:
        cp = az_exec(
            [
                "repos", "pr", "list",
                "--source-branch", source_branch,
                "--repository", repo_info["repo"],
                *_orgproj_args(repo_info),
                "--status", "active",
                "-o", "json",
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
    debug: bool = False,
) -> dict[str, Any]:
    """Create a new pull request. Returns result dict.

    Labels and reviewers are handled after creation; ADO uses work-item IDs
    instead of GitHub issue-closing keywords.
    """
    args = [
        "repos", "pr", "create",
        "--repository", repo_info["repo"],
        "--source-branch", source_branch,
        "--target-branch", target_branch,
        "--title", title,
        "--description", description,
        *_orgproj_args(repo_info),
        "-o", "json",
    ]
    if draft:
        args += ["--draft", "true"]

    try:
        cp = az_exec(args, debug=debug, check=True, timeout_sec=300)
        data = json.loads(cp.stdout) if cp.stdout.strip() else {}
        pr_id = str(data.get("pullRequestId") or "")
        # Build browser URL (the API returns a REST URL, not a web URL)
        pr_url = (
            f"{repo_info.get('organization_url', '')}/{repo_info.get('project', '')}/"
            f"_git/{repo_info.get('repo', '')}/pullrequest/{pr_id}"
            if pr_id else ""
        )

        if not pr_id:
            return {"ok": False, "error": "az repos pr create did not return pullRequestId"}

        return {"ok": True, "pr_id": pr_id, "pr_url": pr_url, "raw": data}

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
        cp = az_exec(
            [
                "repos", "pr", "show",
                "--id", pr_id,
                *_org_args(repo_info),
                "-o", "json",
            ],
            debug=debug,
            check=True,
        )
        return json.loads(cp.stdout) if cp.stdout.strip() else None
    except (CommandError, json.JSONDecodeError):
        return None


def set_auto_complete(
    repo_info: dict,
    pr_id: str,
    *,
    squash: bool = False,
    delete_source_branch: bool = False,
    transition_work_items: bool = False,
    debug: bool = False,
) -> tuple[bool, str]:
    """Set auto-complete options on a PR. Returns (ok, err)."""
    args = [
        "repos", "pr", "update",
        "--id", pr_id,
        *_org_args(repo_info),
        "--auto-complete", "true",
    ]

    if squash:
        args += ["--squash", "true"]
    if delete_source_branch:
        args += ["--delete-source-branch", "true"]
    if transition_work_items:
        args += ["--transition-work-items", "true"]

    try:
        az_exec(args, debug=debug, check=True, timeout_sec=300)
        return True, ""
    except CommandError as e:
        return False, str(e)


def link_work_items(
    repo_info: dict,
    pr_id: str,
    work_item_ids: list[str],
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    """Link work items to a PR. Returns (ok, err)."""
    if not work_item_ids:
        return True, ""

    try:
        az_exec(
            [
                "repos", "pr", "work-item", "add",
                "--id", pr_id,
                *_org_args(repo_info),
                "--work-items", *[str(w) for w in work_item_ids],
            ],
            debug=debug,
            check=True,
        )
        return True, ""
    except CommandError as e:
        return False, str(e)


def approve_pr(
    repo_info: dict,
    pr_id: str,
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    """Approve a PR (set-vote approve). Returns (ok, err)."""
    try:
        az_exec(
            [
                "repos", "pr", "set-vote",
                "--id", pr_id,
                *_org_args(repo_info),
                "--vote", "approve",
            ],
            debug=debug,
            check=True,
        )
        return True, ""
    except CommandError as e:
        return False, str(e)


def add_reviewers(
    repo_info: dict,
    pr_id: str,
    reviewers: list,
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    """Add reviewers to an ADO PR.

    Accepts either a list of strings (emails/UPNs — treated as optional
    reviewers) or a list of dicts ``{id, is_required}`` (or ``{email, ...}`` /
    ``{upn, ...}``). Strings default to optional. Required and optional
    reviewers are submitted in separate ``az repos pr reviewer add`` calls
    because ``--is-required`` applies to the whole call.
    """
    if not reviewers:
        return True, ""

    # Split into required vs optional
    required: list[str] = []
    optional: list[str] = []
    for r in reviewers:
        if isinstance(r, dict):
            ident = r.get("id") or r.get("email") or r.get("upn")
            if not ident:
                continue
            if r.get("is_required"):
                required.append(str(ident))
            else:
                optional.append(str(ident))
        else:
            optional.append(str(r))

    errors: list[str] = []
    for group, is_required in [(required, True), (optional, False)]:
        if not group:
            continue
        args = [
            "repos", "pr", "reviewer", "add",
            "--id", pr_id,
            *_org_args(repo_info),
            "--reviewers", *group,
        ]
        if is_required:
            args += ["--is-required", "true"]
        try:
            az_exec(args, debug=debug, check=True)
        except CommandError as e:
            errors.append(str(e))
    if errors:
        return False, "; ".join(errors)
    return True, ""


def update_pr(
    repo_info: dict,
    pr_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    draft: bool | None = None,
    debug: bool = False,
) -> tuple[bool, str]:
    """Update PR fields. Skips entirely if all three are None."""
    if title is None and description is None and draft is None:
        return True, ""
    args = ["repos", "pr", "update", "--id", pr_id, *_org_args(repo_info)]
    if title is not None:
        args += ["--title", title]
    if description is not None:
        args += ["--description", description]
    if draft is not None:
        args += ["--draft", "true" if draft else "false"]
    args += ["-o", "json"]
    try:
        az_exec(args, debug=debug, check=True, timeout_sec=300)
        return True, ""
    except CommandError as e:
        return False, str(e)


def set_draft(
    repo_info: dict,
    pr_id: str,
    draft: bool,
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    """Toggle PR draft state via update_pr."""
    return update_pr(repo_info, pr_id, draft=draft, debug=debug)
