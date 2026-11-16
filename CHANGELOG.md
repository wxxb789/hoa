# Changelog

Notable changes to this repo. `VERSION` is authoritative for all custom skills;
their YAML `metadata.version` fields mirror it. Earlier entries retain historical per-skill versions.

## [0.1.66] — 2026-11-16

### Added

- `scripts/run_all_tests.py` discovers, isolates and settles every repository test suite from the
  data in `scripts/test_manifest.toml`: named entry-point patterns only, a reviewed discovery floor
  that turns a shrunken discovery set into a plan error, per-suite process groups with task-local
  TMPDIR/HOME/XDG roots and a timeout, and PASS/FAIL/ERROR/TIMEOUT/SKIP terminal states with a JSON
  result record.
- Tested assertion adapters stop a required suite from passing with zero executed checks: declared
  unittest suites reject `Ran 0 tests`, a missing summary and an all-skipped summary (`Ran N tests` is
  unittest's collection count, not execution), the custom-assertion suites must report a positive
  count, and a covered child settles from the parent output that claims to run it under the same
  counter-consistency rule as a scheduled suite — a line whose totals contradict the parent's PASS is
  ERROR, not PASS.
- The manifest declares the non-glob suites discovery cannot name: five static gates, three
  pull-request gates, the three Bun CDP packages, and the `paseo-plugins/gdd-run-observer` Vitest
  package with its own cwd, provisioning, typecheck and test commands.
- Coverage the old globs missed: `skills/ghc-search/scripts/test_ghc_search.py`, plus two Python
  suites that existed but were never wired into CI —
  `skills/delegated-work-acceptance/scripts/tests/test_worktree_scope.py` and
  `skills/gdd/scripts/tests/test_paseo_run_python.py`.

### Changed

- The CI test job installs the runtimes and dependencies, then calls the discoverer. The 34 hand-written
  test-job commands it replaces are reconciled entry by entry in `scripts/test_manifest.toml`, and were
  deleted only once `scripts/test_run_all_tests.py` reproduced every fault plan §4 item 8 requires red —
  a syntax error, a failing assertion, a hang, a missing runtime and an empty discovery set; the
  fault-to-detector mapping is in `docs/evidence/2026-11-14-catalog-refactor.md`.
- Per-suite scratch trees are created under `/tmp` whenever it can hold a directory (an inherited
  operator `TMPDIR` is consulted only where it cannot, and `--scratch` overrides the location); the
  default is outside the checkout, and a root whose worst-case tmux socket would exceed the 108-byte
  `sun_path` limit is reported as that suite's ERROR before it runs instead of failing later as a tmux
  mystery.
- Suite processes keep the shim toolchain's absolute state directories (`MISE_STATE_DIR`,
  `MISE_DATA_DIR`), so a mise-managed `bun` on `PATH` runs under the task-local `HOME` instead of
  refusing with "Config files … are not trusted" or re-installing the tool into the scratch tree.
- Teardown is observed, not assumed, and covers every uncontrolled suite exit. The escalation
  follows the process *group* rather than its leader, so a leader that exits on SIGTERM no longer
  ends it while a same-group descendant keeps running; a suite the runner timed out, or one a signal
  killed before its cleanup callbacks could run, has its process group terminated (POSIX only,
  through `os.killpg`) and the processes still holding its task-local scratch stopped — identified
  by the cwd they were started in or the scratch paths in their environment, from `/proc` — before
  that scratch is deleted; and the record says which outcome happened instead of claiming a teardown
  nothing verified. Every signal has to be justified by identity the run recorded itself: a group is
  signalled only while the kernel still holds the command's own process as this run's unreaped child
  — `waitid` with `WNOWAIT` is that probe, the reservation that keeps a pid which still names its own
  group from being a recycled number — and a scratch holder only while it still points into the
  suite's own task-local scratch; where neither proof holds, nothing is signalled and the record says
  teardown is unverified. The check runs before a command is reaped, so a command that exits cleanly
  and still leaves same-group members behind is torn down while its group is still provable; on a
  host where Python exposes no `waitid`/`WNOWAIT` (macOS before 3.13) the exit observation reaps the
  command instead, whose group teardown — a signal-killed command's above all — is then recorded
  unverified rather than assumed; and a child the kernel reaps outright (an inherited
  `SIGCHLD=SIG_IGN`) settles as an error with an unverified teardown instead of crashing the
  discoverer. Both launcher suites declare the detached resource its sweep owns in
  `scripts/test_manifest.toml`.
- The suite `PATH` prepends the selected interpreter's own directory without resolving it: a POSIX
  virtual environment's `bin/python3` is a symlink to the base interpreter, and resolving it handed a
  suite's own `python3` the base interpreter instead of the environment that carries the repository
  dependencies. `scripts/test_run_all_tests.py` measures that against a real virtual environment.
- The merge with main accounts for the merge-gate suites its CI added: `test_verdict_matrix.py` is
  discovered and refined with a counter adapter (its `unittest.mock` import would otherwise make
  `auto` read it as a unittest suite its summary format is not), and `mutate_verdict_matrix.py`,
  which no discovery pattern names, is declared — both keep running in the discoverer's job.
- The DSH route's suite, `test_dsh_run_python.py`, arrives discovered: the `test*.py` pattern
  schedules it, its detached runner and agent processes are declared in the manifest, and its
  measured 94-126s wall time on the 4-core host makes the 300s timeout explicit.
- Bumped shared skill/catalog version from 0.1.65 to 0.1.66.

## [0.1.65] — 2026-11-15

### Added

