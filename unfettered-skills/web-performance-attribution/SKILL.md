---
name: web-performance-attribution
description: "Use when a browser perf number moved: explain or cut it."
metadata:
  version: "0.1.0"
  areas: "software-development,research"
  targets: "runtime-agnostic"
  summary: "one clock per claim, attribute cost by layer, measure the shape of the cost, report populations"
  summary_zh: "同一时钟、分层归因、量化成本形状、标注样本与局限"
  kind: "entry"
---

# Web performance attribution

A performance number is a fact only inside its instrument. Two numbers from two instruments are not
comparable until they share a clock origin, an environment and a workload. Most "performance
regressions" found in a built site are either the wrong clock, the wrong population, or a cost that
belongs to a layer nobody timed.

## When to Use

| You hear / see | Do |
|---|---|
| "why did this get slower/faster?", a version-to-version latency or byte delta | §1 clock and instrument, then §2 attribution |
| "where can we still optimize?", "do a perf exploration", a ranked cost inventory | §2 layers, §3 shape of the cost, then report |
| a recorded benchmark claim that drives a ship / no-ship decision | §1, plus `report-claim-audit` |
| "make the graph / tag list / preview faster" | §2 page-layer attribution before touching product code |

**Not for**: server throughput, bundle size with no runtime question, or framework selection.

## 0. Name the question first

- *Why did it change?* → cross-version delta. Needs both sides measured the same way, and the
  mechanism named per layer.
- *What is left to optimize?* → cost inventory. Rank transfer / startup / per-interaction / render /
  build separately; they have different fixes and different owners.
- *Is this acceptable?* → a policy question. Produce the trade table (bytes vs latency vs size) and
  let the owner decide; do not silently pick a UX trade.

## 1. Pin the instrument before reading any number

Record, per number: artifact hash (commit / tarball), instrument file + hash, **clock origin**,
browser + device profile + CPU throttle, network (loopback vs real), cache state, corpus fixture +
seed, sample count, quantile method.

**One clock per claim.** The clock origin is either the Node-side harness (`Date.now()` around a
`locator.hover()` / `click()` / `waitFor()`) or a page-side observer (`performance.now()` at
`pointerover`, at a mutation, at a custom event). Never compare the two, never subtract a delay from
one side only.

Mechanism, so you can spot it: a locator action plus `waitFor` pays actionability checks, scroll-into
-view and polling detection — order 100 ms warm and 150 ms cold at 4× CPU throttle. A page observer
never sees that, so the harness with the Node-side clock looks ~100 ms slower for identical product
behaviour. When both instruments exist, each side's page-clock sub-observation (e.g. hover→visible)
is the comparable pair; the harness residue is stated, not compared.

When one instrument records both clocks in the same sample — a Node-side total beside a page-clock
sub-field such as `hoverDelayMs` — compare through the sub-field and state the residue. Do not
re-derive one clock from the other, and do not "subtract the overhead" from a single side.

**Pin the deployed artifact too when the claim is about what readers get.** A site can serve a build
weeks older than the checkout you are benchmarking (an unpinned or stale generator reference in the
deploy workflow is enough), and every number then describes software nobody runs. Fetch an identity the
origin actually serves — a content-addressed filename, a version banner — and compare it with the build
you are about to measure before you measure it.

## 2. Attribute by layer before proposing anything

Take the layers in the order the reader pays them:

1. **Transfer** — encoded vs decoded bytes, per asset class, cache state per request.
2. **Engine** — fetch, hash/integrity, WASM init, module import, query. Read these from the
   runtime's own telemetry spans; do not infer them from the total.
3. **Page** — DOM construction, style/layout, list growth, redraw. This is where "the query is fast and
   the UI is slow" lives.

Two instruments do the work:

- **The runtime's own spans.** If the app can emit per-operation and inner-engine time (SQL ms,
  operation ms, phases), arm that seam *before the first dispatch* and read it. A span that stays
  flat while the end-to-end number grows exonerates that layer in one line.
