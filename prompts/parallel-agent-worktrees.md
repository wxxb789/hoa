<!-- index: areas=software-development,work-management; targets=repo-only -->

# Parallel agent worktrees

A one-shot request template for running several coding-agent CLIs (Claude
Code, Codex, pi, OpenCode, and others) on one repository at the same time,
each in its own `git worktree`. It keeps the layout and safety rules that are
easy to get subtly wrong; ordinary `git worktree` usage is left to the model.

## Template

```text
Set up isolated git worktrees so these agent sessions can run in parallel on
this repository without touching each other's files.

Sessions: {agent CLI + branch name, one per line}
Base: {base ref, default: the default branch}
Setup: {dependency install command, files to copy, dev-server needs}

Layout
- One branch = one worktree = one agent session. Launch each agent with a
  plain `cd "<absolute worktree path>" && <agent>`; pin absolute paths in
  any prompt you hand to a background agent.
- Put worktrees at <repo-parent>/.wt/<repo>/<slug>: outside the repository
  (main `git status` stays clean and tools do not load AGENTS.md/CLAUDE.md
  twice) and on the same drive (on Windows a cross-drive cwd can send writes
  to the wrong directory). Never nest a worktree inside the checkout.
- slug = branch name reduced to [A-Za-z0-9._-] plus a short hash of the
  full branch name, so feature/one and feature-one cannot share a directory.
  Reuse an existing directory only if Git has it checked out on the requested
  branch.

Environment
- Each worktree is a fresh checkout: ignored files (.env, venv,
  node_modules) do not follow. Copy the ignored files I list (expand glob
  patterns; honor .worktreeinclude if present) without overwriting a
  differing file, and run the dependency install per worktree.
- Give each worktree its own environment file and port. direnv does not see
  a .envrc in the main checkout from a sibling worktree, so put one in each
  worktree (and `direnv allow` it). A port derived from a path hash is not
  unique; check for collisions before starting servers.

Setup must fail closed
- A worktree is ready only after every copy and setup command succeeded. On
  failure: exit nonzero, print no path, do not launch the agent, keep the
  partial worktree for me to inspect, and do not silently rerun setup on the
  next call. If you record readiness, store the marker in the worktree's
  private Git directory (`git rev-parse --absolute-git-dir`), not in tracked
  files.

Cleanup
- Remove a worktree only when its branch is merged into the default branch
  and the worktree is clean (no modified or untracked files). Keep worktrees
  whose only extra content is ignored files (.env, local data) unless I say
  to force it. Delete branches with `git branch -d`, never -D, then
  `git worktree prune`.

Do not install helpers on PATH, edit shell profiles, or add hooks or git
config unless I ask. Report each worktree's path, branch, port, setup result,
and the exact command to start its agent.
```

## Notes

- **Worktrees are not a security boundary.** They share one `.git`: refs,
  hooks, config, and objects. An agent in one worktree can read and write the
  others and the main checkout. Use containers or sandboxes for isolation.
- **Prefer plain `git worktree` over tool-private flags.** Claude Code
  (`claude -w`) and Hermes (`hermes -w`) create their own worktrees; Codex, pi,
  and OpenCode do not isolate files (OpenCode `--fork` forks a conversation, not
  a checkout). One shared layout lets you switch agents freely.
- **Fan-out.** Headless runs (`codex exec`, `claude -p`) can run in the
  background; interactive TUIs need separate terminals. Several agents on the
  same prompt cost little to run; judging the results is the bottleneck.

## If you script it

A helper script is optional. If you write or adopt one, it must guarantee:

- Space-safe paths: parse `git worktree list --porcelain` without word
  splitting; a repo path with a space must work.
- Collision-safe slugs as above, and branch-verified reuse.
- Fail-closed setup with a private readiness marker; no automatic rerun.
- Per-branch locking so concurrent create/remove/cleanup cannot race.
- A `.envrc` (or equivalent) in every worktree, not only the main checkout.
- Glob copy patterns expanded before copying; differing destinations refused.
- Cleanup limited to merged, clean, ready worktrees; ignored content kept
  unless forced.
- Portability across Git Bash, macOS, and Linux: no GNU-only flags, explicit
  `tr` ranges instead of `[:alnum:]`, no `xargs` on names containing quotes.
- On Windows, run it with Git Bash, not the WSL `bash.exe` that may come
  first on PATH. Avoid the names `wt` (Windows Terminal alias) and `git-wt`
  (an unrelated published tool).
- Regression tests for each guarantee above.

## Provenance

Retired from the `git-worktree-workflow` skill (2026-11-06) after an A/B
necessity eval showed the bare model producing the same layout, fail-closed
setup, and safe cleanup on its own.
