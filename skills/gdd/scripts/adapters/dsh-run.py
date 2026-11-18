#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
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
waits for the run's own finalizer, and only then escalates to a process-instance
TERM/KILL. The request names the run generation it was issued for, and the runner
acts only on its own generation's request. A run stopped this way ends as
`killed` with exit 143. Every stop path ends in exactly one of three outcomes and
never confuses them: *stopped* (proven gone), *not stopped, survivors known*, or
*not stopped, survivors could not be enumerated* (Windows has no group table, and
an inspection command can fail on any platform). Only the first is allowed to
reach a terminal state: "no survivors were reported" is never the same value as
"the stop is confirmed". A stop that did not complete publishes no terminal state
— the run stays `running` with `stopping: true`, the survivors it could name
recorded in `state.json` and `lock` (`survivors_complete: false` when the
enumeration itself failed) — so the run is still alive to `run_alive`, still
occupies its slug (a new `start` refuses it, `status`/`list` report it as
stopping, not finished), and a later `kill` can finish the job through the
survivors' recorded identities or its own new enumeration; when the stop still
cannot be confirmed, `kill` exits 1 and says so rather than guessing. A run that
died without finalizing is finalized as `failed` with exit -1 by the next
`status`/`result`/`list`/`answer`, which sets `stale_recovered: true` — and only
while no terminal record is committed, so recovery stays idempotent. A run whose
stop was requested is never recovered that way: once every recorded process is
conclusively gone it settles as `killed` with exit 143, and while anything is
unproven it stays non-terminal.

Forced stopping is a capability, not an assumption. On Linux the adapter signals
only through a `pidfd` process handle — open the handle, re-read the process's
identity, verify it against the record, confirm the handle has not reported exit,
signal through that same handle — never through a bare pid and never through
`killpg`. Group breadth comes from enumerating the group under a continuously
verified anchor member and signalling each member through its own handle; the
group id itself is never signalled (a negative group-existence probe may say a
formerly tracked group is gone, but it never attributes members). Where that
capability does not exist — Linux without `pidfd_open`/`pidfd_send_signal`,
macOS (`ps` gives a display timestamp, not a reuse-proof identity), Windows (no
reuse-proof tree-termination primitive) — no destructive call is made at all: the
stop stays a request, the run stays `running`/`stopping`, `kill` exits 1 with an
explicit "cannot confirm", and the operator ends the tree and settles the run
afterwards. This is a documented limit, not a fallback to hope.

A run root can be shared — `GDD_RUN_ROOT` is one tree for every route — so
discovery and recovery are route-scoped: a run is this route's only when the
`state.json` this adapter writes identifies it (`"backend": "dsh"`). `list` shows
any other recorded run as it records itself and every reader leaves it alone: a
run of another backend is never finalized, rewritten, moved aside or signalled.

Process identity
----------------
A recorded pid is not a process: the OS reuses pids, so `kill` (or `start
--replace`) long after a run died could otherwise signal whatever now owns that
pid — on the reference adapter's `os.getpgid` fallback, an entire unrelated
process group. This adapter therefore records `pid_identity`/`agent_pid_identity`
next to the runner and agent pids. On Linux the token is
`linux:v2:<boot-id>:<pid-namespace>:<pid>:<start-ticks>`: the pid alone is not
enough across a reboot (the tick counter restarts with the boot) and not enough
across a shared run root (the same pid number names different processes in
different pid namespaces). Boot id and pid-namespace identity are read and
validated, and if any component cannot be read the adapter has **no** strong
identity — it does not fall back to the display-timestamp probe. On Windows the
token is `win:v1:<creation FILETIME>:<pid>`; on macOS `ps -o lstart=` is kept
only as diagnostic evidence and never authorizes a signal. An unverifiable
identity — missing token, a token that changed, a legacy `proc:<ticks>` token —
fails closed: no signal is sent, the refusal is reported. The `os.getpgid(pid)`
fallback is gone for the same reason. Liveness itself is three-valued: `LIVE`,
`GONE` and `UNKNOWN` (access denial or a failed inspection is never conclusive
death), so recovery requires a conclusive `GONE` and an enumeration that cannot
be read returns "unknown", never "nobody".

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
"started_at","pid_identity","agent_pid_identity"} — plus `survivors` (pid,
identity and group of each process a failed stop left alive) when a stop did not
complete: `pid` is the detached runner, `agent_pid` the dsh process it started,
and the two identity tokens are what makes a pid still this run's process (see
"Process identity" above). `start` writes the lock and the identity tokens of a
spawned process are recorded by the runner as it spawns it.

`start.lock` files and the `lock` record are process metadata, not mutexes: a
pidless window and a recorded generation are not ownership. Ownership is two
stable OS locks, both keyed by the sanitized slug and both outside every
replaceable run directory, so moving a run aside cannot move a lock:
`<run root>/<slug>.start.lock` (S) serializes every entry point that can start an
agent across every date bucket, and `<run root>/.dsh-locks/<slug>.lifecycle.lock`
(M) is the one authority for mutation: a terminal write, a stop request, an
escalation step, a recovery, a publication and the spawn handshake all revalidate
ownership under M and hold it through the action. Kernel ownership is
authoritative — a remaining lock file is not a stale lock, and neither mtime nor
a recorded pid transfers it; contention and I/O failure both deny the mutation.
The nesting order is fixed (S local → S OS → M local → M OS → EventLog.lock →
TEMP_LOCK); M is released before any wait (a runner, a child, a marker, a reader
thread), and finalization never acquires S. The files are never unlinked and
their inodes are never replaced.

Every mutation is bound to an immutable operation context — canonical root, slug,
logical run path, expected generation. Under M the guard re-reads `state.json`,
checks the route, checks the generation against that context (and against the
process metadata the operation relies on), checks whether a terminal record is
already committed, and only then authorizes the action; a changed generation
means no run-directory write, no further signal and no enumeration against
whoever occupies the path now. A record with no generation — a legacy run — stays
readable but authorizes no mutation: the adapter says it cannot confirm the run
generation instead of manufacturing one.

Terminal publication is one atomic file replacement. The authoritative terminal
record lives in `state.json` as `terminal_record{version, generation, commit_id,
answer, session_id, exit}`, written by an atomic `os.replace` **last**, after the
compatibility artifacts (`answer.md`, `exit.code`, `session.id`) are materialized;
the `finalized` marker keeps its historical exit-code-text form and is written
**after** the commit, for the observer plugin and for older readers only. Every
terminal decision in the adapter goes through the validator that reads that
record, never through the marker's existence or content: a crash before the
commit publishes nothing, a crash after it leaves the whole verdict in one file,
and a state that looks terminal without a valid commit is uncommitted data that
no reader trusts or rewrites. Readers take the answer from the record — before
the commit, a prepared `answer.md` is not a result, and `answer` still says "not
finished".

Replaying a finished invocation goes through the same fresh-start path: the old
directory is preserved as `<SLUG>.prev-<time>`, then the recorded runner command
starts in a new directory at the original path, with the same prompt, cwd, agent,
profile, mode, policy and flags. The old finalized artifacts are never
overwritten by the replay. A replay of a run that is *still live* is refused
before anything is written: the ownership a fresh start recorded (the run's pids
and identity tokens, and the absence of a terminal commit) is checked by `_run`
too, so replaying a running run cannot overwrite its runner pid or start a
second agent on the same cwd.

Residual limits, stated as limits and never as guarantees: the macOS and Windows
strong-identity and tree-termination capability is **UNCONFIRMED**, so those
platforms refuse destructive escalation; Linux without `pidfd` refuses it too;
power-loss durability across platforms and filesystems is **UNCONFIRMED**
(`os.replace` is atomic, not durable); "every possible escaped descendant is
gone" is not guaranteed for descendants that deliberately leave the recorded
groups; and no atomic arbitration is promised against a foreign starter that does
not follow this protocol.

Exit codes: 0 success, 1 refusal or error — the reference adapter's convention.
"""

from __future__ import annotations

import argparse
import atexit
import errno
import glob
import itertools
import json
import math
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import namedtuple
from contextlib import ExitStack, contextmanager
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
# The single lifecycle vocabulary every reader reports (R5). `terminal` requires
# the `finalized` marker, never merely a state word; the two `stopping` forms keep
# "the stop failed and we know who survived" apart from "the stop failed and we
# could not even enumerate the survivors", so no caller can read either as success.
LIFECYCLE_TERMINAL = "terminal"
LIFECYCLE_LIVE = "live"
LIFECYCLE_STOPPING_KNOWN = "stopping (survivors known)"
LIFECYCLE_STOPPING_UNKNOWN = "stopping (enumeration failed)"
LIFECYCLE_UNKNOWN = "unknown (no state)"
LIFECYCLE_GONE = "gone (unfinalized)"
LIFECYCLE_FOREIGN = "read-only"
# The single-use handshake between a `start` (which holds the slug claim) and the
# detached runner it spawns: the token is written to `spawn.token` in the run
# directory and passed only in the runner's own environment, then consumed. A
# replay of the recorded `run.sh`/`run.cmd` carries neither half, so it must take
# the slug claim like any other starter (see `runner_main`).
RUNNER_TOKEN_ENV = "DSH_RUN_SPAWN_TOKEN"
SPAWN_TOKEN_FILE = "spawn.token"
LIFECYCLE_LOCK_DIR = ".dsh-locks"
# The operation-context guard's verdicts. Only GUARD_OK authorizes the action the
# caller holds the lifecycle mutex for; every other verdict must produce no
# run-directory write and no signal.
GUARD_OK = "OK"
GUARD_GENERATION_CHANGED = "GENERATION_CHANGED"
GUARD_UNCONFIRMED = "UNCONFIRMED"
GUARD_FOREIGN = "FOREIGN"
GUARD_TERMINAL = "TERMINAL"
GUARD_BUSY = "BUSY"
# The authoritative terminal record's own schema version, beside the state.json it
# is embedded in (see `terminal_snapshot_locked`).
TERMINAL_RECORD_VERSION = 1
# Distinct return values of a generation-bound wait. `wait_for_terminal` never
# returns marker text, and a generation change is not a timeout.
WAIT_TERMINAL = "terminal"
WAIT_GENERATION_CHANGED = "generation-changed"
WAIT_TIMEOUT = "timeout"
# Liveness is three-valued: an inspection that failed is not a death.
LIVE = "live"
GONE = "gone"
UNKNOWN = "unknown"
# Process-identity token versions. Linux needs the boot cycle (the tick counter
# restarts with it) and the pid namespace (the same pid number is a different
# process in another namespace); Windows pairs the creation FILETIME with the pid.
LINUX_IDENTITY_VERSION = "linux:v2:"
WINDOWS_IDENTITY_VERSION = "win:v1:"
PS_IDENTITY_PREFIX = "ps:"
BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"
SELF_PIDNS_PATH = "/proc/self/ns/pid"
# Startup grace remains a conservative liveness rule (a young run that has
# recorded no pid is *starting*, not dead). It is not a lock: no ownership is
# ever taken over by age.
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
# Committing a terminal verdict and the stopped tree being *gone* are two events:
# the runner that wrote the verdict is still one of the run's recorded processes
# until it returns and is reaped, and an enumeration that anchors on it answers
# "unknown" (never "nobody") while it leaves. `start --replace` therefore asks the
# settle question again until the evidence is conclusive, bounded by this — see
# `await_settled_stop`. A stop that is genuinely unresolved (a live survivor, or a
# table that cannot be read at all) still ends in the existing refusal; the bound
# only keeps a momentary one from being read as the operator's problem.
SETTLE_WAIT_SECONDS = 10.0
GRACE_SECONDS = 60.0
DRAIN_TIMEOUT_SECONDS = 30.0
# How long a mutation that must land (a start, a stop request, a publisher, a
# spawn registration, an escalation step, a survivor report) waits for the
# lifecycle mutex. M is only ever held for a short critical section, so a bound of
# a few seconds converts a momentary hold — another process publishing a tracker
# update while `start --replace` is entering — into waiting instead of a spurious
# refusal, while a mutex that is genuinely held still ends in a refusal quickly
# enough for the operator to be told about it. The bound is deliberately small: a
# *contended* acquisition is not a *broken* one, and only contention waits (see
# `_lock_contention`).
MUTEX_WAIT_SECONDS = 5.0
# How often the runner republishes counters while the agent works. state.json is
# polled by gdd.py and by operators, so it must stay current without turning a
# long run into a write storm.
STATE_REFRESH_SECONDS = 0.5
DEFAULT_EVENTS_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_PROFILE = "headless"
DEFAULT_PERMISSION_MODE = "workspace-write"
DEFAULT_APPROVAL_POLICY = "never"
# The one word that identifies a run as this route's, in state.json and in lock:
# discovery, recovery and every signal are scoped to it (see `is_this_route`).
BACKEND = "dsh"
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
    """A finite, positive number of seconds from the environment, else the default.

    `float()` accepts `inf`, `-inf` and `nan`, and a non-finite deadline is not a
    deadline: a stop wait of `inf` would never escalate and a drain timeout of
    `nan` compares false against every elapsed time. Anything that is not finite
    and positive falls back to the finite default.
    """
    try:
        value = float((os.environ.get(name) or "").strip())
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


def start_grace_seconds() -> float:
    return env_seconds("DSH_RUN_START_GRACE_SECONDS", GRACE_SECONDS)


def stop_wait_seconds() -> float:
    return env_seconds("DSH_RUN_STOP_WAIT_SECONDS", STOP_WAIT_SECONDS)


def settle_wait_seconds() -> float:
    return env_seconds("DSH_RUN_SETTLE_WAIT_SECONDS", SETTLE_WAIT_SECONDS)


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
    everything else is passed through unchanged. The runner handshake token is
    dropped for the same reason: only the one runner `start` spawns may present
    it, so no process below the runner — and no replay script — can inherit it.
    """
    env = dict(os.environ)
    for name in RESERVED_HARNESS_ENV:
        env.pop(name, None)
    env.pop(RUNNER_TOKEN_ENV, None)
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
    """A finite, positive number of seconds, or None. Raises ValueError otherwise."""
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
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"--max-time must be a positive number of seconds (got {text!r})")
    return seconds


# -- stable locks and the operation context ----------------------------------
#
# Two lock objects carry ownership, and both live outside every replaceable run
# directory (a run directory is moved aside by `start --replace`, so a lock
# inside it would move with the generation it protects):
#
#   S  <run root>/<slug>.start.lock                  the right to start a slug
#   M  <run root>/.dsh-locks/<slug>.lifecycle.lock   the right to mutate a slug
#
# Both are keyed by the sanitized slug, across every date bucket, and both are
# held as `fcntl.flock` (POSIX) or `msvcrt.locking` (Windows) on a file that is
# never unlinked and whose inode is never replaced. Kernel ownership is
# authoritative: a file that exists is not a held lock, and neither its mtime nor
# a pid it records transfers ownership. The complete nesting order is
# S local → S OS → M local → M OS → EventLog.lock → TEMP_LOCK; a caller may take
# a suffix of that order, never a reversed pair. M is released across every wait,
# and a mutation that must land (a start, a stop request, a spawn registration, a
# publisher, an escalation step, a survivor report) waits a bounded time for M
# (`MUTEX_WAIT_SECONDS`) instead of reading a momentary hold as a refusal.


