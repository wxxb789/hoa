# Goal — a run log with a ceiling

Increment id: `bounded-run-events`
Repo: `wxxb789/hoa` · one run · one PR · mergeable alone

## Why this exists (the failure it answers)

The launcher writes the agent's whole NDJSON event stream with no bound:

```sh
printf ' > >(tee %q) 2> %q\n' "$run/events.ndjson" "$run/stderr.log"
```

Measured on this host today: one 17-minute run produced **23 MB**, another **21 MB**, four runs in one
day totalled **~86 MB**, and nothing ever reclaims them. A long goal (45-minute implement stage) can
therefore fill the disk mid-run, and the failure mode is not "the log is big" — it is that the run dies
and the ledger records a partially written state. There is no cap, no rotation-by-size, and no signal in
`state.json` that the log was ever clipped.

Consumers that make this non-trivial, and which the fix must not break:

- `cmd_status` reports `events_bytes` (a file size, so it silently becomes a *truncated* size);
- `cmd_tail` renders the last N events (`tail -n`);
- `finalize.py` walks the whole file to count tool calls and find the session id;
- `start` resolves the session id from **the head of the file** (`head -n 5 … | jq 'select(.type=="session")'`),
  so naïvely truncating from the front destroys session recovery and `--resume`.

## 1. Observable pass condition

- The event stream is written through a bounded writer that the run directory itself carries (a file
  written next to `finalize.py`), so `run.sh` stays replayable by hand. Configuration:
  `OMP_RUN_EVENTS_MAX_BYTES` (env; default **8 MiB**), same precedence style as `OMP_RUN_ROOT`
  (`OMP_*` variable wins; documented default when unset). No absolute host path is compiled in.
- Under the cap, the file is the byte-for-byte event stream — same content as `tee` produces today.
- Over the cap, the file keeps **a head region and a rolling tail**: the first line(s) (up to 64 KiB,
  which is where the `session` event lives) plus the most recent events, with exactly one marker line at
  the splice point:
  `{"type":"truncated","dropped_bytes":<int>,"dropped_lines":<int>}` — valid JSON, one line, so every
  existing line-oriented consumer keeps working.
- The **total** stream length is always knowable: the writer keeps a sidecar count so `state.json` can
  report `events_bytes` (retained), `events_bytes_total` (everything the agent emitted),
  `events_truncated` (bool) and `events_dropped_bytes` (int). `status` prints them.
- Session-id recovery no longer depends on the head of the log: `start` persists `session.id` when it
  first sees the session event, and the resume path uses that file, falling back to the log only when
  the sidecar is absent.
- `finalize.py` reads through the marker: the run still finalises with a valid `state.json` and
  `exit.code`, and any counter it derives from the stream is reported as partial when the stream was
  truncated (`tool_calls_partial: true`) rather than presented as a total.

## 2. Judging artifact

- A generated run directory from a synthetic event stream larger than the configured cap (feed the writer
  directly; no agent needed) showing: retained size ≤ cap + head region, exactly one marker line, the
  session event still present in the head, and a `state.json` whose four `events_*` fields are consistent
  with the writer's sidecar.
- `bash skills/goal-driven-delivery/scripts/tests/run-gdd-selftest.sh` covering: an under-cap run is
  byte-identical to the input; an over-cap run keeps head+tail+one marker; `tail` still renders; `status`
  prints the truncated fields; `finalize` still writes state.

## 3. Failure control

- The writer never exits non-zero because of truncation, and never blocks the agent's stdout: what the
  agent prints to the terminal stays complete — only the file is bounded.
- A crash mid-write leaves a syntactically valid file (line-buffered writes; never a half line).
- An unset or non-positive `OMP_RUN_EVENTS_MAX_BYTES` falls back to the documented default with a warning
  on the run's `stderr.log`; it never means "unbounded".
- Existing oversized run directories are **not** deleted by this increment (destructive, out of scope).

## 4. Out of scope

- Pruning or compressing historical run directories (`~/.local/state/gdd/runs/**`), including today's 86 MB.
- Bounding `stderr.log` (measured at kilobytes per run; a separate decision if it ever matters).
- Any change to the launcher's CLI contract (`start/status/result/answer/kill/tail`).
- Any change to `gdd.py` or the stage templates.

## 5. Evidence plan

- Selftest cases as above, run by the operator on the final tree, with the real numbers in the evidence
  record (input bytes, retained bytes, dropped bytes, marker line content).
- One real opt-in run of the launcher against a stub command that emits a large synthetic stream, showing
  the directory sizes before/after and that the terminal output stayed complete.

## 6. Mergeable alone

Touches `skills/goal-driven-delivery/scripts/adapters/omp-run.sh`, files it generates into the run
directory, the selftest script, the evidence record and `VERSION`/`CHANGELOG.md`. No skill frontmatter
change, no contract-graph change, no change to any other adapter. Reverting the commit restores today's
`tee` behaviour exactly.
