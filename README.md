# hoa — Hall of Armor

> **English** · [简体中文](./README.zh-CN.md)

[![CI](https://github.com/wxxb789/hoa/actions/workflows/ci.yml/badge.svg)](https://github.com/wxxb789/hoa/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

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
├── index.md · index.zh-CN.md   # every artifact, labeled by area + target (GENERATED — see scripts/)
├── CHANGELOG.md   # notable changes; skills carry per-skill `version=` metadata
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
└── scripts/       # repo tooling: generate_index.py (index), vendor_shared.py (shared skill scripts)
```

`skills/` follows the `npx skills` layout: `skills/<name>/SKILL.md` (flat) or
`skills/<category>/<name>/SKILL.md` (catalog); `skills/.curated/`,
`skills/.experimental/`, `skills/.system/` are recognized too.

`index.md` / `index.zh-CN.md` are **generated** — run
`python scripts/generate_index.py` after editing any artifact's
`<!-- index: ... -->` metadata comment (CI fails on drift). Artifacts are
skills (`skills/<name>/SKILL.md`) and library files (`<folder>/<name>.md` or
`<folder>/<name>/README.md` under `agents/`, `mcps/`, `orchestration/`,
`prompts/`, `rules/`, `workflows/`). Each catalog name must be unique, every
configured library folder must hold at least one artifact, and each artifact's
index note comes from a `NOTES` override in the generator or the first line of
its frontmatter description (plain-Markdown body as last resort).

## Bilingual policy

Docs are maintained in English and 简体中文. **English is the source of
truth**; the Chinese mirror follows in the same commit. Generated files
(indexes) come from a single source and are emitted in both languages, so
only hand-written docs pay the translation tax.

## Cloning

```bash
git clone https://github.com/wxxb789/hoa   # submodules NOT needed for skills/tests
```

`ref/` holds 35 reference repos as submodules — heavy, and only needed when
studying an upstream. A plain clone (no `--recursive`) is fully sufficient to
use and test everything else. Refresh the references when needed:
`git submodule update --init --remote --merge`.

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

## Work on skills

Choose the capability by the work you want done, not by the model running it:

| Need | Skill | Result |
|---|---|---|
| Audit an existing skill, review a proposed change, or judge its behavior | `hoa-skill-review` | Evidence-backed findings; no changes to the reviewed skill |
| Create a skill from a defined capability or improve an existing skill | `hoa-skill-work` | A complete skill change with validation results and any unverified paths |
| Discover recurring work in agent history | `hoa-introspect` | Evidence-cited work-pattern findings; no automatic creation |
| Qualify a supplied recurring-work finding before choosing an asset | `hoa-introspect-distill` | Individually approved candidate and, when approved, its created asset |

For behavior changes, `hoa-skill-work` starts with focused checks and expands to multiple
variants, models, or runtimes when reach, risk, or conflicting evidence warrants
it. `hoa-introspect-distill` retains its per-candidate approval gate; a direct
request to create or improve a defined skill does not need that intake flow.
`evals/skill-method-cases.json` holds the focused behavior scenarios; CI checks
their structure and isolation paths, while model/host behavior is judged in
fresh runs rather than claimed from the CI fixture check.
Claude Code's native `plugin eval` tests plugin-shaped packages; Anthropic's
`skill-creator` is a separate first-party plugin, and the earlier
`define-goal` review used CE guidance plus a session-written runner. None is
a required dependency of these runtime-agnostic hoa skills. The
[source-level ownership study](./reflections/2026-09-25-claude-code-skill-source.md)
distinguishes the implementations and their evidence limits.

## Labels

Areas and targets are tracked as labels in [`index.md`](./index.md) (generated
from each skill's `<!-- index: ... -->` comment), not as folders (one artifact
often serves several):

- `areas`: `software-development` · `work-management` · `self-management`
- `targets`: `runtime-agnostic` · `repo-only` · `claude-code` · `codex` ·
  `opencode` · `hermes` · `pi` · `kimi-code` (the `npx skills --agent` a skill is
  meant for)

Type is derived from the folder. Both axes are multi-valued.

## Reference map

[`ref/README.md`](./ref/README.md) maps **35 external agent/skill/harness
repos** to what each is and the specific pattern worth stealing from it — the
densest page in this repo if you are designing your own agent setup.

## Roadmap

- **Phase 1:** skeleton + definition + area/target-labeled index (taxonomy
  pressure-tested via Oracle). ✓
- **Phase 2:** skills-first deploy — `skills/` via `npx skills`, settings via
  chezmoi; `runtimes/` dropped. ✓
- **Phase 3:** grow real skills in `skills/`; generate `index.md` from
  per-artifact metadata (✓ `scripts/generate_index.py`, now covering library
  folders too); build out `evals/` + `reflections/` (first retro:
  `reflections/2026-09-23-skills-first-split.md`; trigger evals:
  `evals/trigger-cases.json`). ✓
- **Phase 4 (current):** make the library real — every library folder now
  carries at least one exemplar adapted from `ref/` (first steals: ECC's
  skill-scout → `agents/`, looper's typed gates → `orchestration/`); next:
  the first skill authored *by* the distill loop, and the first external
  consumer issue.

## Reflect cadence

Reflection is scheduled, not aspirational: run **hoa-introspect** monthly as a
self-retro and land the write-up in `reflections/`. The distill loop
(introspect → retrieve → distill) should produce its first self-authored skill
before the next phase closes.

## Request a skill

Public repo, open intake: if a capability here is missing or half-covers your
case, open an issue (bug or skill request) — the issue templates cover both.
External requests are also the best signal for what to build next.

## Using this repo

- **Anyone:** `npx skills add wxxb789/hoa` to install the skills, or fork and
  take whichever parts help.
- **Me:** author skills here → `npx skills add wxxb789/hoa -g` → they land in
  every runtime; settings ride along via chezmoi.
