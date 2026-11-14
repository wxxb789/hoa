#!/usr/bin/env python3
"""dsh-run.py — launcher adapter for DeepSeek Harness (`dsh`) headless runs.

The goal-driven delivery tools (gdd.py, delivery-state.py) never start an agent
themselves: they render a prompt and call a launcher that implements one contract
(full text: references/transport.md in the gdd skill).

    <launcher> start  --name SLUG --prompt FILE [--cwd DIR] [--session-id ID]
                      [--model M] [--thinking L] [--max-time D] [--resume ID]
                      [--replace]
    <launcher> list        # every recorded run + liveness
    <launcher> status [SLUG]
    <launcher> tail SLUG [N]
    <launcher> result SLUG
    <launcher> answer SLUG
    <launcher> kill SLUG

`start` exits 0 only after the run has actually started — the runner must have
recorded the agent pid it spawned, not merely its own; whether that agent is
still alive or already gone is the run's outcome, not the start's — prints
`started: NAME` and `run dir   : DIR`, which is what gdd.py parses, and creates

    <run_root>/<YYYY-MM-DD>/<SLUG>/state.json
    <run_root>/<YYYY-MM-DD>/<SLUG>/answer.md

with state.json holding at least {"name","state","exit","cwd","started","ended",
"duration_s"} and `state` in running|done|killed|failed|unknown. A missing
state.json is unknown, never success.

The DSH route, measured
-----------------------
`dsh` boots a profile and hands the remaining arguments to that profile's app.
The headless app takes one task and exits:

    dsh --profile headless [launcher flags] [app flags] [task|-]

Launcher flags must come first (`--patch` after an app flag is rejected with
`unknown option '--patch'`). The task is read from stdin when the argument is
omitted or is a lone `-`; `dsh … - < prompt.md` is therefore the shape this
adapter uses, and the prompt is sent verbatim. `--json` projects the run as
newline-delimited events on stdout:

    session      {sessionId, cwd}
    status       {turn, step, phase: turn_start|step_start|step_end|turn_end, reason?, usage?}
    thinking     {text, truncated}
    text         {text}
    tool_call    {callId, tool, input}
    tool_result  {callId, status, result, truncated}
    final        {sessionId, reason: {kind}, text}
    error        {message}

`status.usage` is {inputTokens, outputTokens, totalTokens, cacheReadTokens} and
is the only token accounting. `error` appears only for runner-level failures,
and then there is no `final` event. Everything on stderr is diagnostics
(reasoning deltas, loader warnings, Node warnings); the adapter keeps it in
stderr.log and reads nothing from it.

Completion is `exit 0` **and** the last `final` event carrying
`reason.kind == "completed"`; a `tool_result.status == "completed"` only means
the tool returned. `killed` means the run was stopped rather than that it failed,
by either route: this adapter's own stop path (which records exit 143) or an exit
carrying one of the signal conventions in `KILLED_EXITS` (130/137/143 and their
raw POSIX forms). A non-signal, non-zero exit is `failed`, and so is a run whose
process disappeared without finalizing (recovered as `failed`, exit -1,
`stale_recovered: true`). The sibling adapter maps the same contract the same way
(`adapters/omp-run.py`, `KILLED_EXITS`).

A DSH run's cwd must be the worktree the stage's session recorded: adoption of a
persisted session compares the recorded directory and refuses a mismatch, and a
stage dispatched into the wrong tree is worse than a refusal. This adapter
records the resolved cwd in state.json and never rewrites it. `--permission-mode
workspace-write` and `--approval-policy never` are passed on every start and
resume, because headless has no live approval channel and both must be repeated
when a session is adopted. `DSH_APPROVAL_POLICY` accepts only `never`: any other
value is refused with an error, because a detached run has no channel through
which a live approval could ever arrive.

Detachment
----------
A run must outlive the session that started it, and `dsh` prints nothing useful
until it exits. The adapter therefore spawns a detached *runner* process that
owns the run: POSIX `start_new_session=True` (its own session and process group,
no controlling terminal); Windows `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`
(one hidden console the whole descendant tree inherits, so a `.cmd` shim does not
flash a window). The agent is spawned into its own session too, so a group signal
reaches the tools a dsh run started without signalling the runner that still has
to finalize. `state.json` records the requested flags under `spawn` and what the
runner observed about its own detachment under `detach` (`session_leader`,
`process_group_leader`, `controlling_terminal` on POSIX; the console facts on
Windows, mirroring the reference adapter's rule; the DSH Windows path itself is
documented, not measured, here). Every spawned process's *identity* is recorded
beside its pid — the POSIX start-time stamp read at spawn, or the Windows
creation time — and no signal is ever sent to a pid whose live identity no longer
matches it (see "Process identity" below).

`kill` works without signals: it writes a `stop` control file the runner polls,
waits for the run's own finalizer, and only then escalates to a process-group
TERM/KILL (POSIX) or `taskkill /T /F` (Windows). A run stopped this way ends as
`killed` with exit 143. A run that died without finalizing is finalized as
`failed` with exit -1 by the next `status`/`result`/`list`/`answer`, which sets
`stale_recovered: true` — and only while no `finalized` marker exists, so
recovery stays idempotent.

Process identity
----------------
A recorded pid is not a process: the OS reuses pids, so `kill` (or `start
--replace`) long after a run died could otherwise signal whatever now owns that
pid — on the reference adapter's `os.getpgid` fallback, an entire unrelated
process group. This adapter therefore records `pid_identity`/`agent_pid_identity`
next to the runner and agent pids (the POSIX `/proc/<pid>/stat` start-time field,
`ps -o lstart=` where there is no procfs, `GetProcessTimes` on Windows) and
verifies a live process against that token before signalling it. An unverifiable
identity — missing token, or a token that changed — fails closed: the signal is
not sent, the refusal is reported, and a run whose tree cannot be proven is left
to the recovery path rather than killed by guesswork. The `os.getpgid(pid)`
fallback is gone for the same reason; a group is signalled only as `killpg(pid)`
on a pid this adapter created as a session leader.

Configuration (nothing about one install is baked in)
----------------------------------------------------
    DSH_BIN                    agent CLI (default: dsh); resolved through PATH, so
                               an absolute path works too. On Windows the real
                               executable beside a `.cmd`/`.bat` shim is preferred
                               and executed directly; only when none exists is
                               %COMSPEC% used, with a verified cmd-specific
                               spelling that refuses an argument cmd would split.
    DSH_RUN_ROOT               run root (default: GDD_RUN_ROOT)
    GDD_RUN_ROOT               run root (default below)
    DSH_RUN_PROFILE            launcher profile (default: headless)
    DSH_PERMISSION_MODE        app `--permission-mode` (default: workspace-write)
    DSH_APPROVAL_POLICY        app `--approval-policy`; only the default, `never`,
                               is accepted. A detached run has no live approval
                               channel, so any other value is refused instead of
                               being dispatched where it could never be honoured.
    DSH_RUN_EVENTS_MAX_BYTES   bound for the retained event log (default 8388608).
                               The bound itself is the shared bounded writer shipped
                               next to this file (`events-writer.py`, the one
                               implementation of that bound, also used by the OMP
                               adapters); this key is resolved here and handed to it.
                               state.json and `status` report events_bytes
                               (retained), events_bytes_total, events_truncated and
                               events_dropped_bytes; every counter derived from a
                               truncated stream is flagged *_partial.
    DSH_RUN_START_GRACE_SECONDS
                               how long a run that has recorded no pid is treated as
                               starting rather than dead (default: 60).
    DSH_RUN_STOP_WAIT_SECONDS  how long `kill` waits for a run to finalize itself
                               before forcing its tree (default: 20).
    DSH_RUN_DRAIN_TIMEOUT_SECONDS
                               how long the runner waits for the agent's stdout to
                               reach EOF after the agent exits (default: 30). A
                               process still holding that pipe makes the run end with
                               `stream_incomplete: true` rather than quietly losing
                               the tail of the stream.
    --model, --thinking        refused: the headless app has no such flags, and the
                               provider route/model is the profile's own configuration
                               (presets are not composed here). Fail loudly instead of
                               accepting a selection this route cannot honour.
    --max-time                 no DSH equivalent, so it is the adapter's own deadline:
                               the runner stops the run through the same path `kill`
                               uses and records `killed` (exit 143) with
                               `deadline_exceeded: true`. It is never silently dropped.

`DSH_PROFILE`, `DSH_PROFILE_DIR` and `DSH_SESSION_ID` are DeepSeek Harness's own
identity variables: the harness exports them into every model shell call, so a
stage dispatched from inside a live `dsh` session inherits its caller's profile and
session. This adapter therefore reads **DSH_RUN_PROFILE**, never `DSH_PROFILE`, and
removes all three reserved names from the environment of every child it spawns
(the runner and the agent). The profile it runs and any session id it adopts travel
explicitly on `argv`, so nothing about the calling session can decide what the
worker runs.

The run-root default is one rule on every platform:
${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs, which on Windows resolves under
%USERPROFILE% — deliberately no %LOCALAPPDATA% branch, so the DSH and OMP
adapters (and gdd.py, delivery-state.py) see one tree. Set GDD_RUN_ROOT to move
it. The DSH route writes no ledger row: `ledger.tsv` under a run root is the OMP
adapters' finished-run ledger, and mixing a second route's rows into it would
change what its consumers read. The contract's authority is `state.json` plus the
`finalized` marker, and this adapter writes both.

Run artifacts: <run_root>/<date>/<SLUG>/ = prompt.md, state.json, lock,
events.ndjson, events.stats.json, stderr.log (dsh's own stderr), runner.log (the
runner's output), exit.code, session.id, answer.md, finalized, stop (the kill
request, below), plus run.json and run.sh (POSIX) or run.cmd (Windows) — the exact
invocation, replayable by hand. `lock` holds {"pid","agent_pid","backend",
"started_at","pid_identity","agent_pid_identity"}: `pid` is the detached runner,
`agent_pid` the dsh process it started, and the two identity tokens are what makes
a pid still this run's process (see "Process identity" above). `start` writes the
lock before spawning and the runner only ever adds `pid`, `agent_pid` and their
identities, so a read-modify-write cannot drop a field.
`start.lock` guards the pidless window of one run directory and is released by the
runner once it owns the run. Starting a slug is serialized *across date buckets*
by `<run_root>/<SLUG>.start.lock`, a stable OS lock: a run started before midnight
still occupies its slug after the date rolls over, and `start` treats a live run
of that slug in any date directory as occupying it. `finalize.lock` is held under
a stable OS lock for the duration of finalization — a competitor cannot unlink it
out from under its holder — so two readers seeing the same dead run write one
final state, and a reader that cannot take the lock never finalizes.

Replaying a finished invocation goes through the same fresh-start path: the old
directory is preserved as `<SLUG>.prev-<time>`, then the recorded runner command
starts in a new directory at the original path, with the same prompt, cwd, agent,
profile, mode, policy and flags. The old finalized artifacts are never
overwritten by the replay.

Exit codes: 0 success, 1 refusal or error — the reference adapter's convention.
"""

