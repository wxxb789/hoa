# Phase 4 — review, then fix

1. Dispatch `review` (report only) only after the simplify fixes are applied, so the reviewer reads
   the tree that will ship. The stage range is `origin/main..HEAD`, so **commit the agent's stage
   output before dispatching the next stage**: `gdd.py` does not refuse a dirty worktree, and
   uncommitted apply fixes are invisible to the reviewer's diff and one stray `git checkout` from
   gone. Commit, rebase onto `origin/main` when the branch has fallen behind, then confirm the
   `--dry-run` range covers exactly the whole increment.
2. Grade by what is FALSE, not by the reviewer's severity label: a P2 that makes documentation state
   something untrue outranks every tidy-up. Gaps that pin a documented promise are real; gaps that
   mirror an internal shape are not.
3. Dispatch `fix` with a per-finding table requirement and an explicit reason for anything judged
   invalid. A silent skip reopens next round — that is why the table is mandatory.
4. **Reproduce every finding yourself before dispatching it**, inside the repo, and give the fixer the
   measured before/after rather than a description. A finding that is merely consistent with documented
   semantics is still unverified, and a plausible false positive costs a 20–40 minute agent round.
5. **Classify before dispatching: regression or pre-existing.** If this goal added one of two paths that
   now disagree about the same input (producer vs renderer, writer vs reader, resolver vs sanitiser), it
   is in scope. If the divergence is decided in the predecessor's completion record, it is not a defect —
   say why in the reply instead of dispatching it.
6. **When two rounds hit the same class, the third dispatch changes the mechanism** — collapse to one
   function, one uniform rule, or drop the path that re-derives the value. Demand a property test over a
   generated matrix instead of hand-picked rows, and require the prompt to prove no second copy of the
   rule remains (`grep` plus `file:line`). Cover every field and every authored shape the new function
   touches in that same dispatch, not just the one the finding named.
7. **A residual limit already recorded does not discharge a finding.** When the reviewer names exactly
   the case the goal record lists as a known limit, that limit is unpaid debt: implement the resolution
   or make the omission explicit in code, then rewrite the limit. "Documented, therefore out of scope"
   keeps a known-wrong value shipping.
8. **Review for semantic widening, not style.** Before merging two byte-identical call sites, write down
   per call site the grant it consumes, what it may touch, and its destination; if any differs, share
   only the mechanics (parsing, query) and keep two decisions. After splitting a predicate, re-assign a
   rule to every caller — any caller left on the old helper silently inherits whichever rule remained.
