#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""agent_run.py — one detached runner for every headless agent CLI gdd dispatches.

    agent_run.py start --name SLUG --prompt FILE [--cwd DIR] [--agent NAME] [--model M]
                       [--thinking L] [--max-time D] [--resume ID] [--schema FILE] [--extra "FLAGS"]
                       [--replace]
    agent_run.py list | status [SLUG] | tail SLUG [N] | result SLUG | answer SLUG | kill SLUG
    agent_run.py _run --run-dir DIR        (internal: the detached runner)

Agent (omp, dsh, codex, claude, pi, opencode): --agent, then GDD_AGENT (env, then the gdd config file), then
omp. Binary: <AGENT>_BIN (e.g. CODEX_BIN), else the agent's name on PATH; a `.py` binary runs
through this interpreter, a Windows `.cmd`/`.bat` shim through %COMSPEC%.

Run dir: <run_root>/<YYYY-MM-DD>/<SLUG>/ = prompt.md, run.json (exact argv), state.json (the
single record), events.ndjson (+ events.1.ndjson after rotation), stderr.log, runner.log,
answer.md, result.json (a valid stage result), exit.code, finalized (marker), stop (kill request). run_root: GDD_RUN_ROOT (env,
then config), else ${XDG_STATE_HOME:-~/.local/state}/gdd/runs.