def canonical_root(root) -> str:
    """The one canonical key of a run root: realpath, plus normcase on Windows.

    Two spellings of the same directory must name the same lock object, or two
    starters could hold "the" slug claim at once through different paths.
    """
    text = os.path.realpath(os.path.abspath(os.path.expanduser(str(root))))
    return os.path.normcase(text) if IS_WINDOWS else text


def start_lock_path(root, slug) -> str:
    """S: the slug claim, a stable sibling of every date bucket."""
    return os.path.join(canonical_root(root), f"{slug}.start.lock")


def lifecycle_lock_path(root, slug) -> str:
    """M: the lifecycle mutex, in this route's own namespace under the run root."""
    return os.path.join(canonical_root(root), LIFECYCLE_LOCK_DIR, f"{slug}.lifecycle.lock")


LOCAL_LOCKS = {}
LOCAL_LOCKS_GUARD = threading.Lock()
LOCK_HANDLES = {}


def local_lock_for(key) -> threading.Lock:
    """The in-process mutex for one lock object.

    Platforms differ in how re-locking one file from the same process behaves, so
    threads of one interpreter are serialized by this mutex *before* the OS lock;
    it is held only around the acquisition and the critical section. The registry
    guard is held just long enough to fetch the reference, never across a
    lifecycle resource.
    """
    with LOCAL_LOCKS_GUARD:
        lock = LOCAL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            LOCAL_LOCKS[key] = lock
        return lock


def close_lock_handles() -> None:
    """Close every cached lock descriptor at interpreter exit.

    The handles are cached for the process's lifetime on purpose (one descriptor
    per lock object, so a lock can never be re-created on a different inode), and
    the kernel releases the locks when they close. Closing them explicitly at exit
    keeps the process's own bookkeeping honest — an unclosed descriptor is not
    ownership, it is just a leak a reader has to reason about.
    """
    for handle in list(LOCK_HANDLES.values()):
        close_quietly(handle)
    LOCK_HANDLES.clear()


atexit.register(close_lock_handles)


def lock_handle_for(path):
    """One cached descriptor per lock object, opened once and never unlinked.

    Re-opening the lock file per acquisition is not needed — and caching it keeps
    the inode the lock lives on alive for this process's lifetime, so a lock can
    never be "replaced" by a concurrent creator.
    """
    handle = LOCK_HANDLES.get(path)
    if handle is None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = open(path, "a+b")
        LOCK_HANDLES[path] = handle
    return handle


def _lock_handle(handle) -> None:
    # Dispatched on the *real* platform, not on the module's test-patchable
    # `IS_WINDOWS`: the lock primitive is a property of the running interpreter,
    # so a test that pretends to be Windows elsewhere does not change how this
    # process locks.
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            # msvcrt.locking locks a byte range; an empty file has none.
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _lock_contention(exc) -> bool:
    """Is this acquisition failure "someone else holds it" rather than "broken"?

    `fcntl.flock(LOCK_NB)` raises `BlockingIOError` for a held lock (EAGAIN), and
    `msvcrt.locking` reports EACCES/EDEADLK for one; a read-only directory, a
    failing filesystem and an exhausted descriptor table are different events. Only
    contention is worth waiting for — everything else is refused immediately, and
    `stable_lock` uses this to tell the two apart.
    """
    if isinstance(exc, BlockingIOError):
        return True
    if isinstance(exc, PermissionError) and os.name == "nt":
        return True
    return getattr(exc, "errno", None) in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK,
                                           errno.EDEADLK)


def _unlock_handle(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def stable_lock(path, wait=0.0):
    """Hold one stable lock object, or report that it could not be held.

    Yields True only when both the in-process mutex and the kernel lock are held.
    Contention, an I/O failure and an unsupported lock all yield False and every
    caller must read that as "deny the mutation" — there is no takeover path, no
    age rule and no pid-file rule. `wait` bounds acquisition in seconds for
    callers that can afford to wait a little (0 means "do not wait at all");
    `wait=None` waits without bound, which is only used for the append-only event
    stream, whose writer must never silently drop a line because a reader held M
    for a moment.
    """
    local = local_lock_for(path)
    if wait is None:
        local_held = local.acquire()
    else:
        local_held = local.acquire(True, max(0.0, wait) or 0.000001) if wait > 0 else local.acquire(False)
    if not local_held:
        yield False
        return
    handle = None
    locked = False
    try:
        try:
            handle = lock_handle_for(path)
        except OSError:
            yield False
            return
        deadline = None if wait is None else time.monotonic() + max(0.0, wait)
        while True:
            try:
                _lock_handle(handle)
                locked = True
                break
            except OSError as exc:
                if not _lock_contention(exc):
                    # A broken acquisition (a read-only lock directory, a failing
                    # filesystem, an exhausted descriptor table) is not contention:
                    # waiting cannot turn it into a lock, so it is refused at once.
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                time.sleep(POLL_SECONDS)
        yield locked
    finally:
        if locked:
            try:
                _unlock_handle(handle)
            except OSError:
                pass
        local.release()


@contextmanager
def slug_start_claim(root, slug, wait=0.0):
    """Hold S: the exclusive right to start one slug, across every date bucket.

    A run started before midnight still occupies its slug after the date rolls
    over, so the claim cannot live in a date directory. The kernel releases the
    claim when this process's handles close, even if the starter dies; its file
    is never unlinked, so a competitor can never lock a fresh inode at the same
    path, and its age is never ownership.
    """
    with stable_lock(start_lock_path(root, slug), wait) as held:
        yield held


@contextmanager
def lifecycle_claim(root, slug, wait=0.0):
    """Hold M: the exclusive right to mutate one slug's run, in any date bucket."""
    with stable_lock(lifecycle_lock_path(root, slug), wait) as held:
        yield held


Operation = namedtuple("Operation", "root slug run_dir generation")


def operation_of(run_dir, state=None, generation=None) -> Operation:
    """The immutable operation context of a run: (root, slug, run path, generation).

    The generation is the strict one — a record with no generation (a legacy run)
    yields "", and every mutation is refused for it — unless the caller passes the
    generation it holds (a terminal write binding itself to the run it decided
    about). The context is captured once and never refreshed: an operation may
    only act on the generation it captured.
    """
    run_dir = os.path.abspath(str(run_dir))
    if state is None:
        state = read_state_file(run_dir)
    slug = sanitize(state.get("name") or os.path.basename(run_dir))
    return Operation(
        canonical_root(bucket_root(run_dir)),
        slug,
        run_dir,
        strict_generation(state) if generation is None else generation,
    )


def mutex_of(op: Operation, wait=0.0):
    """M for one operation's slug."""
    return lifecycle_claim(op.root, op.slug, wait)


def strict_generation(state) -> str:
    """The run's generation token, or "" when the record has none.

    The `name|started` fallback `generation_of` keeps for *reading* is not an
    authorization token: mutating a record that cannot name its own generation
    is refused (see `guard_locked`).
    """
    generation = (state or {}).get("generation")
    return generation if isinstance(generation, str) and generation else ""


def terminal_snapshot_locked(state):
    """The committed terminal record in one state snapshot, or None.

    This is the only terminal authority in the adapter. A terminal commit exists
    only when the snapshot identifies this route, names a nonempty generation,
    carries a terminal `state`, and embeds a structurally valid `terminal_record`
    that agrees with it — the same generation, the same exit code, a nonempty
    commit id. `finalized` is deliberately not consulted: it is the compatibility
    marker written *after* the commit, and a crash between the two leaves a valid
    commit with no marker, never the reverse. Reading one atomically replaced file
    needs no mutex; every decision made from the result is taken under M.
    """
    state = state or {}
    if route_of(state) != BACKEND:
        return None
    if state.get("state") not in ("done", "killed", "failed"):
        return None
    if not strict_generation(state):
        return None
    record = state.get("terminal_record")
    if not isinstance(record, dict):
        return None
    if record.get("version") != TERMINAL_RECORD_VERSION:
        return None
    if record.get("generation") != state.get("generation"):
        return None
    if record.get("exit") != state.get("exit"):
        return None
    commit_id = record.get("commit_id")
    if not isinstance(commit_id, str) or not commit_id:
        return None
    for field in ("answer", "session_id"):
        if not isinstance(record.get(field), str):
            return None
    return record


def terminal_commit(run_dir, state=None):
    """The committed terminal record of a run directory, or None."""
    return terminal_snapshot_locked(read_state_file(run_dir) if state is None else state)


def guard_locked(op: Operation, require_lock_generation=False):
    """Revalidate everything a mutation needs, under M, immediately before it.

    Returns `(verdict, state, detail)`. The steps are: re-read `state.json`; check
    the route; check the captured generation; check the generation the process
    metadata used by the operation carries; check whether a terminal record is
    already committed. Only `GUARD_OK` authorizes the action the caller is holding
    M for — every other verdict is a refusal that must write nothing, signal
    nothing and enumerate nothing.
    """
    state = read_state_file(op.run_dir)
    if not is_this_route(state):
        return (
            GUARD_FOREIGN,
            state,
            f"it records backend {route_of(state) or 'unknown'}, not this route",
        )
    recorded = strict_generation(state)
    if not op.generation or not recorded:
        return (
            GUARD_UNCONFIRMED,
            state,
            "I cannot confirm the run generation (the record names none; a legacy run is "
            "not an authorization token)",
        )
    if recorded != op.generation:
        return (
            GUARD_GENERATION_CHANGED,
            state,
            f"the path now holds generation {recorded}, not {op.generation}",
        )
    if require_lock_generation:
        metadata = lock_of(op.run_dir)
        metadata_generation = metadata.get("generation")
        if metadata_generation != op.generation:
            return (
                GUARD_UNCONFIRMED if not metadata_generation else GUARD_GENERATION_CHANGED,
                state,
                "the process metadata does not carry the generation this operation holds "
                f"(it names {metadata_generation or 'none'})",
            )
    if terminal_snapshot_locked(state) is not None:
        return (GUARD_TERMINAL, state, "a terminal verdict is already committed")
    return (GUARD_OK, state, "")


def guard_refusal(op: Operation, verdict: str, detail: str) -> str:
    """The one sentence a refused mutation says."""
    if verdict == GUARD_GENERATION_CHANGED:
        return (
            f"not acting on {op.run_dir}: it now holds a different run ({detail}); a run "
            "created after the decision is not the one it was made about, so nothing was "
            "written and nothing was signalled"
        )
    if verdict == GUARD_UNCONFIRMED:
        return f"not acting on {op.run_dir}: {detail}"
    if verdict == GUARD_FOREIGN:
        return f"not acting on {op.run_dir}: {detail}"
    if verdict == GUARD_TERMINAL:
        return f"not acting on {op.run_dir}: {detail}"
    if verdict == GUARD_BUSY:
        return f"{op.run_dir} is being mutated by another process; not proceeding"
    return f"not acting on {op.run_dir}: {detail}"


# -- small helpers -----------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_nonce() -> str:
    """A fresh random token: a run's generation, and the single-use spawn token."""
    return os.urandom(16).hex()


def generation_of(run_dir, state=None) -> str:
    """The token naming the run generation at this path, or "" when there is none.

    The `generation` `start` records when it writes a run; the recorded name plus
    start time otherwise, so a run written before that field existed still has a
    token. A directory with no readable state has no token, and a caller holding
    no token verifies nothing (there is no run to bind a write to).
    """
    if state is None:
        state = read_state_file(run_dir)
    generation = state.get("generation")
    if isinstance(generation, str) and generation:
        return generation
    name = state.get("name")
    started = state.get("started")
    if name or started:
        return f"{name or ''}|{started or ''}"
    return ""


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def read_state_file(run_dir) -> dict:
    state = read_json(os.path.join(run_dir, "state.json"), {})
    return state if isinstance(state, dict) else {}


def route_of(state) -> str:
    """The backend a run's state records, or "" when it records none."""
    backend = (state or {}).get("backend")
    return backend if isinstance(backend, str) else ""


def is_this_route(state) -> bool:
    """Is this run provably this route's?

    One run root can hold the runs of several adapters, and the only thing that
    identifies the route that wrote a run is the `backend` this adapter records
    in `state.json`. Anything else — another adapter's backend, or no recorded
    backend at all — is not proof, and a run that is not provably this route's is
    never finalized, rewritten, moved aside or signalled by it.
    """
    return route_of(state) == BACKEND


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


def write_text_atomic(path, text) -> None:
    """Materialize `text` at `path` by an atomic replacement of a temp file.

    A unique temp file in the destination directory, flushed and closed, then
    `os.replace` with bounded retries (on Windows `MoveFileEx` fails while another
    process holds the destination open). There is deliberately no in-place
    fallback: truncating the destination to "make progress" turns one failed write
    into a torn artifact, and a torn `state.json` is a lost run. If the replacement
    never succeeds the failure is raised and the previous bytes stay intact.
    """
    tmp = json_temp_path(path)
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
    last = None
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(0.05 + 0.05 * (attempt % 5))
        except OSError:
            remove_quietly(tmp)
            raise
    remove_quietly(tmp)
    raise OSError(
        f"could not atomically replace {path} after 40 attempts ({last}); the previous "
        "bytes are intact and no partial file was published"
    )


def write_json(path, payload) -> None:
    """Replace atomically: gdd.py polls state.json and must never read half of it."""
    write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


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
    """The reference adapter's slug rule: lower-case, [a-z0-9._-], 48 characters.

    `.` and `..` are the one output of that rule which is not a name: they are
    path components, and a run directory built from one of them is the date
    bucket or the run root itself. They are refused here (the empty string is
    this adapter's word for "no usable slug"), so no caller can address a run
    with one, and `start` refuses such a name before it writes anything.
    """
    slug = SANITIZE_RE.sub("-", str(value or "").lower()).strip("-")[:48]
    return "" if slug in (".", "..") else slug


def checked_run_dir(run_dir) -> str:
    """The run directory, proven to be a direct child of its own date bucket.

    `start` (and a replay) writes prompt.md, state.json, the lock and every other
    artifact into this directory, so the shape is verified before any write: a
    slug that resolves anywhere but a date bucket's direct child is refused, not
    sanitized into shape. Two cases are caught — a directory that is not
    `<run root>/<YYYY-MM-DD>/<slug>` at all (which is what `start --name ..`
    resolves to), and a slug directory that resolves elsewhere through a symlink.
    Raises ValueError, which the callers turn into the adapter's refusal.
    """
    run_dir = os.path.abspath(str(run_dir))
    bucket = os.path.dirname(run_dir)
    slug = os.path.basename(run_dir)
    if slug in ("", ".", "..") or not DATE_RE.match(os.path.basename(bucket)):
        raise ValueError(
            f"run directory {run_dir} is not <run root>/<YYYY-MM-DD>/<slug>; refusing to "
            "write a run outside its own date bucket"
        )
    resolved = os.path.realpath(run_dir)
    if os.path.dirname(resolved) != os.path.realpath(bucket):
        raise ValueError(
            f"run directory {run_dir} resolves to {resolved}, which is not a direct child of "
            f"its date bucket {bucket}; refusing to write a run outside its own bucket"
        )
    return run_dir


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


def _proc_stat_state(pid) -> str:
    """The Linux process state letter from `/proc/<pid>/stat`, or "".

    `os.kill(pid, 0)` succeeds for a zombie, but a zombie has exited: it runs no
    code, holds no pipe and can write nothing, so every liveness question this
    adapter asks must read it as gone. A process the adapter itself spawned is
    reaped with `poll()`; one it did not cannot be reaped at all, which is
    exactly the case this probe exists for.
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            raw = handle.read()
    except OSError:
        return ""
    closing = raw.rfind(b")")
    if closing < 0:
        return ""
    fields = raw[closing + 1 :].split()
    if len(fields) < 1:
        return ""
    try:
        return fields[0].decode("ascii", "replace")
    except AttributeError:  # pragma: no cover - bytes always decode here
        return ""


def liveness_of(pid) -> str:
    """LIVE / GONE / UNKNOWN for one pid. A failed inspection is never GONE.

    `os.kill(pid, 0)` is not a liveness check on Windows for a process in another
    session: it raises AccessDenied for a process that exists. OpenProcess +
    GetExitCodeProcess answers the same question there, and its two failure modes
    are distinguished: an invalid parameter means there is no such process, while
    access denial, a failed query or any other error leaves the question open.
    Recovery requires a conclusive GONE; an UNKNOWN keeps the run conservative.
    On Linux a zombie is GONE: it has exited.
    """
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return GONE
    if IS_WINDOWS:
        ERROR_INVALID_PARAMETER = 87
        SYNCHRONIZE = 0x00100000
        QUERY_LIMITED = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        kernel32.SetLastError(0)
        handle = kernel32.OpenProcess(SYNCHRONIZE | QUERY_LIMITED, False, int(pid))
        if not handle:
            error = kernel32.GetLastError()
            return GONE if error == ERROR_INVALID_PARAMETER else UNKNOWN
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return UNKNOWN
            return LIVE if code.value == STILL_ACTIVE else GONE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return GONE
    except PermissionError:
        return UNKNOWN
    except OSError:
        return UNKNOWN
    if _proc_stat_state(pid) in ("Z", "X", "x"):
        # An exited process that has not been reaped: dead for every purpose this
        # adapter has, including "can this still be signalled about a group".
        return GONE
    return LIVE


def pid_alive(pid) -> bool:
    """Is this pid a live process? UNKNOWN answers False here, and never `GONE`.

    Used where "is it really alive right now" decides an assertion or a report;
    code whose correctness depends on a *conclusive* disappearance reads
    `liveness_of` directly, because UNKNOWN must not be read as either.
    """
    return liveness_of(pid) == LIVE


def _boot_id() -> str:
    """The kernel's boot id, validated as a nonempty UUID, or "".

    The Linux start-tick counter restarts with every boot, so a persisted token
    without the boot cycle cannot tell one boot's pid instance from another's.
    """
    try:
        with open(BOOT_ID_PATH, encoding="utf-8") as handle:
            text = handle.read().strip().lower()
    except OSError:
        return ""
    parts = text.split("-")
    if len(parts) != 5 or [len(part) for part in parts] != [8, 4, 4, 4, 12]:
        return ""
    if any(ch not in "0123456789abcdef" for part in parts for ch in part):
        return ""
    return text


def _pid_namespace_identity() -> str:
    """This observer's pid-namespace identity (`pid:[…]`), or "".

    The same pid number names different processes in different pid namespaces, so
    a shared run root could otherwise treat a stranger's process as the recorded
    one. The observer's own namespace is the domain a `/proc` reading is valid in.
    """
    try:
        link = os.readlink(SELF_PIDNS_PATH)
    except OSError:
        return ""
    link = str(link).strip()
    return link if link.startswith("pid:[") and link.endswith("]") and len(link) > 6 else ""


def _proc_stat_identity(pid) -> str:
    """`linux:v2:<boot-id>:<pid-namespace>:<pid>:<start-ticks>`, or "".

    Field 22 of `/proc/<pid>/stat` is the process's start time in clock ticks
    since boot: stable for the process's lifetime, and — paired with the boot id
    and the pid namespace — a token that a recycled pid, a later boot or another
    namespace cannot reproduce. If any component cannot be read or validated the
    answer is "" (no strong identity), never a weaker token: a persisted
    `proc:<ticks>` token from an older revision does not authorize a signal.
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
        ticks = int(fields[19])
    except ValueError:
        return ""
    boot = _boot_id()
    namespace = _pid_namespace_identity()
    if not boot or not namespace:
        return ""
    return f"{LINUX_IDENTITY_VERSION}{boot}:{namespace}:{int(pid)}:{ticks}"


def _ps_identity(pid) -> str:
    """`ps` start time: diagnostic evidence on POSIX systems without procfs.

    `ps -o lstart=` renders a localized, timezone-shaped *display* timestamp, so
    the probe fixes its own view (`TZ=UTC`, `LC_ALL=C`, for this call only) — the
    worker's environment is untouched. Two processes can nevertheless share a
    timestamp, and a timestamp is not a process-instance handle, so this token is
    **never** allowed to authorize a destructive signal (`identity_is_strong`
    rejects it); it is recorded as evidence an operator can read and used for
    conservative liveness only.
    """
    env = dict(os.environ)
    env["TZ"] = "UTC"
    env["LC_ALL"] = "C"
    try:
        proc = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            creationflags=hidden_flags(),
        )
    except OSError:
        return ""
    text = (proc.stdout or "").strip()
    return f"{PS_IDENTITY_PREFIX}{text}" if proc.returncode == 0 and text else ""


