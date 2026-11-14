#!/usr/bin/env python3
"""Portable native-launcher contract tests with a stub paseo binary on PATH."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1] / "adapters" / "paseo-run.py"
STUB = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ["STUB_HOME"])
with (root / "argv.ndjson").open("a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\\n")
config = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
command = args[0]
if config.get("offline"):
    print("daemon unavailable", file=sys.stderr)
    sys.exit(1)
if command == "run":
    (root / "run-env.json").write_text(json.dumps({key: os.environ[key] for key in
        ("PASEO_AGENT_ID", "PASEO_WORKSPACE_ID") if key in os.environ}), encoding="utf-8")
    cwd = (os.environ.get("PASEO_AGENT_CWD") if os.environ.get("PASEO_AGENT_ID") or
           os.environ.get("PASEO_WORKSPACE_ID") else None) or os.getcwd()
    print(json.dumps({"agentId": config["id"], "status": "running",
                      "provider": "stub", "cwd": cwd, "title": "stage"}))
elif command == "inspect":
    if config.get("missing"):
        print("Agent not found", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"Id": config["id"], "Status": config["status"],
                      "Cwd": os.getcwd(), "PendingPermissions": config.get("permissions", [])}))
elif command == "logs":
    print(config.get("answer", "No activity to display."))
elif command == "stop":
    stopped = config["status"] == "running" and not config.get("stop_failed")
    print(json.dumps({"stoppedCount": int(stopped),
                      "agentIds": [config["id"]] if stopped else []}))
    if stopped:
        config["status"] = "idle"
        target = root / "fixture.next"
        target.write_text(json.dumps(config), encoding="utf-8")
        os.replace(target, root / "fixture.json")
elif command == "delete":
    deleted = not config.get("delete_failed")
    receipt = config.get("delete_receipt", {"deletedCount": int(deleted), "agentIds": [config["id"]] if deleted else []})
    print(json.dumps(receipt))
    if deleted and type(receipt.get("deletedCount")) is int and receipt == {"deletedCount": 1, "agentIds": [config["id"]]}:
        config["missing"] = True
        target = root / "fixture.next"
        target.write_text(json.dumps(config), encoding="utf-8")
        os.replace(target, root / "fixture.json")
elif command == "ls":
    print(json.dumps([] if config.get("missing") else
                     [{"id": config["id"], "status": config["status"]}]))
else:
    sys.exit(2)
'''


class PaseoLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="paseo-run-test.")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        source = self.bin / "paseo.py"
        source.write_text(STUB, encoding="utf-8")
        if os.name == "nt":
            (self.bin / "paseo.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" "{source}" %*\r\n', encoding="utf-8")
        else:
            executable = self.bin / "paseo"
            executable.write_text(f"#!{sys.executable}\n" + STUB.split("\n", 1)[1], encoding="utf-8")
            executable.chmod(0o755)
        self.root = self.home / "runs"
        self.prompt = self.home / "prompt.md"
        self.prompt.write_text("Reply with STAGE OK", encoding="utf-8")
        self.fixture = {"id": str(uuid.uuid4()), "status": "running", "answer": "STAGE OK"}
        self.save_fixture()
        self.env = dict(os.environ)
        for key in ("PASEO_BIN", "GDD_MODEL", "GDD_THINKING", "OMP_RUN_ROOT"):
            self.env.pop(key, None)
        self.env.update(GDD_RUN_ROOT=str(self.root), STUB_HOME=str(self.home),
                        PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""))
        self.monitors = []
        self.addCleanup(self.stop_monitors)

    def save_fixture(self, **fields):
        self.fixture.update(fields)
        path = self.home / "fixture.tmp"
        path.write_text(json.dumps(self.fixture), encoding="utf-8")
        os.replace(path, self.home / "fixture.json")

    def run_adapter(self, *args, env=None):
        return subprocess.run([sys.executable, "-B", str(ADAPTER), *args], env=env or self.env,
                              capture_output=True, text=True, timeout=30)

    def start(self, *flags, name="stage", env=None):
        result = self.run_adapter("start", "--name", name, "--prompt", str(self.prompt),
                                  "--cwd", str(self.home), *flags, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("started: " + name, result.stdout)
        pid = json.loads((self.run_dir(name) / "state.json").read_text(encoding="utf-8"))["pid"]
        if os.name == "nt":
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            self.monitors.append((pid, kernel.OpenProcess(0x00100000, False, pid)))
        else:
            self.monitors.append((pid, None))
        return result

    def run_dir(self, name="stage"):
        return self.root / datetime.now().strftime("%Y-%m-%d") / name

    def calls(self):
        path = self.home / "argv.ndjson"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def status(self, name="stage"):
        result = self.run_adapter("status", name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def wait_state(self, word):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = json.loads((self.run_dir() / "state.json").read_text(encoding="utf-8"))
            if state["state"] == word:
                return state
            time.sleep(0.1)
        self.fail(f"monitor never wrote {word}: {state}")

    def stop_monitors(self):
        # Stop only monitor pids recorded in this test's own isolated run root.
        if not self.root.exists():
            return
        self.save_fixture(status="closed", offline=False, missing=False)
        for pid, handle in self.monitors:
            if os.name == "nt":
                import ctypes
                if handle:
                    try:
                        if ctypes.windll.kernel32.WaitForSingleObject(handle, 5000) == 258:
                            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                            ctypes.windll.kernel32.WaitForSingleObject(handle, 5000)
                    finally:
                        ctypes.windll.kernel32.CloseHandle(handle)
            else:
                try:
                    os.kill(pid, 15)
                except ProcessLookupError:
                    pass

    def test_start_argv_identity_and_artifacts(self):
        self.start("--model", "stub-provider", "--thinking", "deliberate")
        expected = ["run", "--no-wait", "--title", "stage", "--cwd", str(self.home),
                    "--provider", "stub-provider", "--thinking", "deliberate", "--json",
                    "--", self.prompt.read_text(encoding="utf-8")]
        self.assertEqual(next(row for row in self.calls() if row[0] == "run"), expected)
        state = self.status()
        self.assertEqual(state["agent_id"], self.fixture["id"])
        self.assertEqual(state["session_id"], self.fixture["id"])
        self.assertEqual(state["backend"], "paseo")
        self.assertIsInstance(state["pid"], int)
        lock = json.loads((self.run_dir() / "lock").read_text(encoding="utf-8"))
        self.assertEqual(lock["agent_id"], self.fixture["id"])
        for filename in ("prompt.md", "run.json", "stderr.log", "events.ndjson"):
            self.assertTrue((self.run_dir() / filename).exists(), filename)

    def test_environment_passthrough_and_flag_precedence(self):
        env = dict(self.env, GDD_MODEL="environment-provider", GDD_THINKING="environment-thinking")
        self.start("--model", "explicit-provider", env=env)
        argv = next(row for row in self.calls() if row[0] == "run")
        self.assertEqual(argv[argv.index("--provider") + 1], "explicit-provider")
        self.assertEqual(argv[argv.index("--thinking") + 1], "environment-thinking")

    def test_explicit_cwd_is_not_overridden_by_callers_workspace(self):
        env = dict(self.env, PASEO_AGENT_ID=str(uuid.uuid4()), PASEO_WORKSPACE_ID=str(uuid.uuid4()),
                   PASEO_AGENT_CWD=str(self.home / "not-the-stage"))
        self.start(env=env)
        state = self.status()
        self.assertEqual(state["cwd"], str(self.home))
        self.assertEqual(json.loads((self.home / "run-env.json").read_text(encoding="utf-8")), {})

    def test_unset_options_are_not_defaulted(self):
        self.start()
        argv = next(row for row in self.calls() if row[0] == "run")
        self.assertNotIn("--provider", argv)
        self.assertNotIn("--thinking", argv)

    def test_literal_multiline_prompt(self):
        text = 'Reply "exactly" with Unicode \u03bb.\nNo tools; keep a & b | c < d > e unchanged.\n'
        self.prompt.write_text(text, encoding="utf-8")
        env = dict(self.env, PASEO_BIN=json.dumps([sys.executable, str(self.bin / "paseo.py")]))
        self.start(env=env)
        argv = next(row for row in self.calls() if row[0] == "run")
        self.assertEqual(argv[-1], text)

    @unittest.skipUnless(os.name == "nt", "batch prompt hazards are Windows-specific")
    def test_batch_prompt_hazards_refuse_before_dispatch(self):
        for text in ("first line\nsecond line", "literal & separator", 'literal "quotes"',
                     "literal %EXPANSION%", "literal !expansion!", "literal | pipe"):
            with self.subTest(text=text):
                self.prompt.write_text(text, encoding="utf-8")
                result = self.run_adapter("start", "--name", "unsafe", "--prompt", str(self.prompt))
                self.assertEqual(result.returncode, 1)
                self.assertIn("PASEO_BIN as a JSON argv array", result.stderr)
                self.assertFalse(self.run_dir("unsafe").exists())
                self.assertFalse((self.home / "argv.ndjson").exists())

    def test_invalid_json_argv_refuses(self):
        for value in ("[]", '["unterminated"', '[1]', '["paseo", ""]'):
            with self.subTest(value=value):
                result = self.run_adapter("start", "--name", "invalid", "--prompt", str(self.prompt),
                                          env=dict(self.env, PASEO_BIN=value))
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.run_dir("invalid").exists())

    def test_each_paseo_lifecycle_state(self):
        # Complete lifecycle enum from Paseo 0.15.4, not inferred aliases.
        for native, expected in (("initializing", "running"), ("running", "running"),
                                 ("idle", "done"), ("error", "failed"), ("closed", "killed")):
            with self.subTest(native=native):
                name = "state-" + native
                self.save_fixture(status=native)
                self.start(name=name)
                state = self.status(name)
                self.assertEqual(state["state"], expected)
                self.assertEqual(state["paseo_status"], native)

    def test_missing_unknown_and_unreachable_are_never_success(self):
        self.start()
        for changes in ({"missing": True}, {"missing": False, "status": "future-state"},
                        {"offline": True}):
            with self.subTest(changes=changes):
                self.save_fixture(**changes)
                state = self.status()
                self.assertEqual(state["state"], "unknown")
                self.assertIsNone(state["exit"])
                self.assertFalse((self.run_dir() / "finalized").exists())

    def test_idle_waiting_for_permission_is_not_done(self):
        self.save_fixture(status="idle", permissions=[{"tool": "write"}])
        self.start()
        self.assertEqual(self.status()["state"], "running")

    def test_unavailable_answer_exposes_logs_without_fabrication(self):
        self.save_fixture(status="idle", answer="No activity to display.")
        self.start()
        result = self.run_adapter("answer", "stage")
        self.assertEqual(result.returncode, 1)
        self.assertIn("logs argv", result.stderr)
        self.assertIn("assistant_message", result.stderr)
        self.assertFalse((self.run_dir() / "answer.md").exists())
        self.save_fixture(answer="Late published answer")
        result = self.run_adapter("answer", "stage")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Late published answer")

    def test_missing_state_file_is_unknown_even_with_an_agent_lock(self):
        self.start()
        (self.run_dir() / "state.json").unlink()
        self.assertEqual(self.status()["state"], "unknown")

    def test_monitor_finalizes_without_status_and_answer_is_last_assistant(self):
        self.start()
        self.save_fixture(status="idle", answer="Final assistant answer\nsecond line")
        state = self.wait_state("done")
        self.assertEqual(state["exit"], 0)
        answer = self.run_adapter("answer", "stage")
        self.assertEqual(answer.returncode, 0, answer.stderr)
        self.assertEqual(answer.stdout, "Final assistant answer\nsecond line\n")
        self.assertIn(["logs", self.fixture["id"], "--filter", "assistant_message", "--tail", "1"],
                      self.calls())
        self.assertEqual((self.run_dir() / "finalized").read_text().strip(), "0")
        self.assertEqual(len((self.root / "ledger.tsv").read_text().splitlines()), 2)
        self.status()
        self.assertEqual(len((self.root / "ledger.tsv").read_text().splitlines()), 2)

    def test_kill_records_confirmed_agent_deletion(self):
        self.start()
        result = self.run_adapter("kill", "stage")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = self.status()
        self.assertEqual(state["state"], "killed")
        self.assertTrue(state["agent_deleted"])
        self.assertEqual(state["termination_verb"], "delete")
        self.assertIn(["delete", self.fixture["id"], "--json"], self.calls())
        self.assertNotIn(["stop", self.fixture["id"], "--json"], self.calls())
        answer = self.run_adapter("answer", "stage")
        self.assertEqual(answer.returncode, 0, answer.stderr)
        self.assertEqual(answer.stdout, "STAGE OK\n")

    def test_unsuccessful_deletion_is_not_reported_killed(self):
        self.start()
        self.save_fixture(delete_failed=True)
        result = self.run_adapter("kill", "stage")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.status()["state"], "running")

    def test_mismatched_deletion_receipt_records_no_termination(self):
        self.start()
        for receipt in ({"deletedCount": 0, "agentIds": [self.fixture["id"]]},
                        {"deletedCount": True, "agentIds": [self.fixture["id"]]},
                        {"deletedCount": 1, "agentIds": []},
                        {"deletedCount": 1, "agentIds": [str(uuid.uuid4())]}):
            with self.subTest(receipt=receipt):
                self.save_fixture(delete_receipt=receipt)
                before = self.status()
                result = self.run_adapter("kill", "stage")
                self.assertEqual(result.returncode, 1)
                self.assertIn("did not confirm termination", result.stderr)
                after = self.status()
                self.assertEqual(after["state"], before["state"])
                self.assertEqual(after["exit"], before["exit"])
                self.assertFalse(after.get("agent_deleted", False))

    def test_interrupted_idle_agent_is_not_reported_killed(self):
        self.start()
        result = subprocess.run([sys.executable, str(self.bin / "paseo.py"), "stop", self.fixture["id"], "--json"],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.status()
        self.assertNotEqual(state["state"], "killed")
        self.assertFalse(state.get("agent_deleted", False))

    def test_deleting_finalized_agent_preserves_historical_outcome(self):
        self.save_fixture(status="idle")
        self.start()
        before = self.status()
        self.assertEqual(before["state"], "done")
        marker = (self.run_dir() / "finalized").read_bytes()
        result = self.run_adapter("kill", "stage")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.status()
        self.assertEqual(state["state"], "done")
        self.assertTrue(state["agent_deleted"])
        for key in ("agent_deleted", "termination_verb", "terminated_at"):
            state.pop(key)
        self.assertEqual(state, before)
        self.assertEqual((self.run_dir() / "finalized").read_bytes(), marker)

    def test_list_and_result_show_agent_identity(self):
        self.start()
        result = self.run_adapter("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stage", result.stdout)
        self.assertIn(self.fixture["id"], result.stdout)
        result = self.run_adapter("result", "stage")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["agent_id"], self.fixture["id"])

    def test_duplicate_slug_refuses_without_another_dispatch(self):
        self.start()
        result = self.run_adapter("start", "--name", "stage", "--prompt", str(self.prompt))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(row[0] == "run" for row in self.calls()), 1)

    def test_binary_override_and_missing_binary_refusal(self):
        env = dict(self.env, PASEO_BIN=str(self.bin / ("paseo.cmd" if os.name == "nt" else "paseo")))
        self.start(env=env)
        env["PASEO_BIN"] = str(self.home / "absent-paseo")
        result = self.run_adapter("start", "--name", "absent", "--prompt", str(self.prompt), env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.run_dir("absent").exists())


if __name__ == "__main__":
    unittest.main()
