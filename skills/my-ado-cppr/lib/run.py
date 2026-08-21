#!/usr/bin/env python3
# /// script
# dependencies = []
# requires-python = ">=3.11"
# ///
"""CLI entry point for commit-push-pr.

Usage:
    uv run ~/.claude/skills/my-ado-cppr/lib/run.py probe [--provider ado|github]
    uv run ~/.claude/skills/my-ado-cppr/lib/run.py apply [--resume] <<'PLAN'
    {...plan JSON...}
    PLAN
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
_lib_dir = Path(__file__).parent
if str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))

import ado
import cli_exec
import git
import github
import state


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

PROTECTED_BRANCHES = {"main", "master", "develop"}

PR_TEMPLATE_PATHS = [
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/pull_request_template.md",
    "docs/PULL_REQUEST_TEMPLATE.md",
    "docs/pull_request_template.md",
    ".azuredevops/PULL_REQUEST_DESCRIPTION.md",
    ".azuredevops/pull_request_template.md",
    "PULL_REQUEST_TEMPLATE.md",
]

CODEOWNERS_PATHS = [
    ".github/CODEOWNERS",
    "CODEOWNERS",
    "docs/CODEOWNERS",
    ".azuredevops/CODEOWNERS",
]


def _debug_flag(args: argparse.Namespace) -> bool:
    """Resolve debug flag from CLI args and environment."""
    return getattr(args, "debug", False) or os.environ.get("CPR_DEBUG", "").lower() in {"1", "true", "yes"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -----------------------------------------------------------------------------
# Build detection (advisory)
# -----------------------------------------------------------------------------


def _detect_build_command() -> str | None:
    """Detect a build command from project files in the current directory."""
    cwd = Path.cwd()

    if (cwd / "package.json").exists():
        if (cwd / "pnpm-lock.yaml").exists():
            return "rtk pnpm run build"
        return "rtk npm run build"

    if (cwd / "Cargo.toml").exists():
        return "rtk cargo check"

    if glob.glob("*.[cf]sproj", root_dir=str(cwd)) or glob.glob("*.sln", root_dir=str(cwd)):
        return "rtk dotnet build"

    return None


# -----------------------------------------------------------------------------
# Provider resolution
# -----------------------------------------------------------------------------


def _get_provider_by_name(name: str):
    if name == "ado":
        return ado
    if name == "github":
        return github
    raise ValueError(f"Unknown provider: {name}")


def _detect_provider(remote_url: str):
    if ado.detect(remote_url):
        return ado
    if github.detect(remote_url):
        return github
    return None


def resolve_provider(remote_url: str, provider_name: str | None = None):
    """Resolve provider from explicit name or auto-detect.

    Returns (provider_module, error_message). On success error_message is None.
    """
    if provider_name:
        try:
            return _get_provider_by_name(provider_name), None
        except ValueError as e:
            return None, str(e)
    prov = _detect_provider(remote_url)
    if prov is None:
        return None, f"Could not detect provider for: {remote_url}. Use --provider ado or --provider github"
    return prov, None


# -----------------------------------------------------------------------------
# Probe helpers
# -----------------------------------------------------------------------------


def _safe(call, default=None):
    """Run a zero-arg callable; on any exception return `default`."""
    try:
        return call()
    except Exception:
        return default


def _read_first(paths: list[str], *, max_chars: int = 2000) -> dict | None:
    """Find the first existing path and return {path, content[:max_chars]} or None."""
    cwd = Path.cwd()
    for p in paths:
        fp = cwd / p
        if fp.exists() and fp.is_file():
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            return {"path": p, "content": content[:max_chars]}
    return None


def _git_config(key: str) -> str:
    """Return `git config <key>` or empty string on failure."""
    try:
        cp = git._run(["config", "--get", key], check=False)
        return cp.stdout.strip()
    except Exception:
        return ""


def _branch_naming_hint() -> str | None:
    """Pick a common branch prefix from recent local branches."""
    try:
        cp = git._run(
            [
                "for-each-ref",
                "refs/heads",
                "--sort=-committerdate",
                "--format=%(refname:short)",
                "--count=20",
            ],
            check=False,
        )
    except Exception:
        return None
    if cp.returncode != 0:
        return None
    branches = [b for b in cp.stdout.splitlines() if b.strip()]
    # Find any prefix ending in '/'
    prefixes: dict[str, int] = {}
    for b in branches:
        if "/" in b:
            prefixes[b.split("/", 1)[0] + "/"] = prefixes.get(b.split("/", 1)[0] + "/", 0) + 1
    if not prefixes:
        return None
    top = max(prefixes.items(), key=lambda kv: kv[1])
    return top[0] if top[1] >= 2 else None


def _normalize_existing_prs(prov, raw_prs: list[dict]) -> list[dict]:
    """Normalize provider-specific PR objects to a uniform shape."""
    out: list[dict] = []
    if prov.NAME == "ado":
        for p in raw_prs:
            out.append({
                "id": str(p.get("pullRequestId") or ""),
                "title": p.get("title") or "",
                "url": _ado_pr_url(p),
                "source_branch": _strip_refs(p.get("sourceRefName") or ""),
                "target_branch": _strip_refs(p.get("targetRefName") or ""),
                "draft": bool(p.get("isDraft", False)),
                "status": p.get("status") or "",
            })
    else:
        for p in raw_prs:
            out.append({
                "id": str(p.get("number") or ""),
                "title": p.get("title") or "",
                "url": p.get("url") or "",
                "source_branch": p.get("headRefName") or "",
                "target_branch": p.get("baseRefName") or "",
                "draft": bool(p.get("isDraft", False)),
                "status": p.get("state") or "",
            })
    return out


def _strip_refs(ref: str) -> str:
    return ref.removeprefix("refs/heads/")


def _ado_pr_url(pr_obj: dict) -> str:
    """Best-effort web URL from an ADO PR object."""
    repo = pr_obj.get("repository") or {}
    web_url = (repo.get("webUrl") or "")
    pr_id = pr_obj.get("pullRequestId")
    if web_url and pr_id:
        return f"{web_url}/pullrequest/{pr_id}"
    return ""


def _state_for_probe(repo_root: str, current_branch: str) -> dict:
    """Inspect the state file and decide if it's stale relative to current branch/HEAD."""
    st = state.load(repo_root=repo_root)
    if st is None:
        return {"present": False, "branch": None, "done_keys": [], "head_at_start": None,
                "stale": False, "stale_reason": None}

    stored_branch = st.get("branch")
    head_at_start = st.get("head_at_start")
    stale = False
    stale_reason: str | None = None

    if stored_branch and stored_branch != current_branch:
        stale = True
        stale_reason = f"state branch '{stored_branch}' != current '{current_branch}'"
    elif head_at_start:
        try:
            if not git.is_ancestor(head_at_start, "HEAD"):
                stale = True
                stale_reason = f"state head_at_start {head_at_start[:8]} not reachable from HEAD"
        except Exception:
            pass

    return {
        "present": True,
        "branch": stored_branch,
        "done_keys": sorted(list((st.get("done") or {}).keys())),
        "head_at_start": head_at_start,
        "stale": stale,
        "stale_reason": stale_reason,
    }


