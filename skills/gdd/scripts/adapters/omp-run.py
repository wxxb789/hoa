#!/usr/bin/env python3
"""omp-run.py — cross-platform launcher adapter for an OMP-style headless agent CLI.

The goal-driven delivery tools (gdd.py, delivery-state.py) never start an agent
themselves: they render a prompt and call a launcher that implements this
contract.

    <launcher> start  --name SLUG --prompt FILE [--cwd DIR] [--model M]
                      [--thinking L] [--max-time D] [--resume ID] [--replace]
                      [--backend setsid|tmux] [--profile P] [--extra "FLAG ..."]
    <launcher> list        # every recorded run + liveness
    <launcher> status [SLUG]
    <launcher> tail SLUG [N]
    <launcher> result SLUG
    <launcher> answer SLUG
    <launcher> kill SLUG

`start` exits 0 only after the run actually started, prints `started: NAME` and
`run dir   : DIR`, and creates

    <run_root>/<YYYY-MM-DD>/<SLUG>/state.json
    <run_root>/<YYYY-MM-DD>/<SLUG>/answer.md

with state.json holding at least {"name","state","exit","cwd","started","ended",
"duration_s","pid","backend"} and `state` in running|done|killed|failed. gdd.py
polls that file; a missing state.json is unknown, never success.

A run is finished only once a `finalized` marker (holding the exit code) sits
next to state.json. When that marker is absent, state.json still says `running`,
and neither the runner pid nor the agent pid it recorded is alive, the process
died before finalizing: status/list/result/answer finalize it as failed with exit
-1, set `stale_recovered: true`, and print `stale_recovered: true`. A marker is
never mutated, so recovery is idempotent. A run that has recorded no pid yet is
still *starting*, not dead, for OMP_RUN_START_GRACE_SECONDS (default 60).

Cross-platform detachment
-------------------------
A run must outlive the session that started it, and a `-p`-style CLI prints only
at exit, so a kill at minute 37 costs the whole run. This adapter detaches without
needing setsid, tmux or bash:

  POSIX   the runner is spawned with start_new_session=True (setsid in the
          child): its own session and process group, no controlling terminal.
          The agent gets its own session too, so a kill reaches the tools it
          started without signalling the runner that still has to finalize.
  Windows the runner is spawned with CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP.

Why CREATE_NO_WINDOW and not DETACHED_PROCESS: a `.cmd` shim runs through cmd.exe,
a console-subsystem program, so Windows allocates a visible console on every
dispatch (the flash). DETACHED_PROCESS fixes that flash but leaves the run with
*no* console, and then the first console-subsystem process the agent starts
allocates one of its own — visible. Measured on Windows 11, same launcher, only
the creation flags differing:

    CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        run: console attached, no window; a grandchild joins the same console
        (process count 1 -> 2, no window) — nothing is ever allocated or shown
    DETACHED_PROCESS
        run: no console; a grandchild allocates its own, visible window — a flash
        per tool command

CREATE_NO_WINDOW therefore gives the run one console nobody sees, which the whole
descendant tree inherits. The runner records what it observed about its own
detachment in state.json under `detach` (`console`, `console_processes`,
`console_window`, `console_window_visible` on Windows; `session_leader`,
`process_group_leader`, `controlling_terminal` on POSIX) and `start` records the
flags it requested under `spawn`, so the rule is asserted mechanically rather
than by eye — a window-less console has no HWND, so "has a console" is
GetConsoleProcessList() > 0, not GetConsoleWindow() != 0.

Do not launch a Windows launcher from inside a WSL distro, or the reverse: WSL2
interop is asymmetric — Windows environment variables are not inherited by the
distro, and a detached Windows `.exe` started from a distro has been observed to
record its session and then never exit, so the run never finalizes. Run the
adapter inside the distro with the distro's own python3 (this file is POSIX code
on POSIX), and point GDD_RUN_ROOT at one root both halves can see.

Configuration (nothing about one install is baked in)
----------------------------------------------------
    OMP_BIN                    agent CLI (default: omp); resolved through PATH, so
                               an absolute path works too. On Windows a `.cmd`/`.bat`
                               shim is invoked through %COMSPEC%.
    OMP_RUN_ROOT               run root (default: GDD_RUN_ROOT)
    GDD_RUN_ROOT               run root (default below)
    OMP_RUN_BACKEND            default for `start --backend`: setsid|tmux (default
                               setsid; on Windows `setsid` means the hidden-console
                               detached runner above)
    OMP_LEDGER                 finished-run ledger (default: <run_root>/ledger.tsv)
    OMP_RUN_EVENTS_MAX_BYTES   bound for the retained event log (default: 8388608).
                               Read by the bounded writer shipped next to this file
                               (`events-writer.py`), the one implementation of that
                               bound shared with the reference adapter. state.json
                               and `status` report events_bytes (retained),
                               events_bytes_total, events_truncated and
                               events_dropped_bytes; every counter derived from a
                               truncated stream is flagged *_partial.
    OMP_RUN_START_GRACE_SECONDS
                               how long a run that has recorded no pid is treated as
                               starting rather than dead (default: 60).
    --model, --thinking, --max-time, --profile, --extra
                               passed to the agent only when supplied; this adapter
                               defaults none of them.

The run-root default is one rule on every platform:
${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs, which on Windows resolves under
%USERPROFILE% — deliberately no %LOCALAPPDATA% branch, so the Windows and POSIX
adapters (and gdd.py, delivery-state.py) see one tree and one ledger. Set
GDD_RUN_ROOT to move it.

Run artifacts: <run_root>/<date>/<SLUG>/ = prompt.md, state.json, lock,
events.ndjson, events.stats.json, stderr.log (the agent's own stderr), runner.log
(the runner's output), exit.code, session.id, answer.md, finalized, stop (the kill
request, below), plus run.json and run.sh (POSIX) or run.cmd (Windows) — the exact
invocation, replayable by hand. `lock` holds {"pid","agent_pid","tmux","backend",
"started_at"}: `pid` is the detached runner (a session and process-group leader on
POSIX), `agent_pid` the agent it started, `tmux` the session under that backend.
`start` writes the lock before spawning, the runner only ever adds `pid` and
`agent_pid`, so a read-modify-write cannot drop a field.

`kill` writes the `stop` control file, which the runner polls, and waits for the
run's own finalizer. A control file rather than a signal, because signal and
process-group delivery is POSIX API, and a Windows shell shares no console with a
hidden run, so it cannot deliver Ctrl-Break to it either. An external SIGTERM
(POSIX) or SIGBREAK (Windows) takes the same path. If the run does not settle,
`kill` escalates to TERM/KILL of the run's process groups (POSIX) or
`taskkill /T /F` of the runner and the agent (Windows); a run stopped this way ends
as `killed` with exit 143.

Exit codes: 0 success, 1 refusal or error — the reference adapter's convention.

Adapting this file to another agent CLI means the same three edits as the
reference adapter: point OMP_BIN at that CLI, map --model/--thinking/--max-time to
its flags in `agent_args`, and adapt `summarize` to its event stream. The state
fields and answer.md stay as they are.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

if os.name == "nt":  # Windows-only: console inspection and open-process checks
    import ctypes

HERE = os.path.dirname(os.path.abspath(__file__))
ADAPTER = os.path.abspath(__file__)
EVENTS_WRITER = os.path.join(HERE, "events-writer.py")
IS_WINDOWS = os.name == "nt"
# Exit codes that mean "the process was stopped", not "it failed": 130 SIGINT,
# 143 SIGTERM, 137 SIGKILL by shell convention, -2 the raw SIGINT of a CLI that
# reports the signal instead of 128+n.
KILLED_EXITS = (130, -2, 137, 143)
KILL_EXIT = 143
# Creation-flag values as documented by Microsoft, repeated here because
# subprocess only exposes them on Windows and the rule must be assertable
# everywhere. A Windows test pins them against subprocess's own constants.
NO_WINDOW_MASK = 0x08000000
NEW_GROUP_MASK = 0x00000200
DETACHED_MASK = 0x00000008
POLL_SECONDS = 0.25
START_WAIT_SECONDS = 20.0
STOP_WAIT_SECONDS = 20.0
GRACE_SECONDS = 60.0
RUN_DIR_PATTERNS = ("*", "*/*", "*/*/runs/*", "*/*/omp-runs/*")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SANITIZE_RE = re.compile(r"[^a-z0-9._-]+")
# Flags that take a value, for `normalize_argv` below.
VALUE_FLAGS = {
    "--name",
    "--prompt",
    "--cwd",
    "--model",
    "--thinking",
    "--max-time",
    "--profile",
    "--extra",
    "--resume",
    "--backend",
    "--run-dir",
    "--agent",
    "--ledger",
}

EPILOG = """\
Launcher contract (full text: references/transport.md in the gdd skill):
  omp-run.py start --name SLUG --prompt FILE [--cwd DIR] [--model M] [--thinking L]
                   [--max-time D] [--resume ID] [--replace] [--backend setsid|tmux]
  omp-run.py list | status [SLUG] | result SLUG | answer SLUG | tail SLUG [N] | kill SLUG

