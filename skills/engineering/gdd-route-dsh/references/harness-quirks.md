# DSH harness quirks

- **Agent presets do not exist in headless.** `standard`/`ptc`/`minimal` are profile patch fragments that
  need the agent-preset registry, which the headless profile does not compose. Applying one logs
  `pending (waiting for service: agentPresets)` and leaves the tool set unchanged. Programmatic tool
  calling needs an explicit overlay (`tool-executor-native` disabled, `tool-executor-ptc` enabled).
  While it is active a direct call to any other tool resolves to `UNKNOWN_TOOL`.
- **Credentials:** launch environment → `<cwd>/.env` → `$DSH_HOME/.env`. The managed store is disabled
  in this profile, so credentials saved through a UI are ignored. A missing key fails with
  `MISSING_CREDENTIAL`.
- **Compaction:** `retainRatio` must stay below `thresholdRatio` or the plugin is rejected at load
  (and the run can still exit 0 with no compaction service). Too small a `maxTokens` produces
  `summarization truncated at the token cap (incomplete checkpoint)` in `compaction/end`. Check both
  plugin activation and the checkpoint event.
- **Plugins can exist twice**, globally and in the profile. The loader validates the version it
  resolves. After upgrading the harness runtime, upgrade both copies or the profile can silently
  drop the bundle with an incompatibility warning.

## Session-log recovery

The session is stored at `$DSH_HOME/sessions/<cwd-slug>/session-<id>/session.v4.jsonl.zstd` as
append-only zstd frames. Dsh refuses a corrupt log and reports the byte offset. Restore from a copy,
or truncate to the last complete frame.
