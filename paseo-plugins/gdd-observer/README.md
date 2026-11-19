# gdd-observer

A Paseo plugin that shows **gdd launcher runs** as a first-class Paseo surface. The gdd delivery
loop dispatches every stage as a detached headless agent run that outlives the session that started
it; each run writes its own run directory, so without this plugin that progress is invisible in the
app. This plugin scans the run root and renders every run, live, on a global `runs` screen opened
from its only entry point — a **GDD runs** row in the sidebar footer.

It is a **read-only observer**: it never writes into a run directory, never finalizes a run, and
never signals a process.

## Surfaces

| Surface                     | What it does                                                                                       |
| --------------------------- | -------------------------------------------------------------------------------------------------- |
| Sidebar footer **GDD runs** | The plugin's only entry point: a sidebar footer row, active while the `runs` screen is open, that opens it on any host. |
| Screen `runs`               | Status summary over the whole scan (a proportional state bar, per-state counts, live/stale/flagged, turns/tools/cost), then a newest-first run list with state and liveness badges, the model each run used, elapsed time, turns/tools/cost, current tool, stale warnings; selecting a run opens its live tail, answer tail, and file paths. |
| Settings screen             | Run root override, poll interval, event tail length, the resolved root with its source, and the status summary the screen shows. |

Both layouts are supported: on compact widths the list and the detail stack with a back row, on wide
windows the list sits beside the detail. Every color comes from the host theme, and all text is
translated (`en`, `zh-CN`).

## Data contract

The plugin reads only what a run writes. Run root resolution, in order:

1. the plugin setting `runRoot`;
2. `GDD_RUN_ROOT` in the daemon process environment;
3. `$XDG_STATE_HOME/gdd/runs`;
4. `$HOME/.local/state/gdd/runs` (the documented default);
5. `%LOCALAPPDATA%\gdd\runs` on Windows.

A setting or `GDD_RUN_ROOT` is authoritative: a missing path is reported as missing rather than
silently replaced. Without either, the first path that exists on disk wins, and the UI always shows
the resolved root, its source, and every candidate, so a misconfigured path diagnoses itself.

Each run is `<root>/<YYYY-MM-DD>/<slug>/`:

| File                 | Meaning                                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| `state.json`         | `state` (`running`, `done`, `killed`, `failed`), `exit`, `cwd`, `started`, `ended`, `duration_s`, `model`, `thinking`, `max_time`, `session_id`, `pid`, `agent_pid`, counters, loss accounting. `model` is what the launcher requested: `provider/model`, a link such as `@sol_high`, or absent when it left the choice to the tool's own default. |
| `events.ndjson`      | One agent-CLI JSON event per line: `session`, `turn_start`/`turn_end`, `message_start`/`message_end`, `tool_execution_start`/`_end`/`_update`, and the launcher's `truncated` splice marker. Assistant `message_start`/`message_end` carry the `provider`, `model`, and `api` of the model that produced the message, which is the only place the run records the model it actually used. |
| `events.stats.json`  | Exact byte accounting for the retained log (`total_bytes`, `retained_bytes`, `dropped_bytes`, `truncated`). |
| `answer.md`          | Final assistant text, written when the run finalizes.                                                   |
| `lock`               | `{pid, agent_pid, backend, started_at}` for liveness.                                                    |
| `finalized`          | Present once the run ended; holds the exit code.                                                        |

Derived per run:

- **state**: from `state.json`; a missing file is `unknown`, never success. `finalized` is
  authoritative, so a stale `running` state plus `finalized` is classified from the exit code
  (`0` = `done`, `130`/`137`/`143`/`-2` = `killed`, otherwise `failed`).
- **liveness**: `settled` when `finalized` exists; otherwise `running` while any recorded pid is
  alive, `stale` when every recorded pid is confirmed gone, `unknown` while unproven. Absence of
  `finalized` with a dead pid is reported `stale`, never `done`.
- **counters**: `turns` counts `turn_end`, `tool_calls` counts every `*tool*start*` event, `cost`
  sums assistant `message_end` usage. Running runs are counted from the retained event log while
  tailing, one pass per run shared by every caller, and each pass reads only the bytes appended
  since the last one; once a run finalized, the launcher's own `state.json` counters win. The UI
  labels which source it used. Counters folded from the log are marked partial when the log was
  spliced or held a line that could not be parsed, because they then describe the retained window;
  launcher counters are marked partial only when the launcher says so, since a spliced log says
  nothing about the counters it wrote for the whole run.
- **current tool**: the last `tool_execution_start` without a matching `tool_execution_end`.
- **model attribution**: `requested` is `state.json`'s `model` verbatim, with a concrete
  `provider/model` split at the first `/` and a link (`@flash_max`) kept whole. `observed` is every
  model the retained assistant events name, with the number of messages each answered, in first-seen
  order. A run that requested nothing shows a tool default next to the model that default resolved
  to, which is how a link default such as `@sol_high` becomes visible after the fact.
