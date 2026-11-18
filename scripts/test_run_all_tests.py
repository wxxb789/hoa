#!/usr/bin/env python3
"""Tests for scripts/run_all_tests.py: discovery, planning, settling and isolation.

Run: python scripts/test_run_all_tests.py
Everything runs against synthetic trees under .tmp-artifacts/test-run-tests/ plus one
read-only plan of the real repository: no test executes a real repository suite.
"""
from __future__ import annotations

import contextlib
import errno
import gc
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import warnings
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / ".tmp-artifacts" / "test-run-tests"
spec = importlib.util.spec_from_file_location("run_all_tests", ROOT / "scripts" / "run_all_tests.py")
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner  # dataclass field resolution needs the module registered
spec.loader.exec_module(runner)

PASS_SUITE = '''import unittest


class Passes(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
'''

FAIL_SUITE = '''import unittest


class Fails(unittest.TestCase):
    def test_nope(self):
        self.assertTrue(False, "fails on purpose")


if __name__ == "__main__":
    unittest.main()
'''

ZERO_TEST_SUITE = '''import unittest


class Nothing(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main()
'''

HANG_SUITE = '''import os
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
with open(os.environ["PID_FILE"], "w", encoding="utf-8") as handle:
    handle.write(f"{os.getpid()} {child.pid}\\n")
time.sleep(120)
'''

ENV_SUITE = '''import json
import os

with open(os.environ["DUMP_FILE"], "w", encoding="utf-8") as handle:
    json.dump(dict(os.environ), handle)
'''

# A unittest module whose only test is skipped: unittest still prints `Ran 1 test` and exits 0,
# so collection is positive while nothing executed.
SKIP_SUITE = '''import unittest


class Skipped(unittest.TestCase):
    @unittest.skip("optional capability absent on this host")
    def test_runs_nowhere(self):
        self.fail("a skipped check must never execute")


if __name__ == "__main__":
    unittest.main()
'''

# The leader exits on SIGTERM, and the child it leaves behind ignores SIGTERM while holding nothing
# the runner could sweep (empty environment, cwd `/`) — only group liveness can stop it.  The pid
# file is written after the child reports readiness so SIGTERM cannot arrive before its handler is
# installed, which would make the fixture discriminate nothing.
STUBBORN_SUITE = '''import os
import signal
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, os.environ["CHILD_FILE"], os.environ["READY"]],
                         env={"READY": os.environ["READY"]}, cwd="/")
while not os.path.exists(os.environ["READY"]):
    time.sleep(0.01)
with open(os.environ["PID_FILE"], "w", encoding="utf-8") as handle:
    handle.write(f"{os.getpid()} {child.pid}\\n")
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
while True:
    time.sleep(1)
'''

STUBBORN_CHILD = '''import os
import signal
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(sys.argv[1], "w", encoding="utf-8").close()
while True:
    time.sleep(1)
'''

# A worker that left the suite's process group (`start_new_session`, the way both launcher adapters
# start theirs) and polls the suite's task-local scratch.  It records `beat.gone` the first time
# that tree disappears and keeps running until the test stops it: the run leaves it alone, and a
# fixture that exited by itself would make the "still running" reading a race with the suite's own
# scratch cleanup.  It counts its heartbeats so a stopped worker is distinguishable from a silent
# one, and replaces the beat file atomically so a test reading it never sees a half-written one.
DETACHED_WORKER = '''import os
import sys
import time

sentinel, beat = sys.argv[1], sys.argv[2]
count = 0
gone = False
while True:
    count += 1
    with open(beat + ".tmp", "w", encoding="utf-8") as handle:
        handle.write(str(count))
    os.replace(beat + ".tmp", beat)
    if not gone and not os.path.exists(sentinel):
        with open(beat + ".gone", "w", encoding="utf-8") as handle:
            handle.write("scratch-gone")
        gone = True
    time.sleep(0.05)
'''

# The suite that starts `DETACHED_WORKER`; `WORKER_CWD_SCRATCH` moves the worker's cwd into the
# suite's own TMPDIR and `WORKER_SANITIZED` empties its environment, so the cwd it was started in is
# the only tie to the suite (the probe a `read_bytes()` on the `/proc/<pid>/cwd` symlink could never
# see).
DETACHED_SUITE = '''import os
import subprocess
import sys
import time

sentinel = os.path.join(os.environ["TMPDIR"], "sentinel")
open(sentinel, "w", encoding="utf-8").close()
options = {}
if os.environ.get("WORKER_CWD_SCRATCH"):
    options["cwd"] = os.environ["TMPDIR"]
if os.environ.get("WORKER_SANITIZED"):
    options["env"] = {}
child = subprocess.Popen([sys.executable, os.environ["WORKER_FILE"], sentinel, os.environ["BEAT"]],
                         start_new_session=True, **options)
with open(os.environ["PID_FILE"], "w", encoding="utf-8") as handle:
    handle.write(f"{child.pid}\\n")
time.sleep(120)
'''

# A same-group child that SIGKILLs the suite leader once the suite reports readiness, then stays.
# Its environment is emptied and its cwd is `/`, so no scratch sweep can match it: only the group
# the leader was recorded in finds it (and only after the leader it outlives is gone).
SIGNAL_KILLER = '''import os
import signal
import sys
import time

ready, target = sys.argv[1], sys.argv[2]
while not os.path.exists(ready):
    time.sleep(0.01)
os.kill(int(target), signal.SIGKILL)
while True:
    time.sleep(1)
'''

SIGNALLED_SUITE = '''import os
import subprocess
import sys
import time

ready = os.environ["READY"]
child = subprocess.Popen([sys.executable, os.environ["KILLER_FILE"], ready, str(os.getpid())],
                         env={}, cwd="/")
with open(os.environ["PID_FILE"], "w", encoding="utf-8") as handle:
    handle.write(f"{child.pid}\\n")
open(ready, "w", encoding="utf-8").close()
time.sleep(120)
'''

# One command of the exit-then-hang fixture: it starts a worker in its *own* process group whose
# environment is emptied and whose cwd is `/` (nothing a scratch sweep could match), writes the
# worker's pid, and exits 0 — leaving the worker behind for the teardown to find while the group is
# still provable.
CLEAN_EXIT_WORKER = '''import subprocess
import sys

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], env={}, cwd="/")
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(f"{child.pid}\\n")
'''

# One provisioning command that leaves a same-group worker behind — environment emptied, cwd `/`,
# nothing a scratch sweep can match — and then exits 1: a normal failure, not a timeout and not a
# death by signal, so only the pre-reap check's own record can account for the worker.
FAILING_PROVISION = '''import subprocess
import sys

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], env={}, cwd="/")
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(f"{child.pid}\\n")
raise SystemExit(1)
'''

# A suite that records its own pid and exits 0 without cleanup — a reaper outside this run can
# block in `os.waitpid` on that pid and take the status the moment the suite ends, leaving the
# runner a child it can no longer wait for.  The pid file is replaced atomically (temp + rename):
# a poller that sees the file must never read a half-written, truncated one.
REAPED_SUITE = '''import os
import time

path = os.environ["PID_FILE"]
with open(path + ".tmp", "w", encoding="utf-8") as handle:
    handle.write(str(os.getpid()))
os.replace(path + ".tmp", path)
time.sleep(0.2)
'''

# A command leader that ignores SIGTERM, starts a same-group child that ignores it too, records
# both pids atomically, and exits by itself inside the first kill-grace window.  A test that blocks
# in `os.waitpid` on the leader takes the leader's status the moment it exits, so the kernel's hold
# on it — the identity the escalation must re-pin before every round — is gone before the second
# round.
ANCHOR_LEADER = '''import os
import signal
import subprocess
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c",
                          "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                          " time.sleep(60)"])
path = os.environ["PID_FILE"]
with open(path + ".tmp", "w", encoding="utf-8") as handle:
    handle.write(f"{os.getpid()} {child.pid}\\n")
os.replace(path + ".tmp", path)
time.sleep(0.5)
os._exit(0)
'''

# A leader that ignores SIGTERM, starts a same-group child that ignores it too, records both pids
# atomically and then keeps running: the test's own instrumentation ends it (and a thread it does
# not control reaps it) at the moment the teardown's evidence enumeration runs.
HELD_LEADER = '''import os
import signal
import subprocess
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c",
                          "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                          " time.sleep(60)"])
path = os.environ["PID_FILE"]
with open(path + ".tmp", "w", encoding="utf-8") as handle:
    handle.write(f"{os.getpid()} {child.pid}\\n")
os.replace(path + ".tmp", path)
while True:
    time.sleep(1)
'''


def synthetic_tree(patterns: list[str], prune: list[str], floor: list[str], suites: str) -> Path:
    """Create a throwaway root with a manifest and return it."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tree-", dir=ARTIFACTS))
    manifest = [
        "schema = 1",
        "[discovery]",
        f"patterns = {json.dumps(patterns)}",
        f"prune = {json.dumps(prune)}",
        f"floor = {json.dumps(floor)}",
        "",
        suites,
    ]
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "test_manifest.toml").write_text("\n".join(manifest), encoding="utf-8")
    return root


def run_synthetic(root: Path, scratch: Path, report: Path, *extra: str) -> tuple[int, str, dict]:
    """Run the discoverer in-process against a synthetic root; return code, stdout, report.

    The kernel boundary is spied for the whole run and the three readings of every delivery — the
    syscall, the record, the log — must agree (`assert_delivery_boundary`), so no test in this file
    can drive a run that quietly disagrees with itself.  The spy is closed before this function
    returns, so no cleanup that runs after the run under test is ever trapped.
    """
    buffer = io.StringIO()
    # 20s, not 5s: these suites start real interpreters and the machine may be loaded; only
    # an injected hang suite is meant to hit the timeout.
    argv = ["--root", str(root), "--event", "local", "--timeout", "20",
            "--scratch", str(scratch), "--report", str(report), *extra]
    spy = DeliverySpy()
    try:
        with contextlib.redirect_stdout(buffer):
            code = runner.main(argv)
    finally:
        spy.close()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert_delivery_boundary(spy, payload)
    return code, buffer.getvalue(), payload


def states_of(payload: dict) -> dict:
    """The report's per-suite entries keyed by id."""
    return {entry["id"]: entry for entry in payload["suites"]}


def write_suite(root: Path, relative: str, body: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return relative


def process_running(pid: int) -> bool:
    """Whether `pid` is still a *running* process, answered from `/proc` where there is one.

    A zombie is not running: it is terminated, and the runner is not necessarily its parent.  The
    runner reads liveness the same way (`_proc_state`), so a test that stopped a process the way the
    runner reports it must agree with the runner's own rule.  Without `/proc` the probe is
    `kill(pid, 0)`, which cannot tell a zombie from a live process.
    """
    if runner.PROC_ROOT.is_dir():
        state = runner._proc_state(pid)
        return state is not None and state != "Z"
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def kill_quietly(pid: int, signum: int | None = None) -> None:
    """Signal `pid`, tolerating a process that is already gone.

    The signal is resolved when a guarded cleanup path runs, never at import: `signal.SIGKILL` does
    not exist on every platform, and a default argument would be evaluated before any capability
    skip could protect the module that uses it.
    """
    if signum is None:
        signum = getattr(signal, "SIGKILL", signal.SIGTERM)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signum)


def stop_recorded_pids(pids_file: Path, signum: int) -> None:
    """Stop whatever pids `pids_file` holds, with a constant the caller captured.

    A safety net for a fixture that outlives a run which died before the test could register the
    pids it recorded (the model that removes `signal.SIGKILL` leaves the fixture running on purpose,
    and a crashed run must still not leak it).  Nothing happens when the file was never written.
    """
    if not pids_file.exists():
        return
    for value in pids_file.read_text(encoding="utf-8").split():
        with contextlib.suppress(ValueError):
            kill_quietly(int(value), signum)


class PatchingTestCase(unittest.TestCase):
    """Attribute patching the test runner itself restores."""

    def patch(self, target, attribute: str, value) -> None:
        """Set `target.attribute` for this test and restore it afterwards."""
        saved = getattr(target, attribute)
        setattr(target, attribute, value)
        self.addCleanup(setattr, target, attribute, saved)

    def remove_attribute(self, target, attribute: str) -> None:
        """Make `target.attribute` absent for this test, restoring exactly what was there before.

        `patch` cannot model absence — it reads the attribute to save it, and a platform where the
        attribute genuinely does not exist is exactly the platform such a test must run on.  So an
        attribute that is there is deleted and restored on the way out, and one that is already
        absent is left untouched, with nothing registered to restore.
        """
        absent = object()
        saved = getattr(target, attribute, absent)
        if saved is not absent:
            delattr(target, attribute)
            self.addCleanup(setattr, target, attribute, saved)


def can_deliver_signals() -> bool:
    """Whether this host can deliver a teardown signal at all (the runner's own delivery gates).

    Successful delivery needs pidfds, `/proc` (start times and group members) and `waitid` with
    `WNOWAIT`; a test that expects a signal to arrive must be guarded by this, while the refusal
    cases pin what each missing capability does.
    """
    return (runner.PIDFD_PINNING and runner.PROC_ROOT.is_dir() and runner.WAITID_WNOWAIT
            and hasattr(signal, "SIGCHLD"))


def pidfd_target(fd: int) -> int | None:
    """The pid a pidfd refers to, from the kernel's own `/proc/self/fdinfo` (`Pid:`), or None."""
    try:
        with open(Path("/proc/self/fdinfo") / str(fd), encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("Pid:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def proc_start_time(pid: int) -> str | None:
    """`/proc/<pid>/stat` field 22, read here rather than through the runner's own readers.

    The spy's reading must be independent of the code under test, so this parses the file itself —
    the command name can contain spaces and parentheses, so the fields begin after the *last* `)` —
    and indexes field 22 itself; a runner that read a different field, or shared its parse with the
    record, could not have the two readings agree by construction (the identity pins in
    `StartTimeOracleTests` compare the runner's own readings against this one).
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    close = raw.rfind(b")")
    fields = raw[close + 1:].split() if close >= 0 else []
    return fields[19].decode() if len(fields) > 19 else None


def delivery(pid: int, signal_name: str = "SIGTERM", *, start: str = "1", stopped: bool = False):
    """One delivery attempt in the model's own terms, for tests that state a record directly."""
    return runner.Delivery(pid=pid, start=start, signal=signal_name, stopped=stopped)


def parse_delivery_lines(log_text: str) -> list[tuple[str, int, int]]:
    """Every delivery line in `log_text` as (signal, pid, start), through the runner's own pattern.

    Strict by construction: every line carrying the runner's `DELIVERY_MARKER` must read back
    through `DELIVERY_LINE_RE`, so a delivery line in a shape this reader cannot parse is a claim
    that cannot be checked — a failure, never a line to skip.  The pattern and the marker are the
    runner's, so the renderer and this reader cannot drift apart without a test going red.
    """
    marked = [line for line in log_text.splitlines() if runner.DELIVERY_MARKER in line]
    parsed = [(match.group("signal"), int(match.group("pid")), int(match.group("start")))
              for match in runner.DELIVERY_LINE_RE.finditer(log_text)]
    if len(parsed) != len(marked):
        raise AssertionError(
            f"a delivery line does not read back through the runner's pattern: {marked}")
    return parsed


class DeliverySpy:
    """The kernel boundary of one in-process run: the signals it really sent.

    Records `(signal name, target pid, start time)` for every successful
    `signal.pidfd_send_signal` call, read back from the pidfd the call went through — the start
    time from `proc_start_time`'s own parse of `/proc/<pid>/stat`, never through the runner's
    readers, so the kernel reading and the record cannot agree by construction — and traps the APIs
    the run must never use for a delivery (`os.kill`, `os.killpg`): signal 0 is allowed, because a
    liveness probe through a bare pid is not a delivery and the runner is entitled to it.  Only
    attributes this platform exposes are patched (a host without pidfds cannot deliver at all, and
    the refusal it records instead is what the tests pin there), and `close()` restores them
    immediately, so no cleanup that runs outside the run under test is ever trapped.  A target that
    cannot be read back is reported separately instead of being dropped: an unreadable delivery is
    evidence the assertion must see, not evidence to skip.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, int, int]] = []
        self.unresolved: list[str] = []
        self.forbidden: list[str] = []
        self._saved: list[tuple[object, str, object]] = []
        if hasattr(signal, "pidfd_send_signal"):
            real_send = signal.pidfd_send_signal

            def record_send(fd: int, signum: int, *flags: int) -> None:
                target = pidfd_target(fd)
                real_send(fd, signum, *flags)
                start = proc_start_time(target) if target is not None else None
                if target is None or start is None:
                    self.unresolved.append(f"{signal.Signals(signum).name} through fd {fd}")
                else:
                    self.sent.append((signal.Signals(signum).name, target, int(start)))

            self._install(signal, "pidfd_send_signal", record_send)
        for module, attribute in ((os, "kill"), (os, "killpg")):
            if hasattr(module, attribute):
                real_call = getattr(module, attribute)
                name = f"{module.__name__}.{attribute}"

                def trap(pid: int, signum: int, *rest: int, _real=real_call, _name=name) -> None:
                    if signum:
                        self.forbidden.append(f"{_name}({pid}, {signum})")
                        raise AssertionError(f"the run signalled through {_name}: {pid}, {signum}")
                    return _real(pid, signum, *rest)

                self._install(module, attribute, trap)

    def _install(self, target: object, attribute: str, value: object) -> None:
        self._saved.append((target, attribute, getattr(target, attribute)))
        setattr(target, attribute, value)

    def close(self) -> None:
        """Restore every patched attribute now, in reverse order."""
        while self._saved:
            target, attribute, saved = self._saved.pop()
            setattr(target, attribute, saved)


def assert_delivery_boundary(spy: DeliverySpy, payload: dict) -> None:
    """`kernel syscalls == record deliveries == parsed log lines`, for a whole in-process run.

    Three independent readings of the same fact must agree: what the kernel accepted (the spy), what
    the run's record publishes as `delivered`, and what each suite's log carries as delivery lines.
    None of the three is trusted over another and none is optional — a signal sent but not recorded,
    a record entry with no syscall behind it, a line with no entry, or a line the runner's pattern
    cannot read are all failures here.  Suites are settled one after another (`main` runs
    `run_suite` over the plan in a plain loop; nothing is scheduled concurrently), so each suite's
    own order is the run's own and is compared — the record's `delivered` against that suite's
    log — while no cross-suite concatenation is compared: the record publishes deliveries per suite
    and no artifact of the run states a global order.
    """
    if spy.forbidden:
        raise AssertionError(f"the run signalled outside its delivery path: {spy.forbidden}")
    if spy.unresolved:
        raise AssertionError(f"a delivery could not be read back at the boundary: {spy.unresolved}")
    recorded: list[tuple[str, int, int]] = []
    for entry in payload["suites"]:
        teardown = entry["teardown"]
        if teardown is None:
            continue
        items = [(item["signal"], item["pid"], int(item["start"]))
                 for item in teardown["delivered"]]
        recorded.extend(items)
        logged = parse_delivery_lines(Path(entry["log"]).read_text(encoding="utf-8"))
        if logged != items:
            raise AssertionError(
                f"suite {entry['id']}: its log's delivery lines {logged} are not the deliveries "
                f"its record carries {items}")
    if sorted(spy.sent) != sorted(recorded):
        raise AssertionError(
            f"the signals the kernel accepted {sorted(spy.sent)} are not the deliveries the record "
            f"publishes {sorted(recorded)}")


SHIM_TOOL_FIXTURE = '''import json
import os
import pathlib
import sys

state = os.environ.get("MISE_STATE_DIR")
if not state or not pathlib.Path(state).is_dir():
    print(f"shim cannot run: MISE_STATE_DIR={state!r}", file=sys.stderr)
    raise SystemExit(1)
pathlib.Path(os.environ["SHIM_STATE_FILE"]).write_text(json.dumps(state), encoding="utf-8")
'''


class SuiteEnvironmentTests(unittest.TestCase):
    """The suite environment: the manifest allowlist plus pinned interpreter and shim state."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)
        self.document = runner.load_manifest(ROOT / runner.MANIFEST_RELATIVE)
        self.scratch = runner.scratch_root_for()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.report = ARTIFACTS / "report.json"

    @contextlib.contextmanager
    def operator(self, home: Path | None = None, **variables):
        """Temporarily set the runner's own HOME/MISE_* as an operator would."""
        saved = {name: os.environ.get(name) for name in ("HOME", *runner.SHIM_STATE_DEFAULTS)}
        for name in runner.SHIM_STATE_DEFAULTS:
            os.environ.pop(name, None)
        if home is not None:
            os.environ["HOME"] = str(home)
        for name, value in variables.items():
            os.environ[name] = value
        try:
            yield
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_shim_state_directories_are_pinned_from_the_operator_home(self):
        home = ARTIFACTS / "operator-home"
        (home / ".local" / "state" / "mise").mkdir(parents=True)
        (home / ".local" / "share" / "mise").mkdir(parents=True)
        with self.operator(home=home):
            environment = runner.base_environment(self.document, sys.executable)
        self.assertEqual(environment["MISE_STATE_DIR"], str(home / ".local" / "state" / "mise"))
        self.assertEqual(environment["MISE_DATA_DIR"], str(home / ".local" / "share" / "mise"))
        for name in runner.SHIM_STATE_DEFAULTS:
            self.assertTrue(Path(environment[name]).is_absolute(), environment[name])

    def test_operator_shim_settings_win_and_are_made_absolute(self):
        home = ARTIFACTS / "operator-home"
        home.mkdir(parents=True, exist_ok=True)
        with self.operator(home=home, MISE_STATE_DIR="./relative-state"):
            environment = runner.base_environment(self.document, sys.executable)
        self.assertEqual(environment["MISE_STATE_DIR"], str(Path("./relative-state").resolve()))
        self.assertNotIn("MISE_DATA_DIR", environment)

    def test_suites_gain_nothing_outside_the_declared_allowlist(self):
        home = ARTIFACTS / "operator-home"
        (home / ".local" / "state" / "mise").mkdir(parents=True, exist_ok=True)
        with self.operator(home=home, MISE_VERBOSE="1", GDD_LAUNCHER="must-not-leak",
                           OMP_RUN_ROOT="must-not-leak"):
            environment = runner.base_environment(self.document, sys.executable)
        allowed = set((self.document.get("env") or {}).get("passthrough") or [])
        # Frozen rather than read from `runner.SHIM_STATE_DEFAULTS`: deriving the permitted
        # set from the constant it polices is how a name appended there starts reaching
        # every suite unnoticed.
        allowed |= {"PATH", "NO_COLOR", "MISE_STATE_DIR", "MISE_DATA_DIR"}
        self.assertLessEqual(set(environment), allowed)
        self.assertNotIn("MISE_VERBOSE", environment)

    def test_the_passthrough_allowlist_is_pinned_by_name(self):
        """The reviewed allowlist is an oracle in its own right, not a mirror of the data."""
        self.assertEqual(tuple(self.document["env"]["passthrough"]), (
            "PATH", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TERM", "TZ",
            "CI", "GITHUB_ACTIONS", "GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA",
            "GITHUB_HEAD_REF", "GITHUB_BASE_REF",
        ))

    def test_the_pinned_shim_state_is_exactly_two_named_directories(self):
        """What may reach every suite as operator state is pinned by name, not by count."""
        self.assertEqual(set(runner.SHIM_STATE_DEFAULTS), {"MISE_STATE_DIR", "MISE_DATA_DIR"})

    @unittest.skipIf(os.name != "posix", "a POSIX virtual environment's interpreter is a symlink")
    def test_a_virtual_environment_keeps_its_identity_on_path(self):
        """PATH pins the interpreter that was selected, not the base one its symlink points at.

        A POSIX virtual environment is `<venv>/bin/python3 -> <base>/python3` beside `pyvenv.cfg`,
        and the interpreter decides it is inside that environment from the path it was started
        with.  Resolving the symlink therefore hands a suite's own `python3` — and any
        `#!/usr/bin/env python3` shebang — the base interpreter, silently discarding the
        environment the repository dependencies are installed in (§4.3).
        """
        venv = ARTIFACTS / "venv"
        created = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                                 capture_output=True, text=True)
        if created.returncode != 0:
            self.skipTest(f"cannot create a virtual environment here: {created.stderr.strip()}")
        python = venv / "bin" / "python3"
        self.assertTrue(python.is_symlink(), f"{python} is not the symlinked shape this pins")
        self.assertNotEqual(str(python.parent), os.path.dirname(os.path.realpath(python)),
                            "the fixture does not exercise symlink resolution")
        environment = runner.base_environment(self.document, str(python))
        self.assertEqual(environment["PATH"].split(os.pathsep)[0], str(venv / "bin"))
        found = shutil.which("python3", path=environment["PATH"])
        self.assertEqual(found, str(python))
        probe = subprocess.run([found, "-c", "import sys; print(sys.prefix)"],
                               capture_output=True, text=True, env=environment)
        self.assertEqual(probe.stdout.strip(), str(venv), probe.stderr)

    def test_a_shim_style_tool_finds_its_state_under_a_task_local_home(self):
        """End to end: the suite process runs the shim, not the operator's HOME."""
        home = ARTIFACTS / "operator-home"
        (home / ".local" / "state" / "mise").mkdir(parents=True, exist_ok=True)
        state_file = ARTIFACTS / "shim-state.json"
        root = synthetic_tree(
            patterns=["scripts/test_*.py"], prune=[], floor=[],
            suites="\n".join([
                "[[suite]]",
                'id = "canned:shim-tool"',
                'command = [["{python}", "scripts/tests/shim_tool.py"]]',
                f'env = {{ SHIM_STATE_FILE = "{state_file}" }}',
                "",
            ]),
        )
        write_suite(root, "scripts/tests/shim_tool.py", SHIM_TOOL_FIXTURE)
        with self.operator(home=home):
            code, output, payload = run_synthetic(root, self.scratch, self.report,
                                                  "--suite", "canned:shim-tool")
        self.assertEqual(payload["shim_state"]["MISE_STATE_DIR"],
                         str(home / ".local" / "state" / "mise"))
        self.assertEqual(states_of(payload)["canned:shim-tool"]["state"], "PASS", output)
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8")),
                         str(home / ".local" / "state" / "mise"))
        self.assertEqual(code, 0)


