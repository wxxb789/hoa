#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""agent_run.py — one detached runner for every headless agent CLI gdd dispatches."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

# Keep the lexical install path: a linked skill's canonical directory may have different siblings.
SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
SKILLS_ROOT = SCRIPT_DIR.parents[1]
ROUTE_SNAPSHOT = "route.py"
sys.path.insert(0, str(SCRIPT_DIR))
# Route modules import this runner, including when it was launched as __main__.
sys.modules.setdefault("agent_run", sys.modules[__name__])
import gdd_process
import skill_config
import stage_result
from run_gc import RunGC, gc_claiming as gc_claiming
from run_process import (
    DATE_RE,
    PID_KEYS,
    STATES,
    STOP_WAIT_SECONDS,
    RunProcess,
    group_alive as group_alive,
    identity_matches,
    is_starting,
    knob,
    make_run_directory,
    read_json,
    read_state,
    sanitize,
    state_age_seconds,
    write_text,
)
from run_supervisors import (
    SUPERVISOR_ENV as SUPERVISOR_ENV,
    WINDOWS_DETACH as WINDOWS_DETACH,
    RunSupervisors,
    add_detach_arguments,
    detach_config,
    private_file,
    restore_detached_env as restore_detached_env,
    supervisor_call as supervisor_call,
    tmux_missing as tmux_missing,
    unit_name as unit_name,
)

IS_WINDOWS = gdd_process.IS_WINDOWS
KILLED_EXITS = (130, -2, 137, -9, 143, -15)
KILL_EXIT, TIMEOUT_EXIT = 143, 124
POLL, PROGRESS_SECONDS = 0.25, 2.0
CMD_UNSAFE = re.compile(r'[\r\n"&|<>^()%!]')
_RENAMED = ("EVENTS_MAX_BYTES", "START_GRACE_SECONDS", "STOP_WAIT_SECONDS", "DRAIN_TIMEOUT_SECONDS")
RETIRED = {
    "OMP_RUN_ROOT": "GDD_RUN_ROOT", "DSH_RUN_ROOT": "GDD_RUN_ROOT",
    "OMP_LEDGER": "nothing (no runner ledger; `list` shows every run)",
    "OMP_RUN_BACKEND": "GDD_RUN_DETACH", "DSH_RUN_SETTLE_WAIT_SECONDS": "nothing",
    **{f"{p}_RUN_{k}": f"GDD_RUN_{k}" for p in ("OMP", "DSH") for k in _RENAMED},
}

# Keep the runner's import surface and use its live bindings for shared OS and I/O operations.
_runtime = sys.modules[__name__]
_process = RunProcess(_runtime)
identity = _process.identity
interpreter = _process.interpreter
observed_state = _process.observed_state
pid_alive = _process.pid_alive
recorded_pid_alive = _process.recorded_pid_alive
run_alive = _process.run_alive
runner_interpreter = _process.runner_interpreter
slug_start_lock = _process.slug_start_lock
terminate = _process.terminate
wait_until = _process.wait_until
write_json = _process.write_json

_supervisors = RunSupervisors(_runtime)
check_tmux_version = _supervisors.check_tmux_version
cleanup_supervisor = _supervisors.cleanup_supervisor
enter_detached = _supervisors.enter_detached
missing_tmux_session = _supervisors.missing_tmux_session
select_detach = _supervisors.select_detach
spawn_detached = _supervisors.spawn_detached

_gc = RunGC(_runtime, os.path.abspath(__file__))
gc_runs = _gc.gc_runs
spawn_auto_gc = _gc.spawn_auto_gc


def die(message):
    print(f"agent_run: {message}", file=sys.stderr)
    sys.exit(1)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def run_root():
    home = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    try:
        root = skill_config.resolve("gdd", "GDD_RUN_ROOT", default=os.path.join(home, "gdd", "runs"))
    except skill_config.ConfigError as exc:
        die(f"GDD_RUN_ROOT: {exc}")
    return os.path.abspath(os.path.expanduser(root))


