# Pi context compaction

- Config: `${PI_HOME:-$HOME/.pi}/agent/settings.json`.
- `compaction.reserveTokens` is a reserve, not a trigger; subtract it from the model window.
  The snapshot default is `16384`. There is no percentage form: the schema requires non-negative
  safe integers, so reserve `500000` tokens for a 50% threshold in a 1M-token window.
- `compaction.modelOverrides` supports per-model `reserveTokens` and `keepRecentTokens`. Set a
  different reserve for each model with a different window when enforcing the same percentage.
- Check that the JSON parses, then compute the implied threshold from the effective reserve and
  model window.
