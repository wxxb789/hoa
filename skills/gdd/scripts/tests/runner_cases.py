"""Stub runner test setup shared with the route integration suites."""

import glob
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(os.path.dirname(HERE), "agent_run.py")
STUB = os.path.join(HERE, "stub_agent.py")
RESULT_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(HERE)), "references", "stage-result.schema.json")
STAGE_RESULT = {"stage": "implement", "verdict": "DONE", "summary": "done", "changed_files": [], "gates": [],
                "findings": [], "unmet_criteria": []}
IS_WINDOWS = os.name == "nt"
sys.path.insert(0, os.path.dirname(RUNNER))
import agent_run
import gdd_process
from gdd_test_support import check_locks, cleanup_child, finalized, remove_tree, route_fixture, stop_headless, wait_for_json

PROMPT = "Do the task.\nReply with the word done.\n"
REPORT = "## Findings\nnothing material"


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def fold_fixture(route, case):
    acc = agent_run.new_acc()
    with open(route_fixture(route.name, case), "rb") as stream:
        for line in stream:
            agent_run.fold_line(route, acc, line)
    return acc


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agent-run-")
        self.addCleanup(remove_tree, self.tmp)
        self.addCleanup(check_locks, self.tmp)
        self.addCleanup(lambda: stop_headless(self.root))
        self.children = []
        self.addCleanup(cleanup_child, self.children)
        self.root = os.path.join(self.tmp, "runs")
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(self.work)
        self.record = os.path.join(self.tmp, "record.json")
        self.prompt = os.path.join(self.tmp, "prompt.md")
        write(self.prompt, PROMPT)
        drop = ("GDD_", "STUB_", "DSH_", "OMP_")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
        self.env.update(GDD_RUN_ROOT=self.root, XDG_CONFIG_HOME=os.path.join(self.tmp, "config"),
                        GDD_RUN_DETACH="windows" if IS_WINDOWS else "setsid",
                        **{f"{agent.upper()}_BIN": STUB for agent in agent_run.discover_routes()}, STUB_RECORD=self.record,
                        PYTHONDONTWRITEBYTECODE="1")

    def cli(self, *args, env=None):
        return gdd_process.run([sys.executable, "-B", RUNNER, *args], capture_output=True, encoding="utf-8",
                              env={**self.env, **(env or {})}, cwd=self.work, timeout=90)

    def start(self, name, agent="omp", fixture="ok", *args, env=None, expect=0):
        self.record = os.path.join(self.tmp, f"record-{uuid.uuid4().hex}.json")
        env = {"STUB_FIXTURE": route_fixture(agent, fixture),
               "STUB_RECORD": self.record, **(env or {})}
        proc = self.cli("start", "--name", name, "--prompt", self.prompt, "--cwd", self.work, "--agent", agent,
                        *args, env=env)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return proc

    def run_dir(self, name):
        return agent_run.newest_first(glob.glob(os.path.join(self.root, "*", name)))[0]

    def state(self, name):
        return wait_for_json(Path(self.run_dir(name)) / "state.json", bool, time.monotonic() + 5)

    def finished(self, name, seconds=30.0):
        run_dir = Path(self.run_dir(name))
        return wait_for_json(run_dir / "state.json", lambda s: finalized(run_dir, s), time.monotonic() + seconds)

    def recorded(self):
        return wait_for_json(self.record, bool, time.monotonic() + 10)

    def assert_native_schema(self, agent, flag, expected, report_event, *, offset, options=()):
        events = [json.loads(line) for line in read(route_fixture(agent)).splitlines()
                  if line.strip() and not line.startswith("#")]
        events.insert(len(events) - offset, report_event)
        path = os.path.join(self.tmp, "report.ndjson")
        write(path, "".join(json.dumps(event) + "\n" for event in events))
        self.start("native-schema", agent, "ok", "--schema", RESULT_SCHEMA, *options, env={"STUB_FIXTURE": path})
        argv = self.recorded()["argv"]
        carried = argv[argv.index(flag) + 1]
        self.assertEqual(json.loads(carried) if isinstance(expected, dict) else carried, expected)
        state = self.finished("native-schema")
        self.assertEqual((state["state"], state["result"]), ("done", "valid"), state)
        run_dir = Path(self.run_dir("native-schema"))
        self.assertEqual(json.loads(read(run_dir / "result.json")), STAGE_RESULT)
        self.assertEqual(read(run_dir / "answer.md"), f"{REPORT}\n\n{json.dumps(STAGE_RESULT, separators=(',', ':'))}")
        return argv
