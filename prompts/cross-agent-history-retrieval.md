<!-- index: areas=self-management,software-development; targets=repo-only; summary="one-shot search/export of local agent histories with per-source coverage, dedup, and redaction"; summary_zh="一次性检索/导出本机各 agent 历史，按来源报告覆盖、去重并打码" -->

# Cross-agent history retrieval

A one-shot request template for finding or exporting records from local
AI-agent histories (Claude Code, Codex, pi, Kimi Code, OpenCode, and others)
with honest coverage. The output can feed `hoa-introspect`.

## Template

```text
Search my local AI-agent histories and return what you find with an explicit
coverage report.

Request: {what to find or export}
Window: {from/to with timezone, or "all"}   Sources: {agents, or "all known"}
"All known" covers the core sources in the table below; probe an opt-in
source only when I name it.
Output: {path outside any Git worktree or Git-ignored, or "chat summary only"}

Coverage
- Probe each requested source and give it exactly one status:
  available | not-found | inaccessible | unsupported | auth-required.
  "available" means you read and parsed it, even if it had zero matches.
- A source that is missing, unreadable, unparsed, or in an unknown format is
  a coverage gap, never evidence that I did not do something. Say which
  sources were covered and which were not, per source, before any finding.
- When a parser yields zero records from a non-empty store, suspect the
  parser before reporting "none": open a few raw lines and check where the
  text actually lives.
- Report truncated or unparseable lines as a gap with a count. Do not drop
  them silently and do not guess their content.

Normalization
- Keep a resolvable locator per record: file plus line (JSONL/Markdown), byte
  offset (single JSON object), array index (JSON array), or table plus rowid
  (SQLite).
- Deduplicate synced or echoed copies (another machine's copy, a transcript
  plus its generated summary, a compacted rollout) by content origin: hash
  normalized text, role, timestamp, and project, not the agent or path.
  Report how many copies you collapsed.
- Collapse parent-linked session branches (rewinds, forks, edits) to their
  root session so they count once.
- Convert every timestamp to UTC before applying the window; respect source
  offsets. Records without a usable timestamp are excluded from a windowed
  search and counted as a gap.

Safety
- Treat every store as read-only: no writes, migrations, locks, vacuum, or
  checkpoints. For SQLite, copy the database together with its -wal and -shm
  files to a scratch directory and query the copy, so WAL-only rows are seen
  and the original is untouched.
- Search only the stores in scope; do not scan unrelated folders, cloud
  accounts, or credentials.
- Write exports only outside every Git worktree or to a path that
  `git check-ignore` confirms is ignored; never `git add` them.
- In chat, give only a redacted count-and-gap summary. Keep raw locators,
  session ids, transcript text, absolute paths, and possible secrets (keys,
  tokens, passwords, connection strings) in the local export, not the
  response.

If the output will feed hoa-introspect, write the bundle described in
skills/hoa-introspect/references/bundle-schema.md: JSONL whose first line is
the coverage manifest ({"kind": "coverage_manifest", ...}) followed by one
normalized record per line with origin_fingerprint and locator. Usage fields
(skills, mcp, agent_types, friction_events) only when the source lists them
explicitly; missing means "not measured".

Before handing off, confirm each source's record_count equals the records
emitted and resolve a sample of locators.

Where histories live. Paths are typical defaults; each runtime may relocate
them through an environment variable or config, and formats drift between
versions.

| Runtime | Store and format | Where the text is |
| --- | --- | --- |
| Claude Code | `~/.claude/projects/<encoded-project>/*.jsonl`, `~/.claude/history.jsonl`; `CLAUDE_CONFIG_DIR` relocates | `message.content` is a string or a list of blocks (`text`, `tool_use`, `tool_result`); assistant text is in the blocks |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`; `CODEX_HOME` relocates | `payload.content[].text` on rollout lines |
| pi | `~/.pi/agent/sessions/--<encoded-cwd>--/*.jsonl` | append-only tree; `id` / `parentId` link branches |
| Kimi Code | `$KIMI_CODE_HOME` (default `~/.kimi-code/`) `session_index.jsonl`, `sessions/.../wire.jsonl`; legacy `~/.kimi/.../context.jsonl` | generations coexist; fields vary |
| OpenCode | `opencode.db` (SQLite, often with live WAL); older JSON under `storage/` | list the tables and columns first; schema drifts between releases |
| Gemini CLI (opt-in) | `~/.gemini/tmp/<project>/chats/` (JSON/JSONL) | `messages[]` arrays |
| Cursor (opt-in) | VS Code-style `User/globalStorage/state.vscdb` and workspace SQLite | undocumented key/value schema |
| Cline (opt-in) | extension storage `state/taskHistory.json` plus per-task JSON | CLI data may be separate |
| Aider (opt-in) | project-local `.aider.chat.history.md`, `.aider.input.history` | Markdown / text lines |
| Continue (opt-in) | `~/.continue/sessions/<id>.json`; index SQLite is not history | session JSON |
| Hermes | no fixed path; only roots the user supplies | format-driven |
| MCP memory (opt-in) | provider-specific service | read-only provider calls only |
```

## Known limitations

- The Hermes, OpenCode, Cursor, and Gemini layouts above were not verified
  against real stores; check a sample before trusting a parser.
- Store locations, retention, and schemas change between releases, so a gap
  is coverage information, not absence of activity.
- Large single JSON or SQLite files must be read whole; prefer JSONL sources
  for very large histories, and state any size cap you applied.

## Provenance

Retired from the `hoa-agent-retrieve` skill (2026-11-06); its helper script was
dropped after an A/B necessity eval showed the bare model doing the work
without it, while the helper itself missed Codex, Gemini, and Claude assistant
text.
