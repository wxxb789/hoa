# Known limitations

- The Hermes, OpenCode, Cursor, and Gemini adapters have not been tested
  against real operator stores. Doing so would require handling the operator's
  PII, which this public skill and its synthetic evals deliberately avoid.
- The SQLite reader is generic-schema: it recognizes tables with documented
  text-bearing columns rather than vendor-specific schemas.
- All adapters are best-effort. Store locations, retention, and schemas may
  drift, so a manifest gap is coverage information rather than evidence of no
  activity.
- Memory is bounded, not fully streamed. JSONL and Markdown stores are read
  line-by-line, but a JSON or SQLite store (and the audit's `index` re-resolution)
  reads a whole file capped at 64 MiB, under a 512 MiB per-source budget. This
  bounds memory rather than assuming everything fits at once, but a single
  pathological file up to the cap is still read in full; prefer JSONL for very
  large histories.
