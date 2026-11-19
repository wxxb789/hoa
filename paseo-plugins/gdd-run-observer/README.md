# gdd-run-observer

A Paseo plugin that shows **gdd launcher runs** as a first-class Paseo surface. The gdd delivery
loop dispatches every stage as a detached headless agent run that outlives the session that started
it; each run writes its own run directory, so without this plugin that progress is invisible in the
app. This plugin scans the run root and renders every run, live, as a workspace panel, a global
screen, and a Command Center entry.

It is an **optional, read-only observer**, not a launcher: it never writes into a run directory,
never finalizes a run, and never signals a process. Adding HOA to a checkout does not install or
activate this plugin, enable plugins on a daemon, or select a launcher. See
[HOA integration](HOA-INTEGRATION.md) for the observation and native Paseo execution routes.

## Surfaces

| Surface                 | What it does                                                                                       |
| ----------------------- | -------------------------------------------------------------------------------------------------- |
| Workspace panel `runs`  | Newest-first run list with state and liveness badges, elapsed time, turns/tools/cost, current tool, stale warnings; selecting a run opens its live tail, answer tail, and file paths. Selection survives tab restoration. |
| Screen `runs`           | The same browser, reachable from any host through the Command Center item **Open GDD runs**.        |
| Settings screen         | Run root override, poll interval, event tail length, and the resolved root with its source.         |

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
| `state.json`         | `state` (`running`, `done`, `killed`, `failed`), `exit`, `cwd`, `started`, `ended`, `duration_s`, `model`, `thinking`, `max_time`, `session_id`, `pid`, `agent_pid`, counters, loss accounting. |
| `events.ndjson`, `events.1.ndjson` | Current and previous NDJSON event segments. The current segment starts with a `truncated` marker only after bytes have been dropped. The plugin tails only the current segment. |
| `run.json`, `runner.log` | Invocation and runner diagnostics, available on disk for inspection. |
| `answer.md`          | Final assistant text, written when the run finalizes.                                                   |
| `finalized`          | Present once the run ended; holds the exit code.                                                        |

The shared runner does not write `events.stats.json`, `lock`, `session.id`, or `runner.out`.
The observer still understands these legacy adapter artifacts where present.

Derived per run:

- **state**: from `state.json`; a missing file is `unknown`, never success. `finalized` is
  authoritative, so a stale `running` state plus `finalized` is classified from the exit code
  (`0` = `done`, `130`/`137`/`143`/`-2` = `killed`, otherwise `failed`).
- **liveness**: `settled` when `finalized` exists; otherwise `running` while any recorded pid is
  alive, `stale` when every recorded pid is confirmed gone, `unknown` while unproven. Absence of
  `finalized` with a dead pid is reported `stale`, never `done`.
