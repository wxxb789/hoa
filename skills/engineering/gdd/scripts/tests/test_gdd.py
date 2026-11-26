"""Contract tests for gdd.py and delivery-state.py, launching through agent_run.py and the stub agent."""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
import gdd_process
import agent_run
from gdd_test_support import (check_locks, cleanup_child, exited, finalized, ready, remove_tree, route_fixture,
                              stop_headless, wait_for_json)
GDD = os.path.join(SCRIPTS, "gdd.py")
DELIVERY = os.path.join(SCRIPTS, "delivery-state.py")
STUB = os.path.join(HERE, "stub_agent.py")
OK_FIXTURE = route_fixture("omp")
GIT_IDENTITY = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


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


def git(repo, env, *args):
    return gdd_process.run(["git", "-C", repo, *args], env=env, capture_output=True, text=True,
                           check=True).stdout.strip()


def commit(repo, env, message):
    git(repo, env, "add", "-A")
    git(repo, env, "commit", "-q", "-m", message)
    return git(repo, env, "rev-parse", "HEAD")


class GddCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = tempfile.mkdtemp(prefix="gdd-seed-")
        cls.addClassCleanup(remove_tree, cls.seed)
        env = {**os.environ, **GIT_IDENTITY}
        git(cls.seed, env, "init", "-q", "-b", "main", "--template=")
        write(os.path.join(cls.seed, "docs", "goals", "0001-first.md"), "# Goal 0001\nState: active\n")
        cls.base = commit(cls.seed, env, "contract")
        git(cls.seed, env, "update-ref", "refs/remotes/origin/main", cls.base)
        write(os.path.join(cls.seed, "a.txt"), "a\n")
        cls.head = commit(cls.seed, env, "work")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gdd-test-")
        self.addCleanup(remove_tree, self.tmp)
        self.addCleanup(check_locks, self.tmp)
        self.addCleanup(stop_headless, self.tmp)
        self.children = []
        self.addCleanup(cleanup_child, self.children)
        self.state_home = os.path.join(self.tmp, "state")
        self.record = os.path.join(self.tmp, "record.json")
        drop = ("GDD_", "STUB_", "DSH_", "OMP_", "PASEO_", "XDG_")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
        # A detached auto-GC child cannot be joined, and it writes into the root while teardown deletes it.
        self.env.update(GDD_RUN_MAX_MB="off", XDG_STATE_HOME=self.state_home,
                        XDG_CONFIG_HOME=os.path.join(self.tmp, "config"),
                        GDD_RUN_DETACH="windows" if os.name == "nt" else "setsid",
                        OMP_BIN=STUB, DSH_BIN=STUB, CLAUDE_BIN=STUB, STUB_FIXTURE=OK_FIXTURE, STUB_RECORD=self.record,
                        PYTHONDONTWRITEBYTECODE="1", **GIT_IDENTITY)
        self.repo = os.path.realpath(os.path.join(self.tmp, "workrepo"))
        shutil.copytree(self.seed, self.repo)

    def commit(self, message):
        return commit(self.repo, self.env, message)

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

    def craft_run(self, name, *, date="2000-01-01", pid=None, pid_identity=None, **state):
        run_dir = os.path.join(self.state_home, "gdd", "runs", date, name)
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
                     "base_is_origin_main: yes", "last_run: none (no attributable runs for this repo and goal)"):
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
        env = {"GDD_AGENT": "claude", "STUB_FIXTURE": route_fixture("claude")}
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
        done = self.stage("implement", "--wait", env={"STUB_FIXTURE": route_fixture("dsh")})
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
        name = "workrepo-0001-implement"
        date = datetime.now().strftime("%Y-%m-%d")
        self.craft_run(name, date=date, pid=os.getpid(), pid_identity=agent_run.identity(os.getpid()))
        refused = self.stage("implement")
        self.assertEqual(refused.returncode, 3)
        self.assertIn("still active", refused.stderr)
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        pid, recorded = dead_pid(self.children)
        history = self.craft_run(name, pid=pid, pid_identity=recorded, started="2000-01-01T00:00:00+00:00")
        history_state = read(os.path.join(history, "state.json"))
        stale = self.craft_run(name, date=date, pid=pid, pid_identity=recorded, started=old)
        write(os.path.join(stale, "lineage.json"), json.dumps({"goal": "0001", "stage": "implement"}))
        original = agent_run.read_state(stale)
        show = self.run_tool(GDD, "status", "--repo", self.repo, "--goal", "0001")
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn("last_run: workrepo-0001-implement stale exit=- dur=-", show.stdout.splitlines())
        done = self.stage("implement", "--wait")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        real_run = os.path.dirname(next(path for path in glob.glob(os.path.join(self.tmp, "**", "run.json"),
                                                                  recursive=True)))
        self.assertEqual(wait_for_json(os.path.join(real_run, "state.json"), bool, time.monotonic() + 5)["state"],
                         "done")
        if real_run == stale:
            stale, = glob.glob(stale + ".prev-*")
        self.assertTrue(os.path.isdir(history))
        self.assertEqual(read(os.path.join(history, "state.json")), history_state)
        self.assertTrue(os.path.isdir(stale))
        saved = agent_run.read_state(stale)
        self.assertEqual({key: saved[key] for key in original}, {**original, "state": "failed", "exit": -1})
        self.assertEqual((saved["state"], saved["exit"], saved["stale_recovered"]), ("failed", -1, True))
        self.assertTrue(finalized(stale, saved))

    def test_custom_launcher_without_pids_keeps_its_recorded_state(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        run_dir = self.craft_run("workrepo-0001-implement", started=old)
        state = json.loads(read(os.path.join(run_dir, "state.json")))
        write(os.path.join(run_dir, "state.json"), json.dumps({k: v for k, v in state.items() if "pid" not in k}))
        refused = self.stage("implement")
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertIn("still active", refused.stderr)


class LineageTests(GddCase):
    def lineage(self, run_dir):
        return json.loads(read(os.path.join(run_dir, "lineage.json")))

    def test_lineage_sidecar_records_goal_and_stage(self):
        done = self.stage("implement", "--wait")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        [run_dir] = self.run_dirs()
        self.assertEqual(self.lineage(run_dir), {"goal": "0001", "stage": "implement"})

    def test_lineage_sidecar_records_inherited_parent_agent(self):
        done = self.stage("implement", "--wait", env={"PASEO_AGENT_ID": "selftest-parent.01"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        [run_dir] = self.run_dirs()
        self.assertEqual(self.lineage(run_dir), {"goal": "0001", "stage": "implement",
                                                 "parentAgentId": "selftest-parent.01"})

    def test_lineage_sidecar_outside_run_root_warns_and_still_records(self):
        outside = os.path.join(self.tmp, "outside", "workrepo-0001-implement")
        launcher = os.path.join(self.tmp, "outside-run.py")
        write(launcher, "\n".join([
            "import os",
            "import sys",
            "",
            f"run_dir = {outside!r}",
            "os.makedirs(run_dir, exist_ok=True)",
            'name = sys.argv[sys.argv.index("--name") + 1]',
            'print("started:", name)',
            'print("run dir:", run_dir)',
        ]) + "\n")
        dispatched = self.stage("implement", env={"GDD_LAUNCHER": launcher})
        self.assertEqual(dispatched.returncode, 0, dispatched.stdout + dispatched.stderr)
        self.assertIn("lineage sidecar not written", dispatched.stderr)
        self.assertEqual([(r["stage"], r["next_action"]) for r in self.ledger()],
                         [("implement", "implement")])
        self.assertEqual(self.run_dirs(), [])
        self.assertFalse(os.path.exists(os.path.join(outside, "lineage.json")))

    def test_lineage_payload_bounds_match_the_observer(self):
        import gdd

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(gdd.lineage_payload(" 0001 ", " simplify "), {"goal": "0001", "stage": "simplify"})
            for goal in ("", "x" * 257):
                with self.assertRaises(ValueError):
                    gdd.lineage_payload(goal, "simplify")
            # 128 astral codepoints are 256 UTF-16 units: exactly the observer's bound.
            self.assertEqual(gdd.lineage_payload("\U0001F600" * 128, "simplify")["goal"], "\U0001F600" * 128)
            # 256 codepoints but 257 UTF-16 units: the observer's TypeScript .length rejects it.
            with self.assertRaises(ValueError):
                gdd.lineage_payload("x" * 255 + "\U0001F600", "simplify")

    def test_lineage_dir_must_be_the_canonical_run_dir(self):
        import gdd

        root = os.path.join(self.tmp, "runs")
        name = "workrepo-0001-implement"
        good = os.path.join(root, "2024-02-29", name)
        os.makedirs(good)
        self.assertTrue(os.path.samefile(gdd.resolve_lineage_dir(root, name, good), good))
        outside = os.path.join(self.tmp, "outside", name)
        for label, run_dir in (
            ("missing date level", os.path.join(root, name)),
            ("different run name", os.path.join(root, "2024-02-29", "other-run")),
            ("non-date level", os.path.join(root, "2024-2-9", name)),
            ("outside the root", outside),
            ("deeper than <date>/<name>", os.path.join(good, "nested")),
            ("missing directory", os.path.join(root, "2024-02-30", name)),
        ):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    gdd.resolve_lineage_dir(root, name, run_dir)
        self.assertFalse(os.path.exists(outside))


class LastRunAttributionTests(GddCase):
    """LIVE `last_run:` is attributed by exact goal lineage, cwd and start instant."""

    def show(self, *, repo=True, env=None):
        command = [DELIVERY, "show", "--goal", "0001",
                   "--state-file", os.path.join(self.state_home, "gdd", "ledger.tsv"),
                   "--task-root", os.path.join(self.state_home, "gdd", "tasks"),
                   "--run-root", os.path.join(self.state_home, "gdd", "runs")]
        if repo:
            command += ["--repo", self.repo if repo is True else repo]
        done = self.run_tool(*command, env=env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done

    def last_run_line(self, done):
        lines = [line for line in done.stdout.splitlines() if line.startswith("last_run:")]
        self.assertEqual(len(lines), 1, done.stdout)
        return lines[0]

    def attribute_run(self, name, *, date="2026-03-01", goal="0001", stage="implement",
                      started="2026-03-01T00:00:00+00:00", state="done", exit_code=0,
                      cwd=None, recorded_name=None, lineage="default", **extra):
        run_dir = os.path.join(self.state_home, "gdd", "runs", date, name)
        payload = {"name": name if recorded_name is None else recorded_name,
                   "agent": "omp", "state": state, "exit": exit_code,
                   "cwd": self.repo if cwd is None else cwd, "started": started,
                   "ended": None, "duration_s": 60}
        payload.update(extra)
        write(os.path.join(run_dir, "state.json"), json.dumps(payload))
        if lineage == "default":
            lineage = {"goal": goal, "stage": stage}
        if lineage is not None:
            write(os.path.join(run_dir, "lineage.json"),
                  lineage if isinstance(lineage, str) else json.dumps(lineage))
        return run_dir

    def test_last_run_uses_the_exact_goal_not_a_name_substring(self):
        self.attribute_run("workrepo-0001-implement", date="2026-03-01")
        self.attribute_run("workrepo-00010-implement", date="2026-03-02", goal="00010",
                           started="2026-03-02T00:00:00+00:00")
        self.assertEqual(self.last_run_line(self.show()),
                         "last_run: workrepo-0001-implement done exit=0 dur=60")

    def test_last_run_does_not_fall_back_to_a_similar_goal(self):
        self.attribute_run("workrepo-00010-implement", goal="00010")
        self.assertEqual(self.last_run_line(self.show()),
                         "last_run: none (no attributable runs for this repo and goal)")

    def test_last_run_skips_another_worktree(self):
        other = os.path.join(self.tmp, "other-worktree")
        os.makedirs(other)
        self.attribute_run("workrepo-0001-implement", date="2026-03-01")
        self.attribute_run("workrepo-0001-review", date="2026-03-02", stage="review",
                           started="2026-03-02T00:00:00+00:00", cwd=other)
        self.assertEqual(self.last_run_line(self.show()),
                         "last_run: workrepo-0001-implement done exit=0 dur=60")

    def test_last_run_orders_by_started_instant_not_state_mtime(self):
        older = self.attribute_run("workrepo-0001-implement", date="2026-03-01",
                                   started="2026-03-01T00:00:00+00:00")
        newer = self.attribute_run("workrepo-0001-review", date="2026-03-02", stage="review",
                                   started="2026-03-02T00:00:00+00:00")
        os.utime(os.path.join(older, "state.json"), (2_000_000_000, 2_000_000_000))
        os.utime(os.path.join(newer, "state.json"), (1_000_000_000, 1_000_000_000))
        self.assertEqual(self.last_run_line(self.show()),
                         "last_run: workrepo-0001-review done exit=0 dur=60")

    def test_last_run_breaks_a_start_tie_by_date_then_name(self):
        started = "2026-03-01T00:00:00+00:00"
        self.attribute_run("workrepo-0001-implement", date="2026-03-01", started=started)
        self.attribute_run("workrepo-0001-review", date="2026-03-01", stage="review", started=started)
        self.assertEqual(self.last_run_line(self.show()),
                         "last_run: workrepo-0001-review done exit=0 dur=60")
        self.attribute_run("workrepo-0001-implement", date="2026-03-02", started=started,
                           exit_code=7)
        self.assertEqual(self.last_run_line(self.show()),
                         "last_run: workrepo-0001-implement done exit=7 dur=60")

    def test_last_run_skips_malformed_and_archived_records(self):
        self.attribute_run("workrepo-0001-implement", date="2026-03-01")
        baseline = "last_run: workrepo-0001-implement done exit=0 dur=60"
        cases = [
            ("malformed-lineage", self.attribute_run("workrepo-0001-bad-lineage",
                                                      date="2026-03-02", lineage="{")),
            ("non-object-lineage", self.attribute_run("workrepo-0001-list-lineage",
                                                       date="2026-03-02", lineage="[1]")),
            ("other-goal-lineage", self.attribute_run("workrepo-0001-other-goal",
                                                       date="2026-03-02", goal="0002")),
            ("non-agent-stage-lineage", self.attribute_run("workrepo-0001-other-stage",
                                                            date="2026-03-02", stage="merge")),
            ("missing-lineage", self.attribute_run("workrepo-0001-no-lineage",
                                                    date="2026-03-02", lineage=None)),
            ("mismatched-state-name", self.attribute_run("workrepo-0001-name-mismatch",
                                                          date="2026-03-02",
                                                          recorded_name="elsewhere")),
            ("missing-state-name", self.attribute_run("workrepo-0001-no-name",
                                                       date="2026-03-02", recorded_name="")),
            ("naive-started", self.attribute_run("workrepo-0001-naive-time",
                                                  date="2026-03-02", started="2026-03-02T00:00:00")),
            ("malformed-started", self.attribute_run("workrepo-0001-bad-time",
                                                      date="2026-03-02", started="not-a-time")),
            ("missing-started", self.attribute_run("workrepo-0001-no-time",
                                                    date="2026-03-02", started=None)),
            ("mismatched-cwd", self.attribute_run("workrepo-0001-bad-cwd", date="2026-03-02",
                                                   cwd=os.path.join(self.tmp, "elsewhere"))),
            ("archived", self.attribute_run("workrepo-0001-archive.prev-1234",
                                             date="2026-03-02")),
        ]
        malformed_state = os.path.join(self.state_home, "gdd", "runs", "2026-03-02",
                                       "workrepo-0001-bad-state")
        write(os.path.join(malformed_state, "state.json"), "{")
        cases.append(("malformed-state", malformed_state))
        for label, run_dir in cases:
            with self.subTest(label=label):
                self.assertEqual(self.last_run_line(self.show()), baseline)
            remove_tree(run_dir)

    def test_last_run_reports_observed_state_and_maps_others_to_unknown(self):
        pid, recorded = dead_pid(self.children)
        cases = [
            ("done", "done", 0, {}),
            ("failed", "failed", 1, {}),
            ("killed", "killed", 143, {}),
            ("running", "running", None, {}),
            ("weird", "unknown", 0, {}),
            ("running-stale", "stale", None, {"pid": pid, "pid_identity": recorded}),
        ]
        for index, (label, expected, code, extra) in enumerate(cases):
            name = f"workrepo-0001-{label}"
            self.attribute_run(name, started=f"2026-03-0{index + 1}T00:00:00+00:00",
                               state="running" if label == "running-stale" else label,
                               exit_code=code, **extra)
            shown = "-" if code is None else code
            self.assertEqual(self.last_run_line(self.show()),
                             f"last_run: {name} {expected} exit={shown} dur=60")

    def test_last_run_none_and_unknown_lines(self):
        self.assertEqual(self.last_run_line(self.show()),
                         "last_run: none (no attributable runs for this repo and goal)")
        missing = os.path.join(self.tmp, "missing-repo")
        self.assertEqual(self.last_run_line(self.show(repo=missing)),
                         "last_run: unknown (repo path unavailable)")
        self.assertEqual(self.last_run_line(self.show(repo=False)),
                         "last_run: unknown (repo path unavailable)")

    def test_last_run_line_reaches_status_and_state_md(self):
        setup = self.run_tool(GDD, "setup", "--repo", self.repo, "--goal", "0001")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        self.attribute_run("workrepo-0001-implement", date="2026-03-01")
        line = self.last_run_line(self.show())
        self.assertEqual(line, "last_run: workrepo-0001-implement done exit=0 dur=60")
        state_md = os.path.join(self.state_home, "gdd", "tasks",
                                datetime.now().strftime("%Y-%m-%d"), "workrepo-0001", "state.md")
        self.assertIn(line, read(state_md).splitlines())
        status = self.run_tool(GDD, "status", "--repo", self.repo, "--goal", "0001")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn(line, status.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
