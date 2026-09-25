# Changelog

Notable changes to this repo. Skills carry per-skill `version=` metadata in
their `<!-- index: ... -->` comment; this file records the notable deltas.

## 2026-09-25 — safer skill execution and goal activation

- **define-goal v1.2.0:** keep independently finishable `/goal` payloads
  separately activatable on one-active-goal runtimes. The usage note sits
  outside copyable goals; broader sampling and readiness rules were rejected
  after they regressed independently meaningful outcomes in weak-model trials.
- **my-ado-cppr v1.1.0:** default to committing staged changes only. Explicit
  file selections use literal Git pathspecs and cannot consume unrelated
  staged changes; reject empty, conflicting, and non-boolean staging plans
  before writes. Real-Git regression cases cover amend and deletions.
- **git-worktree-workflow v1.1.0:** configured post-create hooks must succeed
  before `gitwt` returns a ready worktree or launches an agent. Failed setup
  preserves partial files for manual recovery; a private Git-admin marker
  prevents unknown checkouts from inheriting readiness. Managed creation and
  removal share a lock. Copy conflicts fail closed, and hashed PORT values
  are documented as potentially colliding rather than guaranteed unique.
- **ghc-search v1.0.1:** quote installed script paths so searches and offline
  checks work when an installation directory contains spaces.

## 2026-09-25 — portable skill review and authoring

- Added `hoa-skill-review` for read-only skill audits, change reviews, and
  evidence-backed judgments, with targeted evaluation before expanding to
  multi-model or multi-variant comparisons.
- Added `hoa-skill-work` for directly requested skill creation and evolution.
  It keeps the existing `hoa-introspect-distill` approval flow limited to
  candidate qualification from repeatable work; direct-creation routing in the
  introspection/retrieval skills and trigger fixtures follows that boundary.
- Added routing fixtures and bilingual catalog notes for both skills.
- Inspected the installed Claude Code v2.1.282 Bun executable and first-party
  plugin scripts to separate native eval/skill/goal machinery from plugin and
  session-authored methods; recorded the source boundaries in `reflections/`.
  Added behavior fixtures for harness errors, comparable baselines, and
  held-out activation checks without making large eval matrices the default.

## 2026-09-24 — library seeding, test consolidation, ref pruning

- **Library folders are live:** every library folder (`agents/`,
  `orchestration/`, `rules/`, `prompts/`, `workflows/`, `mcps/`) now holds
  one exemplar with a provenance note — most adapted from a `ref/` row
  (first steals: ECC's skill-scout, looper's typed verification gates);
  `rules/generated-means-generated.md` and `mcps/ghc-proxy.md` document this
  repo's own incidents and local service instead. Second retro:
  `reflections/2026-09-23-first-steals.md`.
- **generate_index.py covers library folders:** library artifacts (a
  `<name>.md` or `<name>/README.md` with an `<!-- index: ... -->` comment)
  are indexed beside skills; index regenerated (13 artifacts).
- **Test consolidation:** same-branch parameter rows merged (my-ado-cppr
  alias tests, generate_index axis tests; 22 → 21 and 12 → 10), one
  downstream-duplicate drift test removed, one redundant distill fixture
  dropped (ambiguous vs group approval hit the same branch); 2 new library
  tests added. Suites: generate-index 12, ghc-search 14, my-ado-cppr 21,
  gitwt 19.
- **New evals:** `skills/define-goal/evals/validate_fixtures.py` (offline
  schema check for the judge fixtures, in CI) and `evals/` trigger evals —
  10 routing cases validated offline against the real catalog.
- **ref/ pruned:** 5 dead submodules removed (40 → 35) after a 5+ month
  staleness + redundancy audit; andrej-karpathy-skills kept as a link-only
  row. All remaining submodules refreshed to upstream heads.
- **Intake:** issue templates (bug report / skill request) and README
  "Reflect cadence" + "Request a skill" sections; roadmap Phase 4.
- **Fixes:** ghc-search SKILL.md no longer hard-codes its test count (it had
  drifted to 11 of 14).

## 2026-09-23 — code-review fixes (round 2)

From the ce-code-review pass (validator-confirmed finding plus
adversarial-codex residual risks):

- **generate_index.py:** quoted metadata values (`areas="..."`) now parse
  equal to unquoted; a skill directory missing `SKILL.md` is a hard error
  (was silently skipped by the glob); catalog notes fall back to the first
  sentence of the SKILL.md frontmatter description — `NOTES` is now an
  optional bilingual override, so a new skill generates without editing the
  generator.
- **vendor_shared.py:** destination symlinks are rejected in both check and
  write modes (a symlink passed content comparison but is not a
  self-contained copy); up-to-date consumers are no longer rewritten.
- **CI:** the SKILL.md frontmatter check now requires non-empty `name:`
  and `description:` values, not just the key prefix; the index-generator
  test suite runs in CI.
- **ghc-search:** env overrides (`GHC_SEARCH_*`) are read per call instead
  of at import (fixes a latent reload trap); env-vs-flag precedence and
  env endpoint are now covered by tests (11 → 14 tests).
- **my-ado-cppr:** the `github_pr` + `pr` plan-conflict case is tested
  (21 → 22 tests).
- **New suite:** `scripts/test_generate_index.py` — 12 round-trip tests
  covering parse, validation, fallback notes, and `--check` drift.

## 2026-09-23 — hardening pass

- **CI:** `.github/workflows/ci.yml` added — runs every skill's offline
  test/eval suite, the index drift check, the shared-script drift check,
  and a SKILL.md frontmatter sanity pass on every push/PR.
- **Index generation:** `index.md` / `index.zh-CN.md` are now generated by
  `scripts/generate_index.py` from each skill's `<!-- index: ... -->`
  comment (single source of truth; includes per-skill `version=`).
  Manual catalog edits are over.
- **ghc-search v1.0.0:** de-personalized (machine-specific description
  removed); `GHC_SEARCH_ENDPOINT` / `GHC_SEARCH_MODEL_GPT` /
  `GHC_SEARCH_MODEL_X` env overrides for proxy endpoint and default models.
- **git-worktree-workflow v1.0.0:** SKILL.md slimmed — the `gitwt` naming
  rationale moved to `references/naming.md`, which also documents the
  Windows Git-Bash-vs-WSL `bash` trap.
- **my-ado-cppr v1.0.0:** SKILL.md slimmed 413 → 133 lines — full
  probe/plan/apply-result schemas moved to `references/schemas.md`;
  offline tests expanded 2 → 21 (plan validation, provider resolution,
  result finalization, headline precedence, porcelain parsing).
- **Shared scripts:** `safety.py` unified under `scripts/shared/` with
  `scripts/vendor_shared.py` to vendor it into each consuming skill
  (plus a CI drift check).
- **Reflections:** first post — `reflections/2026-09-23-skills-first-split.md`.
- **ref/:** all 40 reference submodules refreshed to their upstream
  default-branch heads.
