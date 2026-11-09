# Project profile template

Copy to `references/profiles/<repo>.md` and fill every section. A profile is **deltas only**: the
protocol lives in `SKILL.md`, generic language/build mechanics live in their own skill, and prompt text
lives in `references/stage-templates/`. If a section does not apply, write `none` — do not restate the protocol.

Target length: 60–120 lines. A 500-line profile means protocol facts leaked into it.

## 1. Repo and stack

Path, language(s), package manager, runtime version pin, test runner, linter/formatter. Note the
heaviest local step (it decides what must be serialized).

## 2. Where the contract lives

Frozen goal files? Issues? A design doc? Name the index file that decides what is next, the numbering
rule (including superseding and archiving), and where a NEW contract document may go — some repos
forbid `docs/plans/` for new work. State the goal-close ritual (what must move/update in the same commit).

## 3. Goal granularity in this repo

How big is one goal here: a single agent run? A PR? Part of a series? If the repo uses series
(lettered goals, phases, epics), state the **series order, prerequisites, and what a `-final` /
review goal must check** — and that a `-final` reuses the lettered goals' evidence instead of redoing
the implementation. Also state the repo's "safe to merge alone" invariant if it has one.

## 4. Gate commands, in order

Exact commands, and which of them CI repeats. Flag any gate that is a subset of the truth ("CI runs
only the docs gate; green CI proves nothing about tests"). Note prerequisites (browser binaries,
external scanners, a prior build) and what a wrong-prerequisite failure looks like — that is the
difference between "gate red" and "environment broken".

## 5. How to read the gate

Passing line, what the counts mean, tolerated warnings, and what must be reported verbatim (test
counts, coverage of pinned surfaces, inventory deltas).

## 6. Frozen surfaces

Public API baselines, generated docs/directories, protocol manifests, lockfiles, schema snapshots.
Name the command that proves the surface did not move, and what a behaviour-preserving pass must show.

## 7. Branch, commit and PR conventions

Branch naming, squash vs merge commit, commit title style (`git log --oneline`), whether the plan ships
inside the feature commit, and what the PR body must contain.

## 8. Machine review bot

Which bot (`chatgpt-codex-connector`, none, other), how its verdict is encoded (marker vs prose — the
marker string is `pr-merge-check.py --marker`), how to trigger a re-review, and what blocks merge. If
the repo has no bot, say so and pass `--allow-no-machine-review` explicitly — that changes Phase 6.

## 9. Evidence conventions

Where the evidence record lives, what counts as a fair baseline, what must be measured twice, how a
negative decision is recorded, and any repo-specific measurement trap (e.g. a helper that must be used
instead of a `Count()` that consumes the enumerator).

## 10. Release and deploy

How a merge reaches users (npm publish, site deploy, action pin bump). Name the step that is
IRREVERSIBLE and therefore needs owner confirmation — never fold publishing into an agent run.

## 11. Access and secrecy

Anything that must never be committed (private paths, personal notes, credentials) beyond the usual,
and whether the repo is public (it changes what prose is allowed).