Configuration: OMP_BIN, OMP_RUN_ROOT, GDD_RUN_ROOT, OMP_LEDGER, OMP_RUN_BACKEND,
OMP_RUN_EVENTS_MAX_BYTES, OMP_RUN_START_GRACE_SECONDS.

Detachment: POSIX start_new_session (no setsid or tmux needed); Windows
CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP — one hidden console for the whole tree,
which is what keeps a dispatch from flashing one and every tool command from
allocating one.
"""


def die(message, code=1):
    print(f"omp-run: {message}", file=sys.stderr)
    sys.exit(code)


def normalize_argv(argv):
    """Fold `--flag value` into `--flag=value` when the value looks like an option.

    argparse refuses a value that begins with `-` (`--extra --no-session`,
    `--model -x`), while the reference adapter's hand-rolled parser accepts both
    spellings — a shell hands it one token either way. Agent flags begin with `-`
    by nature, so the spellings have to agree: joining them here is what keeps the
    two adapters interchangeable. A value that is not option-like is untouched.
    """
    out = []
    index = 0
    while index < len(argv):
        token = argv[index]
        following = argv[index + 1] if index + 1 < len(argv) else ""
        if token in VALUE_FLAGS and following.startswith("-"):
            out.append(f"{token}={following}")
            index += 2
            continue
        out.append(token)
        index += 1
    return out


# -- configuration -----------------------------------------------------------


def state_home() -> str:
    """Per-user state root: $XDG_STATE_HOME, else $HOME/.local/state.

    Deliberately one rule on every platform: on Windows the XDG layout resolves
    under %USERPROFILE%, so this adapter, gdd.py and delivery-state.py agree on one
    run root and one ledger. Point GDD_RUN_ROOT somewhere else to move it.
    """
    return os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )


def run_root() -> str:
    return os.path.expanduser(
        os.environ.get("OMP_RUN_ROOT")
        or os.environ.get("GDD_RUN_ROOT")
        or os.path.join(state_home(), "gdd", "runs")
    )


def ledger_path(root) -> str:
    return os.environ.get("OMP_LEDGER") or os.path.join(root, "ledger.tsv")


def start_grace_seconds() -> float:
    try:
        value = float((os.environ.get("OMP_RUN_START_GRACE_SECONDS") or "").strip())
    except ValueError:
        return GRACE_SECONDS
    return value if value > 0 else GRACE_SECONDS


def agent_binary() -> str:
    return os.environ.get("OMP_BIN") or "omp"


def is_wsl(proc_version="/proc/version") -> bool:
    """True inside a WSL distro: its kernel version line names Microsoft."""
    try:
        with open(proc_version, encoding="utf-8", errors="replace") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def interop_warning(agent, wsl=None) -> str:
    """Warn when a WSL distro is about to drive a Windows agent binary.

    WSL2 interop is asymmetric: Windows environment variables do not reach the
    distro, and a detached Windows `.exe` started from a distro has been observed
    to record its session and then never exit, so the run never finalizes. A
    warning rather than a refusal — an operator may know better than this check.
    """
    # On Windows this never fires: launching a Windows binary from Windows is the
    # normal case. An explicit `wsl` argument states the context, which is also how
    # the rule stays testable on every platform.
    in_wsl = (is_wsl() and not IS_WINDOWS) if wsl is None else wsl
    if not in_wsl:
        return ""
    if re.match(r"^/mnt/[a-zA-Z]/", str(agent)) or str(agent).lower().endswith(
        (".exe", ".cmd", ".bat")
    ):
        return (
            f"agent '{agent}' looks like a Windows binary reached through WSL interop; a "
            "detached Windows run can record its session and never exit — install the agent "
            "inside the distro, or run the launcher from Windows"
        )
    return ""


# -- small helpers -----------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def read_state_file(run_dir) -> dict:
    state = read_json(os.path.join(run_dir, "state.json"), {})
    return state if isinstance(state, dict) else {}


def write_json(path, payload) -> None:
    """Replace atomically: gdd.py polls state.json and must never read half of it.

    On Windows the replace needs retries. `os.replace` is MoveFileEx, which fails
    with WinError 5 when any process holds the destination open, and CPython opens
    files sharing read and write but not delete — so a poller as ordinary as
    `gdd.py status`, `delivery-state.py` or `omp-run.py status` can make a runner
    die before it recorded the run. Retry briefly, then degrade to an in-place
    write with a note on stderr: a torn read is bad, a lost run is worse.
    """
    tmp = f"{path}.{os.getpid()}.tmp"
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 + 0.05 * (attempt % 5))
        except OSError as exc:
            remove_quietly(tmp)
            raise
    sys.stderr.write(f"omp-run: {path} stayed locked; written in place\n")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    remove_quietly(tmp)


def remove_quietly(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def read_sidecar(run_dir, name) -> str:
    try:
        with open(os.path.join(run_dir, name), encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError:
        return ""
    return text.splitlines()[0].strip() if text else ""


def sanitize(value) -> str:
    """The reference adapter's slug rule: lower-case, [a-z0-9._-], 48 characters."""
    return SANITIZE_RE.sub("-", str(value or "").lower()).strip("-")[:48]


