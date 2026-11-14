gdd-run-observer shows the runs of the gdd delivery launcher inside Paseo. Every gdd stage runs as
a detached headless agent that outlives the session that started it and writes its own run
directory, so progress is normally invisible in the app. This plugin finds those run directories and
renders them live.

It contributes a workspace panel, a screen reachable from the Command Center, and a settings screen.
The panel lists runs newest first with their state, whether the recorded process is still alive,
elapsed time, turns, tool calls, cost, and the tool that is currently running. Selecting a run
streams its event tail, its answer tail, and the exact paths of the files the launcher wrote. Runs
whose process is gone without a finalize marker are flagged as stale rather than done.

Setup is limited to pointing the plugin at the run root if the defaults do not match. It resolves
the root from its own setting, then GDD_RUN_ROOT, then the documented state directory
(`$XDG_STATE_HOME/gdd/runs` or `$HOME/.local/state/gdd/runs`), then `%LOCALAPPDATA%\gdd\runs` on
Windows. The settings screen always shows the resolved root, where it came from, and every
candidate path, so a wrong path is visible instead of silent. The poll interval and the number of
event lines in the tail are configurable; the defaults are two seconds and eighty lines.

The plugin only reads what a run writes. It never writes into a run directory, never finalizes a
run, and never signals a process; the only command it runs on the daemon host is a process listing
on Windows, used to confirm whether a recorded pid is still alive. It requires no credentials and
logs only counters, tool names, and paths, never prompts, transcripts, or answers. Counters for a
running run come from the retained event log and are marked partial once the launcher has spliced
that log; after a run finalizes, the launcher's own counters are used.