def warn_wsl(binary, run_dir):
    if sys.platform != "linux" or "microsoft" not in os.uname().release.lower():
        return
    if Path(binary).suffix.lower() == ".exe":
        print(f"gdd: warning: WSL is using Windows CLI {binary} through interop; prefer a native Linux CLI",
              file=sys.stderr)
    if run_dir is not None and re.match(r"^/mnt/[a-z](?:/|$)", Path(run_dir).resolve().as_posix(), re.IGNORECASE):
        print(f"gdd: warning: WSL run directory {run_dir} is on a Windows drive; prefer the Linux filesystem",
              file=sys.stderr)


def cmd_gc(args):
    return gc_runs(args.run_root, args.now)


def new_acc():
    return {"session_id": "", "answer": "", "turns": 0, "tool_calls": 0, "cost_usd": None,
            "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "total_tokens": 0},
            "error": "", "success_marker": None, "structured": None, "report": ""}


def text_parts(content):
    if not isinstance(content, list):
        return ""
    return "".join(p.get("text") or "" for p in content if isinstance(p, dict) and p.get("type") == "text")


def fold_message_events(acc, event):
    """Fold the message-event protocol shared by OMP, Pi, and Omo."""
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



def tokens(usage, input_key, output_key, cache_key, *also_total):
    """Normalized usage; total = input + output + the `also_total` keys."""
    usage = usage if isinstance(usage, dict) else {}
    count = {key: int(usage.get(key) or 0) for key in (input_key, output_key, cache_key, *also_total)}
    return {"input_tokens": count[input_key], "output_tokens": count[output_key], "cache_read_tokens": count[cache_key],
            "total_tokens": count[input_key] + count[output_key] + sum(count[key] for key in also_total)}


def flags(*pairs):
    """[flag, value, ...] for every pair whose value is set: unset options are never passed."""
    return [token for flag, value in pairs if value for token in (flag, value)]


def message_succeeded(marker):
    return marker not in (None, "error", "aborted", "length")


@dataclass(frozen=True)
class Route:
    """Contract for ROUTE exports in sibling gdd-route-*/scripts/route.py modules."""

    name: str
    prompt: Literal["stdin", "argv"]  # "argv" appends the prompt last
    argv: Callable[[argparse.Namespace, list[str]], list[str]]  # flags after the binary
    fold: Callable[[dict[str, Any], dict[str, Any]], None]
    marker: str  # diagnostic description of the exit-0 success marker
    succeeded: Callable[[object], bool]
    scrub_env: tuple[str, ...] = ()
    prepare: Callable[[argparse.Namespace], None] | None = None  # pre-start validation
    legacy: tuple[Literal["backend", "profile", "session_id"], ...] = ()
    windows_native: bool = False  # never cross cmd.exe's batch shim boundary


class RouteError(ValueError):
    pass


def skills_root() -> Path:
    value = skill_config.resolve("gdd", "GDD_SKILLS_ROOT", default=str(SKILLS_ROOT))
    return Path(os.path.abspath(os.path.expanduser(value)))


def route_package(name: str) -> str:
    return "gdd-route-cc" if name == "claude" else f"gdd-route-{name}"


def discover_routes(root: Path | None = None) -> dict[str, Path]:
    root = skills_root() if root is None else root
    installed = {}
    for path in sorted(root.glob("gdd-route-*/scripts/route.py")):
        package = path.parents[1].name
        name = "claude" if package == "gdd-route-cc" else package.removeprefix("gdd-route-")
        if route_package(name) == package and path.is_file():
            installed[name] = path
    return installed


def installed_route(name: str, root: Path) -> Path:
    installed = discover_routes(root)
    if name not in installed:
        package = route_package(name)
        raise RouteError(f"agent {name!r} has no installed route (scanned: {root}; "
                         f"installed: {', '.join(installed) or 'none'}); install for the same host (-a) and scope as gdd: "
                         f"npx skills add wxxb789/hoa -s {package} (project) or "
                         f"npx skills add wxxb789/hoa -g -s {package} (global). "
                         "For a resolved runner path, set GDD_SKILLS_ROOT to the host skills root")
    return installed[name]


