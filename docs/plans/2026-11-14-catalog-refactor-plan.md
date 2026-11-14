# Catalog refactor — measured, then revised under two independent audits

Date: 2026-11-14 · baseline: `main` at `cabf8c6` (VERSION 0.1.59) · this increment: 0.1.60

This is the plan of record for the catalog's own refactor. Version 1 was a measurement plus three
candidate refactors and seven open questions; it went to two independent, read-only audits (GPT-6.1-sol and
gemini-4-carbon, separate harnesses, neither shown the other's report, neither allowed to write). §2
records what they overturned and what they confirmed, and the rest of this document is the plan after
those corrections. The audit reports themselves are deliberately not committed: they quote local paths and
host state, and this repository publishes conclusions, not the machine they were reached on.

Numbers below were re-measured on the merged tree at `cabf8c6`, not copied from the audits.

## 1. What the catalog actually looks like

| indicator | measured |
|---|---|
| skills | 59 (plus `evals/` routing cases and the artifact contract registry) |
| SKILL.md body | 10,116 lines; median 143, p90 323, max 517 (`github-repo-management`) |
| over 120 lines | 38 / 59 |
| shape | 30 carry `references/`, 21 ship `scripts/`, 6 carry a test of their own |
| scripts with no test anywhere | **13** (derivation below) |
| `areas` | software-development 46, work-management 38, self-management 10 |
| `targets` | runtime-agnostic 55, `hermes` 3, `pi` 1 — all four are legal enum values |
| `kind` | entry 46, mechanism 11, controller 1, stage 1 — all four are enforced values |
| CI | 33 hand-written steps in `.github/workflows/ci.yml`, each naming its test path |
| contract registry | `external` 4, `terminal` 5, `shared` 0 |
| complete duplicate bodies | 0 |

Script coverage, exactly: of the 21 skills that ship `scripts/`, six have a test of their own and four
more are exercised by CI steps that live elsewhere (`hoa-introspect` and `hoa-introspect-distill` through
their `evals/` entry points, `m365-copilot-cdp` and `teams-cdp` through the shared CDP suites). That
leaves **13 skills that ship executable code with no test anywhere** — and 33 hand-written CI steps whose
coverage cannot be derived from the repository, which is how `test_worktree_scope.py` came to exist
without ever running in CI.

### 1.1 Two claims in v1 were wrong, and both audits said so independently

- **`kind` is not a dead field.** `scripts/check_contract_graph.py` enforces it (R1/R4/R5/R7/R8):
  `mechanism` may not appear in `evals/trigger-cases.json` as `must_pick`; `controller` produces only
  `chain-plan` and is capped at 120 lines; `stage` closes the
  `spec-convergence → writing-plans → subagent-driven-development` chain. 46 entries is a normal shape for
  a library of routable entries, not an unclassified remainder. v1's "give it meaning or delete it" was
  wrong about its premise: it has meaning and it is checked.
- **`hermes` and `pi` are not enum drift.** They are members of `TARGETS` in `scripts/generate_index.py`
  and validated per skill through `check_frontmatter.py`. Those four skills really are runtime-specific;
  renaming them to `runtime-agnostic` would be a false claim, and would break the generalization rubric
  that exists to prevent exactly that.

### 1.2 What v1 missed

- **Four stub skills** — `plan-to-issues` (14 body words), `arch-improvement-plan` and
  `design-an-interface` (20 each), `notes-to-prd` (46). `plan-to-issues` also points at a skill that does
  not exist in the catalog. Damage at the bottom end of the size range is as real as bloat at the top, and
  v1's line-count lens cannot see it.
- **Orphan references.** 12 reference files are never named by path from their own `SKILL.md`; ten belong
  to `gdd`, whose references are chained from other references, so the real orphan set is three
  (`github-repo-management/references/github-api-cheatsheet.md`,
  `grounded-citations/references/grounding-rationale.md`, `whisper/references/languages.md`).
- **Unresolvable local paths in `SKILL.md` bodies** — `omp-headless-orchestration` cites
  `references/transport.md`, `scripts/adapters/omp-run.py` and `scripts/gdd.py`;
  `subagent-driven-development` cites `references/stage-templates/implement.md`;
  `hoa-introspect-distill` cites `scripts/approval.py`. Nothing resolves these today.
- **A routing blind spot no static check can see.** `evals/trigger-cases.json` holds 27 cases and 17
  distinct `must_pick` artifacts, about a dozen of which are skills. Of the six skills v1 proposed to
  split, only `writing-plans` has a routing assertion at all, and `evals/run_trigger_evals.py` validates
  case structure offline and never re-runs the judge — so a `description` that halves the hit rate still
  ships green.
- **Host links are already loose.** All 59 host links resolve, but 31 sit in a category directory that no
  longer matches the skill's first `area`. Name-stable refactors do not care; renames do.

## 2. Audit verdict

Both audits returned the same headline: **the direction is right, the scope as written is not shippable
yet.** Both refused the two factual claims in §1.1, both refused folding `A′`/`A″` into the discoverer PR,
and both insisted the discoverer start as a precise contract rather than four globs. Where they differed,
this plan takes the stricter reading.

| # | correction both audits demanded | consequence here |
|---|---|---|
| 1 | A stays one mechanical PR: the discoverer plus its CI wiring, nothing else | `A′`, `A″` become separate items (§8, §9) |
| 2 | Discovery is a whitelist of named entry-point patterns, never `*` | §4 |
| 3 | Full accounting: every discovered suite reaches a terminal state; old CI steps are deleted only after a new/old coverage reconciliation | §4 |
| 4 | C splits in two: cheap static checks first, script tests later by dependency tier | §5, §7 |
| 5 | No `untested: <reason>` escape hatch — it becomes a permanent exemption | §5 |
| 6 | B's criterion is progressive disclosure of an oversized entry, not a rewrite into `controller` | §6 |

Each audit's "if you change one thing" landed on the same instruction: make A's merge standard "prove no
old coverage was lost and nothing was silently skipped" rather than "CI down to ~10 steps", and tighten
A's discovery contract while stripping `A′`/`A″` out of it.

## 3. Order

**A (mechanical hygiene) → C1 (light static checks) → B (oversized entries, one skill per PR) → C2 (script
tests by dependency tier).**

A first, because a new check that still has to be hand-wired into `ci.yml` repeats the failure it is meant
to fix. C1 next, because B's splits need a machine verdict rather than a reviewer's. C2 last, because it
is bounded by dependency isolation rather than by will. `A′` and `A″` are independent of all four.

## 4. A — the test discoverer (`scripts/run_all_tests.py`)

The four globs v1 proposed (`scripts/test_*.py`, `skills/*/scripts/tests/*`, `skills/*/evals/*`,
`evals/*`) fail in four ways at once, all measured on the current tree:

| failure | evidence |
|---|---|
| runs an online judge as a CI test | `evals/judge_trigger_evals.py` needs an endpoint and exits 2 without one |
| treats fixtures as tests | `evals/baseline.json`, `evals/trigger-cases.json`, `skills/*/evals/*.json` |
| drops coverage CI has today | `skills/ghc-search/scripts/test_ghc_search.py` lives under `scripts/`, not `scripts/tests/` |
| runs one suite twice | `run-gdd-selftest.sh` already invokes `test-dispatch-guards.py` |

The contract instead:

1. **Discovery is by name, on files, never a bare `*`.** `scripts/test_*.py`; `skills/*/scripts/test_*.py`
   and `test-*.py`; `skills/*/scripts/tests/test*.py`, `*.sh`, `run-*-selftest.sh`;
   `skills/*/evals/run*.py` and `validate_*.py`; `evals/run_*.py`, `evals/validate_*.py`,
   `evals/test_*.py`. Online judges are excluded by naming convention: `judge_*.py` never runs in the
   offline set.
2. **Pruned directories:** `node_modules`, `__pycache__`, `.git`, `.tmp-artifacts`, `ref/`, `fixtures/`,
   `scripts/shared/`, and the two CDP script trees whose suites stay in their own CI step.
3. **Runtime is pinned, not inherited.** Python suites run as `[sys.executable, "-B", path]` with
   `cwd=REPO_ROOT` and `PYTHONPATH=REPO_ROOT` — a bare `python3` from `PATH` is not guaranteed to carry
   PyYAML; shell suites run under `bash`.
4. **Isolation per suite:** its own process, `start_new_session=True`, its own `TMPDIR`, its own
   `HOME`/XDG so no suite can read or write operator configuration; default timeout 120 s, then `killpg` —
   killing the parent of a `setsid`/`tmux` suite is not enough.
5. **Every suite reaches a terminal state:** `PASS`, `FAIL`, `ERROR`, `TIMEOUT`, `SKIP`. A missing
   interpreter, an import error or an unknown entry point is an error, never a silent skip. The run
   settles every suite and then exits non-zero once.
6. **Anti-false-green:** assert a floor on the number of discovered suites, reject a suite reporting
   `Ran 0 tests`, and report planned versus settled counts.
7. **Serial by default**; concurrency is opt-in after suites are proven isolated.
8. **Exit criterion for the PR:** a new/old coverage reconciliation (every step currently in `ci.yml` is
   either discovered or explicitly declared with its command, `cwd`, runtime and `covered_by`), plus five
   injected failures — syntax error, failing assertion, hang, missing runtime, empty suite set — each
   observed red while the remaining suites still settle. Only then are the hand-written steps deleted.

## 5. C1 — the static checks worth having

Build:

- **Local path existence.** Every backticked local `references/`, `scripts/`, `templates/`, `assets/` path
  in a `SKILL.md` must resolve. This catches today's five dead paths and is the cheapest possible defense
  for B. Placeholder forms (`references/<channel>.md`, `references/phases/*.md`) and external prefixes
  (`$HERMES_HOME/…`) are filtered out, not waved through.
- **Orphan references.** Every `references/**/*.md` must be reachable from `SKILL.md` directly or from an
  already-reachable reference. Three real orphans today.
- **One source for the enums.** `TARGETS` and `KINDS` move into `scripts/skill_metadata.py` so the index
  generator, the frontmatter checker and any scanner read one tuple instead of three copies.
- **Optional `kind`.** Absent means `entry` (one rule in R7), which retires 46 boilerplate lines without
  changing semantics.

Do not build:

- **`untested: <reason>` in frontmatter.** It converts a gap into a permanent, legal exemption, and the
  skills that would use it are exactly the ones whose scripts cannot run in CI (`microsoft-office`'s 20
  scripts against `python-docx`/`openpyxl`/`python-pptx`, `ocr-and-documents` against `pymupdf` and a
  ~5 GB `marker` stack).
- **A second copy of the contract-graph checks.** They exist and are tested; the fix is the shared enum
  source, not another checker.
- **A bilingual index check.** Already generated from one source and already drift-checked.

## 6. B — oversized entries, by measurement

Candidate rule, reproducible and mechanical:

> `SKILL.md` body > 200 lines **and** (`##` sections ≥ 8 **or** body > 2,500 words).

It selects **15** skills — all six v1 named, plus `contract-bound-deliverables` (3,260 words),
`agent-operating-contract-evolution` (4,282), `kanban-workflows`, `grounded-citations`,
`skill-porting-and-publishing`, `ai-coding-agent-delegation`, `design-md`, `skill-library-curation`, and
`hermes-models` (279 lines but 3,067 words).

- **Split means progressive disclosure.** The thin entry keeps the routing contract, trigger conditions
  and hard constraints; topic detail moves to `references/`, which the entry names by path together with
  the condition for reading each one. `kind` does not change.
- **`controller` is not the target and 120 lines is not the threshold.** In this repository `controller`
  means a chain-plan producer capped at 120 lines; the six skills v1 named produce `plan` and
  `implementation`, and converting them would violate R5 or invent a fake `chain-plan`. A 120-line gate
  would also push the 24 compact, already-split skills (121–200 lines, e.g. `html-artifact` 189,
  `writing` 160) into moving routing boundaries out of their entries — the opposite of the goal.
- **One skill per PR**, each carrying the evidence in §10.
- **The other end:** add a floor check — a body under 50 words is a stub to be filled or retired. Four
  today.
- Size generates the **queue**, not a correctness standard: the same rule says nothing about overlap
  between short skills, which is decided on evidence of overlap.

## 7. C2 — script tests by dependency tier

- **L0, every script-shipping skill, zero exemptions:** `py_compile` for Python, `bash -n` for shell, and
  `--help` exiting 0 for every CLI entry point. Cheap, offline, and it separates "shipped code" from "code
  nobody has executed since it was written".
- **L1, stdlib-only scripts:** behaviour fixtures with offline inputs and asserted outputs — the text
  checks in `writing`, `grounded-citations/scripts/sources.py`,
  `official-document-verification/scripts/scan_bill_text.py`, `agent-operating-contract-evolution`.
- Heavy-dependency skills (`microsoft-office`, `ocr-and-documents`) stay at L0 unless a separate CI step
  with its own isolation is accepted; they must not drag their dependencies into
  `scripts/requirements.txt`.

## 8. A′ — the oversized code files, judged rather than queued

v1 listed nine files over 600 lines as split candidates. Length alone does not identify a boundary; both
audits agreed, so the list survives only as a review queue:

| file | reading |
|---|---|
| `skills/gdd/scripts/adapters/omp-run.sh` | real extraction: it embeds an independent Python finalizer with its own interface |
| `skills/gdd/scripts/pr-merge-check.py` | real extraction: the embedded self-test, keeping the `--selftest` surface intact |
| `grounded-citations/scripts/sources.py` | ledger, citation matching and draft validation are separable — after behaviour tests exist |
| `m365-copilot-cdp/scripts/copilot.ts` | the Chat and Code paths diverge independently |
| `run-gdd-selftest.sh`, `test_version.py`, `delivery-state.py`, `gdd.py`, `teams.ts` | not splits: linear suite state, one test class, one CLI, one command family |

Queue rule: single file > 400 lines **and** ≥ 2 responsibilities that can be named, tested and changed
independently. "More than one function group" is not a responsibility.

## 9. A″ — the reference area and the four catalog documents

- `ref/` is 38 submodules tracked by pointer; nothing under `skills/` reads a local `ref/` path, but the
  library's own research notes link into it. Decide per repository on "do we still want this snapshot
  locally", then keep it or reduce it to a link; do not delete by theme. There is no case for forcing one
  upstream per topic — same author is not the same function, and the same theme is not the same modes,
  languages and false-positive baselines.
- The four catalog documents converge to: an English `README.md` carrying positioning, install and
  contribution entry points only (no hand-maintained catalog table, no CI step table — both drift), both
  generated indexes, and a Chinese `README.zh-CN.md` that is a short pointer to them. That also retires
  the same-commit Chinese mirror obligation for content that is generated anyway.

## 10. Evidence each step must carry before merge

- **A:** new/old coverage reconciliation plus the five injected failures of §4.
- **C1:** the checker's own tests, plus today's findings as fixtures (five dead paths, three orphans).
- **C2:** fixture tests that fail when the guard is removed.
- **B, per skill:** (1) a rule-migration table — where each hard prohibition, gate and artifact lives after
  the split, and what condition makes the entry load it; (2) a before/after behaviour comparison on the
  same input including a refusal path, with real transcripts; (3) real-install verification — the skill
  still resolves its own files as a self-contained package, and removing a migrated rule makes the
  counter-example fail; (4) a re-recorded routing baseline for skills with any routing coverage, and new
  `must_pick` cases with same-family distractors for those without.
- **Host side:** no action for content-only or split-only changes — the 59 links are name-stable and the
  next hygiene run re-materializes drifted copies. A rename or a merge needs all four of: update
  `allowed_skills` in the affected profiles, remove the dangling old link, re-run the host installer,
  re-materialize and verify the affected profiles.

## 11. Constraints (unchanged)

One patch bump plus a `CHANGELOG.md` entry per PR; `check_frontmatter`, `check_contract_graph`,
`generate_index.py --check` and `version.py check` green; no host paths, host names, channel ids or
personal data in the repository; every script cross-platform (Python via `uv`/`uvx` with PEP 723 inline
dependencies, TypeScript via `bun`, F# via `dotnet fsi`, no shell or PowerShell carrying logic); and every
change lands through a branch, a PR and a squash merge so `main` stays linear.