state: running|done|failed|killed|unknown. done = exit 0 plus the agent's own success marker.
--schema FILE: codex and claude enforce it natively; other agents are asked by the prompt. The
result (native structured output, else the whole answer as JSON, else its last ```json block)
sets state.result valid|invalid|missing and never changes the run's state (a result codex or
claude rejects natively fails their turn, and so the run).
--max-time is enforced here (exit 124, failed). A `running` run with neither pid nor
agent_pid alive, no marker and no stop request is finalized failed/-1, stale_recovered, by
the next reader; a pid-less run younger than GDD_RUN_START_GRACE_SECONDS (60) is starting.
`kill` writes `stop`; the runner ends the agent (POSIX group TERM, 5 s, KILL; Windows
taskkill /T /F) and finalizes killed/143. With the runner gone, `kill` signals a recorded pid
only if its live start time equals the one recorded at spawn, else exits 1 naming the pid.

Detachment: GDD_RUN_DETACH=auto|systemd|session. Linux prefers a transient user unit;
other POSIX hosts use start_new_session. Windows uses a detached process group and
breaks away from the caller's job when allowed.

Knobs: GDD_RUN_EVENTS_MAX_BYTES (8388608), GDD_RUN_START_GRACE_SECONDS (60),
GDD_RUN_STOP_WAIT_SECONDS (20), GDD_RUN_DRAIN_TIMEOUT_SECONDS (30; 5 after a stop).
dsh: DSH_RUN_PROFILE (headless), DSH_PERMISSION_MODE (workspace-write), DSH_APPROVAL_POLICY (only `never`).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import errno
import glob
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gdd_process
import skill_config
import stage_result

IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    import ctypes
    import msvcrt
    from ctypes import wintypes
else:
    import fcntl

KILLED_EXITS = (130, -2, 137, -9, 143, -15)
KILL_EXIT, TIMEOUT_EXIT = 143, 124
WINDOWS_DETACH = gdd_process.NO_WINDOW | gdd_process.NEW_GROUP
POLL, PROGRESS_SECONDS = 0.25, 2.0
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLUG_RE = re.compile(r"[^a-z0-9._-]+")
CMD_UNSAFE = re.compile(r'[\r\n"&|<>^()%!]')
STATES = ("running", "done", "failed", "killed")
_RENAMED = ("EVENTS_MAX_BYTES", "START_GRACE_SECONDS", "STOP_WAIT_SECONDS", "DRAIN_TIMEOUT_SECONDS")
RETIRED = {
    "OMP_RUN_ROOT": "GDD_RUN_ROOT", "DSH_RUN_ROOT": "GDD_RUN_ROOT",
    "OMP_LEDGER": "nothing (no runner ledger; `list` shows every run)",
    "OMP_RUN_BACKEND": "nothing (the tmux backend is gone)", "DSH_RUN_SETTLE_WAIT_SECONDS": "nothing",
    **{f"{p}_RUN_{k}": f"GDD_RUN_{k}" for p in ("OMP", "DSH") for k in _RENAMED},
}


def die(message):
    print(f"agent_run: {message}", file=sys.stderr)
    sys.exit(1)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def knob(name, default):
    try:
        value = float(os.environ.get(name) or "")
    except ValueError:
        return default
    return value if value > 0 else default


def run_root():
    home = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    try:
        root = skill_config.resolve("gdd", "GDD_RUN_ROOT", default=os.path.join(home, "gdd", "runs"))
    except skill_config.ConfigError as exc:
        die(f"GDD_RUN_ROOT: {exc}")
    return os.path.abspath(os.path.expanduser(root))


def detach_config():
    try:
        return skill_config.resolve("gdd", "GDD_RUN_DETACH", default="auto")
    except skill_config.ConfigError as exc:
        raise ValueError(f"GDD_RUN_DETACH: {exc}") from exc


def select_detach(requested):
    if requested not in ("auto", "systemd", "session"):
        raise ValueError(f"GDD_RUN_DETACH={requested!r}: expected auto, systemd or session")
    if requested != "session" and sys.platform == "linux":
        if (launcher := shutil.which("systemd-run")) and (ctl := shutil.which("systemctl")):
            try:
                status = gdd_process.run([ctl, "--user", "is-system-running"], stdin=subprocess.DEVNULL,
                                        capture_output=True, encoding="utf-8", errors="replace", timeout=1)
                if status.stdout.strip() in ("running", "degraded"):
                    return "systemd", launcher
            except (OSError, subprocess.TimeoutExpired):
                pass
    if requested == "systemd":
        raise ValueError("GDD_RUN_DETACH=systemd requires systemd-run and a reachable Linux user manager")
    return ("windows" if IS_WINDOWS else "session"), None


def systemd_argv(launcher, unit, cwd, log, runner):
    return [launcher, "--user", "--collect", "--quiet", "--unit", unit, "--service-type=exec",
            "--no-ask-password", f"--working-directory={cwd.replace('%', '%%')}",
            f"--property=StandardOutput=append:{str(log).replace('%', '%%')}",
            "--property=StandardError=inherit", "--", runner[0],
            *(arg.replace("$", "$$") for arg in runner[1:]), "--restore-env"]


def spawn_detached(runner, run_dir, cwd, env, mode, launcher=None, unit=None):
    log_path = Path(run_dir) / "runner.log"
    if mode == "systemd":
        # A transient unit inherits the manager's environment, not the dispatcher's.
        # Pass the exact environment privately; don't put credentials in argv or unit properties.
        path = Path(run_dir) / ".runner-env"
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(env, stream)
            gdd_process.run(systemd_argv(launcher, unit, cwd, log_path, runner), check=True,
                           stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace")
        except (OSError, subprocess.CalledProcessError) as exc:
            path.unlink(missing_ok=True)
            raise OSError(getattr(exc, "stderr", "").strip() or str(exc)) from exc
        return None, 0
    with log_path.open("ab", buffering=0) as log:
        options = dict(cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env)
        if mode == "windows":
            for creationflags in (WINDOWS_DETACH | gdd_process.BREAKAWAY, WINDOWS_DETACH):
                try:
                    return gdd_process.popen([*runner, "--creationflags", str(creationflags)],
                                            creationflags=creationflags, **options), creationflags
                except OSError as exc:
                    if creationflags == WINDOWS_DETACH or getattr(exc, "winerror", None) != 5:
                        raise
        return gdd_process.popen(runner, start_new_session=True, **options), 0


def restore_detached_env(run_dir):
    path = Path(run_dir) / ".runner-env"
    with path.open(encoding="utf-8") as handle:
        env = json.load(handle)
    path.unlink()
    os.environ.clear()
    os.environ.update(env)


def unit_name(slug):
    return f"gdd-{slug}-{uuid.uuid4().hex[:12]}"


def warn_wsl(binary, run_dir):
    if sys.platform != "linux" or "microsoft" not in os.uname().release.lower():
        return
    if Path(binary).suffix.lower() == ".exe":
        print(f"gdd: warning: WSL is using Windows CLI {binary} through interop; prefer a native Linux CLI",
              file=sys.stderr)
    if run_dir is not None and re.match(r"^/mnt/[a-z](?:/|$)", Path(run_dir).resolve().as_posix(), re.IGNORECASE):
        print(f"gdd: warning: WSL run directory {run_dir} is on a Windows drive; prefer the Linux filesystem",
              file=sys.stderr)


@contextmanager
def slug_start_lock(root, slug):
    Path(root).mkdir(parents=True, exist_ok=True)
    # Keep the lock file: unlinking would allow another process to lock a different inode.
    with (Path(root) / f"{slug}.start.lock").open("a+b") as handle:
        if IS_WINDOWS:
            handle.seek(0)
        try:
            if IS_WINDOWS:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            die(f"start: run '{slug}' is already starting")
        except OSError as exc:
            if not IS_WINDOWS or exc.errno != errno.EACCES:
                raise
            die(f"start: run '{slug}' is already starting")
        yield  # closing the file releases the kernel lock on both platforms


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def read_state(run_dir):
    state = read_json(os.path.join(run_dir, "state.json"), {})
    return state if isinstance(state, dict) else {}


def write_json(path, payload):
    """Retry WinError 5 from a poller before sacrificing atomicity, not the run."""
    tmp = f"{path}.{os.getpid()}.tmp"
    data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    write_text(tmp, data)
    try:
        for attempt in range(40):
            try:
                return os.replace(tmp, path)
            except PermissionError as exc:
                if getattr(exc, "winerror", None) != 5:
                    raise
                if attempt < 39:
                    time.sleep(0.05 + 0.05 * (attempt % 5))
        # A torn read is bad, a lost run is worse.
        print(f"gdd: warning: could not replace {path} (WinError 5); writing in place", file=sys.stderr)
        write_text(path, data)
    finally:
        Path(tmp).unlink(missing_ok=True)


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def sanitize(value):
    slug = SLUG_RE.sub("-", str(value or "").lower()).strip("-")[:48]
    return "" if slug in (".", "..") else slug


def interpreter():
    """python.exe, not pythonw.exe: a pythonw parent loses the std handles children need."""
    console = os.path.join(os.path.dirname(sys.executable), "python.exe")
    return console if IS_WINDOWS and os.path.exists(console) else sys.executable


def state_age_seconds(state):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(state["started"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return float("inf")


def wait_until(predicate, seconds):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL)
    return True


def _windows_query(pid, query):
    """query(kernel32, handle) on an open process handle, or None when it cannot be opened."""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED
    if not handle:
        return None
    try:
        return query(kernel32, handle)
    finally:
        kernel32.CloseHandle(handle)


def _probe(send, target):
    """kill(target, 0) semantics: gone only on ProcessLookupError-like failures."""
    try:
        send(target, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def pid_alive(pid):
    """Windows: OpenProcess + GetExitCodeProcess (os.kill reads AccessDenied as dead)."""
    if isinstance(pid, str) and pid.isdigit():
        pid = int(pid)
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if IS_WINDOWS:
        code = ctypes.c_ulong()
        return bool(_windows_query(pid, lambda k, h: k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259))
    return _probe(os.kill, pid)


def identity(pid):
    """Process start time (Linux stat field 22, macOS ps lstart, Windows creation time), or ""."""
    if not pid_alive(pid):
        return ""
    if IS_WINDOWS:
        times = [wintypes.FILETIME() for _ in range(4)]
        ok = _windows_query(pid, lambda k, h: k.GetProcessTimes(h, *(ctypes.byref(t) for t in times)))
        return f"win:{(times[0].dwHighDateTime << 32) | times[0].dwLowDateTime}" if ok else ""
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
                return "linux:" + handle.read().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            return ""
    try:
        out = gdd_process.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                              env={**os.environ, "LC_ALL": "C"}, stdin=subprocess.DEVNULL).stdout.strip()
    except OSError:
        out = ""
    return f"ps:{out}" if out else ""


def terminate(pid, reap=lambda: None, *, single=False):
    """End the tree pid leads; True once gone. `reap` lets the parent collect its own zombie."""
    def gone():
        reap()
        return not (pid_alive(pid) or (not IS_WINDOWS and not single and _probe(os.killpg, pid)))

    if IS_WINDOWS:
        gdd_process.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return wait_until(gone, 5)
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            (os.kill if single else os.killpg)(pid, signum)
        except OSError:
            pass
        if wait_until(gone, 5):
            return True
    return False


def run_alive(run_dir, state=None):
    """The runner or the agent recorded in state.json is alive (public: gdd.py imports it)."""
    state = read_state(run_dir) if state is None else state
    return pid_alive(state.get("pid")) or pid_alive(state.get("agent_pid"))


def is_starting(state):
    return state.get("pid") is None and state_age_seconds(state) < knob("GDD_RUN_START_GRACE_SECONDS", 60)


def observed_state(run_dir, state):
    """Read-only view for gdd.py and delivery-state.py: the recorded state, or "stale" for a
    `running` run with nothing alive, no `finalized` marker and no startup grace left. A custom
    launcher that records no pid keys at all cannot be probed, so its recorded state stands."""
    recorded = str(state.get("state") or "?")
    if (recorded != "running" or not {"pid", "agent_pid"} & state.keys()
            or os.path.exists(os.path.join(run_dir, "finalized"))
            or run_alive(run_dir, state) or is_starting(state)):
        return recorded
    return "stale"


def new_acc():
    return {"session_id": "", "answer": "", "turns": 0, "tool_calls": 0, "cost_usd": None,
            "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "total_tokens": 0},
            "error": "", "success_marker": None, "structured": None, "report": ""}


def text_parts(content):
    if not isinstance(content, list):
        return ""
    return "".join(p.get("text") or "" for p in content if isinstance(p, dict) and p.get("type") == "text")


def fold_pi(acc, event):
    """omp and pi: `session`, assistant `message_end`, `tool_execution_start`, `turn_end`, `agent_settled`."""
    kind = event.get("type")
    if kind == "session" and not acc["session_id"]:
        acc["session_id"] = event.get("id") or ""
    elif kind == "agent_settled" and event.get("aborted") is True:
        acc["success_marker"], acc["error"] = "aborted", acc["error"] or "agent_settled.aborted is true"
    elif kind == "tool_execution_start":
        acc["tool_calls"] += 1
    elif kind == "turn_end":
        acc["turns"] += 1
    elif kind == "message_end" and (event.get("message") or {}).get("role") == "assistant":
        message = event["message"]
        acc["answer"] = text_parts(message.get("content")) or acc["answer"]
        acc["success_marker"] = message.get("stopReason")
        if message.get("stopReason") in ("error", "aborted", "length"):
            acc["error"] = str(message.get("errorMessage") or f"stopReason {message.get('stopReason')}")
        usage = message.get("usage") or {}
        for key, source in (("input_tokens", "input"), ("output_tokens", "output"),
                            ("cache_read_tokens", "cacheRead"), ("total_tokens", "totalTokens")):
            acc["usage"][key] += int(usage.get(source) or 0)
        cost = usage.get("cost")
        cost = cost.get("total") if isinstance(cost, dict) else cost
        if isinstance(cost, (int, float)):
            acc["cost_usd"] = round((acc["cost_usd"] or 0) + cost, 6)


def fold_dsh(acc, event):
    kind = event.get("type")
    if kind == "session":
        acc["session_id"] = event.get("sessionId") or acc["session_id"]
    elif kind == "tool_call":
        acc["tool_calls"] += 1
    elif kind == "status":
        acc["turns"] += event.get("phase") == "turn_end"
        usage = event.get("usage")
        if isinstance(usage, dict):
            acc["usage"] = {key: int(usage.get(source) or 0) for key, source in (
                ("input_tokens", "inputTokens"), ("output_tokens", "outputTokens"),
                ("cache_read_tokens", "cacheReadTokens"), ("total_tokens", "totalTokens"))}
    elif kind == "text" and acc["success_marker"] is None and event.get("text"):
        acc["answer"] = str(event["text"])
    elif kind == "final":
        acc["answer"] = str(event.get("text") or acc["answer"])
        acc["success_marker"] = (event.get("reason") or {}).get("kind")
    elif kind == "error":
        acc["error"] = str(event.get("message") or "error event")


def fold_codex(acc, event):
    kind, item = event.get("type"), event.get("item") if isinstance(event.get("item"), dict) else {}
    if kind == "thread.started":
        acc["session_id"] = event.get("thread_id") or acc["session_id"]
    elif kind == "item.completed":
        if item.get("type") == "agent_message":  # under --output-schema the last one is the JSON
            acc["report"], acc["answer"] = acc["answer"] or acc["report"], str(item.get("text") or "")
        acc["tool_calls"] += item.get("type") in ("command_execution", "file_change", "mcp_tool_call", "web_search")
    elif kind == "turn.completed":
        acc["turns"], acc["success_marker"] = acc["turns"] + 1, kind
        usage = tokens(event.get("usage"), "input_tokens", "output_tokens", "cached_input_tokens")
        acc["usage"] = {key: acc["usage"][key] + usage[key] for key in usage}
    elif kind in ("turn.failed", "error"):
        acc["success_marker"] = kind
        acc["error"] = str(event.get("message") or (event.get("error") or {}).get("message") or kind)


def fold_claude(acc, event):
    kind, message = event.get("type"), event.get("message") if isinstance(event.get("message"), dict) else {}
    if kind == "system" and event.get("subtype") == "init":
        acc["session_id"] = event.get("session_id") or acc["session_id"]
    elif kind == "assistant":
        blocks = [b for b in message.get("content") or [] if isinstance(b, dict)]
        acc["tool_calls"] += sum(b.get("type") == "tool_use" and b.get("name") != "StructuredOutput" for b in blocks)
        acc["answer"] = acc["report"] = text_parts(blocks) or acc["answer"]
    elif kind == "result":
        ok = event.get("subtype") == "success" and event.get("is_error") is False
        acc["success_marker"] = "success" if ok else str(event.get("terminal_reason") or event.get("subtype"))
        acc["answer"], acc["structured"] = str(event.get("result") or acc["answer"]), event.get("structured_output")
        acc["turns"], acc["error"] = int(event.get("num_turns") or 0), "" if ok else acc["answer"]
        acc["usage"] = tokens(event.get("usage"), "input_tokens", "output_tokens", "cache_read_input_tokens",
                              "cache_read_input_tokens", "cache_creation_input_tokens")
        cost = event.get("total_cost_usd")
        acc["cost_usd"] = round(cost, 6) if isinstance(cost, (int, float)) else acc["cost_usd"]


def fold_opencode(acc, event):
    """`step_finish` per step; the answer is the text after the last `step_start`; an `error` sticks."""
    kind, part = event.get("type"), event.get("part") if isinstance(event.get("part"), dict) else {}
    acc["session_id"] = acc["session_id"] or str(event.get("sessionID") or "")
    if kind == "step_start":
        acc["answer"] = ""
    elif kind == "text":
        acc["answer"] += str(part.get("text") or "")
    elif kind == "tool_use":
        acc["tool_calls"] += 1
    elif kind == "step_finish":
        acc["turns"] += 1
        acc["success_marker"] = "error" if acc["success_marker"] == "error" else part.get("reason")
        count = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
        cache = count.get("cache") if isinstance(count.get("cache"), dict) else {}
        usage = tokens({**count, "cache_read": cache.get("read"), "cache_write": cache.get("write")}, "input",
                       "output", "cache_read", "reasoning", "cache_read", "cache_write")
        acc["usage"] = {key: acc["usage"][key] + usage[key] for key in usage}
        if isinstance(part.get("cost"), (int, float)):
            acc["cost_usd"] = round((acc["cost_usd"] or 0) + part["cost"], 6)
    elif kind == "error":
        error = event.get("error") if isinstance(event.get("error"), dict) else {}
        acc["success_marker"], acc["error"] = "error", str(error.get("message") or error.get("type") or "error event")


def tokens(usage, input_key, output_key, cache_key, *also_total):
    """Normalized usage; total = input + output + the `also_total` keys (codex input includes its cache)."""
    usage = usage if isinstance(usage, dict) else {}
    count = {key: int(usage.get(key) or 0) for key in (input_key, output_key, cache_key, *also_total)}
    return {"input_tokens": count[input_key], "output_tokens": count[output_key], "cache_read_tokens": count[cache_key],
            "total_tokens": count[input_key] + count[output_key] + sum(count[key] for key in also_total)}


def flags(*pairs):
    """[flag, value, ...] for every pair whose value is set: unset options are never passed."""
    return [token for flag, value in pairs if value for token in (flag, value)]


def omp_argv(args, extra):
    return ["-p", "--mode=json", "--approval-mode", "yolo",
            *flags(("--model", args.model), ("--thinking", args.thinking), ("-r", args.resume),
                   ("--profile", args.profile)), *extra]


def dsh_argv(args, extra):
    policy = os.environ.get("DSH_APPROVAL_POLICY") or "never"
    if policy != "never":
        die(f"start: DSH_APPROVAL_POLICY={policy!r} is refused: a detached run has no approval channel")
    argv = ["--profile", os.environ.get("DSH_RUN_PROFILE") or "headless", *extra, "--json"]
    argv += ["--session-id", args.resume] if args.resume else []
    mode = os.environ.get("DSH_PERMISSION_MODE") or "workspace-write"
    return argv + ["--permission-mode", mode, "--approval-policy", "never", "-"]


def codex_argv(args, extra):
    """Unquoted -c values parse as literal strings, so a Windows `.cmd` shim can carry them too."""
    effort = args.thinking and f"model_reasoning_effort={args.thinking}"
    return ["exec", *(["resume"] if args.resume else []), "--json", "-c", "approval_policy=never",
            "-c", "sandbox_mode=workspace-write", "-c", "sandbox_workspace_write.network_access=true",
            *flags(("-m", args.model), ("-c", effort), ("--output-schema", args.schema)), *extra,
            *([args.resume] if args.resume else []), "-"]


def claude_argv(args, extra):
    session = ["--resume", args.resume] if args.resume else ["--session-id", str(uuid.uuid4())]
    schema = args.schema and json.dumps(read_json(args.schema), separators=(",", ":"))
    return ["-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions", *session,
            *flags(("--model", args.model), ("--effort", args.thinking), ("--json-schema", schema)), *extra]


def pi_argv(args, extra):
    """pi has no tool approvals; --no-approve ignores project-local files (repo extensions never run)."""
    return ["--mode", "json", "--no-approve",
            *flags(("--model", args.model), ("--thinking", args.thinking), ("--session", args.resume)), *extra]


def opencode_argv(args, extra):
    """--standalone runs a private server inside this process tree, so kill and liveness reach the work."""
    if args.thinking and not args.model:
        die("start: --thinking on the opencode route needs --model (thinking is the #variant suffix)")
    model = args.model and (f"{args.model}#{args.thinking}" if args.thinking else args.model)
    return ["run", "--standalone", "--format", "json", "--auto", "--title", sanitize(args.name),
            *flags(("-s", args.resume), ("-m", model)), *extra]


@dataclass(frozen=True)
class Agent:
    name: str
    prompt: str  # "stdin" | "argv" (appended last)
    argv: Callable  # (args, extra) -> flags after the binary
    fold: Callable  # (acc, event) -> None
    marker: str  # where the success marker lives, for the error an exit-0 failure records
    succeeded: Callable  # success_marker -> bool
    scrub_env: tuple = ()
    refuse: tuple = ()  # start flags this route rejects


def pi_ok(marker):
    return marker not in (None, "error", "aborted", "length")


AGENTS = {
    "omp": Agent("omp", "argv", omp_argv, fold_pi, "the last assistant message_end stopReason", pi_ok),
    "pi": Agent("pi", "stdin", pi_argv, fold_pi, "the last assistant message_end stopReason", pi_ok),
    "dsh": Agent("dsh", "stdin", dsh_argv, fold_dsh, "the last final.reason.kind", lambda marker: marker == "completed",
                 scrub_env=("DSH_PROFILE", "DSH_PROFILE_DIR", "DSH_SESSION_ID"), refuse=("model", "thinking")),
    "codex": Agent("codex", "stdin", codex_argv, fold_codex, "the last turn event",
                   lambda marker: marker == "turn.completed"),
    "claude": Agent("claude", "stdin", claude_argv, fold_claude, "the result event outcome",
                    lambda marker: marker == "success"),
    "opencode": Agent("opencode", "argv", opencode_argv, fold_opencode, "the last step_finish reason",
                      lambda marker: marker == "stop"),
}


def fold_line(spec, acc, raw):
    try:
        event = json.loads(raw)
        if isinstance(event, dict) and event.get("type") != "truncated":
            spec.fold(acc, event)
    except (ValueError, AttributeError, TypeError, KeyError):
        pass


def resolve_binary(spec):
    key = f"{spec.name.upper()}_BIN"
    name = os.path.expanduser(os.environ.get(key) or spec.name)
    path = name if os.path.dirname(name) else shutil.which(name)
    if not path or not os.path.isfile(path):
        die(f"start: agent binary not found: {key}={name}")
    return command_prefix(path)


def command_prefix(path):
    """argv that runs `path`: a `.py` through this interpreter, a Windows `.cmd`/`.bat` shim through %COMSPEC%."""
    path, ext = os.path.abspath(path), os.path.splitext(path)[1].lower()
    if ext == ".py":
        return [interpreter(), path]
    if IS_WINDOWS and ext in (".cmd", ".bat"):
        return [os.environ.get("COMSPEC") or "cmd.exe", "/c", path]
    return [path]


def shim_hazard(binary, argv):
    """Why argv cannot pass through cmd.exe to a Windows `.cmd`/`.bat` shim, or ""."""
    if not IS_WINDOWS or os.path.splitext(binary)[1].lower() not in (".cmd", ".bat"):
        return ""
    for number, arg in enumerate(argv, 1):
        if found := "".join(sorted(set(CMD_UNSAFE.findall(arg)))):
            return f"{binary} is a .cmd shim and argument {number} contains {found!r}"
    return ""


def max_time_seconds(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", str(value).strip())
    if not match or float(match.group(1)) <= 0:
        die(f"start: --max-time must be N[s|m|h] (got {value!r})")
    return float(match.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[match.group(2)]


def child_env(scrub):
    return {key: value for key, value in os.environ.items() if key not in scrub}


class EventLog:
    """events.ndjson bounded by GDD_RUN_EVENTS_MAX_BYTES: at half, rotate to events.1.ndjson."""

    def __init__(self, run_dir):
        self.path, self.old = (os.path.join(run_dir, n) for n in ("events.ndjson", "events.1.ndjson"))
        self.half = max(int(knob("GDD_RUN_EVENTS_MAX_BYTES", 8388608)) // 2, 1)
        self.dropped, self.handle, self.size = 0, open(self.path, "ab"), 0

    def write(self, raw):
        raw = raw if raw.endswith(b"\n") else raw + b"\n"
        if self.size and self.size + len(raw) > self.half:
            self.handle.close()
            dropped = os.path.getsize(self.old) if os.path.exists(self.old) else 0
            try:  # one attempt: a reader holding the file just defers rotation to a later line
                os.replace(self.path, self.old)
                self.dropped, self.size = self.dropped + dropped, 0
            except OSError:
                pass
            self.handle = open(self.path, "ab")
            if not self.size and self.dropped:
                self.write(json.dumps({"type": "truncated", "dropped_bytes": self.dropped}).encode())
        self.handle.write(raw)
        self.handle.flush()
        self.size += len(raw)


def event_files(run_dir):
    return [p for p in (os.path.join(run_dir, n) for n in ("events.1.ndjson", "events.ndjson")) if os.path.exists(p)]


def event_stats(run_dir):
    retained, dropped = sum(os.path.getsize(path) for path in event_files(run_dir)), 0
    try:
        with open(os.path.join(run_dir, "events.ndjson"), encoding="utf-8", errors="replace") as handle:
            first = json.loads(handle.readline() or "{}")
        dropped = int(first.get("dropped_bytes") or 0) if first.get("type") == "truncated" else 0
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {"events_bytes": retained, "events_bytes_total": retained + dropped,
            "events_truncated": dropped > 0, "events_dropped_bytes": dropped}


def progress(acc):
    return {key: acc[key] for key in ("session_id", "turns", "tool_calls", "usage", "cost_usd")}


def finalize(run_dir, exit_code, acc=None, note=None, recovered=False, extra=None):
    """First terminal state wins. Writes answer.md, state.json, exit.code, then `finalized`."""
    if os.path.exists(os.path.join(run_dir, "finalized")):
        return read_state(run_dir)
    state = read_state(run_dir)
    spec, refolded = AGENTS.get(state.get("agent")), acc is None
    if refolded:  # the runner died: re-fold whatever events were retained
        acc = new_acc()
        for path in event_files(run_dir) if spec else []:
            with open(path, "rb") as handle:
                for raw in handle:
                    fold_line(spec, acc, raw)
    marker = acc["success_marker"]
    failure = f"exit 0 but {spec.marker} is {marker!r}" if spec and exit_code == 0 and not spec.succeeded(marker) else ""
    if exit_code == 0 and not (recovered or failure):
        verdict = "done"
    else:
        verdict = "killed" if exit_code in KILLED_EXITS and not recovered else "failed"
    stats = event_stats(run_dir)
    state.update(progress(acc), **stats, state=verdict, exit=exit_code, ended=now_iso(),
                 session_id=acc["session_id"] or state.get("session_id") or "")
    duration = state_age_seconds(state)
    state["duration_s"] = round(duration, 1) if duration != float("inf") else None
    if failure or (verdict != "done" and acc["error"]):
        state["error"] = ": ".join(filter(None, (failure, acc["error"])))
        state["errors"] = [state["error"]]  # the observer reads `errors`
    if refolded and stats["events_truncated"]:
        state.update(turns_partial=True, tool_calls_partial=True, cost_partial=True)
    if recovered:
        state["stale_recovered"] = True
        note = f"runner/agent pids {state.get('pid')}/{state.get('agent_pid')} died without finalizing"
    state.update({"note": note} if note else {}, **(extra or {}))
    if schema := read_json(os.path.join(run_dir, "run.json"), {}).get("schema"):
        state.update(stage_result.record(run_dir, acc["answer"], acc["structured"], schema))
    # a native structured result is the JSON alone: keep the report written before it in answer.md
    report = acc["report"] if schema and acc["report"].strip() not in ("", acc["answer"].strip()) else ""
    answer = f"{report.rstrip()}\n\n{acc['answer']}" if report else acc["answer"]
    state["answer_chars"] = len(answer)
    write_text(os.path.join(run_dir, "answer.md"), answer)
    write_json(os.path.join(run_dir, "state.json"), state)
    write_text(os.path.join(run_dir, "exit.code"), f"{exit_code}\n")
    write_text(os.path.join(run_dir, "finalized"), str(exit_code))
    return state


def effective_state(run_dir):
    """(state, stale_recovered): settle a run whose runner died before finalizing."""
    state = read_state(run_dir)
    if os.path.exists(os.path.join(run_dir, "finalized")) or state.get("state") not in STATES:
        return state, False
    if state.get("backend") == "paseo" or not {"pid", "agent_pid"} & state.keys():
        return state, False  # another launcher's run: its liveness is not ours to settle
    if run_alive(run_dir, state) or is_starting(state):
        return state, False
    if state["state"] != "running":  # terminal state published but the marker is missing
        write_text(os.path.join(run_dir, "exit.code"), f"{state.get('exit')}\n")
        write_text(os.path.join(run_dir, "finalized"), str(state.get("exit")))
        return state, False
    if os.path.exists(os.path.join(run_dir, "stop")):
        return finalize(run_dir, KILL_EXIT, note="stop requested and the runner is gone; recorded by a reader"), False
    return finalize(run_dir, -1, recovered=True), True


def reported_state(state):
    return state if state.get("state") in STATES else {**state, "state": "unknown"}


def newest_first(paths):
    def key(path):
        return os.path.basename(os.path.dirname(path)), os.path.getmtime(path) if os.path.exists(path) else 0.0
    return sorted(paths, key=key, reverse=True)


def find_run(name, command=None):
    """Newest run dir called SLUG; with `command`, a missing run is an error."""
    slug = sanitize(name)
    found = [p for p in glob.glob(os.path.join(run_root(), "*", glob.escape(slug)))
             if slug and os.path.isdir(p) and DATE_RE.match(os.path.basename(os.path.dirname(p)))]
    if not found and command:
        die(f"{command}: no run '{name}' under {run_root()}")
    return newest_first(found)[0] if found else None


def stop_run(run_dir):
    """"" once the run is finalized after a stop request, else why the stop is unproven."""
    marker = os.path.join(run_dir, "finalized")
    if os.path.exists(marker):
        return ""
    write_json(os.path.join(run_dir, "stop"), {"requested_at": now_iso(), "by": os.getpid()})
    if wait_until(lambda: os.path.exists(marker), knob("GDD_RUN_STOP_WAIT_SECONDS", 20)):
        return ""
    state, problems = read_state(run_dir), []
    for key in ("agent_pid", "pid"):
        pid = state.get(key)
        if not pid_alive(pid):
            continue
        live = identity(pid)
        if not live or live != state.get(f"{key}_identity"):
            problems.append(f"{key} {pid} not signalled (start time {'unreadable' if not live else 'differs from the recorded one'})")
        elif not terminate(pid, single=key == "pid" and state.get("detach") == "systemd"):
            problems.append(f"{key} {pid} still alive after TERM/KILL")
    if problems:
        return "; ".join(problems)
    if not wait_until(lambda: os.path.exists(marker), 5):
        finalize(run_dir, KILL_EXIT, note="stop requested; the runner did not finalize, so kill recorded the stop")
    return ""


def cmd_start(args):
    for key, replacement in RETIRED.items():
        if os.environ.get(key):
            print(f"agent_run: warning: {key} is retired; use {replacement}", file=sys.stderr)
    try:
        agent = skill_config.resolve("gdd", "GDD_AGENT", flag=args.agent, default="omp")
    except skill_config.ConfigError as exc:
        die(f"start: {exc}")
    spec = AGENTS.get(agent) or die(f"start: unknown agent {agent!r} (known: {', '.join(AGENTS)})")
    if args.session_id is not None:
        if agent != "dsh" or args.resume is not None:
            die("start: --session-id is a DSH alias for --resume; do not combine them")
        args.resume = args.session_id
    if (args.backend is not None or args.profile is not None) and agent != "omp":
        die("start: --backend and --profile are OMP compatibility flags")
    if args.backend is not None:
        print(f"agent_run: warning: --backend {args.backend} is retired; using GDD_RUN_DETACH instead",
              file=sys.stderr)
    for field in spec.refuse:
        if getattr(args, field):
            die(f"start: --{field} is not supported on the {agent.upper()} route")
    slug = sanitize(args.name) or die(f"start: --name {args.name!r} does not sanitize to a usable slug")
    try:
        with open(os.path.expanduser(args.prompt), "rb") as handle:
            prompt = handle.read()
    except OSError as exc:
        die(f"start: cannot read --prompt: {exc}")
    cwd = os.path.abspath(os.path.expanduser(args.cwd or os.getcwd()))
    if not os.path.isdir(cwd):
        die(f"start: --cwd {cwd} is not a directory")
    max_time = max_time_seconds(args.max_time) if args.max_time else None
    if args.schema:
        args.schema = os.path.abspath(os.path.expanduser(args.schema))
        if not isinstance(read_json(args.schema), dict):
            die(f"start: --schema {args.schema} is not a readable JSON object")
    prefix = resolve_binary(spec)
    command = prefix + spec.argv(args, shlex.split(args.extra or ""))
    shim = command[2] if command[1:2] == ["/c"] else command[0]
    checked = command[command.index(shim) + 1:] + ([prompt.decode("utf-8", "replace")] if spec.prompt == "argv" else [])
    if hazard := shim_hazard(shim, checked):
        die(f"start: {hazard}; point {agent.upper()}_BIN at the real executable")

    root = run_root()
    run_dir = str(Path(root) / datetime.now().strftime("%Y-%m-%d") / slug)
    warn_wsl(prefix[-1], run_dir)
    try:
        mode, launcher = select_detach(detach_config())
        with slug_start_lock(root, slug):
            return start_locked(args, spec, slug, cwd, run_dir, command, prompt, max_time, mode, launcher)
    except (OSError, ValueError) as exc:
        die(f"start: {exc}")


def start_locked(args, spec, slug, cwd, run_dir, command, prompt, max_time, mode, launcher):
    previous = find_run(slug)
    if previous:
        state, _ = effective_state(previous)
        if state.get("backend") == "paseo" and state.get("state") in ("running", "unknown"):
            die(f"start: native Paseo run '{slug}' is unresolved; use the Paseo adapter")
        live = not os.path.exists(os.path.join(previous, "finalized")) and (run_alive(previous, state) or is_starting(state))
        if live and not args.replace:
            die(f"start: run '{slug}' is still running (pid {state.get('pid')}/{state.get('agent_pid')}; use --replace)")
        if live and (problem := stop_run(previous)):
            die(f"start: could not stop run '{slug}': {problem}")
    try:
        if os.path.isdir(run_dir):  # keep the previous run; on Windows its exiting runner still holds files
            wait_until(lambda: not run_alive(run_dir), knob("GDD_RUN_STOP_WAIT_SECONDS", 20))
            archive = f"{run_dir}.prev-{datetime.now():%H%M%S%f}"
            before = os.stat(run_dir)
            for attempt in range(10):
                try:
                    os.rename(run_dir, archive)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    # DrvFS can briefly deny a rename after the final state files close.
                    time.sleep(0.1)
                    if not os.path.samestat(before, os.stat(run_dir)):
                        raise
        os.makedirs(os.path.dirname(run_dir), exist_ok=True)
        os.mkdir(run_dir)  # the slug claim
    except OSError as exc:
        die(f"start: cannot claim {run_dir}: {exc}")
    with open(os.path.join(run_dir, "prompt.md"), "wb") as handle:
        handle.write(prompt)
    agent = spec.name
    unit = unit_name(slug) if mode == "systemd" else None
    write_json(os.path.join(run_dir, "run.json"), {"agent": agent, "argv": command, "prompt": spec.prompt,
                                                   "cwd": cwd, "scrub_env": spec.scrub_env, "max_time_s": max_time,
                                                   "schema": args.schema})
    write_json(os.path.join(run_dir, "state.json"), {
        "name": slug, "agent": agent, "state": "running", "exit": None, "cwd": cwd, "started": now_iso(),
        "ended": None, "duration_s": None, "run_dir": run_dir, "pid": None, "agent_pid": None,
        "session_id": args.resume or (command[command.index("--session-id") + 1] if "--session-id" in command else ""),
        "backend": {"session": "setsid", "windows": "windows", "systemd": "systemd"}[mode],
        "detach": mode, **({"unit": unit} if unit else {}), "model": args.model,
        "thinking": args.thinking, "max_time": args.max_time, "resumed_from": args.resume,
        "spawn": {"creationflags": 0, "platform": sys.platform}})
    runner = [interpreter(), "-B", os.path.abspath(__file__), "_run", "--run-dir", run_dir]
    try:
        process, _ = spawn_detached(runner, run_dir, cwd, child_env(spec.scrub_env), mode, launcher, unit)
    except OSError as exc:
        finalize(run_dir, 127, note=f"could not spawn the runner: {exc}")
        die(f"start: could not spawn the runner: {exc}")
    seen = {}

    def started():
        seen.update(read_state(run_dir))
        return (seen.get("agent_pid") or seen.get("state") not in (None, "running")
                or (process is not None and process.poll() is not None))

    if not wait_until(started, 20):
        die(f"start: no agent pid recorded within 20 s (see {os.path.join(run_dir, 'runner.log')})")
    if not seen.get("agent_pid"):
        die(f"start: agent did not start: {seen.get('note') or seen.get('state')} (see {run_dir})")
    print(f"started: {slug}\n  agent     : {agent} (pid {seen['agent_pid']}, runner {seen.get('pid')})")
    print(f"  run dir   : {run_dir}")
    return 0


def runner_main(args):
    run_dir = os.path.abspath(args.run_dir)
    if args.restore_env:
        restore_detached_env(run_dir)
    plan, state_path = read_json(os.path.join(run_dir, "run.json"), {}), os.path.join(run_dir, "state.json")
    spec, state = AGENTS[plan["agent"]], read_state(run_dir)
    state.update(pid=os.getpid(), pid_identity=identity(os.getpid()))
    state["spawn"]["creationflags"] = args.creationflags
    write_json(state_path, state)
    with open(os.path.join(run_dir, "prompt.md"), "rb") as handle:
        prompt = handle.read()
    argv = plan["argv"] + ([prompt.decode("utf-8", "replace")] if spec.prompt == "argv" else [])
    log, acc, lock, requested = EventLog(run_dir), new_acc(), threading.Lock(), threading.Event()
    with open(os.path.join(run_dir, "stderr.log"), "ab") as stderr:
        try:
            process = gdd_process.popen(
                argv, cwd=plan["cwd"], stdout=subprocess.PIPE, stderr=stderr,
                stdin=subprocess.PIPE if spec.prompt == "stdin" else subprocess.DEVNULL,
                env=child_env(plan.get("scrub_env") or ()), start_new_session=not IS_WINDOWS)
        except OSError as exc:
            finalize(run_dir, 127, acc, note=f"agent did not start: {exc}")
            return 1
        state.update(agent_pid=process.pid, agent_pid_identity=identity(process.pid))
        write_json(state_path, state)

        def read():
            for raw in process.stdout:
                with lock:
                    log.write(raw)
                    fold_line(spec, acc, raw)

        def feed():
            try:
                process.stdin.write(prompt)
                process.stdin.close()
            except OSError:
                pass

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        if spec.prompt == "stdin":
            threading.Thread(target=feed, daemon=True).start()
        for name in ("SIGTERM", "SIGBREAK", "SIGHUP"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), lambda *_: requested.set())
        deadline = time.monotonic() + plan["max_time_s"] if plan.get("max_time_s") else None
        note, next_write, stop = None, 0.0, False
        while (exit_code := process.poll()) is None:
            stop = requested.is_set() or os.path.exists(os.path.join(run_dir, "stop"))
            if stop or (deadline is not None and time.monotonic() >= deadline):
                exit_code = KILL_EXIT if stop else TIMEOUT_EXIT
                note = None if stop else f"max_time exceeded ({plan['max_time_s']:g} s)"
                if not terminate(process.pid, process.poll):
                    note = f"{note or 'stopped'}; agent pid {process.pid} still alive after TERM/KILL"
                break
            if time.monotonic() >= next_write:
                with lock:
                    state.update(progress(acc), **event_stats(run_dir))
                write_json(state_path, state)
                next_write = time.monotonic() + PROGRESS_SECONDS
            time.sleep(POLL)
        # A descendant still holding stdout must not wedge the runner (measured on Windows). After a
        # stop, drain at most 5 s so TERM 5 + KILL 5 + drain finalize inside kill's 20 s stop wait.
        drain = knob("GDD_RUN_DRAIN_TIMEOUT_SECONDS", 30)
        reader.join(min(drain, 5) if stop else drain)
        with lock:
            extra = {"stream_incomplete": True} if reader.is_alive() else {}
            final = finalize(run_dir, exit_code, dict(acc), note=note, extra=extra)
    print(f"[finalize] {final.get('name')} state={final.get('state')} exit={exit_code}", flush=True)
    return 0


def first_text(event):
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    candidates = [event.get("text"), text_parts(message.get("content")), (event.get("item") or {}).get("text"),
                  (event.get("part") or {}).get("text"), event.get("result")]
    return next((c for c in candidates if isinstance(c, str) and c), "")


def cmd_tail(args):
    path = os.path.join(find_run(args.name, "tail"), "events.ndjson")
    if not os.path.exists(path):
        die(f"tail: no event log at {path}")
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()[-(args.lines or 20):]
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        if not isinstance(event, dict):
            print(line.strip()[:160])
            continue
        text = " ".join(first_text(event).split())[:160]
        print(f"{event.get('type', '?')}: {text}" if text else str(event.get("type", "?")))
    return 0


def cmd_list(_args):
    runs = newest_first(p for p in glob.glob(os.path.join(run_root(), "*", "*"))
                        if os.path.isfile(os.path.join(p, "state.json")))
    for run_dir in runs:
        state, _ = effective_state(run_dir)
        word = "failed(stale)" if state.get("stale_recovered") else reported_state(state)["state"]
        print(f"{str(state.get('started') or '')[:19].replace('T', ' ')}  {os.path.basename(run_dir):<28} "
              f"{state.get('agent') or '?':<8} {word} exit={state.get('exit')} dur={state.get('duration_s')} "
              f"sess={state.get('session_id') or '-'}")
    if not runs:
        print("(no runs recorded)")
    return 0


def cmd_status(args):
    """`status` prints state.json plus liveness; `result` adds the answer head."""
    if not args.name:
        return cmd_list(args)
    run_dir = find_run(args.name, args.command)
    state, recovered = effective_state(run_dir)
    shown = {**reported_state(state), "alive": run_alive(run_dir, state)} if args.command == "status" else reported_state(state)
    print(json.dumps(shown, indent=2, ensure_ascii=False) + ("\nstale_recovered: true" if recovered else ""))
    answer = os.path.join(run_dir, "answer.md")
    if args.command == "result" and os.path.exists(answer):
        with open(answer, encoding="utf-8", errors="replace") as handle:
            print("\n--- answer (first 1500 chars) ---\n" + handle.read()[:1500])
    return 0


def cmd_answer(args):
    run_dir = find_run(args.name, "answer")
    effective_state(run_dir)
    if not os.path.exists(os.path.join(run_dir, "finalized")):
        die(f"answer: run '{args.name}' is not finished")
    with open(os.path.join(run_dir, "answer.md"), encoding="utf-8", errors="replace") as handle:
        sys.stdout.write(handle.read())
    return 0


def cmd_kill(args):
    run_dir = find_run(args.name, "kill")
    state, _ = effective_state(run_dir)
    if os.path.exists(os.path.join(run_dir, "finalized")):
        die(f"kill: run '{args.name}' is already finished (state {state.get('state')})")
    if not (run_alive(run_dir, state) or is_starting(state)):
        die(f"kill: no live process recorded for '{args.name}' (state {reported_state(state)['state']})")
    if problem := stop_run(run_dir):
        die(f"kill: cannot confirm the stop of '{args.name}': {problem}")
    final = read_state(run_dir)
    print(f"killed: {args.name} state={final.get('state')} exit={final.get('exit')}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=f"Agents: {', '.join(AGENTS)}.",
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="start one detached run")
    for flag in ("--cwd", "--agent", "--model", "--thinking", "--max-time", "--resume", "--schema", "--extra"):
        start.add_argument(flag)
    for compat in ("--backend", "--profile", "--session-id"):
        start.add_argument(compat, help=argparse.SUPPRESS)
    start.add_argument("--name", required=True)
    start.add_argument("--prompt", required=True)
    start.add_argument("--replace", action="store_true")
    start.set_defaults(func=cmd_start)
    internal = sub.add_parser("_run")
    internal.add_argument("--run-dir", required=True)
    internal.add_argument("--restore-env", action="store_true")
    internal.add_argument("--creationflags", type=int, default=0)
    internal.set_defaults(func=runner_main)
    sub.add_parser("list").set_defaults(func=cmd_list)
    for name, func in (("status", cmd_status), ("result", cmd_status), ("answer", cmd_answer),
                       ("kill", cmd_kill), ("tail", cmd_tail)):
        command = sub.add_parser(name)
        command.add_argument("name", nargs="?" if name == "status" else None)
        if name == "tail":
            command.add_argument("lines", nargs="?", type=int)
        command.set_defaults(func=func)
    args = parser.parse_args(normalize_argv(sys.argv[1:] if argv is None else argv))
    return args.func(args)


def normalize_argv(argv):
    """`--extra --flag` becomes `--extra=--flag`: argparse refuses a value that starts with "-"."""
    tokens, normalized = list(argv), []
    while tokens:
        token = tokens.pop(0)
        if token in ("--extra", "--model", "--thinking", "--resume") and tokens and tokens[0].startswith("-"):
            token = f"{token}={tokens.pop(0)}"
        normalized.append(token)
    return normalized


if __name__ == "__main__":
    sys.exit(main())
