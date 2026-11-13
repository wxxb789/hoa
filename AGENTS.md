# hoa — Project Agent Instructions

## Portability — configuration, not hard-coding

Every skill here runs on someone else's machine. A change born in one working environment is portable
only when each environment-specific value can be supplied from outside it.

- **No literals for environment.** No home paths, personal or assistant names, repository/bot/channel
  ids, model ids, hostnames or host sizing in a skill's behaviour. Resolution order: CLI flag → env
  var → config file → documented default.
- **Skills may read the operator's configuration, and should.** That is the preferred mechanism, not a
  workaround. Look for `$XDG_CONFIG_HOME/<skill>/config.yaml`, falling back to
  `~/.config/<skill>/config.yaml`, and let an env var override a single key (the gdd
  scripts do exactly this with `GDD_STATE_FILE`, `GDD_TASK_ROOT`, `GDD_RUN_ROOT`, `GDD_LAUNCHER`,
  `GDD_TEMPLATES`, `GDD_GOAL_GLOB`). Document every key and its default inside the skill.
- **Prefer the capability to the tool.** When a step needs a launcher, a review bot or a scheduler,
  state the contract it must satisfy and ship one reference adapter; another install substitutes its
  own.
- **Per-project or per-install detail goes in a profile or overlay file**, never in the protocol body.
- **Merging a self-evolved skill is a review gate, not a copy.** Take the method, then walk every new
  literal path, id and model: demote each to configuration, keep the defaults honest, and re-run the
  skill's own acceptance commands before opening the PR. A skill that only works here is not ready.

## Composition contracts

Skills declare their role and artifacts in `metadata` as comma-separated strings:

- `kind`: one of four roles. `controller` routes a chain and produces only `chain-plan`; `stage` is
  one phase of a chain and is invoked by its controller; `mechanism` is invoked only by another skill
  and is never a routing target; `entry` is directly routable from a user request. Every skill
  declares a kind, and CI rejects a skill that does not.
- `consumes` / `produces`: artifact names; declaring either requires `kind`.

A mechanism is never a routing target, so it must not appear in `must_pick` in
`evals/trigger-cases.json` (it may be a distractor). A controller routes and produces only
`chain-plan`. Every consumed artifact must be produced by exactly one skill, or registered under
`external:`/`shared:` in `scripts/contract_graph_registry.yaml`; duplicate producers are errors
unless listed under `shared:`. Every produced artifact must be consumed by some skill or listed under
`terminal:` in that registry with a one-line reason (`R9`); `external:` artifacts are exempt. CI
enforces the graph with `python scripts/check_contract_graph.py`.

## Generated Artifacts Output

All HTML artifacts and their related assets **MUST** be written to `./.tmp-artifacts/`.

- **Scope**: rendered reports, dashboards, visualizations, session/insight
  reports, screenshots, and any backing assets they depend on (CSS, JS,
  images, fonts, and JSON/data files).
- **Location**: always under `./.tmp-artifacts/` at the repo root. Create it
  with `mkdir -p .tmp-artifacts` if it does not exist. Never scatter these
  files in the repo root or in source directories.
- **Bundle per artifact**: every artifact gets its **own subfolder** named
  after it, e.g. `./.tmp-artifacts/<artifact-name>/`. The main file and **all**
  of its related assets (data JSON, CSS, JS, images, fonts) live together in
  that one subfolder so each bundle is self-contained and portable. Never drop
  loose files directly in `./.tmp-artifacts/` — its root holds only bundle
  subfolders.
- **Version control**: `./.tmp-artifacts/` is git-ignored. Never commit its
  contents and never force-add (`git add -f`) files from it.

Example layout:

```
.tmp-artifacts/
  session-report-20260626/      # one bundle
    session-report-20260626.html
    _session-report.json
    _session_index.json
  insights-report-zh-cn/        # another bundle
    insights-report-zh-cn.md
    _insights_data.json
```
