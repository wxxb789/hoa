# Comparator measurement

## When the standard instrument refuses the comparator

A comparator tree can predate the feature the instrument verifies (no database asset, different
publication model). Keep the refusal report as evidence, record the limitation in the goal record,
and add separately labelled structural evidence (build output size, asset inventory, largest pages)
describing what the old design shipped. Do not weaken the corpus or synthesize latency from a
structurally different path.

## When timer origins differ

A comparator too old to run the instrument may need a purpose-built probe. Align the clock origins
before comparing its latency with the candidate's:

- The candidate's driver timer, such as `Date.now()` around `locator.hover()` plus
  `waitFor({state:'visible'})`, includes actionability checks, scroll-into-view, CDP round-trips, and
  visibility polling. A probe that times from `performance.now()` in a `pointerover` listener or
  immediately before `mouse.move` omits some or all of that work. Under CPU throttling the gap can
  be ~100 ms per hover, all charged to the candidate, and look like a product regression.
- If the candidate instrument records a page-clock observation (pointerover → visible), compare
  that to the corresponding probe number. Keep the driver result in a separate "as-driven" column.
- Bound probe overhead from the measurements, not code review. With the same constant intent delay
  on both trees, a warm probe total within a few milliseconds of that delay shows its overhead is
  negligible.
- Match sample shape as well: an n=1 candidate observation against a p50 of 30 is a point estimate,
  not a distribution. Raise the candidate to the same n or say so in the same sentence as the delta.

If the numbers cannot be put on one clock, report two separate records, not a delta with a caveat.
Correct any such delta in the committed goal record before asking the maintainer to accept it.
