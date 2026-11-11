---
name: hermes-context-file-loading
description: >-
  Trace how Hermes assembles its system prompt from instruction files: which file loads from which
  directory, which project file wins when several exist, and which tier each rule lands in. Use when
  auditing or editing SOUL/AGENTS/MEMORY/USER files, deciding where a durable rule belongs, debugging
  an instruction file that did or did not take effect, or reasoning about subagent context and prompt
  cache stability. Not for editing the runtime source, and not for other harnesses' context files.
metadata:
  version: "0.1.36"
  areas: "software-development"
  targets: "hermes"
  summary: "which Hermes instruction file loads from where, which project file wins, and which prompt tier a rule belongs to"
  summary_zh: "Hermes 指令文件各自从何处加载、哪个项目文件生效，以及规则该放进哪个 prompt 层"
  kind: "entry"
---

# Hermes Context File Loading

How Hermes builds its system prompt from instruction files. Mechanics here override any
vibe-based assumption — when in doubt, re-read the loader functions in
`$HERMES_HOME/hermes-agent/agent/prompt_builder.py` and the runtime's context-files docs page
(`user-guide/features/context-files/`). Function names are stable; line numbers drift between
versions, so locate by name.

## When to use this skill

- Auditing / editing `SOUL.md`, `AGENTS.md`, `MEMORY.md`, `USER.md`, or any context file.
- Deciding **which layer** a durable rule belongs in (identity vs project vs memory).
- Debugging "why did/didn't this instruction file take effect?"
- Reasoning about subagent context, cwd dependence, or prompt-cache stability.

> For a step-by-step **audit + surgical de-dup procedure** (backup → verify-paths → owner
> decisions → collapse-duplicates-to-pointer → memory-cap handling → verify), see
> `references/auditing-instruction-files-workflow.md`. Run it whenever the owner asks to clean,
> de-dup, or fix conflicts across the four instruction files.

## The one table that matters: file → mechanism

| File | Loader fn (`prompt_builder.py`) | Discovery scope | git? | Global? |
|------|--------------------------------|-----------------|------|---------|
| **`SOUL.md`** | `load_soul_md()` | **`HERMES_HOME/SOUL.md` ONLY** — never probes cwd | no | ✅ **YES — the only truly global file** |
| **`.hermes.md` / `HERMES.md`** | `_load_hermes_md` → `_find_hermes_md` | cwd, then walk **up parents to git root** | uses git root as the walk's stop boundary (no git → walks to filesystem root) | ❌ project-scoped |
| **`AGENTS.md` / `agents.md`** | `_load_agents_md` | **`cwd / name` — that ONE directory only. No walk up, no recursion, no git** | no | ❌ binds to exact cwd |
| **`CLAUDE.md` / `claude.md`** | `_load_claude_md` | cwd only | no | ❌ |
| **`.cursorrules` + `.cursor/rules/*.mdc`** | `_load_cursorrules` | cwd only | no | ❌ |
| **`MEMORY.md`** | volatile tier (memory tool) | `HERMES_HOME/memories/MEMORY.md` | no | ✅ injected every turn |
| **`USER.md`** | volatile tier (memory tool) | `HERMES_HOME/memories/USER.md` | no | ✅ injected every turn |

`HERMES_HOME` = `~/.hermes/` by default (or `~/.hermes/profiles/<name>/` under a named profile).
The default path is a runtime convention; a deployment may point `HERMES_HOME` elsewhere.

## Critical precedence rule (project context = ONE slot)

`build_context_files_prompt()` loads **exactly one** project-context type, **first match wins**, in
this order:

```
.hermes.md / HERMES.md   →   AGENTS.md   →   CLAUDE.md   →   .cursorrules
```

- They are **mutually exclusive**. If a `.hermes.md` exists, your `AGENTS.md` is **silently
  ignored** (`HERMES.md` outranks it). Creating `HERMES.md` next to a working `AGENTS.md` is a
  **footgun, not an upgrade**.
