# Delivery checks

Read before verifying any handoff. Use the actual worktree and artifacts, not
the sender’s receipt or the write state reported by its harness.

## Verify from the diff, not from the receipt

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
9. **Read the diff for meaning.** A green suite and an in-scope path set still pass these defects, so
   look for each class in the changed lines:
   - a default that fails open: a policy that allows when a field is absent, or an allow list a later
     field can widen;
   - a state the code cannot leave: an unknown or blocked result that neither retries within a
     budget nor stops loudly;
   - a check that rejects every normal input, such as a smoke gate that fails on every real pack;
   - a deleted comment that carried a constraint;
   - a "simplification" that adds branches, parameters or indirection.
   Send each back with the line and the input that exposes it.
10. **Size the independent review to the change.** A small mechanical or text-only diff (moves, a scoped
   one-defect fix, docs) is accepted on steps 1-9 and your own gate run; a second reviewer adds little.
   New gate, policy or validation logic, or a large diff, gets an independent reviewer asked which guard
   can be deleted with the suite still green. A green report that even flagged its own spec gaps still
   carried four such defects in one ~900-line gate change.

## Re-derive every number that the deliverable depends on

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

## Pitfalls

- Treating "both fixes done, verified" as the verification.
- Quoting the earlier "clean tree" after a teammate has written into it.
- Accepting a line count without checking what the second hunk is: a 17-insertion diff means the
  appended block *and* the edited line, and the edited line is the one that needs reading.
- Reporting the population you were shown instead of the population that exists.
- Re-deriving a tool's ratio over your own glob, then calling the mismatch a finding against the tool.
- Accepting a green test count as proof a tool works, when the tests never touch the path you will run.
  Read one case before trusting the suite; a hermetic fake of the external command (a stub on `PATH`
  that writes the expected state file) is what makes the act-path testable at all.
