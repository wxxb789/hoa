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
├── VERSION        # canonical version shared by every custom skill
├── CHANGELOG.md   # notable changes; older entries retain historical per-skill versions
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
└── scripts/       # repo tooling: generate_index.py (index), install_host_skills.py (host parity), vendor_shared.py (shared skill scripts)
```

`skills/` follows the `npx skills` layout: `skills/<name>/SKILL.md` (flat) or
`skills/<category>/<name>/SKILL.md` (catalog); `skills/.curated/`,
`skills/.experimental/`, `skills/.system/` are recognized too.

`index.md` / `index.zh-CN.md` are **generated** — run
`python scripts/generate_index.py` after editing catalog metadata: YAML
`metadata.areas` / `metadata.targets` for custom skills, or `<!-- index: ... -->`
comments for library artifacts (CI fails on drift). Artifacts are
skills (`skills/<name>/SKILL.md`) and library files (`<folder>/<name>.md` or
`<folder>/<name>/README.md` under `agents/`, `mcps/`, `orchestration/`,
`prompts/`, `rules/`, `workflows/`). Each catalog name must be unique, every
configured library folder must hold at least one artifact, and each artifact's
index note comes from its own metadata: `metadata.summary` /
`metadata.summary_zh` for skills, `summary` / `summary_zh` in the index comment
for library artifacts, falling back to the first sentence of the description
(and, for Chinese, to the English note).

Host install parity is separate from the catalog: `python
scripts/install_host_skills.py --root <host-skills-dir> --check` searches
`<root>/<name>` and `<root>/<category>/<name>`, names every skill that is
absent, drifted, wrongly linked or has two entries, and `--link` creates the
missing symlinks at `<category>/<name>` — the skill's first `metadata.areas`
value unless `--category` overrides it (`.` links flat). It never replaces a
real directory and never adds a second entry for one skill.

## How this repository is shaped

Two axes describe everything here: **what an artifact is** (its surface) and **how a skill composes
with other skills** (its layer). `index.md` is the inventory; this section is the map.

### Four composition layers

Every `skills/<name>/SKILL.md` declares `metadata.kind`. CI rejects a missing or unknown value, so
the layer is a fact about the tree, not a label someone remembers to add.

| `kind` | What it is for | At this tree |
|---|---|---|
| `entry` | Directly routable from a user request. It may consume/produce artifacts, but it needs no controller to be invoked. | 37 skills, e.g. `ghc-search`, `hoa-skill-work`, `spec-convergence` |
| `controller` | Routes a chain: decides which stage runs, and produces only `chain-plan`. | `goal-driven-delivery` |
| `stage` | One phase of a chain, invoked by its controller. Declares what it consumes and produces. | `subagent-driven-development` (`plan` → `implementation`) |
| `mechanism` | Invoked only by another skill; never a routing target. CI rejects it as a trigger-case `must_pick`. | `delegated-work-acceptance` |

### Surfaces

| Folder | What lives there | Deployed? |
|---|---|---|
| `skills/` | 40 `SKILL.md` packages: the only auto-deployed artifact. `npx skills add wxxb789/hoa` installs them. | yes |
| `agents/` | 1 role / authority / I-O contract (`skill-scout`). | no — library |
| `mcps/` | 1 portable MCP definition (`ghc-proxy`). | no — library |
| `orchestration/` | 1 scheduling/handoff/termination pattern (`typed-verification-gates`). | no — library |
| `prompts/` | 4 per-task request templates. | no — library |
| `rules/` | 1 standing constraint (`generated-means-generated`). | no — library |
| `workflows/` | 1 finite outcome-oriented recipe (`adopt-a-pattern`). | no — library |
| `evals/` | Two case suites (`trigger-cases.json`, `skill-method-cases.json`) and their offline validators. | no — repo only |
| `reflections/`, `ref/` | Write-ups and external reference submodules; study material, never deployed. | no |
| `scripts/` | Repo maintenance: catalog, host parity, version/release, contract graph, config resolver. | no |

A skill's frontmatter carries the catalog and composition fields together: `version`, `kind`,
optional comma-separated `consumes` / `produces`, `areas`, `targets`, `summary`, `summary_zh`.
Library artifacts keep their metadata in an `<!-- index: ... -->` comment. `index.md` and
`index.zh-CN.md` are generated from those two sources and cover 49 artifacts; CI fails on drift.
Runtime **settings** (provider, models, plugins) are chezmoi's job, not this repo's.

### The contract graph

`scripts/check_contract_graph.py` reads every skill's `kind` / `consumes` / `produces`, builds the
artifact graph, and checks it offline (`--list` prints the graph). `scripts/contract_graph_registry.yaml`
registers three escape hatches: `external:` artifacts produced outside the skill graph (request,
work-report, git-commit, ci-result), `shared:` artifacts two skills may both produce (currently
none), and `terminal:` artifacts no skill consumes, each with a one-line reason (chain-plan,
implementation, acceptance-verdict, scope-seal). Every rule is enforced by that command:

| Rule | Rejects |
|---|---|
| R1 | A `kind` outside `entry`, `controller`, `stage`, `mechanism`. |
| R2 | `consumes` / `produces` declared without a `kind`. |
| R3 | A consumed artifact that no skill produces and that is not registered `external:`. |
| R4 | A `mechanism` listed in any trigger case's `must_pick` — mechanisms are never routing targets. |
| R5 | A controller that does not produce `chain-plan`, or that produces anything else. |
| R6 | One artifact produced by more than one skill unless it is registered `shared:`. |
| R7 | A skill that does not declare `kind` at all. |
| R8 | A controller `SKILL.md` longer than 120 lines. |
| R9 | A produced artifact that no skill consumes and that is not registered `terminal:` with a one-line reason; `external:` artifacts are exempt. |

### What CI runs

The `test` job runs on every push to `main`, every pull request, and `workflow_dispatch`; the
`release` job runs only after it on `main` and tags the commit CI tested.

| Gate command (CI step) | Protects |
|---|---|
| `bun install --frozen-lockfile && bun run check && bun test` in `scripts/shared`, `skills/teams-cdp/scripts`, `skills/m365-copilot-cdp/scripts` | Desktop CDP types and behavior in the shared code and both desktop skills. |
| `python scripts/vendor_shared.py --check` | Vendored copies of shared scripts match their canonical file. |
| `python scripts/generate_index.py --check` | `index.md` / `index.zh-CN.md` match artifact metadata. |
| `python scripts/check_contract_graph.py` | Rules R1–R9 above. |
| `python scripts/test_check_contract_graph.py` | The graph checker's own rule tests. |
| `python -m unittest scripts.test_skill_config` | Config resolution order and malformed-config behavior. |
| `python scripts/test_generate_index.py` | Catalog collection, summaries, bilingual fallback, drift. |
| `python -m unittest scripts.test_install_host_skills` | Host install parity (`--check` / `--link`). |
| `python -m unittest scripts.test_check_changelog` | The changelog rule's own tests. |
| `python scripts/check_frontmatter.py` | Every `SKILL.md` frontmatter and catalog field. |
| `python -m unittest scripts.test_check_frontmatter` | The frontmatter checker's own tests. |
| `python scripts/version.py check` | `VERSION` is mirrored by every skill and both indexes. |
| `python scripts/version.py check-bump` (pull requests) | `VERSION` is exactly `origin/main`'s patch + 1. |
| `python scripts/check_changelog.py --base origin/main` (pull requests) | A changed `VERSION` has a changed `CHANGELOG.md`. |
| `python scripts/version.py check-merge` (pull requests) | The version claim is still free on the remote before merge. |
| `python scripts/test_version.py` | Version, sync and release-guard behavior. |
| `python scripts/test_release.py` | Automatic release against isolated local Git remotes. |
| `python skills/ghc-search/scripts/test_ghc_search.py` | The search client's request/parse/error behavior. |
| `python skills/hoa-introspect/evals/run.py` | `hoa-introspect` eval fixtures. |
| `python skills/hoa-introspect-distill/evals/run_evals.py` | `hoa-introspect-distill` eval fixtures. |
| `python skills/define-goal/evals/validate_fixtures.py` | `define-goal` eval fixtures. |
| `python evals/run_trigger_evals.py` | Trigger-case structure, catalog cross-references, and baseline arithmetic (offline). |
| `python -m unittest evals.test_judge_trigger_evals` | Judge configuration precedence, exit codes, per-case failures, baseline writes, against a local stub. |
| `python evals/validate_skill_method_cases.py` | `skill-method-cases.json` structure and isolation paths. |
| `python -m unittest evals.test_validate_skill_method_cases` | Setup-file isolation for skill-method cases. |
| `python scripts/release.py` (release job, after `test` on `main`) | Publishes the version CI just tested; never bumps. |

The dependency install (`python -m pip install -r scripts/requirements.txt`) precedes the gates.
The judge's HTTP client is stdlib only; the catalog builder it imports uses the repo's PyYAML
tooling.

### How an eval case is graded — and what that proves

`evals/trigger-cases.json` holds 25 routing cases: an `id`, a user `request`, exactly one
`must_pick` artifact, and `distractors` that must not be chosen. The grader is an LLM in a fresh
context, and it is told only what a new contributor would see:

1. Build the catalog from `scripts/generate_index.py collect()`: name, type, and English summary
   for all 49 artifacts.
2. For one case, send the catalog and the request, and ask for exactly one artifact name.
3. Pass iff the stripped reply is exactly the case's `must_pick`. A reply that names no catalog
   entry is a failed case and is preserved verbatim as the pick. A network or endpoint error fails
   that case only; the rest of the batch completes.
4. `must_pick` and `distractors` are never shown to the judge.

The judge is configured, never compiled in. Endpoint, model, and effort resolve as CLI flag →
environment variable → `$XDG_CONFIG_HOME/evals/config.yaml` (fallback `~/.config/evals/config.yaml`)
→ documented default:

```bash
python evals/judge_trigger_evals.py --json \
  --base-url <openai-compatible-base> --model <judge-model> --effort low
