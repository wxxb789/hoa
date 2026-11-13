---
name: measurement-campaign-evidence
description: >-
  Run a measurement campaign as the evidence phase of a goal whose completion condition is measured:
  pin the candidate first, measure serially, keep one report set, and never let a comparator fake a
  latency number. Use when the pass condition is a size, duration, count or ratio rather than a passing
  test. Do not use for a plain gate run, or when the numbers are not the acceptance criterion.
metadata:
  version: "0.1.54"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "bind the candidate, measure serially, keep one report set, never let a comparator fake a latency"
  summary_zh: "测量运动：先钉候选身份、串行跑、一致报告集，不让基线伪造延迟对比"
  kind: "entry"
---

# Measurement campaign evidence

A campaign is the evidence phase of a goal whose completion condition is *measured*: sizes ×
topologies, a packaged artifact, a browser/runtime profile, a comparator tree, overload controls. The
repeatable failure is not a missing number — it is a number belonging to a slightly different artifact
than the one the record claims. For the surrounding delivery loop and its gate verification rules see `gdd`.

## When to use

- A goal says "measure A against B at N sizes" or "accept only if p95 < X".
- A prior campaign exists but its reports came from a dirty tree, a mixed artifact, or a pre-change
  instrument.
- A delegate hands back a campaign with a summary table.

## 1. Bind the candidate before measuring

- Measure the **shipped artifact**, not the checkout, whenever the goal claims the package works: build
the tarball, install it into a scratch prefix, and drive the instrument with the package's own entry
file (`<prefix>/node_modules/<scope>/<name>/bin/<cli>.mjs`). A `node_modules/.bin/<cli>` symlink hides
the package manifest from an identity hasher, so the report records no installed-package or tarball
hash and cannot prove which bytes ran.
- Pass the tarball to the instrument when it validates one (flag or env var); it compares the tarball
payload with the installed tree and refuses a mismatch.
- After the campaign, verify **every** report carries the same payload/tree hash. One divergent report
means two artifacts were measured and no aggregate from that set is valid.

## 2. An interrupted run poisons the candidate

An instrument that hashes the installed package fails later runs with `payload does not match installed
package` when a killed build left its scratch directory inside the package (`<pkg>/.<tool>-build-*` and
siblings). Successful runs clean up; kills do not.

1. Reinstall the prefix from the tarball and delete stray scratch dirs.
2. Re-run the cheapest workload and confirm the payload hash equals the earlier reports before spending
   minutes on the large ones.
3. Keep long campaigns away from anything that restarts your supervisor — a gateway/service restart
   mid-build is what creates the poisoned state, and the campaign restarts from that workload.

## 3. Comparators that cannot satisfy the oracle

A comparator tree usually predates the feature the instrument verifies (no database asset, different
publication model). The instrument refuses it; that refusal IS the evidence: keep the refusal report,
record the limitation in the goal record, and add separately labelled structural evidence (build output
size, asset inventory, largest pages) describing what the old design shipped. Never synthesize a
comparative latency from a structurally different path, and never simplify the corpus so the old tree
passes.

### Clock origin: the comparison that looks real and is not

A comparator too old to run the instrument needs a purpose-built probe, and that is where a latency
comparison silently becomes apples-to-oranges:

- The candidate number usually starts in the driver — `Date.now()` around `locator.hover()` plus
  `waitFor({state:'visible'})` — so it contains actionability checks, scroll-into-view, several CDP
  round-trips and the polling interval that notices the panel. The probe number usually starts in the
  page — `performance.now()` in a `pointerover` listener, or immediately before `mouse.move` — so it
  contains none of that. Under CPU throttling the gap is ~100 ms per hover and lands entirely on the
  candidate, which then reads as a product regression.
- Align the origin before writing any delta. Usually free: if the candidate instrument already records
  its own page-clock observation (pointerover → visible), compare that to the probe number and keep the
  driver number as a separate "as-driven" column.
- Bound the probe's overhead from its own numbers instead of asserting it from code review: with the
  same constant intent delay on both trees, a probe warm total of ~delay + a few ms proves its driver
  overhead is negligible.
- Match sample shape as well: an n=1 candidate observation against a p50 of 30 is a point estimate, not
  a distribution. Raise the candidate to the same n or say so in the same sentence as the delta.

## 4. Report the target metric alone, and the cost beside it

- Quote the metric the goal defines, in its own definition (for example dispatch to validated result,
excluding rendering).
- Then report what a maintainer must rule on — render cost, largest-list cost, transfer — as their own
columns, even at ten times the target. A passing headline that hides the material UX number is a P1 in
the evidence record.
- State the emulation channel that actually ran: a bundled Chromium is not "Chrome", and Chrome is not
"Edge". Note which target the throttle applies to (page vs worker) and that loopback is not a network.
- Keep the raw per-workload reports plus their digests; the aggregate table is derived, the reports are
  the evidence.

## 5. Accepting someone else's campaign

- Re-run at least one workload and one overload control yourself on a committed tree; a summary table
  is a claim.
- Check how the reported run got its result. A campaign whose gate is a clean tree or a stable candidate
  identity can be run through a defeated gate — `git update-index --assume-unchanged` (`git ls-files -v`
  shows a lowercase flag), `--no-verify`, a stub on `PATH`. That is disqualifying, not thorough: the
  numbers belong to a tree state you cannot reconstruct. Commit, re-run, then quote.
- A control that fails for an *instrument* reason (a child runner changed where it writes its
  machine-readable output) is a real defect to fix in the instrument, and the whole affected control set
  has to be re-run afterwards — not waived.

## 6. Execute serially and size the host

A 10,000-item workload builds for minutes and peaks near 1 GB. Two of those beside a test suite on an
8 GB host is an OOM the kernel resolves by killing whichever job it dislikes. One workload at a time,
no suite in parallel, and record peak RSS per workload so the next campaign can budget the host.

## Output shape

1. Candidate identity line: version, tarball digest, payload/tree hash, instrument source hash.
2. One row per workload: target metric, its inner cost, the drawing/transfer cost, failures.
3. Controls: each bound, the observed overshoot, the bounded failure, the retry.
4. A limits section: emulation not hardware, throttled target, loopback, which memory instruments are
   unavailable, and which comparator could not be measured.
5. What the maintainer must decide, as a short numbered list — never a conclusion the evidence does not
   own.

## Pitfalls

- Aggregating reports without checking that all of them share one candidate hash.
- Driving the instrument with the `.bin` symlink and losing the package identity the goal requires.
- Treating an instrument refusal on a comparator as a setup bug and "fixing" it by weakening the fixture.
- Letting a failing large or hub-heavy case disappear into an average; the goal usually forbids it.
- Reporting a south-of-target headline while the drawing cost tripled, so the maintainer accepts a UX
  trade-off they never saw.
- Comparing one harness's driver-side timer against another's page-side timer and publishing the delta as
  a trade-off. A footnote that says "clocks not decomposed" does not make the headline direction valid —
  if the two numbers cannot be put on one clock, there is no delta to report, only two separate records.
  When the committed goal record already carries such a delta, correct the record before asking the
  maintainer to accept it.
- Running the campaign beside a full test suite on a host sized for one.
