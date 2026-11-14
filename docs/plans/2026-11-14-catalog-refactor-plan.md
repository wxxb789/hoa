# Catalog refactor — measured, reviewed, and corrected

Date: 2026-11-14 · measurement baseline: `cabf8c6` (VERSION 0.1.59) · this increment: 0.1.61

This is the plan of record, not implementation of its future phases. Version 1 received two separately
produced read-only audit reports; version 2 received simplify and code-review reports.
[The sanitized evidence and disposition record](../evidence/2026-11-14-catalog-refactor.md) attributes
conclusions and records input/report fingerprints. Report contents are operator-held; reading them
does not establish execution isolation or current host state. Raw reports remain outside this repository
because they contain installation details.

All measurements below are pinned to `cabf8c6`, not claims about an evolving latest tree. Reproduce size
and queue measurements with `python docs/evidence/catalog_measurement.py --ref cabf8c6` from the repo
root, with `scripts/requirements.txt` installed. Strip YAML frontmatter and exterior blank lines; use
`splitlines()` for body lines and whitespace `split()` for words, including code. Count ATX H2 outside
matching backtick/tilde fences; p90 uses nearest rank. The evidence record specifies other static
inventory methods. No size measurement proves behavior coverage.

## 1. What the catalog actually looks like

| indicator | measured at the pinned baseline |
|---|---|
| skills | 59 (plus routing cases and the artifact contract registry) |
| SKILL.md body | 9,164 lines; median 131, p90 305, max 503 (`github-repo-management`) |
| complete SKILL.md files | 10,124 lines; median 143, p90 323, max 516 |
| over 120 body lines | 35 / 59 |
| shape | 30 carry `references/`, 21 ship `scripts/`, 6 carry a test of their own |
| script skills without an identified own test/eval entrypoint | 13 (test presence, not branch coverage) |
| `areas` | software-development 46, work-management 38, self-management 10 |
| `targets` | runtime-agnostic 55, `hermes` 3, `pi` 1: three used values among eight legal values |
| `kind` | entry 46, mechanism 11, controller 1, stage 1; explicit declaration required |
| CI test job | 33 run steps plus three setup actions; reconcile commands and provisioning separately |
| contract registry | `external` 4, `terminal` 4, `shared` 0 |
| complete duplicate trimmed bodies | 0 |

The six script skills with own tests are `delegated-work-acceptance`, `gdd`, `ghc-search`,
`hermes-models`, `m365-copilot-cdp`, and `teams-cdp`. Two additional script skills have offline eval
entrypoints: `hoa-introspect` and `hoa-introspect-distill`. CDP skills are already in the six, not
additional coverage: `21 - (6 + 2) = 13`. Presence does not prove a test runs in CI or covers every
shipped script. Both `test_worktree_scope.py` and `test_paseo_run_python.py` exist but are not wired into
baseline CI; the Paseo plugin's Vitest package is also absent from the package test loop.

### 1.1 Two v1 premises were wrong

- `kind` is not dead. `scripts/check_contract_graph.py` enforces R1/R2/R4/R5/R7/R8:
  mechanisms cannot be `must_pick`; controllers produce only `chain-plan` and are capped at 120 lines;
  stages participate in `spec-convergence → writing-plans → subagent-driven-development`.
  Entries are routable skills, not an unclassified remainder. Keep explicit kinds and safeguards.
- `hermes` and `pi` are legal `TARGETS`, validated by the existing metadata parser/frontmatter checker.
  Four skills are runtime-specific, using two runtime-specific target values. Relabeling them
  runtime-agnostic would be false. There are eight legal values, not four.

### 1.2 What the earlier plan missed or misclassified

- Four stub bodies: `plan-to-issues` 16 words, `arch-improvement-plan` 22,
  `design-an-interface` 19, `notes-to-prd` 47. `plan-to-issues` names a missing catalog skill.
