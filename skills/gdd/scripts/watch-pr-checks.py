#!/usr/bin/env python3
"""watch-pr-checks.py — bounded CI poller for one PR, with infra-only auto-rerun.

Cross-platform port of `watch-pr-checks.sh`; same semantics, same exit codes, no
bash. Why it exists at all: a job that dies in under a minute on a download step
(curl 5xx while installing a pinned binary) is infra, not your diff. Rerunning it
by hand costs a round trip per occurrence; rerunning it unbounded turns a broken
job green-adjacent by attrition. This bounds both.

Usage:
    watch-pr-checks.py <PR> [max_reruns] [max_polls] [logfile]
    defaults: max_reruns=2  max_polls=40  logfile=<repo>/ci-watch-<head7>.log

Exit: 0 all checks passed and the PR is MERGEABLE CLEAN · 1 a check failed for
real · 2 still pending, or the PR head moved while watching · 3 usage or
environment error.

Configuration (the `.sh` hard-codes these; they are knob-tunable here so a test can
drive the whole state machine in a second, and an operator can widen the window on
a slow runner):

    WATCH_POLL_SECONDS         wait between polls (default 30)
    WATCH_FAST_FAIL_SECONDS    a failing job shorter than this is infra (default 60)
    WATCH_RERUN_WAIT_SECONDS   wait after a rerun before polling again (default 20)
    GH_BIN                     the GitHub CLI (default: gh, resolved through PATH)

The log records every poll and its raw output, plus what was decided and why — the
`gh run rerun <id> --failed` line names the job and its duration, so a reader can
disagree with the infra call instead of trusting it.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

IS_WINDOWS = os.name == "nt"
# `gh pr checks` prints one row per check: name, state, duration, optional link.
ROW_RE = re.compile(r"^[^\t]+\t(pass|fail|pending|skipping)")
NO_CHECKS_RE = re.compile(r"no checks reported|no check runs found", re.IGNORECASE)
RUN_ID_RE = re.compile(r"runs/(\d+)")
PENDING_RE = re.compile(r"pending|queued|in_progress")
STATE = {"pass", "fail", "pending", "skipping"}


def env_seconds(key, default):
    raw = (os.environ.get(key) or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return float(default)
    return value if value > 0 else float(default)


def hidden_flags() -> int:
    """CREATE_NO_WINDOW on Windows: a poller must not flash a console per `gh` call."""
    return 0x08000000 if IS_WINDOWS else 0


def command_for(binary, args):
    """argv for the GitHub CLI: a Windows `.cmd`/`.bat` shim runs through %COMSPEC%."""
    if IS_WINDOWS and os.path.splitext(binary)[1].lower() in (".cmd", ".bat"):
        return [os.environ.get("COMSPEC") or "cmd.exe", "/c", binary, *args]
    return [binary, *args]


def run(argv, cwd=None):
    """Run a helper, capturing everything; never inherits the caller's console state."""
    return subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        creationflags=hidden_flags(),
    )


