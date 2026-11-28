# Stage handoff discipline

The driver loops the stage protocol; these are the seams between stages where a driver and a human
operator make the same mistakes. The rules are mechanical — put them in the dispatch prompt, not in the
dispatcher's memory.

## A report-only stage must prove it wrote nothing

Ask the prompt to print `git status --porcelain` and `git rev-parse HEAD` at the **start and the end** of the
run, and check both yourself. "Do not commit" is weaker than "do not modify a byte": a report stage that
edited the tree it measured measured the wrong tree, so its findings describe a tree that no longer exists.
A lane that cannot produce the two readbacks is not one to trust with the measurement.

A report stage that must **mutate** to measure — a mutation proof, a probe, a branch deleted to see which
test fails — does it on a throwaway copy (`git archive <head> | tar -x -C /tmp/<probe>`) and says in the
report that every measurement ran there. The readbacks then still show the real tree untouched, which is
what makes the measurements and the untouched tree compatible facts rather than a contradiction.

## Hand findings forward as data, not as chat

Every stage report ends with a machine-readable verdict object — head sha, whether there are findings, and
one entry per finding carrying id, group, file, line range, evidence and the requested change. Extract it
into `findings.json` beside the prose and hand the next stage **both** paths: the prose so the applier reads
the evidence rather than the headline, and the JSON so nothing is lost to paraphrase and the disposition
can be written per id.

The next stage's prompt then carries one disposition line per finding — accept, or reject with the reason —
plus the constraint that keeps an accepted finding from also deleting a contract statement, an evidence row
or a disclosed limit. "Apply all" is not a disposition.

## Where a finding offers two readings, pin the strict one

A finding that says "this claims X but does Y" is a correctness defect wearing a comment or a test name.
When the requested change can be read strictly (make the behaviour match the claim, or make the claim
visible where a reader checks it) or leniently (soften the claim), the apply prompt pins the strict reading
and requires code, docstring and docs to end up saying the same thing.

## Bind the report to the decisions already settled

A freshly dispatched lane has no memory of the rounds, consults or owner decision that settled the
increment's design. When the increment's point is a **deletion or a replacement**, expect it to spend the
round proposing to restore or "improve" the removed mechanism — a report that then has to be argued down,
which is a wasted round and a poisoned ledger entry. Put the boundary in the prompt:

- one line saying what the increment *is*, naming the file that records the decision (the goal contract, a
  decisions record, the consult's answer);
- an explicit **do-not-report list**: restoring or re-deriving the removed mechanism, a variant of it under
  a new name (a per-case special case, a different tolerance or trimming rule), and the accepted design
  itself as a finding;
- the one thing you do want instead: where the **code disagrees with that settled contract**, with the
  clause named.

Weight the round the way the increment moves: a net-deleting increment is reviewed for what is *left* of the
removed machinery (names that still promise it, comments that still describe it, tests whose expectations
are still derived from it), not for additions. A finding that only re-proposes the settled design is not a
finding — reject it by id and say why, so the next round does not raise it again.

## A consolidation finding is accepted only with its pin, proven

When a finding says one decision is written N times and some of those copies are untested, accepting the
hoist alone buys a single copy nobody tests. Accept it **together with** the test that covers every route,
and require the mutation proof in the same round: disable the shared branch once, show a test fails. The
evidence that the gap is real is the converse measurement the report should already carry — disable the
branch in each copy in turn and name which copies stay green — so ask for that measurement rather than for a
reviewer's confidence. A hoist moves counts: re-derive every recorded number on the new tree.

## A number the gate already counts is quoted, not recounted

When a report needs a count a gate verifies (cited rows, tests, files under parity), quote the gate's own
verifier line and the head it ran on. A separately obtained count that differs by a row or two is an
artifact of your own command, and raising it as a discrepancy spends a round on nothing.

## A narrowed predicate must say where every old shape now lands

A tightening — an exact comparison where there was a trim, a state machine gaining a case, a route gate
moved — silently drops shapes the previous predicate named, and it is invisible exactly because no test
pinned those shapes. Ask the report for one table: every shape the old predicate classified, and the
category **each** gets now, per route. A shape that lands in no category is a **disclosure regression**,
not a simplification; the fix is the restored predicate plus the missing case, and the case is the pin.

## Decide a disclosure where the text is decided, not before its gate

A category counted before the gate that discards the text claims carriage for bytes the artifact does not
hold ("written byte for byte") and makes one source record count differently on two routes. Count and
classify **after** every gate that can drop the record, and put the same shape through two routes in the
same test to catch the divergence.

## The review is the last authoring event

A machine verdict is pinned to a head, so a review dispatched while an `apply` or `fix` stage is still owed
is spent budget: the next commit invalidates it. Order the series so the review runs on the tree that will
be merged, and re-dispatch it after any later write, rebase included.

## A hand-rendered round prompt inherits the last round's literals

When a round's prompt is produced by copying the previous round's prompt file — the usual shape for a
hand-driven round on a stopped or idle driver — every round-specific literal travels with the copy: the
findings/mandate path the round reads first, the reviewed base and head SHA, the round label, the run name,
and the model and effort pinned in the consult line. Re-point each one and then **prove** it: `grep -n` the
derived file for the values the *previous* round used (the old label, the old findings path, the old model
id) and read the result as zero before dispatching. A copy that still names the previous round's findings
file sends the lane at the wrong artifact, and one that keeps a retired model id spends the round's single
consult on a caller that no longer exists — neither failure is visible in the launcher's own output, and
both surface as a round that answered confidently about the wrong input.

Fix the literal at the file the copies are rendered *from*, not only in the copy in hand: a rendered prompt
propagates nothing, so a repair applied to one round's file is inherited by none. When the copied file was
already wrong, correct it there in the same pass and say so — the copy is the mechanism by which one stale
literal reappears round after round.

## Bridging two stages without idling a turn

Start the next stage the moment its input artifact exists, never on a fixed clock: poll the run's own
`exit.code` in a bounded loop (`for i in $(seq 1 34); do [ -f <run>/exit.code ] && break; sleep 15; done`).
Take two witnesses before believing a stage is done — the run's `exit.code` **and** the artifact it was
supposed to produce; a finished run and a produced report are different facts. The same discipline applies
in the other direction, at dispatch: a printed run directory, session id and pid are the launcher's intent,
not the agent's first turn. Read the run's own state leaving idle (`state: running`), an event log that is
actually growing, and a live process before reporting the work as in flight to anyone.

When the wait cannot finish inside the turn, start a waiter with completion notification rather than holding
the turn open on a bare `sleep`:

```
terminal(background=true, notify=true, command="…block on <run>/exit.code, then print the run's last lines…")
```

A driver's progress must never depend on the operator's turn still being open, and a run's own summary line
is a claim about its work, not evidence of it.
