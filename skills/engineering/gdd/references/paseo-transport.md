# Native Paseo adapter

This reference applies only to `scripts/adapters/paseo-run.py`. The
[launcher contract](transport.md#launcher-contract) still applies.

`PASEO_BIN` defaults to `paseo` on PATH. An executable path or JSON argv
array overrides it; only the executable is resolved, not the remaining
literal arguments. `--model`/`GDD_MODEL` select `--provider`, and
`--thinking`/`GDD_THINKING` select thinking. Flags win; unset uses daemon
defaults. `--max-time` is refused: a wait timeout is not an execution deadline.

Windows batch shims handle ordinary single-line prompts; newlines and shell
metacharacters are refused before dispatch. For multiline stages configure
native argv. Example for the bundled Paseo 0.15.4 CLI; verify other layouts
and substitute the installed gdd skill directory:

```powershell
$skillDir = '<installed gdd skill directory>'
$install = Join-Path $env:LOCALAPPDATA 'Programs/Paseo'
$resources = Join-Path $install 'resources'
$env:ELECTRON_RUN_AS_NODE = '1'
$env:PASEO_NODE_ENV = 'production'
$env:PASEO_BIN = ConvertTo-Json -Compress -InputObject @(
  (Join-Path $install 'Paseo.exe'),
  '--disable-warning=DEP0040',
  (Join-Path $resources 'app.asar.unpacked/dist/daemon/node-entrypoint-runner.js'),
  'node-script',
  (Join-Path $resources 'app.asar/node_modules/@getpaseo/cli/dist/index.js')
)
$env:GDD_LAUNCHER = Join-Path $skillDir 'scripts/adapters/paseo-run.py'
```

- **Dispatch:** the daemon owns execution; the detached monitor owns local
  observations. `run --no-wait --json` records `agentId` as `agent_id` and
  `session_id`. Dispatch drops `PASEO_AGENT_ID` and `PASEO_WORKSPACE_ID` because
  they override `--cwd`. A mismatched cwd preserves identity but stays unknown
  until inspect verifies the requested directory. Do not retry blindly.
- **Lifecycle:** initializing/running or idle with pending permissions map
  to running; settled idle to done; error to failed; closed to killed.
  Missing identity, unknown status, or unreachable daemon is unknown, not
  success. Running/unknown reserves the worktree until terminal evidence,
  even without a monitor. An idle agent may merely have been interrupted.
- **Claim:** a persistent `refresh` kernel lock serializes observations and
  releases on process exit. Do not mix with old unlinking monitors. A CLI
  call times out in 60 seconds; one claim attempt waits 30. Contention does
  not update state; the monitor waits one second and retries until terminal
  state or marker, not merely until the CLI becomes reachable.
- **Delete:** `kill` uses `paseo delete ID --json`, not `stop`. The receipt
  must say `deletedCount: 1` with exactly that ID. A pre-delete answer is
  provisional until confirmed. Active runs finalize killed/143 with a
  partial-answer flag if captured; already-finalized runs retain outcome,
  timing and marker. Raw receipts are in `cli.ndjson`.
- **Answer:** inspect has no answer field. Use text from
  `paseo logs ID --filter assistant_message --tail 1`, not JSON logs.
  Unavailable text yields a nonzero answer command with the logs argv;
  retry later. Native events are lifecycle transitions, not token/tool
  telemetry. The live Windows 0.15.4 smoke verified one configured path;
  it did not verify native daemons on WSL2, Linux or macOS.