from __future__ import annotations

import argparse
import glob
import itertools
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
from contextlib import contextmanager
from datetime import datetime, timezone

if os.name == "nt":  # Windows-only: console inspection
    import ctypes

HERE = os.path.dirname(os.path.abspath(__file__))
ADAPTER = os.path.abspath(__file__)
EVENTS_WRITER = os.path.join(HERE, "events-writer.py")
IS_WINDOWS = os.name == "nt"
# Exit codes that mean "the process was stopped", not "it failed": 130 SIGINT
# (raw -2), 137 SIGKILL (raw -9) and 143 SIGTERM (raw -15) by shell convention.
# `killed` therefore covers both routes to a stopped run: this adapter's own stop
# path, which records KILL_EXIT (143), and an exit that carries a signal
# convention. A non-signal, non-zero exit is `failed`. The sibling adapter maps
# the same contract the same way: adapters/omp-run.py documents KILLED_EXITS as
# "exit codes that mean the process was stopped, not it failed".
KILLED_EXITS = (130, -2, 137, -9, 143, -15)
KILL_EXIT = 143
# Creation-flag values as documented by Microsoft, repeated here because
# subprocess only exposes them on Windows.
NO_WINDOW_MASK = 0x08000000
NEW_GROUP_MASK = 0x00000200
# Characters that may be handed to `cmd.exe /c` verbatim. cmd re-parses the whole
# /c line, so anything outside this set could start a second command, expand a
# variable or split a token; `cmd_safe_argument` refuses it instead of guessing.
# Deliberately absent: whitespace, quotes, %, !, & | < > ( ) ^ ; , = and control
# characters.
CMD_SAFE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-+:@#/\\~[]"
)
# Characters a generated `.cmd` replay line can never spell safely: inside a batch
# line `%` and `!` still expand and a `"` cannot be represented; those arguments
# are refused. Whitespace and cmd's metacharacters are fine *inside* double quotes,
# which is what `batch_argument` adds.
BATCH_REFUSED_CHARS = frozenset('"\r\n\x00%!')
BATCH_QUOTE_CHARS = frozenset(" \t&|<>()^")
# Per-call temp names for write_json: the pid alone is shared by every call in one
# process, so two concurrent writers (the runner's tracker and its own finalizer,
# or an in-process test) would steal each other's temp path.
TEMP_SERIAL = itertools.count()
TEMP_LOCK = threading.Lock()
POLL_SECONDS = 0.25
START_WAIT_SECONDS = 20.0
STOP_WAIT_SECONDS = 20.0
GRACE_SECONDS = 60.0
DRAIN_TIMEOUT_SECONDS = 30.0
# How often the runner republishes counters while the agent works. state.json is
# polled by gdd.py and by operators, so it must stay current without turning a
# long run into a write storm.
STATE_REFRESH_SECONDS = 0.5
DEFAULT_EVENTS_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_PROFILE = "headless"
DEFAULT_PERMISSION_MODE = "workspace-write"
DEFAULT_APPROVAL_POLICY = "never"
# DeepSeek Harness reserves these in the shell environment it hands to every model
# shell call. A stage dispatched from inside a live `dsh` session inherits its
# caller's identity, so they are removed from every child this adapter spawns; the
# profile this route runs is DSH_RUN_PROFILE and travels on argv.
RESERVED_HARNESS_ENV = ("DSH_PROFILE", "DSH_PROFILE_DIR", "DSH_SESSION_ID")
RUN_DIR_PATTERNS = ("*", "*/*", "*/*/runs/*", "*/*/dsh-runs/*")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SANITIZE_RE = re.compile(r"[^a-z0-9._-]+")
# Flags that take a value, for `normalize_argv` below.
VALUE_FLAGS = {
    "--name",
    "--prompt",
    "--cwd",
    "--session-id",
    "--model",
    "--thinking",
    "--max-time",
    "--resume",
    "--run-dir",
    "--agent",
    "--profile",
    "--permission-mode",
    "--approval-policy",
}

EPILOG = """\
Launcher contract (full text: references/transport.md in the gdd skill):
  dsh-run.py start --name SLUG --prompt FILE [--cwd DIR] [--session-id ID]
                   [--model M] [--thinking L] [--max-time D] [--resume ID] [--replace]
  dsh-run.py list | status [SLUG] | result SLUG | answer SLUG | tail SLUG [N] | kill SLUG

Configuration: DSH_BIN, DSH_RUN_ROOT, GDD_RUN_ROOT, DSH_RUN_PROFILE,
DSH_PERMISSION_MODE, DSH_APPROVAL_POLICY, DSH_RUN_EVENTS_MAX_BYTES,
DSH_RUN_START_GRACE_SECONDS, DSH_RUN_STOP_WAIT_SECONDS,
DSH_RUN_DRAIN_TIMEOUT_SECONDS.

DSH_APPROVAL_POLICY is accepted only as `never` (its default): a detached run has
no live approval channel, so this adapter refuses any other value with an error
rather than dispatching a policy the run could never honour.

The profile key is DSH_RUN_PROFILE, not DSH_PROFILE: DSH_PROFILE, DSH_PROFILE_DIR
and DSH_SESSION_ID are reserved by DeepSeek Harness and are deliberately removed
from the environment of every child this adapter spawns (the profile and any
session id travel on argv instead).

On Windows, a `.cmd`/`.bat` DSH_BIN is dispatched as the real executable beside it
when one exists; otherwise it goes through %COMSPEC% with a verified cmd-specific
spelling, and an argument cmd.exe would re-parse (a session id containing `&`, a
path containing a space) is refused rather than dispatched.

Completion: exit 0 and the last `final` event carrying reason.kind == completed.
`--model`/`--thinking` are refused (the headless app has no such flags);
`--max-time` is this adapter's own deadline and records `killed` (143).
"""


def die(message, code=1):
    print(f"dsh-run: {message}", file=sys.stderr)
    sys.exit(code)


def warn(message):
    sys.stderr.write(f"dsh-run: {message}\n")


def normalize_argv(argv):
    """Fold `--flag value` into `--flag=value` when the value looks like an option.

    argparse refuses a value that begins with `-`, while a shell hands a launcher
    one token either way; joining them keeps the two spellings interchangeable
    with the reference adapter.
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
    """Per-user state root: $XDG_STATE_HOME, else $HOME/.local/state."""
    return os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )


def run_root() -> str:
    # Absolute: the runner gets the run's cwd, so a relative root would mean two
    # different directories to the launcher and to the run it started.
    return os.path.abspath(
        os.path.expanduser(
            os.environ.get("DSH_RUN_ROOT")
            or os.environ.get("GDD_RUN_ROOT")
            or os.path.join(state_home(), "gdd", "runs")
        )
    )


def env_seconds(name, default) -> float:
    """A positive number of seconds from the environment, else the default."""
    try:
        value = float((os.environ.get(name) or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def start_grace_seconds() -> float:
    return env_seconds("DSH_RUN_START_GRACE_SECONDS", GRACE_SECONDS)


def stop_wait_seconds() -> float:
    return env_seconds("DSH_RUN_STOP_WAIT_SECONDS", STOP_WAIT_SECONDS)


def drain_timeout_seconds() -> float:
    return env_seconds("DSH_RUN_DRAIN_TIMEOUT_SECONDS", DRAIN_TIMEOUT_SECONDS)


def events_max_bytes():
    """(cap, warning): the retained event log's bound, DSH_RUN_EVENTS_MAX_BYTES."""
    raw = (os.environ.get("DSH_RUN_EVENTS_MAX_BYTES") or "").strip()
    if not raw:
        return DEFAULT_EVENTS_MAX_BYTES, None
    try:
        value = int(raw, 10)
    except ValueError:
        return DEFAULT_EVENTS_MAX_BYTES, (
            f"DSH_RUN_EVENTS_MAX_BYTES={raw!r} is not an integer; using default "
            f"{DEFAULT_EVENTS_MAX_BYTES} bytes"
        )
    if value <= 0:
        return DEFAULT_EVENTS_MAX_BYTES, (
            f"DSH_RUN_EVENTS_MAX_BYTES={value} is not positive; using default "
            f"{DEFAULT_EVENTS_MAX_BYTES} bytes"
        )
    return value, None


