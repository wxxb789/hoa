"""Portable native-launcher contract tests with a stub paseo binary on PATH."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_run
import gdd_process
from gdd_test_support import (check_locks, check_processes, claim, cleanup_child, exited, finalized, publish_json, ready,
                              remove_tree, retry_windows, run_python_cli, wait_for_json)

ADAPTER = Path(__file__).resolve().parents[1] / "adapters" / "paseo-run.py"
STUB = '''import json, os, sys, time
from pathlib import Path
sys.path[:0] = [os.environ["STUB_TESTS"], os.environ["STUB_SCRIPTS"]]
from gdd_test_support import own_identity, publish_json
args = sys.argv[1:]
root = Path(os.environ["STUB_HOME"])
pid = os.getpid()
publish_json(root / "children" / f"{pid}.json", [pid, own_identity()])
with (root / "argv.ndjson").open("a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\\n")
deadline = time.monotonic() + 2
while True:
    try:
        config = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
        break
    except PermissionError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.025)
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
                      "provider": "stub", "cwd": config.get("run_cwd", cwd), "title": "stage"}))
elif command == "inspect":
    if config.get("missing"):
        print("Agent not found", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"Id": config["id"], "Status": config["status"],
                      "Cwd": config.get("inspect_cwd", os.getcwd()), "PendingPermissions": config.get("permissions", [])}))
elif command == "logs":
    print(config.get("answer", "No activity to display."))
elif command == "stop":
    stopped = config["status"] == "running" and not config.get("stop_failed")
    print(json.dumps({"stoppedCount": int(stopped),
                      "agentIds": [config["id"]] if stopped else []}))
    if stopped:
        config["status"] = "idle"
        publish_json(root / "fixture.json", config)
elif command == "delete":
    deleted = not config.get("delete_failed")
    receipt = config.get("delete_receipt", {"deletedCount": int(deleted), "agentIds": [config["id"]] if deleted else []})
    print(json.dumps(receipt))
    if deleted and type(receipt.get("deletedCount")) is int and receipt == {"deletedCount": 1, "agentIds": [config["id"]]}:
        config["missing"] = True
        publish_json(root / "fixture.json", config)
else:
    sys.exit(2)
'''


class PaseoLauncherTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="paseo-run-test."))
        self.addCleanup(remove_tree, self.home)
        self.addCleanup(check_locks, self.home)
        self.addCleanup(self.stop_stub_children)
        self.monitors = {}
        self.addCleanup(self.stop_monitors)
        self.children = []
        self.addCleanup(cleanup_child, self.children)
        (self.home / "children").mkdir()
        self.bin = self.home / "bin with spaces"
        self.bin.mkdir()
        source = self.bin / "paseo.py"
        source.write_text(STUB, encoding="utf-8")
        if os.name == "nt":
            (self.bin / "paseo.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" "{source}" %*\r\n', encoding="utf-8")
        else:
            executable = self.bin / "paseo"
            executable.write_text(f"#!{sys.executable}\n" + STUB, encoding="utf-8")
            executable.chmod(0o755)
        self.root = self.home / "runs"
        self.prompt = self.home / "prompt.md"
        self.prompt.write_text("Reply with STAGE OK", encoding="utf-8")
        self.fixture = {"id": str(uuid.uuid4()), "status": "running", "answer": "STAGE OK"}
        self.save_fixture()
        self.env = dict(os.environ)
        for key in ("PASEO_BIN", "GDD_MODEL", "GDD_THINKING"):
            self.env.pop(key, None)
        # A detached auto-GC child cannot be joined, and it writes into the root while teardown deletes it.
        self.env.update(GDD_RUN_MAX_MB="off", GDD_RUN_ROOT=str(self.root), STUB_HOME=str(self.home),
                        STUB_TESTS=str(Path(__file__).resolve().parent), STUB_SCRIPTS=str(ADAPTER.parents[1]),
                        GDD_RUN_DETACH="windows" if os.name == "nt" else "setsid",
                        PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""))

    def save_fixture(self, **fields):
        self.fixture.update(fields)
        publish_json(self.home / "fixture.json", self.fixture)

    def run_adapter(self, *args, env=None, external=False):
        environment = self.env if env is None else env
        try:
            if external:
                return gdd_process.run([sys.executable, "-B", str(ADAPTER), *args], env=environment,
                                       capture_output=True, text=True, timeout=30)
            return run_python_cli(ADAPTER, *args, env=environment)
        finally:
            if args[0] == "start":
                issues = []
                for path in self.root.glob("*/*/state.json"):
                    try:
                        state = wait_for_json(path, bool, time.monotonic() + 3)
                        if pid := state.get("pid"):
                            self.monitors[pid, state.get("pid_identity")] = (path, False)
                    except (OSError, AssertionError) as exc:
                        issues.append(str(exc))
                if issues:
                    self.fail("\n".join(issues))

    def start(self, *flags, name="stage", env=None, expect=0, external=False):
        result = self.run_adapter("start", "--name", name, "--prompt", str(self.prompt),
                                  "--cwd", str(self.home), *flags, env=env, external=external)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return result

    def run_dir(self, name="stage"):
        return Path(agent_run.newest_first([str(path) for path in self.root.glob(f"*/{name}")])[0])

    def test_native_start_dispatches_background_gc(self):
        old = self.root / "2020-01-01" / "old"
        old.mkdir(parents=True)
        ended = datetime.fromtimestamp(time.time() - 10 * 86400, timezone.utc).isoformat()
        (old / "state.json").write_text(json.dumps({"state": "done", "ended": ended}), encoding="utf-8")
        (old / "refresh").touch()
        marker = old / "finalized"
        marker.touch()
        os.utime(marker, (time.time() - 10 * 86400,) * 2)
        env = {**self.env, "GDD_RUN_MAX_MB": "0.000001", "GDD_RUN_RETENTION_DAYS": "7",
               "GDD_RUN_GC_MIN_INTERVAL_SECONDS": "0", "GDD_STATE_FILE": str(self.home / "ledger.tsv")}
        result = self.start(env=env, external=True)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.splitlines()[0], "started: stage")
        self.assertTrue(agent_run.wait_until((self.root / ".gc.stamp").exists, 10))
        self.assertFalse(old.exists())
        self.assertTrue(self.run_dir().exists())

    def state(self, name="stage"):
        return wait_for_json(self.run_dir(name) / "state.json", bool, time.monotonic() + 5)

    def calls(self):
        path = self.home / "argv.ndjson"
        text = retry_windows(lambda: path.read_text(encoding="utf-8"), time.monotonic() + 2)
        return [json.loads(line) for line in text.splitlines()]

    def status(self, name="stage", *, external=False):
        result = self.run_adapter("status", name, external=external)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def wait_state(self, word):
        run_dir = self.run_dir()
        return wait_for_json(run_dir / "state.json", lambda s: s.get("state") == word and finalized(run_dir, s),
                             time.monotonic() + 15)

    def stop_monitors(self):
        if not self.monitors:
            return
        try:
            self.save_fixture(status="closed", offline=False, missing=False)
        finally:
            check_processes(self.monitors, 10)

    def stop_stub_children(self):
        owned = {}
        issues = []
        for path in (self.home / "children").glob("*.json"):
            try:
                pid, recorded = wait_for_json(path, lambda row: len(row) == 2, time.monotonic() + 3)
                owned[pid, recorded] = (path, True)
            except (OSError, AssertionError) as exc:
                issues.append(str(exc))
        check_processes(owned, 5)
        if issues:
            self.fail("\n".join(issues))

    def test_start_argv_identity_and_artifacts(self):
        env = dict(self.env, GDD_MODEL="environment-provider", GDD_THINKING="deliberate",
                   PASEO_AGENT_ID="caller", PASEO_WORKSPACE_ID="caller-workspace",
                   PASEO_AGENT_CWD=str(self.home / "not-the-stage"))
        result = self.start("--model", "stub-provider", name="Stage V1", env=env, external=True)
        self.assertIn("started: stage-v1", result.stdout.splitlines())
        expected = ["run", "--no-wait", "--title", "stage-v1", "--cwd", str(self.home),
                    "--provider", "stub-provider", "--thinking", "deliberate", "--json",
                    "--", self.prompt.read_text(encoding="utf-8")]
        self.assertEqual(next(row for row in self.calls() if row[0] == "run"), expected)
        state = self.status("stage-v1", external=True)
        self.assertEqual((state["agent_id"], state["session_id"], state["backend"]),
                         (self.fixture["id"], self.fixture["id"], "paseo"))
        self.assertIsInstance(state["pid"], int)
        if os.name == "nt":
            self.assertTrue(state["spawn"]["creationflags"] & gdd_process.NO_WINDOW, state["spawn"])
        for filename in ("prompt.md", "run.json", "stderr.log", "events.ndjson"):
            self.assertTrue((self.run_dir("stage-v1") / filename).exists(), filename)

        self.assertEqual(state["cwd"], str(self.home))
        self.assertEqual(json.loads((self.home / "run-env.json").read_text(encoding="utf-8")), {})

    def test_start_cwd_mismatch_stays_unknown_until_verified(self):
        wrong_cwd = str(self.home / "not-the-stage")
        self.save_fixture(status="idle", run_cwd=wrong_cwd, inspect_cwd=wrong_cwd)
        result = self.start(expect=1)
        self.assertIn("different cwd", result.stderr)
        recorded = self.state()
        self.assertEqual((recorded["state"], recorded["agent_id"]), ("unknown", self.fixture["id"]))
        self.assertIn("cwd", recorded["error"])

        for inspected_cwd in (wrong_cwd, None):
            self.save_fixture(inspect_cwd=inspected_cwd)
            for command in ("status", "result", "list"):
                with self.subTest(inspected_cwd=inspected_cwd, command=command):
                    result = self.run_adapter(command, *([] if command == "list" else ["stage"]))
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    state = self.state()
                    self.assertEqual((state["state"], state["exit"], state["agent_id"], state["cwd"]),
                                     ("unknown", None, self.fixture["id"], str(self.home)))
                    for name in ("finalized", "exit.code", "answer.md"):
                        self.assertFalse((self.run_dir() / name).exists(), name)

        self.save_fixture(inspect_cwd=str(self.home))
        verified = self.status()
        self.assertEqual((verified["state"], verified["exit"]), ("done", 0))
        self.assertNotIn("error", verified)
        self.assertEqual(self.wait_state("done")["exit"], 0)

    def test_literal_multiline_prompt(self):
        text = 'Reply "exactly" with Unicode \u03bb.\nNo tools; keep a & b | c < d > e unchanged.\n'
        self.prompt.write_text(text, encoding="utf-8")
        env = dict(self.env, PASEO_BIN=json.dumps([sys.executable, str(self.bin / "paseo.py")]))
        self.start(env=env, external=True)
        argv = next(row for row in self.calls() if row[0] == "run")
        self.assertEqual(argv[-1], text)
        self.assertFalse({"--provider", "--thinking"} & set(argv))

    @unittest.skipUnless(os.name == "nt", "batch prompt hazards are Windows-specific")
    def test_batch_prompt_hazards_refuse_before_dispatch(self):
        for text in ("first line\nsecond line", "literal & separator", 'literal "quotes"',
                     "literal %EXPANSION%", "literal !expansion!", "literal | pipe"):
            with self.subTest(text=text):
                self.prompt.write_text(text, encoding="utf-8")
                result = self.run_adapter("start", "--name", "unsafe", "--prompt", str(self.prompt))
                self.assertEqual(result.returncode, 1)
                self.assertIn("PASEO_BIN as a JSON argv array", result.stderr)
                self.assertEqual(list(self.root.glob("*/unsafe")), [])
                self.assertFalse((self.home / "argv.ndjson").exists())

    def test_invalid_json_argv_refuses(self):
        for value in ("[]", '["unterminated"', '[1]', '["paseo", ""]'):
            with self.subTest(value=value):
                self.start(name="invalid", env=dict(self.env, PASEO_BIN=value), expect=1)
                self.assertEqual(list(self.root.glob("*/invalid")), [])

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

    def test_refresh_claim_is_held_while_its_holder_lives(self):
        spec = importlib.util.spec_from_file_location("paseo_under_test", ADAPTER)
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        path = self.home / "refresh"
        with adapter.claim(str(path)):
            with mock.patch.object(adapter, "CLAIM_WAIT_SECONDS", 0.1), self.assertRaises(adapter.ClaimTimeout):
                with adapter.claim(str(path)):
                    pass
        self.assertTrue(path.exists())
        with adapter.claim(str(path)):
            pass

    @unittest.skipIf(os.name == "nt", "POSIX abrupt holder exit and competing processes")
    def test_only_one_contender_takes_over_a_dead_refresh_holder(self):
        source = """