- An opt-in DeepSeek Harness launcher, `skills/gdd/scripts/adapters/dsh-run.py`, implements the GDD
  launcher contract on `dsh --profile headless`. `start` spawns a detached runner that pipes the
  `--json` NDJSON stream through the shared `adapters/events-writer.py` bound, keeps `state.json`
  current, and refuses a second `start` for a live slug. Completion is `exit 0` **and** the last
  `final` event carrying `reason.kind == "completed"`; an `exit 0` whose last `final` is missing or not
  `completed`, a runner-level `error` and any other non-signal non-zero exit are `failed`, an
  unfinalized death is recovered as `failed`/`-1` with `stale_recovered: true`, and `kill` writes a
  generation-bound `stop` request the runner polls. A run whose runner is gone is ended by signalling
  each validated process instance through its own `pidfd` handle (TERM, then KILL) — never a bare pid or
  group id — and a platform without that primitive (macOS, Windows, Linux without pidfds) refuses to
  escalate: `kill` exits 1, the run stays `running`/`stopping`, and an operator ends the tree by hand.
  `--max-time` is
  the runner's own stop path (`killed`/`143`, `deadline_exceeded: true`); `--model`/`--thinking` are
  refused before a run directory exists because headless composes no agent presets. Ownership and
  recovery are strict: `start`/`_run` refuse a slug whose run is still live (a hand replay of `run.sh`
  cannot start a second agent), a `.`/`..` name or a slug directory that resolves out of its date bucket
  is refused before any write, discovery and recovery touch only runs whose `state.json` records
  `backend: dsh` (another route's run is listed read-only), a stop that leaves processes alive stays
  `running`/`stopping` with the survivors named instead of publishing `killed`, and a process group is
  only ever signalled per member, enumerated under a continuously verified live anchor — including when
  the group's leader has already exited. Every setting is environment-only: `DSH_BIN`,
  `DSH_RUN_ROOT`/`GDD_RUN_ROOT`, `DSH_RUN_PROFILE`, `DSH_PERMISSION_MODE`, `DSH_APPROVAL_POLICY`, the
  four timeouts (`DSH_RUN_START_GRACE_SECONDS`, `DSH_RUN_STOP_WAIT_SECONDS`,
  `DSH_RUN_SETTLE_WAIT_SECONDS`, `DSH_RUN_DRAIN_TIMEOUT_SECONDS`) and `DSH_RUN_EVENTS_MAX_BYTES`.
- The launcher's ownership and lifecycle are *provable*, not documented: two stable OS locks outside
  every replaceable run directory (a slug claim for starting, a per-slug lifecycle mutex for mutating)
  carry ownership, kernel-held and never taken by age or by a recorded pid; every mutation is bound to
  the immutable operation context (root, slug, run path, generation) and re-validated under the mutex
  immediately before it writes or signals, so a run that replaced the one an operation decided about
  refuses the write; the terminal verdict is one atomic `state.json` replacement written last (the
  `finalized` marker stays for the observer plugin and is never an authority); a stop request names the
  generation and a runner acts only on its own; and escalation signals only through a validated process
  handle (`pidfd`) with the group enumerated under a continuously verified anchor — a platform without
  that primitive (Linux without pidfds, macOS, Windows) refuses to escalate, `kill` exits 1 saying so,
  and the operator ends the tree by hand before re-running `kill` or `status`.
- `skills/dsh-headless-gdd/SKILL.md` is the `kind: mechanism` operating method for that route:
  launcher flags before app flags, one worktree per recorded session (the isolation unit is the
  worktree/session, so the *same* worktree never has two writers while several goals of one repository
  run in parallel in their own), resume of the same increment in the same cwd, the exit→state mapping
  restated with its conditions (including `exit 0` whose last `final` is not `completed` → `failed`),
  the two-condition completion rule with `tool_result.status == "completed"` read as "the tool
  returned", and the file-only recovery substrate (worktree, harness session log, run artifacts).
- `skills/gdd/scripts/tests/test_dsh_run_python.py` runs the adapter against a stub `dsh` on `PATH`
  that emits canned headless NDJSON, with no network or model: **123 tests** pin the completion rule, the
  exit mapping (including `exit 0` whose last `final` is not `completed` → `failed`), the `--max-time`
  deadline, the stop request and its identity-gated escalation, stale recovery, the bounded event
  accounting, argv/stdin passthrough, and every refusal (second start, live replay, bucket escape,
  foreign runs). The hardening rounds add the ownership and lifecycle rules — the mutex spanning a whole
  terminal publication, one lock object per slug across date buckets, generation-bound stops and
  publications, the single-commit order under injected death, fail-closed process identity and
  capability handling, the forced stop holding its mutex through the signal — each with a
  revert-the-rule mutation that fails the suite (the mutation rows, the fifteen-run stability series and
  the counts are recorded in `docs/evidence/2026-11-15-dsh-headless-launcher.md`). A momentary hold of
  the lifecycle mutex is waited out, not read as a refusal, and a committed stop whose tree has not
  vanished yet is waited out within a bound (`DSH_RUN_SETTLE_WAIT_SECONDS`); both are pinned by name.

### Changed

- `skills/gdd/references/transport.md` adds the DSH row to the route table, the DSH headless adapter
  section with the two route-specific rules (the run's cwd must be the worktree its session recorded;
  `--approval-policy never` is required for unattended runs), the DSH configuration table, and the
  route's stub-driven suite beside the OMP and Paseo suites. The route is selected with
  `GDD_LAUNCHER`, never by a reachability probe.
- Bumped the shared skill/catalog version from `0.1.64` to `0.1.65` through `scripts/version.py bump`,
  which mirrors every `skills/*/SKILL.md` `metadata.version` and regenerates both indexes.

## [0.1.64] — 2026-11-15

### Changed

- GDD phase 6 names when its CI clause is inapplicable: no `.github/workflows/*.yml|*.yaml` in the PR
  head tree and zero registered workflows, check runs or statuses on the head SHA, with the merge
  script's verdict exactly `verdict: BLOCKED: no checks`; the operator records `workflows: 0`,
  `checks: 0` beside the script's literal output. Red or pending checks, or workflows present but
  unreported, still block.

## [0.1.63] — 2026-11-15

### Added

- **Three PR-closeout failure modes the catalog was missing.** `gdd/references/run-failure-modes.md`: §6
  out-of-tree tools can silently review missing inputs; §7 gates run under a bare runtime die on a
  missing import and then get skipped; §8 a gate backgrounded inside its launcher unit must be awaited
  before the stage returns or moved outside the stage's teardown boundary.
  `omp-headless-orchestration/SKILL.md` pitfall 15: a "launched" verification is not evidence
  without an exit code.

## [0.1.62] — 2026-11-14

### Fixed

- **Round-17 review findings: the ignored-line report's order is pinned, and the diagnostic surface
  gets the one-shot systematic pass.** The round-16 fixture carried the ignored lines `required-a,
  required-b, required-a` — a palindrome — so a report that reverses its iteration order
  (`for line in reversed(lines):`) survived all 397 cells, the golden call log, the 94 evidence
  tests and the 68 selftest fixtures, with the same MERGE-OK and tally `1/1/0/0`. The fixture is now
  `required-a, required-b, required-a, required-c` — non-palindromic, the repeat kept — and both
  cells assert the exact four-line stderr list in order. Per the standing rule the one-round patch
  stopped there: the whole ignored-line diagnostic surface and the cell assertion mechanism that
  pins it were enumerated as eight properties and each is pinned by its own mutation —
  completeness (`ignored-line-diagnostic-truncated-to-the-first`, from round 16), ordering
  (`ignored-line-diagnostic-reversed`), duplicates (`ignored-line-diagnostic-deduplicated`),
  exactness (`ignored-line-diagnostic-extra-note`), no false positives
  (`ignored-lines-include-recognised-rows`), both paths
  (`ignored-line-diagnostic-only-under-the-opt-in`, `ignored-line-opt-in-warning-dropped`), silence
  when clean (`ignored-line-diagnostic-prints-when-clean`) and the comparison itself (below). The
  comparison is test-side, so no gate mutation can pin its strictness: the comparison is factored
  into one `stderr_problems()` and `comparator_self_check()` runs the de-duplicated, re-ordered and
  extra-line witness of every pinned stderr list through `main()`'s guards — a comparator weakened
  to set equality or containment, or a fixture that stops discriminating (no repeat, a palindrome),
  fails the guard by name while the matrix passes everything else, so neither can land silently.
  The catalogue grows to 90 mutations (58 anchored plus the 32 generated from the 16 declared
  vocabulary entries) and all 90 are caught; the class of gap is recorded under *Closed* in
  `tests/COVERAGE_BACKLOG.md` with the property-to-pin table. The matrix stays at its 397 cells (390
  verdict + 3 stream + 1 sh-trim + 3 boundary) over 9 declared dimensions,
  `test_review_evidence.py` stays at its 94 tests, and the selftest at its 68 fixtures.
- **Round-16 review finding: the ignored-line report is pinned to the whole list.** Both cells that
  drove a tab-less line through `main()` used a *one-line* fixture and asserted the diagnostic as
  substrings, so the reporting loop in `report_ignored_table_lines()` could stop at the first line —
  `for line in lines[:1]:`, or a de-duplicating rewrite — and survive the whole matrix: through
  `main()` on the opt-in path the fallback `(0, "build\tpass\nrequired-a\nrequired-b\n", "")`
  printed two diagnostics under the shipped gate and one under the mutant, both MERGE-OK with tally
  `1/1/0/0`, the second truncated row swallowed silently. The truncated fixture now carries three
  ignored tab-less lines — two distinct, one repeated — and both cells (the opt-in path and the
  default path) assert the **exact stderr line list**: every expected line, in order, repeats
  included, and no other line beside them (a non-ERROR cell that names none must print none), so a
  report that stops at the first line or de-duplicates fails. The mutation
  `ignored-line-diagnostic-truncated-to-the-first` is registered and
  is caught by these two cells (82 -> 83 mutations, 50 -> 51 anchored); the class of gap is
  recorded under *Closed* in `tests/COVERAGE_BACKLOG.md`. The matrix stays at its 397 cells (390
  verdict + 3 stream + 1 sh-trim + 3 boundary) over 9 declared dimensions, and
  `test_review_evidence.py` stays at its 94 tests.

- **Round-15 review findings: the row-retention contract is qualified, the ignored line is named, and
  the table opt-in is pinned against the evidence blockers.** `pr-merge-check.py` stated "only the
  exact header is skipped: every other line is a row", but the shipped parser also ignored a nonblank
  line **without a tab** — and a truncated row has exactly that shape — so the replicated run
  `(0, "build\tpass\nrequired\n", "")` with `--allow-table-only-checks` printed `1 total, 1 ok` and
  reported MERGE-OK with the `required` line gone without trace. The contract is now qualified where
  it is stated — the module docstring, the parser, Phase 6 and this entry: only tab-delimited lines
  other than the exact header are rows; a nonblank line without a tab is not a row, and the explicit
  opt-in accepts that parsing limitation. The skip is no longer silent: `ignored_table_lines()`
  collects every nonblank tab-less line of the table read and `report_ignored_table_lines()` prints
  one `pr-merge-check: ignored table line without a tab (not a row): '…'` diagnostic per line on
  stderr once the read has produced something to report — an operator error keeps its single stderr
  line — adding on the opt-in path that the ignored line could conceal a check. The merge decision
  is unchanged (observability, not a new gate); two cells drive the truncated fixture with and
  without the opt-in and assert the diagnostic beside the unchanged verdict, and the mutation that
  drops the diagnostic is registered. Separately, no cell enabled `--allow-table-only-checks`
  beside blocking *evidence* rather than a blocking *checks* read, so two mutants survived the whole
  matrix — `if not review["pass"] and not
  allow_table_only_checks:` and `if unresolved and not allow_table_only_checks:`, each reporting
  MERGE-OK over a green exit-0 fallback table while the shipped gate blocks with `review` /
  `threads`. Two cells now pair the opt-in with the page-2 marker and the page-2 unresolved thread;
  the two mutations are registered (79 -> 82 mutations, 47 -> 50 anchored), and the class of gap is
  recorded under *Closed* in `tests/COVERAGE_BACKLOG.md`. The matrix now runs 397 cells (390 verdict
  + 3 stream + 1 sh-trim + 3 boundary) over 9 declared dimensions, and `test_review_evidence.py`
  stays at its 94 tests.

- **Round-14 review findings: the table opt-in is pinned against the head/gate blockers, and the
  completeness guards count only executed reads.** `--allow-table-only-checks` decides only whether
  the *table* read is authoritative; every cell that enabled it supplied a matching verified head
  and `--gates-rc 0`, so a mutant that clears the reasons already accumulated at the `table_only = …`
  assignment — `if allow_table_only_checks: reasons = []` — survived all 391 cells (the total then),
  the golden call log, the 94 evidence tests and the selftest, turning a mismatched verified head or
  a failing local gate into MERGE-OK over a green table. Two cells now drive the opt-in beside
  `--verified-head MISMATCHED_HEAD` (BLOCKED `head mismatch, verified head missing`) and
  `--gates-rc 1` (BLOCKED `gates unverified`), and the mutation is registered (78 -> 79 mutations,
  46 -> 47 anchored). Separately, the two completeness guards read `cell.table_result[0]` for every
  cell, including the ones whose structured read succeeded and whose `TABLE_UNUSED = (0, "", "")`
  fixture was never consulted — so table-exit 0 (and its negative coverage) was supplied by cells
  whose table never ran. Both guards now count a table exit only when the cell's read actually ends
  on the table (`_table_consumed()`), and `guard_self_check()` runs the reviewer's reproduction —
  replace every *consumed* table exit 0 with a pending exit-8 table — requiring both guards to name
  the missing table exit 0. The matrix then ran 393 cells (386 verdict + 3 stream + 1 sh-trim + 3
  boundary) over 9 declared dimensions.

- **Round-13 review finding: the exit-code domain is declared once, and both read surfaces carry it.**
  The structured-exit dimension named `0, 1, 4, 8` while the table-exit one named `0, 1, 8, 2, 4,
  -15, 127` — the same `gh pr checks` domain written twice, so one copy fell behind and a category
  could be represented on one surface and missing from the other. Two mutants survived the whole
  matrix through that gap: `if returncode == 0:` read as `if returncode <= 0:` (trusting a
  signal-terminated read, exit -15) and as `if returncode in (0, 2):` (trusting a cancelled one,
  exit 2), each turning a structured `(-15, <passing array>, "")` / `(2, <passing array>, "")` over
  a non-green fallback from BLOCKED `checks pending` (2/1/1/0) into MERGE-OK (1/1/0/0). The domain
  is now declared **once** (`CHECK_RESULT_EXITS` + `OPERATOR_FAILURE_EXITS` = `EXIT_CATEGORIES`) and
  both the `structured-exit` and `table-exit` dimensions are driven from it, so a category cannot
  appear on one surface only; six generated cells — one per declared non-zero exit — hand the
  structured read a parseable **passing** array beside a parsing, pending fallback table, asserting
  the exact verdict and tally. The completeness guard gains a **cross-surface** check
  (`cross_surface_exit_problems()`) that fails by name on a category represented on one surface but
  missing from the other, alongside the per-dimension `dimension_problems()`. Both mutations are
  registered (76 -> 78 mutations, 44 -> 46 anchored); the matrix then ran 391 cells (384 verdict + 3
  stream + 1 sh-trim + 3 boundary) over 9 declared dimensions.

- **Round-11 review findings: the structured read's exit code is required, and the opt-in wording is
  corrected.** Every non-zero structured-read fixture paired its exit with *empty* stdout, so the
  cells could not tell "require exit 0" from "trust any parseable stdout": `if returncode == 0:` read
  as `if returncode == 0 or stdout:` survived all 379 cells (the total then), the golden call log,
  the 94 evidence tests and the selftest — a structured exit 4 whose stdout parsed reported MERGE-OK
  while the real gate fell back to the table and its operator error. Three cells now hand the
  structured read a non-zero exit *and* a parseable payload — a passing array (falling back to a table
  at exit 4 with `authentication failed`, exit 2 with the diagnostic preserved, and to an all-green
  `checks unreadable`), and, with `--allow-no-checks`, an empty array — and the mutation
  is registered (74 -> 75 mutations, 42 -> 43 anchored), so the matrix then ran 382 cells (375
  verdict + 3 stream + 1 sh-trim + 3 boundary). Separately, the *structured-only* wording of
  `--allow-no-checks` was wrong in Phase 6, the module docstring and this entry: alone the flag
  cannot authorise table-only evidence, but together with `--allow-table-only-checks` the table is
  authoritative and an empty one is accepted, so the documented boundary now matches the implemented
  and tested one.

- **Round-12 review finding: the check-result exits are covered, and the completeness of the cell
  dimensions is asserted.** Every round-11 non-zero structured-read fixture used exit **4** — not a
  check-result exit — so the narrower mutant `if returncode == 0 or (returncode in (1, 8) and
  stdout):`, trusting a parseable stdout only at the two exits `gh pr checks` uses for CI state,
  survived all 382 cells and the golden call log. Three cells now pair a structured exit **1** and
  **8** carrying a parseable payload (a passing array, and an empty one under `--allow-no-checks`)
  with a **non-green** fallback table, so the fallback verdict and its exact tally are asserted —
  BLOCKED `checks` (3/1/1/1) at exit 1, BLOCKED `checks pending` (2/1/1/0) at exit 8 — and the
  mutation is registered (75 -> 76 mutations, 43 -> 44 anchored). The class-closing fix is
  structural: every dimension the cells vary over — read source, structured exit code, table exit
  code, flag combinations, JSON shape, table shape, bucket, state, and the fixed
  `--verified-head`/`--gates-rc` pair — is declared as a constant list in the test file, and
  `dimension_problems()` asserts over the assembled `CELLS` that each declared value is represented
  by at least one cell — and by at least one *negative* (BLOCKED or ERROR) cell where the value has a
  verdict consequence — naming the missing value and dimension otherwise. Rounds 11 and 12 both
  slipped through as a value of a declared dimension (a structured exit code) that no cell
  represented; this turns that class into a loud failure. The matrix then ran 385 cells (378 verdict
  + 3 stream + 1 sh-trim + 3 boundary) over 9 declared dimensions.

- **Round-8 review finding: the subprocess boundary pins the repository it forwards.**
  Both boundary fakes accepted `cwd` and ignored it, and every `gh` argument was the same whichever
  directory was passed, so dropping `cwd=repo` at a call site — or replacing `cwd=cwd` inside
  `sh_raw()` with `cwd=None` — left all 376 cells (the matrix total then), the 94 review-evidence
  tests and the 68-fixture selftest green while the child inspected the caller's repository instead
  of the one `--repo` named, invalidating the evidence the gate exists to collect. The matrix gains a
  **boundary dimension** — `boundary-repo-gh-cwd` (`gh` must run in the working directory `--repo`
  names) and `boundary-repo-git-flag` (`git` must carry the same directory in argv as `-C <path>`),
  each driven from a directory distinct from the runner's against a fake that records what
  `subprocess.run()` actually received, and the fingerprint of the hole is that only the *boundary*
  cells flip.
  `RealSubprocessBoundaryTests` gains a recording run over the whole gate and a probe that runs a
  **real** child and asserts the directory it reports — one assertion that covers the forwarded
  directory, text mode and captured output at once. Both surviving mutations are registered in the
  catalogue (63 -> 65 mutations, 31 -> 33 anchored). This is the only relied-on obligation of that
  shape besides the repository: the gate passes no `env=` (its docstring states "Environment:
  none"), so no test pins an environment the gate does not use. The `gh` argv was **not** pinned:
  the cells branch on `cmd[:3]` and on the presence of `--json`, so a dropped `str(pr)` or a trimmed
  field list is invisible to them — round 9 closes that with the golden call log below.
- **Round-9 review findings: the whole forwarded call surface is pinned mechanically, not case by
  case.** Round 8 added the boundary dimension, but two holes of the same family remained, both
  invisible to every cell, every evidence test and the selftest. First, the boundary cells all drove
  a *successful* structured read, so the **table-fallback** call site
  (`sh_raw(["gh", "pr", "checks", str(pr)], cwd=repo)`) was never reached and dropping its `cwd=repo`
  survived the whole matrix — with the requested repository pending and the caller's green, the
  baseline blocked with `checks pending` while the mutant merged. Second, the disk assertions
  dispatched on prefixes (`cmd[:3] == ["gh", "pr", "checks"]`, `"--json" in cmd`) and on path
  membership (`repo in cmd`), so dropping `str(pr)` from the structured argv survived — real `gh`
  then reads the *current branch's* PR — as did `["git", "-C", repo, ...]` -> `["git", repo, ...]`,
  where the path is still in argv but Git no longer has a valid repository selection. The matrix now
  exercises the fallback read at the boundary (`boundary-repo-gh-fallback-cwd`), requires that call
  to have happened with the repository directory, asserts the **complete** check-command shape — the
  structured `gh pr checks <pr> --json name,state,bucket` or the fallback `gh pr checks <pr>`, for
  the requested PR — on both read surfaces, and asserts the adjacent `["-C", <repo>]` pair for every
  `git` call. The class is closed by construction with a **golden call log**: every
  `subprocess.run()` invocation the gate issues while a cell drives `main()` is recorded as
  `(argv, cwd, has_env)` — normalised only by folding the named repository onto `<repo>`; nothing the
  gate relies on is dropped — and the distinct set is compared with an **8-entry snapshot committed
  in the test file** (10 entries after round 10), one entry per distinct call with the reason it is
  there. Any change to a command, an argument, a flag, the PR number, the repository pair or a call's
  working directory, or any new call, fails with the added or removed entry spelled out, and the
  failure tells the operator to review the gate diff and update the snapshot deliberately — a blind
  paste-back would turn "the gate invokes something new" into "the test agrees with the mutation".
  `evaluate_with_calls()` runs the comparison, so the mutation harness exercises it per mutant as
  well: a mutation that trims the `gh pr view --json` field list, which no cell names, is caught by
  the log alone. Six mutations are registered (65 -> 71 mutations, 33 -> 39 anchored), and the matrix
  ran 376 cells after that round (one more boundary cell).
- **Round-10 review findings: the evidence reads' continuation pages and `sh()`'s trimming are
  pinned, and the unexercised paths become a work list.** Both evidence readers paginate, and every
  fake handed back a single terminal page — 100 comments then a stop, or `hasNextPage: false` — so
  neither continuation rule was exercised. `fetch_issue_comments()`'s `if len(batch) < 100: return`
  read as `<= 100` stops at a full page before the page 2 that carries the machine-review marker, and
  `fetch_review_threads()`'s `cursor = page.get("endCursor")` read as `None` stops the thread loop
  before the page 2 that carries an unresolved thread; each turns `BLOCKED` into `MERGE-OK` once the
  blocking evidence lives on page 2, and both survived all 376 cells, the golden log, the 94
  evidence tests and the selftest. The matrix now serves multi-page evidence (`comment_pages`,
  `thread_pages`) and drives two cells whose **page 2 is what changes the verdict** — a marker on
  comment page 2 and an unresolved thread on thread page 2 — and the golden call log grows to 10
  entries so it covers the comment page-2 read and the cursor-carrying GraphQL request. Separately,
  every fake fed the gate a child that printed exactly `feature`/`HEAD` with no trailing newline, so
  `sh()`'s `stdout.strip()` never had to remove anything and deleting it survived everything; a real
  child prints `feature\n`, which `resolve_head()` would compare against `headRefName` and report as
  `head not verified` for a branch that did verify. A new `ShCell` probe asserts the value `sh()`
  returns from newline-terminated output, against the literal. Three mutations are registered (71 ->
  74, 39 -> 42 anchored), and because four rounds each found an unexercised path rather than a
  defect, the increment also adds `tests/COVERAGE_BACKLOG.md`: an ordered work list of the paths in
  `pr-merge-check.py` these artefacts still do not pin — a GraphQL `errors` payload read as an empty
  thread list, a non-array comment page read as no comments, `main()`'s `--json` contract and usage
  exits, a `hasNextPage` page that returns no cursor, the composed human lines other than `checks:`
  and `verdict:`, the malformed `gh pr view` payload, the `--gates-note`/`--gates-rc` plumbing, a
  slash-less `gh repo view` name, and the unreachable `offline` parameter — each with the
  regression's effect on a verdict and the smallest fixture that would pin it.
- **Round-7 review findings: only a check-result exit is CI data, and both opt-ins together still
  cannot forgive a non-green read.** `gh pr checks` reports CI state through exactly two exit codes —
  1 (a check failed) and 8 (a check is pending). The table fallback accepted *every* non-zero exit as
  data once the parsed table was not all green, so an operator error — gh's documented 2
  (cancellation) and 4 (authentication), or a signal's negative code — was laundered into
  `verdict: BLOCKED: checks pending` (exit 1) with stderr discarded, hiding an interrupted or
  unauthorised read behind the gate's own exit-2 operator-error contract. `fetch_checks()` now
  accepts only `1`/`8` as table data and raises `GateError` (exit 2) for any other non-zero exit,
  preserving that exit code and the diagnostic in the one-line message. `--allow-table-only-checks`
  together with `--allow-no-checks` is still two narrow opt-ins, not a bypass: the matrix now pins
  both flags against non-green JSON **and** non-green table evidence, where a mutant that skipped the
  non-green branch when both flags were set previously reported MERGE-OK over a pending run. And
  because `gh` check names are not unique identifiers, the matrix pins row retention as a family —
  two rows that differ only by verdict, under a repeated name, an empty name, a whitespace-only name
  and a printed column name, in both orders and on both surfaces — where a mutant that indexed
  structured rows by name previously collapsed two rows into one and reported MERGE-OK over a failing
  run. All three mutations are registered in the catalogue.
- **The merge gate could not be run while CI was in flight.** `pr-merge-check.py` asked `gh pr
  checks --json name,state,conclusion`; gh 2.103 removed `conclusion` (`Unknown JSON field:
  "conclusion"`), so it failed and fell back to the table, whose non-zero exits — 8 while a check is
  pending, 1 when one failed — reached `sh()` and ended the gate at **exit 2**. `fetch_checks()` now
  reads `--json name,state,bucket`, mapping gh's grouping to the tool's vocabulary:
  `pass`/`skipping`/`neutral` ok, `fail`/`cancel` failures, anything else — including `pending` —
  pending. With `--json` gh exits 0, an unfinished run as a `"bucket":"pending"` row, so the bucket
  mapping is the mechanism for a pending run. The non-zero table branch is the `gh < 2.103`
  fallback, where a parsed table is data too: an unfinished run reports `checks: N total, M ok, P
  pending, F failing` and verdict `BLOCKED: checks pending`, so the operator re-runs. Unparseable
  output raises and exits 2. A malformed `--json` array — a non-object row beside a passing one, or
  only non-objects — also exits 2 rather than dropping the bad row: `--allow-no-checks` forgives a
  PR with zero check runs, never an unreadable list. The table fallback no longer skips rows by a
  `NAME` prefix — that dropped checks named e.g. `NAME-required` and could report MERGE-OK over a
  failing run; gh's column header is now recognized as exactly the five printed column names in
  print order (`NAME STATUS ELAPSED URL DESCRIPTION`), because matching them as an unordered set
  accepted `STATUS\tNAME` as a header and let a row whose verdict word was unknown *vanish* under an
  all-green remainder; and a comparison that stripped empty fields and uppercased before comparing
  made two more data rows indistinguishable from the header — `NAME\t\tSTATUS\tELAPSED\tURL\t
  DESCRIPTION` (an empty field) and `name\tstatus\telapsed\turl\tdescription` (lower case) — so the
  row vanished and only the passing remainder counted. The header comparison is now exact: the five
  printed column names, in print order, with the field count, the empty fields and the case
  preserved. Every other line — a permutation of the column names, a partial header, an empty-field
  row, a lower-cased row, a check named after a column — is a row, and a row whose verdict word is
  unknown blocks. Header recognition and the field split both read the **original** line: stripping
  the whole line first erased a field boundary, so a row carrying a leading empty field, and the
  five-column header carrying one extra trailing tab, collapsed onto the exact header and vanished,
  leaving an all-green remainder to report MERGE-OK. Only a whitespace-only line is now detected
  through a strip, and each data field is normalised on its own. The verdict words are one declared
  `CHECK_VOCABULARY` (`pass`/`skipping`/`neutral` ok, `fail`/`cancel` failures, `pending` pending,
  plus the words earlier revisions accepted) rather than two hand-kept maps, and
  `tests/gh_checks_fixtures.py` holds the `gh pr checks` table and
  `--json` output captured live from three open PRs — one with a pending run, one failing, one
  finished — so the vocabulary is read from the tool rather than remembered. A non-zero exit is also
  evidence the read was incomplete, so an *all-green* parsed table under one — a truncated row that
  vanished, or a command error beside passing rows — now exits 2 instead of reporting MERGE-OK; only
  a successful read of zero check runs is the empty state, and
  only `--allow-no-checks` accepts it. The class-closing rule ends the whole family of fail-opens
  this increment produced, all of which came from the human table fallback authorising a merge: a
  **table-only read may never produce MERGE-OK**. When the structured read did not produce the rows,
  the parsed table is *advisory* — a non-green row blocks as before, and an all-green or empty table
  blocks too, with reason `checks unreadable` and **exit 1** (a verdict about unverifiable evidence,
  not an operator error, so not exit 2). `--allow-table-only-checks`, named in the module docstring
  and in Phase 6, is the explicit opt-in that restores the table's authority for an operator whose
  gh cannot do `--json`; the default fails closed, and the opt-in bypasses neither the exact-header
  rule nor the unknown-verdict rule. The zero-check-runs block, `--allow-no-checks`, the marker
  schema and the `--gates-rc`/`--verified-head` clauses are untouched: pending is never green.
- **Tests**: `tests/test_review_evidence.py` gains `CheckFetchTests` and `CheckFetchCliTests` — the
  requested JSON fields, the surface label each read carries (`json` authoritative, `table`
  advisory), the bucket mapping (including an unknown bucket, which must stay pending even when the
  raw `state` reads `SUCCESS`), a pending table at exit 8 and at exit 1, unparseable output,
  malformed check rows at exit 2 with and without `--allow-no-checks`, the empty fallback table with
  a zero exit in all four flag combinations (table-only: neither flag and `--allow-no-checks` alone
  block `checks unreadable`, the table opt-in alone blocks `no checks`, and only both flags together
  merge), a missing gh binary at exit 2, the non-JSON and non-list-JSON fallbacks, a table-only green
  read blocking with `--allow-table-only-checks` restoring it, the opt-in unable to bypass the header
  or unknown-verdict rules, and `main()`'s exit code plus verdict for each — plus
  `RealSubprocessBoundaryTests`, which patches `subprocess.run()` only, keeping `sh()`/`sh_raw()`
  real: the exit code and both streams are forwarded verbatim, and a non-zero exit never becomes an
  empty-but-valid check list — 42 -> 94 test methods. The shipped `--selftest` gains the bucket
  vocabulary (a recognized raw state under an unknown bucket stays pending), its tally, the table
  rows whose names begin with `NAME`, the unordered and partial headers that used to vanish, the four
  header-shaped data rows a normalising comparison dropped (an empty middle field, a lower-cased
  row, a leading empty field and the header with a trailing one) with their tallies, the captured
  pending row, and one fixture per declared table verdict with the whole vocabulary's tally
  (30 -> 68 fixtures).
- **The check-fetch surface is pinned by two self-verifying artefacts** rather than hand-picked
  cases. `tests/test_verdict_matrix.py` declares, test-side and literally, the meaning of every
  vocabulary token (`DECLARED_VOCABULARY`) and asserts the gate's `CHECK_VOCABULARY` matches it token
  by token; the cells derive their expectations from that declaration, never from the gate, so a
  reclassified token — or a swap of two tokens' meanings, the shape that stayed invisible while the
  matrix read the artefact for what was correct — fails loudly. It enumerates the closed input space
  — JSON shape x fallback table shape x exit code x `--allow-no-checks` x the table-only opt-in,
  with all four combinations of the two opt-ins pinned for an empty table so neither can stand in for
  the other — and *generates* the rest: one cell per declared `CHECK_VOCABULARY` entry (on the table
  surface with and without the opt-in) and the bucket x state dimension from the raw state vocabulary
  gh reports, with each expectation computed from the invariants (fail closed; the bucket governs;
  pending and failing block; a table-only read may never authorise; the opt-out forgives a
  zero-check read, and the two opt-ins are independent — the table opt-in alone makes an empty
  table the zero-check state, which only `--allow-no-checks` forgives). Every cell drives `main()`
  with `subprocess.run()` mocked and compares
  the **complete** verdict line plus the printed `checks:` tally — and, where a cell names them,
  its exact stderr line list, no line beside them — so a failing read cannot pass as a
  pending one (`verdict: BLOCKED: checks` is a prefix of `verdict: BLOCKED: checks pending`) — 390
  verdict cells + 3 stream cells + 1 sh-trim cell + 3 boundary cells (397 cells) over 9 declared
  dimensions, plus
  the 10-entry golden call
  log that pins every `subprocess.run()` invocation the gate issues. `dimension_problems()` asserts
  that every value of every declared dimension is represented by at least one cell — and by at least
  one negative cell where the value has a verdict consequence — so a future dimension value cannot be
  silently unrepresented, and `cross_surface_exit_problems()` fails on an exit category the cells
  exercise on one read surface but not the other (round 13's gap, now a hard failure). The captured
  live output in
  `tests/gh_checks_fixtures.py` is a matrix input as well: a value gh prints that the declared
  vocabulary does not know fails the matrix instead of reaching the gate as an unknown token.
  `tests/mutate_verdict_matrix.py` applies 90 in-memory mutations of the module — 58 anchored plus
  two generated per declared vocabulary entry, reclassifying that token into every other
  classification — and requires each to flip at least one cell (or change the golden call log),
  naming the survivor loudly if one does. Both run in CI. The paths the artefacts still do not
  pin are queued, by consequence, in `tests/COVERAGE_BACKLOG.md`, which also keeps the gaps already
  found and closed.

## [0.1.61] — 2026-11-14

### Added

- A portable pinned-snapshot catalog measurement helper and regression tests distinguish
  trimmed SKILL.md bodies from complete files and exclude fenced pseudoheadings. The baseline
  split predicate selects 13 skills; sanitized evidence records input/report hashes and all findings.

### Changed

- Revised the catalog plan after simplify/code-review findings: withdraw the five false dead-path
  claims and retain them as scoped positive fixtures; correct test-presence, targets, registry,
  code-size and body-size measurements. Claims that kind is dead or runtime targets are enum drift
  are withdrawn; the plan cites the checker code that refutes them, without removing that code.
- Keep explicit kind/R2/R7 and role-aware routing, including the mechanism must_pick prohibition.
  Discovery uses named shell patterns, covered-child accounting, explicit Paseo/Vitest package
  reconciliation, tested result/skip protocols and complete fault evidence before deleting CI commands.
- Separate universal static syntax from safe bounded CLI-help remediation and dependency-tier
  behavior tests; preserve every split migration/refusal/install/rule-removal evidence requirement.
  Attribute audit conclusions instead of claiming unverified independence or host automation.
- Bumped shared skill/catalog version from 0.1.60 to 0.1.61 after integrating the machine-review PR.
  This is a corrected implementation plan, not execution of its future refactor phases.

## [0.1.60] — 2026-11-14

### Added

- GDD's `review-evidence.py` generates a PR comment from the exact completed UTF-8 report file,
  with explicit full head, model, provider, and findings flags. Shared `machine_review.py` embeds
  the entire report and hashes its original bytes without newline or Unicode normalization.
- Offline schema/mutation, Unicode/CRLF, hash-tamper, malformed JSON/type, newest-evidence,
  custom-marker, real CLI file roundtrip, and full merge-gate integration regressions run in CI.

### Changed

- `pr-merge-check.py` defaults to provider-independent `machine-review-state:v1` and requires
  completed, clean evidence with an exact full 40-hex current head, nonempty model/provider,
  nonempty UTF-8 report, and matching SHA256. Abbreviated SHAs and status/SHA-only evidence no
  longer pass. Custom markers retain the same schema; malformed newest evidence blocks older
  clean evidence, and the explicit no-review opt-out applies only when no selected marker exists.
- Restored the documented local-gates clause: absent `--gates-rc` now blocks instead of merely
  displaying `UNKNOWN` while allowing an otherwise green PR. CI, PR-state, verified-head, and
  unresolved-thread clauses remain independent of the machine-review verdict.
- Replaced stale hosted-bot request instructions with an explicitly provider/model-pinned
  headless review lane, configured Responses-route requirements for GPT-family endpoints,
  full-report evidence generation, exact PR-comment readback, head rechecks, and finding/thread
  dispositions. No login, credentials, services, runtime configuration, or model defaults are changed.
- Custom-token evidence starts directly with the token, avoiding heading/delimiter collisions.
  The reference lane rejects fuzzy-only registry matches and verifies actual resolved model/provider
  and Responses transport from a fresh runtime session receipt before stamping provenance.
- `review-receipt.py` validates explicit lane API IDs and transport independently of model spelling;
  all supported Responses adapters are accepted when declared, while namespaced models cannot bypass
  that requirement. Failed, aborted, truncated or incomplete final assistant receipts block the lane;
  Unicode separators inside JSON strings are preserved by LF-delimited receipt reading.
- Bumped the shared skill/catalog version from `0.1.59` to `0.1.60`.

## [0.1.59] — 2026-11-14

### Added

- An opt-in native Paseo launcher, `skills/gdd/scripts/adapters/paseo-run.py`, implements the GDD
  launcher contract with daemon-backed agents and a detached artifact monitor. Runs retain
  `backend: paseo`, `session_id` / `agent_id`, polled state, and answer artifacts. Missing state or
  agents, an unreachable daemon, and unknown daemon states never count as success.
- Optional `paseo-plugins/gdd-run-observer` source with clean-checkout install/test instructions,
  trust boundaries, disable/removal instructions, and an HOA integration guide. The read-only
  observer is not a launcher and is never auto-installed.

### Changed

- The native Paseo detached monitor retries refresh-claim contention indefinitely instead of
  exiting after 30 seconds while a permitted 60-second CLI call still holds the claim. Only
  terminal state or a finalized marker resolves its wait; contention preserves the published
  observation. A real 33-second stub regression covers monitor liveness, finalization, and the
  file-only reads used by `gdd.py stage --wait`.
- Unresolved native Paseo runs keep reserving their worktree through offline status refreshes
  and monitor loss without disguising `unknown` as `running`; confirmed terminal outcomes or
  deletion release the reservation. Headless run-state handling is unchanged.
- Observer metrics stay unavailable for lifecycle-only event streams instead of displaying
  invented zero turns, tool calls, and cost; the counter source reflects actual measurements.
- Observer native Paseo lifecycle rows retain the adapter's `at` timestamp and both `state` and
  `status` in the existing bounded `detail` field. Running, outage, failure, and completion
  transitions remain distinguishable and advance `lastEventAt` without changing the RPC schema.
- Observer counters recount retained events in the same list, follow, or detail scan after the
  launcher atomically replaces `events.ndjson`, instead of briefly returning null metrics.
- Preserved native Paseo cwd provenance failures across refreshes until inspect verifies the
  requested directory. Observer counters now share per-run in-flight updates, retain split NDJSON
  lines without rereading buffered bytes, and keep complete UTF-8 events in detail/follow tails.
- Documented explicit transport selection through `GDD_LAUNCHER`: bundled `omp-run.py` remains the
  default; `paseo-run.py` requires a reachable daemon, with no reachability-driven substitution.
  Native provider/thinking overrides leave daemon defaults intact when unset. CLI 0.15.4 answer
  retrieval uses `paseo logs <id> --filter assistant_message --tail 1`, deliberately without
  `--json` because logs returns rendered text, rather than inventing an inspect answer field.
- Added deterministic JSON-argv `PASEO_BIN` configuration for Windows multiline prompts; batch
  shims refuse unsafe prompts instead of truncating them. Native dispatch scrubs verified ambient
  caller/workspace identity variables so the explicit stage cwd controls placement.
- Native `kill` requires a confirmed hard-delete receipt, not a turn interrupt. It preserves
  cached answer text and appends deletion evidence without changing finalized outcomes.
- Recorded Windows/WSL aggregate verification (83 tests each, exit 0; three Windows skips and
  four WSL skips) and observer plugin tests (45 passed, one skipped, exit 0), plus a corrected Windows native
  multiline daemon smoke, separate from inherited headless evidence. Documented WSL tmux's
  native-filesystem temp-directory requirement after DrvFS rejected unsafe permissions.
- Bumped the shared skill/catalog version from `0.1.58` to `0.1.59`.

## 2026-11-14 — the X engine's default names a model the proxy still serves

An `x` search that passed no `--model` died with `HTTP 400 … the selected model could not
be resolved`: the built-in default `grok-4.5` is no longer among the models the proxy
serves, which now lists `grok-4.6` and `grok-4.7`. The default is `grok-4.7` now, and the
skill's default table and the per-engine default test say the same thing. The
`GHC_SEARCH_MODEL_X` override and the gpt engine are unchanged.

## 2026-11-14 — the delivery loop's launcher stops being bash-only

The launcher was `skills/gdd/scripts/adapters/omp-run.sh`: bash, `setsid` (or `tmux`) and a POSIX
`python3`. On Windows the loop could not run at all, and macOS ships no `setsid` either, so it needed
`--backend tmux` there. The contract now has a cross-platform implementation, and `gdd.py` defaults to it.

- **`skills/gdd/scripts/adapters/omp-run.py`** (new, stdlib Python 3): the whole contract — `start`,
  `list`, `status`, `result`, `answer`, `tail`, `kill` — with the same run-directory artifacts, the same
  bounded event log (`adapters/events-writer.py` is reused, not reimplemented), the same stale recovery
  (`failed`, exit `-1`, `stale_recovered: true`, idempotent, never over a `finalized` marker) and the
  same ledger row. Detachment is `start_new_session=True` on POSIX and
  `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` on Windows.
- **The Windows console rule is measured, not asserted.** Same launcher, only the creation flags
  differing: with `DETACHED_PROCESS` the run has *no* console and the first console-subsystem process
  below it allocates a **visible** one (the flash, once per tool command); with `CREATE_NO_WINDOW` the
  run and its descendants share one console that has no window at all. `state.json` records both halves
  — `spawn` (the flags requested) and `detach` (what the run observed: console, console process count,
  window, window visibility on Windows; session/process-group leader and controlling terminal on POSIX)
  — and the suite asserts them against each other.
- **`kill` works where signals do not.** The adapter writes a `stop` control file the run polls, waits
  for the run's own finalizer, and only then escalates to a process-group TERM/KILL (POSIX) or
  `taskkill /T /F` (Windows). A stopped run ends as `killed` with exit `143` on both platforms, instead
  of only being discovered dead by the next `status`.
- **`skills/gdd/scripts/gdd.py`**: a `.py` launcher is spawned through the current interpreter on
  Windows — `CreateProcess` cannot execute a `.py` file at all — and with `CREATE_NO_WINDOW`, so a
  dispatch flashes nothing either. POSIX spawns exactly as before, and `DEFAULT_LAUNCHER` is the `.py`
  adapter.
- **`skills/gdd/scripts/tests/test_omp_run_python.py`** (new): stdlib `unittest`, so it runs where the
  bash suites cannot. A stub agent CLI emits OMP-style NDJSON; the suite covers start → settled run,
  answer extraction, the exit-code mapping, stale recovery (once), `kill` through the stop file, the
  event bound with a non-zero `events_dropped_bytes`, argument passthrough, the detachment evidence
  above, the Windows `os.replace` retry, and the `tmux` backend on an isolated socket. 34 tests by the
  end; the `tmux` one skips where tmux is absent. One drives `gdd.py stage --wait` through the bundled
  default launcher into a temp repo, so the dispatch path itself — not just the adapter — is pinned; the
  rest pin what an adversarial review found: a second `start` over a live claim, a finalizer that died
  before its marker, a forced stop recorded as `failed`, a tool that outlives the agent, and the event
  bound held under a live reader.
- **`skills/gdd/references/transport.md`**: a platform matrix with the evidence for every row, the
  adapter's own keys (`OMP_BIN`, `OMP_RUN_ROOT`, `OMP_LEDGER`, `OMP_RUN_EVENTS_MAX_BYTES`,
  `OMP_RUN_START_GRACE_SECONDS`, `OMP_RUN_DRAIN_TIMEOUT_SECONDS`, `OMP_RUN_STOP_WAIT_SECONDS`) and the
  two platform rules: one hidden console on Windows, and never a
  Windows launcher from inside a WSL2 distro — interop is asymmetric, so `start` warns when a distro is
  about to launch a `/mnt/<drive>/…` or `.exe`/`.cmd` agent.
- **`adapters/omp-run.sh` stays** the POSIX reference adapter, the one with the attachable `tmux`
  backend, and its two bash suites are unchanged. The forwarder in `omp-headless-orchestration`
  resolves the bundled `.py` adapter first so manual and dispatched runs still share one code path.
- Also: `os.replace` of `state.json` now retries on Windows (`WinError 5` when any process holds the
  file open — a plain `status` poll was enough to kill a starting run), the selftest exercises the
  bundled adapter's contract and its default in `gdd.py`, and CI runs the new suite.
- **`skills/gdd/scripts/watch-pr-checks.py`** (new, the loop's other bash-only tool): the CI poller
  ported with the same semantics — bounded polls, the under-60 s infra rerun, a `MERGEABLE CLEAN`
  requirement before it reports green, exit 0/1/2/3, every poll in `ci-watch-<head7>.log`. Its
  intervals are configuration now (`WATCH_POLL_SECONDS`, `WATCH_FAST_FAIL_SECONDS`,
  `WATCH_RERUN_WAIT_SECONDS`, `GH_BIN`) instead of literals, which is also what lets
  `scripts/tests/test_watch_pr_checks.py` drive the whole state machine against a scripted `gh` in
  seconds. `watch-pr-checks.sh` stays as the POSIX twin.

## 2026-11-13 — retired names stop being headings

`notes-to-prd`, `plan-to-issues` and `arch-improvement-plan` kept their pre-rename titles as the H1
(`# to-prd`, `# to-issues`, `# improve-codebase-architecture`), so a reader following the old name landed
on a document that still called itself that. The headings now match the skill names, which is what makes
a rename finished rather than merely staged.

The three host copies the same names came from are retired on the host side (backup kept).

## 2026-11-13 — batch 2 closes the port list: design-md, find-nearby, whisper

The rest of the A2 handover. `design-md` (Google's DESIGN.md token spec, with its starter template),
`find-nearby` (with `scripts/find_nearby.py`) and `whisper` (with `references/languages.md`) move into
the catalog under its schema; host-only companions in their prose are rephrased so nothing dangles.

The handover's ten items resolve as seven ports and three duplicates: `to-prd` and `to-issues` are the
older names of `notes-to-prd` and `plan-to-issues`, and `improve-codebase-architecture` is a 13-line
stub whose description `arch-improvement-plan` already carries.

## 2026-11-13 — four research skills join the catalog (A2 batch 1)

`official-document-verification`, `research-stream-consolidation`, `review-revision-candidates` and
`rss-feeds` were running from the host with hub-style frontmatter. Their bodies are now in the catalog
under its schema, and the references that pointed at skills nobody can install
(`research-control-record-repair`, `reddit-reading`, `blocked-page-recovery`) are rephrased.

Two of the ten skills in the same handover, `to-prd` and `to-issues`, are the older names of
`notes-to-prd` and `plan-to-issues` — not ports.

## 2026-11-13 — the round caps become mechanical, and a gate exit stops meaning "red"

`SKILL.md` said `implement`/`simplify`/`review` run at most twice. Nothing enforced it: `stage`
dispatched regardless, and the ledger's `rounds_simplify`/`rounds_review` columns were `-` in every
row of a 36-row ledger, so a new session could neither read the count nor be stopped by it.

- `budget_problem()` + `ledger_rounds()` (pure): `stage` counts the ledger rows for this repo+goal+stage
  and refuses the third run with exit 3; `--over-budget` is the explicit override, and every dispatch
  writes its own rounds value.
- `02-verify.md`: a non-zero gate exit does not say *why*. Three consumer repos flatten "tool missing",
  "process killed" and "code regressed" into the same `exit 1`. The phase now asks for prerequisite
  markers, signals/OOM and a toolchain `PATH` in the same subshell before a `fix` round is dispatched.
- `06-merge.md`: the merge gate is `<gdd-skill>/scripts/pr-merge-check.py`, not a repo-relative path
  that no consumer repo has.

## 2026-11-13 — three live host skills flow back into the catalog

`hermes-models`, `hermes-updates` and `hermes-context-file-loading` had been running from real
directories in the host for weeks while the catalog kept the earlier port. The host copies are the ones
edited daily (Chinese trigger tables, the routing-audit rules, several new failure cases), so the
catalog was quietly behind: `install_host_skills.py --check` reported all three as drifted and refused
to re-link them.

- Bodies now come from the host; the frontmatter schema stays hoa's (the checker owns it).
- `hermes-models` gains `references/fleet-cutover.md` and `scripts/audit-routing-inventory.py`; every
  changed reference (`config-drift*.md`, `custom-providers.md`, `delegation-routing.md`,
  `model-endpoint-matrix.md`, `model-switching.md`, `provider-metadata-audit.md`, `cases.md`,
  `install-layout.md`, `upgrade-*.md`, `maintenance-window-recovery.md`,
  `update-execution-and-runtime-state.md`, `auditing-instruction-files-workflow.md`) and its scripts
  and template come across too.
- Scanned for host-private literals before landing: no home paths, handles, ids or keys in any of the
  three.

## 2026-11-13 — the ledger gets its landing row, and the protocol loses two phantom commands

Field audit of four consumer repos (`anc`, `funnysharp`, `passquest`, `symmetry`) against
`~/.local/state/gdd/ledger.tsv`: 36 rows, **zero** `verify`/`review`/`gates`/`pr`/`merge`/`done`
entries, `pr`/`rounds_*`/`findings` columns empty throughout, and four goals whose recorded `head_sha`
was the tree *before* the final stage. More than 80% of merged PRs were absent from the ledger.

- **`gdd.py close --repo R --goal G --pr N`** (new): writes the landing row — `stage=done`, the PR, the
  merged head. It is the row the operator stopped writing by hand, which is why a new session read every
  shipped goal as still in `fix`. `07-ledger.md` now says to write it in the same breath as the merge.
- **`--wait` backfills the head**: an authoring stage (`implement`/`apply`/`fix`) now records the
  post-run `rev-parse HEAD` instead of the pre-run SHA (`note` gains `head=<sha7>`). Report-only stages
  keep the head they were given: the checkout may have moved on, and the reviewed SHA is the fact.
- **`gdd.py scope`** (new): prints the resolved `worktree-scope.py`, resolving `GDD_WORKTREE_SCOPE`
  through the same config chain as every other key — the phase docs call it, so a value in
  `$XDG_CONFIG_HOME/gdd/config.yaml` counts, not just an exported variable.
- **Dispatch gate** (new, pure and unit-tested): `implement` is refused when no contract resolves (it
  printed `-` and dispatched anyway), when the contract is archived, when its header says
  `Provisional`/`superseded`/`completed`, or when the worktree is dirty; `simplify`/`apply`/`review`/
  `fix` are refused when `base == head` (empty range). `--force` overrides; `GDD_DISPATCH_GUARDS=off`
  exists for the selftest fixtures.
- **Two phantom commands removed from the protocol**: `worktree-scope.py` is invoked as
  `${GDD_WORKTREE_SCOPE:-../delegated-work-acceptance/scripts/worktree-scope.py}` (a bare command made
  Phase 1 a `command not found` for anyone who installed `gdd` alone), and `python scripts/version.py
  check-merge` is now the profile-declared merge-time gate — it exists in `hoa` only, and writing it as
  universal made all four consumer repos silently skip Phase 6.
- **Tests**: `tests/test-dispatch-guards.py` (13 cases: empty/archived/provisional/dirty/empty-range/
  force/state-header) runs inside `run-gdd-selftest.sh`, which is now 86 cases.

## 2026-11-13 — the merge gate stops accepting "no checks"

- **`skills/gdd/scripts/pr-merge-check.py`**: `evaluate_checks()` returned `pass = pending == 0 and
  failing == 0`, so a PR with **zero check runs** — a `CONFLICTING` PR, for which GitHub dispatches no
  workflow at all — printed `MERGE-OK`. An empty list is now a block with reason `no checks`; accepting
  that state takes an explicit `--allow-no-checks`, for a repo that genuinely has no CI.
- **Same gate, two truncations**: `reviewThreads(first:100)` never followed `pageInfo`, so the 101st
  unresolved thread was invisible; issue comments came from `gh pr view --json comments`, which truncates
  on a large PR. Both are paginated now, and the bot marker's `commit_sha` goes through the file's own
  `same_sha()` (>= 7 chars) instead of `startswith`, which accepted a 4-character prefix.
- **Tests**: `--selftest` covers `evaluate_checks` (empty, pending, failing, all-green, allowed-by-flag)
  and `same_sha` (exact, 7-char, short prefix, empty) — 19 -> 28 cases. `.github/workflows/ci.yml` now
  runs `test-omp-run-setsid.sh`, the default launcher backend, which had no CI coverage at all.

## 2026-11-13 — `gdd` controller + phase playbooks, four standalone entries

- **Monolithic `gdd` controller**: `goal-driven-delivery` → **`gdd`** (controller, ≤120 lines), with
  per-stage detail in `references/phases/*.md` playbooks rather than separate stage/mechanism skills.
  `GDD_*` keys, `scripts/gdd.py`, the ledger and the state directory are unchanged; only the config
  file moves to `$XDG_CONFIG_HOME/gdd/config.yaml`.
- **Standalone non-family skills**: among the eight candidate ports, four were falsified as separate
  skills and removed after folding their net-new rules into `gdd/references/` (`agent-run-acceptance`,
  `repo-gate-execution`, `unattended-pipeline-recovery`, `mechanism-propagation`); four ship as
  independent `entry` skills outside any `gdd-*` family: `measurement-campaign-evidence`,
  `project-phase-closeout`, `structural-validity-gates`, and `package-release-verification`.
  `subagent-driven-development` keeps its original name (`stage`) and `SDD_*` configuration keys, with
  an explicit boundary note against `gdd`'s single-run, no-commit stage protocol.
- **Contract graph**: `define-goal` produces `goal-contract` (consumed by `gdd`); `external:` gained
  nothing.
- **Rules**: `generalization-rubric.md` now admits `controller` and `stage` when every repo-specific
  gate, launcher, review bot and approval boundary is configuration — the old "atomic mechanisms only"
  line contradicted the four-layer contract CI already enforces.
- **CI**: the loop's own tests run in CI now (`run-gdd-selftest.sh` 85/85, `test-omp-run-stale.sh`
  7/7). They were local-only, so a broken launcher path or a stale `SKILL` constant could merge green.
- **Evals**: two routing cases for `gdd` (`route-contract-increment-to-gdd`, `route-explicit-gdd`).
- **README**: catalog counts removed from prose, per `rules/generated-means-generated.md`.

## 2026-11-11 — the reference launcher gets a second backend

- **`skills/goal-driven-delivery/scripts/adapters/omp-run.sh`**: the launcher no longer hardcodes tmux.
  `OMP_RUN_BACKEND` (or `--backend`) picks `setsid` (default, survives a dropped session) or `tmux`, and the
  chosen backend is written to `state.json` so `poll` and `kill` act on what actually started the run.
  Resolves the "run has no lock file" and "kill the wrong process group" pair in one place.
- **`skills/goal-driven-delivery/scripts/tests/test-omp-run-setsid.sh`** (new): drives a stub CLI through
  both backends — start, running, finalize, kill — 7/7. Existing selftest 85/85 and the stale-lock test 7/7
  still pass, including the case where a run recorded a pid but never wrote a lock.
- **`skills/goal-driven-delivery/references/transport.md`**: documents the two backends and how a caller
  chooses one, so the contract is written down next to the code that implements it.

## 2026-11-11 — `notes-to-prd` joins the catalog

- **`skills/notes-to-prd/`** (new): turn notes or an idea into a structured PRD draft. Ported from a private runtime: no machine path, no bot
  name, no model id, and the capabilities it names are the general ones. Chinese note: 把笔记或想法转成结构化 PRD 草稿.
  Targets `runtime-agnostic`; areas `work-management`; kind `entry`.

## 2026-11-11 — `plan-to-issues` joins the catalog

- **`skills/plan-to-issues/`** (new): break a PRD or plan into issue-level tasks with titles, bodies and labels. Ported from a private runtime: no machine path, no bot
  name, no model id, and the capabilities it names are the general ones. Chinese note: 把 PRD 或计划拆成 issue 级任务：标题、正文、标签.
  Targets `runtime-agnostic`; areas `work-management`; kind `entry`.

## 2026-11-11 — `ocr-and-documents` joins the catalog

- **`skills/ocr-and-documents/`** (new): extract text from PDFs and scans with pymupdf or marker-pdf. Ported from a private runtime: no machine path, no bot
  name, no model id, and the capabilities it names are the general ones. Chinese note: 用 pymupdf 或 marker-pdf 从 PDF 与扫描件里抽文本.
  Targets `runtime-agnostic`; areas `work-management`; kind `mechanism`.

## 2026-11-11 — `jupyter-live-kernel` joins the catalog

- **`skills/jupyter-live-kernel/`** (new): iterate on Python inside a live Jupyter kernel instead of restarting scripts. Ported from a private runtime: no machine path, no bot
  name, no model id, and the capabilities it names are the general ones. Chinese note: 在活的 Jupyter kernel 里迭代 Python，而不是反复重启脚本.
  Targets `runtime-agnostic`; areas `software-development`; kind `mechanism`.

## 2026-11-11 — `arch-improvement-plan` joins the catalog

- **`skills/arch-improvement-plan/`** (new): incremental architecture improvement: find boundaries, plan the migration, emit PRD plus tasks. Ported from a private runtime: no machine path, no bot
  name, no model id, and the capabilities it names are the general ones. Chinese note: 增量架构改进：划边界、给迁移计划、产出 PRD 与任务.
  Targets `runtime-agnostic`; areas `software-development`; kind `entry`.

## 2026-11-11 — `github-repo-management` joins the catalog

- **`skills/github-repo-management/`** (new): clone, create and fork repositories; manage remotes and releases. Ported from a private runtime: no machine path, no bot
  name, no model id, and the capabilities it names are the general ones. Chinese note: 克隆、创建、fork 仓库；管理 remote 与 release.
  Targets `runtime-agnostic`; areas `software-development`; kind `mechanism`.

## 2026-11-11 — `github-code-review` joins the catalog

- **`skills/github-code-review/`** (new): review a pull request: read the diff, post inline comments through gh or the REST API. Ported from a private runtime: no machine path, no bot
  name, no model id, and the capabilities it names are the general ones. Chinese note: 评审 PR：读 diff，用 gh 或 REST 发行内评论.
  Targets `runtime-agnostic`; areas `software-development,work-management`; kind `mechanism`.

## 2026-11-11 — `design-an-interface` joins the catalog

- **`skills/design-an-interface/`** (new): sketch a software interface or public API: signatures, OpenAPI snippet, usage examples. Ported from a private runtime: no machine path, no bot
  name, no model id, and the capabilities it names are the general ones. Chinese note: 设计软件接口或公开 API：签名草稿、OpenAPI 片段、用法示例.
  Targets `runtime-agnostic`; areas `software-development`; kind `entry`.

## 2026-11-11 — a run that never wrote a lock read as running forever

- **`skills/goal-driven-delivery/scripts/gdd.py`, `scripts/delivery-state.py`**: `omp-run.sh` records
  `pid` and `tmux` in `state.json` but writes no `lock` file, so `read_lock()` found nothing, the
  recorded `state: running` was trusted as-is, and a run that had already died kept reporting
  `running` until the 6h deadline — blocking the next stage. `effective_state()` now falls back to the
  launcher identity in `state.json` (`recorded_lock()`), in both the CLI and the state reporter.
- **`scripts/tests/run-gdd-selftest.sh`**: new case for a run with a recorded pid and no lock file;
  it must read `stale lock`, not `running`. Both scripts carried the same gap, and the new test caught
  the second copy.

## 2026-11-11 — the same shell expansion, one file further

- **`skills/skill-library-curation/references/skills-cli-installs.md`**: the provenance snippet passed
  `${SKILLS_HUB:-~/.agents}` into a quoted heredoc, so Python received the literal string and
  `expanduser()` could not make it a path — the verification command raised `FileNotFoundError`. The
  snippet now reads `SKILLS_HUB` from `os.environ` with the same fallback as the script it documents.

## 2026-11-11 — a skill library path that is not one machine's path

- **`skills/skill-library-curation`**: the shared skill store was hardcoded to `~/.agents`, so the skill
  only told the truth on the machine that wrote it. `SKILLS_HUB` (store), `SKILLS_ROOT` (what the runtime
  loads) and `SKILL_RUNTIME_CONFIG` are now documented in a Configuration table that points at the porting
  contract instead of restating it.
- **`scripts/upstream-freshness-check.py`**: `DEFAULT_LOCK` reads `SKILLS_HUB` from the environment and
  falls back to `~/.agents`. The previous value was `os.path.expanduser("${SKILLS_HUB:-~/.agents}/...")` —
  a literal string, so the documented default never applied.
- **`references/skills-cli-installs.md`**: provenance paths follow the same key.

## 2026-11-11 — the failure modes of a long stage run

- **`skills/goal-driven-delivery/references/run-failure-modes.md`** (new) collects five rules, each from a
  run that actually failed: a test must never be able to kill the process under test (`tmux kill-server`
  killed the stage that ran it); a hermetic test can pass for the wrong reason when the developer's machine
  has the binary it promised to stub; a crashed run silently blocks the next stage and deleting its `lock`
  does not clear it — recover with `<adapter> result <run>`; catching a broken sink is not enough when the
  interpreter still exits non-zero into a `pipefail` pipeline; and a recorded measurement whose producer and
  validator disagree is not evidence.
- `SKILL.md` links the new reference from the phase section.

## 2026-11-11 — a run log with a ceiling

- **`skills/goal-driven-delivery/scripts/adapters/events-writer.py`** replaces `tee` in the
  launcher's event pipeline: stdin lines are passed to stdout unchanged (the terminal keeps the
  whole stream) and retained in `events.ndjson` under a bound. Under the cap the file is
  byte-identical to the input; over it the file keeps the first lines (≤ 64 KiB, the session event)
  plus the most recent lines, with exactly one
  `{"type":"truncated","dropped_bytes":N,"dropped_lines":M}` line at the splice point. A sidecar
  `events.stats.json` carries `total_bytes`, `dropped_bytes`, `dropped_lines`, `retained_bytes` and
  `session_id`; the session id is also written atomically to `session.id` as soon as the event
  arrives. `OMP_RUN_EVENTS_MAX_BYTES` sets the bound (default 8 MiB); unset, empty, non-integer or
  non-positive values warn on the run's `stderr.log` and use the default, never unbounded. The
  writer exits 0 on truncation, file failure or a broken terminal pipe, truncates its log on start
  like `tee` (a replay in the same run directory replaces the stream instead of mixing two), and
  the `start` hint uses `tail -F` because compaction replaces the inode.
- **`adapters/omp-run.sh`** copies the writer into each run directory, pipes the agent through it
  under `pipefail`, seeds `session.id` for `--resume`, and recovers the session id from that sidecar
  first (scanning the first 64 KiB of the log only when it is absent). `state.json` and `status`
  report `events_bytes` (retained), `events_bytes_total`, `events_truncated` and
  `events_dropped_bytes`; `events_bytes` is no longer mistaken for the stream length.
- **Generated `finalize.py`** skips the marker rather than counting it, takes the session id from
  `state.json` → `session.id` → the retained stream, and labels stream-derived counters
  (`tool_calls`, `turns`, `cost_usd`) partial via `tool_calls_partial`, `turns_partial`,
  `cost_partial` whenever the stream was truncated. Run directories without a sidecar finalize as
  before, with zero truncation and totals equal to the retained file.
- **`references/transport.md`** states the four `events_*` fields the launcher contract now
  requires and adds the adapter-testing rule: a stage run is itself hosted in tmux, so tests use a
  stub `tmux` or an isolated socket and never `kill-server` / kill a session they did not create.
- **`tests/run-gdd-selftest.sh`** adds 21 checks: under-cap byte-identity, a replay replacing the
  log, over-cap head + one marker + tail arithmetic, invalid-cap fallback, a closed-terminal case
  (the writer exits 0 with a bounded, valid file and no shutdown re-raise when the reader goes
  away mid-stream), and an end-to-end stub-agent/stub-tmux run covering `tail`, `status`, `finalize`,
  terminal completeness and session recovery when the session event lies beyond the 64 KiB log
  head. Every adapter invocation that can reach tmux carries the stub `PATH`. Selftest 83/83.
- **Measured.** A stub agent emitted 33,249,020 bytes (240,003 lines) into the default 8 MiB cap:
  the run retained 8,453,877 bytes, dropped 24,795,212 bytes in 179,171 lines, kept a 65,405-byte
  head whose first line is the session event, and wrote one marker
  `{"type":"truncated","dropped_bytes":24795212,"dropped_lines":179171}`; the run directory is
  8,475,959 bytes against 33,249,020 for today's `tee` log, and the first 33,249,020 bytes of the
  pane were byte-identical to the input (sha256 `6e924715…`). A direct writer run at cap 262,144 on
  2,749,019 input bytes retained 327,426 bytes (≤ cap + 65,405 head), dropped 2,421,660 bytes, and
  its `state.json` four `events_*` fields matched the sidecar.
- `VERSION` 0.1.33, mirrored into every `SKILL.md` by `python scripts/version.py bump`.

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
