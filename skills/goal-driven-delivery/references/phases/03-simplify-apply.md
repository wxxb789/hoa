# Phase 3 — simplify, then apply

1. Dispatch `simplify`: report only, standalone mode — never a pipeline mode that applies silently.
2. Read the report; dispatch `apply` with the accepted numbers and a one-line reason per rejection.
   A bare "apply all" hands the skill permission to delete tests and evidence.
3. Accept: invariant fixes, misleading names, duplicated fixtures, tests that would still pass with
   the semantics swapped. Reject: deleting a clause-pinning test, deleting an evidence row or a
   disclosed measurement, unmeasured micro-optimizations, sentinel encodings that break
   default-value semantics.
4. **A "dead / unreachable / unused" finding needs mechanical evidence, not a reviewer's confidence:**
   a reference search (zero call sites) or an instrumented run proving the branch is never taken. An
   unevidenced deletion of a defensive guard is how a contract check disappears. Conversely, an
   unreachable branch that cannot run is dead code and keeping it "just in case" is the failure —
   decide, and record which way.
5. **A finding that says the record's rule and the code disagree is a correctness defect, not
   style.** The goal file is the contract: fix the code and leave the measured rows alone. A comment
   or test name claiming a rule the code no longer implements is the same defect wearing a comment.
6. **A `Delete` finding that removes an inert allowlist grant is worth taking** — a class or
   attribute the policy already drops is how the next change re-opens a channel by accident.
   Conversely, suspicious of consolidating duplicated styling across conditional asset graphs: those
   copies are usually deliberate.
7. **Name the rejected numbers in the apply prompt**, so the agent cannot "improve" them back in.
   When an accepted finding changes line or test counts, every recorded count must be re-derived from
   the tree or a real suite run — never adjusted arithmetically.
8. If the accepted set touches measured consumers, re-run the measurement harness — not just tests.
