# Codex context compaction

- Config: `${CODEX_HOME:-$HOME/.codex}/config.toml`.
- Inspect both `model_post_turn_compact_threshold_percent` (0–100) and
  `model_auto_compact_token_limit` (absolute tokens). Both were unset in the snapshot; the example
  values for a 50% trigger in a 1M-token window are `50` and `500000`, respectively.
- `codex doctor` reports `config.toml parse ok` when parsing succeeds. Verify separately which
  settings are effective in the target profile and session.