def _windows_identity(pid) -> str:
    """`win:v1:<creation FILETIME>:<pid>` — creation time paired with the pid.

    The handle and query calls are typed explicitly (`c_void_p` for the handle,
    `c_ulonglong` for the FILETIMEs): a native handle must not be truncated to a
    default C `int`. The token is identity *evidence*; the destructive operation
    is still refused on Windows, because nothing here binds the eventual
    termination of a whole tree to that process object.
    """
    QUERY_LIMITED = 0x1000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
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
        return f"{WINDOWS_IDENTITY_VERSION}{created.value}:{int(pid)}"
    finally:
        kernel32.CloseHandle(handle)


def process_identity(pid) -> str:
    """A token naming the process instance behind `pid`, or "" when unverifiable.

    Recorded next to every pid this adapter spawns and re-read before any signal
    is sent: a pid whose identity changed was reused, and belongs to someone else.
    Linux answers with the versioned boot/namespace/tick token or nothing at all —
    there is deliberately no fallback to a weaker probe there, because the weak
    token would authorize exactly the signal the strong one exists to gate.
    """
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return ""
    if IS_WINDOWS:
        return _windows_identity(pid)
    if os.path.exists("/proc"):
        return _proc_stat_identity(pid)
    return _ps_identity(pid)


def identity_is_strong(identity) -> bool:
    """Is this token an admissible authorization for a destructive signal?

    Only the versioned platform tokens are: Linux's boot/namespace/tick token and
    Windows' creation time paired with the pid. A legacy `proc:<ticks>` token, a
    `ps:` display timestamp and an empty value are evidence at most.
    """
    text = str(identity or "")
    return text.startswith(LINUX_IDENTITY_VERSION) or text.startswith(WINDOWS_IDENTITY_VERSION)


