---
name: git-worktree-workflow
description: Run multiple AI coding agents (Claude Code, Codex, PI, OpenCode, Hermes, aider, gemini, …) in parallel on the same repo using isolated git worktrees. Tool-agnostic by design — agents are pluggable, so you can switch between them freely. Use when the user wants parallel agent sessions, worktree isolation, "work on two features at once", per-worktree environment setup and deterministic port defaults, or to avoid agents stepping on each other's edits.
---

<!-- index: areas=software-development,work-management; targets=runtime-agnostic; version=1.1.0 -->

# Git Worktree Workflow (tool-agnostic)

One repo, many agents, isolated working trees. Each agent runs in its own `git worktree`
(separate working dir + branch, shared `.git`). **Core principle: build a thin shell
over `git worktree` and treat the agent CLI as pluggable.** Do NOT rely on any tool's
private `--worktree` flag (Claude Code, Hermes have one) — that locks you in. The
`gitwt` helper works the same for every tool, so migrating between Claude Code /
Codex / PI / OpenCode / Hermes / aider is friction-free.

## TL;DR — the `gitwt` helper

```bash
gitwt <branch>                 # create/reuse worktree + cd in   (needs shell fn: `gitwt --shell`)
gitwt new <branch> [base]      # create/reuse, print path
gitwt ls                       # list worktrees
gitwt path <branch>            # print path
gitwt run <tool> <branch> [-- …]  # isolate + launch ANY agent CLI in the worktree
gitwt rm <branch> [--force]    # remove worktree + delete branch
gitwt clean [--merged] [--force]  # remove worktrees whose branch is merged into default
gitwt prune                    # clean stale metadata + empty dirs
gitwt env                      # drop a direnv .envrc: auto env + deterministic hashed PORT
gitwt doctor                   # check git/direnv/agents + show layout
gitwt --shell                  # print shell fn so bare `gitwt <branch>` can cd for you
```

The helper ships at `references/gitwt`. Install it on PATH and `chmod +x`.

The name deliberately avoids `wt` and `git-wt` — both collide with existing
tools, quietly. See [naming](references/naming.md) for the full rationale.

### One-time setup
```bash
echo 'command -v gitwt >/dev/null 2>&1 && eval "$(command gitwt --shell)"' >> ~/.bashrc
# per repo, optional:
git config --add gitwt.hook "npm install"      # or: uv sync / pnpm i — required postCreate setup
git config --add gitwt.copy "**/.env.example"  # extra files to seed into new worktrees
```

Only the shell **function** can `cd` — a child process cannot change its caller's
directory. Running the script directly still creates the worktree and prints its
path; it just leaves you where you were, and says so.

### Hook readiness and recovery

Configured `gitwt.hook` (or legacy `wt.hook`) commands are required before a
worktree is ready. If a hook fails, `gitwt new`, bare `gitwt <branch>`, and
`gitwt run` return nonzero; no path is printed, no directory change is made, and
`gitwt run` does not launch the tool. The worktree and all partial copy/hook writes
are kept. A failed or interrupted setup is never automatically retried: an existing
worktree is reused only with a valid `ready` marker, so `new`, the bare shell function,
and `run` refuse an `in-progress`, missing, malformed, or legacy marker without
rerunning copies or hooks. This applies even when no hooks are currently configured.

The marker is stored as `.gitwt-instance-id` in the linked worktree's private Git
admin directory (`git rev-parse --absolute-git-dir`), never in tracked checkout files.
It contains `gitwt-instance-v2`, a fresh 128-bit lowercase-hex ID from `/dev/urandom`
via `od`, and `in-progress` or `ready`; same-directory rename publishes each marker
atomically. Gitwt verifies the branch, expected repository, and ID before marking
ready and before reporting a path. A raw Git removal/re-add loses the private marker
and is refused; old external v1/v2 state files are ignored.

Per-branch atomic `mkdir` locks live under `<repo-parent>/.wt/<repo>/.gitwt-locks/`.
`new`, `rm`, and each `clean` removal share the lock. If a process is interrupted,
the lock directory named in the error may remain; after confirming no gitwt operation
for that branch is active, remove the empty lock with `rmdir <lock-dir>`. This only
unblocks coordination; it does not make an `in-progress` worktree ready.

To recover, inspect and manually finish/verify setup at the preserved path, then use
tools there directly; or preserve/migrate its changes, remove it with `gitwt rm
[--force] <branch>`, and create a fresh worktree with `gitwt new <branch> [base]`.
Use `--force` only after backing up files Git would otherwise refuse to remove. An
uncoordinated raw Git removal can race after the final readiness check; the marker
checks detect normal replacement during setup but cannot serialize raw Git commands.

Copy-on-create does not overwrite existing files or nest directories: it skips an
existing regular file only when bytes match, or a directory only when its tree
matches; a differing destination fails closed and leaves the worktree for manual
recovery. Once ready, later hook-config changes apply only to future worktrees.

## Layout & why
Worktrees live at `<repo-parent>/.wt/<repo>/<branch-slug>`, where the slug is the
branch name reduced to `[A-Za-z0-9._-]` plus a short `git hash-object` digest of the
full name:
- **same drive** as the repo → avoids the Windows cross-drive cwd-drift trap (subagent writes
  landing in the wrong physical dir).
- **outside** the repo dir → main `git status` stays clean; no double-load of `CLAUDE.md`
  / `AGENTS.md` by tools that walk parent dirs.
  (Alt: some put worktrees under `.git/wt/` so tools ignore them entirely — also valid.)
