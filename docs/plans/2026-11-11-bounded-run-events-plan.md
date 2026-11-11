# Plan — a run log with a ceiling

Contract: [`docs/goals/2026-11-11-bounded-run-events.md`](../goals/2026-11-11-bounded-run-events.md)
Increment: `bounded-run-events` · branch `feat/bounded-run-events`

The repo's designated plan location is `docs/plans/` (the three archived increments use it). The
contract moves to `docs/goals/archive/` unchanged on close.

## 1. Public / API shape

### 1.1 New `skills/goal-driven-delivery/scripts/adapters/events-writer.py`

One stdlib-only executable, the single implementation of the bound:

```bash
python3 events-writer.py RUN_DIR < agent-events.ndjson > terminal
```

- Reads the agent's `--mode=json` NDJSON stream from stdin, line by line, in binary
  (`sys.stdin.buffer.readline()`), so an invalid UTF-8 byte in an event cannot change the retained
  bytes. Every completed line is passed to stdout unchanged and written to the retained file. This
  is the replacement for `> >(tee events.ndjson)`: the terminal gets the whole stream, the file gets
  the bounded stream.
- Writes into `RUN_DIR`:
  - `events.ndjson` — retained stream (head + optional marker + rolling tail);
  - `events.stats.json` — the sidecar counters;
  - `session.id` — the session id, written atomically the first time a `{"type":"session"}` line is
    seen (preserved byte-for-byte if already present and identical).
- Configuration: `OMP_RUN_EVENTS_MAX_BYTES`. Resolution is exactly `OMP_RUN_ROOT`'s style — the
  `OMP_*` variable wins, else the documented default `8388608` (8 MiB). A missing, non-integer,
  zero or negative value falls back to the default and prints one line to stderr, which `run.sh`
  appends to the run's `stderr.log`; it never means unbounded. `run.sh` captures a supplied value in
  an `export` line so a hand replay uses the same cap.
- Never exits non-zero because of truncation. Any file/sidecar/terminal write error is reported on
  stderr, disables the failed sink, and the process still exits 0 so `pipefail` can only reflect the
  agent's own exit code.
- Nothing host-specific: no absolute path, no model, no user.

#### Retained layout

| Region | Bound | Content |
|---|---|---|
| head | complete lines totalling ≤ 64 KiB (the first line is kept whole if it alone exceeds 64 KiB, so a large `session` line is never lost) | first event line(s), `session` lives here |
| marker | exactly one line, only when something was dropped | `{"type":"truncated","dropped_bytes":<int>,"dropped_lines":<int>}` |
| tail | complete lines totalling ≤ `max_bytes` minus a 128-byte marker reserve | most recent events |

`events_bytes` (retained) = actual file size. `events_bytes_total` = every input byte, including
dropped bytes. The invariant `total_bytes == head_bytes + dropped_bytes + tail_bytes` holds at
every sidecar write; the marker's own bytes are not part of any of the three.

##### Streaming and compaction

- Before the first eviction every line is appended to `events.ndjson` as it arrives: byte-for-byte
  the input, live for `tail -f`.
- On the first eviction the file is rewritten atomically (`events.ndjson.tmp` + `os.replace`) to
  `head + marker + tail`. After that, new lines are appended and the in-memory tail is kept bounded;
  the file is rewritten from the buffers only when it exceeds the final bound by a slack of
  `max(64 KiB, min(1 MiB, max_bytes/8))`, and once more at EOF. A crash between compactions leaves
  the last complete snapshot plus complete appended lines — syntactically valid, at most one slack
  over the final bound. The final EOF rewrite is exact.
- A single tail line larger than the tail budget is dropped whole (and counted); storing it would
  break the bound. It never produces a partial line.

#### Sidecar schema (`events.stats.json`, atomic replace)

```json
{
  "max_bytes": 8388608,
  "head_limit_bytes": 65536,
  "head_bytes": 65532,
  "total_bytes": 24000000,
  "total_lines": 120000,
  "retained_bytes": 8454144,
  "dropped_bytes": 15545856,
  "dropped_lines": 110000,
  "truncated": true,
  "defaulted": false,
  "session_id": "sess-..."
}
```

Updated at least every 64 KiB of input and at EOF/compaction. Atomic replace means a reader never
sees half JSON. `retained_bytes` is `os.path.getsize(events.ndjson)`.

### 1.2 `adapters/omp-run.sh`

- `cmd_start` copies `events-writer.py` into the run directory next to `finalize.py`, and generates:

  ```bash
  "# agent -> stderr.log, stdout -> writer -> terminal; writer -> events.ndjson"
  "$OMP_BIN" ... "$(cat prompt.md)" 2>> stderr.log \
    | python3 events-writer.py RUN_DIR 2>> stderr.log
  ```

  `set -o pipefail` keeps the agent's exit code authoritative because the writer always exits 0.
