"""File handshakes and cleanup checks shared by the lifecycle tests and stubs."""

import json
import os
import queue
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from contextlib import chdir, contextmanager, nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path


def run_python_cli(script, *args, env, cwd=None, main=None):
    """Run the script's real CLI wrapper without another interpreter startup."""
    import io
    import runpy
    from unittest.mock import patch

    argv = [os.fspath(script), *args]
    stdout, stderr = io.StringIO(), io.StringIO()
    with (patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", argv),
          patch.object(sys, "path", [os.path.dirname(argv[0]), *sys.path]),
          patch.object(sys, "dont_write_bytecode", True),
          chdir(cwd) if cwd is not None else nullcontext(),
          redirect_stdout(stdout), redirect_stderr(stderr)):
        try:
            if main is None:
                runpy.run_path(argv[0], run_name="__main__")
                code = 0
            else:
                code = main() or 0
        except SystemExit as exc:
            code = exc.code or 0
    return subprocess.CompletedProcess(argv, code, stdout.getvalue(), stderr.getvalue())


def route_fixture(agent, case="ok"):
    from agent_run import route_package

    skills = Path(__file__).absolute().parents[3]
    return str(skills / route_package(agent) / "scripts" / "tests" / "fixtures" / f"{agent}.{case}.ndjson")


def transient_windows_error(exc):
    winerror = getattr(exc, "winerror", None)
    # CRT open() can collapse a Windows sharing failure to EACCES without winerror.
    return winerror in (5, 32, 33) or (os.name == "nt" and winerror is None and isinstance(exc, PermissionError))


def retry_windows(operation, deadline):
    while True:
        try:
            return operation()
        except OSError as exc:
            if not transient_windows_error(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.025)


def publish_json(path, value):
    path = Path(path)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        # Unlike mkstemp, exclusive open keeps the record's inherited umask.
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(value, handle)
        retry_windows(lambda: os.replace(temp, path), time.monotonic() + 2)
    finally:
        retry_windows(lambda: temp.unlink(missing_ok=True), time.monotonic() + 2)


def own_identity():
    """Record the stub's start time without importing the runner in each CLI process."""
    pid = os.getpid()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        times = [wintypes.FILETIME() for _ in range(4)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        if kernel.GetProcessTimes(wintypes.HANDLE(-1), *(ctypes.byref(t) for t in times)):
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return f"win:{created}" if created else ""
        return ""
    if sys.platform.startswith("linux"):
        try:
            data = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
            ticks = data.rsplit(")", 1)[1].split()[19]
            return f"linux:{ticks}" if ticks.isascii() and ticks.isdecimal() else ""
        except (OSError, IndexError):
            return ""

    from datetime import datetime, timezone

    import gdd_process

    try:
        result = gdd_process.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                                 env={**os.environ, "TZ": "UTC", "LC_ALL": "C"}, stdin=subprocess.DEVNULL)
        if result.returncode:
            return ""
        _, month, day, clock, year = result.stdout.split()
        month = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split().index(month) + 1
        hour, minute, second = map(int, clock.split(":"))
        started = datetime(int(year), month, int(day), hour, minute, second, tzinfo=timezone.utc)
        return f"ps-utc:{int(started.timestamp())}"
    except (OSError, ValueError):
        return ""


def wait_for_json(path, predicate, deadline):
    path = Path(path)
    while True:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if predicate(value):
                return value
            last = repr(value)[-2048:]
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            last = repr(exc)
        except OSError as exc:
            if not transient_windows_error(exc):
                raise
            last = repr(exc)
        if time.monotonic() >= deadline:
            tails = []
            directories = [path.parent, *sorted(path.parent.glob("runs/*/*"), reverse=True)[:2]]
            names = ("runner.log", "stderr.log", "events.ndjson", "cli.ndjson", "argv.ndjson")
            for log in (directory / name for directory in directories for name in names):
                try:
                    with log.open("rb") as handle:
                        handle.seek(max(0, os.fstat(handle.fileno()).st_size - 1024))
                        tails.append(f"{log}: {handle.read(1024).decode('utf-8', 'replace')}")
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    tails.append(f"{log}: {exc}")
            raise AssertionError(f"Timed out waiting for {path}; last error or value: {last}\n" + "\n".join(tails))
        time.sleep(0.05)


def finalized(run_dir, state):
    return (state.get("state") in ("done", "failed", "killed") and state.get("exit") is not None
            and (Path(run_dir) / "finalized").read_text(encoding="utf-8").strip() == str(state["exit"]))


def ready(child, seconds=10):
    lines = queue.Queue()
    seen = []

    def read():
        try:
            for _ in range(128):
                char = child.stdout.read(1)
                seen.append(char)
                if char in ("", "\n"):
                    break
            lines.put("".join(seen))
        except OSError as exc:
            lines.put(exc)

    threading.Thread(target=read, daemon=True).start()
    try:
        line = lines.get(timeout=seconds)
    except queue.Empty:
        raise AssertionError(f"PID {child.pid}: waiting for READY, saw {''.join(seen)!r} "
                             f"(exit={child.poll()})") from None
    if line != "READY\n":
        raise AssertionError(f"PID {child.pid}: expected READY, saw {line!r} (exit={child.poll()})")