def mtime_of(path) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def run_quiet(argv) -> int:
    """Run a helper command with no console and no output of its own."""
    try:
        return subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=hidden_flags(),
        ).returncode
    except OSError:
        return -1


def interpreter() -> str:
    """Interpreter for child Python processes.

    python.exe under CREATE_NO_WINDOW keeps stdin/stdout/stderr correct and shows
    no window. pythonw.exe would be windowless too, but a pythonw parent loses the
    standard handles its own subprocess children need: `gdd.py status` printed
    nothing through a pythonw shim.
    """
    if IS_WINDOWS:
        console = os.path.join(os.path.dirname(sys.executable), "python.exe")
        if os.path.exists(console):
            return console
    return sys.executable


# -- processes ---------------------------------------------------------------


def detach_flags() -> int:
    """Creation flags for a run that must outlive its caller and flash nothing.

    CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: one hidden console for the whole
    tree. DETACHED_PROCESS is deliberately absent — it would leave every tool
    command the agent runs to allocate (and flash) a console of its own.
    """
    if IS_WINDOWS:
        return NO_WINDOW_MASK | NEW_GROUP_MASK
    return 0


def hidden_flags() -> int:
    """Creation flags for a short-lived helper: never a window of its own."""
    return NO_WINDOW_MASK if IS_WINDOWS else 0


def agent_flags() -> int:
    """Creation flags for the agent inside a run: inherit the hidden console."""
    return NO_WINDOW_MASK if IS_WINDOWS else 0


def pid_alive(pid) -> bool:
    """Is this pid a live process?

    os.kill(pid, 0) is not a liveness check on Windows: for a detached process in
    another session it raises AccessDenied, which reported a live run as dead and
    made the recovery path finalize it as failed. OpenProcess(SYNCHRONIZE |
    PROCESS_QUERY_LIMITED_INFORMATION) + GetExitCodeProcess answers the same
    question for a process this user cannot fully open.
    """
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if IS_WINDOWS:
        SYNCHRONIZE = 0x00100000
        QUERY_LIMITED = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE | QUERY_LIMITED, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def tmux_alive(session) -> bool:
    if not session:
        return False
    return run_quiet(["tmux", "has-session", "-t", str(session)]) == 0


def tmux_sessions():
    try:
        proc = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            creationflags=hidden_flags(),
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [
        line.strip()
        for line in (proc.stdout or "").splitlines()
        if line.strip().startswith("omp-")
    ]


def lock_of(run_dir) -> dict:
    lock = read_json(os.path.join(run_dir, "lock"), {})
    return lock if isinstance(lock, dict) else {}


def update_lock(run_dir, **fields) -> dict:
    lock = lock_of(run_dir)
    lock.update(fields)
    write_json(os.path.join(run_dir, "lock"), lock)
    return lock


def recorded_pids(run_dir, state=None) -> list:
    """Pids that prove the run is live: the runner and the agent it started.

    Either one counts: the runner outlives a crashed agent only long enough to
    finalize, and the agent can outlive a runner killed by a signal it cannot
    handle.
    """
    if state is None:
        state = read_state_file(run_dir)
    lock = lock_of(run_dir)
    seen = []
    for value in (lock.get("pid"), lock.get("agent_pid"), state.get("agent_pid")):
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            if value not in seen:
                seen.append(value)
    return seen


def run_alive(run_dir, state=None) -> bool:
    if any(pid_alive(pid) for pid in recorded_pids(run_dir, state)):
        return True
    session = lock_of(run_dir).get("tmux") or (state or {}).get("tmux")
    return tmux_alive(session)


def state_age_seconds(state) -> float:
    started = (state or {}).get("started")
    if not started:
        return float("inf")
    try:
        delta = datetime.now(timezone.utc) - datetime.fromisoformat(started)
    except ValueError:
        return float("inf")
    return delta.total_seconds()


def is_starting(run_dir, state) -> bool:
    """A young run that has recorded no pid yet is starting, not dead.

    `start` spawns the runner and the runner claims its pid as its first act; a
    `status` inside that window must not finalize a live run as failed.
    """
    if recorded_pids(run_dir, state):
        return False
    return state_age_seconds(state) < start_grace_seconds()


def observe_detachment() -> dict:
    """What this process can prove about its own detachment (not what was asked).

    The runner writes this into state.json, so a test asserts an observed fact
    rather than the flag that was requested (`spawn` holds that half).

    Windows: `console` is "this process is attached to a console", which is the
    property that decides whether a descendant inherits one or allocates (and
    flashes) its own. A CREATE_NO_WINDOW console has no window at all, so
    GetConsoleWindow() is 0 while GetConsoleProcessList() still counts the console
    the tree shares; under DETACHED_PROCESS the count is 0 and the first
    console-subsystem grandchild opens a visible window. IsWindowVisible is in
    user32, not kernel32.

    POSIX: this process is its own session and process-group leader with no
    controlling terminal — a session that has one cannot open /dev/tty.
    """
    facts = {"mode": "hidden-console" if IS_WINDOWS else "new-session"}
    if IS_WINDOWS:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        attached = (ctypes.c_ulong * 64)()
        count = kernel32.GetConsoleProcessList(attached, 64)
        window = kernel32.GetConsoleWindow()
        facts["console"] = count > 0
        facts["console_processes"] = count
        facts["console_window"] = bool(window)
        facts["console_window_visible"] = bool(user32.IsWindowVisible(window)) if window else False
        return facts
    facts["session_leader"] = os.getsid(0) == os.getpid()
    facts["process_group_leader"] = os.getpgrp() == os.getpid()
    try:
        with open("/dev/tty", "rb"):
            facts["controlling_terminal"] = True
    except OSError:
        facts["controlling_terminal"] = False
    return facts


def install_stop_handler(requested: threading.Event) -> None:
    """Turn an external stop signal into the path the `stop` file already takes."""

    def handler(_signum, _frame):
        requested.set()

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            signal.signal(number, handler)
        except (OSError, ValueError, RuntimeError):
            continue


def spawn_runner(argv, cwd, log_path):
    """Start the detached runner: POSIX own session, Windows hidden console."""
    with open(log_path, "ab") as log:
        kwargs = {
            "cwd": cwd,
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
        }
        if IS_WINDOWS:
            kwargs["creationflags"] = detach_flags()
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(argv, **kwargs)


def spawn_agent(argv, cwd, stderr):
    """Start the agent inside the run, in its own process group on POSIX.

    Its own session keeps a group signal from reaching the runner, which still has
    to finalize the run after the agent is gone.
    """
    kwargs = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": stderr,
    }
    if IS_WINDOWS:
        kwargs["creationflags"] = agent_flags()
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def signal_group(pid, signum) -> None:
    """Signal a process group, falling back to the process itself."""
    try:
        os.killpg(os.getpgid(pid), signum)
    except OSError:
        try:
            os.kill(pid, signum)
        except OSError:
            pass


