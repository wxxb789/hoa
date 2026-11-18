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
fork it, install the skills you need with `npx skills`, take any part you like. Because it is
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
| Skills (`SKILL.md` packages) | **hoa** | `npx skills add wxxb789/hoa -s <skill>` → `~/<agent>/skills/` |
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
├── VERSION        # the one project version; skills carry their own metadata.revision
├── CHANGELOG.md   # notable changes; older entries retain historical per-skill versions
├── skills/        # THE deploy surface — SKILL.md packages installed via `npx skills`
├── paseo-plugins/ # optional Paseo plugin source; explicitly installed, never auto-deployed
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
missing symlinks flat at `<root>/<name>`, or at `<root>/<category>/<name>` with
`--category`, so a parent and the siblings it chains to through `../` share one
directory. It never replaces a real directory and never adds a second entry for
one skill.

## How this repository is shaped

Two axes describe everything here: **what an artifact is** (its surface) and **how a skill composes
with other skills** (its layer). `index.md` is the inventory; this section is the map.

### Four composition layers

Every `skills/<name>/SKILL.md` declares `metadata.kind`. CI rejects a missing or unknown value, so
the layer is a fact about the tree, not a label someone remembers to add.

| `kind` | What it is for | At this tree |
|---|---|---|
| `entry` | Directly routable from a user request. It may consume/produce artifacts, but it needs no controller to be invoked. | e.g. `ghc-search`, `hoa-skill-create`, `spec-convergence` |
| `controller` | Routes a chain: decides which stage runs, and produces only `chain-plan`. | `gdd` |
| `stage` | One phase of a chain, invoked by its controller. Declares what it consumes and produces. | none at present |
| `mechanism` | Invoked only by another skill; never a routing target. CI rejects it as a trigger-case `must_pick`. | `delegated-work-acceptance` |

### Surfaces

| Folder | What lives there | Deployed? |
|---|---|---|
| `skills/` | `SKILL.md` packages: the only deployable artifact. `npx skills add wxxb789/hoa -s <skill>` installs the ones you pick. | yes |
| `paseo-plugins/` | Optional Paseo plugin source, including the read-only GDD run observer. | manual opt-in only |
| `agents/` | 1 role / authority / I-O contract (`skill-scout`). | no — library |
| `mcps/` | 1 portable MCP definition (`ghc-proxy`). | no — library |
| `orchestration/` | 1 scheduling/handoff/termination pattern (`typed-verification-gates`). | no — library |
| `prompts/` | 5 per-task request templates. | no — library |
| `rules/` | 1 standing constraint (`generated-means-generated`). | no — library |
| `workflows/` | 1 finite outcome-oriented recipe (`adopt-a-pattern`). | no — library |
| `evals/` | Two case suites (`trigger-cases.json`, `skill-method-cases.json`) and their offline validators. | no — repo only |
| `reflections/`, `ref/` | Write-ups and external reference submodules; study material, never deployed. | no |
| `scripts/` | Repo maintenance: catalog, host parity, version/revision gates, contract graph, config resolver. | no |

A skill's frontmatter carries the catalog and composition fields together: `revision`, `kind`,
optional comma-separated `consumes` / `produces`, `areas`, `targets`, `summary`, `summary_zh`.
Library artifacts keep their metadata in an `<!-- index: ... -->` comment. `index.md` and
`index.zh-CN.md` are generated from those two sources and cover every artifact in the catalog; CI fails on drift.
Runtime **settings** (provider, models, plugins) are chezmoi's job, not this repo's.

### The contract graph

`scripts/check_contract_graph.py` reads every skill's `kind` / `consumes` / `produces`, builds the
artifact graph, and checks it offline (`--list` prints the graph). `scripts/contract_graph_registry.yaml`
registers three escape hatches: `external:` artifacts produced outside the skill graph (request,
work-report, git-commit, ci-result), `shared:` artifacts two skills may both produce (currently
none), and `terminal:` artifacts no skill consumes, each with a one-line reason (chain-plan,
spec, acceptance-verdict, scope-seal). Every rule is enforced by that command:

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
| R10 | A hidden skill (`disable-model-invocation: true`) listed in any trigger case's `must_pick`. |

### What CI runs

The `test` job runs on every push to `main`, every pull request, and `workflow_dispatch`. There is
no release job: `npx skills` installs straight from GitHub, so nothing is tagged or published.

