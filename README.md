# hoa — Hall of Armor

> **English** · [简体中文](./README.zh-CN.md)

A personal home for the **portable parts** of how I run AI agents across my whole
operation — software development, company / project management, and personal
self-management. Skills, agent roles, orchestration patterns, prompts, rules,
MCP configs, workflows, and evals live here under version control. The
deployable ones — **skills** — install into every runtime with
[`npx skills`](https://github.com/vercel-labs/skills); runtime **settings** (LLM
provider, models, plugins) stay in chezmoi.

Named after Tony Stark's *Hall of Armor*: the workshop where every suit is
built, stored, compared, and improved — gear for every mission, not one narrow
focus.

## Two disciplines

This repo is a practice ground for two crafts:

- **Harness engineering** — *capability = model × harness.* A harness is
  everything wrapped around the model: context, tools, control loop, memory,
  permissions, output handling. `hoa` doesn't store whole harnesses — a harness
  is an *assembly*: the runtime's own **settings** (managed by chezmoi) plus
  **portable parts** from here (`skills/` installed via `npx skills`, with
  `agents/` `prompts/` `rules/` `mcps/` as the library they draw on).
- **Orchestration & loop engineering** — the control structures that drive
  iterative, multi-agent work: continuation, termination, retry, handoff,
  fan-out / fan-in, best-of-N. Loops are one shape of orchestration, so they
  live in `orchestration/`, not a `loops/` folder.

## Personal aim, public repo

Built for my **personal** use, but the repository is **public** — clone it,
fork it, `npx skills add wxxb789/hoa`, take any part you like. Because it is
public, **no secrets and no personal information are ever tracked by git** (see
[`.gitignore`](./.gitignore)): commit templates and sanitized assets only; real
credentials and private content stay untracked (`.env`, `*.key`, `*.token`,
`*.local.*`, `private/`) or live in a secret manager.

## What it's for

1. **Manage** — one versioned home for the portable agent parts, instead of
   copies scattered across `~/.claude`, `~/.codex`, `~/.config/opencode`, …
2. **Deploy** — `skills/` installs into every runtime with `npx skills`;
   runtime **settings** are deployed by chezmoi. `hoa` reinvents neither.
3. **Reflect** — analyze / review / retro how I use AI agents: which setup wins
   which task, what worked, what broke, why I chose X.

## Runtimes in scope

Hermes · Claude Code · Codex · pi · OpenCode · Kimi Code · *(any of the 70+
agents `npx skills` supports)*

## `hoa` ↔ chezmoi (who owns what)

| Concern | Owner | Mechanism |
|---|---|---|
| Skills (`SKILL.md` packages) | **hoa** | `npx skills add wxxb789/hoa` → `~/<agent>/skills/` |
| Agent roles, orchestration, prompts, rules, mcps, workflows, evals | **hoa** | version-controlled library / knowledge (composed into skills or used by hand) |
| Reflections & external refs | **hoa** | knowledge, never deployed |
| Runtime **settings** — LLM provider, models, plugins, `settings.json` / `config.toml` / `opencode.json` | **chezmoi** | `chezmoi apply` |

The split is deliberate: chezmoi already handles machine-specific settings and
secret templating; `hoa` handles the portable, shareable parts. No overlap, no
custom deploy tooling.

## Structure

```text
hoa/
├── index.md · index.zh-CN.md   # every artifact, labeled by area + target
├── skills/        # THE deploy surface — SKILL.md packages installed via `npx skills`
├── agents/        # portable, runtime-agnostic role / persona / authority / I-O contracts
├── orchestration/ # scheduling, handoff, retry, continuation, termination, aggregation (loops, crews, fan-out/in, best-of-N)
├── mcps/          # portable MCP server definitions & catalogs
├── prompts/       # per-task prompt templates
├── rules/         # always-on normative constraints / reusable rulesets
├── workflows/     # outcome-oriented finite recipes (no retry / termination controller)
├── evals/         # repeatable benchmarks, cases, fixtures, rubrics, sanitized datasets
├── reflections/   # human write-ups: comparisons, decisions, retros, post-mortems
├── ref/           # external references
└── scripts/       # this repo's own validation / index tooling
```

