#!/usr/bin/env python3
"""Cross-platform tests for the Python launcher adapter (scripts/adapters/omp-run.py).

The bash suites beside this file pin the POSIX reference adapter and the forwarder,
and a Windows operator cannot run them. This suite is stdlib unittest and runs
wherever python3 does, driving a stub agent CLI that emits OMP-style NDJSON: no
network, no model, no real agent.

Covered: start -> settled run (state transitions, answer extraction, artifacts,
ledger row), the exit-code mapping, stale recovery (once, idempotently), kill of a
live run through the `stop` control file, the bounded event log's loss accounting,
the detachment evidence — the creation flags plus what the run observed about its
own console (Windows) or session (POSIX) — and the argument passthrough to the
agent, including refusal when the agent executable cannot actually be spawned.
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
ADAPTER = SCRIPTS / "adapters" / "omp-run.py"
IS_WINDOWS = os.name == "nt"
START_TIMEOUT = 30.0
SETTLE_TIMEOUT = 60.0

STUB_SOURCE = '''\
#!/usr/bin/env python3
"""Stub agent CLI: an OMP-style --mode=json NDJSON stream, driven by env vars."""
import json
import os
import subprocess
import sys
import time


def emit(event):
    sys.stdout.write(json.dumps(event) + "\\n")
    sys.stdout.flush()


def main():
    argv_file = os.environ.get("STUB_ARGV_FILE")
    if argv_file:
        with open(argv_file, "w", encoding="utf-8") as handle:
            json.dump(sys.argv[1:], handle)
    mode = os.environ.get("STUB_MODE", "settle")
    emit({"type": "session", "id": os.environ.get("STUB_SESSION") or "stub-session-1"})
    if mode == "sleep":
        emit({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "half a report"}], "usage": {"cost": {"total": 0.25}}}})
        while True:
            emit({"type": "turn_end"})
            time.sleep(0.2)
    if mode == "quiet":
        # Stops writing after one event: a chatty agent dies with its runner's pipe
        # (BrokenPipeError), which hides the window this mode exists to hold open.
        time.sleep(300)
        return 0
    if mode == "flood":
        filler = "x" * 2000
        for index in range(300):
            emit({"type": "tool_use_start", "index": index, "filler": filler})
        emit({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "flooded"}]}})
        return 0
    if mode == "lingering":
        # A tool the agent started that keeps the agent's stdout open after the agent
        # exits: the runner's reader never sees EOF.
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(300)"],
            stdout=sys.stdout, stderr=sys.stderr,
        )
        with open(os.environ["STUB_CHILD_PID_FILE"], "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
        emit({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "started a tool and left"}]}})
        return 0
    if mode == "sleep_tool":
        # A tool that ignores SIGTERM, below an agent that is later stopped: the run may
        # only be called killed once that tool is gone too.
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(300)",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        with open(os.environ["STUB_CHILD_PID_FILE"], "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
        emit({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "working with a stubborn tool"}]}})
        while True:
            emit({"type": "turn_end"})
            time.sleep(0.2)
    if mode == "two-messages":
        emit({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "first draft"}]}})
        emit({"type": "turn_end"})
    emit({
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": os.environ.get("STUB_TEXT") or "STUB ANSWER: the stage finished."}],
            "usage": {"cost": {"total": 0.0123}},
        },
    })
    emit({"type": "turn_end"})
    return int(os.environ.get("STUB_EXIT") or "0")


if __name__ == "__main__":
    sys.exit(main())
'''

CONSOLE_PROBE = '''\
"""Reports the console a process sees; the parent compares two spawn modes."""
import ctypes
import json
import os
import subprocess
import sys

KERNEL32 = ctypes.windll.kernel32
USER32 = ctypes.windll.user32


def facts():
    attached = (ctypes.c_ulong * 64)()
    count = KERNEL32.GetConsoleProcessList(attached, 64)
    window = KERNEL32.GetConsoleWindow()
    visible = bool(USER32.IsWindowVisible(window)) if window else False
    return {"console": count > 0, "attached": count, "window": bool(window), "visible": visible}


def main(role):
    if role == "grandchild":
        print(json.dumps(facts()), flush=True)
        return 0
    if role == "child":
        grandchild = subprocess.run(
            [sys.executable, __file__, "grandchild"], capture_output=True, text=True
        )
        parsed = json.loads(grandchild.stdout.strip().splitlines()[-1]) if grandchild.stdout.strip() else {}
        print(json.dumps({"child": facts(), "grandchild": parsed}), flush=True)
        return 0
    hidden = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    out = {"parent": facts()}
    for label, flags in (("hidden_console", hidden), ("detached_process", detached)):
        done = subprocess.run(
            [sys.executable, __file__, "child"],
            capture_output=True, text=True, creationflags=flags, stdin=subprocess.DEVNULL,
        )
        out[label] = json.loads(done.stdout.strip().splitlines()[-1])
    print(json.dumps(out), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "parent"))
'''


def load_adapter() -> types.ModuleType:
    """The adapter as a module, without leaving bytecode in the installed skill dir."""
    module = types.ModuleType("gdd_omp_run")
    module.__file__ = str(ADAPTER)
    exec(compile(ADAPTER.read_bytes(), str(ADAPTER), "exec"), module.__dict__)
    return module


def own_console_visible() -> bool:
    """Is the test process's own console window visible (never the run's own question)?"""
    import ctypes

    window = ctypes.windll.kernel32.GetConsoleWindow()
    return bool(ctypes.windll.user32.IsWindowVisible(window)) if window else False


adapter = load_adapter()


class LauncherTests(unittest.TestCase):
    """One temp run root for the class; every test owns its own slugs and run dirs."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="omp-run-py."))
        cls.bin = cls.tmp / "bin"
        cls.bin.mkdir()
        cls.stub_py = cls.bin / "stub-agent.py"
        cls.stub_py.write_text(STUB_SOURCE, encoding="utf-8")
        if IS_WINDOWS:
            (cls.bin / "stub-agent.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" "{cls.stub_py}" %*\r\n', encoding="utf-8"
            )
        else:
            stub = cls.bin / "stub-agent"
            stub.write_text(STUB_SOURCE, encoding="utf-8")
            stub.chmod(0o755)
        cls.prompt = cls.tmp / "prompt.md"
        cls.prompt.write_text("do the thing\n", encoding="utf-8")
        cls.run_root = cls.tmp / "runs"
        cls.env = dict(os.environ)
        cls.env.update(
            {
                "OMP_RUN_ROOT": str(cls.run_root),
                "OMP_BIN": "stub-agent",
                "PATH": str(cls.bin) + os.pathsep + os.environ.get("PATH", ""),
            }
        )
        for key in ("GDD_RUN_ROOT", "OMP_LEDGER", "OMP_RUN_BACKEND", "OMP_RUN_EVENTS_MAX_BYTES",
                    "OMP_RUN_START_GRACE_SECONDS", "STUB_MODE", "STUB_EXIT", "STUB_ARGV_FILE"):
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

    def run_dir(self, slug):
        return self.run_root / datetime.now().strftime("%Y-%m-%d") / slug

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

    def wait_for_state(self, slug, states, timeout=SETTLE_TIMEOUT):
        """Poll state.json until its state is one of `states`; return the state."""
        deadline = time.monotonic() + timeout
        state = {}
        while time.monotonic() < deadline:
            try:
                state = self.state_of(slug)
            except (OSError, ValueError):
                time.sleep(adapter.POLL_SECONDS)
                continue
            if state.get("state") in states:
                return state
            time.sleep(adapter.POLL_SECONDS)
        self.fail(f"{slug} never reached {states}: last state {state}")

    def settle(self, slug, **env_overrides):
        self.start(slug, env=self.env_for(**env_overrides) if env_overrides else None)
        return self.wait_for_state(slug, {"done", "killed", "failed"})

    def kill_hard(self, run_dir):
        """Kill a run and its agent with no chance to finalize.

        `kill_tree` is not enough for the stale path: on POSIX it sends SIGTERM,
        which the runner handles by finalizing the run as killed — deliberately,
        that is what makes `kill` deterministic there. The stale path is for a run
        that died abruptly, so this uses SIGKILL (POSIX) or taskkill /F (Windows).
        """
        if IS_WINDOWS:
            adapter.kill_tree(str(run_dir), adapter.read_state_file(str(run_dir)))
            return
        for pid in adapter.recorded_pids(str(run_dir)):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

    def status_view(self, slug, env=None):
        """`status` output is one JSON object, then the recovery line when it acted."""
        proc = self.adapter_run("status", slug, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.split("\nstale_recovered: true")[0]), proc.stdout

    # -- start, settle, artifacts -------------------------------------------

    def test_01_start_settles_and_records_the_run(self):
        slug = "settle-01"
        state = self.settle(slug, STUB_TEXT="STUB ANSWER: stage complete.")
        self.assertEqual(state["state"], "done", state)
        self.assertEqual(state["exit"], 0)
        self.assertEqual(state["name"], slug)
        self.assertEqual(state["session_id"], "stub-session-1")
        self.assertGreater(state["duration_s"], 0)
        self.assertTrue(state["ended"])
        self.assertEqual(state["tool_calls"], 0)
        self.assertEqual(state["turns"], 1)
        self.assertEqual(state["cost_usd"], 0.0123)
        self.assertFalse(state["events_truncated"])
        self.assertEqual(state["events_dropped_bytes"], 0)
        self.assertFalse(state["tool_calls_partial"])
        # The contract fields the dispatcher reads.
        for field in ("name", "state", "exit", "cwd", "started", "ended", "duration_s", "pid",
                      "backend", "session_id", "answer_chars", "events_bytes",
                      "events_bytes_total", "events_truncated", "events_dropped_bytes"):
            self.assertIn(field, state)
        run_dir = self.run_dir(slug)
        answer = (run_dir / "answer.md").read_text(encoding="utf-8")
        self.assertEqual(answer.strip(), "STUB ANSWER: stage complete.")
        self.assertEqual(state["answer_chars"], len(answer))
        for name in ("prompt.md", "state.json", "lock", "events.ndjson", "events.stats.json",
                     "stderr.log", "runner.log", "exit.code", "session.id", "answer.md",
                     "finalized", "run.json"):
            self.assertTrue((run_dir / name).exists(), f"missing artifact {name}")
        self.assertTrue((run_dir / ("run.cmd" if IS_WINDOWS else "run.sh")).exists())
        self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "0")
        self.assertEqual((run_dir / "exit.code").read_text(encoding="utf-8").strip(), "0")
        self.assertEqual((run_dir / "prompt.md").read_text(encoding="utf-8"), "do the thing\n")
        events = [json.loads(line) for line in
                  (run_dir / "events.ndjson").read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(events[0]["type"], "session")
        self.assertEqual(events[0]["id"], "stub-session-1")
        self.assertEqual(state["events_bytes"], (run_dir / "events.ndjson").stat().st_size)
        self.assertEqual(state["events_bytes_total"], state["events_bytes"])
        replay = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(replay["argv"][1], str(ADAPTER))
        self.assertIn("_run", replay["argv"])
        # The agent got the prompt as the last positional argument.
        self.assertIn("--agent", replay["argv"])
        script = (run_dir / ("run.cmd" if IS_WINDOWS else "run.sh")).read_text(encoding="utf-8")
        self.assertIn("_run", script)
        self.assertIn(str(run_dir), script)
        self.assertIn(str(ADAPTER), script)
        if not IS_WINDOWS:
            self.assertTrue(script.startswith("#!/usr/bin/env bash"))
            self.assertIn("exec ", script)
            self.assertTrue(os.access(run_dir / "run.sh", os.X_OK))
        ledger = (self.run_root / "ledger.tsv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(ledger[0].split("\t")[0], "ended")
        self.assertTrue(any(slug in row and "\tdone\t0\t" in row for row in ledger[1:]), ledger)
        # And the read-only views agree with the finalized state.
        status = self.adapter_run("status", slug)
        self.assertEqual(status.returncode, 0, status.stderr)
        view, _ = self.status_view(slug)
        self.assertEqual(view["state"], "done")
        self.assertFalse(view["alive"])
        result = self.adapter_run("result", slug)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--- answer (first 1500 chars) ---", result.stdout)
        self.assertIn("STUB ANSWER: stage complete.", result.stdout)
        answer_only = self.adapter_run("answer", slug)
        self.assertEqual(answer_only.returncode, 0, answer_only.stderr)
        self.assertEqual(answer_only.stdout.strip(), "STUB ANSWER: stage complete.")

    def test_02_answer_keeps_only_the_final_assistant_message(self):
        state = self.settle("answer-02", STUB_MODE="two-messages", STUB_TEXT="final report")
        self.assertEqual(state["state"], "done")
        answer = (self.run_dir("answer-02") / "answer.md").read_text(encoding="utf-8")
        self.assertEqual(answer, "final report")
        # Two assistant messages, two turns: only the last one is the answer.
        self.assertEqual(state["turns"], 2)

    def test_03_live_run_reports_running_then_settles(self):
        slug = "live-03"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        live = self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        self.assertEqual(live["state"], "running")
        self.assertIsNone(live["exit"])
        self.assertTrue(live["pid"])
        self.assertTrue(live["agent_pid"])
        view, _ = self.status_view(slug)
        self.assertIn(view["state"], {"running", "done"})
        if view["state"] == "running":
            self.assertTrue(view["alive"])
        killed = self.adapter_run("kill", slug)
        self.assertEqual(killed.returncode, 0, killed.stderr)
        settled = self.wait_for_state(slug, {"killed"}, timeout=30.0)
        self.assertEqual(settled["state"], "killed")

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

    def test_05_stale_recovery_finalizes_once(self):
        slug = "stale-05"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        run_dir = self.run_dir(slug)
        # Kill the runner and the agent out from under the run: no finalizer left.
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
        self.assertEqual(failed["exit"], -1)
        self.assertTrue(failed["stale_recovered"])
        self.assertIn("disappeared without finalizing", failed["note"])
        self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "-1")
        before = (run_dir / "state.json").read_bytes()
        second = self.adapter_run("status", slug)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("stale_recovered: true", second.stdout)
        self.assertEqual(before, (run_dir / "state.json").read_bytes())
        listed = self.adapter_run("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        line = [row for row in listed.stdout.splitlines() if slug in row][0]
        self.assertIn("failed(stale)", line)

    def test_06_kill_stops_a_live_run_through_the_stop_file(self):
        slug = "kill-06"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        run_dir = self.run_dir(slug)
        pids = adapter.recorded_pids(str(run_dir))
        self.assertTrue(pids)
        killed = self.adapter_run("kill", slug)
        self.assertEqual(killed.returncode, 0, killed.stderr)
        self.assertIn(f"killed: {slug}", killed.stdout)
        state = self.wait_for_state(slug, {"killed"}, timeout=30.0)
        self.assertEqual(state["exit"], adapter.KILL_EXIT)
        self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "143")
        self.assertTrue((run_dir / "stop").exists())
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and any(adapter.pid_alive(pid) for pid in pids):
            time.sleep(adapter.POLL_SECONDS)
        self.assertFalse(any(adapter.pid_alive(pid) for pid in pids), f"still alive: {pids}")
        again = self.adapter_run("kill", slug)
        self.assertEqual(again.returncode, 1)
        self.assertIn("already finished", again.stderr)
        missing = self.adapter_run("kill", "no-such-run")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no run", missing.stderr)

    def test_07_event_bound_reports_dropped_bytes(self):
        slug = "flood-07"
        state = self.settle(slug, STUB_MODE="flood", OMP_RUN_EVENTS_MAX_BYTES=200000)
        self.assertEqual(state["state"], "done")
        self.assertGreater(state["events_dropped_bytes"], 0, state)
        self.assertTrue(state["events_truncated"])
        self.assertTrue(state["tool_calls_partial"])
        self.assertTrue(state["turns_partial"])
        self.assertTrue(state["cost_partial"])
        self.assertGreater(state["events_bytes_total"], state["events_bytes"])
        run_dir = self.run_dir(slug)
        text = (run_dir / "events.ndjson").read_text(encoding="utf-8")
        self.assertIn('"type":"truncated"', text)
        stats = json.loads((run_dir / "events.stats.json").read_text(encoding="utf-8"))
        self.assertEqual(stats["dropped_bytes"], state["events_dropped_bytes"])
        self.assertEqual(stats["total_bytes"], state["events_bytes_total"])
        self.assertTrue(stats["truncated"])
        self.assertLess(state["events_bytes"], state["events_bytes_total"])
        # The tail of the stream survives the bound: the agent's final message is
        # still the last line, even though most of the stream was dropped.
        last = [json.loads(line) for line in text.splitlines() if line.strip()][-1]
        self.assertEqual(last["type"], "message_end")
        self.assertEqual(last["message"]["content"][0]["text"], "flooded")
        view, _ = self.status_view(slug)
        self.assertEqual(view["events_dropped_bytes"], state["events_dropped_bytes"])
        self.assertTrue(view["events_truncated"])

    def test_08_detachment_is_measured_not_asserted(self):
        slug = "detach-08"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        live = self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        try:
            spawn = live["spawn"]
            detach = live["detach"]
            self.assertEqual(spawn["creationflags"], adapter.detach_flags())
            if IS_WINDOWS:
                self.assertEqual(spawn["mode"], "hidden-console")
                # The decision that keeps a dispatch, and every tool command below
                # it, from allocating a console window of its own.
                self.assertEqual(adapter.detach_flags() & adapter.DETACHED_MASK, 0)
                self.assertTrue(adapter.detach_flags() & adapter.NO_WINDOW_MASK)
                # What the run itself observed: it owns a console nobody sees.
                self.assertEqual(detach["mode"], "hidden-console")
                self.assertTrue(detach["console"], detach)
                self.assertGreater(detach["console_processes"], 0)
                if not own_console_visible():
                    self.assertFalse(detach["console_window_visible"], detach)
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

    @unittest.skipUnless(IS_WINDOWS, "console creation flags are a Windows question")
    def test_09_hidden_console_beats_detached_process(self):
        """The flags this adapter uses, compared against the one that flashes.

        A grandchild is where DETACHED_PROCESS shows itself: with no console to
        inherit, the first console-subsystem descendant allocates a visible window.
        """
        probe = self.tmp / "console_probe.py"
        probe.write_text(CONSOLE_PROBE, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(probe)], capture_output=True, text=True, timeout=120.0
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        facts = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertTrue(facts["hidden_console"]["child"]["console"])
        self.assertTrue(facts["hidden_console"]["grandchild"]["console"])
        self.assertFalse(facts["hidden_console"]["grandchild"]["window"])
        self.assertFalse(facts["detached_process"]["child"]["console"])
        self.assertTrue(facts["detached_process"]["grandchild"]["window"])
        self.assertTrue(facts["detached_process"]["grandchild"]["visible"])
        # The masks the rule is written in are the operating system's own values.
        self.assertEqual(adapter.NO_WINDOW_MASK, subprocess.CREATE_NO_WINDOW)
        self.assertEqual(adapter.NEW_GROUP_MASK, subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertEqual(adapter.DETACHED_MASK, getattr(subprocess, "DETACHED_PROCESS", 0x8))

    def test_10_a_young_pidless_run_is_not_finalized(self):
        slug = "grace-10"
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True)
        (run_dir / "prompt.md").write_text("dispatched a moment ago\n", encoding="utf-8")
        (run_dir / "state.json").write_text(
            json.dumps({"name": slug, "state": "running", "exit": None, "started": adapter.now_iso()}),
            encoding="utf-8",
        )
        view, _ = self.status_view(slug)
        self.assertEqual(view["state"], "running")
        self.assertFalse((run_dir / "finalized").exists())
        # The same run, older than the grace window: nothing will ever claim it.
        (run_dir / "state.json").write_text(
            json.dumps(
                {
                    "name": slug,
                    "state": "running",
                    "exit": None,
                    "started": (
                        datetime.now(timezone.utc) - timedelta(hours=2)
                    ).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        status = self.adapter_run("status", slug)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("stale_recovered: true", status.stdout)
        self.assertEqual(self.state_of(slug)["state"], "failed")

    def test_11_missing_state_is_unknown_never_success(self):
        slug = "unknown-11"
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

    def test_12_start_refuses_without_an_agent_binary(self):
        slug = "no-agent-12"
        proc = self.start(slug, assert_started=False, env=self.env_for(OMP_BIN="stub-agent-missing"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("agent binary not found", proc.stderr)
        self.assertFalse(self.run_dir(slug).exists())
        bad_cwd = self.adapter_run(
            "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp / "nope")
        )
        self.assertEqual(bad_cwd.returncode, 1)
        self.assertIn("is not a directory", bad_cwd.stderr)

    def test_13_replace_restarts_a_live_run(self):
        slug = "replace-13"
        self.start(slug, env=self.env_for(STUB_MODE="sleep"))
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        first_pid = self.state_of(slug)["pid"]
        again = self.adapter_run(
            "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp),
            env=self.env_for(STUB_MODE="sleep"),
        )
        self.assertEqual(again.returncode, 1)
        self.assertIn("still running", again.stderr)
        replaced = self.adapter_run(
            "start", "--name", slug, "--prompt", str(self.prompt), "--cwd", str(self.tmp),
            "--replace", env=self.env_for(STUB_MODE="sleep"),
        )
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        self.assertNotEqual(self.state_of(slug)["pid"], first_pid)
        previous = sorted(self.run_dir(slug).parent.glob(f"{slug}.prev-*"))
        self.assertEqual(len(previous), 1, previous)
        self.assertTrue((previous[0] / "finalized").exists())
        self.assertEqual(
            json.loads((previous[0] / "state.json").read_text(encoding="utf-8"))["state"], "killed"
        )
        self.adapter_run("kill", slug)
        self.wait_for_state(slug, {"killed"}, timeout=30.0)

    def test_14_list_and_tail(self):
        empty_root = self.tmp / "empty-runs"
        listed = self.adapter_run("list", env=self.env_for(OMP_RUN_ROOT=empty_root))
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("(no runs recorded)", listed.stdout)
        self.settle("list-14")
        listed = self.adapter_run("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        line = [row for row in listed.stdout.splitlines() if "list-14" in row][0]
        self.assertIn("done exit=0", line)
        tail = self.adapter_run("tail", "list-14", "2")
        self.assertEqual(tail.returncode, 0, tail.stderr)
        lines = [line for line in tail.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[-1])["type"], "turn_end")
        self.assertEqual(self.adapter_run("tail", "list-14").returncode, 0)

    def test_15_agent_arguments_are_passed_through(self):
        slug = "argv-15"
        argv_file = self.tmp / "argv-15.json"
        state = self.settle(
            slug,
            STUB_ARGV_FILE=argv_file,
            STUB_SESSION="resumed-session-7",
        )
        self.assertEqual(state["state"], "done")
        argv = json.loads(argv_file.read_text(encoding="utf-8"))
        self.assertEqual(argv[0:4], ["-p", "--mode=json", "--approval-mode", "yolo"])
        self.assertEqual(argv[-1].strip(), "do the thing")
        self.assertEqual(state["session_id"], "resumed-session-7")
        explicit = self.settle(
            "argv-15b",
            STUB_ARGV_FILE=argv_file,
            STUB_SESSION="resumed-session-8",
        )
        self.assertEqual(explicit["state"], "done")
        # The prompt is the last argument, and the prompt file is unchanged.
        self.assertEqual(json.loads(argv_file.read_text(encoding="utf-8"))[-1].strip(), "do the thing")
        flags = self.start(
            "argv-15c",
            "--model", "some-model",
            "--thinking", "high",
            "--max-time", "600",
            "--profile", "some-profile",
            "--resume", "session-9",
            "--extra", "--no-session --tools bash",
            # A resumed agent keeps its session id, so the stub reports that id:
            # whatever the agent reports is what session.id ends up holding.
            env=self.env_for(STUB_MODE="sleep", STUB_SESSION="session-9"),
            assert_started=False,
        )
        self.assertEqual(flags.returncode, 0, flags.stderr)
        self.wait_for_state("argv-15c", {"running"}, timeout=START_TIMEOUT)
        live_dir = self.run_dir("argv-15c")
        replay = json.loads((live_dir / "run.json").read_text(encoding="utf-8"))
        agent_argv = replay["agent_argv"]
        if IS_WINDOWS:
            # The stub is a `.cmd` shim, so the recorded command line names the
            # interpreter that runs it before the agent's own flags.
            self.assertEqual(agent_argv[1], "/c")
            self.assertTrue(agent_argv[0].lower().endswith(("cmd.exe", "cmd")), agent_argv[0])
        start = agent_argv.index("-p")
        self.assertEqual(
            agent_argv[start:start + 4], ["-p", "--mode=json", "--approval-mode", "yolo"]
        )
        self.assertEqual(agent_argv[agent_argv.index("--model") + 1], "some-model")
        self.assertEqual(agent_argv[agent_argv.index("--thinking") + 1], "high")
        self.assertEqual(agent_argv[agent_argv.index("--max-time") + 1], "600")
        self.assertEqual(agent_argv[agent_argv.index("--profile") + 1], "some-profile")
        self.assertEqual(agent_argv[agent_argv.index("-r") + 1], "session-9")
        self.assertIn("--no-session", agent_argv)
        self.assertIn("bash", agent_argv)
        # -r comes before --profile and --extra, exactly like the reference adapter.
        self.assertLess(agent_argv.index("-r"), agent_argv.index("--profile"))
        self.assertLess(agent_argv.index("--profile"), agent_argv.index("--no-session"))
        self.assertEqual((live_dir / "session.id").read_text(encoding="utf-8").strip(), "session-9")
        self.assertEqual(self.state_of("argv-15c")["resumed_from"], "session-9")
        self.adapter_run("kill", "argv-15c")
        self.wait_for_state("argv-15c", {"killed"}, timeout=30.0)
        # A single agent flag that begins with '-': the spelling the reference
        # adapter accepts and argparse would otherwise refuse.
        argv_file.unlink()
        self.start(
            "argv-15d",
            "--extra", "--no-session",
            env=self.env_for(STUB_MODE="sleep", STUB_ARGV_FILE=argv_file),
        )
        self.wait_for_state("argv-15d", {"running"}, timeout=START_TIMEOUT)
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline and not argv_file.exists():
            time.sleep(adapter.POLL_SECONDS)
        recorded = json.loads(argv_file.read_text(encoding="utf-8"))
        self.assertIn("--no-session", recorded)
        self.assertEqual(recorded[-1].strip(), "do the thing")
        self.adapter_run("kill", "argv-15d")
        self.wait_for_state("argv-15d", {"killed"}, timeout=30.0)

    def test_16_gdd_runs_a_python_launcher_through_the_interpreter(self):
        """gdd.py must not hand CreateProcess a `.py` path on Windows.

        POSIX executes a `.py` adapter through its shebang and exec bit; Windows
        cannot, so the dispatcher prefixes the current interpreter there and
        nothing changes on POSIX.
        """
        code = (
            "import json, sys; "
            f"sys.path.insert(0, {str(SCRIPTS)!r}); "
            "import gdd; "
            "print(json.dumps({"
            "'py': gdd.launcher_command('/opt/skills/gdd/scripts/adapters/omp-run.py'), "
            "'bin': gdd.launcher_command('/opt/tools/gdd-launcher.exe')}))"
        )
        done = subprocess.run(
            [sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=60.0
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        commands = json.loads(done.stdout.strip().splitlines()[-1])
        path = "/opt/skills/gdd/scripts/adapters/omp-run.py"
        if IS_WINDOWS:
            self.assertEqual(
                [os.path.normcase(item) for item in commands["py"]],
                [os.path.normcase(sys.executable), os.path.normcase(path)],
            )
            self.assertEqual(commands["bin"], ["/opt/tools/gdd-launcher.exe"])
        else:
            self.assertEqual(commands["py"], [path])
            self.assertEqual(commands["bin"], ["/opt/tools/gdd-launcher.exe"])

    def test_19_gdd_dispatches_through_the_bundled_launcher(self):
        """The dispatcher's own path: gdd.py -> the bundled adapter -> state, ledger, answer.

        The bash selftest covers this shape with a fake launcher on PATH. This runs
        the real default — `adapters/omp-run.py`, named by `DEFAULT_LAUNCHER`, spawned
        the way `launcher_command` decides — against the stub agent, which is what a
        Windows operator actually dispatches.
        """
        repo = self.tmp / "dispatch-repo"
        goals = repo / "docs" / "goals"
        goals.mkdir(parents=True)
        (goals / "0002-dispatch-smoke.md").write_text(
            "# 0002 — dispatch smoke\n\nState: Ready\n\nDone when: the smoke runs.\n",
            encoding="utf-8",
        )
        git = ["git", "-C", str(repo)]
        identity = ["-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false"]

        def run_git(*args):
            done = subprocess.run([*git, *args], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            return done

        run_git("init", "-q")
        run_git("add", "-A")
        run_git(*identity, "commit", "-q", "-m", "base")
        run_git("update-ref", "refs/remotes/origin/main", "HEAD")
        (repo / "second.txt").write_text("a second commit, so base..head is a range\n", encoding="utf-8")
        run_git("add", "-A")
        run_git(*identity, "commit", "-q", "-m", "head")

        env = self.env_for(
            GDD_STATE_FILE=self.tmp / "dispatch-ledger.tsv",
            GDD_TASK_ROOT=self.tmp / "dispatch-tasks",
            STUB_TEXT="BUNDLED LAUNCHER SMOKE: implement stage done.",
        )
        done = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPTS / "gdd.py"),
                "stage",
                "--repo",
                str(repo),
                "--goal",
                "0002",
                "--stage",
                "implement",
                "--wait",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=180,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("state=done", done.stdout)
        self.assertIn("BUNDLED LAUNCHER SMOKE", done.stdout)
        run_dir = Path(
            [
                line.split(":", 1)[1].strip()
                for line in done.stdout.splitlines()
                if line.startswith("run_dir:")
            ][0]
        )
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "done")
        self.assertEqual(state["exit"], 0)
        # The launcher the dispatcher actually ran is the bundled adapter.
        self.assertEqual(Path(state["launcher"]).name, ADAPTER.name)
        self.assertEqual(
            (run_dir / "answer.md").read_text(encoding="utf-8").strip(),
            "BUNDLED LAUNCHER SMOKE: implement stage done.",
        )
        ledger = (self.tmp / "dispatch-ledger.tsv").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any("\timplement\t" in row for row in ledger[1:]), ledger)
        self.assertTrue(
            any(row.split("\t")[10] == "-" and "exit=0" in row for row in ledger[2:]),
            f"no completion row in {ledger}",
        )
        self.assertTrue(state["detach"]["mode"] in {"hidden-console", "new-session"}, state["detach"])

    def test_17_events_writer_is_the_shared_implementation(self):
        """The adapter uses adapters/events-writer.py, not a second copy of the bound."""
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn('"events-writer.py"', source)
        self.assertNotIn("def _compact", source)
        # Loading it leaves no bytecode beside the installed adapter, and the bound
        # comes from the documented key (with the default loud when it is unset).
        writer_class, resolve_cap = adapter.load_writer()
        self.assertTrue(writer_class)
        # Loading must not *create* bytecode: another tool (py_compile) may have left
        # some, so compare before and after rather than asserting the directory empty.
        cached_before = sorted(path.name for path in ADAPTER.parent.glob("__pycache__/*"))
        adapter.load_writer()
        cached_after = sorted(path.name for path in ADAPTER.parent.glob("__pycache__/*"))
        self.assertEqual(cached_before, cached_after)
        saved = os.environ.get("OMP_RUN_EVENTS_MAX_BYTES")
        try:
            os.environ.pop("OMP_RUN_EVENTS_MAX_BYTES", None)
            cap, warning = resolve_cap()
            self.assertGreater(cap, 0)
            self.assertIsNotNone(warning, "an unset cap must be reported as defaulted")
            os.environ["OMP_RUN_EVENTS_MAX_BYTES"] = "4096"
            cap, warning = resolve_cap()
            self.assertEqual(cap, 4096)
            self.assertIsNone(warning)
            os.environ["OMP_RUN_EVENTS_MAX_BYTES"] = "not a number"
            cap, warning = resolve_cap()
            self.assertGreater(cap, 0)
            self.assertIn("not an integer", warning)
        finally:
            if saved is None:
                os.environ.pop("OMP_RUN_EVENTS_MAX_BYTES", None)
            else:
                os.environ["OMP_RUN_EVENTS_MAX_BYTES"] = saved


    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed here")
    def test_18_tmux_backend_owns_its_session(self):
        """The attachable backend, on an isolated server: only its own session is touched."""
        socket_dir = self.tmp / "tmux-tmp"
        socket_dir.mkdir(exist_ok=True)
        env = self.env_for(STUB_MODE="sleep", TMUX_TMPDIR=str(socket_dir))
        slug = "tmux-18"
        session = f"omp-{slug}"
        self.start(slug, "--backend", "tmux", env=env)
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        state = self.state_of(slug)
        self.assertEqual(state["backend"], "tmux")
        self.assertEqual(state["tmux"], session)
        self.assertEqual(adapter.lock_of(str(self.run_dir(slug)))["tmux"], session)
        view, _ = self.status_view(slug, env=env)
        self.assertTrue(view["tmux_alive"], view)
        killed = self.adapter_run("kill", slug, env=env)
        self.assertEqual(killed.returncode, 0, killed.stderr)
        self.wait_for_state(slug, {"killed"}, timeout=30.0)
        self.assertFalse(
            subprocess.run(
                ["tmux", "has-session", "-t", session],
                env=env, capture_output=True,
            ).returncode
            == 0
        )
        # The kill above ended only this run's session; tmux kill-server is never
        # used, so an operator's other sessions on the same socket survive.


    def test_20_a_second_start_cannot_clobber_a_fresh_claim(self):
        """A run inside its pidless window is occupied work, not a stale directory."""
        slug = "claim-20"
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True)
        # Exactly the window `start` holds before the runner records a pid.
        (run_dir / "start.lock").write_text("", encoding="utf-8")
        (run_dir / "prompt.md").write_text("first dispatch\n", encoding="utf-8")
        (run_dir / "state.json").write_text(
            json.dumps(
                {"name": slug, "state": "running", "exit": None, "started": adapter.now_iso()}
            ),
            encoding="utf-8",
        )
        proc = self.start(slug, assert_started=False)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("still running", proc.stderr)
        self.assertTrue((run_dir / "prompt.md").read_text(encoding="utf-8").startswith("first"))
        self.assertFalse((run_dir / "run.json").exists())

    def test_21_a_forced_stop_is_recorded_as_killed(self):
        """A runner that cannot finalize is stopped by force, and the stop is recorded as one."""
        slug = "forced-21"
        env = self.env_for(STUB_MODE="quiet", OMP_RUN_STOP_WAIT_SECONDS="1")
        self.start(slug, env=env)
        run_dir = self.run_dir(slug)
        live = self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        # A recorded pid precedes the stub's only write. Let the product consume
        # its session event before killing the pipe reader, or BrokenPipe kills it too.
        deadline = time.monotonic() + START_TIMEOUT
        while (adapter.read_sidecar(str(run_dir), "session.id") != "stub-session-1"
               and time.monotonic() < deadline):
            time.sleep(adapter.POLL_SECONDS)
        self.assertEqual(adapter.read_sidecar(str(run_dir), "session.id"), "stub-session-1",
                         "quiet agent never published session readiness before the forced stop")
        runner = live["pid"]
        # Kill the runner alone: the agent it started stays alive, so the run is live
        # with nobody left to finalize it — the case the forced path exists for.
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(runner)], capture_output=True
            )
        else:
            os.kill(runner, signal.SIGKILL)
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and adapter.pid_alive(runner):
            time.sleep(adapter.POLL_SECONDS)
        self.assertFalse(adapter.pid_alive(runner))
        self.assertTrue(adapter.run_alive(str(run_dir)))
        killed = self.adapter_run("kill", slug, env=env)
        self.assertEqual(killed.returncode, 0, killed.stdout + killed.stderr)
        state = self.wait_for_state(slug, {"killed"}, timeout=60.0)
        self.assertEqual(state["exit"], adapter.KILL_EXIT)
        self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "143")
        self.assertNotIn("stale_recovered", state)

    def test_22_concurrent_recovery_appends_one_row(self):
        """Two readers seeing the same dead run finalize it once, with one ledger row."""
        slug = "recover-22"
        env = self.env_for(STUB_MODE="sleep")
        self.start(slug, env=env)
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        run_dir = self.run_dir(slug)
        self.kill_hard(run_dir)
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and adapter.run_alive(str(run_dir)):
            time.sleep(adapter.POLL_SECONDS)
        ledger = self.run_root / "ledger.tsv"
        readers = [
            subprocess.Popen(
                [sys.executable, str(ADAPTER), "status", slug],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                text=True,
            )
            for _ in range(4)
        ]
        for reader in readers:
            reader.communicate(timeout=60)
        state = self.state_of(slug)
        self.assertEqual(state["state"], "failed")
        self.assertTrue(state["stale_recovered"])
        rows = [
            row
            for row in ledger.read_text(encoding="utf-8").splitlines()[1:]
            if row.split("\t")[1] == slug
        ]
        self.assertEqual(len(rows), 1, rows)

    def test_22_delayed_recovery_rechecks_marker_after_claim(self):
        """A reader paused before claiming cannot rewrite another reader's finished run."""
        slug = "recover-delayed-22"
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True)
        ledger = self.tmp / "recover-delayed-22.tsv"
        adapter.write_json(
            str(run_dir / "state.json"),
            {
                "name": slug,
                "state": "running",
                "exit": None,
                "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "ledger": str(ledger),
            },
        )
        events = [
            {"type": "session", "id": "recovery-session"},
            {"type": "message_end", "message": {
                "role": "assistant", "content": [{"type": "text", "text": "partial report"}],
            }},
        ]
        (run_dir / "events.ndjson").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )
        real_claim = adapter.claim_finalize
        first_ended = adapter.now_iso()
        later_ended = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        finished = {}
        artifacts = {}

        def delayed_claim(path):
            # The delayed reader has passed effective_state's marker check. Let the
            # other reader finish and release the real claim before this one takes it.
            self.assertFalse((run_dir / "finalized").exists())
            with (
                mock.patch.object(adapter, "claim_finalize", real_claim),
                mock.patch.object(adapter, "now_iso", return_value=first_ended),
            ):
                state, recovered = adapter.effective_state(path)
            self.assertTrue(recovered)
            self.assertEqual(state["state"], "failed")
            self.assertEqual(state["exit"], -1)
            self.assertFalse((run_dir / "finalize.lock").exists())
            finished.update(state)
            for name in ("state.json", "answer.md", "exit.code", "session.id", "finalized"):
                artifact = run_dir / name
                artifacts[name] = (artifact.read_bytes(), artifact.stat().st_mtime_ns)
            claimed, descriptor = real_claim(path)
            self.assertTrue(claimed)
            self.assertIsNotNone(descriptor)
            return claimed, descriptor

        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(adapter, "claim_finalize", side_effect=delayed_claim) as claim,
            mock.patch.object(adapter, "now_iso", return_value=later_ended),
        ):
            state, _ = adapter.effective_state(str(run_dir))
        claim.assert_called_once_with(str(run_dir))
        rows = [
            row for row in ledger.read_text(encoding="utf-8").splitlines()[1:]
            if row.split("\t")[1] == slug
        ]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(state, finished)
        for name, before in artifacts.items():
            artifact = run_dir / name
            self.assertEqual((artifact.read_bytes(), artifact.stat().st_mtime_ns), before, name)
        self.assertFalse((run_dir / "finalize.lock").exists())

    def test_23_a_terminal_state_without_a_marker_is_repaired(self):
        """A finalizer that died between state.json and the marker gets the marker written."""
        slug = "repair-23"
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text(
            json.dumps(
                {
                    "name": slug,
                    "state": "done",
                    "exit": 0,
                    # Older than the startup grace: a terminal state that young could
                    # still be the runner's own finalization in flight.
                    "started": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                    "ended": adapter.now_iso(),
                    "duration_s": 1.0,
                }
            ),
            encoding="utf-8",
        )
        view, output = self.status_view(slug)
        self.assertEqual(view["state"], "done")
        self.assertTrue((run_dir / "finalized").exists())
        self.assertEqual((run_dir / "finalized").read_text(encoding="utf-8"), "0")
        repaired = self.state_of(slug)
        self.assertTrue(repaired["finalize_repaired"])
        self.assertIn("without the finalized marker", repaired["note"])
        before = (run_dir / "state.json").read_bytes()
        self.adapter_run("status", slug)
        self.assertEqual(before, (run_dir / "state.json").read_bytes())

    def test_24_an_open_event_stream_is_recorded(self):
        """A tool holding the agent's stdout after it exits is stated, not hidden."""
        slug = "stream-24"
        child_file = self.tmp / "linger-24.pid"
        env = self.env_for(
            STUB_MODE="lingering",
            STUB_CHILD_PID_FILE=child_file,
            OMP_RUN_DRAIN_TIMEOUT_SECONDS="1",
        )
        self.start(slug, env=env)
        state = self.wait_for_state(slug, {"done"}, timeout=SETTLE_TIMEOUT)
        self.assertTrue(state["stream_incomplete"], state)
        self.assertIn("event stream was still open", state["note"])
        self.assertEqual(state["state"], "done")
        run_dir = self.run_dir(slug)
        # The writer's terminal passthrough is off for this adapter: the event bound
        # bounds the whole run directory's growth, not just events.ndjson.
        self.assertLess((run_dir / "runner.log").stat().st_size, 4096)
        lingering = int(child_file.read_text(encoding="utf-8"))
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/PID", str(lingering)], capture_output=True)
        else:
            try:
                os.kill(lingering, signal.SIGKILL)
            except OSError:
                pass

    def test_25_a_run_is_not_killed_while_its_tool_lives(self):
        """Escalation reaches the tool the agent started, not just the agent."""
        slug = "tree-25"
        child_file = self.tmp / "tool-25.pid"
        env = self.env_for(
            STUB_MODE="sleep_tool",
            STUB_CHILD_PID_FILE=child_file,
            OMP_RUN_STOP_WAIT_SECONDS="2",
        )
        self.start(slug, env=env)
        self.wait_for_state(slug, {"running"}, timeout=START_TIMEOUT)
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline and not child_file.exists():
            time.sleep(adapter.POLL_SECONDS)
        tool = int(child_file.read_text(encoding="utf-8"))
        self.assertTrue(adapter.pid_alive(tool))
        killed = self.adapter_run("kill", slug, env=env)
        self.assertEqual(killed.returncode, 0, killed.stdout + killed.stderr)
        state = self.wait_for_state(slug, {"killed"}, timeout=60.0)
        self.assertEqual(state["exit"], adapter.KILL_EXIT)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and adapter.pid_alive(tool):
            time.sleep(adapter.POLL_SECONDS)
        self.assertFalse(adapter.pid_alive(tool), f"tool {tool} outlived the run")

    def test_26_relative_configuration_resolves_against_the_callers_directory(self):
        """A relative run root or agent path means one directory, not two."""
        slug = "relative-26"
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(exist_ok=True)
        env = self.env_for(
            OMP_RUN_ROOT="relative-runs",
            OMP_BIN="./bin/" + ("stub-agent.cmd" if IS_WINDOWS else "stub-agent"),
        )
        proc = subprocess.run(
            [
                sys.executable,
                str(ADAPTER),
                "start",
                "--name",
                slug,
                "--prompt",
                str(self.prompt),
                "--cwd",
                str(elsewhere),
            ],
            cwd=str(self.tmp),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        expected = self.tmp / "relative-runs" / datetime.now().strftime("%Y-%m-%d") / slug
        self.assertTrue(expected.exists(), f"run landed outside the calling directory: {expected}")
        state = json.loads((expected / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(os.path.dirname(state["agent"]), str(self.bin))
        self.wait_for_state_in(expected, {"done", "killed", "failed"}, timeout=SETTLE_TIMEOUT)

    def wait_for_state_in(self, run_dir, states, timeout=SETTLE_TIMEOUT):
        deadline = time.monotonic() + timeout
        state = {}
        while time.monotonic() < deadline:
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            if state.get("state") in states:
                return state
            time.sleep(adapter.POLL_SECONDS)
        self.fail(f"{run_dir} never reached {states}: last {state}")

    @unittest.skipUnless(IS_WINDOWS, "cmd.exe is the shell that expands the prompt")
    def test_27_a_percent_prompt_is_refused_for_a_cmd_agent(self):
        """cmd.exe rewrites %VAR% in the command line, so that prompt is refused."""
        prompt = self.tmp / "percent-27.md"
        prompt.write_text("set PATH like %PATH% on Windows\n", encoding="utf-8")
        proc = self.adapter_run(
            "start", "--name", "percent-27", "--prompt", str(prompt), "--cwd", str(self.tmp)
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("cmd.exe would expand", proc.stderr)
        self.assertIn("%PATH%", proc.stderr)
        self.assertFalse(self.run_dir("percent-27").exists())

    def test_28_start_refuses_an_agent_with_a_missing_shebang_interpreter(self):
        """An existing executable is not proof that the OS can start the agent."""
        slug = "spawn-failure-28"
        missing_interpreter = self.bin / "missing-interpreter"
        broken_agent = self.bin / "unspawnable-agent.exe"
        broken_agent.write_text(f"#!{missing_interpreter}\n", encoding="utf-8")
        broken_agent.chmod(0o755)
        self.assertFalse(missing_interpreter.exists())
        proc = self.start(slug, assert_started=False, env=self.env_for(OMP_BIN=broken_agent))
        state = self.wait_for_state(slug, {"failed"})
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertNotIn("started:", proc.stdout)
        self.assertIn("agent did not start", proc.stderr)
        self.assertEqual(state["exit"], 127)
        self.assertTrue(state.get("error"), state)
        self.assertIn(state["error"], proc.stderr)
        self.assertEqual(state["note"], f"agent did not start: {state['error']}")
        self.assertFalse(state.get("agent_pid"), state)
        self.assertFalse((self.run_dir(slug) / "session.id").exists())

    def test_29_start_rejects_a_failed_run_even_while_the_runner_is_alive(self):
        """A terminal startup failure differs from a healthy, slow agent spawn."""
        for verdict in ("failed", "running"):
            with self.subTest(state=verdict):
                slug = f"startup-29-{verdict}"
                args = adapter.build_parser().parse_args(
                    ["start", "--name", slug, "--prompt", str(self.prompt),
                     "--cwd", str(self.tmp)]
                )
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    mock.patch.dict(os.environ, self.env, clear=True),
                    mock.patch.object(adapter, "spawn_runner"),
                    mock.patch.object(adapter, "wait_for_start", return_value={"state": verdict}),
                    mock.patch.object(adapter, "recorded_pids", return_value=[os.getpid()]),
                    mock.patch.object(adapter, "pid_alive", return_value=True),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    if verdict == "failed":
                        with self.assertRaises(SystemExit) as caught:
                            adapter.cmd_start(args)
                        self.assertEqual(caught.exception.code, 1)
                        self.assertNotIn("started:", stdout.getvalue())
                        self.assertIn("runner exited before the agent started", stderr.getvalue())
                    else:
                        self.assertEqual(adapter.cmd_start(args), 0)
                        self.assertIn(f"started: {slug}", stdout.getvalue())


    def test_30_completed_replay_initializes_a_fresh_run(self):
        """The replay's events, answer, exit and counters belong to one new execution."""
        slug = "replay-30"
        argv_file = self.tmp / "replay-30-argv.json"
        ledger = self.tmp / "replay-30-ledger.tsv"
        env = self.env_for(
            STUB_MODE="two-messages", STUB_TEXT="the original answer",
            STUB_SESSION="original-session", STUB_ARGV_FILE=argv_file,
            OMP_LEDGER=ledger, OMP_RUN_EVENTS_MAX_BYTES="4096",
        )
        self.start(slug, "--model", "some-model", "--extra", "--no-session", env=env)
        first = self.wait_for_state(slug, {"done"})
        run_dir = self.run_dir(slug)
        self.assertEqual(adapter.wait_for_marker(str(run_dir), START_TIMEOUT), "0")
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline and adapter.run_alive(str(run_dir)):
            time.sleep(adapter.POLL_SECONDS)
        self.assertFalse(adapter.run_alive(str(run_dir)))
        original = {name: (run_dir / name).read_bytes() for name in (
            "state.json", "answer.md", "exit.code", "events.ndjson", "events.stats.json",
            "session.id", "finalized", "prompt.md", "run.json",
        )}
        original_argv = json.loads(argv_file.read_text(encoding="utf-8"))
        script = run_dir / ("run.cmd" if IS_WINDOWS else "run.sh")
        command = ([os.environ.get("COMSPEC", "cmd.exe"), "/c", str(script)]
                   if IS_WINDOWS else ["bash", str(script)])
        replay_env = dict(env)
        replay_env.update(
            STUB_MODE="settle", STUB_TEXT="a different replay answer", STUB_EXIT="3",
            STUB_SESSION="replay-session", OMP_BIN="must-not-resolve-this-agent",
            OMP_RUN_ROOT=str(self.tmp / "not-the-recorded-root"),
            OMP_LEDGER=str(self.tmp / "not-the-recorded-ledger.tsv"),
            OMP_RUN_EVENTS_MAX_BYTES="1",
        )
        replay = subprocess.run(
            command, cwd=str(self.bin), env=replay_env, capture_output=True, text=True,
            timeout=SETTLE_TIMEOUT,
        )
        self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
        state = self.wait_for_state(slug, {"done", "failed"})
        # Check the event first: the old bug executes again but keeps the old answer.
        self.assertIn("a different replay answer", (run_dir / "events.ndjson").read_text(encoding="utf-8"))
        self.assertEqual((run_dir / "answer.md").read_text(encoding="utf-8"), "a different replay answer")
        self.assertEqual(adapter.wait_for_marker(str(run_dir), SETTLE_TIMEOUT), "3")
        self.assertEqual((run_dir / "exit.code").read_text(encoding="utf-8").strip(), "3")
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["exit"], 3)
        self.assertEqual(state["turns"], 1)
        self.assertEqual(first["turns"], 2)
        self.assertEqual(state["session_id"], "replay-session")
        self.assertEqual(state["answer_chars"], len("a different replay answer"))
        self.assertEqual(state["events_bytes"], (run_dir / "events.ndjson").stat().st_size)
        self.assertEqual(state["events_bytes_total"], state["events_bytes"])
        self.assertFalse(state["events_truncated"])
        self.assertEqual(state["cwd"], str(self.tmp))
        self.assertNotEqual(state["started"], first["started"])
        self.assertNotEqual(state["pid"], first["pid"])
        self.assertEqual(json.loads(argv_file.read_text(encoding="utf-8")), original_argv)
        self.assertEqual((run_dir / "run.json").read_bytes(), original["run.json"])
        previous = list(run_dir.parent.glob(f"{slug}.prev-*"))
        self.assertEqual(len(previous), 1, previous)
        for name, content in original.items():
            self.assertEqual((previous[0] / name).read_bytes(), content, name)
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(adapter.find_run(slug), str(run_dir))
            old_state, recovered = adapter.effective_state(str(previous[0]))
        self.assertEqual(old_state, first)
        self.assertFalse(recovered)
        self.assertEqual(old_state["state"], "done")
        rows = ledger.read_text(encoding="utf-8").splitlines()[1:]
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual([row.split("\t")[3] for row in rows], ["0", "3"])
        self.assertFalse((self.tmp / "not-the-recorded-root").exists())
        self.assertFalse((self.tmp / "not-the-recorded-ledger.tsv").exists())

    def test_31_delayed_finalizer_keeps_the_first_final_state(self):
        """A second finalizer with a stale exit code returns the first state unchanged."""
        slug = "finalize-delayed-31"
        ledger = self.tmp / "finalize-delayed-31.tsv"
        first = self.settle(slug, STUB_TEXT="the final answer", OMP_LEDGER=ledger)
        run_dir = self.run_dir(slug)
        self.assertEqual(adapter.wait_for_marker(str(run_dir), START_TIMEOUT), "0")
        artifacts = {name: (run_dir / name).read_bytes() for name in (
            "state.json", "answer.md", "exit.code", "session.id", "finalized",
        )}
        before = ledger.read_bytes()
        delayed = adapter.finalize(str(run_dir), -1, recovered=True)
        self.assertEqual(delayed, first)
        self.assertEqual(ledger.read_bytes(), before)
        self.assertEqual(len(before.decode("utf-8").splitlines()), 2)
        for name, content in artifacts.items():
            self.assertEqual((run_dir / name).read_bytes(), content, name)

    def test_32_completed_slug_starts_cannot_archive_a_live_run(self):
        """Pause after occupancy, then dispatch a rival before the first rename."""
        slug = "start-race-32"
        run_dir = self.run_dir(slug)
        run_dir.mkdir(parents=True)
        adapter.write_json(str(run_dir / "state.json"), {"name": slug, "state": "done"})
        (run_dir / "finalized").write_text("0\n", encoding="utf-8")
        (run_dir / "answer.md").write_text("previous answer\n", encoding="utf-8")
        args = adapter.build_parser().parse_args(
            ["start", "--name", slug, "--prompt", str(self.prompt),
             "--cwd", str(self.tmp)]
        )
        real_move = adapter.move_aside
        rival = []
        launches = []
        interleaved = False
        runner_pid = 987654321
        stdout, stderr = io.StringIO(), io.StringIO()

        def move_after_rival(path):
            nonlocal interleaved
            if not interleaved:
                interleaved = True
                try:
                    rival.append(adapter.cmd_start(args))
                except SystemExit as exc:
                    rival.append(exc.code)
            return real_move(path)

        def runner_owns_run(command, cwd, log_path):
            launches.append(command)
            adapter.update_lock(str(run_dir), pid=runner_pid, agent_pid=runner_pid)
            state = adapter.read_state_file(str(run_dir))
            state.update(pid=runner_pid, agent_pid=runner_pid)
            adapter.write_json(str(run_dir / "state.json"), state)
            adapter.remove_quietly(str(run_dir / "start.lock"))

        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(adapter, "move_aside", side_effect=move_after_rival),
            mock.patch.object(adapter, "spawn_runner", side_effect=runner_owns_run),
            mock.patch.object(adapter, "wait_for_start", side_effect=adapter.read_state_file),
            mock.patch.object(adapter, "pid_alive", side_effect=lambda pid: pid == runner_pid),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(adapter.cmd_start(args), 0)
            self.assertTrue(adapter.run_alive(str(run_dir)))
        self.assertEqual(rival, [1], stderr.getvalue())
        self.assertIn("another start", stderr.getvalue())
        self.assertEqual(len(launches), 1)
        self.assertEqual(stdout.getvalue().count(f"started: {slug}"), 1)
        self.assertEqual(self.state_of(slug)["state"], "running")
        self.assertFalse((run_dir / "finalized").exists())
        previous = list(run_dir.parent.glob(f"{slug}.prev-*"))
        self.assertEqual(len(previous), 1, previous)
        self.assertTrue((previous[0] / "finalized").exists())
        self.assertEqual(adapter.read_state_file(str(previous[0]))["state"], "done")
        self.assertEqual((previous[0] / "answer.md").read_text(encoding="utf-8"),
                         "previous answer\n")

    def test_33_a_killed_starter_releases_the_slug_claim(self):
        """The claim file survives, but a killed holder cannot wedge a later start."""
        slug = "killed-starter-33"
        run_dir = self.run_dir(slug)
        code = """
import sys, types
module = types.ModuleType("gdd_omp_run_claim_holder")
module.__file__ = sys.argv[1]
with open(module.__file__, "rb") as source:
    exec(compile(source.read(), module.__file__, "exec"), module.__dict__)
with module.slug_start_claim(sys.argv[2]) as claimed:
    print("claimed" if claimed else "refused", flush=True)
    sys.stdin.buffer.read(1)
"""
        with subprocess.Popen(
            [sys.executable, "-c", code, str(ADAPTER), str(run_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=self.env,
        ) as holder:
            try:
                # The pipe is the barrier: do not race the child acquiring its lock.
                self.assertEqual(holder.stdout.readline(), "claimed\n")
                refused = self.start(slug, assert_started=False)
                self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
                self.assertIn("another start", refused.stderr)
                self.assertFalse(run_dir.exists())
            finally:
                holder.kill()
                holder.communicate(timeout=START_TIMEOUT)
        self.assertTrue(Path(f"{run_dir}.start.lock").exists())
        state = self.settle(slug)
        self.assertEqual(state["state"], "done")
        self.assertEqual(list(run_dir.parent.glob(f"{slug}.prev-*")), [])


class AdapterUnitTests(unittest.TestCase):
    """Pure helpers: the rules that do not need a process to prove."""

    def test_slug_claim_fails_closed_when_the_file_cannot_be_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("builtins.open", side_effect=PermissionError("claim denied")):
                with adapter.slug_start_claim(str(Path(tmp) / "unavailable")) as claimed:
                    self.assertFalse(claimed)

    def test_slug_claim_ownership_not_file_age_controls_takeover(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = str(Path(tmp) / "claim-age")
            path = Path(f"{run_dir}.start.lock")
            with adapter.slug_start_claim(run_dir) as claimed:
                self.assertTrue(claimed)
                # An active initialization cannot be stolen even after the grace.
                old = time.time() - adapter.start_grace_seconds() - 1
                os.utime(path, (old, old))
                with adapter.slug_start_claim(run_dir) as second:
                    self.assertFalse(second)
            # Conversely, a fresh file with no holder is immediately reusable.
            path.touch()
            with adapter.slug_start_claim(run_dir) as claimed:
                self.assertTrue(claimed)

    def test_sanitize_matches_the_reference_slug_rule(self):
        self.assertEqual(adapter.sanitize("Repo-0041-Implement"), "repo-0041-implement")
        self.assertEqual(adapter.sanitize("  weird//name  "), "weird-name")
        self.assertEqual(adapter.sanitize("UPPER_under.dot"), "upper_under.dot")
        self.assertEqual(len(adapter.sanitize("x" * 80)), 48)
        self.assertEqual(adapter.sanitize("!!!"), "")

    def test_option_like_values_survive_argparse(self):
        """`--extra --no-session` must parse: agent flags begin with '-' by nature."""
        self.assertEqual(
            adapter.normalize_argv(["start", "--extra", "--no-session"]),
            ["start", "--extra=--no-session"],
        )
        self.assertEqual(
            adapter.normalize_argv(["start", "--model", "some-model", "--thinking", "high"]),
            ["start", "--model", "some-model", "--thinking", "high"],
        )
        self.assertEqual(adapter.normalize_argv(["status", "run"]), ["status", "run"])
        # A flag with no value is left alone rather than swallowing the next flag.
        self.assertEqual(adapter.normalize_argv(["--extra"]), ["--extra"])
        parsed = adapter.build_parser().parse_args(
            adapter.normalize_argv(["start", "--name", "n", "--prompt", "p", "--extra", "--no-session"])
        )
        self.assertEqual(parsed.extra, "--no-session")

    def test_run_root_follows_the_documented_chain(self):
        with_env = {"GDD_RUN_ROOT": "/gdd/runs", "OMP_RUN_ROOT": "/omp/runs"}
        saved = {key: os.environ.get(key) for key in with_env}
        try:
            os.environ.pop("OMP_RUN_ROOT", None)
            os.environ["GDD_RUN_ROOT"] = "/gdd/runs"
            # Absolute on purpose: the runner runs in the run's cwd, so a relative root
            # would mean two different directories to the launcher and to the run.
            self.assertEqual(adapter.run_root(), os.path.abspath("/gdd/runs"))
            os.environ["OMP_RUN_ROOT"] = "/omp/runs"
            self.assertEqual(adapter.run_root(), os.path.abspath("/omp/runs"))
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_wsl_detection_reads_the_kernel_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            micro = Path(tmp) / "version"
            micro.write_text("Linux version 5.15.90.1-microsoft-standard-WSL2 (x86_64)\n", encoding="utf-8")
            plain = Path(tmp) / "plain"
            plain.write_text("Linux version 6.8.0-generic (gcc 13)\n", encoding="utf-8")
            self.assertTrue(adapter.is_wsl(micro))
            self.assertFalse(adapter.is_wsl(plain))
            self.assertFalse(adapter.is_wsl(Path(tmp) / "missing"))
        # The rule, independent of the platform this suite runs on.
        self.assertIn("interop", adapter.interop_warning("/mnt/c/tools/omp.exe", wsl=True))
        self.assertEqual(adapter.interop_warning("/usr/lib/omp-agent", wsl=True), "")
        self.assertEqual(adapter.interop_warning("/usr/local/bin/omp", wsl=True), "")
        self.assertEqual(adapter.interop_warning("/mnt/c/tools/omp.exe", wsl=False), "")
        if IS_WINDOWS:
            self.assertFalse(adapter.is_wsl())
            self.assertEqual(adapter.interop_warning(r"C:\tools\omp.exe"), "")

    def test_killed_exit_codes_are_the_documented_set(self):
        self.assertEqual(adapter.KILLED_EXITS, (130, -2, 137, 143))
        self.assertEqual(adapter.KILL_EXIT, 143)

    def test_state_age_tolerates_a_missing_or_broken_started_stamp(self):
        self.assertEqual(adapter.state_age_seconds({}), float("inf"))
        self.assertEqual(adapter.state_age_seconds({"started": "not a timestamp"}), float("inf"))
        self.assertLess(adapter.state_age_seconds({"started": adapter.now_iso()}), 60.0)

    @unittest.skipUnless(IS_WINDOWS, "a concurrent reader only blocks the replace on Windows")
    def test_state_write_survives_a_concurrent_reader(self):
        """WinError 5: MoveFileEx fails while any process holds the destination open.

        A poller as ordinary as `status` was enough to kill a starting run before
        `write_json` retried, so the retry is pinned here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            adapter.write_json(path, {"state": "running"})
            release = threading.Event()

            def hold_open():
                with open(path, encoding="utf-8") as handle:
                    handle.read()
                    release.wait(15.0)

            reader = threading.Thread(target=hold_open)
            reader.start()
            try:
                time.sleep(0.2)
                adapter.write_json(path, {"state": "done", "exit": 0})
            finally:
                release.set()
                reader.join(timeout=15.0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "done")
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