def terminate_agent(process) -> int:
    """Stop the agent and the tool processes under it; report exit 143."""
    if process.poll() is None:
        if IS_WINDOWS:
            run_quiet(["taskkill", "/T", "/F", "/PID", str(process.pid)])
        else:
            signal_group(process.pid, signal.SIGTERM)
            for _ in range(20):
                if process.poll() is not None:
                    break
                time.sleep(POLL_SECONDS)
            if process.poll() is None:
                signal_group(process.pid, signal.SIGKILL)
    for _ in range(40):
        if process.poll() is not None:
            break
        time.sleep(POLL_SECONDS)
    return KILL_EXIT


def kill_tree(run_dir, state=None) -> bool:
    """Force an unresponsive run to stop: its groups (POSIX) or its trees (Windows)."""
    pids = recorded_pids(run_dir, state)
    if not pids:
        return False
    if IS_WINDOWS:
        for pid in pids:
            run_quiet(["taskkill", "/T", "/F", "/PID", str(pid)])
        return True
    for pid in pids:
        signal_group(pid, signal.SIGTERM)
    for _ in range(20):
        if not any(pid_alive(pid) for pid in pids):
            return True
        time.sleep(POLL_SECONDS)
    for pid in pids:
        signal_group(pid, signal.SIGKILL)
    return True


def request_stop(run_dir) -> None:
    """The kill request the runner polls (see the module docstring)."""
    write_json(os.path.join(run_dir, "stop"), {"requested_at": now_iso(), "by": os.getpid()})


def wait_for_marker(run_dir, seconds) -> str:
    """Wait for the `finalized` marker; return its content, or "" on timeout."""
    path = os.path.join(run_dir, "finalized")
    deadline = time.monotonic() + seconds
    while True:
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return ""
        time.sleep(POLL_SECONDS)


# -- run discovery -----------------------------------------------------------


def date_of(path) -> str:
    for part in reversed(os.path.abspath(path).split(os.sep)):
        if DATE_RE.match(part):
            return part
    return ""


def newest_first(paths):
    return sorted(paths, key=lambda path: (date_of(path), mtime_of(path)), reverse=True)


def run_dirs(root=None):
    """Every recorded run under the root, newest date first."""
    root = root or run_root()
    found = []
    seen = set()
    for pattern in RUN_DIR_PATTERNS:
        for path in glob.glob(os.path.join(root, pattern)):
            if not os.path.isfile(os.path.join(path, "state.json")):
                continue
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            found.append(path)
    return newest_first(found)


def find_run(name):
    """Newest run directory called NAME, or None.

    A directory with no state.json is still a run directory: `status` reports it as
    unknown, which is the honest answer for a launcher that died before it could
    write one.
    """
    slug = sanitize(name)
    if not slug:
        return None
    root = run_root()
    candidates = []
    for pattern in RUN_DIR_PATTERNS:
        for path in glob.glob(os.path.join(root, pattern)):
            if os.path.basename(path) != slug or not os.path.isdir(path):
                continue
            if not any(
                os.path.exists(os.path.join(path, marker))
                for marker in ("state.json", "lock", "prompt.md")
            ):
                continue
            candidates.append(path)
    if not candidates:
        return None
    return newest_first(candidates)[0]


def require_run(command, name):
    if not name:
        die(f"{command}: slug required")
    run_dir = find_run(name)
    if not run_dir:
        die(f"{command}: no run '{name}' under {run_root()}")
    return run_dir


# -- events, summary, finalize ----------------------------------------------


def load_writer():
    """The bounded writer shipped beside this adapter, without leaving bytecode.

    Compiled and exec'd rather than imported: a normal import writes __pycache__
    into the installed skill directory, and this adapter may be run from a tree
    nobody owns. events-writer.py stays the one implementation of the event bound
    and of events.stats.json, shared with the reference adapter.
    """
    try:
        with open(EVENTS_WRITER, "rb") as handle:
            source = handle.read()
    except OSError as exc:
        raise RuntimeError(f"bounded event writer not readable at {EVENTS_WRITER}: {exc}")
    namespace = {"__name__": "gdd_events_writer", "__file__": EVENTS_WRITER}
    exec(compile(source, EVENTS_WRITER, "exec"), namespace)
    return namespace["Writer"], namespace["resolve_cap"]


class EventLog:
    """This run's bounded NDJSON log: the shared writer plus its stats sidecar."""

    def __init__(self, run_dir):
        writer_class, resolve_cap = load_writer()
        cap, warning = resolve_cap()
        if warning:
            sys.stderr.write(f"omp-run: {warning}\n")
        self.path = os.path.join(run_dir, "events.ndjson")
        self.stats_path = os.path.join(run_dir, "events.stats.json")
        self.writer = writer_class(run_dir, cap, defaulted=warning is not None)

    def feed(self, raw) -> None:
        self.writer.feed(raw)

    def finish(self) -> dict:
        self.writer.finish()
        stats = read_json(self.stats_path, {})
        return stats if isinstance(stats, dict) else {}


def to_text(parts) -> str:
    out = []
    for part in parts or []:
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
            out.append(part["text"])
    return "".join(out)


def summarize(run_dir, events_path) -> dict:
    """Aggregate the retained event stream exactly as the reference finalizer does."""
    stats = read_json(os.path.join(run_dir, "events.stats.json"), {})
    stats = stats if isinstance(stats, dict) else {}
    session_id = ""
    answer = ""
    cost = 0.0
    tool_calls = 0
    turns = 0
    errors = []
    marker = {}
    if os.path.exists(events_path):
        with open(events_path, "rb") as handle:
            for raw in handle:
                try:
                    event = json.loads(raw.decode("utf-8", "replace").strip())
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get("type") or ""
                if kind == "truncated":
                    # The writer's splice marker: a counter boundary, not an event.
                    marker = event
                    continue
                if kind == "session" and not session_id:
                    session_id = event.get("id") or session_id
                elif kind == "message_end":
                    message = event.get("message") or {}
                    if message.get("role") == "assistant":
                        text = to_text(message.get("content"))
                        if text:
                            answer = text
                        usage = message.get("usage") or {}
                        charged = usage.get("cost")
                        if isinstance(charged, dict):
                            cost += float(charged.get("total") or 0)
                        elif isinstance(charged, (int, float)):
                            cost += float(charged)
                elif "tool" in kind:
                    if "start" in kind:
                        tool_calls += 1
                    if "error" in kind:
                        errors.append(str(event)[:300])
                elif kind == "turn_end":
                    turns += 1
    retained = os.path.getsize(events_path) if os.path.exists(events_path) else 0
    # The sidecar is exact at a normal exit; the marker only bounds the loss.
    total_bytes = stats.get("total_bytes")
    if not isinstance(total_bytes, int) or total_bytes < retained:
        dropped = marker.get("dropped_bytes")
        total_bytes = retained + (dropped if isinstance(dropped, int) and dropped > 0 else 0)
    dropped_bytes = stats.get("dropped_bytes")
    if not isinstance(dropped_bytes, int) or dropped_bytes < 0:
        dropped = marker.get("dropped_bytes")
        dropped_bytes = dropped if isinstance(dropped, int) and dropped > 0 else 0
    truncated = bool(stats.get("truncated")) or bool(marker) or dropped_bytes > 0
    return {
        "session_id": session_id,
        "answer": answer,
        "cost_usd": round(cost, 4),
        "tool_calls": tool_calls,
        "turns": turns,
        "errors": errors[-5:],
        "events_bytes": retained,
        "events_bytes_total": total_bytes,
        "events_truncated": truncated,
        "events_dropped_bytes": dropped_bytes,
    }