# -----------------------------------------------------------------------------
# Probe
# -----------------------------------------------------------------------------


def probe(*, provider_name: str | None = None, debug: bool = False) -> dict[str, Any]:
    """Collect context for planning."""
    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    # --- Git basics (must succeed) ---
    try:
        repo_root = git.git_root()
        branch = git.current_branch()
        origin = git.remote_origin_url()
    except Exception as e:
        return {
            "ok": False,
            "blockers": [f"Not in a git repository or git unavailable: {e}"],
            "warnings": [],
            "notes": [],
        }

    # --- Detached HEAD ---
    detached = _safe(git.is_detached_head, default=False)
    if detached:
        blockers.append("HEAD is detached. Check out a branch first.")

    # --- Provider ---
    prov, prov_err = resolve_provider(origin, provider_name)
    if prov is None:
        return {"ok": False, "blockers": [prov_err], "warnings": warnings, "notes": notes,
                "git": {"branch": branch, "remote_url": origin}}

    # --- pwsh blocker (Windows Git Bash + ADO) ---
    if prov.NAME == "ado" and cli_exec.is_windows_posix_shell() and shutil.which("pwsh") is None:
        blockers.append(
            "pwsh not on PATH — required to run `az` cleanly under Git Bash on Windows. "
            "Install: winget install Microsoft.PowerShell"
        )

    # --- Parse remote ---
    try:
        repo_info = prov.parse_remote(origin)
    except ValueError as e:
        warnings.append(f"Could not parse remote URL: {e}")
        repo_info = {"owner": "", "repo": "", "project": None, "organization_url": None}

    # --- Auth + identity ---
    auth_ok, auth_account = prov.check_auth(debug=debug)
    if not auth_ok:
        blockers.append(f"Not authenticated. Run: {prov.AUTH_REMEDY}")

    provider_login: str | None = None
    if auth_account:
        if prov.NAME == "ado":
            user = (auth_account.get("user") or {})
            provider_login = user.get("name") or auth_account.get("name")
        else:
            provider_login = auth_account.get("login") or auth_account.get("name")

    identity = {
        "git_name": _git_config("user.name"),
        "git_email": _git_config("user.email"),
        "provider_login": provider_login,
    }
    if prov.NAME == "ado" and auth_account:
        identity["tenant_id"] = auth_account.get("tenantId")
        identity["subscription_name"] = auth_account.get("name")

    # --- Default branch (try API, then local ref) ---
    default_branch = None
    default_branch_source: str | None = None
    if auth_ok:
        try:
            default_branch = prov.get_default_branch(repo_info, debug=debug)
            if default_branch:
                default_branch_source = "api"
        except Exception as e:
            warnings.append(f"get_default_branch failed: {e}")

    if not default_branch:
        try:
            cp = git._run(["symbolic-ref", "refs/remotes/origin/HEAD"], check=False)
            if cp.returncode == 0:
                ref = cp.stdout.strip()
                if ref.startswith("refs/remotes/origin/"):
                    default_branch = ref.removeprefix("refs/remotes/origin/")
                    default_branch_source = "local-ref"
        except Exception:
            pass
    if not default_branch:
        default_branch_source = "unknown"

    # --- Existing PRs (normalized) ---
    existing_prs: list[dict] = []
    if auth_ok and branch:
        try:
            raw = prov.list_active_prs(repo_info, branch, debug=debug)
            existing_prs = _normalize_existing_prs(prov, raw)
        except Exception as e:
            warnings.append(f"list_active_prs failed: {e}")

    # --- Git diff / status ---
    status = _safe(git.status_porcelain, default=[])
    staged_list, unstaged_list, untracked_list = git._split_porcelain(status)
    ds = _safe(git.diff_stat, default={"files": 0, "insertions": 0, "deletions": 0})
    changed = sorted(set(staged_list) | set(unstaged_list) | set(untracked_list))

    if not status:
        notes.append(
            "Working tree clean. This blocks plans with commit.do=true. "
            "It does NOT block plans with pr.action='update' (label add, description edit, etc.)."
        )

    # --- Protected branch (warning, not blocker — apply still re-checks) ---
    if branch in PROTECTED_BRANCHES:
        warnings.append(
            f"On protected branch '{branch}'. Plan MUST include branch.create with a feature branch name "
            f"if you intend to commit; pure pr.action='update' is fine."
        )

    # --- Suggestions ---
    suggestions = {
        "build_command": _detect_build_command(),
        "pr_template": _read_first(PR_TEMPLATE_PATHS),
        "codeowners": _read_first(CODEOWNERS_PATHS),
        "branch_naming_hint": _branch_naming_hint(),
    }

    # --- State (for resume guidance) ---
    state_info = _state_for_probe(repo_root, branch)

    return {
        "ok": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "notes": notes,
        "provider": prov.NAME,
        "identity": identity,
        "git": {
            "branch": branch,
            "remote_url": origin,
            "detached_head": detached,
            "status_porcelain": status,
            "staged": staged_list,
            "unstaged": unstaged_list,
            "untracked": untracked_list,
            "diff_stat": ds,
            "changed_files": changed,
            "recent_commits": git.recent_commits(count=5),
        },
        "repo": {
            "owner": repo_info.get("owner", ""),
            "project": repo_info.get("project"),
            "name": repo_info.get("repo", ""),
            "organization_url": repo_info.get("organization_url"),
            "default_branch": default_branch,
            "default_branch_source": default_branch_source,
            "existing_prs": existing_prs,
        },
        "suggestions": suggestions,
        "state": state_info,
        # Back-compat alias (also at top level):
        "build_command": suggestions["build_command"],
    }


