# Synthetic source fixture

- `claude.jsonl` is the one available, parseable store. It includes a
  parent-linked branch to exercise canonical session statistics.
- `codex` is represented by an intentionally absent path created by the eval
  runner; no private or real history is needed.
- `kimi-unparseable.json` is intentionally malformed and must result in
  `unsupported`, never guessed records.
