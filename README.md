# hoa: Agent skills and goal-driven delivery

> **English** · [简体中文](README.zh-CN.md)

[![hoa CI status](https://github.com/wxxb789/hoa/actions/workflows/ci.yml/badge.svg)](https://github.com/wxxb789/hoa/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

hoa is an open collection of skills for AI coding agents: get ready-to-use
Claude Code skills or install them for Codex, OpenCode, Pi, and other runtimes
with [`npx skills`](https://github.com/vercel-labs/skills), or use
[gdd for goal-driven delivery](docs/gdd.md).

## Install agent skills

Pick a skill from the [catalog](index.md#catalog), then use its generated command
in the [install guide](index.md#install). For a standalone skill, for example:

```sh
npx skills add wxxb789/hoa -g -s official-document-verification
```

`-g` installs globally; omit it for the current project. Add `-a <agent>` to
choose a runtime. For skills with siblings, use the generated command so they
land in the same skills root: `npx skills` does not install dependencies
automatically. To install the collection, use the generated **Without Hermes**
command unless you also want the Hermes-only skills.

## What's inside

This is a monorepo of separate parts, not a harness you have to install as a
unit. Use the parts you need; individual skills can have documented dependencies.

### Agent skill catalog

The installable [`skills/`](skills/) catalog is for people looking for reusable
agent capabilities across software development, work management, and
self-management. Start with the [generated skill catalog](index.md#catalog).

- **Evidence and verification:** audit claims, check official documents, and
  verify delegated work or measurement campaigns.
- **Skill lifecycle:** `hoa-skill-*` skills create, review, port, curate, and audit
  skills. There are also explicit-only practice and repository retros.
- **Writing:** draft and revise publishable prose, including analytical
  arguments backed by evidence.
- **Delivery:** define deliverables, check package releases, and close out
  project phases.
- **Other capabilities:** converge on a spec, consolidate research, and work
  with individual tools such as Discord.
- **Hermes operations (opt-in):** `hermes-*` skills are only for people operating
  Hermes, including model routing, Kanban, updates, and runtime repairs.

### gdd: Goal-driven delivery

For repository owners handing off a written, machine-checkable increment,
[`gdd`](skills/gdd/SKILL.md) defines the delivery protocol: goal, staged agent
runs, operator-run gates, and a scripted merge check. Install the agent route
separately. OMP (`gdd-route-omp`) is the only model-visible route; DeepSeek
Harness, Codex, Claude Code, Pi, and OpenCode routes are hidden. The optional
[Paseo GDD Observer](paseo-plugins/gdd-observer/README.md) is a read-only plugin,
not part of skill installation.

Start with the [gdd delivery and transport guide](docs/gdd.md).

### Routing and skill necessity evals

For maintainers and evaluators: routing cases test which skill a request should
select, while the necessity runner compares task outcomes with no skill, terse
instructions, and the full skill. CI validates routing cases and the recorded
baseline offline; live comparisons are separate.

Start with the [evaluation runner guide](evals/README.md).

### Repository tooling and CI gates

For contributors maintaining hoa: [`scripts/`](scripts/) generates the indexes,
checks vendored files, and validates metadata, links, composition, and revisions.
[`rules/`](rules/) defines the repository's standing constraints. These are
repo-only tools and rules, not an installed runtime.

Start with the [CI gate map](docs/architecture.md#what-ci-runs).

### Small library of roles, patterns, prompts, and recipes

For people assembling their own agent workflows: [`agents/`](agents/) holds a
role contract, [`orchestration/`](orchestration/) a verification-gate pattern,
[`prompts/`](prompts/) task templates, and [`workflows/`](workflows/) a finite
recipe. This is a small reference library for manual reuse, not a package.

Start with the [library guide](docs/library.md).

### External reference submodules

For people studying upstream agent, skill, and harness projects:
[`ref/`](ref/README.md) maps external repos to patterns worth studying.
The shallow submodules track upstream default branches via daily Dependabot
updates. They are never deployed and are not needed to install skills or run
repo tests.

### Reflections, goals, and plans

For readers tracing how hoa evolved: [`reflections/`](reflections/) holds
comparisons, decisions, and retrospectives; [`docs/goals/`](docs/goals/README.md)
and [`docs/plans/`](docs/plans/) record work contracts and plans. These are
working and historical records, not runtime inputs.

Start with the [notes and project history](docs/contributing.md#notes-and-project-history).

## Supported runtimes

Use the catalog with Claude Code, Codex, OpenCode, Pi, Kimi Code, or another
[`npx skills`-supported runtime](https://github.com/vercel-labs/skills).
Check individual skills for prerequisites and runtime-specific behavior;
Hermes operations require Hermes, and gdd routes have their own CLI requirements.
Skills that run Python scripts require uv and Python 3.13 or newer.

## License and project links

[MIT license](LICENSE) · [Changelog](CHANGELOG.md) ·
[Architecture](docs/architecture.md) · [Contributing and skill requests](docs/contributing.md)
