# GitHub Provider Reference

Provider-specific details for the GitHub backend. The main workflow is in `SKILL.md`.

## Authentication

- Requires GitHub CLI: `gh auth login`
- Verified by: `gh auth status`
- Identity fetched via: `gh api user --jq '{login, name}'` (non-fatal if it fails)

## Remote URL Formats

Supported patterns for auto-detection:
- `https://github.com/<owner>/<repo>.git`
- `git@github.com:<owner>/<repo>.git`
- `https://github.com/<owner>/<repo>`

## Identity in probe

`probe.identity` is populated from `gh api user`:

```jsonc
{
  "git_name":       "Han Li",          // git config user.name
  "git_email":      "han@example.com", // git config user.email
  "provider_login": "hanli"            // gh api user .login
}
```

Use `identity.git_email` (or compare against `provider_login`) to drop the author from `pr.reviewers` — GitHub rejects self-review.

## GitHub-Specific Plan Fields

Fields in the `pr` section that are GitHub-relevant. (`labels` and `reviewers` also work on ADO with caveats — see `references/ado.md`.)

| Field | Type | Description |
|---|---|---|
| `labels` | `string[]` | Apply labels. Works on `create` (`gh pr create --label ...`) AND `update` (`gh pr edit --add-label ...`). |
| `reviewers` | `string[]` | Request reviewers. Works on `create` AND `update` (`gh pr edit --add-reviewer ...`). |
| `closes_issues` | `int[]` | Auto-appends `Closes #N` lines to `description` for any issue numbers not already referenced. See **Issue Linking**. |
| `merge_method` | `"squash" \| "merge" \| "rebase"` | Wired into `gh pr merge --auto --<method>` when `auto_complete: true`. Deprecated alias: `squash: true` → `"squash"`. |
| `delete_source_branch` | `bool` | Passes `--delete-branch` to `gh pr merge --auto`. |
| `draft` | `bool` | On `create` adds `--draft`. On `update` toggles via `gh pr ready N` / `gh pr ready --undo N` (requires `gh >= 2.40` to undo). |

## Auto-Merge

When `auto_complete: true` is set in the plan, the skill runs:

```
gh pr merge <id> -R <owner>/<repo> --auto --<merge_method> [--delete-branch]
```

Auto-merge can fail for any of several reasons: repo policy disallows it, branch protection requires checks that haven't run yet, or merge queue is enabled. When that happens, the `pr_auto_complete` step records `ok: false` with the raw `gh` stderr but does **not** abort the run (the PR itself still exists). Surface the stderr to the user and let them enable auto-merge manually or fix the upstream policy.

## Issue Linking

GitHub recognizes a fixed set of closing keywords in PR descriptions, all case-insensitive:

```
Closes #42
Fixes  #42
Resolves #42
```

(Plus `close`, `closed`, `fix`, `fixed`, `resolve`, `resolved`.)

### `pr.closes_issues`

Pass a list of issue numbers — the skill auto-appends them if not already referenced:

- Existing `Closes/Fixes/Resolves #N` references in `description` are detected and deduped (so you can safely include `closes_issues: [42]` even if your description already says "Fixes #42").
- New references are appended on a new line as `Closes #N1, #N2, ...`.
- **No-op on ADO** — use `work_item_ids` instead.

## Work Items

Work items are an ADO-only concept. `work_item_ids`, `approve`, and `transition_work_items` in the plan are silently ignored for GitHub.

## CLI Commands Used

| Operation | Command |
|---|---|
| Auth check     | `gh auth status` |
| Identity       | `gh api user --jq '{login, name}'` |
| Default branch | `gh repo view -R <owner>/<repo> --json defaultBranchRef --jq .defaultBranchRef.name` |
| List PRs       | `gh pr list -R <owner>/<repo> --head <branch> --state open --json ...` |
| Create PR      | `gh pr create -R <owner>/<repo> --head ... --base ... [--draft] [--label ...] [--reviewer ...]` |
| Edit PR        | `gh pr edit N -R <owner>/<repo> [--title T] [--body B] [--add-label ...] [--add-reviewer ...]` |
| Toggle draft   | `gh pr ready N -R <owner>/<repo>` (mark ready) / `gh pr ready --undo N` (mark draft, gh ≥ 2.40) |
| Auto-merge     | `gh pr merge N -R <owner>/<repo> --auto --squash\|--merge\|--rebase [--delete-branch]` |
| PR status      | `gh pr view N -R <owner>/<repo> --json number,title,url,state,headRefName,baseRefName,mergeable,mergeStateStatus,isDraft,reviewDecision` |

## Deferred capabilities

The following GitHub features are **not yet supported** by this skill. PRs that need them have to be fixed up manually after `apply`:

- `assignees` (`gh pr edit --add-assignee`)
- `milestone` (`gh pr edit --milestone`)
- `projects` (Project v2 board linking)
- Pushing to a fork's branch (`pr.head_repo`)
- GPG / SSH signed commits
