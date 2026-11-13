---
name: gdd-closeout
description: >-
  Close a phase: enumerate the task surface and reconcile the record, the index, the published release
  and the thing users actually load, then rank the closeout list so one decision clears the phase. Use
  when a goal series ends and before the next phase's goals are written on top of the drift. Do not use
  mid-goal, or as a substitute for one increment's merge gate.
metadata:
  version: "0.1.49"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "enumerate the task surface, reconcile record/index/release/production, output a ranked closeout list with one decision"
  summary_zh: "清点任务面，对账记录/索引/发布/生产四层，输出带唯一决策点的收尾清单"
  kind: "entry"
---

# Project phase closeout

A phase is not finished because its features pass. It is finished when the record, the index, the
published release and the thing users actually load all say the same thing. This is the sweep that
finds where they disagree, before the next phase's goals are written on top of the disagreement.

## When to Use

| You hear | Do |
|---|---|
| "anything left undone?", "还没做的部分", "don't leave tails" | full sweep, then the ranked list |
| "before I set up the next phase / next goals" | sweep first: the next phase inherits every tail |
| a phase whose goals are all marked complete | reconcile record, index, release, production |
| a deploy pipeline whose pin you have never resolved | steps 3–4 only, and say what is unproven |

Not for auditing one report's numbers (that is report-claim-audit) or accepting a teammate's delivery
(delegated-work-acceptance).

## Order of work

1. **Enumerate the task surface from its own bookkeeping, never from memory.**
   - Every status line in the goal/task files (`grep -m1 '^Status:' docs/goals/*.md`), and the
     completion archive's table — count rows, do not skim prose.
   - Open PRs and issues (`gh pr list --state open`, `gh issue list --state open`).
   - Live delegated runs (run dirs, job ids, cards): in flight is not a tail, but it belongs on the
     list as in flight.
2. **Classify each item**: done-and-recorded / done-but-unrecorded / not-done /
   deliberately-not-doing. Only the middle two are work; say which is which.
3. **Reconcile four layers against reality.**
   - *Record*: the goal doc's own numbers and decisions vs what was actually measured and decided.
   - *Index*: the list and archive tables vs the files present and their status lines.
   - *Release*: tag/registry version vs the changelog's Unreleased section.
   - *Production*: what the deploy pipeline actually builds with — resolve the pinned
     generator/tool commit or version to a date and count the commits behind it.
4. **Check that post-deploy verification exists.** "Deployment succeeded" is not "the deployed
   artifact works": nothing checks that the shipped assets are reachable, that the runtime boots, or
   that the site's own headers/compression rules are honoured by the host that serves it.
5. **Housekeeping**: merged-but-undeleted branches (local and remote), stale worktrees, build
   artifacts left inside the repo.
6. **Report** in the shape below.

## Rules that carry the value

- **An index is a cache, not a source of truth.** Squash merges, archive moves and hand-edited tables
  leave prose behind that contradicts the files; list the files first, then read the index, never
  the reverse.
- **The most expensive tail is production lagging the release.** A published package plus green CI
  proves the code; a deploy pipeline pinned to an older commit means the shipped features have never
  run for a real user. Resolve the pin to a date and a commit distance, and check whether any real
  content even exercises the new capability.
- **Host features are host-specific.** A headers/compression config in the repo describes what one
  platform does; fetch the live response headers to see what the platform in use really sends, and
  record in the docs which host gets which behaviour.
- **Anything proven only by gates is unproven in use.** Name it as such instead of counting it done.
- **Do not edit the repo while a measurement or benchmark run hashes its tree.** Those harnesses fail
  their own identity check on an unexpected edit and can void hours of work; queue documentation
  fixes behind the run and say so.
- **Close tails now, do not schedule them.** "Write the erratum", "fix the index", "delete merged
  branches" are minutes of work; turning them into a goal makes the next phase inherit them.
- **One decision per closeout.** Everything reversible is done on the spot; the single question is the
  irreversible or production-facing item (a deploy pin bump, a public release).

## Output shape

- Conclusion line first: is the feature surface complete, and what is the one structural gap — often
  that no scope document exists for the *next* version, so nothing defines "done" after this phase.
- Then numbered tails, each with the evidence path that proves it, ordered by cost of leaving it.
- Then the order of execution, naming what is blocked behind an in-flight run.
- Then exactly one numbered decision for the owner.

## Pitfalls

- **A fix in the generator is not a fix in the runtime.** When the phase's change lives in a template,
  binding or generator, the generated artifact on this machine is its own layer: re-materialize it and
  verify the rendered output, not only the source commit. CI sees the repo; nothing sees a profile or
  config that was never rebuilt — and hand-editing the rendered copy is a tail the next materialize
  silently erases. Fix the binding, re-render, then read the rendered file back.
- **A checker that skips the failing item is not green.** A drift script that prints an error and then
  `continue`s past that target never repairs it, and every later run repeats the same line while the
  summary reads as "handled". Treat *reported but skipped* as not-done: fix the input that made it skip
  (a name that resolves to nothing, a missing key), re-run, and only then trust the summary line.
- Counting a goal complete because its file moved into the archive while its index row stayed behind:
  the archive table is the second place that goes stale, not the first.
- Treating "the package is published" as "the site runs it" — resolve the deployment's pin.
- Reporting a gap without its evidence path, which the owner then has to re-derive.
- Auditing only the current phase: a superseded goal that still carries an obligation is a tail too.
- Fixing docs mid-run because the edit is "only markdown" (see the tree-hash rule above).
