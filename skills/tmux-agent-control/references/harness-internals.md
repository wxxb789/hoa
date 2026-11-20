# Linux and OMP TUI diagnostics (2026-11-21)

Recheck the installed harness's documentation. On Linux, compare process
ancestry and `/proc/<pid>/cwd` to tmux pane metadata. A parent shell's
executable is not the agent binary. A vanished session name can still have
a live pane in a session group; a blank capture can mean a small viewport,
not a dead process. Ask before resizing an operator's pane.

Use the actual running TUI banner to verify a staged self-update. For a
restart, confirm the session lease or equivalent ownership before a resume.
Use the harness's shutdown/quit mechanism, verify the shell prompt before
relaunch, and do not send a launch command into the composer. Interrupt is
not quit. Stop supervised workers via their supervisor, not arbitrary
signals to child PIDs. Do not delete session data by hand.

Use the effective OMP root and current log schema. Correlate the run PID and
session ID with recent exit, retry and scheduled-continuation records;
historical errors alone are not evidence of a current stall. Provider wait
and compaction can make the screen look idle. Read the transcript by parsing
JSONL records where available. Do not collect unrelated messages or expose
content in watcher reports.

A live idle TUI is not disposable. For a headless run, rely on its observed
exit status and output, not quiet terminal state. Storage reclamation is a
separate authorized operation; check live/session ownership first.
