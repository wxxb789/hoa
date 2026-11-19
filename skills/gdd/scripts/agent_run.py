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

Detachment: GDD_RUN_DETACH=auto|systemd|launchd|setsid|windows|tmux|herdr.
Auto prefers a Linux user unit or a macOS LaunchAgent, then a POSIX double fork
or a Windows process group. tmux and herdr require explicit environment opt-in.

Knobs: GDD_RUN_EVENTS_MAX_BYTES (8388608), GDD_RUN_START_GRACE_SECONDS (60),
GDD_RUN_STOP_WAIT_SECONDS (20), GDD_RUN_DRAIN_TIMEOUT_SECONDS (30; 5 after a stop).
dsh: DSH_RUN_PROFILE (headless), DSH_PERMISSION_MODE (workspace-write), DSH_APPROVAL_POLICY (only `never`).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import glob
import json
import os
import plistlib
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

KILLED_EXITS = (130, -2, 137, -9, 143, -15)
KILL_EXIT, TIMEOUT_EXIT = 143, 124
WINDOWS_DETACH = gdd_process.NO_WINDOW | gdd_process.NEW_GROUP
# Ubuntu 22.04 leaves standard support in 2027-04; then move the floor to 24.04's 3.4.
TMUX_MIN_VERSION = (3, 2, "a")
POLL, PROGRESS_SECONDS = 0.25, 2.0
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLUG_RE = re.compile(r"[^a-z0-9._-]+")
CMD_UNSAFE = re.compile(r'[\r\n"&|<>^()%!]')
STATES = ("running", "done", "failed", "killed")
_RENAMED = ("EVENTS_MAX_BYTES", "START_GRACE_SECONDS", "STOP_WAIT_SECONDS", "DRAIN_TIMEOUT_SECONDS")
RETIRED = {
    "OMP_RUN_ROOT": "GDD_RUN_ROOT", "DSH_RUN_ROOT": "GDD_RUN_ROOT",
    "OMP_LEDGER": "nothing (no runner ledger; `list` shows every run)",
    "OMP_RUN_BACKEND": "GDD_RUN_DETACH", "DSH_RUN_SETTLE_WAIT_SECONDS": "nothing",
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
        requested = skill_config.resolve("gdd", "GDD_RUN_DETACH", default="auto")
    except skill_config.ConfigError as exc:
        raise ValueError(f"GDD_RUN_DETACH: {exc}") from exc
    if requested in ("tmux", "herdr") and os.environ.get("GDD_RUN_DETACH") != requested:
        raise ValueError(f"GDD_RUN_DETACH={requested} must be set in the environment")
    return requested


def select_detach(requested):
    modes = ("auto", "systemd", "launchd", "setsid", "windows", "tmux", "herdr")
    if requested not in modes:
        raise ValueError(f"GDD_RUN_DETACH={requested!r}: expected {', '.join(modes)}")
    if requested in ("tmux", "herdr"):
        if requested == "tmux" and IS_WINDOWS:
            raise ValueError("GDD_RUN_DETACH=tmux is not supported on native Windows")
        launcher = shutil.which(requested)
        if not launcher:
            raise ValueError(f"GDD_RUN_DETACH={requested}: {requested} executable not found on PATH")
        if requested == "tmux":
            check_tmux_version(launcher)
        return requested, launcher
    if requested in ("auto", "systemd") and sys.platform == "linux":
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
    if requested == "launchd" and sys.platform != "darwin":
        raise ValueError("GDD_RUN_DETACH=launchd requires macOS")
    if requested in ("auto", "launchd") and sys.platform == "darwin":
        return "launchd", shutil.which("launchctl")
    native = "windows" if IS_WINDOWS else "setsid"
    if requested not in ("auto", native):
        raise ValueError(f"GDD_RUN_DETACH={requested} is not supported on {sys.platform}")
    return native, None


def check_tmux_version(launcher):
    try:
        found = require_success(supervisor_call([launcher, "-V"])).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"tmux: cannot check version: {exc}") from exc
    if found == "tmux master":
        return
    match = re.fullmatch(r"tmux (?:next-)?([0-9]+)\.([0-9]+)([a-z]*)", found)
    if match and (int(match[1]), int(match[2]), match[3]) >= TMUX_MIN_VERSION:
        return
    minimum = "{}.{}{}".format(*TMUX_MIN_VERSION)
    raise ValueError(f"tmux: found {found!r}; requires tmux {minimum} or newer")


