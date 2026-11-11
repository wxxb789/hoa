# Changelog

Notable changes to this repo. `VERSION` is authoritative for all custom skills;
their YAML `metadata.version` fields mirror it. Earlier entries retain historical per-skill versions.

## 2026-11-11 — the eval judge runs on a configuration

- **`evals/judge_trigger_evals.py`** no longer hard-codes a judge model or reaches another skill's
  private gateway client. Endpoint, model, effort and the optional credential resolve through
  `scripts/skill_config.py`: CLI flag → environment variable → `$XDG_CONFIG_HOME/evals/config.yaml`
  (fallback `~/.config/evals/config.yaml`) → documented default. The wire protocol is a plain
  OpenAI-compatible `POST <base_url>/chat/completions`; effort is sent as `reasoning_effort`.
  With no endpoint/model configured the script exits 2, prints `base_url`, `model`, `effort` and
  the config-file path, and never guesses. A malformed config exits 2 naming `path:line`.
- **Baseline record.** `--record` writes `evals/baseline.json` (`case_count`, `model`, `effort`,
  `passed`, `total`, `judge_endpoint_host`, `generated_at`, `per_case`) atomically, only for the
  full case set; an existing record is replaced only with `--force`. Before writing, the proposed
  record is validated with the offline gate's own rules: a run whose picks include transport errors
  or non-catalog answers cannot be represented in the accepted schema, so nothing is written, the
  existing baseline is untouched, and the script exits 2 naming the offending cases. A
  wrong-but-catalog pick is recorded as the failure it is. `evals/run_trigger_evals.py`
  stays offline and now rejects a record whose ids are unknown, whose pick names no catalog
  artifact, whose recorded flag disagrees with `pick ∈ must_pick` recomputed against the current
  case set, whose `passed` is not the sum of its rows, or whose `case_count`/`total` do not
  describe the current suite. A missing record is reported and allowed until the first explicit
  `--record` run.
- Added **`evals/test_judge_trigger_evals.py`** (31 tests): precedence flag > env > config >
  default, the unconfigured exit-2 path, malformed config, an OpenAI-compatible
  chat-completions stub on `127.0.0.1`, non-catalog replies and per-case network failures, the
  baseline schema/overwrite rules, refusal to replace a baseline with an unrepresentable run, and
  every baseline inconsistency the CI gate rejects. CI runs it as a new gate; no test uses the
  network or a credential.
- **`README.md`** gains "How this repository is shaped": the four `kind` layers, the artifact
  surfaces with their counts, contract-graph rules R1–R9 with what each rejects, every CI gate
  command and what it protects, and how an eval case is graded — including the honest limit of a
  single-model judge. `README.zh-CN.md` mirrors the section.
- `VERSION` 0.1.32, mirrored into every `SKILL.md` by `python scripts/version.py bump`.

## 2026-11-11 — a mechanism, or no claim

- Added **`scripts/skill_config.py`**, the one implementation of the documented chain
  (flag → env var → `$XDG_CONFIG_HOME/<skill>/config.yaml`, fallback `~/.config` → default).
  It is stdlib only and parses a flat `key: value` subset; nested mappings, anchors/aliases,
  flow collections, block scalars and multi-document files are errors naming the path and line,
  never silent defaults. `resolve()` returns the value, `explain()` adds its provenance, and
  `python scripts/skill_config.py --skill <name> --key <KEY>` prints both.
- **goal-driven-delivery** resolves its six documented keys through that resolver:
  `GDD_STATE_FILE`, `GDD_TASK_ROOT`, `GDD_RUN_ROOT`, `GDD_LAUNCHER`, `GDD_TEMPLATES` and the
  previously unused `GDD_GOAL_GLOB`. Environment behaviour is unchanged (`GDD_STATE_FILE` still
  resolves to exactly its string), a config file now takes effect, a flag or env var still wins,
  and a malformed file exits 2 naming the path and line. The resolver is vendored beside `gdd.py`
  by `scripts/vendor_shared.py`, so an installed skill package stays self-contained.
- Contract graph **R9**: every artifact a skill produces is consumed by some skill or listed under
  `terminal:` in `scripts/contract_graph_registry.yaml` with a one-line reason; `external:`
  artifacts are exempt. The four dangling artifacts — `implementation`, `chain-plan`,
  `acceptance-verdict`, `scope-seal` — are terminal. The last two are not consumed by
  goal-driven-delivery as written: phase 5 runs `worktree-scope.py`, phase 6 runs
  `pr-merge-check.py`, and neither reads the acceptance skill's artifacts.
- The nine skills that restated the resolution chain now point at
  `skill-porting-and-publishing` § Configuration, which names the shared resolver once. The
  `AGENTS.md` composition contract now states the two-sided graph rule.

## 2026-11-11 — host install parity and catalog truth

- Added **`scripts/install_host_skills.py`**. `--root <host-skills-dir> --check` searches flat and
  one-level category layouts, names every skill that is absent, drifted, wrongly linked or present
  twice, and exits 1; `--link` creates only missing symlinks at the skill's first
  `metadata.areas` category (or `--category`), is idempotent, relinks a wrong link in place, and
  refuses to replace a real directory or a duplicated skill. The audit that motivated it found 8 of
  40 skills installed in no runtime.
- The generated catalog no longer has a second source of truth. The `NOTES` table is gone from
  `scripts/generate_index.py`; every one of its 49 notes moved unchanged into the artifact that
  owns it — `metadata.summary` / `metadata.summary_zh` for skills, `summary` / `summary_zh` in the
  `<!-- index: ... -->` comment for library artifacts. Missing summaries fall back to the first
  sentence of `description`, and a missing Chinese summary falls back to the English one. The
  `spec-convergence` row now describes the current one-root-per-round protocol.
