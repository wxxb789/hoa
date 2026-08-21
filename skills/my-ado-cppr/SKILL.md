---
name: my-ado-cppr
description: Commit local changes, push branches, and create or update PRs in Azure DevOps or GitHub repositories. Use when asked to commit/push and open PRs, automate ADO work item linking/auto-complete, or create GitHub PRs (ignore work items for GitHub).
---

<!-- index: areas=software-development; targets=runtime-agnostic -->

# Commit Push PR

Create a clean commit, push the current branch, and open or update a pull request in Azure DevOps or GitHub.

## Prerequisites

- **uv** — required to run the entry script (`uv run ...`)
- **git** — any modern version
- **az CLI** — required for Azure DevOps (`az login`)
  - On Windows Git Bash / MSYS / Cygwin, `pwsh` (PowerShell 7+) must also be on `PATH`; `az` is routed through it to avoid stdout capture bugs. Install with:
    ```
    winget install Microsoft.PowerShell
    ```
- **gh CLI** — required for GitHub (`gh auth login`)

The probe will surface missing prerequisites as `blockers` (e.g. detached HEAD, not authenticated, or `pwsh not on PATH` for ADO on Git Bash).

## Workflow: probe → plan → apply

The entry script is `lib/run.py` in this skill's own directory — under
`~/.claude/skills/my-ado-cppr/` for a global Claude Code install, and the
equivalent `skills/` dir for any other runtime `npx skills` installed it into.
Adjust the paths below accordingly.

### Step 1: Probe

```bash
uv run ~/.claude/skills/my-ado-cppr/lib/run.py probe
```

Returns JSON with context and preflight checks (schema documented in **Probe Output** below).

- **`ok: false`** → STOP, report `blockers` to the user, do NOT proceed.
- **`warnings` non-empty** → proceed, but the plan MUST address each warning (e.g. protected branch → include `branch.create`; missing identity → ask user).
- **`notes` non-empty** → informational only. The most common note is "working tree clean", which blocks `commit.do=true` plans but is fine for `pr.action="update"` flows (label edits, description fixes, etc.).
- **`state.stale=true`** → a previous run left state behind that no longer matches the current branch/HEAD. Either call again without `--resume` (to start fresh) or discard the state via `state.clear` semantics — `apply` with `--resume` will auto-discard stale state and record a `resume` warning step.

### Step 2: Plan

Build a plan JSON from the probe output. See **Plan Schema** below.

### Step 3: Apply

```bash
uv run ~/.claude/skills/my-ado-cppr/lib/run.py apply <<'PLAN'
{...plan JSON...}
PLAN
```

On failure, fix the plan and retry with `--resume`:

```bash
uv run ~/.claude/skills/my-ado-cppr/lib/run.py apply --resume <<'PLAN'
{...corrected plan...}
PLAN
```

## Provider Detection

Auto-detected from `git remote get-url origin`:
- **Azure DevOps**: `dev.azure.com`, `*.visualstudio.com`, `ssh.dev.azure.com`
- **GitHub**: `github.com`

To force a provider:
- **Probe**: `--provider ado` or `--provider github` (CLI flag, probe-only)
- **Apply**: set `"provider": "ado" | "github"` in the plan JSON

`--provider` does NOT exist on `apply`. To pin the provider in an apply run, put it in the plan.

## Probe Output

Top-level keys:

| Key | Type | Notes |
|---|---|---|
| `ok` | bool | `false` when `blockers` is non-empty |
| `blockers` | string[] | STOP conditions — do not proceed |
| `warnings` | string[] | Address in plan, then proceed |
| `notes` | string[] | Informational only |
| `provider` | `"ado" \| "github"` | Resolved provider |
| `identity` | object | See below |
| `git` | object | See below |
| `repo` | object | See below |
| `suggestions` | object | Advisory data; never executed |
| `state` | object | Whether `--resume` would pick up prior progress |
| `build_command` | string \| null | Back-compat alias of `suggestions.build_command` |

### `identity`

```jsonc
{
  "git_name": "Han Li",
  "git_email": "han@example.com",
  "provider_login": "han@example.com",  // az account user.name OR gh api user.login
  "tenant_id": "...",                   // ADO only
  "subscription_name": "..."            // ADO only
}
```

