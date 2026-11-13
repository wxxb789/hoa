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
agent.
"""
from __future__ import annotations

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
    if mode == "flood":
        filler = "x" * 2000
        for index in range(300):
            emit({"type": "tool_use_start", "index": index, "filler": filler})
        emit({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "flooded"}]}})
        return 0
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
        self.assertEqual(list(ADAPTER.parent.glob("__pycache__/events-writer*")), [])
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


class AdapterUnitTests(unittest.TestCase):
    """Pure helpers: the rules that do not need a process to prove."""

    def test_sanitize_matches_the_reference_slug_rule(self):
        self.assertEqual(adapter.sanitize("Repo-0041-Implement"), "repo-0041-implement")
        self.assertEqual(adapter.sanitize("  weird//name  "), "weird-name")
        self.assertEqual(adapter.sanitize("UPPER_under.dot"), "upper_under.dot")
        self.assertEqual(len(adapter.sanitize("x" * 80)), 48)
        self.assertEqual(adapter.sanitize("!!!"), "")

    def test_run_root_follows_the_documented_chain(self):
        with_env = {"GDD_RUN_ROOT": "/gdd/runs", "OMP_RUN_ROOT": "/omp/runs"}
        saved = {key: os.environ.get(key) for key in with_env}
        try:
            os.environ.pop("OMP_RUN_ROOT", None)
            os.environ["GDD_RUN_ROOT"] = "/gdd/runs"
            self.assertEqual(adapter.run_root(), "/gdd/runs")
            os.environ["OMP_RUN_ROOT"] = "/omp/runs"
            self.assertEqual(adapter.run_root(), "/omp/runs")
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