def rerun_seconds(duration: str) -> tuple:
    """'1m5s' -> (65, True) · '32s' -> (32, True) · 'weird' -> (0, False).

    The reference script reads a missing duration as 0, which makes the job
    infra-eligible; the boolean here is what lets the log say so out loud.
    """
    minutes = re.search(r"(\d+)m", duration or "")
    seconds = re.search(r"(\d+)s", duration or "")
    if not minutes and not seconds:
        return 0, False
    return (int(minutes.group(1)) * 60 if minutes else 0) + (int(seconds.group(1)) if seconds else 0), True


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or len(argv) > 4:
        print(
            "usage: watch-pr-checks.py <PR> [max_reruns] [max_polls] [logfile]",
            file=sys.stderr,
        )
        return 3
    pull_request = argv[0]
    try:
        max_reruns = int(argv[1]) if len(argv) > 1 else 2
        max_polls = int(argv[2]) if len(argv) > 2 else 40
    except ValueError:
        print(
            "watch-pr-checks: max_reruns and max_polls must be integers; "
            f"got {argv[1:3]!r}",
            file=sys.stderr,
        )
        return 3
    poll_seconds = env_seconds("WATCH_POLL_SECONDS", 30)
    fast_fail_seconds = env_seconds("WATCH_FAST_FAIL_SECONDS", 60)
    rerun_wait = env_seconds("WATCH_RERUN_WAIT_SECONDS", 20)
    gh = shutil.which(os.environ.get("GH_BIN") or "gh")
    if not gh:
        print("watch-pr-checks: gh not found on PATH (set GH_BIN)", file=sys.stderr)
        return 3

    top = run(["git", "rev-parse", "--show-toplevel"])
    if top.returncode != 0:
        print("watch-pr-checks: not inside a git repository", file=sys.stderr)
        return 3
    repo_root = top.stdout.strip()
    head = run(["git", "-C", repo_root, "rev-parse", "--short", "HEAD"]).stdout.strip()
    log_path = argv[3] if len(argv) > 3 else os.path.join(repo_root, f"ci-watch-{head}.log")

    def log(message):
        line = f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}"
        print(line, flush=True)
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            print(f"watch-pr-checks: cannot write {log_path}: {exc}", file=sys.stderr)

    def append(text):
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(text if text.endswith("\n") else text + "\n")
        except OSError:
            pass

    log(f"watching PR #{pull_request} at head {head} (log: {log_path})")
    child_env = dict(os.environ)
    # Headless gh otherwise prints 'open terminal failed: not a terminal'.
    child_env["GH_NO_SPINNER"] = "1"

    def gh_run(args):
        return subprocess.run(
            command_for(gh, args),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=child_env,
            creationflags=hidden_flags(),
        )

    reruns = 0
    poll = 0
    while poll < max_polls:
        poll += 1
        checks = gh_run(["pr", "checks", pull_request])
        output = (checks.stdout or "") + (checks.stderr or "")
        log(f"poll {poll}")
        append(output.rstrip())

        # Immediately after a push GitHub lists no checks at all and `gh pr checks`
        # exits 1 with "no checks reported", which matches none of the pending
        # words: reading that as "nothing left to wait for" declares a false green
        # before the matrix has registered. Require real rows, then require the
        # merge state to agree with them.
        if NO_CHECKS_RE.search(output):
            log(f"  poll {poll}: no checks registered yet")
            time.sleep(poll_seconds)
            continue
        rows = [line for line in output.splitlines() if ROW_RE.match(line)]
        if not rows:
            log(f"  poll {poll}: no parseable check rows yet")
            time.sleep(poll_seconds)
            continue
        if PENDING_RE.search(output):
            time.sleep(poll_seconds)
            continue

        failed = [line for line in rows if line.split("\t")[1] == "fail"]
        real_failure = False
        reran = False
        for line in failed:
            fields = line.split("\t")
            name = fields[0]
            duration = fields[2] if len(fields) > 2 else ""
            seconds, parsed = rerun_seconds(duration)
            if not parsed:
                log(f"  unreadable duration {duration!r} for {name}; treating it as infra-sized 0s")
            if seconds < fast_fail_seconds and reruns < max_reruns:
                found = RUN_ID_RE.search(line)
                run_id = found.group(1) if found else ""
                log(
                    f"infra-looking fail: {name} ({duration or '-'}) -> "
                    f"gh run rerun {run_id or '<no run id>'} --failed"
                )
                if run_id:
                    rerun = gh_run(["run", "rerun", run_id, "--failed"])
                    append((rerun.stdout or "") + (rerun.stderr or ""))
                reruns += 1
                reran = True
                break
            log(f"real fail: {name} ({duration or '-'})")
            real_failure = True
        if reran:
            time.sleep(rerun_wait)
            continue
        if real_failure:
            log(f"CI failed after {reruns} infra rerun(s)")
            return 1

        view = gh_run(
            [
                "pr",
                "view",
                pull_request,
                "--json",
                "mergeable,mergeStateStatus,headRefOid",
                "--jq",
                r'"\(.mergeable) \(.mergeStateStatus) \(.headRefOid)"',
            ]
        )
        state_line = (view.stdout or view.stderr or "").strip()
        append(state_line)
        observed_head = state_line.split(" ")[-1] if state_line else ""
        if observed_head and not observed_head.startswith(head):
            log(f"head moved: watching {head} but the PR is at {observed_head}")
            return 2
        if not state_line.startswith("MERGEABLE CLEAN"):
            log(f"  poll {poll}: checks done, merge state not CLEAN yet")
            time.sleep(poll_seconds)
            continue
        log("CI green")
        return 0

    log(f"still pending after {max_polls} polls")
    return 2


def _interrupt(_signum, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGINT, _interrupt)
    except (ValueError, OSError):
        pass
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("watch-pr-checks: interrupted", file=sys.stderr)
        sys.exit(130)
