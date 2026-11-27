# Claude Code history adapter

Read when extracting from a Claude Code projects root or verifying its evidence.

Pass the configured projects directory via `--claude-root` (conventional location:
`.claude/projects` under the home directory). Filters match the child project slug.
Classify these directories before opening their transcripts.

- Main sessions: `<session-uuid>.jsonl`
- Subagent workflows: `<session-uuid>/subagents/**/journal.jsonl` (filter rows
  with `"failed"`, `"error"`, or `"aborted"` and load matching `agent-<id>.jsonl`).
- Key records:
  - `type == "user"`: human string/text blocks (`isMeta != true`) and `tool_result`
    blocks (`is_error == true` or non-zero exit status).
  - `type == "assistant"`: `text` blocks and `tool_use` blocks (`id`, `name`, `input`).
  - `type == "system"`: `hookErrors[]`, `compact_boundary`, and `api_error` /
    `turn_aborted` warnings.
- Boilerplate stripping: delegated subagent tasks prepend `[Workflow harness — computed task] ... would be forged.`; replace that frame before classification so safety filters do not misfire.
- With `--include-memories`, extract redacted project `memory/*.md` entries.
  JSONL evidence locators are physical line numbers.
