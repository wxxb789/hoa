"""Contract tests for agent_run.py with synthetic agent CLIs."""
import contextlib
import glob
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from runner_cases import (HERE, IS_WINDOWS, PROMPT, RESULT_SCHEMA, RUNNER, STAGE_RESULT, STUB, RunnerCase,
                          fold_fixture, read, write)
import agent_run
import gdd_process
import stage_result
from gdd_test_support import (check_processes, exited, finalized, own_identity, ready,
                              route_fixture, wait_for_json)


SCHEMA = json.loads(read(os.path.join(HERE, "state.schema.json")))


def force_kill(pid, recorded):
    if not recorded or agent_run.identity(pid) != recorded:
        return
    if IS_WINDOWS:
        gdd_process.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGKILL)


def different_identity(recorded):
    source, timestamp = recorded.split(":")
    return f"{source}:{int(timestamp) + 1}"


class AutoGCTests(RunnerCase):
    def setUp(self):
        super().setUp()
        self.ledger = Path(self.tmp, "ledger.tsv")
        self.env.update(GDD_RUN_MAX_MB="0.0009765625", GDD_RUN_RETENTION_DAYS="7",
                        GDD_RUN_GC_MIN_INTERVAL_SECONDS="0", GDD_STATE_FILE=str(self.ledger))
        self.now = 1_800_000_000

    def old_run(self, slug, *, day="2020-01-01", age=10, ended_age=None, state="done", pid=None,
                marker=True, size=610):
        run = Path(self.root, day, slug)
        run.mkdir(parents=True)
        ended = datetime.fromtimestamp(self.now - (age if ended_age is None else ended_age) * 86400,
                                       timezone.utc).isoformat()
        write(run / "state.json", json.dumps({"state": state, "ended": ended, "pid": pid}))
        with (run / "data").open("wb") as handle:
            handle.truncate(size - (run / "state.json").stat().st_size)
        if marker:
            path = run / "finalized"
            path.touch()
            os.utime(path, (self.now - age * 86400,) * 2)
        return run

    def gc(self, **env):
        proc = gdd_process.run([sys.executable, "-B", RUNNER, "_gc", "--run-root", self.root,
                                "--now", str(self.now)], capture_output=True, encoding="utf-8",
                               env={**self.env, **env}, cwd=self.work, timeout=10)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""), proc)

    def test_exact_budget_and_disable_keep_old_runs(self):
        first = self.old_run("first", age=30, size=512)
        second = self.old_run("second", age=30, size=512)
        self.gc()
        self.assertTrue(first.exists() and second.exists())
        (first / "extra").write_bytes(b"x")
        self.gc(GDD_RUN_MAX_MB="off")
        self.assertTrue(first.exists() and second.exists())
        self.gc()
        self.assertEqual(sum(run.exists() for run in (first, second)), 1)

    def test_prunes_oldest_to_budget_and_preserves_retention(self):
        near = self.old_run("near", age=8, size=400)
        old = self.old_run("old", day="2020-01-02", age=10, size=400)
        recent = self.old_run("recent", age=2, size=600)
        self.gc()
        self.assertFalse(old.parent.exists())
        self.assertTrue(near.exists() and recent.exists())
        self.gc(GDD_RUN_MAX_MB="0.0001")
        self.assertFalse(near.exists())
        self.assertTrue(recent.exists())

    def test_preserves_live_unfinalized_ledger_and_each_age_guard(self):
        protected = [self.old_run("live", pid=os.getpid()), self.old_run("stale", state="running", marker=False),
                     self.old_run("recent-end", ended_age=1), self.old_run("recent-marker", age=1, ended_age=30),
                     self.old_run("boundary", age=7), self.old_run("ledger")]
        no_time = self.old_run("no-time")
        write(no_time / "state.json", json.dumps({"state": "done"}))
        protected.append(no_time)
        write(self.ledger, "repo\tgoal\tstage\tnote\nrepo\tgoal\timplement\t run=ledger \n")
        eligible = self.old_run("eligible")
        self.gc()
        self.assertFalse(eligible.exists())
        self.assertTrue(all(run.exists() for run in protected))

    def test_recovers_orphan_tombstones_and_headerless_ledger_and_waits_for_claim(self):
        orphan = Path(self.root, "2020-01-01", "~gc-deadbeef")
        orphan.mkdir(parents=True)
        (orphan / "data").write_bytes(b"x" * 2000)
        kept = self.old_run("kept")
        write(self.ledger, "2020-01-01T00:00:00Z\trepo\tgoal\timplement\tb\th\t-\t-\t-\t-\t-\t-\trun=kept\n")
        self.gc()
        self.assertFalse(orphan.exists())
        self.assertTrue(kept.exists())

        root = Path(self.root)
        (root / ".gc.claim").write_text("claimed\n", encoding="utf-8", newline="\n")
        released = []
        gc_lock = (root / ".gc.lock").open("a+b")
        slug_lock = (root / "claimed.start.lock").open("a+b")
        try:
            self.assertTrue(gdd_process.try_file_lock(gc_lock))
            self.assertTrue(gdd_process.try_file_lock(slug_lock))

            def release_soon():
                time.sleep(0.08)
                (root / ".gc.claim").unlink(missing_ok=True)
                slug_lock.close()
                gc_lock.close()
                released.append(True)

            import threading
            worker = threading.Thread(target=release_soon)
            worker.start()
            try:
                with agent_run.slug_start_lock(root, "claimed"):
                    self.assertEqual(released, [True])
            finally:
                worker.join(timeout=5)
        finally:
            if not slug_lock.closed:
                slug_lock.close()
            if not gc_lock.closed:
                gc_lock.close()

    def test_does_not_count_or_follow_directory_symlinks(self):
        outside = Path(self.tmp, "outside")
        outside.mkdir()
        (outside / "data").write_bytes(b"x" * 2000)
        (outside / "finalized").touch()
        first = self.old_run("first")
        for link in (first / "linked", first.parent / "linked", Path(self.root, "2020-01-02")):
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                if not IS_WINDOWS or exc.winerror != 1314:
                    raise
                self.skipTest(f"Symlink privilege unavailable: {exc}")
        self.gc()
        self.assertTrue(first.exists())
        self.old_run("second")
        self.gc()
        self.assertTrue((outside / "data").exists())
        self.assertTrue((first.parent / "linked").is_symlink())

    def test_gc_skips_contended_global_slug_and_refresh_locks(self):
        slug = self.old_run("busy.prev-123456", age=30)
        refresh = self.old_run("native", age=20)
        free = self.old_run("free")
        root = Path(self.root)
        with (root / ".gc.lock").open("a+b") as lock:
            self.assertTrue(gdd_process.try_file_lock(lock))
            self.gc()
            self.assertTrue(free.exists())
        with (root / "busy.start.lock").open("a+b") as start, (refresh / "refresh").open("a+b") as claim:
            self.assertTrue(gdd_process.try_file_lock(start))
            self.assertTrue(gdd_process.try_file_lock(claim))
            if IS_WINDOWS:
                self.assertIn("already starting", self.start("busy.", expect=1).stderr)
            self.gc()
            self.assertFalse(free.exists())
            self.assertTrue(slug.exists() and refresh.exists())
        self.gc(GDD_RUN_MAX_MB="0.0001")
        self.assertFalse(slug.exists() or refresh.exists())
        self.assertTrue((root / "busy.start.lock").is_file() and (root / ".gc.lock").is_file())

    def test_config_settings_and_cooldown(self):
        config = Path(self.env["XDG_CONFIG_HOME"], "gdd", "config.yaml")
        config.parent.mkdir(parents=True)
        write(config, "GDD_RUN_MAX_MB: 0.0001\nGDD_RUN_RETENTION_DAYS: 1\nGDD_RUN_GC_MIN_INTERVAL_SECONDS: 60\n")
        first = self.old_run("first", age=2)
        self.gc(GDD_RUN_MAX_MB="", GDD_RUN_RETENTION_DAYS="", GDD_RUN_GC_MIN_INTERVAL_SECONDS="")
        self.assertFalse(first.exists())
        second = self.old_run("second", age=2)
        self.gc(GDD_RUN_MAX_MB="", GDD_RUN_RETENTION_DAYS="", GDD_RUN_GC_MIN_INTERVAL_SECONDS="")
        self.assertTrue(second.exists())
        self.gc(GDD_RUN_MAX_MB="", GDD_RUN_RETENTION_DAYS="", GDD_RUN_GC_MIN_INTERVAL_SECONDS="0")
        self.assertFalse(second.exists())

    def test_start_dispatches_background_gc_and_keeps_stdout_contract(self):
        self.now = time.time()
        old = self.old_run("old", size=2048)
        release = Path(self.tmp, "release-gc")
        wrapper = """
import runpy, sys, time
from pathlib import Path
release = Path(sys.argv.pop(1))
deadline = time.monotonic() + 10
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if not release.exists():
    raise SystemExit(2)
sys.argv.pop(0)
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        popen = gdd_process.popen

        def delayed_gc(argv, **kwargs):
            if argv[3:4] != ["_gc"]:
                return popen(argv, **kwargs)
            child = popen([*argv[:2], "-c", wrapper, str(release), *argv[2:]], **kwargs)
            self.children.append(child)
            return child

        try:
            with mock.patch.object(gdd_process, "popen", side_effect=delayed_gc):
                proc = self.start("gc-launch", in_process=True)
            self.assertEqual(proc.stderr, "")
            self.assertEqual(proc.stdout.splitlines()[0], "started: gc-launch")
            self.assertIn(f"run dir   : {self.run_dir('gc-launch')}", proc.stdout)
            self.assertTrue(old.exists())
        finally:
            release.touch()
            for child in self.children:
                self.assertEqual(child.wait(timeout=10), 0)
        self.assertFalse(old.exists())
        self.finished("gc-launch")


class ContractTests(RunnerCase):
    def test_concurrent_starts_cannot_move_a_starting_run(self):
        wrapper = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv.pop(1)).parent))
import agent_run
write_json = agent_run.write_json
def paused_write(path, payload):
    if Path(path).name == "run.json":
        print("READY", flush=True)
        if sys.stdin.readline().strip() != "RELEASE":
            raise SystemExit(2)
    write_json(path, payload)
agent_run.write_json = paused_write
sys.exit(agent_run.main())
"""
        argv = ("start", "--name", "race", "--prompt", self.prompt)
        fixture = {"STUB_FIXTURE": route_fixture("omp"), "STUB_HANG": "1"}
        first = gdd_process.popen([sys.executable, "-B", "-c", wrapper, RUNNER, *argv],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding="utf-8", env={**self.env, **fixture}, cwd=self.work)
        self.children.append(first)
        ready(first)
        try:
            second = self.cli(*argv, env=fixture)
        finally:
            stdout, stderr = first.communicate("RELEASE\n", timeout=40)
        self.assertEqual((first.returncode, second.returncode), (0, 1),
                         stdout + stderr + second.stdout + second.stderr)
        self.assertEqual(list(Path(self.root).glob("*/race.prev-*")), [])

    def test_t1_new_and_resume_process_contract_for_every_installed_route(self):
        metrics = ("session_id", "turns", "tool_calls", "usage", "cost_usd")
        for agent in agent_run.discover_routes():
            route = agent_run.load_route(agent)
            expected = fold_fixture(route, "ok")
            for label, extra in (("new", ()), ("resume", ("--resume", "S1"))):
                with self.subTest(agent=agent, session=label):
                    name = f"{agent}-{label}"
                    self.start(name, agent, "ok", "--max-time", "10m", *extra,
                               in_process=bool(extra) and agent != "omp")
                    record = self.recorded()
                    run_dir = Path(self.run_dir(name))
                    plan = json.loads(read(run_dir / "run.json"))
                    prompt_in_argv = route.prompt == "argv"
                    self.assertEqual(record["argv"], plan["argv"][2:] + ([PROMPT] if prompt_in_argv else []))
                    self.assertEqual(record["stdin"], "" if prompt_in_argv else PROMPT)
                    self.assertEqual(os.path.realpath(record["cwd"]), os.path.realpath(self.work))
                    state = self.finished(name)
                    self.assertEqual((state["state"], state["exit"]), ("done", 0), state)
                    self.assertEqual(state["resumed_from"], "S1" if extra else None)
                    if IS_WINDOWS:
                        self.assertTrue(state["spawn"]["creationflags"] & gdd_process.NO_WINDOW, state["spawn"])
                    self.assertEqual(stage_result.error(state, SCHEMA), "")
                    self.assertEqual({key: state[key] for key in metrics}, {key: expected[key] for key in metrics})
                    self.assertEqual(read(run_dir / "exit.code").strip(), "0")
                    answer_cli = self.cli if agent == "omp" and not extra else self.in_process_cli
                    answer = answer_cli("answer", name)
                    self.assertEqual(read(run_dir / "answer.md"), expected["answer"])
                    self.assertEqual((answer.returncode, answer.stdout), (0, expected["answer"]))

    def test_t3_exit_zero_without_success_marker_fails(self):
        for agent in agent_run.discover_routes():
            with self.subTest(agent=agent):
                self.start(f"fail-{agent}", agent, "fail")
                state = self.finished(f"fail-{agent}")
                self.assertEqual((state["state"], state["exit"]), ("failed", 0))
                self.assertIn(agent_run.load_route(agent).marker, state["error"])
                self.assertEqual(state["errors"], [state["error"]])
                self.assertEqual(stage_result.error(state, SCHEMA), "")

    def test_t4_exit_codes(self):
        for code, verdict in ((3, "failed"), (130, "killed"), (143, "killed")):
            with self.subTest(code=code):
                self.start(f"exit-{code}", env={"STUB_EXIT": str(code)})
                state = self.finished(f"exit-{code}")
                self.assertEqual((state["state"], state["exit"]), (verdict, code))

    def test_t5_kill_a_hanging_run(self):
        with self.stdout_holder("hang", STUB_HANG="1") as (_, descendant):
            before = self.state("hang")
            killed = self.cli("kill", "hang")
            self.assertEqual(killed.returncode, 0, killed.stderr)
            state = self.finished("hang")
            self.assertEqual((state["state"], state["exit"]), ("killed", 143))
            self.assertTrue(agent_run.wait_until(lambda: exited(before["agent_pid"], before["agent_pid_identity"]), 10))
            self.assertTrue(agent_run.wait_until(lambda: exited(*descendant), 5),
                            f"Grandchild PID {descendant[0]} survived kill")
        again = self.cli("kill", "hang")
        self.assertEqual(again.returncode, 1)
        self.assertIn("already finished", again.stderr)

    def test_t6_stale_recovery_is_idempotent(self):
        self.start("stale", env={"STUB_HANG": "1"})
        before = self.state("stale")
        for key in ("pid", "agent_pid"):
            force_kill(before[key], before[f"{key}_identity"])
        self.assertTrue(agent_run.wait_until(lambda: all(exited(before[key], before[f"{key}_identity"])
                                                         for key in ("pid", "agent_pid")), 10))
        first = self.cli("status", "stale")
        self.assertIn("stale_recovered: true", first.stdout)
        state = self.state("stale")
        self.assertEqual((state["state"], state["exit"], state["stale_recovered"]), ("failed", -1, True))
        second = self.cli("status", "stale")
        self.assertNotIn("stale_recovered: true", second.stdout)
        self.assertEqual(self.state("stale"), state)
        self.assertIn("failed(stale)", self.cli("list").stdout)

    def test_t6_kill_with_runner_gone_checks_agent_identity(self):
        fast = {"GDD_RUN_STOP_WAIT_SECONDS": "1"}
        for name, forged in (("orphan", False), ("reused", True)):
            with self.subTest(forged=forged):
                # The agent must survive the runner's pipe closing until kill checks its identity.
                self.start(name, env={"STUB_HANG": "1", "STUB_FIXTURE": ""})
                state = self.state(name)
                self.addCleanup(check_processes, {(state["agent_pid"], state["agent_pid_identity"]):
                                                  (self.run_dir(name), False)}, 0)
                force_kill(state["pid"], state["pid_identity"])
                self.assertTrue(agent_run.wait_until(lambda: exited(state["pid"], state["pid_identity"]), 10))
                self.assertEqual(agent_run.identity(state["agent_pid"]), state["agent_pid_identity"])
                if forged:  # the recorded pid now names a different process
                    write(os.path.join(self.run_dir(name), "state.json"),
                          json.dumps({**state, "agent_pid_identity": different_identity(state["agent_pid_identity"])}))
                killed = self.cli("kill", name, env=fast)
                if forged:
                    self.assertEqual(killed.returncode, 1, killed.stdout)
                    self.assertIn("already finished", killed.stderr)
                    self.assertFalse(json.loads(self.cli("status", name).stdout)["alive"])
                    self.assertEqual(agent_run.identity(state["agent_pid"]), state["agent_pid_identity"])
                    force_kill(state["agent_pid"], state["agent_pid_identity"])
                else:
                    self.assertEqual(killed.returncode, 0, killed.stderr)
                    final = self.state(name)
                    self.assertEqual((final["state"], final["exit"]), ("killed", 143))
                self.assertTrue(agent_run.wait_until(lambda: exited(state["agent_pid"], state["agent_pid_identity"]), 10))

    @unittest.skipIf(IS_WINDOWS, "POSIX stopped runner and zombie process group")
    def test_kill_finalizes_with_a_non_reaping_runner(self):
        self.start("stuck", env={"STUB_HANG": "1", "STUB_FIXTURE": ""})
        state = self.state("stuck")
        self.assertEqual(agent_run.identity(state["pid"]), state["pid_identity"])
        os.kill(state["pid"], signal.SIGSTOP)
        killed = self.cli("kill", "stuck", env={"GDD_RUN_STOP_WAIT_SECONDS": "1"})
        self.assertEqual(killed.returncode, 0, killed.stderr)
        self.assertEqual(self.finished("stuck")["state"], "killed")

    @unittest.skipUnless(sys.platform == "linux", "requires a Linux user manager")
    def test_systemd_preserves_literal_paths_and_umask(self):
        try:
            agent_run.select_detach("systemd")
        except ValueError as exc:
            self.skipTest(str(exc))
        self.root = os.path.join(self.tmp, "runs %h $HOME")
        self.work = os.path.join(self.tmp, "work %n $USER")
        os.mkdir(self.work)
        self.env["GDD_RUN_ROOT"] = self.root
        self.check_dispatcher_umask("systemd")
        self.assertEqual(self.recorded()["cwd"], self.work)

    @unittest.skipIf(IS_WINDOWS, "POSIX file creation mask")
    def test_setsid_keeps_the_dispatchers_umask(self):
        self.check_dispatcher_umask("setsid")

    def check_dispatcher_umask(self, mode):
        started = gdd_process.run(
            [sys.executable, "-B", RUNNER, "start", "--name", "umask", "--prompt", self.prompt],
            env={**self.env, "GDD_RUN_DETACH": mode, "STUB_FIXTURE": route_fixture("omp")},
            cwd=self.work, umask=0o027, capture_output=True, text=True, timeout=30)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(self.finished("umask")["state"], "done")
        self.assertEqual(Path(self.record).stat().st_mode & 0o777, 0o640)
        self.assertEqual(Path(self.run_dir("umask"), "answer.md").stat().st_mode & 0o777, 0o640)

    def craft(self, name, state=None, raw=None):
        run_dir = os.path.join(self.root, "2000-01-01", name)
        os.makedirs(run_dir)
        write(os.path.join(run_dir, "prompt.md"), PROMPT)
        if state is not None or raw is not None:
            write(os.path.join(run_dir, "state.json"), raw if raw is not None else json.dumps(state))
        return run_dir

    def test_status_treats_a_reused_runner_pid_as_stale(self):
        state = {"name": "reused-runner", "agent": "omp", "state": "running", "pid": os.getpid(),
                 "pid_identity": different_identity(agent_run.identity(os.getpid())), "agent_pid": None}
        run_dir = self.craft("reused-runner", state)
        self.assertEqual(agent_run.observed_state(run_dir, state), "stale")
        status = self.cli("status", "reused-runner")
        self.assertEqual(status.returncode, 0, status.stderr)
        result = json.JSONDecoder().raw_decode(status.stdout)[0]
        self.assertFalse(result["alive"])
        self.assertTrue(result["stale_recovered"])

    def test_ps_identity_survives_changes_to_dispatcher_timezone_and_locale(self):
        outputs = {"America/Los_Angeles": "Wed Nov 18 21:39:53 2026",
                   "UTC": "Thu Nov 19 05:39:53 2026"}

        def ps(argv, *, env, **kwargs):
            output = outputs[env["TZ"]] if env["LC_ALL"] == "C" else "localized output"
            return subprocess.CompletedProcess(argv, 0, output + "\n")

        state = {"name": "mac-run", "state": "running", "pid": os.getpid()}
        with mock.patch.object(agent_run, "IS_WINDOWS", False), mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(agent_run, "pid_alive", return_value=True), \
                mock.patch.object(gdd_process, "run", side_effect=ps):
            with mock.patch.dict(os.environ, {"TZ": "America/Los_Angeles", "LC_ALL": "fr_FR.UTF-8"}):
                state["pid_identity"] = agent_run.identity(state["pid"])
            with mock.patch.dict(os.environ, {"TZ": "UTC", "LC_ALL": "C"}):
                self.assertEqual(agent_run.identity(state["pid"]), state["pid_identity"])
                self.assertEqual(agent_run.observed_state(self.tmp, state), "running")
            self.assertRegex(state["pid_identity"], r"^ps-utc:[0-9]+$")

    def test_unverified_identity_never_settles_or_signals_a_live_pid(self):
        cases = [
            ("ps:Thu Nov 19 05:39:53 2026", "ps-utc:123"),
            ("ps-utc:garbage", "ps-utc:123"),
            ("linux:garbage", "linux:123"),
            ("win:garbage", "win:123"),
            ("linux:123", "win:456"),
            ("linux:123", ""),
        ]
        for i, (recorded, current) in enumerate(cases):
            with self.subTest(recorded=recorded, current=current):
                state = {"name": f"unknown-{i}", "state": "running", "pid": os.getpid(), "pid_identity": recorded}
                run_dir = self.craft(state["name"], state)
                with mock.patch.object(agent_run, "identity", return_value=current), \
                        mock.patch.object(agent_run, "wait_until", side_effect=lambda ready, _: ready()), \
                        mock.patch.object(agent_run, "terminate") as terminate:
                    self.assertEqual(agent_run.observed_state(run_dir, state), "running")
                    self.assertIn("start time unverified", agent_run.stop_run(run_dir))
                    terminate.assert_not_called()
                    self.assertFalse(Path(run_dir, "finalized").exists())

    def test_t7_starting_grace(self):
        base = {"name": "s", "agent": "omp", "state": "running", "exit": None, "pid": None, "agent_pid": None}
        self.craft("young", {**base, "started": datetime.now(timezone.utc).isoformat()})
        self.assertEqual(json.loads(self.cli("status", "young").stdout)["state"], "running")
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.craft("old", {**base, "started": old})
        out = self.cli("status", "old").stdout
        self.assertIn("stale_recovered: true", out)
        self.assertEqual((self.state("old")["state"], self.state("old")["exit"]), ("failed", -1))
        foreign = {"name": "s", "state": "running", "exit": None, "started": old}
        for name, state in (("paseo", {**base, **foreign, "backend": "paseo"}), ("custom", foreign)):
            with self.subTest(name=name):  # another launcher's run is never settled here
                run_dir = self.craft(name, state)
                self.cli("list")
                self.assertEqual(self.state(name)["state"], "running")
                self.assertFalse(os.path.exists(os.path.join(run_dir, "finalized")))

    def test_t8_missing_or_garbage_state_is_unknown(self):
        self.craft("missing")
        self.craft("garbage", raw="{not json")
        for name in ("missing", "garbage"):
            with self.subTest(name=name):
                status = self.cli("status", name)
                self.assertEqual(json.loads(status.stdout)["state"], "unknown")
                self.assertEqual(self.cli("answer", name).returncode, 1)

    def test_t9_start_refusals(self):
        cases = [
            ((), {"OMP_BIN": os.path.join(self.tmp, "nope")}, "agent binary not found: OMP_BIN="),
            (("--name", ".."), {}, "does not sanitize"),
            (("--max-time", "soon"), {}, "--max-time must be"),
        ]
        if IS_WINDOWS:
            shim = os.path.join(self.tmp, "omp.cmd")
            write(shim, "@echo off\n")
            cases.append(((), {"OMP_BIN": shim}, "is a .cmd shim and argument 5 contains"))
        for args, env, message in cases:
            with self.subTest(message=message):
                argv = ["start", "--prompt", self.prompt, "--cwd", self.work]
                argv += [] if "--name" in args else ["--name", "refused"]
                proc = self.cli(*argv, *args, env=env)
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn(message, proc.stderr)
                self.assertFalse(glob.glob(os.path.join(self.root, "*", "*")), "a refusal created a run dir")

    def test_t9_bad_config_file_is_one_line_error(self):
        os.makedirs(os.path.join(self.tmp, "gdd"))
        write(os.path.join(self.tmp, "gdd", "config.yaml"), "not a mapping\n")
        for command in (("list",), ("status", "x"), ("kill", "x")):
            with self.subTest(command=command[0]):
                proc = self.cli(*command, env={"GDD_RUN_ROOT": "", "XDG_CONFIG_HOME": self.tmp})
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn("agent_run: GDD_RUN_ROOT: ", proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)

    def test_t9_live_slug_needs_replace(self):
        self.start("busy", env={"STUB_HANG": "1"})
        previous = Path(self.run_dir("busy"))
        refused = self.start("busy", env={"STUB_HANG": "1"}, expect=1)
        self.assertIn("still running", refused.stderr)
        self.start("busy", "omp", "ok", "--replace")
        self.assertEqual(self.finished("busy")["state"], "done")
        # A same-day restart archives the old directory; across midnight it is already separate.
        if Path(self.run_dir("busy")) == previous:
            previous, = previous.parent.glob("busy.prev-*")
        state = wait_for_json(previous / "state.json", lambda s: finalized(previous, s), time.monotonic() + 5)
        self.assertEqual(state["state"], "killed")

    def test_t10_max_time(self):
        with self.stdout_holder("slow", flags=("--max-time", "5"), STUB_HANG="1") as (_, descendant):
            state = self.finished("slow")
            self.assertEqual((state["state"], state["exit"]), ("failed", 124))
            self.assertIn("max_time exceeded", state["note"])
            self.assertTrue(agent_run.wait_until(lambda: exited(*descendant), 5),
                            f"Grandchild PID {descendant[0]} survived max-time")

    def test_t11_event_bound_rotates_and_counters_stay_exact(self):
        self.start("bound", env={"GDD_RUN_EVENTS_MAX_BYTES": "1500"})
        state = self.finished("bound")
        run_dir = self.run_dir("bound")
        self.assertTrue(os.path.exists(os.path.join(run_dir, "events.1.ndjson")))
        first = json.loads(read(os.path.join(run_dir, "events.ndjson")).splitlines()[0])
        self.assertEqual(first["type"], "truncated")
        self.assertGreater(first["dropped_bytes"], 0)
        self.assertTrue(state["events_truncated"])
        self.assertEqual(state["events_dropped_bytes"], first["dropped_bytes"])
        self.assertEqual((state["turns"], state["tool_calls"], state["state"]), (2, 1, "done"))
        self.assertNotIn("tool_calls_partial", state)

    @contextmanager
    def stdout_holder(self, name, *, flags=(), **env):
        record = None

        def verify_child_exit():
            path = Path(record or (self.record + ".child"))
            child = wait_for_json(path, lambda row: len(row) == 2 and row[1], time.monotonic() + 5)
            check_processes({tuple(child): (path, True)}, 5)

        with socket.socket(socket.AF_INET if IS_WINDOWS else socket.AF_UNIX) as listener:
            endpoint = os.path.join(self.tmp, "drain.sock")
            listener.bind(("127.0.0.1", 0) if IS_WINDOWS else endpoint)
            if IS_WINDOWS:
                endpoint = str(listener.getsockname()[1])
            listener.listen()
            listener.settimeout(10)
            self.addCleanup(verify_child_exit)
            self.start(name, "omp", "ok", *flags, env={"STUB_DRAIN_ENDPOINT": endpoint, **env})
            record = self.record + ".child"
            peer, _ = listener.accept()
            with peer, peer.makefile("rb") as stream:
                peer.settimeout(5)
                self.assertEqual(stream.readline(16), b"READY\n")
                child = wait_for_json(self.record + ".child", lambda row: len(row) == 2 and row[1],
                                      time.monotonic() + 5)
                self.assertFalse(exited(*child), f"Grandchild PID {child[0]} did not stay alive")
                yield peer, child

    def test_t12_drain_timeout_marks_stream_incomplete(self):
        with self.stdout_holder("drain", GDD_RUN_DRAIN_TIMEOUT_SECONDS="1") as (peer, _):
            state = self.finished("drain")
            self.assertTrue(state.get("stream_incomplete"), state)
            self.assertEqual(state["state"], "done")
            peer.sendall(b"R")

    def omp_fixture(self, answer):
        """omp.ok with every assistant message_end answering `answer`."""
        events = [json.loads(line) for line in read(route_fixture("omp")).splitlines()
                  if line.strip() and not line.startswith("#")]
        for event in events:
            if event["type"] == "message_end" and event["message"]["role"] == "assistant":
                event["message"]["content"] = [{"type": "text", "text": answer}]
        path = os.path.join(self.tmp, f"omp-{len(os.listdir(self.tmp))}.ndjson")
        write(path, "".join(json.dumps(event) + "\n" for event in events))
        return path

    def test_t14_structured_result(self):
        bad = {**STAGE_RESULT, "gates": [{"command": "make test", "exit_code": "0", "counts": None}]}
        cases = (("fenced", f"Report.\n```json\n{json.dumps(STAGE_RESULT)}\n```\n", "valid", None),
                 ("invalid", f"```json\n{json.dumps(bad)}\n```", "invalid",
                  '$.gates[0].exit_code: expected integer, got "0"'),
                 ("missing", "done", "missing", None))
        for name, answer, verdict, error in cases:
            with self.subTest(case=name):
                self.start(name, "omp", "ok", "--schema", RESULT_SCHEMA, env={"STUB_FIXTURE": self.omp_fixture(answer)})
                state = self.finished(name)
                self.assertEqual((state["state"], state["result"], state.get("result_error")), ("done", verdict, error))
                self.assertEqual(os.path.exists(os.path.join(self.run_dir(name), "result.json")), verdict == "valid")
                self.assertEqual(stage_result.error(state, SCHEMA), "")
                if verdict == "valid":
                    result = self.cli("result", name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    reported, end = json.JSONDecoder().raw_decode(result.stdout)
                    self.assertEqual(reported["result"], "valid")
                    self.assertIn(answer, result.stdout[end:])
        refused = self.cli("start", "--name", "noschema", "--prompt", self.prompt, "--schema", os.path.join(self.tmp, "nope"))
        self.assertEqual(refused.returncode, 1)
        self.assertIn("is not a readable JSON object", refused.stderr)

    @unittest.skipIf(IS_WINDOWS or not shutil.which("bash"), "the gdd-route-omp forwarder is bash")
    def test_t15_omp_headless_forwarder_resolves_the_sibling_runner(self):
        forwarder = os.path.join(HERE, "..", "..", "..", "gdd-route-omp", "scripts", "omp-run.sh")
        env = {**self.env, "STUB_FIXTURE": route_fixture("omp"), "GDD_AGENT": "dsh"}
        proc = gdd_process.run(["bash", forwarder, "start", "--name", "fwd", "--prompt", self.prompt, "--cwd", self.work],
                              capture_output=True, text=True, env=env, timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.finished("fwd")["agent"], "omp")  # the forwarder pins GDD_AGENT=omp
        listed = gdd_process.run(["bash", forwarder, "list"], capture_output=True, text=True, env=env, timeout=90)
        self.assertIn("fwd", listed.stdout)

    def test_t16_tail_renders_one_line_per_event(self):
        self.start("tail")
        self.finished("tail")
        events = read(os.path.join(self.run_dir("tail"), "events.ndjson")).splitlines()
        lines = self.cli("tail", "tail", "100").stdout.splitlines()
        self.assertEqual(len(lines), len(events))
        self.assertIn("message_end: done", lines)
        for line, raw in zip(lines, events):
            kind = json.loads(raw)["type"]
            self.assertTrue(line == kind or (line.startswith(f"{kind}: ") and len(line) <= len(kind) + 162), line)

    def test_t17_detachment_rule(self):
        self.start("detached", env={"STUB_HANG": "1"})
        state = self.state("detached")
        if IS_WINDOWS:
            self.assertEqual(state["detach"], "windows")
            self.assertIn(state["spawn"]["creationflags"], (0x08000200, 0x09000200))
        else:
            self.assertEqual(state["detach"], "setsid")
            self.assertNotEqual(os.getsid(state["pid"]), state["pid"])
            self.assertNotEqual(os.getsid(state["pid"]), os.getsid(0))
            self.assertEqual(os.getsid(state["agent_pid"]), state["agent_pid"])

    @unittest.skipUnless(sys.platform == "linux", "requires Linux process/session inspection")
    def test_double_fork_survives_dispatcher_process_group_death(self):
        wrapper = """
import subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[3]).parent))
import gdd_process
gdd_process.run(sys.argv[1:], check=True, stdout=subprocess.DEVNULL)
print("READY", flush=True)
if sys.stdin.readline().strip() != "RELEASE":
    raise SystemExit(2)
"""
        argv = [sys.executable, "-B", RUNNER, "start", "--name", "survival", "--prompt", self.prompt]
        caller = gdd_process.popen([sys.executable, "-c", wrapper, *argv], start_new_session=True,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                                   env={**self.env, "STUB_HANG": "1"}, cwd=self.work)
        self.children.append(caller)
        with contextlib.ExitStack() as release:
            def release_caller():
                if caller.poll() is None:
                    caller.communicate("RELEASE\n", timeout=5)

            release.callback(release_caller)
            ready(caller, 25)
            self.assertIsNone(caller.poll())
            state = self.state("survival")
            pid = state["pid"]
            self.assertNotEqual(os.getsid(pid), os.getsid(caller.pid))
            self.assertNotEqual(os.getpgid(pid), os.getpgid(caller.pid))
            self.assertNotEqual(os.getsid(pid), pid)  # grandchild, not the setsid leader
            os.killpg(caller.pid, signal.SIGKILL)
            self.assertEqual(caller.wait(timeout=5), -signal.SIGKILL)
            self.assertEqual(agent_run.identity(pid), state["pid_identity"])
            self.assertEqual(agent_run.identity(state["agent_pid"]), state["agent_pid_identity"])
            stopped = self.cli("kill", "survival")
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertEqual(self.finished("survival")["state"], "killed")


class RunnerMechanicsTests(unittest.TestCase):
    def test_stub_identity_matches_runner(self):
        stub_identity = own_identity()
        self.assertTrue(stub_identity)
        self.assertEqual(stub_identity, agent_run.identity(os.getpid()))

    def test_child_env_drops_the_uv_script_venv_only(self):
        with tempfile.TemporaryDirectory() as venv:
            bindir = os.path.join(venv, "Scripts" if IS_WINDOWS else "bin")
            caller = os.pathsep.join([bindir, "/usr/bin"])
            uv = {"VIRTUAL_ENV": venv, "UV_RUN_RECURSION_DEPTH": "1", "PATH": caller, "KEEP": "1",
                  "DROP": "1"}
            with mock.patch.dict(os.environ, uv, clear=True), mock.patch.object(sys, "prefix", venv):
                env = agent_run.child_env({"DROP"})
            self.assertEqual(env, {"PATH": "/usr/bin", "KEEP": "1"})
            # A venv the caller activated (not uv run's) is theirs: keep it.
            own = {"VIRTUAL_ENV": venv, "PATH": caller}
            with mock.patch.dict(os.environ, own, clear=True), mock.patch.object(sys, "prefix", venv):
                self.assertEqual(agent_run.child_env(set()), own)

    def test_finalize_keeps_first_terminal_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            agent_run.write_json(run / "state.json", {"state": "running"})
            first = agent_run.finalize(run, 0)
            self.assertEqual((first["state"], first["exit"]), ("done", 0))
            self.assertEqual(agent_run.finalize(run, 2), first)
            self.assertEqual(agent_run.read_state(run), first)
            self.assertEqual((run / "exit.code").read_text(encoding="utf-8").strip(), "0")
            self.assertTrue(finalized(run, first))

    def test_terminate_stops_when_pid_is_reused_after_first_signal(self):
        pid = 12345
        recorded = current = "win:1" if IS_WINDOWS else "linux:1"

        def replaced(*args, **kwargs):
            nonlocal current
            current = different_identity(recorded)

        signal_target, method = (gdd_process, "run") if IS_WINDOWS else (os, "killpg")
        with mock.patch.object(agent_run, "identity", side_effect=lambda _: current), \
                mock.patch.object(agent_run, "pid_alive", return_value=True), \
                mock.patch.object(signal_target, method, side_effect=replaced) as send:
            self.assertTrue(agent_run.terminate(pid, recorded=recorded))
        send.assert_called_once()

    def test_detach_modes(self):
        for platform, available, response, expected in (
            ("linux", True, "running", "systemd"), ("linux", True, "degraded", "systemd"),
            ("linux", True, "offline", "setsid"), ("linux", False, "", "setsid"),
            ("darwin", True, "", "launchd"), ("darwin", False, "", "launchd"),
            ("freebsd14", True, "", "setsid"), ("win32", True, "", "windows"),
        ):
            with self.subTest(platform=platform, available=available, response=response), \
                    mock.patch.object(agent_run.sys, "platform", platform), \
                    mock.patch.object(agent_run, "IS_WINDOWS", platform == "win32"), \
                    mock.patch.object(agent_run.shutil, "which", side_effect=lambda name: name if available else None), \
                    mock.patch.object(agent_run.subprocess, "run",
                                      return_value=subprocess.CompletedProcess([], int(response != "running"), response)) as probe:
                plain = "windows" if platform == "win32" else "setsid"
                self.assertEqual(agent_run.select_detach(plain), (plain, None))
                probe.assert_not_called()
                tool = {"systemd": "systemd-run", "launchd": "launchctl"}.get(expected) if available else None
                self.assertEqual(agent_run.select_detach("auto"), (expected, tool))
                if expected == "systemd":
                    self.assertEqual(agent_run.select_detach("systemd"), ("systemd", "systemd-run"))
                else:
                    with self.assertRaises(ValueError):
                        agent_run.select_detach("systemd")
        with mock.patch.object(agent_run.sys, "platform", "linux"), \
                mock.patch.object(agent_run, "IS_WINDOWS", False), \
                mock.patch.object(agent_run.shutil, "which", side_effect=lambda name: name), \
                mock.patch.object(agent_run.subprocess, "run",
                                  side_effect=subprocess.TimeoutExpired("systemctl", 1)) as probe:
            self.assertEqual(agent_run.select_detach("auto"), ("setsid", None))
            self.assertEqual(probe.call_args.kwargs["timeout"], 1)

    def test_windows_detach_retries_without_breakaway_on_access_denied(self):
        error = PermissionError("job denies breakaway")
        error.winerror = 5
        process = mock.Mock(pid=1234)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(gdd_process, "IS_WINDOWS", True), \
                mock.patch.object(subprocess, "Popen", side_effect=[error, process]) as spawn:
            self.assertEqual(agent_run.spawn_detached(["python", "runner.py"], tmp, tmp, {},
                                                       {"name": "demo"}, "windows"), (1234, 0x08000200))
            self.assertEqual([call.kwargs["creationflags"] for call in spawn.call_args_list],
                             [0x09000200, 0x08000200])

    def test_systemd_argv_and_private_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            state = {"name": "demo.slug"}

            def submit(argv, **kwargs):
                self.assertRegex(state["unit"], r"^gdd-demo\.slug-[0-9a-f]{12}$")
                self.assertNotEqual(state["unit"], agent_run.unit_name(state["name"]))
                self.assertEqual(argv, [
                    "systemd-run", "--user", "--collect", "--unit", state["unit"], "--service-type=exec",
                    "--no-ask-password", "--working-directory=/work/with spaces", "--property=UMask=0027",
                    f"--property=StandardOutput=append:{run / 'runner.log'}", "--property=StandardError=inherit",
                    "--", "/python", "-B", "/runner.py", "_run", "--run-dir", "/runs/$$literal", "--restore-env",
                ])
                with mock.patch.dict(os.environ, {"MANAGER_ONLY": "unused"}, clear=True):
                    agent_run.restore_detached_env(run)
                    self.assertEqual(dict(os.environ), {"SECRET": "value with \n and $"})
                return subprocess.CompletedProcess(argv, 0, "", "")

            with mock.patch.object(agent_run, "supervisor_call", side_effect=submit), \
                    mock.patch.object(os, "umask", return_value=0o027) as umask:
                agent_run.spawn_detached(["/python", "-B", "/runner.py", "_run", "--run-dir", "/runs/$literal"],
                                         run, "/work/with spaces", {"SECRET": "value with \n and $"},
                                         state, "systemd", "systemd-run")
            self.assertEqual(umask.call_args_list, [mock.call(0o777), mock.call(0o027)])
            self.assertFalse((run / ".runner-env").exists())

    def test_progress_tick_waits_out_windows_reader_before_replacing(self):
        error = PermissionError("locked by a reader")
        error.winerror = 5
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            replace = os.replace
            waited = 0.0

            def sleep(seconds):
                nonlocal waited
                waited += seconds

            def replace_when_released(source, dest):
                if waited < 0.5:
                    raise error
                return replace(source, dest)

            with mock.patch.object(os, "replace", side_effect=replace_when_released) as attempt, \
                    mock.patch.object(agent_run.time, "sleep", side_effect=sleep):
                agent_run.write_json(path, {"turns": 2}, progress_tick=True)
            self.assertGreater(attempt.call_count, 3)
            self.assertGreaterEqual(waited, 0.5)
            self.assertLessEqual(waited, 1.0)
            self.assertEqual(agent_run.read_state(tmp), {"turns": 2})

    def test_winerror_5_falls_back_to_in_place_write(self):
        error = PermissionError("locked by a reader")
        error.winerror = 5
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            original = {"state": "running"}
            agent_run.write_json(path, original)
            with mock.patch.object(agent_run.os, "replace", side_effect=error) as replace, \
                    mock.patch.object(agent_run.time, "sleep"), contextlib.redirect_stderr(stderr):
                agent_run.write_json(path, {"state": "done"})
            self.assertEqual(replace.call_count, 40)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"state": "done"})
            self.assertEqual(list(Path(tmp).iterdir()), [path])
            self.assertEqual(len(stderr.getvalue().splitlines()), 1)

    def test_runner_retries_progress_when_replace_and_in_place_write_fail(self):
        fixture = route_fixture("omp")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            agent_run.write_json(path / "state.json", {"name": "progress", "spawn": {}})
            agent_run.write_json(path / "run.json", {
                "agent": "omp", "argv": [sys.executable, STUB], "cwd": tmp, "prompt": "argv",
            })
            (path / "prompt.md").write_text("finish", encoding="utf-8")
            writes, real_replace, real_write = [], os.replace, agent_run.write_text
            error = PermissionError("locked by a reader")
            error.winerror = 5

            def replace(source, target):
                if writes == [False] and str(target) == str(path / "state.json"):
                    raise error
                return real_replace(source, target)

            def write_text(target, data):
                if str(target) == str(path / "state.json") and writes == [False]:
                    writes.append(True)
                    raise error
                if str(target).endswith(".tmp") and '"turns":' in data and '"ended":' not in data:
                    writes.append(False)
                    if writes == [False, True, False]:
                        (path / "release").touch()
                return real_write(target, data)

            stderr = io.StringIO()
            with mock.patch.object(os, "replace", side_effect=replace), \
                    mock.patch.object(agent_run, "write_text", side_effect=write_text), \
                    mock.patch.object(agent_run, "PROGRESS_SECONDS", 0.05), \
                    mock.patch.dict(os.environ, {"STUB_FIXTURE": fixture,
                                                 "STUB_PROGRESS_RELEASE": str(path / "release")}), \
                    contextlib.redirect_stderr(stderr):
                handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM,
                            getattr(signal, "SIGBREAK" if IS_WINDOWS else "SIGHUP"))}
                try:
                    self.assertEqual(agent_run.main(["_run", "--run-dir", tmp]), 0)
                finally:
                    for sig, handler in handlers.items():
                        signal.signal(sig, handler)
                    state = agent_run.read_state(tmp)
                    if pid := state.get("agent_pid"):
                        check_processes({(pid, state.get("agent_pid_identity")): (path, False)}, 0)
            self.assertEqual(writes[:3], [False, True, False])
            self.assertEqual(len(stderr.getvalue().splitlines()), 1)
            self.assertEqual(agent_run.read_state(tmp)["state"], "done")


