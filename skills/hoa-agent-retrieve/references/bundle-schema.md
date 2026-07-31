# Retrieval Bundle schema

`hoa-agent-retrieve` owns this contract. Consumers may add fields, but they must
preserve the manifest-first ordering and may not infer absence from an
unavailable source.

## Encoding

The bundle is UTF-8 JSONL. Line 1 is exactly one object with
`"kind":"coverage_manifest"`. Every following line has `"kind":"record"`.
This permits a consumer to reject an incomplete or non-manifested bundle before
it reads sensitive text.

## Coverage manifest

```json
{
  "kind": "coverage_manifest",
  "generated_at": "RFC-3339 UTC timestamp",
  "time_window": {"from": "RFC-3339 timestamp or null", "to": "RFC-3339 timestamp or null"},
  "sources": [
    {
      "agent": "catalog adapter name",
      "status": "available | inaccessible | unsupported | auth-required | not-found",
      "path_probed": ["local paths, retained only in the local bundle"],
      "record_count": 0,
      "note": "bounded machine-readable reason"
    }
  ],
  "deduplication": {
    "input_records": 0,
    "origin_records_removed": 0,
    "branch_records_canonicalized": 0,
    "sessions_with_branches": 0,
    "max_branches_per_session": 0,
    "avg_branches_per_session": 0.0
  }
}
```

`available` means this run read and parsed the listed source, even when its
record count is zero. All other states limit downstream claims to the stated
gap; they never establish that the operator did not perform some behavior.

## Record row

```json
{
  "kind": "record",
  "source": "path-independent source label",
  "agent": "catalog adapter name",
  "project": "short project label or null",
  "project_full": "source-provided project locator or null",
  "session_id": "canonical session identifier or null",
  "timestamp": "source timestamp or null",
  "dur_min": null,
  "role_or_type": "user | assistant | tool | note | unknown",
  "text_or_summary": "minimal source text",
  "locator": {"file": "absolute local path", "line": 1},
  "origin_fingerprint": "sha256 hex",
  "status_or_confidence": "parsed | best-effort",
  "skills": ["optional explicit source list"],
  "mcp": ["optional explicit source list"],
  "agent_types": ["optional explicit source list"],
  "friction_events": ["optional explicit source list"],
  "tools": ["optional structured tool-use name list"]
}
```

Usage fields are emitted only when explicitly list-valued in the source
(`skill_calls`, `mcp_tools`, and `uses_agent` map to their canonical names),
or for declared names in nested `tool_use`/`tool_call` blocks. They are never
inferred from prose.

Locators are intentionally local and may contain private paths. They belong in
the safely-written bundle only, never in a tracked artifact or chat echo.

Each locator has exactly one of these shapes; no null placeholder keys are
emitted:

- `{"file": "absolute local path", "line": 1}` for JSONL and Markdown.
- `{"file": "absolute local path", "offset": 0}` for one JSON object.
- `{"file": "absolute local path", "index": 1}` for JSON array element N.
- `{"file": "absolute local path", "table": "name", "rowid": 1}` for a
  SQLite row selected by its stable `rowid`.

## Deduplication rules

1. **Origin dedup:** hash canonical text, role, timestamp, and project, but not
   the agent. Equivalent
   transcript copies, generated summaries, or synchronized copies that have the
   same content origin are emitted once. The retained row keeps one resolvable
   locator. A later analytical claim requiring two independent evidences needs
    two different `origin_fingerprint` values.

   This deliberately collapses content-identical items in the same context to
   one origin, so synced copies cannot masquerade as two independent origins in
   L2. The rare cost is that genuinely distinct identical texts with no
   timestamp under-count L1; this is conservative and never fabricates
   independence.
2. **Session-branch dedup:** when an adapter exposes a parent/session link
   (`parentId`, `parent_id`, or equivalent), resolve its root with cycle
   protection and write that root as `session_id`. Forked rewind/edit
   continuations therefore form one logical session rather than inflating
   sessions or evidence counts. Their distinct records remain available unless
   origin dedup removes a true duplicate.
3. The manifest exposes `sessions_with_branches`,
   `max_branches_per_session`, and `avg_branches_per_session`. These are based
   on distinct observed branch IDs before canonicalization; missing parent links
   yield zero branch statistics rather than guessed branches.

Filters run after parsing and deduplication. `record_count` is the number of
records actually emitted for that source after filters.
