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
import os
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


class DshLauncherTests(unittest.TestCase):
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
            "STUB_TEXT", "STUB_REASON", "STUB_SESSION",
        ):
            cls.env.pop(key, None)

    @classmethod
    def tearDownClass(cls):
        for run_dir in adapter.run_dirs(str(cls.run_root)):
            state = adapter.read_state_file(str(run_dir))
            if adapter.run_alive(str(run_dir), state):
                adapter.kill_tree(str(run_dir), state)
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

        On POSIX the tree ignores TERM and holds a child in its own process group,
        so neither a plain TERM nor a signal to the leader alone could stop it:
        only the group signal plus the TERM->KILL escalation behind `kill` can.
        """
        slug = "kill-forced-09"
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True)
        (run_dir / "prompt.md").write_text("dispatched, runner lost\n", encoding="utf-8")
        (run_dir / "events.ndjson").write_text("", encoding="utf-8")
        (run_dir / "state.json").write_text(
            json.dumps({"name": slug, "state": "running", "exit": None, "cwd": str(self.tmp),
                        "started": adapter.now_iso(), "backend": "dsh"}),
            encoding="utf-8",
        )
        # A process tree this test does not own: the helper exits immediately after
        # reporting it, so nothing here has to reap it and the liveness check sees
        # the real thing. The leader ignores TERM and holds a child in its group.
        helper = (
            "import subprocess, sys\n"
            "inner = (\n"
            "    'import signal, subprocess, sys, time\\n'\n"
            "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
            "    'child = subprocess.Popen([sys.executable, \"-c\", \"import signal, time;"
            " signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(300)\"],"
            " stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,"
            " stderr=subprocess.DEVNULL)\\n'\n"
            "    'print(child.pid, flush=True)\\n'\n"
            "    'time.sleep(300)\\n'\n"
            ")\n"
            "leader = subprocess.Popen([sys.executable, '-c', inner], start_new_session=True,"
            " stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,"
            " text=True)\n"
            "print(leader.pid, flush=True)\n"
            "print(leader.stdout.readline().strip(), flush=True)\n"
        )
        spawned = subprocess.run(
            [sys.executable, "-c", helper], capture_output=True, text=True, timeout=30.0
        )
        self.assertEqual(spawned.returncode, 0, spawned.stderr)
        reported = spawned.stdout.split()
        self.assertEqual(len(reported), 2, spawned.stdout)
        pid, child_pid = int(reported[0]), int(reported[1])
        try:
            # The identity a real run records at spawn: without it the adapter
            # refuses to signal, so the escalation this test exercises needs it.
            leader_identity = adapter.process_identity(pid)
            self.assertTrue(leader_identity, "the platform must supply a process identity")
            (run_dir / "lock").write_text(
                json.dumps({"pid": pid, "agent_pid": None, "pid_identity": leader_identity,
                            "backend": "dsh", "started_at": adapter.now_iso()}),
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
            for target in (pid, child_pid):
                if adapter.pid_alive(target):
                    self.kill_pid_tree(target)

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

        The runner is driven to completion synchronously by the patched
        `spawn_runner`: by the time `start` confirms, the stub agent has already
        written its `error` event, exited, and the run's own finalizer has
        recorded `failed` with that error. `start` must still exit 0 — the
        guarantee is that the runner spawned an agent and recorded it, and
        whether the agent then succeeded or died is what `state.json` says.
        Running the runner to completion before confirmation is what makes this
        deterministic: no sleep, no timeout and no scheduling question is
        involved.
        """
        slug = "fastfail-28"
        args = adapter.build_parser().parse_args(
            ["start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp)]
        )
        env = self.env_for(STUB_MODE="error")

        def run_runner_to_completion(argv, cwd, log_path):
            done = subprocess.run(
                argv, cwd=cwd, env=adapter.child_env(), stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=60.0,
            )
            Path(log_path).write_text(done.stdout + done.stderr, encoding="utf-8")
            return types.SimpleNamespace(pid=0)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
            adapter, "spawn_runner", run_runner_to_completion
        ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = adapter.cmd_start(args)
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn(f"started: {slug}", out.getvalue())
        state = self.wait_for_state(slug, {"failed"})
        self.assertTrue(state.get("agent_pid"), state)
        self.assertEqual(state["exit"], 1, state)
        self.assertEqual(state["final_reason"], None, state)
        self.assertIn("MISSING_CREDENTIAL", state["error"])
        self.assertEqual((self.run_dir(slug) / "finalized").read_text(encoding="utf-8"), "1")

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

        `terminate_agent` used to report exit 143 whether or not anything
        survived, so the run was finalized `killed` while its agent still wrote to
        the worktree: `kill` then refused to touch it and a new `start` no longer
        saw the slug as occupied.
        """
        slug = "stopfail-33"
        run_dir = self.run_root / adapter.date_stamp() / slug
        run_dir.mkdir(parents=True)
        (run_dir / "prompt.md").write_text("the agent is still working\n", encoding="utf-8")
        adapter.write_json(str(run_dir / "state.json"), {
            "name": slug, "state": "running", "exit": None, "cwd": str(self.tmp),
            "started": adapter.now_iso(), "backend": "dsh",
        })
        adapter.write_json(str(run_dir / "lock"), {
            "pid": None, "agent_pid": None, "backend": "dsh", "started_at": adapter.now_iso(),
        })
        (run_dir / "stop").write_text("{}", encoding="utf-8")  # what `kill` writes
        # The agent that survives the stop: a real process of its own, so the later
        # attempt can signal it through the identity read while it was observed.
        victim = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(300)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        victim_identity = adapter.process_identity(victim.pid)
        self.assertTrue(victim_identity, "the platform must supply a process identity")
        args = adapter.build_parser().parse_args([
            "_run", "--run-dir", str(run_dir), "--prompt", str(run_dir / "prompt.md"),
            "--cwd", str(self.tmp), "--agent", str(self.dsh_bin()), "--name", slug,
            "--profile", "headless", "--permission-mode", "workspace-write",
            "--approval-policy", "never",
        ])
        # Driving the runner in-process must not record this interpreter as the
        # run's runner: a pid beyond pid_max is what a detached runner that has
        # exited looks like to every reader.
        dead_pid = 1 << 22
        self.assertFalse(adapter.pid_alive(dead_pid))

        class NoSelfPid:
            """The os module, with getpid answering a pid that is not this process's."""

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
                    mock.patch.object(
                        adapter, "terminate_agent",
                        lambda process, identity="": (
                            adapter.KILL_EXIT, [(victim.pid, victim_identity, victim.pid)]
                        ),
                    ), \
                    mock.patch.object(adapter, "os", NoSelfPid()), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                code = adapter.runner_main(args)
            self.assertEqual(code, 1, "a stop that failed is not a finished run")
            self.assertFalse((run_dir / "finalized").exists())
            self.assertFalse((run_dir / "exit.code").exists())
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
            self.assertFalse((run_dir / "answer.md").exists())
            # A later stop attempt resolves it: the survivor is signalled through
            # its verified identity and the run settles killed/143.
            reaper = threading.Thread(target=victim.wait, daemon=True)
            reaper.start()
            with mock.patch.object(adapter, "POLL_SECONDS", 0.01), \
                    contextlib.redirect_stderr(io.StringIO()):
                stopped = adapter.stop_run(str(run_dir), state, seconds=1)
            self.assertTrue(stopped, "a later stop attempt must settle the run")
            self.assertFalse(adapter.pid_alive(victim.pid), "the survivor must be stopped")
            final = adapter.read_state_file(str(run_dir))
            self.assertEqual((final["state"], final["exit"]), ("killed", adapter.KILL_EXIT), final)
            self.assertNotIn("stopping", final)
            self.assertEqual([victim.pid], final.get("survivors_stopped"), final)
            self.assertEqual(
                (run_dir / "finalized").read_text(encoding="utf-8"), str(adapter.KILL_EXIT)
            )
        finally:
            for name, handler in saved.items():
                signal.signal(getattr(signal, name), handler)
            if adapter.pid_alive(victim.pid):
                adapter.kill_tree(str(run_dir))
            victim.kill()
            victim.wait(timeout=10)


class AdapterUnitTests(unittest.TestCase):
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
            state_path = run_dir / "state.json"
            state = {"name": "late", "state": "running", "exit": None, "cwd": tmp,
                     "started": adapter.now_iso()}
            adapter.write_json(str(state_path), state)
            (run_dir / "events.ndjson").write_text(
                json.dumps({"type": "final", "sessionId": "s", "reason": {"kind": "completed"},
                            "text": "the answer"}) + "\n",
                encoding="utf-8",
            )
            track, stop = adapter.make_tracker(str(run_dir), state, str(state_path))
            track(json.dumps({"type": "session", "sessionId": "s"}).encode())
            stop()
            final = adapter.finalize(str(run_dir), 0)
            self.assertEqual(final["state"], "done", final)
            committed = state_path.read_bytes()
            # Lines a descendant kept the stream open for, arriving after the
            # finalizer committed: a forcing `session` event and a counted one.
            track(json.dumps({"type": "session", "sessionId": "late"}).encode())
            track(json.dumps({"type": "status", "turn": 1, "phase": "turn_end"}).encode())
            self.assertEqual(committed, state_path.read_bytes())
            self.assertEqual(adapter.read_state_file(str(run_dir))["state"], "done")

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

    @unittest.skipIf(IS_WINDOWS, "process groups and killpg are POSIX-only")
    def test_signal_group_refuses_a_pid_it_cannot_prove(self):
        """No signal without a matching identity, and no getpgid fallback (A5)."""
        pid = os.getpid()
        identity = adapter.process_identity(pid)
        self.assertTrue(identity, "the platform must supply a process identity")
        calls = []
        err = io.StringIO()
        with mock.patch.object(
            adapter.os, "killpg", lambda pgid, signum: calls.append((pgid, signum))
        ), mock.patch.object(
            adapter.os, "getpgid",
            side_effect=AssertionError("the current-process-group fallback must be gone"),
        ), contextlib.redirect_stderr(err):
            self.assertFalse(adapter.signal_group(pid, signal.SIGTERM, "somewhere-else"))
            self.assertFalse(adapter.signal_group(pid, signal.SIGTERM, ""))
            self.assertEqual(calls, [])
            self.assertIn("not signalling", err.getvalue())
            # The pid that still carries its recorded identity is signalled as
            # the group it leads.
            self.assertTrue(adapter.signal_group(pid, signal.SIGTERM, identity))
        self.assertEqual(calls, [(pid, signal.SIGTERM)])

    @unittest.skipIf(IS_WINDOWS, "process groups are POSIX-only")
    def test_a_vanished_leader_is_never_signalled(self):
        """A group id whose leader is gone proves nothing, so nothing is sent (A2)."""
        pid = os.getpid()
        identity = adapter.process_identity(pid)
        self.assertTrue(identity, "the platform must supply a process identity")
        calls = []
        err = io.StringIO()
        with mock.patch.object(adapter, "pid_alive", lambda target: False), \
                mock.patch.object(
                    adapter.os, "killpg", lambda pgid, signum: calls.append((pgid, signum))
                ), contextlib.redirect_stderr(err):
            self.assertFalse(adapter.signal_group(pid, signal.SIGTERM, identity))
            # The member path is not a way around that either: a member that is
            # gone cannot name the group.
            self.assertFalse(adapter.signal_member_group(pid, signal.SIGTERM, identity, pid))
        self.assertEqual(calls, [], "a bare group id must never be signalled")
        self.assertIn("not signalling", err.getvalue())

    @unittest.skipIf(IS_WINDOWS, "process groups are POSIX-only")
    def test_a_verified_member_names_the_group_of_a_gone_leader(self):
        """A survivor's own identity is what may aim a group signal (A2)."""
        victim = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        identity = adapter.process_identity(victim.pid)
        try:
            calls = []
            err = io.StringIO()
            with mock.patch.object(
                adapter.os, "killpg", lambda pgid, signum: calls.append((pgid, signum))
            ), contextlib.redirect_stderr(err):
                self.assertTrue(
                    adapter.signal_member_group(victim.pid, signal.SIGTERM, identity, victim.pid)
                )
                # A member whose recorded identity is not its own is refused…
                self.assertFalse(
                    adapter.signal_member_group(victim.pid, signal.SIGTERM, "proc:0", victim.pid)
                )
                # …and so is a recorded group the member no longer belongs to.
                self.assertFalse(
                    adapter.signal_member_group(
                        victim.pid, signal.SIGTERM, identity, victim.pid + 1
                    )
                )
            self.assertEqual(calls, [(victim.pid, signal.SIGTERM)])
            self.assertIn("not signalling the group", err.getvalue())
        finally:
            victim.kill()
            victim.wait(timeout=10)

    def test_a_failed_stop_records_survivors_without_finalizing(self):
        """A failed stop stays live/stopping and a later stop settles it (A3)."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            victim = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            identity = adapter.process_identity(victim.pid)
            try:
                adapter.write_json(str(run_dir / "state.json"), {
                    "name": "stopping", "state": "running", "exit": None, "cwd": tmp,
                    "started": adapter.now_iso(), "backend": "dsh",
                })
                adapter.write_json(str(run_dir / "lock"), {
                    "pid": None, "agent_pid": None, "backend": "dsh",
                })
                with contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    code = adapter.report_incomplete_stop(
                        str(run_dir), [(victim.pid, identity, victim.pid)], "control-file"
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
                # Once a terminal state is committed the transient flags are history.
                final = adapter.finalize(str(run_dir), adapter.KILL_EXIT)
                self.assertEqual(final["state"], "killed")
                self.assertNotIn("stopping", final)
                self.assertNotIn("survivors", final)
                self.assertEqual(final.get("survivors_stopped"), [victim.pid])
            finally:
                victim.kill()
                victim.wait(timeout=10)

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
        """`ps -o lstart=` is timezone-shaped; the probe must not inherit TZ (A6)."""
        seen = []

        def fake_run(argv, **kwargs):
            env = kwargs.get("env") or {}
            seen.append((list(argv), env.get("TZ"), env.get("LC_ALL")))
            # What `ps` prints for one process, rendered in two different zones.
            text = (
                "Mon Nov 17 10:00:00 2025"
                if env.get("TZ") == "UTC" else "Mon Nov 17 23:00:00 2025"
            )
            return types.SimpleNamespace(returncode=0, stdout=text + "\n")

        pid = os.getpid()
        with mock.patch.object(adapter, "_proc_stat_identity", lambda target: ""), \
                mock.patch.object(adapter.subprocess, "run", fake_run):
            with mock.patch.dict(os.environ, {"TZ": "UTC", "LC_ALL": "C"}, clear=False):
                first = adapter.process_identity(pid)
            with mock.patch.dict(
                os.environ, {"TZ": "Pacific/Kiritimati", "LC_ALL": "de_DE.UTF-8"}, clear=False
            ):
                second = adapter.process_identity(pid)
                # The probe fixes its own view; the caller's environment is untouched.
                self.assertEqual(os.environ.get("TZ"), "Pacific/Kiritimati")
                self.assertEqual(os.environ.get("LC_ALL"), "de_DE.UTF-8")
        self.assertTrue(first, "the probe must produce a token")
        self.assertEqual(first, second, "one process must yield one token under any caller TZ")
        self.assertEqual([entry[1:] for entry in seen], [("UTC", "C"), ("UTC", "C")])
        self.assertIn("lstart=", seen[0][0])

    def test_the_stop_escalation_branches_on_the_platform(self):
        """Windows must not read `signal.SIGKILL`, which does not exist there (A7)."""
        seen = []

        class FakeSignal:  # a Windows-shaped signal module: SIGTERM and no SIGKILL at all
            SIGTERM = 15

        class StandInProcess:
            pid = os.getpid()

            def poll(self):
                return None

        alive = {"calls": 0}

        def fake_tree_alive(pid):
            alive["calls"] += 1
            # Alive through the TERM wait and the pause, gone after the escalation.
            return alive["calls"] <= 61

        def run_case(windows, signum_module):
            seen.clear()
            alive["calls"] = 0
            with mock.patch.object(adapter, "IS_WINDOWS", windows), \
                    mock.patch.object(adapter, "signal", signum_module), \
                    mock.patch.object(adapter, "terminate_tree", lambda pid, signum, identity="":
                                       seen.append(signum) or True), \
                    mock.patch.object(adapter, "tree_alive", fake_tree_alive), \
                    mock.patch.object(adapter, "POLL_SECONDS", 0), \
                    contextlib.redirect_stderr(io.StringIO()):
                return adapter.terminate_agent(StandInProcess(), "fake:1"), seen[:]

        (code, survivors), signals = run_case(True, FakeSignal)
        self.assertEqual((code, survivors), (adapter.KILL_EXIT, []))
        self.assertEqual(signals, [None, None], "Windows sends no POSIX signal number")
        (code, survivors), signals = run_case(
            False, types.SimpleNamespace(SIGTERM=15, SIGKILL=9)
        )
        self.assertEqual((code, survivors), (adapter.KILL_EXIT, []))
        self.assertEqual(signals, [15, 9])

    def test_a_failing_taskkill_is_reported_not_assumed(self):
        """A taskkill that failed is a stop that did not happen (A7)."""
        commands = []
        err = io.StringIO()
        with mock.patch.object(adapter, "IS_WINDOWS", True), \
                mock.patch.object(adapter, "pid_alive", lambda pid: True), \
                mock.patch.object(adapter, "identity_ok", lambda pid, identity: True), \
                mock.patch.object(adapter, "run_quiet",
                                  lambda argv: commands.append(argv) or 1), \
                contextlib.redirect_stderr(err):
            self.assertFalse(adapter.terminate_tree(4321, 0, "win:1"))
        self.assertEqual(commands, [["taskkill", "/T", "/F", "/PID", "4321"]])
        self.assertIn("taskkill", err.getvalue())
        self.assertIn("may still be alive", err.getvalue())

    def test_kill_tree_leaves_an_unverified_pid_alone(self):
        """The forced-kill path fails closed instead of signalling a stranger (A5)."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "stranger", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso()})
            victim = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                adapter.write_json(str(run_dir / "lock"), {
                    "pid": victim.pid, "agent_pid": None, "pid_identity": "proc:0"})
                with mock.patch.object(adapter, "POLL_SECONDS", 0.01), \
                        contextlib.redirect_stderr(io.StringIO()):
                    forced = adapter.kill_tree(str(run_dir))
                self.assertFalse(forced)
                self.assertIsNone(victim.poll(), "an unverified pid must not be signalled")
            finally:
                victim.kill()
                victim.wait(timeout=10)

    def test_a_held_finalize_claim_stops_a_reader_from_finalizing(self):
        """The finalize claim is an OS lock a competitor cannot delete (A6)."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "events.ndjson").write_text("", encoding="utf-8")
            adapter.write_json(str(run_dir / "state.json"), {
                "name": "claim", "state": "running", "exit": None, "cwd": tmp,
                "started": adapter.now_iso()})
            holder = open(run_dir / "finalize.lock", "a+b")
            try:
                if IS_WINDOWS:
                    import msvcrt

                    holder.seek(0)
                    msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Age does not transfer ownership: the deleted-by-age claim file
                # is exactly how two readers could both finalize.
                stale = time.time() - 3600
                os.utime(run_dir / "finalize.lock", (stale, stale))
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    returned = adapter.finalize(str(run_dir), -1, recovered=True, claim_wait=0.0)
                self.assertFalse((run_dir / "finalized").exists())
                self.assertEqual(returned.get("state"), "running")
                self.assertIn("being finalized by another process", err.getvalue())
                with contextlib.redirect_stderr(io.StringIO()):
                    adapter.finalize(str(run_dir), -1, recovered=True, claim_wait=0.3)
                self.assertFalse((run_dir / "finalized").exists())
            finally:
                holder.close()
            # Released: the next reader settles the same run.
            state = adapter.finalize(str(run_dir), -1, recovered=True, claim_wait=1.0)
            self.assertEqual(state["state"], "failed", state)
            self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "-1")

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
                                    "cwd": tmp, "started": adapter.now_iso()}),
                        encoding="utf-8",
                    )
                    state = adapter.finalize(str(run_dir), exit_code)
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
                            "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}),
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

    def test_a_terminal_state_without_a_marker_is_repaired_from_its_exit_code(self):
        """A finalizer that died between state.json and the marker leaves both facts."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "events.ndjson").write_text("", encoding="utf-8")
            (run_dir / "state.json").write_text(
                json.dumps({"name": "repaired", "state": "killed", "exit": 143, "cwd": tmp,
                            "backend": "dsh",
                            "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}),
                encoding="utf-8",
            )
            state, recovered = adapter.effective_state(str(run_dir))
            self.assertTrue(recovered)
            self.assertTrue(state["finalize_repaired"], state)
            self.assertEqual((state["state"], state["exit"]), ("killed", 143), state)
            self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "143")
            self.assertIn("without the finalized marker", state["note"])

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


if __name__ == "__main__":
    unittest.main()
