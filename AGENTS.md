# hoa — Project Agent Instructions

## Portability — configuration, not hard-coding

Every skill in the curated `skills/` catalog runs on someone else's machine. A change born in one
working environment is portable only when each environment-specific value can be supplied from
outside it; candidates in `unfettered-skills/` are unconstrained until promoted.

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
- **Promotion is a review gate, not a copy.** Take the method, then walk every new literal path, id
  and model: demote each to configuration, keep the defaults honest, and re-run the skill's own
  acceptance commands before opening the PR. A skill that only works here is not ready.

## Privacy red line — the whole repository

This repository is public, so no personal data may sit anywhere in it — not only inside `skills/`:
host user names, absolute home paths, personal handles or account IDs, e-mail addresses, phone
numbers, channel or bot snowflakes, model IDs, private repository names, employer or work-project
identifiers. `unfettered-skills/` is unconstrained in shape, never in this.

- **Desensitize every arrival, new or edited.** A skill that enters or is updated here gets the same
  review as a port (`hoa-skill-port`): each environment-specific or personal value becomes
  configuration — CLI flag → environment variable → config file → documented default — with the
  default stated inside the skill. An edit to an existing skill is the easiest way for a literal to
  slip back in.
- **Fixtures and worked examples may use invented identities** — the reserved `example.*` domains,
  invented user names, documented-reserved paths. Finding those is not a leak: sharpen the scan,
  never rewrite the fixture.
- **Know what CI covers.** `scripts/check_unfettered.py` enforces this mechanically for
  `unfettered-skills/`, and `scripts/check_public_privacy.py` scans tracked public files (plus
  introduced blobs on PRs) for private keys, tokens, corporate feeds, home paths, emails, and
  private IPs. Fixed-signature scans cannot catch private model IDs or repo names, so still review
  those manually before opening a PR.

## Hermes-evolved skills

`skills/` is the curated catalog; every rule in this file binds what is promoted into it.
`unfettered-skills/` is its landing zone: Hermes, or a similar self-evolving system, checks
candidates in there automatically and unconstrained. It is a sibling of `skills/`, never an install
source or a manifest search path.

- **Only that writer lands candidates**, by automatic check-in. A candidate is
  `unfettered-skills/<name>/SKILL.md` (required) with any support files under
  `unfettered-skills/<name>/`; the landing root holds at most one `unfettered-skills/README.md`.
  Humans and regular agents only promote or delete them. A change set that adds or modifies
  anything there may touch no other path; a deletion there may ship beside an outside change,
  because promotion moves a skill out.
- **CI stays loose.** It checks sensitive content (keys, tokens, e-mail addresses, home paths,
  private-range IPs), the candidate shape (`SKILL.md` under its own directory; non-empty `name`
  equal to that directory, and `description`), and name collisions with `skills/` or
  `scripts/retired_skills.toml` — nothing else, no line caps, links, revisions, index or tests.
- **Promote through the port review.** One PR moves a candidate into `skills/<category>/<name>/`,
  normalized to the full bar: every rule in this file, the curated gates, and the raw copy gone. Raw renames
  and deletions never create retired entries; only previously curated names retire through the
  usual curated workflow. `hoa-skill-port` owns the procedure.
- **Never depend on the landing zone.** A curated skill must not require anything from
  `unfettered-skills/`; do not reference it from manifests, curated dependencies or install docs.
- **Discovery stays limited.** While standard locations yield valid skills, normal `npx skills`
  discovery does not list `unfettered-skills/`; an explicit path, recursive fallback,
  `--full-depth` or a specific-name retry can still reach it. Install commands point only at
  `skills/`.
- **Coupled skills carry `hermes-`** in both tiers: coupled means a dependency on Hermes runtime
  paths, config, tools, gateway or memory. Everything else stays portable and free of Hermes paths.
- **Never fork a Hermes built-in**, in either tier; they are tracked upstream. Propose the change
  upstream instead. `prompts/hermes-skill-naming.md` is the brief to hand Hermes.

## Engineering restraint

Scripts and tests follow one bar: default to deletion. Keep a gate, check, or abstraction only when
removing it risks real, irreversible harm, or after the same pain has hit three times.

- Record verified dead-code candidates and dated maintenance tasks in [TODO.md](TODO.md).
- Stdlib first; no single-caller wrapper layers, custom verification envelopes, or lockfile ceremony
  on zero-dependency code. Diagnostics name the exact offending key, path, or value.
- Tests target public contracts and CLI behaviour, not private functions. No tests that pin prose.
- No mutation harnesses or self-tests of test infrastructure unless they clear the irreversible-harm bar.
  The gdd merge-gate mutation harness clears it: a fail-open merge gate means an irreversible merge.
- New Python tests are `test_*.py` unittest or pytest files; `python -m pytest` collects them with no
  registration. A standalone check that is not a test file gets its own named step in `ci.yml`.

## Composition contracts

These contracts bind the curated catalog in `skills/`. The catalog is grouped into five
source-only categories — `engineering`, `productivity`, `research-writing`, `skill-authoring`,
`hermes` — so a package lives at `skills/<category>/<name>/`; installation stays flat at
`<skills-root>/<name>/` and a skill's name is its global identity across categories. A landing-zone
candidate is exempt until promotion.

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

**Visibility.** A hidden skill (not advertised to the model, still user-invocable) sets
`disable-model-invocation: true` and ships `agents/openai.yaml` with
`allow_implicit_invocation: false` for Codex; hiding is a per-skill choice, never implied by `kind`,
and never an authorization gate. A hidden skill must not appear in `must_pick`. A parent chains to
a sibling child in its own category only with `Read ../<child>/SKILL.md`, one level deep, and keeps
must-hold rules itself; installing it installs its whole `../` closure (installed packages are flat
siblings). CI enforces the flag/sidecar pair
(`check_frontmatter.py`), hidden-not-`must_pick` (`R10`), and sibling links
(`check_skill_links.py`). `npx skills` has no dependency concept, so closure is delivered by the
generated `npx skills add` commands in `index.md` and retired names by its generated
`npx skills remove` line (`generate_index.py --check` keeps both current); hoa-skill-set-audit
diagnoses an installed set on a machine. Binding detail:
[`rules/skill-composition.md`](rules/skill-composition.md) and
[`rules/cross-platform-skills.md`](rules/cross-platform-skills.md).

**Naming.** A name is a global kebab-case identity, equal to its directory in any category, and
categories are source-only: they never appear in an install name. A family uses
`<family>-<object>-<verb>` with one meaning per verb; `hoa-` is only for the skill-library family.
A rename goes through `scripts/retired_skills.toml` in the same change; a category move keeps the
name, creates no retired entry, and leaves the revision alone unless the package is also edited.
Binding detail:
[`rules/skill-naming.md`](rules/skill-naming.md).

## External references

`ref/` submodules set `update = none`, so clones and `npx skills add` skip them. Before
brainstorming, researching, or porting a pattern from an upstream in [ref/README.md](ref/README.md),
check out the ones in scope and read their source rather than recalling it:
`git submodule update --init --checkout --remote --depth 1 ref/<name>`. Leave pointer moves out of
commits; the daily [ref sync workflow](.github/workflows/ref-sync.yml) owns them.

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
