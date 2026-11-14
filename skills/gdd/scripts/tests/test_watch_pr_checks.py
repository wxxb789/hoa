#!/usr/bin/env python3
"""Tests for watch-pr-checks.py, driven by a scripted `gh` on PATH.

The watcher's whole job is a state machine over `gh pr checks` output — pending,
no-checks-yet, infra-sized fail, real fail, settled-but-not-CLEAN, head moved — and
none of it can be exercised against a live PR on demand. The scripted `gh` replays
canned check tables from a directory and records every invocation, so each branch
is asserted here instead of by hand.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
WATCHER = SCRIPTS / "watch-pr-checks.py"
IS_WINDOWS = os.name == "nt"
BASE_ENV = {
    "WATCH_POLL_SECONDS": "0.2",
    "WATCH_RERUN_WAIT_SECONDS": "0.2",
    "WATCH_FAST_FAIL_SECONDS": "60",
}

GH_STUB = '''\
#!/usr/bin/env python3
"""Scripted `gh`: replays checks.<n>.txt / view.<n>.txt, records every call."""
import os
import pathlib
import sys

state = pathlib.Path(os.environ["STUB_GH_DIR"])
args = sys.argv[1:]


def next_index(name):
    counter = state / f"{name}.count"
    index = int(counter.read_text(encoding="utf-8") or "0") if counter.exists() else 0
    counter.write_text(str(index + 1), encoding="utf-8")
    return index


def scripted(prefix, index):
    candidate = state / f"{prefix}.{index}.txt"
    if candidate.exists():
        return candidate
    files = sorted(state.glob(f"{prefix}.*.txt"))
    return files[-1] if files else None


with open(state / "calls.log", "a", encoding="utf-8") as handle:
    handle.write(" ".join(args) + "\\n")

if args[:2] == ["pr", "checks"]:
    path = scripted("checks", next_index("checks"))
    if path is None:
        print("no checks reported on the 'main' branch", file=sys.stderr)
        sys.exit(1)
    body = path.read_text(encoding="utf-8")
    if body.startswith("!"):
        print(body[1:].strip(), file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(body)
    sys.exit(0)

if args[:2] == ["pr", "view"]:
    print(scripted("view", next_index("view")).read_text(encoding="utf-8").strip())
    sys.exit(0)

if args[:2] == ["run", "rerun"]:
    sys.exit(0)

print(f"stub gh: unsupported invocation {args}", file=sys.stderr)
sys.exit(2)
'''

PASS_ROW = "test\tpass\t1m0s\thttps://github.com/o/r/actions/runs/11/job/1\n"
PENDING_ROW = "test\tpending\t0\thttps://github.com/o/r/actions/runs/11/job/1\n"


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="watch-pr."))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.state = self.tmp / "gh-state"
        self.state.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        stub = self.bin / "gh.py"
        stub.write_text(GH_STUB, encoding="utf-8")
        if IS_WINDOWS:
            (self.bin / "gh.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" "{stub}" %*\r\n', encoding="utf-8"
            )
        else:
            executable = self.bin / "gh"
            executable.write_text(GH_STUB, encoding="utf-8")
            executable.chmod(0o755)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for args in (
            ["init", "-q"],
            ["-c", "user.email=t@example.invalid", "-c", "user.name=t",
             "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "seed"],
        ):
            done = subprocess.run(
                ["git", "-C", str(self.repo), *args], capture_output=True, text=True
            )
            self.assertEqual(done.returncode, 0, done.stderr)
        self.head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        self.log = self.tmp / "watch.log"

    def script(self, checks, views):
        for index, body in enumerate(checks):
            (self.state / f"checks.{index}.txt").write_text(body, encoding="utf-8")
        for index, body in enumerate(views):
            (self.state / f"view.{index}.txt").write_text(body, encoding="utf-8")

    def gh_bin(self):
        return self.bin / ("gh.cmd" if IS_WINDOWS else "gh")

    def watch(self, pull_request="7", max_reruns="2", max_polls="40", env=None):
        """The watcher's four positionals: PR, max_reruns, max_polls, logfile."""
        environment = dict(os.environ)
        environment.update(BASE_ENV)
        environment["STUB_GH_DIR"] = str(self.state)
        environment["GH_BIN"] = str(self.gh_bin())
        environment.update(env or {})
        return subprocess.run(
            [
                sys.executable,
                str(WATCHER),
                str(pull_request),
                str(max_reruns),
                str(max_polls),
                str(self.log),
            ],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=environment,
            timeout=120,
        )

    def calls(self):
        try:
            return (self.state / "calls.log").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

    def log_text(self):
        try:
            return self.log.read_text(encoding="utf-8")
        except OSError:
            return ""

    def test_pending_then_green(self):
        self.script([PENDING_ROW, PASS_ROW], [f"MERGEABLE CLEAN {self.head}"])
        done = self.watch()
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn("CI green", self.log_text())
        self.assertIn("poll 2", self.log_text())
        checks = [call for call in self.calls() if call.startswith("pr checks")]
        self.assertEqual(len(checks), 2, self.calls())

    def test_an_empty_check_list_is_never_a_pass(self):
        self.script(
            ["!no checks reported on the 'main' branch", PASS_ROW],
            [f"MERGEABLE CLEAN {self.head}"],
        )
        done = self.watch("7")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn("no checks registered yet", self.log_text())
        self.assertIn("CI green", self.log_text())

    def test_an_infra_sized_fail_is_rerun_once(self):
        failing = "build\tfail\t32s\thttps://github.com/o/r/actions/runs/12345/job/9\n"
        self.script([failing, PASS_ROW], [f"MERGEABLE CLEAN {self.head}"])
        done = self.watch("7")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn("infra-looking fail: build (32s)", self.log_text())
        self.assertIn("run rerun 12345 --failed", self.calls())
        self.assertIn("run rerun 12345 --failed", self.log_text())

    def test_a_real_fail_is_not_rerun(self):
        failing = "build\tfail\t5m0s\thttps://github.com/o/r/actions/runs/12345/job/9\n"
        self.script([failing], [f"MERGEABLE CLEAN {self.head}"])
        done = self.watch("7")
        self.assertEqual(done.returncode, 1, done.stderr + done.stdout)
        self.assertIn("real fail: build (5m0s)", self.log_text())
        self.assertIn("CI failed after 0 infra rerun(s)", self.log_text())
        self.assertEqual([call for call in self.calls() if call.startswith("run rerun")], [])

    def test_the_rerun_budget_is_bounded(self):
        failing = "build\tfail\t30s\thttps://github.com/o/r/actions/runs/99/job/9\n"
        self.script([failing], [f"MERGEABLE CLEAN {self.head}"])
        done = self.watch(max_reruns="1")
        self.assertEqual(done.returncode, 1, done.stderr + done.stdout)
        self.assertEqual(len([call for call in self.calls() if call.startswith("run rerun")]), 1)
        self.assertIn("real fail: build", self.log_text())

    def test_a_settled_but_not_clean_pr_keeps_waiting(self):
        self.script(
            [PASS_ROW, PASS_ROW],
            [f"MERGEABLE BEHIND {self.head}", f"MERGEABLE CLEAN {self.head}"],
        )
        done = self.watch("7")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn("merge state not CLEAN yet", self.log_text())
        self.assertIn("CI green", self.log_text())

    def test_a_moved_head_stops_the_watch(self):
        self.script([PASS_ROW], ["MERGEABLE CLEAN deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"])
        done = self.watch("7")
        self.assertEqual(done.returncode, 2, done.stderr + done.stdout)
        self.assertIn("head moved", self.log_text())

    def test_a_pending_pr_hits_the_poll_budget(self):
        self.script([PENDING_ROW], [f"MERGEABLE CLEAN {self.head}"])
        done = self.watch(max_polls="2")
        self.assertEqual(done.returncode, 2, done.stderr + done.stdout)
        self.assertIn("still pending after 2 polls", self.log_text())
        self.assertEqual(len([call for call in self.calls() if call.startswith("pr checks")]), 2)

    def test_usage_and_environment_errors_exit_three(self):
        done = subprocess.run(
            [sys.executable, str(WATCHER)], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(done.returncode, 3)
        self.assertIn("usage:", done.stderr)
        done = self.watch(env={"GH_BIN": str(self.tmp / "no-such-gh")})
        self.assertEqual(done.returncode, 3)
        self.assertIn("gh not found", done.stderr)
        done = self.watch(max_reruns="later")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("must be integers", done.stderr)

    def test_an_unreadable_duration_is_logged_and_treated_as_infra_sized(self):
        failing = "build\tfail\t-\thttps://github.com/o/r/actions/runs/7/job/9\n"
        self.script([failing, PASS_ROW], [f"MERGEABLE CLEAN {self.head}"])
        done = self.watch("7")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn("unreadable duration '-'", self.log_text())


class DurationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_watcher()

    def test_durations_match_the_reference_script(self):
        cases = {
            "1m5s": (65, True),
            "32s": (32, True),
            "5m45s": (345, True),
            "5m": (300, True),
            "": (0, False),
            "-": (0, False),
            # Hours are read as the reference script reads them: minutes and
            # seconds only, so '1h2m3s' is 2m3s. The raw duration is in the log.
            "1h2m3s": (123, True),
        }
        for text, expected in cases.items():
            with self.subTest(duration=text):
                self.assertEqual(self.module.rerun_seconds(text), expected)


def load_watcher():
    """The watcher as a module, without leaving bytecode in the skill directory."""
    import types

    module = types.ModuleType("gdd_watch_pr_checks")
    module.__file__ = str(WATCHER)
    exec(compile(WATCHER.read_bytes(), str(WATCHER), "exec"), module.__dict__)
    return module


if __name__ == "__main__":
    unittest.main(verbosity=2)