- **`SOUL.md` is independent** — always loaded as identity (slot #1), regardless of the project
  slot. It does not compete in the first-match race.

## Prompt-assembly tiers (cache discipline)

`agent/system_prompt.py` joins three tiers: **`stable` → `context` → `volatile`**.

| Tier | Holds | Cache behavior |
|------|-------|----------------|
| **stable** | `SOUL.md` identity (or `DEFAULT_AGENT_IDENTITY` fallback), tool/model guidance, **skills index**, env/platform hints | cached; stable across turns |
| **context** | caller `system_message` + the ONE project file (`.hermes.md`/`AGENTS.md`/`CLAUDE.md`/`.cursorrules`) | cached |
| **volatile** | `MEMORY.md` snapshot, `USER.md` snapshot, external memory block, timestamp/session/model line | cached but refreshed; **injected every turn** |

Implication for de-dup: **SOUL (stable) and AGENTS (context) sit in different tiers** — any rule
duplicated across them is pure prompt weight. **MEMORY + USER (volatile) re-inject every turn** —
duplicating facts across those two costs tokens on *every* call. De-dup volatile first.

## Hard facts to design around

1. **Want a rule global / cwd-independent / loaded every session → it MUST live in `SOUL.md`.**
   `AGENTS.md`, `HERMES.md`, `CLAUDE.md`, `.cursorrules` are ALL cwd-bound. None can be made
   global by relocating into `$HERMES_HOME/` — that is not their mechanism. Putting `HERMES.md` or
   `AGENTS.md` in `$HERMES_HOME/` does **nothing** unless your session cwd happens to be there.

2. **`AGENTS.md` binds to the EXACT cwd directory, not a subtree.**
   - cwd = `/home/user/proj` → `/home/user/proj/AGENTS.md` loads ✓
   - cwd = `/home/user/proj/sub` → top-level `AGENTS.md` does **NOT** auto-load (no walk-up).
     Subdirectory `AGENTS.md` files load via a *separate* progressive-discovery mechanism
     (`agent/subdirectory_hints.py`), appended to tool results only when the agent reads files
     in that subdir, and only that subdir's own file.
   - **AGENTS.md does NOT require a git repo.** Verified: a non-git dir still loads its AGENTS.md.

3. **`HERMES.md` uses git root only as a search boundary**, not a requirement. No `.git` → it
   walks up to the filesystem root. It still works without git; git just caps the walk.

4. **Subagent delegation skips project context + SOUL.** When `skip_context_files` /
   `skip_soul` is set (e.g. `delegate_task`), Hermes uses the hardcoded `DEFAULT_AGENT_IDENTITY`
   and loads **no** project file. → Subagents do NOT see your SOUL persona or AGENTS contract.
   Pass anything they need explicitly in the delegation `context`.

5. **Limits & processing:** each context file is security-scanned (`_scan_context_content`,
   prompt-injection patterns from `tools/threat_patterns.py`), then truncated at **~20,000 chars**
   (head/tail). YAML frontmatter is stripped from `.hermes.md` before injection
   (`_strip_yaml_frontmatter`). Empty file → nothing added.

6. **`cd` into a directory with its own `AGENTS.md` costs context, silently.** Command-level
   directory changes trigger the subdirectory-hint loader, so `cd <repo> && …` or a shell
   call with `workdir=<subdir>` appends that directory's `AGENTS.md` (up to 20k chars) to the tool
   result — a monorepo worktree can inject a full project map you never asked for. Operate with
   `git -C <path> …`, absolute paths, or `--workdir` at the level you actually need, and note that a
   *detached git worktree* carries its own copy of every instruction file in that snapshot.

## Decision shortcut

- "Make X apply everywhere, always" → put X in **`SOUL.md`**.
- "Project-specific rules for repo Y" → `AGENTS.md` at repo root (or `.hermes.md` if you want
  git-root reach across subdirs — but it then *displaces* AGENTS.md).
- "Stable fact / preference" → **`MEMORY.md`** (or `USER.md` for identity-of-the-user facts).
- "Reusable procedure" → a **skill** (not memory, not AGENTS).
- Never create `HERMES.md` and `AGENTS.md` side by side expecting both — first-match eats one.

## Verification recipe (re-confirm after Hermes upgrades)

```bash
SRC="$HERMES_HOME/hermes-agent/agent/prompt_builder.py"
# Confirm the loader functions and their scopes still match this skill:
grep -n "_load_agents_md\|_load_hermes_md\|_load_claude_md\|load_soul_md\|_find_git_root\|build_context_files_prompt" "$SRC"
```

Then read each function body. If scopes changed, **patch this skill immediately**. Docs: the
context-files page under `user-guide/features/` plus `website/docs/developer-guide/prompt-assembly.md`
in the runtime repo.
