# Repository architecture

> **English** · [简体中文](architecture.zh-CN.md) · [Repository home](../README.md)

The [generated index](../index.md) is the inventory. This guide describes two
different things: where an artifact belongs and how a skill composes with others.

## Surfaces: Where does it go?

Classify an artifact by its primary consumption interface, not its internals.

| Surface | Put this here | Keep this elsewhere |
|---|---|---|
| [`skills/`](../skills/) | A complete capability invoked by skill or command name, installed with `npx skills` | A prompt or role meant only to be assembled by something else |
| [`paseo-plugins/`](../paseo-plugins/) | Portable source of explicitly installed Paseo plugins | Machine-specific registration or runtime settings |
| [`agents/`](../agents/) | A single-agent role, authority, and I/O contract | Vendor settings or multi-agent scheduling |
| [`orchestration/`](../orchestration/) | Patterns for who runs when, handoff, retry, continuation, termination, or aggregation | A concrete finite recipe |
| [`prompts/`](../prompts/) | One-shot task templates | Standing rules or agent personas |
| [`rules/`](../rules/) | Always-on "must" and "never" constraints | One-off task instructions |
| [`workflows/`](../workflows/) | Finite steps toward an outcome | Retry, continuation, or agent scheduling controllers |
| [`evals/`](../evals/README.md) | Repeatably scored cases, fixtures, and rubrics | Prose analysis of results |
| [`reflections/`](../reflections/) | Observations, decisions, comparisons, and retros | Runtime fixtures, configs, or datasets |
| [`ref/`](../ref/README.md) | External submodules for study | Runtime code or install dependencies |
| [`scripts/`](../scripts/) | Catalog generation, vendoring, validation, and shared tooling such as config resolution | Machine-specific settings and hooks |
| [`docs/goals/`](goals/README.md), [`docs/plans/`](plans/) | Delivery contracts and planning records | Runtime inputs |

A runtime-specific stop hook belongs with runtime settings; a generic
continuation or termination pattern belongs in `orchestration/`. A multi-agent
capability invoked as a skill belongs in `skills/` even when it uses orchestration
internally. Only skills are installed by `npx skills`; Paseo plugins are manual
opt-ins. The other surfaces are for reference or repository maintenance.

## Composition layers

Each skill declares `metadata.kind` in its `SKILL.md`. This role is independent
of visibility:

| Kind | Role | Example |
|---|---|---|
| `entry` | Directly routable from a request, without a controller | `ghc-search`, `hoa-skill-create`, `spec-convergence` |
| `controller` | Routes a chain and produces only `chain-plan` | `gdd` |
| `stage` | A phase invoked by its controller, with declared inputs and outputs | No current example |
| `mechanism` | Invoked by another skill, never a routing target | `gdd-route-dsh` |

Hidden skills are still manually invocable. See the [composition rules](../rules/skill-composition.md)
for visibility, the Codex sidecar, and one-level Read links to flat siblings.

## Contract graph

`uv run --script scripts/check_contract_graph.py --list` prints the graph
built from `kind`, `consumes`, and `produces`. The
[registry](../scripts/contract_graph_registry.yaml) defines `external:` inputs
such as `request` and `ci-result`, `shared:` outputs with multiple producers
(none currently), and `terminal:` outputs such as `chain-plan` and `spec` that
do not need a consumer. The checker rejects:

| Rule | Rejects |
|---|---|
| R1, R2, R7 | An unknown or missing kind, including contracts declared without a kind |
| R3 | An input without a skill producer or external registration |
| R4, R10 | A mechanism or hidden skill in a trigger case's `must_pick` |
| R5, R8 | A controller whose only output is not `chain-plan`, or whose `SKILL.md` exceeds 120 lines |
| R6 | Multiple producers for an output not registered as shared |
| R9 | An output without a consumer or a terminal registration with a reason; external outputs are exempt |
| R11 | A visible mechanism not named or linked in another skill's `SKILL.md` or references |

## Catalog metadata and labels

Skills live at `skills/<name>/SKILL.md`. hoa uses a flat layout even though
`npx skills` also recognizes categorized layouts, including `skills/.curated/`,
`skills/.experimental/`, and `skills/.system/`. Skill frontmatter holds
`revision`, `kind`, optional `consumes` and `produces`, and the catalog fields:

```yaml
metadata:
  revision: "1"
  kind: entry
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "One line for the English catalog"
  summary_zh: "中文目录用一行"
```

- `areas`: `software-development`, `work-management`, `self-management`.
- `targets`: `runtime-agnostic`, `repo-only`, `claude-code`, `codex`,
  `opencode`, `hermes`, `pi`, `kimi-code`. Runtime names indicate the intended
  target for `npx skills --agent`.

Both labels accept comma-separated values; artifact type comes from its
folder. Library artifacts in `agents/`, `orchestration/`, `prompts/`, `rules/`,
and `workflows/` use an `<!-- index: ... -->` comment in `<name>.md` or
`<name>/README.md`. Each catalog name must be unique and each library folder
must have an artifact. Notes come from `summary` and `summary_zh`; a missing
English skill note falls back to the first sentence of its description, and a
missing Chinese note falls back to English.

