---
name: git-worktree-workflow
description: Run multiple AI coding agents (Claude Code, Codex, PI, OpenCode, Hermes, aider, gemini, …) in parallel on the same repo using isolated git worktrees. Tool-agnostic by design — agents are pluggable, so you can switch between them freely. Use when the user wants parallel agent sessions, worktree isolation, "work on two features at once", per-worktree env/port isolation, or to avoid agents stepping on each other's edits.
---

<!-- index: areas=software-development,work-management; targets=runtime-agnostic -->

# Git Worktree Workflow (tool-agnostic)

One repo, many agents, zero collisions. Each agent runs in its own `git worktree`
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
gitwt env                      # drop a direnv .envrc: auto env + unique PORT per worktree
gitwt doctor                   # check git/direnv/agents + show layout
gitwt --shell                  # print shell fn so bare `gitwt <branch>` can cd for you
```

The helper ships at `references/gitwt`. Install it on PATH and `chmod +x`.

### Why the name is `gitwt`

Not `wt`, and not `git-wt` — both collide, and both failures are quiet:

- **`wt`** is Windows Terminal's App Execution Alias
  (`%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe`), registered system-wide. A helper
  named `wt` only wins by PATH order and loses the moment its directory drops out,
  at which point a `command -v wt` guard passes on Windows Terminal and
  `wt --shell` pops a **modal error dialog** on every shell start. Because git-bash
  starts as a login shell, that is one dialog per shell — unbounded.
- **`git-wt`** would be reachable as `git wt …` (git dispatches `git <verb>` to
  `git-<verb>` on PATH), but it is the binary name of
  [k1LoW/git-wt](https://github.com/k1LoW/git-wt), whose CLI has **no subcommands** —
  `git wt list` there creates a worktree named `list`. Sharing the name means a
  later `brew install k1LoW/tap/git-wt` silently shadows this script with one whose
  verbs mean something else.

`gitwt` collides with neither, at the cost of not being a `git <verb>` subcommand.

### One-time setup
```bash
echo 'command -v gitwt >/dev/null 2>&1 && eval "$(command gitwt --shell)"' >> ~/.bashrc
# per repo, optional:
git config --add gitwt.hook "npm install"      # or: uv sync / pnpm i — runs after `gitwt new`
git config --add gitwt.copy "**/.env.example"  # extra files to seed into new worktrees
```

Only the shell **function** can `cd` — a child process cannot change its caller's
directory. Running the script directly still creates the worktree and prints its
path; it just leaves you where you were, and says so.

## Layout & why
Worktrees live at `<repo-parent>/.wt/<repo>/<branch>`:
- **same drive** as the repo → avoids the Windows cross-drive cwd-drift trap (subagent writes
  landing in the wrong physical dir).
- **outside** the repo dir → main `git status` stays clean; no double-load of `CLAUDE.md`
  / `AGENTS.md` by tools that walk parent dirs.
  (Alt: some put worktrees under `.git/wt/` so tools ignore them entirely — also valid.)

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
   per-worktree `PORT` (3000–3999 from a path hash). (Pattern from waldencui's "direnv
   is all you need".) Requires `direnv`.
2. **Gitignored files don't follow** (`.env`) → copy-on-create via `.worktreeinclude`
   (Claude-compatible) and `git config gitwt.copy`.
3. **Deps need reinstalling** per worktree → `git config gitwt.hook "npm install"` runs
   automatically after `gitwt new`.

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
- no `readlink -f` (absent on macOS)

## References
- `references/gitwt` — the helper (put it on PATH, `chmod +x`).
- Git worktree docs: https://git-scm.com/docs/git-worktree
- direnv pattern: waldencui "direnv is all you need to parallelize … with git worktrees".