- **A synthetic microbenchmark in the same browser profile and throttle.** It proves a mechanism, not
  a presence: first read how big the real workload actually is — the drawn node count, the list
  length, the rule that bounds them — and only then build that shape. Time element construction
  separately from layout (on a wide table layout is ~90% of the total). A shape the product never
  renders measures nothing: 60 rows × 40 joined links costs ~240 ms synthetically while the shipped
  page renders figure and table in ~22 ms, because its node bound is what keeps the table small.
  Report the bound and the cliff separately — "cheap at the current cap" and "expensive if the cap
  moves" are both true and the second one is the design fact.

## 3. Measure the shape of the cost, not just one point

- **Fixed tax vs corpus-proportional cost.** Measure two corpus sizes. The crossover is the design
  fact to report (e.g. old path wins at 1k by ~68 ms, new path wins at 10k by ~240 ms); a single
  size hides it.
- **Startup serialization.** If a dwell/intent timer gates a lazy runtime, the fixed startup tax and
  the dwell are paid serially and the sum is the cold latency. Overlapping them (start init at the
  intent event, keep the gate on presentation) recovers the smaller of the two — usually the whole
  dwell. State the trade: a reader who hovers and leaves now pays the download.
- **Per-item slopes.** Any list that appends and never releases pays ~0.05 ms per item; multiply by
  the target size before deciding it is a rounding error.
- **Transport rules.** Content-addressed filenames can be cached immutable — check whether the
  emitted header rule actually covers them. Compression: measure brotli and gzip on exactly the bytes
  shipped; brotli is worth 13–29% on wasm/sqlite/js, but only on hosts that negotiate it.

### Cutting a list's cost without cutting its reachability

- **Measure the logical collection, not the DOM.** Once a list renders a window, its element count is
  constant by design: a probe that waits for `childElementCount` to grow never resolves and hangs
  instead of failing — minutes of "still running" that read like a slow build. Read the position a row
  advertises (`aria-posinset`, `aria-setsize`) or the runtime's own counter, and assert the logical
  total moved. The same rule applies to any acceptance gate written against the old accumulated DOM.
- **Drive the window from scroll position, not from shift events.** A window that only advances inside
  a `scroll` handler strands every earlier row once there is no further scroll to produce an event: at
  `scrollY 0` inside a tall "before" spacer nothing fires and the reader can never walk back to row 1.
  Make the rendered range a function of `scrollTop` and keep a prefetch margin of at least one
  viewport on both sides, so a spacer is replaced by rows before it enters the viewport.
- **Acceptance for a bounded list is reachability, not the metric.** From any loaded state,
  `scrollTo(0)` must land on row 1 in one operation; a continuous wheel-up run from the tail must reach
  row 1 with no gap. Hand-test the gestures the change touches — scroll back, focus, in-page find — and
  state what a window costs: Ctrl+F then sees only the rendered rows, so the site's own search becomes
  the way to find an unrendered match.

### When the fix trades correctness for speed

- **A correctness fix that costs latency must be measured against the same bound it breaks.** Reading
  real row geometry (because titles wrap) doubled p50 and pushed p95 to 42–62 ms on a list whose
  acceptance line was 40 ms. The fix was not "revert to the cheap approximation": it was to make the
  geometry query O(log n) in the logical position (prefix-sum/Fenwick over per-row heights with a mean
  for unmeasured rows) and to remove a second, unrelated cost the measurement then exposed — a width
  read after the DOM edits that forced one layout, then a spacer resize that dirtied it, then a rect
  read that forced it again. Result: faster than the pre-fix build *and* correct.
- **A/B in one session, two rounds each, and report every round.** Cross-day comparisons mix host load
  into the claim. The same tarball measured p95 23.5 / 36.6 / 23.6 ms in three rounds and 57.0 ms in a
  fourth taken while load average rose 1.46 → 2.53; the pre-change build itself reached 63.9 ms in an
  earlier round. Publish the rounds and name the outlier instead of averaging it away.
- **Separate the populations, not just the ratio.** First-20 and last-20 p50 answer different
  questions: a cost that tracks scroll depth makes early continuations cheap and late ones expensive,
  which a single growth number can hide when the sample is noisy. When they disagree with the total,
  the mechanism is position-dependence, not list size.

## 4. Report

- Every number carries its population (`n=30 p50`, `single observation`) and its clock.
- Structure: what changed in reader terms → the mechanism per layer → the limits of the evidence
  (emulation not hardware, loopback not mobile, throttle applied to one target only).
