# Import candidate: release 2.4.0

The shipped archive, not a local rebuild, must deliver p95 <= 250 ms on
**each** pinned dataset. The metric is dispatch to verified import receipt.
The comparator is context, not a way to waive the absolute ceiling. Report
comparative values only for the same dataset and metric on real work.

The fake clock is pre-recorded. Treat `sample_counts` as a histogram of
milliseconds to observations. Use nearest-rank p95: rank ceil(0.95 * n) in
ascending order, 1-based, with no interpolation. No row is a warm-up.

Use one complete campaign; do not stitch campaign IDs together. All selected
runs must be serial on the same host. Intervals are half-open [start, end);
they are operator slots, not the sample measurements.

A matching receipt means identity and end-to-end equivalence. The runner
emits a receipt class even on its preview route, so look up the class in the
registry. A preview never imported records. A second run of the same size is
not automatically a replacement.
