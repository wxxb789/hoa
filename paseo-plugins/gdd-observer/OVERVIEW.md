gdd-observer shows the runs of the gdd delivery launcher inside Paseo. Every gdd stage runs as
a detached headless agent that outlives the session that started it and writes its own run
directory, so progress is normally invisible in the app. This plugin finds those run directories and
renders them live.

The **GDD runs** sidebar footer opens the full list on the selected host. A **GDD** Composer pill
appears when the agent has workers identified by recorded `parentAgentId` lineage. Its popover shows
those workers and opens the filtered list or a run's detail on that same host. The list identifies
the host and summarizes the visible runs with a proportional bar, state, live, stale, and flagged counts, and
the totals of turns, tool calls, and cost. Below it,
runs are listed newest first with their state, whether the recorded process is still alive, the model
(observed when available, otherwise requested), elapsed time, turns, tool calls, cost, and the tool
that is currently running. A cold list does not read event logs for finalized runs with launcher
counters. Selecting a run shows recent assistant progress, tools, failures, and splice markers,
not routine protocol frames. It also shows the answer tail and the exact paths of the files
the launcher wrote, and names the model that answered: what the launcher requested (or the tool
default it left in charge) beside the provider, model id, and API the run's own events report. Runs
whose process is gone without a finalize marker are flagged as stale rather than done.

Setup is limited to pointing the plugin at the run root if the defaults do not match. It resolves
the root from its own setting, then GDD_RUN_ROOT, then the documented state directory
(`$XDG_STATE_HOME/gdd/runs` or `$HOME/.local/state/gdd/runs`), then `%LOCALAPPDATA%\gdd\runs` on
Windows. The settings screen always shows the resolved root, where it came from, and every
candidate path, so a wrong path is visible instead of silent. The poll interval and tail limit are
configurable; the defaults are two seconds and eighty activity items or answer lines. A host with no
active workers and no open list, settings screen, or popover refreshes only when its agent directory changes.

The plugin only reads what a run writes. It never writes into a run directory, never finalizes a
run, and never signals a process; the only command it runs on the daemon host is a process listing
on Windows, used to confirm whether a recorded pid is still alive. It requires no credentials and
logs only counters, tool names, and paths, never prompts, transcripts, or answers. When available,
runner counters take precedence after finalization, after event rotation, and for agents other than
OMP and Pi. Otherwise the observer uses counters from the active event log when present, marking
them partial after rotation or legacy truncation.
