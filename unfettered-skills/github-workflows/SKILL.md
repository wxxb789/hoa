---
name: github-workflows
description: "Use when doing GitHub work end-to-end with gh and git."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [github, git, gh-cli, pull-requests, issues, code-review, ci, releases]
    related_skills: []
---

# GitHub Workflows

## Overview

This umbrella covers the full GitHub task class: authenticate, inspect a repository, manage remotes/repos, create and triage issues, branch/commit/push/open PRs, monitor CI, review code, and merge/release. It replaces separate micro-skills for auth, repo management, issues, PR workflow, code review, and codebase inspection.

Prefer `gh` when authenticated. Fall back to `git` plus REST API via `curl` when `gh` is missing or unavailable.

## When to Use

- A repo needs cloning, creation, forking, remotes, branch protection, secrets, workflows, releases, or gists.
- The user asks to create/triage/label/assign/comment/close GitHub issues.
- The user asks for a branch, commit, PR, CI monitoring, merge, or release.
- The user asks to review local changes or a remote PR.
- The user asks for codebase size/language/file inspection before planning work.
- Authentication or credential setup blocks GitHub work.

## Discovery and Authentication

Start with live checks:

```bash
git --version
gh --version 2>/dev/null || echo "gh not installed"
gh auth status 2>/dev/null || echo "gh not authenticated"
git config --global credential.helper 2>/dev/null || echo "no git credential helper"
git remote -v
git status --short --branch
```

If auth is missing:
- Prefer `gh auth login` / existing token flow when the user can interact.
- For git-only HTTPS, configure a credential helper and test with `git ls-remote`.
- For SSH, check keys and remote URL before changing anything.
- Never print tokens. Do not bake tokens into remotes unless the user explicitly chooses that trade-off.

Common helpers:

```bash
git config --global credential.helper store
git config --global credential.helper 'cache --timeout=28800'
git ls-remote https://github.com/<owner>/<repo>.git
```

## Repository Management

Typical commands:

```bash
git clone https://github.com/owner/repo-name.git
git clone --depth 1 https://github.com/owner/repo-name.git
gh repo clone owner/repo-name
gh repo create my-new-project --public --clone
gh repo create my-project --source . --public --push
gh repo fork owner/repo --clone
gh repo view owner/repo
gh repo edit owner/repo --description "..."
gh secret set NAME --body "$VALUE"
gh release create v1.2.3 ./dist/* --notes "..."
```

Rules:
- Confirm private/public visibility before creating repos.
- Check remotes before pushing.
- Use branch protection/secrets/release APIs carefully; these are high-impact repo settings.

## Codebase Inspection

Use when planning, scoping, or explaining a repo. Prefer fast structural facts before reading dozens of files.

Suggested approaches:
- Use `pygount` or equivalent line-count/language tools when installed.
- Exclude generated/vendor folders (`node_modules`, `.git`, `dist`, `build`, `.venv`, `vendor`, lockfile dumps).
- Inspect both LOC and file counts; a small LOC repo can still have complex topology.

Report language mix, largest directories/files, generated-code exclusions, and implications for the user's task.

## Issues

Useful commands:

```bash
gh issue list
gh issue list --state open --label bug
gh issue list --assignee @me
gh issue list --search "authentication error" --state all
gh issue view 42
gh issue create --title "..." --body "..." --label bug
gh issue edit 42 --add-label "priority:high,bug"
gh issue edit 42 --remove-label needs-triage
gh issue edit 42 --add-assignee @me
gh issue comment 42 --body "Investigated — root cause is ..."
gh issue close 42
```

Issue bodies should include the right structure for the task:
- Bug: description, steps to reproduce, expected behavior, actual behavior, environment, suspected cause, test plan.
- Feature: problem, proposed solution, alternatives, scope, acceptance criteria, non-goals.

## PR Lifecycle

Canonical flow:

```bash
git fetch origin
git checkout main && git pull origin main
git checkout -b feat/short-name
# edit + test
git status --short
git diff --stat
git add <files>
git commit -m "feat: concise subject"
git push -u origin HEAD
gh pr create --title "..." --body "..." --base main --head "$(git branch --show-current)"
gh pr checks
gh pr checks --watch
gh run list --branch "$(git branch --show-current)" --limit 5
gh run view <RUN_ID> --log-failed
gh pr merge --squash --delete-branch
```

Scope discipline:
- Keep bugfix PRs minimal and easy to review.
- Include a real test plan and actual commands run.
- Fix CI with the smallest change that addresses the failure; do not bundle unrelated cleanup.

## Code Review

For local pre-push review:

```bash
git diff --staged
git diff main...HEAD
git diff main...HEAD --name-only
git diff main...HEAD --stat
git log main..HEAD --oneline
git diff main...HEAD | grep -n "print\|console\.log\|TODO\|FIXME\|HACK\|XXX\|debugger"
git diff main...HEAD | grep -in "password\|secret\|api_key\|token.*=\|private_key"
git diff main...HEAD | grep -n "<<<<<<\|>>>>>>\|======="
```

For PR review:

```bash
gh pr view <PR> --json title,body,author,baseRefName,headRefName,files,commits
gh pr diff <PR>
gh pr checkout <PR>
gh pr review <PR> --comment --body "..."
gh pr review <PR> --request-changes --body "..."
gh pr review <PR> --approve --body "..."
```

Review checklist:
- Correctness and edge cases.
- Security/secrets/auth handling.
- Tests and regression coverage.
- Migration/backward compatibility.
- Simplicity and reviewability.
- CI/build/runtime risks.

## REST API Fallback

When `gh` is unavailable, use GitHub REST with a token from the environment or credential store. Keep headers explicit and never echo token values.

```bash
curl -sS -H "Authorization: Bearer ***" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/OWNER/REPO
```

## Common Pitfalls

1. Skipping `git status` and accidentally committing unrelated work.
2. Creating a PR without a real test plan.
3. Guessing base branches; check remote default/base first.
4. Treating a passing local command as CI proof; monitor the actual GitHub checks.
5. Printing credentials or embedding tokens in remote URLs.
6. Reviewing only the summary and not the diff.

## Verification Checklist

- [ ] Auth and repository target verified.
- [ ] Local worktree clean/expected before writes.
- [ ] Commands that changed GitHub state returned success and object URLs/IDs where applicable.
- [ ] PR/issue/release links captured in the final response.
- [ ] CI or review status checked when relevant.
