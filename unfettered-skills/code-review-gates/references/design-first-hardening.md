# Design-first hardening — when the review loop stops converging

Use when the same class of blocking finding survives both per-finding patches and the systematic sweep
(`mechanical-gate-design` §6). The class is structural — ownership, lifecycle, concurrency, cross-process
state, generation/versioning — and each locally correct fix reveals the next edge of the same state machine.
Coverage findings (a rule that was never pinned) are the sweep's job, not this one's.

## The cheaper rung first: close the seam the class leaks through

A full spec is a scope change (three lanes, one implementation round, a fresh grader). Before spending it, ask
the root-cause consult for the structural closure, and expect a few small seams rather than a rewrite: the
invariants have been written in comments, so every site was written *beside* the invariant instead of *through*
it, and no enumeration of sites can close that. **Keep the one artifact; replace the seams.** A consult that
names them has answered "do not re-decompose", so the next dispatch is an implementation round.

The tell that this rung applies: across rounds the **predicate moved** — each fix widened the previous patch
(one more existence check before the act, one more rule filtered out of the reported set, one more `except`
clause beside the call), so the next defect always sat in the gap the latest predicate did not cover.

Shapes that recur, with their closure and the pin that proves it:

- **A resource created in a surface you do not own** (a file planted into a caller's directory). Closure:
  record the path at the instant the exclusive create succeeds, on one ownership object whose teardown removes
  every recorded path. Not a success flag the caller sets after the function returns — a raise between the
  create and the assignment skips cleanup and leaves the surface poisoned for the next run. Pin: a write or a
  close that fails *after* the name is reserved; the surface ends as found and a retry finds no leftover.
- **A check pipeline where a skipped prerequisite makes "not evaluated" read as "passed".** Closure: evaluate
  every rule, or record it as `NotEvaluated` with what blocked it; make disabling a rule a subtraction *after*
  evaluation; require `PASS` to mean every rule was evaluated. A rule decidable only on decoded input then
  declares that dependency as a first-class result instead of sitting behind a gate that drops an independently
  provable violation of its sibling (termination of the raw bytes, say). Pin: the combined input whose disabled
  arm still cites the byte-level rule.
- **A result the callers re-interpret** — a bare tuple/bool whose meaning each caller re-derives with its own
  `except` list, so every round finds the next uncaught exception type. Closure: one result type, the transport
  and teardown errors folded in **at the object that owns the resource**, and the refusal variant constructible
  by nothing but the one matcher — so a broken pipe can never be reported as the refusal under test. Pin: the
  closed-pipe path driven through that seam, not through a stub that returns the expected value.

Make each seam's tests pin by **mutating the seam**, never by stubbing its result: a stub of the plant or of the
interaction that returns the expected value stays green when the seam's own line is deleted.

Declare the one residual the consult names (a run that creates the resource and then dies leaves no teardown to
recover it) as a limit in the closeout — not as another review round.

## Three-lane separation

Author (implementer) / designer (spec) / grader (verdict) are three distinct model families, and the round's
report names which lane filled each role. A designer that graded earlier rounds rewrites its findings list as
prose; a grader that helped design the spec has nothing independent left to check.

## The spec packet

One packet, one subject, whole — the chunking discipline for review packets does not apply here, because the
designer needs the state machine, not the diff.

1. the instruction below;
2. the **verbatim findings of the last round** — they define the class and its vocabulary;
3. the **full current source** of the subject (not a diff);
4. its **test file** — the spec extends the existing discipline instead of inventing a second one;
5. the **contract** the subject implements (route doc, goal contract, protocol note);
6. the **sibling implementation(s)** sharing that contract, marked FROZEN, so a proven mechanism can be
   reused and no sibling is silently changed.

State the packet's byte count in the round report. A subject of a few hundred KB still fits a large-context
lane; splitting it across lanes is what the review round does, not this.

## The instruction

- "You are an independent architecture reviewer: design only — no implementation, no findings list, no
  restating of the diff."
- Required sections: object model (and what the current design lacks), mutex/locking protocol with a total
  order and where each lock lives, lifecycle state machine with what *proves* each terminal transition,
  generation binding for every mutating operation, identity/ownership rules, the stop protocol, the invariant
  table, the change surface in implementation order (naming real functions from the attached source),
  operator-visible behaviour, residual limits, and ≤5 open questions each carrying a recommended default so
  implementation can proceed unanswered.
- Invariant table, mandatory columns: id · checkable statement · the failure it prevents · the deterministic
  test that must exist (name the interleaving it drives) · the mutation that must make that test fail.
- Constraints: each rule implementable in one round and checkable by one reviewer; standard library only; keep
  the public CLI and status vocabulary unless the model requires a change (then justify it under
  operator-visible behaviour); mark `UNCONFIRMED` rather than inventing.
- Require an explicit mapping of **every** finding of the last round to at least one invariant, and an explicit
  list of what the designer rejected as over-engineering.

## Dispatch and grading

- Dispatch as a **detached unit**, not a turn-bound foreground call: a gateway/adapter drop must not take the
  work with it. Report the unit name, the packet path and the artifact path.
- Grade the artifact before dispatching the implementation — non-empty output with a real byte count; the
  invariant table present; every last-round finding mapped; the change surface naming functions that exist in
  the attached source; residual limits stated; **no code implementing the change**. A document that reads as
  the findings list again means the lane reviewed instead of designing: re-dispatch, do not implement from it.
- Then exactly one implementation round against the spec: quote the spec sections by name in the dispatch,
  state the acceptance commands, and require a pin test per invariant with its pre-fix failure quoted.
- Then a fresh grader over the new head: a fourth family, neither the implementer nor the designer, driven as
  the review round's report-only packets (SKILL.md's chunking rule), each packet's prelude carrying the branch
  manifest, the adjudication, the spec's digest and the already-settled list — a grader without the settled
  list re-opens the decisions the rounds below it already paid for.
- The **adjudication** written between the spec and the implementation round is part of the instrument, not
  paperwork: a numbered clause list that overrides the spec wherever it contradicts the goal, the sibling
  route's contract, or a deliberate capability reduction (refuse rather than guess where no verified handle
  exists; keep a historical on-disk format because a sibling reads it). Quote it into the implementation
  dispatch and into every grader packet, or "conform to the spec" means one thing to each lane.

## Stop rules

- If the post-implementation grader still returns the class, stop and answer it with the spec's residual-limits
  section plus the evidence. Another design pass on the same subject means the first spec was not the problem —
  escalate the contradiction to the operator instead.
- The PR stays open for the whole exercise, and the exercise is a scope change: raise it as a decision with its
  costs rather than spending it, because an authorization to merge does not authorize an extra round.