def dsh_binary() -> str:
    return os.environ.get("DSH_BIN") or "dsh"


def dsh_profile() -> str:
    # DSH_RUN_PROFILE, not DSH_PROFILE: the latter is the *harness's* identity key
    # (see RESERVED_HARNESS_ENV and the module docstring), not this launcher's.
    return os.environ.get("DSH_RUN_PROFILE") or DEFAULT_PROFILE


def child_env() -> dict:
    """The environment for a spawned child, without the harness's reserved identity.

    A caller inside a live `dsh` session has DSH_PROFILE, DSH_PROFILE_DIR and
    DSH_SESSION_ID exported into its shell; letting them reach the runner or the
    agent would let the caller's session decide what the worker runs. The profile
    and any adopted session id are passed on argv, so these three are dropped and
    everything else is passed through unchanged.
    """
    env = dict(os.environ)
    for name in RESERVED_HARNESS_ENV:
        env.pop(name, None)
    return env


def date_stamp() -> str:
    """The date bucket a run started right now is filed under.

    One place for `start` and for callers that need to find the directory a run
    created, so the two can never disagree about how a run is dated.
    """
    return datetime.now().strftime("%Y-%m-%d")


def permission_mode() -> str:
    return os.environ.get("DSH_PERMISSION_MODE") or DEFAULT_PERMISSION_MODE


def approval_policy() -> str:
    return os.environ.get("DSH_APPROVAL_POLICY") or DEFAULT_APPROVAL_POLICY


def parse_max_time(value):
    """Positive seconds, or None. Raises ValueError for anything else."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        seconds = float(text)
    except ValueError:
        raise ValueError(
            f"--max-time must be a positive number of seconds (got {text!r}); DSH has no "
            "task-deadline flag, so this adapter enforces its own"
        ) from None
    if not seconds > 0 or seconds == float("inf"):
        raise ValueError(f"--max-time must be a positive number of seconds (got {text!r})")
    return seconds


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


def json_temp_path(path) -> str:
    """A temp name unique per call, not merely per process.

    The pid alone is shared by every call in one interpreter, so two writers in
    one process (the runner's tracker and its own finalizer, or an in-process
    caller) would otherwise race on the same temp path and could steal or delete
    each other's half-written file.
    """
    with TEMP_LOCK:
        serial = next(TEMP_SERIAL)
    return f"{path}.{os.getpid()}.{threading.get_ident()}.{serial}.tmp"


def write_json(path, payload) -> None:
    """Replace atomically: gdd.py polls state.json and must never read half of it.

    On Windows the replace needs retries: `os.replace` is MoveFileEx, which fails
    with WinError 5 while any process holds the destination open. Retry briefly,
    then degrade to an in-place write with a note on stderr: a torn read is bad, a
    lost run is worse.
    """
    tmp = json_temp_path(path)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 + 0.05 * (attempt % 5))
        except OSError:
            remove_quietly(tmp)
            raise
    warn(f"{path} stayed locked; written in place")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    remove_quietly(tmp)


def remove_quietly(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def close_quietly(stream) -> None:
    try:
        stream.close()
    except (OSError, ValueError, AttributeError):
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
    """Interpreter for child Python processes (python.exe, never pythonw.exe)."""
    if IS_WINDOWS:
        console = os.path.join(os.path.dirname(sys.executable), "python.exe")
        if os.path.exists(console):
            return console
    return sys.executable


# -- processes ---------------------------------------------------------------


def detach_flags() -> int:
    """Creation flags for a run that must outlive its caller and flash nothing."""
    return NO_WINDOW_MASK | NEW_GROUP_MASK if IS_WINDOWS else 0


def hidden_flags() -> int:
    """Creation flags for a short-lived helper: never a window of its own."""
    return NO_WINDOW_MASK if IS_WINDOWS else 0


def pid_alive(pid) -> bool:
    """Is this pid a live process?

    os.kill(pid, 0) is not a liveness check on Windows for a process in another
    session: it raises AccessDenied. OpenProcess + GetExitCodeProcess answers the
    same question for a process this user cannot fully open.
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