- Orphan references: among 107 Markdown references, 12 are not directly named by full path in their
  own `SKILL.md`, nine belonging to `gdd`. Directory-aware reachability leaves three orphans:
  `github-repo-management/references/github-api-cheatsheet.md`,
  `grounded-citations/references/grounding-rationale.md`, `whisper/references/languages.md`.
  Strict file-link-only reachability yields eight: five additional GDD templates are exposed by an
  explicit `references/stage-templates` directory declaration. C1 must pin and test that directory rule.
  `html-artifact/references/.gitignore` is outside the Markdown reference universe.
- Withdraw all five alleged dead-path findings. Transport/adapter/dispatcher references in
  `omp-headless-orchestration` and the implementation template in `subagent-driven-development`
  explicitly belong to `gdd` and exist there. `hoa-introspect-distill`'s
  `scripts/approval.py:resolve_approval` names an existing file and symbol. These become positive
  scoped-reference fixtures, not failures.
- Routing evidence is sparse: 27 cases, 17 distinct `must_pick` artifacts, 11 skill picks. Only
  `writing-plans` in the corrected queue has a positive routing assertion. Offline case validation and
  baseline consistency do not rerun the model judge or prove description hit rate.
- Host layout is installation-specific. No current link/category counts are claimed here. Use the
  installer contract and operator-scoped verification in §10, not a presumed hygiene service.

## 2. Audit conclusions and their limits

The original reports agree on preserving role/target semantics, keeping the discoverer mechanical and
separating unrelated cleanup. They emphasize different things: one prioritizes coverage reconciliation,
the other precise discovery and scope. The four-phase ordering below is a selected plan, not a verbatim
unanimous demand. Later reviews corrected false dead paths, size conventions, role-aware routing,
optional-kind and universal-help proposals.

| decision | location |
|---|---|
| A is one discoverer/CI PR, not code or README refactoring | §4; A′/A″ are separate |
| Named discovery needs covered-child accounting and explicit packages | §4 |
| Reduced CI step count is not acceptance | §4 item 8 is the sole full A acceptance definition |
| C separates light static checks from dependency-tier behavior tests | §5, §7 |
| No permanent `untested: <reason>` exemption | §5 |
| B means role-preserving progressive disclosure, not a controller conversion | §6 |

## 3. Order

A (mechanical hygiene) → C1 (light static checks) → B (oversized skills, one per PR) → C2 (script tests
by dependency tier). A prevents new checks requiring another manual CI step; C1 supplies static feedback
for B; C2 is bounded by dependency isolation. A′ and A″ proceed independently, with one exception:
A′'s `sources.py` extraction requires C2/L1 behavior fixtures first. Those fixtures may land independently
of unrelated heavy-dependency work.

## 4. A — the test discoverer (`scripts/run_all_tests.py`)

The original globs include online judges and fixture JSON, miss
`skills/ghc-search/scripts/test_ghc_search.py`, and independently schedule a dispatch-guard child
already called by `run-gdd-selftest.sh`. The replacement contract is:

1. Discover files by named entrypoint patterns: `scripts/test_*.py`;
   `skills/*/scripts/test_*.py` and `test-*.py`; `skills/*/scripts/tests/test*.py`, `test*.sh`,
   `run-*-selftest.sh`; `skills/*/evals/run*.py`, `validate_*.py`; `evals/run_*.py`,
   `evals/validate_*.py`, `evals/test_*.py`. Never collect bare `*.sh` or fixture data.
   `judge_*.py` belongs to online evaluation, not offline CI. Declare `test-dispatch-guards.py` as
   `covered_by: run-gdd-selftest.sh`: account for it without independent scheduling. Validate covered-child
   ownership and require its parent to execute/assert that child.
2. Prune `node_modules`, `__pycache__`, `.git`, `.tmp-artifacts`, `ref/`, `fixtures/`, and explicitly
   declared package trees. Existing Bun CDP packages keep their separate commands. Declare
   `paseo-plugins/gdd-run-observer` separately with cwd, package-manager/dependency provisioning,
   typecheck and Vitest commands; it is not a Bun-test glob. Include both previously unwired Python
   suites and all four plugin test sources in coverage reconciliation.