def identity_ok(pid, identity) -> bool:
    """Is the live process behind `pid` still the one `identity` names?

    Used before any signal: a missing recorded token, an unreadable current one,
    or one that does not match, is *not* proof and fails closed.
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


def process_group(pid) -> int:
    """The process group `pid` currently belongs to, or 0 when it cannot be read.

    `0` is "unknown", never "no group" and never permission to use a historical
    group id: every caller must treat a non-positive answer as a refusal. Read
    only on a process whose identity has already been proven to be this run's, so
    the group it names is this run's group too — the opposite of the removed
    `os.getpgid` fallback, which named a group from a bare pid.
    """
    if IS_WINDOWS or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return 0
    try:
        return int(os.getpgid(pid))
    except (OSError, ValueError):
        return 0


def group_member_pids(pgid):
    """Every pid currently in this process group (POSIX), or None when unreadable.

    `ps -e -o pid=,pgid=` answers on Linux, macOS and the BSDs alike. A failure to
    read the table is *not* an empty group: `None` is returned so the caller reports
    a stop it could not enumerate rather than one that left nobody alive.
    """
    if IS_WINDOWS or isinstance(pgid, bool) or not isinstance(pgid, int) or pgid <= 0:
        return None
    try:
        proc = subprocess.run(
            ["ps", "-e", "-o", "pid=,pgid="],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            creationflags=hidden_flags(),
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    pids = []
    for line in (proc.stdout or "").splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            pid, group = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        if group == pgid and pid > 0:
            pids.append(pid)
    return pids


def pidfd_available() -> bool:
    """Can this interpreter/kernel signal through a pidfd process handle?"""
    if IS_WINDOWS or not sys.platform.startswith("linux"):
        return False
    return hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")


def platform_can_force_stop() -> bool:
    """Is there a verified way to force this platform's processes to stop?

    Only the pidfd path is accepted: it binds the signal to the process instance
    that was validated. macOS (`ps` is a display timestamp), Windows (no
    reuse-proof tree-termination primitive) and Linux without pidfds answer False,
    and every caller must then refuse destructive escalation rather than fall back
    to a bare pid, a group id or `taskkill`.
    """
    return pidfd_available()


class ProcessHandle:
    """A pidfd for one process instance: the only thing this adapter signals.

    `open()` acquires the handle; `exited()` asks the kernel whether the process
    behind it has already reported exit; `signal()` delivers through that same
    handle, so nothing an OS-level reuse could do between validation and delivery
    can retarget it. `close()` is safe on every path.
    """

    def __init__(self, pid, identity=""):
        self.pid = pid
        self.identity = identity
        self.fd = None

    def open(self) -> bool:
        try:
            self.fd = os.pidfd_open(self.pid, 0)
        except OSError:
            self.fd = None
        return self.fd is not None

    def exited(self) -> bool:
        """Has the process behind this handle exited (or is the handle unusable)?"""
        if self.fd is None:
            return True
        try:
            readable, _, _ = select.select([self.fd], [], [], 0)
        except (OSError, ValueError):
            return True
        return bool(readable)

    def signal(self, signum) -> bool:
        if self.fd is None:
            return False
        try:
            signal.pidfd_send_signal(self.fd, signum, None, 0)
            return True
        except (OSError, AttributeError, ValueError):
            return False

    def close(self) -> None:
        fd, self.fd = self.fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def signal_instance(pid, identity, signum) -> bool:
    """Signal one verified process instance through its own pidfd handle.

    The order is the contract: open the handle, re-read the identity and require
    it to match the recorded one, confirm the handle has not reported exit, then
    signal through that same handle and close it on every path. A missing or weak
    identity, a mismatch, an unreadable process or an unavailable handle all
    return False without a signal — a bare pid is never signalled.
    """
    if not identity_is_strong(identity):
        return False
    handle = ProcessHandle(pid, identity)
    try:
        if not handle.open():
            return False
        if not identity_ok(pid, identity):
            return False
        if handle.exited():
            return False
        return handle.signal(signum)
    finally:
        handle.close()


def anchored_members(anchor_pid, anchor_identity, group):
    """[(pid, identity, group)] of a group's verified live members, or None.

    The group is enumerated only while a member whose identity this run recorded
    is *continuously* verified as the live anchor: the anchor is checked before
    the enumeration and again after it (through its own pidfd handle, which also
    tells us whether it exited mid-way), and if it did not stay the same live
    process the whole enumeration is discarded. Every member discovered in the
    table is revalidated — its identity read now, its current group required to
    equal the group — before it is recorded, so a reused group id cannot mint new
    ownership out of a stale `ps` row. `None` means ownership or enumeration could
    not be established (including "the table was read but nothing in it proved
    live"): it is never `[]`, which would read as "nobody is alive".
    """
    if not identity_is_strong(anchor_identity):
        return None
    if process_group(anchor_pid) != group:
        return None
    handle = ProcessHandle(anchor_pid, anchor_identity)
    try:
        if not handle.open():
            return None
        if not identity_ok(anchor_pid, anchor_identity):
            return None
        if handle.exited():
            return None
        table = group_member_pids(group)
        if table is None:
            return None
        found = []
        for pid in sorted(table):
            state = liveness_of(pid)
            if state == GONE:
                continue
            if state == UNKNOWN:
                return None
            identity = anchor_identity if pid == anchor_pid else process_identity(pid)
            if not identity:
                return None
            if not identity_is_strong(identity):
                return None
            if pid != anchor_pid and not identity_ok(pid, identity):
                return None
            if process_group(pid) != group:
                return None
            found.append((pid, identity, group))
        if handle.exited() or not identity_ok(anchor_pid, anchor_identity):
            return None
        return found or None
    finally:
        handle.close()


def surviving_members(anchor_pid, anchor_identity, group):
    """Alias of `anchored_members`: the survivor set a stop observed, or None."""
    return anchored_members(anchor_pid, anchor_identity, group)


def survivor_records(*sources) -> list:
    """[(pid, identity, group)] for the processes a failed stop recorded alive.

    Written by the runner when its stop could not complete, and by nothing else.
    A record is never trusted on its own: the caller re-verifies the pid against
    the identity recorded beside it before anything is signalled, so a doctored
    or stale record can never aim a signal by itself.
    """
    found, seen = [], set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        records = source.get("survivors")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            pid = record.get("pid")
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or pid in seen:
                continue
            seen.add(pid)
            group = record.get("group")
            if isinstance(group, bool) or not isinstance(group, int) or group <= 0:
                group = 0
            identity = record.get("identity")
            found.append((pid, identity if isinstance(identity, str) else "", group))
    return found


def recorded_survivors(run_dir, state=None, lock=None) -> list:
    """The survivors a failed stop recorded in this run's lock and state, lock first."""
    if state is None:
        state = read_state_file(run_dir)
    if lock is None:
        lock = lock_of(run_dir)
    return survivor_records(lock, state)


def lock_of(run_dir) -> dict:
    lock = read_json(os.path.join(run_dir, "lock"), {})
    return lock if isinstance(lock, dict) else {}


def merge_state_locked(op: Operation, fields, state=None) -> dict:
    """Merge `fields` into state.json for one generation, with M held.

    The base is the state re-read here (or the state the caller just read under
    the same lock), never a snapshot captured at process start: a publisher may
    not republish a whole `running` state over a concurrent `stopping` update, and
    the merge keeps both halves.
    """
    base = read_state_file(op.run_dir) if state is None else dict(state)
    base.update(fields)
    write_json(os.path.join(op.run_dir, "state.json"), base)
    return base


def write_state_op(op: Operation, fields) -> dict:
    """Acquire M and merge `fields` into the current generation's state.json.

    Returns {} when the mutation is refused — no mutex, a changed generation, a
    foreign run or an already-committed verdict — and writes nothing in that case.
    """
    with mutex_of(op, MUTEX_WAIT_SECONDS) as held:
        if not held:
            warn(guard_refusal(op, GUARD_BUSY, ""))
            return {}
        verdict, state, detail = guard_locked(op)
        if verdict != GUARD_OK:
            warn(guard_refusal(op, verdict, detail))
            return {}
        return merge_state_locked(op, fields, state)


def merge_lock_locked(op: Operation, **fields) -> dict:
    """Merge fields into the lock record with M already held (see `update_lock`)."""
    lock = lock_of(op.run_dir)
    lock.update(fields)
    lock.setdefault("generation", op.generation)
    write_json(os.path.join(op.run_dir, "lock"), lock)
    return lock


def update_lock(run_dir, **fields) -> dict:
    """Merge fields into the lock record, under M, for the run's own generation.

    `lock` is process metadata, never a mutex, and it carries the generation of
    the run it describes: a merge that would write into a different generation is
    refused instead. A record with no generation cannot be mutated (see
    `guard_locked`).
    """
    op = operation_of(run_dir)
    with mutex_of(op, MUTEX_WAIT_SECONDS) as held:
        if not held:
            warn(guard_refusal(op, GUARD_BUSY, ""))
            return {}
        verdict, state, detail = guard_locked(op)
        if verdict != GUARD_OK:
            warn(guard_refusal(op, verdict, detail))
            return {}
        del state
        return merge_lock_locked(op, **fields)


def recorded_processes(run_dir, state=None) -> list:
    """(pid, identity) pairs that prove the run is live, runner first.

    Identity comes from the field the runner recorded at spawn
    (`pid_identity`/`agent_pid_identity`), and a lock entry is preferred over a
    state entry for the same pid only when it carries more information. The
    processes a failed stop recorded as still alive are appended: they are live
    members of the agent's group, and they are what keeps a run whose leader is
    gone visibly alive until a later stop ends them.
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
    for pid, identity, _group in recorded_survivors(run_dir, state, lock=lock):
        if not any(known == pid for known, _ in found):
            found.append((pid, identity))
    return found


def recorded_pids(run_dir, state=None) -> list:
    """Pids that prove the run is live: the runner and the dsh process it started."""
    return [pid for pid, _ in recorded_processes(run_dir, state)]


def run_alive(run_dir, state=None) -> bool:
    """Is a recorded process possibly alive *and* still the one that was recorded?

    A pid whose recorded identity no longer matches is a reused pid, not this
    run's — but only a token that was actually read and differs proves that; a
    read that failed leaves the run alive. When no identity was recorded at all —
    an older run, or a platform with no usable token — liveness is the only
    evidence there is and it is trusted here: declaring a possibly-live run dead
    is what lets a reader settle work that is still being written. An `UNKNOWN`
    (access denial, failed inspection) counts as possibly alive for the same
    reason; signalling makes the opposite, fail-closed choice. The processes a
    failed stop recorded count too, so a run whose surviving tools outlived their
    agent is still live and still occupies its slug.
    """
    if state is None:
        state = read_state_file(run_dir)
    for pid, identity in recorded_processes(run_dir, state):
        if liveness_of(pid) == GONE:
            continue
        if identity_changed(pid, identity):
            continue
        return True
    return False


def stop_unconfirmed(state) -> bool:
    """Was this run's stop left with survivors that could not be enumerated?

    `survivors_complete: false` is written by `report_incomplete_stop` when the
    enumeration itself failed (Windows, or an inspection command that errored).
    It is the one record that says "nothing was found alive" is not the same
    statement as "nothing is alive", so no reader may finalize such a run on
    liveness evidence alone. A run with no `stopping` flag is not a stop at all.
    """
    state = state or {}
    return bool(state.get("stopping")) and state.get("survivors_complete") is False


def stop_survivors(run_dir, state=None):
    """Every live member of the groups this run can *prove* it owns, or None.

    Ownership comes from a currently verified recorded process whose group is
    readable now — the runner, the agent, or a survivor a failed stop observed —
    never from a historical group number: a positive `group` in a record is not a
    candidate by itself, because after pid reuse that number may name a stranger's
    group. Each group is enumerated under such an anchor (`anchored_members`).

    Three answers, and the callers must keep them apart:
      * a list — the enumeration completed and these members are alive;
      * `[]`   — every recorded process is conclusively `GONE` *and* no group it
                 led still exists, so nothing this run owns is alive;
      * `None` — ownership or enumeration could not be established, a recorded
                 process could not be inspected (`UNKNOWN`), or a recorded group
                 still exists with no live member to anchor it (its id may have
                 been reused, and members of this run it never observed could be
                 in it), so "nobody alive" must not be inferred.
    """
    if state is None:
        state = read_state_file(run_dir)
    recorded_groups = {
        pid: group for pid, _identity, group in recorded_survivors(run_dir, state)
    }
    anchors, examined, vanished_groups = [], 0, []
    for pid, identity in recorded_processes(run_dir, state):
        examined += 1
        state_of_pid = liveness_of(pid)
        if state_of_pid == GONE:
            # Gone processes cannot anchor, but a group they led may still hold
            # members this run never recorded: a group that still exists is not
            # evidence of absence.
            vanished_groups.append(recorded_groups.get(pid) or pid)
            continue
        if state_of_pid == UNKNOWN:
            return None
        if identity_changed(pid, identity):
            continue
        if not identity_is_strong(identity):
            # A live process whose token cannot authorize anything: we can see it
            # and we cannot prove what it is, so the answer is unknown.
            return None
        group = process_group(pid)
        if group <= 0:
            return None
        anchors.append((pid, identity, group))
    if examined == 0:
        # Nothing was ever recorded: there is nothing to prove anything with, and
        # "nobody alive" would be a guess.
        return None
    if not anchors:
        for group in vanished_groups:
            if not group:
                continue
            if group_live(group) is not False:
                # True (a live member this run never recorded may be in it) or
                # None (the table could not be read): both stay unknown.
                return None
        return []
    groups, seen, members = set(), set(), []
    for pid, identity, group in anchors:
        if group in groups:
            continue
        groups.add(group)
        found = anchored_members(pid, identity, group)
        if found is None:
            return None
        for member in found:
            if member[0] not in seen:
                seen.add(member[0])
                members.append(member)
    return members


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


def spawn_credentials(op: Operation) -> tuple:
    """(generation, token) from the handshake file, or ("", "").

    The file is written by `start` for exactly one runner and names the run
    generation: a credential that does not name the generation of the run it is
    presented to authorizes nothing.
    """
    payload = read_json(os.path.join(op.run_dir, SPAWN_TOKEN_FILE), None)
    if not isinstance(payload, dict):
        return "", ""
    generation = payload.get("generation")
    token = payload.get("token")
    if not isinstance(generation, str) or not isinstance(token, str):
        return "", ""
    return generation, token


def spawn_runner(argv, cwd, log_path) -> subprocess.Popen:
    """Start the detached runner: POSIX own session, Windows hidden console.

    The child environment is scrubbed of the harness's reserved identity keys
    (`child_env`), so a caller inside a live `dsh` session cannot shape the run.
    The generation-stamped handshake `start` wrote is read here and its credential
    — generation and token — travels only in this child's environment, so the
    runner can prove both that it is the process `start` spawned and which
    generation it was spawned for; every child below the runner sees the name
    removed again (`child_env`).
    """
    credentials = ""
    try:
        with open(
            os.path.join(os.path.dirname(os.path.abspath(log_path)), SPAWN_TOKEN_FILE),
            encoding="utf-8",
        ) as handle:
            payload = json.load(handle)
        generation = payload.get("generation") or ""
        token = payload.get("token") or ""
        if generation and token:
            credentials = f"{generation}:{token}"
    except (OSError, ValueError, AttributeError):
        credentials = ""
    with open(log_path, "ab") as log:
        env = child_env()
        if credentials:
            env[RUNNER_TOKEN_ENV] = credentials
        kwargs = {
            "cwd": cwd,
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
            "env": env,
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
    """Signal the group this pid leads — by verified members, never by the group id.

    `pid` is a group leader by construction (`start_new_session` /
    `CREATE_NEW_PROCESS_GROUP`), but the group id is a pid: once that leader is
    gone the number alone proves nothing, and even while it is alive a bare
    `killpg` has an exit/reuse window that no mutex can close. So the group is
    enumerated under the leader as a continuously verified anchor
    (`anchored_members`) and every member — the leader included — is signalled
    through its own validated process handle (`signal_instance`). Return value
    means "signals were sent", never "the stop completed". A leader whose
    identity is missing, weak or changed is refused outright; if the enumeration
    cannot be established only the verified anchor itself is signalled, and the
    caller's own enumeration decides whether the stop is complete.
    """
    if IS_WINDOWS:
        return False
    if not identity_is_strong(identity):
        warn(
            f"not signalling the group of pid {pid}: the recorded identity is "
            f"{'missing' if not identity else 'not admissible'}; refusing to guess"
        )
        return False
    pid_state = liveness_of(pid)
    if pid_state == GONE:
        warn(
            f"not signalling process group {pid}: the process this run recorded is gone, so "
            "the group id does not prove the group is this run's; refusing to guess"
        )
        return False
    if pid_state == UNKNOWN:
        warn(f"not signalling the group of pid {pid}: the process could not be inspected")
        return False
    if not identity_ok(pid, identity):
        warn(
            f"not signalling pid {pid}: it is no longer the process this run recorded "
            f"(identity {'missing' if not identity else 'changed'}); refusing to guess"
        )
        return False
    group = process_group(pid)
    if group <= 0:
        warn(f"not signalling the group of pid {pid}: its process group could not be read")
        return False
    if group != pid:
        warn(
            f"not signalling the group of pid {pid}: it now belongs to process group {group} "
            "rather than leading its own; refusing to guess"
        )
        return False
    if not platform_can_force_stop():
        warn(
            f"not signalling the group of pid {pid}: this platform has no verified process "
            "handle primitive (a pidfd); refusing to fall back to a bare pid or group id"
        )
        return False
    members = anchored_members(pid, identity, group)
    if members is None:
        # Ownership of the group could not be established; the anchor itself is
        # verified, so it may be signalled, and nothing else may.
        warn(
            f"the group of pid {pid} could not be enumerated under a verified anchor; "
            "signalling only the verified process itself"
        )
        members = [(pid, identity, group)]
    sent = False
    for member_pid, member_identity, _member_group in members:
        if signal_instance(member_pid, member_identity, signum):
            sent = True
    return sent


def signal_member_group(pid, signum, identity="", group=0) -> bool:
    """Signal the group through a recorded *member*, by verified handles only.

    Used for the survivors a failed stop named: the member must be alive, carry
    an admissible recorded identity that still matches, and belong to a group
    that can be read *now* — a historical group number is never a fallback, even
    when the current one cannot be read. When a group was recorded it must equal
    the current one. The member then anchors an enumeration of that group and
    every verified member is signalled through its own handle; if the enumeration
    fails, only the verified member itself is signalled.
    """
    if IS_WINDOWS:
        return False
    if not identity_is_strong(identity):
        warn(
            f"not signalling the group of pid {pid}: the recorded identity is "
            f"{'missing' if not identity else 'not admissible'}; refusing to guess"
        )
        return False
    pid_state = liveness_of(pid)
    if pid_state == GONE:
        return False
    if pid_state == UNKNOWN:
        warn(f"not signalling the group of pid {pid}: the process could not be inspected")
        return False
    if not identity_ok(pid, identity):
        warn(
            f"not signalling the group of pid {pid}: it is no longer the process this run "
            f"recorded (identity {'missing' if not identity else 'changed'}); refusing to guess"
        )
        return False
    current = process_group(pid)
    if current <= 0:
        warn(
            f"not signalling the group of pid {pid}: its current process group could not be "
            "read; a recorded group number is not a fallback"
        )
        return False
    if group and current != group:
        warn(
            f"not signalling the group of pid {pid}: it now belongs to process group {current}, "
            f"not the recorded {group}; refusing to guess"
        )
        return False
    if not platform_can_force_stop():
        warn(
            f"not signalling the group of pid {pid}: this platform has no verified process "
            "handle primitive (a pidfd); refusing to fall back to a bare pid or group id"
        )
        return False
    members = anchored_members(pid, identity, current)
    if members is None:
        warn(
            f"the group of pid {pid} could not be enumerated under a verified anchor; "
            "signalling only the verified process itself"
        )
        members = [(pid, identity, current)]
    sent = False
    for member_pid, member_identity, _member_group in members:
        if signal_instance(member_pid, member_identity, signum):
            sent = True
    return sent


def group_live(pgid):
    """Does this group still hold a *live* (non-zombie) process? True/False/None.

    `killpg(pgid, 0)` alone is not the answer: an unreaped zombie — a child of the
    observer that nobody has waited for — keeps answering that the group exists
    while running no code, holding no pipe and writing nothing. So the group is
    read out and each member's liveness is asked for; `False` means the table was
    read and holds no live member, `True` means one is alive, and `None` means the
    table could not be read (Windows has no group table at all), which must never
    be read as "nobody".
    """
    if IS_WINDOWS or isinstance(pgid, bool) or not isinstance(pgid, int) or pgid <= 0:
        return None
    table = group_member_pids(pgid)
    if table is None:
        return None
    for pid in sorted(table):
        if liveness_of(pid) == LIVE:
            return True
    return False


def tree_alive(pid) -> bool:
    """The process itself, or on POSIX any live member of the group it leads."""
    if liveness_of(pid) != GONE:
        return True
    return group_live(pid) is not False


def terminate_tree(pid, signum, identity="") -> bool:
    """Refuse the unverifiable platform paths; signal a verified group nowhere else.

    Windows has no verified tree-termination primitive — `OpenProcess →
    GetProcessTimes → CloseHandle → taskkill /PID` never binds the destructive
    operation to the process object it validated — so `taskkill` is disabled as
    an authorized stop path there. Everywhere else this is `signal_group`.
    """
    if IS_WINDOWS:
        warn(
            f"not stopping pid {pid}: this platform has no verified process-instance "
            "termination primitive, so no destructive call is made; the run stays "
            "non-terminal until its process is gone"
        )
        return False
    return signal_group(pid, signum, identity)


def terminate_agent(process, op: Operation, agent_identity="") -> tuple:
    """Stop the agent and the tools under it; (KILL_EXIT, survivors).

    `survivors` is the stop's outcome and never an empty hole:
      * `[]` — the stop is *proven*: the agent is reaped or conclusively gone and
        the group id it led no longer names a group;
      * a list — the stop did not complete, and these (pid, identity, group)
        members were still alive when it gave up;
      * `None` — the stop did not complete and the survivors could not be
        enumerated (no group table, a failed inspection, a member whose identity
        cannot be read, or a platform with no verified handle primitive at all).
    Only `[]` may reach a terminal state; the caller must not publish one for a
    list or for `None` (see `report_incomplete_stop`).

    Every escalation step is re-authorized first: M is taken, the operation's
    generation and terminal status are re-checked, and only then is a signal sent
    — and M is released again before the next bounded wait. A generation change
    stops the escalation where it stands. Windows has no `signal.SIGKILL`
    attribute at all, so the POSIX signal numbers are only read on the branch that
    uses one (`stop_signal`).
    """
    agent = process.pid
    group = process_group(agent) or agent

    def settled() -> bool:
        process.poll()  # reap a zombie before judging the group
        return liveness_of(agent) == GONE and group_live(group) is False

    def authorize() -> bool:
        """Revalidate the generation under M; True when a signal may be sent."""
        with mutex_of(op, MUTEX_WAIT_SECONDS) as held:
            if not held:
                warn(guard_refusal(op, GUARD_BUSY, ""))
                return False
            verdict, _state, detail = guard_locked(op, require_lock_generation=True)
            if verdict != GUARD_OK:
                warn(guard_refusal(op, verdict, detail))
                return False
            return True

    if not platform_can_force_stop():
        # No verified handle primitive: no destructive call exists, so the stop
        # is reported as unconfirmed instead of pretending a signal was "safe".
        warn(
            "this platform has no verified process-instance signalling primitive "
            "(a pidfd); the stop stays a request and the run is not finalized"
        )
        return KILL_EXIT, None
    if process.poll() is None and authorize():
        terminate_tree(agent, stop_signal(escalate=False), agent_identity)
        for _ in range(20):
            if settled():
                break
            time.sleep(POLL_SECONDS)
    for _ in range(40):
        if settled():
            break
        time.sleep(POLL_SECONDS)
    if not settled() and authorize():
        terminate_tree(agent, stop_signal(escalate=True), agent_identity)
        for _ in range(20):
            if settled():
                break
            time.sleep(POLL_SECONDS)
    if settled():
        return KILL_EXIT, []
    members = surviving_members(agent, agent_identity, group)
    if members:
        return KILL_EXIT, members
    return KILL_EXIT, None


def stop_signal(escalate: bool):
    """The signal number for one stop step, or None where signals do not apply.

    Windows has no process groups and no `signal.SIGKILL` attribute at all, so
    the POSIX constants are read only on the branch that actually signals.
    """
    if IS_WINDOWS:
        return None
    return signal.SIGKILL if escalate else signal.SIGTERM


def kill_tree(op: Operation, state=None) -> bool:
    """Force an unresponsive run to stop, one authorized step at a time.

    Every signal decision is revalidated under M for the generation the caller
    captured, and M is *retained through the signal*: the guard re-reads the
    route, the generation and the terminal commit, the recorded process evidence
    is refreshed from that re-read (never from the entry snapshot), and the
    permitted signal action is performed before M is released. A generation
    change therefore stops the escalation where it stands — no further signal, no
    enumeration of the replacement, no write — and M is released only while the
    polling loops wait for the tree to disappear. A platform with no verified
    handle primitive refuses outright (`platform_can_force_stop`). Returns True
    when the caller's operation generation is the one that was acted on and no
    recorded process of it is still alive; a guarded pass that finds every
    recorded process of that generation already GONE is the same conclusion
    (there is nothing left to signal), so it returns True rather than a spurious
    False.
    """
    processes = recorded_processes(op.run_dir, state)
    if not processes:
        return False
    if not platform_can_force_stop():
        warn(
            "this platform has no verified process-instance signalling primitive (a pidfd); "
            "refusing to force any stop"
        )
        return False
    survivors = {
        pid: (identity, group)
        for pid, identity, group in recorded_survivors(op.run_dir, state)
    }

    def alive(pid) -> bool:
        record = survivors.get(pid)
        if record:
            _identity, group = record
            return tree_alive(pid) or (bool(group) and group_live(group) is not False)
        return tree_alive(pid)

    def gone() -> bool:
        return not any(alive(pid) for pid, _ in processes)

    def act(signum):
        """One guarded signalling pass; M is held from the guard read to the signal.

        Returns `(outcome, evidence)`. `outcome` is one of:
        `"acted"` — at least one recorded process of the validated generation was
        signalled; `"complete"` — the validated state still holds and every
        recorded process it names is already GONE, so nothing is left to signal;
        `"idle"` — recorded processes are live but none could be signalled;
        `"refused"` — the guard refused (busy, foreign, changed generation or an
        already-committed verdict), and nothing was signalled or enumerated.
        `evidence` is the `(processes, survivors)` pair refreshed from the very
        state the guard validated, so the polling that follows asks about the
        same generation the signal decision was made from.
        """
        with mutex_of(op, MUTEX_WAIT_SECONDS) as held:
            if not held:
                warn(guard_refusal(op, GUARD_BUSY, ""))
                return "refused", None
            verdict, fresh, detail = guard_locked(op, require_lock_generation=True)
            if verdict != GUARD_OK:
                warn(guard_refusal(op, verdict, detail))
                return "refused", None
            fresh_processes = recorded_processes(op.run_dir, fresh)
            fresh_survivors = {
                pid: (identity, group)
                for pid, identity, group in recorded_survivors(op.run_dir, fresh)
            }
            acted, pending = False, False
            for pid, identity in fresh_processes:
                if liveness_of(pid) == GONE:
                    continue
                pending = True
                record = fresh_survivors.get(pid)
                if record:
                    record_identity, group = record
                    if group <= 0:
                        record_identity, group = identity, process_group(pid)
                    if signal_member_group(pid, signum, record_identity or identity, group):
                        acted = True
                elif signal_group(pid, signum, identity):
                    acted = True
            evidence = (fresh_processes, fresh_survivors)
            if acted:
                return "acted", evidence
            if pending:
                return "idle", evidence
            return "complete", evidence

    def step(signum) -> str:
        """One pass; the evidence it acted on becomes the evidence polled next."""
        nonlocal processes, survivors
        outcome, evidence = act(signum)
        if evidence is not None:
            processes, survivors = evidence
        return outcome

    outcome = step(signal.SIGTERM)
    if outcome == "complete":
        return True
    if outcome != "acted":
        return False
    for _ in range(20):
        if gone():
            return True
        time.sleep(POLL_SECONDS)
    outcome = step(signal.SIGKILL)
    if outcome == "complete":
        return True
    if outcome != "acted":
        return False
    for _ in range(20):
        if gone():
            return True
        time.sleep(POLL_SECONDS)
    return False


def request_stop(op: Operation) -> bool:
    """Publish the stop request the runner polls, bound to one generation.

    Written under M and only after the guard accepted this operation, so a stop
    request issued against one generation can never land in the run that
    replaced it. The request names the generation, a fresh request id, the
    timestamp and the requesting pid; a runner acts only on its own generation's
    request.
    """
    with mutex_of(op, MUTEX_WAIT_SECONDS) as held:
        if not held:
            warn(guard_refusal(op, GUARD_BUSY, ""))
            return False
        verdict, state, detail = guard_locked(op)
        if verdict != GUARD_OK:
            warn(guard_refusal(op, verdict, detail))
            return False
        del state
        write_json(
            os.path.join(op.run_dir, "stop"),
            {
                "generation": op.generation,
                "request_id": new_nonce(),
                "requested_at": now_iso(),
                "by": os.getpid(),
            },
        )
        return True


def stop_request_for(run_dir, generation) -> dict:
    """The stop request that is actionable for this runner generation, or {}.

    A request is actionable only when its generation equals both the runner's
    captured generation and the generation the current state records; file
    existence is not a request, and a malformed or foreign-generation request is
    never acted on (and never deleted — it belongs to whoever wrote it).
    """
    request = read_json(os.path.join(run_dir, "stop"), None)
    if not isinstance(request, dict):
        return {}
    if request.get("generation") != generation or not generation:
        return {}
    if strict_generation(read_state_file(run_dir)) != generation:
        return {}
    return request


def wait_for_terminal(op: Operation, seconds) -> str:
    """Wait for a *validated* terminal snapshot of this generation.

    Returns `WAIT_TERMINAL`, `WAIT_GENERATION_CHANGED` or `WAIT_TIMEOUT`. The
    marker is not consulted and its contents are never returned: a run is
    terminal when its committed record says so, which is exactly the moment every
    reader may act on it. A generation change is reported as such rather than as
    a timeout, so the caller can say the run it waited for is gone.
    """
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        state = read_state_file(op.run_dir)
        if op.generation and strict_generation(state) not in ("", op.generation):
            # Generation binding first: a terminal record the replacement run
            # committed is that run's verdict, never evidence about this one.
            return WAIT_GENERATION_CHANGED
        record = terminal_snapshot_locked(state)
        if record is not None and (
            not op.generation or record.get("generation") == op.generation
        ):
            return WAIT_TERMINAL
        if time.monotonic() >= deadline:
            return WAIT_TIMEOUT
        time.sleep(POLL_SECONDS)


# -- run discovery -----------------------------------------------------------


def await_settled_stop(run_dir, generation, seconds=None) -> bool:
    """Wait, bounded, for a *committed* stop to be conclusively settled.

    A committed terminal verdict and the tree being gone are two events. The
    runner that wrote the verdict is still one of the run's recorded processes
    until it returns and the kernel reaps it, and while it exits the same evidence
    the replacement check reads can be momentarily unproven in two ways: a
    recorded process is still live, or the enumeration cannot be established at
    all — `stop_survivors` returns `None`, never an empty list, when its anchor
    leaves mid-enumeration. Sampling that instant *once* refuses the very run that
    was just stopped, so the question is asked again on freshly read state, until
    it is conclusive (`run_alive` false and `stop_survivors() == []`) or `seconds`
    expires.

    This is re-asked evidence, not a sleep: every iteration re-reads state.json
    and re-runs the same predicate the refusal below uses, and the mutation mutex
    is *not* held while waiting (the same discipline as `stop_run` and the start
    handshake). `False` means the evidence was still unproven at the bound — a
    genuinely live survivor, or a table that cannot be read — so the caller's
    refusal stands unchanged. A generation change ends the wait immediately:
    whoever holds the path now is not what this stop decided about, and the
    caller's generation check reports that instead.

    `seconds` is the bound and is resolved at call time — `settle_wait_seconds()`
    when omitted, i.e. the `DSH_RUN_SETTLE_WAIT_SECONDS` knob over
    `SETTLE_WAIT_SECONDS` — so a caller can shorten a wait it is prepared to
    answer for, and the environment can bound it per install.
    """
    if not generation:
        return False
    if seconds is None:
        seconds = settle_wait_seconds()
    deadline = time.monotonic() + max(0.0, seconds)
    announced = False
    while True:
        state = read_state_file(run_dir)
        if strict_generation(state) != generation:
            return False
        if not run_alive(run_dir, state) and stop_survivors(run_dir, state) == []:
            return True
        if not announced:
            warn(
                f"the stop of {run_dir} is not settled yet: a recorded process is still live, or "
                f"its groups cannot be enumerated; waiting up to {seconds:g}s for a conclusive "
                "answer (the replacement refusal stands if it does not come)"
            )
            announced = True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)


def date_of(path) -> str:
    for part in reversed(os.path.abspath(path).split(os.sep)):
        if DATE_RE.match(part):
            return part
    return ""


def newest_first(paths):
    return sorted(paths, key=lambda path: (date_of(path), mtime_of(path)), reverse=True)


def run_dirs(root=None):
    """Every recorded run under the root, newest date first.

    A directory with no `state.json` is still a run directory — a launcher that
    died before it could write one — and it must be listable, because `unknown
    (no state)` is one of the lifecycle answers this adapter owes a caller.
    """
    root = root or run_root()
    found = []
    seen = set()
    for pattern in RUN_DIR_PATTERNS:
        for path in glob.glob(os.path.join(root, pattern)):
            if os.path.basename(path) and DATE_RE.match(os.path.basename(path)):
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
    The discovery (globbing, marker checks, realpath dedup, ordering) is
    `run_dirs`' single implementation; this only selects the slug's entries.
    """
    return [
        path
        for path in run_dirs(root)
        if os.path.basename(path) == slug and os.path.isdir(path)
    ]


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


def _occupying_run_locked(root, slug):
    """`occupying_run` with M held: the scan itself may settle dead runs."""
    for candidate in slug_run_dirs(root, slug):
        state, _ = _effective_state_locked(operation_of(candidate))
        if terminal_snapshot_locked(state) is not None:
            continue
        if (
            run_alive(candidate, state)
            or is_starting(candidate, state)
            or stop_unconfirmed(state)
        ):
            return candidate, state
    return None, {}


class LifecycleBusy(RuntimeError):
    """A question that needs the lifecycle mutex could not get it.

    Raised instead of answering, so "another process is mutating this slug right
    now" can never be mistaken for the answer itself (for `occupying_run`, the
    "slug is free" sentinel).
    """


def occupying_run(root, slug, wait=MUTEX_WAIT_SECONDS):
    """(run_dir, state): this slug's unfinished run, in any date bucket.

    Returns the `(None, {})` sentinel only for a slug no unfinished run occupies.
    The scan needs M (settling a dead run is a mutation), so it waits up to `wait`
    for it; if the mutex cannot be held — another process is mutating the slug —
    that is *busy*, not free, and this raises `LifecycleBusy` rather than
    answering the unoccupied sentinel. A run directory is unfinished while no
    terminal record is committed, and it occupies its slug wherever it is dated:
    `start` must not create a second run for the same slug just because midnight
    moved the date bucket. Dead unfinished runs are settled first by the recovery
    path, so what remains — and what this returns — is work that is still live,
    still inside its startup grace, or a stop that was never proven complete.
    That last case occupies the slug even when nothing recorded is alive: the
    enumeration that would have shown there is nobody left is exactly the one
    that failed.
    """
    with lifecycle_claim(root, slug, wait) as held:
        if not held:
            warn(
                f"cannot scan {root} for run '{slug}': its lifecycle mutex is held by "
                "another process"
            )
            raise LifecycleBusy(
                f"run '{slug}' is being mutated by another process "
                f"(see {lifecycle_lock_path(root, slug)}); refusing to report it unoccupied"
            )
        return _occupying_run_locked(root, slug)


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


def terminal_record_line(raw) -> bool:
    """Whether one raw stream line carries this route's terminal record.

    `summarize` settles the run from the retained stream alone, and both the
    verdict (`final_reason == "completed"`) and the answer come from the last
    `final` event — so that is the one line the bounded writer is told to
    protect, whatever arrives after it. The test is exactly `summarize`'s own:
    decode, strip, parse, `type == "final"`. The `.strip()` is load-bearing for
    that parity: `str.strip` removes whitespace `json.loads` alone would reject,
    so dropping it would make the declaration narrower than the reader — and a
    narrower declaration can drop a line the reader still settles from. A
    byte-level prefilter would be cheaper but would miss a `final` whose type
    value is JSON-escaped, which `summarize` still reads as a final.
    """
    try:
        event = json.loads(raw.decode("utf-8", "replace").strip())
    except ValueError:
        return False
    return isinstance(event, dict) and event.get("type") == "final"


class EventLog:
    """This run's bounded NDJSON log: the shared writer plus its stats sidecar.

    Every append and the final sidecar write happen inside the lifecycle mutex of
    the generation this log belongs to, after the guard accepted that generation:
    the event files are part of the run directory, and a late append from a
    generation that a starter has already replaced would land in the new run's
    stream. The mutex is taken without a bound — dropping an event line because a
    reader held M for a moment would silently corrupt the accounting, and the
    drain thread is never joined by a thread that is holding M.
    """

    def __init__(self, op: Operation):
        self.op = op
        cap, warning = events_max_bytes()
        if warning:
            warn(warning)
        # The bound is resolved from DSH_RUN_EVENTS_MAX_BYTES here and handed to
        # the shared writer's constructor, so the DSH key is the only knob this
        # route needs and no OMP-named default warning lands in runner.log.
        writer_class = load_writer()
        self.path = os.path.join(op.run_dir, "events.ndjson")
        # passthrough=False: this adapter's own stdout is runner.log, and the
        # writer's terminal passthrough would copy the whole stream there
        # unbounded, so the event bound would bound nothing.
        self.writer = writer_class(op.run_dir, cap, defaulted=warning is not None, passthrough=False)
        self.finished = False
        self.lock = threading.Lock()

    def feed(self, raw) -> None:
        with mutex_of(self.op, wait=None) as held:
            if not held:
                return
            with self.lock:
                if self.finished:
                    # A reader thread can still be draining a stream a descendant kept
                    # open. After `finish()` its remaining lines are dropped on purpose:
                    # the run records `stream_incomplete` rather than pretending to have
                    # them.
                    return
                verdict, _state, _detail = guard_locked(self.op)
                if verdict != GUARD_OK:
                    return
                self.writer.feed(raw, protect=terminal_record_line(raw))

    def finish(self) -> None:
        with mutex_of(self.op, wait=None) as held:
            if not held:
                return
            with self.lock:
                if self.finished:
                    return
                verdict, _state, _detail = guard_locked(self.op)
                if verdict != GUARD_OK:
                    # A committed verdict or a replaced run: the sidecar must not be
                    # (re)written for this generation.
                    self.finished = True
                    return
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


def survivors_blocking_commit(state, run_dir, stop_proven=False) -> str:
    """Why a terminal commit must wait, or "" when the stop evidence allows one.

    A terminal verdict claims the run is over. That claim needs the stop to be
    proven: an enumeration that could not be established (`survivors_complete:
    false`) is not proof that nobody is alive, and a recorded survivor that is
    still the process it was when it was recorded is a live process whatever the
    caller's exit code says — including a direct `finalize(..., KILL_EXIT)` call.
    `stop_proven` is the caller saying it has established completion *now*: a
    fresh, complete enumeration that found nobody, or a verified process-instance
    stop that left nobody behind. Fresh evidence resolves an older `unknown`
    record; it never overrides a survivor that is alive right now.
    """
    state = state or {}
    if (
        state.get("stopping")
        and state.get("survivors_complete") is False
        and not stop_proven
    ):
        return "the stop's survivor enumeration could not be established"
    for pid, identity, _group in recorded_survivors(run_dir, state):
        if liveness_of(pid) == GONE:
            continue
        if identity_changed(pid, identity):
            continue
        return f"recorded survivor pid {pid} is still the process it was recorded as"
    return ""


def _publish_terminal_locked(op: Operation, state, exit_code, recovered, note, extra) -> dict:
    """Publish one terminal record, in one order, with M held throughout.

    1. The compatibility artifacts are materialized atomically: `answer.md`,
       `exit.code`, and `session.id` when there is a session.
    2. `state.json` is replaced atomically, carrying the complete terminal record
       — this replacement is the linearization point: before it, no reader
       reports a verdict; after it, state, answer, session and exit all come from
       one snapshot.
    3. The `finalized` marker is written for compatibility only (the exit code as
       its historical text form). A failure to write it is reported, never turned
       into a failed finalization, because the authority is already committed.

    No generation artifact is written after step 2.
    """
    run_dir = op.run_dir
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
        # Everything else, including an exit 0 whose last `final` is missing or
        # not `completed`.
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
            f"process disappeared without finalizing (backend {BACKEND}; runner/agent pids {pids} "
            "are gone); finalized with exit -1"
        )
    elif note:
        state["note"] = note
    # A failed stop publishes `stopping`/`survivors` so the run stays visibly
    # alive; once a terminal state is committed they are history, not liveness.
    leftover = survivor_records(state, lock_of(run_dir))
    state.pop("stopping", None)
    state.pop("survivors_complete", None)
    if leftover:
        state.pop("survivors", None)
        state["survivors_stopped"] = [pid for pid, _identity, _group in leftover]
    if extra:
        state.update(extra)
    # (1) compatibility artifacts, atomically and before the commit
    write_text_atomic(os.path.join(run_dir, "answer.md"), summary["answer"])
    write_text_atomic(os.path.join(run_dir, "exit.code"), f"{exit_code}\n")
    if state.get("session_id"):
        write_text_atomic(os.path.join(run_dir, "session.id"), f"{state['session_id']}\n")
    # (2) the commit itself: one atomic replacement, holding everything
    state["terminal_record"] = {
        "version": TERMINAL_RECORD_VERSION,
        "generation": op.generation,
        "commit_id": new_nonce(),
        "answer": summary["answer"],
        "session_id": state.get("session_id") or "",
        "exit": exit_code,
    }
    write_json(os.path.join(run_dir, "state.json"), state)
    # (3) the compatibility marker, after the commit and never an authority
    write_marker(os.path.join(run_dir, "finalized"), str(exit_code))
    return state