def _proc_stat_identity(pid) -> str:
    """The Linux `/proc/<pid>/stat` start-time stamp (field 22), or "".

    Field 22 is the process's start time in clock ticks since boot; it is stable
    for the process's lifetime and different for a recycled pid.
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            raw = handle.read()
    except OSError:
        return ""
    # `comm` is parenthesized and may itself contain spaces or parentheses, so
    # parse from the last ')' and count from `state` (field 3) to field 22.
    closing = raw.rfind(b")")
    if closing < 0:
        return ""
    fields = raw[closing + 1 :].split()
    if len(fields) < 20:
        return ""
    try:
        return f"proc:{int(fields[19])}"
    except ValueError:
        return ""


def _ps_identity(pid) -> str:
    """`ps` start time, for POSIX systems without procfs (macOS, BSD)."""
    try:
        proc = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            creationflags=hidden_flags(),
        )
    except OSError:
        return ""
    text = (proc.stdout or "").strip()
    return f"ps:{text}" if proc.returncode == 0 and text else ""


def _windows_identity(pid) -> str:
    """The Windows process creation time (FILETIME), or ""."""
    QUERY_LIMITED = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(QUERY_LIMITED, False, int(pid))
    if not handle:
        return ""
    try:
        created = ctypes.c_ulonglong()
        exited = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return ""
        return f"win:{created.value}"
    finally:
        kernel32.CloseHandle(handle)


def process_identity(pid) -> str:
    """A token naming the process instance behind `pid`, or "" when unverifiable.

    Recorded next to every pid this adapter spawns and re-read before any signal
    is sent: a pid whose identity changed was reused, and belongs to someone else.
    The platform order — procfs, `ps`, Windows creation time — is what makes the
    token available on every route; where none of them answers, "" is returned and
    signalling fails closed rather than guessing.
    """
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return ""
    if IS_WINDOWS:
        return _windows_identity(pid)
    return _proc_stat_identity(pid) or _ps_identity(pid)


def identity_ok(pid, identity) -> bool:
    """Is the live process behind `pid` still the one `identity` names?

    Used before any signal: a missing recorded token, or an unreadable current
    one, is *not* proof and fails closed.
    """
    if not identity:
        return False
    current = process_identity(pid)
    return bool(current) and current == str(identity)


def identity_changed(pid, identity) -> bool:
    """Is a live process conclusively *not* the one `identity` names?

    Used for liveness: only a token that was read and differs marks a reused pid.
    A token that could not be read at all leaves the question open, and a run
    that might be live is not declared dead on a failed read.
    """
    if not identity:
        return False
    current = process_identity(pid)
    return bool(current) and current != str(identity)


def lock_of(run_dir) -> dict:
    lock = read_json(os.path.join(run_dir, "lock"), {})
    return lock if isinstance(lock, dict) else {}


def update_lock(run_dir, **fields) -> dict:
    lock = lock_of(run_dir)
    lock.update(fields)
    write_json(os.path.join(run_dir, "lock"), lock)
    return lock


def recorded_processes(run_dir, state=None) -> list:
    """(pid, identity) pairs that prove the run is live, runner first.

    Identity comes from the field the runner recorded at spawn
    (`pid_identity`/`agent_pid_identity`), and a lock entry is preferred over a
    state entry for the same pid only when it carries more information.
    """
    if state is None:
        state = read_state_file(run_dir)
    lock = lock_of(run_dir)
    found = []
    for key, identity_key in (("pid", "pid_identity"), ("agent_pid", "agent_pid_identity")):
        for source in (lock, state):
            pid = source.get(key)
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                continue
            identity = source.get(identity_key) or ""
            for index, (known, known_identity) in enumerate(found):
                if known == pid:
                    if not known_identity and identity:
                        found[index] = (pid, identity)
                    break
            else:
                found.append((pid, identity))
    return found


def recorded_pids(run_dir, state=None) -> list:
    """Pids that prove the run is live: the runner and the dsh process it started."""
    return [pid for pid, _ in recorded_processes(run_dir, state)]


def run_alive(run_dir, state=None) -> bool:
    """Is a recorded process still alive *and* still the one that was recorded?

    A pid whose recorded identity no longer matches is a reused pid, not this
    run's. When no identity was recorded at all — an older run, or a platform
    with no usable token — liveness is the only evidence there is and it is
    trusted here: declaring a possibly-live run dead is what lets a reader
    finalize work that is still being written. Signalling makes the opposite
    choice, because a wrong signal cannot be taken back (see `signal_group`).
    Only a token that was read and differs marks a reused pid; a read that failed
    leaves the question open and the run alive.
    """
    if state is None:
        state = read_state_file(run_dir)
    for pid, identity in recorded_processes(run_dir, state):
        if not pid_alive(pid):
            continue
        if identity_changed(pid, identity):
            continue
        return True
    return False


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
    """A young run that has recorded no pid yet is starting, not dead."""
    if recorded_pids(run_dir, state):
        return False
    return state_age_seconds(state) < start_grace_seconds()


def starting_claim(run_dir) -> bool:
    """Is another `start` still writing this run directory?"""
    path = os.path.join(run_dir, "start.lock")
    if not os.path.exists(path):
        return False
    return time.time() - mtime_of(path) < start_grace_seconds()


def claim_start(run_dir) -> bool:
    """Take the exclusive right to start this slug; False when another start holds it."""
    path = os.path.join(run_dir, "start.lock")
    for attempt in range(2):
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            return True
        except FileExistsError:
            if attempt or not starting_claim(run_dir):
                remove_quietly(path)
                continue
            return False
        except OSError:
            return True  # a claim this process cannot take must not block starting
    return False


@contextmanager
def slug_start_claim(root, slug):
    """Hold the OS lock that claims one slug across every date bucket.

    The lock file is a stable sibling of the date directories
    (`<root>/<slug>.start.lock`), never inside one: the in-directory `start.lock`
    guards only the pidless window of a single directory, while this claim is
    what stops a run started before midnight from being started again after it.
    Keep the file: unlinking a locked inode would let a competitor lock a fresh
    inode at the same path. The kernel releases the claim when the handle closes,
    even if the starter dies; unlike an age-based file, its age is not ownership.
    """
    handle = None
    try:
        os.makedirs(root, exist_ok=True)
        handle = open(os.path.join(root, f"{slug}.start.lock"), "a+b")
        if IS_WINDOWS:
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        close_quietly(handle)
        yield False
        return
    try:
        yield True
    finally:
        close_quietly(handle)


@contextmanager
def finalize_claim(run_dir, wait=0.0):
    """Hold the OS lock that is the exclusive right to finalize one run.

    Two readers can see the same stale `running` state at once; without a claim
    both would write final artifacts. This is a stable OS lock on `finalize.lock`
    rather than an exclusively-created file: a competitor cannot delete a lock out
    from under its holder (unlinking a locked inode would let a third process lock
    a fresh one at the same path), and the kernel releases it if the holder dies,
    so an abandoned claim never strands a run. There is no stale-takeover path:
    what cannot be taken is waited for (`wait` seconds) or reported, never
    ignored. Yields True while the claim is held, False otherwise.
    """
    path = os.path.join(run_dir, "finalize.lock")
    handle = None
    try:
        handle = open(path, "a+b")
    except OSError:
        close_quietly(handle)
        yield False
        return
    if IS_WINDOWS:
        import msvcrt

        def try_lock():
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

        def unlock():
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    else:
        import fcntl

        def try_lock():
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        def unlock():
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    locked = False
    deadline = time.monotonic() + max(0.0, wait)
    try:
        while True:
            try:
                try_lock()
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(POLL_SECONDS)
        yield locked
    finally:
        if locked:
            try:
                unlock()
            except OSError:
                pass
        close_quietly(handle)


def observe_detachment() -> dict:
    """What this process can prove about its own detachment (not what was asked)."""
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
    """Start the detached runner: POSIX own session, Windows hidden console.

    The child environment is scrubbed of the harness's reserved identity keys
    (`child_env`), so a caller inside a live `dsh` session cannot shape the run.
    """
    with open(log_path, "ab") as log:
        kwargs = {
            "cwd": cwd,
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
            "env": child_env(),
        }
        if IS_WINDOWS:
            kwargs["creationflags"] = detach_flags()
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(argv, **kwargs)


def spawn_agent(argv, cwd, stderr, prompt_path):
    """Start dsh inside the run, in its own process group on POSIX.

    Its own session keeps a group signal from reaching the runner, which still has
    to finalize the run after the agent is gone. stdin is the prompt file: the
    headless app reads the task from stdin when the argument is a lone `-`.
    """
    stdin = open(prompt_path, "rb")
    kwargs = {
        "cwd": cwd,
        "stdin": stdin,
        "stdout": subprocess.PIPE,
        "stderr": stderr,
        # Also scrubbed here, not only around the runner: `_run` (the replay path)
        # can be entered directly by a recorded run.sh inside a live dsh session.
        "env": child_env(),
    }
    try:
        if IS_WINDOWS:
            kwargs["creationflags"] = hidden_flags()
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(argv, **kwargs)
    finally:
        # The child holds its own descriptor; the parent must not keep the prompt
        # file open or a later move-aside of the run directory would be blocked.
        close_quietly(stdin)


def signal_group(pid, signum, identity="") -> bool:
    """Signal the process group this pid leads, only when it is provably ours.

    POSIX only; returns True when a signal was sent. `pid` is a group leader by
    construction (`start_new_session` / `CREATE_NEW_PROCESS_GROUP`), so `killpg`
    with that pid reaches the tools the agent started without reaching the runner.
    The identity recorded when this pid was spawned must still match the live
    process: a mismatch — or a missing token, when the platform cannot supply one
    — is a reused or unverifiable pid, and it is never signalled. The
    `os.getpgid(pid)` fallback is gone on purpose: it would signal whatever group
    the pid *now* belongs to, which is exactly the unrelated job this guard keeps
    safe. A pid that is already gone is different: any process group still bearing
    that id can only be the one it created, so its surviving members are still
    signalled.
    """
    if IS_WINDOWS:
        return False
    if pid_alive(pid):
        if not identity_ok(pid, identity):
            warn(
                f"not signalling pid {pid}: it is no longer the process this run recorded "
                f"(identity {'missing' if not identity else 'changed'}); refusing to guess"
            )
            return False
        try:
            os.killpg(pid, signum)
            return True
        except OSError:
            try:
                os.kill(pid, signum)
                return True
            except OSError:
                return False
    try:
        os.killpg(pid, signum)
        return True
    except OSError:
        return False


def group_alive(pgid) -> bool:
    """Is any process still in this process group? POSIX only; False on Windows."""
    if IS_WINDOWS or not isinstance(pgid, int) or pgid <= 0:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def tree_alive(pid) -> bool:
    """The process itself, or on POSIX any surviving member of the group it leads."""
    return pid_alive(pid) or group_alive(pid)


def terminate_tree(pid, signum, identity="") -> bool:
    """Stop one recorded process tree, and only when it is provably this run's.

    Windows has no groups: `taskkill /T /F` stops a tree by pid, and the same
    identity gate applies before it runs.
    """
    if IS_WINDOWS:
        if not pid_alive(pid):
            return False
        if not identity_ok(pid, identity):
            warn(
                f"not stopping pid {pid}: it is no longer the process this run recorded "
                f"(identity {'missing' if not identity else 'changed'}); refusing to guess"
            )
            return False
        run_quiet(["taskkill", "/T", "/F", "/PID", str(pid)])
        return True
    return signal_group(pid, signum, identity)


def terminate_agent(process, agent_identity="") -> tuple:
    """Stop the agent and the tools under it; return (exit code, surviving pids)."""
    agent = process.pid

    def settled() -> bool:
        process.poll()  # reap a zombie before judging the group
        return not tree_alive(agent)

    if process.poll() is None:
        terminate_tree(agent, signal.SIGTERM, agent_identity)
        for _ in range(20):
            if settled():
                break
            time.sleep(POLL_SECONDS)
    for _ in range(40):
        if settled():
            break
        time.sleep(POLL_SECONDS)
    if not settled():
        terminate_tree(agent, signal.SIGKILL, agent_identity)
        for _ in range(20):
            if settled():
                break
            time.sleep(POLL_SECONDS)
    return KILL_EXIT, ([] if settled() else [agent])


def kill_tree(run_dir, state=None) -> bool:
    """Force an unresponsive run to stop: its groups (POSIX) or its trees (Windows).

    Every signal is gated on the identity recorded at spawn; a recorded pid whose
    live identity no longer matches is reported and left alone. Returns True once
    nothing recorded is still alive.
    """
    processes = recorded_processes(run_dir, state)
    if not processes:
        return False
    if IS_WINDOWS:
        for pid, identity in processes:
            terminate_tree(pid, 0, identity)
        return not any(pid_alive(pid) for pid, _ in processes)
    for pid, identity in processes:
        signal_group(pid, signal.SIGTERM, identity)
    for _ in range(20):
        if not any(tree_alive(pid) for pid, _ in processes):
            return True
        time.sleep(POLL_SECONDS)
    for pid, identity in processes:
        signal_group(pid, signal.SIGKILL, identity)
    for _ in range(20):
        if not any(tree_alive(pid) for pid, _ in processes):
            return True
        time.sleep(POLL_SECONDS)
    return False


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


def bucket_root(run_dir) -> str:
    """The run root above a run directory's date bucket.

    Deriving the root from the run directory (rather than from the environment)
    keeps the slug claim beside the run it protects even when a replay runs with
    a different DSH_RUN_ROOT than the one the recorded run was filed under.
    """
    run_dir = os.path.abspath(run_dir)
    bucket = os.path.dirname(run_dir)
    return os.path.dirname(bucket) if DATE_RE.match(os.path.basename(bucket)) else bucket


def slug_run_dirs(root, slug):
    """Every run directory for this slug under the root, newest date first.

    Not `find_run`'s newest-only answer: a slug can have one run per date bucket,
    and `start` has to see all of them to know whether the slug is occupied.
    """
    found = []
    seen = set()
    for pattern in RUN_DIR_PATTERNS:
        for path in glob.glob(os.path.join(root, pattern)):
            if os.path.basename(path) != slug or not os.path.isdir(path):
                continue
            if not any(
                os.path.exists(os.path.join(path, marker))
                for marker in ("state.json", "lock", "prompt.md")
            ):
                continue
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            found.append(path)
    return newest_first(found)


def find_run(name):
    """Newest run directory called NAME, or None.

    A directory with no state.json is still a run directory: `status` reports it
    as unknown, which is the honest answer for a launcher that died before it
    could write one.
    """
    slug = sanitize(name)
    if not slug:
        return None
    candidates = slug_run_dirs(run_root(), slug)
    return candidates[0] if candidates else None


def occupying_run(root, slug):
    """(run_dir, state): this slug's unfinished run, in any date bucket, or (None, {}).

    A run directory is unfinished while its `finalized` marker is missing, and it
    occupies its slug wherever it is dated: `start` must not create a second run
    for the same slug just because midnight moved the date bucket. Dead
    unfinished runs are settled first by `effective_state`, so what remains — and
    what this returns — is work that is still live, still inside its startup
    grace, or still claimed by a starting process.
    """
    for candidate in slug_run_dirs(root, slug):
        state, _ = effective_state(candidate)
        if os.path.exists(os.path.join(candidate, "finalized")):
            continue
        if (
            run_alive(candidate, state)
            or is_starting(candidate, state)
            or starting_claim(candidate)
        ):
            return candidate, state
    return None, {}


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
    return namespace["Writer"]


class EventLog:
    """This run's bounded NDJSON log: the shared writer plus its stats sidecar."""

    def __init__(self, run_dir):
        cap, warning = events_max_bytes()
        if warning:
            warn(warning)
        # The bound is resolved from DSH_RUN_EVENTS_MAX_BYTES here and handed to
        # the shared writer's constructor, so the DSH key is the only knob this
        # route needs and no OMP-named default warning lands in runner.log.
        writer_class = load_writer()
        self.path = os.path.join(run_dir, "events.ndjson")
        # passthrough=False: this adapter's own stdout is runner.log, and the
        # writer's terminal passthrough would copy the whole stream there
        # unbounded, so the event bound would bound nothing.
        self.writer = writer_class(run_dir, cap, defaulted=warning is not None, passthrough=False)
        self.finished = False
        self.lock = threading.Lock()

    def feed(self, raw) -> None:
        with self.lock:
            if self.finished:
                # A reader thread can still be draining a stream a descendant kept
                # open. After `finish()` its remaining lines are dropped on purpose:
                # the run records `stream_incomplete` rather than pretending to have
                # them.
                return
            self.writer.feed(raw)

    def finish(self) -> None:
        with self.lock:
            self.finished = True
            self.writer.finish()


