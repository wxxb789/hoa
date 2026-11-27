# OMP history adapter

Read when extracting from an OMP sessions root or resolving a branched session.

Pass the configured sessions directory via `--omp-root` (conventional location:
`.omp/agent/sessions` under the home directory). Filters match the child
`<encoded-cwd>` directory name. Classify these directories before opening
transcripts.

- Main sessions: `<timestamp>_<session-uuid>.jsonl` (`type == "session"` line
  carries `cwd` and optional `parentSession` for branched continuations).
- Key records:
  - `type == "message"` with `message.role == "user"`: `message.content[].text`
    (strip injected `<system-reminder>` / `<system-notice>` wrappers when indexing
    human intent).
  - `type == "message"` with `message.role == "assistant"`: `message.content[]`
    contains `text` and `toolCall` (`id`, `name`, `arguments`).
  - `type == "message"` with `message.role == "toolResult"`: `toolCallId`,
    `toolName`, `isError`, and `content[].text`.

JSONL evidence locators are physical line numbers.