def write_marker(path, text) -> None:
    """Write the compatibility marker, best effort, after a committed verdict."""
    try:
        write_text_atomic(path, text)
    except OSError as exc:
        warn(
            f"the terminal record is committed but its compatibility marker {path} could not "
            f"be written ({exc}); the record in state.json is the authority"
        )


def marker_text(path) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def commit_terminal(op: Operation, state, exit_code, *, recovered=False, note=None, extra=None,
                    stop_proven=False) -> dict:
    """Guard, check the stop evidence, and publish — with M held by the caller.

    Returns the state as it now stands. A refused commit writes nothing at all:
    not an answer, not an exit code, not a session sidecar, not the state, not
    the marker.
    """
    verdict, fresh, detail = guard_locked(op)
    if verdict == GUARD_TERMINAL:
        return fresh
    if verdict != GUARD_OK:
        warn(guard_refusal(op, verdict, detail))
        return fresh
    blocked = survivors_blocking_commit(fresh, op.run_dir, stop_proven=stop_proven)
    if blocked:
        warn(
            f"not committing a terminal verdict for {op.run_dir}: {blocked}; a stop that is "
            "not proven complete cannot end a run"
        )
        return fresh
    return _publish_terminal_locked(op, fresh, exit_code, recovered, note, extra)


