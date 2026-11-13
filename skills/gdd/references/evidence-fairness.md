# Evidence fairness — making a "we're cheaper/faster" claim survive review

Goal-contract repos demand a measured comparison between the library consumer and a baseline. A
headline number that reverses under a competent baseline is the single most repeated defect class
in this pipeline. Treat the comparison as a claim that must be falsified before it ships.

## Two opposite failure modes — both fake a win

1. **Naive baseline under-charges the reference (winner reversed earlier).** The reference does
   avoidable work the library doesn't, so the library looks cheaper:
   - builds diagnostic path/description strings on the SUCCESS path (a string per row × per field is
     hundreds of KB);
   - `foreach`es an interface-typed `IReadOnlyList<T>` property (boxes an enumerator per element)
     instead of indexing an array/list;
   - builds an index inside the delegate on one side but reuses a prebuilt one on the other;
   - a hand-written simulation adapter that skips work the real adapter must do.
   Fix: make the reference the strongest reasonable form doing the SAME real work, re-measure, and
   report the true direction (the sign often reverses to "library is larger/slower").

2. **Over-corrected baseline over-charges the reference (new failure, easy to introduce in a fix).**
   When you fix failure mode 1 by adding the coordination the baseline was missing, you can leave
   REDUNDANT coordination — an extra semaphore/counter/lock whose bound is already implied by the
   others. Example: a bounded-concurrency baseline already capping `unstarted ≤ B` and `active ≤ C`
   is implicitly `total ≤ C+B`, so a third `capacity(C+B)` semaphore adds one `WaitAsync`/`Release`
   round-trip per item with no new constraint — and manufactures a per-item allocation edge for the
   library. Always ask "would a competent engineer writing the minimal equivalent KEEP this step?"
   Remove every step the minimal competent form would not need, then re-measure and report whatever
   direction results (it may flip back toward the library being larger).

## Other parity axes

- **Output carrier.** Compare consumers returning the SAME carrier. `Result<T,E>` (inline struct,
  tens of bytes/row) vs reference-type outcome records alone moves KBs and can flip the sign. Keep a
  raw-carrier cost as a separately labeled disclosure row, not folded into the headline.
- **Presizing vs machinery.** A delta blamed on "async overhead" that is mostly a list pre-sizing
  difference (sync pre-sizes from a known count, async grows from 0) is a presizing artifact,
  isolated with a sync control over an uncounted wrapper.
- **One tier, one counter, two runs.** Rows at mixed tiers or with mismatched counters (per-thread
  vs process-wide allocated bytes) contradict themselves. State the tier and counter; run twice.
  For allocation, publisher rows must be byte-identical across runs. For CONCURRENCY goals the
  allocation legitimately jitters a percent or two per run — report ranges plus the correctness
  metrics (overlap violations = 0, order OK), never a single pristine number.
- **Same ledger, same events — check the COUNTING, not just the unit.** Two consumers that both
  record "visited nodes" can charge different events: one counts `path.Count + 1` even when
  resolution fails early, the other omits failed resolutions entirely, so one row carries a
  constant offset that reads as an implementation difference. Recompute one row by hand from the
  consumer's own code before grading any delta; when the countings differ, normalize the accounting
  and re-measure, and say in the evidence whether the sign changed. A mixed accounting is an unfair
  comparison in exactly the same way a mixed counter unit is.

## Honest maintainer judgment when the library LOSES

When the fair baseline shows the library larger and/or slower, do NOT reverse the direction back to
"win" and do NOT drop the row. The evidence record and the maintainer-judgment section must say
plainly: the case for the family is consumer-code SHAPE (composition, explicit policy/ownership,
structured failures, deterministic simulation), NOT allocation, code size, or speed — and the "for a
small/trusted single workflow the plain BCL/switch remains shorter/leaner" caveat stays in. A claim
that points at the wrong side (or spins a loss) is a P2 in an evidence record, not a wording nit.

## Clause-vs-boundary conflict (scope the claim, don't silently violate)

A goal clause can demand something a stated design boundary forbids. Example: "state or payload
mutation must not invalidate reproducibility" vs a "no deep copy of arbitrary caller records"
boundary. Do NOT deep-copy to satisfy it literally, and do NOT silently violate it. Resolve it by:
(1) scoping the claim explicitly in the evidence ("reproducibility is over value-immutable inputs;
library-produced outputs — returned snapshots, emitted command payloads — are immune; the initial
model and recorded messages are caller-owned by reference"), (2) recording it as a maintainer-
ACCEPTED INTERPRETATION in the evidence, (3) adding the same caveat to the public XML doc, and
(4) a boundary test that pins both the guarantee and the caller-owned edge. Transparency over a
silently-narrowed guarantee.

## Concurrency goals specifically

- **Deterministic tests only.** Gate with `TaskCompletionSource`/counters/controlled sources; never
  use wall-clock sleeps or thread-pool luck as correctness evidence. Run the suite 3× — a flaky
  concurrency test is a DEFECT to fix, not noise to tolerate.
- **The correctness proof is the gated start-order test, not the measurement table.** "Never START a
  later same-key op before its predecessor COMPLETED" is proven by a small gated test asserting
  start/completion sequence; a delivery/outcome-order column in the throughput table only shows
  scheduling, and its label must say "delivery order", not "correctness".
- **Evidence under skew.** The contract usually requires exposing per-key overlap, start AND
  completion order, in-flight, retained buffering under skewed inputs — instrument the processor to
  log start/completion transitions and print them; don't infer order from delivery order.
- **Bounds under handoff.** A measured retained count that leads the declared bound by one is
  usually a measurement handoff (slot freed before the consumer increments its counter), not a
  breach — but prove the real bound with a quiescent deterministic read-count test and label the
  metric as a handoff, don't just assert "13 vs 12".