- **digest suffix** → the readable half is lossy (`/` and space become `-`, non-ASCII
  drops out), so `feature/one` and `feature-one` would otherwise share a directory and
  the second `gitwt new` would hand back the first branch's checkout. `gitwt new` also
  refuses to reuse a directory git does not have checked out on the requested branch.

## Per-tool worktree support (verified 2026-06-15)
| Tool | Native worktree | Use with `gitwt` |
|------|----------------|---------------|
| Claude Code | ✅ `claude -w <name>` (`.claude/worktrees/`, `.worktreeinclude`, `#PR` base) | `gitwt run claude <br>` — one layout for all tools |
| Hermes | ✅ `hermes -w` | `gitwt run hermes <br>` |
| Codex | ❌ (sandboxes shell cmds via `-s/--sandbox`; has `-C/--cd`) | `gitwt run codex <br> -- exec "…"` |
| PI | ❌ (relies on cwd) | `gitwt run pi <br>` |
| OpenCode | ❌ (`--session`/`--fork` = conversation, NOT file isolation) | `gitwt run opencode <br>` |

**Only Claude Code & Hermes isolate files natively.** For the rest you MUST make the
worktree yourself. `gitwt` gives all five the same isolation + the env-copy + hooks
that only Claude Code had built in.

## The 3 pain points and how `gitwt` solves them (community-validated)
1. **Env/ports collide** when every worktree runs a dev server → `gitwt env` writes a
   `direnv` `.envrc` that inherits the main `.env`/venv and assigns a deterministic
   `PORT` (3000–3999 from a path hash). This is not a uniqueness guarantee: the range
   has only 1,000 values, so different worktrees can collide; edit the generated
   `.envrc` to override `PORT`/`DEV_PORT` for a colliding worktree. Worktrees are
   siblings of the main checkout, not children, so direnv would never find a `.envrc`
   left only in the repo — `gitwt` copies it into each worktree (`direnv allow` each
   one once), following waldencui's "direnv is all you need" pattern. Requires `direnv`.
2. **Gitignored files don't follow** (`.env`) → copy-on-create via `.worktreeinclude`
   (Claude-compatible) and `git config gitwt.copy`. Both accept globs (`**/.env.example`),
   expanded before copying.
3. **Deps need reinstalling** per worktree → `git config gitwt.hook "npm install"` runs
   after `gitwt new`; hook failures block readiness and require manual recovery.

## Two mental models (pick per task)
- **By concurrent activity** (matklad): a few long-lived worktrees mapped to *activities*,
  not branches — e.g. `main` (read pristine), `work` (write), `review` (others' PRs),
  `fuzz`/`ci` (long jobs), `scratch` (quick fixes). Long jobs use detached HEAD.
- **By task, fan-out N agents** (skeptrune/uzi): same prompt → several agents in parallel
  worktrees → keep the best. Empirically ~1 of 4 is good; LLMs are cheap so over-provision.
  Bottleneck is **verification**, not generation — only worth it when you can judge fast.

## Golden rules
1. One branch = one worktree (git enforces it). `gitwt` names the worktree after the branch.
2. Never nest a worktree inside the repo. `gitwt` uses a sibling `.wt/`.
3. Clean up: `gitwt clean --merged` after merging; `gitwt prune` periodically. Dirty
   worktrees are protected — `gitwt clean` skips them unless `--force`.
4. Each worktree is a fresh checkout: `node_modules`/venv/`.env` are NOT shared. Use
   `gitwt.hook` for deps, `gitwt env`/`.worktreeinclude` for env.
5. Windows: keep worktrees on the repo's drive; pin absolute paths in fan-out prompts.

## Parallel fan-out pattern
```bash
cd ~/repos/myproj
# Headless / non-interactive (safe to background):
( cd "$(gitwt new feat-auth)"    && codex exec "implement login"    ) &
( cd "$(gitwt new feat-billing)" && claude -p "add stripe webhook"  ) &
wait
# Interactive TUIs (claude/pi/opencode default UI): use SEPARATE terminals, not `&`.
#   term1: gitwt run claude  feat-auth
#   term2: gitwt run opencode feat-billing
```
Then review/merge each branch and `gitwt clean --merged`.

## Portability notes
The helper is bash (uses process substitution, so `sh` will not do) and avoids
GNU-only constructs so it runs on Windows git-bash, macOS, and Linux:
- explicit `tr` ranges instead of `[:alnum:]` — BSD/macOS `tr` also treats a literal
  `[`/`]` as set members, which would slug bracketed branch names differently per OS
- shell-builtin trimming instead of `xargs` — BSD `xargs` interprets quotes in input
- `find -delete` is never handed an empty path
- `.envrc` probes both `.venv/bin` and `.venv/Scripts`
- Windows: verify bare `bash` is Git Bash, not the WSL `bash.exe` —
  see [naming](references/naming.md#windows-bash-trap)

## References
- `references/gitwt` — the helper (put it on PATH, `chmod +x`).
- `scripts/test_gitwt.sh` — regression tests (`bash skills/git-worktree-workflow/scripts/test_gitwt.sh`).
  Builds a throwaway repo whose path contains a space and checks space-safe root
  parsing, collision-resistant slugs with branch-verified reuse, `.envrc`
  propagation, glob copying, and fail-closed hook readiness.
- Git worktree docs: https://git-scm.com/docs/git-worktree