import importlib.util, os, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location('adapter', sys.argv[1])
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
root, *gates = sys.argv[2:]
root = Path(root)
if not gates:
    with adapter.claim(str(root / 'refresh')):
        print('READY', flush=True)
        os._exit(0 if sys.stdin.readline().strip() == 'RELEASE' else 2)

overlap = False
for number, fd in enumerate(gates):
    round_dir = root / f'takeover-{number}'
    print('READY', flush=True)
    with os.fdopen(int(fd), 'rb') as gate:
        gate.read()  # EOF releases all contenders in this round.
    with adapter.claim(str(round_dir / 'refresh')):
        inside = round_dir / 'inside'
        try:
            inside.touch(exist_ok=False)
        except FileExistsError:
            print(f'round {number}: two contenders held the refresh claim at once', file=sys.stderr)
            overlap = True
        else:
            try:
                time.sleep(0.04)
            finally:
                inside.unlink()
raise SystemExit(int(overlap))
"""
        def start(root, *gates):
            child = gdd_process.popen([sys.executable, "-B", "-c", source, str(ADAPTER), str(root),
                                       *map(str, gates)], pass_fds=gates,
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding="utf-8")
            self.children.append(child)
            return child

        with ExitStack() as stack:
            readers, writers = [], []
            for _ in range(5):
                read_fd, write_fd = os.pipe()
                readers.append(stack.enter_context(os.fdopen(read_fd, "rb")))
                writers.append(stack.enter_context(os.fdopen(write_fd, "wb")))
            contenders = [start(self.home, *(reader.fileno() for reader in readers)) for _ in range(10)]
            for round_number, gate in enumerate(writers):
                root = self.home / f"takeover-{round_number}"
                root.mkdir()
                holder = start(root)
                ready(holder, 5)
                deadline = time.monotonic() + 5
                for contender in contenders:
                    ready(contender, max(0, deadline - time.monotonic()))
                _, stderr = holder.communicate("RELEASE\n", timeout=5)
                self.assertEqual(holder.returncode, 0, stderr)
                gate.close()
            results = [contender.communicate(timeout=10)[1] for contender in contenders]
        self.assertEqual([child.returncode for child in contenders], [0] * len(contenders),
                         "\n".join(filter(None, results)))

    def test_unknown_native_run_reserves_worktree_until_confirmed_termination(self):
        spec = importlib.util.spec_from_file_location("gdd_under_test", ADAPTER.parent.parent / "gdd.py")
        gdd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gdd)
        env = dict(self.env, GDD_TASK_ROOT=str(self.home / "tasks"))
        repo = os.path.realpath(self.home)
        for termination in ("delete", "idle", "error", "closed"):
            with self.subTest(termination=termination), mock.patch.dict(os.environ, env, clear=True):
                # The daemon owns this run; no local monitor is needed for status refreshes.
                name = "reservation-" + termination
                run_dir = self.root / "2000-01-01" / name
                run_dir.mkdir(parents=True)
                state = {"name": name, "backend": "paseo", "state": "running", "exit": None,
                         "cwd": str(self.home), "cwd_verified": True, "pid": None,
                         "started": datetime.now().astimezone().isoformat(),
                         "run_dir": str(run_dir), "agent_id": self.fixture["id"],
                         "paseo_argv": [sys.executable, str(self.bin / "paseo.py")]}
                (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
                expected = [(name, str(run_dir))]
                self.assertEqual(gdd.active_runs(repo), expected)

                self.save_fixture(offline=True)
                refreshed = self.status(name)
                self.assertEqual(refreshed["state"], "unknown")
                self.assertIsNone(refreshed["exit"])
                self.assertFalse((run_dir / "finalized").exists())
                self.assertEqual(gdd.agent_run.observed_state(str(run_dir), refreshed), "unknown")
                self.assertEqual(gdd.active_runs(repo), expected,
                                 "offline inspect must not release the native worktree reservation")

                self.save_fixture(offline=False, status="future-state", missing=False)
                self.assertEqual(gdd.active_runs(repo), expected,
                                 "reachability alone must not release an unresolved native run")
                self.assertEqual(json.loads((run_dir / "state.json").read_text())["state"], "unknown")
                if termination == "delete":
                    self.save_fixture(delete_failed=True)
                    rejected = self.run_adapter("kill", name)
                    self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
                    self.assertEqual(self.status(name)["state"], "unknown")
                    self.assertEqual(gdd.active_runs(repo), expected)
                    self.save_fixture(delete_failed=False)
                    result = self.run_adapter("kill", name)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    settled = json.loads(result.stdout)
                    self.assertTrue(settled["agent_deleted"])
                    self.assertEqual(settled["state"], "killed")
                else:
                    self.save_fixture(status=termination)
                    settled = self.status(name)
                    self.assertIn(settled["state"], ("done", "failed", "killed"))
                self.assertTrue(finalized(run_dir, settled))
                self.assertEqual(gdd.active_runs(repo), [])

    def test_native_reservation_ignores_dead_monitor_and_preserves_headless_states(self):
        spec = importlib.util.spec_from_file_location("gdd_under_test", ADAPTER.parent.parent / "gdd.py")
        gdd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gdd)
        run_dir = self.root / "2000-01-01" / "stage"
        run_dir.mkdir(parents=True)
        state = {"name": "stage", "backend": "paseo", "state": "running",
                 "cwd": str(self.home), "pid": 999999999}
        env = dict(self.env, GDD_TASK_ROOT=str(self.home / "tasks"))
        expected = [("stage", str(run_dir))]
        with mock.patch.dict(os.environ, env, clear=True):
            (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(gdd.agent_run.observed_state(str(run_dir), state), "stale")
            self.assertEqual(gdd.active_runs(os.path.realpath(self.home)), expected)
            (run_dir / "finalized").write_text("143\n", encoding="utf-8")
            self.assertEqual(gdd.active_runs(os.path.realpath(self.home)), [])
            (run_dir / "finalized").unlink()

            state.update(backend="windows", pid=None, started=datetime.now().astimezone().isoformat())
            for word in ("running", "done", "failed", "killed"):
                with self.subTest(headless_state=word):
                    state["state"] = word
                    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
                    self.assertEqual(gdd.agent_run.observed_state(str(run_dir), state), word)
                    self.assertEqual(gdd.active_runs(os.path.realpath(self.home)),
                                     expected if word == "running" else [])

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
        run_dir = self.run_dir()
        path = run_dir / "state.json"
        with claim(run_dir / "refresh"):
            state = self.state()
            retry_windows(path.unlink, time.monotonic() + 2)
        try:
            self.assertEqual(self.status()["state"], "unknown")
        finally:
            with claim(run_dir / "refresh"):
                publish_json(path, state)

    def test_monitor_finalizes_without_status_and_answer_is_last_assistant(self):
        self.start(external=True)
        self.save_fixture(status="idle", answer="Final assistant answer\nsecond line")
        state = self.wait_state("done")
        self.assertEqual(state["exit"], 0)
        answer = self.run_adapter("answer", "stage", external=True)
        self.assertEqual(answer.returncode, 0, answer.stderr)
        self.assertEqual(answer.stdout, "Final assistant answer\nsecond line\n")
        self.assertIn(["logs", self.fixture["id"], "--filter", "assistant_message", "--tail", "1"],
                      self.calls())
        tail = self.run_adapter("tail", "stage", "1", external=True)
        self.assertEqual(tail.returncode, 0, tail.stderr)
        self.assertEqual(json.loads(tail.stdout)["state"], "done")

    def test_stage_result_in_the_answer_is_checked_against_the_schema(self):
        schema = ADAPTER.parent.parent.parent / "references" / "stage-result.schema.json"
        result = {"stage": "review", "verdict": "APPROVE", "summary": "ok", "changed_files": [], "gates": [],
                  "findings": [], "unmet_criteria": []}
        self.start("--schema", str(schema))
        self.save_fixture(status="idle", answer=f"Report.\n```json\n{json.dumps(result)}\n```")
        state = self.wait_state("done")
        self.assertEqual(state["result"], "valid", state)
        self.assertEqual(json.loads((self.run_dir() / "result.json").read_text(encoding="utf-8")), result)
        refused = self.run_adapter("start", "--name", "noschema", "--prompt", str(self.prompt),
                                   "--cwd", str(self.home), "--schema", str(self.home / "nope.json"))
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("is not a readable JSON object", refused.stderr)
        self.assertEqual(list(self.run_dir().parent.glob("noschema*")), [])

    def test_kill_records_confirmed_agent_deletion(self):
        self.start(external=True)
        result = self.run_adapter("kill", "stage", external=True)
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

    def test_failed_deletion_does_not_publish_a_provisional_answer(self):
        self.start()
        self.save_fixture(delete_failed=True)
        result = self.run_adapter("kill", "stage")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.status()["state"], "running")
        self.assertFalse((self.run_dir() / "answer.md").exists())
        # The agent later completes while the final logs stay unavailable: the
        # discarded pre-delete capture must not stand in as the final answer.
        self.save_fixture(status="idle", answer="No activity to display.")
        state = self.wait_state("done")
        self.assertFalse(state["answer_available"])
        answer = self.run_adapter("answer", "stage")
        self.assertEqual(answer.returncode, 1, answer.stdout + answer.stderr)
        self.assertIn("final assistant text unavailable", answer.stderr)
        self.assertFalse((self.run_dir() / "answer.md").exists())

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
        result = gdd_process.run([sys.executable, str(self.bin / "paseo.py"), "stop", self.fixture["id"], "--json"],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.status()
        self.assertNotEqual(state["state"], "killed")
        self.assertFalse(state.get("agent_deleted", False))

    def test_lifecycle_commands_survive_worktree_removal(self):
        worktree = self.home / "worktree"
        worktree.mkdir()
        self.save_fixture(status="idle")
        self.start("--cwd", str(worktree), external=True)
        before = self.wait_state("done")
        self.assertTrue(agent_run.wait_until(lambda: exited(before["pid"], before["pid_identity"]), 10))
        self.assertEqual(before["state"], "done")
        self.assertEqual(before["cwd"], str(worktree))
        marker = (self.run_dir() / "finalized").read_bytes()
        # Normal worktree cleanup removes the recorded dispatch directory; the
        # already-finalized agent must still be deletable afterwards.
        shutil.rmtree(worktree)
        result = self.run_adapter("kill", "stage", external=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(["delete", self.fixture["id"], "--json"], self.calls())
        state = self.status()
        self.assertTrue(state["agent_deleted"])
        for key in ("agent_deleted", "termination_verb", "terminated_at"):
            del state[key]
        self.assertEqual(state, before)
        self.assertEqual((self.run_dir() / "finalized").read_bytes(), marker)

    def test_list_and_result_show_agent_identity(self):
        self.start()
        result = self.run_adapter("list", external=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stage", result.stdout)
        self.assertIn(self.fixture["id"], result.stdout)
        result = self.run_adapter("result", "stage", external=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["agent_id"], self.fixture["id"])

    def test_duplicate_slug_refuses_without_another_dispatch(self):
        self.start()
        self.start(expect=1)
        self.assertEqual(sum(row[0] == "run" for row in self.calls()), 1)

    def test_binary_override_and_missing_binary_refusal(self):
        env = dict(self.env, PASEO_BIN=str(self.bin / ("paseo.cmd" if os.name == "nt" else "paseo")))
        self.start(env=env)
        env["PASEO_BIN"] = str(self.home / "absent-paseo")
        self.start(name="absent", env=env, expect=1)
        self.assertEqual(list(self.root.glob("*/absent")), [])


if __name__ == "__main__":
    unittest.main()