- `--resume ID` seeds `session.id` before the agent starts. The session-recovery poll reads
  `session.id` first; it scans the log head (`head -c 65536`) only when the sidecar file is absent.
  It no longer relies on the log being complete.
- `state.json` is created with `events_bytes: 0`, `events_bytes_total: 0`,
  `events_truncated: false`, `events_dropped_bytes: 0`.
- `cmd_status` reads the sidecar (falling back to the finalized `state.json` values, then to the
  retained file size) and prints `events_bytes`, `events_bytes_total`, `events_truncated`,
  `events_dropped_bytes` even while the writer is live.
- `cmd_tail` is unchanged: `tail -n` plus `jq` on the retained file; the marker is a valid JSON line
  and renders as `truncated`.
- Header documentation: the bound, its default, the sidecar, the two new run artifacts.

### 1.3 Generated `finalize.py`

- Keeps its contract (`state.json`, `answer.md`, ledger, `finalized` marker).
- Session id precedence: existing `state.session_id` → `session.id` sidecar → scan the retained
  stream → empty.
- Parses the stream through the marker (a `truncated` line is skipped, not counted as an event).
- Counters derived from a truncated stream are labelled partial: `tool_calls_partial`,
  `turns_partial`, `cost_partial` are `true` iff the stream was truncated. `tool_calls`, `turns`,
  `cost_usd` stay numbers, now explicitly partial measurements.
- Writes the four `events_*` fields from the sidecar; if the sidecar is missing, from the marker
  (`events_bytes_total = retained + dropped_bytes`) or the retained file.
- Backward compatible with an existing run directory that has no sidecar: zero truncation, totals
  equal the retained file.

### 1.4 Tests — `tests/run-gdd-selftest.sh`

New section, hermetic:

1. **Writer, under cap**: a synthetic stream (session event + varied JSON lines) fed directly to
   `adapters/events-writer.py`; `cmp` against the input; sidecar says not truncated, zero dropped,
   `total_bytes == input size`; `session.id` written.
2. **Writer, over cap**: same writer, `OMP_RUN_EVENTS_MAX_BYTES` small (e.g. 262144), input larger;
   asserts retained ≤ cap + 64 KiB, exactly one line parses as `type=truncated`, first line is the
   session event, dropped counters equal `input - retained + marker?` via the sidecar invariant, and
   the last retained line is the last input line.
3. **Invalid cap**: `OMP_RUN_EVENTS_MAX_BYTES=0` and `=nope` fall back to 8 MiB with a warning on
   stderr; a small stream stays byte-identical (not unbounded, not truncated).
4. **End to end without tmux**: a stub `OMP_BIN` emits a prepared stream; a stub `tmux` on `PATH`
   runs `run.sh` in the background. Asserts:
   - `tail` renders events and the `truncated` marker;
   - `status` prints the four fields consistent with the sidecar;
   - `finalize` wrote `state.json`, `exit.code`, `finalized`, `tool_calls_partial: true`, and the
     four `events_*` fields consistent with the sidecar;
   - the captured terminal output (writer stdout) equals the input stream, so the bound did not
     touch the terminal.
5. **Start session recovery**: the stub emits a session event; `start` prints the session id from
   `session.id` without depending on the log head. (Covered by the same end-to-end case; the stub
   stream can put a large non-session line first to prove the fallback is not reading line 1.)

`tests/test-omp-run-stale.sh` stays unchanged (it synthesizes run dirs without events).

### 1.5 Docs / release

- `VERSION` 0.1.32 → 0.1.33 via `python scripts/version.py bump` (mechanical skill version mirror).
- `CHANGELOG.md` entry with the semantics and measured numbers.
- `docs/evidence/2026-11-11-bounded-run-events.md`.
- Move the contract unchanged to `docs/goals/archive/`, update `docs/goals/README.md`.

## 2. Edge-case semantics

- **Empty input**: writer creates an empty `events.ndjson` and a sidecar with zeros; succeeds.
- **Final line without `\n`**: preserved exactly; under cap the file matches `tee`. When truncated,
  only complete preceding lines enter the head/tail; the marker always ends in `\n`; the final
  partial line, if retained, stays partial at EOF exactly as the agent wrote it.
- **Line larger than the tail budget**: dropped whole, counted, never stored partially.
- **First line larger than 64 KiB**: kept whole in the head (session recovery wins); documented
  exception to the 64 KiB head budget, still bounded by one input line.
- **Cap ≤ marker reserve**: tail budget is zero; head + marker only; no crash, never unbounded.
- **Invalid/zero/negative/unset cap**: default 8 MiB + one stderr warning.
- **Disk full or unwritable run dir**: warn once on stderr, keep passing stdout through, exit 0;
  `finalize.py` degrades to the retained size.