def finalize(run_dir, exit_code, *, expect_generation, recovered=False, note=None, extra=None,
             claim_wait=0.0, stop_proven=False) -> dict:
    """Commit one terminal record for one run generation.

    `expect_generation` is mandatory and is the whole binding: the caller passes
    the generation it decided about, the guard re-reads it under M immediately
    before any write, and when the path now holds a different run (a stale reader
    after a replacement, a starter that rebuilt the directory) nothing is written
    and nothing is reported as settled. `claim_wait` is how long to wait for M: the
    runner passes a positive value because its own finalization must land, a
    reader passes 0 and reports whatever the run records when another lifecycle
    operation is already in progress. An already committed verdict is returned
    as-is — a commit is never rewritten. `stop_proven` is the caller's fresh
    evidence that the stop completed (see `survivors_blocking_commit`).
    """
    run_dir = os.path.abspath(str(run_dir))
    op = operation_of(run_dir, generation=str(expect_generation or ""))
    with mutex_of(op, claim_wait) as held:
        if not held:
            warn(guard_refusal(op, GUARD_BUSY, ""))
            return read_state_file(run_dir)
        return commit_terminal(op, read_state_file(run_dir), exit_code, recovered=recovered,
                               note=note, extra=extra, stop_proven=stop_proven)


def repair_marker_locked(op: Operation, state=None) -> bool:
    """Write the compatibility marker for an already committed record, M held.

    This is the only repair a committed run needs: the authority is in
    `state.json`, and a crash between the commit and the marker leaves a settled
    run whose marker is missing. Nothing else is written — the committed bytes
    stay exactly as they are.
    """
    record = terminal_snapshot_locked(read_state_file(op.run_dir) if state is None else state)
    if record is None:
        return False
    marker = os.path.join(op.run_dir, "finalized")
    if marker_text(marker) == str(record.get("exit")):
        return False
    write_marker(marker, str(record.get("exit")))
    return True


def _effective_state_locked(op: Operation):
    """(state, recovered): settle a run whose own finalizer did not get that far.

    Called with M held (see `effective_state`). A valid terminal commit is
    returned without rewriting anything except a missing compatibility marker. A
    state that looks terminal without a valid commit is **uncommitted data**: the
    adapter does not trust its stored exit code and does not manufacture a
    verdict — it reports what is there and writes nothing. A run still `running`
    with nothing alive is a crash and settles as `failed`/`-1` with
    `stale_recovered`.

    A run whose stop was requested is never settled as a crash: once every
    recorded process is conclusively gone it settles as `killed`/`143` (the stop
    did happen), and while the enumeration is incomplete it stays non-terminal —
    "the survivors could not be enumerated" is not evidence that there are none.
    A record with no generation authorizes nothing at all.
    """
    run_dir = op.run_dir
    state = read_state_file(run_dir)
    record = terminal_snapshot_locked(state)
    if record is not None:
        marker = os.path.join(run_dir, "finalized")
        if marker_text(marker) != str(record.get("exit")):
            return state, repair_marker_locked(op, state)
        return state, False
    if not is_this_route(state):
        # Another adapter's run, or a directory whose state names no backend:
        # shown as it records itself, never recovered and never rewritten.
        return state, False
    recorded = state.get("state")
    if recorded not in ("running", "done", "killed", "failed"):
        return state, False
    if not op.generation:
        # A legacy record: readable, but it cannot authorize a mutation and the
        # adapter will not invent a generation to manufacture one.
        return state, False
    if run_alive(run_dir, state) or is_starting(run_dir, state):
        return state, False
    if state.get("stopping"):
        if stop_unconfirmed(state) and stop_survivors(run_dir, state) != []:
            return state, False
        settled = commit_terminal(
            op,
            state,
            KILL_EXIT,
            note=(
                "stop completed: every process the failed stop recorded is gone; finalized "
                "from the stop request"
            ),
            extra={"stopped_by": state.get("stopped_by") or "stop-completed"},
            stop_proven=True,
        )
        return settled, terminal_snapshot_locked(settled) is not None
    if recorded == "running":
        recovered = commit_terminal(op, state, -1, recovered=True)
        return recovered, terminal_snapshot_locked(recovered) is not None
    return state, False


def effective_state(run_dir):
    """Acquire M and settle a run whose own finalizer did not get that far.

    A reader that cannot take M writes nothing and reports the run as it is on
    disk — never a finalization it did not perform.
    """
    op = operation_of(run_dir)
    with mutex_of(op) as held:
        if not held:
            return read_state_file(run_dir), False
        return _effective_state_locked(op)


def reported_state(state) -> dict:
    return state if state.get("state") else {**state, "state": "unknown"}


def lifecycle_of(run_dir, state) -> str:
    """The one lifecycle word every reader reports, out of the shared vocabulary.

    `terminal` needs a *validated terminal commit* — a state word is not proof of
    anything, and neither is the compatibility marker, which is written after the
    commit. `live` needs a recorded process that is still that process (or a run
    still inside its startup grace). The two `stopping` answers keep "survivors
    known" apart from "the enumeration failed", so a failed stop can never be
    read as a finished one; `unknown (no state)` is the honest answer for a
    directory that never recorded a state, and `read-only` is another backend's
    run, which this route reports but never judges. A state that looks terminal
    without a valid commit is uncommitted data and is reported as unfinished.
    """
    state = state or {}
    if not state.get("state"):
        return LIFECYCLE_UNKNOWN
    if not is_this_route(state):
        return LIFECYCLE_FOREIGN
    if terminal_snapshot_locked(state) is not None:
        return LIFECYCLE_TERMINAL
    if state.get("stopping"):
        if stop_unconfirmed(state):
            return LIFECYCLE_STOPPING_UNKNOWN
        return LIFECYCLE_STOPPING_KNOWN
    if run_alive(run_dir, state) or is_starting(run_dir, state):
        return LIFECYCLE_LIVE
    return LIFECYCLE_GONE


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
        # The lifecycle word every reader shares: `stopping (enumeration failed)`
        # is not `running`, and neither is `terminal`.
        "lifecycle": lifecycle_of(run_dir, state),
        # Never claim this route for a run whose state does not record it: the
        # view of another adapter's run says what that run records, or `unknown`.
        "backend": route_of(state) or "unknown",
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


def target_expectation(run_dir):
    """What the target path holds right now: (kind, generation-or-route).

    Kinds: `absent` (nothing there), `empty` (a directory with no run markers),
    `this-route` (a recorded run of this route, with its generation), `other`
    (another backend's run, with that backend) and `unproven` (run markers but no
    readable state, so the route cannot be established). `start` captures this
    under M and re-checks it under M immediately before it initializes anything: a
    path that changed in between is refused, never written.
    """
    if not os.path.isdir(run_dir):
        return ("absent", "")
    state = read_state_file(run_dir)
    if not state or not state.get("state"):
        markers = ("state.json", "lock", "prompt.md")
        if not any(os.path.exists(os.path.join(run_dir, marker)) for marker in markers):
            return ("empty", "")
        return ("unproven", "")
    if not is_this_route(state):
        return ("other", route_of(state))
    return ("this-route", strict_generation(state))


def describe_expectation(expectation) -> str:
    kind, detail = expectation
    if kind == "absent":
        return "nothing"
    if kind == "empty":
        return "no recorded run"
    if kind == "this-route":
        return f"this route's generation {detail or 'unknown'}"
    if kind == "other":
        return f"backend {detail or 'unknown'}"
    return "a directory whose route cannot be established"


def move_aside(run_dir) -> str:
    """Keep the previous run of a slug instead of deleting it.

    Only a directory that is provably this route's — it records `backend: dsh` —
    or one that holds no run markers at all is moved aside. A directory whose
    ownership cannot be established is not permission to move it: doing so would
    mix two routes' artifacts under one slug, and the foreign run's own readers
    would follow it into the archive.
    """
    kind, detail = target_expectation(run_dir)
    if kind in ("other", "unproven"):
        warn(
            f"not moving {run_dir} aside: it holds {describe_expectation((kind, detail))}, "
            "which is not provably this route's"
        )
        return ""
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


