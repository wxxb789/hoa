# Level 3: reconcile with live rules and verify evidence

Read before baseline novelty scoring, verifying raw evidence, or reporting gaps.
Send only redacted state, including the rules baseline, to the endpoint.

Join strong non-routine Round 2 judgments back to their source spans to
restore the `text` stripped by `judge`. Assemble `current-rules-summary.md`
from the target repositories (or curate one manually), then score the restored spans:

```bash
hoa mine baseline --repo /path/to/repo-a --repo /path/to/repo-b \
  --output "$OUT/current-rules-summary.md"
hoa mine select-survivors --stage l1-v2 \
  --scored "$OUT/l1-r2-scored.jsonl" --spans "$OUT/l1-candidates.jsonl" \
  --output "$OUT/l3-candidates.jsonl"
hoa mine judge --stage l3-novelty --baseline-file "$OUT/current-rules-summary.md" \
  --input "$OUT/l3-candidates.jsonl" --output "$OUT/l3-scored.jsonl"
```

If using a custom L1 revision, pass `--rubrics <file>` to `select-survivors`.

Separate the resulting novelty judgments:
- `target_gap` (uncovered actionable gap),
- `route_to_sibling_repo` (valid lesson owned by another repo),
- `already_covered` (prevented by existing docs, hooks, or tests).

Re-open the raw JSONL lines or the read-only SQLite items at the cited ordinals
for every surviving gap:

```bash
hoa history show --spans "$OUT/spans.jsonl" --format readable --context 3 <span-id> [<span-id> ...]
```

`show` prints unredacted evidence for the primary agent (use `--format raw` for
verbatim JSONL lines); never forward it to a decision endpoint. If `--include-memories`
was used, also run `l3-novelty` on `$OUT/memories.jsonl` against the same live rules baseline to surface single-machine memories ready
to graduate into canonical repos. Verify each surviving memory in its source
Markdown file or read-only SQLite row. Verify current repository files before
presenting
`evidence locator -> concrete harm -> live coverage -> minimal fix -> canonical owner`.
