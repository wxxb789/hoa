---
name: harness-engineering
description: >-
  Audit, restructure, and design harnesses — scheduled operational scripts, drift checkers,
  watchdogs, gated data pipelines wrapped around a repo or agent system. Use when helper scripts
  have grown past one screen, checkers are multiplying, or a harness subsystem needs a home.
  Not for one-off scripts, and not for application code that no scheduled check or gate runs.
metadata:
  version: "0.1.24"
  areas: "software-development"
  targets: "runtime-agnostic"
---

# Harness Engineering

Harnesses (cron-run operational scripts, drift checkers, watchdogs, gated data pipelines around a
repo or agent system) are engineered products, not scratch scripts. This skill covers how to
review, restructure, and design them to this owner's standards.

## When to Use

- "review / 重构 / 工程化 harness / helper scripts"、单文件脚本超长、检查器增殖
- designing a new harness home, consolidating checkers, deleting zombie dirs
- deciding where a harness subsystem belongs

## Owner's architecture principles (always-on)

1. **Self-containment**: every repo/system owns its harness. Never extract a repo's harness
   dependency into another repo or a shared library.
2. **Reuse boundary**: within one git repo, extract common modules and maximize reuse; across
   repos, zero dependencies — a similar feature gets a copy in each repo (expect little real
   similarity: each harness is purpose-designed).
3. **Engineering standard**: SOLID, real abstraction and modularity; functional style — less code
   for the same expression, data structures chosen for performance. Immutability is NOT required.
4. **No checks for checks' sake**: every check must bind to an owner DECISION ("this finding
   triggers which action?"). No defensive validation written out of caution. Git is the byte layer,
   declaration files are the intent layer; checks only align the two.

## Procedure

1. **Inventory and classify before judging.**
   - Line counts: `find <roots> \( -name '*.py' -o -name '*.sh' \) | xargs wc -l | sort -rn`,
     excluding `.venv`, `__pycache__`, backups, and task-archive dirs (process records, not harness).
   - Live surface: the scheduler's job listing (`cron list --all` for whichever scheduler owns the
     box) plus skill/repo greps — a script nothing references is dead code, not a disease to refactor.
   - Classify each cluster: drift checks / observability / domain data pipeline / gated execution.
     A domain pipeline (finance capture, report generation) is a TENANT of the harness, not a gate —
     keep it out of the checker framework.
2. **Reduce to root requirements.** Drift control has three faces — read-path checks, write-path
   gates, single delivery path — not three requirements. Observability is the delivery mechanism of
   drift control, not a separate pillar.
3. **Audit obligations, not just job names, deletion-led.** Produce a per-check keep/drop/relocate list
   with its bound owner decision and evidence. No decision → propose retirement with no invented successor
   report. Relocate only to a confirmed consumer/gate, not a hypothetical one. Drop invalid heuristics
   rather than moving them into a digest: zero use does not imply uselessness, upstream HEAD difference
   does not imply pinned-install drift, and prose-count/model-mention regexes are not declarations.
   A consolidation where every obligation survives is theater; fewer rare schedules is not a measured
   performance improvement.
4. **Design pure checks + a thin bounded runner.** Checks are
   `(declarations, live_state) -> findings[]`, zero IO; adapters acquire read-only state, and the runner
   owns finding cache/dedup/delivery/TTL. Keep config repair/plugin install/destructive maintenance outside
   periodic detectors. Audit helper IO, not flag names, before calling check/dry-run/JSON modes. Bound each
   step so one stall cannot hide other findings; dedupe stable identity/severity, not changing ages/dates.
   Each check names `intent_ref`, `decision` and `ttl`; validate registration at load time, not through a
   periodic checker-of-checkers. Notification state must be rebuildable from zero.
   Preserve independent execution, inputs and verdict ownership for producer/verifier boundaries; a mode
   flag or shared directory alone neither proves nor disproves independence.
5. **Restructure with a net-negative live-code budget.** Measure replaced reachable code and the
   proposed replacement, excluding rollback copies. Stage the replacement and fault fixtures, switch
   approved references coherently, then retire approved schedules without dual-run effects or coverage
   gaps; preserve rollback artifacts. Require healthy/silent behavior plus injected failure rejection,
   especially false-green paths. Do not invent a multi-week soak or repeated owner-read gate: use explicit
   acceptance criteria and report first scheduled proof separately. Roll back targeted definitions, not
   stale shared-state snapshots. A wrapper retaining every old check is not redesign.
6. **Keep the repo's own gates green at every step.** For vault writes that means the vault's own
   stack (unit tests + status/structure audit + markdownlint), run through its documented environment.

## Pitfalls

