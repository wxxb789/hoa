# DSH route configuration

For `GDD_AGENT`, `GDD_RUN_ROOT`, and `GDD_RUN_DETACH`, the runner checks the environment, then the
GDD config file, then the default. `start --agent` wins over `GDD_AGENT`. Set `tmux` or `herdr`
only in the environment, not the config file. Other keys resolve from the environment, then the default.

| Key | Resolves | Default |
|---|---|---|
| `GDD_AGENT` | the agent CLI (`--agent` wins) | `omp`; set `dsh` for this route |
| `DSH_BIN` | the harness CLI the runner spawns | `dsh` resolved through `PATH` |
| `GDD_RUN_ROOT` | run/artifact root, the one `gdd.py` exports | `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs` |
| `GDD_RUN_DETACH` | shared runner detach mode; `tmux` needs 3.2a or newer | `auto` |
| `DSH_RUN_PROFILE` | launcher `--profile` | `headless` |
| `DSH_PERMISSION_MODE` | app `--permission-mode`; verify the resulting write boundary | `workspace-write` |
| `DSH_APPROVAL_POLICY` | app `--approval-policy`; any other value is refused | `never` |
| `GDD_RUN_EVENTS_MAX_BYTES` | retained event-log bound | `8388608` |
| `GDD_RUN_START_GRACE_SECONDS` | how long a run with no recorded PID is still starting | `60` |
| `GDD_RUN_STOP_WAIT_SECONDS` | how long `kill` waits for the run to finalize itself | `20` |
| `GDD_RUN_DRAIN_TIMEOUT_SECONDS` | how long the runner waits for dsh's stdout to reach EOF after dsh exits | `30` |

`DSH_PROFILE`, `DSH_PROFILE_DIR`, and `DSH_SESSION_ID` are harness session identity variables exported
into every model shell call. The runner ignores and removes all three from every child it spawns. A
stage dispatched inside a live dsh session therefore cannot inherit the caller's profile or session:
use `DSH_RUN_PROFILE` and pass the adopted session ID on `argv`.

## Flags and input

Leave `--model` and `--thinking` unset, including `GDD_MODEL` and `GDD_THINKING` (which `gdd.py`
turns into flags when set). Headless has no agent presets or these flags. The runner exits 1 before
creating a run directory, with `start: --model is not supported on the DSH route` or the `--thinking`
equivalent. Change a config made for another route rather than expecting an override. The runner's
own `--max-time` deadline is supported (exit 124, `failed`).

`agent_run.py --help` lists the installed routes. The runner invokes dsh as follows and reads the
prompt from stdin:

```text
dsh --profile PROFILE [extra flags] --json [--session-id ID] --permission-mode MODE --approval-policy never -
```

Launcher flags (`--profile`, `--patch`, `--dump-config`) come before app flags. `--patch` after `--json`
or `--session-id` fails with `unknown option '--patch'`. To resume manually with the raw CLI, pass
`--session-id <session-id>` from the recording cwd, repeat `--permission-mode` and `--approval-policy`,
and supply `--add-dir` for extra writable paths. Re-confirm the write boundary first.

The stage asks for JSON in its prompt; dsh has no native schema flag. The stub CLI acceptance tests
are in `scripts/tests/test_dsh_route.py` relative to the skill root.