- **status summary**: the whole scan folded into counts per state and per liveness verdict, plus the
  totals of turns, tool calls, and cost over the runs that report them. It also reports how many
  runs supplied counters, how many are partial, and how many carry a warning, so a total is never
  read as complete when it is only what was reported.
- **loss accounting**: `eventsTruncated` and `eventsDroppedBytes` take the largest value reported by
  `state.json`, `events.stats.json`, and the splice marker.

### Liveness details

On Windows, `process.kill(pid, 0)` is libuv's `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` plus
`GetExitCodeProcess`, so a clean result and `EPERM` both prove the process exists; `EPERM` is never
read as death. An `ESRCH` verdict is unproven, so it is confirmed against one batched `tasklist`
listing, reused for 30 seconds, and run **off the scan path** (the next scan sees the verdict), so
a host with slow process listing cannot stall the screen. A failed listing leaves the previous
verdict in place instead of inventing death; failed attempts also have a 30-second reuse window.
An uncertain inline probe continues refreshing a previously confirmed verdict. A newer inline
proof of life is not overwritten by an older listing's absence, and a listing invoked before a pid
was first observed cannot prove its absence. On POSIX `process.kill(pid, 0)` is authoritative.

With successful OS listings, a conservative disappearance observation budget includes up to 8 seconds remaining
on a listing already in flight, its completion-based 30-second reuse window, another 8-second listing
timeout budget, and up to two scan intervals. This is 50 seconds at the screen's default 2-second
cadence, or 66 seconds with only the settings screen's 10-second cadence. A causally skipped listing
still opens the shared reuse window; it does not trigger a per-pid bypass. This is a scheduling/timeout
budget, not an OS/event-loop response-time SLA. OS failures have no finite confirmation bound; they
never turn uncertainty into `stale`.

## Settings

| Setting          | Default | Bounds        | Meaning                                              |
| ---------------- | ------- | ------------- | ---------------------------------------------------- |
| `runRoot`        | `""`    | any path      | Absolute path on the daemon host; empty resolves the order above. |
| `pollIntervalMs` | `2000`  | 500–60000     | Scan interval for the list and the selected run's tail. |
| `tailLines`      | `80`    | 10–500        | Event lines kept in the tail view.                   |

Settings are stored per host as an ordinary host-side JSON document. The list, the tail, and the
file-path listing are the only RPCs (`runs.list`, `runs.follow`, `runs.paths`); nothing else leaves
the daemon.

The mounted screen and settings surfaces share one list-query polling owner per host query cache.
The fastest requested interval wins; settings still requests 10 seconds. Owner unmount transfers
polling to the remaining surfaces, and unmounting all surfaces stops it. A root-setting save refreshes
the shared scan. A joining surface waits for the active owner's next scheduled refresh, at most
the elected interval (at most 10 seconds when settings is mounted); reopening as the sole observer
still refetches stale data and retries an initial error immediately, including a one-commit surface
replacement. Selected-run following keeps its own configured cadence.

## Trust model

Plugins are trusted, unsandboxed code. On the daemon host this plugin's server subprocess reads run
directories under the resolved root and spawns `tasklist` (Windows only) to confirm process
liveness. It writes nothing, kills nothing, and needs no credentials. Logging is restricted to
counters, tool names, and paths: transcript bodies, prompts, answers, and tokens are never logged.
Client code runs inside Paseo and uses only the plugin SDK and React Native primitives.

## Commands

