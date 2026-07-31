# Source catalog

Patterns below use a home-directory placeholder (`~`) or an environment
variable; they are documentation, not machine-specific paths. The agent must
supply each path through untracked config or `--source`; the helper never
redirects or expands the requested scope. Format drift is expected: an adapter
only parses formats explicitly marked **v1 parsed**.

| Adapter | Documented store pattern and format | Read-only method | Drift / v1 status |
| --- | --- | --- | --- |
| Claude Code | `~/.claude/projects/<encoded-project>/*.jsonl`; `~/.claude/history.jsonl` (JSONL) | Read UTF-8 lines; retain line locators | `CLAUDE_CONFIG_DIR` may relocate and fields vary. **v1 parsed JSONL**. |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (rollout JSONL) | Read UTF-8 lines; extract stable text-like fields | `CODEX_HOME`, archives, and event fields vary. **v1 parsed JSONL, best-effort fields**. |
| pi | `~/.pi/agent/sessions/--<encoded-cwd>--/*.jsonl` (append-only JSONL tree) | Read lines; use documented `id`/`parentId` when present | Root/session overrides and compaction exist. **v1 parsed JSONL + parent branches**. |
| Kimi Code | `$KIMI_CODE_HOME` (default `~/.kimi-code/`) with `session_index.jsonl` and `sessions/.../wire.jsonl`; legacy `~/.kimi/.../context.jsonl` (JSONL/JSON) | Read JSONL and JSON only | Kimi Code differs from deprecated kimi-cli; generations coexist. **v1 parsed JSONL/JSON, best-effort fields**. |
| Hermes | No fixed local path is assumed; explicitly supplied JSONL, JSON, Markdown, or recognized SQLite roots are format-driven | Parse only a supplied recognized format | Schema remains unverified, but it is no longer categorically rejected. **best-effort format-driven**. |
| OpenCode | Current releases commonly use a local `opencode.db` (SQLite); older storage may contain JSON under `storage/` | JSON and recognized SQLite tables are opened read-only | JSON-to-SQLite migration and WAL schemas drift. **v1 parses explicit JSON and recognized `opencode.db` tables**. |
| Cursor *(opt-in)* | OS-specific VS Code `User/globalStorage` plus `state.vscdb` and workspace SQLite (SQLite/WAL) | Read only explicitly supplied plain text or recognized SQLite tables | Undocumented schema and workspace mapping. **best-effort; unrecognized schemas unsupported**. |
| Gemini CLI *(opt-in)* | `~/.gemini/tmp/<project>/chats/` (versioned JSON/JSONL recordings) | Requires an explicit configured root; parse only plain JSON/JSONL | Project identifiers, retention, and formats changed. **best-effort JSON/JSONL; otherwise unsupported**. |
| Cline *(opt-in)* | VS Code extension storage with `state/taskHistory.json` and task JSON files; CLI data may be separate (JSON) | Read explicitly configured JSON roots | Extension/CLI stores are separate. **v1 parsed JSON**. |
| Aider *(opt-in)* | Project-local `.aider.chat.history.md` and `.aider.input.history` (Markdown/text) | Read selected Markdown as line records | Location is configurable. **v1 parsed Markdown**. |
| Continue *(opt-in)* | `~/.continue/sessions/<id>.json`, index data may be SQLite | Read explicit session JSON or recognized SQLite tables only | Active migrations; indexes are not histories. **v1 parsed JSON; SQLite best-effort**. |
| MCP memory *(opt-in)* | Provider-specific MCP/knowledge-graph service | Invoke only an explicitly configured read-only provider outside this script | Credentials, schemas, and consent vary. **unsupported by local v1 script**. |

## Status meanings

- `available`: configured or discovered plain-text source parsed successfully,
  including zero-record files and partial parses with an explicit gap note.
- `not-found`: no path matching the documented/configured pattern existed in
  this bounded probe. It is not evidence that the runtime or activity is absent.
- `inaccessible`: enumeration or opening a source was denied by the OS; partial
  records from other files remain available with a gap note.
- `auth-required`: reserved for an explicit remote/MCP provider that reports
  authentication is needed.
- `unsupported`: a source exists but has an unimplemented format, unknown
  schema, or parse failure. It is intentionally not best-guessed.

The v1 helper only opens UTF-8 JSONL, size-capped JSON, Markdown, and SQLite
through a percent-encoded `mode=ro` URI with a bounded query. SQLite locators
use the selected table name and stable `rowid`. Per source it lazily scans at
most 20,000 non-symlink files, 200,000 emitted records, and 512 MiB cumulative
file bytes; a reached cap is reported as `limit-exceeded`. It does not query
cloud history, decrypt blobs, scan unrelated directories, follow symlinks, or
write beside any vendor store.
