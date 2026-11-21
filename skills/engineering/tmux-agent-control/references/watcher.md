# One-line watcher

Run from the skill directory in Bash where the authorized tmux server is reachable. Pass the operator's
verified target and pane PID; use a private artifact directory and a background
job with completion notification. Set `MSG` only with send authorization.

```bash
TARGET='<pane-id>' EXPECTED_PANE_PID='<pid>' RESTART_CHECK='<local-executable>' \
  OUT='<private-dir>' MSG='<complete one-line instruction>' bash scripts/tmux-agent-watch.sh
```

`RESTART_CHECK` receives the stable pane ID and pane PID. Resolve the actual
agent process/session and consult its current lifecycle log or state. Return
0 only when the identity is unchanged and no restart, exit, retry or
continuation is pending. Return nonzero when evidence is unavailable, the
process changed or its state is ambiguous. The watcher reruns the check
on each capture and before sending; it does not guess the harness log format.

`MSG` unset means monitor only. `OUT` defaults to the current directory;
`POLL_S`, `IDLE_TIMEOUT_MIN`, and `TURN_TIMEOUT_MIN` default to 15, 65 and
90. `COMPOSER_PREFIX` defaults to the OMP prompt character; verify the exact
prefix on a live idle frame before using another TUI. Wrapped drafts the
watcher cannot read back exactly are refused rather than submitted.

Exit 0 means verified idle, not that the requested work passed. Exit 2 means
identity or capture failure; 3 means refusal or unknown harness state; 4/5
are initial/post-send timeouts; 6 means a send failed; 7 means the evidence
could not be recorded. Inspect `watch.log` and available pane snapshots.
`SENT` confirms both tmux commands succeeded, not that the TUI processed the
message. A failed or interrupted delivery can leave a draft: inspect it
before attempting any further keypress.
