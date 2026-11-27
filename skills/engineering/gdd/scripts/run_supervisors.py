"""Select, launch, and clean up the detach supervisor that owns a run."""

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gdd_process
import skill_config

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

WINDOWS_DETACH = gdd_process.NO_WINDOW | gdd_process.NEW_GROUP
# Ubuntu 22.04 leaves standard support in 2027-04; then move the floor to 24.04's 3.4.
TMUX_MIN_VERSION = (3, 2, "a")
SUPERVISOR_ENV = {
    "tmux": ("TMUX_TMPDIR", "TMPDIR"),
    "herdr": ("HERDR_SESSION", "HERDR_SOCKET_PATH", "HERDR_CONFIG_PATH", "XDG_CONFIG_HOME"),
}


def detach_config():
    try:
        requested = skill_config.resolve("gdd", "GDD_RUN_DETACH", default="auto")
    except skill_config.ConfigError as exc:
        raise ValueError(f"GDD_RUN_DETACH: {exc}") from exc
    if requested in SUPERVISOR_ENV and os.environ.get("GDD_RUN_DETACH") != requested:
        raise ValueError(f"GDD_RUN_DETACH={requested} must be set in the environment")
    return requested


def dispatcher_umask():
    # Called by the single-threaded dispatcher. Never make its mask more permissive.
    mask = os.umask(0o777)
    os.umask(mask)
    return mask


