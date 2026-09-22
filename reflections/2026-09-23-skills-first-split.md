# Skills-first split: what survived contact with reality

> 2026-09-23 · retro on Phase 1 → Phase 2 of this repo

## Context

Three weeks ago this repo (then `ha`) had a `runtimes/` folder: per-runtime
copies of settings, prompts, and skills for Claude Code, Codex, OpenCode, pi,
Hermes, and Kimi Code. Phase 2 deleted it. The decision under test:

- **Skills** are the portable, deployable unit → live here, deploy via
  `npx skills`.
- **Runtime settings** (provider, models, plugins, `settings.json` /
  `config.toml` / `opencode.json`) are machine-specific → chezmoi.
- Everything else (agents, orchestration, prompts, rules, mcps, workflows,
  evals, reflections) is a **library**, not a deploy target.

## What worked

- **Deleting `runtimes/` was pure win.** No deploy tooling to write, no drift
  between six copies of the same prompt. `npx skills add wxxb789/hoa -g`
  genuinely lands a skill in every runtime it detects; `npx skills update`
  is the whole upgrade story. The Vercel CLI does what it promises.
- **The taxonomy held up.** The "classify by primary consumption interface"
  table in the README resolved every edge case we threw at it, including the
  sneaky ones: a multi-agent skill is still a `skill/` (external interface),
  a stop-hook is `settings` → chezmoi, not `rules/`.
- **Bilingual from day one was cheap** while the repo was small. Two READMEs,
  two indexes — the translation cost was maybe 10% per doc change.
- **Offline evals inside skills** (ghc-search: 11 tests, gitwt: 19,
  introspect family: full fixture suites) turned every refactor in this repo
  from "hope it works" into "run the suite".

## What hurt

- **Nine of ten folders are still `.gitkeep`.** The taxonomy is well-shaped
  but mostly empty; the real content converged on `skills/` faster than
  expected. Library types (agents, orchestration, prompts) are getting
  absorbed *into* skills rather than living beside them — the distill skill
  writes new skills, not new library files.
- **Submodules are the heaviest part of a "lightweight" repo.** 40 reference
  submodules under `ref/` inflate every clone that forgets
  `--recursive` isn't needed... and every `git submodule update --remote`
  session is a 2-minute fetch party. The value is the *map* (what to steal
  from each), not the checkouts. Keeping them was a convenience decision;
  revisit if clone complaints appear.
- **Bilingual is a tax that compounds.** Each new artifact doubles its doc
  surface. Today we added generated indexes (single source, machine-written
  in both languages) precisely because hand-maintaining two index tables
  already drifted.
- **Personal naming leaks into public artifacts.** `ghc-search`'s description
  said "Built-in WebSearch is denied on this machine" — true here, false on
  any other host. Skill descriptions are routing inputs; they must describe
  the capability, not the author's machine. Fixed today; the lesson is to
  read every public skill description as if you don't own the machine it
  runs on.

## Decisions reaffirmed

1. **Skills are the only deploy surface.** No second one until a real need
   appears.
2. **Generated over hand-synced.** `index.md` / `index.zh-CN.md` are now
   outputs of `scripts/generate_index.py`, not documents. Any file that must
   agree with another file should be generated from one source.
3. **Vendored copies need a vending machine.** `npx skills` packages are
   self-contained by design, so shared scripts (`safety.py`) must be copied
   into each skill. `scripts/vendor_shared.py` + a CI drift check makes
   copy-drift impossible instead of merely unlikely.

## On the horizon

- Write the second reflection only when there's a real outcome to report
  (first skill authored *by* the distill loop, first external consumer
  issue, or the first `ref/` pattern actually stolen into production).
- Consider promoting the `ref/` map (40 repos × what-to-steal) into a
  top-level doc if it keeps earning external traffic.
