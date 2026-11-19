#!/usr/bin/env python3
"""Contract tests for gdd.py and delivery-state.py, launching through agent_run.py and the stub agent."""
import glob
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
import gdd_process
import agent_run
from gdd_test_support import check_locks, cleanup_child, exited, ready, remove_tree, stop_headless, wait_for_json
GDD = os.path.join(SCRIPTS, "gdd.py")
DELIVERY = os.path.join(SCRIPTS, "delivery-state.py")
STUB = os.path.join(HERE, "stub_agent.py")
OK_FIXTURE = os.path.join(HERE, "fixtures", "events", "omp.ok.ndjson")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def dead_pid(children):
    proc = gdd_process.popen(
        [sys.executable, "-c", 'import sys; print("READY", flush=True); sys.exit(sys.stdin.readline() != "RELEASE\\n")'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    children.append(proc)
    ready(proc)
    recorded = agent_run.identity(proc.pid)
    proc.communicate("RELEASE\n", timeout=5)
    assert proc.returncode == 0 and exited(proc.pid, recorded), (proc.pid, recorded, proc.returncode)
    return proc.pid, recorded


class GddCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gdd-test-")
        self.addCleanup(remove_tree, self.tmp)
        self.addCleanup(check_locks, self.tmp)
        self.addCleanup(stop_headless, self.tmp)
        self.children = []
        self.addCleanup(cleanup_child, self.children)
        self.state_home = os.path.join(self.tmp, "state")
        self.record = os.path.join(self.tmp, "record.json")
        drop = ("GDD_", "STUB_", "DSH_", "OMP_", "XDG_")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
        self.env.update(XDG_STATE_HOME=self.state_home, XDG_CONFIG_HOME=os.path.join(self.tmp, "config"),
                        GDD_RUN_DETACH="windows" if os.name == "nt" else "setsid",
                        OMP_BIN=STUB, DSH_BIN=STUB, CLAUDE_BIN=STUB, STUB_FIXTURE=OK_FIXTURE, STUB_RECORD=self.record,
                        PYTHONDONTWRITEBYTECODE="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        self.repo = os.path.realpath(os.path.join(self.tmp, "workrepo"))
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        write(os.path.join(self.repo, "docs", "goals", "0001-first.md"), "# Goal 0001\nState: active\n")
        self.commit("contract")
        self.base = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        write(os.path.join(self.repo, "a.txt"), "a\n")
        self.head = self.commit("work")

    def git(self, *args):
        return gdd_process.run(["git", "-C", self.repo, *args], env=self.env, capture_output=True, text=True,
                              check=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def run_tool(self, script, *args, env=None):
        return gdd_process.run([sys.executable, "-B", script, *args], capture_output=True, text=True,
                              env={**self.env, **(env or {})}, timeout=120)

    def stage(self, stage, *args, env=None):
        self.record = os.path.join(self.tmp, f"record-{uuid.uuid4().hex}.json")
        return self.run_tool(GDD, "stage", "--repo", self.repo, "--goal", "0001", "--stage", stage, *args,
                             env={"STUB_RECORD": self.record, **(env or {})})

    def ledger(self, path=None):
        path = path or os.path.join(self.state_home, "gdd", "ledger.tsv")
        lines = read(path).splitlines() if os.path.exists(path) else []
        header = lines[0].split("\t") if lines else []
        return [dict(zip(header, line.split("\t"))) for line in lines[1:]]

    def run_dirs(self, root=None):
        return glob.glob(os.path.join(root or os.path.join(self.state_home, "gdd", "runs"), "*", "*"))

    def craft_run(self, name, *, pid=None, pid_identity=None, **state):
        run_dir = os.path.join(self.state_home, "gdd", "runs", "2000-01-01", name)
        write(os.path.join(run_dir, "state.json"), json.dumps(
            {"name": name, "agent": "omp", "state": "running", "exit": None, "cwd": self.repo,
             "started": datetime.now(timezone.utc).isoformat(), "pid": pid, "pid_identity": pid_identity,
             "agent_pid": None, **state}))
        return run_dir


class LedgerAndRenderTests(GddCase):
    def test_ledger_append_show_and_invalid_stage(self):
        ledger = os.path.join(self.tmp, "ledger.tsv")
        appended = self.run_tool(DELIVERY, "append", "--repo", self.repo, "--goal", "0001", "--stage", "implement",
                                 "--base", self.base, "--head", self.head, "--next", "review", "--state-file", ledger)
        self.assertEqual(appended.returncode, 0, appended.stderr)
        show = self.run_tool(DELIVERY, "show", "--repo", self.repo, "--goal", "0001", "--state-file", ledger,
                             "--task-root", os.path.join(self.tmp, "tasks"), "--run-root", os.path.join(self.tmp, "r"))
        self.assertEqual(show.returncode, 0, show.stderr)
        for line in ("stage: implement", "next_action: review", "ahead_of_origin_main: 1", "behind_origin_main: 0",
                     "base_is_origin_main: yes", "last_run: none (no runs for this repo)"):
            self.assertIn(line, show.stdout.splitlines())
        bad = self.run_tool(DELIVERY, "append", "--repo", self.repo, "--goal", "0001", "--stage", "bogus",
                            "--state-file", ledger)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(self.stage("bogus").returncode, 2)
        self.assertEqual(self.stage("gates").returncode, 2)  # mechanical stage

    def test_dry_run_uses_xdg_defaults_and_findings_are_required(self):
        dry = self.stage("implement", "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        prompt = dry.stdout.splitlines()[0].removeprefix("prompt: ")
        self.assertTrue(prompt.startswith(os.path.join(self.state_home, "gdd", "tasks")), prompt)
        self.assertIn(self.head, read(prompt))
        self.assertIn("0001-first.md", read(prompt))
        missing = self.stage("apply", "--dry-run")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--findings is required", missing.stderr)
        self.assertEqual(self.run_dirs(), [])

    def test_dispatch_guards(self):
        write(os.path.join(self.repo, "dirty.txt"), "x\n")
        cases = [
            (("implement",), "worktree is dirty"),
            (("review", "--base", self.head, "--head", "HEAD"), "base == head"),
        ]
        for args, message in cases:
            with self.subTest(message=message):
                refused = self.stage(*args, "--dry-run")
                self.assertEqual(refused.returncode, 3, refused.stdout)
                self.assertIn(message, refused.stderr)
        self.assertEqual(self.stage("implement", "--dry-run", "--force").returncode, 0)
        os.remove(os.path.join(self.repo, "dirty.txt"))
        for header, message in (("State: draft", "declares state 'draft'"), (None, "is archived")):
            with self.subTest(message=message):
                goal = os.path.join(self.repo, "docs", "goals", "0001-first.md")
                if header:
                    write(goal, f"# Goal 0001\n{header}\n")
                else:
                    os.makedirs(os.path.join(self.repo, "docs", "goals", "archive"), exist_ok=True)
                    os.replace(goal, os.path.join(self.repo, "docs", "goals", "archive", "0001-first.md"))
                self.commit(message)
                refused = self.stage("implement", "--dry-run")
                self.assertEqual(refused.returncode, 3, refused.stdout)
                self.assertIn(message, refused.stderr)


class LaunchTests(GddCase):
    def test_stage_wait_through_agent_run(self):
        done = self.stage("implement", "--wait")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("finished: state=done", done.stdout)
        self.assertIn("answer: ", done.stdout)
        self.assertEqual(done.stdout.rstrip().splitlines()[-2:], ["done", "result: missing"])
        rows = self.ledger()
        self.assertEqual([(r["stage"], r["next_action"]) for r in rows], [("implement", "implement"), ("implement", "-")])
        self.assertTrue(rows[1]["note"].startswith("exit=0 "), rows[1])
        state = json.loads(read(os.path.join(self.run_dirs()[0], "state.json")))
        self.assertEqual((state["agent"], state["state"], state["cwd"]), ("omp", "done", self.repo))

    def test_stage_result_reaches_the_agent_and_the_ledger(self):
        env = {"GDD_AGENT": "claude", "STUB_FIXTURE": OK_FIXTURE.replace("omp.", "claude.")}
        done = self.stage("implement", "--wait", env=env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.stdout.rstrip().splitlines()[-1], "result: DONE")
        self.assertTrue(self.ledger()[-1]["note"].endswith(" verdict=DONE"), self.ledger()[-1])
        record = json.loads(read(self.record))
        schema = os.path.join(os.path.dirname(SCRIPTS), "references", "stage-result.schema.json")
        self.assertEqual(json.loads(record["argv"][record["argv"].index("--json-schema") + 1]), json.loads(read(schema)))
        self.assertIn(f"`{schema}`", record["stdin"])  # the template names the schema for prompt-instructed agents

    def test_model_thinking_max_time_pass_through_without_defaults(self):
        self.assertEqual(self.stage("implement", "--wait").returncode, 0)
        argv = json.loads(read(self.record))["argv"]
        self.assertFalse({"--model", "--thinking"} & set(argv), argv)
        self.assertIsNone(json.loads(read(os.path.join(self.run_dirs()[0], "state.json")))["max_time"])
        flags = {"GDD_MODEL": "m1", "GDD_THINKING": "high", "GDD_MAX_TIME": "5m"}
        done = self.stage("review", "--base", self.base, "--wait", env=flags)
        self.assertEqual(done.returncode, 0, done.stderr)
        argv = json.loads(read(self.record))["argv"]
        self.assertEqual(argv[argv.index("--model"):argv.index("--model") + 4], ["--model", "m1", "--thinking", "high"])
        review = [d for d in self.run_dirs() if d.endswith("-review")][0]
        self.assertEqual(json.loads(read(os.path.join(review, "state.json")))["max_time"], "5m")

    def test_config_file_run_root_and_agent_reach_the_launcher(self):
        root = os.path.join(self.tmp, "configured-runs")
        write(os.path.join(self.tmp, "config", "gdd", "config.yaml"), f"GDD_RUN_ROOT: {json.dumps(root)}\nGDD_AGENT: dsh\n")
        done = self.stage("implement", "--wait", env={"STUB_FIXTURE": OK_FIXTURE.replace("omp.", "dsh.")})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        [run_dir] = self.run_dirs(root)
        self.assertEqual(json.loads(read(os.path.join(run_dir, "state.json")))["agent"], "dsh")
        self.assertEqual(json.loads(read(self.record))["stdin"].split("\n")[0], "# Stage template — implement")

    def test_report_only_stage_keeps_the_supplied_head(self):
        write(os.path.join(self.repo, "b.txt"), "b\n")
        moved = self.commit("moved on")
        done = self.stage("review", "--base", self.base, "--head", self.head, "--wait")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ledger()[-1]["head_sha"], self.head)
        done = self.stage("implement", "--wait")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ledger()[-1]["head_sha"], moved)  # authoring stage: the post-run HEAD

    def test_failed_launch_records_one_blocked_row_and_no_run_dir(self):
        failed = self.stage("implement", env={"OMP_BIN": os.path.join(self.tmp, "missing-omp")})
        self.assertEqual(failed.returncode, 3)
        self.assertIn("launch failed: agent_run: start: agent binary not found", failed.stderr)
        rows = self.ledger()
        self.assertEqual([r["stage"] for r in rows], ["blocked"])
        self.assertIn("launch-failed:", rows[0]["note"])
        self.assertEqual(self.run_dirs(), [])

    def test_live_run_blocks_and_stale_run_does_not(self):
        self.craft_run("workrepo-0001-implement", pid=os.getpid(), pid_identity=agent_run.identity(os.getpid()))
        refused = self.stage("implement")
        self.assertEqual(refused.returncode, 3)
        self.assertIn("still active", refused.stderr)
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        pid, recorded = dead_pid(self.children)
        self.craft_run("workrepo-0001-implement", pid=pid, pid_identity=recorded, started=old)
        show = self.run_tool(GDD, "status", "--repo", self.repo, "--goal", "0001")
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn("last_run: workrepo-0001-implement stale exit=- dur=-", show.stdout.splitlines())
        done = self.stage("implement", "--wait")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        real_run = os.path.dirname(next(path for path in glob.glob(os.path.join(self.tmp, "**", "run.json"),
                                                                  recursive=True)))
        self.assertEqual(wait_for_json(os.path.join(real_run, "state.json"), bool, time.monotonic() + 5)["state"],
                         "done")

    def test_custom_launcher_without_pids_keeps_its_recorded_state(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        run_dir = self.craft_run("workrepo-0001-implement", started=old)
        state = json.loads(read(os.path.join(run_dir, "state.json")))
        write(os.path.join(run_dir, "state.json"), json.dumps({k: v for k, v in state.items() if "pid" not in k}))
        refused = self.stage("implement")
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertIn("still active", refused.stderr)


if __name__ == "__main__":
    unittest.main()