# -----------------------------------------------------------------------------
# Apply helpers
# -----------------------------------------------------------------------------


def _result_envelope(repo_info: dict, prov_name: str, repo_root: str, branch: str) -> dict:
    artifacts: dict = {
        "repo_root": repo_root,
        "branch": branch,
        "provider": prov_name,
        "owner": repo_info.get("owner", ""),
        "repo": repo_info.get("repo", ""),
    }
    if repo_info.get("project"):
        artifacts["project"] = repo_info["project"]
    if repo_info.get("organization_url"):
        artifacts["organization_url"] = repo_info["organization_url"]
    return {
        "ok": True,
        "meta": {"schema": "commit-push-pr/result/v1", "generated_at": _now_iso()},
        "steps": [],
        "artifacts": artifacts,
    }


def _is_warning_step(step: dict) -> bool:
    return step.get("severity") == "warning"


def _step_failed_hard(step: dict) -> bool:
    return (not step.get("ok", True)) and not _is_warning_step(step)


def _finalize_result(result: dict) -> None:
    """Synthesize ok, error, summary, headline at the end of apply()."""
    steps = result.get("steps", [])

    # ok = no hard failures
    result["ok"] = not any(_step_failed_hard(s) for s in steps)

    # Synthesize result.error from failed hard steps
    if not result["ok"]:
        parts = [
            f"{s.get('name', '?')}: {s.get('error', 'failed')}"
            for s in steps
            if _step_failed_hard(s)
        ]
        result["error"] = "; ".join(parts) if parts else "unspecified failure"

    art = result.get("artifacts", {})
    succeeded = [s.get("name") for s in steps if s.get("ok", True) and not _is_warning_step(s)]
    failed = [s.get("name") for s in steps if _step_failed_hard(s)]
    warnings = [s.get("name") for s in steps if _is_warning_step(s)]

    summary = {
        "pr_url": art.get("pr_url"),
        "pr_id": art.get("pr_id"),
        "branch": art.get("branch"),
        "commit_sha": art.get("commit_sha"),
        "provider": art.get("provider"),
        "succeeded": succeeded,
        "failed": failed,
        "warnings": warnings,
    }
    result["summary"] = summary

    # Headline: most-useful-first
    pr_id = art.get("pr_id")
    pr_url = art.get("pr_url")
    headline: str | None = None
    if "pr_update" in succeeded and pr_id:
        headline = f"Updated PR #{pr_id}" + (f": {pr_url}" if pr_url else "")
    elif "pr_create" in succeeded and pr_id:
        headline = f"Created PR #{pr_id}" + (f": {pr_url}" if pr_url else "")
    elif "push" in succeeded:
        headline = f"Pushed branch {art.get('branch','?')}"
    elif "commit" in succeeded and art.get("commit_sha"):
        headline = f"Committed {art.get('commit_sha','')[:8]}"

    if headline:
        result["headline"] = headline


