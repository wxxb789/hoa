"""Supervisor contract tests. All supervisor commands reach a local recording stub."""

import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_run
import gdd_process
HERE = Path(__file__).resolve().parent
RUNNER = str(HERE.parent / "agent_run.py")
STUB = str(HERE / "stub_agent.py")
FIXTURE = str(HERE / "fixtures" / "events" / "omp.ok.ndjson")


SUPERVISOR = r"""
import json, os, signal, sys
from pathlib import Path
root, tool, *args = sys.argv[1:]
root = Path(root)
with (root / "calls").open("a", encoding="utf-8") as log:
    log.write(json.dumps([tool, *args]) + "\n")
if tool == "launchctl" and args[0] == "bootstrap":
    if (root / "unsupported").exists():
        sys.exit("Unrecognized subcommand: bootstrap")
    if (root / "refuse").exists():
        sys.exit("permission denied")
elif tool == "launchctl" and args[0] == "bootout":
    if (root / "refuse").exists():
        sys.exit("Domain does not support specified action")
    if (root / "self-bootout").exists():
        run = root / "2026-01-01" / "test"
        assert (run / "finalized").read_text(encoding="utf-8").strip() == "0"
        assert (run / "exit.code").read_text(encoding="utf-8").strip() == "0"
        assert (run / "answer.md").is_file()
        runner_pid = json.loads((run / "state.json").read_text(encoding="utf-8"))["pid"]
        assert runner_pid == os.getppid()
        os.kill(runner_pid, signal.SIGTERM)
elif tool == "tmux" and args[0] == "-V":
    version = root / "tmux-version"
    print(version.read_text(encoding="utf-8") if version.exists() else "tmux 3.2a")
elif tool == "tmux" and args[0] == "new-session":
    if (root / "refuse").exists():
        sys.exit("cannot connect")
    session = args[args.index("-s") + 1]
    assert "." not in session and ":" not in session
    (root / "session").write_text(session, encoding="utf-8")
elif tool == "tmux" and args[0] == "has-session":
    if not (root / "session").exists() or args[-1] != "=" + (root / "session").read_text(encoding="utf-8"):
        sys.exit("can't find session")
elif tool == "tmux" and args[0] == "kill-session":
    (root / "session").unlink()
elif args[:2] == ["tab", "create"]:
    print(json.dumps({"result": {"tab": {"tab_id": "tab-1"}, "root_pane": {"pane_id": "pane-1"}}}))
elif args[:2] == ["pane", "run"] and (root / "refuse").exists():
    sys.exit("pane command refused")
elif args[:2] == ["tab", "close"]:
    if (root / "tab-missing").exists():
        sys.exit(json.dumps({"error": {"code": "tab_not_found"}}))
    print(json.dumps({"result": {"closed": True}}))
"""


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="gdd-detach-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.run_dir = self.root / "2026-01-01" / "test"
        self.run_dir.mkdir(parents=True)
        self.argv = [sys.executable, "-B", RUNNER, "_run", "--run-dir", str(self.run_dir)]
        self.herdr_python = r"C:\Python-3\python.exe" if os.name == "nt" else "/opt/python-3/bin/python3"
        self.state = {"name": "test", "state": "running", "started": "2000-01-01T00:00:00+00:00",
                      "pid": None, "agent_pid": None, "spawn": {}}
        self.env = {**os.environ, "GDD_RUN_ROOT": str(self.root), "STUB_FIXTURE": FIXTURE,
                    "SECRET_TEST": "keep out of supervisor argv"}
        self.env.pop("TMUX", None)
        patch = mock.patch.dict(os.environ, self.env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(agent_run, "supervisor_call", side_effect=self.invoke_stub)
        patch.start()
        self.addCleanup(patch.stop)

    def invoke_stub(self, argv, *, env=None):
        if argv[0] not in ("launchctl", "tmux", "herdr"):
            self.fail(f"unexpected supervisor executable: {argv[0]}")
        return gdd_process.run([sys.executable, "-c", SUPERVISOR, str(self.root), *argv],
                               env=env, capture_output=True, text=True, timeout=5)

    def calls(self):
        return [json.loads(line) for line in (self.root / "calls").read_text(encoding="utf-8").splitlines()]

    def start(self, mode, tool):
        with mock.patch.object(os, "getuid", return_value=123, create=True):
            if mode == "tmux":
                with mock.patch.object(agent_run, "IS_WINDOWS", False), \
                        mock.patch.object(agent_run.shutil, "which", return_value=tool):
                    mode, tool = agent_run.select_detach(mode)
            return agent_run.spawn_detached(self.argv, self.run_dir, str(self.root), self.env,
                                            self.state, mode, tool)

    def test_launchd_plist_and_runner_exit_cleanup(self):
        with mock.patch.object(os, "umask", return_value=0o027):
            self.start("launchd", "launchctl")
        target = self.state["supervisor"]
        plist = self.run_dir / "runner.plist"
        with plist.open("rb") as stream:
            job = plistlib.load(stream)
        self.assertRegex(job["Label"], r"^gdd\.test\.[0-9a-f]{12}$")
        expected = [*self.argv, "--launchd-start"]
        self.assertEqual(job, {"Label": target["label"], "ProgramArguments": expected,
                               "WorkingDirectory": str(self.root), "EnvironmentVariables": self.env,
                               "StandardOutPath": str(self.run_dir / "runner.log"),
                               "StandardErrorPath": str(self.run_dir / "runner.log"),
                               "AbandonProcessGroup": True, "RunAtLoad": True, "Umask": 0o027})
        self.assertEqual(self.calls(), [["launchctl", "bootstrap", "gui/123", str(plist)]])
        if os.name != "nt":
            (self.root / "self-bootout").touch()
        run = self.run_launchd_job(expected)
        self.assertEqual(run.returncode, 0 if os.name == "nt" else -signal.SIGTERM, run.stderr)
        self.assertEqual(agent_run.read_state(self.run_dir)["state"], "done")
        self.assertFalse(plist.exists())
        self.assertEqual(self.calls()[-1], ["launchctl", "bootout", f"gui/123/{target['label']}"])

    def run_launchd_job(self, argv, **kwargs):
        agent_run.write_json(self.run_dir / "run.json", {"agent": "omp", "argv": [sys.executable, STUB],
                                                        "cwd": str(self.root), "prompt": "argv"})
        (self.run_dir / "prompt.md").write_text("finish", encoding="utf-8")
        # Replay the stub's job after launchctl returns and the runner is released.
        source = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
import agent_run, gdd_process
stub, root, _, *args = sys.argv[2:]
agent_run.supervisor_call = lambda argv, env=None: gdd_process.run(
    [sys.executable, "-c", stub, root, *argv], env=env, capture_output=True, text=True, timeout=5)
sys.exit(agent_run.main(args))
"""
        try:
            return gdd_process.run([sys.executable, "-c", source, RUNNER, SUPERVISOR, str(self.root),
                                    *argv[2:]], cwd=self.root, capture_output=True, text=True,
                                   timeout=15, **kwargs)
        finally:
            state = agent_run.read_state(self.run_dir)
            for key in ("agent_pid", "pid"):
                pid = state.get(key)
                if (recorded := state.get(f"{key}_identity")) and agent_run.identity(pid) == recorded:
                    agent_run.terminate(pid, single=key == "pid")

    def test_launchd_submit_and_stale_status_cleanup(self):
        (self.root / "unsupported").touch()
        self.start("launchd", "launchctl")
        label = self.state["supervisor"]["label"]
        log = str(self.run_dir / "runner.log")
        submit = self.calls()[1]
        self.assertEqual(submit[:9], ["launchctl", "submit", "-l", label, "-o", log, "-e", log, "--"])
        self.assertEqual(submit[9:-2], [*self.argv, "--launchd-start", "--restore-env", "--runner-cwd",
                                       str(self.root)])
        self.assertEqual(agent_run.effective_state(self.run_dir)[0]["state"], "failed")
        self.assertEqual(self.calls()[-1], ["launchctl", "bootout", f"gui/123/{label}"])
        self.assertFalse((self.run_dir / "runner.plist").exists())
        self.assertFalse(agent_run.effective_state(self.run_dir)[1])

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_launchd_submit_keeps_dispatchers_umask(self):
        (self.root / "unsupported").touch()
        record = self.root / "record.json"
        self.env["STUB_RECORD"] = str(record)
        with mock.patch.object(os, "umask", return_value=0o027):
            self.start("launchd", "launchctl")
        submit = self.calls()[1]
        run = self.run_launchd_job(submit[submit.index("--") + 1:], umask=0o002)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(agent_run.read_state(self.run_dir)["state"], "done")
        for path in (record, self.run_dir / "answer.md"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_launchd_failure_records_setsid_fallback(self):
        (self.root / "refuse").touch()
        with mock.patch.object(gdd_process, "daemonize", return_value=313) as fork:
            self.assertEqual(self.start("launchd", "launchctl"), (313, 0))
            fork.assert_called_once()
        state = agent_run.read_state(self.run_dir)
        self.assertEqual(state["detach"], "setsid")
        self.assertIn("permission denied", state["detach_fallback"])
        self.assertNotIn("supervisor", state)
        self.assertFalse((self.run_dir / "runner.plist").exists())
        self.assertEqual(self.calls()[-1][1], "bootout")
        agent_run.effective_state(self.run_dir)
        self.assertEqual(len(self.calls()), 2)

    def test_missing_launchctl_records_setsid_fallback(self):
        with mock.patch.object(gdd_process, "daemonize", return_value=313):
            self.assertEqual(self.start("launchd", None), (313, 0))
        state = agent_run.read_state(self.run_dir)
        self.assertEqual(state["detach"], "setsid")
        self.assertIn("launchctl executable not found", state["detach_fallback"])
        self.assertNotIn("supervisor", state)

    def test_optional_modes_require_env_and_executable(self):
        for mode in ("tmux", "herdr"):
            with self.subTest(mode=mode), mock.patch.object(agent_run, "IS_WINDOWS", mode == "herdr" and os.name == "nt"), \
                    mock.patch.object(agent_run, "interpreter", return_value=self.herdr_python):
                with mock.patch.object(agent_run.skill_config, "resolve", return_value=mode), \
                        mock.patch.dict(os.environ, {"GDD_RUN_DETACH": "auto"}):
                    with self.assertRaisesRegex(ValueError, "must be set in the environment"):
                        agent_run.detach_config()
                with mock.patch.dict(os.environ, {"GDD_RUN_DETACH": mode}), \
                        mock.patch.object(agent_run.shutil, "which", return_value=None):
                    self.assertEqual(agent_run.detach_config(), mode)
                    with self.assertRaisesRegex(ValueError, f"{mode} executable not found"):
                        agent_run.select_detach(mode)
                with mock.patch.object(agent_run.shutil, "which", return_value=mode):
                    self.assertEqual(agent_run.select_detach(mode), (mode, mode))
        with mock.patch.object(agent_run, "IS_WINDOWS", True):
            with self.assertRaisesRegex(ValueError, "tmux.*native Windows"):
                agent_run.select_detach("tmux")

    def check_kill(self, mode):
        # Model a dead runner and still-live agent: cleanup must follow the guarded signal.
        state = agent_run.read_state(self.run_dir)
        state.update(pid=101, pid_identity="linux:101", agent_pid=102, agent_pid_identity="linux:102")
        agent_run.write_json(self.run_dir / "state.json", state)
        signalled = []

        def terminate(pid, **kwargs):
            signalled.append((pid, kwargs["single"]))
            self.assertNotIn("close" if mode == "herdr" else "kill-session", str(self.calls()))
            return True

        with mock.patch.object(agent_run, "wait_until", return_value=False), \
                mock.patch.object(agent_run, "pid_alive", side_effect=lambda pid: pid == 102), \
                mock.patch.object(agent_run, "identity", return_value="linux:102"), \
                mock.patch.object(agent_run, "terminate", side_effect=terminate):
            self.assertEqual(agent_run.stop_run(self.run_dir), "")
        self.assertEqual(signalled, [(102, False)])
        self.assertEqual(agent_run.read_state(self.run_dir)["state"], "killed")

    def test_launchd_kill_cleans_up(self):
        self.start("launchd", "launchctl")
        self.check_kill("launchd")
        self.assertEqual(self.calls()[-1][1], "bootout")
        self.assertFalse((self.run_dir / "runner.plist").exists())

    def test_tmux_argv_handle_and_kill(self):
        self.state["name"] = "test.v1:rc"
        self.start("tmux", "tmux")
        target = agent_run.read_state(self.run_dir)["supervisor"]
        name = target["session"]
        self.assertRegex(name, r"^gdd-test-v1-rc-[0-9a-f]{12}$")
        argv = self.calls()[1]
        self.assertEqual(argv[:8], ["tmux", "new-session", "-d", "-s", name, "-c", str(self.root), "-e"])
        self.assertEqual(argv[argv.index("--") + 1:], [*self.argv, "--restore-env"])
        self.assertNotIn("SECRET_TEST", str(argv))
        self.check_kill("tmux")
        self.assertEqual(self.calls()[-2:], [["tmux", "has-session", "-t", "=" + name],
                                             ["tmux", "kill-session", "-t", "=" + name]])

    def test_tmux_version_floor(self):
        for version in ("2.9a", "3.1c", "3.2", "next-3.1", "3.2a", "3.4", "3.6a", "next-3.7", "master", "unknown"):
            with self.subTest(version=version):
                (self.root / "tmux-version").write_text(f"tmux {version}", encoding="utf-8")
                (self.root / "calls").unlink(missing_ok=True)
                self.run_dir = self.root / version
                self.run_dir.mkdir()
                if version in ("2.9a", "3.1c", "3.2", "next-3.1", "unknown"):
                    with self.assertRaises(ValueError) as exc:
                        self.start("tmux", "tmux")
                    self.assertIn(f"tmux {version}", str(exc.exception))
                    self.assertIn("3.2a", str(exc.exception))
                    self.assertEqual(self.calls(), [["tmux", "-V"]])
                    self.assertFalse((self.run_dir / ".runner-env").exists())
                else:
                    self.start("tmux", "tmux")
                    self.assertEqual(self.calls()[1][1], "new-session")
                    self.assertIn("-e", self.calls()[1])
                    self.assertEqual(agent_run.cleanup_supervisor(self.run_dir, self.state), "")

    def test_tmux_missing_session_recovers_stale_run(self):
        self.start("tmux", "tmux")
        (self.root / "session").unlink()
        self.state["started"] = agent_run.now_iso()
        agent_run.write_json(self.run_dir / "state.json", self.state)
        final, recovered = agent_run.effective_state(self.run_dir)
        self.assertTrue(recovered)
        self.assertEqual(final["state"], "failed")
        self.assertEqual(self.calls()[-1][1], "has-session")

    def test_herdr_json_handle_and_unfocused_start_and_kill(self):
        script = self.root / "runner's path with spaces \u2019; test.py"
        (self.root / "runner_sibling.py").write_text("import json\n", encoding="utf-8")
        script.write_text("import sys\nfrom runner_sibling import json\nprint(json.dumps(sys.argv))\n",
                          encoding="utf-8")
        self.argv[2] = str(script)
        self.argv[0] = self.herdr_python
        self.start("herdr", "herdr")
        target = agent_run.read_state(self.run_dir)["supervisor"]
        self.assertEqual((target["tab"], target["pane"]), ("tab-1", "pane-1"))
        create, run = self.calls()
        self.assertEqual(create[:9], ["herdr", "tab", "create", "--no-focus", "--cwd", str(self.run_dir),
                                      "--label", "gdd-test", "--env"])
        self.assertNotIn("--focus", create)
        self.assertEqual(run[:4], ["herdr", "pane", "run", "pane-1"])
        entry = target["entry"]
        self.assertRegex(entry, r"^\.runner-herdr-[0-9a-f]{12}\.py$")
        self.assertFalse(any(option.startswith("PATH=") for option in create))
        executable = self.argv[0].replace("\\", "/")
        self.assertEqual(run[4:], [f"{executable} -B {entry}"])
        executed = gdd_process.run([sys.executable, "-B", entry], cwd=self.run_dir, env=self.env,
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(executed.returncode, 0, executed.stderr)
        self.assertEqual(json.loads(executed.stdout), [*self.argv[2:], "--restore-env", "--runner-cwd", str(self.root)])
        self.assertFalse((self.run_dir / entry).exists())
        if os.name == "nt":
            env_file = self.run_dir / ".runner-env"
            acl = gdd_process.run(["icacls.exe", str(env_file)], capture_output=True, text=True, check=True).stdout
            self.assertNotIn("(I)", acl)
            self.assertEqual(len(re.findall(r":\(F\)", acl)), 1, acl)
            with mock.patch.dict(os.environ):
                agent_run.restore_detached_env(self.run_dir)
                self.assertEqual(os.environ["SECRET_TEST"], self.env["SECRET_TEST"])
            self.assertFalse(env_file.exists())
        self.check_kill("herdr")
        self.assertEqual(self.calls()[-1], ["herdr", "tab", "close", "tab-1"])

    def test_herdr_refuses_paths_requiring_shell_quoting(self):
        for windows, template in ((False, "/opt/py{}thon/bin/python3"),
                                  (True, r"C:\py{}thon\python.exe")):
            for char in (" ", "'", "\u2018", "\u2019", "\u201a", "\u201b", "\u00e9", "\u4e2d"):
                with self.subTest(windows=windows, char=char), \
                        mock.patch.object(agent_run, "IS_WINDOWS", windows), \
                        mock.patch.object(agent_run, "supervisor_call") as call, \
                        mock.patch.object(agent_run.shutil, "which", return_value="herdr"):
                    self.argv[0] = template.format(char)
                    with mock.patch.object(agent_run, "interpreter", return_value=self.argv[0]):
                        with self.assertRaises(OSError):
                            agent_run.select_detach("herdr")
                    with self.assertRaises(OSError):
                        self.start("herdr", "herdr")
                    call.assert_not_called()
                    self.assertFalse((self.run_dir / ".runner-env").exists())
                    self.assertFalse(list(self.run_dir.glob(".runner-herdr-*.py")))

    def test_herdr_start_uses_selected_interpreter(self):
        prompt = self.root / "prompt.md"
        prompt.write_text("test", encoding="utf-8")
        executable = str(HERE / "python.exe")
        with mock.patch.object(agent_run, "interpreter", return_value=executable), \
                mock.patch.object(agent_run, "select_detach", return_value=("herdr", "herdr")), \
                mock.patch.object(agent_run, "spawn_detached", side_effect=OSError) as spawn, \
                mock.patch.dict(os.environ, {"GDD_AGENT": "omp", "OMP_BIN": STUB}):
            with self.assertRaises(SystemExit):
                agent_run.main(["start", "--name", "interpreter", "--prompt", str(prompt)])
        self.assertEqual(spawn.call_args.args[0][0], executable)

    def test_herdr_tab_already_closed_is_clean(self):
        self.argv[0] = self.herdr_python
        self.start("herdr", "herdr")
        (self.root / "tab-missing").touch()
        self.assertEqual(agent_run.cleanup_supervisor(self.run_dir, self.state), "")
        self.assertFalse((self.run_dir / self.state["supervisor"]["entry"]).exists())
        self.assertTrue((self.run_dir / ".supervisor-cleaned").exists())

    def test_optional_failures_do_not_fall_back(self):
        (self.root / "refuse").touch()
        self.argv[0] = self.herdr_python
        for mode, error in (("tmux", "cannot connect"), ("herdr", "pane command refused")):
            with self.subTest(mode=mode), mock.patch.object(gdd_process, "daemonize") as fork:
                # Each submission owns a fresh directory.
                self.run_dir = self.root / mode
                self.run_dir.mkdir()
                self.state = {"name": mode}
                with self.assertRaisesRegex(OSError, f"{mode}: {error}"):
                    self.start(mode, mode)
                fork.assert_not_called()
                self.assertFalse((self.run_dir / ".runner-env").exists())
        self.assertEqual(self.calls()[-1], ["herdr", "tab", "close", "tab-1"])