def usage_of(event) -> dict:
    """The token accounting one status event carries, normalized, or {}."""
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return {}
    fields = {
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
        "total_tokens": usage.get("totalTokens"),
        "cache_read_tokens": usage.get("cacheReadTokens"),
    }
    numbers = {}
    for key, value in fields.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numbers[key] = value
    return numbers


def summarize(run_dir, events_path) -> dict:
    """Fold the retained DSH event stream into the run's answer and counters.

    The retained stream is the source, not a side channel: a run finalized by a
    reader after its runner died has nothing else to read. The sidecar supplies
    exact byte totals when it is present; the stream's own `truncated` marker
    bounds the loss when it is not.
    """
    stats = read_json(os.path.join(run_dir, "events.stats.json"), {})
    stats = stats if isinstance(stats, dict) else {}
    session_id = ""
    answer = ""
    answer_source = ""
    last_text = ""
    final_reason = None
    error = ""
    turns = 0
    tool_calls = 0
    usage = {}
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
                if kind == "session":
                    session_id = event.get("sessionId") or session_id
                elif kind == "status":
                    if event.get("phase") == "turn_end":
                        turns += 1
                    found = usage_of(event)
                    if found:
                        usage = found
                elif kind == "tool_call":
                    tool_calls += 1
                elif kind == "text":
                    text = event.get("text")
                    if isinstance(text, str) and text:
                        last_text = text
                elif kind == "final":
                    reason = event.get("reason")
                    final_reason = reason.get("kind") if isinstance(reason, dict) else None
                    text = event.get("text")
                    answer = text if isinstance(text, str) else ""
                    answer_source = "final"
                elif kind == "error":
                    error = str(event.get("message") or "")
    if answer_source != "final" and last_text:
        # No `final` event: this run was stopped or died. The last committed
        # assistant text is the most that stream can honestly offer.
        answer = last_text
        answer_source = "text"
    retained = os.path.getsize(events_path) if os.path.exists(events_path) else 0
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
        "answer_source": answer_source,
        "final_reason": final_reason,
        "error": error,
        "turns": turns,
        "tool_calls": tool_calls,
        "usage": usage,
        "events_bytes": retained,
        "events_bytes_total": total_bytes,
        "events_truncated": truncated,
        "events_dropped_bytes": dropped_bytes,
    }


def finalize(run_dir, exit_code, recovered=False, note=None, extra=None, claim_wait=0.0) -> dict:
    """Write state.json, answer.md, exit.code, the `finalized` marker.

    `claim_wait` is how long to wait for the finalize claim: the runner passes a
    positive value because its own finalization must land, a reader passes 0 and
    reports whatever is on disk when another process is already finalizing. The
    claim is an OS lock (`finalize_claim`), never taken over by age, and a caller
    that cannot take it never continues into finalization. Recheck the marker
    under the claim: another reader may have finished between the caller's marker
    check and this process acquiring the claim.
    """
    with finalize_claim(run_dir, claim_wait) as claimed:
        if not claimed:
            warn(f"{run_dir} is being finalized by another process")
            return read_state_file(run_dir)
        if os.path.exists(os.path.join(run_dir, "finalized")):
            return read_state_file(run_dir)
        return _finalize_locked(run_dir, exit_code, recovered, note, extra)


def _finalize_locked(run_dir, exit_code, recovered, note, extra) -> dict:
    """The finalization itself, with the claim already held."""
    state_path = os.path.join(run_dir, "state.json")
    state = read_state_file(run_dir)
    summary = summarize(run_dir, os.path.join(run_dir, "events.ndjson"))
    if recovered:
        # The process disappeared without finalizing: -1 is the adapter's word for
        # "no exit code was ever observed", never a success.
        verdict = "failed"
    elif exit_code == 0 and summary["final_reason"] == "completed":
        verdict = "done"
    elif exit_code in KILLED_EXITS:
        verdict = "killed"
    else:
        verdict = "failed"
    duration = None
    if state.get("started"):
        try:
            duration = round(
                (datetime.now(timezone.utc) - datetime.fromisoformat(state["started"])).total_seconds(),
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
            "session_id": state.get("session_id") or summary["session_id"] or read_sidecar(run_dir, "session.id"),
            "turns": summary["turns"],
            "tool_calls": summary["tool_calls"],
            "usage": summary["usage"],
            "final_reason": summary["final_reason"],
            "error": summary["error"],
            "answer_chars": len(summary["answer"]),
            "answer_source": summary["answer_source"],
            "events_bytes": summary["events_bytes"],
            "events_bytes_total": summary["events_bytes_total"],
            "events_truncated": truncated,
            "events_dropped_bytes": summary["events_dropped_bytes"],
            "turns_partial": truncated,
            "tool_calls_partial": truncated,
            "usage_partial": truncated,
        }
    )
    if recovered:
        pids = "/".join(str(pid) for pid in recorded_pids(run_dir, state)) or "-"
        state["stale_recovered"] = True
        state["note"] = (
            f"process disappeared without finalizing (backend dsh; runner/agent pids {pids} "
            "are gone); finalized with exit -1"
        )
    elif note:
        state["note"] = note
    if extra:
        state.update(extra)
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
    return state


def effective_state(run_dir):
    """(state, recovered): settle a run whose own finalizer did not get that far.

    Two cases, both idempotent and both guarded by the marker: a run still
    `running` with nothing alive is a crash (finalized `failed`, exit -1,
    `stale_recovered`), and a run whose state is already terminal but whose
    `finalized` marker is missing died between publishing the state and writing
    the marker (finalized again from the exit code it recorded).
    """
    state = read_state_file(run_dir)
    if os.path.exists(os.path.join(run_dir, "finalized")):
        return state, False
    recorded = state.get("state")
    if recorded not in ("running", "done", "killed", "failed"):
        return state, False
    if run_alive(run_dir, state) or is_starting(run_dir, state):
        return state, False
    if recorded == "running":
        return finalize(run_dir, -1, recovered=True, claim_wait=0.0), True
    exit_code = state.get("exit")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        exit_code = -1
    repaired = finalize(
        run_dir,
        exit_code,
        note=(
            f"state.json was published as {recorded} without the finalized marker (the "
            "finalizer died between the two); finalized again from the recorded exit code"
        ),
        extra={"finalize_repaired": True},
        claim_wait=0.0,
    )
    if not os.path.exists(os.path.join(run_dir, "finalized")):
        return repaired, False
    return repaired, True


def reported_state(state) -> dict:
    return state if state.get("state") else {**state, "state": "unknown"}


def events_view(run_dir, state) -> dict:
    """state.json plus the liveness and event-accounting facts `status` adds."""
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
        "backend": state.get("backend") or "dsh",
        "alive": run_alive(run_dir, state),
        "events_bytes": retained,
        "events_bytes_total": total,
        "events_truncated": truncated,
        "events_dropped_bytes": dropped,
    }


# -- start -------------------------------------------------------------------


def agent_args(session_id, profile, mode, policy) -> list:
    """The dsh command line, launcher flags first, then the app's own flags.

    A lone `-` asks the headless app to read the task from stdin, which is how the
    prompt travels verbatim. `--permission-mode` and `--approval-policy` are
    always sent, because DSH requires both to be repeated when a session is
    adopted; `never` is the unattended default (there is no live approval channel).
    """
    argv = ["--profile", profile]
    argv += ["--json"]
    if session_id:
        argv += ["--session-id", session_id]
    argv += ["--permission-mode", mode, "--approval-policy", policy, "-"]
    return argv


def resolve_binary(binary) -> str:
    """Absolute path of the dsh CLI, or "" — a `.cmd` shim is fine on Windows."""
    candidate = os.path.expanduser(str(binary))
    if not (os.sep in candidate or (os.altsep and os.altsep in candidate)):
        candidate = shutil.which(candidate) or ""
    if not candidate or not os.path.isfile(candidate):
        return ""
    if not IS_WINDOWS and not os.access(candidate, os.X_OK):
        return ""
    # Absolute: the runner runs in the run's cwd, not the dispatcher's.
    return os.path.abspath(candidate)