def ledger_append(run_dir, state, exit_code) -> None:
    """One row per finished run, in the ledger the reference adapter writes."""
    ledger = (
        state.get("ledger")
        or os.environ.get("OMP_LEDGER")
        or os.path.join(os.path.dirname(os.path.dirname(run_dir)), "ledger.tsv")
    )
    header = "ended\tname\tstate\texit\tduration_s\tcost_usd\tsession_id\trun_dir\n"
    row = "\t".join(
        [
            str(state.get("ended") or ""),
            str(state.get("name") or os.path.basename(run_dir)),
            str(state.get("state") or ""),
            str(exit_code),
            str(state.get("duration_s")),
            str(state.get("cost_usd")),
            str(state.get("session_id") or ""),
            run_dir,
        ]
    )
    try:
        os.makedirs(os.path.dirname(ledger), exist_ok=True)
        fresh = not os.path.exists(ledger)
        with open(ledger, "a", encoding="utf-8") as handle:
            if fresh:
                handle.write(header)
            handle.write(row + "\n")
    except OSError as exc:
        sys.stderr.write(f"omp-run: ledger append failed: {exc}\n")


def finalize(run_dir, exit_code, recovered=False, note=None) -> dict:
    """Write state.json, answer.md, exit.code, the `finalized` marker and the ledger row."""
    state_path = os.path.join(run_dir, "state.json")
    state = read_state_file(run_dir)
    events_path = os.path.join(run_dir, "events.ndjson")
    summary = summarize(run_dir, events_path)
    if exit_code == 0:
        verdict = "done"
    elif exit_code in KILLED_EXITS:
        verdict = "killed"
    else:
        verdict = "failed"
    if recovered:
        verdict = "failed"
    duration = None
    if state.get("started"):
        try:
            duration = round(
                (
                    datetime.now(timezone.utc) - datetime.fromisoformat(state["started"])
                ).total_seconds(),
                1,
            )
        except ValueError:
            duration = None
    truncated = summary["events_truncated"]
    state.update(
        {
            "state": verdict,
            "exit": exit_code,
            "ended": now_iso(),
            "duration_s": duration,
            "session_id": state.get("session_id")
            or summary["session_id"]
            or read_sidecar(run_dir, "session.id"),
            "cost_usd": summary["cost_usd"],
            "tool_calls": summary["tool_calls"],
            "turns": summary["turns"],
            "answer_chars": len(summary["answer"]),
            "errors": summary["errors"],
            "events_bytes": summary["events_bytes"],
            "events_bytes_total": summary["events_bytes_total"],
            "events_truncated": truncated,
            "events_dropped_bytes": summary["events_dropped_bytes"],
            "tool_calls_partial": truncated,
            "turns_partial": truncated,
            "cost_partial": truncated,
        }
    )
    if recovered:
        lock = lock_of(run_dir)
        pids = "/".join(str(pid) for pid in recorded_pids(run_dir, state)) or "-"
        state["stale_recovered"] = True
        state["note"] = (
            f"process disappeared without finalizing (backend "
            f"{lock.get('backend') or state.get('backend') or '-'}; runner/agent pids "
            f"{pids} are gone); finalized with exit -1"
        )
    elif note:
        state["note"] = note
    with open(os.path.join(run_dir, "answer.md"), "w", encoding="utf-8") as handle:
        handle.write(summary["answer"])
    with open(os.path.join(run_dir, "exit.code"), "w", encoding="utf-8") as handle:
        handle.write(f"{exit_code}\n")
    if state.get("session_id"):
        with open(os.path.join(run_dir, "session.id"), "w", encoding="utf-8") as handle:
            handle.write(f"{state['session_id']}\n")
    write_json(state_path, state)
    # Finished, not to be mistaken for a live run: the marker holds the exit code.
    with open(os.path.join(run_dir, "finalized"), "w", encoding="utf-8") as handle:
        handle.write(str(exit_code))
    ledger_append(run_dir, state, exit_code)
    return state


def effective_state(run_dir):
    """(state, recovered): finalize a genuinely dead run exactly once."""
    state = read_state_file(run_dir)
    if os.path.exists(os.path.join(run_dir, "finalized")):
        return state, False
    if state.get("state") != "running":
        return state, False
    if run_alive(run_dir, state) or is_starting(run_dir, state):
        return state, False
    return finalize(run_dir, -1, recovered=True), True


def reported_state(state) -> dict:
    return state if state.get("state") else {**state, "state": "unknown"}


def events_view(run_dir, state, alive=None) -> dict:
    """state.json plus the liveness and event-accounting facts `status` adds."""
    lock = lock_of(run_dir)
    session = lock.get("tmux") or state.get("tmux") or ""
    stats = read_json(os.path.join(run_dir, "events.stats.json"), {})
    stats = stats if isinstance(stats, dict) else {}
    events = os.path.join(run_dir, "events.ndjson")
    retained = os.path.getsize(events) if os.path.exists(events) else 0
    total = stats.get("total_bytes")
    if not isinstance(total, int):
        total = state.get("events_bytes_total")
    if not isinstance(total, int) or total < retained:
        # Before the first sidecar write, retained bytes are the only lower bound.
        total = retained
    dropped = stats.get("dropped_bytes", state.get("events_dropped_bytes", 0))
    if not isinstance(dropped, int):
        dropped = 0
    truncated = stats.get("truncated")
    if not isinstance(truncated, bool):
        truncated = bool(state.get("events_truncated")) or dropped > 0
    return {
        **reported_state(state),
        "backend": lock.get("backend") or state.get("backend") or ("tmux" if session else "setsid"),
        "alive": run_alive(run_dir, state) if alive is None else alive,
        "tmux_alive": tmux_alive(session),
        "events_bytes": retained,
        "events_bytes_total": total,
        "events_truncated": truncated,
        "events_dropped_bytes": dropped,
    }


# -- start -------------------------------------------------------------------


