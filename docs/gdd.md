# gdd: Goal-driven delivery and agent routes

> **English** · [简体中文](gdd.zh-CN.md) · [Repository home](../README.md)

Use the [gdd protocol](../skills/gdd/SKILL.md) when a written goal defines one
machine-checkable repository increment. It coordinates fresh authoring runs per
stage, operator-run gates, a scripted merge check, and a resumable ledger.
The [goal contracts directory](goals/README.md) shows where this repo keeps its
active contracts.

## Headless routes

The default launcher is the bundled `agent_run.py` headless runner;
`GDD_AGENT` picks the CLI (default `omp`). Install the selected route skill
separately, into the same skills root. In the current route design the shared
runner handles processes, discovers installed sibling routes, and reports
which are installed if the selected route is missing. A default agent name
does not install a route.

| Agent | `GDD_AGENT` | Route skill | Visibility |
|---|---|---|---|
| OMP | `omp` | `gdd-route-omp` | Visible |
| DeepSeek Harness | `dsh` | `gdd-route-dsh` | Hidden |
| Codex | `codex` | `gdd-route-codex` | Hidden |
| Claude Code | `claude` | `gdd-route-cc` | Hidden |
| Pi | `pi` | `gdd-route-pi` | Hidden |
| OpenCode | `opencode` | `gdd-route-opencode` | Hidden |
| Omo | `omo` | `gdd-route-omo` | Hidden |
| GitHub Copilot | `copilot` | `gdd-route-copilot` | Hidden |

This table describes the separate-route design. Use the
[generated install guide](../index.md#install) to see which packages are
available in the checked-out revision. Hidden routes are not advertised for
model routing; hiding does not grant authorization. See the
[transport contract](../skills/gdd/references/transport.md) for configuration,
answer retrieval, completion rules, and platform evidence.

## Native Paseo transport

Explicitly point `GDD_LAUNCHER` at the bundled `paseo-run.py` to run stages as
native Paseo agents. This option requires a reachable daemon. Reachability
never changes the selected launcher automatically. The transport contract
documents native and headless platform evidence separately.

## Optional Paseo GDD Observer

The [GDD Observer](../paseo-plugins/gdd-observer/README.md) is read-only and
neither launches runs nor changes the selected transport. It is not installed
by `npx skills`. The sidebar footer's **GDD runs** row opens the global
`runs` screen; the plugin also has a separate settings screen.

Read the plugin guide for installation, settings, observed artifacts, trust,
development checks, and removal. The
[integration guide](../paseo-plugins/gdd-observer/HOA-INTEGRATION.md) explains
the shared `GDD_RUN_ROOT` and route integration. Review the source before
installing: plugins execute trusted, unsandboxed code in the Paseo daemon
and client. Registration and runtime settings stay local.