def cleanup_child(children):
    issues = []
    for child in children:
        try:
            if child.poll() is None:
                # The retained handle owns this child; on POSIX it has not been reaped.
                child.kill()
                issues.append(f"PID {child.pid} required forced cleanup")
            child.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            issues.append(f"PID {child.pid}: {exc}")
        finally:
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError as exc:
                        issues.append(f"PID {child.pid}: {exc}")
    if issues:
        raise AssertionError("\n".join(issues))


def exited(pid, recorded):
    import agent_run

    return bool(recorded and (agent_run.identity_matches(recorded, agent_run.identity(pid)) is False
                              or not agent_run.pid_alive(pid)))


@contextmanager
def claim(path, seconds=5):
    import agent_run
    import gdd_process

    with Path(path).open("a+b") as handle:
        if not agent_run.wait_until(lambda: gdd_process.try_file_lock(handle), seconds):
            raise AssertionError(f"Held lock: {path}")
        yield


def check_locks(root):
    issues = []
    for path in Path(root).rglob("*"):
        if path.is_file() and (path.name == "refresh" or path.suffix == ".lock"):
            try:
                with claim(path):
                    pass
            except (OSError, AssertionError) as exc:
                issues.append(str(exc))
    if issues:
        raise AssertionError("\n".join(issues))


def remove_tree(path):
    def remove_readonly(operation, name, error):
        if (os.name == "nt" and getattr(error, "winerror", None) == 5
                and not os.stat(name).st_mode & stat.S_IWRITE):
            os.chmod(name, stat.S_IWRITE)
            operation(name)
        else:
            raise error

    if Path(path).exists():
        retry_windows(lambda: shutil.rmtree(path, onexc=remove_readonly), time.monotonic() + 5)


def check_processes(owned, seconds):
    import agent_run

    issues = []
    agent_run.wait_until(lambda: all(exited(*pair) for pair in owned), seconds)
    for (pid, recorded), (path, single) in owned.items():
        if exited(pid, recorded):
            continue
        if not recorded or agent_run.identity_matches(recorded, agent_run.identity(pid)) is not True:
            issues.append(f"{path}: PID {pid} identity unverified ({recorded!r})")
            continue
        issues.append(f"{path}: PID {pid} required forced cleanup")
        try:
            if not single and os.name != "nt":
                # The double-fork watcher belongs to the first fork's group, not its own PID.
                group = os.getpgid(pid)
                if group == os.getpgrp() or group != os.getsid(pid):
                    issues.append(f"{path}: PID {pid} has no isolated process group ({group})")
                    agent_run.terminate(pid, single=True, recorded=recorded)
                elif agent_run.identity(pid) == recorded:
                    # Check and signal are not atomic; macOS start times also have one-second resolution.
                    os.killpg(group, signal.SIGKILL)
                    if not agent_run.wait_until(lambda: not agent_run.group_alive(group), 5):
                        issues.append(f"{path}: process group {group} survived cleanup")
                if not agent_run.wait_until(lambda: exited(pid, recorded), 5):
                    issues.append(f"{path}: PID {pid} survived cleanup")
            elif not agent_run.terminate(pid, single=True, recorded=recorded) or not exited(pid, recorded):
                issues.append(f"{path}: PID {pid} survived cleanup")
        except OSError as exc:
            if not exited(pid, recorded):
                issues.append(f"{path}: PID {pid}: {exc}")
    if issues:
        raise AssertionError("\n".join(issues))


def stop_headless(root):
    import agent_run

    issues = []
    owned = {}
    for config in Path(root).rglob("run.json"):
        path = config.parent / "state.json"

        def remember(state):
            for key in ("agent_pid", "pid"):
                if pid := state.get(key):
                    owned[pid, state.get(f"{key}_identity")] = (path, key == "pid")
            return state

        try:
            state = wait_for_json(path, remember, time.monotonic() + 3)
            if not state.get("agent_pid") and state.get("exit") is None:
                # An interrupted dispatcher may have left its detached runner in startup.
                agent_run.write_json(path.parent / "stop", {"requested_at": agent_run.now_iso(), "by": os.getpid()})
                state = wait_for_json(path, lambda s: remember(s) and (s.get("agent_pid") or s.get("exit") is not None),
                                      time.monotonic() + 3)
            try:
                done = finalized(path.parent, state)
            except FileNotFoundError:
                done = False
            if not done and any(not exited(pid, state.get(f"{key}_identity"))
                                for key in ("pid", "agent_pid") if (pid := state.get(key))):
                agent_run.write_json(path.parent / "stop", {"requested_at": agent_run.now_iso(), "by": os.getpid()})
        except (OSError, AssertionError) as exc:
            issues.append(str(exc))

    try:
        check_processes(owned, agent_run.STOP_WAIT_SECONDS)
    except AssertionError as exc:
        issues.append(str(exc))
    if issues:
        raise AssertionError("\n".join(issues))