`skills/` follows the `npx skills` layout: `skills/<name>/SKILL.md` (flat) or
`skills/<category>/<name>/SKILL.md` (catalog); `skills/.curated/`,
`skills/.experimental/`, `skills/.system/` are recognized too.

## Where does it go? (classification)

Classify by an artifact's **primary consumption interface**, not by what it uses
internally.

| Folder | Belongs here | Not here |
|---|---|---|
| `skills/` | a whole capability invoked by skill / command name; deployable via `npx skills` | a prompt or role meant only to be assembled by something else |
| `agents/` | a single-agent role contract many runtimes could implement | vendor-specific runtime settings (→ chezmoi); crew scheduling (→ `orchestration/`) |
| `orchestration/` | decides who runs when, how results flow, whether to retry / stop | a concrete business recipe (→ `workflows/`) |
| `mcps/` | portable MCP endpoint / tool definition | vendor-specific registration in `settings.json` (→ chezmoi) |
| `prompts/` | a one-shot, per-task request template | standing behavioral constraints (→ `rules/`); persona (→ `agents/`) |
| `rules/` | "always / never / must" standing constraints | one-off task instructions (→ `prompts/`) |
| `workflows/` | outcome-centered finite steps | anything owning retry / continuation / agent scheduling (→ `orchestration/`) |
| `evals/` | machine-runnable / repeatably-scored inputs + rubrics | prose analysis of results (→ `reflections/`) |
| `reflections/` | observations, conclusions, decisions, retros | fixtures / configs / datasets used at run time |
| `scripts/` | maintains the `hoa` repo itself | runtime settings or hooks (→ chezmoi) |

> Edge cases: a stop-hook that tweaks a runtime is **settings** → chezmoi; a
> generic continuation / termination pattern → `orchestration/`. A multi-agent
> skill like `/security-review` is a `skill/` (its external interface), even
> though it uses orchestration inside.

## Deploy

**Skills** — the only auto-deployed artifacts — install with the Vercel
[`skills`](https://github.com/vercel-labs/skills) CLI:

```bash
# install all hoa skills into every detected runtime (global)
npx skills add wxxb789/hoa -g

# just some skills, into specific runtimes
npx skills add wxxb789/hoa -g -s <skill> -a claude-code -a opencode

# list before installing / update / remove
npx skills add wxxb789/hoa --list
npx skills update
npx skills remove <skill>
```

- Global (`-g`) installs to `~/<agent>/skills/` (`~/.claude/skills`,
  `~/.config/opencode/skills`, `~/.agents/skills`, …); default scope installs to
  the current project.
- **Symlink** by default (one canonical copy, easy updates) or `--copy` (Windows
  / no-symlink environments).
- Everything else in `hoa` is **library / knowledge** — not auto-deployed. Fold
  it into a skill, or reference it by hand.
- Runtime **settings** deploy separately via `chezmoi apply`.

## Labels

Areas and targets are tracked as labels in [`index.md`](./index.md), not as
folders (one artifact often serves several):

- `areas`: `software-development` · `work-management` · `self-management`
- `targets`: `runtime-agnostic` · `repo-only` · `claude-code` · `codex` ·
  `opencode` · `hermes` · `pi` · `kimi-code` (the `npx skills --agent` a skill is
  meant for)

Type is derived from the folder. Both axes are multi-valued.

## Roadmap

- **Phase 1:** skeleton + definition + area/target-labeled index (taxonomy
  pressure-tested via Oracle). ✓
- **Phase 2:** skills-first deploy — `skills/` via `npx skills`, settings via
  chezmoi; `runtimes/` dropped. ✓
- **Phase 3:** grow real skills in `skills/`; generate `index.md` from
  per-artifact metadata; build out `evals/` + `reflections/`.

## Using this repo

- **Anyone:** `npx skills add wxxb789/hoa` to install the skills, or fork and
  take whichever parts help.
- **Me:** author skills here → `npx skills add wxxb789/hoa -g` → they land in
  every runtime; settings ride along via chezmoi.