def agent_args(args) -> list:
    """The agent's own flags, in the order the reference adapter uses."""
    extra = shlex.split(args.extra) if args.extra else []
    argv = ["-p", "--mode=json", "--approval-mode", "yolo"]
    for flag, value in (
        ("--model", args.model),
        ("--thinking", args.thinking),
        ("--max-time", args.max_time),
    ):
        if value:
            argv += [flag, str(value)]
    if args.resume:
        argv += ["-r", args.resume]
    if args.profile:
        argv += ["--profile", args.profile]
    return argv + extra


def resolve_agent(binary) -> str:
    """Absolute path of the agent CLI, or "" — a `.cmd` shim is fine on Windows."""
    candidate = os.path.expanduser(str(binary))
    if not (os.sep in candidate or (os.altsep and os.altsep in candidate)):
        candidate = shutil.which(candidate) or ""
    if not candidate or not os.path.isfile(candidate):
        return ""
    if not IS_WINDOWS and not os.access(candidate, os.X_OK):
        return ""
    return candidate


def agent_command(agent, argv) -> list:
    """The full command line, wrapping a Windows `.cmd`/`.bat` shim in cmd.exe."""
    if IS_WINDOWS and os.path.splitext(agent)[1].lower() in (".cmd", ".bat"):
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/c", agent, *argv]
    return [agent, *argv]


def runner_argv(run_dir, prompt, cwd, agent, ledger, args, slug) -> list:
    argv = [
        interpreter(),
        ADAPTER,
        "_run",
        "--run-dir",
        run_dir,
        "--prompt",
        prompt,
        "--cwd",
        cwd,
        "--agent",
        agent,
        "--ledger",
        ledger,
        "--name",
        slug,
    ]
    for flag, value in (
        ("--model", args.model),
        ("--thinking", args.thinking),
        ("--max-time", args.max_time),
        ("--profile", args.profile),
        ("--extra", args.extra),
    ):
        if value:
            argv += [flag, str(value)]
    if args.resume:
        argv += ["--resume", args.resume]
    return argv


def write_replay(run_dir, payload) -> None:
    """The exact invocation: run.json for tools, plus the shell this platform uses.

    Rendered per shell on purpose — POSIX quoting is wrong in cmd.exe — and the one
    gap is recorded rather than papered over: run.cmd quotes each argument with
    double quotes, so a path holding a double quote or an unexpanded %VAR% is not
    replayable there, while run.json always is.
    """
    argv = payload["argv"]
    write_json(os.path.join(run_dir, "run.json"), payload)
    exports = [("OMP_LEDGER", payload.get("ledger") or "")]
    cap = os.environ.get("OMP_RUN_EVENTS_MAX_BYTES")
    if cap:
        exports.append(("OMP_RUN_EVENTS_MAX_BYTES", cap))
    if IS_WINDOWS:
        lines = [
            "@echo off",
            f"rem generated by omp-run.py — replay of {payload.get('name')}",
            f'cd /d "{payload["cwd"]}" || exit /b 90',
        ]
        lines += [f'set "{key}={value}"' for key, value in exports if value]
        lines.append(" ".join(f'"{item}"' if " " in item else item for item in argv))
        path = os.path.join(run_dir, "run.cmd")
        with open(path, "w", encoding="utf-8", newline="\r\n") as handle:
            handle.write("\n".join(lines) + "\n")
        return
    lines = [
        "#!/usr/bin/env bash",
        f"# generated by omp-run.py — replay of {payload.get('name')}",
        "set -uo pipefail",
        f"cd {shlex.quote(payload['cwd'])} || exit 90",
    ]
    lines += [f"export {key}={shlex.quote(value)}" for key, value in exports if value]
    lines.append("exec " + shlex.join(argv))
    path = os.path.join(run_dir, "run.sh")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    os.chmod(path, 0o755)


def move_aside(run_dir) -> str:
    """Keep the previous run of a slug instead of deleting it."""
    for attempt in range(20):
        suffix = datetime.now().strftime("%H%M%S") + (f"-{attempt}" if attempt else "")
        candidate = f"{run_dir}.prev-{suffix}"
        if os.path.exists(candidate):
            continue
        try:
            os.rename(run_dir, candidate)
            return candidate
        except OSError:
            continue
    return ""