The `test` job provisions the runtimes and dependencies, then runs
`python scripts/run_all_tests.py`. That discoverer schedules the commands below as entries in
`scripts/test_manifest.toml` rather than as separate CI steps (the table is being converged onto the
manifest in a later step of this series). It also schedules the Python suites that were never wired in
before —
`skills/delegated-work-acceptance/scripts/tests/test_worktree_scope.py` and
`skills/gdd/scripts/tests/test_paseo_run_python.py` — and the `paseo-plugins/gdd-run-observer` Vitest
package.

Settling is anti-false-green. Zero executed checks never settles PASS, and a counter must account for
every check it did not pass — including a suite that settles from a parent's log through
`covered_by`. Each suite runs in its own process group and task-local scratch tree; a suite that did
not finish under its own control — the runner timed it out, or a signal killed it — has the process
the run spawned terminated, while everything else that command left behind is *reported and left
alone*: the members of the group the command led, and the processes still holding the suite's
task-local scratch (found by the cwd they were started in or the scratch paths in their environment,
from `/proc`). The rule is deliberately narrow — **the runner signals only the process it spawned** —
because that is the one process whose identity it recorded itself; a same-group member, a scratch
holder or any descendant is named in the suite's record and keeps running, and the suite's teardown
is `unverified` whenever such a process is found, so the limit is readable in the result instead of
being silently absorbed. Nothing is ever broadcast to a process group, and no signal ever goes
through a bare pid or group number. The spawned process's identity — its pid and the start time
`/proc/<pid>/stat` field 22 read at spawn — is pinned *at delivery* rather than sampled before it: a
pidfd is opened for that pid (`os.pidfd_open`), the start time is re-read and must equal the recorded
one, and only then is the signal sent through `signal.pidfd_send_signal`. The pidfd pins that
process instance, so a pid someone else's reap recycled cannot receive the run's signal, a target
that is gone is reported as gone, a process that has already terminated takes no signal at all, and
escalation (TERM, a bounded grace, KILL) re-pins the target in every round instead of reusing an
earlier round's authority. The run also establishes its own `SIGCHLD` disposition (`SIG_DFL`) before
spawning anything and observes a command's exit without reaping it (`waitid` with `WNOWAIT`), which
is what keeps the pid from being recycled while the teardown still needs it; the group the command
led is read before the command is reaped, so what a clean exit left behind is reported while the
number is still the command's own. Where any of that proof cannot be held — no established or
still-live disposition, no kernel probe, no pidfd, no `/proc` to read the identity from, a
start-time re-check that fails, a target reaped by someone else — nothing is signalled and the
teardown is reported unverified; there is no fallback to `Popen`'s cached `returncode` (which cannot
see a reap) or to a bare pid or group number (which can name anything by the time it is used). Every
exit path — clean, timed out or signalled — publishes the teardown record, limits included, in the
suite's entry of the result, so a limit is readable by whoever reads the run and not only by the
helper that found it; and a command whose exit can no longer be waited for settles as an error
rather than taking the run down. **Residual limit, stated plainly:** the runner signals only the
process it spawned, so whatever else a suite leaves behind — a same-group member, a detached holder,
any descendant — outlives the run; the teardown's record names it and says it was left alone. The
gates bound the teardown's reach on real platforms: macOS and Windows expose no pidfds (and no
`/proc`), so there nothing is ever signalled — each teardown refuses and records that limit — while
on Linux the same run gates every delivery as described above.

