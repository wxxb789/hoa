# Minimal Retrieval Bundle consumed by hoa-introspect

`hoa-introspect` consumes the public contract below. It intentionally does not
define discovery paths, agent adapters, or source catalogs; those belong to
**hoa-agent-retrieve** when it is available.

Narrative report language is configured separately through untracked
`report_language` (default `en-US`); this machine-readable schema, including
numbers, identifiers, and citations, remains unchanged.

## Envelope

A bundle is either one JSON object or JSONL. JSONL begins with the manifest and
then has one normalized record per line.

```json
{
  "coverage_manifest": {
    "generated_at": "2026-01-01T00:00:00Z",
    "time_window": {"from": "2026-01-01", "to": "2026-01-31"},
    "sources": [
      {"agent": "example-agent", "status": "available", "path_probed": "…", "record_count": 2, "note": ""}
    ]
  },
  "records": []
}
```

Manifest `status` is exactly one of `available`, `inaccessible`,
`unsupported`, `auth-required`, or `not-found`. Interpret only `available`
sources. An unavailable source is a coverage gap, never negative evidence.

## Normalized record

Every record must include enough data to re-resolve its origin:

```json
{
  "source": "example-store",
  "agent": "example-agent",
  "project": "sanitized-project",
  "project_full": "optional private value",
  "session_id": "private-id",
  "timestamp": "2026-01-02T03:04:05Z",
  "dur_min": 15,
  "role_or_type": "user",
  "text_or_summary": "private text",
  "locator": {"file": "source.txt", "line": 7},
  "origin_fingerprint": "stable-origin-hash",
  "status_or_confidence": "available"
}
```

`origin_fingerprint` identifies the underlying content origin, not a copy or
session branch. Deduplicated bundles contain one row per origin. A locator is
`file` plus **exactly one** position, matching what `scripts/audit.py` resolves:
a 1-based `line` (JSONL / Markdown), a 0-based byte `offset` (a single JSON
object), a 1-based array `index` (a JSON-array element), or `table` + integer
`rowid` (a SQLite row). `audit.py` re-resolves each kind read-only and drops any
citation whose locator is malformed, carries more than one position, or fails to
resolve.

## Optional deterministic usage fields

The aggregator uses optional explicit fields only; it never guesses from prose:

```json
{
  "skills": ["hoa-introspect", "plugin:review"],
  "mcp": ["memory.search"],
  "agent_types": ["explore"],
  "friction_events": ["retry"]
}
```

An adapter may use `skill_calls`, `mcp_tools`, or `uses_agent` as equivalent
aliases. Missing fields mean “not measured”, not zero usage. See
`facets.md` for exact aggregation semantics.

## Claims sidecar used by `scripts/audit.py`

```json
{
  "claims": [
    {
      "id": "candidate-1",
      "label": "inference",
      "text": "A bounded, evidence-backed statement.",
      "citations": [
        {"origin_fingerprint": "origin-a", "locator": {"file": "a.txt", "line": 2}},
        {"origin_fingerprint": "origin-b", "locator": {"file": "b.txt", "offset": 0}}
      ]
    }
  ]
}
```

The validator retains only claims whose citations are resolvable and represent
at least two distinct origins. It does not judge semantic truth; the report
author still must label conclusions and seek counter-evidence.