def cmd_start(args) -> int:
    root = run_root()
    ledger = ledger_path(root)
    slug = sanitize(args.name)
    if not slug:
        die("start: --name is required (and must not sanitize to nothing)")
    prompt = os.path.abspath(os.path.expanduser(args.prompt or ""))
    if not os.path.isfile(prompt):
        die("start: --prompt FILE is required and must exist")
    cwd = os.path.abspath(os.path.expanduser(args.cwd or os.getcwd()))
    if not os.path.isdir(cwd):
        die(f"start: --cwd '{args.cwd}' is not a directory")
    agent = resolve_agent(agent_binary())
    if not agent:
        die(f"start: agent binary not found at {agent_binary()} (set OMP_BIN)")
    warning = interop_warning(agent)
    if warning:
        sys.stderr.write(f"omp-run: start: {warning}\n")
    backend = args.backend or os.environ.get("OMP_RUN_BACKEND") or "setsid"
    if backend not in ("setsid", "tmux"):
        die(f"start: --backend must be setsid or tmux (got '{backend}')")
    if backend == "tmux" and not tmux_available():
        die("start: tmux not found (use --backend setsid)")

    run_dir = os.path.join(root, datetime.now().strftime("%Y-%m-%d"), slug)
    session = f"omp-{slug}" if backend == "tmux" else ""
    if os.path.isdir(run_dir):
        state, _ = effective_state(run_dir)
        if run_alive(run_dir, state) or tmux_alive(session):
            if not args.replace:
                pids = "/".join(str(pid) for pid in recorded_pids(run_dir, state)) or "-"
                die(
                    f"start: run '{slug}' is still running (pid {pids}; "
                    f"use --replace to restart)"
                )
            if not stop_run(run_dir, state):
                die(f"start: could not stop run '{slug}' (see {run_dir})")
        if not move_aside(run_dir):
            # Refuse rather than mix two runs in one directory: the previous run's
            # `finalized` marker would make the new one look finished.
            die(f"start: cannot move {run_dir} aside for the new run")

    os.makedirs(run_dir, exist_ok=True)
    shutil.copyfile(prompt, os.path.join(run_dir, "prompt.md"))
    if args.resume:
        with open(os.path.join(run_dir, "session.id"), "w", encoding="utf-8") as handle:
            handle.write(args.resume + "\n")

    effective_backend = "tmux" if backend == "tmux" else ("windows" if IS_WINDOWS else "setsid")
    state = {
        "name": slug,
        "state": "running",
        "exit": None,
        "cwd": cwd,
        "started": now_iso(),
        "ended": None,
        "duration_s": None,
        "model": args.model or None,
        "thinking": args.thinking or None,
        "max_time": args.max_time or None,
        "profile": args.profile or None,
        "backend": effective_backend,
        "tmux": session or None,
        "run_dir": run_dir,
        "session_id": args.resume or "",
        "resumed_from": args.resume or None,
        "events_bytes": 0,
        "events_bytes_total": 0,
        "events_truncated": False,
        "events_dropped_bytes": 0,
        "launcher": ADAPTER,
        "agent": agent,
        "ledger": ledger,
        # What was requested; the runner records what it observed as `detach`.
        "spawn": {
            "mode": "tmux" if backend == "tmux" else ("hidden-console" if IS_WINDOWS else "new-session"),
            "creationflags": 0 if backend == "tmux" else detach_flags(),
            "platform": sys.platform,
        },
    }
    write_json(os.path.join(run_dir, "state.json"), state)
    # Written before the spawn so the runner's own update cannot race this one:
    # `pid` and `agent_pid` belong to the runner, everything here belongs to `start`.
    write_json(
        os.path.join(run_dir, "lock"),
        {
            "pid": None,
            "agent_pid": None,
            "tmux": session or None,
            "backend": effective_backend,
            "started_at": state["started"],
        },
    )
    command = runner_argv(
        run_dir,
        os.path.join(run_dir, "prompt.md"),
        cwd,
        agent,
        ledger,
        args,
        slug,
    )
    write_replay(
        run_dir,
        {
            "name": slug,
            "argv": command,
            "agent_argv": agent_command(agent, agent_args(args)),
            "cwd": cwd,
            "agent": agent,
            "ledger": ledger,
            "backend": effective_backend,
            "note": "replay of one run: the exact runner command, rerun in place",
        },
    )

    if backend == "tmux":
        if run_quiet(["tmux", "new-session", "-d", "-s", session, "-c", cwd, shlex.join(command)]):
            die(f"start: tmux new-session failed for {session}")
    else:
        try:
            spawn_runner(command, cwd, os.path.join(run_dir, "runner.log"))
        except OSError as exc:
            die(f"start: could not start the run: {exc}")

    started = wait_for_start(run_dir)
    pids = recorded_pids(run_dir, started)
    if started.get("error"):
        die(f"start: agent did not start: {started['error']}")
    if not pids:
        die(f"start: run did not start (see {os.path.join(run_dir, 'runner.log')})")
    if (
        not started.get("agent_pid")
        and not os.path.exists(os.path.join(run_dir, "session.id"))
        and not any(pid_alive(pid) for pid in pids)
    ):
        # The runner recorded its own pid and then died before starting the agent:
        # report that here instead of letting the caller treat a dead run as dispatched.
        die(
            "start: the runner exited before the agent started "
            f"(see {os.path.join(run_dir, 'runner.log')})"
        )
    print(f"started: {slug}")
    print(f"  backend   : {effective_backend}")
    if backend == "tmux":
        print(f"  tmux      : {session}")
    else:
        print(f"  pid       : {pids[0]}")
    print(f"  run dir   : {run_dir}")
    print(f"  session id: {started.get('session_id') or '(pending)'}")
    print(f"  events    : {os.path.join(run_dir, 'events.ndjson')}")
    print(f"  summary   : {os.path.join(run_dir, 'run.json')} (replay argv) + state.json")
    return 0


def wait_for_start(run_dir) -> dict:
    """Wait until the runner claimed the run, then until the agent is visible."""
    state_path = os.path.join(run_dir, "state.json")
    deadline = time.monotonic() + START_WAIT_SECONDS
    while True:
        state = reported_state(read_state_file(run_dir))
        if recorded_pids(run_dir, state) or state.get("state") != "running":
            break
        if time.monotonic() >= deadline:
            return state
        time.sleep(POLL_SECONDS)
    deadline = time.monotonic() + START_WAIT_SECONDS
    while True:
        state = read_state_file(run_dir)
        if (
            state.get("agent_pid")
            or os.path.exists(os.path.join(run_dir, "session.id"))
            or state.get("state") not in (None, "running")
        ):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(POLL_SECONDS)
    return state


# -- list, status, result, answer, tail, kill --------------------------------


def state_word(run_dir, state, recovered) -> str:
    """The one-word verdict `list` prints, including the resume hint."""
    session = state.get("session_id") or "?"
    if recovered:
        # Just finalized by the recovery path: report what was observed, not the
        # bookkeeping that was written.
        return f"GONE (resume with -r {session})"
    if state.get("state") == "running" and not run_alive(run_dir, state) and not is_starting(
        run_dir, state
    ):
        return f"GONE (resume with -r {session})"
    if state.get("stale_recovered") and state.get("state") == "failed":
        return "failed(stale)"
    return str(state.get("state"))


def cmd_list(_args) -> int:
    runs = run_dirs()
    if not runs:
        print("(no runs recorded)")
    for run_dir in runs:
        state, recovered = effective_state(run_dir)
        started = str(state.get("started") or "")[:19].replace("T", " ")
        name = str(state.get("name") or os.path.basename(run_dir))
        print(
            f"{started}  {name:<28} {state_word(run_dir, state, recovered)} "
            f"exit={state.get('exit')} dur={state.get('duration_s')} "
            f"cost=${state.get('cost_usd', 0)} sess={state.get('session_id') or '-'}"
        )
    if tmux_available():
        sessions = tmux_sessions()
        print(f"\nlive tmux: {len(sessions)} session(s)")
        for session in sessions:
            print(f"  {session}")
    return 0


def cmd_status(args) -> int:
    if not args.name:
        return cmd_list(args)
    run_dir = require_run("status", args.name)
    state, recovered = effective_state(run_dir)
    print(json.dumps(events_view(run_dir, state), indent=2, ensure_ascii=False))
    if recovered:
        print("stale_recovered: true")
    return 0