def real_executable(candidate) -> str:
    """The real executable behind a Windows `.cmd`/`.bat` shim, or "".

    A shim is a wrapper; when the executable of the same base name sits beside it
    (as installers ship, and as PATHEXT order already prefers), running that
    directly is both faster and safe: there is no cmd.exe in the chain, so no
    command line for cmd to re-parse. Never guesses by parsing the shim's body —
    a wrong guess would change what runs.
    """
    if not IS_WINDOWS:
        return ""
    base, extension = os.path.splitext(str(candidate))
    if extension.lower() not in (".cmd", ".bat"):
        return ""
    for suffix in (".exe", ".com"):
        real = base + suffix
        if os.path.isfile(real):
            return real
    return ""


def cmd_safe_argument(value) -> str:
    """One argument spelled so `cmd.exe /c` cannot re-parse it, or ValueError.

    A line handed to `cmd.exe /c` is parsed by cmd itself: an unquoted `&`, `|`,
    `<`, `>` or `^` starts another command or redirects, `%` expands, and there is
    no quoting scheme that survives both cmd's parser and the C runtime's argv
    reconstruction when the line itself contains quotes. This adapter therefore
    passes only arguments built from `CMD_SAFE_CHARS` verbatim and refuses
    everything else — including whitespace — instead of guessing: a wrong guess
    runs a second command.
    """
    text = str(value)
    if not text:
        raise ValueError("an empty argument cannot be passed through cmd.exe safely")
    bad = "".join(sorted({ch for ch in text if ch not in CMD_SAFE_CHARS}))
    if bad:
        raise ValueError(
            f"argument {text!r} contains {bad!r}, which cmd.exe would re-parse; point DSH_BIN "
            "at the real executable behind the .cmd/.bat shim, or remove the character — this "
            "adapter will not dispatch an argument it cannot spell safely"
        )
    return text


def cmd_command_line(argv) -> str:
    """The `cmd.exe /c` command line for argv, or ValueError (see `cmd_safe_argument`)."""
    return " ".join(cmd_safe_argument(item) for item in argv)


def batch_argument(value) -> str:
    """One argument for a generated `.cmd` replay line, or ValueError.

    Unlike a dispatch through `cmd /c`, a batch line's double quotes are handled
    by cmd itself: a token wrapped in quotes is one token even when it contains
    spaces or the metacharacters `& | < > ( ) ^`. `%` and `!` still expand inside
    those quotes and a `"` cannot be represented, so such arguments are refused
    rather than emitted into a script that would run something else.
    """
    text = str(value)
    bad = "".join(sorted({ch for ch in text if ch in BATCH_REFUSED_CHARS}))
    if bad:
        raise ValueError(
            f"argument {text!r} cannot be spelled safely in a generated .cmd script "
            f"(it contains {bad!r})"
        )
    if text == "" or any(ch in BATCH_QUOTE_CHARS for ch in text):
        return f'"{text}"'
    return text


def agent_command(agent, argv) -> list:
    """The full command line, preferring the real executable behind a shim.

    A Windows `.cmd`/`.bat` shim is only dispatched through %COMSPEC% when no real
    executable sits beside it; that route uses `cmd_command_line`'s verified
    spelling and raises instead of serializing an argument cmd would split.
    """
    if IS_WINDOWS and os.path.splitext(agent)[1].lower() in (".cmd", ".bat"):
        real = real_executable(agent)
        if real:
            return [real, *argv]
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/d", "/s", "/c", cmd_command_line([agent, *argv])]
    return [agent, *argv]


def runner_argv(run_dir, prompt, cwd, agent, args, slug, profile, mode, policy) -> list:
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
        "--name",
        slug,
        "--profile",
        profile,
        "--permission-mode",
        mode,
        "--approval-policy",
        policy,
    ]
    if args.session_id:
        argv += ["--session-id", args.session_id]
    elif args.resume:
        argv += ["--resume", args.resume]
    if args.max_time:
        argv += ["--max-time", str(args.max_time)]
    return argv


def replay_exports() -> list:
    """Environment carried into the replay script: the integer-valued knobs only.

    A raw value is not written into a generated script: anything cmd would expand
    (`%`, `!`) must never reach run.cmd, and the documented shape of this knob is
    an integer, so only that shape is exported.
    """
    raw = (os.environ.get("DSH_RUN_EVENTS_MAX_BYTES") or "").strip()
    return [("DSH_RUN_EVENTS_MAX_BYTES", raw)] if raw.isdigit() else []


