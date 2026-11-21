# Phase 3 — simplify, then apply

1. **Preflight the range before dispatching.** Skip the pass when it holds no human-authored code —
   documentation, prose, data, config, generated or vendored files, lockfiles — when the code change
   is mechanical (formatting, dependency bumps, lint-only fixes, renames), or when it adds or changes
   fewer than 30 substantive code lines. Count added or changed human-authored code outside tests;
   docs, data, config, generated files, lockfiles, fixtures and blank lines never count. A goal
   contract or project profile may set another threshold or require the pass anyway — resolve
   contract, then profile, then this default.
2. **Record the skip, never a fake run.** Append a `simplify` ledger row with an `exit=`-prefixed
   note — `--note "exit=not-run skipped: <reason>"` — as completion rows do, so the skip does not
   spend a round against the cap. Name the deciding rule (docs-only, mechanical, sub-threshold, or an
   override). Dispatch no agent and write no dispatch row for a pass that did not happen.
   **Correctness review still runs**: phase 4 starts from the current tree.
3. When the pass runs, dispatch `simplify`: report only, standalone mode — never a pipeline mode
   that applies silently.
4. Read the report; dispatch `apply` with the accepted numbers and a one-line reason per rejection.
   A bare "apply all" hands the skill permission to delete tests and evidence.
5. Accept: invariant fixes, misleading names, duplicated fixtures, tests that would still pass with
   the semantics swapped. Reject: deleting a clause-pinning test, deleting an evidence row or a
   disclosed measurement, unmeasured micro-optimizations, sentinel encodings that break
   default-value semantics. **The increment's proof tests are protected**: reject a finding that
   deletes, weakens, renames, moves, merges or rewrites one, or removes the test-only code it calls.
6. **A "dead / unreachable / unused" finding needs mechanical evidence, not a reviewer's confidence:**
   a reference search (zero call sites) or an instrumented run proving the branch is never taken. An
   unevidenced deletion of a defensive guard is how a contract check disappears. Conversely, an
   unreachable branch that cannot run is dead code and keeping it "just in case" is the failure —
   decide, and record which way.
7. **A finding that says the record's rule and the code disagree is a correctness defect, not
   style.** The goal file is the contract: fix the code and leave the measured rows alone. A comment
   or test name claiming a rule the code no longer implements is the same defect wearing a comment.
8. **A `Delete` finding that removes an inert allowlist grant is worth taking** — a class or
   attribute the policy already drops is how the next change re-opens a channel by accident.
   Conversely, suspicious of consolidating duplicated styling across conditional asset graphs: those
   copies are usually deliberate.
9. **Name the rejected numbers in the apply prompt**, so the agent cannot "improve" them back in.
   When an accepted finding changes line or test counts, every recorded count must be re-derived from
   the tree or a real suite run — never adjusted arithmetically.
10. If the accepted set touches measured consumers, re-run the measurement harness — not just tests.