- **counters**: `turns` counts `turn_end`, `tool_calls` counts every `*tool*start*` event, `cost`
  sums assistant `message_end` usage when counting events. The runner's `state.json` counters
  take precedence after rotation, at finalization and for non-OMP/Pi headless routes.
  A lifecycle-only stream (such as the native adapter's `paseo_status` transitions)
  supplies no measurements: metrics remain unavailable (`null`, source `none`) unless the
  launcher records counters. Recognized agent instrumentation establishes event counters,
  including measured zeros. The UI labels the source and marks event-derived counts partial
  when a rotated segment exists or truncation is reported.
- **current tool**: the last `tool_execution_start` without a matching `tool_execution_end`.
- **loss accounting**: `eventsTruncated` and `eventsDroppedBytes` take the largest value reported by
  the runner's `events_*` state fields, supported truncation markers, and legacy `events.stats.json`.

### Liveness details

On Windows, `process.kill(pid, 0)` is libuv's `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` plus
`GetExitCodeProcess`, so a clean result and `EPERM` both prove the process exists; `EPERM` is never
read as death. An `ESRCH` verdict is unproven, so it is confirmed against one batched `tasklist`
listing, cached for five seconds, and run **off the scan path** (the next scan sees the verdict), so
a host with slow process listing cannot stall the panel. A failed listing leaves the previous
verdict in place instead of inventing death. On POSIX `process.kill(pid, 0)` is authoritative.

## Settings

| Setting          | Default | Bounds        | Meaning                                              |
| ---------------- | ------- | ------------- | ---------------------------------------------------- |
| `runRoot`        | `""`    | any path      | Absolute path on the daemon host; empty resolves the order above. |
| `pollIntervalMs` | `2000`  | 500–60000     | Scan interval for the list and the selected run's tail. |
| `tailLines`      | `80`    | 10–500        | Event lines kept in the tail view.                   |

Settings are stored per host as an ordinary host-side JSON document. The list, the tail, and the
file-path listing are the only RPCs (`runs.list`, `runs.follow`, `runs.detail`); nothing else leaves
the daemon.

## Trust model

Plugins are trusted, unsandboxed daemon and client code. Installing this plugin means trusting its
source and dependencies: backend code has the daemon user's access to files, processes,
credentials, and network services; client code runs inside the Paseo app. Read-only describes this
implementation, not a sandbox or permission restriction.

On the daemon host this plugin's server subprocess reads run directories under the resolved root
and spawns `tasklist` (Windows only) to confirm process liveness. It writes no run artifacts,
kills nothing, and needs no credentials. Logging is restricted to counters, tool names, and paths:
transcript bodies, prompts, answers, and tokens are never logged. Selected event and answer tails
are returned to the client for display, so run contents must be appropriate for the connected
client. Client code uses only the plugin SDK and React Native primitives; Paseo persists plugin
settings separately from run artifacts.

## Commands

Requires a Paseo daemon and app satisfying the manifest's `>=0.15.4` requirement. For checkout
preparation and checks, use npm with Node.js 20.19.4 or newer, as required by the locked React Native
dependency. From a clean checkout, complete the [development setup and checks](#development) first,
then run the commands below from the HOA repository root.

Installation is opt-in. Review the trust model and source before enabling **Settings → Plugins →
Enable plugins** on the intended daemon. This daemon-wide switch affects every plugin; automated
tools must obtain explicit permission before enabling it. Merely copying or testing this directory
does not enable it. Checkout typechecking and tests do not certify a running installation. Install
and verify the plugin on the intended host; the commands below are not evidence of an installation.

```bash
# install / refresh after source edits, from the HOA repository root
paseo plugin install ./paseo-plugins/gdd-run-observer
paseo plugin reload gdd-run-observer
paseo plugin ls
paseo plugin logs gdd-run-observer

# stop or remove
paseo plugin disable gdd-run-observer
paseo plugin enable gdd-run-observer
paseo plugin remove gdd-run-observer

# the daemon-wide switch (do not flip to false unless every plugin should stop)
# edit $PASEO_HOME/config.json: "pluginsEnabled": false, then: paseo reload
```

## Development

From the HOA repository root, prepare the clean checkout with the committed lockfile, then check
both runtime boundaries and the test suite. Keep npm's cache inside the repository's ignored
artifact directory; do not copy `node_modules` or caches from another installation.

```bash
cd paseo-plugins/gdd-run-observer
npm ci --cache ../../.tmp-artifacts/gdd-run-observer/npm-cache
npm run typecheck   # tsconfig.json (client + shared, no Node types) and tsconfig.server.json
npm test            # vitest: state mapping, event parsing, tailing against synthetic run dirs
```

Successful typechecking exits zero; `npm test` should pass the synthetic tests. The live test is
skipped unless `GDD_LIVE_ROOT` is set. To opt in on a host with an existing run root, stay in the
plugin directory and use a shell-appropriate environment assignment, for example in Bash:

```bash
GDD_LIVE_ROOT="$GDD_RUN_ROOT" npm test -- server/tests/live-check.test.ts
```

Set `GDD_RUN_ROOT` to a real root containing runs before that live check. It reads real run files
and probes process liveness; it does not install the plugin or launch a run. Return to the HOA root
with `cd ../..` before using the installation command above. After installation, `paseo plugin ls`
should report `gdd-run-observer` as `running`; open **Open GDD runs** in the Command Center and
confirm the resolved root in settings. If it is wrong, set `runRoot` to the launcher's root rather
than installing another launcher or starting a daemon from this plugin.

Layout: `shared/` holds the Zod RPC and settings contracts, `server/` the filesystem and liveness
work, `client/` the surfaces, translations, and styles. Tests live in `server/tests/`.

## Known limits

- **Polling, not subscriptions.** Paseo 0.15 has no plugin subscription transport, so the live tail
  is a bounded poll that reuses a per-run byte offset: each tick reads only what the launcher
  appended, and polling stops as soon as the surface unmounts.
- **Retained event tail.** The runner moves the previous event segment to `events.1.ndjson`
  and overwrites that segment on the next rotation. The observer does not replay the previous
  segment. Without runner counters, the visible event totals are therefore partial after rotation.
- **Unproven liveness reads `unknown`.** On Windows the first scan of a stale run shows `unknown`
  until the background listing confirms it; a run is only ever labelled `stale` after the OS stops
  listing its pid.
- **No kill.** Killing a stale run needs an explicit user action and signaling a run is outside the
  read-only contract, so no `killRun` RPC exists.
- **Answer tails are capped.** `answer.md` and the event window are read from the last 64 KiB and
  256 KiB respectively; larger content is truncated at the head.