Use `identity.git_email` to filter the author out of `pr.reviewers` (PR providers reject self-review).

### `git`

```jsonc
{
  "branch": "feature/x",
  "remote_url": "https://...",
  "detached_head": false,
  "status_porcelain": ["M src/a.py", "?? new.txt"],
  "staged": ["src/a.py"],
  "unstaged": [],
  "untracked": ["new.txt"],
  "diff_stat": {"files": 2, "insertions": 25, "deletions": 12},
  "changed_files": ["src/a.py", "new.txt"],
  "recent_commits": ["abc1234 prev", ...]
}
```

### `repo`

```jsonc
{
  "owner": "org",
  "project": "proj",                       // ADO only; null on GitHub
  "name": "repo",
  "organization_url": "https://dev.azure.com/org",  // ADO only
  "default_branch": "main",
  "default_branch_source": "api" | "local-ref" | "unknown",
  "existing_prs": [
    {
      "id": "1234",
      "title": "Add feature X",
      "url": "https://...",
      "source_branch": "feature/x",
      "target_branch": "main",
      "draft": false,
      "status": "active" | "open"
    }
  ]
}
```

`existing_prs[]` is provider-normalized — always these seven keys regardless of backend.

### `suggestions`

```jsonc
{
  "build_command": "rtk pnpm run build" | null,
  "pr_template":   {"path": "...", "content": "..."} | null,
  "codeowners":    {"path": "...", "content": "..."} | null,
  "branch_naming_hint": "feature/" | null
}
```

All suggestions are advisory — the skill never runs them.

### `state`

```jsonc
{
  "present": true,
  "branch": "feature/x",
  "done_keys": ["preflight", "branch_create", "commit"],
  "head_at_start": "abc123...",
  "stale": false,
  "stale_reason": null
}
```

### Decision rules

- `ok: false` → STOP, report `blockers`.
- `existing_prs` non-empty → BEFORE you build a plan, summarize each PR (`id`, `title`, `source_branch → target_branch`, `draft`) and ask the user: **update** that PR, **abandon and create new**, or **abort**.
- `state.stale=true` → either start fresh (omit `--resume`) or run with `--resume` and accept the auto-discard (a `resume` warning step will record the reason).
- `detached_head=true` → also a blocker; user must check out a branch first.
- `identity.git_email == reviewer` → drop self from `pr.reviewers` before sending.

## Plan Schema

```json
{
  "provider": "ado",
  "debug": false,
  "branch": {
    "create": true,
    "name": "feature/my-branch"
  },
  "commit": {
    "do": true,
    "stage_all": true,
    "amend": false,
    "paths": null,
    "message": "[feat] description\n\n- details"
  },
  "push": {
    "do": true,
    "set_upstream": true,
    "force_with_lease": false,
    "remote": "origin"
  },
  "pr": {
    "action": "create",
    "source_branch": "feature/x",
    "target_branch": "main",
    "title": "Add feature X",
    "description": "## Summary\n...",
    "draft": false,
    "auto_complete": true,
    "merge_method": "squash",
    "delete_source_branch": true,
    "transition_work_items": true,
    "approve": true,
    "work_item_ids": ["12345"],
    "labels": ["enhancement"],
    "reviewers": ["username"],
    "closes_issues": [42]
  }
}
```

### Field notes

**Top-level**
- `provider` — `"ado" \| "github"`. Optional; auto-detected from origin if absent.
- `debug` — same effect as `CPR_DEBUG=1`.

**`branch`**
- `create: true` requires `name`. Falls back to `git checkout <name>` if the branch already exists.

**`commit`**
- `do: true` requires `message` unless `amend: true`.
- `stage_all: true` runs `git add -A` before commit.
- `amend: true` → uses `--amend`. With empty `message` it adds `--no-edit`.
- `paths: ["a/b", "c/d"]` — stage only these via `git add -- <paths>` instead of `-A`. Mutually exclusive with `stage_all`.

**`push`**
- `set_upstream: true` (default) runs `git push -u <remote> <branch>`.
- `force_with_lease: true` adds `--force-with-lease`. Required when `commit.amend: true` re-pushes an already-pushed branch.
- `remote` defaults to `"origin"`.