def route_source(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RouteError(f"{path}: could not read ROUTE: {exc}") from exc


def parse_route(name: str, path: Path, source: bytes) -> Route:
    exports = {"__name__": "gdd_route", "__file__": str(path)}
    try:
        exec(compile(source, str(path), "exec"), exports)
    except Exception as exc:
        raise RouteError(f"{path}: could not load ROUTE: {exc}") from exc
    if "ROUTE" not in exports:
        raise RouteError(f"{path}: missing ROUTE export")
    route = exports["ROUTE"]
    if not isinstance(route, Route):
        raise RouteError(f"{path}: invalid ROUTE: expected agent_run.Route")
    checks = (
        ("name", route.name == name, f"expected {name!r} to match the skill directory"),
        ("prompt", route.prompt in ("stdin", "argv"), "expected 'stdin' or 'argv'"),
        ("argv", callable(route.argv), "expected a callable"),
        ("fold", callable(route.fold), "expected a callable"),
        ("marker", isinstance(route.marker, str) and route.marker.strip(), "expected a non-empty string"),
        ("succeeded", callable(route.succeeded), "expected a callable"),
        ("scrub_env", isinstance(route.scrub_env, tuple) and all(isinstance(key, str) and key for key in route.scrub_env),
         "expected a tuple of environment names"),
        ("prepare", route.prepare is None or callable(route.prepare), "expected a callable or None"),
        ("legacy", isinstance(route.legacy, tuple) and all(key in ("backend", "profile", "session_id")
                                                         for key in route.legacy),
         "expected a tuple of legacy start option names"),
        ("windows_native", isinstance(route.windows_native, bool), "expected a bool"),
    )
    for field, valid, detail in checks:
        if not valid:
            raise RouteError(f"{path}: invalid ROUTE.{field}: {detail}")
    return route


def load_route(name: str, root: Path | None = None) -> Route:
    path = installed_route(name, skills_root() if root is None else root)
    return parse_route(name, path, route_source(path))


def run_route(run_dir, name: str, plan: dict) -> Route:
    if "route_sha256" not in plan:
        return load_route(name)  # legacy run
    path = Path(run_dir, ROUTE_SNAPSHOT)
    source = route_source(path)
    if hashlib.sha256(source).hexdigest() != plan["route_sha256"]:
        raise RouteError(f"{path}: route snapshot differs from the one recorded at start")
    return parse_route(name, path, source)


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
    native = IS_WINDOWS and spec.windows_native
    lookup = f"{name}.exe" if native and not os.path.splitext(name)[1] else name
    path = name if os.path.dirname(name) else shutil.which(lookup)
    if native and (not path or os.path.splitext(path)[1].lower() not in (".exe", ".py")):
        die(f"start: {name!r} requires a native executable; point {key} at the real executable")
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
    env = {key: value for key, value in os.environ.items() if key not in scrub}
    # `uv run --script` activates its cached script venv; the agent and its gates need the caller's
    # python, not a stdlib-only interpreter shadowing the target repo's.
    venv = env.get("VIRTUAL_ENV")
    if ("UV_RUN_RECURSION_DEPTH" in env and venv and os.path.isdir(venv)
            and os.path.samefile(venv, sys.prefix)):
        bindir = os.path.normcase(os.path.join(venv, "Scripts" if IS_WINDOWS else "bin"))
        env["PATH"] = os.pathsep.join(entry for entry in env.get("PATH", "").split(os.pathsep)
                                      if os.path.normcase(entry.rstrip("\\/")) != bindir)
        for key in ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "UV_RUN_RECURSION_DEPTH"):
            env.pop(key, None)
    return env