@unittest.skipUnless(os.environ.get("GDD_SMOKE_AGENTS"), "set GDD_SMOKE_AGENTS=omp,... to run real CLIs")
class SmokeTests(RunnerCase):
    def test_real_agents(self):
        """A new session, then a resume of it, per agent; each must end done with a valid stage result."""
        gdd_process.run(["git", "init", "-q", self.work], check=True)  # codex refuses a non-repo cwd
        write(self.prompt, f"Change nothing. Reply with one line saying done, then exactly this block:\n"
                           f"```json\n{json.dumps(STAGE_RESULT)}\n```\n")
        for agent in os.environ["GDD_SMOKE_AGENTS"].split(","):
            env, resume = {f"{agent.upper()}_BIN": os.environ.get(f"{agent.upper()}_BIN") or agent}, ()
            model = os.environ.get(f"GDD_SMOKE_{agent.upper()}_MODEL")
            for name in (f"smoke-{agent}", f"smoke-{agent}-resume"):
                with self.subTest(run=name):
                    proc = self.cli("start", "--name", name, "--prompt", self.prompt, "--agent", agent, "--cwd",
                                    self.work, "--schema", RESULT_SCHEMA, *resume,
                                    *(("--model", model) if model else ()), env=env)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    state = self.finished(name, 300)
                    print(f"smoke {name}: state={state['state']} exit={state['exit']} turns={state['turns']} "
                          f"result={state.get('result')} session={state['session_id']}")
                    self.assertEqual((state["state"], state.get("result")), ("done", "valid"), state)
                    resume = ("--resume", state["session_id"])


class InterpreterTests(unittest.TestCase):
    def test_runner_pid_is_the_running_interpreter_inside_a_venv(self):
        # Supervisors record the runner's Popen pid. A Windows venv python.exe is a launcher that
        # re-spawns the base interpreter, so its pid would not name the process that runs. Build a
        # venv here: CI may run pytest from a base interpreter, which would hide the launcher.
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "v"
            made = gdd_process.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(made.returncode, 0, made.stderr)
            python = venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
            probe = ("import sys, subprocess; sys.path.insert(0, sys.argv[1]); import agent_run, gdd_process;"
                     "c = gdd_process.popen([agent_run.runner_interpreter(), '-c', 'import os; print(os.getpid())'],"
                     " stdout=subprocess.PIPE, text=True); out, _ = c.communicate(timeout=60);"
                     "print(int(out) == c.pid, int(out), c.pid)")
            result = gdd_process.run([str(python), "-c", probe, os.path.dirname(RUNNER)], capture_output=True,
                                     text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith("True"), result.stdout)


if __name__ == "__main__":
    unittest.main()
