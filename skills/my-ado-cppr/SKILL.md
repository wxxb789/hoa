---
name: my-ado-cppr
description: Commit local changes, push branches, and create or update PRs in Azure DevOps or GitHub repositories. Use when asked to commit/push and open PRs, automate ADO work item linking/auto-complete, or create GitHub PRs (ignore work items for GitHub).
---

<!-- index: areas=software-development; targets=runtime-agnostic; version=1.0.0 -->

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

Returns JSON with context and preflight checks (full shape:
[schemas — probe output](references/schemas.md#probe-output)).

- **`ok: false`** → STOP, report `blockers` to the user, do NOT proceed.
- **`warnings` non-empty** → proceed, but the plan MUST address each warning (e.g. protected branch → include `branch.create`; missing identity → ask user).
- **`notes` non-empty** → informational only. The most common note is "working tree clean", which blocks `commit.do=true` plans but is fine for `pr.action="update"` flows (label edits, description fixes, etc.).
- **`state.stale=true`** → a previous run left state behind that no longer matches the current branch/HEAD. Either call again without `--resume` (to start fresh) or discard the state via `state.clear` semantics — `apply` with `--resume` will auto-discard stale state and record a `resume` warning step.

### Step 2: Plan

Build a plan JSON from the probe output (full shape:
[schemas — plan](references/schemas.md#plan-schema)). Minimal skeleton:

```json
{
  "provider": "ado",
  "branch": {"create": true, "name": "feature/my-branch"},
  "commit": {"do": true, "stage_all": true, "message": "[feat] description\n\n- details"},
  "push":   {"do": true, "set_upstream": true},
  "pr": {
    "action": "create", "source_branch": "feature/x", "target_branch": "main",
    "title": "Add feature X", "description": "## Summary\n...",
    "auto_complete": true, "merge_method": "squash", "delete_source_branch": true
  }
}
```

Key decision rules (full field notes in [schemas](references/schemas.md)):

- `existing_prs` non-empty → BEFORE you build a plan, summarize each PR (`id`, `title`, `source_branch → target_branch`, `draft`) and ask the user: **update** that PR, **abandon and create new**, or **abort**.
- `identity.git_email == reviewer` → drop self from `pr.reviewers` before sending.
- `commit.amend: true` re-pushing a pushed branch → `push.force_with_lease: true`.
- `provider` optional; auto-detected from `git remote get-url origin` (`dev.azure.com` / `*.visualstudio.com` / `ssh.dev.azure.com` = ADO; `github.com` = GitHub). To pin in an apply run, put it in the plan — `--provider` exists on `probe` only.

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

Apply returns a step-list result — full shape and step names in
[schemas — apply result](references/schemas.md#apply-result-schema). The rules
that matter:

- `result.ok: false` only when a non-warning step failed; warning steps record problems without aborting.
- **The PR may still exist on `ok: false`** — always inspect `summary.pr_url` and `headline` before re-creating.
- `result.headline` always reflects the most useful outcome (`pr_update` > `pr_create` > `push` > `commit`).
- Resume semantics, state persistence (`.git/commit-push-pr-state.json`), error shapes, and debug mode: see [schemas](references/schemas.md).

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

## Provider-specific references

- **Azure DevOps**: [references/ado.md](references/ado.md) — auth, identity / tenant cross-check, full plan field reference, CLI command table, labels caveat, approval-policy gotchas, deferred capabilities.
- **GitHub**: [references/github.md](references/github.md) — auth, identity, full plan field reference (`closes_issues`, `merge_method`, `delete_source_branch`, labels, reviewers), CLI command table, issue-linking grammar, deferred capabilities.
