# Codex history adapter

Read when extracting Codex rollouts or memories, or verifying SQLite evidence.

Pass the configured history directory via `--codex-root` (conventional location:
`.codex` under the home directory). The scope filters match the working directory
(without its Windows extended-length prefix) or the derived project slug. Deny
matches take precedence. Classify checkouts before reading their transcripts.

## Rollouts and threads

- Prefer existing rollout JSONL. Completed items take precedence over duplicate
  raw response records; older rollouts can use `response_item` records directly.
  Without both databases, scan `rollout-*.jsonl`, including under `sessions/` and
  `archived_sessions/`.
- If a rollout is missing, look up its thread in `state_5.sqlite` and reconstruct
  its records from `thread_history_1.sqlite` in `rollout_ordinal` order. SQLite
  locators use those ordinals; JSONL locators use physical file lines.
- Open SQLite read-only. When WAL sidecars are missing or a lock blocks reads,
  use an immutable view to avoid creating or touching sidecars. The warning
  means recent WAL changes may be unavailable.
- Within the selected directory scope, retain user threads, clean `worker` or
  `default` subagents, and subagent threads with tool errors. Omit other clean
  internal roles unless `--include-codex-subagents` is passed.

With the database pair, the incremental cutoff uses `threads.updated_at`;
rollout-only discovery uses JSONL modification time. The extraction manifest
counts included and skipped threads and distinguishes JSONL from SQLite backing.

## Memories and evidence

- With `--include-memories`, extract redacted `memories_1.sqlite` summaries scoped
  to projects using the thread working directories in `state_5.sqlite`.
- `thread_history_1.sqlite#thread=<id>` evidence uses `rollout_ordinal` values,
  not file lines. Open the source read-only; never mutate it or its sidecars.