| Gate command (CI step) | Protects |
|---|---|
| `python scripts/vendor_shared.py --check` | Vendored copies of shared scripts match their canonical file. |
| `python scripts/generate_index.py --check` | `index.md` / `index.zh-CN.md` match artifact metadata. |
| `python scripts/check_contract_graph.py` | Rules R1–R10 above. |
| `python scripts/check_skill_links.py` | Every `../<name>/` reference in a skill names an existing sibling skill and path, relative to the file that holds it; every `uv run <path>.py` in skill Markdown runs a script with a PEP 723 block, `uv run python` carries `--no-project`, and no bare `python`/`python3` runs a skill script. |
| `python -m unittest scripts.test_check_skill_links` | The link checker's own tests. |
| `python scripts/test_check_contract_graph.py` | The graph checker's own rule tests. |
| `python -m unittest scripts.test_skill_config` | Config resolution order and malformed-config behavior. |
| `python scripts/test_generate_index.py` | Catalog collection, summaries, bilingual fallback, drift. |
| `python -m unittest scripts.test_install_host_skills` | Host install parity (`--check` / `--link`), `../` closure, retired names. |
| `python -m unittest scripts.test_check_changelog` | The changelog rule's own tests. |
| `python scripts/check_frontmatter.py` | Every `SKILL.md` frontmatter and catalog field; 1024-char description cap; hidden flag agrees with `agents/openai.yaml`. |
| `python -m unittest scripts.test_check_frontmatter` | The frontmatter checker's own tests. |
| `python scripts/version.py check-bump` (pull requests) | `VERSION` is exactly `origin/main`'s patch + 1. |
| `python scripts/version.py check-revisions` (pull requests) | Every skill directory changed since the merge base raises its `metadata.revision`. |
| `python scripts/check_changelog.py --base origin/main` (pull requests) | A changed `VERSION` has a changed `CHANGELOG.md`. |
| `python scripts/test_version.py` | The `bump`, `check-bump` and `check-revisions` CLI against throwaway Git repos. |
| `python skills/ghc-search/scripts/test_ghc_search.py` | The search client's request/parse/error behavior. |
| `python skills/hoa-introspect/evals/run.py` | `hoa-introspect` eval fixtures. |
| `python skills/hoa-introspect-distill/evals/run_evals.py` | `hoa-introspect-distill` eval fixtures. |
| `python skills/define-goal/evals/validate_fixtures.py` | `define-goal` eval fixtures. |
| `python evals/run_trigger_evals.py` | Trigger-case structure, catalog cross-references, and baseline arithmetic (offline). |
| `python -m unittest evals.test_judge_trigger_evals` | Judge configuration precedence, exit codes, per-case failures, baseline writes, against a local stub. |
| `python evals/validate_skill_method_cases.py` | `skill-method-cases.json` structure and isolation paths. |
| `python -m unittest evals.test_validate_skill_method_cases` | Setup-file isolation for skill-method cases. |

The dependency install (`python -m pip install -r scripts/requirements.txt`) precedes the gates.
The judge's HTTP client is stdlib only; the catalog builder it imports uses the repo's PyYAML
tooling.

### How an eval case is graded — and what that proves

`evals/trigger-cases.json` holds the routing cases: an `id`, a user `request`, exactly one
`must_pick` artifact, and `distractors` that must not be chosen. The grader is an LLM in a fresh
context, and it is told only what a new contributor would see:

1. Build the catalog from `scripts/generate_index.py collect()`: name, type, and English summary
   for every artifact in the catalog.
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
replaced only with `--force`. The proposed record is checked with the gate's own rules before it is
written: a run containing transport errors or non-catalog answers cannot be represented in the
accepted schema, so the file is left untouched and the script exits 2 naming the offending cases
(re-run instead of losing the previous measurement); a wrong-but-catalog pick is recorded as the
failure it is. CI never calls the model: `run_trigger_evals.py` validates the
baseline's ids, catalog picks, recomputed pass flags and case totals offline, and reports
`no baseline recorded yet` before the first record.

The honest limit: one model, one prompt, one effort level, one curated case set. A pass rate says
that this judge on this date read these descriptions as intended; it is not evidence that users
will route the same way, that the descriptions are good, or that another model agrees. The baseline
pins model, effort, endpoint host and date precisely because changing any of them breaks
comparability. The suite proves discrimination on curated near-misses, not routing quality in the
wild.

## Versions and revisions

Two counters, each with one job:

- `VERSION` is the one project version (semver). Every pull request bumps its patch: CI requires
  exactly `origin/main`'s patch + 1, so a branch cut before another merge rebases and bumps again.
- `metadata.revision` in each `SKILL.md` is an integer string counting that skill's own iterations.
  A pull request raises it only for the skill directories it changes; a new skill starts at `"1"`.
  The project version is never copied into skills.

```bash
python -m pip install -r scripts/requirements.txt  # repository tooling; prefer a venv
python scripts/version.py bump             # patch by default: 0.1.0 -> 0.1.1
python scripts/version.py check-bump       # VERSION is origin/main's patch + 1
python scripts/version.py check-revisions  # every changed skill raised its revision
```

There are no releases, tags or binaries: `npx skills` installs from the GitHub default branch.
Local version commands never commit or push.


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
| `paseo-plugins/` | portable source packages explicitly installed as Paseo plugins | machine-specific plugin registration or runtime settings (→ chezmoi) |
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

