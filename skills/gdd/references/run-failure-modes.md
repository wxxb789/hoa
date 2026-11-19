# Failure modes of a long stage run

Every rule below was learned from a real run that died or lied. Read this before adding a test to the
GDD suites (`scripts/tests/test_*.py`), writing a stage's verification plan, or trusting its report.

## 1. A test must never be able to kill the process under test

A stage agent runs inside the same tmux server it is testing. One implement run executed
`tmux kill-server 2>/dev/null || true` while cleaning up its scratch sessions; that tore down its own
panes, its stdout pipe broke, and the run died with `EPIPE: broken pipe` eleven minutes in — after
producing several hundred lines of uncommitted work and no `answer.md`.

- Never `tmux kill-server`, and never kill a session you did not create, from inside a stage.
- Tests for the runner's tmux and Herdr backends use recording stubs, never either live server.
- Same class of hazard: killing by process name (`pkill -f python`), `kill 0`, and anything that
  addresses "the" server rather than your own handle.

## 2. A hermetic test that passes on your machine may be proving nothing

The retired shell selftest claimed "no network, no tmux". After a change added a `status` assertion, only the `start`
invocation received the fake-bin `PATH`; `status` reached the real `tmux`. On the maintainer's machine
(which has tmux) it printed 80/80 — green. On a machine without tmux it raised `FileNotFoundError` and
two checks failed.

- When a test depends on absence, prove absence: shadow the external binary with one that exits 127 and
  run the suite that way.
- Any invocation of the tool under test gets the same stubbed environment; auditing one call site is not
  enough — grep the whole file for the adapter/binary name.

## 3. A crashed run blocks every later stage, and the error does not say so

`gdd.py` refuses to start a stage while a run for the repo is "active":

```
refusing to start: run(s) still active in <repo>: <run-name> (use --force to override)
```

After the crash in §1 the run's `state.json` still said `running`, so this message named a run that had
been dead for hours. Deleting the run's `lock` file does **not** clear it — `active_runs()` reads
`state.json`.

- Recover with the launcher's own path: `<adapter> result <run-name>` reports `stale_recovered: true` and
  rewrites the state to `failed` with a real `exit` and `duration_s`.
- Do this before dispatching again; `--force` hides the problem instead of clearing it.

## 4. "It returned 0" is not "the file is right", and "the file is right" is not "the run succeeded"

The bounded event writer caught a broken terminal pipe, kept writing the file correctly, and still
exited **120**, because the interpreter's shutdown flush raised again. The old adapter generated a
`run.sh` with `set -o pipefail`, so a successful agent run was recorded as failed whenever the pane went away.

- A process that is honest about a degraded sink must neutralize that sink, not just stop writing to it
  (retarget the descriptor at Python's `os.devnull`; do not rely on the exception having been caught).
- When a wrapper's exit status feeds a `pipefail` pipeline or a finalizer, the wrapper's exit code is
  part of the contract. Test it with the reader closed, not only with a live reader.

## 5. A record nobody can falsify is not evidence

Two review rounds on one increment were spent on the same defect class: a stored artifact whose
*producer* and *validator* disagreed about what a valid record is. First the validator trusted the
stored pass flags; then the recorder happily overwrote a good baseline with one the validator rejects.

- Validate with the same function the consumer uses, and validate **before** writing.
- Prefer one entry point that cannot be bypassed over per-call-site checks.
- Resolve a setting once, pass it by value in `env` to child processes, and shell-quote any command you
  print; after writing a record, self-check it with a validator that recomputes the values, or the
  stored record cannot be falsified.

## 6. A tool may resolve path arguments against a base of its own choosing and silently review missing inputs

A review runner resolves the prompt and diff arguments against its `--repo` directory (its own cwd), so
a relative path typed from the orchestrator's directory silently read a different file — or nothing —
while the run still exited 0 and reported a review of the increment. A tool may resolve a path argument
against a base of its own choosing — its repo root, its own cwd, or the caller's cwd — and it is the
tool's documented resolution rule, not whether the tool is out-of-tree, that decides: the launcher
bundled with skill `gdd-route-omp` resolves `--prompt` against the caller's cwd, not the
run's own `--cwd`.

- Resolve each intended input against that documented base yourself and verify it exists and is
  non-empty before launch: the tool may review an empty attachment and still exit 0.
- Pass absolute paths for arguments that accept filesystem paths.
- Any wrapper you ship must exit non-zero before launching the tool when an input is missing or empty.

## 7. Running gates under a bare or shim runtime causes missing-dependency failures and skipped gates

A gate command executed outside the project's dependency-bearing runtime — under a toolchain shim or a
system interpreter — can die on a missing import before it checks anything (for example, checkers that
import a YAML parser fail with `ModuleNotFoundError: No module named 'yaml'`). That reads like a
repository failure when it is an environment one, and it invites the next reader to skip the gate.

- Run each gate command through an interpreter that has its dependencies, and record **which
  interpreter** the run used.
- Treat that error class as an environment failure to be fixed: never as a pass, and never as grounds
  for skipping or waiving the gate.

## 8. A gate must finish before its stage returns, or live outside the stage's teardown boundary

Whether teardown kills what the stage leaves behind is the launcher's cleanup contract, not a universal
law: a launcher that terminates its cleanup group at finalize — a transient `systemd-run` unit, any
unit with `KillMode=control-group`, and the like — takes every process still in that cgroup, so a gate
started with `&` / `nohup` and left behind dies with the unit and no exit code exists anywhere. A
launcher that merely returns may leave that child running, and a killed tmux session can leave a
`nohup` child alive; assuming the gate necessarily died only buys a duplicate gate run.

- Background execution itself is not the hazard; leaving unfinished verification behind is. Run the gate
  in the **foreground** of the stage, or start it in the background and await its completion before the
  stage returns.
- A gate that must outlive the stage needs a lifetime outside the stage's teardown boundary — a new
  session or process group is **not** that boundary: even a double-forked runner stays in
  the launcher's cgroup and still dies when a `KillMode=control-group` unit finalizes. Hand the gate
  **and whatever records its result** to a separate detached unit/job whose id the operator can poll.
- Record the result as an exit code; until one exists, treat "I started the verification in the
  background" in a stage report as **unverified**.

| Mode | Dispatch session | Gateway/service restart | Logout/reboot |
|---|---|---|---|
| `systemd` | Yes | Yes, separate user unit; not a user-manager restart | No |
| `launchd` | Yes | Yes, separate job; not a GUI-domain restart | No |
| `setsid` | Yes | No guarantee against cgroup or job teardown | No |
| `windows` | Yes | Only if the runner is outside the terminating job | No |
| `tmux` (optional, 3.2a or newer) | Yes | Only if the tmux server is outside the gateway's cgroup/job | No |
| `herdr` (optional) | Yes | Only if the Herdr server survives the restart | No |

Launchd was tested only with stubs. The double fork was tested against dispatch-group death on WSL2,
not against a real macOS/BSD service restart.