3. Pin runtime, cwd and invocation. Direct Python suites use `[sys.executable, "-B", path]`,
   `cwd=REPO_ROOT`, `PYTHONPATH=REPO_ROOT`; preserve declared `python -m unittest ...` invocations where
   direct execution is not equivalent. Use the interpreter containing repository dependencies, not
   arbitrary PATH `python3`. Existing shell reference suites use bash. Gates, conditional gates,
   packages and provisioning are explicit declarations, not misclassified test files.
4. Isolate each suite: own process, `start_new_session=True`, task-local scratch `TMPDIR`, `HOME` and
   XDG roots; no operator configuration reads/writes. Default timeout 120 seconds, then terminate/reap
   its process group. Suites creating separate `setsid` groups or tmux sessions declare and test teardown
   for those detached resources; parent-group `killpg` alone is insufficient.
5. Settle every logical suite as PASS, FAIL, ERROR, TIMEOUT or SKIP, then exit nonzero for any failed,
   errored or timed-out required suite. Missing runtime, import failure or unknown entrypoint is ERROR.
   Whole-suite SKIP requires an explicit permitted optional-capability reason and result record; zero
   executed checks in a required suite cannot be PASS or permitted whole-suite SKIP. PASS with optional
   subcase skips is distinct: record executed/passed/failed/skipped counts (the setsid suite runs other
   cases without tmux). Legacy exit-0 prose is not an implicit SKIP protocol.
6. Prevent false green: pin a reviewed discovery floor; compare planned/settled unique logical suites,
   including covered children. Tested adapters for existing custom assertion formats require positive
   executed-check counts; do not demand unittest text from them. Declared unittest suites require
   positive collection and reject `Ran 0 tests`. Empty custom suites also fail. Test adapters against
   real baseline formats and zero-assertion outputs.
7. Serial by default; concurrency only after isolation/teardown is proven.
8. Sole full PR acceptance definition: reconcile every existing CI test-job command as discovered or
   explicitly declared, with command, cwd, runtime, conditions, provisioning and `covered_by` as relevant.
   Include existing coverage, both formerly unwired Python suites and the Paseo package without duplicate
   child execution. Inject syntax error, failing assertion, hang, missing runtime and empty discovery
   set: each goes red while remaining runnable suites settle; separately prove zero-test unittest/custom
   adapters go red. Only after runtime reconciliation and this fault evidence may old hand-written
   commands be deleted. The static snapshot is preparation, not completed A acceptance.

## 5. C1 — the static checks worth having

Build:

- Scoped local-path existence. Check explicitly declared skill-local, cross-skill and repository-relative
  Markdown targets/backticked asset declarations. Strip supported `:symbol`, `:line` and `#anchor`
  suffixes before checking files; validate symbol/anchor contracts when declared. Preserve explicit scope:
  GDD-owned references are not assets of the referring skill. Require disambiguation of ambiguous prose,
  not blind resolution or silent acceptance. Classify placeholders/globs, external tools, output paths
  and illustrative excluded directories separately, not as required shipped assets. Missing declared
  real local targets still fail. Fixtures cover all five corrected positive paths, root/cross-skill/
  symbol/anchor cases, placeholders/examples and injected genuinely missing targets.
- Directory-aware reference reachability: every `references/**/*.md` is reachable from `SKILL.md` or an
  already-reachable reference. An explicit existing directory declaration exposes its Markdown children;
  a placeholder wildcard alone does not. Test this policy, three actual orphan fixtures, graph cycles and
  detached references. Direct absence is not synonymous with orphanhood.
- Reuse enum definitions/parsers. `TARGETS` exists once in `generate_index.py`, `KINDS` once in
  `check_contract_graph.py`; `check_frontmatter.py` delegates parsing. No three-copy consolidation is
  needed. A new scanner must not introduce another definition.