**Skills** — the only deployable artifacts — install with the Vercel
[`skills`](https://github.com/vercel-labs/skills) CLI:

```bash
# 1. see what is available
npx skills add wxxb789/hoa --list

# 2. install only the skills you need, into the runtimes you use
npx skills add wxxb789/hoa -g -s <skill> -s <other-skill> -a claude-code -a codex

# update / remove
npx skills update
npx skills remove <skill>
```

**Install only what you need.** Do not install the whole library (`--all` or `-s '*'`): every
installed skill's description competes for routing in every session, and many skills here are
specialised (Hermes-coupled `hermes-*`, `gdd` and its launchers, repo maintenance). Read
[`index.md`](./index.md), pick the few that match your work, and add more later.

- Global (`-g`) installs to `~/<agent>/skills/` (`~/.claude/skills`,
  `~/.config/opencode/skills`, `~/.agents/skills`, …); default scope installs to
  the current project.
- **Symlink** by default (one canonical copy, easy updates) or `--copy` (Windows
  / no-symlink environments).
- Some skills chain to sibling skills through `../<child>/SKILL.md`. A copy install
  (`--copy`, Codex's skill-installer) must put that whole `../` dependency closure
  in the same skills root, or the chain breaks. On Windows the repo installer
  (`python scripts/install_host_skills.py --root <host-skills-dir> --link`, then
  `--check`; it links flat by default, and one `--category` keeps a parent and its children together)
  links whole directories with absolute-target symlinks, which need Developer Mode or
  admin; `--check` reports a missing or split closure and retired names still
  installed. See [`rules/cross-platform-skills.md`](./rules/cross-platform-skills.md).
- Everything else in `hoa` is **library / knowledge** — not auto-deployed. Fold
  it into a skill, or reference it by hand.
- Runtime **settings** deploy separately via `chezmoi apply`.

### GDD transport and optional Paseo observer

[`gdd`](./skills/gdd/SKILL.md) keeps the bundled `omp-run.py` headless launcher as its default.
Explicitly set `GDD_LAUNCHER` to the bundled `paseo-run.py` to make stages native Paseo agents;
that route requires a reachable daemon. Reachability never switches launchers automatically.
Read the [transport contract](./skills/gdd/references/transport.md) for configuration, answer
retrieval, completion rules, and the separate headless/native platform evidence.

[`paseo-plugins/gdd-run-observer`](./paseo-plugins/gdd-run-observer/README.md) is optional,
read-only observer source, **not a launcher**. It is not auto-installed by `npx skills` and does
not change the selected transport. Its [README](./paseo-plugins/gdd-run-observer/README.md)
documents clean-checkout dependency installation, typecheck/tests, trust, disable, and removal;
[HOA-INTEGRATION.md](./paseo-plugins/gdd-run-observer/HOA-INTEGRATION.md) documents the shared
`GDD_RUN_ROOT` and route integration. Review it before installing: plugins execute trusted,
unsandboxed code in the Paseo daemon/client. Runtime registration and settings remain local.

## Work on skills

Choose the capability by the work you want done, not by the model running it:

| Need | Skill | Result |
|---|---|---|
| Audit an existing skill, review a proposed change, or judge its behavior | `hoa-skill-review` | Evidence-backed findings; no changes to the reviewed skill |
| Create a skill from a defined capability, or evolve or compose an existing skill | `hoa-skill-create` | A complete skill change with validation results and any unverified paths |
| Discover recurring work in agent history | `hoa-introspect` | Evidence-cited work-pattern findings; no automatic creation |
| Qualify a supplied recurring-work finding before choosing an asset | `hoa-introspect-distill` | Individually approved candidate and, when approved, its created asset |
| Audit the whole skill set a session is offered for overlap, shadowing, drift, visibility and budget (hidden: run `/hoa-skill-set-audit`, Codex `$hoa-skill-set-audit`) | `hoa-skill-set-audit` | Ranked set-level findings with evidence; nothing changed |

For behavior changes, `hoa-skill-create` starts with focused checks and expands to multiple
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

Areas and targets are tracked as labels in [`index.md`](./index.md), not as folders
(one artifact often serves several). Custom skills store them as comma-separated
strings under standard YAML `metadata`, alongside their revision:

```yaml
metadata:
  revision: "1"
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

- **Anyone:** `npx skills add wxxb789/hoa --list`, then install the few skills you
  need with `-s <skill>`, or fork and take whichever parts help.
- **Me:** author skills here → `npx skills add wxxb789/hoa -g -s <skill> -a '*'` →
  they land in every runtime; settings ride along via chezmoi.