Requires a Paseo daemon and app satisfying the manifest's `>=0.15.4` requirement. From a clean
checkout, complete the [development setup and checks](#development) first, then run these commands
from the HOA repository root. Installation is opt-in: copying or testing this directory does not
enable it, checkout checks do not certify a running installation, and automated tools must obtain
explicit permission before enabling the daemon-wide plugin switch.

The plugin id changed from `gdd-run-observer` to `gdd-observer`. Install and verify the new id
first, then remove the old one only if it is still installed — `paseo plugin remove` errors when
the id is absent. Settings are stored per plugin id on each host, so the renamed plugin starts
with defaults: reapply the run root override, poll interval, and tail length in the new
**Settings** screen. Observation is read-only, so the launcher's existing run data is preserved.

```bash
# install or refresh the renamed plugin first, from the HOA repository root
paseo plugin install ./paseo-plugins/gdd-observer
paseo plugin reload gdd-observer
paseo plugin ls
paseo plugin logs gdd-observer

# retire the pre-rename id only if it is still installed (remove errors when the id is absent)
paseo plugin remove gdd-run-observer

# stop or remove
paseo plugin disable gdd-observer
paseo plugin enable gdd-observer
paseo plugin remove gdd-observer

# the daemon-wide switch (do not flip to false unless every plugin should stop)
# edit $PASEO_HOME/config.json: "pluginsEnabled": false, then: paseo reload
```

## Development

Use npm with Node.js 20.19.4 or newer, as required by the locked React Native dependency. From a
clean checkout, install from the committed lockfile and keep npm's cache inside the repository's
ignored artifact directory; do not copy `node_modules` or caches from another installation.

```bash
cd paseo-plugins/gdd-observer
npm ci --cache ../../.tmp-artifacts/gdd-observer/npm-cache
npm run typecheck   # tsconfig.json (client + shared, no Node types) and tsconfig.server.json
npm test            # offline client surfaces and server suites against synthetic data
npm test -- --project client   # client behavior only; no Paseo host, window or network
GDD_LIVE_ROOT=<run root> npx vitest run server/tests/live-check.test.ts   # opt-in live check
```

Layout: `shared/` holds the Zod RPC and settings contracts, `server/` the filesystem and liveness
work, `client/` the surfaces (`runs-browser` the browser, `status-strip` the status summary and
badges, `model-card` the model attribution, `labels` the state and liveness key/color maps),
translations, and styles. Tests live in `server/tests/` and `client/tests/`.

Client tests render the actual components with `react-test-renderer` matching React 19.1. The SDK's
translation runtime, RPC validation, and React Query remain real. Only host-injected
React Native/UI primitives, settings persistence, clipboard and toast services are test adapters;
RPC responses are synthetic and never connect to a daemon. The client project fixes the timezone to
UTC and cleans up renderers and query caches after every test. Literal text, accessible props,
interactions and retained event-row instances are asserted instead of snapshots.

These checks do not verify Paseo's widget implementations, native accessibility announcements,
clipboard permissions, pixel layout or platform fonts. The renderer emits React's deprecation
warning; it is a development-only dependency pinned to the current React version. Identical event
occurrences have no source ID: distinct occurrence slots are retained, but eviction of one identical
leading event cannot identify which physical occurrence survived. No host-independent test can
recover identity the source does not supply.

The standalone plugin's evidence archive (behavior-to-test maps, deletion controls, scale
measurements) and its archived goal contracts are not part of this checkout; the suites under
`server/tests/` and `client/tests/` are the executable record.

## Known limits

- **Polling, not subscriptions.** Paseo 0.15 has no plugin subscription transport, so the live tail
  is a bounded poll and polling stops as soon as the last observing surface unmounts. File revision
  checks reuse unchanged event counters and bounded event/answer tails; warmed unchanged polls
  read and parse zero retained-event bytes. Appends extend the cached tails, while replacement,
  shrink and detected splicing invalidate the retained revision. Event and answer windows remain
  capped at 256 KiB and 64 KiB. No file-content TTL delays a changed revision until a later poll.
- **Windowed list, whole-scan facts.** The SDK FlatList mounts a viewport window instead of every
  known run, retaining the same newest-first membership and global status totals. Metadata discovery,
  sorting and the full list payload still scale with total runs. Cold counter/model discovery and
  recounts after replacement/splicing still scale with retained log bytes; no displayed aggregate
  or observed model is dropped to reduce that work. Filesystem metadata is not an atomic multi-file
  snapshot, so concurrent launcher writes can still span scan observations.
- **Writer and filesystem signals.** Incremental tails follow the launcher's append-between-replacement
  or splice protocol. Arbitrary in-place growing rewrites are not that protocol. Revision caches
  depend on file identity, size, mtime and ctime; a same-size rewrite hidden within a coarse filesystem
  timestamp tick may be indistinguishable from unchanged content. Metadata-only changes can cause a
  conservative reread. Offscreen rows mount on the host's scroll/render schedule in batches of 10;
  a variable-height list can require progressive scrolling rather than a single jump to its end.
- **Spliced logs are not always valid NDJSON.** The launcher's compaction can leave a line that
  glues the JSON it cut to the `truncated` marker it inserted. The parser tolerates it, counts it as
  an unusable line, and reports counters folded from that log as partial.
- **Retained-window counters.** At its bound the launcher replaces the log with
  `head + truncated marker + tail`. The plugin then recounts the retained log, so turns, tools, and
  cost describe the retained window only; `state.json` counters take over once a run finalizes.
- **Retained-window model attribution.** The model that actually ran is read from the assistant
  events the log still holds, so a heavily spliced log may name fewer models than the run used, and
  a run with no assistant event shows only what the launcher requested. The model card explains
  where its numbers came from.
- **Unproven liveness reads `unknown`.** On Windows the first scan of a stale run shows `unknown`
  until the background listing confirms it; a run is only ever labelled `stale` after the OS stops
  listing its pid.
- **No kill.** Killing a stale run needs an explicit user action and signaling a run is outside the
  read-only contract, so no `killRun` RPC exists.
- **Answer tails are capped.** `answer.md` and the event window are read from the last 64 KiB and
  256 KiB respectively; larger content is truncated at the head.