- Keep explicit `kind` and R2/R7. Optional-kind/default-entry is withdrawn, not semantics-preserving
  boilerplate cleanup; it can hide omitted mechanism/stage roles and contradict AGENTS.md.

Do not build permanent `untested: <reason>` frontmatter exemptions, a second contract-graph checker, or
a bilingual index checker already supplied by generation/drift checks. Office/OCR isolation is a C2
concern, not a reason to legalize missing tests.

## 6. B — oversized skills, by measurement

Queue rule: body >200 lines and (fence-aware ATX H2 ≥8 or body >2,500 whitespace words). The pinned
snapshot selects 13 skills, not 15:

| skill | kind | body lines | body words | H2 |
|---|---|---:|---:|---:|
| agent-operating-contract-evolution | entry | 254 | 4445 | 12 |
| ai-coding-agent-delegation | entry | 222 | 1655 | 10 |
| contract-bound-deliverables | entry | 290 | 3362 | 10 |
| design-md | entry | 207 | 1147 | 8 |
| github-repo-management | mechanism | 503 | 1596 | 12 |
| grounded-citations | entry | 245 | 1914 | 9 |
| hermes-models | entry | 261 | 3019 | 5 |
| kanban-workflows | entry | 254 | 2117 | 12 |
| skill-porting-and-publishing | entry | 222 | 2588 | 13 |
| subagent-driven-development | stage | 428 | 2332 | 13 |
| systematic-debugging | entry | 411 | 2304 | 14 |
| whisper | mechanism | 305 | 934 | 14 |
| writing-plans | entry | 326 | 1272 | 10 |

`skill-library-curation` (186 lines) and `github-code-review` (468 lines, 1,806 words, six H2 outside
fences) are excluded. The rule does not select every v1 name. Discretionary overlap/boundary review is
separate and needs evidence, not altered measurements to force a preferred queue.

- Progressive disclosure retains routing/caller contract, triggers and hard constraints in `SKILL.md`;
  topic detail moves to named references with explicit load conditions. Kind never changes.
- Controllers are not a target role or generic 120-line limit. Of the v1 six, three are mechanisms,
  one a stage, two entries; only `writing-plans` produces `plan` and the stage produces `implementation`.
  Converting them invents false `chain-plan` contracts. There are 21 compact bodies in 121–200 lines
  (`html-artifact` 172, `writing` 143); size alone does not justify moving routing boundaries.
- One skill per PR with §10 evidence. Bodies below 50 words are stubs to fill or retire: four at baseline.
- Size generates a queue, not a correctness standard; short-skill overlap needs overlap evidence.

## 7. C2 — script tests by dependency tier

- L0 static, every script-shipping skill, no permanent exemptions: Python syntax compilation and
  `bash -n`, writing compilation cache only to an explicit artifact/scratch bundle.
- L0 CLI help is a separate explicit entrypoint contract. First inventory/remediate CLIs so help is
  bounded, dependency-free and side-effect-free; then test declared help paths offline. Never blindly
  run every file with `--help`: helper modules are not CLIs, Office has top-level heavy imports,
  `events-writer.py` treats its argument as a directory, `fetch-examples.sh` performs network writes,
  `watch-pr-checks.py` has no help parser. Track unsafe/missing help as remediation work, not a permanent
  exemption or falsely completed CLI-help tier.
- L1 stdlib-only behavior fixtures use offline inputs and asserted outputs: `writing` text guards,
  `grounded-citations/scripts/sources.py`, `official-document-verification/scripts/scan_bill_text.py`,
  `agent-operating-contract-evolution`.
- Heavy Office/OCR behavior dependencies belong to a separately accepted isolated CI step, never root
  `scripts/requirements.txt`. Such skills still receive universal syntax checks; repair CLI-help paths
  before claiming help success. Help alone is not behavior coverage.

## 8. A′ — oversized code, judged rather than automatically split

The v1 nine-file list was stale. The pinned snapshot has 12 tracked code files over 600 `splitlines()`
lines, excluding `ref/`; the evidence record enumerates them. `teams.ts` has 591 and is not in that set.