def _validate_plan(plan: dict, prov_name: str) -> str | None:
    """Return an error string if the plan is malformed; otherwise None."""
    # Both pr and <prov>_pr present? Use 'in' so empty dict counts as present.
    other = f"{prov_name}_pr"
    if "pr" in plan and other in plan:
        return f"Both 'pr' and '{other}' present in plan; use only one."

    # If pr block exists, action must be valid
    pr_block = None
    for key in ("pr", "ado_pr", "github_pr"):
        if key in plan:
            pr_block = plan[key] or {}
            break
    if pr_block is not None:
        action = pr_block.get("action")
        if action not in ("create", "update"):
            return f"pr.action must be 'create' or 'update' (got {action!r})"
        if action == "update" and not pr_block.get("id"):
            return "pr.action='update' requires pr.id"

    # branch.create requires name
    branch_block = plan.get("branch") or {}
    if branch_block.get("create") and not branch_block.get("name"):
        return "branch.create=true requires branch.name"

    # commit.do requires message (unless amend)
    commit_block = plan.get("commit") or {}
    if commit_block.get("do") and not commit_block.get("amend"):
        if not (commit_block.get("message") or "").strip():
            return "commit.do=true requires commit.message (or commit.amend=true)"

    return None


def _resolve_pr_block(plan: dict, prov_name: str) -> dict:
    """Find the PR block (pr / ado_pr / github_pr)."""
    if plan.get("pr"):
        return plan["pr"]
    if plan.get(f"{prov_name}_pr"):
        return plan[f"{prov_name}_pr"]
    # legacy: accept either alias even when wrong provider (warning would have caught true conflict)
    return plan.get("ado_pr") or plan.get("github_pr") or {}


# -----------------------------------------------------------------------------
# Apply
# -----------------------------------------------------------------------------


