---
name: delegated-work-acceptance
description: >-
  Verify work a teammate or sub-agent reports as done — the artifact, the numbers, and the write
  boundary — before you accept it or pass it on. Use when a delegated batch, repair, report, corpus
  scan or handoff comes back "complete", when a sub-agent's summary must be turned into a ruling, or
  when deciding what to authorize and what to send back. Do not use for grading your own work, or when
  no artifact exists to inspect.
metadata:
  version: "0.1.31"
  areas: "work-management,software-development"
  targets: "runtime-agnostic"
  summary: "verify a delegated \"done\" against the artifact, the re-derived numbers and the write boundary"
  summary_zh: "验收被委派的交付：核对 artifact、重算关键数字、检查写入边界"
  kind: "mechanism"
  consumes: "work-report"
  produces: "acceptance-verdict, scope-seal"
---

# Delegated work acceptance

A teammate's completion message is a claim, not a delivery. This skill is the pass that decides whether
to accept it, and it is the same pass whether the work is a repair, a report, a corpus scan or a writing
handoff.

## 0. Know what acceptance means here

Acceptance has two halves: **the artifact matches the claim**, and **the change stayed inside the
sender's write surface and out of the reserved lanes**. Both are verified by you. Nothing the teammate
says about its own verification transfers — it is a witness, not evidence.

Before you answer, re-open the role contract: your own write list, the sender's write list, and what
needs operator approval. Your job in this loop is verify + rule + route, almost never repair.

## 0.5 Dispatching the bounded batch (the other half of the loop)

Acceptance presupposes a bounded dispatch. Send the work as a request FILE, not a chat prompt, so the
sender works from a fixed scope and the acceptance criteria exist before the work starts:

- Request file in the owning task dir (`<task>/<batch>-request.md`): Context (exact files to read) →
  Scope (explicit write surface, named exclusions, "no scheduled-job / config / profile / repo write"
  clauses, rollback expectations) → Deliver (numbered, each item with its gate and the real baseline
  numbers) → output artifact requirements (`result.md`, backups, diffs, ledger).
- Dispatch it headless and in the background — it runs for minutes; use the transport your harness
  provides (see `omp-headless-orchestration` for the OMP path) and keep the log plus the produced
  artifacts in the task dir.
- A line like `open terminal failed: not a terminal` is the CLI failing to open an interactive terminal
  under a headless flag — not a run failure. Judge by exit code and produced artifacts.
- A clean process exit is itself only a claim: acceptance still re-runs the gates itself (§1.5).

## 0.6 The working increment is a path set, not a document hash

Review dispatches at a commit range, so uncommitted work is invisible to it. Bind the tree to a
recorded scope with `scripts/worktree-scope.py`:

1. `snapshot` when you take the tree: HEAD plus every dirty path (mode and content digest). Those
   paths are the baseline, not part of the increment.
2. `diff` after the work: `changed_paths` are the increment, `excluded_preexisting_paths` were
   already dirty and are untouched, `overlapping_paths` had two writers — stop and ask the operator
   which one owns each path before going further.
3. `seal` once the review passes. `--accept-overlap` is an explicit operator decision and is
   recorded, so the fact survives into the record.
4. `verify` after committing and before landing: exit 1 names every `added`, `modified` or `removed`
   path, so a post-review edit cannot ship unexamined.

The oracle is the path set, not a content hash of the report: a document can be rewritten without
changing the increment, and a one-line edit can change everything. Put the same path set and
`scope_sha` in the acceptance verdict and the PR body. State resolution: `--state-file`, then
`$HOA_SCOPE_STATE`, then `$XDG_STATE_HOME/hoa/scope`, then `~/.local/state/hoa/scope`; one JSON file
per repo+label.

## 1. Verify from the diff, not from the receipt

Order matters; each step decides whether the next one is worth doing.

1. `git status --short` — what changed, and what is untracked? An untracked report or receipt is part
   of the delivery whether or not it was mentioned.
2. `git diff --stat` — do the insertion/deletion counts match the claim? A claimed "+15 lines" against
   a 17/1 diff is an honest mismatch to reconcile, not a rounding error. Do the hunks contain only the
   regions it admitted touching?
3. Read the changed region in the file itself. The claim "blank line added before the header" is proven
   by the file, not by the diff hunk header.
4. For any format or encoding claim, count bytes. Newline discipline and separator counts are cheap and
   teammates get them wrong: count CRLF vs bare LF, count blank lines before each section marker, count
   entries the parser actually yields.
5. Re-run the repo's gates yourself and quote the real numbers. A gate the teammate reports as "rc=0"
   is unverified until your own run prints it.
6. For a landing through the repo's own gateway, the JSON is still a claim: confirm `git rev-parse HEAD`
   equals `origin/main` and `git ls-remote origin refs/heads/main`, and that `git status --porcelain` is
   empty at HEAD. A "pushed: true" line with a local-only commit is the failure this catches.
7. Re-check `git status` at the end. Their write landed in the tree you called clean earlier, so any
   "clean tree" sentence from earlier in the session is now false and must not be repeated.
8. **When the delivery is a tool or script with its own test suite, verify COVERAGE before the count.**
   `selftest: 13/13 ok` is compatible with the real invocation crashing on a variable typo: the suite
   stopped at `--dry-run` and never reached the launch path. Ask which path the cases exercise, require
   the path you will actually use (launch/act, the failure path, the flag you rely on) to have a case,
   and require a mutation check — revert each fix and confirm the suite goes red. A suite that still
   passes with the fix reverted is decoration, not evidence.