**`pr`**
- `action: "create" | "update"`. For `"update"`, also set `"id": "1234"`.
- `title`, `description`, `draft` are honored on BOTH `create` and `update`.
- `merge_method: "squash" | "merge" | "rebase"`. Deprecated alias `pr.squash: true` maps to `"squash"`. New plans should use `merge_method`.
- `closes_issues: [42, 99]` — **GitHub only**. Auto-appends `Closes #42, #99` to `description` for issue numbers not already referenced via `Closes/Fixes/Resolves`. No-op on ADO; use `work_item_ids` instead.
- `labels: ["x"]` — **GitHub** fully supported on create and update. **ADO** surfaces a `pr_labels` warning step (REST API integration not yet wired; add manually in the PR web UI).
- `reviewers: [...]` — both providers.
  - GitHub: list of usernames (strings).
  - ADO: list of strings (emails/UPNs, treated as optional reviewers) OR list of dicts `{"id": "...", "is_required": true}`.
- `approve: true` — **ADO only**. Self-approve via `az repos pr set-vote`. Often fails on policy-protected branches; see `references/ado.md`.
- `work_item_ids: ["12345"]` and `transition_work_items: true` — **ADO only**.
- `delete_source_branch: true` — both providers (ADO via `--delete-source-branch`; GitHub via `gh pr merge --delete-branch`).
- `auto_complete: true` — enable auto-complete (ADO) / auto-merge (GitHub).

### PR key aliases

`ado_pr` and `github_pr` are accepted as aliases for `pr`. Using `pr` AND an alias in the same plan errors out at `validate_plan`.

## Apply Result Schema

```jsonc
{
  "ok": true,
  "meta": {
    "schema": "commit-push-pr/result/v1",
    "generated_at": "2026-06-04T..."
  },
  "steps": [
    {"name": "preflight",          "ok": true},
    {"name": "branch_create",      "ok": true, "branch": "feature/x"},
    {"name": "commit",             "ok": true, "sha": "abc..."},
    {"name": "push",               "ok": true},
    {"name": "pr_create",          "ok": true, "pr_id": "42", "pr_url": "..."},
    {"name": "pr_auto_complete",   "ok": true},
    {"name": "pr_verify",          "ok": true}
  ],
  "artifacts": {
    "repo_root":  "...",
    "branch":     "feature/x",
    "provider":   "ado",
    "owner":      "org",
    "repo":       "myrepo",
    "project":    "proj",
    "organization_url": "https://dev.azure.com/org",
    "commit_sha": "abc...",
    "pr_id":      "42",
    "pr_url":     "https://..."
  },
  "summary": {
    "pr_url":     "https://...",
    "pr_id":      "42",
    "branch":     "feature/x",
    "commit_sha": "abc...",
    "provider":   "ado",
    "succeeded":  ["preflight", "branch_create", "commit", "push", "pr_create", "pr_auto_complete", "pr_verify"],
    "failed":     [],
    "warnings":   []
  },
  "headline":  "Created PR #42: https://...",
  "pr_status": { /* provider-shaped PR detail blob */ }
  // "error": "..." only present when ok=false
}
```

### Step names

`preflight`, `validate_plan`, `resume`, `branch_create`, `commit`, `push`, `pr_create`, `pr_update`, `pr_draft_toggle`, `pr_auto_complete`, `pr_work_items`, `pr_approve`, `pr_labels`, `pr_reviewers`, `pr_verify`.

### Warning vs hard failure

A step may carry `"severity": "warning"`. Such steps are excluded from `result.ok` — they record a problem (e.g. ADO labels not wired, `pr_verify` lookup hiccup) without aborting the run.

- `result.ok` is `false` only when one or more non-warning steps failed.
- When `result.ok` is `false`, `result.error` is synthesized from each hard-failed step's `error` field, joined by `; `.
- `result.headline` always reflects the most useful outcome (`pr_update` > `pr_create` > `push` > `commit`).

> **Important**: even when `result.ok: false`, the PR may exist. Always inspect `summary.pr_url` and `headline` before re-creating.

## Commit Message Format

```
[category] brief description

- Detailed point 1
- Detailed point 2
```

