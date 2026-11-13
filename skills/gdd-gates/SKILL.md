---
name: gdd-gates
description: >-
  Run a repository's gates so its counts hold: pin the runtime, fix the worker count, and tell a test
  failure apart from a kill. Use when verifying a delegated agent's gate run before accepting its
  counts, when reproducing a CI result on the operator's host, or when two runs of the same commit
  disagree. Do not use for the repo's own test design, or for writing a new file-integrity gate.
metadata:
  version: "0.1.49"
  areas: "software-development"
  targets: "runtime-agnostic"
  summary: "run a repo's gates with a pinned runtime and worker count, and tell a kill apart from a failure"
  summary_zh: "跑仓库门禁：钉运行时、定并行数、把被 kill 和真失败分开"
  kind: "mechanism"
---

# Executing a repo's gates

A gate run is evidence only if you can state three things about it: **which runtime it used**, **how
much parallelism it used**, and **whether the exit code came from the test or from the kernel**. Most
wrong "the tests are red" / "the tests are green" claims come from losing one of those three.

## When to Use

- Verifying a delegated agent's gate run before accepting its counts.
- Reproducing a CI result on the operator's host.
- A suite that died with `exit -9`, printed nothing, or reported a count you cannot bind to a runtime.

Not for designing a gate (that is `structural-validity-gates`) or for the staging protocol around a
delivery (that is `gdd`).

## Procedure

1. **Find the repo's pin and put it first on `PATH`.** `.nvmrc`, `tool-versions`, `global.json`,
   `rust-toolchain.toml`, or the venv the repo activates. An ambient interpreter below the floor fails
   in a way that reads like a code defect; an ambient interpreter *above* the pin silently produces
   counts CI will never see. The version string printed into the same log as the counts is the cheapest
   insurance there is, and it is the only way to catch a *delegated* run whose harness resolves its own
   runtime — an agent reporting "the stated version was unavailable" measured a different engine than
   the repo ships, so re-run it yourself before accepting its counts.
2. **Read the gate command before you run it.** `pnpm run verify` is usually a chain — lint, type check,
   a build with extra flags, then the test runner — and a wrapper such as `build:fixture` may build a
   corpus, run scans, spawn its own test runner with its own worker count, then restore the previous
   build. The log tells you which phase you are in; the script's source tells you what that phase does
   to the tree.
3. **Size parallelism to the host.** One test file that drives a browser or a native codec can peak
   above 1 GB. Four workers on an 8 GB host that is also running an agent gateway is a race the kernel
   wins. Default to fewer workers locally than CI uses, and state the number.
4. **Capture artifacts, not the tail.** Exit code per command, the suite's own summary line
   (`Test Files … / Tests … passed | skipped`), peak RSS (`/usr/bin/time -f 'rss_kb=%M exit=%x'`), and
   the log path. A count with no log path cannot be re-checked by anyone else.
5. **Distinguish a kill from a failure.** `exit -9`/`-15` with no test output, plus
   `systemd-oomd killed N process(es)` or `Killed process … (node)` in `journalctl --user`, means the
   host ran out of memory. That is not a regression and must never be reported as one — re-run at 1
   worker on a quiet host before drawing a conclusion.
6. **When a wrapper hard-codes a worker count you cannot override, execute its steps yourself.** Run
   the build and scan steps it lists, then the suite with your worker count and the same artifact
   selector, then the wrapper's own restore step. The tree must end in the state the wrapper would have
   left, or the next command fails for a reason you created.
7. **Take liveness from the launcher, not the process table.** `pgrep -f "<pattern>"` matches the
   wrapper shell's own command line, which contains the pattern, so it reports `RUNNING` long after the
   job died. Use the launcher's status, the run's `state.json`/`exit.code`, or the process handle the
   background tool returns.
8. **One OS of a matrix failing is a different runtime, not a flaky test.** The passing rows say the code is
   correct under one set of path, permission and case-sensitivity rules; the failing row names the
   assumption that is code-level. Read the failing job's own log (`gh run view <run-id> --log-failed`) and
   quote the first error the *gate* printed, not the test names it cascaded into. Fix the assumption in one
   shared helper, and pin it with a test that takes the GOOS as a parameter, so the local suite proves the
   emitted string while CI proves the platform. The recurring win32 assumption classes — path literals,
   `filepath.Abs`, JSON-escaped separators, signal delivery, IPv6 brackets — are catalogued in
   [`references/windows-matrix.md`](references/windows-matrix.md).

## Reporting