def start_run(args, run_dir, agent, replace, profile, mode, policy, claim_held=False) -> int:
    """Initialize and dispatch a fresh run, for `start` or a completed replay.

    The stable slug claim is taken here for `start`; an internal caller that
    already holds it (the `_run` replay path) passes `claim_held=True`, because
    the claim is the one thing that makes "one agent per run" atomic for every
    entry point that can start one.
    """
    slug = sanitize(args.name)
    if not slug:
        die(
            "start: --name is required (and must not sanitize to nothing; '.' and '..' are "
            "path components, not run names)"
        )
    # Before anything is claimed or written: the directory this run would own has
    # to be a date bucket's direct child. `--name ..` (and a slug directory that
    # resolves elsewhere through a symlink) is refused here, never sanitized into
    # a run that writes its artifacts into the run root or another directory.
    try:
        run_dir = checked_run_dir(run_dir)
    except ValueError as exc:
        die(f"start: {exc}")
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
    if claim_held:
        return _start_run_claimed(
            args, run_dir, agent, agent_argv, replace, slug, cwd, prompt_bytes, session_id,
            max_time, profile, mode, policy,
        )
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
    """Capture, re-check and initialize, each step under the lifecycle mutex.

    Three phases, with M released in between so the waits (`stop_run`, the bounded
    settle wait for a committed stop in `await_settled_stop`, the handshake in
    `wait_for_start`) hold no lock:

    1. under M: discover any occupant of the slug and capture what the target path
       holds — an explicit expectation, generation included;
    2. `--replace` only: stop the captured occupant generation, through the same
       generation-bound protocol `kill` uses, then wait — bounded, and holding no
       lock — until the stopped tree is conclusively settled (no recorded process
       alive and nothing left to enumerate), because the verdict's commit and the
       tree's disappearance are two events (see `await_settled_stop`);
    3. under M: re-check the target expectation and the occupant's termination,
       then move the old run aside and initialize the new generation, still under
       M, and spawn the runner.

    Any check that does not hold refuses with no move, no spawn and no write into
    the run directory.
    """
    root = bucket_root(run_dir)

    with lifecycle_claim(root, slug, MUTEX_WAIT_SECONDS) as held:
        if not held:
            die(
                f"start: run '{slug}' has a lifecycle operation in progress or its mutex is "
                f"unavailable (see {lifecycle_lock_path(root, slug)})"
            )
        occupant, occupant_state = _occupying_run_locked(root, slug)
        expected = target_expectation(run_dir)

    if occupant:
        if not replace:
            pids = "/".join(str(pid) for pid in recorded_pids(occupant, occupant_state)) or "-"
            die(f"start: run '{slug}' is still running (pid {pids}; use --replace to restart)")
        if not is_this_route(occupant_state):
            # Another adapter's run may own this slug; this route neither stops it
            # nor replaces it, whatever `--replace` asks for.
            die(
                f"start: run '{slug}' in {occupant} belongs to backend "
                f"{route_of(occupant_state) or 'unknown'}, not this route; refusing to stop or "
                "replace another adapter's run"
            )
        occupant_op = operation_of(occupant, occupant_state)
        if not stop_run(occupant_op, occupant_state):
            die(f"start: could not stop run '{slug}' (see {occupant})")
        # The verdict is committed; the tree it describes may still be visibly
        # present for a moment (the runner that wrote it is exiting, and an
        # enumeration can answer "unknown" while it does). Wait that moment out —
        # bounded, holding no lock — before the under-M re-check decides, so the
        # first momentarily-unproven sample is never read as an unresolved stop.
        # The refusal below is unchanged: it stands whenever the evidence is still
        # unproven at the bound.
        await_settled_stop(occupant, strict_generation(occupant_state))

    with lifecycle_claim(root, slug, MUTEX_WAIT_SECONDS) as held:
        if not held:
            die(f"start: run '{slug}' has a lifecycle operation in progress; nothing was written")
        current = target_expectation(run_dir)
        if current != expected:
            die(
                f"start: {run_dir} changed while run '{slug}' was being prepared "
                f"({describe_expectation(expected)} → {describe_expectation(current)}); "
                "nothing was written"
            )
        if current[0] in ("other", "unproven"):
            die(
                f"start: {run_dir} holds {describe_expectation(current)}, not provably this "
                "route's; refusing to move or writes into it"
            )
        if occupant:
            # A successful stop of one generation is not permission to replace
            # whatever occupies the path now: recheck the captured generation's
            # committed verdict and that no owned work is still unproven.
            stopped_state, _ = _effective_state_locked(operation_of(occupant))
            if strict_generation(stopped_state) != strict_generation(occupant_state):
                die(
                    f"start: run '{slug}' in {occupant} is no longer the generation that was "
                    "stopped; nothing was written"
                )
            if terminal_snapshot_locked(stopped_state) is None:
                die(
                    f"start: run '{slug}' in {occupant} has no committed terminal verdict after "
                    "the stop; refusing to replace it (stop it again, or stop it by hand)"
                )
            if run_alive(occupant, stopped_state) or stop_survivors(occupant, stopped_state) != []:
                die(
                    f"start: run '{slug}' in {occupant} still has unproven processes; refusing "
                    "to replace it while a stop is unresolved"
                )
        if os.path.isdir(run_dir):
            if not move_aside(run_dir):
                # Refuse rather than mix two runs in one directory: the previous
                # run's committed verdict would make the new one look finished.
                die(f"start: cannot move {run_dir} aside for the new run")

        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "prompt.md"), "wb") as handle:
            handle.write(prompt_bytes)

        state = {
            "name": slug,
            "state": "running",
            "exit": None,
            "cwd": cwd,
            "started": now_iso(),
            # This run generation: the token every mutation is bound to, so a
            # reader that decided about the previous run at this path can never
            # finalize, signal or write into this one (see `guard_locked`).
            "generation": new_nonce(),
            "ended": None,
            "duration_s": None,
            "model": None,
            "thinking": None,
            "max_time": max_time,
            "backend": BACKEND,
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
        # everything here belongs to `start`. The lock carries the generation, so
        # a signalling path can require the process metadata to be this run's.
        write_json(
            os.path.join(run_dir, "lock"),
            {
                "pid": None,
                "agent_pid": None,
                "backend": BACKEND,
                "generation": state["generation"],
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
        # The single-use handshake with the runner this call spawns: the file
        # names the generation and a token, the credential travels only in the
        # runner's own environment, and the runner consumes both. A replay of the
        # recorded run.sh carries neither, so it takes the slug claim like any
        # other starter (see `runner_main`).
        write_json(
            os.path.join(run_dir, SPAWN_TOKEN_FILE),
            {"generation": state["generation"], "token": new_nonce()},
        )
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
    print(f"  backend   : {BACKEND}")
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
        if terminal_snapshot_locked(state) is not None:
            return reported_state(state), False
        if time.monotonic() >= deadline:
            return reported_state(state), False
        time.sleep(POLL_SECONDS)


# -- list, status, result, answer, tail, kill --------------------------------


def state_word(run_dir, state, recovered) -> str:
    """The one word `list` prints: the lifecycle, never a hopeful abbreviation.

    Each of the five answers is spelled differently — `terminal` by its state
    name, `running(live)`, `stopping(survivors-known)`,
    `stopping(enumeration-failed)`, `unknown(no-state)` — so a stop that failed
    can never be read as a finished run from a `list` line alone.
    """
    if not state.get("state"):
        return "unknown(no-state)"
    if not is_this_route(state):
        # Another adapter's run (or one that names another backend): listed as it
        # records itself, and never recovered or rewritten by this route.
        return f"read-only({route_of(state) or 'unknown'})"
    session = state.get("session_id") or "?"
    if recovered and state.get("stale_recovered"):
        # Just finalized by the crash-recovery path: report the crash and the
        # resume hint, not the bookkeeping that was written. Every other
        # recovery lands on a lifecycle word below (a completed stop is
        # `killed`, not "gone").
        return f"GONE (resume with --session-id {session})"
    lifecycle = lifecycle_of(run_dir, state)
    if lifecycle == LIFECYCLE_STOPPING_KNOWN:
        return "stopping(survivors-known)"
    if lifecycle == LIFECYCLE_STOPPING_UNKNOWN:
        return "stopping(enumeration-failed)"
    if lifecycle == LIFECYCLE_TERMINAL:
        if state.get("stale_recovered") and state.get("state") == "failed":
            return "failed(stale)"
        return str(state.get("state"))
    if lifecycle == LIFECYCLE_LIVE:
        return f"{state.get('state')}(live)"
    if lifecycle == LIFECYCLE_FOREIGN:
        return f"read-only({route_of(state) or 'unknown'})"
    return f"GONE (resume with --session-id {session})"


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
    if recovered and state.get("stale_recovered"):
        print("stale_recovered: true")
    return 0


def cmd_result(args) -> int:
    run_dir = require_run("result", args.name)
    state, recovered = effective_state(run_dir)
    # `result` names the lifecycle too: a caller must never have to infer
    # "finished" from a state word while a stop is unresolved.
    view = {
        **reported_state(state),
        "lifecycle": lifecycle_of(run_dir, state),
        "alive": run_alive(run_dir, state),
    }
    print(json.dumps(view, indent=2, ensure_ascii=False))
    if recovered and state.get("stale_recovered"):
        print("stale_recovered: true")
    record = terminal_snapshot_locked(state)
    if record is not None:
        # The committed record is the authority: the answer it carries, not an
        # independently reopened sidecar.
        print("\n--- answer (first 1500 chars) ---")
        print(str(record.get("answer") or "")[:1500])
        return 0
    if not is_this_route(state):
        # Another route's run: this adapter never judges it and never rewrites it,
        # so its sidecar is passed through exactly as that route left it.
        print("\n--- answer (first 1500 chars) ---")
        print(answer_sidecar(run_dir)[:1500])
    return 0


def answer_sidecar(run_dir) -> str:
    """The `answer.md` of a run as it is on disk, read-only (foreign runs only)."""
    path = os.path.join(run_dir, "answer.md")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def cmd_answer(args) -> int:
    run_dir = require_run("answer", args.name)
    state, _recovered = effective_state(run_dir)
    record = terminal_snapshot_locked(state)
    if record is not None:
        sys.stdout.write(str(record.get("answer") or ""))
        return 0
    if not is_this_route(state) and os.path.exists(os.path.join(run_dir, "answer.md")):
        # Another route's run, read-only: its file is shown as that route left it.
        sys.stdout.write(answer_sidecar(run_dir))
        return 0
    # Before the commit an `answer.md` may physically exist as a prepared
    # compatibility artifact; it is not a result, so this refuses — and the
    # refusal names the lifecycle, because "not finished" is a different answer
    # for a live run, a failed stop and a directory that never had a state.
    die(
        f"answer: not finished yet ({lifecycle_of(run_dir, state)}; "
        f"state {state.get('state') or 'unknown'})"
    )


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


def stop_run(op: Operation, state=None, seconds=STOP_WAIT_SECONDS) -> bool:
    """Ask the run to stop, then force it: True once a verdict is committed.

    The request is written under M and names this operation's generation, so a
    stop issued against one generation can never land in the run that replaced
    it. The wait for the run's own finalizer holds no lock, and is a wait for a
    *validated terminal snapshot*: a generation change is reported as such, not as
    a timeout.

    A run whose runner is gone cannot execute its own finalizer, so the forced
    path commits the stop itself — as `killed`, exit 143, because that is what
    happened. Recording it as a stale crash (failed, exit -1) would contradict
    both the operator's request and the contract in references/transport.md. A
    stop that is *not* proven complete never finalizes: the run is left (or put)
    in the `stopping` state with what is known, and the caller reports failure.
    """
    if terminal_snapshot_locked(read_state_file(op.run_dir)) is not None:
        return True
    if state is None:
        state = read_state_file(op.run_dir)
    if not request_stop(op):
        return False
    waited = wait_for_terminal(op, seconds)
    if waited == WAIT_TERMINAL:
        return True
    if waited == WAIT_GENERATION_CHANGED:
        warn(
            f"not waiting for {op.run_dir}: it now holds a different generation than the one "
            "this stop was issued for"
        )
        return False
    forced = False
    if run_alive(op.run_dir, state):
        forced = kill_tree(op, state)
        if forced and wait_for_terminal(op, 2.0) == WAIT_TERMINAL:
            # The run's own finalizer observed the force and committed its verdict.
            return True
    state = read_state_file(op.run_dir)
    survivors = stop_survivors(op.run_dir, state)
    if forced or survivors == []:
        # A verified process-instance stop proved every recorded process gone, or
        # a complete enumeration found nobody alive: the stop did happen, so it is
        # recorded as `killed`/143 rather than left for the crash-recovery path.
        finalize(
            op.run_dir,
            KILL_EXIT,
            note=(
                "stopped on request: the run's own finalizer did not complete after the stop "
                "request, so the stop was recorded here"
            ),
            extra={"stopped_by": "control-file-forced"},
            expect_generation=op.generation,
            stop_proven=True,
        )
        return terminal_snapshot_locked(read_state_file(op.run_dir)) is not None
    # The tree survived, or nothing could be proven gone: leave the run to the
    # recovery path rather than claiming a stop that did not happen.
    report_incomplete_stop(op, survivors, "control-file-forced")
    return False


def cmd_kill(args) -> int:
    run_dir = require_run("kill", args.name)
    state, _ = effective_state(run_dir)
    if not is_this_route(state):
        die(
            f"kill: run '{args.name}' is not this route's (backend "
            f"{route_of(state) or 'unknown'}); refusing to signal another adapter's run"
        )
    if terminal_snapshot_locked(state) is not None:
        die(f"kill: run '{args.name}' is already finished (state {state.get('state')})")
    if (
        not run_alive(run_dir, state)
        and not is_starting(run_dir, state)
        and not state.get("stopping")
    ):
        die(f"kill: no live process recorded for '{args.name}' (state {state.get('state')})")
    op = operation_of(run_dir, state)
    if not op.generation:
        die(
            f"kill: cannot confirm the run generation of '{args.name}' (its record names none, "
            "and a legacy run is not an authorization token); no stop request was written"
        )
    pids = "/".join(str(pid) for pid in recorded_pids(run_dir, state)) or "-"
    stop_run(op, state, seconds=stop_wait_seconds())
    final = reported_state(read_state_file(run_dir))
    if terminal_snapshot_locked(final) is None:
        die(
            f"kill: cannot confirm the stop of '{args.name}' ({lifecycle_of(run_dir, final)}); "
            f"no terminal verdict is committed and nothing further will be signalled — "
            f"see {run_dir}"
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


def make_tracker(op: Operation, state) -> tuple:
    """A per-line hook that keeps session.id and the live counters current.

    dsh's opening `session` event carries `sessionId` (not the `id` the shared
    writer looks for), so the runner persists session.id itself; the counters let
    `status` describe a live run without re-reading the retained log.

    Returns `(track, stop)`. Publication happens inside M for the generation this
    tracker was created for, after the guard accepted it: the state is re-read and
    the tracker's fields merged into it, never a whole `running` snapshot
    republished over a concurrent `stopping` update, and a committed verdict or a
    replaced generation ends publication for good. M is also the stop barrier —
    `stop()` marks publication finished and then takes M, so once it returns no
    write this tracker started can still land, without a second mutex of its own.
    """
    seen = {"session_id": state.get("session_id") or "", "turns": 0, "tool_calls": 0}
    last = {"at": 0.0}
    stopped = threading.Event()

    def publish_locked(session_id=None):
        verdict, current, _detail = guard_locked(op)
        if verdict != GUARD_OK:
            # A committed verdict (or a replaced generation, or a foreign route):
            # nothing this tracker has to say may be published any more.
            stopped.set()
            return False
        fields = {
            "session_id": seen["session_id"],
            "turns": seen["turns"],
            "tool_calls": seen["tool_calls"],
        }
        if session_id is not None:
            write_text_atomic(os.path.join(op.run_dir, "session.id"), session_id + "\n")
        merge_state_locked(op, fields, current)
        return True

    def publish(force=False):
        now = time.monotonic()
        if not force and now - last["at"] < STATE_REFRESH_SECONDS:
            return
        with mutex_of(op, wait=None) as held:
            if not held or stopped.is_set():
                return
            last["at"] = now
            publish_locked()

    def track(raw):
        try:
            event = json.loads(raw.decode("utf-8", "replace").strip())
        except (ValueError, UnicodeDecodeError, AttributeError):
            return
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        changed = False
        session_id = None
        if kind == "session":
            found = event.get("sessionId")
            if isinstance(found, str) and found and found != seen["session_id"]:
                seen["session_id"] = found
                session_id = found
                changed = True
        elif kind == "status" and event.get("phase") == "turn_end":
            seen["turns"] += 1
            changed = True
        elif kind == "tool_call":
            seen["tool_calls"] += 1
            changed = True
        if not changed:
            return
        if kind == "session":
            with mutex_of(op, wait=None) as held:
                if not held or stopped.is_set():
                    return
                publish_locked(session_id=session_id)
            return
        publish()

    def stop():
        stopped.set()
        # The publication barrier: any write in flight holds M, so taking it here
        # means it has finished before this returns.
        with mutex_of(op, wait=None):
            pass

    return track, stop


def wait_for_agent(process, op, generation, requested: threading.Event, deadline,
                   agent_identity="") -> tuple:
    """Wait for dsh, honouring its own generation's stop request, a signal, a deadline.

    Returns (exit code, survivors, stopped_by): the second is the stop's outcome
    (`terminate_agent`): `[]` when the stop is proven complete, a list naming each
    survivor as (pid, identity, group) when it is not, `None` when it is not and
    the survivors could not be enumerated. The third names what ended the run
    ("control-file", "signal", "deadline") or "" when dsh ended by itself.

    The control-file branch is generation-bound: a request is read under M and is
    actionable only when its generation equals this runner's captured generation
    *and* the generation the current state records. A different generation's
    request is not this runner's to act on — and is never deleted, because it
    belongs to whoever wrote it. A signal delivered to this runner's own handler
    belongs to this runner instance; every publication it leads to is still bound
    to the captured generation. `agent_identity` is the token read when dsh was
    spawned; it gates every signal so a reused pid is never signalled.
    """
    while True:
        exit_code = process.poll()
        if exit_code is not None:
            return exit_code, [], ""
        requested_stop = False
        with mutex_of(op, wait=None) as held:
            if held:
                requested_stop = bool(stop_request_for(op.run_dir, generation))
        if requested.is_set() or requested_stop:
            reason = "control-file" if requested_stop else "signal"
            code, survivors = terminate_agent(process, op, agent_identity)
            return code, survivors, reason
        if deadline is not None and time.monotonic() >= deadline:
            code, survivors = terminate_agent(process, op, agent_identity)
            return code, survivors, "deadline"
        time.sleep(POLL_SECONDS)


def stop_note(records, complete) -> str:
    """The human sentence for a stop that did not complete."""
    if complete:
        named = ", ".join(str(record["pid"]) for record in records) or "none recorded"
        return (
            f"stop incomplete: {named} still alive after TERM and KILL; the run is not "
            "finalized and a later `kill` can still stop it"
        )
    known = ", ".join(str(record["pid"]) for record in records)
    suffix = f"; known survivors: {known}" if known else ""
    return (
        "stop incomplete: the survivors could not be enumerated (Windows, or an inspection "
        f"command failed){suffix}; the run is not finalized, stays stopping, and a later "
        "`kill` can still stop it"
    )


def report_incomplete_stop(op: Operation, survivors, stopped_by="") -> int:
    """Publish a stop that failed: the run stays live/stopping, never finalized.

    A committed `killed` verdict with processes still alive tells every reader the
    slot is free — `kill` refuses to touch it and `start` no longer sees the slug
    as occupied — while the survivors keep writing to the worktree. This is the
    opposite record: the run stays `running` with `stopping: true`, and the
    survivors are named (pid, identity, group) in `state.json` and `lock`, so
    `run_alive` still finds them, the slug stays occupied, and a later `kill`
    signals their group through a verified member and settles the run.

    The report is generation-bound and guarded under M: a generation that changed,
    a foreign run, or an already committed verdict makes it write neither the
    state nor the lock — a late report from an old operation may not revive a run
    that has since been replaced or settled. `survivors` is `terminate_agent`'s
    second outcome: a list of what was still alive, or `None` when the enumeration
    itself failed (recorded as `survivors_complete: false`, which no reader may
    read as "nobody is alive"). Survivors named by an earlier failed stop are kept,
    so a later attempt still has their identities to verify.
    """
    with mutex_of(op, MUTEX_WAIT_SECONDS) as held:
        if not held:
            warn(guard_refusal(op, GUARD_BUSY, ""))
            return 1
        verdict, state, detail = guard_locked(op)
        if verdict == GUARD_TERMINAL:
            warn(
                f"not reporting an incomplete stop for {op.run_dir}: a terminal verdict is "
                "already committed"
            )
            return 1
        if verdict != GUARD_OK:
            warn(guard_refusal(op, verdict, detail))
            return 1
        merged = {
            pid: {"pid": pid, "identity": identity, "group": group}
            for pid, identity, group in recorded_survivors(op.run_dir, state)
        }
        for pid, identity, group in survivors or []:
            merged[pid] = {"pid": pid, "identity": identity, "group": group}
        if survivors is None:
            # Even a failed enumeration knows which recorded processes are still
            # alive, and their group ids: record them, so a later attempt has real
            # identities to verify instead of starting from nothing.
            for pid, identity in recorded_processes(op.run_dir, state):
                if liveness_of(pid) == GONE or identity_changed(pid, identity) or pid in merged:
                    continue
                group = process_group(pid)
                merged[pid] = {
                    "pid": pid,
                    "identity": identity,
                    "group": group if group > 0 else 0,
                }
        records = list(merged.values())
        complete = survivors is not None
        fields = {
            "state": "running",
            "stopping": True,
            "survivors": records,
            "survivors_complete": complete,
            "note": stop_note(records, complete),
        }
        if stopped_by:
            fields["stopped_by"] = stopped_by
        state = merge_state_locked(op, fields, state)
        merge_lock_locked(op, survivors=records)
    listed = ",".join(str(record["pid"]) for record in records) if complete else "unknown"
    print(
        f"[stop-incomplete] {state.get('name')} state=running survivors={listed}",
        flush=True,
    )
    warn(
        f"run in {op.run_dir} still has live processes after the stop; left running/stopping, "
        "not finalized"
    )
    return 1


def consume_spawn_credential_locked(op: Operation) -> str:
    """Consume the single-use handshake for this run, with M held.

    The credential in the environment carries both the generation and the token;
    the handshake file carries the same pair. Both halves must match *and* the
    generation must be the one the run records, or nothing is consumed and the
    caller is not the runner `start` spawned. On success the file and the
    environment variable are consumed together, so a hand replay of the recorded
    `run.sh`/`run.cmd` — which carries no credential — cannot present it, and a
    credential minted for another generation cannot adopt this run. Returns the
    generation the credential proves, or "".
    """
    raw = os.environ.get(RUNNER_TOKEN_ENV) or ""
    if ":" not in raw:
        return ""
    generation, token = raw.split(":", 1)
    recorded_generation, recorded_token = spawn_credentials(op)
    if not generation or not token or not recorded_token:
        return ""
    if generation != recorded_generation or token != recorded_token:
        warn(
            f"refusing to run {op.run_dir}: the spawn credential does not match the handshake "
            "recorded for this run"
        )
        return ""
    if strict_generation(read_state_file(op.run_dir)) != generation:
        warn(
            f"refusing to run {op.run_dir}: the spawn credential names generation {generation}, "
            "which is not the generation the run records"
        )
        return ""
    remove_quietly(os.path.join(op.run_dir, SPAWN_TOKEN_FILE))
    os.environ.pop(RUNNER_TOKEN_ENV, None)
    return generation


def runner_main(args) -> int:
    """Run one dsh task in the foreground of the detached process `start` spawned.

    Two entries reach this function, and only one of them already has an owner:
    the runner `start` spawned while holding the slug claim (proved by the
    generation-stamped, single-use credential it alone was given), and a replay of
    a recorded `run.sh`/`run.cmd` — of a finished run, or a takeover of a run that
    died unfinished. The replay must take the stable slug claim itself, so two
    replays, or a replay racing a `start`, still produce exactly one agent; the
    loser writes nothing and says why. The claim is
    `<run root>/<slug>.start.lock`, a sibling of every date bucket, so replacing
    the run directory does not move it. The authenticated branch takes no claim:
    its parent holds it until this process has recorded that it owns the run.
    """
    run_dir = os.path.abspath(str(args.run_dir))
    if os.environ.get(RUNNER_TOKEN_ENV):
        return _runner_main(args, run_dir, claim_held=False, release_claim=None)
    slug = sanitize(args.name) or sanitize(os.path.basename(run_dir))
    if not slug:
        warn(f"refusing to run {run_dir}: no run name is recorded for it")
        return 1
    root = bucket_root(run_dir)
    with ExitStack() as stack:
        if not stack.enter_context(slug_start_claim(root, slug)):
            warn(
                f"refusing to run {run_dir}: another start owns '{slug}' "
                f"(see {os.path.join(root, slug + '.start.lock')}); one run, one agent"
            )
            return 1
        return _runner_main(args, run_dir, claim_held=True, release_claim=stack.close)


def _runner_main(args, run_dir, claim_held, release_claim) -> int:
    """One dsh task, with the slug claim's state made explicit.

    `claim_held` is True only when this process holds the slug claim itself, and
    therefore may run the fresh-start path (`start_run`) that assumes the claim is
    held. The runner `start` spawned does not hold it (its parent does), and a
    finished run appearing here is a refusal, never a replay.

    All of the ownership work happens in one M scope — credential consumption,
    generation revalidation, the liveness refusal, agent spawn and the recording
    of the runner's and the agent's pid/identity — and M is released before any
    wait. `release_claim` gives the claim up as soon as this process has recorded
    that it owns the run: after that every other entry sees a live run and
    refuses, and holding the claim for the agent's whole life would block
    `start --replace`.
    """
    state = read_state_file(run_dir)
    if terminal_snapshot_locked(state) is not None:
        if not claim_held:
            warn(
                f"refusing to run {run_dir}: the run is finished and this invocation does not "
                "hold its slug claim; replay it through the recorded script so the claim is taken"
            )
            return 1
        # A replay initializes a fresh generation before touching any finished
        # artifact, and keeps the recorded command's paths and agent rather than
        # the caller's current defaults.
        return start_run(
            args, run_dir, args.agent, False, args.profile, args.permission_mode,
            args.approval_policy, claim_held=True,
        )
    if claim_held and state.get("state") in ("done", "killed", "failed"):
        warn(
            f"refusing to run {run_dir}: its state records {state.get('state')} without a "
            "committed terminal record (uncommitted data); clear the directory or record a "
            "verdict before replaying"
        )
        return 1
    generation = strict_generation(state)
    op = operation_of(run_dir, state, generation)
    log = None
    process = None
    agent_identity = ""
    argv = []
    outcome = None
    with mutex_of(op, MUTEX_WAIT_SECONDS) as held:
        if not held:
            warn(guard_refusal(op, GUARD_BUSY, ""))
            return 1
        if not claim_held and not consume_spawn_credential_locked(op):
            warn(
                f"refusing to run {run_dir}: this invocation holds no valid spawn credential "
                "for the run generation it would take over"
            )
            return 1
        verdict, fresh, detail = guard_locked(op)
        if verdict != GUARD_OK:
            warn(guard_refusal(op, verdict, detail))
            return 1
        if run_alive(run_dir, fresh):
            # A hand replay of `run.sh`/`run.cmd` arrives here too, and `start`'s
            # ownership of a live slug must hold for this entry as well: replaying
            # a run that is still live would overwrite its runner pid, reopen its
            # artifacts and start a second agent on the same cwd.
            pids = "/".join(str(pid) for pid in recorded_pids(run_dir, fresh)) or "-"
            warn(
                f"refusing to run {run_dir}: this run is still live (pids {pids}); stop it "
                "with `kill` before replaying, so two agents never share one cwd"
            )
            return 1
        if (args.approval_policy or DEFAULT_APPROVAL_POLICY) != DEFAULT_APPROVAL_POLICY:
            # A replay of an older run may carry a policy this route can no longer
            # honour. Refuse it where the run's own finalizer can record why.
            note = (
                f"refused approval policy {args.approval_policy!r}: a detached run has no live "
                f"approval channel, so only {DEFAULT_APPROVAL_POLICY!r} can be honoured"
            )
            commit_terminal(op, fresh, 127, note=note)
            warn(note)
            return 1
        if not os.path.isfile(args.prompt):
            commit_terminal(op, fresh, 127, note=f"prompt missing: {args.prompt}")
            warn(f"prompt missing: {args.prompt}")
            return 1
        try:
            log = EventLog(op)
        except (RuntimeError, OSError, KeyError) as exc:
            commit_terminal(op, fresh, 127, note=f"event writer unavailable: {exc}")
            warn(f"event writer unavailable: {exc}")
            return 1
        session_id = args.session_id or args.resume or ""
        try:
            argv = agent_command(
                args.agent,
                agent_args(session_id, args.profile, args.permission_mode, args.approval_policy),
            )
        except ValueError as exc:
            outcome = (127, f"cannot dispatch the agent: {exc}", {"error": str(exc)})
        else:
            self_identity = process_identity(os.getpid())
            # A stop that arrived before the agent was spawned is honoured here:
            # the run was stopped, so no agent is started for it.
            requested_before_spawn = bool(stop_request_for(run_dir, generation))
            if not requested_before_spawn:
                with open(os.path.join(run_dir, "stderr.log"), "ab") as stderr:
                    try:
                        process = spawn_agent(argv, args.cwd, stderr, args.prompt)
                    except OSError as exc:
                        outcome = (127, f"agent did not start: {exc}", {"error": str(exc)})
                if process is not None:
                    agent_identity = process_identity(process.pid)
            merge_state_locked(
                op,
                {
                    "pid": os.getpid(),
                    "pid_identity": self_identity,
                    "detach": observe_detachment(),
                    "interpreter": interpreter(),
                    "agent_pid": process.pid if process is not None else None,
                    "agent_pid_identity": agent_identity or None,
                    "agent_argv": argv if process is not None else None,
                    "stopped_before_agent_spawn": requested_before_spawn or None,
                },
                fresh,
            )
            merge_lock_locked(
                op,
                pid=os.getpid(),
                pid_identity=self_identity,
                agent_pid=process.pid if process is not None else None,
                agent_pid_identity=agent_identity or None,
            )
    if release_claim is not None:
        # Ownership is recorded (this pid, this identity): the run is live to
        # every other entry now, so the claim has done its job.
        release_claim()
    if outcome is not None:
        if log is not None:
            log.finish()
        finalize(
            run_dir, outcome[0], note=outcome[1], extra=outcome[2],
            expect_generation=generation,
        )
        warn(outcome[1])
        return 1
    if process is None:
        # The stop arrived before the agent was spawned: the run was stopped, and
        # its own finalizer records that rather than reporting a dispatch.
        exit_code, survivors, stopped_by = KILL_EXIT, [], "control-file"
        extra = {}
    else:
        requested = threading.Event()
        install_stop_handler(requested)
        tracker, stop_tracker = make_tracker(op, read_state_file(run_dir))
        reader = threading.Thread(target=drain, args=(process.stdout, log, tracker), daemon=True)
        reader.start()
        deadline = None
        if args.max_time:
            deadline = time.monotonic() + float(args.max_time)
        exit_code, survivors, stopped_by = wait_for_agent(
            process, op, generation, requested, deadline, agent_identity
        )
        extra = {}
        if stopped_by:
            extra["stopped_by"] = stopped_by
        if stopped_by == "deadline":
            extra["deadline_exceeded"] = True
        reader.join(timeout=drain_timeout_seconds())
        # Publication ends before the terminal state is committed. The reader may
        # still be alive (a descendant holds the stream open) and would otherwise
        # publish its `running` state over the verdict after the commit.
        stop_tracker()
        if reader.is_alive():
            # A descendant of dsh still holds the write end of its stdout. Stop
            # waiting and say in state.json that the tail is missing rather than late.
            warn("the event stream was still open at exit; recording the truncation")
            write_state_op(
                op,
                {
                    "stream_incomplete": True,
                    "note": (
                        "finalized while the event stream was still open: a process below dsh "
                        "held its stdout, so the events after this point are missing from the log"
                    ),
                },
            )
            extra["stream_incomplete"] = True
        log.finish()
    if survivors is None or survivors:
        # The stop did not complete — survivors known, or not enumerable at all:
        # publish that, never a terminal state.
        return report_incomplete_stop(op, survivors, stopped_by)

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
    final = finalize(
        run_dir, exit_code, note=note, extra=extra, claim_wait=30.0,
        expect_generation=generation,
    )
    print(
        f"[finalize] {final.get('name')} state={final.get('state')} exit={exit_code} "
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