class DiscoveryTests(unittest.TestCase):
    """Patterns, pruning and the reviewed floor."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)

    def test_glob_star_never_crosses_a_slash(self):
        regex = runner._glob_regex("skills/*/scripts/test_*.py")
        self.assertTrue(regex.match("skills/gdd/scripts/test_thing.py"))
        self.assertIsNone(regex.match("skills/gdd/nested/scripts/test_thing.py"))

    def test_double_star_crosses_directories(self):
        self.assertTrue(runner._glob_regex("evals/**/test_*.py").match("evals/a/b/test_x.py"))

    def test_prune_matches_a_name_at_any_depth_or_a_path_prefix(self):
        self.assertTrue(runner._pruned("skills/a/scripts/node_modules/test_x.py", ["node_modules"]))
        self.assertTrue(runner._pruned("paseo-plugins/gdd-run-observer/server/tests/x.ts", ["paseo-plugins"]))
        self.assertFalse(runner._pruned("skills/a/scripts/test_x.py", ["paseo-plugins"]))

    def test_discovery_collects_named_entry_points_only(self):
        root = synthetic_tree(
            patterns=["skills/*/scripts/tests/test*.py", "skills/*/scripts/tests/test*.sh",
                      "skills/*/scripts/tests/run-*-selftest.sh"],
            prune=["node_modules", "fixtures"],
            floor=[],
            suites="",
        )
        write_suite(root, "skills/a/scripts/tests/test-one.py", PASS_SUITE)
        write_suite(root, "skills/a/scripts/tests/test-two.sh", "#!/usr/bin/env bash\nexit 0\n")
        write_suite(root, "skills/a/scripts/tests/run-a-selftest.sh", "#!/usr/bin/env bash\nexit 0\n")
        write_suite(root, "skills/a/scripts/tests/helper.py", "print('not a suite')\n")
        write_suite(root, "skills/a/scripts/tests/judge_cases.py", "print('online evaluation')\n")
        write_suite(root, "skills/a/scripts/tests/payload.sh", "#!/usr/bin/env bash\nexit 0\n")
        write_suite(root, "skills/a/scripts/tests/fixtures/test_fixture.py", PASS_SUITE)
        write_suite(root, "skills/a/scripts/tests/node_modules/test_installed.py", PASS_SUITE)
        found = runner.discover(root, runner.load_manifest(root / "scripts/test_manifest.toml")
                                ["discovery"]["patterns"],
                                ["node_modules", "fixtures"])
        self.assertEqual(found, sorted([
            "skills/a/scripts/tests/run-a-selftest.sh",
            "skills/a/scripts/tests/test-one.py",
            "skills/a/scripts/tests/test-two.sh",
        ]))

    def test_unmet_floor_is_a_plan_error(self):
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=["scripts/test_gone.py"],
                              suites="")
        write_suite(root, "scripts/test_present.py", PASS_SUITE)
        plan = runner.build_plan(root, runner.load_manifest(root / "scripts/test_manifest.toml"),
                                 event="local")
        self.assertEqual(plan.floor_missing, ["scripts/test_gone.py"])
        self.assertTrue(any("floor unmet" in problem for problem in plan.problems))

    def test_empty_discovery_is_a_plan_error(self):
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[], suites="")
        plan = runner.build_plan(root, runner.load_manifest(root / "scripts/test_manifest.toml"),
                                 event="local")
        self.assertEqual(plan.discovered, [])
        self.assertTrue(any("produced no suites" in problem for problem in plan.problems))

    def test_unpinned_discovery_is_reported_not_rejected(self):
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="")
        write_suite(root, "scripts/test_new.py", PASS_SUITE)
        plan = runner.build_plan(root, runner.load_manifest(root / "scripts/test_manifest.toml"),
                                 event="local")
        self.assertEqual(plan.problems, [])
        self.assertEqual(plan.unpinned, ["scripts/test_new.py"])
        self.assertEqual([suite.id for suite in plan.scheduled], ["scripts/test_new.py"])

    def test_a_filtered_plan_is_not_a_floor_check(self):
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[],
                              floor=["scripts/test_gone.py"], suites="")
        write_suite(root, "scripts/test_present.py", PASS_SUITE)
        document = runner.load_manifest(root / "scripts/test_manifest.toml")
        full = runner.build_plan(root, document, event="local")
        self.assertEqual(full.floor_missing, ["scripts/test_gone.py"])
        self.assertTrue(any("floor unmet" in problem for problem in full.problems))
        filtered = runner.build_plan(root, document, event="local",
                                     only=["scripts/test_present.py"])
        self.assertEqual(filtered.problems, [])
        self.assertEqual(filtered.floor_missing, [])
        self.assertEqual([suite.id for suite in filtered.scheduled],
                         ["scripts/test_present.py"])


class ManifestValidationTests(unittest.TestCase):
    """Manifest contradictions surface as plan problems, never as silent skips."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)

    def plan(self, suites: str) -> runner.Plan:
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[], suites=suites)
        write_suite(root, "scripts/test_real.py", PASS_SUITE)
        write_suite(root, "scripts/parent.py", "print('parent-counter: 3/3 ok')\n")
        document = runner.load_manifest(root / "scripts/test_manifest.toml")
        return runner.build_plan(root, document, event="local")

    def test_counter_without_patterns_is_rejected(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_real.py"\nassertion = "counter"\n')
        self.assertTrue(any("needs count_regexes" in problem for problem in plan.problems))

    def test_counter_pattern_without_a_passed_group_is_rejected(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_real.py"\nassertion = "counter"\n'
                         'count_regexes = ["^x: (\\\\d+)$"]\n')
        self.assertTrue(any("passed" in problem for problem in plan.problems))

    def test_condition_without_skip_reason_is_rejected(self):
        plan = self.plan('[[suite]]\nid = "gate:x"\ncommand = [["true"]]\n'
                         'condition = "pull_request"\n')
        self.assertTrue(any("skip_reason" in problem for problem in plan.problems))

    def test_stale_refinement_is_rejected(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_missing.py"\nassertion = "exit"\n')
        self.assertTrue(any("matches no discovered suite" in problem for problem in plan.problems))

    def test_declared_command_naming_a_missing_entry_point_is_rejected(self):
        plan = self.plan('[[suite]]\nid = "declared:missing"\n'
                         'command = [["{python}", "scripts/not_there.py"]]\n')
        self.assertTrue(any("entry point does not exist: scripts/not_there.py" in problem
                            for problem in plan.problems))

    def test_duplicate_suite_id_is_rejected(self):
        plan = self.plan(
            '[[suite]]\nid = "gate:x"\ncommand = [["true"]]\n\n'
            '[[suite]]\nid = "gate:x"\ncommand = [["true"]]\n'
        )
        self.assertTrue(any("duplicate suite id" in problem for problem in plan.problems))

    def test_covered_by_must_name_a_scheduled_suite(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_real.py"\n'
                         'covered_by = "scripts/nope.py"\n')
        self.assertTrue(any("covered_by names no known suite" in problem for problem in plan.problems))

    def test_covered_by_requires_the_parent_to_name_the_child(self):
        plan = self.plan(
            '[[suite]]\nid = "parent"\ncommand = [["{python}", "scripts/parent.py"]]\npath = "scripts/parent.py"\n'
            'assertion = "counter"\ncount_regexes = ["^parent-counter: (?P<passed>\\\\d+)/(?P<total>\\\\d+) ok$"]\n\n'
            '[[suite]]\npath = "scripts/test_real.py"\ncovered_by = "parent"\n'
        )
        self.assertTrue(any("never names" in problem for problem in plan.problems))

    def test_declared_entry_may_take_its_id_from_its_path(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_real.py"\n'
                         'command = [["{python}", "-B", "-m", "unittest", "scripts.test_real"]]\n')
        self.assertEqual(plan.problems, [])
        self.assertEqual([suite.id for suite in plan.scheduled], ["scripts/test_real.py"])

    def test_selection_by_covered_child_points_at_its_parent(self):
        root = synthetic_tree(
            patterns=["scripts/test_*.py"], prune=[], floor=[],
            suites='[[suite]]\nid = "parent"\npath = "scripts/parent.py"\n'
                   'command = [["{python}", "scripts/parent.py"]]\n\n'
                   '[[suite]]\npath = "scripts/test_real.py"\ncovered_by = "parent"\n',
        )
        write_suite(root, "scripts/parent.py", "# runs scripts/test_real.py\n")
        write_suite(root, "scripts/test_real.py", PASS_SUITE)
        document = runner.load_manifest(root / "scripts/test_manifest.toml")
        plan = runner.build_plan(root, document, event="local", only=["scripts/test_real.py"])
        self.assertTrue(any("covered by parent" in problem for problem in plan.problems))
        self.assertEqual(plan.scheduled, [])


class RealTreePlanTests(unittest.TestCase):
    """The plan of the real repository: the reconciliation this PR has to keep honest."""

    @classmethod
    def setUpClass(cls):
        cls.document = runner.load_manifest(ROOT / runner.MANIFEST_RELATIVE)
        cls.plan = runner.build_plan(ROOT, cls.document, event="local")
        cls.ids = {suite.id for suite in cls.plan.scheduled}

    def test_every_static_gate_is_still_scheduled(self):
        for suite_id in ("gate:frontmatter", "gate:contract-graph", "gate:index-drift",
                         "gate:vendor-shared"):
            self.assertIn(suite_id, self.ids)
        self.assertTrue({"gate:version-bump", "gate:changelog", "gate:revision-bump"}
                        <= {suite.id for suite in self.plan.skipped})

    def test_the_plan_has_no_problems_and_no_filtered_floor(self):
        self.assertEqual(self.plan.problems, [])
        self.assertEqual(self.plan.floor_missing, [])
        # This repository pins every discovered path, so it has no unpinned discovery to
        # name here; an unpinned one is scheduled and reported, never a problem (owner
        # decision, 2026-11-14), which DiscoveryTests pins on a synthetic tree.

    def test_discovery_finds_the_suites_the_old_globs_missed(self):
        self.assertIn("skills/ghc-search/scripts/test_ghc_search.py", self.ids)
        self.assertIn("skills/delegated-work-acceptance/scripts/tests/test_worktree_scope.py", self.ids)
        self.assertIn("skills/gdd/scripts/tests/test_paseo_run_python.py", self.ids)

    def test_dispatch_guards_are_accounted_through_their_parent(self):
        self.assertNotIn("skills/gdd/scripts/tests/test-dispatch-guards.py", self.ids)
        covered = {child.id: child for child in self.plan.covered}
        self.assertEqual(
            covered["skills/gdd/scripts/tests/test-dispatch-guards.py"].covered_by,
            "skills/gdd/scripts/tests/run-gdd-selftest.sh",
        )

    def test_paseo_package_is_declared_with_its_own_cwd_and_commands(self):
        suite = next(item for item in self.plan.scheduled if item.id == "pkg:paseo-run-observer")
        self.assertEqual(suite.cwd, ROOT / "paseo-plugins" / "gdd-run-observer")
        self.assertEqual(suite.provision, (("npm", "ci"),))
        self.assertEqual([argv[1] for argv in suite.commands], ["run", "test"])
        self.assertEqual(suite.assertion, "counter")

    def test_unittest_suites_keep_their_declared_module_invocation(self):
        for path, module in (
            ("scripts/test_skill_config.py", "scripts.test_skill_config"),
            ("scripts/test_check_changelog.py", "scripts.test_check_changelog"),
            ("scripts/test_check_frontmatter.py", "scripts.test_check_frontmatter"),
            ("evals/test_judge_trigger_evals.py", "evals.test_judge_trigger_evals"),
            ("evals/test_validate_skill_method_cases.py", "evals.test_validate_skill_method_cases"),
        ):
            suite = next(item for item in self.plan.scheduled if item.id == path)
            self.assertEqual(suite.commands, ((sys.executable, "-B", "-m", "unittest", module),))

    def test_direct_python_suites_pin_interpreter_cwd_and_pythonpath(self):
        suite = next(item for item in self.plan.scheduled if item.id == "scripts/test_version.py")
        self.assertEqual(suite.commands, ((sys.executable, "-B", "scripts/test_version.py"),))
        self.assertEqual(suite.cwd, ROOT)
        environment = runner.base_environment(self.document, sys.executable)
        # The interpreter's own directory, never the directory its symlink resolves to: what that
        # costs is measured in `SuiteEnvironmentTests` against a real virtual environment.
        prefix = Path(environment["PATH"].split(os.pathsep)[0])
        self.assertEqual(prefix, Path(sys.executable).absolute().parent)

    def test_shell_suites_run_under_bash(self):
        suite = next(item for item in self.plan.scheduled
                     if item.id == "skills/gdd/scripts/tests/test-omp-run-stale.sh")
        self.assertEqual(suite.runtime, "bash")
        self.assertEqual(suite.commands, (("bash", "skills/gdd/scripts/tests/test-omp-run-stale.sh"),))

    def test_custom_assertion_suites_have_positive_count_adapters(self):
        for path, marker in (
            ("skills/hermes-models/scripts/tests/test-routing-inventory.py", "^routing-inventory:"),
            ("skills/hermes-models/scripts/tests/test-provider-metadata.py", "^provider-metadata:"),
            ("skills/gdd/scripts/tests/test-dispatch-guards.py", "^dispatch-guards:"),
            ("skills/gdd/scripts/tests/test-omp-run-stale.sh", "^stale-test:"),
        ):
            suite = next(item for item in self.plan.scheduled + self.plan.covered if item.id == path)
            self.assertEqual(suite.assertion, "counter")
            self.assertTrue(suite.count_regexes[0].startswith(marker), suite.count_regexes)

    def test_python_launcher_suites_declare_their_detached_workers(self):
        """Both launcher suites name the resource their own teardown stops (§4 item 4).

        The runner sweeps a timed-out suite's scratch whatever the declaration says (the suite that
        lost its cleanup callbacks is exactly the one that cannot clean up), so the declaration is
        what keeps the resource, its mechanism and its owning teardown visible in the manifest.
        """
        for path, adapter, teardown in (
            ("skills/gdd/scripts/tests/test_omp_run_python.py", "omp-run.py", "kill_hard"),
            ("skills/gdd/scripts/tests/test_paseo_run_python.py", "paseo-run.py", "stop_monitors"),
        ):
            suite = next(item for item in self.plan.scheduled if item.id == path)
            declaration = suite.detached or ""
            self.assertIn(adapter, declaration, path)
            self.assertIn("start_new_session", declaration, path)
            self.assertIn(teardown, declaration, path)

    def test_pull_request_gates_skip_outside_a_pull_request(self):
        skipped = {suite.id: suite for suite in self.plan.skipped}
        self.assertEqual(set(skipped), {"gate:version-bump", "gate:changelog", "gate:revision-bump"})
        for suite in skipped.values():
            self.assertEqual(suite.condition, "pull_request")
            self.assertTrue(suite.skip_reason)

    def test_pull_request_event_schedules_those_gates(self):
        plan = runner.build_plan(ROOT, self.document, event="pull_request")
        ids = {suite.id for suite in plan.scheduled}
        self.assertIn("gate:version-bump", ids)
        self.assertIn("gate:changelog", ids)
        self.assertIn("gate:revision-bump", ids)
        self.assertEqual(plan.skipped, [])

    def test_filtered_plan_skips_the_floor_check_and_keeps_children(self):
        plan = runner.build_plan(ROOT, self.document, event="local",
                                 only=["skills/gdd/scripts/tests/run-gdd-selftest.sh"])
        self.assertEqual(plan.problems, [])
        self.assertEqual(len(plan.scheduled), 1)
        self.assertEqual([child.id for child in plan.covered],
                         ["skills/gdd/scripts/tests/test-dispatch-guards.py"])


class SettleTests(unittest.TestCase):
    """Terminal states and the anti-false-green rules of §4.5/§4.6."""

    def suite(self, **overrides) -> runner.Suite:
        values = dict(id="s", origin="discovered", commands=(("cmd",),), cwd=ROOT,
                      runtime="python")
        values.update(overrides)
        return runner.Suite(**values)

    def test_unittest_suite_with_zero_collected_tests_is_error(self):
        state, counts, reason = runner.settle(
            self.suite(assertion="unittest"), exit_code=0, timed_out=False,
            output="Ran 0 tests in 0.000s\n\nOK\n")
        self.assertEqual(state, "ERROR")
        self.assertEqual(counts["executed"], 0)
        self.assertIn("Ran 0 tests", reason)

    def test_unittest_suite_without_a_summary_is_error(self):
        state, _, _ = runner.settle(self.suite(assertion="unittest"), exit_code=0,
                                    timed_out=False, output="ImportError: no module named thing\n")
        self.assertEqual(state, "ERROR")

    def test_unittest_summary_settles_pass_and_fail(self):
        output = "Ran 3 tests in 0.002s\n\nOK\n"
        self.assertEqual(runner.settle(self.suite(assertion="unittest"), exit_code=0,
                                       timed_out=False, output=output)[0], "PASS")
        self.assertEqual(runner.settle(self.suite(assertion="unittest"), exit_code=1,
                                       timed_out=False, output=output)[0], "FAIL")

    def test_unittest_skips_are_recorded(self):
        state, counts, _ = runner.settle(
            self.suite(assertion="unittest"), exit_code=0, timed_out=False,
            output="Ran 4 tests in 0.002s\n\nOK (skipped=1)\n")
        self.assertEqual((state, counts), ("PASS", {"executed": 4, "skipped": 1}))

    def test_unittest_suite_that_skips_every_test_is_error(self):
        """`Ran N tests` is collection, not execution: an all-skipped run executed nothing."""
        state, counts, reason = runner.settle(
            self.suite(assertion="unittest"), exit_code=0, timed_out=False,
            output="Ran 2 tests in 0.002s\n\nOK (skipped=2)\n")
        self.assertEqual(state, "ERROR")
        self.assertEqual(counts, {"executed": 2, "skipped": 2})
        self.assertIn("all skipped", reason)

    def test_counter_suite_with_zero_checks_is_error(self):
        suite = self.suite(assertion="counter", count_regexes=(r"^x: (?P<passed>\d+)/(?P<total>\d+) ok$",))
        state, counts, _ = runner.settle(suite, exit_code=0, timed_out=False, output="x: 0/0 ok\n")
        self.assertEqual(state, "ERROR")
        self.assertEqual(counts, {"passed": 0, "executed": 0, "total": 0})

    def test_counter_suite_without_its_line_is_error(self):
        suite = self.suite(assertion="counter", count_regexes=(r"^x: (?P<passed>\d+) ok$",))
        self.assertEqual(runner.settle(suite, exit_code=0, timed_out=False, output="nothing\n")[0],
                         "ERROR")

    def test_counter_line_that_hides_checks_is_error(self):
        suite = self.suite(assertion="counter",
                           count_regexes=(r"^x: (?P<passed>\d+)/(?P<total>\d+) ok$",))
        self.assertEqual(runner.settle(suite, exit_code=0, timed_out=False, output="x: 2/3 ok\n")[0],
                         "ERROR")

    def test_counter_accepts_declared_subcase_skips(self):
        suite = self.suite(assertion="counter", count_regexes=(
            r"^ *Tests +(?P<passed>\d+) passed(?: \| (?P<skipped>\d+) skipped)? \((?P<total>\d+)\)$",
        ))
        state, counts, _ = runner.settle(suite, exit_code=0, timed_out=False,
                                         output=" Test Files  3 passed | 1 skipped (4)\n"
                                                "      Tests  47 passed | 1 skipped (48)\n")
        self.assertEqual(state, "PASS")
        self.assertEqual(counts, {"passed": 47, "executed": 48, "total": 48, "skipped": 1})

    def test_counter_failure_settles_fail(self):
        suite = self.suite(assertion="counter", count_regexes=(r"^x: (?P<passed>\d+) ok$",))
        self.assertEqual(runner.settle(suite, exit_code=1, timed_out=False, output="x: 2 ok\n")[0],
                         "FAIL")

    def test_require_regex_miss_on_a_passing_exit_is_error(self):
        suite = self.suite(assertion="exit", require_regex=r"^PASS: ")
        self.assertEqual(runner.settle(suite, exit_code=0, timed_out=False, output="done\n")[0],
                         "ERROR")
        self.assertEqual(runner.settle(suite, exit_code=0, timed_out=False,
                                       output="PASS: validated\n")[0], "PASS")

    def covered_child(self, parent_log: str, *, assertion: str = "counter",
                      patterns: tuple[str, ...] = (r"^child: (?P<passed>\d+)/(?P<total>\d+) ok$",),
                      parent_state: str = "PASS") -> runner.Outcome:
        """Settle a covered child whose parent's whole log is written for one test."""
        directory = Path(tempfile.mkdtemp(prefix="covered-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        log = directory / "parent.log"
        log.write_text(parent_log, encoding="utf-8")
        child = self.suite(id="child", assertion=assertion, count_regexes=patterns)
        parent = self.suite(id="parent")
        parent_outcome = runner.Outcome(suite_id=parent.id, state=parent_state, log=str(log))
        return runner.settle_covered(child, parent, parent_outcome, log)

    def test_covered_counter_child_with_zero_checks_is_error(self):
        outcome = self.covered_child("child: 0/0 ok\n")
        self.assertEqual(outcome.state, "ERROR")
        self.assertIn("zero executed checks", outcome.reason)
        self.assertEqual(outcome.counts, {"passed": 0, "executed": 0, "total": 0})

    def test_covered_counter_child_with_a_disagreeing_line_is_error(self):
        """The consistency rule of a scheduled counter suite applies through `covered_by` too.

        A PASS parent with the real dispatch-guard pattern (`dispatch-guards: 1/100 ok`) used to
        settle this child PASS although `settle` rejects that identical summary as ERROR, so
        contradictory evidence went green by not being scheduled.
        """
        outcome = self.covered_child("dispatch-guards: 1/100 ok\n", patterns=(
            r"^dispatch-guards: (?P<passed>\d+)/(?P<total>\d+) ok$",
        ))
        self.assertEqual(outcome.state, "ERROR")
        self.assertEqual(outcome.counts, {"passed": 1, "executed": 100, "total": 100})
        self.assertIn("disagrees", outcome.reason)

    def test_covered_unittest_child_needs_a_summary_in_the_parent_log(self):
        outcome = self.covered_child("the parent ran the child without a summary\n",
                                     assertion="unittest", patterns=())
        self.assertEqual(outcome.state, "ERROR")
        self.assertIn("no unittest summary", outcome.reason)
        outcome = self.covered_child("Ran 4 tests in 0.002s\n\nOK\n",
                                     assertion="unittest", patterns=())
        self.assertEqual((outcome.state, outcome.counts), ("PASS", {"executed": 4}))

    def test_covered_unittest_child_that_skips_every_test_is_error(self):
        outcome = self.covered_child("Ran 2 tests in 0.002s\n\nOK (skipped=2)\n",
                                     assertion="unittest", patterns=())
        self.assertEqual(outcome.state, "ERROR")
        self.assertIn("all skipped", outcome.reason)

    def test_covered_child_of_a_skipped_or_failed_parent_is_never_pass(self):
        skipped = self.covered_child("", parent_state="SKIP")
        self.assertEqual(skipped.state, "SKIP")
        self.assertIn("parent parent skipped", skipped.reason)
        failed = self.covered_child("", parent_state="FAIL")
        self.assertEqual(failed.state, "ERROR")
        self.assertIn("parent parent settled FAIL", failed.reason)

    def test_timeout_signal_and_spawn_failures(self):
        self.assertEqual(runner.settle(self.suite(), exit_code=None, timed_out=True, output="")[0],
                         "TIMEOUT")
        self.assertEqual(runner.settle(self.suite(), exit_code=-9, timed_out=False, output="")[0],
                         "ERROR")
        self.assertEqual(runner.settle(self.suite(), exit_code=None, timed_out=False, output="")[0],
                         "ERROR")
        self.assertEqual(runner.settle(self.suite(), exit_code=0, timed_out=False, output="",
                                       provisioned=False)[0], "ERROR")

    def test_timeout_reason_reports_the_teardown_it_observed(self):
        """The record says what teardown established, not what it hoped for."""
        suite = self.suite()
        nothing = runner.settle(suite, exit_code=0, timed_out=True, output="",
                                teardown=runner.Teardown())
        self.assertEqual(nothing[0], "TIMEOUT")
        self.assertIn("no processes remained to be terminated", nothing[2])
        observed = runner.settle(suite, exit_code=0, timed_out=True, output="",
                                 teardown=runner.Teardown(attempts=(delivery(4242, stopped=True),)))
        self.assertIn("the spawned process terminated", observed[2])
        unobserved = runner.settle(suite, exit_code=0, timed_out=True, output="")
        self.assertIn("teardown was not observed", unobserved[2])
        survivor = runner.settle(suite, exit_code=0, timed_out=True, output="",
                                 teardown=runner.Teardown(attempts=(
                                     delivery(4242, runner.ESCALATION_NAMES[-1]),)))
        self.assertIn("4242", survivor[2])
        self.assertIn("survived SIGKILL", survivor[2])
        unverified = runner.settle(suite, exit_code=0, timed_out=True, output="",
                                   teardown=runner.Teardown(
                                       unverified=(runner._unverified(runner.NO_ENUMERATION),)))
        self.assertIn("unverified", unverified[2])
        self.assertIn("cannot enumerate", unverified[2])


class TeardownRecordTests(unittest.TestCase):
    """`Teardown` says what it established, and nothing it did not."""

    def test_a_surviving_pid_does_not_suppress_a_terminated_target(self):
        """Clauses describe their own targets: a survivor elsewhere is not the terminated target."""
        described = runner.Teardown(attempts=(
            delivery(4242, "SIGTERM", start="7", stopped=True),
            delivery(99, runner.ESCALATION_NAMES[-1], start="8"),
        )).describe()
        self.assertIn("the spawned process terminated", described)
        self.assertIn("99 survived SIGKILL", described)

    def test_unverified_notes_are_deduplicated_as_units(self):
        """Merging keeps each note whole instead of joining first and deduplicating a string."""
        merged = (runner.Teardown(unverified=("a", "b"))
                  .merge(runner.Teardown(unverified=("b", "c"))))
        self.assertEqual(merged.unverified, ("a", "b", "c"))

    def test_unverified_notes_alone_mean_the_record_is_not_verified(self):
        """`verified` is derived from the notes: none, verified; any, not verified."""
        self.assertTrue(runner.Teardown().verified)
        self.assertFalse(runner.Teardown(unverified=("a limit this run cannot observe",)).verified)

    def test_verified_is_false_for_a_limit_a_refusal_or_a_survivor_and_nothing_else(self):
        """`verified` is decided by the three qualifying facts, and a delivery qualifies nothing.

        The if-and-only-if, one term at a time: a record carrying only a limit note, only a refused
        delivery, or only a pid that took a delivered final signal and outlived the grace is not
        verified, while a record whose only content is a delivery that stopped the target is — a
        delivery is what the teardown established, not a reason to distrust it.
        """
        stopped = runner.Teardown(attempts=(delivery(4242, stopped=True),))
        self.assertTrue(stopped.verified, stopped.describe())
        self.assertFalse(runner.Teardown(unverified=("a limit",)).verified)
        self.assertFalse(runner.Teardown(attempts=(
            runner.Refusal(pid=4242, signal="SIGKILL", detail="not sent"),)).verified)
        self.assertFalse(runner.Teardown(attempts=(
            delivery(4242, runner.ESCALATION_NAMES[-1]),)).verified)

    def test_a_refusal_renders_its_own_note_and_is_not_a_limit(self):
        """A refusal is an attempt: its note says what was not sent, and it lives in `refused`."""
        refusal = runner.Refusal(pid=4242, signal="SIGKILL", detail="nothing was sent to it")
        teardown = runner.Teardown(attempts=(refusal,), unverified=("a limit",))
        self.assertEqual(teardown.refused, ("nothing was sent to it; teardown is unverified",))
        self.assertEqual(teardown.unverified, ("a limit",),
                         "a refusal must never be filed as a limit")
        self.assertEqual(teardown.delivered, ())
        self.assertEqual(teardown.describe(),
                         "a limit; nothing was sent to it; teardown is unverified")

    def test_merge_unions_attempts_and_limits_in_order_without_duplication(self):
        """`merge` is the union of the two stored facts, each kept once, order preserved."""
        term_refused = runner.Refusal(pid=7, signal="SIGTERM", detail="no pidfd for pid 7")
        kill_survived = delivery(9, runner.ESCALATION_NAMES[-1], start="2")
        left = runner.Teardown(attempts=(term_refused,), unverified=("a", "b"))
        right = runner.Teardown(attempts=(term_refused, kill_survived), unverified=("b", "c"))
        merged = left.merge(right)
        self.assertEqual(merged.attempts, (term_refused, kill_survived))
        self.assertEqual(merged.unverified, ("a", "b", "c"))
        self.assertEqual(merged.delivered, (kill_survived,))
        self.assertEqual(merged.refused, (term_refused.note,))
        self.assertEqual(merged.survivors, (9,))
        self.assertEqual(merged.clauses, ())
        self.assertFalse(merged.verified)

    def test_a_record_the_escalation_cannot_have_produced_is_refused(self):
        """The orderings the outcome rules forbid are refused where the record is built.

        Per pid: an attempt after a refusal or after a delivery that stopped the target is rejected,
        and so is a sequence ending on a delivery that is neither stopped nor the final escalation
        signal — the shape that would leave "delivered something, stopped nothing, refused nothing,
        no limit" readable as verified.
        """
        with self.assertRaises(ValueError):
            runner.Teardown(attempts=(delivery(4242),))
        with self.assertRaises(ValueError):
            runner.Teardown(attempts=(
                runner.Refusal(pid=4242, signal="SIGTERM", detail="not sent"),
                delivery(4242, runner.ESCALATION_NAMES[-1]),
            ))
        with self.assertRaises(ValueError):
            runner.Teardown(attempts=(
                delivery(4242, "SIGTERM", stopped=True),
                delivery(4242, runner.ESCALATION_NAMES[-1]),
            ))
        # The accepted shorthands and the real one- and two-attempt shapes stay constructible: a
        # lone stopped delivery, a lone final-signal delivery, and TERM then a stopped final signal.
        self.assertTrue(runner.Teardown(attempts=(delivery(4242, stopped=True),)))
        self.assertTrue(runner.Teardown(attempts=(delivery(4242, runner.ESCALATION_NAMES[-1]),)))
        self.assertTrue(runner.Teardown(attempts=(
            delivery(4242), delivery(4242, runner.ESCALATION_NAMES[-1], stopped=True))))

    def test_the_delivery_line_reads_back_as_the_attempt_it_was_written_from(self):
        """The line the runner writes and the pattern the tests read are one wording.

        The renderer (`Delivery.log_line`) and the reader (`DELIVERY_LINE_RE`, `DELIVERY_MARKER`)
        are the same fact in two forms: the attempt's pid, start time and signal name must come back
        out unchanged, which is what lets a log be compared with a record at all.
        """
        attempt = delivery(4242, "SIGKILL", start="112233")
        line = attempt.log_line()
        self.assertIn(runner.DELIVERY_MARKER, line)
        self.assertEqual(parse_delivery_lines(line), [("SIGKILL", 4242, 112233)])
        self.assertEqual([int(raw) for raw in runner.DELIVERY_TARGET_RE.findall(line)], [4242])


class TeardownOwnershipTests(PatchingTestCase):
    """Every signal must be justified by identity pinned at delivery (module docstring)."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)
        self.log_path = ARTIFACTS / "ownership.log"
        # Delivery rests on the run's own `SIGCHLD` disposition (`establish_exit_disposition`); the
        # end-to-end runs take that startup step in `main`, and these unit tests stand in for it
        # instead of inheriting whatever this test host happens to have.  Both the disposition and
        # the module state the step sets are restored, so no other test inherits either.
        self.patch(runner, "EXIT_DISPOSITION", False)
        if hasattr(signal, "SIGCHLD"):
            saved = signal.getsignal(signal.SIGCHLD)
            self.addCleanup(signal.signal, signal.SIGCHLD, saved)
            self.assertTrue(runner.establish_exit_disposition(),
                            "the test host will not let the run establish its own disposition")

    def spawn(self, *, code: str = "import time; time.sleep(60)",
              env: dict[str, str] | None = None) -> subprocess.Popen:
        """A child that is a session (and process group) leader, and always reaped."""
        process = subprocess.Popen([sys.executable, "-c", code], start_new_session=True,
                                   env={**os.environ, **env} if env else None)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def record_deliveries(self, deliveries: list) -> None:
        """Record every delivery and every pidfd the runner opens, and deliver nothing for real.

        The log holds `("open", pid)` per pin the runner opens and
        `("pidfd"|"kill"|"killpg", target, signum)` per delivery it attempts; signal 0 is the
        non-destructive liveness probe, never a delivery.  A pidfd's target is the pid the runner
        opened it for, with the kernel's own `/proc/self/fdinfo` as the fallback — fdinfo alone
        reports no pid for a handle whose process is already gone, which is exactly when the target
        must still be named.  Recording instead of forwarding keeps a fixture alive long enough for
        the escalation to be observed, and keeps every refusal test safe from a real signal.
        Instrumentation is conditional on the platform exposing the API: on a host without
        `os.pidfd_open` (or `os.killpg`) the refusal tests must still run and exercise the runner's
        own refusal, instead of failing in this recorder before they get there.
        """
        fds: dict[int, int] = {}
        real_kill = os.kill

        def kill(pid: int, signum: int) -> None:
            if signum:
                deliveries.append(("kill", pid, signum))
            real_kill(pid, signum)

        def send(fd: int, signum: int) -> None:
            deliveries.append(("pidfd", fds.get(fd) or pidfd_target(fd) or -1, signum))

        self.patch(os, "kill", kill)
        if hasattr(os, "pidfd_open"):
            real_open = os.pidfd_open

            def opening(pid: int, *flags: int) -> int:
                fd = real_open(pid, *flags)
                if not flags:  # `subprocess`'s own wait path passes one; that is not the run's pin
                    fds[fd] = pid
                    deliveries.append(("open", pid))
                return fd

            self.patch(os, "pidfd_open", opening)
        if hasattr(os, "killpg"):
            real_killpg = os.killpg

            def killpg(group: int, signum: int) -> None:
                if signum:
                    deliveries.append(("killpg", group, signum))
                real_killpg(group, signum)

            self.patch(os, "killpg", killpg)
        if hasattr(signal, "pidfd_send_signal"):
            self.patch(signal, "pidfd_send_signal", send)

    def deliveries(self, events: list, signum: int | None = None) -> list[tuple[str, int]]:
        """The recorded deliveries as (handle, pid), optionally only those of one signal."""
        return [(handle, pid) for handle, pid, *rest in events
                if handle != "open" and (signum is None or rest[0] == signum)]

    def anchor_fixture(self, fixture: str) -> tuple[runner.Spawned, int, int]:
        """Spawn a leader fixture that records its own and its same-group child's pids.

        Returns the spawned command (its identity recorded at spawn, as the run does), the leader's
        pid and the child's pid; both are killed when the test ends.
        """
        pid_file = ARTIFACTS / f"anchor-{time.monotonic_ns()}.txt"
        pid_file.unlink(missing_ok=True)
        process = self.spawn(code=fixture, env={"PID_FILE": str(pid_file)})
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        leader_pid, child_pid = (int(value) for value in pid_file.read_text().split())
        self.addCleanup(kill_quietly, child_pid)
        self.assertEqual(leader_pid, process.pid, "the fixture's pid file is not the leader's")
        return runner._spawned(process), leader_pid, child_pid

    @unittest.skipUnless(runner.PROC_ROOT.is_dir() and hasattr(os, "killpg"),
                         "the model reads /proc and POSIX group ids")
    def test_group_teardown_refuses_a_recycled_group_id(self):
        """A reaped command's pid is history, however complete the recycle looks to a field reader.

        Model: the command finished and this run reaped it, and the number now answers the one
        readable question the run asks about an instance — its start time, here with the very value
        recorded at spawn — so nothing field-shaped can tell the difference.  The pin is not
        field-shaped: `pidfd_open` cannot be opened for a pid the kernel has released, so the
        teardown must refuse every delivery and report teardown unverified, and the unrelated
        process the number now names must not be signalled.
        """
        victim = self.spawn()
        command = self.spawn(code="pass")
        spawned = runner._spawned(command)  # recorded at spawn, the way the run records it
        command.wait()  # reaped: the pid no longer names the instance this run spawned
        self.patch(runner, "_start_time", lambda pid: spawned.start)
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        self.assertEqual(self.deliveries(deliveries), [],
                         "the teardown signalled a number it cannot prove is this run's")
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())
        self.assertNotIn("terminated", teardown.describe())
        self.assertIsNone(victim.poll(), "the unrelated group's leader was signalled")

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX process groups only")
    def test_group_teardown_refuses_without_the_proc_evidence_it_cannot_pin(self):
        """A host without `/proc` cannot read an identity, so no delivery can be justified.

        Model: POSIX with the group API but no `/proc` (macOS).  The group number is not a target
        in its own right — nothing about it can be proven — and no start time can be read, so the
        teardown must signal nothing at all, report the processes it cannot even enumerate, and
        record the limit.
        """
        process = self.spawn()
        spawned = runner._spawned(process)
        self.patch(runner, "PROC_ROOT", Path("/nonexistent-proc"))
        self.patch(runner, "KILL_GRACE_SECONDS", 0.5)
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        self.assertEqual(self.deliveries(deliveries), [],
                         "a delivery was attempted with no /proc to read an identity from")
        self.assertFalse(teardown.verified)
        # The refusal names the first capability this host cannot hold: `/proc` on a host with
        # pidfds, the pidfd itself where the platform has none (an earlier gate refuses there).
        expected = "pidfd" if not runner.PIDFD_PINNING else "/proc"
        self.assertIn(expected, teardown.describe(),
                      f"the refusal does not name what this host cannot hold: {teardown.describe()}")
        self.assertNotIn("terminated", teardown.describe())
        self.assertIsNone(process.poll(), "the probe's own child must stay untouched")

    @unittest.skipUnless(runner.WAITID_WNOWAIT and runner.PIDFD_PINNING,
                         "the observation is waitid(WNOWAIT) and the identity is a pidfd")
    def test_an_observed_exit_leaves_the_pid_reserved_for_the_teardown(self):
        """The exit is observed without reaping, so the identity recorded at spawn still pins.

        This is what still lets a signal-killed suite be torn down: the command is dead, but its
        pid — and with it the group it leads — stays reserved until this run reaps it itself.
        """
        spawned = runner._spawned(self.spawn(code="import sys; sys.exit(3)"))
        self.assertEqual(runner._observe_exit(spawned.process, 5), (3, False))
        self.assertIsNone(spawned.process.returncode, "the observation reaped the command")
        self.assertEqual(runner._proc_state(spawned.pid), "Z",
                         "the observation reaped the command instead of leaving it reserved")
        pin, note = runner._pin_identity(spawned.pid, spawned.start)
        self.assertIsNotNone(pin, f"a zombie's recorded identity is no longer pinnable: {note}")
        pin.close()
        killed = runner._spawned(self.spawn())
        os.kill(killed.pid, signal.SIGKILL)
        self.assertEqual(runner._observe_exit(killed.process, 5), (-signal.SIGKILL, False))
        self.assertIsNone(killed.process.returncode, "the observation reaped the signalled command")

    @unittest.skipUnless(runner.WAITID_WNOWAIT and runner.PIDFD_PINNING,
                         "a reaped pid is refused by the identity pin itself")
    def test_an_externally_reaped_child_is_no_longer_this_runs_to_signal(self):
        """A reaper outside `Popen` leaves `returncode` at None; the identity pin is the proof.

        Model: another waiter reaped the command (`os.waitpid`) — its number no longer names
        anything, and the cached field cannot see that.  The start time is unreadable and
        `pidfd_open` raises for the pid, so the teardown must refuse it and report teardown
        unverified rather than signal a number whose content it can no longer ask about.
        """
        spawned = runner._spawned(self.spawn(code="pass"))
        os.waitpid(spawned.pid, 0)  # reaped outside Popen: the cached returncode stays None
        self.assertIsNone(spawned.process.returncode,
                          "the external reap must stay invisible to Popen")
        pin, note = runner._pin_identity(spawned.pid, spawned.start)
        self.assertIsNone(pin, f"a pid the kernel no longer holds is no identity to pin: {note}")
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        self.assertEqual(self.deliveries(deliveries), [],
                         "the teardown signalled a pid the kernel no longer reserves for it")
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the non-reaping observation is waitid(WNOWAIT)")
    def test_an_externally_reaped_child_is_a_lost_exit_not_a_status(self):
        """A child reaped elsewhere is not waitable: the exit observation must say so.

        `waitid` raises `ChildProcessError` once the kernel no longer holds the child; returning
        that as a status (or letting it escape) would settle a suite on evidence that does not
        exist.  The observation reports the loss for the caller to settle as an error.
        """
        process = self.spawn(code="pass")
        os.waitpid(process.pid, 0)
        self.assertEqual(runner._observe_exit(process, 5), (None, True),
                         "a status that is gone is reported as lost, not as an exit")

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX process groups only")
    def test_an_unowned_live_command_is_refused_without_claiming_survivors(self):
        """Nothing was signalled to a command whose identity was never recorded, so nothing
        "survived SIGKILL".

        Model: the run holds a live command but never recorded its identity — the start time could
        not be read when it was spawned — so no delivery can be justified.  The refusal must not
        wait out the kill grace on a process nothing stopped, and the record must not borrow the
        survivor wording of a signalled process.
        """
        process = self.spawn(code="import time; time.sleep(60)")
        spawned = runner.Spawned(process=process, start=None)
        self.patch(runner, "KILL_GRACE_SECONDS", 5.0)
        deliveries: list = []
        self.record_deliveries(deliveries)
        started = time.monotonic()
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.0,
                        "an unpinnable command was waited out instead of refused")
        self.assertEqual(self.deliveries(deliveries), [],
                         "a delivery was attempted with no identity to pin")
        self.assertEqual(teardown.survivors, ())
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())
        self.assertIsNone(process.poll(), "the probe's own child must stay untouched")
        self.assertNotIn(runner.DELIVERY_MARKER, self.log_path.read_text(encoding="utf-8"),
                         "the log claimed a delivery that never happened")

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the exit observation must not reap")
    def test_a_clean_exit_whose_group_cannot_be_checked_is_recorded_unverified(self):
        """When the group cannot be checked before the reap, the record must not claim it emptied.

        Model: the identity can no longer be read at the check (a host without `waitid(WNOWAIT)`
        reaps its command inside the exit observation; here `/proc` itself is gone by then) while
        the exit itself was observed normally; the reap must still happen, and the record must say
        the check did not.
        """
        spawned = runner._spawned(self.spawn(code="pass"))
        self.assertEqual(runner._observe_exit(spawned.process, 5), (0, False))
        self.patch(runner, "PROC_ROOT", Path("/nonexistent-proc"))
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._teardown_before_reap(spawned, log)
        self.assertEqual(self.deliveries(deliveries), [],
                         "a clean exit was signalled: only the process this run spawned is ever "
                         "signalled, and this path signals nothing at all")
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())
        self.assertIn("could not be checked before the reap", teardown.describe())
        self.assertIsNotNone(spawned.process.poll(), "the command must still be reaped")

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX process groups only")
    def test_an_externally_reaped_child_is_no_proof_without_the_kernel_probe(self):
        """Where there is no `waitid(WNOWAIT)` probe, a cached field is all that is left — and it
        cannot see a reap, so it is not an identity.

        Model: a host without the non-reaping observation and a command reaped by someone else, so
        `Popen.returncode` still reads None while the kernel's hold on the child is long gone.  The
        absence of the probe must fail closed: no pin, no signal, teardown unverified.
        """
        spawned = runner._spawned(self.spawn(code="pass"))
        os.waitpid(spawned.pid, 0)  # reaped outside Popen: the cached returncode stays None
        self.assertIsNone(spawned.process.returncode,
                          "the external reap must stay invisible to Popen")
        self.patch(runner, "WAITID_WNOWAIT", False)
        self.patch(runner, "KILL_GRACE_SECONDS", 0.2)
        pin, note = runner._pin_identity(spawned.pid, spawned.start)
        self.assertIsNone(pin, f"a cached `returncode` is not an identity to pin: {note}")
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        self.assertEqual(self.deliveries(deliveries), [],
                         "a signal went out with no pinnable identity behind it")
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX process groups only")
    def test_ownership_is_refused_where_the_disposition_was_never_established(self):
        """A run that could not establish its own child-reaping disposition proves nothing.

        Model: the startup step failed (`EXIT_DISPOSITION` stays False — no `SIGCHLD` on this
        platform, or a process that will not let the run change it), so the reservation the
        delivery's identity rests on cannot be held.  The teardown must refuse instead of
        signalling, and say why.
        """
        process = self.spawn(code="import time; time.sleep(60)")
        self.patch(runner, "EXIT_DISPOSITION", False)
        self.patch(runner, "KILL_GRACE_SECONDS", 0.5)
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(runner._spawned(process), log)
        self.assertEqual(self.deliveries(deliveries), [],
                         "a signal went out with no disposition to justify it")
        self.assertFalse(teardown.verified)
        self.assertIn("SIGCHLD", teardown.describe())
        self.assertIsNone(process.poll(), "the probe's own child must stay untouched")

    @unittest.skipUnless(hasattr(signal, "SIGCHLD") and hasattr(signal, "SIG_IGN"),
                         "the gate is the SIGCHLD disposition itself")
    def test_a_sigchld_disposition_changed_after_startup_refuses_delivery(self):
        """A disposition changed after startup must not leave the invariant reported intact.

        Model: the run established `SIG_DFL` before spawning, and `SIGCHLD` was changed afterwards
        (a library, an operator, an inherited handler restored) — the kernel will now reap this
        run's children inside their own exit, so the reservation the delivery rests on is gone even
        though the startup step once succeeded.  The gate must read the live disposition and
        refuse, never trust the recorded one.
        """
        process = self.spawn(code="import time; time.sleep(60)")
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(runner._spawned(process), log)
        self.assertEqual(self.deliveries(deliveries), [],
                         "a signal went out while the disposition was no longer SIG_DFL")
        self.assertFalse(teardown.verified)
        self.assertIn("SIGCHLD", teardown.describe())
        self.assertIsNone(process.poll(), "the probe's own child must stay untouched")

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX process groups only")
    def test_a_platform_without_pidfds_refuses_every_delivery(self):
        """`pidfd is unavailable (platform)` is a refusal, never a fallback to a bare pid.

        Model: POSIX process groups and `/proc` exist, but the platform cannot open a pidfd (no
        `os.pidfd_open`/`signal.pidfd_send_signal` — Windows), so the target's identity cannot be
        pinned at delivery.  Nothing may be signalled, and the record must name the reason.
        """
        process = self.spawn(code="import time; time.sleep(60)")
        self.patch(runner, "PIDFD_PINNING", False)
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(runner._spawned(process), log)
        self.assertEqual(self.deliveries(deliveries), [],
                         "a signal was delivered without a pidfd to carry the identity")
        self.assertFalse(teardown.verified)
        self.assertIn("pidfd", teardown.describe())
        self.assertIsNone(process.poll(), "the probe's own child must stay untouched")

    def test_a_platform_without_a_readable_pidfd_api_still_runs_its_refusal_tests(self):
        """The delivery recorder instruments pidfd APIs only where the platform has them.

        Model: the same platform as the refusal test above — no `os.pidfd_open` — reached through
        this module's own instrumentation instead of `PIDFD_PINNING`: the API is genuinely absent
        for the duration of this test rather than set to a stand-in value, the recorder must not
        read or patch what the platform does not expose, and the refusal must still be the runner's
        own, recorded as nothing delivered.
        """
        process = self.spawn(code="import time; time.sleep(60)")
        self.remove_attribute(os, "pidfd_open")  # the platform genuinely has no such attribute
        self.patch(runner, "PIDFD_PINNING", False)
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(runner._spawned(process), log)
        self.assertEqual(self.deliveries(deliveries), [],
                         "a signal was delivered on a platform without pidfds")
        self.assertFalse(teardown.verified)
        self.assertIn("pidfd", teardown.describe())
        self.assertIsNone(process.poll(), "the probe's own child must stay untouched")

    @unittest.skipUnless(runner.PIDFD_PINNING, "the pin is a pidfd")
    def test_a_pid_that_no_longer_names_the_spawned_instance_is_refused(self):
        """The pinned start time is what makes the pin the run's own instance, not just any.

        Model: the number still names a live process, but a *different* instance — the start time
        the run's evidence carries does not match what the pid reports now.  The pin must refuse
        it, because delivering on that number would signal a process that is not the one this run
        addressed; the note states both readings instead of claiming the target was spawned here.
        """
        process = self.spawn(code="import time; time.sleep(60)")
        real_start = runner._start_time(process.pid)
        self.assertIsNotNone(real_start, "the fixture's start time must be readable")
        pin, note = runner._pin_identity(process.pid, str(int(real_start) + 1))
        self.assertIsNone(pin, "a mismatched expected identity was pinned anyway")
        self.assertIn("no longer names the process instance the evidence identified", note)
        self.assertIn(real_start, note, "the note must state what the pid reports now")
        self.assertNotIn("at spawn", note,
                         "the note must not claim a target this run never spawned")
        pin, note = runner._pin_identity(process.pid, real_start)
        self.assertIsNotNone(pin, note)
        pin.close()

    @unittest.skipUnless(runner.PROC_ROOT.is_dir(), "the report reads /proc")
    def test_no_scratch_holder_is_ever_signalled_only_reported(self):
        """A scratch holder is a report line, never a target: the run signals only what it spawned.

        Model: a live worker whose cwd really is the suite's scratch tree (found by the same
        `/proc` probe the report uses).  Whatever such an enumeration finds, nothing is delivered
        to it, it keeps running, the record names it as found and left alone, no kill grace is
        waited out for it, and the log claims no delivery it did not make.
        """
        scratch = Path(tempfile.mkdtemp(prefix="scratch-report-", dir=self.log_path.parent))
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                  cwd=scratch, env={}, start_new_session=True)
        self.addCleanup(worker.wait)
        self.addCleanup(kill_quietly, worker.pid)
        log_path = ARTIFACTS / "scratch-report.log"
        self.patch(runner, "KILL_GRACE_SECONDS", 0.3)
        deliveries: list = []
        self.record_deliveries(deliveries)
        started = time.monotonic()
        teardown = runner._report_scratch(scratch, log_path)
        self.assertLess(time.monotonic() - started, 2.0, "a report waited out a kill grace")
        self.assertEqual(self.deliveries(deliveries), [],
                         "a delivery was attempted for a scratch holder")
        self.assertEqual(teardown.survivors, (),
                         "a process that was never signalled is not a survivor")
        self.assertFalse(teardown.verified)
        self.assertIn("left alone", teardown.describe())
        self.assertIn(str(worker.pid), teardown.describe(),
                      "the report must name the process it left alone")
        self.assertTrue(process_running(worker.pid), "the holder must be left running")
        log_text = log_path.read_text(encoding="utf-8")
        self.assertNotIn(runner.DELIVERY_MARKER, log_text, "the log claimed a delivery it never made")
        self.assertIn("left alone", log_text)
        self.assertIn(str(worker.pid), log_text)

    @unittest.skipUnless(can_deliver_signals(), "the delivery needs a pinnable identity")
    def test_members_are_never_signalled_however_well_their_evidence_matches(self):
        """Membership evidence is never a delivery authority: only the spawned process is signalled.

        Model: the enumeration hands back the spawned process and a same-group member, each with
        the start time its pid really reports right now — every per-pid check a delivery could make
        would pass, so this models the worst case the removed per-member delivery could not survive
        (the group number outliving whatever made it that run's own).  The rule that replaces it:
        the member must receive nothing, the spawned process must be delivered to through a pin
        reopened for each round (TERM, then KILL — the fixture ignores TERM), and the record must
        name the member as found and left alone.
        """
        spawned, leader_pid, child_pid = self.anchor_fixture(HELD_LEADER)
        self.patch(runner, "KILL_GRACE_SECONDS", 0.5)
        self.patch(runner, "_group_members",
                   lambda group: [(leader_pid, spawned.start),
                                  (child_pid, runner._start_time(child_pid))])
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        sends = [entry for entry in deliveries if entry[0] != "open"]
        self.assertEqual(self.deliveries(deliveries, signal.SIGTERM), [("pidfd", leader_pid)],
                         "the spawned process was not the only TERM target")
        self.assertEqual(self.deliveries(deliveries, signal.SIGKILL), [("pidfd", leader_pid)],
                         "the spawned process was not the only SIGKILL target")
        self.assertEqual({pid for _handle, pid, _signum in sends}, {leader_pid},
                         f"a delivery targeted something other than the spawned process: {sends}")
        term_index = deliveries.index(("pidfd", leader_pid, signal.SIGTERM))
        kill_index = deliveries.index(("pidfd", leader_pid, signal.SIGKILL))
        self.assertIn(("open", leader_pid), deliveries[term_index:kill_index],
                      "the second round reused an earlier pin instead of re-pinning")
        self.assertFalse(teardown.verified)
        self.assertIn("left alone", teardown.describe())
        self.assertIn(str(child_pid), teardown.describe(),
                      "the note must name the member that was left alone")
        self.assertNotIn(str(child_pid), " ".join(teardown.clauses),
                         "the record must not claim the member as a target it terminated")

    @unittest.skipUnless(can_deliver_signals(), "the delivery needs a pinnable identity")
    def test_no_signal_is_delivered_to_a_target_lost_after_the_rounds_last_probe(self):
        """Nothing is carried by a bare number, even when the loss lands inside the enumeration.

        The spawned process is killed and reaped by a thread this run does not control at the
        moment the group is read — after the escalation already delivered through pinned handles,
        and before any report is written.  Every delivery must still be a pidfd open for its own
        target, the surviving member must not be signalled by anything, and the record must say it
        was found and left alone.
        """
        spawned, leader_pid, child_pid = self.anchor_fixture(HELD_LEADER)
        reaped: list[int] = []
        reaper = threading.Thread(target=lambda: reaped.append(os.waitpid(leader_pid, 0)[0]),
                                  daemon=True)
        reaper.start()
        kill_directly = os.kill  # before the delivery recorder patches it: this kill is the test's
        real_members = runner._group_members
        released: list[bool] = []

        def release_then_enumerate(group: int) -> list[tuple[int, str]] | None:
            members = real_members(group)
            if not released:
                released.append(True)
                kill_directly(leader_pid, signal.SIGKILL)  # release it to the external reaper
                reaper.join(5)
            return members

        self.patch(runner, "_group_members", release_then_enumerate)
        self.patch(runner, "KILL_GRACE_SECONDS", 0.5)
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        self.assertEqual(reaped, [leader_pid], "the external reaper did not take the status")
        recorded = self.deliveries(deliveries)
        self.assertEqual({handle for handle, _pid in recorded}, {"pidfd"},
                         f"a signal was carried by something other than a pinned handle: {recorded}")
        for index, entry in enumerate(deliveries):
            if entry[0] == "pidfd":
                self.assertIn(("open", entry[1]), deliveries[:index],
                              "a signal went through a handle not opened for its target")
        sends = [entry for entry in deliveries if entry[0] != "open"]
        self.assertEqual({pid for _handle, pid, _signum in sends}, {leader_pid},
                         f"a delivery targeted something other than the spawned process: {sends}")
        self.assertFalse(teardown.verified)
        self.assertIn("left alone", teardown.describe())
        self.assertIn(str(child_pid), teardown.describe(),
                      "the member that outlived the spawned process is not named in the record")

    @unittest.skipUnless(can_deliver_signals(), "the delivery needs a pinnable identity")
    def test_only_the_spawned_process_is_delivered_to_and_re_pinned_every_round(self):
        """The spawned process is the only target, and each round re-pins it at delivery.

        The spawned process and its same-group member both ignore SIGTERM, so both rounds run.  The
        escalation must deliver TERM and then KILL to the spawned process alone — each through a
        pidfd opened for it after the previous round, never an earlier round's handle, and never a
        bare pid or group number — and the member that outlives it must be reported as found and
        left alone, not as a survivor (nothing was delivered to it).
        """
        spawned, leader_pid, child_pid = self.anchor_fixture(HELD_LEADER)
        self.patch(runner, "KILL_GRACE_SECONDS", 0.5)
        events: list = []
        self.record_deliveries(events)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        sends = [entry for entry in events if entry[0] != "open"]
        self.assertEqual([handle for handle, _pid, _sig in sends], ["pidfd"] * len(sends),
                         f"a signal went out through something other than a pinned pidfd: {sends}")
        for signum in (signal.SIGTERM, signal.SIGKILL):
            self.assertEqual(self.deliveries(events, signum), [("pidfd", leader_pid)],
                             f"pid {leader_pid} was not the only {signal.Signals(signum).name} "
                             f"target")
        term_index = events.index(("pidfd", leader_pid, signal.SIGTERM))
        kill_index = events.index(("pidfd", leader_pid, signal.SIGKILL))
        self.assertIn(("open", leader_pid), events[term_index:kill_index],
                      "the second round reused an earlier pin instead of re-pinning")
        self.assertEqual({pid for _handle, pid, _signum in sends}, {leader_pid},
                         f"a delivery targeted something other than the spawned process: {sends}")
        self.assertEqual(teardown.survivors, (leader_pid,),
                         "the spawned process took both delivered signals and outlived them")
        self.assertNotIn(child_pid, teardown.survivors,
                         "a member that was never signalled is not a survivor")
        self.assertEqual(teardown.clauses, (), teardown.describe())
        self.assertFalse(teardown.verified)
        self.assertIn(str(child_pid), teardown.describe(),
                      "the member that outlived the spawned process must be named")
        self.assertIn("left alone", teardown.describe())

    @unittest.skipUnless(can_deliver_signals(), "the escalation needs a pinnable identity")
    def test_escalation_stops_when_the_anchor_is_lost_before_a_round(self):
        """The escalation stops with the spawned process: a lost pid is not signalable again.

        The spawned process ignores SIGTERM and exits by itself inside the first grace window, and
        a thread this run does not control is already blocked in `os.waitpid` on it, so the status
        — and with it the instance the recorded identity names — is gone the moment it exits.  The
        first round delivers to it through its pin; the second round must find the identity lost,
        send no SIGKILL, and record the group's members as found and left alone instead of claiming
        a termination it can no longer justify.
        """
        spawned, leader_pid, child_pid = self.anchor_fixture(ANCHOR_LEADER)
        reaped: list[int] = []
        reaper = threading.Thread(target=lambda: reaped.append(os.waitpid(leader_pid, 0)[0]),
                                  daemon=True)
        reaper.start()
        self.patch(runner, "KILL_GRACE_SECONDS", 1.0)
        deliveries: list = []
        self.record_deliveries(deliveries)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        reaper.join(5)
        self.assertEqual(reaped, [leader_pid], "the external reaper did not take the status")
        self.assertEqual(self.deliveries(deliveries, signal.SIGTERM), [("pidfd", leader_pid)],
                         "the first round did not deliver to the spawned process through its pin")
        self.assertEqual(self.deliveries(deliveries, signal.SIGKILL), [],
                         "escalation continued although the spawned process was lost")
        self.assertEqual(teardown.survivors, (),
                         "a process whose identity was lost is not a survivor")
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())
        self.assertIn(str(child_pid), teardown.describe(),
                      "the member left behind must be named in the record")
        self.assertEqual(teardown.clauses, ("the spawned process",), teardown.describe())

    @unittest.skipUnless(can_deliver_signals(), "the delivery needs a pinnable identity")
    def test_an_already_terminated_target_resolves_the_delivery_that_stopped_it(self):
        """A round that finds the target already gone resolves the delivery that preceded it.

        Model: the target ignores SIGTERM and dies between the first round's grace and the second
        round's identity check — killed at that boundary here, so the state is reached
        deterministically, which is the state a target that exits on its own produces — and the
        kernel keeps the corpse until this run reaps it, so the second round's pin still succeeds
        and the round finds it in `Z`.  The log already carries the SIGTERM delivery, so the record
        must resolve that delivery as what the target stopped after: a termination, never "no
        processes remained to be terminated" against a log that records a delivery.
        """
        child = self.spawn(code="import signal, time;"
                                " signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)")
        time.sleep(0.2)  # let the fixture's handler land: the delivery must not end it
        spawned = runner._spawned(child)
        real_pin = runner._pin_identity
        rounds: list[int] = []

        def pin(pid: int, expected: str):
            rounds.append(pid)
            if len(rounds) == 2:  # the target dies before the second round's identity check
                os.kill(child.pid, signal.SIGKILL)
                time.sleep(0.1)
            return real_pin(pid, expected)

        self.patch(runner, "_pin_identity", pin)
        self.patch(runner, "KILL_GRACE_SECONDS", 0.2)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        self.assertEqual(rounds, [child.pid, child.pid],
                         "the escalation did not reach its second round")
        self.assertEqual(teardown.delivered,
                         (runner.Delivery(pid=child.pid, start=spawned.start, signal="SIGTERM",
                                          stopped=True),),
                         teardown.describe())
        self.assertEqual(teardown.clauses, ("the spawned process",), teardown.describe())
        self.assertEqual(teardown.survivors, (), "a target that stopped is no survivor")
        self.assertEqual(teardown.refused, ())
        self.assertTrue(teardown.verified, teardown.describe())
        self.assertEqual(teardown.describe(), "the spawned process terminated")
        self.assertEqual(parse_delivery_lines(self.log_path.read_text(encoding="utf-8")),
                         [("SIGTERM", child.pid, int(spawned.start))])


class StartTimeOracleTests(PatchingTestCase):
    """The identity every published reading carries is pinned against a test-side parse."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)
        self.log_path = ARTIFACTS / "start-time-oracle.log"
        # `_stop_spawned`'s delivery path rests on the run's own `SIGCHLD` disposition
        # (`establish_exit_disposition`); the end-to-end runs take that startup step in `main`, and
        # this class stands in for it instead of inheriting whatever this test host happens to
        # have.  Both the disposition and the module state the step sets are restored.
        self.patch(runner, "EXIT_DISPOSITION", False)
        if hasattr(signal, "SIGCHLD"):
            saved = signal.getsignal(signal.SIGCHLD)
            self.addCleanup(signal.signal, signal.SIGCHLD, saved)
            self.assertTrue(runner.establish_exit_disposition(),
                            "the test host will not let the run establish its own disposition")

    def spawn(self, *, code: str = "import time; time.sleep(60)",
              cwd: Path | None = None) -> subprocess.Popen:
        """A child in its own session, killed and reaped by this test."""
        return self.spawn_via(sys.executable, code=code, cwd=cwd)

    def spawn_via(self, interpreter: Path | str, *, code: str = "import time; time.sleep(60)",
                  cwd: Path | None = None) -> subprocess.Popen:
        """A child started through `interpreter`, so its kernel `comm` is `interpreter`'s basename."""
        process = subprocess.Popen([str(interpreter), "-c", code], cwd=cwd, start_new_session=True)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def interpreter_named(self, name: str) -> Path:
        """A symlink to this interpreter whose basename is `name` — a fixture's kernel `comm`.

        `/proc/<pid>/stat` carries the executed file's basename as its second field, so a fixture
        started through this link is exactly the input a `comm` containing stat-shaped text
        (`) `, a bare `(`) produces; the link is made inside this test's artifact tree.
        """
        directory = ARTIFACTS / "interpreters"
        directory.mkdir(parents=True, exist_ok=True)
        link = directory / name
        if not link.exists():
            link.symlink_to(sys.executable)
        return link

    @unittest.skipUnless(can_deliver_signals(), "the spy needs one real pidfd delivery")
    def test_the_spy_reads_the_start_time_itself_not_through_the_runner(self):
        """The kernel side of the trijection is read without the runner's start-time readers.

        One real pidfd delivery goes through the installed spy (the fixture ignores SIGTERM, so the
        process the spy reads stays the one the delivery reached), and the start time the spy
        records must be this test's own parse of `/proc/<pid>/stat`: a spy that delegated to the
        runner would publish whatever the runner read, which is exactly what this reading exists to
        catch.
        """
        child = self.spawn(code="import signal, time; signal.signal(signal.SIGTERM, "
                                "signal.SIG_IGN); time.sleep(60)")
        independent = proc_start_time(child.pid)
        self.assertIsNotNone(independent, "the test could not read the fixture's own start time")
        fd = os.pidfd_open(child.pid)
        spy = DeliverySpy()
        try:
            signal.pidfd_send_signal(fd, signal.SIGTERM)
        finally:
            spy.close()
            os.close(fd)
        self.assertEqual(spy.sent, [("SIGTERM", child.pid, int(independent))])

    @unittest.skipUnless(can_deliver_signals(), "the record's identity needs one real delivery")
    def test_the_start_time_every_reading_reports_is_the_readers_own_field_22(self):
        """Every reading is compared with this test's own parse of its own target's field 22.

        The value `_spawned` records, what `_start_time` re-reads, what the group report carries
        and what the delivered entry publishes are readings of the spawned child, each compared
        against this test's independent parse of the child's `/proc/<pid>/stat`; the scratch
        report's reading is of the holder, and is compared against this test's independent parse of
        the holder's file.  A runner that indexed another field could not publish any of them.
        """
        child = self.spawn()
        independent = proc_start_time(child.pid)
        self.assertIsNotNone(independent, "the test could not read the fixture's own start time")
        spawned = runner._spawned(child)
        self.assertEqual(spawned.start, independent, "the spawn record is not field 22")
        self.assertEqual(runner._start_time(child.pid), independent,
                         "the runner's own start-time read is not field 22")
        self.assertEqual(dict(runner._group_members(child.pid)).get(child.pid), independent,
                         "the group report's start time is not field 22")
        scratch = ARTIFACTS / "start-time-scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        holder = self.spawn(cwd=scratch)
        holder_start = proc_start_time(holder.pid)
        self.assertIsNotNone(holder_start, "the test could not read the holder's own start time")
        self.assertEqual(dict(runner._scratch_processes(scratch)).get(holder.pid), holder_start,
                         "the scratch report's start time is not field 22")
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        self.assertEqual([item["start"] for item in runner._teardown_record(teardown)["delivered"]],
                         [independent], "the published delivery's start time is not field 22")

    @unittest.skipUnless(runner.PROC_ROOT.is_dir(), "the field 22 readings need /proc")
    def test_a_command_name_containing_a_paren_and_a_space_does_not_shift_the_parsed_field_22(self):
        """A `comm` containing `) ` or `(` must leave every parsed reading on field 22.

        The file is parsed by cutting after the *last* `) `; a command name that itself contains
        that sequence is the input a first-occurrence cut would corrupt, so every reading must
        still equal this test's own parse of the same file: a parser that stopped at the first
        `) ` would carry field 21 (the unused `itrealvalue`, always 0) as the start time instead.
        """
        scratch = ARTIFACTS / "start-time-parens-scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        for name in ("a) b", "a(b"):
            with self.subTest(command_name=name):
                child = self.spawn_via(self.interpreter_named(name), cwd=scratch)
                raw = (runner.PROC_ROOT / str(child.pid) / "stat").read_bytes()
                self.assertEqual(raw[raw.index(b"(") + 1:raw.rindex(b")")], name.encode(),
                                 "the fixture no longer runs under the name it stands for")
                independent = proc_start_time(child.pid)
                self.assertIsNotNone(independent, "the test could not read the fixture's field 22")
                self.assertEqual(runner._start_time(child.pid), independent,
                                 "the runner's own start-time read is not field 22")
                self.assertEqual(runner._spawned(child).start, independent,
                                 "the spawn record is not field 22")
                self.assertEqual(dict(runner._group_members(child.pid)).get(child.pid), independent,
                                 "the group report's start time is not field 22")
                self.assertEqual(dict(runner._scratch_processes(scratch)).get(child.pid),
                                 independent, "the scratch report's start time is not field 22")

    @unittest.skipUnless(can_deliver_signals(), "the record's identity needs one real delivery")
    def test_a_command_name_containing_a_paren_and_a_space_does_not_shift_the_published_field_22(
            self):
        """The record's published start time must be this test's own parse of the file.

        The child runs under a name containing `) `: the record is driven through a real delivery,
        and the value it publishes is compared against this test's independent parse of the same
        `/proc/<pid>/stat` — a parser that cut at the first `) ` would publish field 21's value.
        """
        child = self.spawn_via(self.interpreter_named("a) b"))
        independent = proc_start_time(child.pid)
        self.assertIsNotNone(independent, "the test could not read the fixture's own start time")
        spawned = runner._spawned(child)
        with self.log_path.open("ab") as log:
            teardown = runner._stop_spawned(spawned, log)
        self.assertEqual([item["start"] for item in runner._teardown_record(teardown)["delivered"]],
                         [independent], "the published delivery's start time is not field 22")


class EscalationMachineTests(PatchingTestCase):
    """One pinned row per ending the decision-point walk below lists, over the machine itself.

    Each row drives the real `_stop_spawned`/`_attempt_delivery` with the kernel boundary stubbed (a
    real pidfd and a real signal would end the fixture before the next round) and states what the
    machine must do: the attempts it commits, the lines its log gains, the signals its send really
    made, and every derived view of the record it publishes.  The rows are derived from the code,
    decision point by decision point: each round resolves its signal name, reads the ownership
    gates, resolves the platform constant, pins identity at delivery, observes an already-terminated
    target, sends through the pidfd and commits the attempt; the escalation ends at the first round
    that stopped the target, refused, or found it already terminated; and `ESCALATION_NAMES` bounds
    the rounds.  That walk is where every row below comes from — the ownership gate (either round:
    it is re-read live, so it can also refuse a round that follows a delivery), an undefined signal
    name and a refused pin (either round), the missing start time only a first round can see, a
    send the kernel refused (target gone, and any other `OSError`, apart), and the non-refusal
    endings (delivered-and-stopped, found-already-terminated before or after a delivery, survived
    the final signal) — one row each.  The table is the walk's output as it stands, not a claim
    about the machine: a shape the table does not list is a gap to be added as a row, not something
    the table denies.  Some rows are pinned a second time over a whole harness (`main`, real
    processes, real signals): the
    ownership-gate refusal by
    `EndToEndTests.test_a_refused_delivery_claims_no_sigkill_and_records_no_survivor`, the
    already-terminated first round by
    `EndToEndTests.test_a_signal_killed_suite_reports_the_group_it_did_not_touch`, the
    delivered-and-stopped ending by
    `EndToEndTests.test_timeout_stops_the_process_it_spawned_and_reports_the_group` and
    `EndToEndTests.test_escalation_stops_the_spawned_process_and_the_member_is_only_reported`, the
    delivered-then-undefined-final-signal row by
    `EndToEndTests.test_a_host_without_the_final_signal_records_the_refusal_it_cannot_send`, and the
    delivered-then-pin-refused row by
    `EndToEndTests.test_a_refusal_after_a_delivery_does_not_erase_it`; the
    delivered-then-already-terminated row is pinned beside `_stop_spawned` itself (not through
    `main`) by
    `TeardownOwnershipTests.test_an_already_terminated_target_resolves_the_delivery_that_stopped_it`.
    """

    TERM, FINAL = runner.ESCALATION_NAMES

    # (name, boundary stubs, what the record must say).  Stubs: `limit` (the ownership gate's
    # answer for every round), `limits` (per round: the gate's answer — None or the reason it
    # refused), `start=False` (no start time recorded at spawn), `pins` (per round: "ok" or the
    # reason the pin refused), `states` (per read: "alive" or "zombie"), `sends` (per round: "ok",
    # "gone" or "emfile"), `stops` (per delivered round: whether the grace observed the exit),
    # `drop_constant` (a signal name removed from the platform for the row).
    PATHS = (
        ("refused-first-round-ownership-limit",
         {"limit": "this platform cannot open a pidfd"},
         {"attempts": (("refused", TERM),), "lines": (), "clauses": False, "survivors": False,
          "refused": ("was not sent SIGTERM: this platform cannot open a pidfd",),
          "verified": False, "describe": ("unverified",)}),
        ("refused-first-round-the-first-signal-is-not-defined",
         {"drop_constant": TERM},
         {"attempts": (("refused", TERM),), "lines": (), "clauses": False, "survivors": False,
          "refused": ("this platform defines no SIGTERM",),
          "verified": False, "describe": ("unverified",)}),
        ("refused-first-round-no-start-time",
         {"start": False},
         {"attempts": (("refused", TERM),), "lines": (), "clauses": False, "survivors": False,
          "refused": ("has no start time recorded at spawn",),
          "verified": False, "describe": ("unverified",)}),
        ("refused-first-round-unpinnable-identity",
         {"pins": ("pid 4242 was gone before a pidfd for it could be opened",)},
         {"attempts": (("refused", TERM),), "lines": (), "clauses": False, "survivors": False,
          "refused": ("was not sent SIGTERM (pid 4242 was gone before a pidfd",),
          "verified": False, "describe": ("unverified",)}),
        ("already-terminated-first-round",
         {"states": ("zombie",)},
         {"attempts": (), "lines": (), "clauses": False, "survivors": False, "refused": (),
          "verified": True, "describe": ("no processes remained to be terminated",)}),
        ("refused-first-round-target-gone-before-the-send",
         {"sends": ("gone",)},
         {"attempts": (("refused", TERM),), "lines": (), "clauses": False, "survivors": False,
          "refused": ("was gone before the SIGTERM could be delivered through its pidfd",),
          "verified": False, "describe": ("unverified",)}),
        ("refused-first-round-send-errored",
         {"sends": ("emfile",)},
         {"attempts": (("refused", TERM),), "lines": (), "clauses": False, "survivors": False,
          "refused": ("could not be delivered through the pidfd of",),
          "verified": False, "describe": ("unverified",)}),
        ("delivered-and-stopped",
         {"stops": (True,)},
         {"attempts": (("delivered", TERM, True),), "lines": (TERM,), "clauses": True,
          "survivors": False, "refused": (), "verified": True,
          "describe": ("the spawned process terminated",)}),
        ("delivered-then-the-final-signal-stopped-it",
         {"stops": (False, True)},
         {"attempts": (("delivered", TERM, False), ("delivered", FINAL, True)),
          "lines": (TERM, FINAL), "clauses": True, "survivors": False, "refused": (),
          "verified": True, "describe": ("the spawned process terminated",)}),
        ("delivered-then-the-final-signal-did-not-stop-it",
         {"stops": (False, False)},
         {"attempts": (("delivered", TERM, False), ("delivered", FINAL, False)),
          "lines": (TERM, FINAL), "clauses": False, "survivors": True, "refused": (),
          "verified": False, "describe": ("survived SIGKILL",)}),
        ("delivered-then-the-final-signal-is-not-defined",
         {"stops": (False,), "drop_constant": FINAL},
         {"attempts": (("delivered", TERM, False), ("refused", FINAL)), "lines": (TERM,),
          "clauses": False, "survivors": False,
          "refused": ("this platform defines no SIGKILL",), "verified": False,
          "describe": ("unverified",)}),
        ("delivered-then-the-ownership-gate-refuses-the-second-round",
         {"stops": (False,),
          "limits": (None, "this run has no child-reaping SIGCHLD disposition of its own, so no "
                          "process can be proven this run's")},
         {"attempts": (("delivered", TERM, False), ("refused", FINAL)), "lines": (TERM,),
          "clauses": False, "survivors": False,
          "refused": ("was not sent SIGKILL: this run has no child-reaping SIGCHLD disposition",),
          "verified": False, "describe": ("unverified",)}),
        ("delivered-then-already-terminated",
         {"stops": (False,), "states": ("alive", "zombie")},
         {"attempts": (("delivered", TERM, True),), "lines": (TERM,), "clauses": True,
          "survivors": False, "refused": (), "verified": True,
          "describe": ("the spawned process terminated",)}),
        ("delivered-then-the-final-signal-could-not-be-pinned",
         {"stops": (False,),
          "pins": ("ok", "a pidfd for pid 4242 could not be opened (Too many open files)")},
         {"attempts": (("delivered", TERM, False), ("refused", FINAL)), "lines": (TERM,),
          "clauses": False, "survivors": False,
          "refused": ("was not sent SIGKILL (a pidfd for pid 4242 could not be opened",),
          "verified": False, "describe": ("unverified",)}),
        ("delivered-then-target-gone-before-the-final-send",
         {"stops": (False,), "sends": ("ok", "gone")},
         {"attempts": (("delivered", TERM, False), ("refused", FINAL)), "lines": (TERM,),
          "clauses": False, "survivors": False,
          "refused": ("was gone before the SIGKILL could be delivered",), "verified": False,
          "describe": ("unverified",)}),
        ("delivered-then-the-final-send-errored",
         {"stops": (False,), "sends": ("ok", "emfile")},
         {"attempts": (("delivered", TERM, False), ("refused", FINAL)), "lines": (TERM,),
          "clauses": False, "survivors": False,
          "refused": ("could not be delivered through the pidfd of",), "verified": False,
          "describe": ("unverified",)}),
    )

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)
        self.process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                        start_new_session=True)
        self.addCleanup(self.process.wait)
        self.addCleanup(self.process.kill)
        self.spawned = runner._spawned(self.process)

    def run_path(self, stubs: dict) -> tuple[runner.Teardown, list[tuple[str, int, int]], list[str]]:
        """Drive `_stop_spawned` once with the boundary stubbed as the row states."""
        log_path = ARTIFACTS / f"machine-{time.monotonic_ns()}.log"
        sends: list[str] = []
        plans = {key: list(stubs.get(key, ()))
                 for key in ("pins", "states", "sends", "stops", "limits")}

        def step(key: str, default):
            return plans[key].pop(0) if plans[key] else default

        def pin(pid: int, expected: str):
            answer = step("pins", "ok")
            return ((runner.Pin(fd=-1, start=expected), None) if answer == "ok"
                    else (None, answer))

        def state(pid: int) -> str | None:
            return {"alive": "S", "zombie": "Z"}[step("states", "alive")]

        def send(fd: int, signum: int) -> None:
            answer = step("sends", "ok")
            if answer == "gone":
                raise ProcessLookupError(errno.ESRCH, "No such process")
            if answer == "emfile":
                raise OSError(errno.EMFILE, "Too many open files")
            sends.append(signal.Signals(signum).name)

        def stopped(spawned, seconds: float) -> bool:
            return bool(step("stops", False))

        def limit() -> str | None:
            # The gate is re-read live every round (`_attempt_delivery`), so a row can change its
            # answer between rounds; `limit` alone answers every round the same way.
            return step("limits", stubs.get("limit"))

        self.patch(runner, "_ownership_limit", limit)
        self.patch(runner, "_group_members", lambda group: [])  # nothing left behind: no limits
        self.patch(runner, "_pin_identity", pin)
        self.patch(runner, "_proc_state", state)
        self.patch(runner, "_command_stopped", stopped)
        self.patch(signal, "pidfd_send_signal", send)
        spawned = self.spawned
        if not stubs.get("start", True):
            spawned = runner.Spawned(process=self.process, start=None)
        # A row that removes a platform constant puts it back before the next row runs: the machine
        # reads `getattr(signal, name)` live, so a leaked removal would decide later rows.
        dropped = stubs.get("drop_constant")
        saved_constant = getattr(signal, dropped, None) if dropped else None
        if dropped:
            delattr(signal, dropped)
        try:
            with log_path.open("ab") as log:
                teardown = runner._stop_spawned(spawned, log)
        finally:
            if dropped:
                setattr(signal, dropped, saved_constant)
        return teardown, parse_delivery_lines(log_path.read_text(encoding="utf-8")), sends

    @unittest.skipUnless(can_deliver_signals(),
                         "the machine's delivery path needs a pinnable identity")
    def test_every_reachable_escalation_path_is_recorded_as_its_attempts(self):
        """Each listed row: the attempts, the lines, the sends and the record must all agree."""
        for name, stubs, expected in self.PATHS:
            with self.subTest(path=name):
                teardown, logged, sends = self.run_path(stubs)
                pid = self.process.pid
                attempts = tuple(
                    ("delivered", attempt.signal, attempt.stopped)
                    if isinstance(attempt, runner.Delivery) else ("refused", attempt.signal)
                    for attempt in teardown.attempts)
                self.assertEqual(attempts, expected["attempts"], name)
                self.assertEqual([(signal_name, target) for signal_name, target, _start in logged],
                                 [(signal_name, pid) for signal_name in expected["lines"]], name)
                self.assertEqual(sends, list(expected["lines"]),
                                 "a delivery is exactly a signal the kernel accepted")
                self.assertEqual(teardown.clauses,
                                 ("the spawned process",) if expected["clauses"] else (), name)
                self.assertEqual(teardown.survivors, (pid,) if expected["survivors"] else (), name)
                self.assertEqual(teardown.verified, expected["verified"], name)
                refused = teardown.refused
                self.assertEqual(len(refused), len(expected["refused"]), refused)
                for fragment in expected["refused"]:
                    self.assertIn(fragment, " ".join(refused), name)
                for fragment in expected["describe"]:
                    self.assertIn(fragment, teardown.describe(), name)
                record = runner._teardown_record(teardown)
                self.assertEqual(record["delivered"],
                                 [{"pid": attempt.pid, "start": attempt.start,
                                   "signal": attempt.signal, "stopped": attempt.stopped}
                                  for attempt in teardown.delivered], name)
                self.assertEqual(record["clauses"], list(teardown.clauses), name)
                self.assertEqual(record["survivors"], list(teardown.survivors), name)
                self.assertEqual(record["unverified"], list(teardown.unverified), name)
                self.assertEqual(record["refused"], list(refused), name)
                self.assertEqual(record["verified"], teardown.verified, name)


class EndToEndTests(PatchingTestCase):
    """One synthetic repository, run through main(): states, isolation, teardown."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)
        self.report = ARTIFACTS / "report.json"
        # Short and outside the checkout, like the operator default -- the runner refuses
        # scratch roots that cannot hold a socket.
        self.scratch = runner.scratch_root_for()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        # `main` takes the run's startup step in-process: both the module state it sets and the
        # signal disposition it establishes are restored, so no other test inherits either.
        self.patch(runner, "EXIT_DISPOSITION", runner.EXIT_DISPOSITION)
        if hasattr(signal, "SIGCHLD"):
            saved = signal.getsignal(signal.SIGCHLD)
            self.addCleanup(signal.signal, signal.SIGCHLD, saved)

    def build(self) -> Path:
        root = synthetic_tree(
            patterns=["scripts/test_*.py", "scripts/tests/test*.py", "scripts/tests/test*.sh"],
            prune=["node_modules", "fixtures"],
            floor=["scripts/test_pass.py", "scripts/tests/test-shell.sh"],
            suites="\n".join([
                "[[suite]]",
                'id = "canned:missing-runtime"',
                'command = [["definitely-not-a-real-runtime-xyz", "run"]]',
                "",
                "[[suite]]",
                'id = "canned:empty-counter"',
                'command = [["{python}", "-c", "print(\'x: 0/0 ok\')"]]',
                'assertion = "counter"',
                'count_regexes = ["^x: (?P<passed>\\\\d+)/(?P<total>\\\\d+) ok$"]',
                "",
                "[[suite]]",
                'path = "scripts/tests/test-counter-child.py"',
                'covered_by = "parent"',
                'assertion = "counter"',
                'count_regexes = ["^child-counter: (?P<passed>\\\\d+)/(?P<total>\\\\d+) ok$"]',
                "",
                "[[suite]]",
                'id = "parent"',
                'path = "scripts/tests/parent.py"',
                'command = [["{python}", "scripts/tests/parent.py"]]',
                'assertion = "counter"',
                'count_regexes = ["^parent-counter: (?P<passed>\\\\d+)/(?P<total>\\\\d+) ok$"]',
                "",
                "[[suite]]",
                'path = "scripts/test_env.py"',
                # PYTHONCOERCECLOCALE=0 so the dump is exactly what the runner sets: under a C
                # locale the interpreter itself would add LC_CTYPE to its own environment
                # (PEP 538), which is a property of CPython, not of the suite's isolation.
                f'env = {{ DUMP_FILE = "{ARTIFACTS / "env-dump.json"}", '
                f'PYTHONCOERCECLOCALE = "0" }}',
                "",
                "[[suite]]",
                'path = "scripts/test_hang.py"',
                f'env = {{ PID_FILE = "{ARTIFACTS / "pids.txt"}" }}',
                "",
            ]),
        )
        write_suite(root, "scripts/test_pass.py", PASS_SUITE)
        write_suite(root, "scripts/test_fail.py", FAIL_SUITE)
        write_suite(root, "scripts/test_zero.py", ZERO_TEST_SUITE)
        write_suite(root, "scripts/test_skipped.py", SKIP_SUITE)
        write_suite(root, "scripts/test_syntax.py", "def broken(:\n    pass\n")
        write_suite(root, "scripts/test_env.py", ENV_SUITE)
        write_suite(root, "scripts/test_hang.py", HANG_SUITE)
        write_suite(root, "scripts/tests/test-shell.sh", "#!/usr/bin/env bash\nexit 0\n")
        write_suite(root, "scripts/tests/test-counter-child.py", "print('never scheduled on its own')\n")
        write_suite(root, "scripts/tests/parent.py",
                    "# executes scripts/tests/test-counter-child.py in production\n"
                    "print('parent-counter: 2/2 ok')\n"
                    "print('child-counter: 3/3 ok')\n")
        return root

    def run_main(self, root: Path, *extra: str) -> tuple[int, str, dict]:
        return run_synthetic(root, self.scratch, self.report, *extra)

    def run_main_leaving_strays(self, root: Path, *extra: str) -> tuple[int, str, dict]:
        """`run_main` for a model whose refusal leaves the spawned process running on purpose.

        Nothing can be signalled under the model, so the suite's own process is still alive when the
        run ends and the runner's `Popen` object for it is collected while it runs — CPython's
        ResourceWarning about exactly that is the model working, not a leak to report.  The
        collection is forced here so it happens under this filter rather than whenever a later
        cyclic pass gets to it.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            result = self.run_main(root, *extra)
            gc.collect()
        return result

    def states(self, payload: dict) -> dict:
        return states_of(payload)

    def test_every_suite_settles_and_the_run_goes_red_for_the_broken_ones(self):
        root = self.build()
        code, output, payload = self.run_main(root)
        states = self.states(payload)
        self.assertEqual(states["scripts/test_pass.py"]["state"], "PASS")
        self.assertEqual(states["scripts/tests/test-shell.sh"]["state"], "PASS")
        self.assertEqual(states["scripts/test_fail.py"]["state"], "FAIL")
        self.assertEqual(states["scripts/test_syntax.py"]["state"], "FAIL")
        self.assertEqual(states["scripts/test_zero.py"]["state"], "ERROR")
        self.assertIn("Ran 0 tests", states["scripts/test_zero.py"]["reason"])
        self.assertEqual(states["scripts/test_skipped.py"]["state"], "ERROR")
        self.assertIn("all skipped", states["scripts/test_skipped.py"]["reason"])
        self.assertEqual(states["canned:missing-runtime"]["state"], "ERROR")
        self.assertEqual(states["canned:empty-counter"]["state"], "ERROR")
        self.assertEqual(states["scripts/test_hang.py"]["state"], "TIMEOUT")
        self.assertEqual(code, 1)
        self.assertIn("failed:", output)

    def test_covered_child_settles_from_the_parent_output(self):
        root = self.build()
        code, _, payload = self.run_main(root, "--suite", "parent")
        states = self.states(payload)
        self.assertEqual(len(payload["suites"]), 2)
        self.assertEqual(states["parent"]["state"], "PASS")
        child = states["scripts/tests/test-counter-child.py"]
        self.assertEqual(child["state"], "PASS")
        self.assertEqual(child["counts"], {"passed": 3, "executed": 3, "total": 3})
        # Unpinned, and selected through its parent: still named in the record's discovery
        # section, and the run is green (owner decision, 2026-11-14).
        self.assertIn("scripts/tests/test-counter-child.py", payload["discovery"]["unpinned"])
        self.assertEqual(code, 0)

    def test_covered_child_without_parent_evidence_is_error(self):
        root = self.build()
        (root / "scripts/tests/parent.py").write_text(
            "# executes scripts/tests/test-counter-child.py in production\n"
            "print('parent-counter: 2/2 ok')\n", encoding="utf-8")
        code, _, payload = self.run_main(root, "--suite", "parent")
        child = self.states(payload)["scripts/tests/test-counter-child.py"]
        self.assertEqual(child["state"], "ERROR")
        self.assertIn("no evidence", child["reason"])
        self.assertEqual(code, 1)

    def test_covered_child_with_zero_checks_is_error(self):
        root = self.build()
        (root / "scripts/tests/parent.py").write_text(
            "# executes scripts/tests/test-counter-child.py in production\n"
            "print('parent-counter: 2/2 ok')\n"
            "print('child-counter: 0/0 ok')\n", encoding="utf-8")
        code, _, payload = self.run_main(root, "--suite", "parent")
        child = self.states(payload)["scripts/tests/test-counter-child.py"]
        self.assertEqual(child["state"], "ERROR")
        self.assertIn("zero executed checks", child["reason"])
        self.assertEqual(code, 1)

    def test_an_untrustworthy_plan_exits_two_and_says_so(self):
        """An empty discovery set or an unmet floor is a red job, not a printed note."""
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[],
                              floor=["scripts/test_gone.py"], suites="")
        code, output, payload = self.run_main(root)
        self.assertEqual(code, 2, output)
        self.assertEqual(payload["exit_code"], 2)
        problems = " ".join(payload["problems"])
        self.assertIn("produced no suites", problems)
        self.assertIn("floor unmet", problems)

    def test_a_condition_skipped_suite_is_recorded_not_dropped(self):
        """A whole-suite SKIP stays in the run record, with its declared reason."""
        root = synthetic_tree(
            patterns=["scripts/test_*.py"], prune=[], floor=[],
            suites="\n".join([
                "[[suite]]",
                'id = "gate:pr-only"',
                'command = [["{python}", "-c", "pass"]]',
                'condition = "pull_request"',
                'skip_reason = "pull-request guard: a push to main has nothing to do"',
                "",
            ]),
        )
        code, output, payload = self.run_main(root)
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["planned"], {"scheduled": 0, "covered": 0,
                                              "condition_skipped": 1})
        self.assertEqual(payload["settled"], 1)
        self.assertEqual((payload["summary"]["PASS"], payload["summary"]["SKIP"]), (0, 1))
        skipped = self.states(payload)["gate:pr-only"]
        self.assertEqual(skipped["state"], "SKIP")
        self.assertEqual(skipped["reason"],
                         "pull-request guard: a push to main has nothing to do")
        code, output, payload = self.run_main(root, "--event", "pull_request")
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["planned"]["condition_skipped"], 0)
        self.assertEqual(payload["summary"]["PASS"], 1)

    def test_suites_run_with_task_local_scratch_and_a_stripped_environment(self):
        root = self.build()
        os.environ["GDD_LAUNCHER"] = "must-not-leak"
        os.environ["OMP_RUN_ROOT"] = "must-not-leak"
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.addCleanup(os.environ.pop, "GDD_LAUNCHER", None)
        self.addCleanup(os.environ.pop, "OMP_RUN_ROOT", None)
        # Controlled, not this host's own setting: the shim pins belong to the exact set
        # asserted below, so they must not depend on what the operator happens to have.
        for name in ("MISE_STATE_DIR", "MISE_DATA_DIR"):
            directory = ARTIFACTS / f"operator-{name.lower()}"
            directory.mkdir(parents=True, exist_ok=True)
            self.addCleanup(os.environ.pop, name, None)
            os.environ[name] = str(directory)
        self.run_main(root, "--suite", "scripts/test_env.py")
        dump = json.loads((ARTIFACTS / "env-dump.json").read_text(encoding="utf-8"))
        scratch = str(self.scratch)
        # The exact set of names, not a subset: the synthetic manifest declares no `[env]`
        # allowlist, so only PATH may come from the operator, and a suite sees the runner's
        # task-local block, the two shim state pins and its own `env` table.  Frozen on
        # purpose: deriving it from the runner would follow the code it exists to police.
        self.assertEqual(set(dump), {
            "PATH", "NO_COLOR", "DUMP_FILE", "PYTHONCOERCECLOCALE",
            "HOME", "TMPDIR", "TMP", "TEMP",
            "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
            "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "GIT_TERMINAL_PROMPT",
            "MISE_STATE_DIR", "MISE_DATA_DIR",
        })
        for name in ("HOME", "TMPDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
                     "XDG_STATE_HOME"):
            self.assertTrue(dump[name].startswith(scratch), f"{name}={dump[name]}")
        self.assertEqual(dump["PYTHONPATH"], str(root))
        self.assertEqual(dump["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertNotIn("GDD_LAUNCHER", dump)
        self.assertNotIn("OMP_RUN_ROOT", dump)
        self.assertEqual(Path(dump["PATH"].split(os.pathsep)[0]),
                         Path(sys.executable).absolute().parent)

    def test_default_scratch_lives_outside_the_checkout(self):
        scratch = runner.scratch_root_for()
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.assertTrue(scratch.is_dir())
        self.assertFalse(scratch.is_relative_to(ROOT), scratch)
        if runner.SHORT_TEMP_ROOT.is_dir():
            self.assertTrue(scratch.is_relative_to(runner.SHORT_TEMP_ROOT), scratch)

    @unittest.skipUnless(runner.SHORT_TEMP_ROOT.is_dir(), "no short temp root on this platform")
    def test_default_scratch_stays_socket_sized_under_a_long_operator_tmpdir(self):
        """A long inherited TMPDIR must not reach the scratch tree (§4 item 4)."""
        long_tmpdir = ARTIFACTS / ("operator-tmpdir-" + "x" * 80)
        long_tmpdir.mkdir(parents=True, exist_ok=True)
        saved = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = str(long_tmpdir)
        try:
            scratch = runner.scratch_root_for()
        finally:
            if saved is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = saved
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.assertFalse(scratch.is_relative_to(long_tmpdir),
                         f"scratch inherited TMPDIR: {scratch}")
        suite_scratch = Path(tempfile.mkdtemp(prefix="skills-gdd-s-", dir=scratch))
        self.addCleanup(shutil.rmtree, suite_scratch, ignore_errors=True)
        plan = runner.build_plan(ROOT, runner.load_manifest(ROOT / runner.MANIFEST_RELATIVE),
                                 event="local")
        self.assertTrue(plan.socket_tail, "no suite declares the socket tree this bound models")
        worst_case = runner.socket_path_length(suite_scratch, plan.socket_tail)
        self.assertIsNotNone(worst_case)
        self.assertLess(worst_case, runner.AF_UNIX_PATH_LIMIT,
                        f"worst-case socket path {worst_case} bytes for {suite_scratch}")

    @unittest.skipIf(os.name != "posix", "AF_UNIX path limits do not apply")
    def test_a_scratch_root_too_long_for_a_socket_errors_before_running(self):
        """The bound is enforced, not assumed: no suite runs under an unusable root."""
        marker = ARTIFACTS / "should-not-exist.txt"
        marker.unlink(missing_ok=True)
        deep = ARTIFACTS / ("deep-" + "d" * 80) / "deeper"
        deep.mkdir(parents=True, exist_ok=True)
        suite = runner.Suite(
            id="scripts/test_marker.py", origin="declared", cwd=ROOT, runtime="python",
            commands=(("{python}", "-c", f"open({str(marker)!r}, 'w').close()"),),
        )
        log_root = ARTIFACTS / "logs"
        log_root.mkdir(parents=True, exist_ok=True)
        outcome = runner.run_suite(suite, root=ROOT, scratch_root=deep, log_root=log_root,
                                   environment=runner.base_environment({}, sys.executable))
        self.assertEqual(outcome.state, "ERROR")
        self.assertIn("AF_UNIX", outcome.reason)
        reported = re.search(r"worst case (\d+) bytes", outcome.reason)
        self.assertIsNotNone(reported, outcome.reason)
        self.assertGreaterEqual(int(reported.group(1)), runner.AF_UNIX_PATH_LIMIT)
        self.assertFalse(marker.exists(), "the suite ran despite an unusable scratch root")
        self.assertEqual([entry.name for entry in deep.iterdir()], [],
                         "the unusable per-suite scratch tree was not cleaned up")

    @unittest.skipUnless(runner.SHORT_TEMP_ROOT.is_dir(), "no short temp root on this platform")
    @unittest.skipIf(os.name != "posix", "AF_UNIX path limits do not apply")
    def test_a_declared_socket_tail_turns_a_usable_root_into_an_error(self):
        """The bound uses the manifest's declared tail, not just the scratch root length."""
        marker = ARTIFACTS / "tail-marker.txt"
        marker.unlink(missing_ok=True)
        plan = runner.build_plan(ROOT, runner.load_manifest(ROOT / runner.MANIFEST_RELATIVE),
                                 event="local")
        self.assertTrue(plan.socket_tail, "no suite declares the socket tree this bound models")
        padded = Path(tempfile.mkdtemp(prefix="hoa-tail-", dir=runner.SHORT_TEMP_ROOT)) / ("p" * 40)
        self.addCleanup(shutil.rmtree, padded.parent, ignore_errors=True)
        padded.mkdir()
        probe = Path(tempfile.mkdtemp(prefix="scripts-test-", dir=padded))
        probe_plain = runner.socket_path_length(probe, "")
        probe_tailed = runner.socket_path_length(probe, plan.socket_tail)
        shutil.rmtree(probe, ignore_errors=True)
        self.assertLess(probe_plain, runner.AF_UNIX_PATH_LIMIT,
                        "the probe root is already too long to control this bound")
        self.assertGreaterEqual(probe_tailed, runner.AF_UNIX_PATH_LIMIT,
                                "the declared tail is too short to model the bound")
        suite = runner.Suite(
            id="scripts/test_marker.py", origin="declared", cwd=ROOT, runtime="python",
            commands=((sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"),),
        )
        log_root = ARTIFACTS / "logs"
        log_root.mkdir(parents=True, exist_ok=True)
        environment = runner.base_environment({}, sys.executable)
        usable = runner.run_suite(suite, root=ROOT, scratch_root=padded, log_root=log_root,
                                  environment=environment)
        self.assertEqual(usable.state, "PASS", usable.reason)
        self.assertTrue(marker.exists(), "the suite did not run under the usable root")
        marker.unlink()
        bounded = runner.run_suite(suite, root=ROOT, scratch_root=padded, log_root=log_root,
                                   environment=environment, socket_tail=plan.socket_tail)
        self.assertEqual(bounded.state, "ERROR")
        self.assertIn("AF_UNIX", bounded.reason)
        self.assertFalse(marker.exists(), "the suite ran although its declared tail cannot fit")
        self.assertEqual([entry.name for entry in padded.iterdir()], [],
                         "the bounded-out per-suite scratch tree was not cleaned up")

    @unittest.skipUnless(can_deliver_signals(),
                         "successful delivery needs pidfds, /proc evidence and waitid(WNOWAIT)")
    def test_timeout_stops_the_process_it_spawned_and_reports_the_group(self):
        """The timeout terminates the spawned suite and reports — never touches — what it left.

        The suite starts a same-group child and hangs.  The runner must stop the process it spawned
        (its own recorded identity, pinned at delivery) while that child — a process the runner did
        not spawn, and so has no authority over — is left running, named in the record, and marked
        as a limit; the run's own exit is the timeout's, not the child's death.
        """
        root = self.build()
        code, _, payload = self.run_main(root, "--suite", "scripts/test_hang.py")
        self.assertEqual(code, 1)
        entry = self.states(payload)["scripts/test_hang.py"]
        self.assertEqual(entry["state"], "TIMEOUT")
        pids = self.leftover_pids(ARTIFACTS / "pids.txt")
        self.assertEqual(len(pids), 2)
        spawned_pid, child_pid = pids
        self.assert_stopped([spawned_pid], "the process the timeout was recorded for")
        self.assertTrue(process_running(child_pid),
                        "the same-group child was stopped: the run must signal only what it spawned")
        self.assertIn(str(child_pid), entry["reason"],
                      "the child that was left alone is not named in the record")
        self.assertIn("left alone", entry["reason"])
        self.assertFalse(entry["teardown"]["verified"], entry["teardown"])
        self.assertEqual(entry["teardown"]["clauses"], ["the spawned process"])
        self.assertEqual(entry["teardown"]["survivors"], [],
                         "a child that was never signalled is not a survivor")

    def assert_no_delivery_to(self, entry: dict, pid: int) -> None:
        """The log's delivery lines and the record's deliveries are one ordered bijection.

        Unconditional, on purpose: an executed suite always publishes its teardown record, so the
        record's `delivered` is read strictly here (a renamed field fails loudly, never as "no
        deliveries"), every line carrying the runner's `DELIVERY_MARKER` is parsed through the
        runner's own anchored pattern, and the two sequences must be equal — an empty log against a
        delivery in the record fails, a line with no delivery in the record fails, and a delivery
        line naming a pid this run did not spawn fails whether or not the record claims it too.
        There is no capability branch and no refusal branch for a defect to steer around: a host
        that cannot deliver writes no line and records no delivery, and the same equality holds
        there.  The fixtures that call this helper run a single command vector, so a second target
        pid in one log would itself be the run signalling something it did not spawn.
        """
        teardown = entry["teardown"]
        self.assertIsNotNone(teardown, "an executed suite always publishes its teardown record")
        delivered = teardown["delivered"]
        claimed = [(item["signal"], item["pid"], int(item["start"])) for item in delivered]
        log_text = Path(entry["log"]).read_text(encoding="utf-8")
        self.assertEqual(parse_delivery_lines(log_text), claimed,
                         "the log's delivery lines and the record's deliveries disagree")
        targets = [int(raw) for raw in runner.DELIVERY_TARGET_RE.findall(log_text)]
        self.assertEqual(targets, [item["pid"] for item in delivered],
                         "the log names delivery targets the record does not carry")
        self.assertLessEqual(len(set(targets)), 1,
                             f"the log names deliveries to more than one target pid: {targets}")
        self.assertNotIn(pid, targets,
                         f"the run claims a delivery to a process it did not spawn: {targets}")

    def leftover_pids(self, pids_file: Path) -> list[int]:
        """The pids a fixture recorded, killed when the test ends.

        The run leaves every process it did not spawn alone, so a fixture that deliberately leaves
        one running stays running until the test owns stopping it.
        """
        pids = [int(value) for value in pids_file.read_text().split()]
        for pid in pids:
            self.addCleanup(kill_quietly, pid)
        return pids

    def leftover_pids_with(self, pids_file: Path, signum: int) -> list[int]:
        """`leftover_pids`, stopping each pid with a signal constant captured by the caller.

        For the one model that removes a signal constant from the platform (`signal.SIGKILL`):
        cleanups run before the attribute is restored, so resolving the constant there would raise
        instead of stopping the fixture the model deliberately leaves running.
        """
        pids = [int(value) for value in pids_file.read_text().split()]
        for pid in pids:
            self.addCleanup(kill_quietly, pid, signum)
        return pids

    def assert_stopped(self, pids: list[int], message: str) -> None:
        """Every pid stops running inside the grace window, or the failure names the survivor."""
        deadline = time.monotonic() + 10
        for pid in pids:
            while time.monotonic() < deadline:
                if not process_running(pid):
                    break
                time.sleep(0.1)
            else:
                for leftover in pids:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(leftover, signal.SIGKILL)
                self.fail(f"{message}: pid {pid} is still running")

    def run_abnormal_fixture(self, name: str, source: str, *, env: dict[str, str],
                             timeout: str = "5") -> tuple[dict, list[int]]:
        """Run one synthetic single-suite fixture whose suite exited without its own cleanup.

        `source` runs as `scripts/test_<name>.py` and records the pids it started in
        `<ARTIFACTS>/<name>-pids.txt` (the runner supplies its `PID_FILE`).  Whatever that abnormal
        exit is, the run owes the same observable outcome: the suite settles red, the scratch tree
        is deleted, and every recorded pid the run did not spawn is left alone — the test owns
        stopping those, so each is registered for cleanup here.  Returns the suite's result entry
        and the recorded pids.
        """
        pids_file = ARTIFACTS / f"{name}-pids.txt"
        variables = {"PID_FILE": str(pids_file), **env}
        # A net registered before the run: these fixtures ignore SIGTERM (or leave workers that do),
        # so a run that dies before the pids below are registered must not leak what it started.
        self.addCleanup(stop_recorded_pids, pids_file, getattr(signal, "SIGKILL", signal.SIGTERM))
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  f'path = "scripts/test_{name}.py"',
                                  "env = { " + ", ".join(f'{key} = "{value}"'
                                                         for key, value in variables.items())
                                  + " }",
                                  "",
                              ]))
        write_suite(root, f"scripts/test_{name}.py", source)
        code, output, payload = self.run_main(root, "--timeout", timeout)
        self.assertEqual(code, 1, output)
        entry = self.states(payload)[f"scripts/test_{name}.py"]
        pids = self.leftover_pids(pids_file)
        self.assertEqual([item.name for item in self.scratch.iterdir()], [],
                         "the per-suite scratch tree was not cleaned up")
        return entry, pids

    @unittest.skipUnless(can_deliver_signals(),
                         "successful delivery needs pidfds, /proc evidence and waitid(WNOWAIT)")
    def test_escalation_stops_the_spawned_process_and_the_member_is_only_reported(self):
        """Escalation follows the spawned process alone, and the member it outlives is reported.

        The spawned process exits cleanly on SIGTERM while the child it leaves in the same group
        ignores it; that child holds nothing a scratch report could match (empty environment, cwd
        `/`), and it is exactly the process the runner must not touch.  The spawned process's exit
        code 0 says SIGTERM reached it; that the child is still running says the escalation did not
        reach out to the group, and the record names the child as found and left alone.
        """
        write_suite(ARTIFACTS, "stubborn-child.py", STUBBORN_CHILD)
        entry, pids = self.run_abnormal_fixture(
            "stubborn", STUBBORN_SUITE, timeout="3",
            env={"READY": str(ARTIFACTS / "stubborn-ready"),
                 "CHILD_FILE": str(ARTIFACTS / "stubborn-child.py")})
        self.assertEqual(entry["state"], "TIMEOUT")
        self.assertEqual(entry["exit_code"], 0, "the fixture leader did not exit on SIGTERM")
        self.assertEqual(len(pids), 2)
        leader_pid, child_pid = pids
        self.assert_stopped([leader_pid], "the spawned process")
        self.assertTrue(process_running(child_pid),
                        "the same-group child was stopped: only the spawned process may be")
        self.assertIn("the spawned process terminated", entry["reason"])
        self.assertFalse(entry["teardown"]["verified"], entry["teardown"])
        self.assertEqual(entry["teardown"]["clauses"], ["the spawned process"])
        self.assertIn(str(child_pid), " ".join(entry["teardown"]["unverified"]),
                      "the child that was left alone is not named in the teardown record")

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the loss is only visible to waitid(WNOWAIT)")
    def test_a_suite_whose_child_is_not_waitable_settles_error_instead_of_crashing(self):
        """A suite leader reaped by someone else is no more waitable than one the kernel took.

        The run establishes its own `SIGCHLD` disposition, so an *inherited* handler can no longer
        take a suite's exit; a reaper this run does not control still can — here a thread already
        blocked in `os.waitpid` on the suite's own pid, which takes its status the moment the suite
        ends (the exit-poll interval is widened so the runner's probe cannot catch that exit first
        and hide the loss).  The affected suite must settle ERROR with an unverified teardown, and
        the run must continue to settle the rest of the plan and publish its record instead of
        taking the whole discoverer down.
        """
        pids_file = ARTIFACTS / "reaped-pids.txt"
        pids_file.unlink(missing_ok=True)
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  'id = "canned:pass"',
                                  'command = [["{python}", "-c", "pass"]]',
                                  'assertion = "exit"',
                                  "",
                                  "[[suite]]",
                                  'path = "scripts/test_reaped.py"',
                                  f'env = {{ PID_FILE = "{pids_file}" }}',
                                  "",
                              ]))
        write_suite(root, "scripts/test_reaped.py", REAPED_SUITE)
        self.patch(runner, "EXIT_POLL_SECONDS", 3.0)
        reaped: list[int] = []

        def reap_outside_popen() -> None:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not pids_file.exists():
                time.sleep(0.01)
            reaped.append(os.waitpid(int(pids_file.read_text()), 0)[0])

        reaper = threading.Thread(target=reap_outside_popen, daemon=True)
        reaper.start()
        code, output, payload = self.run_main(root)
        reaper.join(5)
        states = self.states(payload)
        self.assertEqual(sorted(states), ["canned:pass", "scripts/test_reaped.py"])
        lost = states["scripts/test_reaped.py"]
        self.assertEqual(lost["state"], "ERROR", lost["reason"])
        self.assertIn("no longer waitable", lost["reason"])
        self.assertIn("unverified", lost["reason"])
        self.assertEqual(reaped, [int(pids_file.read_text())],
                         "the external reaper did not take the suite's status")
        self.assertEqual(states["canned:pass"]["state"], "PASS",
                         states["canned:pass"]["reason"])
        self.assertEqual(code, 1, output)

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the loss would only be visible to waitid(WNOWAIT)")
    def test_an_inherited_sigchld_ignore_is_normalized_before_anything_is_spawned(self):
        """An inherited `SIGCHLD=SIG_IGN` must not reap a suite's exit out from under the run.

        Under `SIG_IGN` the kernel reaps a child inside its own exit: the status, and with it the
        `waitid(WNOWAIT)` reservation every ownership proof reads, is gone the moment a suite ends,
        and even a clean exit settles as "no longer waitable" ERROR.  `main` puts the run's own
        disposition in `SIG_DFL` before the first spawn, so both suites below settle on their real
        exits instead.
        """
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  'id = "canned:pass"',
                                  'command = [["{python}", "-c", "pass"]]',
                                  'assertion = "exit"',
                                  "",
                              ]))
        write_suite(root, "scripts/test_pass.py", PASS_SUITE)
        saved = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        self.addCleanup(signal.signal, signal.SIGCHLD, saved)
        code, output, payload = self.run_main(root)
        states = self.states(payload)
        self.assertEqual(code, 0, output)
        for suite_id, entry in states.items():
            self.assertEqual(entry["state"], "PASS",
                             f"{suite_id}: {entry['state']} ({entry['reason']})")
        self.assertEqual(signal.getsignal(signal.SIGCHLD), signal.SIG_DFL,
                         "the run did not leave its own disposition in the state it established")

    @unittest.skipUnless(can_deliver_signals(),
                         "the report's evidence needs the enumeration gates")
    def test_a_command_that_exited_cleanly_is_checked_before_its_reap(self):
        """A clean exit can still leave same-group members; the group is read before the reap.

        Command one starts a worker whose environment is empty and whose cwd is `/` — nothing a
        scratch report can match — and exits 0; command two times out.  While command one's own
        instance is still unreaped the group is still its own, so the worker is found there and
        named; the run leaves it running (it signals only what it spawned), the suite's record
        carries that limit instead of claiming a clean teardown, and the later timeout's own
        teardown is recorded beside it.
        """
        pids_file = ARTIFACTS / "clean-exit-pids.txt"
        pids_file.unlink(missing_ok=True)
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  'id = "canned:exit-then-hang"',
                                  "command = [",
                                  f'  ["{{python}}", "scripts/exit_worker.py", '
                                  f'{json.dumps(str(pids_file))}],',
                                  '  ["{python}", "-c", "import time; time.sleep(120)"],',
                                  "]",
                                  "",
                              ]))
        write_suite(root, "scripts/exit_worker.py", CLEAN_EXIT_WORKER)
        code, output, payload = self.run_main(root, "--suite", "canned:exit-then-hang",
                                              "--timeout", "4")
        self.assertEqual(code, 1, output)
        entry = self.states(payload)["canned:exit-then-hang"]
        self.assertEqual(entry["state"], "TIMEOUT")
        pids = self.leftover_pids(pids_file)
        self.assertEqual(len(pids), 1)
        worker_pid = pids[0]
        self.assertTrue(process_running(worker_pid),
                        "the worker the cleanly exited command left was stopped: the run signals "
                        "only the process it spawned")
        self.assertIn(str(worker_pid), entry["reason"],
                      "the worker found before the reap is not named in the record")
        self.assertIn("left alone", entry["reason"])
        self.assertIn("the spawned process terminated", entry["reason"],
                      "the timeout's own teardown was not recorded beside the clean exit's")
        self.assertFalse(entry["teardown"]["verified"], entry["teardown"])
        self.assertEqual(entry["teardown"]["clauses"], ["the spawned process"])
        self.assertEqual(entry["teardown"]["survivors"], [],
                         "a worker that was never signalled is not a survivor")

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the clean exit is observed without reaping")
    def test_a_clean_exits_unverified_teardown_reaches_the_published_record(self):
        """A clean exit whose group cannot be checked must say so in the run's own record.

        Model: a host that cannot enumerate processes (`PROC_ROOT` absent — macOS/BSD).  Command one
        exits 0 and leaves a same-group worker whose environment is empty and whose cwd is `/`; the
        pre-reap check cannot run, so the worker is left running — and the suite's published entry
        must carry that limit in its reason and in its teardown record instead of reading
        `PASS / reason: ok` with nothing else to show.
        """
        pids_file = ARTIFACTS / "degraded-clean-exit-pids.txt"
        pids_file.unlink(missing_ok=True)
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  'id = "canned:clean-exit"',
                                  "command = [",
                                  f'  ["{{python}}", "scripts/exit_worker.py", '
                                  f'{json.dumps(str(pids_file))}],',
                                  "]",
                                  "",
                              ]))
        write_suite(root, "scripts/exit_worker.py", CLEAN_EXIT_WORKER)
        self.patch(runner, "PROC_ROOT", Path("/nonexistent-proc"))
        code, output, payload = self.run_main(root)
        self.assertEqual(code, 0, output)
        entry = self.states(payload)["canned:clean-exit"]
        self.assertEqual(entry["state"], "PASS", entry["reason"])
        self.assertIn("unverified", entry["reason"])
        self.assertIn("could not be checked before the reap", entry["reason"])
        self.assertFalse(entry["teardown"]["verified"], entry["teardown"])
        self.assertIn("could not be checked before the reap",
                      " ".join(entry["teardown"]["unverified"]))
        pids = self.leftover_pids(pids_file)
        self.assertEqual(len(pids), 1)
        self.assertTrue(process_running(pids[0]),
                        "the worker this platform cannot find was reported as stopped")

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the clean exit is observed without reaping")
    def test_provisionings_teardown_limits_survive_the_suite_command_vector(self):
        """Successful provisioning's own teardown is merged into the suite's, never replaced.

        Model: a host that cannot read an identity (`/proc` absent).  Provisioning exits 0 and
        leaves a same-group worker behind, so its own record says the pre-reap check could not run;
        the suite command then times out and cannot be torn down either.  The published record must
        carry both limits — the provisioning vector's and the command vector's — because the
        provisioning limit is a limit of this suite's run, wherever the worker was started.
        """
        pids_file = ARTIFACTS / "provision-pids.txt"
        pids_file.unlink(missing_ok=True)
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  'id = "canned:provision-then-hang"',
                                  "provision = [",
                                  f'  ["{{python}}", "scripts/exit_worker.py", '
                                  f'{json.dumps(str(pids_file))}],',
                                  "]",
                                  "command = [",
                                  '  ["{python}", "-c", "import time; time.sleep(120)"],',
                                  "]",
                                  "",
                              ]))
        write_suite(root, "scripts/exit_worker.py", CLEAN_EXIT_WORKER)
        self.patch(runner, "PROC_ROOT", Path("/nonexistent-proc"))
        self.patch(runner, "KILL_GRACE_SECONDS", 0.3)
        code, output, payload = self.run_main_leaving_strays(root, "--timeout", "3")
        self.assertEqual(code, 1, output)
        entry = self.states(payload)["canned:provision-then-hang"]
        self.assertEqual(entry["state"], "TIMEOUT", entry["reason"])
        self.assertIn("could not be checked before the reap", entry["reason"],
                      "provisioning's teardown record was replaced by the suite command's")
        self.assertNotIn("the spawned process terminated", entry["reason"],
                         "a platform that can pin nothing claimed a termination")
        notes = " ".join(entry["teardown"]["unverified"])
        self.assertIn("could not be checked before the reap", notes,
                      "provisioning's own limit is missing from the merged record")
        self.assertIn("was not sent SIGTERM", " ".join(entry["teardown"]["refused"]),
                      "the command vector's own refusal is missing from the merged record")
        # The refusal names the first capability this host cannot hold (`/proc` where pidfds
        # exist, the pidfd itself where they do not); the enumeration limit above is exact either
        # way, because the group report never consults the delivery gates.
        expected = "pidfd" if not runner.PIDFD_PINNING else "has no /proc"
        self.assertIn(expected, " ".join(entry["teardown"]["refused"]),
                      "the merged record does not say which capability refused the delivery")
        pids = self.leftover_pids(pids_file)
        self.assertEqual(len(pids), 1)

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the clean exit is observed without reaping")
    def test_a_provisioning_failure_publishes_its_teardown_limit(self):
        """A provisioning failure that is a normal non-zero exit still carries its teardown's limit.

        Provisioning exits 1 — not a timeout, not a death by signal — after leaving a same-group
        worker whose environment is empty and whose cwd is `/`, and this host cannot read the
        identity the pre-reap check needs, so the teardown is unverified.  That limit must reach
        `outcome.reason` the way `settle()` publishes its own: a provisioning failure may not read
        like a bare command echo while its record says the group was never checked.
        """
        pids_file = ARTIFACTS / "provision-fail-pids.txt"
        pids_file.unlink(missing_ok=True)
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  'id = "canned:provision-fails"',
                                  "provision = [",
                                  f'  ["{{python}}", "scripts/failing_provision.py", '
                                  f'{json.dumps(str(pids_file))}],',
                                  "]",
                                  'command = [["{python}", "-c", "pass"]]',
                                  "",
                              ]))
        write_suite(root, "scripts/failing_provision.py", FAILING_PROVISION)
        self.patch(runner, "PROC_ROOT", Path("/nonexistent-proc"))
        code, output, payload = self.run_main(root)
        self.assertEqual(code, 1, output)
        entry = self.states(payload)["canned:provision-fails"]
        self.assertEqual(entry["state"], "ERROR", entry["reason"])
        self.assertIn("provisioning failed", entry["reason"])
        self.assertIn("could not be checked before the reap", entry["reason"],
                      "the provisioning failure's teardown limit is not in its reason")
        self.assertFalse(entry["teardown"]["verified"], entry["teardown"])
        pids = self.leftover_pids(pids_file)
        self.assertEqual(len(pids), 1)

    @unittest.skipUnless(runner.PROC_ROOT.is_dir(), "the report reads /proc")
    def test_a_detached_worker_is_reported_before_the_scratch_goes(self):
        """A worker that left the suite's group is found and named before the scratch is deleted.

        The fixture worker does what both launcher adapters do — `start_new_session`, then poll the
        suite's task-local scratch — and records `beat.gone` the first time that tree disappears.
        It keeps running until the test stops it, so the "still running" reading cannot race the
        suite's own scratch cleanup: the run must name the worker it found in the record, its log
        must claim no delivery to it, and it must leave it running for the test to stop.
        """
        write_suite(ARTIFACTS, "detached-worker.py", DETACHED_WORKER)
        beat = ARTIFACTS / "beat"
        entry, pids = self.run_abnormal_fixture(
            "detached", DETACHED_SUITE,
            env={"BEAT": str(beat), "WORKER_FILE": str(ARTIFACTS / "detached-worker.py")})
        self.assertEqual(entry["state"], "TIMEOUT")
        self.assertEqual(len(pids), 1)
        worker_pid = pids[0]
        self.assertGreaterEqual(int(beat.read_text(encoding="utf-8")), 1,
                                "the worker never wrote a heartbeat")
        self.assertTrue(process_running(worker_pid),
                        "the detached worker was stopped: the run must signal only what it spawned")
        self.assertIn(str(worker_pid), entry["reason"],
                      "the detached worker left behind is not named in the record")
        self.assertIn("left alone", entry["reason"])
        self.assert_no_delivery_to(entry, worker_pid)
        self.assertEqual(entry["teardown"]["survivors"], [],
                         "a worker that was never signalled is not a survivor")
        self.assertFalse(entry["teardown"]["verified"], entry["teardown"])

    @unittest.skipUnless(runner.PROC_ROOT.is_dir(), "the detection reads /proc")
    def test_scratch_detection_follows_the_cwd_symlink(self):
        """`cwd` is a symlink, not a file: readlink sees what read_bytes raised IsADirectoryError on.

        The worker empties its environment, so the cwd it was started in is the only tie to the
        suite's scratch — and the only way to find it is the `/proc/<pid>/cwd` symlink.
        """
        scratch = Path(tempfile.mkdtemp(prefix="cwd-detect-", dir=self.scratch))
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                  cwd=scratch, env={}, start_new_session=True)
        self.addCleanup(worker.wait)
        self.addCleanup(worker.kill)
        found = [pid for pid, _start in runner._scratch_processes(scratch) or []]
        self.assertIn(worker.pid, found,
                      "a worker whose only tie to scratch is its cwd was not found")

    @unittest.skipUnless(runner.PROC_ROOT.is_dir(), "the report reads /proc")
    def test_a_worker_only_its_cwd_identifies_is_found_and_reported(self):
        """The environment check is not the only tie to scratch: the cwd symlink counts too.

        The fixture worker sanitizes its environment (`WORKER_SANITIZED`) and is started with its
        cwd inside the suite's task-local TMPDIR (`WORKER_CWD_SCRATCH`), so `environ` shows nothing
        and only the `/proc/<pid>/cwd` symlink finds it after the timeout; the record must name it,
        the run's log must claim no delivery to it, and the run must leave it running.
        """
        write_suite(ARTIFACTS, "detached-worker.py", DETACHED_WORKER)
        beat = ARTIFACTS / "cwd-beat"
        entry, pids = self.run_abnormal_fixture(
            "cwd_detached", DETACHED_SUITE,
            env={"BEAT": str(beat), "WORKER_FILE": str(ARTIFACTS / "detached-worker.py"),
                 "WORKER_SANITIZED": "1", "WORKER_CWD_SCRATCH": "1"})
        self.assertEqual(entry["state"], "TIMEOUT")
        self.assertEqual(len(pids), 1)
        worker_pid = pids[0]
        self.assertGreaterEqual(int(beat.read_text(encoding="utf-8")), 1,
                                "the worker never wrote a heartbeat")
        self.assertTrue(process_running(worker_pid),
                        "the worker identified only by its cwd was stopped")
        self.assertIn(str(worker_pid), entry["reason"],
                      "the worker found through its cwd symlink is not named in the record")
        self.assertIn("left alone", entry["reason"])
        self.assert_no_delivery_to(entry, worker_pid)
        self.assertEqual(entry["teardown"]["survivors"], [],
                         "a worker that was never signalled is not a survivor")

    @unittest.skipUnless(can_deliver_signals(),
                         "a signalled command needs pidfds, /proc evidence and waitid(WNOWAIT)")
    def test_a_signal_killed_suite_reports_the_group_it_did_not_touch(self):
        """A suite killed by a signal is already terminated: its group is reported, never signalled.

        The fixture's same-group child SIGKILLs the suite leader once it is ready, and the long
        timeout keeps the timeout path out of the picture.  The spawned process is a corpse by the
        time the teardown runs, so nothing is signalled at all — no delivery to a dead process, no
        delivery to the child — and the child, which sanitizes its environment and runs with
        `cwd="/"`, can only be found through the group the leader led; the record must name it and
        the run must leave it alone.
        """
        write_suite(ARTIFACTS, "signal-killer.py", SIGNAL_KILLER)
        ready = ARTIFACTS / "signal-ready"
        ready.unlink(missing_ok=True)
        entry, pids = self.run_abnormal_fixture(
            "signalled", SIGNALLED_SUITE, timeout="20",
            env={"READY": str(ready), "KILLER_FILE": str(ARTIFACTS / "signal-killer.py")})
        self.assertEqual(entry["state"], "ERROR")
        self.assertEqual(entry["exit_code"], -9, "the fixture leader was not killed by SIGKILL")
        self.assertEqual(len(pids), 1)
        child_pid = pids[0]
        self.assertIn("terminated by signal 9", entry["reason"])
        self.assertTrue(process_running(child_pid),
                        "the group member was signalled although the run's process was already dead")
        self.assertIn(str(child_pid), entry["reason"],
                      "the member the signal-killed suite left behind is not named in the record")
        self.assertIn("left alone", entry["reason"])
        self.assertFalse(entry["teardown"]["verified"], entry["teardown"])
        self.assertEqual(entry["teardown"]["clauses"], [],
                         "a teardown that signalled nothing terminated nothing")
        self.assertEqual(entry["teardown"]["survivors"], [],
                         "a process that was never signalled is not a survivor")

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the timeout needs the observation to fire")
    def test_a_refused_delivery_claims_no_sigkill_and_records_no_survivor(self):
        """Nothing signalled means nothing survived: no SIGKILL claim, no survivor, no kill grace.

        Model: a host that cannot open a pidfd (`PIDFD_PINNING` False), so every delivery is
        refused and the timeout's process keeps running.  The record must say the refusal, must not
        borrow the survivor vocabulary of a process that took a SIGKILL, and must not wait out a
        kill grace for a signal that was never sent — the elapsed time is the observable proof of
        the last one.
        """
        root = self.build()
        self.patch(runner, "PIDFD_PINNING", False)
        self.patch(runner, "KILL_GRACE_SECONDS", 5.0)
        started = time.monotonic()
        code, output, payload = self.run_main_leaving_strays(root, "--suite", "scripts/test_hang.py",
                                                            "--timeout", "3")
        elapsed = time.monotonic() - started
        self.assertEqual(code, 1, output)
        entry = self.states(payload)["scripts/test_hang.py"]
        self.assertEqual(entry["state"], "TIMEOUT")
        self.assertLess(elapsed, 7.0,
                        "a refused delivery was waited out as if a signal had been sent")
        self.assertEqual(entry["teardown"]["survivors"], [],
                         "a process that was never signalled is not a survivor")
        self.assertNotIn("survived SIGKILL", entry["reason"])
        self.assertIn("was not sent SIGTERM", " ".join(entry["teardown"]["refused"]),
                      "the refusal and its reason are missing from the record")
        self.assertIn("pidfd", " ".join(entry["teardown"]["refused"]))
        pids = self.leftover_pids(ARTIFACTS / "pids.txt")
        self.assertEqual(len(pids), 2)
        for pid in pids:
            self.assertTrue(process_running(pid),
                            "a process was stopped although nothing could be delivered")

    def test_the_delivery_log_and_the_record_are_one_bijection(self):
        """Both directions of the bijection fail, and a renamed field fails loudly.

        The helper reads the record's `delivered` strictly and compares it with the log through the
        runner's own pattern, so: a log with no line for a delivery the record carries fails, a line
        the record does not carry fails, a line the pattern cannot read fails, a record that has been
        renamed where `delivered` was fails (`KeyError`, never "no deliveries"), and a delivery to a
        pid this run did not spawn fails even when the record carries it consistently.
        """
        attempt = delivery(4242, start="7", stopped=True)
        record = runner._teardown_record(runner.Teardown(attempts=(attempt,)))
        agreeing = ARTIFACTS / "bijection-agreeing.log"
        agreeing.write_text(attempt.log_line(), encoding="utf-8")
        self.assert_no_delivery_to({"log": str(agreeing), "teardown": record}, 999)
        empty = ARTIFACTS / "bijection-empty.log"
        empty.write_text("", encoding="utf-8")
        with self.assertRaises(AssertionError, msg="an empty log passed for a real delivery"):
            self.assert_no_delivery_to({"log": str(empty), "teardown": record}, 999)
        phantom = ARTIFACTS / "bijection-phantom.log"
        phantom.write_text(attempt.log_line() + delivery(999, start="3").log_line(),
                           encoding="utf-8")
        with self.assertRaises(AssertionError, msg="a phantom line passed"):
            self.assert_no_delivery_to({"log": str(phantom), "teardown": record}, 4242)
        reworded = ARTIFACTS / "bijection-reworded.log"
        reworded.write_text(
            f"[discoverer] teardown: {runner.DELIVERY_MARKER} {attempt.pid}, the process this run "
            f"spawned (pinned at delivery)\n", encoding="utf-8")
        with self.assertRaises(AssertionError, msg="an unreadable delivery line passed"):
            self.assert_no_delivery_to(
                {"log": str(reworded),
                 "teardown": runner._teardown_record(runner.Teardown())}, 999)
        renamed = {key: value for key, value in record.items() if key != "delivered"}
        with self.assertRaises(KeyError, msg="a renamed field did not fail loudly"):
            self.assert_no_delivery_to({"log": str(agreeing), "teardown": renamed}, 999)

    @unittest.skipUnless(can_deliver_signals(),
                         "the mixed path needs one real delivery and one real pin")
    def test_a_refusal_after_a_delivery_does_not_erase_it(self):
        """A later round's refusal is an attempt beside the delivery, never a replacement for it.

        Model: the fixture ignores SIGTERM and the run's second pin cannot open a pidfd (`EMFILE`
        injected on the runner's own `os.pidfd_open(pid)` call, the second one) — so SIGTERM is
        really delivered and logged, SIGKILL is refused with its reason, and the record must carry
        both: `delivered` names the SIGTERM delivery, `refused` names the SIGKILL refusal, and the
        refusal does not erase the delivery.  Neither `clauses` nor `survivors` may claim anything,
        though — the SIGTERM did not stop the target and the SIGKILL was never sent, so both must
        stay empty.  The delivery lines must be
        required of the log whichever way the record reads, so clearing them from a copy of the log
        must fail — that negative control is what the helper is unconditional for.
        """
        real_open = os.pidfd_open
        pins: list[int] = []

        def opening(pid: int, *flags: int) -> int:
            if not flags:  # the runner's pin calls `os.pidfd_open(pid)`; `subprocess` passes flags
                pins.append(pid)
                if len(pins) >= 2:
                    raise OSError(errno.EMFILE, "Too many open files")
            return real_open(pid, *flags)

        self.patch(os, "pidfd_open", opening)
        self.patch(runner, "KILL_GRACE_SECONDS", 0.3)
        entry, pids = self.run_abnormal_fixture("held", HELD_LEADER, env={}, timeout="3")
        leader_pid, child_pid = pids
        self.assertEqual(len(pins), 2, "the run did not pin the target once per round")
        teardown = entry["teardown"]
        self.assertEqual([(item["pid"], item["signal"], item["stopped"])
                          for item in teardown["delivered"]],
                         [(leader_pid, "SIGTERM", False)],
                         "the delivered SIGTERM is not in the record")
        self.assertIn("was not sent SIGKILL", " ".join(teardown["refused"]),
                      "the refused SIGKILL and its reason are missing from the record")
        self.assertIn("Too many open files", " ".join(teardown["refused"]))
        self.assertEqual(teardown["clauses"], [],
                         "the record claims a terminated target although the delivered SIGTERM "
                         "stopped nothing and no SIGKILL was sent")
        self.assertEqual(teardown["survivors"], [],
                         "a process that took no SIGKILL is not a survivor")
        self.assertFalse(teardown["verified"], teardown)
        self.assertEqual([signal_name for signal_name, _pid, _start
                          in parse_delivery_lines(Path(entry["log"]).read_text(encoding="utf-8"))],
                         ["SIGTERM"], "the log does not carry exactly the delivery that happened")
        self.assert_no_delivery_to(entry, child_pid)
        self.assertTrue(process_running(leader_pid),
                        "the fixture ignores SIGTERM, so it must still be running")
        self.assertTrue(process_running(child_pid),
                        "the member was signalled although the run signals only what it spawned")
        cleared = ARTIFACTS / "held-cleared.log"
        cleared.write_text("\n".join(
            line for line in Path(entry["log"]).read_text(encoding="utf-8").splitlines()
            if runner.DELIVERY_MARKER not in line) + "\n", encoding="utf-8")
        with self.assertRaises(AssertionError,
                               msg="a cleared log passed for a run that delivered a signal"):
            self.assert_no_delivery_to({**entry, "log": str(cleared)}, child_pid)

    @unittest.skipUnless(can_deliver_signals(),
                         "the path needs one real delivery before the missing constant")
    def test_a_host_without_the_final_signal_records_the_refusal_it_cannot_send(self):
        """A signal name this platform does not define is a refusal, never a silently skipped round.

        Model: the host can deliver (pidfds, `/proc`, the observation all hold) but `signal.SIGKILL`
        is gone, and the fixture ignores SIGTERM — the escalation's first round really delivers and
        logs, and the second round must record that it could not send its signal.  The record names
        the missing constant, the target is still running, and nothing claims it was terminated or
        that it survived a signal nobody sent.
        """
        kill_signal = signal.SIGKILL
        self.remove_attribute(signal, "SIGKILL")
        pids_file = ARTIFACTS / "no-final-signal-pids.txt"
        pids_file.unlink(missing_ok=True)
        # Registered before the run: this fixture ignores SIGTERM and only the test can stop it, so a
        # run that dies before the pids below are registered must not leak it.
        self.addCleanup(stop_recorded_pids, pids_file, kill_signal)
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  'path = "scripts/test_held.py"',
                                  f'env = {{ PID_FILE = "{pids_file}" }}',
                                  "",
                              ]))
        write_suite(root, "scripts/test_held.py", HELD_LEADER)
        self.patch(runner, "KILL_GRACE_SECONDS", 0.5)
        code, output, payload = self.run_main_leaving_strays(root, "--timeout", "3")
        self.assertEqual(code, 1, output)
        entry = self.states(payload)["scripts/test_held.py"]
        self.assertEqual(entry["state"], "TIMEOUT")
        leader_pid, child_pid = self.leftover_pids_with(pids_file, kill_signal)
        teardown = entry["teardown"]
        self.assertEqual([(item["pid"], item["signal"], item["stopped"])
                          for item in teardown["delivered"]],
                         [(leader_pid, "SIGTERM", False)], teardown)
        self.assertIn("this platform defines no SIGKILL", " ".join(teardown["refused"]),
                      "the round that could not resolve its constant is not in the record")
        self.assertEqual(teardown["survivors"], [],
                         "a target nothing could finish off is not a survivor")
        self.assertEqual(teardown["clauses"], [],
                         "nothing terminated the target, so no clause may claim it")
        self.assertFalse(teardown["verified"], teardown)
        self.assert_no_delivery_to(entry, child_pid)
        self.assertTrue(process_running(leader_pid),
                        "the fixture must still be running: no signal could stop it")

    def test_only_an_executed_suite_publishes_the_teardown_record(self):
        """An executed suite's entry always carries the full record; one that never ran has none.

        The record is the evidence surface, so its key set is pinned as a whole — a rename must fail
        loudly rather than read as an empty field — and both ways a suite is not executed publish
        None instead of a record that pretends a teardown happened: a covered child, whose evidence
        lives in its parent's log, and a condition-skipped suite.
        """
        root = synthetic_tree(patterns=["scripts/test_*.py", "scripts/tests/test*.py"], prune=[],
                              floor=[], suites="\n".join([
                                  "[[suite]]",
                                  'path = "scripts/test_pass.py"',
                                  "",
                                  "[[suite]]",
                                  'id = "canned:pr-only"',
                                  'condition = "pull_request"',
                                  'skip_reason = "the local event does not run PR gates"',
                                  'command = [["{python}", "-c", "print(\'pr-only: 1/1 ok\')"]]',
                                  'assertion = "counter"',
                                  'count_regexes = ["^pr-only: (?P<passed>\\\\d+)/'
                                  '(?P<total>\\\\d+) ok$"]',
                                  "",
                                  "[[suite]]",
                                  'path = "scripts/tests/test-child.py"',
                                  'covered_by = "scripts/test_pass.py"',
                                  'assertion = "unittest"',
                                  "required = false",
                                  "",
                              ]))
        write_suite(root, "scripts/test_pass.py",
                    "# executes scripts/tests/test-child.py in production\n" + PASS_SUITE)
        write_suite(root, "scripts/tests/test-child.py", "print('never scheduled on its own')\n")
        code, output, payload = self.run_main(root)
        entries = self.states(payload)
        executed = entries["scripts/test_pass.py"]
        self.assertEqual(executed["state"], "PASS", output)
        self.assertEqual(set(executed["teardown"]),
                         {"verified", "delivered", "clauses", "survivors", "unverified", "refused"},
                         "the published record's fields are the record's contract")
        self.assertEqual(executed["teardown"]["delivered"], [])
        self.assertTrue(executed["teardown"]["verified"], executed["teardown"])
        self.assertEqual(entries["canned:pr-only"]["state"], "SKIP", output)
        self.assertIsNone(entries["canned:pr-only"]["teardown"],
                          "a suite that never executed published a record")
        self.assertIsNone(entries["scripts/tests/test-child.py"]["teardown"],
                          "a covered child published a record of its own")
        self.assertEqual(code, 0, output)

    def test_covered_child_with_a_hiding_counter_line_is_error(self):
        """Contradictory counter evidence may not settle PASS by way of `covered_by`.

        The parent settles PASS on its own consistent line while the child's line claims 1 of
        100 checks passed; the same summary is ERROR for a scheduled suite, so it is ERROR here.
        """
        root = self.build()
        (root / "scripts/tests/parent.py").write_text(
            "# executes scripts/tests/test-counter-child.py in production\n"
            "print('parent-counter: 2/2 ok')\n"
            "print('child-counter: 1/100 ok')\n", encoding="utf-8")
        code, _, payload = self.run_main(root, "--suite", "parent")
        self.assertEqual(self.states(payload)["parent"]["state"], "PASS")
        child = self.states(payload)["scripts/tests/test-counter-child.py"]
        self.assertEqual(child["state"], "ERROR")
        self.assertEqual(child["counts"], {"passed": 1, "executed": 100, "total": 100})
        self.assertIn("disagrees", child["reason"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