One line per command: command, exit code, real counts, runtime, worker count, log path. Anything you
could not run is "not run", never "presumably passes". When a number moved against the previous tree,
say which side you measured it on. **Compose anything that quotes a count — commit message, PR body,
hand-over — after this run's output is in hand.** A count written from memory, from the previous
head, or from a delegated agent's summary becomes an immutable wrong claim once pushed; correct a
shipped one in a follow-up comment with the verified value instead of amending the published commit.

## Pitfalls

- **A green suite on an unpinned runtime is not a pass.** It is a pass for a runtime the repo does not
  ship, and CI will answer differently.
- **A suite that prints nothing and exits non-zero is usually memory, not logic.** Read the kernel log
  before reading the code.
- **The wrapper's restore step is part of the gate.** A build wrapper that leaves a fixture corpus in
  `dist/` makes the next ordinary test run fail for a second, unrelated reason — an interrupted
  operator run is what creates that state, so finish the sequence.
- **An artifact-selector suite is only meaningful against that artifact's build.** The env var that
  selects a fixture corpus changes the *expectations*, not the `dist/` on disk: run the suite without
  rebuilding for that corpus and dozens of tests fail on missing routes, which reads exactly like a
  regression you introduced. Build the corpus, run the suite with your worker count, then run the
  wrapper's restore step.
- **Two heavy suites at once is an OOM of whichever loses — and the casualty is often the other
  agent.** The full suite you run to verify an increment and a delegated agent's build/scan/test chain
  compete for RAM on a host sized for one; when the agent's session scope is killed, its run dies with
  no exit code while every status file still says `running`. Serialize on a sized-for-one host: your
  measurements go before the dispatch or after the report, never beside it. If a stage went quiet when
  your suite started, check `systemd-oomd` in the journal and recover the run by session id rather than
  re-dispatching it (`gdd-recover`).
- **A build running while the suite reads its own output turns green tests red.** When tests assert on the
  live build artifact (`dist/`, a generated inventory, a page index), a build in a parallel shell rewrites
  it mid-run and a dozen unrelated tests fail on missing or half-written routes — a failure shape that
  reads exactly like a regression you introduced. Build first, run the suite alone, and re-run one failing
  file alone before blaming the change.
- **A path handed to something that parses it as a URI is the classic cross-OS defect.**
  `url.URL{Scheme: "file", Path: "C:\\Users\\x\\db.sqlite"}` serialises to `file:C:%5CUsers%5C…`, whose
  "authority" is `C:`, and SQLite answers `invalid uri authority`; the same shape breaks image loaders,
  ffmpeg filters and anything that accepts a `file:` spec. Emit `file:///C:/Users/…` — forward slashes, a
  leading slash before the drive letter, and a UNC path kept in the path component because SQLite rejects
  every authority except an empty one or `localhost` — put the formatting in one helper, and assert both
  spellings from a GOOS parameter.
- **A gate that names the failing item but not its message costs a CI round-trip per failure.**
  `go test -json` already carries each failing test's own output; a summary that keeps only
  `pkg/Test: failed` discards the `_test.go:NN: message` line the fix needs. Emit each failing item's
  own output tail (bounded per item, e.g. last 12 lines) under its header, and make sure the
  top-level renderer's line cap cannot cut the last failure's reason (40 lines truncates four failures
  × 13 lines). Pin it in the harness self-test: a gate that drops the message must fail the self-test.
- **A count you changed in code is stale in the docs, and both get cited as evidence.** Adding a gate or
  a self-test case moves a number the prose repeats ("16 gates", "22 cases over 16/16 gates"); the doc
  then contradicts the run that proves it, and the hand-over quotes whichever it read last. Grep every
  doc for the old figure in the same edit that changes the suite (`grep -rn '<old> gates\|<old> cases'\
  docs README.md`), and prefer quoting the runner's own summary line as the number's single home so
  there is nothing to keep in sync.
- **Prefer one clean 1-worker run to three killed 4-worker attempts.** The count must come from a run
  that finished, and never report a cross-OS matrix green from a local run — say which rows only CI can
  prove.
- **A gate that parses a child runner's machine-readable output must control where that runner writes
  it.** Runner majors move the report: `vitest --reporter=json` writes `.vitest/json/output.json`
  instead of stdout, so a gate that reads stdout fails closed with "missing … reporter output", and the
  stray directory lands in the tree that same run certified clean — which a second gate then reports as
  candidate identity drift. Pass an explicit destination outside the repository (`--outputFile` into an
  `mkdtemp` dir), read that file, delete it in `finally`, and keep missing / unreadable / empty as
  distinct failure details instead of one "parse failed".