- Added **`scripts/check_changelog.py --base <ref>`**: a changed `VERSION` without a changed
  `CHANGELOG.md` exits 1, and CI runs it in the pull-request job.
- Added **`scripts/check_frontmatter.py`**, which replaces the inline shell loop in CI and rejects a
  missing frontmatter, a name that does not match its directory, an empty description, or invalid
  catalog scalars.

## 2026-11-10 — cross-platform increments in goal-driven-delivery

- Added **goal-driven-delivery** [`references/cross-platform-increments.md`](skills/goal-driven-delivery/references/cross-platform-increments.md)
  and a pointer section in its controller. A Linux-only green is not evidence for a repo that ships on
  more than one OS: fixtures with `/tmp/...` literals, path substitution into serialised JSON, POSIX
  signals and mode bits each fail on Windows without failing locally, and a gate that reports a test
  name without its message costs one CI round trip per failure.

## 2026-11-06 — three skills retired to prompts

- Removed **my-ado-cppr**, **hoa-agent-retrieve**, and **git-worktree-workflow**. An A/B
  necessity eval at the DeepSeek Flash 4.1 bar found the bare model already did their
  tasks as well or better. The bundled engines also had defects: my-ado-cppr sent
  `--is-required` (az accepts `--required`) and then skipped work items and auto-complete,
  cut multi-line PR descriptions at the first newline, and wrongly called ADO labels
  unsupported; the hoa-agent-retrieve helper reported Codex, Gemini, and Claude assistant
  records as "available, 0 records".
- What a capable model cannot infer now lives in three one-shot prompts:
  `prompts/ado-commit-push-pr.md` (commit and PR conventions, defaults, az/gh pitfalls),
  `prompts/cross-agent-history-retrieval.md` (store catalog, coverage-manifest discipline,
  dedup, redaction, read-only access, the bundle hoa-introspect consumes), and
  `prompts/parallel-agent-worktrees.md` (layout, env/port isolation, fail-closed setup,
  safe cleanup, and what a helper script must guarantee).
- `gitwt` no longer ships here; its authoritative copy and regression tests live in the
  owner's chezmoi dotfiles. hoa-introspect and hoa-introspect-distill no longer route to a
  retrieval skill. CI, shared-script vendoring, and index notes drop the removed skills;
  trigger evals now route those requests to the new prompts.

## 2026-11-05 — define-goal verifiable goal files

- **define-goal:** numbered goal files (which replaced the v1.2.0 `/goal` payloads before
  0.1.0) now give each ready goal a standalone **Done when** section. It lists only what
  the receiving agent can show during its run, keeps user-supplied validators without added
  gates, and asks for a closing evidence report. Each file states its prerequisite, so one
  numbered series can mark goals that run earlier or in parallel. When the request assigns
  acceptance to someone else or to an event outside the feedback window, the agent goal ends
  at a verifiable handoff and the acceptance becomes an external-acceptance goal that is
  recorded, not run. Questions only the user can answer are asked together up front, and a
  goal stays provisional while one would change it. Users write their own goal commands;
  files carry no command text or size cap.
- The define-goal judge fixtures follow this contract: the board case uses a relative deadline
  and expects an agent goal plus external acceptance, and new cases cover revising a series
  already on disk (`setup` files, checked by `validate_fixtures.py`) and front-loaded questions.

## 0.1.0 — unified custom-skill versioning

- Start one release version for every custom skill under `skills/`; reference
  repositories and non-skill library artifacts retain their own versions. Custom
  skills use standard frontmatter `metadata.version`, without a duplicate HTML version.
- Move custom-skill catalog labels to `metadata.areas` / `metadata.targets`
  string fields. Reject legacy skill HTML index comments while preserving
  library metadata and ordinary report-template comments.
- Add version consistency/sync/bump tooling. Patch is the default increment;
  minor and major are explicit choices. Generated catalogs stay synchronized.
- Publish the initial `v0.1.0` and subsequent CI-approved main releases through
  serialized, stale-head-checked, atomic branch/tag updates. Local commands do
  not publish; existing repository protection and token permissions still apply.

## 2026-10-28 — desktop Teams and M365 Copilot automation

- Added **teams-cdp** for exact person/group discovery and authorized plain-text
  sending through the existing Teams profile. Native popouts, trusted multiline
  input, draft preservation, and fresh Sent receipts keep dispatch scoped.
- Group search waits for a changed conversation ID and the exact rendered title
  in one snapshot before returning a destination. An unchanged prior composer
  cannot certify the clicked result, even when its group name matches.
- Added **m365-copilot-cdp** for actual Chat and Code model selection, sending,
  and completed reply reading. It reuses one consent-approved connection,
  preserves profile settings with a durable rollback receipt, and rejects stale
  or cross-conversation completion evidence. Native dual-window parallelism is
  not established; the session runner remains sequential.

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
  before `gitwt` returns a ready worktree or launches an agent; each hook runs
  in an errexit-enabled Bash process so earlier command failures are not masked.
  Failed setup preserves partial files for manual recovery; `gitwt clean` also
  requires a valid ready private Git-admin marker, even with `--force`. Managed
  creation and removal share a lock. Copy conflicts fail closed, and hashed PORT
  values are documented as potentially colliding rather than guaranteed unique.
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