- If the measurement invalidates an earlier record, **correct that record in place**; an erratum
  appended beside a wrong headline leaves the wrong sentence in force.
- Deliverable shape for this user: chat gets the conclusion plus a ranked table of win / cost / risk
  with evidence paths; the long form goes to `~/claw/tasks/<date>/<task>/README.md` with the probe
  scripts beside it. Policy trade-offs (prefetch on hover? virtualization vs paging?) come back as
  one numbered decision, not a unilateral change.

## 5. Verify the fix the same way

Re-run the identical probe after any change and publish the new number beside the old one. A fix
claim without a re-measured number is a plan. Keep raw probe output as JSON on disk and aggregate in
code — medians and p95 by hand are how one lucky run becomes a reported median.

## Pitfalls

- Comparing a Node-side harness clock to a page-side observer and reporting the difference as a
  product regression; look for a page-clock sub-observation on both sides first.
- Quoting a percentile from one observation, or a p50 whose n is not stated.
- Benchmarking the repository HEAD while the deployed origin still serves an older pinned build; the
  numbers describe software no reader runs. Fetch the served artifact identity first — a green deploy
  job does not prove the origin was updated.
- Arming a telemetry seam after the request was dispatched — the reply then carries null spans and
  reads as "no engine cost".
- Installing a `MutationObserver` in an init script for an element that does not exist yet: it never
  fires and every measurement comes back null. Time dispatch→DOM change with a rAF promise inside a
  single `page.evaluate`.
- Looping "load more" to exhaustion without recording where it stopped; an early stop looks like a
  plateau and a late stop looks like a cliff.
- Optimizing the largest absolute number before decomposing it. A field named "global graph" or
  "render" may be end-to-end: one such number was 356 ms of which 129 was cold Worker start, 210 the
  query and 22 the drawing. The same record almost always carries the split (`renderMs`, `phases`,
  `operationMs`, `sqlMs`) — read those before naming a layer, and prefer them over re-deriving the
  split yourself.
- Editing the measured checkout while a benchmark run is live. Instruments that hash the tree or
  assert a clean worktree fail at their next identity check, which costs the whole campaign. Do
  unrelated doc work in a separate `git worktree add <path> -b <branch>` and land it after the run.
- Reporting gzip bytes as if the host negotiates brotli (GitHub Pages does not; Pages/Workers do),
  or marking a non-hashed asset immutable because a sibling file is hashed.
- **Reading transfer bytes with a client that sends no `Accept-Encoding`.** A bare `curl` receives the
  identity body, so `Content-Length` equals the decoded size and the file reads as "served
  uncompressed" — a conclusion inherited from exactly that mistake had to be corrected later. Send
  `Accept-Encoding: gzip, deflate, br`, report wire bytes and decoded bytes as a pair, and probe `br`
  alone separately: answering `identity` to `br` while answering `gzip` to the full list means the host
  negotiates no brotli.
- Presenting emulated mobile as mobile hardware, or loopback latency as a network claim.
- **Treating DOM ARIA attributes as proof of what a screen reader gets.** A windowed `ol` can carry
  `aria-posinset`/`aria-setsize` on every rendered `li`, contiguous 1..n, while Chrome's accessibility
  tree exposes the items with no `posinset` property at all (`a11yAx: listitems 125, withPosinset 0`).
  Read the AX tree (`Accessibility.getFullAXTree`) before claiming accessibility for virtualized
  content, and let the DOM contract be the claim only if you say so explicitly.
- Running the repo's full gate suite locally on a small host: `--maxWorkers=4` plus browser tests on a
  7.7 GiB box gets the whole run SIGKILLed (oomd at 80% of the user slice), which reads as a hang and
  wastes a cycle. Run the affected files at `--maxWorkers=1` locally and let CI run the full suite —
  and pin the runtime the repo asks for (`.nvmrc`) rather than the global default.

## References

- `references/measurement-recipes.md` — the probe scaffold, seam arming, attribution table, and the
  cache/compression checks that need exact commands.
- `templates/probe-browser-timing.mjs` — a copy-and-adapt Playwright + CDP probe: static gzip server,
  Pixel-class profile, CPU throttle, page-clock dispatch measurement.