class EventLog:
    """events.ndjson bounded by GDD_RUN_EVENTS_MAX_BYTES: at half, rotate to events.1.ndjson."""

    def __init__(self, run_dir):
        self.path, self.old = (os.path.join(run_dir, n) for n in ("events.ndjson", "events.1.ndjson"))
        self.half = max(int(knob("GDD_RUN_EVENTS_MAX_BYTES", 8388608)) // 2, 1)
        self.dropped, self.handle, self.size = 0, open(self.path, "ab"), 0  # noqa: SIM115 - one handle is owned across writes and closed by close()

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
            self.handle = open(self.path, "ab")  # noqa: SIM115 - the same owned handle reopened after rotation
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


def finalize(run_dir, exit_code, acc=None, note=None, recovered=False, extra=None, *, spec=None):
    """First terminal state wins. Writes answer.md, state.json, exit.code, then `finalized`."""
    if os.path.exists(os.path.join(run_dir, "finalized")):
        return read_state(run_dir)
    state = read_state(run_dir)
    plan = read_json(os.path.join(run_dir, "run.json"), {})
    refolded = acc is None
    if refolded:  # the runner died: re-fold whatever events were retained
        if spec is None and (agent := state.get("agent")):
            try:
                spec = run_route(run_dir, agent, plan)
            except (RouteError, skill_config.ConfigError) as exc:
                # Show the dead process outcome, but let a later read retry the refold.
                unavailable = f"events could not be refolded: {exc}"
                pending = ": ".join(filter(None, (note, unavailable)))
                if state.get("note") != pending:
                    state["note"] = pending
                    write_json(os.path.join(run_dir, "state.json"), state)
                return {**state, "state": "killed" if exit_code in KILLED_EXITS else "failed", "exit": exit_code}
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
    if schema := plan.get("schema"):
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
    if state.get("backend") == "paseo" or state.keys().isdisjoint(PID_KEYS):
        return state, False  # another launcher's run: its liveness is not ours to settle
    if is_starting(state) and not (Path(run_dir, ".supervisor-started").exists() and missing_tmux_session(state)):
        return state, False
    if run_alive(run_dir, state):
        if missing_tmux_session(state):
            # A vanished session can leave the agent's separate process group behind.
            stop_run(run_dir)
            return read_state(run_dir), False
        return state, False
    recovered = False
    if state["state"] != "running":  # terminal state published but the marker is missing
        write_text(os.path.join(run_dir, "exit.code"), f"{state.get('exit')}\n")
        write_text(os.path.join(run_dir, "finalized"), str(state.get("exit")))
    elif os.path.exists(os.path.join(run_dir, "stop")):
        state = finalize(run_dir, KILL_EXIT, note="stop requested and the runner is gone; recorded by a reader")
    else:
        state = finalize(run_dir, -1, recovered=True)
        recovered = bool(state.get("stale_recovered"))
    cleanup_supervisor(run_dir, state)
    return state, recovered


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
    """Return an empty string after confirming the stop, or why it is unproven."""
    marker = os.path.join(run_dir, "finalized")

    def settled():
        if os.path.exists(marker):
            return True
        current = read_state(run_dir)
        return not (run_alive(run_dir, current) or is_starting(current))

    if not os.path.exists(marker):
        write_json(os.path.join(run_dir, "stop"), {"requested_at": now_iso(), "by": os.getpid()})
        wait_until(settled, knob("GDD_RUN_STOP_WAIT_SECONDS", STOP_WAIT_SECONDS))
    if os.path.exists(marker):
        cleanup_supervisor(run_dir, read_state(run_dir))
        return ""
    state, problems = read_state(run_dir), []
    for key in reversed(PID_KEYS):
        pid, recorded = state.get(key), state.get(f"{key}_identity")
        if not pid_alive(pid):
            continue
        matches = identity_matches(recorded, identity(pid))
        if matches is None:
            if pid_alive(pid):
                problems.append(f"{key} {pid} not signalled (start time unverified)")
        elif matches and not terminate(
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
        route_root = skills_root()
        module = installed_route(agent, route_root)
        source = route_source(module)
        spec = parse_route(agent, module, source)
    except (RouteError, skill_config.ConfigError) as exc:
        die(f"start: {exc}")
    if args.session_id is not None:
        if "session_id" not in spec.legacy or args.resume is not None:
            die("start: --session-id is a DSH alias for --resume; do not combine them")
        args.resume = args.session_id
    if any(getattr(args, key) is not None and key not in spec.legacy for key in ("backend", "profile")):
        die("start: --backend and --profile are OMP compatibility flags")
    if args.backend is not None:
        print(f"agent_run: warning: --backend {args.backend} is retired; using GDD_RUN_DETACH instead",
              file=sys.stderr)
    if spec.prepare:
        spec.prepare(args)
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
            result = start_locked(args, spec, slug, cwd, run_dir, command, prompt, max_time, mode, launcher,
                                  route_root, source)
    except (OSError, ValueError) as exc:
        die(f"start: {exc}")
    spawn_auto_gc(root)
    return result


def start_locked(args, spec, slug, cwd, run_dir, command, prompt, max_time, mode, launcher, route_root, source):
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
            wait_until(lambda: not run_alive(run_dir), knob("GDD_RUN_STOP_WAIT_SECONDS", STOP_WAIT_SECONDS))
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
        make_run_directory(run_dir)
    except OSError as exc:
        die(f"start: cannot claim {run_dir}: {exc}")
    with open(os.path.join(run_dir, "prompt.md"), "wb") as handle:
        handle.write(prompt)
    with os.fdopen(private_file(Path(run_dir, ROUTE_SNAPSHOT)), "wb") as handle:
        handle.write(source)
    agent = spec.name
    write_json(os.path.join(run_dir, "run.json"), {"agent": agent, "argv": command, "prompt": spec.prompt,
                                                   "cwd": cwd, "scrub_env": spec.scrub_env, "max_time_s": max_time,
                                                   "schema": args.schema, "skills_root": str(route_root),
                                                   "route_sha256": hashlib.sha256(source).hexdigest()})
    state = {
        "name": slug, "agent": agent, "state": "running", "exit": None, "cwd": cwd, "started": now_iso(),
        "ended": None, "duration_s": None, "run_dir": run_dir, "pid": None, "agent_pid": None,
        "session_id": args.resume or (command[command.index("--session-id") + 1] if "--session-id" in command else ""),
        "model": args.model,
        "thinking": args.thinking, "max_time": args.max_time, "resumed_from": args.resume,
        "spawn": {"creationflags": 0, "platform": sys.platform}}
    runner = [runner_interpreter(), "-B", os.path.abspath(__file__), "_run", "--run-dir", run_dir]
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
    state = read_state(run_dir)
    state.update(pid=os.getpid(), pid_identity=identity(os.getpid()))
    state["spawn"]["creationflags"] = args.creationflags
    write_json(state_path, state)
    if os.path.exists(os.path.join(run_dir, "stop")):
        finalize(run_dir, KILL_EXIT, note="stop requested before agent startup")
        return 1
    try:
        spec = run_route(run_dir, plan["agent"], plan)
    except (RouteError, skill_config.ConfigError) as exc:
        finalize(run_dir, 127, new_acc(), note=str(exc))
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
            final = finalize(run_dir, exit_code, dict(acc), note=note, extra=extra, spec=spec)
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
    marker = Path(run_dir, "finalized")
    state, _ = effective_state(run_dir)
    if marker.exists():
        die(f"kill: run '{args.name}' is already finished (state {state.get('state')})")
    if not (run_alive(run_dir, state) or is_starting(state)):
        die(f"kill: no live process recorded for '{args.name}' (state {reported_state(state)['state']})")
    if problem := stop_run(run_dir):
        die(f"kill: cannot confirm the stop of '{args.name}': {problem}")
    final = read_state(run_dir) if marker.exists() else effective_state(run_dir)[0]
    print(f"killed: {args.name} state={final.get('state')} exit={final.get('exit')}")
    return 0


def main(argv=None):
    argv = normalize_argv(sys.argv[1:] if argv is None else argv)
    epilog = None
    if argv[:1] in (["--help"], ["-h"]):
        try:
            epilog = f"Installed routes: {', '.join(discover_routes()) or 'none'}."
        except skill_config.ConfigError as exc:
            epilog = f"Could not list installed routes: {exc}"
    parser = argparse.ArgumentParser(description=__doc__, epilog=epilog)
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
    gc = sub.add_parser("_gc")
    gc.add_argument("--run-root", required=True)
    gc.add_argument("--now", type=float)
    gc.set_defaults(func=cmd_gc)
    sub.add_parser("list").set_defaults(func=cmd_list)
    for name, func in (("status", cmd_status), ("result", cmd_status), ("answer", cmd_answer),
                       ("kill", cmd_kill), ("tail", cmd_tail)):
        command = sub.add_parser(name)
        command.add_argument("name", nargs="?" if name == "status" else None)
        if name == "tail":
            command.add_argument("lines", nargs="?", type=int)
        command.set_defaults(func=func)
    args = parser.parse_args(argv)
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
