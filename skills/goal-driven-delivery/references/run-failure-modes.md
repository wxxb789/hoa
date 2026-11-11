# Failure modes of a long stage run

Every rule below was learned from a real run that died or lied. Read this before adding a test to the
selftest, before writing a stage's verification plan, and before trusting a run's own report of itself.

## 1. A test must never be able to kill the process under test

A stage agent runs inside the same tmux server it is testing. One implement run executed
`tmux kill-server 2>/dev/null || true` while cleaning up its scratch sessions; that tore down its own
panes, its stdout pipe broke, and the run died with `EPIPE: broken pipe` eleven minutes in — after
producing several hundred lines of uncommitted work and no `answer.md`.

- Never `tmux kill-server`, and never kill a session you did not create, from inside a stage.
- Tests that need tmux use a stub binary on `PATH` (`fake-tmux` that records its argv) or an isolated
  socket: `tmux -L <unique-name>` or `TMUX_TMPDIR=<temp dir>`.
- Same class of hazard: killing by process name (`pkill -f python`), `kill 0`, and anything that
  addresses "the" server rather than your own handle.

## 2. A hermetic test that passes on your machine may be proving nothing

The selftest claims "no network, no tmux". After a change added a `status` assertion, only the `start`
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
exited **120**, because the interpreter's shutdown flush raised again. The generated `run.sh` uses
`set -o pipefail`, so a successful agent run was recorded as failed whenever the pane went away.

- A process that is honest about a degraded sink must neutralize that sink, not just stop writing to it
  (retarget the descriptor at `/dev/null`; do not rely on the exception having been caught).
- When a wrapper's exit status feeds a `pipefail` pipeline or a finalizer, the wrapper's exit code is
  part of the contract. Test it with the reader closed, not only with a live reader.

## 5. A record nobody can falsify is not evidence

Two review rounds on one increment were spent on the same defect class: a stored artifact whose
*producer* and *validator* disagreed about what a valid record is. First the validator trusted the
stored pass flags; then the recorder happily overwrote a good baseline with one the validator rejects.

- Validate with the same function the consumer uses, and validate **before** writing.
- Prefer one entry point that cannot be bypassed over per-call-site checks.