def apply(
    plan: dict[str, Any],
    *,
    resume: bool = False,
    debug: bool = False,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Execute the commit-push-pr plan."""
    debug = debug or plan.get("debug", False)

    # --- Bootstrap: git context ---
    try:
        if repo_root is None:
            repo_root = git.git_root()
        branch = git.current_branch()
        origin = git.remote_origin_url()
    except Exception as e:
        return {
            "ok": False,
            "error": f"Not in a git repository or git unavailable: {e}",
            "meta": {"schema": "commit-push-pr/result/v1", "generated_at": _now_iso()},
            "steps": [],
            "artifacts": {},
        }

    # --- Provider ---
    provider_name = plan.get("provider")
    prov, prov_err = resolve_provider(origin, provider_name)
    if prov is None:
        return {
            "ok": False,
            "error": prov_err,
            "meta": {"schema": "commit-push-pr/result/v1", "generated_at": _now_iso()},
            "steps": [],
            "artifacts": {},
        }

    try:
        repo_info = prov.parse_remote(origin)
    except ValueError as e:
        return {
            "ok": False,
            "error": f"Could not parse remote: {e}",
            "meta": {"schema": "commit-push-pr/result/v1", "generated_at": _now_iso()},
            "steps": [],
            "artifacts": {},
        }

    # --- Plan validation ---
    plan_err = _validate_plan(plan, prov.NAME)
    if plan_err:
        result = _result_envelope(repo_info, prov.NAME, repo_root, branch)
        result["steps"].append({"name": "validate_plan", "ok": False, "error": plan_err})
        _finalize_result(result)
        return result

    # --- Capture HEAD before any writes (for state staleness + nothing-to-commit detection) ---
    pre_head: str | None = None
    try:
        pre_head = git.head_sha()
    except Exception:
        pre_head = None

    # --- State (resume) ---
    st = None
    if resume:
        st = state.load(repo_root=repo_root)

    # Staleness check
    result = _result_envelope(repo_info, prov.NAME, repo_root, branch)

    if resume and st is None:
        result["steps"].append({
            "name": "resume",
            "ok": False,
            "severity": "warning",
            "error": "state missing or corrupt; starting fresh",
        })
        st = None

    if st is not None:
        stored_branch = st.get("branch")
        head_at_start = st.get("head_at_start")
        stale_reason: str | None = None
        if stored_branch and stored_branch != branch:
            stale_reason = f"state branch '{stored_branch}' != current '{branch}'"
        elif head_at_start:
            try:
                if not git.is_ancestor(head_at_start, "HEAD"):
                    stale_reason = f"state head_at_start {head_at_start[:8]} not reachable from HEAD"
            except Exception:
                pass
        if stale_reason:
            result["steps"].append({
                "name": "resume",
                "ok": False,
                "severity": "warning",
                "error": f"state stale: {stale_reason}; starting fresh",
            })
            st = None

    if st is None:
        st = state.new_state(
            provider=prov.NAME,
            remote_url=origin,
            branch=branch,
            head_at_start=pre_head,
        )

    # --- Preflight: auth always re-checked (tokens expire) ---
    auth_ok, _account = prov.check_auth(debug=debug)
    if not auth_ok:
        result["steps"].append({
            "name": "preflight",
            "ok": False,
            "error": f"Not authenticated. Run: {prov.AUTH_REMEDY}",
        })
        _finalize_result(result)
        state.save(st, repo_root=repo_root)
        return result

    # --- Preflight: protected branch (always re-checked, even on resume) ---
    branch_plan = plan.get("branch") or {}
    if branch in PROTECTED_BRANCHES and not branch_plan.get("create"):
        # Allow protected-branch operations when commit.do is false (pure PR update flows)
        commit_plan = plan.get("commit") or {}
        if commit_plan.get("do"):
            result["steps"].append({
                "name": "preflight",
                "ok": False,
                "error": f"On protected branch '{branch}' but plan does not include branch.create",
            })
            _finalize_result(result)
            state.save(st, repo_root=repo_root)
            return result

    result["steps"].append({"name": "preflight", "ok": True})

    # --- Branch Creation ---
    if branch_plan.get("create"):
        if not st["done"].get("branch_create"):
            try:
                new_branch = branch_plan.get("name")
                # _validate_plan already caught missing name; defensive only
                if not new_branch:
                    raise ValueError("branch.name is required when branch.create is true")

                try:
                    git.create_branch(new_branch)
                except git.GitError:
                    git.checkout(new_branch)

                branch = new_branch
                result["artifacts"]["branch"] = branch
                st["branch"] = branch  # update state's branch too

                st["done"]["branch_create"] = True
                st["artifacts"]["branch"] = branch
                result["steps"].append({"name": "branch_create", "ok": True, "branch": new_branch})
                state.save(st, repo_root=repo_root)

            except (git.GitError, ValueError) as e:
                result["steps"].append({"name": "branch_create", "ok": False, "error": str(e)})
                _finalize_result(result)
                state.save(st, repo_root=repo_root)
                return result
        else:
            # Resumed
            new_branch = branch_plan.get("name") or st["artifacts"].get("branch")
            if new_branch:
                try:
                    if git.current_branch() != new_branch:
                        git.checkout(new_branch)
                except git.GitError as e:
                    result["steps"].append({"name": "branch_create", "ok": False,
                                            "error": f"resumed checkout failed: {e}"})
                    _finalize_result(result)
                    state.save(st, repo_root=repo_root)
                    return result
                branch = new_branch
                result["artifacts"]["branch"] = branch
            result["steps"].append({"name": "branch_create", "ok": True,
                                    "branch": branch, "resumed": True})

    # --- Commit ---
    commit_plan = plan.get("commit") or {}
    if commit_plan.get("do"):
        if not st["done"].get("commit"):
            try:
                msg = str(commit_plan.get("message") or "").strip()
                amend = bool(commit_plan.get("amend"))
                paths = commit_plan.get("paths") or []

                if amend and not msg:
                    # --amend --no-edit
                    msg = ""

                cli_exec.breadcrumb("committing...")
                if paths:
                    sha = git.commit_with_paths(msg, [str(p) for p in paths], amend=amend)
                else:
                    sha = git.commit(
                        msg,
                        stage_all_first=bool(commit_plan.get("stage_all", True)),
                        amend=amend,
                    )

                result["artifacts"]["commit_sha"] = sha
                st["artifacts"]["commit_sha"] = sha
                st["done"]["commit"] = True
                result["steps"].append({"name": "commit", "ok": True, "sha": sha})
                state.save(st, repo_root=repo_root)

            except (git.GitError, ValueError) as e:
                result["steps"].append({"name": "commit", "ok": False, "error": str(e)})
                _finalize_result(result)
                state.save(st, repo_root=repo_root)
                return result
        else:
            sha = st["artifacts"].get("commit_sha", "")
            result["artifacts"]["commit_sha"] = sha
            result["steps"].append({"name": "commit", "ok": True, "sha": sha, "resumed": True})

    # --- Push ---
    push_plan = plan.get("push") or {}
    if push_plan.get("do"):
        if not st["done"].get("push"):
            try:
                cli_exec.breadcrumb("pushing...")
                git.push(
                    branch=branch,
                    set_upstream=bool(push_plan.get("set_upstream", True)),
                    force_with_lease=bool(push_plan.get("force_with_lease", False)),
                    remote=str(push_plan.get("remote", "origin")),
                )
                st["done"]["push"] = True
                result["steps"].append({"name": "push", "ok": True})
                state.save(st, repo_root=repo_root)

            except git.GitError as e:
                hint = ""
                if "non-fast-forward" in str(e).lower() or "rejected" in str(e).lower():
                    hint = " (hint: try push.force_with_lease=true if you rewrote history)"
                result["steps"].append({
                    "name": "push", "ok": False,
                    "error": f"{e}{hint}",
                })
                _finalize_result(result)
                state.save(st, repo_root=repo_root)
                return result
        else:
            result["steps"].append({"name": "push", "ok": True, "resumed": True})

    # --- PR section ---
    pr_plan = _resolve_pr_block(plan, prov.NAME)
    pr_action = pr_plan.get("action")
    pr_id: str | None = None

    # Resolve merge_method (with squash back-compat)
    merge_method = pr_plan.get("merge_method")
    if merge_method is None and pr_plan.get("squash"):
        merge_method = "squash"

    # --- PR Update branch ---
    if pr_action == "update":
        pr_id = str(pr_plan.get("id") or "")
        if not pr_id:
            # caught by _validate_plan but defensive
            result["steps"].append({"name": "pr_update", "ok": False, "error": "pr.id is required for update"})
            _finalize_result(result)
            state.save(st, repo_root=repo_root)
            return result
        result["artifacts"]["pr_id"] = pr_id

        # Title / description update
        title = pr_plan.get("title")
        description = pr_plan.get("description")
        if (title is not None or description is not None) and not st["done"].get("pr_update"):
            cli_exec.breadcrumb("updating PR...")
            ok, err = prov.update_pr(repo_info, pr_id, title=title, description=description, debug=debug)
            if ok:
                st["done"]["pr_update"] = True
                result["steps"].append({"name": "pr_update", "ok": True})
            else:
                result["steps"].append({"name": "pr_update", "ok": False, "error": err or "update_pr failed"})
            state.save(st, repo_root=repo_root)

        # Draft toggle
        draft_pref = pr_plan.get("draft")
        if draft_pref is not None and not st["done"].get("pr_draft_toggle"):
            ok, err = prov.set_draft(repo_info, pr_id, bool(draft_pref), debug=debug)
            if ok:
                st["done"]["pr_draft_toggle"] = True
                result["steps"].append({"name": "pr_draft_toggle", "ok": True, "draft": bool(draft_pref)})
            else:
                result["steps"].append({"name": "pr_draft_toggle", "ok": False,
                                        "error": err or "set_draft failed"})
            state.save(st, repo_root=repo_root)

        # Populate pr_url from status lookup
        try:
            pr_status = prov.get_pr_status(repo_info, pr_id, debug=debug)
            if pr_status:
                url = pr_status.get("url")
                if not url and prov.NAME == "ado":
                    url = _ado_pr_url(pr_status)
                if url:
                    result["artifacts"]["pr_url"] = url
                    st["artifacts"]["pr_url"] = url
        except Exception:
            pass

    elif pr_action == "create" and st["done"].get("pr_create"):
        # Resumed create
        pr_id = st["artifacts"].get("pr_id")
        pr_url = st["artifacts"].get("pr_url")
        if not pr_id:
            result["steps"].append({"name": "pr_create", "ok": False, "error": "Resumed but pr_id missing"})
            _finalize_result(result)
            state.save(st, repo_root=repo_root)
            return result
        result["artifacts"]["pr_id"] = pr_id
        if pr_url:
            result["artifacts"]["pr_url"] = pr_url
        result["steps"].append({"name": "pr_create", "ok": True, "pr_id": pr_id, "pr_url": pr_url, "resumed": True})

    elif pr_action == "create":
        cli_exec.breadcrumb("creating PR...")
        provider_args = {}
        if prov.NAME == "github":
            provider_args = {
                "labels": pr_plan.get("labels"),
                "reviewers": pr_plan.get("reviewers"),
                "closes_issues": pr_plan.get("closes_issues"),
            }
        pr_result = prov.create_pr(
            repo_info,
            source_branch=pr_plan.get("source_branch") or branch,
            target_branch=pr_plan.get("target_branch") or "main",
            title=pr_plan.get("title") or "",
            description=pr_plan.get("description") or "",
            draft=bool(pr_plan.get("draft", False)),
            debug=debug,
            **provider_args,
        )

        if not pr_result.get("ok"):
            result["steps"].append({"name": "pr_create", "ok": False,
                                    "error": pr_result.get("error", "PR creation failed")})
            _finalize_result(result)
            state.save(st, repo_root=repo_root)
            return result

        pr_id = pr_result.get("pr_id")
        pr_url = pr_result.get("pr_url")
        result["artifacts"]["pr_id"] = pr_id
        if pr_url:
            result["artifacts"]["pr_url"] = pr_url
        st["artifacts"]["pr_id"] = pr_id
        st["artifacts"]["pr_url"] = pr_url
        st["done"]["pr_create"] = True
        result["steps"].append({"name": "pr_create", "ok": True, "pr_id": pr_id, "pr_url": pr_url})
        state.save(st, repo_root=repo_root)

    # --- ADO labels: surface as warning on create (since create_pr drops them) ---
    labels = pr_plan.get("labels") or []
    if labels and pr_action == "create" and prov.NAME == "ado":
        result["steps"].append({
            "name": "pr_labels", "ok": False, "severity": "warning",
            "labels": labels,
            "error": ado.LABELS_UNSUPPORTED,
        })

    # --- Reviewers (post-create, or update) ---
    reviewers = pr_plan.get("reviewers") or []
    # GitHub applies reviewers during create_pr; ADO deliberately defers them
    # to its reviewer API, so a newly-created ADO PR still needs this step.
    should_add_reviewers = pr_action != "create" or prov.NAME == "ado"
    if reviewers and pr_id and should_add_reviewers and not st["done"].get("pr_reviewers"):
        ok, err = prov.add_reviewers(repo_info, pr_id, reviewers, debug=debug)
        if not ok:
            result["steps"].append({"name": "pr_reviewers", "ok": False,
                                    "reviewers": reviewers, "error": err or "add_reviewers failed"})
            _finalize_result(result)
            state.save(st, repo_root=repo_root)
            return result
        st["done"]["pr_reviewers"] = True
        result["steps"].append({"name": "pr_reviewers", "ok": True, "reviewers": reviewers})
        state.save(st, repo_root=repo_root)

    # --- Auto-complete ---
    if pr_plan.get("auto_complete") and pr_id and not st["done"].get("pr_auto_complete"):
        cli_exec.breadcrumb("enabling auto-complete...")
        if prov.NAME == "github":
            ok, err = prov.set_auto_complete(
                repo_info, pr_id,
                merge_method=merge_method or ("squash" if pr_plan.get("squash") else "merge"),
                delete_source_branch=bool(pr_plan.get("delete_source_branch", False)),
                debug=debug,
            )
        else:
            ok, err = prov.set_auto_complete(
                repo_info, pr_id,
                squash=bool((merge_method or ("squash" if pr_plan.get("squash") else "")) == "squash"),
                delete_source_branch=bool(pr_plan.get("delete_source_branch", False)),
                transition_work_items=bool(pr_plan.get("transition_work_items", False)),
                debug=debug,
            )
        if ok:
            st["done"]["pr_auto_complete"] = True
            result["steps"].append({"name": "pr_auto_complete", "ok": True})
        else:
            result["steps"].append({"name": "pr_auto_complete", "ok": False, "error": err or "set_auto_complete failed"})
        state.save(st, repo_root=repo_root)

    # --- Work Items (ADO) ---
    work_items = pr_plan.get("work_item_ids") or []
    if prov.NAME == "ado" and work_items and pr_id and not st["done"].get("pr_work_items"):
        cli_exec.breadcrumb("linking work items...")
        ok, err = prov.link_work_items(repo_info, pr_id, work_items, debug=debug)
        if ok:
            st["done"]["pr_work_items"] = True
            result["steps"].append({"name": "pr_work_items", "ok": True, "work_item_ids": work_items})
        else:
            result["steps"].append({"name": "pr_work_items", "ok": False, "error": err or "link_work_items failed"})
        state.save(st, repo_root=repo_root)

    # --- Approve (ADO) ---
    if prov.NAME == "ado" and pr_plan.get("approve") and pr_id and not st["done"].get("pr_approve"):
        cli_exec.breadcrumb("approving PR...")
        ok, err = prov.approve_pr(repo_info, pr_id, debug=debug)
        if ok:
            st["done"]["pr_approve"] = True
            result["steps"].append({"name": "pr_approve", "ok": True})
        else:
            result["steps"].append({"name": "pr_approve", "ok": False, "error": err or "approve_pr failed"})
        state.save(st, repo_root=repo_root)

    # --- Labels (GitHub on update, or post-create resume) ---
    if labels and pr_id and pr_action != "create" and not st["done"].get("pr_labels"):
        if prov.NAME == "ado":
            result["steps"].append({
                "name": "pr_labels", "ok": False, "severity": "warning",
                "labels": labels, "error": ado.LABELS_UNSUPPORTED,
            })
        else:
            ok, err = prov.add_labels(repo_info, pr_id, labels, debug=debug)
            if ok:
                st["done"]["pr_labels"] = True
                result["steps"].append({"name": "pr_labels", "ok": True, "labels": labels})
            else:
                result["steps"].append({"name": "pr_labels", "ok": False,
                                        "labels": labels, "error": err or "add_labels failed"})
        state.save(st, repo_root=repo_root)

    # --- Inline verify (always recorded as its own step) ---
    if pr_id:
        try:
            pr_status = prov.get_pr_status(repo_info, pr_id, debug=debug)
            if pr_status is not None:
                result["pr_status"] = pr_status
                result["steps"].append({"name": "pr_verify", "ok": True})
            else:
                result["steps"].append({"name": "pr_verify", "ok": False,
                                        "severity": "warning",
                                        "error": "get_pr_status returned None"})
        except Exception as e:
            result["steps"].append({"name": "pr_verify", "ok": False,
                                    "severity": "warning",
                                    "error": f"get_pr_status raised: {e}"})

    # --- Finalize ---
    _finalize_result(result)

    # --- Persist or clear state ---
    if result["ok"]:
        # Hard success → clean up
        state.clear(repo_root=repo_root)
    else:
        state.save(st, repo_root=repo_root)

    return result


# -----------------------------------------------------------------------------
# CLI Commands
# -----------------------------------------------------------------------------


def cmd_probe(args: argparse.Namespace) -> int:
    debug = _debug_flag(args)
    try:
        result = probe(provider_name=args.provider, debug=debug)
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        return 0
    except Exception as e:
        # JSON-out contract: always emit valid JSON even on exception
        err_obj = {
            "ok": False,
            "error": str(e),
            "blockers": [str(e)],
            "warnings": [],
            "notes": [],
        }
        sys.stdout.write(json.dumps(err_obj, indent=2, ensure_ascii=False) + "\n")
        if debug:
            traceback.print_exc(file=sys.stderr)
        return 2


def cmd_apply(args: argparse.Namespace) -> int:
    debug = _debug_flag(args)

    if args.plan:
        plan_path = Path(args.plan)
        if not plan_path.exists():
            err_obj = {
                "ok": False, "error": f"Plan file not found: {plan_path}",
                "meta": {"schema": "commit-push-pr/result/v1", "generated_at": _now_iso()},
                "steps": [], "artifacts": {},
            }
            sys.stdout.write(json.dumps(err_obj, indent=2, ensure_ascii=False) + "\n")
            return 2
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            err_obj = {
                "ok": False, "error": f"Invalid JSON in plan file: {e}",
                "meta": {"schema": "commit-push-pr/result/v1", "generated_at": _now_iso()},
                "steps": [], "artifacts": {},
            }
            sys.stdout.write(json.dumps(err_obj, indent=2, ensure_ascii=False) + "\n")
            return 2
    else:
        try:
            plan = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            err_obj = {
                "ok": False, "error": f"Invalid JSON from stdin: {e}",
                "meta": {"schema": "commit-push-pr/result/v1", "generated_at": _now_iso()},
                "steps": [], "artifacts": {},
            }
            sys.stdout.write(json.dumps(err_obj, indent=2, ensure_ascii=False) + "\n")
            return 2

    try:
        result = apply(plan, resume=args.resume, debug=debug)
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        return 0 if result["ok"] else 2
    except Exception as e:
        err_obj = {
            "ok": False, "error": str(e),
            "meta": {"schema": "commit-push-pr/result/v1", "generated_at": _now_iso()},
            "steps": [], "artifacts": {},
        }
        sys.stdout.write(json.dumps(err_obj, indent=2, ensure_ascii=False) + "\n")
        if debug:
            traceback.print_exc(file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Commit, push, and create PRs for Azure DevOps and GitHub.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser("probe", help="Collect context for planning")
    probe_parser.add_argument("--provider", choices=["ado", "github"], help="Force provider")

    apply_parser = subparsers.add_parser("apply", help="Execute a plan")
    apply_parser.add_argument("plan", nargs="?", default=None, help="Plan JSON file (reads stdin if omitted)")
    apply_parser.add_argument("--resume", action="store_true", help="Resume from previous state")

    args = parser.parse_args()

    commands = {
        "probe": cmd_probe,
        "apply": cmd_apply,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