**Categories**: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`

No `Co-Authored-By`, no "Generated with" footer, no emoji.

## PR Description Format

```markdown
## Summary

Brief description of changes.

## Changes

- Key change 1
- Key change 2

## Test Plan

- [ ] Verified locally
- [ ] Tests pass
```

No attribution footer, no emoji.

## Resume Semantics

- When `apply` starts, it stamps the new state file with the current `branch` and `head_at_start` (HEAD SHA).
- `--resume` loads that state and skips any step listed in `state.done`.
- **Stale state is auto-discarded.** If `state.branch != current_branch` or `head_at_start` is no longer reachable from `HEAD`, the run records a `resume` step with `severity: "warning"` and starts fresh.
- **On hard success, state is cleared** (next run starts fresh automatically).
- **On hard failure, state is saved** so `--resume` can pick up where things left off.
- **Auth is always re-checked** on every invocation (tokens expire — never gated by `state.done.preflight`).
- **Protected-branch guard is always re-checked** — `--resume` cannot bypass it.

### When to re-probe

- After any `apply` that succeeded — re-probe before issuing a follow-up operation (the new HEAD, new PR, and cleared state file all change planning context).
- `probe.state.present` tells you whether a prior run left state behind.
- `probe.repo.existing_prs` reflects current PR state (use this to decide create vs. update).

## Provider-Specific Features

### Azure DevOps

See `references/ado.md` for: auth, identity / tenant cross-check, full plan field reference, CLI command table, labels caveat, approval-policy gotchas, and deferred capabilities.

### GitHub

See `references/github.md` for: auth, identity, full plan field reference (`closes_issues`, `merge_method`, `delete_source_branch`, labels, reviewers), CLI command table, issue-linking grammar, and deferred capabilities.

## Error Handling

- **Soft-failure helpers** (`set_auto_complete`, `link_work_items`, `approve_pr`, `add_labels`, `add_reviewers`, `update_pr`, `set_draft`) return `(ok: bool, err: str)`. Each step's `error` field carries the real stderr from the provider CLI — surface it to the user verbatim.
- **Warning-severity steps** (e.g. ADO `pr_labels` until REST integration lands, `pr_verify` lookup hiccup) do NOT flip `result.ok`.
- **Hard failures** are aggregated into a top-level `result.error: "step_a: ...; step_b: ..."`.
- **`result.headline`** always reflects the most useful outcome — even on partial failure.
- **PR may still exist on `ok: false`** — always inspect `summary.pr_url` before retrying create.

### State persistence

- Progress is saved to `.git/commit-push-pr-state.json` (main checkout) or `.git/worktrees/<wt>/commit-push-pr-state.json` (linked worktrees). Path is resolved via `git rev-parse --git-path`, so it works in worktrees and submodules.
- On JSON corruption (e.g. partial write, manual edit gone wrong), the file is renamed to `<file>.corrupt` with a stderr warning and a fresh run starts.
- State is cleared automatically on hard success.

### Common failure shapes

- **Auth failure** → `preflight` step `ok: false`, error includes the remediation (`az login` / `gh auth login`).
- **Protected branch without `branch.create`** → `preflight` step `ok: false`; the plan must add `branch.create`.
- **Push rejected** → `push` step `ok: false`, error includes a hint to set `push.force_with_lease: true` when it looks like a non-fast-forward.
- **PR creation failure** → `pr_create` step `ok: false` with provider error. Retry with `--resume` after fixing the plan; state already records earlier completed steps.

## Debug Mode

- Enable with `CPR_DEBUG=1` (env) or `"debug": true` in the plan JSON.
- `--debug` CLI flag also works.
- Debug output goes to stderr: each subprocess invocation, return code, stderr (up to 4000 chars), stdout sample (up to 1000 chars), and a Python traceback on any uncaught exception.
- `CPR_TIMEOUT_SEC` overrides the default per-command timeout (120s). Known long ops (push, PR create, auto-complete) override to 300s internally.
- The lib also writes one-line breadcrumbs to stderr unconditionally before each slow subprocess (`[cppr] committing...`, `[cppr] pushing...`, `[cppr] creating PR...`, etc.) so you can see progress on long runs.
