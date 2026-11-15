#!/usr/bin/env python3
"""Tests for the DSH launcher adapter (scripts/adapters/dsh-run.py).

Stdlib unittest, driving a stub `dsh` on PATH that emits canned NDJSON: no
network, no model, no real dsh run. Covered: start -> settled run (state
transitions, answer extraction, artifacts, the agent's cwd), the exit-code and
completion mapping (including streams with several `final` events), stale recovery
once and idempotently through every reader that triggers it, kill through the
`stop` control file and the forced TERM->KILL escalation behind it, the bounded
event log's loss accounting and its byte bound, the argument passthrough to the
agent (including the prompt on stdin), the scrubbing of the harness's reserved
`DSH_PROFILE`/`DSH_PROFILE_DIR`/`DSH_SESSION_ID` from every child, the refusal of
a second `start`, the `--max-time` deadline, and the detachment evidence.

Also pinned here: `start` succeeds only once the runner recorded the agent pid
(a live runner alone is not a started run), a live run occupies its slug across
date buckets, publication stops before the finalizer commits so a late reader
cannot rewrite the verdict, a recorded pid is never signalled unless its process
identity still matches, the finalize claim is an OS lock a competitor cannot
delete, the generated `.cmd` replay quotes what cmd would parse, and a non-`never`
approval policy is refused instead of dispatched.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import re
import select
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
ADAPTER = SCRIPTS / "adapters" / "dsh-run.py"
REPO = HERE.parents[3]
IS_WINDOWS = os.name == "nt"
START_TIMEOUT = 30.0
SETTLE_TIMEOUT = 60.0
# The adapter's terminal states: a `state` in this set is only settled once the
# `finalized` marker exists and the runner that wrote it has exited.
TERMINAL_STATES = frozenset({"done", "killed", "failed", "unknown"})

STUB_SOURCE = '''\
#!/usr/bin/env python3
"""Stub `dsh`: canned headless NDJSON on stdout, driven by env vars."""
import json
import os
import signal
import sys
import time


def emit(event):
    sys.stdout.write(json.dumps(event) + "\\n")
    sys.stdout.flush()


def main():
    argv = sys.argv[1:]
    # Every agent start is appended here: a race that produces two agents leaves
    # two lines, whichever run directory the second one wrote into.
    append_file = os.environ.get("STUB_APPEND_FILE")
    if append_file:
        with open(append_file, "a", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\\n")
    argv_file = os.environ.get("STUB_ARGV_FILE")
    if argv_file:
        with open(argv_file, "w", encoding="utf-8") as handle:
            json.dump(argv, handle)
    env_file = os.environ.get("STUB_ENV_FILE")
    if env_file:
        # What the worker actually inherited, presence and value: the adapter must
        # have removed the caller's harness identity before this process started.
        names = ("DSH_PROFILE", "DSH_PROFILE_DIR", "DSH_SESSION_ID", "DSH_RUN_PROFILE")
        with open(env_file, "w", encoding="utf-8") as handle:
            json.dump({"present": [name for name in names if name in os.environ],
                       "values": {name: os.environ.get(name) for name in names}}, handle)
    # The headless app reads the task from stdin when the argument is a lone `-`.
    task = ""
    if not argv or argv[-1] == "-":
        task = sys.stdin.read()
    stdin_file = os.environ.get("STUB_STDIN_FILE")
    if stdin_file:
        with open(stdin_file, "w", encoding="utf-8") as handle:
            handle.write(task)
    mode = os.environ.get("STUB_MODE", "settle")
    session = os.environ.get("STUB_SESSION") or "session-stub-0001"
    emit({"type": "session", "sessionId": session, "cwd": os.getcwd()})
    if mode == "signal":
        os.kill(os.getpid(), getattr(signal, os.environ["STUB_SIGNAL"]))
    if mode == "error":
        emit({"type": "error", "message": os.environ.get("STUB_ERROR")
              or "MISSING_CREDENTIAL: llm-pi-ai: no credential for provider route \\"stub\\""})
        return int(os.environ.get("STUB_EXIT") or "1")
    if mode == "sleep":
        emit({"type": "status", "turn": 1, "step": 0, "phase": "turn_start"})
        emit({"type": "text", "text": "half a report"})
        emit({"type": "tool_call", "callId": "c1", "tool": "bash", "input": {"command": "sleep 300"}})
        while True:
            emit({
                "type": "status", "turn": 1, "step": 1, "phase": "turn_end",
                "usage": {"inputTokens": 10, "outputTokens": 2, "totalTokens": 12,
                          "cacheReadTokens": 0},
            })
            time.sleep(0.2)
    if mode == "quiet":
        # One committed text, then silence: no further event makes the runner
        # republish state.json, so a test can treat the run directory as stable
        # while it checks that a stale reader wrote nothing.
        emit({"type": "text", "text": "quarter report"})
        time.sleep(300)
        return 0
    if mode == "flood":
        filler = "x" * 2000
        for index in range(300):
            emit({"type": "status", "turn": 1, "step": index, "phase": "step_start",
                  "filler": filler})
        emit({"type": "tool_call", "callId": "flood", "tool": "bash", "input": {"filler": filler}})
        emit({"type": "text", "text": "flooded"})
        emit({"type": "status", "turn": 1, "step": 300, "phase": "turn_end"})
        emit({"type": "final", "sessionId": session, "reason": {"kind": "completed"},
              "text": "flooded"})
        return 0
    # settle / aborted / exitcode: one committed assistant message, then the final.
    emit({
        "type": "status", "turn": 1, "step": 1, "phase": "turn_start",
        "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120,
                  "cacheReadTokens": 5},
    })
    emit({"type": "tool_call", "callId": "c1", "tool": "bash", "input": {"command": "echo hi"}})
    emit({"type": "tool_result", "callId": "c1", "status": "completed", "result": "hi"})
    emit({"type": "thinking", "text": "considering", "truncated": False})
    text = os.environ.get("STUB_TEXT") or "STUB ANSWER: the stage finished."
    reason = os.environ.get("STUB_REASON") or "completed"
    emit({"type": "text", "text": text})
    emit({"type": "status", "turn": 1, "step": 1, "phase": "turn_end",
          "reason": {"kind": reason}})
    finals = os.environ.get("STUB_FINALS")
    if finals:
        # Several finals in one stream: only the last one may decide the run.
        for index, kind in enumerate(json.loads(finals)):
            emit({"type": "final", "sessionId": session,
                  "reason": None if kind is None else {"kind": kind},
                  "text": f"{text} (final {index + 1}: {kind})"})
    else:
        emit({"type": "final", "sessionId": session, "reason": {"kind": reason}, "text": text})
    return int(os.environ.get("STUB_EXIT") or "0")


if __name__ == "__main__":
    sys.exit(main())
'''


def load_adapter() -> types.ModuleType:
    """The adapter as a module, without leaving bytecode in the installed skill dir."""
    module = types.ModuleType("gdd_dsh_run")
    module.__file__ = str(ADAPTER)
    exec(compile(ADAPTER.read_bytes(), str(ADAPTER), "exec"), module.__dict__)
    return module


adapter = load_adapter()


class ProcessFixtures(unittest.TestCase):
    """Process fixtures shared by both suites: readiness by handshake, cleanup always.

    Every spawned process is registered for cleanup *immediately* after a
    successful `Popen`, so a failing assertion — or an exception in the test's own
    setup — cannot leak a live process. Readiness is never a sleep and never the
    bare return of `Popen`: the child acknowledges what it has installed, and the
    parent blocks on that acknowledgement under a finite deadline.
    """

    def spawn(self, argv, **kwargs):
        """`Popen` with cleanup registered immediately after a successful spawn."""
        process = subprocess.Popen(argv, **kwargs)
        self.addCleanup(self.reap, process)
        return process

    def reap(self, victim):
        """Kill and reap one spawned process, closing its pipes — always safe."""
        try:
            if victim.poll() is None:
                victim.kill()
            victim.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for stream in (getattr(victim, "stdout", None), getattr(victim, "stderr", None)):
            if stream is None:
                continue
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def read_line(self, process, timeout=30.0):
        """One line of a spawned process's stdout, with a finite timeout."""
        deadline = time.monotonic() + timeout
        buffer = b""
        fd = process.stdout.fileno()
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if not ready:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            if b"\n" in buffer:
                line, _, _ = buffer.partition(b"\n")
                return line.decode("utf-8", "replace").strip()
        self.fail(f"the child never reported readiness (stdout so far: {buffer!r})")

    def ignoring_agent(self):
        """A real agent process that ignores SIGTERM and *then* reports ready.

        The acknowledgement is what makes the fixture deterministic: a TERM the
        test sends afterwards is guaranteed to meet the installed handler, so
        "the process ignores TERM" is established rather than hoped for.
        """
        code = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "sys.stdout.write('ready\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(300)\n"
        )
        process = self.spawn(
            [sys.executable, "-c", code],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.assertEqual(self.read_line(process), "ready")
        return process

    def group_with_ready_member(self):
        """(leader, member_pid): a group leader and a distinct member that is ready.

        The member installs its signal handlers, reports ready and then waits; the
        leader relays that readiness and also ignores TERM. The member is in the
        leader's process group (no new session of its own), which is the shape a
        dsh run's tool has: a process whose leader can die first.
        """
        member_code = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "sys.stdout.write('ready\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(300)\n"
        )
        leader_code = (
            "import signal, subprocess, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            f"member = subprocess.Popen([sys.executable, '-c', {member_code!r}],"
            " stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)\n"
            "member.stdout.readline()\n"
            "sys.stdout.write('member %d ready\\n' % member.pid)\n"
            "sys.stdout.flush()\n"
            "time.sleep(300)\n"
        )
        leader = self.spawn(
            [sys.executable, "-c", leader_code],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        line = self.read_line(leader)
        self.assertTrue(line.startswith("member "), line)
        member_pid = int(line.split()[1])
        self.addCleanup(self.reap_pids, [member_pid])
        return leader, member_pid

    def reap_pids(self, pids):
        """Kill a set of pids this test no longer owns (best effort, always safe)."""
        for pid in pids:
            if adapter.liveness_of(pid) == adapter.GONE:
                continue
            try:
                info = adapter.ProcessHandle(pid, adapter.process_identity(pid))
                if info.open():
                    try:
                        info.signal(signal.SIGKILL)
                    finally:
                        info.close()
            except OSError:
                pass
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and any(
            adapter.liveness_of(pid) != adapter.GONE for pid in pids
        ):
            time.sleep(0.02)

    def signal_spy(self):
        """Record every signal the adapter *delivers*, and forbid the group path.

        Delivery is observed on the validated handle itself
        (`ProcessHandle.signal`), so the assertion is about which process instance
        was targeted, not about what the target does with the signal. Any
        `os.killpg` carrying a real signal is an error; signal 0 is the existence
        probe the adapter is allowed to make.
        """
        delivered = []
        real_killpg = adapter.os.killpg

        def killpg(pgid, signum):
            if signum != 0:
                raise AssertionError("the group id itself must never be signalled")
            return real_killpg(pgid, signum)

        def handle_signal(handle, signum):
            delivered.append((handle.pid, signum))
            return True

        return delivered, [
            mock.patch.object(adapter.os, "killpg", killpg),
            mock.patch.object(adapter.ProcessHandle, "signal", handle_signal),
        ]


class DshLauncherTests(ProcessFixtures):
    """One temp run root for the class; every test owns its own slugs and run dirs."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="dsh-run-py."))
        cls.bin = cls.tmp / "bin"
        cls.bin.mkdir()
        if IS_WINDOWS:
            cls.stub_py = cls.bin / "stub-dsh.py"
            cls.stub_py.write_text(STUB_SOURCE, encoding="utf-8")
            (cls.bin / "dsh.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" "{cls.stub_py}" %*\r\n', encoding="utf-8"
            )
        else:
            stub = cls.bin / "dsh"
            stub.write_text(STUB_SOURCE, encoding="utf-8")
            stub.chmod(0o755)
        cls.prompt = cls.tmp / "prompt.md"
        cls.prompt.write_text("do the thing\n", encoding="utf-8")
        cls.run_root = cls.tmp / "runs"
        cls.env = dict(os.environ)
        cls.env.update(
            {
                "DSH_RUN_ROOT": str(cls.run_root),
                "DSH_BIN": "dsh",
                "PATH": str(cls.bin) + os.pathsep + os.environ.get("PATH", ""),
            }
        )
        for key in (
            "GDD_RUN_ROOT", "DSH_RUN_EVENTS_MAX_BYTES", "DSH_RUN_START_GRACE_SECONDS",
            "DSH_RUN_STOP_WAIT_SECONDS", "DSH_RUN_DRAIN_TIMEOUT_SECONDS", "DSH_PROFILE",
            "DSH_PROFILE_DIR", "DSH_SESSION_ID", "DSH_RUN_PROFILE",
            "DSH_PERMISSION_MODE", "DSH_APPROVAL_POLICY", "STUB_MODE", "STUB_EXIT",
            "STUB_ARGV_FILE", "STUB_STDIN_FILE", "STUB_ENV_FILE", "STUB_FINALS",
            "STUB_TEXT", "STUB_REASON", "STUB_SESSION", "STUB_APPEND_FILE",
        ):
            cls.env.pop(key, None)

    @classmethod
    def tearDownClass(cls):
        for run_dir in adapter.run_dirs(str(cls.run_root)):
            state = adapter.read_state_file(str(run_dir))
            if adapter.run_alive(str(run_dir), state):
                adapter.kill_tree(adapter.operation_of(str(run_dir), state), state)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------

    def env_for(self, **overrides):
        env = dict(self.env)
        env.update({key: str(value) for key, value in overrides.items()})
        return env

    def adapter_run(self, *args, env=None, timeout=SETTLE_TIMEOUT):
        return subprocess.run(
            [sys.executable, str(ADAPTER), *args],
            capture_output=True, text=True, env=env or self.env, timeout=timeout,
        )

    def dsh_bin(self):
        """The stub CLI this class put on PATH (`dsh.cmd` on Windows)."""
        return self.bin / ("dsh.cmd" if IS_WINDOWS else "dsh")

    def run_dir(self, slug):
        """The slug's run directory: one that exists wins over today's date bucket.

        The adapter owns the bucketing rule (and its clock), so resolving from a
        local date alone would race midnight and would break if the adapter's
        bucket changed. An existing directory with run markers is the authority;
        otherwise fall back to the adapter's own date helper, which is also what
        `start` uses for a slug that does not exist yet.
        """
        matches = [
            path for path in sorted(self.run_root.glob(f"*/{slug}"))
            if path.is_dir() and any(
                (path / marker).exists() for marker in ("state.json", "lock", "prompt.md")
            )
        ]
        if matches:
            return max(matches, key=lambda path: adapter.mtime_of(str(path)))
        return self.run_root / adapter.date_stamp() / slug

    def state_of(self, slug):
        return json.loads((self.run_dir(slug) / "state.json").read_text(encoding="utf-8"))

    def start(self, slug, *extra, env=None, assert_started=True):
        proc = self.adapter_run(
            "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp),
            *extra, env=env,
        )
        if assert_started:
            self.assertEqual(proc.returncode, 0, f"start failed: {proc.stderr}{proc.stdout}")
            self.assertIn(f"started: {slug}", proc.stdout)
            self.assertIn("run dir", proc.stdout)
        return proc

    def settled(self, slug, state=None):
        """Has finalization fully landed: `finalized` written and runner gone?"""
        run_dir = self.run_dir(slug)
        if not (run_dir / "finalized").exists():
            return False
        return not adapter.run_alive(str(run_dir), state)

    def wait_for_state(self, slug, states, timeout=SETTLE_TIMEOUT):
        """Poll state.json until its state is one of `states`; return the state.

        A terminal `state` alone is not settled: the adapter publishes state.json
        just before it writes the `finalized` marker and exits just after, so a
        caller that reads the marker, asserts `alive is False`, or renames the run
        directory would race those last milliseconds. Waiting for a terminal state
        therefore also requires the marker and the recorded processes' exit.

        A non-terminal `running` wait requires the runner's pid too: `start`
        publishes `running` before the detached runner takes ownership, so
        returning on that first write would hand the caller a state with no pid,
        no agent pid and no detachment facts to read.
        """
        terminal = set(states) <= TERMINAL_STATES
        deadline = time.monotonic() + timeout
        state = {}
        while time.monotonic() < deadline:
            try:
                state = self.state_of(slug)
            except (OSError, ValueError):
                time.sleep(adapter.POLL_SECONDS)
                continue
            if state.get("state") in states:
                if terminal:
                    if self.settled(slug, state):
                        return state
                elif state.get("pid") or state.get("agent_pid"):
                    return state
            time.sleep(adapter.POLL_SECONDS)
        self.fail(f"{slug} never reached {states}: last state {state}")

    def settle(self, slug, **env_overrides):
        self.start(slug, env=self.env_for(**env_overrides) if env_overrides else None)
        return self.wait_for_state(slug, {"done", "killed", "failed"})

    def dead_run(self, slug, session="session-dead", text="half a report"):
        """An unfinalized run whose processes are gone: input to the recovery path."""
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "prompt.md").write_text("dispatched, then the process died\n",
                                           encoding="utf-8")
        events = (
            {"type": "session", "sessionId": session, "cwd": str(self.tmp)},
            {"type": "text", "text": text},
        )
        (run_dir / "events.ndjson").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )
        (run_dir / "state.json").write_text(
            json.dumps({
                "name": slug, "state": "running", "exit": None, "cwd": str(self.tmp),
                # Older than the start grace: no pid is recorded and this run is
                # not "starting", it is dead.
                "started": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                "backend": "dsh",
                # Every run the adapter writes records a generation; a record
                # without one is a legacy run and authorizes no mutation.
                "generation": adapter.new_nonce(),
            }),
            encoding="utf-8",
        )
        return run_dir

    def kill_pid_tree(self, pid):
        """Kill one pid and its tree abruptly: SIGKILL (POSIX) or taskkill /F."""
        if IS_WINDOWS:
            adapter.run_quiet(["taskkill", "/T", "/F", "/PID", str(pid)])
            return
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def kill_hard(self, run_dir):
        """Kill a run and its agent with no chance to finalize.

        `kill_tree` is not enough for the stale path: on POSIX it sends SIGTERM,
        which the runner handles by finalizing the run — deliberately, that is
        what makes `kill` deterministic there. The stale path is for a run that
        died abruptly, so this uses SIGKILL (POSIX) or taskkill /F (Windows). On
        Windows the runner goes first, so it cannot finalize the run in between.
        """
        if IS_WINDOWS:
            lock = adapter.lock_of(str(run_dir))
            state = adapter.read_state_file(str(run_dir))
            ordered, seen = [], []
            for pid in (lock.get("pid"), lock.get("agent_pid"),
                        state.get("pid"), state.get("agent_pid")):
                if (isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
                        and pid not in seen):
                    seen.append(pid)
                    ordered.append(pid)
            for pid in ordered:
                self.kill_pid_tree(pid)
            return
        for pid in adapter.recorded_pids(str(run_dir)):
            self.kill_pid_tree(pid)

    def status_view(self, slug, env=None):
        """`status` output is one JSON object, then the recovery line when it acted."""
        proc = self.adapter_run("status", slug, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.split("\nstale_recovered: true")[0]), proc.stdout

    def wait_for_pids_gone(self, pids, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and any(adapter.pid_alive(pid) for pid in pids):
            time.sleep(adapter.POLL_SECONDS)
        self.assertFalse(any(adapter.pid_alive(pid) for pid in pids), f"still alive: {pids}")

    # -- start, settle, artifacts -------------------------------------------

    def test_01_start_settles_and_records_the_run(self):
        slug = "settle-01"
        state = self.settle(slug, STUB_TEXT="STUB ANSWER: stage complete.")
        self.assertEqual(state["state"], "done", state)
        self.assertEqual(state["exit"], 0)
        self.assertEqual(state["name"], slug)
        self.assertEqual(state["session_id"], "session-stub-0001")
        self.assertEqual(state["final_reason"], "completed")
        self.assertGreater(state["duration_s"], 0)
        self.assertTrue(state["ended"])
        self.assertEqual(state["tool_calls"], 1)
        self.assertEqual(state["turns"], 1)
        self.assertEqual(state["usage"]["total_tokens"], 120)
        self.assertEqual(state["usage"]["cache_read_tokens"], 5)
        self.assertFalse(state["events_truncated"])
        self.assertEqual(state["events_dropped_bytes"], 0)
        self.assertFalse(state["tool_calls_partial"])
        self.assertFalse(state["usage_partial"])
        self.assertEqual(state["cwd"], str(self.tmp))
        self.assertEqual(state["backend"], "dsh")
        self.assertEqual(state["permission_mode"], "workspace-write")
        self.assertEqual(state["approval_policy"], "never")
        self.assertEqual(state["profile"], "headless")
        # The contract fields the dispatcher reads.
        for field in ("name", "state", "exit", "cwd", "started", "ended", "duration_s", "pid",
                      "backend", "session_id", "answer_chars", "events_bytes",
                      "events_bytes_total", "events_truncated", "events_dropped_bytes"):
            self.assertIn(field, state)
        run_dir = self.run_dir(slug)
        answer = (run_dir / "answer.md").read_text(encoding="utf-8")
        self.assertEqual(answer, "STUB ANSWER: stage complete.")
        self.assertEqual(state["answer_chars"], len(answer))
        self.assertEqual(state["answer_source"], "final")
        for name in ("prompt.md", "state.json", "lock", "events.ndjson", "events.stats.json",
                     "stderr.log", "runner.log", "exit.code", "session.id", "answer.md",
                     "finalized", "run.json"):
            self.assertTrue((run_dir / name).exists(), f"missing artifact {name}")
        # The identity of each process, recorded at spawn: what a later signal is
        # verified against, so a reused pid can never be signalled.
        lock = json.loads((run_dir / "lock").read_text(encoding="utf-8"))
        self.assertTrue(lock.get("pid_identity"), lock)
        self.assertTrue(lock.get("agent_pid_identity"), lock)
        self.assertEqual(lock["pid_identity"], state["pid_identity"])
        self.assertEqual(lock["agent_pid_identity"], state["agent_pid_identity"])
        self.assertTrue((run_dir / ("run.cmd" if IS_WINDOWS else "run.sh")).exists())
        self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "0")
        self.assertEqual((run_dir / "exit.code").read_text(encoding="utf-8").strip(), "0")
        # The committed terminal record: the one authority for "finished", written
        # last by an atomic replacement, carrying everything a reader needs without
        # re-reading the event stream.
        record = adapter.terminal_snapshot_locked(state)
        self.assertIsNotNone(record, state)
        self.assertEqual(
            set(record), {"version", "generation", "commit_id", "answer", "session_id", "exit"}
        )
        self.assertEqual(record["version"], adapter.TERMINAL_RECORD_VERSION)
        self.assertEqual(record["generation"], state["generation"])
        self.assertTrue(state["generation"])
        self.assertTrue(record["commit_id"])
        self.assertEqual(record["exit"], 0)
        self.assertEqual(record["session_id"], "session-stub-0001")
        self.assertEqual(record["answer"], "STUB ANSWER: stage complete.")
        with tempfile.TemporaryDirectory() as bare:
            self.assertIsNone(adapter.terminal_commit(bare))
            self.assertIsNone(adapter.terminal_snapshot_locked({"state": "done", "exit": 0}))
        self.assertEqual((run_dir / "prompt.md").read_text(encoding="utf-8"), "do the thing\n")
        self.assertEqual((run_dir / "session.id").read_text(encoding="utf-8").strip(),
                         "session-stub-0001")
        events = [json.loads(line) for line in
                  (run_dir / "events.ndjson").read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(events[0]["type"], "session")
        self.assertEqual(events[0]["sessionId"], "session-stub-0001")
        # The stub reported the directory it was actually started in: the run's cwd
        # (realpath: a temp dir can sit behind a symlink, as on macOS).
        self.assertEqual(os.path.realpath(events[0]["cwd"]), os.path.realpath(str(self.tmp)))
        self.assertEqual(events[-1]["type"], "final")
        self.assertEqual(state["events_bytes"], (run_dir / "events.ndjson").stat().st_size)
        self.assertEqual(state["events_bytes_total"], state["events_bytes"])
        replay = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(replay["argv"][1], str(ADAPTER))
        self.assertIn("_run", replay["argv"])
        agent_argv = replay["agent_argv"]
        self.assertEqual(agent_argv[agent_argv.index("--profile") + 1], "headless")
        self.assertIn("--json", agent_argv)
        # Windows resolves the `.cmd` shim, and its case is not guaranteed.
        self.assertEqual(os.path.normcase(replay["agent"]),
                         os.path.normcase(str(self.dsh_bin())))
        self.assertEqual(replay["cwd"], str(self.tmp))
        script = (run_dir / ("run.cmd" if IS_WINDOWS else "run.sh")).read_text(encoding="utf-8")
        self.assertIn("_run", script)
        self.assertIn(str(run_dir), script)
        self.assertIn(str(ADAPTER), script)
        if not IS_WINDOWS:
            self.assertTrue(script.startswith("#!/usr/bin/env bash"))
            self.assertIn("exec ", script)
            self.assertTrue(os.access(run_dir / "run.sh", os.X_OK))
        # And the read-only views agree with the finalized state.
        view, _ = self.status_view(slug)
        self.assertEqual(view["state"], "done")
        self.assertFalse(view["alive"])
        self.assertEqual(view["backend"], "dsh")
        result = self.adapter_run("result", slug)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--- answer (first 1500 chars) ---", result.stdout)
        self.assertIn("STUB ANSWER: stage complete.", result.stdout)
        answer_only = self.adapter_run("answer", slug)
        self.assertEqual(answer_only.returncode, 0, answer_only.stderr)
        self.assertEqual(answer_only.stdout, "STUB ANSWER: stage complete.")

    def test_02_answer_comes_from_the_final_event(self):
        slug = "answer-02"
        state = self.settle(slug, STUB_TEXT="final report")
        self.assertEqual(state["state"], "done")
        self.assertEqual((self.run_dir(slug) / "answer.md").read_text(encoding="utf-8"),
                         "final report")
        self.assertEqual(state["answer_source"], "final")

    def test_03_live_run_reports_running_then_settles(self):
        slug = "live-03"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        live = self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        self.assertEqual(live["state"], "running")
        self.assertTrue(live["pid"])
        self.assertTrue(live["agent_pid"])
        self.assertTrue(live["detach"]["session_leader"] or IS_WINDOWS)
        # `status` on a run that is still working: it is alive, and the counters
        # the runner publishes grow while the agent works.
        view, _ = self.status_view(slug)
        self.assertEqual(view["state"], "running")
        self.assertTrue(view["alive"], view)
        self.assertEqual(view["pid"], live["pid"])
        self.assertEqual(view["agent_pid"], live["agent_pid"])
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline and not view["turns"]:
            time.sleep(adapter.POLL_SECONDS)
            view, _ = self.status_view(slug)
        self.assertGreaterEqual(view["turns"], 1, view)
        self.adapter_run("kill", slug)
        killed = self.wait_for_state(slug, {"killed"}, timeout=30.0)
        self.assertEqual(killed["exit"], 143)
        self.assertFalse(adapter.run_alive(str(self.run_dir(slug)), killed))
        # And a run that completes on its own settles to `done` with its counters.
        settled = self.settle("live-03b", STUB_TEXT="the settled answer")
        self.assertEqual(settled["state"], "done")
        self.assertEqual(settled["turns"], 1)
        self.assertEqual(settled["tool_calls"], 1)

    def test_04_exit_codes_map_to_states(self):
        cases = ((0, "done"), (3, "failed"), (130, "killed"), (137, "killed"), (143, "killed"))
        for index, (code, expected) in enumerate(cases):
            with self.subTest(exit=code):
                slug = f"exit-04-{index}"
                state = self.settle(slug, STUB_EXIT=code)
                self.assertEqual(state["state"], expected, state)
                self.assertEqual(state["exit"], code)
                self.assertEqual(
                    (self.run_dir(slug) / "finalized").read_text(encoding="utf-8"), str(code)
                )

    def test_05_completion_requires_the_final_reason(self):
        """Exit 0 alone is not completion: the last final event must say completed."""
        slug = "reason-05"
        state = self.settle(slug, STUB_REASON="aborted", STUB_EXIT=0)
        self.assertEqual(state["state"], "failed", state)
        self.assertEqual(state["exit"], 0)
        self.assertEqual(state["final_reason"], "aborted")
        self.assertTrue((self.run_dir(slug) / "answer.md").read_text(encoding="utf-8"))
        # A runner-level error has no final event at all, and keeps its own exit code.
        failed = self.settle("reason-05b", STUB_MODE="error")
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["exit"], 1)
        self.assertIsNone(failed["final_reason"])
        self.assertIn("MISSING_CREDENTIAL", failed["error"])

    @unittest.skipIf(IS_WINDOWS, "raw negative signal return codes are POSIX-only")
    def test_06_posix_sigterm_records_killed_with_raw_exit(self):
        slug = "sigterm-06"
        state = self.settle(slug, STUB_MODE="signal", STUB_SIGNAL="SIGTERM")
        self.assertEqual((state["state"], state["exit"]), ("killed", -15), state)
        self.assertEqual((self.run_dir(slug) / "exit.code").read_text(encoding="utf-8").strip(),
                         "-15")

    def test_07_stale_recovery_finalizes_once(self):
        slug = "stale-07"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        run_dir = self.run_dir(slug)
        # Wait until the run has committed something observable. The stub emits its
        # partial text before its first tool_call, so seeing the call counted means
        # that text is already in the log; killing first would make the partial
        # answer this test asserts on a race.
        deadline = time.monotonic() + START_TIMEOUT
        live = {}
        while time.monotonic() < deadline:
            live = self.state_of(slug)
            if live.get("tool_calls"):
                break
            time.sleep(adapter.POLL_SECONDS)
        self.assertEqual(live.get("tool_calls"), 1, live)
        # Kill the runner and dsh out from under the run: no finalizer left.
        self.kill_hard(run_dir)
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and adapter.run_alive(str(run_dir)):
            time.sleep(adapter.POLL_SECONDS)
        self.assertFalse(adapter.run_alive(str(run_dir)))
        self.assertFalse((run_dir / "finalized").exists())
        self.assertEqual(self.state_of(slug)["state"], "running")
        view, output = self.status_view(slug)
        self.assertEqual(view["state"], "failed")
        self.assertIn("stale_recovered: true", output)
        failed = self.state_of(slug)
        # No exit code was ever observed, so -1 is the only honest record.
        self.assertEqual(failed["exit"], -1)
        self.assertTrue(failed["stale_recovered"])
        self.assertIn("disappeared without finalizing", failed["note"])
        self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "-1")
        # The last committed assistant text survives as the partial answer.
        self.assertEqual((run_dir / "answer.md").read_text(encoding="utf-8"), "half a report")
        self.assertEqual(failed["answer_source"], "text")
        before = (run_dir / "state.json").read_bytes()
        second = self.adapter_run("status", slug)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("stale_recovered: true", second.stdout)
        self.assertEqual(before, (run_dir / "state.json").read_bytes())
        listed = self.adapter_run("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        line = [row for row in listed.stdout.splitlines() if slug in row][0]
        self.assertIn("failed(stale)", line)

    def test_08_kill_stops_a_live_run_through_the_stop_file(self):
        slug = "kill-08"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        live = self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        run_dir = self.run_dir(slug)
        pids = adapter.recorded_pids(str(run_dir))
        self.assertTrue(pids)
        killed = self.adapter_run("kill", slug)
        self.assertEqual(killed.returncode, 0, killed.stderr)
        self.assertIn(f"killed: {slug}", killed.stdout)
        state = self.wait_for_state(slug, {"killed"}, timeout=30.0)
        self.assertEqual(state["exit"], 143)
        # The control file is the request; the run's OWN finalizer recorded the stop
        # (a forced stop by the reader would carry a different marker).
        self.assertTrue((run_dir / "stop").exists())
        stop = json.loads((run_dir / "stop").read_text(encoding="utf-8"))
        self.assertIn("requested_at", stop)
        self.assertEqual(state.get("stopped_by"), "control-file")
        self.assertIn("observed the stop control file", state["note"])
        self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "143")
        self.assertEqual((run_dir / "exit.code").read_text(encoding="utf-8").strip(), "143")
        self.wait_for_pids_gone(pids)
        again = self.adapter_run("kill", slug)
        self.assertEqual(again.returncode, 1)
        self.assertIn("already finished", again.stderr)
        missing = self.adapter_run("kill", "no-such-run")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no run", missing.stderr)

    def test_09_kill_escalates_when_nothing_observes_the_control_file(self):
        """A live process tree with no runner is stopped by the escalation.

        On POSIX the tree ignores TERM — its readiness is acknowledged only after
        the handlers are installed — and it holds a child in its own process
        group, so neither a plain TERM nor a signal to the leader alone could stop
        it: only the TERM->KILL escalation behind `kill` can.
        """
        slug = "kill-forced-09"
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True)
        (run_dir / "prompt.md").write_text("dispatched, runner lost\n", encoding="utf-8")
        (run_dir / "events.ndjson").write_text("", encoding="utf-8")
        (run_dir / "state.json").write_text(
            json.dumps({"name": slug, "state": "running", "exit": None, "cwd": str(self.tmp),
                        "started": adapter.now_iso(), "backend": "dsh",
                        "generation": adapter.new_nonce()}),
            encoding="utf-8",
        )
        leader, child_pid = self.group_with_ready_member()
        pid = leader.pid
        try:
            # The identity a real run records at spawn: without it the adapter
            # refuses to signal, so the escalation this test exercises needs it.
            leader_identity = adapter.process_identity(pid)
            self.assertTrue(leader_identity, "the platform must supply a process identity")
            generation = adapter.new_nonce()
            state = adapter.read_state_file(str(run_dir))
            state["generation"] = generation
            adapter.write_json(str(run_dir / "state.json"), state)
            (run_dir / "lock").write_text(
                json.dumps({"pid": pid, "agent_pid": None, "pid_identity": leader_identity,
                            "backend": "dsh", "started_at": adapter.now_iso(),
                            "generation": generation}),
                encoding="utf-8",
            )
            if not IS_WINDOWS:
                # Proof the escalation is real and reaches the group: a plain TERM
                # to the group leaves both processes running. Wait up to a bounded
                # time for a death that must not happen, rather than sleeping a
                # fixed length and hoping it was enough.
                adapter.signal_group(pid, signal.SIGTERM, leader_identity)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and adapter.pid_alive(pid):
                    time.sleep(adapter.POLL_SECONDS)
                self.assertTrue(adapter.pid_alive(pid), "the leader should ignore SIGTERM")
                self.assertTrue(adapter.pid_alive(child_pid), "the child should ignore SIGTERM")
            killed = self.adapter_run("kill", slug, env=self.env_for(DSH_RUN_STOP_WAIT_SECONDS=1))
            self.assertEqual(killed.returncode, 0, killed.stderr)
            state = self.state_of(slug)
            self.assertEqual((state["state"], state["exit"]), ("killed", 143), state)
            self.assertEqual(state.get("stopped_by"), "control-file-forced")
            self.assertIn("did not complete after the stop request", state["note"])
            self.wait_for_pids_gone([pid, child_pid])
        finally:
            self.reap_pids([pid, child_pid])

    def test_10_event_bound_reports_dropped_bytes(self):
        slug = "flood-10"
        cap = 200000
        state = self.settle(slug, STUB_MODE="flood", DSH_RUN_EVENTS_MAX_BYTES=cap)
        self.assertEqual(state["state"], "done")
        self.assertGreater(state["events_dropped_bytes"], 0, state)
        self.assertTrue(state["events_truncated"])
        self.assertTrue(state["tool_calls_partial"])
        self.assertTrue(state["turns_partial"])
        self.assertTrue(state["usage_partial"])
        self.assertGreater(state["events_bytes_total"], state["events_bytes"])
        run_dir = self.run_dir(slug)
        text = (run_dir / "events.ndjson").read_text(encoding="utf-8")
        self.assertIn('"type":"truncated"', text)
        stats = json.loads((run_dir / "events.stats.json").read_text(encoding="utf-8"))
        self.assertEqual(stats["dropped_bytes"], state["events_dropped_bytes"])
        self.assertEqual(stats["total_bytes"], state["events_bytes_total"])
        self.assertTrue(stats["truncated"])
        self.assertEqual(stats["max_bytes"], cap)
        # The retained file really stayed inside the configured bound: the cap
        # bounds the rolling tail, and the writer keeps at most its documented head
        # region beside it, so head_bytes + cap is the upper bound it promises.
        self.assertEqual(stats["head_limit_bytes"], 64 * 1024)
        self.assertLessEqual(state["events_bytes"], stats["head_bytes"] + cap, state)
        self.assertLessEqual(state["events_bytes"], cap + 64 * 1024, state)
        self.assertEqual(state["events_bytes"], (run_dir / "events.ndjson").stat().st_size)
        # The tail of the stream survives the bound: the final answer is still last.
        last = [json.loads(line) for line in text.splitlines() if line.strip()][-1]
        self.assertEqual(last["type"], "final")
        self.assertEqual(last["text"], "flooded")
        self.assertEqual((run_dir / "answer.md").read_text(encoding="utf-8"), "flooded")
        view, _ = self.status_view(slug)
        self.assertEqual(view["events_dropped_bytes"], state["events_dropped_bytes"])
        self.assertTrue(view["events_truncated"])

    def test_11_agent_arguments_and_prompt_are_passed_through(self):
        slug = "argv-11"
        argv_file = self.tmp / "argv-11.json"
        stdin_file = self.tmp / "argv-11-stdin.txt"
        state = self.settle(
            slug,
            STUB_ARGV_FILE=argv_file,
            STUB_STDIN_FILE=stdin_file,
            STUB_SESSION="session-adopted-7",
        )
        self.assertEqual(state["state"], "done")
        argv = json.loads(argv_file.read_text(encoding="utf-8"))
        # Launcher flags come first, then the app's own flags, then the stdin marker.
        self.assertEqual(argv[0:2], ["--profile", "headless"])
        self.assertLess(argv.index("--profile"), argv.index("--json"))
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "workspace-write")
        self.assertEqual(argv[argv.index("--approval-policy") + 1], "never")
        self.assertEqual(argv[-1], "-")
        self.assertNotIn("--max-time", argv)  # not a DSH flag: it is the adapter's deadline
        self.assertNotIn("--model", argv)
        # The prompt travelled verbatim on stdin, trailing newline included.
        self.assertEqual(stdin_file.read_text(encoding="utf-8"), "do the thing\n")
        self.assertEqual(state["session_id"], "session-adopted-7")
        replay = json.loads((self.run_dir(slug) / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(replay["agent_argv"][-1], "-")
        self.assertNotIn("--session-id", replay["agent_argv"])  # a fresh session
        # --session-id adopts a persisted session, and is repeated on resume.
        explicit = self.start(
            "argv-11c", "--session-id", "session-explicit-9",
            # An adopted session reports the id it was given, so the stub does too.
            env=self.env_for(STUB_SESSION="session-explicit-9"),
        )
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertEqual(self.wait_for_state("argv-11c", {"done"})["session_id"],
                         "session-explicit-9")
        recorded = json.loads(
            (self.run_dir("argv-11c") / "run.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            recorded["agent_argv"][recorded["agent_argv"].index("--session-id") + 1],
            "session-explicit-9",
        )
        self.assertEqual(
            recorded["argv"][recorded["argv"].index("--session-id") + 1], "session-explicit-9"
        )
        resumed = self.start(
            "argv-11d", "--resume", "session-resumed-11",
            env=self.env_for(STUB_SESSION="session-resumed-11"),
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        state_d = self.wait_for_state("argv-11d", {"done"})
        self.assertEqual(state_d["session_id"], "session-resumed-11")
        self.assertEqual(state_d["resumed_from"], "session-resumed-11")
        recorded = json.loads(
            (self.run_dir("argv-11d") / "run.json").read_text(encoding="utf-8")
        )
        self.assertEqual(recorded["agent_argv"][recorded["agent_argv"].index("--session-id") + 1],
                         "session-resumed-11")
        self.assertEqual(
            recorded["argv"][recorded["argv"].index("--resume") + 1], "session-resumed-11"
        )
        disagree = self.adapter_run(
            "start", "--name", "argv-11e", "--prompt", str(self.prompt), "--cwd", str(self.tmp),
            "--session-id", "one", "--resume", "two",
        )
        self.assertEqual(disagree.returncode, 1)
        self.assertIn("disagree", disagree.stderr)

    def test_12_second_start_is_refused_and_replace_restarts(self):
        slug = "second-12"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        first_pid = self.state_of(slug)["pid"]
        again = self.adapter_run(
            "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp),
            env=self.env_for(STUB_MODE="sleep"),
        )
        self.assertEqual(again.returncode, 1)
        self.assertIn("still running", again.stderr)
        self.assertEqual(self.state_of(slug)["pid"], first_pid)
        self.adapter_run("kill", slug)
        self.wait_for_state(slug, {"killed"}, timeout=30.0)
        # A finished slug starts fresh: the old directory is preserved, not mixed.
        replaced = self.start(slug, env=self.env_for(STUB_TEXT="the second run"))
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        state = self.wait_for_state(slug, {"done"})
        self.assertEqual(state["answer_chars"], len("the second run"))
        previous = sorted(self.run_dir(slug).parent.glob(f"{slug}.prev-*"))
        self.assertEqual(len(previous), 1, previous)
        self.assertTrue((previous[0] / "finalized").exists())
        self.assertEqual(
            json.loads((previous[0] / "state.json").read_text(encoding="utf-8"))["state"], "killed"
        )
        self.assertNotEqual(state["pid"], first_pid)

    def test_12b_replace_stops_a_live_run_before_restarting_it(self):
        slug = "replace-12b"
        self.start(slug, env=self.env_for(STUB_MODE="sleep", STUB_SESSION="session-first"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        first_pids = adapter.recorded_pids(str(self.run_dir(slug)))
        self.assertTrue(first_pids)
        replaced = self.start(
            slug, "--replace", env=self.env_for(STUB_TEXT="replaced", STUB_SESSION="session-second")
        )
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        state = self.wait_for_state(slug, {"done"})
        self.assertEqual(state["session_id"], "session-second")
        previous = sorted(self.run_dir(slug).parent.glob(f"{slug}.prev-*"))
        self.assertEqual(len(previous), 1, previous)
        # The replaced run was stopped, not left running in the archive.
        archived = json.loads((previous[0] / "state.json").read_text(encoding="utf-8"))
        self.assertEqual((archived["state"], archived["exit"]), ("killed", 143), archived)
        self.wait_for_pids_gone(first_pids)

    def hold_mutex_for(self, lock_path, seconds):
        """A child process that holds one lock object for `seconds`, then releases it.

        Readiness is the child's own acknowledgement after it holds the lock, so the
        caller knows a real hold exists before it acts; the child exits (and the
        kernel releases the lock) when the delay is over.
        """
        code = (
            "import importlib.util, sys, time\n"
            "spec = importlib.util.spec_from_file_location('holder', sys.argv[1])\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "with mod.stable_lock(sys.argv[2], None) as held:\n"
            "    sys.stdout.write('held\\n' if held else 'refused\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(float(sys.argv[3]))\n"
        )
        process = self.spawn(
            [sys.executable, "-c", code, str(ADAPTER), str(lock_path), str(seconds)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.assertEqual(self.read_line(process), "held")
        return process

    def test_12c_a_momentary_mutation_never_fails_a_start_or_a_stop(self):
        """L3/M: a momentary hold of M must not fail a replacement or a stop.

        A live run's own runner holds M for a moment per publication. A `start
        --replace` that read the first refusal as a verdict would fail against the
        very run it is about to stop, and a `kill` would report a stop it never
        issued. A child process holds M for 1.5 s; both commands must wait it out
        and succeed.
        """
        slug = "momentary-12c"
        self.start(slug, env=self.env_for(STUB_MODE="sleep", STUB_SESSION="session-12c-first"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        run_dir = self.run_dir(slug)
        lock_path = adapter.lifecycle_lock_path(adapter.bucket_root(str(run_dir)), slug)
        holder = self.hold_mutex_for(lock_path, 1.5)
        replaced = self.start(
            slug, "--replace", env=self.env_for(STUB_TEXT="replaced", STUB_SESSION="session-12c-second"),
            assert_started=False,
        )
        self.assertEqual(replaced.returncode, 0, f"start --replace failed: {replaced.stderr}")
        self.wait_for_state(slug, {"done"}, timeout=START_TIMEOUT)
        self.reap(holder)
        # And a stop issued while M is momentarily held is issued, not refused.
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        holder = self.hold_mutex_for(lock_path, 1.5)
        killed = self.adapter_run("kill", slug)
        self.reap(holder)
        self.assertEqual(killed.returncode, 0, f"kill failed: {killed.stderr}")
        self.assertEqual(self.wait_for_state(slug, {"killed"})["exit"], adapter.KILL_EXIT)

    def test_13_missing_state_is_unknown_never_success(self):
        slug = "unknown-13"
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True)
        (run_dir / "prompt.md").write_text("no state was ever written\n", encoding="utf-8")
        view, _ = self.status_view(slug)
        self.assertEqual(view["state"], "unknown")
        self.assertFalse((run_dir / "finalized").exists())
        result = self.adapter_run("result", slug)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"state": "unknown"', result.stdout)
        answer = self.adapter_run("answer", slug)
        self.assertEqual(answer.returncode, 1)
        self.assertIn("not finished yet", answer.stderr)

    def test_14_start_refusals(self):
        slug = "refuse-14"
        missing = self.start(slug, assert_started=False, env=self.env_for(DSH_BIN="dsh-missing"))
        self.assertEqual(missing.returncode, 1)
        self.assertIn("dsh binary not found", missing.stderr)
        self.assertFalse(self.run_dir(slug).exists())
        bad_cwd = self.adapter_run(
            "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp / "nope")
        )
        self.assertEqual(bad_cwd.returncode, 1)
        self.assertIn("is not a directory", bad_cwd.stderr)
        no_prompt = self.adapter_run(
            "start", "--name", slug, "--prompt", str(self.tmp / "nope.md"), "--cwd", str(self.tmp)
        )
        self.assertEqual(no_prompt.returncode, 1)
        self.assertIn("--prompt FILE is required", no_prompt.stderr)
        # The headless app has no model or thinking flag, so a selection this route
        # cannot honour is refused rather than silently dropped.
        for flag, value in (("--model", "some-model"), ("--thinking", "high")):
            with self.subTest(flag=flag):
                proc = self.adapter_run(
                    "start", "--name", slug, "--prompt", str(self.prompt),
                    "--cwd", str(self.tmp), flag, value,
                )
                self.assertEqual(proc.returncode, 1)
                self.assertIn("is not supported on the DSH route", proc.stderr)
        bad_time = self.adapter_run(
            "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp),
            "--max-time", "soon",
        )
        self.assertEqual(bad_time.returncode, 1)
        self.assertIn("--max-time must be a positive number of seconds", bad_time.stderr)
        self.assertFalse(self.run_dir(slug).exists())
        # A name that sanitizes to nothing is refused, and refuses before it can
        # claim or create a run directory (the date directory would be the target,
        # so an untouched fresh root is the proof).
        bogus_root = self.tmp / "refuse-14-bogus"
        bogus = self.adapter_run(
            "start", "--name", "---", "--prompt", str(self.prompt), "--cwd", str(self.tmp),
            env=self.env_for(DSH_RUN_ROOT=bogus_root),
        )
        self.assertEqual(bogus.returncode, 1)
        self.assertIn("must not sanitize to nothing", bogus.stderr)
        self.assertFalse(bogus_root.exists())
        # And the same sanitized-to-nothing name cannot address a run either: past
        # the parser (`--`) it is a lookup that finds nothing, never a match.
        for command in ("status", "result", "answer", "tail", "kill"):
            with self.subTest(command=command):
                proc = self.adapter_run(command, "--", "---")
                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertIn(f"{command}: no run '---'", proc.stderr)
        # The bare option-like spelling does not even reach the lookup: the parser
        # refuses it outright, so it can never be folded into a slug.
        for command in ("status", "result", "answer", "tail", "kill"):
            with self.subTest(command=command, spelling="bare"):
                proc = self.adapter_run(command, "---")
                self.assertNotEqual(proc.returncode, 0, proc.stdout)
                self.assertFalse(self.run_dir("---").exists())

    def test_15_max_time_is_the_adapters_own_deadline(self):
        slug = "deadline-15"
        proc = self.start(slug, "--max-time", "1", env=self.env_for(STUB_MODE="sleep"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state = self.wait_for_state(slug, {"killed"}, timeout=SETTLE_TIMEOUT)
        self.assertEqual(state["exit"], 143)
        self.assertTrue(state["deadline_exceeded"])
        self.assertEqual(state["stopped_by"], "deadline")
        self.assertIn("--max-time 1", state["note"])
        self.assertEqual((self.run_dir(slug) / "finalized").read_text(encoding="utf-8"), "143")

    def test_16_start_reports_a_run_that_died_before_the_agent_started(self):
        """A terminal startup failure is not a successful dispatch."""
        slug = "startup-16"
        broken = self.bin / "dsh-unspawnable"
        if IS_WINDOWS:
            broken = self.bin / "dsh-unspawnable.exe"
        broken.write_text(f"#!{self.tmp / 'missing-interpreter'}\n", encoding="utf-8")
        broken.chmod(0o755)
        proc = self.start(slug, assert_started=False, env=self.env_for(DSH_BIN=broken))
        self.assertNotIn("started:", proc.stdout)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("did not start", proc.stderr)
        state = self.wait_for_state(slug, {"failed"})
        self.assertEqual(state["exit"], 127)
        self.assertIn("agent did not start", state["note"])

    def test_17_list_and_tail(self):
        empty_root = self.tmp / "empty-runs"
        listed = self.adapter_run("list", env=self.env_for(DSH_RUN_ROOT=empty_root))
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("(no runs recorded)", listed.stdout)
        self.settle("list-17", STUB_TEXT="listed answer")
        listed = self.adapter_run("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        line = [row for row in listed.stdout.splitlines() if "list-17" in row][0]
        self.assertIn("done exit=0", line)
        self.assertIn("turns=1 tools=1", line)
        tail = self.adapter_run("tail", "list-17", "2")
        self.assertEqual(tail.returncode, 0, tail.stderr)
        lines = [line for line in tail.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[-1])["type"], "final")
        self.assertEqual(self.adapter_run("tail", "list-17").returncode, 0)
        self.assertEqual(self.adapter_run("tail", "no-such-run").returncode, 1)
        self.assertEqual(self.adapter_run("status", "no-such-run").returncode, 1)
        # A bare `status` has no slug and is the listing, not an error.
        bare = self.adapter_run("status", env=self.env_for(DSH_RUN_ROOT=empty_root))
        self.assertEqual(bare.returncode, 0, bare.stderr)
        self.assertIn("(no runs recorded)", bare.stdout)
        bare = self.adapter_run("status")
        self.assertEqual(bare.returncode, 0, bare.stderr)
        self.assertIn("list-17", bare.stdout)
        self.assertIn("done exit=0", bare.stdout)

    def test_18_detachment_is_measured_not_asserted(self):
        slug = "detach-18"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        live = self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        try:
            spawn = live["spawn"]
            detach = live["detach"]
            self.assertEqual(spawn["creationflags"], adapter.detach_flags())
            if IS_WINDOWS:
                self.assertEqual(spawn["mode"], "hidden-console")
                self.assertTrue(detach["console"], detach)
            else:
                self.assertEqual(spawn["mode"], "new-session")
                self.assertEqual(spawn["creationflags"], 0)
                self.assertEqual(detach["mode"], "new-session")
                self.assertTrue(detach["session_leader"], detach)
                self.assertTrue(detach["process_group_leader"], detach)
                self.assertFalse(detach["controlling_terminal"], detach)
                runner = live["pid"]
                self.assertEqual(os.getsid(runner), runner)
        finally:
            self.adapter_run("kill", slug)
            self.wait_for_state(slug, {"killed"}, timeout=30.0)

    def test_19_a_killed_run_keeps_the_last_committed_text(self):
        slug = "partial-19"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        # The live counters are published while dsh works, not only at finalize.
        deadline = time.monotonic() + START_TIMEOUT
        live = {}
        while time.monotonic() < deadline:
            live = self.state_of(slug)
            if live.get("tool_calls"):
                break
            time.sleep(adapter.POLL_SECONDS)
        self.assertEqual(live.get("tool_calls"), 1, live)
        self.adapter_run("kill", slug)
        state = self.wait_for_state(slug, {"killed"}, timeout=30.0)
        self.assertIsNone(state["final_reason"])
        self.assertEqual(state["answer_source"], "text")
        self.assertEqual((self.run_dir(slug) / "answer.md").read_text(encoding="utf-8"),
                         "half a report")


    def test_20_a_completed_replay_initializes_a_fresh_run(self):
        """The recorded run.sh replays the invocation; the old artifacts survive."""
        slug = "replay-20"
        argv_file = self.tmp / "replay-20.json"
        replay_argv_file = self.tmp / "replay-20-replay.json"
        replay_env_file = self.tmp / "replay-20-env.json"
        first = self.settle(
            slug, STUB_ARGV_FILE=argv_file, STUB_TEXT="the original answer",
            STUB_SESSION="original-session",
        )
        self.assertEqual(first["state"], "done")
        run_dir = self.run_dir(slug)
        original = (run_dir / "answer.md").read_text(encoding="utf-8")
        # The stub recorded the arguments it was given and the cwd it ran in.
        original_argv = json.loads(argv_file.read_text(encoding="utf-8"))
        self.assertEqual(original_argv[0:2], ["--profile", "headless"])
        self.assertEqual(original_argv[-1], "-")
        self.assertEqual(first["cwd"], str(self.tmp))
        first_events = [json.loads(line) for line in
                        (run_dir / "events.ndjson").read_text(encoding="utf-8").splitlines()
                        if line.strip()]
        self.assertEqual(os.path.realpath(first_events[0]["cwd"]),
                         os.path.realpath(str(self.tmp)))
        script = run_dir / ("run.cmd" if IS_WINDOWS else "run.sh")
        command = (
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", str(script)]
            if IS_WINDOWS else ["bash", str(script)]
        )
        replay_env = self.env_for(
            STUB_TEXT="a different replay answer",
            STUB_SESSION="replay-session",
            STUB_ARGV_FILE=replay_argv_file,
            STUB_ENV_FILE=replay_env_file,
            DSH_BIN="must-not-resolve-this-agent",
            DSH_RUN_ROOT=str(self.tmp / "not-the-recorded-root"),
            # The recorded argv decides the profile, and the `_run` entry point
            # drops the caller's harness identity just like `start` does.
            DSH_RUN_PROFILE="must-not-decide-the-replay",
            DSH_PROFILE="interactive",
            DSH_PROFILE_DIR="/somewhere",
            DSH_SESSION_ID="session-x",
        )
        replay = subprocess.run(
            command, cwd=str(self.bin), env=replay_env, capture_output=True, text=True,
            timeout=SETTLE_TIMEOUT,
        )
        self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
        state = self.wait_for_state(slug, {"done"})
        self.assertEqual(state["session_id"], "replay-session")
        self.assertEqual(state["profile"], "headless")
        self.assertEqual(state["cwd"], str(self.tmp))
        self.assertEqual((run_dir / "answer.md").read_text(encoding="utf-8"),
                         "a different replay answer")
        self.assertEqual((run_dir / "events.ndjson").read_text(encoding="utf-8").count('"final"'), 1)
        replay_argv = json.loads(replay_argv_file.read_text(encoding="utf-8"))
        self.assertEqual(replay_argv[0:2], ["--profile", "headless"])
        self.assertEqual(replay_argv[-1], "-")
        replay_events = [json.loads(line) for line in
                         (run_dir / "events.ndjson").read_text(encoding="utf-8").splitlines()
                         if line.strip()]
        self.assertEqual(os.path.realpath(replay_events[0]["cwd"]),
                         os.path.realpath(str(self.tmp)))
        observed = json.loads(replay_env_file.read_text(encoding="utf-8"))
        for name in ("DSH_PROFILE", "DSH_PROFILE_DIR", "DSH_SESSION_ID"):
            self.assertNotIn(name, observed["present"], observed)
        previous = sorted(run_dir.parent.glob(f"{slug}.prev-*"))
        self.assertEqual(len(previous), 1, previous)
        self.assertEqual((previous[0] / "answer.md").read_text(encoding="utf-8"), original)
        self.assertEqual((previous[0] / "finalized").read_text(encoding="utf-8"), "0")


    def test_21_stale_recovery_is_triggered_by_result_list_and_answer(self):
        """Done-when #4: every reader of a dead unfinalized run finalizes it once."""
        for command in ("result", "list", "answer"):
            with self.subTest(command=command):
                slug = f"recover-21-{command}"
                run_dir = self.dead_run(slug)
                if command == "answer":
                    proc = self.adapter_run("answer", slug)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    # `answer` prints the answer and nothing else: the recovery is
                    # recorded in state.json, never mixed into the answer text.
                    self.assertEqual(proc.stdout, "half a report")
                elif command == "list":
                    proc = self.adapter_run("list")
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    line = [row for row in proc.stdout.splitlines() if slug in row][0]
                    self.assertIn("GONE (resume with --session-id session-dead)", line)
                else:
                    proc = self.adapter_run("result", slug)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertIn("stale_recovered: true", proc.stdout)
                    self.assertIn("half a report", proc.stdout)
                state = self.state_of(slug)
                self.assertTrue(state["stale_recovered"], state)
                self.assertEqual((state["state"], state["exit"]), ("failed", -1), state)
                self.assertEqual(state["session_id"], "session-dead")
                self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "-1")
                self.assertEqual((run_dir / "answer.md").read_text(encoding="utf-8"),
                                 "half a report")
                # The marker is the guard: every other reader sees a settled run.
                before = (run_dir / "state.json").read_bytes()
                for reader, target in (("status", [slug]), ("result", [slug]),
                                       ("answer", [slug]), ("list", [])):
                    with self.subTest(command=command, reader=reader):
                        again = self.adapter_run(reader, *target)
                        self.assertEqual(again.returncode, 0, again.stderr)
                        if reader in ("status", "result"):
                            self.assertNotIn("stale_recovered: true", again.stdout)
                self.assertEqual(before, (run_dir / "state.json").read_bytes())

    def test_22_a_multi_final_stream_is_decided_by_its_last_final(self):
        """Completion comes from the last `final` event, never from an earlier one."""
        cases = (
            (["completed", "aborted"], "failed", "aborted"),
            (["completed", None], "failed", None),
            (["aborted", "completed"], "done", "completed"),
        )
        for index, (kinds, expected_state, expected_reason) in enumerate(cases):
            with self.subTest(finals=kinds):
                slug = f"finals-22-{index}"
                state = self.settle(slug, STUB_FINALS=json.dumps(kinds), STUB_TEXT="the answer")
                self.assertEqual(state["state"], expected_state, state)
                self.assertEqual(state["final_reason"], expected_reason, state)
                self.assertEqual(state["exit"], 0)
                self.assertEqual(state["answer_source"], "final")
                # The answer is the last final's too, not the first one's.
                last = f"the answer (final {len(kinds)}: {kinds[-1]})"
                self.assertEqual((self.run_dir(slug) / "answer.md").read_text(encoding="utf-8"),
                                 last)
                self.assertEqual(state["answer_chars"], len(last))

    def test_23_harness_identity_does_not_leak_into_the_worker(self):
        """DSH_PROFILE/DSH_PROFILE_DIR/DSH_SESSION_ID belong to the caller's dsh.

        A stage dispatched from inside a live `dsh` session inherits them, so the
        adapter's own key is DSH_RUN_PROFILE and no child it spawns may see the
        caller's identity: the profile it runs travels on argv.
        """
        slug = "env-23"
        probe = self.tmp / "env-23.json"
        state = self.settle(
            slug,
            DSH_PROFILE="interactive",
            DSH_PROFILE_DIR="/somewhere",
            DSH_SESSION_ID="session-x",
            STUB_ENV_FILE=probe,
        )
        self.assertEqual(state["state"], "done")
        self.assertEqual(state["profile"], "headless")
        replay = json.loads((self.run_dir(slug) / "run.json").read_text(encoding="utf-8"))
        argv = replay["agent_argv"]
        self.assertEqual(argv[argv.index("--profile") + 1], "headless")
        observed = json.loads(probe.read_text(encoding="utf-8"))
        for name in ("DSH_PROFILE", "DSH_PROFILE_DIR", "DSH_SESSION_ID"):
            self.assertNotIn(name, observed["present"], observed)
        # The adapter's own key selects the profile; the harness's key is not a
        # fallback for it.
        second = self.settle(
            "env-23b",
            DSH_RUN_PROFILE="interactive",
            DSH_PROFILE="headless",
            DSH_SESSION_ID="session-y",
            STUB_ENV_FILE=self.tmp / "env-23b.json",
        )
        self.assertEqual(second["profile"], "interactive")
        recorded = json.loads((self.run_dir("env-23b") / "run.json").read_text(encoding="utf-8"))
        argv_b = recorded["agent_argv"]
        self.assertEqual(argv_b[argv_b.index("--profile") + 1], "interactive")
        observed_b = json.loads((self.tmp / "env-23b.json").read_text(encoding="utf-8"))
        self.assertIn("DSH_RUN_PROFILE", observed_b["present"])
        self.assertEqual(observed_b["values"]["DSH_RUN_PROFILE"], "interactive")
        for name in ("DSH_PROFILE", "DSH_PROFILE_DIR", "DSH_SESSION_ID"):
            self.assertNotIn(name, observed_b["present"], observed_b)


    def test_24_the_run_dir_helper_uses_the_adapters_own_bucket(self):
        """A run directory is found where the adapter put it, not where a date says."""
        slug = "datedir-24"
        other = self.run_root / "2001-02-03" / slug
        other.mkdir(parents=True)
        (other / "prompt.md").write_text("an older bucket\n", encoding="utf-8")
        try:
            self.assertEqual(self.run_dir(slug), other)
            # Nothing recorded under any bucket: the adapter's own date helper decides.
            self.assertEqual(self.run_dir("never-started-24"),
                             self.run_root / adapter.date_stamp() / "never-started-24")
        finally:
            shutil.rmtree(other.parent, ignore_errors=True)

    def test_25_a_live_run_in_another_date_bucket_occupies_its_slug(self):
        """Midnight must not let the same slug start twice.

        The live run is filed under a date bucket that is not today's, so a check
        that only looks at today's directory would start a second run behind it.
        """
        slug = "crossdate-25"
        root = self.tmp / "crossdate-25-runs"
        old = root / "2001-02-03" / slug
        old.mkdir(parents=True)
        (old / "prompt.md").write_text("started before the date rolled over\n", encoding="utf-8")
        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            # The lock a real run leaves: the live pid (no identity is needed for
            # the occupancy check, which must not signal anything).
            adapter.write_json(str(old / "state.json"), {
                "name": slug, "state": "running", "exit": None, "cwd": str(self.tmp),
                "started": adapter.now_iso(), "backend": "dsh", "pid": sleeper.pid,
                "generation": adapter.new_nonce(),
            })
            adapter.write_json(str(old / "lock"), {
                "pid": sleeper.pid, "agent_pid": None, "backend": "dsh",
            })
            proc = self.start(slug, assert_started=False, env=self.env_for(DSH_RUN_ROOT=root))
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("still running", proc.stderr)
            self.assertFalse((root / adapter.date_stamp() / slug).exists())
        finally:
            sleeper.kill()
            sleeper.wait(timeout=10)
        # Once the old run is dead `start` recovers it instead of treating it as
        # an occupant, and the slug starts again in today's bucket.
        started = self.start(slug, env=self.env_for(DSH_RUN_ROOT=root))
        self.assertEqual(started.returncode, 0, started.stderr)
        today = root / adapter.date_stamp() / slug
        deadline = time.monotonic() + SETTLE_TIMEOUT
        state = {}
        while time.monotonic() < deadline:
            state = adapter.read_state_file(str(today))
            if (state.get("state") in TERMINAL_STATES and (today / "finalized").exists()
                    and not adapter.run_alive(str(today), state)):
                break
            time.sleep(adapter.POLL_SECONDS)
        self.assertEqual(state.get("state"), "done", state)
        self.assertTrue((old / "finalized").exists())
        self.assertTrue(adapter.read_state_file(str(old)).get("stale_recovered"))

    def test_26_a_non_never_approval_policy_is_refused(self):
        """A detached run has no approval channel, so only `never` is honoured."""
        slug = "policy-26"
        root = self.tmp / "policy-26-runs"
        proc = self.start(
            slug, assert_started=False,
            env=self.env_for(DSH_APPROVAL_POLICY="on-request", DSH_RUN_ROOT=root),
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("DSH_APPROVAL_POLICY", proc.stderr)
        self.assertIn("'never'", proc.stderr)
        self.assertNotIn("started:", proc.stdout)
        # Refused before a run directory exists: there is no run to clean up.
        self.assertFalse(root.exists())
        help_text = adapter.build_parser().format_help()
        self.assertIn("DSH_APPROVAL_POLICY is accepted only as `never`", help_text)
        # `never` itself still starts normally.
        self.assertEqual(self.settle("policy-26b", DSH_APPROVAL_POLICY="never")["state"], "done")

    def test_27_the_slug_claim_is_a_root_level_os_lock(self):
        """The claim that stops a double start lives in the run root, not a date bucket."""
        slug = "slugclaim-27"
        root = self.tmp / "slugclaim-27-runs"
        with adapter.slug_start_claim(str(root), slug) as claimed:
            self.assertTrue(claimed)
            self.assertTrue((root / f"{slug}.start.lock").exists())
            proc = self.start(slug, assert_started=False, env=self.env_for(DSH_RUN_ROOT=root))
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("another start is claiming", proc.stderr)
            self.assertFalse((root / adapter.date_stamp() / slug).exists())
        # Released with its holder: the same claim is available again.
        with adapter.slug_start_claim(str(root), slug) as again:
            self.assertTrue(again)

    def test_28_start_accepts_an_agent_that_spawned_and_died_immediately(self):
        """A fast-failing agent is the run's outcome, not a failed dispatch (E1).

        The runner is spawned exactly as `start` spawns it (the real detached
        process, with the generation-stamped credential the handshake names), and
        the assertion is on what `start` reports afterwards: it confirms the
        dispatch because the runner *recorded* the agent it spawned, even when
        that agent has already written its `error` event and exited. The stand-in
        also pins that the credential carries both halves of the handshake, so the
        runner could authenticate at all — a replay that carries none must not.
        """
        slug = "fastfail-28"
        args = adapter.build_parser().parse_args(
            ["start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp)]
        )
        env = self.env_for(STUB_MODE="error")
        seen = {}
        real_spawn = adapter.spawn_runner

        def spawn_like_start(argv, cwd, log_path):
            run_dir = Path(log_path).parent
            generation, token = adapter.spawn_credentials(
                adapter.operation_of(str(run_dir))
            )
            self.assertTrue(generation and token, "start must write a generation-stamped handshake")
            seen["credential"] = (generation, token)
            process = real_spawn(argv, cwd, log_path)
            self.addCleanup(self.reap, process)
            return process

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
            adapter, "spawn_runner", spawn_like_start
        ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = adapter.cmd_start(args)
        # The runner is a child of this process: reap it, or a zombie would keep
        # answering the liveness probe and the run would look live forever.
        reaper = self.reap_runner_async(self.run_root / adapter.date_stamp() / slug)
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn(f"started: {slug}", out.getvalue())
        state = self.wait_for_state(slug, {"failed"})
        reaper.join(timeout=30.0)
        self.assertTrue(state.get("agent_pid"), state)
        self.assertEqual(state["exit"], 1, state)
        self.assertEqual(state["final_reason"], None, state)
        self.assertIn("MISSING_CREDENTIAL", state["error"])
        run_dir = self.run_dir(slug)
        self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "1")
        # The handshake was consumed by that runner, and the credential named the
        # generation the run records.
        self.assertFalse((run_dir / adapter.SPAWN_TOKEN_FILE).exists())
        self.assertEqual(seen["credential"][0], state["generation"])

    def test_29_a_run_that_died_at_once_still_started(self):
        """The fast failure through the real detached CLI: `start` exits 0 (E1).

        No patching here: the detached runner spawns the stub, the stub emits its
        `error` event and exits immediately (as a real dsh does when the profile's
        provider has no credential), and the run finalizes `failed` with that
        error. `start` reports the dispatch — the recorded agent — so its exit
        code stays 0.
        """
        slug = "fastfail-29"
        proc = self.start(slug, env=self.env_for(STUB_MODE="error"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state = self.wait_for_state(slug, {"failed"})
        self.assertTrue(state.get("agent_pid"), state)
        self.assertEqual(state["exit"], 1, state)
        self.assertEqual(state["final_reason"], None, state)
        self.assertIn("MISSING_CREDENTIAL", state["error"])
        self.assertEqual((self.run_dir(slug) / "finalized").read_text(encoding="utf-8"), "1")
        view, _ = self.status_view(slug)
        self.assertEqual(view["state"], "failed", view)
        self.assertFalse(view["alive"], view)


    def test_30_a_special_slug_cannot_escape_its_date_bucket(self):
        """`.` and `..` are path components, and a run dir may not resolve elsewhere (A1).

        `sanitize` lets both through by its alphabet, and `start --name ..`
        resolved to the run root itself, so the run wrote prompt.md, state.json,
        run.json and the lock into the directory every run shares.
        """
        self.assertEqual(adapter.sanitize(".."), "")
        self.assertEqual(adapter.sanitize("."), "")
        self.assertEqual(adapter.sanitize("..."), "...")  # a name, not a component
        root = self.tmp / "escape-30-runs"
        env = self.env_for(DSH_RUN_ROOT=root)
        for name in (".", ".."):
            with self.subTest(name=name):
                proc = self.adapter_run(
                    "start", "--name", name, "--prompt", str(self.prompt), "--cwd", str(self.tmp),
                    env=env,
                )
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                self.assertIn("must not sanitize to nothing", proc.stderr)
                self.assertNotIn("started:", proc.stdout)
        # The clobber this finding describes would leave the run's artifacts in
        # the shared root; refusing means nothing was written there at all.
        for artifact in ("prompt.md", "state.json", "lock", "run.json", "answer.md", "events.ndjson"):
            with self.subTest(artifact=artifact):
                self.assertFalse((root / artifact).exists())
        # A slug directory that resolves somewhere else through a symlink is
        # refused before anything is written into the target either.
        outside = self.tmp / "escape-30-outside"
        outside.mkdir()
        bucket = root / adapter.date_stamp()
        bucket.mkdir(parents=True, exist_ok=True)
        try:
            (bucket / "sneaky").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):  # a host without the privilege
            (bucket / "sneaky").mkdir()
        if (bucket / "sneaky").is_symlink():
            proc = self.adapter_run(
                "start", "--name", "sneaky", "--prompt", str(self.prompt), "--cwd", str(self.tmp),
                env=env,
            )
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("refusing to write a run outside", proc.stderr)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((outside / "state.json").exists())

    def test_31_a_live_run_cannot_be_replayed(self):
        """The recorded run.sh must not start a second agent for a running run (A4).

        Only a finalized run went through the slug claim: replaying a live run
        overwrote the runner pid, reopened the same artifacts and started a second
        agent on the same cwd.
        """
        slug = "replay-live-31"
        second_argv = self.tmp / "replay-live-31-second.json"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        live = self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        run_dir = self.run_dir(slug)
        script = run_dir / ("run.cmd" if IS_WINDOWS else "run.sh")
        command = (
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", str(script)]
            if IS_WINDOWS else ["bash", str(script)]
        )
        try:
            replay = subprocess.run(
                command, cwd=str(self.bin),
                env=self.env_for(
                    STUB_MODE="error",  # a second agent would exit at once, after writing…
                    STUB_ARGV_FILE=second_argv,  # …this file that proves it ran
                    DSH_RUN_ROOT=str(self.run_root),
                ),
                capture_output=True, text=True, timeout=SETTLE_TIMEOUT,
            )
            self.assertNotEqual(replay.returncode, 0, replay.stdout + replay.stderr)
            self.assertIn("still live", replay.stdout + replay.stderr)
            self.assertFalse(second_argv.exists(), "a live run was replayed into a second agent")
            self.assertFalse((run_dir / "finalized").exists())
            state = self.state_of(slug)
            self.assertEqual(state["state"], "running", state)
            self.assertEqual(state["pid"], live["pid"])
            self.assertEqual(state["agent_pid"], live["agent_pid"])
            self.assertEqual(adapter.lock_of(str(run_dir))["pid"], live["pid"])
            self.assertTrue(adapter.run_alive(str(run_dir)))
        finally:
            self.adapter_run("kill", slug)
            self.wait_for_state(slug, {"killed"}, timeout=30.0)

    def test_32_recovery_leaves_another_routes_run_alone(self):
        """A shared run root: another backend's run is shown, never rewritten (A5).

        `list`/`status`/`result`/`answer` used to recover any run whose pids were
        gone, finalizing another adapter's run and emptying its `answer.md`.
        """
        root = self.tmp / "foreign-32-runs"
        slug = "foreign-32"
        run_dir = root / adapter.date_stamp() / slug
        run_dir.mkdir(parents=True)
        record = {
            "name": slug, "state": "running", "exit": None, "cwd": str(self.tmp),
            "backend": "omp",
            "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        }
        adapter.write_json(str(run_dir / "state.json"), record)
        (run_dir / "answer.md").write_text("ANOTHER ROUTE'S ANSWER\n", encoding="utf-8")
        (run_dir / "events.ndjson").write_text("", encoding="utf-8")
        # A directory whose state names no backend is not provably this route's
        # either: it is shown, and it stays exactly as it is.
        unknown_dir = root / adapter.date_stamp() / "foreign-32-unknown"
        unknown_dir.mkdir()
        adapter.write_json(str(unknown_dir / "state.json"), {
            "name": "foreign-32-unknown", "state": "running", "exit": None, "cwd": str(self.tmp),
            "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        })
        (unknown_dir / "answer.md").write_text("NO BACKEND RECORDED\n", encoding="utf-8")
        before = {path.name: path.read_bytes() for path in run_dir.iterdir()}
        before_unknown = {path.name: path.read_bytes() for path in unknown_dir.iterdir()}
        env = self.env_for(DSH_RUN_ROOT=root)
        listed = self.adapter_run("list", env=env)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("read-only(omp)", listed.stdout)
        self.assertIn("read-only(unknown)", listed.stdout)
        for reader in (("status", slug), ("result", slug), ("answer", slug)):
            with self.subTest(reader=reader):
                proc = self.adapter_run(*reader, env=env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
        view = json.loads(self.adapter_run("status", slug, env=env).stdout)
        self.assertEqual(view["backend"], "omp", view)
        self.assertEqual(view["state"], "running", view)
        self.assertEqual({path.name: path.read_bytes() for path in run_dir.iterdir()}, before)
        self.assertEqual(
            {path.name: path.read_bytes() for path in unknown_dir.iterdir()}, before_unknown
        )
        for directory in (run_dir, unknown_dir):
            self.assertFalse((directory / "finalized").exists())
            self.assertFalse((directory / "exit.code").exists())
        # `kill` refuses a foreign run outright; it never signals one.
        killed = self.adapter_run("kill", slug, env=env)
        self.assertEqual(killed.returncode, 1, killed.stdout + killed.stderr)
        self.assertIn("not this route's", killed.stderr)
        self.assertEqual({path.name: path.read_bytes() for path in run_dir.iterdir()}, before)
        # A live foreign run keeps its slug too: `--replace` refuses instead of
        # stopping it, even though the recorded pid is right there.
        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(300)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            live_record = dict(record, pid=sleeper.pid)
            adapter.write_json(str(run_dir / "state.json"), live_record)
            adapter.write_json(str(run_dir / "lock"), {
                "pid": sleeper.pid, "agent_pid": None, "backend": "omp",
            })
            proc = self.adapter_run(
                "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp),
                "--replace", env=env,
            )
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("another adapter's run", proc.stderr)
            self.assertIsNone(sleeper.poll(), "another route's run must not be signalled")
            self.assertEqual(adapter.read_state_file(str(run_dir))["backend"], "omp")
        finally:
            sleeper.kill()
            sleeper.wait(timeout=10)

    def test_33_a_failed_stop_keeps_the_run_live_and_stoppable(self):
        """A stop that leaves processes alive must not publish a terminal state (A3).

        A stop that failed used to report exit 143 whether or not anything
        survived, so the run was finalized `killed` while its agent still wrote to
        the worktree: `kill` then refused to touch it and a new `start` no longer
        saw the slug as occupied. The report path is driven through the runner
        (`failed_stop_run`), the survivor is a real process that acknowledged its
        readiness, and the run is then settled by a *later stop that really ends
        it* — the survivor has exited and been reaped before `killed` is accepted.
        """
        slug = "stopfail-33"
        run_dir, victim, _identity = self.failed_stop_run(slug)
        self.assertFalse((run_dir / "finalized").exists())
        self.assertFalse((run_dir / "exit.code").exists())
        self.assertFalse((run_dir / "answer.md").exists())
        state = adapter.read_state_file(str(run_dir))
        self.assertEqual(state["state"], "running", state)
        self.assertTrue(state["stopping"], state)
        self.assertEqual([record["pid"] for record in state["survivors"]], [victim.pid],
                         state["survivors"])
        self.assertIn(str(victim.pid), state["note"])
        self.assertTrue(adapter.run_alive(str(run_dir), state))
        # Every reader keeps reporting it live/stopping and recovers nothing.
        state_again, recovered = adapter.effective_state(str(run_dir))
        self.assertFalse(recovered)
        self.assertEqual(state_again["state"], "running")
        self.assertTrue(adapter.events_view(str(run_dir), state)["alive"])
        self.assertFalse((run_dir / "finalized").exists())
        # A direct terminal commit is refused while the survivor is alive: an exit
        # code is not stop evidence (T3).
        before = (run_dir / "state.json").read_bytes()
        op = adapter.operation_of(str(run_dir), state)
        with contextlib.redirect_stderr(io.StringIO()):
            refused = adapter.finalize(
                str(run_dir), adapter.KILL_EXIT, expect_generation=op.generation
            )
        self.assertEqual(refused["state"], "running", refused)
        self.assertFalse((run_dir / "finalized").exists())
        self.assertEqual(before, (run_dir / "state.json").read_bytes())
        # A later stop attempt resolves it: the survivor is signalled through its
        # verified identity, and the victim has really exited and been reaped
        # before the `killed` verdict and its receipt are accepted.
        reaper = threading.Thread(target=victim.wait, daemon=True)
        reaper.start()
        with mock.patch.object(adapter, "POLL_SECONDS", 0.01), \
                contextlib.redirect_stderr(io.StringIO()):
            stopped = adapter.stop_run(op, state, seconds=1)
        self.assertTrue(stopped, "a later stop attempt must settle the run")
        self.assertFalse(adapter.pid_alive(victim.pid), "the survivor must be stopped")
        self.assertIsNotNone(victim.poll(), "the survivor must have exited, not merely vanished")
        final = adapter.read_state_file(str(run_dir))
        self.assertEqual((final["state"], final["exit"]), ("killed", adapter.KILL_EXIT), final)
        self.assertNotIn("stopping", final)
        self.assertEqual([victim.pid], final.get("survivors_stopped"), final)
        self.assertEqual(
            (run_dir / "finalized").read_text(encoding="utf-8"), str(adapter.KILL_EXIT)
        )
        self.assertEqual(adapter.lifecycle_of(str(run_dir), final), adapter.LIFECYCLE_TERMINAL)


    # -- round-6 pins: the run-lifecycle class -------------------------------

    def failed_stop_run(self, slug, mode="known"):
        """A run whose runner loses a stop against an agent that ignores SIGTERM.

        The runner is driven in-process (the shape `test_33` uses), so the failure
        is deterministic; the TERM reaches a real, acknowledged-ready process and
        is really ignored, and the runner is then told the escalation could not
        name a completion. `mode="unknown"` is the same stop with a failed
        enumeration instead of a survivor list.
        """
        victim = self.ignoring_agent()
        identity = adapter.process_identity(victim.pid)
        self.assertTrue(identity, "the platform must supply a process identity")
        run_dir = self.run_root / adapter.date_stamp() / slug
        run_dir.mkdir(parents=True)
        (run_dir / "prompt.md").write_text("the agent is still working\n", encoding="utf-8")
        generation = adapter.new_nonce()
        adapter.write_json(str(run_dir / "state.json"), {
            "name": slug, "state": "running", "exit": None, "cwd": str(self.tmp),
            "started": adapter.now_iso(), "backend": "dsh", "generation": generation,
        })
        adapter.write_json(str(run_dir / "lock"), {
            "pid": None, "agent_pid": None, "backend": "dsh", "started_at": adapter.now_iso(),
            "generation": generation,
        })
        # What `kill` writes: a stop request bound to this run's generation.
        adapter.write_json(str(run_dir / "stop"), {
            "generation": generation, "request_id": adapter.new_nonce(),
            "requested_at": adapter.now_iso(), "by": os.getpid(),
        })
        args = adapter.build_parser().parse_args([
            "_run", "--run-dir", str(run_dir), "--prompt", str(run_dir / "prompt.md"),
            "--cwd", str(self.tmp), "--agent", str(self.dsh_bin()), "--name", slug,
            "--profile", "headless", "--permission-mode", "workspace-write",
            "--approval-policy", "never",
        ])
        survivors = None if mode == "unknown" else [(victim.pid, identity, victim.pid)]

        def stop_did_not_complete(process, op, agent_identity=""):
            # One real TERM, delivered through the verified process-instance path
            # and ignored by the agent; the escalation then reports the outcome it
            # could prove.
            adapter.signal_group(process.pid, signal.SIGTERM, agent_identity)
            return adapter.KILL_EXIT, survivors

        dead_pid = 1 << 22
        real_request = adapter.stop_request_for
        seen = {"calls": 0}

        def request_after_spawn(run_dir_arg, generation_arg):
            # The request must arrive while the agent is running, not before it is
            # spawned: a stop seen before the spawn is honoured as a stop and the
            # agent is never started (which is its own test). This makes the
            # fixture's ordering explicit instead of depending on timing.
            seen["calls"] += 1
            if seen["calls"] == 1:
                return {}
            return real_request(run_dir_arg, generation_arg)

        class NoSelfPid:
            """The os module, with getpid answering a pid this process is not."""

            def __getattr__(self, name):
                return getattr(os, name)

            def getpid(self):
                return dead_pid

        saved = {
            name: signal.getsignal(getattr(signal, name)) for name in ("SIGTERM", "SIGINT")
        }
        try:
            with mock.patch.dict(
                os.environ, self.env_for(DSH_RUN_DRAIN_TIMEOUT_SECONDS=1), clear=False
            ), mock.patch.object(adapter, "spawn_agent", lambda *a, **k: victim), \
                    mock.patch.object(adapter, "terminate_agent", stop_did_not_complete), \
                    mock.patch.object(adapter, "stop_request_for", request_after_spawn), \
                    mock.patch.object(adapter, "os", NoSelfPid()), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                code = adapter.runner_main(args)
        finally:
            for name, handler in saved.items():
                signal.signal(getattr(signal, name), handler)
        self.assertEqual(code, 1, "a stop that did not complete is not a finished run")
        return run_dir, victim, identity

    def stable_snapshot(self, run_dir, timeout=20.0, quiet=0.6):
        """A byte snapshot of the run directory's files, once they stop changing."""
        deadline = time.monotonic() + timeout
        previous, stable_since = None, None
        while time.monotonic() < deadline:
            current = {
                path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()
            }
            now = time.monotonic()
            if current == previous:
                if now - stable_since >= quiet:
                    return current
            else:
                previous, stable_since = current, now
            time.sleep(0.1)
        self.fail(f"{run_dir} never settled into a stable snapshot")

    def reap_runner_async(self, run_dir, timeout=30.0):
        """Reap the runner an in-process start spawned, as soon as it is recorded.

        `spawn_runner` in this process leaves the detached runner as a child; an
        unreaped zombie still answers a liveness probe, so the run would look
        alive forever. A recorded pid that is not this process's child (the run
        directory may still hold the previous run's state) is skipped, not
        waited on.
        """
        def wait_for_runner():
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                pid = adapter.read_state_file(str(run_dir)).get("pid")
                if isinstance(pid, int) and pid > 0:
                    try:
                        os.waitpid(pid, 0)
                        return
                    except ChildProcessError:
                        pass  # the previous run's runner; keep looking
                    except OSError:
                        return
                time.sleep(0.05)

        thread = threading.Thread(target=wait_for_runner, daemon=True)
        thread.start()
        return thread

    def list_line(self, slug):
        listed = self.adapter_run("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        rows = [row for row in listed.stdout.splitlines() if slug in row]
        self.assertEqual(len(rows), 1, listed.stdout)
        return rows[0]

    def result_view(self, slug):
        result = self.adapter_run("result", slug)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.split("\n--- answer")[0])

    def test_34_a_stop_that_cannot_enumerate_never_finalizes(self):
        """R1: "no survivors reported" is never "the stop is confirmed".

        Enumeration can fail (Windows has no group table; `ps` can error), and
        that used to look exactly like a confirmed stop: `surviving_members`
        returned `[]`, so the runner published `killed` while the tools were
        still alive. The three outcomes are distinct now — proven gone, survivors
        known, enumeration failed — and only the first reaches a terminal state.
        """
        with mock.patch.object(adapter, "IS_WINDOWS", True), \
                mock.patch.object(adapter, "platform_can_force_stop", lambda: False), \
                mock.patch.object(
                    adapter, "terminate_tree", lambda *a, **k: self.fail("no tree command on Windows")
                ), \
                mock.patch.object(adapter, "POLL_SECONDS", 0), \
                contextlib.redirect_stderr(io.StringIO()):
            code, survivors = adapter.terminate_agent(
                types.SimpleNamespace(pid=os.getpid(), poll=lambda: None), "win-shaped-op", "win:v1:1:1"
            )
        self.assertEqual(code, adapter.KILL_EXIT)
        self.assertIsNone(
            survivors, "an enumeration that never ran is not an empty survivor list"
        )

        slug = "stop-unknown-34"
        run_dir, victim, _identity = self.failed_stop_run(slug, mode="unknown")
        try:
            self.assertFalse((run_dir / "finalized").exists())
            self.assertFalse((run_dir / "exit.code").exists())
            state = adapter.read_state_file(str(run_dir))
            self.assertEqual(state["state"], "running", state)
            self.assertTrue(state["stopping"])
            self.assertIs(state["survivors_complete"], False, state)
            self.assertEqual(
                adapter.lifecycle_of(str(run_dir), state),
                adapter.LIFECYCLE_STOPPING_UNKNOWN,
            )
            self.assertIn("could not be enumerated", state["note"])
            # Even a failed enumeration names what it still knows is alive, so a
            # later attempt has a real identity to verify.
            self.assertIn(victim.pid, adapter.recorded_pids(str(run_dir), state))
            # The hole this pins: liveness says "gone" while the enumeration
            # cannot confirm it. No reader may finalize anything from that.
            with mock.patch.object(adapter, "run_alive", lambda run, state=None: False):
                settled, recovered = adapter.effective_state(str(run_dir))
            self.assertFalse(recovered)
            self.assertEqual(settled["state"], "running", settled)
            self.assertFalse((run_dir / "finalized").exists())
            # Windows-shaped / inspection failed: the group table cannot be read
            # at all, so the same "nothing recorded alive" is not proof.
            with mock.patch.object(adapter, "group_member_pids", lambda pgid: None), \
                    mock.patch.object(adapter, "run_alive", lambda run, state=None: False):
                settled, recovered = adapter.effective_state(str(run_dir))
            self.assertFalse(recovered)
            self.assertEqual(settled["state"], "running", settled)
            self.assertFalse((run_dir / "finalized").exists())
            # Whatever liveness says, the slug stays occupied: a probe that found
            # nothing is not a probe that proved nothing is there.
            with mock.patch.object(adapter, "run_alive", lambda run, state=None: False):
                occupant, _occupant_state = adapter.occupying_run(str(self.run_root), slug)
            self.assertEqual(occupant, str(run_dir))
            # Once the agent is really gone, a *complete* enumeration proves the
            # stop and the run settles killed/143 — never failed/-1.
            victim.kill()
            victim.wait(timeout=10)
            settled, recovered = adapter.effective_state(str(run_dir))
            self.assertTrue(recovered, settled)
            self.assertEqual(
                (settled["state"], settled["exit"]), ("killed", adapter.KILL_EXIT)
            )
        finally:
            self.reap(victim)

    def test_35_an_unconfirmed_stop_is_non_terminal_and_records_survivors(self):
        """R2: a stop that did not complete is not a result, and says what survived."""
        slug = "stopfail-35"
        run_dir, victim, identity = self.failed_stop_run(slug)
        try:
            self.assertFalse((run_dir / "finalized").exists())
            self.assertFalse((run_dir / "exit.code").exists())
            self.assertFalse((run_dir / "answer.md").exists())
            state = adapter.read_state_file(str(run_dir))
            self.assertEqual(state["state"], "running", state)
            self.assertTrue(state["stopping"])
            self.assertIs(state["survivors_complete"], True)
            self.assertEqual([record["pid"] for record in state["survivors"]], [victim.pid])
            self.assertEqual(state["survivors"][0]["identity"], identity)
            self.assertEqual(state["survivors"][0]["group"], victim.pid)
            lock = adapter.lock_of(str(run_dir))
            self.assertEqual([record["pid"] for record in lock["survivors"]], [victim.pid])
            self.assertTrue(adapter.run_alive(str(run_dir), state))
            self.assertEqual(
                adapter.lifecycle_of(str(run_dir), state),
                adapter.LIFECYCLE_STOPPING_KNOWN,
            )
        finally:
            self.reap(victim)

    def test_36_an_unconfirmed_stop_is_still_reported_as_live(self):
        """R2: `status`/`list` keep showing the run and its stop as unfinished."""
        slug = "stopfail-36"
        run_dir, victim, _identity = self.failed_stop_run(slug)
        try:
            view, _output = self.status_view(slug)
            self.assertTrue(view["alive"], view)
            self.assertTrue(view["stopping"], view)
            self.assertEqual(view["lifecycle"], "stopping (survivors known)")
            self.assertIn("stopping(survivors-known)", self.list_line(slug))
            self.assertEqual(self.result_view(slug)["lifecycle"], "stopping (survivors known)")
            answer = self.adapter_run("answer", slug)
            self.assertEqual(answer.returncode, 1)
            self.assertIn("stopping (survivors known)", answer.stderr)
        finally:
            self.reap(victim)

    def test_37_an_unconfirmed_stop_blocks_a_new_start_for_the_slug(self):
        """R2: the slug stays occupied, and the refusal leaves the run untouched."""
        slug = "stopfail-37"
        run_dir, victim, _identity = self.failed_stop_run(slug)
        try:
            before = self.stable_snapshot(run_dir)
            proc = self.adapter_run(
                "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp)
            )
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("still running", proc.stderr)
            self.assertEqual(self.stable_snapshot(run_dir), before)
            self.assertFalse((run_dir / "finalized").exists())
            self.assertTrue(adapter.run_alive(str(run_dir)))
        finally:
            self.reap(victim)

    def test_38_an_unconfirmed_stop_stays_killable_by_a_later_attempt(self):
        """R2: a later `kill` finishes the job through the recorded survivors."""
        slug = "stopfail-38"
        run_dir, victim, _identity = self.failed_stop_run(slug)
        try:
            # Reap the survivor as soon as it dies: an unreaped zombie still
            # answers a liveness probe, and the run would rightly stay stopping
            # until the process is really gone.
            reaper = threading.Thread(target=victim.wait, daemon=True)
            reaper.start()
            killed = self.adapter_run(
                "kill", slug, env=self.env_for(DSH_RUN_STOP_WAIT_SECONDS=1)
            )
            self.assertEqual(killed.returncode, 0, killed.stdout + killed.stderr)
            final = self.wait_for_state(slug, {"killed"}, timeout=30.0)
            self.assertEqual((final["state"], final["exit"]), ("killed", adapter.KILL_EXIT))
            self.assertEqual(final["stopped_by"], "control-file-forced")
            self.assertFalse(adapter.pid_alive(victim.pid), "the survivor must be stopped")
            self.assertEqual(
                (run_dir / "finalized").read_text(encoding="utf-8"), str(adapter.KILL_EXIT)
            )
        finally:
            self.reap(victim)

    def controlled_replacement(self, run_dir, slug):
        """The write `start --replace` performs, in-process, under S and M.

        The occupant is settled as the crash it is, moved aside (never deleted),
        and a *new* generation is initialized at the original path with its runner
        already gone — the shape a stale reader meets when it finally takes the
        mutation mutex.
        """
        root = adapter.bucket_root(str(run_dir))
        with adapter.slug_start_claim(root, slug) as got_s, \
                adapter.lifecycle_claim(root, slug) as got_m:
            self.assertTrue(got_s and got_m, "the replacement holds the slug claim and the mutex")
            adapter._effective_state_locked(adapter.operation_of(str(run_dir)))
            moved = adapter.move_aside(str(run_dir))
            self.assertTrue(moved, "the old run is preserved, not deleted")
            run_dir.mkdir(parents=True, exist_ok=True)
            generation = adapter.new_nonce()
            adapter.write_json(str(run_dir / "state.json"), {
                "name": slug, "state": "running", "exit": None, "cwd": str(self.tmp),
                "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "backend": "dsh", "generation": generation,
            })
            (run_dir / "events.ndjson").write_text(
                json.dumps({"type": "session", "sessionId": "session-new",
                            "cwd": str(self.tmp)}) + "\n",
                encoding="utf-8",
            )
        return moved, generation

    def test_39_a_stale_reader_never_finalizes_a_replaced_run(self):
        """R3: a terminal write is bound to the run generation it decided about.

        The reader takes its snapshot of the old run at this path; a starter then
        settles that run, moves it aside and builds a new generation at the same
        path — all of it *before* the reader takes the mutation mutex. The reader
        must then write nothing — byte for byte — and say why. The interleaving is
        explicit: the starter runs from inside the reader's own pre-mutex step
        (`operation_of`), so no scheduling accident is involved.
        """
        slug = "generation-39"
        run_dir = self.dead_run(slug)
        old_state = adapter.read_state_file(str(run_dir))
        old_generation = adapter.strict_generation(old_state)
        self.assertTrue(old_generation)
        held = {}
        real_operation_of = adapter.operation_of

        def replace_before_the_guard(path, state=None, generation=None):
            op = real_operation_of(path, state, generation)
            if (
                "replacing" not in held
                and not held.get("done")
                and generation is None
                and os.path.abspath(str(path)) == str(run_dir)
                and adapter.strict_generation(adapter.read_state_file(str(run_dir)))
                == old_generation
            ):
                # Set the sentinel before the replacement: the replacement itself
                # asks for the operation context, and that call must not recurse.
                held["replacing"] = True
                try:
                    held["moved"], held["generation"] = self.controlled_replacement(run_dir, slug)
                    held["before"] = self.stable_snapshot(run_dir)
                finally:
                    held["done"] = True
                    held.pop("replacing", None)
            return op

        err = io.StringIO()
        with mock.patch.object(adapter, "operation_of", replace_before_the_guard), \
                contextlib.redirect_stderr(err):
            state, recovered = adapter.effective_state(str(run_dir))
        self.assertFalse(recovered, state)
        self.assertIn("different run", err.getvalue())
        self.assertEqual(adapter.strict_generation(state), held["generation"])
        self.assertNotEqual(adapter.strict_generation(state), old_generation)
        self.assertEqual(state["state"], "running", state)
        self.assertEqual(self.stable_snapshot(run_dir), held["before"])
        self.assertFalse((run_dir / "finalized").exists())
        self.assertFalse((run_dir / "answer.md").exists())
        self.assertFalse((run_dir / "exit.code").exists())
        # The replacement preserved the old run, and settled it as the crash it was.
        old_final = json.loads(
            (Path(held["moved"]) / "state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(old_final["state"], "failed")
        self.assertTrue(old_final["stale_recovered"])
        # The new generation is untouched, and its *own* readers settle it: the
        # stale reader's refusal did not consume the new run's recovery.
        settled, recovered_now = adapter.effective_state(str(run_dir))
        self.assertTrue(recovered_now, settled)
        self.assertEqual(settled["state"], "failed")
        self.assertEqual(settled["terminal_record"]["generation"], held["generation"])

    def test_40_two_concurrent_starts_produce_exactly_one_agent(self):
        """R4: the slug claim is atomic for every start, so a race has one winner."""
        slug = "race-40"
        run_dir = self.run_root / adapter.date_stamp() / slug
        agent_log = self.tmp / "race-40.agents"
        entered = self.tmp / "race-40.entered"
        release = self.tmp / "race-40.release"
        env = self.env_for(STUB_APPEND_FILE=agent_log, STUB_MODE="settle")
        args = adapter.build_parser().parse_args([
            "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp)])
        real = adapter._start_run_claimed
        outcome = {}

        def hold_inside(*call_args, **call_kwargs):
            # The file the test controls holds the winner inside the critical
            # section, so the loser meets a held claim, not a scheduling accident.
            entered.write_text("in\n", encoding="utf-8")
            deadline = time.monotonic() + 60.0
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            return real(*call_args, **call_kwargs)

        def racer():
            try:
                outcome["code"] = adapter.start_run(
                    args, run_dir, str(self.dsh_bin()), False, "headless",
                    "workspace-write", "never",
                )
            except SystemExit as exc:
                outcome["code"] = exc.code

        with mock.patch.object(adapter, "_start_run_claimed", hold_inside), \
                mock.patch.dict(os.environ, env, clear=False):
            winner = threading.Thread(target=racer, daemon=True)
            winner.start()
            deadline = time.monotonic() + 30.0
            while not entered.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(entered.exists(), "the winner never entered the critical section")
            loser = self.adapter_run(
                "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp),
                env=env,
            )
            self.assertEqual(loser.returncode, 1, loser.stdout + loser.stderr)
            self.assertIn("another start is claiming", loser.stderr)
            self.assertFalse(run_dir.exists(), "the loser wrote a run directory")
            self.assertFalse(agent_log.exists(), "the loser started an agent")
            release.write_text("go\n", encoding="utf-8")
            reaper = self.reap_runner_async(run_dir)
            winner.join(timeout=START_TIMEOUT + 30.0)
        self.assertFalse(winner.is_alive())
        self.assertEqual(outcome.get("code"), 0, outcome)
        state = self.wait_for_state(slug, {"done", "killed", "failed"})
        self.assertTrue(state.get("agent_pid"), state)
        self.assertEqual(
            agent_log.read_text(encoding="utf-8").split(), [str(state["agent_pid"])],
            "two racers must produce exactly one agent",
        )

    def test_41_a_start_concurrent_with_a_replay_produces_exactly_one_agent(self):
        """R4: the recorded `run.sh` takes the same claim, so a replay cannot race it."""
        slug = "race-41"
        self.settle(slug, STUB_TEXT="first answer")
        run_dir = self.run_dir(slug)
        agent_log = self.tmp / "race-41.agents"
        entered = self.tmp / "race-41.entered"
        release = self.tmp / "race-41.release"
        env = self.env_for(STUB_APPEND_FILE=agent_log, STUB_MODE="settle")
        args = adapter.build_parser().parse_args([
            "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp)])
        real = adapter._start_run_claimed
        outcome = {}

        def hold_inside(*call_args, **call_kwargs):
            entered.write_text("in\n", encoding="utf-8")
            deadline = time.monotonic() + 60.0
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            return real(*call_args, **call_kwargs)

        def racer():
            try:
                outcome["code"] = adapter.start_run(
                    args, run_dir, str(self.dsh_bin()), False, "headless",
                    "workspace-write", "never",
                )
            except SystemExit as exc:
                outcome["code"] = exc.code

        with mock.patch.object(adapter, "_start_run_claimed", hold_inside), \
                mock.patch.dict(os.environ, env, clear=False):
            winner = threading.Thread(target=racer, daemon=True)
            winner.start()
            deadline = time.monotonic() + 30.0
            while not entered.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(entered.exists(), "the winner never entered the critical section")
            before = self.stable_snapshot(run_dir)
            if IS_WINDOWS:
                command = [os.environ.get("COMSPEC") or "cmd.exe", "/d", "/c",
                           str(run_dir / "run.cmd")]
            else:
                command = [str(run_dir / "run.sh")]
            replay = subprocess.run(
                command, capture_output=True, text=True, env=self.env, timeout=SETTLE_TIMEOUT
            )
            self.assertNotEqual(replay.returncode, 0, replay.stdout + replay.stderr)
            self.assertIn("another start owns", replay.stdout + replay.stderr)
            self.assertEqual(self.stable_snapshot(run_dir), before)
            self.assertFalse(agent_log.exists(), "the replay started a second agent")
            release.write_text("go\n", encoding="utf-8")
            reaper = self.reap_runner_async(run_dir)
            winner.join(timeout=START_TIMEOUT + 30.0)
        self.assertFalse(winner.is_alive())
        self.assertEqual(outcome.get("code"), 0, outcome)
        final = self.wait_for_state(slug, {"done", "killed", "failed"})
        self.assertTrue(final.get("agent_pid"), final)
        self.assertEqual(
            agent_log.read_text(encoding="utf-8").split(), [str(final["agent_pid"])],
            "a start and a replay must produce exactly one agent",
        )
        previous = sorted(run_dir.parent.glob(f"{slug}.prev-*"))
        self.assertTrue(previous, "the replay's previous run must be preserved")
        self.assertIn("first answer",
                      (previous[0] / "answer.md").read_text(encoding="utf-8"))

    def test_42_lifecycle_terminal_over_the_real_artifacts(self):
        """R5: a finished run says `terminal` in every answer."""
        slug = "life-42"
        self.settle(slug, STUB_TEXT="terminal answer")
        view, output = self.status_view(slug)
        self.assertEqual(view["lifecycle"], "terminal")
        self.assertEqual(view["state"], "done")
        self.assertNotIn("not finished", output)
        self.assertIn("done exit=0", self.list_line(slug))
        self.assertEqual(self.result_view(slug)["lifecycle"], "terminal")
        answer = self.adapter_run("answer", slug)
        self.assertEqual(answer.returncode, 0, answer.stderr)
        self.assertEqual(answer.stdout, "terminal answer")

    def test_43_lifecycle_live_over_the_real_artifacts(self):
        """R5: a working run says `live`, and its answer is refused as such."""
        slug = "life-43"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        try:
            view, _output = self.status_view(slug)
            self.assertEqual(view["lifecycle"], "live")
            self.assertTrue(view["alive"])
            self.assertIn("running(live)", self.list_line(slug))
            self.assertEqual(self.result_view(slug)["lifecycle"], "live")
            answer = self.adapter_run("answer", slug)
            self.assertEqual(answer.returncode, 1)
            self.assertIn("not finished yet (live", answer.stderr)
        finally:
            self.adapter_run("kill", slug)
            self.wait_for_state(slug, {"killed"}, timeout=30.0)

    def test_44_lifecycle_stopping_with_survivors_over_the_real_artifacts(self):
        """R5: `stopping (survivors known)` is not a terminal state anywhere."""
        slug = "life-44"
        run_dir, victim, _identity = self.failed_stop_run(slug)
        try:
            view, _output = self.status_view(slug)
            self.assertEqual(view["lifecycle"], "stopping (survivors known)")
            self.assertIs(view["survivors_complete"], True)
            self.assertTrue(view["alive"])
            self.assertIn("stopping(survivors-known)", self.list_line(slug))
            self.assertEqual(
                self.result_view(slug)["lifecycle"], "stopping (survivors known)"
            )
            answer = self.adapter_run("answer", slug)
            self.assertEqual(answer.returncode, 1)
            self.assertIn("stopping (survivors known)", answer.stderr)
        finally:
            self.reap(victim)

    def test_45_lifecycle_stopping_without_enumeration_over_the_real_artifacts(self):
        """R5: `stopping (enumeration failed)` is a state of its own, not `running`."""
        slug = "life-45"
        run_dir, victim, _identity = self.failed_stop_run(slug, mode="unknown")
        try:
            view, _output = self.status_view(slug)
            self.assertEqual(view["lifecycle"], "stopping (enumeration failed)")
            self.assertIs(view["survivors_complete"], False)
            self.assertIn("stopping(enumeration-failed)", self.list_line(slug))
            self.assertEqual(
                self.result_view(slug)["lifecycle"], "stopping (enumeration failed)"
            )
            answer = self.adapter_run("answer", slug)
            self.assertEqual(answer.returncode, 1)
            self.assertIn("stopping (enumeration failed)", answer.stderr)
        finally:
            self.reap(victim)

    def test_46_lifecycle_unknown_without_a_state_over_the_real_artifacts(self):
        """R5: a directory that never recorded a state is `unknown (no state)`."""
        slug = "life-46"
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "prompt.md").write_text("no state was ever written\n", encoding="utf-8")
        view, _output = self.status_view(slug)
        self.assertEqual(view["lifecycle"], "unknown (no state)")
        self.assertEqual(view["state"], "unknown")
        self.assertIn("unknown(no-state)", self.list_line(slug))
        self.assertEqual(self.result_view(slug)["lifecycle"], "unknown (no state)")
        answer = self.adapter_run("answer", slug)
        self.assertEqual(answer.returncode, 1)
        self.assertIn("unknown (no state)", answer.stderr)

class AdapterUnitTests(ProcessFixtures):
    """The pieces a run needs but a full dispatch does not exercise."""

    def test_sanitize_matches_the_reference_slug_rule(self):
        self.assertEqual(adapter.sanitize("Repo-Goal Stage/One"), "repo-goal-stage-one")
        self.assertEqual(adapter.sanitize("x" * 80), "x" * 48)
        self.assertEqual(adapter.sanitize(""), "")

    def test_run_root_follows_the_documented_chain(self):
        base = tempfile.gettempdir()
        xdg = os.path.join(base, "dsh-run-test-state")
        gdd = os.path.join(base, "dsh-run-test-gdd")
        dsh = os.path.join(base, "dsh-run-test-dsh")
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": xdg}, clear=True):
            self.assertEqual(adapter.run_root(), os.path.join(xdg, "gdd", "runs"))
        with mock.patch.dict(
            os.environ, {"XDG_STATE_HOME": xdg, "GDD_RUN_ROOT": gdd}, clear=True
        ):
            self.assertEqual(adapter.run_root(), gdd)
        with mock.patch.dict(
            os.environ,
            {"XDG_STATE_HOME": xdg, "GDD_RUN_ROOT": gdd, "DSH_RUN_ROOT": dsh},
            clear=True,
        ):
            self.assertEqual(adapter.run_root(), dsh)

    def test_the_profile_key_is_the_adapters_own_not_the_harness_identity(self):
        """The harness reserves DSH_PROFILE; this launcher's key is DSH_RUN_PROFILE."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(adapter.dsh_profile(), "headless")
        with mock.patch.dict(os.environ, {"DSH_PROFILE": "interactive"}, clear=True):
            self.assertEqual(adapter.dsh_profile(), "headless")
        with mock.patch.dict(os.environ, {"DSH_RUN_PROFILE": "interactive"}, clear=True):
            self.assertEqual(adapter.dsh_profile(), "interactive")
        with mock.patch.dict(
            os.environ, {"DSH_RUN_PROFILE": "one", "DSH_PROFILE": "two"}, clear=True
        ):
            self.assertEqual(adapter.dsh_profile(), "one")

    def test_the_child_environment_drops_the_reserved_harness_identity(self):
        with mock.patch.dict(
            os.environ,
            {"DSH_PROFILE": "interactive", "DSH_PROFILE_DIR": "/somewhere",
             "DSH_SESSION_ID": "session-x", "DSH_RUN_PROFILE": "headless", "KEEP": "yes"},
            clear=True,
        ):
            env = adapter.child_env()
        for name in ("DSH_PROFILE", "DSH_PROFILE_DIR", "DSH_SESSION_ID"):
            self.assertNotIn(name, env)
        # Everything else is passed through, including this adapter's own key.
        self.assertEqual(env["KEEP"], "yes")
        self.assertEqual(env["DSH_RUN_PROFILE"], "headless")

    def test_the_reserved_keys_are_documented_where_the_adapter_documents_itself(self):
        for text in (adapter.__doc__, adapter.EPILOG):
            for name in ("DSH_RUN_PROFILE", "DSH_PROFILE", "DSH_PROFILE_DIR",
                         "DSH_SESSION_ID"):
                self.assertIn(name, text)
        # And the harness's key is never read as this adapter's profile.
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertNotIn('os.environ.get("DSH_PROFILE")', source)
        self.assertNotIn("os.environ.get('DSH_PROFILE')", source)

    def test_parser_edge_cases(self):
        parser = adapter.build_parser()
        # `--replace` before `--name`: a store_true flag must not swallow the next
        # token, and the value flag after it must still take its value.
        argv = adapter.normalize_argv(
            ["start", "--replace", "--name", "n", "--prompt", "p", "--cwd", "c"]
        )
        args = parser.parse_args(argv)
        self.assertTrue(args.replace)
        self.assertEqual((args.name, args.prompt, args.cwd), ("n", "p", "c"))
        argv = adapter.normalize_argv(
            ["start", "--name", "n", "--replace", "--prompt", "p", "--cwd", "c"]
        )
        args = parser.parse_args(argv)
        self.assertTrue(args.replace)
        self.assertEqual(args.name, "n")
        # A bare `status` has no slug; it routes to the listing.
        bare = parser.parse_args(adapter.normalize_argv(["status"]))
        self.assertEqual(bare.func, adapter.cmd_status)
        self.assertIsNone(bare.name)

    def test_option_like_values_survive_argparse(self):
        argv = adapter.normalize_argv(
            ["start", "--name", "n", "--prompt", "p", "--session-id", "-weird-id"]
        )
        self.assertIn("--session-id=-weird-id", argv)
        self.assertEqual(len(argv), 6)
        self.assertEqual(
            adapter.normalize_argv(["start", "--name", "n", "--prompt", "p"]),
            ["start", "--name", "n", "--prompt", "p"],
        )

    def test_events_bound_is_configuration_with_a_honest_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cap, warning = adapter.events_max_bytes()
            self.assertEqual(cap, 8388608)
            self.assertIsNone(warning)
        with mock.patch.dict(os.environ, {"DSH_RUN_EVENTS_MAX_BYTES": "1024"}, clear=True):
            self.assertEqual(adapter.events_max_bytes(), (1024, None))
        with mock.patch.dict(os.environ, {"DSH_RUN_EVENTS_MAX_BYTES": "nope"}, clear=True):
            cap, warning = adapter.events_max_bytes()
            self.assertEqual(cap, 8388608)
            self.assertIn("not an integer", warning)
        with mock.patch.dict(os.environ, {"DSH_RUN_EVENTS_MAX_BYTES": "0"}, clear=True):
            cap, warning = adapter.events_max_bytes()
            self.assertEqual(cap, 8388608)
            self.assertIn("not positive", warning)

    def test_max_time_parsing(self):
        self.assertIsNone(adapter.parse_max_time(None))
        self.assertEqual(adapter.parse_max_time("600"), 600.0)
        self.assertEqual(adapter.parse_max_time("1.5"), 1.5)
        for bad in ("soon", "0", "-3", "inf", "nan"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    adapter.parse_max_time(bad)

    def test_killed_exit_codes_are_the_documented_set(self):
        self.assertEqual(adapter.KILLED_EXITS, (130, -2, 137, -9, 143, -15))
        self.assertEqual(adapter.KILL_EXIT, 143)

    def test_the_killed_mapping_documents_both_routes(self):
        """`killed` is the adapter's stop *and* a signal exit; `failed` is the rest."""
        source = ADAPTER.read_text(encoding="utf-8")
        comment = source.split("KILLED_EXITS = ", 1)[0][-1400:]
        comment = " ".join(comment.replace("#", " ").split())
        self.assertIn("adapters/omp-run.py", comment)
        self.assertIn("KILL_EXIT (143)", comment)
        self.assertIn("signal convention", comment)
        self.assertIn("`failed`", comment)

    def test_start_fails_when_only_the_runner_recorded_a_pid(self):
        """A live runner without an agent pid is not a successful dispatch (A1).

        The runner is simulated by the test: it records its own (live) pid and
        never reaches `spawn_agent`, which is exactly the wedged-runner case.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            prompt = Path(tmp) / "prompt.md"
            prompt.write_text("do the thing\n", encoding="utf-8")
            args = adapter.build_parser().parse_args(
                ["start", "--name", "wedged-runner", "--prompt", str(prompt), "--cwd", tmp]
            )
            run_dir = root / adapter.date_stamp() / "wedged-runner"

            def fake_spawn(argv, cwd, log_path):
                adapter.update_lock(str(run_dir), pid=os.getpid())
                state = adapter.read_state_file(str(run_dir))
                state["pid"] = os.getpid()
                adapter.write_json(str(run_dir / "state.json"), state)
                return types.SimpleNamespace(pid=os.getpid(), poll=lambda: None)

            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(
                os.environ,
                {"DSH_RUN_ROOT": str(root), "DSH_BIN": sys.executable,
                 "DSH_APPROVAL_POLICY": "never"},
                clear=False,
            ), mock.patch.object(adapter, "spawn_runner", fake_spawn), mock.patch.object(
                adapter, "START_WAIT_SECONDS", 0.5
            ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as caught:
                    adapter.cmd_start(args)
            self.assertNotEqual(caught.exception.code, 0)
            self.assertNotIn("started:", out.getvalue())
            self.assertIn("did not start", err.getvalue())

    def test_the_tracker_stops_publishing_before_the_verdict_is_committed(self):
        """A reader outliving the drain timeout cannot rewrite the terminal state (A3)."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = {"name": "late", "state": "running", "exit": None, "cwd": tmp,
                     "started": adapter.now_iso(), "backend": "dsh",
                     "generation": adapter.new_nonce()}
            adapter.write_json(str(run_dir / "state.json"), state)
            (run_dir / "events.ndjson").write_text(
                json.dumps({"type": "final", "sessionId": "s", "reason": {"kind": "completed"},
                            "text": "the answer"}) + "\n",
                encoding="utf-8",
            )
            op = adapter.operation_of(str(run_dir), state)
            track, stop = adapter.make_tracker(op, state)
            track(json.dumps({"type": "session", "sessionId": "s"}).encode())
            stop()
            final = adapter.finalize(str(run_dir), 0, expect_generation=op.generation)
            self.assertEqual(final["state"], "done", final)
            committed = (run_dir / "state.json").read_bytes()
            # Lines a descendant kept the stream open for, arriving after the
            # finalizer committed: a forcing `session` event and a counted one.
            track(json.dumps({"type": "session", "sessionId": "late"}).encode())
            track(json.dumps({"type": "status", "turn": 1, "phase": "turn_end"}).encode())
            self.assertEqual(committed, (run_dir / "state.json").read_bytes())
            self.assertEqual(adapter.read_state_file(str(run_dir))["state"], "done")
            self.assertEqual(adapter.terminal_snapshot_locked(final)["exit"], 0)

    def test_write_json_temp_names_are_unique_per_call(self):
        """Two writers in one interpreter must not share a temp path (A3)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            self.assertEqual(len({adapter.json_temp_path(path) for _ in range(50)}), 50)
            payloads = [{"n": index, "filler": "x" * 4096} for index in range(2)]
            errors = []

            def writer(payload):
                try:
                    for _ in range(20):
                        adapter.write_json(path, payload)
                except Exception as exc:  # surfaced below, not swallowed
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(payload,)) for payload in payloads]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            final = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertIn(final, payloads)

    def test_a_recycled_pid_is_not_alive_for_this_run(self):
        """Liveness must be identity-checked, or a reused pid resurrects a dead run."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "reused", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso()})
            victim = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                # The same live pid recorded against a token that is not its own
                # is a reused pid, not this run's process.
                adapter.write_json(str(run_dir / "lock"), {
                    "pid": victim.pid, "agent_pid": None, "pid_identity": "proc:0"})
                self.assertFalse(adapter.run_alive(str(run_dir)))
                # The identity read at spawn keeps the run alive.
                identity = adapter.process_identity(victim.pid)
                self.assertTrue(identity, "the platform must supply a process identity")
                adapter.write_json(str(run_dir / "lock"), {
                    "pid": victim.pid, "agent_pid": None, "pid_identity": identity})
                self.assertTrue(adapter.run_alive(str(run_dir)))
                # No identity at all: liveness is the only evidence and is kept
                # (an older run may be live), but the signal path refuses it.
                adapter.write_json(str(run_dir / "lock"), {"pid": victim.pid, "agent_pid": None})
                self.assertTrue(adapter.run_alive(str(run_dir)))
            finally:
                victim.kill()
                victim.wait(timeout=10)

    @unittest.skipIf(IS_WINDOWS, "process groups and pidfds are POSIX/Linux-only")
    def test_signal_group_refuses_a_pid_it_cannot_prove(self):
        """No signal without a matching, admissible identity; the group id is never sent.

        An identity the platform cannot reproduce, a legacy `proc:<ticks>` token
        and an empty value all refuse — nothing is delivered. What is delivered
        for a verified leader is its group, enumerated under that leader as a
        continuously verified anchor and signalled per member through its own
        validated handle, never `killpg` on the group id.
        """
        leader, member = self.group_with_ready_member()
        identity = adapter.process_identity(leader.pid)
        self.assertTrue(adapter.identity_is_strong(identity), identity)
        delivered, patches = self.signal_spy()
        err = io.StringIO()
        try:
            with patches[0], patches[1], contextlib.redirect_stderr(err):
                self.assertFalse(adapter.signal_group(leader.pid, signal.SIGTERM, "linux:v2:nope"))
                self.assertFalse(adapter.signal_group(leader.pid, signal.SIGTERM, ""))
                self.assertFalse(adapter.signal_group(leader.pid, signal.SIGTERM, "proc:1"))
                self.assertEqual(delivered, [], "no admissible identity, no delivery")
                self.assertIn("not signalling", err.getvalue())
                # The verified leader names the group: every member is signalled
                # through its own validated handle, the leader included.
                self.assertTrue(adapter.signal_group(leader.pid, signal.SIGTERM, identity))
            self.assertEqual([pid for pid, _ in delivered], [leader.pid, member])
            self.assertEqual({signum for _pid, signum in delivered}, {signal.SIGTERM})
            self.assertEqual(adapter.liveness_of(leader.pid), adapter.LIVE)
        finally:
            self.reap_pids([member])

    @unittest.skipIf(IS_WINDOWS, "process groups are POSIX-only")
    def test_a_vanished_leader_is_never_signalled(self):
        """A historical group number is not ownership, and nothing is enumerated (P4).

        The record names a pid that is gone and a group number some unrelated live
        process now carries. Adding that number to the candidate set — the old
        behaviour — enumerated those strangers and minted them as this run's
        survivors, identities that then passed the later checks.
        """
        victim = self.spawn(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "reused-group", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso(), "backend": "dsh",
                "generation": adapter.new_nonce(),
                "stopping": True, "survivors_complete": True,
                "survivors": [{"pid": 1 << 22, "identity": "linux:v2:x", "group": victim.pid}],
            })
            enumerated = []
            with mock.patch.object(
                adapter, "anchored_members", lambda *a, **k: enumerated.append(a) or None
            ), contextlib.redirect_stderr(io.StringIO()):
                survivors = adapter.stop_survivors(str(run_dir))
                self.assertIsNone(survivors, "a historical group number is not a candidate")
                self.assertEqual(enumerated, [], "nothing is enumerated without a live anchor")
                self.assertFalse(
                    adapter.signal_member_group(
                        1 << 22, signal.SIGTERM, "linux:v2:x", victim.pid
                    )
                )
            self.assertEqual(adapter.liveness_of(victim.pid), adapter.LIVE)

    @unittest.skipIf(IS_WINDOWS, "process groups are POSIX-only")
    def test_a_verified_member_names_the_group_of_a_gone_leader(self):
        """A survivor's own identity aims the group signal after its leader is gone (P7).

        The leader is *really* reaped first, so an implementation that requires
        the group leader to be alive cannot pass this: the surviving member is the
        anchor, its recorded identity is the evidence, and only verified members
        are signalled through their own handles.
        """
        leader, member = self.group_with_ready_member()
        member_identity = adapter.process_identity(member)
        self.assertTrue(adapter.identity_is_strong(member_identity), member_identity)
        leader.kill()
        leader.wait(timeout=10)
        self.assertEqual(adapter.liveness_of(leader.pid), adapter.GONE)
        delivered, patches = self.signal_spy()
        err = io.StringIO()
        try:
            with patches[0], patches[1], contextlib.redirect_stderr(err):
                self.assertTrue(
                    adapter.signal_member_group(
                        member, signal.SIGTERM, member_identity, leader.pid
                    )
                )
                # A member whose recorded identity is not its own is refused…
                self.assertFalse(
                    adapter.signal_member_group(
                        member, signal.SIGTERM, "linux:v2:other", leader.pid
                    )
                )
                # …and so is a recorded group the member does not belong to.
                self.assertFalse(
                    adapter.signal_member_group(
                        member, signal.SIGTERM, member_identity, leader.pid + 1
                    )
                )
            self.assertEqual([pid for pid, _ in delivered], [member])
            self.assertIn("not signalling the group", err.getvalue())
        finally:
            self.reap_pids([member])

    def test_a_failed_stop_records_survivors_without_finalizing(self):
        """A failed stop stays live/stopping, and only a real stop settles it (A3/T4).

        The report itself is exercised here; the *terminal* half is exercised only
        after the survivor has really exited — with the survivor alive, a direct
        `finalize(..., KILL_EXIT)` is refused, and the receipt is accepted only
        once the process it names is gone.
        """
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            victim = self.ignoring_agent()
            identity = adapter.process_identity(victim.pid)
            self.assertTrue(identity, "the platform must supply a process identity")
            generation = adapter.new_nonce()
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "stopping", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso(), "backend": "dsh", "generation": generation,
            })
            adapter.write_json(str(run_dir / "lock"), {
                "pid": None, "agent_pid": None, "backend": "dsh", "generation": generation,
            })
            op = adapter.operation_of(str(run_dir))
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                code = adapter.report_incomplete_stop(
                    op, [(victim.pid, identity, victim.pid)], "control-file"
                )
            self.assertEqual(code, 1)
            self.assertFalse((run_dir / "finalized").exists())
            self.assertFalse((run_dir / "exit.code").exists())
            state = adapter.read_state_file(str(run_dir))
            self.assertEqual(state["state"], "running", state)
            self.assertTrue(state["stopping"], state)
            # The survivor is what keeps the run alive and its slug occupied…
            self.assertTrue(adapter.run_alive(str(run_dir), state))
            self.assertIn(victim.pid, adapter.recorded_pids(str(run_dir), state))
            # …so no reader recovers it into failed/-1 while it is still there.
            settled, recovered = adapter.effective_state(str(run_dir))
            self.assertFalse(recovered)
            self.assertEqual(settled["state"], "running")
            self.assertFalse((run_dir / "finalized").exists())
            # A direct terminal commit is refused while the survivor is alive.
            with contextlib.redirect_stderr(io.StringIO()):
                refused = adapter.finalize(
                    str(run_dir), adapter.KILL_EXIT, expect_generation=generation
                )
            self.assertEqual(refused["state"], "running", refused)
            # Only a real stop settles it, and the receipt names a process that is
            # really gone by the time the verdict is accepted.
            with mock.patch.object(adapter, "POLL_SECONDS", 0.01), \
                    contextlib.redirect_stderr(io.StringIO()):
                stopped = adapter.stop_run(op, state, seconds=1)
            self.assertTrue(stopped)
            self.assertIsNotNone(victim.poll(), "the survivor must have exited")
            final = adapter.read_state_file(str(run_dir))
            self.assertEqual(final["state"], "killed")
            self.assertNotIn("stopping", final)
            self.assertEqual(final.get("survivors_stopped"), [victim.pid])
            self.assertEqual(adapter.lifecycle_of(str(run_dir), final), adapter.LIFECYCLE_TERMINAL)

    def test_a_run_dir_must_be_a_direct_child_of_a_date_bucket(self):
        """Any shape but `<root>/<date>/<slug>` is refused before a write (A1)."""
        with tempfile.TemporaryDirectory() as tmp:
            bucket = Path(tmp) / "2026-11-15"
            bucket.mkdir()
            self.assertEqual(adapter.checked_run_dir(str(bucket / "ok")), str(bucket / "ok"))
            for bad in (tmp, str(bucket), str(bucket / ".."), str(bucket / "."), str(bucket / "")):
                with self.subTest(path=bad):
                    with self.assertRaises(ValueError):
                        adapter.checked_run_dir(bad)

    def test_the_ps_identity_probe_fixes_its_own_view(self):
        """`ps -o lstart=` is timezone-shaped, fixed per call — and never a signal's proof.

        On a host with procfs the adapter uses the boot/namespace/tick token and
        does **not** fall back to the display timestamp when that token cannot be
        read (the fallback would authorize exactly the signal the strong token
        exists to gate). Where the probe is used at all, it fixes its own view
        (`TZ=UTC`, `LC_ALL=C`) without touching the caller's environment.
        """
        seen = []

        def fake_run(argv, **kwargs):
            env = kwargs.get("env") or {}
            seen.append((list(argv), env.get("TZ"), env.get("LC_ALL")))
            text = (
                "Mon Nov 17 10:00:00 2025"
                if env.get("TZ") == "UTC" else "Mon Nov 17 23:00:00 2025"
            )
            return types.SimpleNamespace(returncode=0, stdout=text + "\n")

        # The probe's own view, exercised directly: one token under any caller TZ.
        with mock.patch.object(adapter.subprocess, "run", fake_run):
            with mock.patch.dict(os.environ, {"TZ": "UTC", "LC_ALL": "C"}, clear=False):
                first = adapter._ps_identity(os.getpid())
            with mock.patch.dict(
                os.environ, {"TZ": "Pacific/Kiritimati", "LC_ALL": "de_DE.UTF-8"}, clear=False
            ):
                second = adapter._ps_identity(os.getpid())
                # The probe fixes its own view; the caller's environment is untouched.
                self.assertEqual(os.environ.get("TZ"), "Pacific/Kiritimati")
                self.assertEqual(os.environ.get("LC_ALL"), "de_DE.UTF-8")
        self.assertTrue(first, "the probe must produce a token")
        self.assertEqual(first, second, "one process must yield one token under any caller TZ")
        self.assertEqual([entry[1:] for entry in seen], [("UTC", "C"), ("UTC", "C")])
        self.assertIn("lstart=", seen[0][0])
        # And it is admissible for nothing: the display timestamp is evidence, not
        # an authorization.
        self.assertFalse(adapter.identity_is_strong(first))
        weak = adapter._ps_identity(os.getpid())
        with mock.patch.object(adapter, "_proc_stat_identity", lambda target: ""), \
                mock.patch.object(adapter, "_ps_identity",
                                  lambda target: self.fail("no weak fallback on Linux")), \
                mock.patch.object(adapter.os.path, "exists", lambda path: True):
            self.assertEqual(adapter.process_identity(os.getpid()), "")
            self.assertFalse(
                adapter.signal_group(os.getpid(), signal.SIGTERM, weak or "ps:x")
            )

    def test_the_stop_escalation_branches_on_the_platform(self):
        """A platform without a verified handle primitive refuses to escalate (P2).

        Windows must not read `signal.SIGKILL` (it does not exist there) and must
        not fall back to `taskkill`; macOS has only a display-timestamp identity;
        Linux without pidfds has no handle to signal through. In every such case no
        destructive call is made and the outcome is the explicit unconfirmed one —
        which no caller may turn into a terminal state.
        """
        attempts = []

        class FakeSignal:  # a Windows-shaped signal module: SIGTERM and no SIGKILL
            SIGTERM = 15

        class StandInProcess:
            pid = os.getpid()

            def poll(self):
                return None

        def run_case(windows, signum_module, capable):
            attempts.clear()
            with tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp)
                generation = adapter.new_nonce()
                adapter.write_json(str(run_dir / "state.json"), {
                    "name": "escalate", "state": "running", "exit": None, "cwd": tmp,
                    "started": adapter.now_iso(), "backend": "dsh",
                    "generation": generation,
                })
                op = adapter.operation_of(str(run_dir))
                # The signalling paths require the process metadata to carry the
                # same generation, exactly as `start` writes it.
                adapter.write_json(str(run_dir / "lock"), {
                    "pid": None, "agent_pid": None, "backend": "dsh",
                    "generation": generation,
                })
                with mock.patch.object(adapter, "IS_WINDOWS", windows), \
                        mock.patch.object(adapter, "signal", signum_module), \
                        mock.patch.object(adapter, "platform_can_force_stop", lambda: capable), \
                        mock.patch.object(
                            adapter, "terminate_tree",
                            lambda pid, signum, identity="": attempts.append(signum) or True
                        ), \
                        mock.patch.object(
                            adapter, "run_quiet", lambda argv: attempts.append(argv) or 0
                        ), \
                        mock.patch.object(adapter, "POLL_SECONDS", 0), \
                        contextlib.redirect_stderr(io.StringIO()):
                    return adapter.terminate_agent(StandInProcess(), op, "fake:1")

        for windows, module in (
            (True, FakeSignal),
            (False, types.SimpleNamespace(SIGTERM=15, SIGKILL=9)),
        ):
            with self.subTest(windows=windows):
                self.assertEqual(run_case(windows, module, False), (adapter.KILL_EXIT, None))
                self.assertEqual(attempts, [], "no destructive call without a verified primitive")
        # With the capability the escalation really runs, and the numbers it reads
        # are the platform's own: TERM, then KILL.
        code, survivors = run_case(False, types.SimpleNamespace(SIGTERM=15, SIGKILL=9), True)
        self.assertEqual(code, adapter.KILL_EXIT)
        self.assertIsNone(survivors, "an unverifiable surrogate names no completion")
        self.assertEqual(attempts[:2], [15, 9])

    def test_a_failing_taskkill_is_reported_not_assumed(self):
        """`taskkill` is disabled as a stop path, so nothing is run or claimed (P2)."""
        attempts = []
        err = io.StringIO()
        with mock.patch.object(adapter, "IS_WINDOWS", True), \
                mock.patch.object(
                    adapter, "run_quiet", lambda argv: attempts.append(argv) or 0
                ), \
                contextlib.redirect_stderr(err):
            self.assertFalse(adapter.terminate_tree(4321, 0, "win:v1:1:4321"))
        self.assertEqual(attempts, [], "no tree-termination command is issued")
        self.assertIn("no verified process-instance termination primitive", err.getvalue())

    def test_kill_tree_leaves_an_unverified_pid_alone(self):
        """The forced-kill path fails closed instead of signalling a stranger (A5)."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            generation = adapter.new_nonce()
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "stranger", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso(), "backend": "dsh", "generation": generation})
            victim = self.spawn(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            adapter.write_json(str(run_dir / "lock"), {
                "pid": victim.pid, "agent_pid": None, "pid_identity": "linux:v2:nope",
                "backend": "dsh", "generation": generation})
            op = adapter.operation_of(str(run_dir))
            with mock.patch.object(adapter, "POLL_SECONDS", 0.01), \
                    contextlib.redirect_stderr(io.StringIO()):
                forced = adapter.kill_tree(op)
            self.assertFalse(forced)
            self.assertIsNone(victim.poll(), "an unverified pid must not be signalled")

    def test_a_held_finalize_claim_stops_a_reader_from_finalizing(self):
        """The lifecycle mutex is a kernel lock a competitor cannot delete (A6/L2).

        Held by another holder, it denies the mutation outright and no partial
        write happens; its file's age transfers nothing (a backdated lock is still
        a held lock); and the holder releasing it lets the same reader settle the
        run without the file ever being unlinked or replaced.
        """
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "events.ndjson").write_text("", encoding="utf-8")
            generation = adapter.new_nonce()
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "claim", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso(), "backend": "dsh", "generation": generation})
            op = adapter.operation_of(str(run_dir))
            lock_path = adapter.lifecycle_lock_path(op.root, op.slug)
            holder = open(lock_path, "a+b")
            try:
                if IS_WINDOWS:
                    import msvcrt

                    holder.seek(0)
                    msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                inode = os.stat(lock_path).st_ino
                # Age does not transfer ownership: a backdated lock is held.
                stale = time.time() - 3600
                os.utime(lock_path, (stale, stale))
                before = (run_dir / "state.json").read_bytes()
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    returned = adapter.finalize(
                        str(run_dir), -1, recovered=True, expect_generation=generation
                    )
                self.assertFalse((run_dir / "finalized").exists())
                self.assertEqual(returned.get("state"), "running")
                self.assertIn("another process", err.getvalue())
                self.assertEqual(before, (run_dir / "state.json").read_bytes())
                with contextlib.redirect_stderr(io.StringIO()):
                    adapter.finalize(
                        str(run_dir), -1, recovered=True, expect_generation=generation,
                        claim_wait=0.3,
                    )
                self.assertFalse((run_dir / "finalized").exists())
                self.assertEqual(inode, os.stat(lock_path).st_ino, "the lock file is never replaced")
            finally:
                holder.close()
            # Released: the next reader settles the same run, same inode.
            state = adapter.finalize(
                str(run_dir), -1, recovered=True, expect_generation=generation, claim_wait=1.0
            )
            self.assertEqual(state["state"], "failed", state)
            self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "-1")
            self.assertEqual(inode, os.stat(lock_path).st_ino)

    def test_cmd_arguments_that_cmd_would_split_are_refused(self):
        """A `&` in a session id must never become a second command (A4)."""
        self.assertEqual(
            adapter.cmd_command_line(["--session-id", "safe-id_9"]),
            "--session-id safe-id_9",
        )
        for bad in ("a&b", "a|b", "a b", "a%b", 'a"b', "a\r\nb", "a^b"):
            with self.subTest(argument=bad):
                with self.assertRaises(ValueError):
                    adapter.cmd_command_line(["dsh", "--session-id", bad])
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / "dsh.cmd"
            shim.write_text("@echo off\r\n", encoding="utf-8")
            with mock.patch.object(adapter, "IS_WINDOWS", True), \
                    mock.patch.dict(os.environ, {"COMSPEC": "cmd.exe"}):
                # No real executable beside the shim: cmd is required, and an
                # argument it would re-parse is refused, never serialized.
                with self.assertRaises(ValueError):
                    adapter.agent_command(str(shim), ["--session-id", "a&b"])
                command = adapter.agent_command(str(shim), ["--session-id", "safe-id"])
                self.assertEqual(command[0:4], ["cmd.exe", "/d", "/s", "/c"])
                self.assertEqual(command[4], f"{shim} --session-id safe-id")
                # The real executable beside the shim takes cmd out of the chain,
                # so the same argument is just an argv element again.
                real = Path(tmp) / "dsh.exe"
                real.write_bytes(b"stub")
                direct = adapter.agent_command(str(shim), ["--session-id", "a&b"])
                self.assertEqual(direct, [str(real), "--session-id", "a&b"])

    def test_a_generated_replay_script_quotes_what_cmd_would_parse(self):
        """The replay `.cmd` must quote metacharacters and refuse `%` (A4)."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            argv = [str(Path(tmp) / "python.exe"), "arg with space", "a&b", "plain"]
            with mock.patch.object(adapter, "IS_WINDOWS", True):
                adapter.write_replay(str(run_dir), {
                    "name": "replay", "argv": argv, "cwd": tmp, "agent_argv": []})
            script = (run_dir / "run.cmd").read_text(encoding="utf-8")
            line = [row for row in script.splitlines() if "a&b" in row][0]
            self.assertIn('"a&b"', line)
            self.assertIn('"arg with space"', line)
            self.assertIn("plain", line)
            self.assertIn(f"cd /d {adapter.batch_argument(tmp)}", script)
            with mock.patch.object(adapter, "IS_WINDOWS", True):
                with self.assertRaises(ValueError):
                    adapter.write_replay(str(run_dir), {
                        "name": "replay", "argv": ["a%b"], "cwd": tmp, "agent_argv": []})

    def test_completion_mapping_is_exhaustive(self):
        """The real finalizer, one temp run directory per case."""
        for index, (exit_code, reason, expected) in enumerate(
            (
                (0, "completed", "done"),
                (0, "aborted", "failed"),
                (0, None, "failed"),
                (1, None, "failed"),
                (1, "completed", "failed"),
                (143, None, "killed"),
                (137, None, "killed"),
                (130, "completed", "killed"),
            )
        ):
            with self.subTest(exit=exit_code, reason=reason):
                with tempfile.TemporaryDirectory() as tmp:
                    run_dir = Path(tmp)
                    events = []
                    if reason is not None:
                        events.append(
                            {"type": "final", "sessionId": "s", "reason": {"kind": reason},
                             "text": "the answer"}
                        )
                    (run_dir / "events.ndjson").write_text(
                        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
                    )
                    (run_dir / "state.json").write_text(
                        json.dumps({"name": f"map-{index}", "state": "running", "exit": None,
                                    "cwd": tmp, "started": adapter.now_iso(),
                                    "backend": "dsh", "generation": adapter.new_nonce()}),
                        encoding="utf-8",
                    )
                    generation = adapter.strict_generation(
                        adapter.read_state_file(str(run_dir))
                    )
                    state = adapter.finalize(
                        str(run_dir), exit_code, expect_generation=generation
                    )
                    self.assertEqual(state["state"], expected, state)
                    self.assertEqual(state["exit"], exit_code)
                    self.assertEqual(
                        (run_dir / "finalized").read_text(encoding="utf-8"), str(exit_code)
                    )
                    self.assertEqual((run_dir / "answer.md").read_text(encoding="utf-8"),
                                     "the answer" if reason is not None else "")

    def test_stale_recovery_is_the_only_path_to_exit_minus_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "events.ndjson").write_text(
                json.dumps({"type": "session", "sessionId": "s"}) + "\n", encoding="utf-8"
            )
            (run_dir / "state.json").write_text(
                json.dumps({"name": "stale", "state": "running", "exit": None, "cwd": tmp,
                            "backend": "dsh",
                            "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                            "generation": adapter.new_nonce()}),
                encoding="utf-8",
            )
            state, recovered = adapter.effective_state(str(run_dir))
            self.assertTrue(recovered)
            self.assertEqual((state["state"], state["exit"]), ("failed", -1), state)
            self.assertTrue(state["stale_recovered"])
            before = (run_dir / "state.json").read_bytes()
            again, recovered_again = adapter.effective_state(str(run_dir))
            self.assertFalse(recovered_again)
            self.assertEqual(before, (run_dir / "state.json").read_bytes())

    def test_a_terminal_state_without_a_marker_is_repaired_from_its_commit(self):
        """A crash between the commit and the marker leaves a committed verdict.

        The authority is the atomic `state.json` replacement; the marker is
        written after it, for compatibility. A reader that finds the commit
        without the marker writes only the marker — the committed bytes are not
        rewritten — and it never treats a state that looks terminal *without* a
        commit as a verdict: that is uncommitted data.
        """
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "events.ndjson").write_text(
                json.dumps({"type": "final", "sessionId": "s", "reason": {"kind": "completed"},
                            "text": "done"}) + "\n",
                encoding="utf-8",
            )
            (run_dir / "state.json").write_text(
                json.dumps({"name": "repaired", "state": "running", "exit": None, "cwd": tmp,
                            "backend": "dsh",
                            "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                            "generation": adapter.new_nonce()}),
                encoding="utf-8",
            )
            # A verdict with no commit is not a verdict: nothing is written for it.
            legacy = dict(adapter.read_state_file(str(run_dir)), state="killed", exit=143)
            adapter.write_json(str(run_dir / "state.json"), legacy)
            before = (run_dir / "state.json").read_bytes()
            state, recovered = adapter.effective_state(str(run_dir))
            self.assertFalse(recovered)
            self.assertEqual(before, (run_dir / "state.json").read_bytes())
            self.assertFalse((run_dir / "finalized").exists())
            self.assertEqual(adapter.lifecycle_of(str(run_dir), state), adapter.LIFECYCLE_GONE)
            # A committed verdict with no marker is settled: the marker is repaired
            # and the committed bytes stay exactly as they are.
            op = adapter.operation_of(str(run_dir), state)
            with contextlib.redirect_stderr(io.StringIO()):
                committed = adapter.finalize(
                    str(run_dir), adapter.KILL_EXIT, expect_generation=op.generation,
                    stop_proven=True,
                )
            self.assertEqual(committed["state"], "killed", committed)
            marker = run_dir / "finalized"
            self.assertEqual(marker.read_text(encoding="utf-8"), str(adapter.KILL_EXIT))
            marker.unlink()
            committed_bytes = (run_dir / "state.json").read_bytes()
            state, recovered = adapter.effective_state(str(run_dir))
            self.assertTrue(recovered, "the missing marker is repaired")
            self.assertEqual(committed_bytes, (run_dir / "state.json").read_bytes())
            self.assertEqual(
                marker.read_text(encoding="utf-8"), str(adapter.KILL_EXIT),
                "the repaired marker carries the committed exit code",
            )
            self.assertEqual(adapter.lifecycle_of(str(run_dir), state), adapter.LIFECYCLE_TERMINAL)
            # And a committed verdict is never rewritten by a later reader.
            again, recovered_again = adapter.effective_state(str(run_dir))
            self.assertFalse(recovered_again)
            self.assertEqual(committed_bytes, (run_dir / "state.json").read_bytes())

    def test_a_final_with_a_null_reason_is_not_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = Path(tmp) / "events.ndjson"
            events.write_text(
                json.dumps({"type": "final", "sessionId": "s", "reason": None, "text": "t"}) + "\n",
                encoding="utf-8",
            )
            summary = adapter.summarize(tmp, str(events))
            self.assertIsNone(summary["final_reason"])
            self.assertEqual(summary["answer"], "t")
            self.assertEqual(summary["answer_source"], "final")

    def test_the_adapter_reuses_the_shared_bounded_writer(self):
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("events-writer.py", source)
        self.assertIn("load_writer", source)
        # The bound has one implementation: this adapter does not re-implement the
        # compaction and its marker.
        self.assertNotIn("def _compact", source)
        self.assertNotIn("dropped_lines", source)

    def test_summarize_reads_the_dsh_session_and_usage_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = Path(tmp) / "events.ndjson"
            events.write_text(
                "\n".join(
                    json.dumps(event)
                    for event in (
                        {"type": "session", "sessionId": "session-abc", "cwd": "/w"},
                        {"type": "status", "turn": 1, "step": 0, "phase": "turn_start",
                         "usage": {"inputTokens": 10, "outputTokens": 1, "totalTokens": 11,
                                   "cacheReadTokens": 2}},
                        {"type": "tool_call", "callId": "c1", "tool": "bash", "input": {}},
                        {"type": "tool_result", "callId": "c1", "status": "completed",
                         "result": "ok"},
                        {"type": "text", "text": "committed text"},
                        {"type": "status", "turn": 1, "step": 1, "phase": "turn_end"},
                        {"type": "final", "sessionId": "session-abc",
                         "reason": {"kind": "completed"}, "text": "the answer"},
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            summary = adapter.summarize(tmp, str(events))
            self.assertEqual(summary["session_id"], "session-abc")
            self.assertEqual(summary["answer"], "the answer")
            self.assertEqual(summary["final_reason"], "completed")
            self.assertEqual(summary["turns"], 1)
            self.assertEqual(summary["tool_calls"], 1)
            self.assertEqual(summary["usage"]["total_tokens"], 11)
            self.assertFalse(summary["events_truncated"])
            self.assertEqual(summary["events_bytes_total"], summary["events_bytes"])

    def test_gdd_launch_shape_is_accepted(self):
        """gdd.py calls `start --name … --prompt … --cwd … [--model|--thinking|--max-time]`."""
        parser = adapter.build_parser()
        args = parser.parse_args(
            ["start", "--name", "repo-goal-stage", "--prompt", "/p.md", "--cwd", "/w",
             "--max-time", "600"]
        )
        self.assertEqual(args.func, adapter.cmd_start)
        self.assertEqual(args.max_time, "600")
        self.assertEqual(args.name, "repo-goal-stage")
        self.assertEqual(parser.parse_args(["list"]).func, adapter.cmd_list)
        self.assertEqual(parser.parse_args(["status"]).func, adapter.cmd_status)
        self.assertEqual(parser.parse_args(["status", "slug"]).func, adapter.cmd_status)
        self.assertEqual(parser.parse_args(["result", "slug"]).func, adapter.cmd_result)
        self.assertEqual(parser.parse_args(["answer", "slug"]).func, adapter.cmd_answer)
        self.assertEqual(parser.parse_args(["tail", "slug", "5"]).func, adapter.cmd_tail)
        self.assertEqual(parser.parse_args(["kill", "slug"]).func, adapter.cmd_kill)

    # -- round-6 pins, unit level -------------------------------------------

    def test_the_stop_outcome_has_three_distinct_values(self):
        """R1: proven gone, survivors known and enumeration failed are never equal."""

        class StandIn:
            pid = os.getpid()

            def poll(self):
                return None

        def run_case(capable, settled, terminated, members):
            with tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp)
                generation = adapter.new_nonce()
                adapter.write_json(str(run_dir / "state.json"), {
                    "name": "outcome", "state": "running", "exit": None, "cwd": tmp,
                    "started": adapter.now_iso(), "backend": "dsh",
                    "generation": generation,
                })
                op = adapter.operation_of(str(run_dir))
                calls = []
                with mock.patch.object(adapter, "platform_can_force_stop", lambda: capable), \
                        mock.patch.object(
                            adapter, "liveness_of",
                            lambda pid: adapter.GONE if settled else adapter.LIVE
                        ), \
                        mock.patch.object(adapter, "group_live", lambda pgid: False), \
                        mock.patch.object(adapter, "process_group", lambda pid: 0), \
                        mock.patch.object(
                            adapter, "terminate_tree",
                            lambda pid, signum, identity="": calls.append(signum) or terminated
                        ), \
                        mock.patch.object(adapter, "surviving_members", lambda *a: members), \
                        mock.patch.object(adapter, "POLL_SECONDS", 0), \
                        contextlib.redirect_stderr(io.StringIO()):
                    return adapter.terminate_agent(StandIn(), op, "linux:v2:x"), calls

        # No verified handle primitive: nothing is even attempted.
        self.assertEqual(run_case(False, False, False, None)[0], (adapter.KILL_EXIT, None))
        self.assertEqual(run_case(False, False, False, None)[1], [])
        # Proven gone: the empty list, the only value a terminal state may accept.
        self.assertEqual(run_case(True, True, True, None)[0], (adapter.KILL_EXIT, []))
        # Not stopped: the survivors are named when they can be read…
        named = [(4242, "linux:v2:1", 4242)]
        self.assertEqual(run_case(True, False, False, named)[0], (adapter.KILL_EXIT, named))
        # …and `None`, never `[]`, when the enumeration failed or came back empty
        # while nothing was proven gone.
        self.assertEqual(run_case(True, False, False, None)[0], (adapter.KILL_EXIT, None))
        self.assertEqual(run_case(True, False, False, [])[0], (adapter.KILL_EXIT, None))

    def test_a_run_that_stopped_without_enumeration_is_never_recovered_as_failed(self):
        """R1: a failed enumeration is not evidence, so a reader leaves it stopping.

        Two shapes of "the enumeration cannot be trusted": a record that says so
        (`survivors_complete: false`, which is what a platform without a group
        table or a failed inspection writes) and a live enumeration that fails
        now. Neither may be read as disappearance, so no reader settles the run,
        and the slug stays occupied.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run-root"
            run_dir = root / adapter.date_stamp() / "unproven"
            run_dir.mkdir(parents=True)
            (run_dir / "events.ndjson").write_text("", encoding="utf-8")
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "unproven", "state": "running", "exit": None, "cwd": tmp,
                "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "backend": "dsh", "stopping": True, "survivors_complete": False,
                "survivors": [],
                "generation": adapter.new_nonce(),
            })
            for shape in ("recorded-unknown", "failed-now", "unreadable-table"):
                with self.subTest(shape=shape):
                    patches = []
                    if shape == "failed-now":
                        patches.append(mock.patch.object(
                            adapter, "stop_survivors", lambda *a, **k: None
                        ))
                    elif shape == "unreadable-table":
                        patches.append(mock.patch.object(
                            adapter, "group_member_pids", lambda pgid: None
                        ))
                    with contextlib.ExitStack() as stack:
                        for patch in patches:
                            stack.enter_context(patch)
                        with mock.patch.object(adapter, "run_alive", lambda run, state=None: False), \
                                contextlib.redirect_stderr(io.StringIO()):
                            state, recovered = adapter.effective_state(str(run_dir))
                    self.assertFalse(recovered, state)
                    self.assertEqual(state["state"], "running", state)
                    self.assertFalse((run_dir / "finalized").exists())
                    self.assertFalse((run_dir / "exit.code").exists())
            # And the slug stays occupied: a probe that found nothing is not a
            # probe that proved nothing is there.
            with mock.patch.object(adapter, "run_alive", lambda run, state=None: False):
                occupant, _occupant_state = adapter.occupying_run(str(root), "unproven")
            self.assertEqual(occupant, str(run_dir))

    def test_a_terminal_write_is_bound_to_the_run_generation(self):
        """R3: `finalize` refuses a run that replaced the one the caller decided about.

        The binding is mandatory: there is no unbound terminal write, and a caller
        that passes the wrong generation writes nothing at all.
        """
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "events.ndjson").write_text("", encoding="utf-8")
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "generation", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso(), "backend": "dsh", "generation": "one",
            })
            decided = adapter.generation_of(str(run_dir))
            self.assertEqual(decided, "one")
            # A starter replaces the path with a new, live generation.
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "generation", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso(), "backend": "dsh", "generation": "two",
            })
            before = (run_dir / "state.json").read_bytes()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                returned = adapter.finalize(
                    str(run_dir), -1, recovered=True, expect_generation=decided
                )
            self.assertEqual(returned.get("generation"), "two", returned)
            self.assertIn("different run", err.getvalue())
            self.assertFalse((run_dir / "finalized").exists())
            self.assertFalse((run_dir / "answer.md").exists())
            self.assertFalse((run_dir / "exit.code").exists())
            self.assertEqual(before, (run_dir / "state.json").read_bytes())
            # The generation is mandatory: there is no unbound terminal write, and
            # a record that names no generation cannot be mutated at all.
            with self.assertRaises(TypeError):
                adapter.finalize(str(run_dir), -1)
            with contextlib.redirect_stderr(err := io.StringIO()):
                unnamed = adapter.finalize(str(run_dir), -1, expect_generation="")
            self.assertEqual(unnamed.get("state"), "running", unnamed)
            self.assertIn("cannot confirm the run generation", err.getvalue())
            self.assertFalse((run_dir / "finalized").exists())
            # The generation the caller decided about finalizes it.
            returned = adapter.finalize(
                str(run_dir), -1, recovered=True, expect_generation="two"
            )
            self.assertEqual(returned["state"], "failed")
            self.assertEqual(returned["terminal_record"]["generation"], "two")
            self.assertTrue((run_dir / "finalized").exists())

    def test_the_runner_handshake_is_single_use(self):
        """R4: only the runner `start` spawned can present the credential (G6).

        The credential carries both halves of the handshake and is consumed by the
        real `runner_main` entry — not by the test deleting the file: after a real
        authentication the file is gone and the same credential is refused, and a
        credential minted for one generation is refused by a run recording another.
        """
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            generation = adapter.new_nonce()
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "handshake", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso(), "backend": "dsh", "generation": generation,
            })
            adapter.write_json(str(run_dir / adapter.SPAWN_TOKEN_FILE),
                               {"generation": generation, "token": adapter.new_nonce()})
            op = adapter.operation_of(str(run_dir))
            recorded_generation, token = adapter.spawn_credentials(op)
            self.assertEqual(recorded_generation, generation)
            credential = f"{generation}:{token}"
            with mock.patch.dict(os.environ, {adapter.RUNNER_TOKEN_ENV: credential}, clear=False):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        adapter.consume_spawn_credential_locked(op), generation
                    )
                # Consumed by that authentication: the credential is refused now.
                self.assertFalse((run_dir / adapter.SPAWN_TOKEN_FILE).exists())
                self.assertIsNone(os.environ.get(adapter.RUNNER_TOKEN_ENV))
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(adapter.consume_spawn_credential_locked(op), "")
            # A credential for another generation is refused, and is not consumed.
            adapter.write_json(str(run_dir / adapter.SPAWN_TOKEN_FILE),
                               {"generation": generation, "token": "minted-for-elsewhere"})
            with mock.patch.dict(
                os.environ, {adapter.RUNNER_TOKEN_ENV: f"{generation}:other"}, clear=False
            ):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(adapter.consume_spawn_credential_locked(op), "")
            self.assertTrue((run_dir / adapter.SPAWN_TOKEN_FILE).exists())
            # …and so is one minted for this token but another run generation.
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "handshake", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso(), "backend": "dsh",
                "generation": adapter.new_nonce(),
            })
            with mock.patch.dict(os.environ, {adapter.RUNNER_TOKEN_ENV: credential}, clear=False):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(adapter.consume_spawn_credential_locked(op), "")
            self.assertTrue((run_dir / adapter.SPAWN_TOKEN_FILE).exists())
            # The agent's environment never carries the credential.
            with mock.patch.dict(
                os.environ, {adapter.RUNNER_TOKEN_ENV: "leak"}, clear=False
            ):
                self.assertNotIn(adapter.RUNNER_TOKEN_ENV, adapter.child_env())

    def test_the_lifecycle_words_are_the_documented_five(self):
        """R5: one vocabulary, and `list`'s single word uses all of it."""
        self.assertEqual(adapter.LIFECYCLE_TERMINAL, "terminal")
        self.assertEqual(adapter.LIFECYCLE_LIVE, "live")
        self.assertEqual(adapter.LIFECYCLE_STOPPING_KNOWN, "stopping (survivors known)")
        self.assertEqual(adapter.LIFECYCLE_STOPPING_UNKNOWN, "stopping (enumeration failed)")
        self.assertEqual(adapter.LIFECYCLE_UNKNOWN, "unknown (no state)")
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn('"stopping(survivors-known)"', source)
        self.assertIn('"stopping(enumeration-failed)"', source)
        self.assertIn('"unknown(no-state)"', source)

    def test_the_documents_state_the_same_exit_mapping(self):
        """R6: goal, transport and the record state the full exit→state mapping.

        The operating-method skill (`skills/dsh-headless-gdd/SKILL.md`) states the
        two endings an operator meets there — `killed`/143 for the adapter's own
        stop and `failed`/−1 with `stale_recovered` for an unfinalized death — and
        does not contradict the full mapping; it is outside this round's four-file
        scope, so the signal-convention clause is pinned where the round can write.
        """
        documents = {
            "goal": REPO / "docs/goals/archive/2026-11-15-dsh-headless-launcher.md",
            "transport": REPO / "skills/gdd/references/transport.md",
            "record": REPO / "docs/evidence/2026-11-15-dsh-headless-launcher.md",
        }
        for name, path in documents.items():
            with self.subTest(document=name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("`130`/`137`/`143`", text)
                self.assertIn("`-2`/`-9`/`-15`", text)
                self.assertIn("stale_recovered", text)
                self.assertIn("`killed`", text)
                # Associations, not keyword presence: each state's own entry carries
                # its own conditions (see
                # `test_q3_the_document_mapping_check_catches_a_swapped_mapping`).
                check_exit_mapping(exit_mapping_entries(text), name)
        skill = (REPO / "skills/dsh-headless-gdd/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("A stopped run is `killed` with exit 143", skill)
        self.assertIn("`failed` with exit −1 and `stale_recovered: true`", skill)

    def test_transport_and_the_skill_state_the_same_isolation_precondition(self):
        """R6: the write boundary is the permission policy, not the cwd."""
        transport = (REPO / "skills/gdd/references/transport.md").read_text(encoding="utf-8")
        skill = (REPO / "skills/dsh-headless-gdd/SKILL.md").read_text(encoding="utf-8")
        for name, text in (("transport.md", transport), ("SKILL.md", skill)):
            with self.subTest(document=name):
                self.assertIn("enforces a sandbox", text)
                self.assertIn("re-confirm", text)
                self.assertIn("working directory", text)
        self.assertNotIn("keeps the sandbox at the stage's worktree", transport)

    def test_the_record_does_not_claim_a_substituted_provider_route(self):
        """R6/D1: the record says what the smoke's artifacts support, and no more.

        The author's smoke ran under a scratch `DSH_HOME`; which provider route
        that copy reached is not evidence this repository holds, so the record must
        mark it unverified and must not claim either way. The check is itself
        mutation-checked on copies.
        """
        def check_route_honesty(text, source):
            assert "substitute provider route" not in text, source
            assert "default route's key is not exposed" not in text, source
            assert "profile's own configuration" in text, source
            assert "**not verified" in text, source
            assert "local `ghc` route" in text, source
            assert "canonical evidence for the route question" in text, source

        record_path = REPO / "docs/evidence/2026-11-15-dsh-headless-launcher.md"
        record = record_path.read_text(encoding="utf-8")
        check_route_honesty(record, "the record")
        for name, mutated in {
            "the unverified mark removed": record.replace("**not verified", "**verified"),
            "the route conflict dropped": record.replace(
                "canonical evidence for the route question", "evidence for the route"
            ),
        }.items():
            with self.subTest(mutation=name):
                with self.assertRaises(AssertionError):
                    check_route_honesty(mutated, f"the record ({name})")


EXIT_MAPPING_ENTRY = re.compile(r"^\s*-\s*`(done|killed|failed)`(.*)$")
EXIT_MAPPING_REQUIREMENTS = {
    # Each state's entry must carry that state's own conditions: a swapped or
    # truncated mapping fails here even though every keyword still appears
    # somewhere in the document.
    "done": ("exit 0", "final", "completed"),
    "killed": ("130", "137", "143", "-2", "-9", "-15", "raw"),
    "failed": ("exit 0", "completed", "non-signal", "-1", "stale_recovered"),
}
EXIT_MAPPING_FORBIDDEN = {
    "done": ("stale_recovered",),
    "killed": ("stale_recovered",),
    "failed": ("130", "137"),
}


def exit_mapping_entries(text):
    """{state: entry text} for a document's `- \\`state\\` — …` mapping bullets.

    A state's entry continues on the following lines and is merged with any later
    bullet naming the same state (the mapping may split one state into two
    bullets), so the check sees everything the document says about that state.
    """
    entries = {}
    current = None
    for line in text.splitlines():
        match = EXIT_MAPPING_ENTRY.match(line)
        if match:
            current = match.group(1)
            entries[current] = entries.get(current, "") + " " + match.group(2)
            continue
        if current and line.strip() and not line.lstrip().startswith("- "):
            entries[current] += " " + line.strip()
        elif not line.strip():
            current = None
    return entries


def exit_mapping_blocks(text):
    """{state: [(start, end)]} character spans of every bullet naming that state.

    The spans are what a mutation needs: a state's whole entry can be replaced by
    another state's entry text without guessing at its wording.
    """
    spans = {}
    current = None
    offset = 0
    for line in text.splitlines(keepends=True):
        match = EXIT_MAPPING_ENTRY.match(line.rstrip("\n"))
        if match:
            current = match.group(1)
            spans.setdefault(current, []).append([offset, offset + len(line)])
        elif current and line.strip() and not line.lstrip().startswith("- "):
            spans[current][-1][1] = offset + len(line)
        elif not line.strip():
            current = None
        offset += len(line)
    return {state: [tuple(span) for span in state_spans] for state, state_spans in spans.items()}


def swap_exit_mapping(text, first, second):
    """A copy of `text` with `first`'s entry text replaced by `second`'s."""
    spans = exit_mapping_blocks(text)
    start, end = spans[first][0]
    second_start, second_end = spans[second][0]
    return text[:start] + text[second_start:second_end] + text[end:]


def edit_exit_mapping_entry(text, state, old, new=""):
    """`text` with the first `old` inside `state`'s own entry replaced.

    Scoped to the entry's span, so a phrase that also appears elsewhere in the
    document cannot absorb the mutation and leave the mapping untouched.
    """
    spans = exit_mapping_blocks(text)
    if state not in spans:
        return text
    start, end = spans[state][0]
    entry = text[start:end]
    if old not in entry:
        return text
    return text[:start] + entry.replace(old, new, 1) + text[end:]


def check_exit_mapping(entries, source):
    """Raise AssertionError unless every state's entry carries its own conditions."""
    for state, required in EXIT_MAPPING_REQUIREMENTS.items():
        text = entries.get(state, "")
        if not text:
            raise AssertionError(f"{source}: no `{state}` entry in the exit→state mapping")
        missing = [token for token in required if token not in text]
        if missing:
            raise AssertionError(
                f"{source}: the `{state}` entry is missing {missing!r}: {text.strip()!r}"
            )
        forbidden = [token for token in EXIT_MAPPING_FORBIDDEN.get(state, ()) if token in text]
        if forbidden:
            raise AssertionError(
                f"{source}: the `{state}` entry carries another state's condition {forbidden!r}"
            )
    return entries


class HardeningRuleTests(ProcessFixtures):
    """The hardening round's rules, each pinned by a deterministic interleaving.

    Every interleaving here is explicit — a barrier, a pipe, or an insertion hook
    that runs *inside* the code under test — and every spawned process is
    registered for cleanup the moment it exists. Nothing depends on how a
    scheduler happens to order two threads.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dsh-rule."))
        self.addCleanup(shutil.rmtree, str(self.tmp), ignore_errors=True)
        self.root = self.tmp / "runs"

    # -- helpers ------------------------------------------------------------

    def staging(self, slug, *, date=None, generation="auto", **fields):
        """A run of this route under `self.root`, with the metadata a mutation needs.

        `generation="auto"` records a fresh token (what every run the adapter
        writes carries); `generation=None` stages a legacy record without one.
        """
        run_dir = self.root / (date or adapter.date_stamp()) / slug
        run_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "name": slug,
            "state": "running",
            "exit": None,
            "cwd": str(self.tmp),
            "started": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "backend": "dsh",
        }
        token = adapter.new_nonce() if generation == "auto" else generation
        if token:
            state["generation"] = token
        state.update(fields)
        adapter.write_json(str(run_dir / "state.json"), state)
        adapter.write_json(str(run_dir / "lock"), {
            "pid": None,
            "agent_pid": None,
            "backend": "dsh",
            "generation": state.get("generation", ""),
        })
        return run_dir

    def commit_into(self, run_dir, verdict="done", exit_code=0):
        """Give a staged run the terminal commit that makes it finished, not occupying."""
        state = adapter.read_state_file(str(run_dir))
        generation = adapter.strict_generation(state)
        state.update({"state": verdict, "exit": exit_code, "ended": adapter.now_iso()})
        state["terminal_record"] = {
            "version": adapter.TERMINAL_RECORD_VERSION,
            "generation": generation,
            "commit_id": "commit-rule",
            "answer": "",
            "session_id": "",
            "exit": exit_code,
        }
        adapter.write_json(str(run_dir / "state.json"), state)
        adapter.write_marker(str(run_dir / "finalized"), str(exit_code))
        return state

    def replace_with_new_generation(self, run_dir, slug=None, hold_start_claim=True):
        """A controlled writer: put a *new* generation at a run path, as `start` does.

        Takes M — the mutex every mutation needs — and, unless
        `hold_start_claim=False`, S as well: the `False` shape is the
        uncooperative writer that respects the lifecycle mutex but not the start
        claim, which is precisely what an under-M expectation re-check defends
        against. The previous run is moved aside, never deleted. Returns the new
        generation.
        """
        run_dir = Path(run_dir)
        slug = slug or (adapter.read_state_file(str(run_dir)).get("name") or run_dir.name)
        root = adapter.bucket_root(str(run_dir))
        with contextlib.ExitStack() as stack:
            if hold_start_claim:
                self.assertTrue(stack.enter_context(adapter.slug_start_claim(root, slug)))
            self.assertTrue(
                stack.enter_context(adapter.lifecycle_claim(root, slug)),
                "the controlled writer holds M",
            )
            if run_dir.is_dir():
                moved = adapter.move_aside(str(run_dir))
                self.assertTrue(moved, "the previous run is preserved, not deleted")
            run_dir.mkdir(parents=True, exist_ok=True)
            generation = adapter.new_nonce()
            adapter.write_json(str(run_dir / "state.json"), {
                "name": slug,
                "state": "running",
                "exit": None,
                "cwd": str(self.tmp),
                "started": adapter.now_iso(),
                "backend": "dsh",
                "generation": generation,
            })
        return generation

    def snapshot(self, path):
        """Byte snapshot of a tree: exactly what a refused mutation must not change."""
        path = Path(path)
        found = {}
        for entry in sorted(path.rglob("*")):
            if entry.is_file():
                found[str(entry.relative_to(path))] = entry.read_bytes()
        return found

    def child_holder(self, path):
        """A child process holding one lock object through the adapter's own primitive."""
        code = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('child_adapter', sys.argv[1])\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "with mod.stable_lock(sys.argv[2], None) as held:\n"
            "    sys.stdout.write('held\\n' if held else 'refused\\n')\n"
            "    sys.stdout.flush()\n"
            "    sys.stdin.readline()\n"
        )
        process = self.spawn(
            [sys.executable, "-c", code, str(ADAPTER), str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.assertEqual(self.read_line(process), "held")
        return process

    def start_probe(self, root, slug):
        """Whether a *separate process* can complete a start's critical section now.

        The child takes S and then M, exactly as `_start_run_claimed` does, and
        writes nothing.
        """
        code = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('start_probe', sys.argv[1])\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "with mod.slug_start_claim(sys.argv[2], sys.argv[3], 1.0) as claim:\n"
            "    if not claim:\n"
            "        sys.stdout.write('no-claim\\n')\n"
            "        raise SystemExit\n"
            "    with mod.lifecycle_claim(sys.argv[2], sys.argv[3], 0.5) as mutex:\n"
            "        sys.stdout.write('claimed\\n' if mutex else 'no-mutex\\n')\n"
        )
        process = self.spawn(
            [sys.executable, "-c", code, str(ADAPTER), str(root), str(slug)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        try:
            return self.read_line(process, timeout=30.0)
        finally:
            self.reap(process)

    def status_cli(self, slug):
        """The real `status` reader for a run under `self.root`."""
        return subprocess.run(
            [sys.executable, str(ADAPTER), "status", slug],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "DSH_RUN_ROOT": str(self.root)},
        )

    def answer_cli(self, slug):
        return subprocess.run(
            [sys.executable, str(ADAPTER), "answer", slug],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "DSH_RUN_ROOT": str(self.root)},
        )

    # -- L: locks -----------------------------------------------------------

    def test_l1_a_finalization_cannot_be_interleaved_with_a_replacement(self):
        """L1: M covers the whole publication, so no starter can slip inside it.

        The finalizer is paused *inside* its under-M publication; a separate
        process trying to complete a start is refused, and a controlled writer
        cannot land either. Once the publication is done the replacement lands, and
        the old generation's later attempt writes nothing into the new run.
        """
        slug = "l1"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        entered, release = threading.Event(), threading.Event()
        real_publish = adapter._publish_terminal_locked

        def paused_publication(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(60.0), "the test released the publication")
            return real_publish(*args, **kwargs)

        outcome = {}

        def finalize():
            with contextlib.redirect_stderr(io.StringIO()):
                outcome["state"] = adapter.finalize(
                    str(run_dir), -1, expect_generation=op.generation, recovered=True
                )

        worker = threading.Thread(target=finalize, daemon=True)
        with mock.patch.object(adapter, "_publish_terminal_locked", paused_publication):
            worker.start()
            self.assertTrue(entered.wait(60.0), "the finalizer reached its publication")
            # A starter cannot pass M while the publication is in flight, and the
            # run directory has not been touched by anyone else.
            self.assertEqual(self.start_probe(op.root, slug), "no-mutex")
            before = self.snapshot(run_dir)
            self.assertFalse((run_dir / "finalized").exists())
            self.assertEqual(self.snapshot(run_dir), before)
            release.set()
        worker.join(60.0)
        self.assertFalse(worker.is_alive(), "the finalizer finished once released")
        committed = adapter.read_state_file(str(run_dir))
        record = adapter.terminal_snapshot_locked(committed)
        self.assertIsNotNone(record, committed)
        self.assertEqual(record["generation"], op.generation)
        self.assertEqual(record["exit"], -1)
        self.assertEqual(committed["state"], "failed")
        self.assertTrue(committed["stale_recovered"])
        # Now the replacement lands, and the paused generation can no longer write.
        generation = self.replace_with_new_generation(run_dir)
        self.assertNotEqual(generation, op.generation)
        after = self.snapshot(run_dir)
        with contextlib.redirect_stderr(io.StringIO()):
            stale = adapter.finalize(str(run_dir), adapter.KILL_EXIT, expect_generation=op.generation)
        self.assertIsNone(adapter.terminal_snapshot_locked(stale))
        self.assertEqual(self.snapshot(run_dir), after, "the stale finalizer wrote into the new run")
        self.assertEqual(adapter.strict_generation(adapter.read_state_file(str(run_dir))), generation)

    def test_l2_a_held_lock_is_never_taken_by_age(self):
        """L2: ownership is the kernel's, so an ancient lock file is still a lock."""
        slug = "l2-age"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        cases = (
            ("start claim", adapter.start_lock_path(op.root, slug),
             lambda: adapter.slug_start_claim(op.root, slug, 0.0)),
            ("lifecycle mutex", adapter.lifecycle_lock_path(op.root, slug),
             lambda: adapter.lifecycle_claim(op.root, slug, 0.0)),
        )
        for name, path, claim in cases:
            with self.subTest(lock=name):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).touch()
                inode = os.stat(path).st_ino
                holder = self.child_holder(path)
                old = time.time() - 86400 * 30
                os.utime(path, (old, old))
                with claim() as held:
                    self.assertFalse(held, f"{name} was taken from a live holder")
                if os.name != "nt":
                    self.assertEqual(os.stat(path).st_ino, inode, f"{name}'s file was replaced")
                self.reap(holder)
                with claim() as held:
                    self.assertTrue(held, f"{name} is free once its holder is gone")
                if os.name != "nt":
                    self.assertEqual(os.stat(path).st_ino, inode, f"{name}'s file was unlinked")
                    self.assertEqual(os.stat(path).st_mtime, old, "the lock file was rewritten")

    def test_l2_a_lock_io_failure_denies_every_mutation(self):
        """L2: an acquisition that failed denies the mutation, and writes nothing."""
        slug = "l2-io"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        before = self.snapshot(run_dir)
        errors = io.StringIO()
        with mock.patch.object(adapter, "_lock_handle", side_effect=OSError("input/output error")), \
                contextlib.redirect_stderr(errors):
            with adapter.stable_lock(adapter.lifecycle_lock_path(op.root, slug), 0.0) as held:
                self.assertFalse(held)
            self.assertEqual(adapter.update_lock(str(run_dir), note="must not land"), {})
            self.assertFalse(adapter.request_stop(op))
            self.assertEqual(adapter.write_state_op(op, {"note": "must not land"}), {})
            self.assertIsNone(
                adapter.terminal_snapshot_locked(
                    adapter.finalize(str(run_dir), 0, expect_generation=op.generation)
                )
            )
            self.assertEqual(adapter.report_incomplete_stop(op, None, "test"), 1)
        self.assertEqual(self.snapshot(run_dir), before, "a refused mutation wrote something")
        self.assertIn("being mutated by another process", errors.getvalue())

    def test_l3_waits_hold_no_mutex_and_finalization_takes_no_start_claim(self):
        """L3: one lock order — M is released across waits, and is taken after S only."""
        slug = "l3-waits"
        run_dir = self.staging(slug, stopping=True)
        op = adapter.operation_of(str(run_dir))
        # 1. Finalization never needs the start claim: holding S cannot block it.
        holder = self.child_holder(adapter.start_lock_path(op.root, slug))
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                settled = adapter.finalize(
                    str(run_dir), adapter.KILL_EXIT, expect_generation=op.generation,
                    stop_proven=True,
                )
            self.assertIsNotNone(adapter.terminal_snapshot_locked(settled), settled)
        finally:
            self.reap(holder)
        # 2. A wait holds no mutex: while `stop_run` waits for the run's own
        #    finalizer, another process can still pass M.
        other = self.staging("l3-waiter")
        other_op = adapter.operation_of(str(other))
        waiting, release = threading.Event(), threading.Event()
        real_wait = adapter.wait_for_terminal

        def paused_wait(wait_op, seconds):
            waiting.set()
            self.assertTrue(release.wait(60.0), "the test released the wait")
            return real_wait(wait_op, seconds)

        outcome = {}

        def kill():
            with contextlib.redirect_stderr(io.StringIO()):
                outcome["stopped"] = adapter.stop_run(other_op, seconds=1.0)

        worker = threading.Thread(target=kill, daemon=True)
        with mock.patch.object(adapter, "wait_for_terminal", paused_wait):
            worker.start()
            self.assertTrue(waiting.wait(60.0), "the stop reached its wait")
            self.assertEqual(self.start_probe(other_op.root, "l3-other-slug"), "claimed")
            release.set()
        worker.join(60.0)
        self.assertFalse(worker.is_alive())
        # The request was written for this generation, which is what the wait saw.
        request = adapter.read_json(str(other / "stop"), {})
        self.assertEqual(request.get("generation"), other_op.generation)

    def test_l3_same_process_writers_are_serialized(self):
        """L3: two threads of one interpreter never hold the same lock object at once."""
        slug = "l3-threads"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        guard = threading.Lock()
        state = {"inside": 0, "max": 0}
        errors = []
        start = threading.Barrier(2)

        def writer():
            try:
                start.wait(10)
                with adapter.lifecycle_claim(op.root, op.slug, wait=None) as held:
                    if not held:
                        errors.append("refused")
                        return
                    with guard:
                        state["inside"] += 1
                        state["max"] = max(state["max"], state["inside"])
                    time.sleep(0.2)
                    with guard:
                        state["inside"] -= 1
            except Exception as exc:  # reported, not swallowed
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=writer) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(state["max"], 1, "two writers were inside one lock object")

    def linger_run(self, slug):
        """(child, run_dir): a staged live run whose recorded process answers its stop.

        The child watches the `stop` control file, commits the verdict through the
        adapter's own finalizer, and then stays alive (`time.sleep(300)`) until the
        caller reaps it — exactly the moment a committed stop's evidence is still
        unproven. It runs in its own session, so the group it leads vanishes with
        it and the enumeration can reach "nobody left".
        """
        run_dir = self.root / adapter.date_stamp() / slug
        code = (
            "import importlib.util, sys, time\n"
            "spec = importlib.util.spec_from_file_location('linger_adapter', sys.argv[1])\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "run_dir = sys.argv[2]\n"
            "sys.stdout.write('ready\\n')\n"
            "sys.stdout.flush()\n"
            "deadline = time.monotonic() + 30.0\n"
            "while time.monotonic() < deadline:\n"
            "    generation = mod.strict_generation(mod.read_state_file(run_dir))\n"
            "    if generation and mod.stop_request_for(run_dir, generation):\n"
            "        mod.finalize(run_dir, mod.KILL_EXIT, claim_wait=5.0, expect_generation=generation,\n"
            "                     note='the runner observed the stop control file and ended the "
            "agent tree')\n"
            "        break\n"
            "    time.sleep(0.05)\n"
            "sys.stdout.write('committed\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(300)\n"          # the linger: this process is not gone yet
        )
        child = self.spawn(
            [sys.executable, "-c", code, str(ADAPTER), str(run_dir)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.assertEqual(self.read_line(child), "ready")
        run_dir = self.staging(
            slug, pid=child.pid, pid_identity=adapter.process_identity(child.pid) or ""
        )
        return child, run_dir

    def replace_cli(self, slug, **env):
        """The real `start --replace` for `slug`, `/bin/true` as the new agent's CLI."""
        prompt = self.tmp / f"{slug}-prompt.md"
        prompt.write_text("do the thing\n", encoding="utf-8")
        return self.spawn(
            [sys.executable, str(ADAPTER), "start", "--name", slug, "--prompt", str(prompt),
             "--cwd", str(self.tmp), "--replace"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "DSH_RUN_ROOT": str(self.root), "DSH_BIN": "/bin/true", **env},
        )

    def test_l3_a_replace_waits_out_a_stop_that_is_not_settled_yet(self):
        """L3/M: a committed stop whose tree has not vanished yet is waited out.

        Committing a terminal verdict and the stopped tree being gone are two
        events: the process that wrote the verdict is still one of the run's
        recorded processes for a moment, and an enumeration that anchors on it
        answers "unknown" — never "nobody" — while it leaves. A replace that
        sampled that instant once would refuse the very run it just stopped. This
        fixture *is* that moment: a child that watches the `stop` control file,
        commits the verdict through the adapter's own finalizer, and then stays
        alive until this test ends it. While it is alive the replacement must wait
        (its sample is unproven and stays unproven); once the process is reaped the
        tree is conclusively gone and the replacement must land.
        """
        slug = "linger-l3"
        child, run_dir = self.linger_run(slug)
        self.assertTrue(adapter.run_alive(str(run_dir)), "the staged run must be live")
        replacing = self.replace_cli(slug)
        # The stop request is written in the replacement's phase 2; the child
        # answers it with a real terminal commit and *stays alive*, so from here
        # until it is reaped the stop's evidence is unproven.
        self.assertEqual(self.read_line(child), "committed")
        self.assertTrue(
            adapter.run_alive(str(run_dir)), "the committed run still records a live process"
        )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and replacing.poll() is None:
            time.sleep(0.05)
        if replacing.poll() is not None:
            self.fail(
                "start --replace decided while the stopped tree was still unproven "
                f"(exit {replacing.returncode}): {replacing.stderr.read()}"
            )
        # The tree is now conclusively gone; the replacement must land.
        self.reap(child)
        self.assertEqual(
            replacing.wait(timeout=60), 0,
            f"start --replace failed after the tree settled: {replacing.stderr.read()}",
        )
        archived = sorted(run_dir.parent.glob(f"{slug}.prev-*"))
        self.assertEqual(len(archived), 1, archived)
        stopped = json.loads((archived[0] / "state.json").read_text(encoding="utf-8"))
        self.assertEqual((stopped["state"], stopped["exit"]), ("killed", adapter.KILL_EXIT))

    def test_l3_the_settle_wait_is_bounded_and_the_refusal_stands_at_the_bound(self):
        """L3/M: a stop that stays unproven is refused at the bound, never waited on forever.

        The bound is part of the rule: `await_settled_stop` answers `False` while
        the evidence is unproven (here: a recorded process that never exits), and
        the replacement then applies its own under-M check and refuses — with the
        same message — instead of holding `start --replace` open indefinitely.
        `DSH_RUN_SETTLE_WAIT_SECONDS` bounds the wait per install; one second here,
        and this test's own deadline is what an unbounded wait fails against.
        """
        slug = "linger-bound-l3"
        child, run_dir = self.linger_run(slug)
        replacing = self.replace_cli(slug, DSH_RUN_SETTLE_WAIT_SECONDS="1")
        self.assertEqual(self.read_line(child), "committed")
        self.assertTrue(
            adapter.run_alive(str(run_dir)), "the tree must still be unproven at the bound"
        )
        try:
            code = replacing.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.fail("the settle wait never gave up: the refusal must stand at its bound")
        stdout, stderr = replacing.stdout.read(), replacing.stderr.read()
        self.assertEqual(code, 1, stdout + stderr)
        self.assertIn("still has unproven processes", stderr)
        # A refused replacement moved nothing aside and left the run where it was.
        self.assertEqual(sorted(run_dir.parent.glob(f"{slug}.prev-*")), [])
        self.assertTrue(adapter.run_alive(str(run_dir)))
        self.reap(child)

    def test_l4_locks_are_keyed_by_slug_not_by_date_or_root(self):
        """L4: distinct slugs proceed; one slug excludes itself across date buckets."""
        first = self.staging("l4", date="2026-01-01")
        second = self.staging("l4", date="2026-01-02")
        neighbour = self.staging("l4-neighbour", date="2026-01-02")
        first_op = adapter.operation_of(str(first))
        second_op = adapter.operation_of(str(second))
        neighbour_op = adapter.operation_of(str(neighbour))
        self.assertEqual(
            adapter.lifecycle_lock_path(first_op.root, first_op.slug),
            adapter.lifecycle_lock_path(second_op.root, second_op.slug),
            "one slug's mutex must be one object, whatever date bucket holds the run",
        )
        self.assertNotEqual(
            adapter.lifecycle_lock_path(first_op.root, first_op.slug),
            adapter.lifecycle_lock_path(neighbour_op.root, neighbour_op.slug),
        )
        # Held by a child process, the slug's mutex refuses a mutation of the run
        # in the *other* date bucket, while the neighbour's slug is untouched.
        holder = self.child_holder(adapter.lifecycle_lock_path(first_op.root, first_op.slug))
        try:
            before = self.snapshot(second)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(adapter.write_state_op(second_op, {"note": "blocked"}), {})
            self.assertEqual(self.snapshot(second), before)
            self.assertNotEqual(adapter.write_state_op(neighbour_op, {"note": "independent"}), {})
        finally:
            self.reap(holder)
        self.assertIn("independent", adapter.read_state_file(str(neighbour)).get("note", ""))

    def test_l4_a_foreign_run_is_never_mutated(self):
        """L4: another backend's run is readable and nothing else, byte for byte."""
        slug = "l4-foreign"
        run_dir = self.staging(slug, backend="paseo")
        op = adapter.operation_of(str(run_dir))
        before = self.snapshot(run_dir)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(adapter.write_state_op(op, {"note": "not mine"}), {})
            self.assertFalse(adapter.request_stop(op))
            self.assertEqual(adapter.update_lock(str(run_dir), note="not mine"), {})
            self.assertEqual(adapter.report_incomplete_stop(op, None, "test"), 1)
            state, recovered = adapter.effective_state(str(run_dir))
        self.assertFalse(recovered)
        self.assertEqual(state["state"], "running")
        self.assertEqual(self.snapshot(run_dir), before, "a foreign run was written to")
        self.assertIn("not this route", errors.getvalue())
        self.assertEqual(adapter.lifecycle_of(str(run_dir), state), adapter.LIFECYCLE_FOREIGN)
        self.assertEqual(adapter.move_aside(str(run_dir)), "", "a foreign run was moved aside")
        kill = subprocess.run(
            [sys.executable, str(ADAPTER), "kill", slug],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "DSH_RUN_ROOT": str(self.root)},
        )
        self.assertNotEqual(kill.returncode, 0)
        self.assertIn("not this route's", kill.stderr)
        self.assertEqual(self.snapshot(run_dir), before)

    # -- G: generation binding ----------------------------------------------

    def test_g1_a_target_that_changed_between_capture_and_commit_is_refused(self):
        """G1: creation and replacement re-check the target under M before writing.

        Phase 1 captures what the path holds; a controlled writer then changes it
        (absent → present, and this route's generation → another generation). Phase
        3 must refuse: no move by `start`, no spawn, no write into the target.
        """
        prompt = self.tmp / "g1-prompt.md"
        prompt.write_text("do the thing\n", encoding="utf-8")

        def start_once(slug, run_dir):
            args = types.SimpleNamespace(
                name=slug, prompt=str(prompt), cwd=str(self.tmp), replace=False,
                max_time=None, model=None, thinking=None, session_id=None, resume=None,
            )
            return adapter.start_run(
                args, str(run_dir), "/bin/true", False, "", "bypassPermissions",
                "never",
            )

        for shape in ("absent", "this-route"):
            with self.subTest(shape=shape):
                slug = f"g1-{shape}"
                run_dir = self.root / adapter.date_stamp() / slug
                if shape == "this-route":
                    run_dir = self.staging(slug)
                    self.commit_into(run_dir)
                # Phase 1 captures the target under M; the writer lands in the gap
                # between the two M scopes, which is exactly where phase 3 must
                # re-check what the path holds.
                state = {"claims": 0}
                real_claim = adapter.lifecycle_claim

                def claim_with_a_writer_between(root, claim_slug, wait=0.0, _state=state,
                                                _run_dir=run_dir, _slug=slug, _real=real_claim):
                    if not _state.get("replacing"):
                        _state["claims"] += 1
                        if _state["claims"] == 2:
                            _state["replacing"] = True
                            try:
                                _state["replaced"] = self.replace_with_new_generation(
                                    _run_dir, _slug, hold_start_claim=False
                                )
                            finally:
                                _state.pop("replacing", None)
                    return _real(root, claim_slug, wait)

                errors = io.StringIO()
                with mock.patch.object(adapter, "lifecycle_claim", claim_with_a_writer_between), \
                        mock.patch.object(adapter, "spawn_runner") as spawned, \
                        contextlib.redirect_stderr(errors), \
                        self.assertRaises(SystemExit):
                    start_once(slug, run_dir)
                self.assertFalse(spawned.called, "the refused start spawned a runner")
                self.assertEqual(state["claims"], 2, "the start did not re-enter its mutex")
                self.assertTrue(state.get("replaced"), "the controlled writer never ran")
                self.assertIn("changed while run", errors.getvalue())
                self.assertIn("nothing was written", errors.getvalue())
                # The writer's generation is exactly what is at the path now: the
                # refused start moved nothing, spawned nothing and wrote nothing.
                written = adapter.read_state_file(str(run_dir))
                self.assertNotEqual(adapter.strict_generation(written), "")
                if shape == "this-route":
                    self.assertEqual(
                        len(sorted(run_dir.parent.glob(f"{slug}.prev-*"))), 1,
                        "only the controlled writer moved a run aside",
                    )
                self.assertFalse((run_dir / "prompt.md").exists(), "start wrote into the target")
                self.assertFalse((run_dir / "runner.log").exists())

    def test_g2_a_stale_kill_cannot_request_or_wait_against_the_new_run(self):
        """G2: a stop decided about one generation cannot land in its replacement."""
        slug = "g2"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        paused, release = threading.Event(), threading.Event()
        real_request = adapter.request_stop

        def paused_request(request_op):
            paused.set()
            self.assertTrue(release.wait(60.0), "the test released the request")
            return real_request(request_op)

        outcome = {}

        def kill():
            with contextlib.redirect_stderr(io.StringIO()):
                outcome["stopped"] = adapter.stop_run(op, seconds=1.0)

        worker = threading.Thread(target=kill, daemon=True)
        with mock.patch.object(adapter, "request_stop", paused_request):
            worker.start()
            self.assertTrue(paused.wait(60.0), "the kill reached its request")
            generation = self.replace_with_new_generation(run_dir)
            after = self.snapshot(run_dir)
            release.set()
        worker.join(60.0)
        self.assertFalse(worker.is_alive())
        self.assertFalse(outcome["stopped"], "a stale kill reported success")
        self.assertEqual(self.snapshot(run_dir), after, "the stale kill wrote into the new run")
        self.assertFalse((run_dir / "stop").exists(), "a stop request landed in the new run")
        self.assertFalse((run_dir / "finalized").exists())
        self.assertEqual(adapter.strict_generation(adapter.read_state_file(str(run_dir))), generation)

    def test_g3_only_the_runs_own_wellformed_stop_request_is_actionable(self):
        """G3: file existence is not a request; generation and shape are validated."""
        slug = "g3"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        other = adapter.new_nonce()
        adapter.write_json(str(run_dir / "stop"), {
            "generation": other, "request_id": "from-another-run", "by": 1,
        })
        self.assertEqual(adapter.stop_request_for(str(run_dir), op.generation), {})
        adapter.write_text_atomic(str(run_dir / "stop"), "{\"generation\": ")
        self.assertEqual(adapter.stop_request_for(str(run_dir), op.generation), {})
        self.assertEqual(adapter.stop_request_for(str(run_dir), ""), {})
        adapter.write_json(str(run_dir / "stop"), ["not", "an", "object"])
        self.assertEqual(adapter.stop_request_for(str(run_dir), op.generation), {})
        request = {
            "generation": op.generation,
            "request_id": "r1",
            "requested_at": adapter.now_iso(),
            "by": os.getpid(),
        }
        adapter.write_json(str(run_dir / "stop"), request)
        self.assertEqual(adapter.stop_request_for(str(run_dir), op.generation), request)
        # The request must agree with the generation the *state* records too: a
        # request left behind by a replaced run is not actionable for the new one.
        state = adapter.read_state_file(str(run_dir))
        state["generation"] = adapter.new_nonce()
        adapter.write_json(str(run_dir / "state.json"), state)
        self.assertEqual(adapter.stop_request_for(str(run_dir), op.generation), {})
        self.assertTrue((run_dir / "stop").exists(), "a foreign request is never deleted")

    def test_g4_every_escalation_step_reauthorizes_the_generation(self):
        """G4: between TERM and the escalation the generation is checked again."""
        slug = "g4"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        identity = adapter.process_identity(os.getpid())
        self.assertTrue(adapter.identity_is_strong(identity))
        group = adapter.process_group(os.getpid())
        signalled = []
        enumerated = []
        replaced = {"done": False}

        def tree(pid, signum, identity_token="", _signalled=signalled):
            _signalled.append(signum)
            if not replaced["done"]:
                replaced["done"] = True
                self.replace_with_new_generation(run_dir)
            return False

        def members(pid, anchor_identity, anchor_group):
            enumerated.append((pid, anchor_identity, anchor_group))
            return [(pid, anchor_identity, anchor_group)]

        class StandIn:
            pid = os.getpid()

            def poll(self):
                return None

        errors = io.StringIO()
        with mock.patch.object(adapter, "terminate_tree", tree), \
                mock.patch.object(adapter, "surviving_members", members), \
                mock.patch.object(adapter, "platform_can_force_stop", lambda: True), \
                mock.patch.object(adapter, "POLL_SECONDS", 0.0), \
                contextlib.redirect_stderr(errors):
            code, survivors = adapter.terminate_agent(StandIn(), op, identity)
        self.assertEqual(code, adapter.KILL_EXIT)
        self.assertTrue(replaced["done"], "the replacement never ran")
        self.assertEqual(
            signalled, [signal.SIGTERM],
            "a later escalation step signalled after the path was replaced",
        )
        # Whatever the stop reports is anchored on the process instance the
        # operation captured, never on anything the replacement could name.
        self.assertEqual(enumerated, [(os.getpid(), identity, group)])
        self.assertEqual(survivors, [(os.getpid(), identity, group)])
        self.assertIn("different run", errors.getvalue())
        self.assertFalse((run_dir / "stop").exists())
        self.assertEqual(adapter.read_state_file(str(run_dir))["state"], "running")

    def test_g5_every_publisher_is_generation_bound(self):
        """G5: the tracker, the event log and the metadata writers all stop at G2."""
        slug = "g5"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        state = adapter.read_state_file(str(run_dir))
        state["stopping"] = True
        adapter.write_json(str(run_dir / "state.json"), state)
        track, stop = adapter.make_tracker(op, state)
        log = adapter.EventLog(op)
        track(json.dumps({"type": "session", "sessionId": "session-g5"}).encode("utf-8"))
        self.assertEqual((run_dir / "session.id").read_text(encoding="utf-8").strip(), "session-g5")
        generation = self.replace_with_new_generation(run_dir)
        after = self.snapshot(run_dir)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            track(json.dumps({"type": "tool_call", "name": "later"}).encode("utf-8"))
            track(json.dumps({"type": "status", "phase": "turn_end"}).encode("utf-8"))
            self.assertFalse(log.feed(b'{"type":"text","text":"late"}\n'))
            log.finish()
            stop()
            self.assertEqual(adapter.write_state_op(op, {"note": "late"}), {})
        self.assertEqual(self.snapshot(run_dir), after, "a publisher wrote into the new run")
        self.assertEqual(adapter.strict_generation(adapter.read_state_file(str(run_dir))), generation)
        self.assertIn("different run", errors.getvalue())
        # `update_lock(run_dir)` takes no operation: it re-derives one from the
        # state it reads, so it is bound to whatever generation is at the path now
        # and the record it writes says so.
        written = adapter.update_lock(str(run_dir), note="from the current generation")
        self.assertEqual(written.get("generation"), generation)
        self.assertEqual(written.get("note"), "from the current generation")

    def test_g5_a_merge_never_republishes_a_stale_snapshot(self):
        """G5: a publisher merges into the state it reads now, not into its snapshot."""
        slug = "g5-merge"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        snapshot = adapter.read_state_file(str(run_dir))
        track, stop = adapter.make_tracker(op, snapshot)
        # A concurrent stop lands after the tracker took its copy.
        concurrent = adapter.read_state_file(str(run_dir))
        concurrent.update({"stopping": True, "survivors_complete": False, "survivors": []})
        adapter.write_json(str(run_dir / "state.json"), concurrent)
        with contextlib.redirect_stderr(io.StringIO()):
            track(json.dumps({"type": "session", "sessionId": "session-late"}).encode("utf-8"))
        merged = adapter.read_state_file(str(run_dir))
        self.assertEqual(merged["session_id"], "session-late")
        self.assertTrue(merged["stopping"], "the merge republished a stale `running` snapshot")
        self.assertEqual(merged["survivors_complete"], False)
        # The stop evidence survives the merge, and the *stale* copy would not have
        # blocked a commit: the tracker merged into the state it read, not its own.
        self.assertTrue(adapter.survivors_blocking_commit(merged, str(run_dir)))
        self.assertEqual(adapter.survivors_blocking_commit(snapshot, str(run_dir)), "")
        stop()

    def test_g7_recovery_repeats_its_liveness_predicate_under_the_mutex(self):
        """G7: a live owner registered after the decision stops the recovery."""
        slug = "g7"
        run_dir = self.staging(slug)
        owner = self.ignoring_agent()
        identity = adapter.process_identity(owner.pid)
        self.assertTrue(adapter.identity_is_strong(identity))
        calls = {"n": 0}
        held = {}
        real_operation_of = adapter.operation_of

        def register_owner_first(path, state=None, generation=None):
            op = real_operation_of(path, state, generation)
            calls["n"] += 1
            if calls["n"] == 1:
                with adapter.lifecycle_claim(op.root, op.slug) as got_m:
                    self.assertTrue(got_m)
                    current = adapter.read_state_file(str(run_dir))
                    current.update({
                        "pid": owner.pid,
                        "pid_identity": identity,
                        "started": adapter.now_iso(),
                    })
                    adapter.write_json(str(run_dir / "state.json"), current)
                held["owner_written"] = self.snapshot(run_dir)
            return op

        errors = io.StringIO()
        with mock.patch.object(adapter, "operation_of", register_owner_first), \
                contextlib.redirect_stderr(errors):
            state, recovered = adapter.effective_state(str(run_dir))
        self.assertFalse(recovered, state)
        self.assertIsNone(adapter.terminal_snapshot_locked(state))
        self.assertEqual(state["state"], "running")
        self.assertTrue(held["owner_written"], "the live owner was never registered")
        self.assertEqual(self.snapshot(run_dir), held["owner_written"],
                         "the recovery wrote over a live owner")
        self.assertEqual(adapter.lifecycle_of(str(run_dir), state), adapter.LIFECYCLE_LIVE)

    def test_g7_a_committed_recovery_is_never_rewritten(self):
        """G7: re-reading a committed verdict leaves every byte of it alone."""
        slug = "g7-again"
        run_dir = self.staging(slug)
        first, recovered = adapter.effective_state(str(run_dir))
        self.assertTrue(recovered, first)
        self.assertEqual(first["state"], "failed")
        committed = self.snapshot(run_dir)
        for reader in (adapter.effective_state, lambda path: (adapter.read_state_file(path), False)):
            second, again = reader(str(run_dir))
            self.assertFalse(again)
            self.assertEqual(second["terminal_record"]["commit_id"],
                             first["terminal_record"]["commit_id"])
        self.assertEqual(self.snapshot(run_dir), committed)

    def test_g9_a_legacy_record_is_readable_and_can_mutate_nothing(self):
        """G9: a record with no generation is read, and authorizes no mutation."""
        slug = "g9"
        run_dir = self.staging(slug, generation=None, pid=os.getpid())
        op = adapter.operation_of(str(run_dir))
        self.assertEqual(op.generation, "")
        self.assertEqual(adapter.generation_of(str(run_dir)), adapter.generation_of(str(run_dir)))
        self.assertTrue(adapter.generation_of(str(run_dir)), "the readable fallback still names it")
        status = self.status_cli(slug)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("\"state\": \"running\"", status.stdout)
        before = self.snapshot(run_dir)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(adapter.write_state_op(op, {"note": "no"}), {})
            self.assertFalse(adapter.request_stop(op))
            self.assertEqual(adapter.update_lock(str(run_dir), note="no"), {})
            self.assertEqual(adapter.report_incomplete_stop(op, None, "test"), 1)
            self.assertIsNone(
                adapter.terminal_snapshot_locked(
                    adapter.finalize(str(run_dir), 0, expect_generation="")
                )
            )
        self.assertEqual(self.snapshot(run_dir), before, "a legacy record was mutated")
        self.assertIn("cannot confirm the run generation", errors.getvalue())
        kill = subprocess.run(
            [sys.executable, str(ADAPTER), "kill", slug],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "DSH_RUN_ROOT": str(self.root)},
        )
        self.assertNotEqual(kill.returncode, 0)
        self.assertIn("cannot confirm the run generation", kill.stderr)
        self.assertEqual(self.snapshot(run_dir), before)


    # -- T: terminal publication --------------------------------------------

    def test_t1_death_at_each_publication_boundary_leaves_one_verdict(self):
        """T1: the commit is one replacement; before it, nothing is a verdict.

        Three boundaries. Death before the `state.json` replacement leaves prepared
        compatibility artifacts and *no* authority: no reader reports a success.
        Death after the replacement and before the marker leaves a committed verdict
        every reader already agrees on. And an `exit 0` whose last `final` is missing
        — the clause the round-3 review found unstated — is `failed` with the exit
        code recorded, never `done`. The forbidden shape — a terminal-looking state
        with a marker and no commit — is reported unfinished, not as an ending.
        """
        class InjectedDeath(Exception):
            pass

        def die_before_the_commit(path, payload, _real=adapter.write_json):
            if str(path).endswith("state.json"):
                raise InjectedDeath("the process died before the commit")
            return _real(path, payload)

        cases = {
            "before-commit": ("none", None),
            "after-commit": ("completed", "done"),
            "exit-zero-without-final": ("none", "failed"),
        }
        for boundary, (final_kind, expected_verdict) in cases.items():
            with self.subTest(boundary=boundary):
                slug = f"t1-{boundary}"
                run_dir = self.staging(slug)
                if final_kind == "completed":
                    (run_dir / "events.ndjson").write_text(
                        json.dumps({"type": "final", "reason": {"kind": "completed"},
                                    "text": "t1 answer"}) + "\n",
                        encoding="utf-8",
                    )
                op = adapter.operation_of(str(run_dir))
                if boundary == "before-commit":
                    patches = (mock.patch.object(adapter, "write_json", die_before_the_commit),)
                else:
                    patches = (mock.patch.object(
                        adapter, "write_marker",
                        mock.Mock(side_effect=InjectedDeath("died before the marker")),
                    ),)
                with contextlib.ExitStack() as stack:
                    for patch in patches:
                        stack.enter_context(patch)
                    with contextlib.redirect_stderr(io.StringIO()), \
                            self.assertRaises(InjectedDeath):
                        adapter.finalize(str(run_dir), 0, expect_generation=op.generation)
                state = adapter.read_state_file(str(run_dir))
                if boundary == "before-commit":
                    self.assertIsNone(adapter.terminal_snapshot_locked(state))
                    self.assertEqual(state["state"], "running")
                    self.assertTrue((run_dir / "answer.md").exists(),
                                    "the prepared artifacts are written first")
                    self.assertFalse((run_dir / "finalized").exists())
                else:
                    record = adapter.terminal_snapshot_locked(state)
                    self.assertIsNotNone(record, state)
                    self.assertEqual(record["exit"], 0, "the exit code is recorded unchanged")
                    self.assertEqual(state["state"], expected_verdict)
                    self.assertFalse((run_dir / "finalized").exists())
                    if expected_verdict == "failed":
                        self.assertIsNot(state.get("stale_recovered"), True,
                                         "an exited process was reported as a disappearance")
                # The readers, on the artifacts as they stand: before the commit a
                # crash is a crash; after it the verdict is already settled.
                status = self.status_cli(slug)
                self.assertEqual(status.returncode, 0, status.stderr)
                if boundary == "before-commit":
                    self.assertIn("\"state\": \"failed\"", status.stdout)
                    self.assertIn("\"exit\": -1", status.stdout)
                    self.assertIn("stale_recovered: true", status.stdout)
                else:
                    self.assertIn(f"\"state\": \"{expected_verdict}\"", status.stdout)
                    self.assertIn("\"exit\": 0", status.stdout)
                    self.assertNotIn("stale_recovered: true", status.stdout)
                    self.assertEqual(self.answer_cli(slug).returncode, 0)
        # The shape the mutation would introduce: `state: done` + a marker, no
        # commit. It is uncommitted data — reported unfinished, never terminal.
        slug = "t1-marker-only"
        run_dir = self.staging(slug, state="done", exit=0)
        adapter.write_marker(str(run_dir / "finalized"), "0")
        state = adapter.read_state_file(str(run_dir))
        self.assertIsNone(adapter.terminal_snapshot_locked(state))
        self.assertNotEqual(adapter.lifecycle_of(str(run_dir), state), adapter.LIFECYCLE_TERMINAL)
        self.assertNotEqual(self.answer_cli(slug).returncode, 0)

    def test_t2_an_atomic_write_failure_never_truncates_the_destination(self):
        """T2: a failed replacement keeps the previous bytes and claims nothing."""
        slug = "t2"
        run_dir = self.staging(slug)
        op = adapter.operation_of(str(run_dir))
        target = run_dir / "state.json"
        before = target.read_bytes()
        attempts = []

        def refuses(src, dst):
            attempts.append(dst)
            raise PermissionError("the destination is held open by another process")

        errors = io.StringIO()
        with mock.patch.object(adapter.os, "replace", refuses), \
                mock.patch.object(adapter.time, "sleep", lambda seconds: None), \
                contextlib.redirect_stderr(errors):
            with self.assertRaises(OSError):
                adapter.write_text_atomic(str(target), "replacement")
            self.assertEqual(target.read_bytes(), before, "the destination was truncated")
            self.assertEqual(len(list(run_dir.glob("*.tmp"))), 0, "a temp file was left behind")
            self.assertEqual(len(attempts), 40, "the retry loop is not bounded")
            with self.assertRaises(OSError):
                adapter.merge_state_locked(op, {"note": "must not land"},
                                          adapter.read_state_file(str(run_dir)))
            self.assertEqual(target.read_bytes(), before)
        self.assertEqual(adapter.read_state_file(str(run_dir)).get("note"), None)

    # -- P: process identity and capability ----------------------------------

    def test_p1_the_linux_identity_binds_boot_and_namespace(self):
        """P1: a later boot or another namespace cannot reproduce a process token."""
        pid = os.getpid()
        token = adapter.process_identity(pid)
        if not token.startswith(adapter.LINUX_IDENTITY_VERSION):
            self.skipTest("no /proc token on this platform to test")
        self.assertTrue(adapter.identity_is_strong(token))
        self.assertTrue(adapter.identity_ok(pid, token))
        other_boot = token.replace(
            adapter._boot_id(), "00000000-0000-0000-0000-000000000000"
        )
        self.assertNotEqual(other_boot, token)
        self.assertFalse(adapter.identity_ok(pid, other_boot))
        self.assertTrue(adapter.identity_changed(pid, other_boot))
        with mock.patch.object(adapter, "_boot_id", lambda: "ffffffff-ffff-ffff-ffff-ffffffffffff"):
            self.assertFalse(adapter.identity_ok(pid, token))
            self.assertTrue(adapter.identity_changed(pid, token))
        with mock.patch.object(adapter, "_pid_namespace_identity", lambda: "ino:1"):
            self.assertFalse(adapter.identity_ok(pid, token))
        # No boot id and no namespace: no strong token at all, and never a weaker
        # one — the ps fallback is not even consulted on a /proc system.
        with mock.patch.object(adapter, "_boot_id", lambda: ""), \
                mock.patch.object(adapter, "_ps_identity",
                                  mock.Mock(side_effect=AssertionError("weak fallback used"))):
            self.assertEqual(adapter.process_identity(pid), "")
            self.assertFalse(adapter.signal_instance(pid, token, signal.SIGTERM))
        with mock.patch.object(adapter, "_pid_namespace_identity", lambda: ""):
            self.assertEqual(adapter.process_identity(pid), "")

    def test_p3_delivery_stays_on_the_handle_that_was_validated(self):
        """P3: the instance is signalled, so a reused number cannot redirect it."""
        pid = os.getpid()
        token = adapter.process_identity(pid)
        self.assertTrue(adapter.identity_is_strong(token))
        delivered = []

        class InjectedHandle:
            def __init__(self, handle_pid, handle_identity):
                self.pid = handle_pid
                self.identity = handle_identity

            def open(self):
                return True

            def exited(self):
                return False

            def signal(self, signum):
                delivered.append((self.pid, self.identity, signum))
                return True

            def close(self):
                return None

        def bomb(*args, **kwargs):
            raise AssertionError("a bare pid or group was signalled")

        with mock.patch.object(adapter, "ProcessHandle", InjectedHandle), \
                mock.patch.object(adapter.os, "kill", bomb), \
                mock.patch.object(adapter.os, "killpg", bomb):
            self.assertTrue(adapter.signal_instance(pid, token, signal.SIGTERM))
        self.assertEqual(delivered, [(pid, token, signal.SIGTERM)])
        # The identity is re-read while the handle is open: a token that no longer
        # matches refuses, whatever the number says.
        delivered.clear()
        with mock.patch.object(adapter, "ProcessHandle", InjectedHandle), \
                mock.patch.object(adapter, "process_identity",
                                  lambda probe: "linux:v2:elsewhere:elsewhere:9:9"), \
                mock.patch.object(adapter.os, "kill", bomb), \
                mock.patch.object(adapter.os, "killpg", bomb):
            self.assertFalse(adapter.signal_instance(pid, token, signal.SIGTERM))
        self.assertEqual(delivered, [], "a signal was delivered to a reused pid")
        # Native capability, where it exists: a real handle, a real stop, and a
        # mismatching token that refuses to touch a live process.
        victim = self.spawn([sys.executable, "-c", "import time; time.sleep(300)"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
        victim_identity = adapter.process_identity(victim.pid)
        if not adapter.identity_is_strong(victim_identity):
            self.skipTest("this platform has no strong process handle primitive")
        self.assertFalse(
            adapter.signal_instance(victim.pid, "linux:v2:other:other:1:1", signal.SIGTERM),
            "a mismatching identity signalled a live process",
        )
        self.assertIsNone(victim.poll(), "the mismatching identity killed the process")
        self.assertTrue(adapter.signal_instance(victim.pid, victim_identity, signal.SIGTERM))
        self.assertEqual(victim.wait(timeout=20), -signal.SIGTERM)

    def test_p5_membership_must_be_readable_and_matching(self):
        """P5: a member outside the group, or with no readable group, is no member."""
        leader, member = self.group_with_ready_member()
        identity = adapter.process_identity(member)
        self.assertTrue(adapter.identity_is_strong(identity), identity)
        group = adapter.process_group(member)
        self.assertGreater(group, 0, "the fixture's member has no readable group")
        found = adapter.anchored_members(member, identity, group)
        self.assertIsNotNone(found)
        self.assertIn(member, [pid for pid, _identity, _group in found])
        # A group the member is not in, an unreadable group, and an unreadable
        # table are all refusals — never a historical group id as a fallback.
        self.assertIsNone(adapter.anchored_members(member, identity, group + 1))
        self.assertIsNone(adapter.anchored_members(member, identity, 0))
        with mock.patch.object(adapter, "process_group", lambda probe: 0):
            self.assertIsNone(adapter.anchored_members(member, identity, group))
        with mock.patch.object(adapter, "group_member_pids", lambda pgid: None):
            self.assertIsNone(adapter.anchored_members(member, identity, group))
        delivered, patches = self.signal_spy()
        errors = io.StringIO()
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            stack.enter_context(mock.patch.object(adapter, "process_group", lambda probe: 0))
            stack.enter_context(contextlib.redirect_stderr(errors))
            self.assertFalse(adapter.signal_member_group(member, signal.SIGTERM, identity, group))
        self.assertEqual(delivered, [], "a group was signalled with no readable membership")
        self.assertIn("not a fallback", errors.getvalue())
        del leader

    def test_p6_an_anchor_that_leaves_the_enumeration_discards_it(self):
        """P6: the anchor is verified throughout, so a half-seen table is not adopted."""
        leader, member = self.group_with_ready_member()
        identity = adapter.process_identity(leader.pid)
        self.assertTrue(adapter.identity_is_strong(identity), identity)
        group = adapter.process_group(leader.pid)
        self.assertGreater(group, 0)
        # The anchor answers "exited" as soon as the table has been read: the
        # enumeration it anchored is discarded, members and all.
        left = {"table_read": False}

        class LeavingAnchor(adapter.ProcessHandle):
            def exited(self):
                return left["table_read"]

        real_table = adapter.group_member_pids

        def table_then_leave(pgid):
            left["table_read"] = True
            return real_table(pgid)

        with mock.patch.object(adapter, "ProcessHandle", LeavingAnchor), \
                mock.patch.object(adapter, "group_member_pids", table_then_leave):
            self.assertIsNone(adapter.anchored_members(leader.pid, identity, group))
        # And the signalling path adopts nothing from it either: with the group's
        # ownership unproven, only the verified process itself may be signalled.
        delivered, patches = self.signal_spy()
        left["table_read"] = False
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            stack.enter_context(mock.patch.object(adapter, "ProcessHandle", LeavingAnchor))
            stack.enter_context(mock.patch.object(adapter, "group_member_pids", table_then_leave))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            # The enumeration is discarded, and by the time the fallback asks the
            # anchor's own handle, that handle reports the process gone: nothing is
            # signalled — least of all a member the discarded table named.
            self.assertFalse(adapter.signal_group(leader.pid, signal.SIGTERM, identity))
        self.assertEqual(delivered, [], "a discarded enumeration was signalled")
        self.assertNotIn(member, [pid for pid, _signum in delivered],
                         "a member discovered in a discarded enumeration was signalled")

    def test_p8_an_unreadable_process_table_stays_conservative(self):
        """P8: a failed inspection is unknown, never "gone" and never "nobody"."""
        slug = "p8"
        run_dir = self.staging(slug, pid=os.getpid(), pid_identity=adapter.process_identity(os.getpid()))
        state = adapter.read_state_file(str(run_dir))
        self.assertTrue(adapter.identity_is_strong(state["pid_identity"]))
        # Access denial: the run is still possibly alive, so nothing settles it.
        with mock.patch.object(adapter, "liveness_of", lambda probe: adapter.UNKNOWN):
            self.assertTrue(adapter.run_alive(str(run_dir), state))
            self.assertIsNone(adapter.stop_survivors(str(run_dir), state))
            self.assertEqual(
                adapter.survivors_blocking_commit(state, str(run_dir)), "",
                "an unreadable process is not a recorded live survivor",
            )
            self.assertNotEqual(adapter.lifecycle_of(str(run_dir), state),
                                adapter.LIFECYCLE_TERMINAL)
        # A recorded pid that cannot be inspected keeps its slug occupied, and no
        # reader settles the run on an inspection that failed.
        with mock.patch.object(adapter, "liveness_of", lambda probe: adapter.UNKNOWN):
            self.assertIsNone(adapter.stop_survivors(str(run_dir), state))
            occupant, _state = adapter.occupying_run(str(self.root), slug)
            self.assertEqual(occupant, str(run_dir))
        self.assertIsNone(adapter.terminal_snapshot_locked(adapter.read_state_file(str(run_dir))))
        self.assertFalse((run_dir / "finalized").exists())
        # An unreadable survivor record does not clear a stop either: a survivor
        # that is live right now blocks the commit whatever the enumeration says.
        stopping = dict(state)
        stopping.update({"stopping": True, "survivors_complete": True, "survivors": [
            {"pid": os.getpid(), "identity": state["pid_identity"], "group": 0},
        ]})
        self.assertTrue(adapter.survivors_blocking_commit(stopping, str(run_dir)))
        with mock.patch.object(adapter, "liveness_of", lambda probe: adapter.UNKNOWN):
            self.assertTrue(adapter.survivors_blocking_commit(stopping, str(run_dir)))
        with mock.patch.object(adapter, "liveness_of", lambda probe: adapter.GONE):
            self.assertEqual(adapter.survivors_blocking_commit(stopping, str(run_dir)), "")

    # -- B/Q: bounds and documents -------------------------------------------

    def test_b1_every_configured_wait_is_finite(self):
        """B1: no environment knob can install an infinite or nonsensical wait."""
        knobs = (
            ("DSH_RUN_START_GRACE_SECONDS", adapter.start_grace_seconds, adapter.GRACE_SECONDS),
            ("DSH_RUN_STOP_WAIT_SECONDS", adapter.stop_wait_seconds, adapter.STOP_WAIT_SECONDS),
            ("DSH_RUN_SETTLE_WAIT_SECONDS", adapter.settle_wait_seconds,
             adapter.SETTLE_WAIT_SECONDS),
            ("DSH_RUN_DRAIN_TIMEOUT_SECONDS", adapter.drain_timeout_seconds,
             adapter.DRAIN_TIMEOUT_SECONDS),
        )
        hostile = ("inf", "Infinity", "-inf", "nan", "0", "-1", "", "abc", "1e400", "  ")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            for name, resolve, default in knobs:
                with self.subTest(knob=name, value="unset"), \
                        mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop(name, None)
                    self.assertEqual(resolve(), default)
                    self.assertTrue(math.isfinite(resolve()) and resolve() > 0)
                for raw in hostile:
                    with self.subTest(knob=name, value=raw), \
                            mock.patch.dict(os.environ, {name: raw}, clear=False):
                        value = resolve()
                        self.assertEqual(value, default, f"{name}={raw!r} was accepted")
                        self.assertTrue(math.isfinite(value) and value > 0)
                with self.subTest(knob=name, value="2.5"), \
                        mock.patch.dict(os.environ, {name: "2.5"}, clear=False):
                    self.assertEqual(resolve(), 2.5)
        for raw in ("inf", "Infinity", "-inf", "nan", "1e400", "0", "-1", "abc"):
            with self.subTest(max_time=raw):
                with self.assertRaises(ValueError):
                    adapter.parse_max_time(raw)
        # A blank value is "unset", not an error: the flag is optional.
        self.assertIsNone(adapter.parse_max_time("  "))
        self.assertIsNone(adapter.parse_max_time(None))
        self.assertEqual(adapter.parse_max_time("90"), 90.0)
        prompt = self.tmp / "b1-prompt.md"
        prompt.write_text("do the thing\n", encoding="utf-8")
        cli = subprocess.run(
            [sys.executable, str(ADAPTER), "start", "--name", "b1", "--prompt", str(prompt),
             "--cwd", str(self.tmp), "--max-time", "inf"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "DSH_RUN_ROOT": str(self.root), "DSH_BIN": "/bin/true"},
        )
        self.assertNotEqual(cli.returncode, 0)
        self.assertIn("--max-time must be a positive number", cli.stderr)

    def test_q3_the_document_mapping_check_catches_a_swapped_mapping(self):
        """Q3: the mapping check is an association check, and it is itself checked."""
        documents = {
            "goal": REPO / "docs/goals/archive/2026-11-15-dsh-headless-launcher.md",
            "transport": REPO / "skills/gdd/references/transport.md",
            "record": REPO / "docs/evidence/2026-11-15-dsh-headless-launcher.md",
            "skill": REPO / "skills/dsh-headless-gdd/SKILL.md",
        }
        for name, path in documents.items():
            with self.subTest(document=name):
                text = path.read_text(encoding="utf-8")
                check_exit_mapping(exit_mapping_entries(text), name)
                # The named mutation: the signal-convention exits presented as
                # `failed` — the `failed` entry replaced by the `killed` entry.
                swapped = swap_exit_mapping(text, "failed", "killed")
                self.assertNotEqual(swapped, text, "the mutation must edit the copy")
                with self.assertRaises(AssertionError):
                    check_exit_mapping(exit_mapping_entries(swapped), f"{name} (swapped)")
                # And a dropped condition, not just a missing keyword elsewhere.
                dropped = edit_exit_mapping_entry(text, "killed", "`-2`/`-9`/`-15`",
                                                 "the signal forms")
                if dropped != text:
                    with self.assertRaises(AssertionError):
                        check_exit_mapping(exit_mapping_entries(dropped), f"{name} (dropped)")
                # The `done` entry alone is not enough: exit 0 without a completed
                # final must still be `failed` in every document.
                for state in ("done", "killed", "failed"):
                    with self.subTest(document=name, missing=state):
                        other = "killed" if state != "killed" else "done"
                        broken = swap_exit_mapping(text, state, other)
                        self.assertNotEqual(broken, text)
                        with self.assertRaises(AssertionError):
                            check_exit_mapping(exit_mapping_entries(broken), f"{name} ({state})")


    def test_g8_a_late_stop_report_cannot_revive_a_committed_verdict(self):
        """G8: a report that arrives after the verdict writes neither state nor lock."""
        slug = "g8"
        run_dir = self.staging(slug, stopping=True)
        op = adapter.operation_of(str(run_dir))
        triggered = {"n": 0}
        real_mutex = adapter.mutex_of

        def commit_first(mutex_op, wait=0.0):
            if triggered["n"] == 0:
                triggered["n"] = 1
                # Stop B commits the verdict while report A is still on its way in.
                with real_mutex(mutex_op) as held:
                    self.assertTrue(held)
                    adapter._publish_terminal_locked(
                        mutex_op, adapter.read_state_file(str(run_dir)),
                        adapter.KILL_EXIT, False, "stop B", {"stopped_by": "stop-b"},
                    )
            return real_mutex(mutex_op, wait)

        errors = io.StringIO()
        with mock.patch.object(adapter, "mutex_of", commit_first), \
                contextlib.redirect_stderr(errors):
            self.assertEqual(adapter.report_incomplete_stop(op, None, "late report A"), 1)
        self.assertTrue(triggered["n"], "the commit did not happen first")
        committed = adapter.read_state_file(str(run_dir))
        self.assertIsNotNone(adapter.terminal_snapshot_locked(committed), committed)
        after = self.snapshot(run_dir)
        self.assertIn("already committed", errors.getvalue())
        self.assertEqual(committed["state"], "killed")
        self.assertNotIn("stopping", committed)
        errors = io.StringIO()
        with mock.patch.object(adapter, "mutex_of", commit_first), \
                contextlib.redirect_stderr(errors):
            self.assertEqual(adapter.report_incomplete_stop(op, [(1, "identity", 1)], "late"), 1)
        self.assertEqual(self.snapshot(run_dir), after, "a late report rewrote a settled run")
        # And after a replacement, the late report writes nothing into the new run.
        generation = self.replace_with_new_generation(run_dir)
        after = self.snapshot(run_dir)
        errors = io.StringIO()
        with mock.patch.object(adapter, "mutex_of", commit_first), \
                contextlib.redirect_stderr(errors):
            self.assertEqual(adapter.report_incomplete_stop(op, None, "late"), 1)
        self.assertEqual(self.snapshot(run_dir), after, "a late report wrote into the new run")
        self.assertIn("different run", errors.getvalue())
        self.assertEqual(adapter.strict_generation(adapter.read_state_file(str(run_dir))), generation)

    def test_the_docs_state_the_write_isolation_unit(self):
        """D4: the isolation unit is the worktree/session, not the whole repository.

        A parallel-work instruction that forbids two writers per *repository*
        contradicts the two worktrees it just told the operator to use. The check is
        an association (the unit is named, the repository-wide sentence is gone) and
        is itself mutation-checked on copies.
        """
        def check_isolation(text, source):
            plain = text.replace("*", "").replace("`", "")
            assert "isolation unit is the worktree/session" in plain, source
            assert "same worktree" in plain, source
            assert "The same repository never has two writers" not in plain, source

        skill_path = REPO / "skills/dsh-headless-gdd/SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        check_isolation(text, "SKILL.md")
        mutations = {
            "unit reverted to the repository": text.replace(
                "isolation unit is the worktree/session", "isolation unit is the repository"
            ),
            "repository-wide sentence restored": text.replace(
                "One goal, one worktree, one session\n",
                "One goal, one worktree, one session\n\nThe same repository never has two writers.\n",
                1,
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(mutation=name):
                self.assertNotEqual(mutated, text, "the mutation must edit the copy")
                with self.assertRaises(AssertionError):
                    check_isolation(mutated, f"SKILL.md ({name})")


    def test_the_docs_state_the_stop_capability_and_its_limits(self):
        """C-2: the refusal, `kill`'s exit 1 and the operator's follow-up are documented.

        Both documents that an operator reads must carry the operational facts of a
        platform without a verified signalling primitive, and the residual limits
        must be stated as limits. The check is mutation-checked on a copy.
        """
        def check_stop_facts(text, source):
            blocks = [
                block for block in re.split(r"\n\s*\n", text) if "pidfd" in block
            ]
            assert blocks, f"{source}: no text that names the signalling primitive"
            plain = " ".join(
                " ".join(text.replace("*", "").replace("`", "").split()) for text in blocks
            )
            assert "no destructive call" in plain or "refuses to escalate" in plain, source
            assert re.search(r"exits? 1(?![0-9])", plain), f"{source}: no `kill` exit 1"
            assert "running/stopping" in plain, source
            assert "by hand" in plain, source
            assert "not durable" in plain, source
            assert "unconfirmed" in plain.lower(), source
            assert "foreign" in plain or "external starter" in plain, source
            assert "descendant" in plain, source

        documents = {
            "transport": REPO / "skills/gdd/references/transport.md",
            "skill": REPO / "skills/dsh-headless-gdd/SKILL.md",
        }
        mutations = {
            "transport": (
                ("kill exit-1 claim dropped", "`kill` exits\n`1` saying it cannot confirm",
                 "`kill` gives up"),
                ("hand-finish dropped", "by hand and runs", "later and runs"),
                ("durability claim dropped", "atomic, not durable", "atomic"),
            ),
            "skill": (
                ("kill exit-1 claim dropped", "`kill` exits **1**", "`kill` gives up"),
                ("hand-finish dropped", "process tree by hand and runs",
                 "process tree later and runs"),
                ("durability claim dropped", "atomic but not durable", "atomic"),
            ),
        }
        for name, path in documents.items():
            with self.subTest(document=name):
                text = path.read_text(encoding="utf-8")
                check_stop_facts(text, name)
                for label, old, new in mutations[name]:
                    mutated = text.replace(old, new, 1)
                    self.assertNotEqual(mutated, text, f"the {label} mutation must edit the copy")
                    with self.subTest(document=name, mutation=label):
                        with self.assertRaises(AssertionError):
                            check_stop_facts(mutated, f"{name} ({label})")


if __name__ == "__main__":
    unittest.main()
