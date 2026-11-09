---
name: dotnet-repo-workflow
description: >-
  Build, gate and ship a change in a .NET (C#/F#) repo: shell prerequisites, the repo's own gate
  harness instead of a hand-rolled `dotnet test`, package/lock-file mechanics, Roslyn in-memory
  compilation traps, and the PR merge-ready checklist. Use when a .NET build/test fails, when adding a
  NuGet package, or when a .NET change is ready to commit and open as a PR. Do not use for the repo's
  code style (its own AGENTS.md) or for orchestrator install maintenance.
metadata:
  version: "0.1.15"
  areas: "software-development"
  targets: "runtime-agnostic"
---

# .NET repo workflow

Building, gating and shipping changes in .NET (C#/F#) repositories: shell prerequisites, the repo's own
gate harness, package/lock mechanics, and the in-memory compilation harness trap.

## When to Use

| You hear / see | Do |
|---|---|
| "build/test this .NET repo", `dotnet test` / `dotnet build` failing | shell prerequisites → the repo's own gate harness |
| adding a NuGet package, `packages.lock.json` diff appears | packages and lock files |
| analyzer / code-fix / example-cleanliness tests fail with CS1061 | in-memory compilation harnesses |
| "commit and open a PR" for a .NET change | shipping |

**Not for**: writing style → the repo's own `AGENTS.md`; orchestrator maintenance → its operations
skill.

## Shell prerequisites

Non-login shells do not read `~/.bashrc`, so `dotnet` can be "command not found" while the SDK is
installed:

```bash
export DOTNET_ROOT="$HOME/.dotnet"; export PATH="$DOTNET_ROOT:$PATH"; dotnet --version
```

Export once per session. Read `command not found` as a PATH gap and check `~/.dotnet/dotnet` (or
`dotnet --list-sdks`) before concluding the SDK is missing.

## Gates: run the repo's own harness

- Read the repo `AGENTS.md` / `README` first. Mature .NET repos route every gate through a build
  script, e.g. `dotnet fsi build.fsx -- -p test|format|verify-docs-snippets|release`; use those, not a
  hand-rolled subset of `dotnet test`, and note that PR CI often runs only some of them — green CI is
  not a green tree.
- Capture real exit codes: `cmd >/tmp/log 2>&1; echo rc=$?`. Piping a gate through a truncating filter
  such as `| tail -5` hands back the filter's status, and a failed run can still end with a
  clean-looking tail. Read the log file itself rather than re-piping it.
- Full suites take minutes: run backgrounded with completion notify, then report counts
  (`2579 passed / 0 failed / 0 skipped`) plus each gate's rc, not adjectives.
- Repo invariants commonly include: every warning is a build error, zero skipped tests, committed
  `packages.lock.json`, and a formatter gate over C# only.

## Repo-specific knowledge

Everything repo-specific — the gate list and how to read it, API-baseline rules, docs-snippet counts,
goal-file/archive conventions, evidence-record rules — belongs in that repo's **project profile**
(skill `goal-driven-delivery` ships the template). This skill supplies only the .NET mechanics.

## Packages and lock files

- With `RestorePackagesWithLockFile`, adding a `PackageReference` needs
  `dotnet restore <proj> --force-evaluate` and the lock diff committed.
- A restore may also rewrite *unrelated* lock files with a trailing-newline-only change; check
  `git diff --stat` afterwards and revert those (`git checkout -- <path>`) so the commit stays scoped.

## In-memory compilation harnesses

Roslyn-based tests that compile repo sources (analyzer / code-fix / example-cleanliness harnesses) use
an explicit metadata reference set. An API shipped in a NuGet package rather than the shared framework
is invisible to them even though the example project itself builds, and the harness fails with CS1061
"missing assembly reference" (e.g. `AddOpenApi`/`MapOpenApi` from `Microsoft.AspNetCore.OpenApi`).
Fix it by adding the package to the *test* project and appending its assemblies to the harness
reference set (scan `AppContext.BaseDirectory` for that assembly prefix) — not by deleting the
example's use of the API to make the test pass.

## Shipping

Commit with explicit paths (never `git add -A`), one logical change per commit, then push and open the
PR. Merging is the operator's call unless they delegated it in writing for that repo.

### Babysit the PR to merge-ready

Act only from a fresh snapshot of PR state, never from chat history. Mark a review bot's "review
running" status comment as `dispatched` instead of spending a resolver pass on it. How to drive a PR
snapshot helper directly, and what each tick checks: [`references/pr-babysit.md`](references/pr-babysit.md).
"Merge-ready" is not a judgement call — in a goal-driven repo the verdict is a script
(`goal-driven-delivery`, Phase 6), not a feeling.

### Pre-existing red work

When the repo's own gate is red for a reason the change did not cause (a stale harness, a broken
example project), fix it in the same branch as its own commit and disclose it as a separate section in
the PR body. Shipping a branch that leaves the full suite red, or folding the repair into the feature
commit, both make the diff lie about what the feature cost.

### Clean up after the merge

A squash merge leaves the branch tip outside `main`'s history, so `git branch -d` refuses (unmerged).
Prove equivalence first — `git diff --stat <squash-merge-commit> origin/<branch>` empty — then
`git branch -D <branch>` and `git push origin --delete <branch>`. Delete remote branches only when the
operator asks, and treat any branch with an open PR in another repo as still in use.