- **A symbol name is not a directory reference.** `reports.status` reads like a reference to a
  zombie `reports/` dir but resolved to `commands/reports.py`. Grep for the path AND trace the actual
  resolution (a validator's `SCHEMA_DIR = Path(__file__).with_name("schemas")` decides which
  same-named file is live) before deleting any "duplicate".
- **Two same-named files can both be live generations.** Diff them: the stale subset copy is
  deletable; the superset is live. Deleting by name match alone removes the wrong one.
- **`pytest` may not be installed in a harness venv.** Run tests the way the repo's sync script
  does (`uv run --project <harness> python -m unittest discover ...`), not by assuming pytest.
- **Never delete a checker without a timestamped backup** when its home is not a git repo, and
  never leave cron pointing at a deleted path — repoint cron in the same step as the migration.
- **Deleting a checker silently disarms an alarm.** Get owner sign-off on the kill list (one line
  per checker: name / bound decision / kill or keep / reason) before executing.
- **An external-reference audit must cover from-imports, not just attribute refs.** A splice
  audit that greps `module.name` misses `from module import name` — a test module kept importing
  moved names and unittest surfaced it only as a loader error. Grep both forms across the whole
  tests/ dir, and treat a DROP in the discovered test count as a hard failure: a `_FailedTest`
  import error replaces one module's tests with a single error entry, so "Ran 173" becoming
  "Ran 166 (errors=1)" means 7 tests vanished, not 7 skipped.
- **Line-splice refactors belong in a one-shot script, not hand-copying.** Assert each block's
  first line before extracting; verify seams with `ruff check --select F821,F401,F811` (F821
  catches missing imports the eye misses; E999 no longer exists in ruff); restore sources from
  git before each rerun instead of patching half-written output.
- **For hard architecture decisions, consult an external model as a second opinion** via an
  other-model-family CLI one-shot; prepend "You have NO tools" to the prompt so it does not claim
  to have inspected the tree.
- **Prove destructive retention/rotation logic with a live no-op run before its first real
  deletion.** Configure the rule against the REAL data so it must delete nothing (keep ≥ existing
  count): a zero-deletion run on live paths proves the marker/prefix selection a synthetic fixture
  cannot, and leaves nothing to roll back — the first real deletion then happens only after the next
  natural produce cycle. Restrict eligibility to an exact dir prefix plus a completion marker, and
  fail closed when no complete generation exists.
- **Test a "duplicated detector code" claim mechanically before designing the dedupe.** Compute
  normalized-line overlap between the claimed duplicates (strip comments/blanks/imports, collapse
  whitespace, drop lines under ~25 chars): an overlap of a handful of lines means the duplication
  does not exist — revise the budget criterion or enumerate a real consumer rewiring instead of
  shipping another patch batch; an extraction designed against imagined duplication cannot meet
  the line cap and trades working code for a number.
- **A commit gateway that prefix-matches `git diff --cached --name-only` against an allowlist rejects every
  non-ASCII path.** `core.quotepath` (on by default) escapes CJK filenames (`raw/\350\267...`), so a valid
  `raw/<中文主题>/_sources/<unit>` entry never matches and the landing is refused as "outside allowed paths".
  Fix the tool (`git -c core.quotepath=false ...` on every name-only call), not the caller: a repo-level
  `git config core.quotepath false` only helps this machine and other agents keep failing.
- **Read the porcelain columns before calling a rejected gateway's index dirty.** `git status --porcelain`
  is `XY path`: ` M path` (space in column 1) is an unstaged working-tree change — normal, nothing to clean;
  `M  path` is staged residue. Check the gateway's own rejection paths first: one that already runs
  `git reset` before raising needs no manual cleanup, and reporting "index residue" from a misread column
  sends the next agent to fix a non-bug. Reset manually only when column 1 is actually set.
- **A gate that only runs at full strength gets bypassed while drafting; split it.** Give scratch work a
  soft mode that keeps the load-bearing invariant (a tagged fact still needs a resolving anchor, a schema
  field still must parse) and drops the promotion ceremony (context binding, coverage thresholds, generated
  sections). Enforce the boundary in the helper — `--soft` rejects any target outside the scratch root and
  is mutually exclusive with the promotion-context flags — and document the split in the helper's README,
  or the soft flag quietly becomes a general bypass.
- **Fixtures prove the code path, not the wiring: drive one live end-to-end run.** Exercise the real writers
  in their real order (submit → digest → capture → gate → independent verifier) and park the artifact on a
  non-research surface (a maintenance record, a fixture-labelled source unit) so proving the pipeline does
  not pollute the corpus. Have a different role verify the record read-only, then fix what it flags — a
  verifier's first pass usually catches a classification error the builder rationalized.
