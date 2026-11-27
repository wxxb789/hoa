"""Run-directory claims, state files, and process identity and termination."""

import json
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import gdd_process

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

STOP_WAIT_SECONDS = 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLUG_RE = re.compile(r"[^a-z0-9._-]+")
STATES = ("running", "done", "failed", "killed")
PID_KEYS = ("pid", "agent_pid")


def knob(name, default):
    try:
        value = float(os.environ.get(name) or "")
    except ValueError:
        return default
    return value if value > 0 else default


def start_lock_slug(slug, is_windows):
    return slug.rstrip(".") if is_windows else slug


def make_run_directory(run_dir):
    parent = os.path.dirname(run_dir)
    while True:
        os.makedirs(parent, exist_ok=True)
        try:
            os.mkdir(run_dir)
            return
        except FileNotFoundError:
            # Collector rmdir won the gap between creating the date and claiming the slug.
            if not Path(parent).parent.is_dir():
                raise


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def read_state(run_dir):
    state = read_json(os.path.join(run_dir, "state.json"), {})
    return state if isinstance(state, dict) else {}


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def sanitize(value):
    slug = SLUG_RE.sub("-", str(value or "").lower()).strip("-")[:48]
    return "" if slug in (".", "..") else slug


def state_age_seconds(state):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(state["started"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return float("inf")


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


def proc_fields(pid):
    with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
        return handle.read().rsplit(")", 1)[1].split()


def identity_matches(recorded, current):
    """True/False only for comparable identities; legacy local-time ps strings are unknown."""
    pattern = r"(linux|win|ps-utc):(0|[1-9][0-9]*)"
    before = re.fullmatch(pattern, recorded) if isinstance(recorded, str) else None
    after = re.fullmatch(pattern, current)
    if before and after and before[1] == after[1]:
        return before[2] == after[2]
    return None


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


def is_starting(state):
    return state.get("pid") is None and state_age_seconds(state) < knob("GDD_RUN_START_GRACE_SECONDS", 60)


class RunProcess:
    """Use the runner's shared process and state operations for composite actions."""

    def __init__(self, runtime):
        self.runtime = runtime

    @contextmanager
    def slug_start_lock(self, root, slug):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        lock_slug = start_lock_slug(slug, self.runtime.IS_WINDOWS)
        deadline = time.monotonic() + knob("GDD_RUN_STOP_WAIT_SECONDS", STOP_WAIT_SECONDS)
        # Keep the lock file: unlinking would allow another process to lock a different inode.
        with (root / f"{lock_slug}.start.lock").open("a+b") as handle:
            while not gdd_process.try_file_lock(handle):
                if time.monotonic() >= deadline or not self.runtime.gc_claiming(root, lock_slug):
                    if not gdd_process.try_file_lock(handle):
                        self.runtime.die(f"start: run '{slug}' is already starting")
                    break
                time.sleep(0.01)
            yield  # closing the file releases the kernel lock on both platforms

    def write_json(self, path, payload, *, progress_tick=False):
        """Retry WinError 5 from a poller before sacrificing atomicity, not the run."""
        tmp = f"{path}.{os.getpid()}.tmp"
        data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        self.runtime.write_text(tmp, data)
        replace_attempts = 40
        try:
            for attempt in range(replace_attempts):
                try:
                    return os.replace(tmp, path)
                except PermissionError as exc:
                    if getattr(exc, "winerror", None) != 5:
                        raise
                    if attempt + 1 < replace_attempts:
                        # Keep all 40 chances, but cap the tick's backoff at 0.975 seconds.
                        time.sleep(0.025 if progress_tick else 0.05 + 0.05 * (attempt % 5))
            # A torn read is bad, a lost run is worse.
            self.runtime.write_text(path, data)
            if not progress_tick:
                print(f"gdd: warning: could not replace {path} (WinError 5); writing in place", file=sys.stderr)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def interpreter(self):
        """python.exe, not pythonw.exe: a pythonw parent loses the std handles children need."""
        console = os.path.join(os.path.dirname(sys.executable), "python.exe")
        return console if self.runtime.IS_WINDOWS and os.path.exists(console) else sys.executable


    def runner_interpreter(self):
        """interpreter() for gdd's own stdlib-only detached runners, whose Popen pid is recorded as theirs.

        On Windows a venv's python.exe (`uv run`, `python -m venv`) is a launcher that re-spawns the base
        interpreter, so its pid names the launcher. User-supplied `.py` agents keep interpreter() and the venv.
        """
        base = getattr(sys, "_base_executable", sys.executable)
        console = os.path.join(os.path.dirname(base), "python.exe")
        return console if self.runtime.IS_WINDOWS and os.path.exists(console) else self.runtime.interpreter()

    def wait_until(self, predicate, seconds):
        deadline = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.runtime.POLL)
        return True

    def pid_alive(self, pid):
        """Windows: OpenProcess + GetExitCodeProcess (os.kill reads AccessDenied as dead)."""
        if isinstance(pid, str) and pid.isdigit():
            pid = int(pid)
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return False
        if self.runtime.IS_WINDOWS:
            code = ctypes.c_ulong()
            return bool(_windows_query(pid, lambda k, h: k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259))
        if sys.platform == "linux":
            try:
                if proc_fields(pid)[0] in ("Z", "X"):
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

    def identity(self, pid):
        """Process start time (Linux stat field 22, macOS ps lstart, Windows creation time), or ""."""
        if not self.runtime.pid_alive(pid):
            return ""
        if self.runtime.IS_WINDOWS:
            times = [wintypes.FILETIME() for _ in range(4)]
            ok = _windows_query(pid, lambda k, h: k.GetProcessTimes(h, *(ctypes.byref(t) for t in times)))
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return f"win:{created}" if ok and created else ""
        if sys.platform.startswith("linux"):
            try:
                ticks = proc_fields(pid)[19]
                return f"linux:{ticks}" if re.fullmatch(r"[0-9]+", ticks) else ""
            except (OSError, IndexError):
                return ""
        try:
            # BSD ps formats lstart in the child's local time; neither that zone nor the
            # parent's locale should affect the stored epoch seconds.
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

    def terminate(self, pid, reap=lambda: None, *, single=False, recorded=None):
        """End the tree pid leads; True once gone. `reap` lets the parent collect its own zombie."""
        def reused():
            return bool(recorded) and identity_matches(recorded, self.runtime.identity(pid)) is False

        def gone():
            reap()
            return reused() or not (self.runtime.pid_alive(pid) or (not self.runtime.IS_WINDOWS and not single and group_alive(pid)))

        if gone():
            return True
        if self.runtime.IS_WINDOWS:
            gdd_process.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self.runtime.wait_until(gone, 5)
        for signum in (signal.SIGTERM, signal.SIGKILL):
            if reused():
                return True
            try:
                (os.kill if single else os.killpg)(pid, signum)
            except OSError:
                pass
            if self.runtime.wait_until(gone, 5):
                return True
        return False

    def recorded_pid_alive(self, state, key):
        pid, recorded = state.get(key), state.get(f"{key}_identity")
        if not self.runtime.pid_alive(pid):
            return False
        current = self.runtime.identity(pid) if recorded else ""
        return identity_matches(recorded, current) is not False


    def run_alive(self, run_dir, state=None):
        """The runner or the agent recorded in state.json is alive."""
        state = read_state(run_dir) if state is None else state
        return any(self.recorded_pid_alive(state, key) for key in PID_KEYS)

    def observed_state(self, run_dir, state):
        """Read-only view for gdd.py and delivery-state.py: the recorded state, or "stale" for a
        `running` run with nothing alive, no `finalized` marker and no startup grace left. A custom
        launcher that records no pid keys at all cannot be probed, so its recorded state stands."""
        recorded = str(state.get("state") or "?")
        if (recorded != "running" or state.keys().isdisjoint(PID_KEYS)
                or os.path.exists(os.path.join(run_dir, "finalized"))
                or self.runtime.run_alive(run_dir, state) or is_starting(state)):
            return recorded
        return "stale"
