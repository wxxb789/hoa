# Azure DevOps Provider Reference

Provider-specific details for the ADO backend. The main workflow is in `SKILL.md`.

## Authentication

- Requires Azure CLI: `az login`
- Verified by: `az account show` (parsed into `probe.identity` and probe `auth_account`)
- On Windows Git Bash / MSYS / Cygwin, `az` is routed through `pwsh -NoProfile` to avoid stdout capture issues
  - `pwsh` must be on `PATH`; otherwise the probe emits a blocker with the install hint
    ```
    winget install Microsoft.PowerShell
    ```

## Remote URL Formats

Supported patterns for auto-detection:
- `https://dev.azure.com/<org>/<project>/_git/<repo>`
- `https://<user>@dev.azure.com/<org>/<project>/_git/<repo>`
- `git@ssh.dev.azure.com:v3/<org>/<project>/<repo>`
- `https://<org>.visualstudio.com/<project>/_git/<repo>` (legacy, with optional `/DefaultCollection/`)

## Identity in probe

`probe.identity` is populated from `az account show -o json`:

```jsonc
{
  "git_name":          "Han Li",                // from git config user.name
  "git_email":         "han@example.com",       // from git config user.email
  "provider_login":    "han@example.com",       // az account user.name (UPN) or .name
  "tenant_id":         "11111111-...",
  "subscription_name": "Visual Studio Enterprise"
}
```

**Cross-check the tenant** against `repo.organization_url`. A common foot-gun is being signed in to the wrong tenant — the call to `az repos pr list` will return empty (or 404), which the LLM should diagnose by comparing `identity.tenant_id` to the tenant that owns the org.

## ADO-Specific Plan Fields

Fields in the `pr` section that are ADO-specific (no-op on GitHub):

| Field | Type | Description |
|---|---|---|
| `work_item_ids` | `string[]` | Link these work items to the PR (`az repos pr work-item add`) |
| `transition_work_items` | `bool` | Transition linked work items when PR completes |
| `approve` | `bool` | Self-approve via `az repos pr set-vote --vote approve`. Often blocked by branch policy — see below. |
| `delete_source_branch` | `bool` | Delete source branch on merge (`--delete-source-branch true`) |
| `reviewers` | `string[] \| dict[]` | See below. |

### `reviewers` on ADO

- A bare string list (`["alice@x.com", "bob@x.com"]`) is treated as **optional** reviewers.
- For required reviewers, pass dicts: `[{"id": "alice@x.com", "is_required": true}, ...]`. The `id` key may also be spelled `email` or `upn`.
- Required and optional reviewers are submitted in separate `az repos pr reviewer add` calls because `--is-required` applies per call.

## Work Item Selection

Work item IDs can be:
1. **Explicit**: provided in `pr.work_item_ids` in the plan
2. **From arguments**: passed as `$ARGUMENTS` when invoking the skill

There is no automatic work-item selection from config files. The LLM must determine the IDs from context or ask the user.

## CLI Commands Used

All commands pass `--organization` (and `--project` where applicable) explicitly — the skill never writes `az devops configure --defaults`.

| Operation | Command |
|---|---|
| Auth check       | `az account show -o json` |
| Default branch   | `az repos show --repository <repo> --query defaultBranch` |
| List PRs         | `az repos pr list --source-branch <branch> --status active` |
| Create PR        | `az repos pr create --source-branch ... --target-branch ... [--draft true]` |
| Update PR        | `az repos pr update --id N --title T --description D --draft true/false` |
| Auto-complete    | `az repos pr update --id N --auto-complete true [--squash true] [--delete-source-branch true] [--transition-work-items true]` |
| Link work items  | `az repos pr work-item add --id N --work-items <ids...>` |
| Approve          | `az repos pr set-vote --id N --vote approve` |
| Add reviewers    | `az repos pr reviewer add --id N --reviewers <ids...> [--is-required true]` |
| PR status        | `az repos pr show --id N` |

## Labels

ADO does **not** expose label management through `az repos pr`. Adding labels requires a direct REST call (`PATCH /pullRequests/{id}/labels`). That call is **not yet wired** in this skill.

When a plan sets `pr.labels`, the apply run emits a `pr_labels` step with:
```jsonc
{ "name": "pr_labels", "ok": false, "severity": "warning",
  "labels": [...], "error": "ADO labels require REST API call ... not yet wired" }
```

The step is **warning-severity** — `result.ok` is unaffected. Surface the warning to the user and tell them to add the labels manually in the PR web UI.

## Approval policy gotchas

`pr.approve: true` calls `az repos pr set-vote --vote approve` as the signed-in user. This commonly fails on policy-protected branches with errors like:

- *"You cannot vote on your own pull request"* (when "Minimum number of reviewers ≥ 2" + "Requestors can't approve their own changes" is enabled)
- *"Required reviewer X has not voted"* (when there is a Required Reviewer policy and you are not it)

When `pr_approve` fails, the step's `error` carries the raw `az` stderr — surface it verbatim and suggest the user add a co-reviewer or remove `approve: true` from the plan.

## Deferred capabilities

The following ADO features are **not yet supported** by this skill. PRs that need them have to be fixed up manually after `apply`:

- `bypass_policy` / `bypass_reason` on auto-complete
- `merge_commit_message` (squash/merge commit body override)
- `update_branch` (rebase / merge target into source before merge)
- Signed commits (GPG / SSH)
- Pushing to a fork's branch (`pr.head_repo`)
- Branch policy preflight in `probe` (which policies are enforced on the target branch)