def cmd_result(args) -> int:
    run_dir = require_run("result", args.name)
    state, recovered = effective_state(run_dir)
    print(json.dumps(reported_state(state), indent=2, ensure_ascii=False))
    if recovered:
        print("stale_recovered: true")
    answer = os.path.join(run_dir, "answer.md")
    if os.path.exists(answer):
        with open(answer, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        print("\n--- answer (first 1500 chars) ---")
        print(text[:1500])
    return 0


def cmd_answer(args) -> int:
    run_dir = require_run("answer", args.name)
    effective_state(run_dir)
    path = os.path.join(run_dir, "answer.md")
    if not os.path.exists(path):
        die("answer: not finished yet")
    with open(path, encoding="utf-8", errors="replace") as handle:
        sys.stdout.write(handle.read())
    return 0


def cmd_tail(args) -> int:
    run_dir = require_run("tail", args.name)
    count = args.lines if args.lines and args.lines > 0 else 20
    path = os.path.join(run_dir, "events.ndjson")
    if not os.path.exists(path):
        die(f"tail: no event log in {run_dir}")
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    sys.stdout.write("".join(lines[-count:]))
    return 0


def stop_run(run_dir, state=None, seconds=STOP_WAIT_SECONDS) -> bool:
    """Ask the run to stop, then force it: True once its finalized marker exists."""
    if os.path.exists(os.path.join(run_dir, "finalized")):
        return True
    request_stop(run_dir)
    if wait_for_marker(run_dir, seconds):
        return True
    state = state if state is not None else read_state_file(run_dir)
    if run_alive(run_dir, state):
        kill_tree(run_dir, state)
    if wait_for_marker(run_dir, 10.0):
        return True
    # Nothing is left to finalize the run: the recovery path owns that now.
    effective_state(run_dir)
    return os.path.exists(os.path.join(run_dir, "finalized"))


def cmd_kill(args) -> int:
    run_dir = require_run("kill", args.name)
    state, _ = effective_state(run_dir)
    if os.path.exists(os.path.join(run_dir, "finalized")):
        die(f"kill: run '{args.name}' is already finished (state {state.get('state')})")
    if not run_alive(run_dir, state) and not is_starting(run_dir, state):
        die(f"kill: no live process recorded for '{args.name}' (state {state.get('state')})")
    pids = "/".join(str(pid) for pid in recorded_pids(run_dir, state)) or "-"
    session = lock_of(run_dir).get("tmux")
    stop_run(run_dir, state)
    if session and tmux_alive(session):
        run_quiet(["tmux", "kill-session", "-t", str(session)])
    final = reported_state(read_state_file(run_dir))
    if not os.path.exists(os.path.join(run_dir, "finalized")):
        die(
            f"kill: run '{args.name}' did not settle (state {final.get('state')}); "
            f"nothing left to finalize it — see {run_dir}"
        )
    print(f"killed: {args.name} (pid {pids}) state={final.get('state')} exit={final.get('exit')}")
    return 0


# -- the runner (internal `_run`) -------------------------------------------


def drain(stream, log) -> None:
    try:
        for raw in stream:
            log.feed(raw)
    except (OSError, ValueError):
        return
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def wait_for_agent(process, run_dir, requested: threading.Event) -> int:
    """Wait for the agent, honouring the stop control file and an external signal."""
    stop_path = os.path.join(run_dir, "stop")
    while True:
        exit_code = process.poll()
        if exit_code is not None:
            return exit_code
        if requested.is_set() or os.path.exists(stop_path):
            return terminate_agent(process)
        time.sleep(POLL_SECONDS)


def runner_main(args) -> int:
    """Run one agent in the foreground of the detached process `start` spawned."""
    run_dir = args.run_dir
    state_path = os.path.join(run_dir, "state.json")
    state = read_state_file(run_dir)
    # Claim the lock `start` wrote before the spawn: the runner owns pid and
    # agent_pid, `start` owns everything else, so no read-modify-write can drop a
    # field that raced it.
    update_lock(run_dir, pid=os.getpid())
    state["pid"] = os.getpid()
    state["detach"] = observe_detachment()
    state["interpreter"] = interpreter()
    write_json(state_path, state)

    try:
        with open(args.prompt, encoding="utf-8") as handle:
            prompt = handle.read()
    except OSError as exc:
        finalize(run_dir, 127, note=f"prompt unreadable: {exc}")
        return 1

    with open(os.path.join(run_dir, "stderr.log"), "ab") as stderr:
        try:
            log = EventLog(run_dir)
        except (RuntimeError, OSError, KeyError) as exc:
            finalize(run_dir, 127, note=f"event writer unavailable: {exc}")
            return 1
        argv = agent_command(args.agent, agent_args(args) + [prompt])
        try:
            process = spawn_agent(argv, args.cwd, stderr)
        except OSError as exc:
            log.finish()
            finalize(run_dir, 127, note=f"agent did not start: {exc}")
            sys.stderr.write(f"omp-run: agent did not start: {exc}\n")
            return 1
        state["agent_pid"] = process.pid
        write_json(state_path, state)
        update_lock(run_dir, agent_pid=process.pid)

        requested = threading.Event()
        install_stop_handler(requested)
        reader = threading.Thread(target=drain, args=(process.stdout, log), daemon=True)
        reader.start()
        exit_code = wait_for_agent(process, run_dir, requested)
        reader.join(timeout=30.0)
        if reader.is_alive():
            sys.stderr.write("omp-run: event reader still draining at exit\n")
        log.finish()

    final = finalize(run_dir, exit_code)
    print(
        f"[finalize] {final.get('name')} state={final['state']} exit={exit_code} "
        f"dur={final.get('duration_s')}s cost=${final.get('cost_usd')} "
        f"tools={final.get('tool_calls')} session={final.get('session_id') or '-'}",
        flush=True,
    )
    return 0


# -- command line ------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-platform launcher adapter for gdd headless runs: start a "
            "detached agent run, then list / status SLUG | result SLUG | "
            "answer SLUG | kill SLUG | tail SLUG."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start one detached run")
    start.add_argument("--name", required=True, help="run slug (sanitized)")
    start.add_argument("--prompt", required=True, help="prompt file")
    start.add_argument("--cwd", default=os.getcwd(), help="working directory of the run")
    start.add_argument("--model", default=None)
    start.add_argument("--thinking", default=None)
    start.add_argument("--max-time", dest="max_time", default=None)
    start.add_argument("--profile", default=None)
    start.add_argument("--extra", default=None, help="extra agent flags, shlex-split")
    start.add_argument("--resume", default=None, help="resume that agent session id")
    start.add_argument("--backend", default=None, help="setsid (default) or tmux")
    start.add_argument("--replace", action="store_true", help="restart a live run")
    start.set_defaults(func=cmd_start)

    runner = sub.add_parser("_run", help="internal: run one agent in the foreground")
    runner.add_argument("--run-dir", dest="run_dir", required=True)
    runner.add_argument("--prompt", required=True)
    runner.add_argument("--cwd", required=True)
    runner.add_argument("--agent", required=True)
    runner.add_argument("--ledger", default=None)
    runner.add_argument("--name", default=None)
    runner.add_argument("--model", default=None)
    runner.add_argument("--thinking", default=None)
    runner.add_argument("--max-time", dest="max_time", default=None)
    runner.add_argument("--profile", default=None)
    runner.add_argument("--extra", default=None)
    runner.add_argument("--resume", default=None)
    runner.set_defaults(func=runner_main)

    status = sub.add_parser("status", help="one run, or every recorded run")
    status.add_argument("name", nargs="?")
    status.set_defaults(func=cmd_status)

    result = sub.add_parser("result", help="state summary + answer head")
    result.add_argument("name")
    result.set_defaults(func=cmd_result)

    answer = sub.add_parser("answer", help="only the final assistant text")
    answer.add_argument("name")
    answer.set_defaults(func=cmd_answer)

    tail = sub.add_parser("tail", help="last N raw event lines (default 20)")
    tail.add_argument("name")
    tail.add_argument("lines", nargs="?", type=int)
    tail.set_defaults(func=cmd_tail)

    kill = sub.add_parser("kill", help="stop a live run and its agent")
    kill.add_argument("name")
    kill.set_defaults(func=cmd_kill)

    listing = sub.add_parser("list", help="every recorded run + liveness")
    listing.set_defaults(func=cmd_list)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(normalize_argv(sys.argv[1:] if argv is None else list(argv)))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
