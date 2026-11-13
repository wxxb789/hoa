---
name: mechanism-propagation
description: >-
  Enumerate every out-of-process consumer of a resolved value and prove each one sees the same value:
  a gate that recomputes the record and a writer that validates itself. Use when a setting resolves
  correctly inside the code path but the process that acts on it may read something else. Do not use
  for a parser bug in the resolver itself, or for a value consumed only in-process.
metadata:
  version: "0.1.49"
  areas: "software-development"
  targets: "runtime-agnostic"
  summary: "enumerate every out-of-process consumer of a resolved value; prove records with a gate that recomputes and a writer that self-validates"
  summary_zh: "枚举一个解析值的所有跨进程消费者；用会重算的门禁和自我校验的写入器来证明记录"
  kind: "entry"
---

# Mechanism propagation

A promise is not kept because the value resolves correctly. It is kept when every place that *acts* on
the value sees the same one. This is the sweep for the gap between "the code reads the config" and "the
thing that runs uses it" — the failure that passes review, passes tests, and still does the wrong thing
in the only situation the configuration existed for.

## When to Use

- A config chain was added or fixed (flag → env → file → default) and you are about to call it done.
- A tool resolves a path/command and *spawns* something, or prints a command for a human to paste.
- A run writes a machine-checked artifact (baseline, receipt, ledger row) that another gate validates.
- A review finding says "resolved here but not there" — the second occurrence of that phrasing is a
  class of bug, not a coincidence.

## Step 1 — enumerate the consumers

List every reader of the value, then classify by **who resolves it**:

| Consumer | What it does | Failure it causes |
|---|---|---|
| Child process (launcher, helper, hook) | re-resolves from its own environment | creation writes to the default while discovery reads the configured one; `status` reports nothing running |
| A command printed for the operator | nothing — the human's shell re-resolves | the paste-back says "not found" for a live run |
| A sibling script with its own precedence | re-resolves independently | two layers disagree; whichever runs first wins |
| A persisted record validated later | trusts what was written | a flaky run overwrites the last good measurement |
| A cache or sidecar file | trusts staleness | the newest state never appears |

**Rule:** one owner of precedence, every other consumer takes the resolved value *by value* — in the
child environment (`env={**os.environ, "KEY": value}`) and in any command you print
(`KEY=<shlex.quote(value)> cmd`). Teaching each reader to re-resolve is the bug, not the fix.

## Step 2 — prove each consumer, not the summary

- **Child process:** stub the child so it fails loudly when the variable is absent (non-zero exit, not a
  default), then assert the value it recorded equals the resolved one. A stub that falls back to the
  default proves nothing.
- **Printed command:** take the line from stdout verbatim, execute it, require the run to be found. Add
  a case whose path contains a space — an unquoted prefix survives only until the first odd path.
- **Discovery and creation agree:** after the stub creates its output under the configured root, the
  status/list path finds it *and* the concurrency guard sees it (assert the guard's exit code).
- **Network- or CLI-shaped behaviour:** drive it yourself against a local stdlib stub (`http.server` on
  `127.0.0.1`) and assert side effects — exit code, file hash, written/not-written — instead of reading
  the agent's summary.
- **"Must not overwrite" claims:** hash the file before and after; an identical hash is the proof, and
  restoring the original afterwards keeps the tree clean.

## Step 3 — records: recompute, then self-validate

Two rules protecting different sides of the same file.

1. **A gate must recompute what it grades.** Internal consistency (ids exist, totals add up) is not a
   measurement. Re-derive each row from the source (`recorded_passed == (recorded_pick in current_expected)`)
   and require recorded values to name something that exists. Otherwise retargeting the source leaves a
   stale record looking green.
2. **Only the writer can protect the previous record.** A failed run may produce values the gate cannot
   represent (transport errors, non-existent names). Validate the *proposed* record with the gate's own
   validator **before** writing; on rejection leave the existing file byte-identical and exit non-zero
   naming the offending rows. A wrong-but-valid value is an honest measurement and must stay
   recordable — "cannot be represented" is not "did not pass".

Both live in one place: the writer calls the gate's validator. Adding the guard at a second call site
instead of the single choke point is how the same finding returns next round.

## Pitfalls

- **Silent fallback is worse than no fallback.** A consumer that quietly uses the default when the
  variable is missing turns a configuration bug into "works here". Make the absent case loud.
- **A literal absolute path as the default** ties the mechanism to one machine; the default must be the
  documented one from the repo's resolution order.
- **Printing a command without its assignment** is half a propagation: the code is right and the
  operator's next action is wrong.
- **A signature change is not a behavioural test.** When proving new tests fail on old code by stashing
  the fix (`git stash push -- <path>` … `git stash pop`), a `TypeError` or import error proves much less
  than an assertion failure. Say which one you got.
- **Re-running until green** turns a flaky case into a fake baseline: record the failure, name the
  ambiguity, give the case fix its own increment.

## Reporting

State the consumer list and the value each one actually received — not "it works". "Resolved and
propagated to the child, the printed command and the validator; the cache sidecar is unproven" is the
shape.