def write_replay(run_dir, payload) -> None:
    """The exact invocation: run.json for tools, plus the shell this platform uses.

    Raises ValueError when an argument cannot be spelled safely in the generated
    script (see `batch_argument`); the caller refuses the start rather than
    writing a replay line that would run a different command.
    """
    argv = payload["argv"]
    write_json(os.path.join(run_dir, "run.json"), payload)
    exports = replay_exports()
    if IS_WINDOWS:
        lines = [
            "@echo off",
            f"rem generated by dsh-run.py — replay of {payload.get('name')}",
            f"cd /d {batch_argument(payload['cwd'])} || exit /b 90",
        ]
        lines += [f'set "{key}={value}"' for key, value in exports if value]
        lines.append(" ".join(batch_argument(item) for item in argv))
        path = os.path.join(run_dir, "run.cmd")
        with open(path, "w", encoding="utf-8", newline="\r\n") as handle:
            handle.write("\n".join(lines) + "\n")
        return
    lines = [
        "#!/usr/bin/env bash",
        f"# generated by dsh-run.py — replay of {payload.get('name')}",
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
    run_dir = os.path.join(root, date_stamp(), sanitize(args.name))
    agent = resolve_binary(dsh_binary())
    if not agent:
        die(f"start: dsh binary not found at {dsh_binary()} (set DSH_BIN)")
    return start_run(
        args, run_dir, agent, args.replace, dsh_profile(), permission_mode(), approval_policy()
    )


def start_run(args, run_dir, agent, replace, profile, mode, policy) -> int:
    """Initialize and dispatch a fresh run, for `start` or a completed replay."""
    slug = sanitize(args.name)
    if not slug:
        die("start: --name is required (and must not sanitize to nothing)")
    if getattr(args, "model", None):
        die(
            "start: --model is not supported on the DSH route: the headless app has no model "
            "flag and presets are not composed there, so the provider route/model is the "
            "profile's own configuration (see references/transport.md)"
        )
    if getattr(args, "thinking", None):
        die(
            "start: --thinking is not supported on the DSH route: the headless app has no "
            "thinking flag; set it in the profile's own configuration instead"
        )
    if (policy or DEFAULT_APPROVAL_POLICY) != DEFAULT_APPROVAL_POLICY:
        die(
            f"start: DSH_APPROVAL_POLICY={policy!r} is refused: this route starts a detached, "
            f"unattended run with no live approval channel, so only "
            f"{DEFAULT_APPROVAL_POLICY!r} can be honoured (see --help)"
        )
    session_id = getattr(args, "session_id", None) or ""
    resume = getattr(args, "resume", None) or ""
    if session_id and resume and session_id != resume:
        die(f"start: --session-id {session_id!r} and --resume {resume!r} disagree")
    session_id = session_id or resume
    try:
        max_time = parse_max_time(getattr(args, "max_time", None))
    except ValueError as exc:
        die(f"start: {exc}")
    prompt = os.path.abspath(os.path.expanduser(args.prompt or ""))
    if not os.path.isfile(prompt):
        die("start: --prompt FILE is required and must exist")
    cwd = os.path.abspath(os.path.expanduser(args.cwd or os.getcwd()))
    if not os.path.isdir(cwd):
        die(f"start: --cwd '{args.cwd}' is not a directory")
    try:
        # A replay's prompt lives inside the directory about to be moved aside.
        # Read it first, retaining its exact bytes for the new run's prompt.md.
        with open(prompt, "rb") as handle:
            prompt_bytes = handle.read()
    except OSError as exc:
        die(f"start: cannot read --prompt {prompt}: {exc}")
    try:
        # The agent's exact argv is fixed here, before anything is created: on
        # Windows a `.cmd` shim with no real executable is dispatched through cmd,
        # whose spelling refuses an argument (a session id containing `&`) rather
        # than letting cmd split it into a second command.
        agent_argv = agent_command(agent, agent_args(session_id, profile, mode, policy))
    except ValueError as exc:
        die(f"start: {exc}")

    root = bucket_root(run_dir)
    with slug_start_claim(root, slug) as claimed:
        if not claimed:
            die(
                f"start: another start is claiming run '{slug}' or the claim is unavailable "
                f"(see {os.path.join(root, slug + '.start.lock')})"
            )
        return _start_run_claimed(
            args, run_dir, agent, agent_argv, replace, slug, cwd, prompt_bytes, session_id,
            max_time, profile, mode, policy,
        )


def _start_run_claimed(
    args, run_dir, agent, agent_argv, replace, slug, cwd, prompt_bytes, session_id, max_time,
    profile, mode, policy,
):
    """Check occupancy and initialize only while the stable slug claim is held."""
    occupant, occupant_state = occupying_run(bucket_root(run_dir), slug)
    if occupant:
        if not replace:
            pids = "/".join(str(pid) for pid in recorded_pids(occupant, occupant_state)) or "-"
            die(f"start: run '{slug}' is still running (pid {pids}; use --replace to restart)")
        if not stop_run(occupant, occupant_state):
            die(f"start: could not stop run '{slug}' (see {occupant})")
    if os.path.isdir(run_dir) and not move_aside(run_dir):
        # Refuse rather than mix two runs in one directory: the previous run's
        # `finalized` marker would make the new one look finished.
        die(f"start: cannot move {run_dir} aside for the new run")

    os.makedirs(run_dir, exist_ok=True)
    if not claim_start(run_dir):
        die(f"start: another start is claiming run '{slug}' (see {run_dir})")
    with open(os.path.join(run_dir, "prompt.md"), "wb") as handle:
        handle.write(prompt_bytes)

    state = {
        "name": slug,
        "state": "running",
        "exit": None,
        "cwd": cwd,
        "started": now_iso(),
        "ended": None,
        "duration_s": None,
        "model": None,
        "thinking": None,
        "max_time": max_time,
        "backend": "dsh",
        "profile": profile,
        "permission_mode": mode,
        "approval_policy": policy,
        "run_dir": run_dir,
        "session_id": session_id,
        "resumed_from": session_id or None,
        "events_bytes": 0,
        "events_bytes_total": 0,
        "events_truncated": False,
        "events_dropped_bytes": 0,
        "launcher": ADAPTER,
        "agent": agent,
        # What was requested; the runner records what it observed as `detach`.
        "spawn": {
            "mode": "hidden-console" if IS_WINDOWS else "new-session",
            "creationflags": detach_flags(),
            "platform": sys.platform,
        },
    }
    write_json(os.path.join(run_dir, "state.json"), state)
    # Written before the spawn so the runner's own update cannot race this one:
    # `pid` and `agent_pid` (and their identities) belong to the runner,
    # everything here belongs to `start`.
    write_json(
        os.path.join(run_dir, "lock"),
        {
            "pid": None,
            "agent_pid": None,
            "backend": "dsh",
            "started_at": state["started"],
        },
    )
    command = runner_argv(
        run_dir, os.path.join(run_dir, "prompt.md"), cwd, agent, args, slug, profile, mode, policy
    )
    try:
        write_replay(
            run_dir,
            {
                "name": slug,
                "argv": command,
                "agent_argv": agent_argv,
                "cwd": cwd,
                "agent": agent,
                "profile": profile,
                "permission_mode": mode,
                "approval_policy": policy,
                "prompt": os.path.join(run_dir, "prompt.md"),
                "note": "the exact runner command; a completed replay preserves the previous run",
            },
        )
    except ValueError as exc:
        die(f"start: {exc}")
    try:
        spawn_runner(command, cwd, os.path.join(run_dir, "runner.log"))
    except OSError as exc:
        die(f"start: could not start the run: {exc}")

    started, agent_confirmed = wait_for_start(run_dir)
    if not agent_confirmed:
        # A recorded agent pid is the proof that the run started; without one the
        # runner either failed to spawn the agent or ended before it could. Report
        # what was observed instead of falling back to the runner's pid, which
        # proves only that the detached wrapper is alive.
        if started.get("error"):
            die(f"start: agent did not start: {started['error']}")
        if started.get("state") not in (None, "running"):
            detail = started.get("note") or started.get("error") or started.get("state")
            die(
                f"start: the run ended before the agent started ({detail}; "
                f"see {os.path.join(run_dir, 'runner.log')})"
            )
        die(
            f"start: run did not start: no agent pid was recorded within "
            f"{START_WAIT_SECONDS:g}s (see {os.path.join(run_dir, 'runner.log')})"
        )
    # The agent was spawned and recorded, so the run started. Whether it is still
    # working, already gone, or gone having recorded an `error` event is the run's
    # outcome, finalized in state.json — not a start failure. `start` guarantees
    # the dispatch (the detached runner exists and spawned the agent); `gdd.py`
    # polls the state file for how the run ended.
    pids = recorded_pids(run_dir, started)
    print(f"started: {slug}")
    print("  backend   : dsh")
    print(f"  pid       : {pids[0] if pids else '-'}")
    print(f"  run dir   : {run_dir}")
    print(f"  session id: {started.get('session_id') or '(pending)'}")
    print(f"  events    : {os.path.join(run_dir, 'events.ndjson')}")
    print(f"  summary   : {os.path.join(run_dir, 'run.json')} (replay argv) + state.json")
    return 0


def agent_recorded(state, lock) -> bool:
    """Has the runner recorded the agent it spawned — pid or identity token?

    `agent_pid` and `agent_pid_identity` are written together, and only after
    `spawn_agent` returned, so either field proves the agent process was created.
    Whether that process is still alive or already gone is a different question,
    answered by the run's outcome in state.json.
    """
    return bool(
        state.get("agent_pid")
        or state.get("agent_pid_identity")
        or lock.get("agent_pid")
        or lock.get("agent_pid_identity")
    )


def wait_for_start(run_dir) -> tuple:
    """(state, agent_confirmed): whether `start` may report a started run.

    A recorded agent pid (or its identity token) is the explicit confirmation
    that the agent process was created, so it confirms the dispatch on its own:
    an agent that has already exited — even one that recorded an `error` event —
    still proves the run started, and what became of it is the run's outcome in
    state.json. A terminal state without either field, and the timeout without
    one, are failed starts — never a fallback to the runner's pid, which proves
    only that the detached wrapper is alive.
    """
    deadline = time.monotonic() + START_WAIT_SECONDS
    while True:
        state = read_state_file(run_dir)
        if agent_recorded(state, lock_of(run_dir)):
            return reported_state(state), True
        if state.get("state") not in (None, "running"):
            return reported_state(state), False
        if time.monotonic() >= deadline:
            return reported_state(state), False
        time.sleep(POLL_SECONDS)


# -- list, status, result, answer, tail, kill --------------------------------


def state_word(run_dir, state, recovered) -> str:
    """The one-word verdict `list` prints, including the resume hint."""
    session = state.get("session_id") or "?"
    if recovered:
        # Just finalized by the recovery path: report what was observed, not the
        # bookkeeping that was written.
        return f"GONE (resume with --session-id {session})"
    if state.get("state") == "running" and not run_alive(run_dir, state) and not is_starting(
        run_dir, state
    ):
        return f"GONE (resume with --session-id {session})"
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
            f"turns={state.get('turns', 0)} tools={state.get('tool_calls', 0)} "
            f"sess={state.get('session_id') or '-'}"
        )
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
    """Ask the run to stop, then force it: True once its finalized marker exists.

    A run whose runner is gone cannot execute its own finalizer, so the forced
    path finalizes the stop itself — as `killed`, exit 143, because that is what
    happened. Recording it as a stale crash (failed, exit -1) would contradict
    both the operator's request and the contract in references/transport.md.
    """
    if os.path.exists(os.path.join(run_dir, "finalized")):
        return True
    request_stop(run_dir)
    if wait_for_marker(run_dir, seconds):
        return True
    state = state if state is not None else read_state_file(run_dir)
    forced = False
    if run_alive(run_dir, state):
        forced = kill_tree(run_dir, state)
    if wait_for_marker(run_dir, 10.0):
        return True
    if forced or not run_alive(run_dir, state):
        finalize(
            run_dir,
            KILL_EXIT,
            note=(
                "stopped on request: the run's own finalizer did not complete after the stop "
                "request, so the stop was recorded here"
            ),
            extra={"stopped_by": "control-file-forced"},
        )
        return os.path.exists(os.path.join(run_dir, "finalized"))
    # The tree survived the escalation: leave the run to the recovery path rather
    # than claiming a stop that did not happen.
    warn(
        f"run in {run_dir} still has live processes after the forced stop; not recording it "
        "as stopped"
    )
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
    stop_run(run_dir, state, seconds=stop_wait_seconds())
    final = reported_state(read_state_file(run_dir))
    if not os.path.exists(os.path.join(run_dir, "finalized")):
        die(
            f"kill: run '{args.name}' did not settle (state {final.get('state')}); nothing "
            f"left to finalize it — see {run_dir}"
        )
    print(f"killed: {args.name} (pid {pids}) state={final.get('state')} exit={final.get('exit')}")
    return 0


# -- the runner (internal `_run`) -------------------------------------------


def drain(stream, log, track) -> None:
    try:
        for raw in stream:
            log.feed(raw)
            track(raw)
    except (OSError, ValueError):
        return
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def make_tracker(run_dir, state, state_path):
    """A per-line hook that keeps session.id and the live counters current.

    dsh's opening `session` event carries `sessionId` (not the `id` the shared
    writer looks for), so the runner persists session.id itself; the counters let
    `status` describe a live run without re-reading the retained log.

    Returns `(track, stop)`. `stop()` ends publication for good and waits for any
    in-flight write; the runner calls it before finalizing, because a reader
    thread still draining a stream a descendant kept open must never publish its
    stale `running` snapshot over the committed verdict. `publish` itself refuses
    to run once a `finalized` marker exists and holds the same lock throughout,
    so publication and finalization are serialized, not merely reordered.
    """
    seen = {"session_id": state.get("session_id") or "", "turns": 0, "tool_calls": 0}
    last = {"at": 0.0}
    session_path = os.path.join(run_dir, "session.id")
    finalized_path = os.path.join(run_dir, "finalized")
    lock = threading.Lock()
    stopped = threading.Event()

    def publish(force=False):
        now = time.monotonic()
        if not force and now - last["at"] < STATE_REFRESH_SECONDS:
            return
        with lock:
            if stopped.is_set():
                return
            last["at"] = now
            if os.path.exists(finalized_path):
                # The terminal state is already committed (by this run's own
                # finalizer or by a reader that settled it): never rewrite it.
                stopped.set()
                return
            write_json(
                state_path,
                {
                    **state,
                    "session_id": seen["session_id"],
                    "turns": seen["turns"],
                    "tool_calls": seen["tool_calls"],
                },
            )

    def track(raw):
        try:
            event = json.loads(raw.decode("utf-8", "replace").strip())
        except (ValueError, UnicodeDecodeError, AttributeError):
            return
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        changed = False
        if kind == "session":
            session_id = event.get("sessionId")
            if isinstance(session_id, str) and session_id and session_id != seen["session_id"]:
                seen["session_id"] = session_id
                with lock:
                    if stopped.is_set():
                        return
                    try:
                        with open(session_path, "w", encoding="utf-8") as handle:
                            handle.write(session_id + "\n")
                    except OSError:
                        pass
                changed = True
        elif kind == "status" and event.get("phase") == "turn_end":
            seen["turns"] += 1
            changed = True
        elif kind == "tool_call":
            seen["tool_calls"] += 1
            changed = True
        if changed:
            publish(force=kind == "session")

    def stop():
        stopped.set()
        # Serialize with a write already in flight: once this returns, nothing
        # this tracker publishes can land after it.
        with lock:
            pass

    return track, stop