- **SIGINT/SIGTERM/BrokenPipe**: flush and exit 0; the agent's exit code (or `pipefail`) decides the
  run, not the writer.
- **Concurrent consumers**: `events.ndjson` is only ever appended with complete lines or atomically
  replaced, so a reader sees a valid prefix/snapshot, never a half line.
- **`events_bytes` remains a file size**: it is the retained size; the total moved to
  `events_bytes_total` so no consumer can mistake it for the stream length.
- **Existing oversized run dirs**: untouched; nothing is deleted. Old run dirs without a sidecar
  finalize exactly as before.

## 3. Evidence plan

1. `bash skills/goal-driven-delivery/scripts/tests/run-gdd-selftest.sh` — all cases, with counts.
2. `bash skills/goal-driven-delivery/scripts/tests/test-omp-run-stale.sh`.
3. Judging artifact: a synthetic stream larger than a small cap fed to the writer directly; record
   input bytes, retained bytes, dropped bytes, marker line, head content, and the `state.json` four
   fields beside the sidecar. The artifact directory stays under
   `.tmp-artifacts/bounded-run-events/` (git-ignored).
4. One real opt-in `omp-run.sh start` against a stub `OMP_BIN` emitting a large synthetic stream:
   directory sizes before/after, `status`/`tail` output, session id recovered from the sidecar, and
   the pane capture compared with the input proving the terminal stream stayed complete.
5. All repository gates run sequentially, each with its real exit code: the shell suites, the CI
   python gates, `generate_index --check`, `check_frontmatter`, `check_contract_graph`,
   `vendor_shared --check`, `version.py check/check-bump/check-merge`,
   `check_changelog --base origin/main`, plus the bun suites if bun is available. No measurement or
   benchmark runs beside the test suite.

## 4. Design trade-offs / ambiguities

- **"cap + head region" (judging artifact) vs "under the cap byte-for-byte".** Read as: the
  configured value bounds the rolling tail; the ≤ 64 KiB head is additional, and the marker is
  reserved out of the tail. A stream whose total is ≤ `max_bytes` is always byte-identical; a stream
  between `max_bytes` and `max_bytes + head` is also byte-identical because nothing was evicted.
  Truncation starts only when a byte must actually be dropped. This satisfies both sentences; the
  alternative (cap the whole file including head) would lose the session event.
- **Crash-time size.** A crash between compactions can leave the last valid snapshot plus appended
  complete lines, at most one slack (≤ 1 MiB) above the final bound. Rewriting the whole tail on
  every event would make the writer O(total × cap) and throttle the agent; the contract only
  requires a syntactically valid file after a crash, and the final artifact is exact. Recommended
  and documented.
- **Unset variable warning.** The contract says "unset or non-positive ... falls back ... with a
  warning". A warning for the normal unset case is noisy but literal; the writer emits one
  informational line and the default stays 8 MiB. The alternative (warn only on a supplied invalid
  value) reads the sentence more loosely; I follow the literal text.
- **Session-id sidecar writer.** The writer, not the launcher poll, is the first code to see the
  session event, so it writes `session.id`. `start` then reads that sidecar and only scans the log
  head when the file is absent, which preserves old run directories. The `--resume` value seeds the
  sidecar before the agent starts.
- **Sidecar name.** `events.stats.json` does not collide with `state.json`; it is run-directory
  local, ignored by existing consumers, and atomic.
- **Partial counters.** `tool_calls_partial`, `turns_partial`, `cost_partial` cover every numeric
  sum `finalize.py` derives from the stream. `answer_chars` is a length of retained text, not a
  counter over the whole stream; the answer itself is still written from the retained events.
- **Replayability.** `run.sh` references the run's own `events-writer.py` and captures the cap in an
  `export`, so `bash run.sh` reproduces the same bound after the launcher exits.

## 5. Out of scope

- Deleting, pruning or compressing existing run directories, including today's ~86 MB.
- Bounding `stderr.log`.
- Changing the launcher CLI (`start/status/result/answer/kill/tail`).
- Changing `gdd.py`, stage templates, skill frontmatter semantics, the contract graph or any other
  adapter.
- Writer-side log shipping, rotation across files, compression, or exposing a `--max-bytes` flag.
- Rewriting `events.ndjson` for runs started before this change.

## 6. Close

Bump `VERSION` 0.1.33 with `python scripts/version.py bump`, add the `CHANGELOG.md` entry and the
evidence record with real output/exit codes, move the contract unchanged to `docs/goals/archive/`,
update `docs/goals/README.md`, leave the tree uncommitted.