def systemd_argv(launcher, unit, cwd, log, runner):
    # Transient unit properties carry literal paths; only ExecStart expands dollar variables.
    return [launcher, "--user", "--collect", "--unit", unit, "--service-type=exec",
            "--no-ask-password", f"--working-directory={cwd}",
            f"--property=StandardOutput=append:{log}",
            "--property=StandardError=inherit", "--", runner[0],
            *(arg.replace("$", "$$") for arg in runner[1:]), "--restore-env"]


def private_file(path):
    if os.name != "nt":
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    # Assign the protected DACL at creation, before writing any private data.
    import csv

    whoami = Path(os.environ["SystemRoot"], "System32", "whoami.exe")
    account = require_success(gdd_process.run([str(whoami), "/user", "/fo", "csv", "/nh"],
                                              capture_output=True, text=True, timeout=5))
    sid = next(csv.reader(account.stdout.splitlines()), ["", ""])[-1]
    if not re.fullmatch(r"S-1-(?:[0-9]+-)*[0-9]+", sid):
        raise OSError("whoami.exe did not return a user SID")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p),
                    ("inherit", wintypes.BOOL)]

    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.POINTER(SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    descriptor = ctypes.c_void_p()
    if not convert(f"O:{sid}D:P(A;;FA;;;{sid})", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attrs = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        handle = create(str(path), 0x40000000, 0, ctypes.byref(attrs), 1, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    finally:
        kernel.LocalFree(descriptor)


def save_detached_env(run_dir, env):
    # Supervisors have their own environment. Restore ours without exposing credentials in argv.
    with os.fdopen(private_file(Path(run_dir) / ".runner-env"), "w", encoding="utf-8") as stream:
        json.dump(env, stream)


def supervisor_call(argv, *, env=None):
    return gdd_process.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=10)


def supervisor_error(result):
    return result.stderr.strip() or f"exit {result.returncode}"


def require_success(result):
    if result.returncode:
        raise OSError(supervisor_error(result))
    return result


def launchd_start(runner, run_dir, cwd, env, state):
    target = state["supervisor"]
    plist = run_dir / "runner.plist"
    runner = [*runner, "--launchd-start"]
    launcher, domain, label = target["argv"][0], target["domain"], target["label"]
    with os.fdopen(private_file(plist), "wb") as stream:
        plistlib.dump({"Label": label, "ProgramArguments": runner, "WorkingDirectory": cwd,
                       "EnvironmentVariables": env, "StandardOutPath": str(run_dir / "runner.log"),
                       "StandardErrorPath": str(run_dir / "runner.log"), "AbandonProcessGroup": True,
                       "RunAtLoad": True}, stream)
    result = supervisor_call([launcher, "bootstrap", domain, str(plist)])
    if result.returncode and (result.returncode == 64 or re.search(
            r"(?:unknown|unrecognized|unsupported) (?:sub)?command", result.stderr, re.IGNORECASE)):
        target["submit"] = True
        write_json(run_dir / "state.json", state)
        save_detached_env(run_dir, env)
        result = supervisor_call([launcher, "submit", "-l", label, "-o", str(run_dir / "runner.log"),
                                  "-e", str(run_dir / "runner.log"), "--", *runner, "--restore-env",
                                  "--runner-cwd", cwd])
    require_success(result)
    (run_dir / ".launchd-ready").touch()


def herdr_response(result):
    require_success(result)
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or not isinstance(response.get("result"), dict):
        raise ValueError("expected a Herdr JSON result")
    return response["result"]


def spawn_detached(runner, run_dir, cwd, env, state, mode, launcher=None):
    run_dir = Path(run_dir)
    log_path = run_dir / "runner.log"
    state["detach"] = mode
    if state.get("backend") != "paseo":
        state["backend"] = mode
    suffix = uuid.uuid4().hex[:12]
    target = {}
    if mode == "launchd" and launcher:
        target = {"mode": mode, "argv": [launcher], "domain": f"gui/{os.getuid()}",
                  "label": f"gdd.{state['name']}.{suffix}"}
    elif mode == "tmux":
        socket = os.environ.get("TMUX", "").partition(",")[0]
        target = {"mode": mode, "argv": [launcher, *(["-S", socket] if socket else [])],
                  "env": {key: os.environ[key] for key in ("TMUX_TMPDIR", "TMPDIR") if key in os.environ},
                  "session": re.sub(r"[^a-zA-Z0-9_-]", "-", f"gdd-{state['name']}-{suffix}")}
    elif mode == "herdr":
        target = {"mode": mode, "argv": [launcher], "entry": f".runner-herdr-{suffix}.py", "env": {
            key: os.environ[key] for key in ("HERDR_SESSION", "HERDR_SOCKET_PATH", "HERDR_CONFIG_PATH", "XDG_CONFIG_HOME")
            if key in os.environ}}
    if target:
        state["supervisor"] = target
    else:
        state.pop("supervisor", None)
    if mode == "systemd":
        state["unit"] = unit_name(state["name"])
    write_json(run_dir / "state.json", state)
    try:
        if mode == "systemd":
            save_detached_env(run_dir, env)
            require_success(supervisor_call(systemd_argv(launcher, state["unit"], cwd, log_path, runner)))
            return None, 0
        if mode == "launchd":
            if not launcher:
                raise OSError("launchctl executable not found on PATH")
            launchd_start(runner, run_dir, cwd, env, state)
            return None, 0
        if mode in ("tmux", "herdr"):
            save_detached_env(run_dir, env)
            runner = [*runner, "--restore-env"]
            setting = "-e" if mode == "tmux" else "--env"
            options = [arg for key in ("PYTHONUNBUFFERED", "PYTHONPATH", "NOWINDOW_GUARD_LOG")
                       if key in env or key == "PYTHONUNBUFFERED" for arg in (setting, f"{key}={env.get(key, '1')}")]
            if mode == "tmux":
                require_success(target_call(target, "new-session", "-d", "-s", target["session"],
                                            "-c", cwd, *options, "--", *runner))
                (run_dir / ".supervisor-started").touch()
            else:
                # Herdr joins arguments into shell input. Only fixed ASCII tokens reach that shell.
                executable = Path(runner[0])
                if not re.fullmatch(r"python[0-9.]*(?:\.exe)?", executable.name):
                    raise ValueError(f"Herdr requires a standard Python executable name: {executable.name}")
                options += ["--env", f"PATH={executable.parent}{os.pathsep}{env.get('PATH', os.defpath)}"]
                with os.fdopen(private_file(run_dir / target["entry"]), "w", encoding="utf-8") as entry:
                    entry.write("import os, runpy, sys\n"
                                f"sys.argv = {ascii([*runner[2:], '--runner-cwd', cwd])}\n"
                                "sys.path[0] = os.path.dirname(os.path.abspath(sys.argv[0]))\n"
                                "os.unlink(__file__)\n"
                                "runpy.run_path(sys.argv[0], run_name='__main__')\n")
                result = herdr_response(target_call(target, "tab", "create", "--no-focus", "--cwd", str(run_dir),
                                                    "--label", f"gdd-{state['name']}", *options))
                tab = result["tab"]["tab_id"]
                if not isinstance(tab, str) or not tab or tab.startswith("-"):
                    raise ValueError("invalid Herdr tab ID")
                target["tab"] = tab
                write_json(run_dir / "state.json", state)
                pane = result["root_pane"]["pane_id"]
                if not isinstance(pane, str) or not pane or pane.startswith("-"):
                    raise ValueError("invalid Herdr pane ID")
                target["pane"] = pane
                write_json(run_dir / "state.json", state)
                require_success(target_call(target, "pane", "run", pane,
                                            f"{executable.name} -B {target['entry']}"))
            return None, 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        (run_dir / ".runner-env").unlink(missing_ok=True)
        if mode == "launchd":
            cleanup_supervisor(run_dir, state)
            state["detach_fallback"] = f"launchd: {exc}"
            return spawn_detached(runner, run_dir, cwd, env, state, "setsid")
        if mode in ("tmux", "herdr"):
            cleanup_supervisor(run_dir, state)
        raise OSError(f"{mode}: {exc}") from exc
    if mode == "setsid":
        return gdd_process.daemonize(runner, cwd, env, log_path), 0
    with log_path.open("ab", buffering=0) as log:
        for flags in (WINDOWS_DETACH | gdd_process.BREAKAWAY, WINDOWS_DETACH):
            try:
                process = gdd_process.popen([*runner, "--creationflags", str(flags)], cwd=cwd,
                                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                            env=env, creationflags=flags)
                return process.pid, flags
            except OSError as exc:
                if flags == WINDOWS_DETACH or getattr(exc, "winerror", None) != 5:
                    raise


def restore_detached_env(run_dir):
    path = Path(run_dir) / ".runner-env"
    with path.open(encoding="utf-8") as handle:
        env = json.load(handle)
    path.unlink()
    os.environ.clear()
    os.environ.update(env)


def enter_detached(args):
    # RunAtLoad can execute before bootstrap returns. Never run a second copy after fallback.
    if args.launchd_start:
        ready = Path(args.run_dir, ".launchd-ready")
        cancelled = lambda: read_state(args.run_dir).get("detach") != "launchd"
        if not wait_until(lambda: ready.exists() or cancelled(), 25) or not ready.exists():
            return False
    if args.restore_env:
        restore_detached_env(args.run_dir)
    if args.runner_cwd:
        os.chdir(args.runner_cwd)
    return True


def add_detach_arguments(parser):
    parser.add_argument("--restore-env", action="store_true")
    parser.add_argument("--runner-cwd")
    parser.add_argument("--launchd-start", action="store_true")
    parser.add_argument("--creationflags", type=int, default=0, help=argparse.SUPPRESS)


def target_call(target, *args):
    env = dict(os.environ)
    keys = ("TMUX", "TMUX_TMPDIR", "TMPDIR") if target["mode"] == "tmux" else (
        "HERDR_SESSION", "HERDR_SOCKET_PATH", "HERDR_CONFIG_PATH", "XDG_CONFIG_HOME")
    for key in keys:
        env.pop(key, None)
    env.update(target.get("env", {}), LC_ALL="C")
    return supervisor_call([*target["argv"], *args], env=env)


def tmux_missing(result):
    return result.returncode == 1 and any(phrase in result.stderr.lower() for phrase in (
        "can't find session", "no server running", "no sessions", "no such file or directory"))


def missing_tmux_session(state):
    target = state.get("supervisor", {})
    if target.get("mode") != "tmux":
        return False
    try:
        return tmux_missing(target_call(target, "has-session", "-t", "=" + target["session"]))
    except (OSError, subprocess.TimeoutExpired):
        return False  # an unavailable probe is not evidence that the runner died


def cleanup_supervisor(run_dir, state):
    target = state.get("supervisor")
    marker = Path(run_dir) / ".supervisor-cleaned"
    if marker.exists():
        return ""
    mode = target["mode"] if target else state.get("detach")
    try:
        if target or mode == "systemd":
            (Path(run_dir) / ".runner-env").unlink(missing_ok=True)
        if not target:
            return ""
        if mode == "launchd":
            service = f"{target['domain']}/{target['label']}"
            (Path(run_dir) / "runner.plist").unlink(missing_ok=True)
            result = supervisor_call([*target["argv"], "bootout", service])
            if result.returncode and target.get("submit"):
                result = supervisor_call([*target["argv"], "remove", target["label"]])
            if result.returncode and result.returncode != 113 and not re.search(
                    r"(?:could not find (?:specified )?service|no such process|not found)", result.stderr, re.IGNORECASE):
                require_success(result)
        elif mode == "tmux":
            session = "=" + target["session"]
            result = target_call(target, "has-session", "-t", session)
            if not tmux_missing(result):
                require_success(result)
                result = target_call(target, "kill-session", "-t", session)
                if not tmux_missing(result):
                    require_success(result)
        elif mode == "herdr" and target.get("tab"):
            result = target_call(target, "tab", "close", target["tab"])
            response = read_json_text(result.stdout if not result.returncode else result.stderr)
            if result.returncode or "result" not in response:
                error = response.get("error") or {}
                if not isinstance(error, dict) or error.get("code") != "tab_not_found":
                    raise OSError(supervisor_error(result) if result.returncode else "invalid tab close result")
        if mode == "herdr" and target.get("entry"):
            (Path(run_dir) / target["entry"]).unlink(missing_ok=True)
        marker.touch()
        return ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        problem = f"{mode} cleanup: {exc}"
        print(f"agent_run: warning: {problem}", file=sys.stderr)
        return problem


def read_json_text(value):
    try:
        result = json.loads(value)
    except ValueError:
        return {}
    return result if isinstance(result, dict) else {}


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
        if not gdd_process.try_file_lock(handle):
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


def write_json(path, payload, *, progress_tick=False):
    """Retry WinError 5 from a poller before sacrificing atomicity, not the run."""
    tmp = f"{path}.{os.getpid()}.tmp"
    data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    write_text(tmp, data)
    replace_attempts = 3 if progress_tick else 40
    try:
        for attempt in range(replace_attempts):
            try:
                return os.replace(tmp, path)
            except PermissionError as exc:
                if getattr(exc, "winerror", None) != 5:
                    raise
                if attempt + 1 < replace_attempts:
                    time.sleep(0.05 + 0.05 * (attempt % 5))
        # A torn read is bad, a lost run is worse.
        write_text(path, data)
        if not progress_tick:
            print(f"gdd: warning: could not replace {path} (WinError 5); writing in place", file=sys.stderr)
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
    if sys.platform == "linux":
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
                if handle.read().rsplit(")", 1)[1].split()[0] in ("Z", "X"):
                    return False
        except (OSError, IndexError):
            pass
    elif _probe(os.kill, pid):
        try:
            result = gdd_process.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
            if result.stdout.strip().startswith("Z"):
                return False
        except OSError:
            pass
        return True
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


def group_alive(pid):
    if not _probe(os.killpg, pid):
        return False
    # killpg(..., 0) also succeeds for zombie-only groups whose parent has not reaped.
    try:
        result = gdd_process.run(["ps", "-ax", "-o", "pgid=", "-o", "stat="], capture_output=True, text=True)
    except OSError:
        return True
    rows = (line.split(None, 1) for line in result.stdout.splitlines())
    return bool(result.returncode or any(
        group == str(pid) and not status.startswith(("Z", "X"))
        for group, status in (row for row in rows if len(row) == 2)))


def terminate(pid, reap=lambda: None, *, single=False, recorded=None):
    """End the tree pid leads; True once gone. `reap` lets the parent collect its own zombie."""
    def reused():
        return bool(recorded and (current := identity(pid)) and current != recorded)

    def gone():
        reap()
        return reused() or not (pid_alive(pid) or (not IS_WINDOWS and not single and group_alive(pid)))

    if gone():
        return True
    if IS_WINDOWS:
        gdd_process.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return wait_until(gone, 5)
    for signum in (signal.SIGTERM, signal.SIGKILL):
        if reused():
            return True
        try:
            (os.kill if single else os.killpg)(pid, signum)
        except OSError:
            pass
        if wait_until(gone, 5):
            return True
    return False


def recorded_pid_alive(state, key):
    pid, recorded = state.get(key), state.get(f"{key}_identity")
    if not pid_alive(pid):
        return False
    current = identity(pid) if recorded else ""
    return not current or current == recorded


def run_alive(run_dir, state=None):
    """The runner or the agent recorded in state.json is alive (public: gdd.py imports it)."""
    state = read_state(run_dir) if state is None else state
    return any(recorded_pid_alive(state, key) for key in ("pid", "agent_pid"))


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
    if os.path.exists(os.path.join(run_dir, "finalized")):
        cleanup_supervisor(run_dir, state)
        return state, False
    if state.get("state") not in STATES:
        return state, False
    if state.get("backend") == "paseo" or not {"pid", "agent_pid"} & state.keys():
        return state, False  # another launcher's run: its liveness is not ours to settle
    if is_starting(state) and not (Path(run_dir, ".supervisor-started").exists() and missing_tmux_session(state)):
        return state, False
    if run_alive(run_dir, state):
        if missing_tmux_session(state):
            # A vanished session can leave the agent's separate process group behind.
            stop_run(run_dir)
            return read_state(run_dir), False
        return state, False
    if state["state"] != "running":  # terminal state published but the marker is missing
        write_text(os.path.join(run_dir, "exit.code"), f"{state.get('exit')}\n")
        write_text(os.path.join(run_dir, "finalized"), str(state.get("exit")))
        cleanup_supervisor(run_dir, state)
        return state, False
    if os.path.exists(os.path.join(run_dir, "stop")):
        state = finalize(run_dir, KILL_EXIT, note="stop requested and the runner is gone; recorded by a reader")
        cleanup_supervisor(run_dir, state)
        return state, False
    state = finalize(run_dir, -1, recovered=True)
    cleanup_supervisor(run_dir, state)
    return state, True


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
    """Return an empty string after finalization, or why the stop is unproven."""
    marker = os.path.join(run_dir, "finalized")

    def settled():
        if os.path.exists(marker):
            return True
        current = read_state(run_dir)
        return not (run_alive(run_dir, current) or is_starting(current))

    if not os.path.exists(marker):
        write_json(os.path.join(run_dir, "stop"), {"requested_at": now_iso(), "by": os.getpid()})
        wait_until(settled, knob("GDD_RUN_STOP_WAIT_SECONDS", 20))
    if os.path.exists(marker):
        cleanup_supervisor(run_dir, read_state(run_dir))
        return ""
    state, problems = read_state(run_dir), []
    for key in ("agent_pid", "pid"):
        pid, recorded = state.get(key), state.get(f"{key}_identity")
        if not pid_alive(pid):
            continue
        live = identity(pid)
        if not live or not recorded:
            if pid_alive(pid):
                problems.append(f"{key} {pid} not signalled (start time unverified)")
        elif live == recorded and not terminate(
                pid, recorded=recorded, single=key == "pid" and state.get("detach") in
                ("systemd", "launchd", "setsid", "tmux", "herdr")):
            problems.append(f"{key} {pid} still alive after TERM/KILL")
    if problems:
        return "; ".join(problems)
    if not os.path.exists(marker):
        state = finalize(run_dir, KILL_EXIT, note="stop requested; the runner did not finalize, so kill recorded the stop")
    cleanup_supervisor(run_dir, state)
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
    write_json(os.path.join(run_dir, "run.json"), {"agent": agent, "argv": command, "prompt": spec.prompt,
                                                   "cwd": cwd, "scrub_env": spec.scrub_env, "max_time_s": max_time,
                                                   "schema": args.schema})
    state = {
        "name": slug, "agent": agent, "state": "running", "exit": None, "cwd": cwd, "started": now_iso(),
        "ended": None, "duration_s": None, "run_dir": run_dir, "pid": None, "agent_pid": None,
        "session_id": args.resume or (command[command.index("--session-id") + 1] if "--session-id" in command else ""),
        "model": args.model,
        "thinking": args.thinking, "max_time": args.max_time, "resumed_from": args.resume,
        "spawn": {"creationflags": 0, "platform": sys.platform}}
    runner = [interpreter(), "-B", os.path.abspath(__file__), "_run", "--run-dir", run_dir]
    try:
        pid, _ = spawn_detached(runner, run_dir, cwd, child_env(spec.scrub_env), state, mode, launcher)
    except OSError as exc:
        finalize(run_dir, 127, note=f"could not spawn the runner: {exc}")
        die(f"start: could not spawn the runner: {exc}")
    seen = {}

    def started():
        seen.update(read_state(run_dir))
        runner_alive = recorded_pid_alive(seen, "pid") if seen.get("pid") == pid else pid_alive(pid)
        return (recorded_pid_alive(seen, "agent_pid") or seen.get("state") not in (None, "running")
                or (pid is not None and not runner_alive))

    if not wait_until(started, 20):
        problem = stop_run(run_dir)
        die(f"start: {mode}: no agent pid recorded within 20 s (see {run_dir})"
            + (f"; stop unconfirmed: {problem}" if problem else ""))
    if not seen.get("agent_pid"):
        if seen.get("state") == "running":
            effective_state(run_dir)
        die(f"start: {mode}: agent did not start: {seen.get('note') or seen.get('state')} (see {run_dir})")
    print(f"started: {slug}\n  agent     : {agent} (pid {seen['agent_pid']}, runner {seen.get('pid')})")
    print(f"  run dir   : {run_dir}")
    return 0


def runner_main(args):
    try:
        return run_agent(args)
    finally:
        # A concurrent kill/status may also recover this handle after finalization.
        state = read_state(args.run_dir)
        if state.get("pid") == os.getpid() and (
                state.get("detach") != "launchd" or Path(args.run_dir, "finalized").exists()):
            if state.get("detach") == "launchd":
                # The job can be terminated by bootout; write all terminal files first.
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
            cleanup_supervisor(args.run_dir, state)


def run_agent(args):
    run_dir = os.path.abspath(args.run_dir)
    if not enter_detached(args):
        return 1
    plan, state_path = read_json(os.path.join(run_dir, "run.json"), {}), os.path.join(run_dir, "state.json")
    spec, state = AGENTS[plan["agent"]], read_state(run_dir)
    state.update(pid=os.getpid(), pid_identity=identity(os.getpid()))
    state["spawn"]["creationflags"] = args.creationflags
    write_json(state_path, state)
    if os.path.exists(os.path.join(run_dir, "stop")):
        finalize(run_dir, KILL_EXIT, note="stop requested before agent startup")
        return 1
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
            log.handle.close()
            finalize(run_dir, 127, acc, note=f"agent did not start: {exc}")
            return 1
        state.update(agent_pid=process.pid, agent_pid_identity=identity(process.pid))
        try:
            write_json(state_path, state)
        except OSError:
            log.handle.close()
            terminate(process.pid, process.poll, recorded=state["agent_pid_identity"])
            process.stdout.close()
            if process.stdin:
                process.stdin.close()
            raise

        def read():
            try:
                with process.stdout:
                    for raw in process.stdout:
                        with lock:
                            log.write(raw)
                            fold_line(spec, acc, raw)
            finally:
                log.handle.close()

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
        note, next_write, stop, progress_failed = None, 0.0, False, False
        while (exit_code := process.poll()) is None:
            stop = requested.is_set() or os.path.exists(os.path.join(run_dir, "stop"))
            if stop or (deadline is not None and time.monotonic() >= deadline):
                exit_code = KILL_EXIT if stop else TIMEOUT_EXIT
                note = None if stop else f"max_time exceeded ({plan['max_time_s']:g} s)"
                if not terminate(process.pid, process.poll, recorded=state["agent_pid_identity"]):
                    note = f"{note or 'stopped'}; agent pid {process.pid} still alive after TERM/KILL"
                break
            if time.monotonic() >= next_write:
                with lock:
                    state.update(progress(acc), **event_stats(run_dir))
                try:
                    write_json(state_path, state, progress_tick=True)
                except OSError as exc:
                    if not progress_failed:
                        print(f"agent_run: warning: could not write progress to {state_path}: {exc}", file=sys.stderr)
                    progress_failed = True
                else:
                    progress_failed = False
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
    add_detach_arguments(internal)
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