def wait_for_agent(process, run_dir, requested: threading.Event, deadline, agent_identity="") -> tuple:
    """Wait for dsh, honouring the stop control file, a signal, and the deadline.

    Returns (exit code, surviving pids, stopped_by): the second is non-empty when
    a process below dsh outlived the signal, and the third names what ended the
    run ("control-file", "signal", "deadline") or "" when dsh ended by itself.
    `agent_identity` is the token read when dsh was spawned; it gates every signal
    so a reused pid is never signalled.
    """
    stop_path = os.path.join(run_dir, "stop")
    while True:
        exit_code = process.poll()
        if exit_code is not None:
            return exit_code, [], ""
        if requested.is_set() or os.path.exists(stop_path):
            reason = "control-file" if os.path.exists(stop_path) else "signal"
            code, survivors = terminate_agent(process, agent_identity)
            return code, survivors, reason
        if deadline is not None and time.monotonic() >= deadline:
            code, survivors = terminate_agent(process, agent_identity)
            return code, survivors, "deadline"
        time.sleep(POLL_SECONDS)


def runner_main(args) -> int:
    """Run one dsh task in the foreground of the detached process `start` spawned."""
    run_dir = args.run_dir
    state_path = os.path.join(run_dir, "state.json")
    state = read_state_file(run_dir)
    if os.path.exists(os.path.join(run_dir, "finalized")):
        # Replay must initialize before touching any finished artifact. Keep the
        # recorded command's paths and agent, not the caller's current defaults.
        return start_run(
            args, run_dir, args.agent, False, args.profile, args.permission_mode,
            args.approval_policy,
        )
    if (args.approval_policy or DEFAULT_APPROVAL_POLICY) != DEFAULT_APPROVAL_POLICY:
        # A replay of an older run may carry a policy this route can no longer
        # honour. Refuse it where the run's own finalizer can record why.
        note = (
            f"refused approval policy {args.approval_policy!r}: a detached run has no live "
            f"approval channel, so only {DEFAULT_APPROVAL_POLICY!r} can be honoured"
        )
        finalize(run_dir, 127, note=note)
        warn(note)
        return 1
    # Claim the lock `start` wrote before the spawn: the runner owns pid and
    # agent_pid, `start` owns everything else, so no read-modify-write can drop a
    # field that raced it. The identity is read now, at spawn, and never guessed
    # from a pid later.
    self_identity = process_identity(os.getpid())
    update_lock(run_dir, pid=os.getpid(), pid_identity=self_identity)
    # The run owns itself now: the start claim exists only for the window before
    # this process recorded a pid.
    remove_quietly(os.path.join(run_dir, "start.lock"))
    state["pid"] = os.getpid()
    state["pid_identity"] = self_identity
    state["detach"] = observe_detachment()
    state["interpreter"] = interpreter()
    write_json(state_path, state)

    if not os.path.isfile(args.prompt):
        finalize(run_dir, 127, note=f"prompt missing: {args.prompt}")
        return 1

    with open(os.path.join(run_dir, "stderr.log"), "ab") as stderr:
        try:
            log = EventLog(run_dir)
        except (RuntimeError, OSError, KeyError) as exc:
            finalize(run_dir, 127, note=f"event writer unavailable: {exc}")
            return 1
        session_id = args.session_id or args.resume or ""
        try:
            argv = agent_command(
                args.agent,
                agent_args(session_id, args.profile, args.permission_mode, args.approval_policy),
            )
        except ValueError as exc:
            log.finish()
            finalize(
                run_dir, 127, note=f"cannot dispatch the agent: {exc}", extra={"error": str(exc)}
            )
            warn(f"cannot dispatch the agent: {exc}")
            return 1
        try:
            process = spawn_agent(argv, args.cwd, stderr, args.prompt)
        except OSError as exc:
            log.finish()
            finalize(
                run_dir, 127, note=f"agent did not start: {exc}", extra={"error": str(exc)}
            )
            warn(f"agent did not start: {exc}")
            return 1
        agent_identity = process_identity(process.pid)
        state["agent_pid"] = process.pid
        state["agent_pid_identity"] = agent_identity
        state["agent_argv"] = argv
        write_json(state_path, state)
        update_lock(run_dir, agent_pid=process.pid, agent_pid_identity=agent_identity)

        requested = threading.Event()
        install_stop_handler(requested)
        tracker, stop_tracker = make_tracker(run_dir, state, state_path)
        reader = threading.Thread(target=drain, args=(process.stdout, log, tracker), daemon=True)
        reader.start()
        deadline = None
        if args.max_time:
            deadline = time.monotonic() + float(args.max_time)
        exit_code, survivors, stopped_by = wait_for_agent(
            process, run_dir, requested, deadline, agent_identity
        )
        extra = {}
        if stopped_by:
            extra["stopped_by"] = stopped_by
        if stopped_by == "deadline":
            extra["deadline_exceeded"] = True
        if survivors:
            state["survivors"] = survivors
            state["note"] = (
                "stopped with processes still alive: "
                + " ".join(str(pid) for pid in survivors)
                + "; they were signalled but did not exit"
            )
            write_json(state_path, state)
        reader.join(timeout=drain_timeout_seconds())
        # Publication ends before the terminal state is committed. The reader may
        # still be alive (a descendant holds the stream open) and would otherwise
        # publish its `running` snapshot over the verdict after the marker exists.
        stop_tracker()
        if reader.is_alive():
            # A descendant of dsh still holds the write end of its stdout. Stop
            # waiting and say in state.json that the tail is missing rather than late.
            warn("the event stream was still open at exit; recording the truncation")
            state["stream_incomplete"] = True
            state["note"] = (
                "finalized while the event stream was still open: a process below dsh held "
                "its stdout, so the events after this point are missing from the log"
            )
            write_json(state_path, state)
            extra["stream_incomplete"] = True
        log.finish()

    note = None
    if stopped_by == "control-file":
        note = "stopped on request: the runner observed the stop control file and ended the agent tree"
    elif stopped_by == "signal":
        note = "stopped by a signal delivered to the runner; the agent tree was ended"
    elif stopped_by == "deadline":
        note = (
            f"--max-time {args.max_time}s elapsed; the runner ended the agent tree "
            "(DSH has no task-deadline flag, so this is the adapter's own deadline)"
        )
    final = finalize(run_dir, exit_code, note=note, extra=extra, claim_wait=30.0)
    print(
        f"[finalize] {final.get('name')} state={final['state']} exit={exit_code} "
        f"dur={final.get('duration_s')}s turns={final.get('turns')} "
        f"tools={final.get('tool_calls')} session={final.get('session_id') or '-'}",
        flush=True,
    )
    return 0


# -- command line ------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Launcher adapter for gdd headless runs on DeepSeek Harness: start a "
            "detached dsh run, then list / status SLUG | result SLUG | answer SLUG "
            "| kill SLUG | tail SLUG."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start one detached dsh run")
    start.add_argument("--name", required=True, help="run slug (sanitized)")
    start.add_argument("--prompt", required=True, help="prompt file")
    start.add_argument("--cwd", default=os.getcwd(), help="working directory of the run")
    start.add_argument("--session-id", dest="session_id", default=None, help="adopt that DSH session id")
    start.add_argument("--model", default=None, help="refused on this route (no headless model flag)")
    start.add_argument("--thinking", default=None, help="refused on this route (no headless thinking flag)")
    start.add_argument("--max-time", dest="max_time", default=None, help="adapter deadline, in seconds")
    start.add_argument("--resume", default=None, help="resume that DSH session id (alias of --session-id)")
    start.add_argument("--replace", action="store_true", help="restart a live run")
    start.set_defaults(func=cmd_start)

    runner = sub.add_parser("_run", help="internal: run one dsh task in the foreground")
    runner.add_argument("--run-dir", dest="run_dir", required=True)
    runner.add_argument("--prompt", required=True)
    runner.add_argument("--cwd", required=True)
    runner.add_argument("--agent", required=True)
    runner.add_argument("--name", default=None)
    runner.add_argument("--profile", default=None)
    runner.add_argument("--permission-mode", dest="permission_mode", default=None)
    runner.add_argument("--approval-policy", dest="approval_policy", default=None)
    runner.add_argument("--session-id", dest="session_id", default=None)
    runner.add_argument("--resume", default=None)
    runner.add_argument("--max-time", dest="max_time", default=None)
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
    if getattr(args, "func", None) is runner_main:
        # The runner's own defaults come from the environment when the recorded
        # command did not fix them; resolve them here, once.
        args.profile = args.profile or dsh_profile()
        args.permission_mode = args.permission_mode or permission_mode()
        args.approval_policy = args.approval_policy or approval_policy()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