After editing metadata, run `uv run --script scripts/generate_index.py` to
regenerate [both indexes](../index.md). Do not edit them or other
[generated files](../rules/generated-means-generated.md) by hand.

## What CI runs

[CI](../.github/workflows/ci.yml) runs on pushes to `main`, pull requests, and
manual dispatch. A newer push to a PR cancels the earlier run. The main ruleset
requires a PR and seven checks (`test`, plus `gdd-runner` and `gdd-observer`
on Linux, macOS, and Windows), blocks force-push and deletion, and allows admin
bypass. The repo uses squash merges, auto-merge, and branch deletion after merge.
The [nightly/manual Windows lifecycle stress workflow](../.github/workflows/gdd-windows-stress.yml)
is not required. There is no release job.

For local use, the Python floor is 3.13 and entry points use uv with PEP 723
metadata. CI pins 3.13, installs the test requirements and uv, and invokes
Python directly inside the job. The commands below are the local equivalents.

| Job or step | Local command or scope | Protects |
|---|---|---|
| Frontmatter | `uv run --script scripts/check_frontmatter.py` | Skill metadata; descriptions at most 350 characters when visible or 1024 when hidden; visibility flag and Codex sidecar agree |
| Contract graph | `uv run --script scripts/check_contract_graph.py` | R1 through R11 |
| Skill links | `uv run --script scripts/check_skill_links.py` | Sibling references resolve; skill script commands use uv and PEP 723, and inline Python uses `--no-project` |
| Catalog drift | `uv run --script scripts/generate_index.py --check` | Both indexes match the source metadata |
| Vendoring drift | `uv run --script scripts/vendor_shared.py --check` | Vendored files match their canonical sources |
| Revisions (PRs) | `uv run --script scripts/version.py check-revisions` | Changed skill directories raise their own revisions |
| pytest | `uv run --no-project --python 3.13 --with-requirements scripts/requirements.txt python -m pytest -n auto --dist load` | Collects `test_*.py` under `scripts/`, `evals/`, and `skills/`; 120-second per-test timeout |
| Standalone checks | Run each with `uv run --script`: trigger cases, define-goal fixtures, Hermes routing inventory and provider metadata, GDD verdict matrix and merge-gate mutation harness | Each named step has its own exit-code contract; see the workflow for exact paths |
| `gdd-runner` | Runner, detach supervisors, dispatch, no-window, Paseo adapter, and PR watcher test suites | Native cross-platform behavior, with platform-specific skips and a private tmux integration test on Linux |
| `gdd-observer` | `npm ci`, `npm run typecheck`, `npm test` in `paseo-plugins/gdd-observer` | Plugin typecheck and Vitest on all three platforms |

New `test_*.py` files in the collected directories need no registration.
A standalone check outside pytest needs its own named CI step.

## Routing eval grading and limits

Each [routing case](../evals/trigger-cases.json) has an `id`, a `request`, one
`must_pick` (an artifact name or `none`), and `distractors` that must not be picked.
The [live judge](../evals/judge_trigger_evals.py) uses a fresh context per case:

1. Build the listing from the index generator's `collect()`: show names, types,
   and full frontmatter descriptions for visible skills, English index notes
   for library artifacts, and no hidden skills.
2. Send the listing and request, but not `must_pick` or `distractors`.
3. Pass only if the stripped response exactly matches `must_pick`. Preserve
   other replies as picks; a transport or endpoint error fails that case only.

```sh
uv run --script evals/judge_trigger_evals.py --json \
  --base-url <openai-compatible-base> --model <judge-model> --effort low
```

Settings resolve from CLI flag, environment, `$XDG_CONFIG_HOME/evals/config.yaml`
(fallback `~/.config/evals/config.yaml`), then default. Keys are `base_url`,
`model`, `effort`, and optional `api_key`; env vars are `EVALS_BASE_URL`,
`EVALS_MODEL`, `EVALS_EFFORT`, and `EVALS_API_KEY`. The endpoint and model are
required (exit 2 if missing); effort defaults to `low` and is sent as
`reasoning_effort` in the OpenAI-compatible `POST /chat/completions`.

`--record` accepts only a full run; replacing the baseline requires `--force`.
The [baseline](../evals/baseline.json) records case counts, model, effort, endpoint
host, timestamp, totals, and per-case results. A transport error or a pick
outside the catalog and `none` prevents recording (exit 2); a valid wrong pick
is recorded as a failure. The [offline gate](../evals/run_trigger_evals.py) checks
case IDs, allowed picks, recomputed pass flags, and totals; without a baseline
it can still validate the cases. CI never calls the live judge.

This measures discrimination on curated cases for one judge, prompt, and effort,
not routing quality in the wild or agreement among models. Keep the model,
effort, endpoint, and date with the result. For task outcomes rather than routing,
use the separate [skill necessity runner](../evals/README.md#run-a-necessity-comparison):
forced activation checks the content with load evidence; natural activation checks
whether it helps under normal discovery. Its no-skill and terse arms are controls.
