# Phase 4 — review, then fix

1. Dispatch `review` (report only) only after the simplify fixes are applied (or the pass was recorded as skipped), so the reviewer reads
   the tree that will ship. The stage range is `origin/main..HEAD`, so **commit the agent's stage
   output before dispatching the next stage** with
   `gdd.py commit --repo <path> --goal <id> -m "<subject>" --result <result.json> --no-push`.
   Uncommitted fixes are invisible to the reviewer's diff. Dispatch refuses pending output but
   allows unchanged baseline dirt. If main moved, reconcile and replay against a new baseline as
   described in [Phase 5](05-gates-pr.md). Confirm the `--dry-run` range covers the whole increment.
2. **Reuse the runtime's read-only reviewer first where it is installed.** The `review` stage
   template has the worker try `ce-code-review mode:agent` first, through its own runtime's skill
   discovery, on `${BASE_SHA}..${HEAD_SHA}` from a checkout clean at that head, with gdd's own
   report-only review as the fallback — and only when the invocation supports the declared no-peer
   boundary before it gets the diff. Let it settle and finish its documented recovery; accept the
   receipt only if it reports `status: complete` with an artifact path or run id, its reported base,
   head and scope cover the dispatched range, and no required coverage failed — an intentional
   depth/peer omission is not a failure. Retain the full receipt with the run and re-read every
   finding it produced. A missing skill, a failed or degraded run, an incomplete receipt, or a
   mismatched range is disclosed, and the fallback completes any materially missing coverage — a
   degraded receipt is not a clean review. No external or peer model receives the diff unless the
   project profile names that peer and the operator holds separate authority for that review run.
   This authoring-stage receipt never replaces the head-bound machine-review marker in Phase 6.
3. Grade by what is FALSE, not by the reviewer's severity label: a P2 that makes documentation state
   something untrue outranks every tidy-up. Gaps that pin a documented promise are real; gaps that
   mirror an internal shape are not.
4. Dispatch `fix` with a per-finding table requirement and an explicit reason for anything judged
   invalid. A silent skip reopens next round — that is why the table is mandatory.
5. **Reproduce every finding yourself before dispatching it**, inside the repo, and give the fixer the
   measured before/after rather than a description. A finding that is merely consistent with documented
   semantics is still unverified, and a plausible false positive costs a 20–40 minute agent round.
6. **Classify before dispatching: regression or pre-existing.** If this goal added one of two paths that
   now disagree about the same input (producer vs renderer, writer vs reader, resolver vs sanitiser), it
   is in scope. If the divergence is decided in the predecessor's completion record, it is not a defect —
   say why in the reply instead of dispatching it.
7. **When two rounds hit the same class, the third dispatch changes the mechanism** — collapse to one
   function, one uniform rule, or drop the path that re-derives the value. Demand a property test over a
   generated matrix instead of hand-picked rows, and require the prompt to prove no second copy of the
   rule remains (`grep` plus `file:line`). Cover every field and every authored shape the new function
   touches in that same dispatch, not just the one the finding named.
8. **A residual limit already recorded does not discharge a finding.** When the reviewer names exactly
   the case the goal record lists as a known limit, that limit is unpaid debt: implement the resolution
   or make the omission explicit in code, then rewrite the limit. "Documented, therefore out of scope"
   keeps a known-wrong value shipping.
9. **Review for semantic widening, not style.** Before merging two byte-identical call sites, write down
   per call site the grant it consumes, what it may touch, and its destination; if any differs, share
   only the mechanics (parsing, query) and keep two decisions. After splitting a predicate, re-assign a
   rule to every caller — any caller left on the old helper silently inherits whichever rule remained.