| file or family | boundary decision |
|---|---|
| `skills/gdd/scripts/adapters/omp-run.sh` | independent embedded Python finalizer is a candidate |
| `skills/gdd/scripts/pr-merge-check.py` | embedded tests may move, preserving `--selftest` |
| `skills/grounded-citations/scripts/sources.py` | ledger/matching/validation only after C2/L1 tests |
| `skills/m365-copilot-cdp/scripts/copilot.ts` | independent Chat/Code divergence needs evidence |
| `omp-run.py`, `test_omp_run_python.py`, `runs-browser.tsx`, `test_paseo_run_python.py` | previously omitted; inspect responsibilities, do not force length-based splits |
| `run-gdd-selftest.sh`, `test_version.py`, `delivery-state.py`, `gdd.py` | no split established: linear suite state, one test class, one CLI or command family |

Queue rule: >400 lines and at least two responsibilities independently named, tested and changed.
Multiple function groups alone are not evidence of responsibilities. This queue is separate from A.

## 9. A″ — the reference area and catalog documents

- `ref/` has 38 tracked gitlink pointers; README's 35 count is stale. Decide per upstream whether a local
  snapshot is useful, then retain or link it. Do not delete by theme or force one upstream per topic:
  shared authorship/theme does not mean identical function, language, modes or false-positive baselines.
- Converge four catalog documents to English README positioning/install/contribution entrypoints, two
  generated indexes and a short Chinese pointer README. Remove hand-maintained catalog/CI tables.
  Changing the manual same-commit Chinese README mirror policy requires changing its current prose;
  absence of a CI mirror checker does not mean absence of policy. Retain same-commit source/index
  regeneration and both generated-index drift checks under `rules/generated-means-generated.md`.

## 10. Evidence each future step must carry before merge

- A: satisfy §4 item 8, the normative reconciliation/fault-injection acceptance definition.
- C1: checker tests, corrected scoped-path positives, genuinely missing-path negatives, directory graph
  fixtures and three orphan cases of §5. Do not freeze withdrawn five-path false positives.
- C2: behavior fixtures fail when the guard is removed; prove declared CLI help is safe and bounded.
- B, per skill: (1) rule-migration table locating every prohibition/gate/artifact and reference load
  condition; (2) same-input before/after behavior comparison including refusal, with real transcripts;
  (3) real-install self-contained file resolution and a counterexample failing when the migrated rule
  is removed; (4) rerun relevant recorded routing baselines and add same-family positive/distractor cases
  for directly routable entries lacking coverage. Mechanisms never enter `must_pick` (R4): test caller/
  invocation behavior and permissible distractors. Stage evidence tests chain/caller integration, not
  invented direct user routing. Offline validation is not a live model-judge result.
- Host/install: name-stable symlink content/split changes need no relinking if all files remain included;
  copies require explicit operator update. `install_host_skills.py --root <configured-root> --check`
  inspects parity; differing real directories are refused, not automatically rematerialized.
  Rename/retirement migrations update configured callers/allowlists, old links and install consumers,
  then run the installation adapter and verify affected consumers. No private profile field, scheduled
  hygiene service or current host-count assumption is part of this repository contract.

## 11. Admission constraints and retained CI scope

Each PR carries one patch bump and CHANGELOG; frontmatter, contract graph, generated-index and version
checks stay green. Preserve every artifact, prohibition and evidence requirement through refactors.
No host paths/names, channel identifiers or personal installation data in repository behavior/evidence.
New or substantially changed skill execution scripts target cross-platform execution with externally
configurable values: Python via uv/uvx and PEP 723 dependencies where needed, TypeScript via bun,
F# via dotnet fsi; do not add business logic in shell/PowerShell. This is admission, not a false claim
that all legacy scripts already conform. A retains current Ubuntu/POSIX CI orchestration/reference
suites; it does not also migrate launchers or shell tests. Every change lands by branch → PR → squash
merge, never a direct main push or published-history rewrite.