def systemd_argv(launcher, unit, cwd, log, runner):
    # Transient unit properties carry literal paths; only ExecStart expands dollar variables.
    return [launcher, "--user", "--collect", "--unit", unit, "--service-type=exec",
            "--no-ask-password", f"--working-directory={cwd}", f"--property=UMask={dispatcher_umask():04o}",
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


def herdr_response(result):
    require_success(result)
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or not isinstance(response.get("result"), dict):
        raise ValueError("expected a Herdr JSON result")
    return response["result"]


def restore_detached_env(run_dir):
    path = Path(run_dir) / ".runner-env"
    with path.open(encoding="utf-8") as handle:
        env = json.load(handle)
    path.unlink()
    os.environ.clear()
    os.environ.update(env)


def add_detach_arguments(parser):
    for flag in ("--restore-env", "--launchd-start"):
        parser.add_argument(flag, action="store_true")
    parser.add_argument("--runner-cwd")
    parser.add_argument("--runner-umask", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--creationflags", type=int, default=0, help=argparse.SUPPRESS)


def tmux_missing(result):
    return result.returncode == 1 and any(phrase in result.stderr.lower() for phrase in (
        "can't find session", "no server running", "no sessions", "no such file or directory"))


def read_json_text(value):
    try:
        result = json.loads(value)
    except ValueError:
        return {}
    return result if isinstance(result, dict) else {}


def unit_name(slug):
    return f"gdd-{slug}-{uuid.uuid4().hex[:12]}"


@dataclass
class _Launch:
    runner: list[str]
    run_dir: Path
    cwd: str
    env: dict
    state: dict
    launcher: str | None
    herdr_python: str | None = None


@dataclass(frozen=True)
class _Strategy:
    start: Callable[[_Launch], tuple[int | None, int] | None]
    target: Callable[[_Launch], dict] | None = None
    cleanup: Callable[[Path, dict], None] | None = None
    restore_env: bool = False


def _supervisor_target(mode, launcher):
    return {"mode": mode, "argv": [launcher],
            "env": {key: os.environ[key] for key in SUPERVISOR_ENV[mode] if key in os.environ}}


def _runner_options(env, setting):
    return [arg for key in ("PYTHONUNBUFFERED", "PYTHONPATH", "NOWINDOW_GUARD_LOG")
            if key in env or key == "PYTHONUNBUFFERED" for arg in (setting, f"{key}={env.get(key, '1')}")]


def _launchd_target(launch):
    if not launch.launcher:
        return {}
    suffix = uuid.uuid4().hex[:12]
    return {"mode": "launchd", "argv": [launch.launcher], "domain": f"gui/{os.getuid()}",
            "label": f"gdd.{launch.state['name']}.{suffix}"}


def _tmux_target(launch):
    target = _supervisor_target("tmux", launch.launcher)
    if socket := os.environ.get("TMUX", "").partition(",")[0]:
        target["argv"] += ["-S", socket]
    suffix = uuid.uuid4().hex[:12]
    target["session"] = re.sub(r"[^a-zA-Z0-9_-]", "-", f"gdd-{launch.state['name']}-{suffix}")
    return target


def _herdr_target(launch):
    target = _supervisor_target("herdr", launch.launcher)
    target["entry"] = f".runner-herdr-{uuid.uuid4().hex[:12]}.py"
    return target


def _start_setsid(launch):
    return gdd_process.daemonize(launch.runner, launch.cwd, launch.env, launch.run_dir / "runner.log"), 0


def _start_windows(launch):
    with (launch.run_dir / "runner.log").open("ab", buffering=0) as log:
        for creationflags in (WINDOWS_DETACH | gdd_process.BREAKAWAY, WINDOWS_DETACH):
            try:
                process = gdd_process.popen([*launch.runner, "--creationflags", str(creationflags)], cwd=launch.cwd,
                                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                            env=launch.env, creationflags=creationflags)
                return process.pid, creationflags
            except OSError as exc:
                if creationflags == WINDOWS_DETACH or getattr(exc, "winerror", None) != 5:
                    raise


class RunSupervisors:
    """Use a per-mode adapter for launch and for cleanup from persisted state."""

    def __init__(self, runtime):
        self.runtime = runtime
        self._strategies = {
            "systemd": _Strategy(self._start_systemd, restore_env=True),
            "launchd": _Strategy(self._start_launchd, _launchd_target, self._cleanup_launchd),
            "setsid": _Strategy(_start_setsid),
            "windows": _Strategy(_start_windows),
            "tmux": _Strategy(self._start_tmux, _tmux_target, self._cleanup_tmux, restore_env=True),
            "herdr": _Strategy(self._start_herdr, _herdr_target, self._cleanup_herdr, restore_env=True),
        }

    def select_detach(self, requested):
        modes = ("auto", *self._strategies)
        if requested not in modes:
            raise ValueError(f"GDD_RUN_DETACH={requested!r}: expected {', '.join(modes)}")
        if requested in SUPERVISOR_ENV:
            if requested == "tmux" and self.runtime.IS_WINDOWS:
                raise ValueError("GDD_RUN_DETACH=tmux is not supported on native Windows")
            launcher = shutil.which(requested)
            if not launcher:
                raise ValueError(f"GDD_RUN_DETACH={requested}: {requested} executable not found on PATH")
            if requested == "tmux":
                self.runtime.check_tmux_version(launcher)
            else:
                self._herdr_executable(self.runtime.runner_interpreter())
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
        native = "windows" if self.runtime.IS_WINDOWS else "setsid"
        if requested not in ("auto", native):
            raise ValueError(f"GDD_RUN_DETACH={requested} is not supported on {sys.platform}")
        return native, None

    def check_tmux_version(self, launcher):
        try:
            found = require_success(self.runtime.supervisor_call([launcher, "-V"])).stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"tmux: cannot check version: {exc}") from exc
        if found == "tmux master":
            return
        match = re.fullmatch(r"tmux (?:next-)?([0-9]+)\.([0-9]+)([a-z]*)", found)
        if match and (int(match[1]), int(match[2]), match[3]) >= TMUX_MIN_VERSION:
            return
        minimum = "{}.{}{}".format(*TMUX_MIN_VERSION)
        raise ValueError(f"tmux: found {found!r}; requires tmux {minimum} or newer")

    def _herdr_executable(self, path):
        executable = os.path.abspath(path)
        if self.runtime.IS_WINDOWS:
            executable = executable.replace("\\", "/")
        if not re.fullmatch(r"[A-Za-z0-9_./:\-]+", executable):
            raise OSError(f"GDD_RUN_DETACH=herdr cannot use Python at {path!r}; "
                          "install Python at a path without spaces or special characters "
                          "(use ASCII letters, digits, underscores, hyphens and dots in path components)")
        return executable

    def spawn_detached(self, runner, run_dir, cwd, env, state, mode, launcher=None):
        run_dir = Path(run_dir)
        executable = self._herdr_executable(runner[0]) if mode == "herdr" else None
        launch = _Launch(runner, run_dir, cwd, env, state, launcher, executable)
        strategy = self._strategies.get(mode, self._strategies["windows"])
        state["detach"] = mode
        if state.get("backend") != "paseo":
            state["backend"] = mode
        target = strategy.target(launch) if strategy.target else None
        if target:
            state["supervisor"] = target
        else:
            state.pop("supervisor", None)
        if mode == "systemd":
            state["unit"] = unit_name(state["name"])
        self.runtime.write_json(run_dir / "state.json", state)
        if not (strategy.restore_env or mode == "launchd"):
            return strategy.start(launch)
        try:
            if strategy.restore_env:
                save_detached_env(run_dir, env)
            strategy.start(launch)
            return None, 0
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
            (run_dir / ".runner-env").unlink(missing_ok=True)
            if mode != "systemd":
                self.runtime.cleanup_supervisor(run_dir, state)
            if mode == "launchd":
                state["detach_fallback"] = f"launchd: {exc}"
                return self.spawn_detached(runner, run_dir, cwd, env, state, "setsid")
            raise OSError(f"{mode}: {exc}") from exc

    def _start_systemd(self, launch):
        argv = systemd_argv(launch.launcher, launch.state["unit"], launch.cwd,
                            launch.run_dir / "runner.log", launch.runner)
        require_success(self.runtime.supervisor_call(argv))

    def _start_launchd(self, launch):
        if not launch.launcher:
            raise OSError("launchctl executable not found on PATH")
        runner, run_dir, cwd, env, state = launch.runner, launch.run_dir, launch.cwd, launch.env, launch.state
        target = state["supervisor"]
        plist = run_dir / "runner.plist"
        runner = [*runner, "--launchd-start"]
        launcher, domain, label = target["argv"][0], target["domain"], target["label"]
        umask = dispatcher_umask()
        with os.fdopen(private_file(plist), "wb") as stream:
            plistlib.dump({"Label": label, "ProgramArguments": runner, "WorkingDirectory": cwd,
                           "EnvironmentVariables": env, "StandardOutPath": str(run_dir / "runner.log"),
                           "StandardErrorPath": str(run_dir / "runner.log"), "AbandonProcessGroup": True,
                           "RunAtLoad": True, "Umask": umask}, stream)
        result = self.runtime.supervisor_call([launcher, "bootstrap", domain, str(plist)])
        if result.returncode and (result.returncode == 64 or re.search(
                r"(?:unknown|unrecognized|unsupported) (?:sub)?command", result.stderr, re.IGNORECASE)):
            target["submit"] = True
            self.runtime.write_json(run_dir / "state.json", state)
            save_detached_env(run_dir, env)
            result = self.runtime.supervisor_call([launcher, "submit", "-l", label, "-o", str(run_dir / "runner.log"),
                                      "-e", str(run_dir / "runner.log"), "--", *runner, "--restore-env",
                                      "--runner-cwd", cwd, "--runner-umask", str(umask)])
        require_success(result)
        (run_dir / ".launchd-ready").touch()

    def _start_tmux(self, launch):
        target = launch.state["supervisor"]
        options = _runner_options(launch.env, "-e")
        require_success(self._target_call(target, "new-session", "-d", "-s", target["session"],
                                          "-c", launch.cwd, *options, "--", *launch.runner, "--restore-env"))
        (launch.run_dir / ".supervisor-started").touch()

    def _start_herdr(self, launch):
        target, run_dir = launch.state["supervisor"], launch.run_dir
        # Herdr sends shell input. Keep run arguments in the private entry, not the command.
        with os.fdopen(private_file(run_dir / target["entry"]), "w", encoding="utf-8") as entry:
            entry.write("import os, runpy, sys\n"
                        f"sys.argv = {ascii([*launch.runner[2:], '--restore-env', '--runner-cwd', launch.cwd])}\n"
                        "sys.path[0] = os.path.dirname(os.path.abspath(sys.argv[0]))\n"
                        "os.unlink(__file__)\n"
                        "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        options = _runner_options(launch.env, "--env")
        result = herdr_response(self._target_call(target, "tab", "create", "--no-focus", "--cwd", str(run_dir),
                                                  "--label", f"gdd-{launch.state['name']}", *options))
        for key, source in (("tab", "tab"), ("pane", "root_pane")):
            value = result[source][f"{key}_id"]
            if not isinstance(value, str) or not value or value.startswith("-"):
                raise ValueError(f"invalid Herdr {key} ID")
            target[key] = value
            self.runtime.write_json(run_dir / "state.json", launch.state)
        require_success(self._target_call(target, "pane", "run", target["pane"],
                                          f"{launch.herdr_python} -B {target['entry']}"))

    def enter_detached(self, args):
        if args.runner_umask is not None:
            os.umask(args.runner_umask)
        # RunAtLoad can execute before bootstrap returns. Never run a second copy after fallback.
        if args.launchd_start:
            ready = Path(args.run_dir, ".launchd-ready")
            cancelled = lambda: self.runtime.read_state(args.run_dir).get("detach") != "launchd"
            if not self.runtime.wait_until(lambda: ready.exists() or cancelled(), 25) or not ready.exists():
                return False
        if args.restore_env:
            restore_detached_env(args.run_dir)
        if args.runner_cwd:
            os.chdir(args.runner_cwd)
        return True

    def _target_call(self, target, *args):
        mode = target["mode"]
        keys = (*SUPERVISOR_ENV[mode], "TMUX") if mode == "tmux" else SUPERVISOR_ENV["herdr"]
        env = {key: value for key, value in os.environ.items() if key not in keys}
        env.update(target.get("env", {}), LC_ALL="C")
        return self.runtime.supervisor_call([*target["argv"], *args], env=env)

    def missing_tmux_session(self, state):
        target = state.get("supervisor", {})
        if target.get("mode") != "tmux":
            return False
        try:
            return tmux_missing(self._target_call(target, "has-session", "-t", "=" + target["session"]))
        except (OSError, subprocess.TimeoutExpired):
            return False  # an unavailable probe is not evidence that the runner died

    def cleanup_supervisor(self, run_dir, state):
        run_dir = Path(run_dir)
        target = state.get("supervisor")
        marker = run_dir / ".supervisor-cleaned"
        if marker.exists():
            return ""
        mode = target["mode"] if target else state.get("detach")
        try:
            if target or mode == "systemd":
                (run_dir / ".runner-env").unlink(missing_ok=True)
            if not target:
                return ""
            strategy = self._strategies.get(mode) if isinstance(mode, str) else None
            if strategy and strategy.cleanup:
                strategy.cleanup(run_dir, target)
            marker.touch()
            return ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            problem = f"{mode} cleanup: {exc}"
            print(f"agent_run: warning: {problem}", file=sys.stderr)
            return problem

    def _cleanup_launchd(self, run_dir, target):
        service = f"{target['domain']}/{target['label']}"
        (run_dir / "runner.plist").unlink(missing_ok=True)
        result = self.runtime.supervisor_call([*target["argv"], "bootout", service])
        if result.returncode and target.get("submit"):
            result = self.runtime.supervisor_call([*target["argv"], "remove", target["label"]])
        if result.returncode and result.returncode != 113 and not re.search(
                r"(?:could not find (?:specified )?service|no such process|not found)", result.stderr, re.IGNORECASE):
            require_success(result)

    def _cleanup_tmux(self, _run_dir, target):
        session = "=" + target["session"]
        for command in ("has-session", "kill-session"):
            result = self._target_call(target, command, "-t", session)
            if tmux_missing(result):
                break
            require_success(result)

    def _cleanup_herdr(self, run_dir, target):
        if target.get("tab"):
            result = self._target_call(target, "tab", "close", target["tab"])
            response = read_json_text(result.stdout if not result.returncode else result.stderr)
            if result.returncode or "result" not in response:
                error = response.get("error") or {}
                if not isinstance(error, dict) or error.get("code") != "tab_not_found":
                    raise OSError(supervisor_error(result) if result.returncode else "invalid tab close result")
        if entry := target.get("entry"):
            (run_dir / entry).unlink(missing_ok=True)
