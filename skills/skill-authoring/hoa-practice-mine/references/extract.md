# Extract redacted history

Read before extracting skeletons and spans, or resuming from a cutoff or cursor.
Apply the scope, redaction, and read-only gates before opening transcripts.

## Select sources

Read only the adapters for the sources you intend to mine:

| If the source is | Read |
|---|---|
| Claude Code projects, failed workflow subagents, or project memories | [Claude Code](sources/claude-code.md) |
| OMP sessions or branched continuations | [OMP](sources/omp.md) |
| Codex rollouts, SQLite history, subagents, or memories | [Codex](sources/codex.md) |

Supply only the roots in scope. Use `--allow-regex '<pattern>'` and/or
`--deny-regex '<pattern>'` when personal and work projects share a supplied root.
For additional local redaction of secrets or fixed workflow frames, add
`--redact-regex`. Do not send unredacted evidence to the endpoint.

## Run the extractor

The Bash function uses the packaged CLI via `uvx`. In a local checkout use
`uv run hoa ...` instead, or omit the function if `hoa` is installed. Adapt
variable syntax for PowerShell or other shells.

```bash
hoa() { uvx --from git+https://github.com/wxxb789/hoa hoa "$@"; }
OUT="<scratch-dir>"   # outside the worktree or confirmed gitignored

hoa history extract \
  --claude-root "<claude-projects-root>" \
  --omp-root "<omp-sessions-root>" \
  --codex-root "<codex-history-root>" \
  --include-memories \
  --cursor-file "$OUT/extract-cursor.txt" \
  --min-lines 12 \
  --out-dir "$OUT"
```

Remove flags for any source you are not mining. Omit `--include-memories` when
project memories are not in scope. `--min-lines 12` skips short Claude Code and
OMP main JSONL sessions up front, including one-turn probes.

For a follow-up run, add `--since <ISO date>` to keep only sessions active since
then (JSONL file modification time; `threads.updated_at` for database-backed
Codex discovery). Alternatively use `--cursor-file <path>` to read and update an
incremental watermark automatically when `--since` is omitted. The manifest
records the cutoff. The extractor streams skeletons and spans to disk as it
parses sessions.

## Confirm the outputs

- `skeletons.jsonl` — one compact trajectory skeleton per session (`~300–600`
  tokens): all user turns, non-zero tool/hook errors, and assistant boundary
  claims, with clean read/edit runs folded. Includes failed workflow subagents.
- `spans.jsonl` — overlapping causal turn-windows (`--max-span-chars`, two-step
  overlap so root cause and resolution are not severed), tagged with `has_pivot`
  and exact source locators. Identical spans across branched sessions are
  deduplicated by content hash by default (`--no-dedup-spans` disables this).
- `memories.jsonl` — with `--include-memories`, redacted Claude project memories
  and scope-matched Codex memory summaries ready for `l3-novelty` scoring against
  live rules.
- `extract-manifest.json` — coverage by root, including Codex included/skipped
  threads and counts backed by JSONL or SQLite. For JSONL spans, locators use
  `file:Lstart-Lend` with physical lines. SQLite locators use
  `thread_history_1.sqlite#thread=<id>` and `rollout_ordinal` values, not file lines.