## 2. Re-derive every number that the deliverable depends on

- Use the checker's own population semantics rather than inventing a new glob. Inspect top-level IO
  before importing its enumerator: audit modules can create directories, write reports or launch work
  at import time. Import only a verified side-effect-free module; otherwise use its persisted inventory
  or a read-only adapter with matched exclusions and composite scope keys. Print both denominators and
  reconcile the exact key sets before accepting ratios.
- Diff the new snapshot against the previous snapshot of the same kind. Dated reports (lint, health,
  audit) exist to be diffed: it is how "no findings" resolves into "identical except two new review
  candidates". Do this before repeating a "nothing found" line.
- Resolve every identifier before repeating it. Cited stems, slugs and path fragments that do not open
  are worse than no citation: check each against the tree and publish the resolved path when
  correcting.
- Count the population before trusting a scoped list. "N orphan pages" is a slice; recompute across the
  whole corpus, group by type, and report the population too — the unreported majority is usually the
  actual finding.

## 3. Judge a corpus or graph finding on its mechanism

When the delivered finding is about a knowledge corpus, three of these decide most cases:

- **Duplicates vs a missing hub.** Before accepting "page A duplicates page B": compare sizes (4:1 is a
  hub and a summary, not a duplicate), count inbound **and** outbound links on both, then check whether
  the whole sibling family is unlinked too. A family with no hub looks duplicated, and merging two
  orphans produces a bigger orphan. The cheapest fix is the link that was never made.
- **Fields with no writer.** Before accepting "N pages lack field X", grep every script for the field.
  All hits read, none write ⇒ the field has no write path, its values are backfill, and every rule
  keyed on it can never fire. Report that as the defect; a page-count of missing values reads as
  routine hygiene and gets deprioritised forever.
- **Coverage declared by a fixed type list.** When a catalog enumerates only legacy types, new canonical
  types are counted in totals yet listed nowhere. Test empirically: for each page of the new types, does
  its slug appear in the generated index? Report `0 of N`, not the summary counts.

## 4. Keeping the change inside the boundary

- Authorize the bounded, meaning-preserving subset and name the exclusion in the same breath. A wikilink
  conversion between pages that already mention each other is mechanical and reversible in one revert;
  a new sentence, a frontmatter `confidence`/`supersedes` edit, a merge, or a code change is not — those
  stay with the operator. "Do the mechanical part; these four stay put" gets work moving without
  spending the operator's ruling on it.
- Ruling on the sender's own house convention is yours when it is reversible in minutes and touches no
  knowledge. Decide it, say why, and say what you are not deciding (a physical reordering of a
  provenance file, for example, buys nothing when the parser is order-independent and rewrites an
  append-only record).
- Two teammates' surfaces can collide in one tree: end every round with the exact list of uncommitted
  paths and whose they are. Commit and push stay with the operator.
- **A worker blocking on scope is doing its job — compare its list with the approved plan's manifest
  before treating it as a stop.** The card you wrote can be narrower than the plan it executes (a
  garden-only card against a vault-wide link rewrite), in which case the paths the *manifest* lists are
  already in scope and authorizing them is not an expansion; anything the manifest does not name is a
  new ruling. When you authorize, name the path classes exactly, require a fresh pre-execute backup (an
  older archive predates later drift and is not a rollback unit), and restate the reserved lanes that
  stay closed.

## 5. Correct the deliverable's own report when it is imprecise

A handoff report becomes next month's diff baseline, so its errors are future work: wrong denominator,
an unresolvable citation, an understated population. Send them back as numbered corrections with the
correct value already supplied — the sender fixes its own file, and you keep the ruling on the
substance.

Before closing a revised handoff, compare it with the latest operator/reviewer ruling, not only the
earlier correction request. Designate one final decision artifact and explicitly supersede conflicting
draft options, counts and approval manifests; an old draft must not become an execution payload. Label
static coverage, design acceptance, implementation, payload effects, scheduled-worker proof and
delivery proof separately — a passing static gate proves neither deployment nor real behavior.

## Output shape

1. What reproduced, with the numbers you computed (not the ones quoted back).
2. What did not, correct value first, in a numbered list the sender can act on.
3. What you authorized and what you explicitly withheld, with the revert unit.
4. Current uncommitted path list and what still needs the operator — as a numbered choice list.

Plain text, one point per line, no decoration: the reader may be on a phone.

## Pitfalls

- Treating "both fixes done, verified" as the verification.
- Quoting the earlier "clean tree" after a teammate has written into it.
- Accepting a line count without checking what the second hunk is: a 17-insertion diff means the
  appended block *and* the edited line, and the edited line is the one that needs reading.
- Fixing the finding yourself because it is two lines. The sender owns the path; a fix from the wrong
  surface is an unaccounted write, and the next audit reports it as one.
- Reporting the population you were shown instead of the population that exists.
- Re-deriving a tool's ratio over your own glob, then calling the mismatch a finding against the tool.
- Escalating a reversible house-convention question to the operator and calling it a decision item.
- Accepting a green test count as proof a tool works, when the tests never touch the path you will run.
  Read one case before trusting the suite; a hermetic fake of the external command (a stub on `PATH`
  that writes the expected state file) is what makes the act-path testable at all.
