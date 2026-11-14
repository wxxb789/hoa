# HOA integration

The optional `gdd-run-observer` plugin displays launcher-owned GDD run artifacts in Paseo. It is a
read-only observer, not a launcher, controller, completion gate, or proof that a stage succeeded.
Its runtime source is imported unchanged from the standalone plugin. That source had no
`HOA-INTEGRATION.md`; this document describes its boundary with HOA.

## Two separate routes

| Route | Execution owner | Plugin's role |
| --- | --- | --- |
| Observe existing GDD launcher runs in Paseo | The launcher selected by HOA, including the default detached OMP adapter, creates and finalizes each run. | Read the shared run root and show state, liveness, counters, event tails, and answer tails. No Paseo-native agent is needed just to observe these artifacts. |
| Execute GDD stages through native Paseo | An explicitly selected native Paseo launcher adapter owns daemon-backed execution and publishes the launcher artifacts. | Optionally display those artifacts through the same file contract. Installing the observer neither selects nor implements this launcher route. |

See the [HOA launcher transport contract](../../skills/gdd/references/transport.md) for launcher
selection, configuration, lifecycle, artifacts, and execution evidence. HOA's `--launcher` /
`GDD_LAUNCHER` selection is independent of plugin installation. The existing default launcher does
not change when the observer is present or enabled.

The plugin registers no agent-creation or agent-control hooks. It never starts a daemon, chooses a
provider or launcher, falls back to another daemon or launcher, starts or resumes an agent, kills a
run, or repairs/finalizes stale artifacts. A missing root is an observation problem, not permission
to launch anything. A launcher remains responsible for producing compatible state and event
shapes; the observer does not translate arbitrary native daemon event protocols.

## Share one run root

Set `GDD_RUN_ROOT` to the same run directory for HOA's launcher and the Paseo daemon process that
hosts the observer. An environment variable set only in the dispatching shell does not change the
environment of an already-running daemon. Alternatively, set the plugin's host-scoped `runRoot`
setting to the exact root the launcher uses. This changes observation only; it does not reconfigure
the launcher.

The plugin does not read HOA's YAML configuration. Its own resolution order, implemented in
[`server/run-root.ts`](server/run-root.ts), is:

1. Non-empty plugin setting `runRoot`.
2. Non-empty `GDD_RUN_ROOT` in the daemon process environment.
3. `$XDG_STATE_HOME/gdd/runs`, when `XDG_STATE_HOME` is set.
4. `$HOME/.local/state/gdd/runs` (using `USERPROFILE` or the OS home directory if `HOME` is unset).
5. `%LOCALAPPDATA%/gdd/runs`, when `LOCALAPPDATA` is set.

An explicit setting or environment root is authoritative even when missing. Otherwise the first
existing candidate wins; if none exists, the home-based default is reported missing. The settings
screen shows the resolved path, source, and candidates. Paths are on the daemon host, not the
client device. For remote hosts or WSL, both producer and observer must see the same files with
paths valid in their own runtime; do not assume equal path strings cross an OS boundary.

## Observed artifacts and RPCs

The store scans `<run-root>/<YYYY-MM-DD>/<slug>/`. The contract is defined by
[`server/run-store.ts`](server/run-store.ts), [`server/state.ts`](server/state.ts),
[`server/events.ts`](server/events.ts), and [`shared/runs.ts`](shared/runs.ts).

| Artifact | Observation |
| --- | --- |
| `state.json` | Declared state, timing, exit code, PIDs, session metadata, counters, and event-loss fields. Missing state is `unknown` unless a `finalized` marker supplies a usable exit code. |
| `events.ndjson` | Event tail, live counters, and current tool, using the supported session/turn/message/tool event shapes and `truncated` splice marker. |
| `events.stats.json` | Retained, total, and dropped event bytes plus truncation status. |
| `answer.md` | Answer presence and a bounded tail for display, not an accepted delivery result. |
| `lock` | Recorded runner/agent PIDs and metadata for process liveness. |
| `finalized` | Settled-run marker and exit code; if declared state is absent or still `running`, the exit code determines the displayed terminal state. |
| `session.id` | Session identifier fallback when `state.json` lacks `session_id`. |

The detail view also lists paths and sizes for `prompt.md`, `runner.out`, and `stderr.log`; it does
not render their bodies. Three read-only RPCs are registered: `runs.list` returns the root and run
summaries, `runs.detail` adds event/answer tails and file paths, and `runs.follow` polls the selected
run's tails. Host settings persistence is separate from these run-data RPCs.

Liveness is separate from state. A finalized marker means `settled`; recorded live PIDs mean
`running`; confirmed dead PIDs without finalization mean `stale`; insufficient evidence means
`unknown`. Windows confirmation uses a background `tasklist` query. The plugin never invokes the
launcher's stale recovery or writes its own finalization marker.

Finalized state counters take precedence when present. Otherwise counters come from the retained
supported event stream or available state values. Spliced streams are marked partial; the observer
does not invent missing turns, tools, or cost. Event tails read at most 256 KiB and answer tails at
most 64 KiB before the line limit is applied. Polling, event vocabulary, and liveness limits remain
those of the imported plugin; see [README](README.md#known-limits).

## Optional installation and trust removal

HOA does not auto-install the plugin or enable the daemon-wide plugin switch. Review its source and
dependencies before opting in. Both runtimes are trusted, unsandboxed code: backend code has the
daemon user's access to files, processes, credentials, and network services; client contributions
run inside the Paseo app. Read-only is an implementation promise, not an enforced sandbox.
Selected event and answer tails are sent to the connected client for display.

Follow [README setup and checks](README.md#commands) for `npm ci` with a repository-contained cache,
typechecking, tests, and installation. The manifest requires Paseo `>=0.15.4`. Commands below are
operator instructions, unverified as part of this source import. From the HOA repository root,
install only after the checks and explicit trust decision:

```bash
paseo plugin install ./paseo-plugins/gdd-run-observer
paseo plugin ls
```

To stop this plugin or remove the installation's trust without affecting other plugins:

```bash
paseo plugin disable gdd-run-observer
paseo plugin remove gdd-run-observer
```

For a non-default daemon, pass `--host <url>` to the lifecycle command. Removing a local directory
installation leaves this checkout's source and launcher run artifacts in place. To stop every
plugin on a daemon, turn off **Settings → Plugins → Enable plugins**; if changing the daemon's
`config.json` directly, set root `pluginsEnabled` to `false` and apply it with `paseo reload`.
Neither disabling nor removing the observer changes HOA's launcher selection or stops GDD runs.
