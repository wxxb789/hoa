# OMP context compaction

- Config: `${OMP_HOME:-$HOME/.omp}/agent/config.yml`.
- `compaction.thresholdPercent` accepts 1–99. The snapshot default `-1` selects reserve-based
  compaction (~80%); set `50` for the 50% example. Read back with
  `omp config get compaction.thresholdPercent`.
- `compaction.thresholdTokens` is an absolute trigger and takes precedence over
  `compaction.thresholdPercent`; check it before claiming the percent is effective.
- The documented trigger order is `[remote, snapcompact, handoff, shake, soft]`.
  Manual `/compact` works even when automatic compaction is off.

## Runtime evidence

For model effort, locate the resolved `thinking_level_change` event and confirm that the session
loaded the intended config. If runtime readback is unavailable, report only the layer verified.
