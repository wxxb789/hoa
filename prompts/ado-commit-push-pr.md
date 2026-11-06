<!-- index: areas=software-development; targets=repo-only -->

# ADO / GitHub commit, push, and PR

A one-shot request template for committing, pushing, and opening or updating a
pull request on Azure DevOps or GitHub. It carries only the house conventions
and the CLI pitfalls a capable model tends to get wrong; ordinary Git and
`az`/`gh` usage is left to the model.

## Template

```text
Commit, push, and open (or update) a pull request for this repository.

Request: {what to ship, plus any PR id, work item ids, reviewers, labels}

Scope and safety
- Commit only what is already staged unless I explicitly authorize other
  files or "all changes". Leave unstaged edits, untracked files, and
  secrets untouched; do not stash them away.
- Never commit or push to the default branch or another protected branch
  (main, master, develop, or any policy-protected branch). Create a feature
  branch first.
- Before creating a PR, list open PRs for the source branch. If one exists,
  show its id, title, source -> target, and draft state, then ask me:
  update it, abandon it and create a new one, or abort.
- Amending an already-pushed commit means pushing with --force-with-lease,
  never --force.
- Pass --organization and --project explicitly to az; do not write
  `az devops configure --defaults`.

Commit message
  [category] brief summary

  - Detail 1
  - Detail 2
Categories: feat, fix, docs, chore, refactor, test.

PR description (follow a repository PR template instead when one exists)
  ## Summary
  Brief description of changes.

  ## Changes
  - Key change 1

  ## Test Plan
  - [ ] Verified locally
  - [ ] Tests pass

No AI attribution anywhere: no Co-Authored-By trailer, no "Generated with"
footer, no emoji, in commits or PR text.

Defaults unless I say otherwise
- Azure DevOps: enable auto-complete with squash merge and delete the source
  branch. Link only work item ids I gave you or that the request names; do
  not guess ids.
- GitHub: same intent via `gh pr merge <n> --auto --squash --delete-branch`.
  Use `Closes #N` lines for issues; work items do not apply.
- Remove my own identity (git user.email / provider login) from reviewers;
  providers reject self-review.

CLI pitfalls
- **Required reviewers on ADO.** On create, use `--required-reviewers` /
  `--optional-reviewers`. On an existing PR, use
  `az repos pr reviewer add --id N --reviewers <ids> --required true`. The flag
  is `--required`; `--is-required` does not exist and fails the call.
- **Independent follow-up steps.** Reviewers, work items, auto-complete, and
  labels are separate calls after create. A failure in one must not skip the
  others, and a failed later step does not mean the PR is missing: check the
  PR before creating it again.
- **Multi-line descriptions on Windows.** `az` on Windows is `az.cmd`, which
  forwards arguments through `%*`. An argument containing a newline (for
  example sent from PowerShell) is cut at the first newline, and later
  arguments are lost. `az repos pr create/update --description` joins multiple
  values with newlines, so pass one value per line, or call the Git Bash `az`
  wrapper. Read the stored description back with
  `az repos pr show --id N --query description -o tsv`. On GitHub use
  `gh pr create/edit --body-file <file>`.
- **Labels on ADO.** `az repos pr create --labels a b` works. For an existing
  PR, `az repos pr update` has no label option; use the REST endpoint
  `POST .../_apis/git/repositories/{repo}/pullRequests/{id}/labels` or the web
  UI. GitHub: `--label` on create, `gh pr edit --add-label` on update.
- **Draft state.** ADO: `az repos pr update --id N --draft false` publishes.
  GitHub: `gh pr ready N`; `gh pr ready --undo N` (gh 2.40+) returns to draft.
- **Wrong tenant.** An empty `az repos pr list` or a 404 often means
  `az login` is on a tenant that does not own the organization. Compare the
  `tenantId` from `az account show` before concluding there are no PRs.
- **Self-approval and policy.** `az repos pr set-vote --vote approve` is often
  rejected by branch policy (for example "You cannot vote on your own pull
  request" or "Required reviewer X has not voted"). Report it verbatim;
  bypassing policy needs my explicit authorization.

Report the PR id and URL, every step that failed with the CLI's stderr
verbatim, and anything still to do by hand.
```

## Provenance

Retired from the `my-ado-cppr` skill (2026-11-06); its probe/plan/apply engine
was dropped after an A/B necessity eval showed the bare model doing the work
without it.
