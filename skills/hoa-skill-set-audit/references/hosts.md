# Host skill roots, precedence, hiding and listing budgets

Defaults as verified on 2026-11-17. A host's own docs and config win over this table; add any
root its config names (`--root`). `~` is the home directory (`%USERPROFILE%` on Windows, `$HOME`
elsewhere); `inventory.py` resolves it with `Path.home()`. `<project>` is `--project` (default cwd).

## Roots and same-name resolution

Preset order is the `--host` scan order: highest precedence first where the host documents it.

| Host | `--host` roots | Discovery depth | Same name in two roots |
|---|---|---|---|
| Claude Code | `$CLAUDE_CONFIG_DIR/skills` (default `~/.claude/skills`), `<project>/.claude/skills`; plugin skills are namespaced `plugin:name` and appear in the listing only | one level (`<root>/<name>/SKILL.md`) | personal beats project ([docs](https://code.claude.com/docs/en/skills)); plugin names cannot collide |
| Codex | `<project>/.agents/skills`, `$CODEX_HOME/skills` (default `~/.codex/skills`, incl. `.system`), `~/.agents/skills` | recursive up to 6 levels in recursive mode; nested `SKILL.md` become separate skills | not verified — report both copies |
| Pi | `<project>/.pi/skills`, `~/.pi/agent/skills`, plus settings `skills` paths | stops at the first `SKILL.md`; skips dot-dirs and `node_modules` | not verified |
| OMP | `<project>/.omp/skills`, `~/.omp/agent/skills` (native roots not verified), `~/.agents/skills` (`skills.enableAgentsUser`, default true); `~/.claude/skills` only when `skills.enableClaudeUser` is true (default false) — not in the preset, add it with `--root` | one level | native (100) > claude (80) > agents (70); identical copies dedup by realpath; a differing copy is namespaced (`<namespace>/name`) and the bare name silently returns the higher-precedence copy |
| OpenCode | `<project>/.opencode/skills`, `~/.config/opencode/skills`, and the `.claude/skills` / `.agents/skills` compat roots | grouping dirs up to 6 levels; never inside a skill dir | not verified |
| DSH | `<project>/.dsh/skills`, `<project>/.agents/skills`, custom dirs, `~/.dsh/skills` (skips `.system`), `~/.agents/skills`, bundled | not documented | rank order as listed (DSH `docs/subsystems/skills.md`) |

Claude Code plugin installs live in a versioned cache that also holds inactive versions; take
plugin skills from the session listing, not from scanning the cache.

## Hiding (hidden = not advertised, still user-invocable)

| Host | Frontmatter / file | Settings | Manual invocation |
|---|---|---|---|
| Claude Code | `disable-model-invocation: true` (puts no description in context; blocks the Skill tool) | `skillOverrides`: `on`, `name-only`, `user-invocable-only`, `off` (not plugin skills) | `/x` |
| Codex | ignores the frontmatter key; `agents/openai.yaml` `policy.allow_implicit_invocation: false` | `[[skills.config]] enabled = false` removes, last match wins | `$x` |
| Pi | `disable-model-invocation: true` | `!pattern` / `-path` **removes** the skill | `/skill:x` |
| OMP | `disable-model-invocation: true` | `skills.manualSkills` globs hide, keep manual | `/skill:x` |
| OpenCode | `metadata.opencode/autoinvoke: false` wins over `disable-model-invocation` | permission rule with `effect: deny` **removes** and rejects loading | `@x` |
| DSH | `disable-model-invocation: true` (camelCase key is dropped) | — | `/x` |

`user-invocable: false` removes the skill from the user's menu; it is never the hiding switch. A
removal setting (Pi `!pattern`, OpenCode deny, Codex `enabled = false`) on a skill a parent chains
to breaks that parent.

## Listing budget and truncation

| Host | Budget | Per entry | On overflow |
|---|---|---|---|
| Claude Code | 1% of the context window (`skillListingBudgetFraction`, or fixed `SLASH_COMMAND_TOOL_CHAR_BUDGET`) | 1,536 chars of `description` + `when_to_use` (`skillListingMaxDescChars`) | least-invoked skills lose their descriptions first ([docs](https://code.claude.com/docs/en/skills#skill-descriptions-are-cut-short)) |
| Codex | 2% of the window in tokens (~4 chars/token); `skills.max_context_tokens` replaces it (capped at 10,000); 8,000 chars when the window is unknown | 1,024 chars | drops all descriptions, then whole skills ("N additional skills were not included") — `codex-rs/ext/skills/src/render.rs` |
| DSH | — | `catalogDescriptionMaxLength`, default 500 | truncates the catalog text |
| Spec | — | `description` 1-1,024 chars ([agentskills.io](https://agentskills.io/specification)) | — |

Estimate: `visible_description_chars` from the inventory plus ~`len(name) + 4` per visible entry,
against the host budget for the session's window. A listing line with a name and no description is
direct evidence the budget is already exceeded.

## Shadowing

Selection, not token load, dominates the loss as the visible set grows: pooled pass rate fell 8, 14
and 21 pp versus oracle-only at 52, 102 and 202 skills, and at 202 about two thirds of the drop was
mis-selection ([arXiv 2605.24050](https://arxiv.org/abs/2605.24050)). Treat the visible count as a
budget; every hidden, retired or merged skill removes a distractor.
