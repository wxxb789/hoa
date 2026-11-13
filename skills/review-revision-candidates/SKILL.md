---
name: review-revision-candidates
description: >-
  Run a revision round on a candidate a reviewer rejected: re-read the governing files at the
  start of the round, treat the numbered list as the entire change set, and deliver bytes plus
  anchors rather than prose about the rejection. Use when a reviewer returns a patch, draft or
  page edit as REJECTED with items to fix. Not for open-ended rewrites or for reviewing someone
  else's work.
metadata:
  version: "0.1.54"
  areas: "work-management"
  targets: "runtime-agnostic"
  summary: "run a rejected candidate's revision round: the numbered list is the whole change set"
  summary_zh: "被驳回候选的返修轮：编号清单就是全部变更集，交的是字节不是辩解"
  kind: "mechanism"
---

# Revision rounds on a rejected candidate

Use when a reviewer returns a candidate (patch, draft, page edit) as REJECTED with a numbered list and
asks for `vN+1`, and the tree must stay untouched while that happens. The deliverable of a revision round
is bytes plus anchors, never prose about the rejection.

## 1. Re-read the governing files at the start of every round

- The review/request file is **amended in place between rounds**: status line, verified-evidence tables,
  and the revision advice all change. A plan built on the earlier read is stale, and arguing against a
  withdrawn instruction is the fastest way to lose the round. Read the review file, the frozen request,
  and that directory's evidence/ledger files again before editing.
- Confirm the baseline has not moved: `git rev-parse --short HEAD`, then check the targets are still clean
  (`git diff --stat -- <paths>`). Peers publish during the round; a patch verified earlier may no longer
  apply.
- Note whose working-tree changes are present before you report anything about the tree. A dirty
  `git status` under the reviewer's own records directory is theirs, not yours; say so explicitly rather
  than letting your "repo untouched" claim look false.

## 2. Treat the numbered list as the sole change set

- Every numbered item is a gate; nothing adjacent gets fixed on your own initiative, however obvious.
  Out-of-scope improvements cost a round and read as not listening.
- Delete hunks the review excluded even when they look harmless — metadata fields (`updated:`,
  `last_accessed:`) are commonly excluded in candidate rounds. Do not argue for them; report that they
  were dropped and that the rest does not depend on them.
- Convert each item into something you can grep for afterwards: the banned phrase, the required sentence,
  the mandatory locator.

## 3. Versioning: the rejected candidate is immutable

- Build `vN+1` from pristine copies of the target files, in scratch, and write new files
  (`vN+1-<name>.patch`, plus the edited whole pages). Never overwrite or "fix" the rejected patch: the
  reviewer may hold its bytes, and an in-place edit destroys the ability to compare versions.
- Apply edits as exact unique-anchor replacements, asserting each anchor occurs exactly once and writing
  only after every replacement matched (all-or-nothing). A partial application produces a candidate that
  looks right in the diff you read and is corrupt where you did not look.
- Produce diffs with stable labels so they apply at the repo root:
  `diff -u --label a/<path> --label b/<path> <pristine> <edited> > vN-<name>.patch`.
- Per version, report **numstat and `git apply --check`** run from the repo root against current HEAD. A
  clean apply is a structural pass only — say so; never present it as content acceptance.

## 4. Pre-resubmit self-review

- **Grep the new candidate for every phrase the review banned and for its softened variants.** Reviewers
  reject a conclusion, not a sentence: a rewrite that trades "is closed" for "is effectively closed" or
  "no longer" reintroduces the same over-claim. Check the inverse direction too — a banned "never X" is
  usually re-smuggled as "only if Y".
- **Downgrade cross-caliber inferences to the observation the evidence supports.** A later, differently
  defined measurement does not retire an earlier one: state the new dated value with its measure, keep the
  older figure with its own date and source, and say the definitions are not aligned instead of ranking or
  converting them.
- **Do not relabel inherited numbers to make them comparable.** Preserving an earlier team's figure "as
  headcount" is itself an unverified definition claim. Mark it prior/attributed, name what is unverified,
  and refuse the conversion.
- **Absence findings need the broader search before they ship.** Search the abbreviation and the full
  phrase, the section number and the subject matter; then disclose a found counterexample and scope the
  limit to the inspected versions and dates. "Not in the version I read" is the claim; "not in the law" is
  not yours to make.
- **Attribute access failures to the run, not the resource.** Write "this client, this date, this path
  returned 403", never "the source is unavailable" or "the channel is closed"; and keep the four things a
  visibility question really contains separate (index/link state, access gate, alternative public copies,
  whether the document was ever filed or required).
- Re-check the mechanical leftovers: no excluded metadata hunk, no forbidden phrase, valid frontmatter
  (`yaml.safe_load` on the block), and a diff line count that matches what you report.

## 5. Deliver: bytes plus an anchor table, not a report

One reply carrying:

1. Paths and per-file numstat + apply-check result, plus the baseline SHA they were built against.
2. A short mapping "review item N → what changed", quoting the new sentence fragment, so the reviewer can
   verify without opening the patch.
3. An evidence table, one row per load-bearing claim: **claim → source URL and exact version →
   figure/section/line locator → short verbatim quote → caliber and status limit** (proposed vs enacted,
   authorized vs actual, aggregated vs per-unit).
4. What stayed unresolved, named as unresolved, with the reason the search could not settle it.
5. The scope statement: not applied, no write lease taken, no metadata or adjacent files touched, and what
   the reviewer must decide or grant next.

Do not restate the review back at the reviewer, and do not send an acknowledgement between rounds — the
next message is the candidate.

## Pitfalls

- Editing the rejected patch in place, then losing the ability to show what the reviewer's bytes were.
- Fixing a nearby defect the review did not ask for; the extra hunk becomes the next rejection.
- Resubmitting a banned conclusion in softer words because the grep only matched the original phrasing.
- Presenting a stricter or newer measure as a refutation of an older attributed figure from a different
  definition, or silently reconciling the two.
- Turning a string-search zero into "the provision does not exist" instead of "not in this version".
- Recording a 403 as an enduring property of the source so later rounds inherit a false blocker.
- Reporting apply-check success as if content had been accepted.

## Supporting files

- `scripts/candidate_diff.sh` — build `vN` patches from pristine vs edited copies with stable labels, then
  print numstat and run `git apply --check` from the repo root.
