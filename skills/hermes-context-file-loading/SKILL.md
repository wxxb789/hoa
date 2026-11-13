---
name: hermes-context-file-loading
description: >-
  Trace how Hermes assembles its system prompt from instruction files: which file loads from which
  directory, which project file wins when several exist, and which tier each rule lands in. Use when
  auditing or editing SOUL/AGENTS/MEMORY/USER files, deciding where a durable rule belongs, debugging
  an instruction file that did or did not take effect, or reasoning about subagent context and prompt
  cache stability. Not for editing the runtime source, and not for other harnesses' context files.
metadata:
  version: "0.1.52"
  areas: "software-development"
  targets: "hermes"
  summary: "which Hermes instruction file loads from where, which project file wins, and which prompt tier a rule belongs to"
  summary_zh: "Hermes 指令文件各自从何处加载、哪个项目文件生效，以及规则该放进哪个 prompt 层"
  kind: "entry"
---

# Hermes Context File Loading

<!-- install-root: `$HERMES_HOME` below means the install root; it defaults to `~/.hermes` -->

How Hermes builds its system prompt from instruction files. **Source-verified** against
`$HERMES_HOME/hermes-agent/agent/prompt_builder.py` (functions cited by line below) and the
official docs. Mechanics here override any vibe-based assumption — when in doubt, re-read
`prompt_builder.py` and the docs at the homepage above.

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
| **`SOUL.md`** | `load_soul_md()` (L1401) | **`HERMES_HOME/SOUL.md` ONLY** — never probes cwd | no | ✅ **YES — the only truly global file** |
| **`.hermes.md` / `HERMES.md`** | `_load_hermes_md` → `_find_hermes_md` (L80) | cwd, then walk **up parents to git root** | uses git root as the walk's stop boundary (no git → walks to filesystem root) | ❌ project-scoped |
| **`AGENTS.md` / `agents.md`** | `_load_agents_md` (L1452) | **`cwd / name` — that ONE directory only. No walk up, no recursion, no git** | no | ❌ binds to exact cwd |
| **`CLAUDE.md` / `claude.md`** | `_load_claude_md` (L1468) | cwd only | no | ❌ |
| **`.cursorrules` + `.cursor/rules/*.mdc`** | `_load_cursorrules` (L1484) | cwd only | no | ❌ |
| **`MEMORY.md`** | volatile tier (memory tool) | `HERMES_HOME/memories/MEMORY.md` | no | ✅ injected every turn |
| **`USER.md`** | volatile tier (memory tool) | `HERMES_HOME/memories/USER.md` | no | ✅ injected every turn |

`HERMES_HOME` = `$HERMES_HOME/` (or `$HERMES_HOME/profiles/<name>/` under a named profile; `$HERMES_HOME`
defaults to `~/.hermes` — substitute the install root in commands when yours is relocated).

## Critical precedence rule (project context = ONE slot)

`build_context_files_prompt()` (L1514) loads **exactly one** project-context type,
**first match wins**, in this order:

```
.hermes.md / HERMES.md   →   AGENTS.md   →   CLAUDE.md   →   .cursorrules
```

- They are **mutually exclusive**. If a `.hermes.md` exists, your `AGENTS.md` is **silently
  ignored** (HERMES.md outranks it). Creating `HERMES.md` next to a working `AGENTS.md` is a
  **footgun, not an upgrade**.
- **`SOUL.md` is independent** — always loaded as identity (slot #1), regardless of the
  project slot. It does not compete in the first-match race.

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
   - cwd = `~/proj` → `~/proj/AGENTS.md` loads ✓
   - cwd = `~/proj/sub` → top-level `AGENTS.md` does **NOT** auto-load (no walk-up).
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
   directory changes trigger the subdirectory-hint loader, so `cd ~/repos/<repo> && …` or a shell
   call with `workdir=<subdir>` appends that directory's `AGENTS.md` (up to 20k chars) to the tool
   result — a monorepo worktree can inject a full project map you never asked for. Operate with
   `git -C <path> …`, absolute paths, or `--workdir` at the level you actually need, and note that a
   *detached git worktree* carries its own copy of every instruction file in that snapshot.

7. **A profile home's `terminal.cwd` decides which repo contract that bot reads every turn.** Profile
   homes are independent `HERMES_HOME`s, but the project slot still follows the session cwd, so a bot
   whose `terminal.cwd` points at the front-door workspace loads the *front door's* operating contract
   (routing tables, delivery channels, board rules it has no authority to act on) as its own project
   context — a silent multi-thousand-token tax per turn. Audit before proposing any instruction
   restructure:

   ```bash
   python3 - <<'PY'
   import yaml, pathlib
   H = pathlib.Path.home()
   for f in [H/'.hermes/config.yaml', *sorted((H/'.hermes/profiles').glob('*/config.yaml'))]:
       d = yaml.safe_load(open(f)) or {}
       cwd = ((d.get('terminal') or {}).get('cwd'))
       agents = pathlib.Path(cwd)/'AGENTS.md' if cwd else None
       size = agents.stat().st_size if agents and agents.exists() else 0
       print(f"{str(f).replace(str(H),''):42} cwd={cwd}  AGENTS={size} B")
   PY
   ```

   Fix shape: give each bot its own workspace dir plus a short `AGENTS.md` (role delta + **pointers**
   to the shared clauses by name, never copies), and leave the front-door contract in the front door's
   cwd. Confirm the split did not drop a safety gate — pointer lines are the review surface.

   **Prove the split by the loaded title, not by the config value.** Run one one-shot in the bot's own
   home and ask it to reply with the first `#` heading of its `AGENTS.md`; then run the identical probe
   with cwd set to the front-door workspace. Two different headings (`Forge — 执行协议` vs
   `AGENTS.md — Zoe Operating Contract`) is the proof that cwd is doing the work; a `config get` only
   echoes what you wrote. A local-terminal CLI takes the caller's `os.getcwd()`, so the front-door run
   must be launched from that directory (or with `--in <dir>`) — otherwise both runs read the same file
   and look falsely identical.

## Decision shortcut

- "Make X apply everywhere, always" → put X in **`SOUL.md`**.
- "Project-specific rules for repo Y" → `AGENTS.md` at repo root (or `.hermes.md` if you want
  git-root reach across subdirs — but it then *displaces* AGENTS.md).
- "Stable fact / preference" → **`MEMORY.md`** (or `USER.md` for identity-of-the-user facts).
- "Reusable procedure" → a **skill** (not memory, not AGENTS).
- Never create `HERMES.md` and `AGENTS.md` side by side expecting both — first-match eats one.

## Verification recipe (re-confirm after Hermes upgrades)

```bash
SRC="${HERMES_HOME:-$HOME/.hermes}/hermes-agent/agent/prompt_builder.py"
# Confirm the loader functions and their scopes still match this skill:
grep -n "_load_agents_md\|_load_hermes_md\|_load_claude_md\|load_soul_md\|_find_git_root\|build_context_files_prompt" "$SRC"
```
Then read each function body. If scopes changed, **patch this skill immediately**
(`skill_manage action='patch'`). Docs: homepage URL in frontmatter +
`website/docs/developer-guide/prompt-assembly.md` in the repo.