```

The config keys are `base_url`, `model`, `effort` and optional `api_key`; the environment names are
`EVALS_BASE_URL`, `EVALS_MODEL`, `EVALS_EFFORT` and `EVALS_API_KEY`. The request is a plain
`POST <base_url>/chat/completions`; effort is sent as the `reasoning_effort` field. With none of
them supplied the script exits 2, prints the keys and the config path, and never guesses a model.
`--record` writes `evals/baseline.json` (`case_count`, `model`, `effort`, `passed`, `total`,
`judge_endpoint_host`, `generated_at`, `per_case`) for the full case set only; an existing record is
replaced only with `--force`. CI never calls the model: `run_trigger_evals.py` validates the baseline's ids, pass count
and case count offline, and reports `no baseline recorded yet` before the first record.

The honest limit: one model, one prompt, one effort level, one curated case set. A pass rate says
that this judge on this date read these descriptions as intended; it is not evidence that users
will route the same way, that the descriptions are good, or that another model agrees. The baseline
pins model, effort, endpoint host and date precisely because changing any of them breaks
comparability. The suite proves discrimination on curated near-misses, not routing quality in the
wild.

## Unified skill versions

`VERSION` is the release version for every custom package under `skills/`, starting
at `0.1.0`. Each SKILL.md mirrors it in standard YAML `metadata.version` so installed
packages retain the version. Catalog labels share the same metadata mapping;
custom-skill HTML index comments are rejected, not read as a fallback.
Third-party/reference trees and non-skill library artifacts keep their own metadata.

```bash
python -m pip install -r scripts/requirements.txt  # repository tooling; prefer a venv
python scripts/version.py check       # read-only consistency and index check
python scripts/version.py sync        # mirror VERSION and regenerate indexes
python scripts/version.py bump        # patch by default: 0.1.0 -> 0.1.1
python scripts/version.py bump minor  # explicit minor; major is also supported
```

Every pull request bumps the patch itself: CI requires `VERSION` to be exactly
`origin/main`'s version with the patch component +1, so a branch cut before another
merge must rebase and run `python scripts/version.py bump` again. After CI succeeds
on `main`, the release job only tags the version already committed by the merged
pull request (initially `v0.1.0` is published as-is); it never bumps or creates a
version commit. Publication retains the browser/CDP tests and all existing
repository gates, serializes releases, rejects stale tested heads, and pushes the
tag atomically without force.

Local version commands never commit or push. The CI-only release helper requires
`contents: write`; branch protection must permit its normal push. It does not
bypass repository policy. Re-running an already published push is a no-op.


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

## Desktop messaging automation

- [`teams-cdp`](./skills/teams-cdp/SKILL.md) discovers exact people and existing
  group chats, sends authorized plain text, and checks a new **Sent** receipt.
- [`m365-copilot-cdp`](./skills/m365-copilot-cdp/SKILL.md) operates desktop Copilot
  Chat and Code through local CDP, including model selection and reply reads.

Both packages use strict TypeScript, Bun, and `playwright-core`; they attach to
already signed-in applications without downloading another browser. Each skill
contains its own dependency manifest and lockfile. Local CDP must be enabled for
the actual working application surface; Code also requires a ready native host.
Read each skill's startup and authority instructions before using a real account.

## Labels

Areas and targets are tracked as labels in [`index.md`](./index.md), not as folders
(one artifact often serves several). Custom skills store them as comma-separated
strings under standard YAML `metadata`, alongside their version:

```yaml
metadata:
  version: "0.1.0"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "one line for the English catalog"
  summary_zh: "中文目录用一行"
```

Library artifacts retain their HTML index comments. Allowed label values:

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
