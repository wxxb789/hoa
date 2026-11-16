#!/usr/bin/env python3
"""Tests for scripts/run_all_tests.py: discovery, planning, settling and isolation.

Run: python scripts/test_run_all_tests.py
Everything runs against synthetic trees under .tmp-artifacts/test-run-tests/ plus one
read-only plan of the real repository: no test executes a real repository suite.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / ".tmp-artifacts" / "test-run-tests"
spec = importlib.util.spec_from_file_location("run_all_tests", ROOT / "scripts" / "run_all_tests.py")
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner  # dataclass field resolution needs the module registered
spec.loader.exec_module(runner)

PASS_SUITE = '''import unittest


class Passes(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
'''

FAIL_SUITE = '''import unittest


class Fails(unittest.TestCase):
    def test_nope(self):
        self.assertTrue(False, "fails on purpose")


if __name__ == "__main__":
    unittest.main()
'''

ZERO_TEST_SUITE = '''import unittest


class Nothing(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main()
'''

HANG_SUITE = '''import os
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
with open(os.environ["PID_FILE"], "w", encoding="utf-8") as handle:
    handle.write(f"{os.getpid()} {child.pid}\\n")
time.sleep(120)
'''

ENV_SUITE = '''import json
import os

with open(os.environ["DUMP_FILE"], "w", encoding="utf-8") as handle:
    json.dump(dict(os.environ), handle)
'''

# A unittest module whose only test is skipped: unittest still prints `Ran 1 test` and exits 0,
# so collection is positive while nothing executed.
SKIP_SUITE = '''import unittest


class Skipped(unittest.TestCase):
    @unittest.skip("optional capability absent on this host")
    def test_runs_nowhere(self):
        self.fail("a skipped check must never execute")


if __name__ == "__main__":
    unittest.main()
'''

# The leader exits on SIGTERM, and the child it leaves behind ignores SIGTERM while holding nothing
# the runner could sweep (empty environment, cwd `/`) — only group liveness can stop it.  The pid
# file is written after the child reports readiness so SIGTERM cannot arrive before its handler is
# installed, which would make the fixture discriminate nothing.
STUBBORN_SUITE = '''import os
import signal
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, os.environ["CHILD_FILE"], os.environ["READY"]],
                         env={"READY": os.environ["READY"]}, cwd="/")
while not os.path.exists(os.environ["READY"]):
    time.sleep(0.01)
with open(os.environ["PID_FILE"], "w", encoding="utf-8") as handle:
    handle.write(f"{os.getpid()} {child.pid}\\n")
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
while True:
    time.sleep(1)
'''

STUBBORN_CHILD = '''import os
import signal
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(sys.argv[1], "w", encoding="utf-8").close()
while True:
    time.sleep(1)
'''

# A worker that left the suite's process group (`start_new_session`, the way both launcher adapters
# start theirs) and polls the suite's task-local scratch.  It records `beat.gone` if that tree
# disappears while it is alive, and counts its heartbeats so a stopped worker is distinguishable
# from a silent one.
DETACHED_WORKER = '''import os
import sys
import time

sentinel, beat = sys.argv[1], sys.argv[2]
count = 0
while True:
    count += 1
    with open(beat, "w", encoding="utf-8") as handle:
        handle.write(str(count))
    if not os.path.exists(sentinel):
        with open(beat + ".gone", "w", encoding="utf-8") as handle:
            handle.write("scratch-gone")
        break
    time.sleep(0.05)
'''

# The suite that starts `DETACHED_WORKER`; `WORKER_CWD_SCRATCH` moves the worker's cwd into the
# suite's own TMPDIR and `WORKER_SANITIZED` empties its environment, so the cwd it was started in is
# the only tie to the suite (the probe a `read_bytes()` on the `/proc/<pid>/cwd` symlink could never
# see).
DETACHED_SUITE = '''import os
import subprocess
import sys
import time

sentinel = os.path.join(os.environ["TMPDIR"], "sentinel")
open(sentinel, "w", encoding="utf-8").close()
options = {}
if os.environ.get("WORKER_CWD_SCRATCH"):
    options["cwd"] = os.environ["TMPDIR"]
if os.environ.get("WORKER_SANITIZED"):
    options["env"] = {}
child = subprocess.Popen([sys.executable, os.environ["WORKER_FILE"], sentinel, os.environ["BEAT"]],
                         start_new_session=True, **options)
with open(os.environ["PID_FILE"], "w", encoding="utf-8") as handle:
    handle.write(f"{child.pid}\\n")
time.sleep(120)
'''

# A same-group child that SIGKILLs the suite leader once the suite reports readiness, then stays.
# Its environment is emptied and its cwd is `/`, so no scratch sweep can match it: only the group
# the leader was recorded in finds it (and only after the leader it outlives is gone).
SIGNAL_KILLER = '''import os
import signal
import sys
import time

ready, target = sys.argv[1], sys.argv[2]
while not os.path.exists(ready):
    time.sleep(0.01)
os.kill(int(target), signal.SIGKILL)
while True:
    time.sleep(1)
'''

SIGNALLED_SUITE = '''import os
import subprocess
import sys
import time

ready = os.environ["READY"]
child = subprocess.Popen([sys.executable, os.environ["KILLER_FILE"], ready, str(os.getpid())],
                         env={}, cwd="/")
with open(os.environ["PID_FILE"], "w", encoding="utf-8") as handle:
    handle.write(f"{child.pid}\\n")
open(ready, "w", encoding="utf-8").close()
time.sleep(120)
'''

# One command of the exit-then-hang fixture: it starts a worker in its *own* process group whose
# environment is emptied and whose cwd is `/` (nothing a scratch sweep could match), writes the
# worker's pid, and exits 0 — leaving the worker behind for the teardown to find while the group is
# still provable.
CLEAN_EXIT_WORKER = '''import subprocess
import sys

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], env={}, cwd="/")
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(f"{child.pid}\\n")
'''


def synthetic_tree(patterns: list[str], prune: list[str], floor: list[str], suites: str) -> Path:
    """Create a throwaway root with a manifest and return it."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tree-", dir=ARTIFACTS))
    manifest = [
        "schema = 1",
        "[discovery]",
        f"patterns = {json.dumps(patterns)}",
        f"prune = {json.dumps(prune)}",
        f"floor = {json.dumps(floor)}",
        "",
        suites,
    ]
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "test_manifest.toml").write_text("\n".join(manifest), encoding="utf-8")
    return root


def run_synthetic(root: Path, scratch: Path, report: Path, *extra: str) -> tuple[int, str, dict]:
    """Run the discoverer in-process against a synthetic root; return code, stdout, report."""
    buffer = io.StringIO()
    # 20s, not 5s: these suites start real interpreters and the machine may be loaded; only
    # an injected hang suite is meant to hit the timeout.
    argv = ["--root", str(root), "--event", "local", "--timeout", "20",
            "--scratch", str(scratch), "--report", str(report), *extra]
    with contextlib.redirect_stdout(buffer):
        code = runner.main(argv)
    return code, buffer.getvalue(), json.loads(report.read_text(encoding="utf-8"))


def states_of(payload: dict) -> dict:
    """The report's per-suite entries keyed by id."""
    return {entry["id"]: entry for entry in payload["suites"]}


def write_suite(root: Path, relative: str, body: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return relative


def process_running(pid: int) -> bool:
    """Whether `pid` is still a *running* process, answered from `/proc` where there is one.

    A zombie is not running: it is terminated, and the runner is not necessarily its parent.  The
    runner reads liveness the same way (`_proc_state`), so a test that stopped a process the way the
    runner reports it must agree with the runner's own rule.  Without `/proc` the probe is
    `kill(pid, 0)`, which cannot tell a zombie from a live process.
    """
    if runner.PROC_ROOT.is_dir():
        state = runner._proc_state(pid)
        return state is not None and state != "Z"
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


SHIM_TOOL_FIXTURE = '''import json
import os
import pathlib
import sys

state = os.environ.get("MISE_STATE_DIR")
if not state or not pathlib.Path(state).is_dir():
    print(f"shim cannot run: MISE_STATE_DIR={state!r}", file=sys.stderr)
    raise SystemExit(1)
pathlib.Path(os.environ["SHIM_STATE_FILE"]).write_text(json.dumps(state), encoding="utf-8")
'''


class SuiteEnvironmentTests(unittest.TestCase):
    """The suite environment: the manifest allowlist plus pinned interpreter and shim state."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)
        self.document = runner.load_manifest(ROOT / runner.MANIFEST_RELATIVE)
        self.scratch = runner.scratch_root_for()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.report = ARTIFACTS / "report.json"

    @contextlib.contextmanager
    def operator(self, home: Path | None = None, **variables):
        """Temporarily set the runner's own HOME/MISE_* as an operator would."""
        saved = {name: os.environ.get(name) for name in ("HOME", *runner.SHIM_STATE_DEFAULTS)}
        for name in runner.SHIM_STATE_DEFAULTS:
            os.environ.pop(name, None)
        if home is not None:
            os.environ["HOME"] = str(home)
        for name, value in variables.items():
            os.environ[name] = value
        try:
            yield
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_shim_state_directories_are_pinned_from_the_operator_home(self):
        home = ARTIFACTS / "operator-home"
        (home / ".local" / "state" / "mise").mkdir(parents=True)
        (home / ".local" / "share" / "mise").mkdir(parents=True)
        with self.operator(home=home):
            environment = runner.base_environment(self.document, sys.executable)
        self.assertEqual(environment["MISE_STATE_DIR"], str(home / ".local" / "state" / "mise"))
        self.assertEqual(environment["MISE_DATA_DIR"], str(home / ".local" / "share" / "mise"))
        for name in runner.SHIM_STATE_DEFAULTS:
            self.assertTrue(Path(environment[name]).is_absolute(), environment[name])

    def test_operator_shim_settings_win_and_are_made_absolute(self):
        home = ARTIFACTS / "operator-home"
        home.mkdir(parents=True, exist_ok=True)
        with self.operator(home=home, MISE_STATE_DIR="./relative-state"):
            environment = runner.base_environment(self.document, sys.executable)
        self.assertEqual(environment["MISE_STATE_DIR"], str(Path("./relative-state").resolve()))
        self.assertNotIn("MISE_DATA_DIR", environment)

    def test_suites_gain_nothing_outside_the_declared_allowlist(self):
        home = ARTIFACTS / "operator-home"
        (home / ".local" / "state" / "mise").mkdir(parents=True, exist_ok=True)
        with self.operator(home=home, MISE_VERBOSE="1", GDD_LAUNCHER="must-not-leak",
                           OMP_RUN_ROOT="must-not-leak"):
            environment = runner.base_environment(self.document, sys.executable)
        allowed = set((self.document.get("env") or {}).get("passthrough") or [])
        # Frozen rather than read from `runner.SHIM_STATE_DEFAULTS`: deriving the permitted
        # set from the constant it polices is how a name appended there starts reaching
        # every suite unnoticed.
        allowed |= {"PATH", "NO_COLOR", "MISE_STATE_DIR", "MISE_DATA_DIR"}
        self.assertLessEqual(set(environment), allowed)
        self.assertNotIn("MISE_VERBOSE", environment)

    def test_the_passthrough_allowlist_is_pinned_by_name(self):
        """The reviewed allowlist is an oracle in its own right, not a mirror of the data."""
        self.assertEqual(tuple(self.document["env"]["passthrough"]), (
            "PATH", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TERM", "TZ",
            "CI", "GITHUB_ACTIONS", "GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA",
            "GITHUB_HEAD_REF", "GITHUB_BASE_REF",
        ))

    def test_the_pinned_shim_state_is_exactly_two_named_directories(self):
        """What may reach every suite as operator state is pinned by name, not by count."""
        self.assertEqual(set(runner.SHIM_STATE_DEFAULTS), {"MISE_STATE_DIR", "MISE_DATA_DIR"})

    @unittest.skipIf(os.name != "posix", "a POSIX virtual environment's interpreter is a symlink")
    def test_a_virtual_environment_keeps_its_identity_on_path(self):
        """PATH pins the interpreter that was selected, not the base one its symlink points at.

        A POSIX virtual environment is `<venv>/bin/python3 -> <base>/python3` beside `pyvenv.cfg`,
        and the interpreter decides it is inside that environment from the path it was started
        with.  Resolving the symlink therefore hands a suite's own `python3` — and any
        `#!/usr/bin/env python3` shebang — the base interpreter, silently discarding the
        environment the repository dependencies are installed in (§4.3).
        """
        venv = ARTIFACTS / "venv"
        created = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                                 capture_output=True, text=True)
        if created.returncode != 0:
            self.skipTest(f"cannot create a virtual environment here: {created.stderr.strip()}")
        python = venv / "bin" / "python3"
        self.assertTrue(python.is_symlink(), f"{python} is not the symlinked shape this pins")
        self.assertNotEqual(str(python.parent), os.path.dirname(os.path.realpath(python)),
                            "the fixture does not exercise symlink resolution")
        environment = runner.base_environment(self.document, str(python))
        self.assertEqual(environment["PATH"].split(os.pathsep)[0], str(venv / "bin"))
        found = shutil.which("python3", path=environment["PATH"])
        self.assertEqual(found, str(python))
        probe = subprocess.run([found, "-c", "import sys; print(sys.prefix)"],
                               capture_output=True, text=True, env=environment)
        self.assertEqual(probe.stdout.strip(), str(venv), probe.stderr)

    def test_a_shim_style_tool_finds_its_state_under_a_task_local_home(self):
        """End to end: the suite process runs the shim, not the operator's HOME."""
        home = ARTIFACTS / "operator-home"
        (home / ".local" / "state" / "mise").mkdir(parents=True, exist_ok=True)
        state_file = ARTIFACTS / "shim-state.json"
        root = synthetic_tree(
            patterns=["scripts/test_*.py"], prune=[], floor=[],
            suites="\n".join([
                "[[suite]]",
                'id = "canned:shim-tool"',
                'command = [["{python}", "scripts/tests/shim_tool.py"]]',
                f'env = {{ SHIM_STATE_FILE = "{state_file}" }}',
                "",
            ]),
        )
        write_suite(root, "scripts/tests/shim_tool.py", SHIM_TOOL_FIXTURE)
        with self.operator(home=home):
            code, output, payload = run_synthetic(root, self.scratch, self.report,
                                                  "--suite", "canned:shim-tool")
        self.assertEqual(payload["shim_state"]["MISE_STATE_DIR"],
                         str(home / ".local" / "state" / "mise"))
        self.assertEqual(states_of(payload)["canned:shim-tool"]["state"], "PASS", output)
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8")),
                         str(home / ".local" / "state" / "mise"))
        self.assertEqual(code, 0)


class DiscoveryTests(unittest.TestCase):
    """Patterns, pruning and the reviewed floor."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)

    def test_glob_star_never_crosses_a_slash(self):
        regex = runner._glob_regex("skills/*/scripts/test_*.py")
        self.assertTrue(regex.match("skills/gdd/scripts/test_thing.py"))
        self.assertIsNone(regex.match("skills/gdd/nested/scripts/test_thing.py"))

    def test_double_star_crosses_directories(self):
        self.assertTrue(runner._glob_regex("evals/**/test_*.py").match("evals/a/b/test_x.py"))

    def test_prune_matches_a_name_at_any_depth_or_a_path_prefix(self):
        self.assertTrue(runner._pruned("skills/a/scripts/node_modules/test_x.py", ["node_modules"]))
        self.assertTrue(runner._pruned("paseo-plugins/gdd-run-observer/server/tests/x.ts", ["paseo-plugins"]))
        self.assertFalse(runner._pruned("skills/a/scripts/test_x.py", ["paseo-plugins"]))

    def test_discovery_collects_named_entry_points_only(self):
        root = synthetic_tree(
            patterns=["skills/*/scripts/tests/test*.py", "skills/*/scripts/tests/test*.sh",
                      "skills/*/scripts/tests/run-*-selftest.sh"],
            prune=["node_modules", "fixtures"],
            floor=[],
            suites="",
        )
        write_suite(root, "skills/a/scripts/tests/test-one.py", PASS_SUITE)
        write_suite(root, "skills/a/scripts/tests/test-two.sh", "#!/usr/bin/env bash\nexit 0\n")
        write_suite(root, "skills/a/scripts/tests/run-a-selftest.sh", "#!/usr/bin/env bash\nexit 0\n")
        write_suite(root, "skills/a/scripts/tests/helper.py", "print('not a suite')\n")
        write_suite(root, "skills/a/scripts/tests/judge_cases.py", "print('online evaluation')\n")
        write_suite(root, "skills/a/scripts/tests/payload.sh", "#!/usr/bin/env bash\nexit 0\n")
        write_suite(root, "skills/a/scripts/tests/fixtures/test_fixture.py", PASS_SUITE)
        write_suite(root, "skills/a/scripts/tests/node_modules/test_installed.py", PASS_SUITE)
        found = runner.discover(root, runner.load_manifest(root / "scripts/test_manifest.toml")
                                ["discovery"]["patterns"],
                                ["node_modules", "fixtures"])
        self.assertEqual(found, sorted([
            "skills/a/scripts/tests/run-a-selftest.sh",
            "skills/a/scripts/tests/test-one.py",
            "skills/a/scripts/tests/test-two.sh",
        ]))

    def test_unmet_floor_is_a_plan_error(self):
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=["scripts/test_gone.py"],
                              suites="")
        write_suite(root, "scripts/test_present.py", PASS_SUITE)
        plan = runner.build_plan(root, runner.load_manifest(root / "scripts/test_manifest.toml"),
                                 event="local")
        self.assertEqual(plan.floor_missing, ["scripts/test_gone.py"])
        self.assertTrue(any("floor unmet" in problem for problem in plan.problems))

    def test_empty_discovery_is_a_plan_error(self):
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[], suites="")
        plan = runner.build_plan(root, runner.load_manifest(root / "scripts/test_manifest.toml"),
                                 event="local")
        self.assertEqual(plan.discovered, [])
        self.assertTrue(any("produced no suites" in problem for problem in plan.problems))

    def test_unpinned_discovery_is_reported_not_rejected(self):
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="")
        write_suite(root, "scripts/test_new.py", PASS_SUITE)
        plan = runner.build_plan(root, runner.load_manifest(root / "scripts/test_manifest.toml"),
                                 event="local")
        self.assertEqual(plan.problems, [])
        self.assertEqual(plan.unpinned, ["scripts/test_new.py"])
        self.assertEqual([suite.id for suite in plan.scheduled], ["scripts/test_new.py"])

    def test_a_filtered_plan_is_not_a_floor_check(self):
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[],
                              floor=["scripts/test_gone.py"], suites="")
        write_suite(root, "scripts/test_present.py", PASS_SUITE)
        document = runner.load_manifest(root / "scripts/test_manifest.toml")
        full = runner.build_plan(root, document, event="local")
        self.assertEqual(full.floor_missing, ["scripts/test_gone.py"])
        self.assertTrue(any("floor unmet" in problem for problem in full.problems))
        filtered = runner.build_plan(root, document, event="local",
                                     only=["scripts/test_present.py"])
        self.assertEqual(filtered.problems, [])
        self.assertEqual(filtered.floor_missing, [])
        self.assertEqual([suite.id for suite in filtered.scheduled],
                         ["scripts/test_present.py"])


class ManifestValidationTests(unittest.TestCase):
    """Manifest contradictions surface as plan problems, never as silent skips."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)

    def plan(self, suites: str) -> runner.Plan:
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[], suites=suites)
        write_suite(root, "scripts/test_real.py", PASS_SUITE)
        write_suite(root, "scripts/parent.py", "print('parent-counter: 3/3 ok')\n")
        document = runner.load_manifest(root / "scripts/test_manifest.toml")
        return runner.build_plan(root, document, event="local")

    def test_counter_without_patterns_is_rejected(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_real.py"\nassertion = "counter"\n')
        self.assertTrue(any("needs count_regexes" in problem for problem in plan.problems))

    def test_counter_pattern_without_a_passed_group_is_rejected(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_real.py"\nassertion = "counter"\n'
                         'count_regexes = ["^x: (\\\\d+)$"]\n')
        self.assertTrue(any("passed" in problem for problem in plan.problems))

    def test_condition_without_skip_reason_is_rejected(self):
        plan = self.plan('[[suite]]\nid = "gate:x"\ncommand = [["true"]]\n'
                         'condition = "pull_request"\n')
        self.assertTrue(any("skip_reason" in problem for problem in plan.problems))

    def test_stale_refinement_is_rejected(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_missing.py"\nassertion = "exit"\n')
        self.assertTrue(any("matches no discovered suite" in problem for problem in plan.problems))

    def test_declared_command_naming_a_missing_entry_point_is_rejected(self):
        plan = self.plan('[[suite]]\nid = "declared:missing"\n'
                         'command = [["{python}", "scripts/not_there.py"]]\n')
        self.assertTrue(any("entry point does not exist: scripts/not_there.py" in problem
                            for problem in plan.problems))

    def test_duplicate_suite_id_is_rejected(self):
        plan = self.plan(
            '[[suite]]\nid = "gate:x"\ncommand = [["true"]]\n\n'
            '[[suite]]\nid = "gate:x"\ncommand = [["true"]]\n'
        )
        self.assertTrue(any("duplicate suite id" in problem for problem in plan.problems))

    def test_covered_by_must_name_a_scheduled_suite(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_real.py"\n'
                         'covered_by = "scripts/nope.py"\n')
        self.assertTrue(any("covered_by names no known suite" in problem for problem in plan.problems))

    def test_covered_by_requires_the_parent_to_name_the_child(self):
        plan = self.plan(
            '[[suite]]\nid = "parent"\ncommand = [["{python}", "scripts/parent.py"]]\npath = "scripts/parent.py"\n'
            'assertion = "counter"\ncount_regexes = ["^parent-counter: (?P<passed>\\\\d+)/(?P<total>\\\\d+) ok$"]\n\n'
            '[[suite]]\npath = "scripts/test_real.py"\ncovered_by = "parent"\n'
        )
        self.assertTrue(any("never names" in problem for problem in plan.problems))

    def test_declared_entry_may_take_its_id_from_its_path(self):
        plan = self.plan('[[suite]]\npath = "scripts/test_real.py"\n'
                         'command = [["{python}", "-B", "-m", "unittest", "scripts.test_real"]]\n')
        self.assertEqual(plan.problems, [])
        self.assertEqual([suite.id for suite in plan.scheduled], ["scripts/test_real.py"])

    def test_selection_by_covered_child_points_at_its_parent(self):
        root = synthetic_tree(
            patterns=["scripts/test_*.py"], prune=[], floor=[],
            suites='[[suite]]\nid = "parent"\npath = "scripts/parent.py"\n'
                   'command = [["{python}", "scripts/parent.py"]]\n\n'
                   '[[suite]]\npath = "scripts/test_real.py"\ncovered_by = "parent"\n',
        )
        write_suite(root, "scripts/parent.py", "# runs scripts/test_real.py\n")
        write_suite(root, "scripts/test_real.py", PASS_SUITE)
        document = runner.load_manifest(root / "scripts/test_manifest.toml")
        plan = runner.build_plan(root, document, event="local", only=["scripts/test_real.py"])
        self.assertTrue(any("covered by parent" in problem for problem in plan.problems))
        self.assertEqual(plan.scheduled, [])


class RealTreePlanTests(unittest.TestCase):
    """The plan of the real repository: the reconciliation this PR has to keep honest."""

    @classmethod
    def setUpClass(cls):
        cls.document = runner.load_manifest(ROOT / runner.MANIFEST_RELATIVE)
        cls.plan = runner.build_plan(ROOT, cls.document, event="local")
        cls.ids = {suite.id for suite in cls.plan.scheduled}

    def test_every_static_gate_is_still_scheduled(self):
        for suite_id in ("gate:frontmatter", "gate:contract-graph", "gate:index-drift",
                         "gate:version-check", "gate:vendor-shared"):
            self.assertIn(suite_id, self.ids)
        self.assertTrue({"gate:version-bump", "gate:changelog", "gate:version-merge"}
                        <= {suite.id for suite in self.plan.skipped})

    def test_the_plan_has_no_problems_and_no_filtered_floor(self):
        self.assertEqual(self.plan.problems, [])
        self.assertEqual(self.plan.floor_missing, [])
        # This repository pins every discovered path, so it has no unpinned discovery to
        # name here; an unpinned one is scheduled and reported, never a problem (owner
        # decision, 2026-11-14), which DiscoveryTests pins on a synthetic tree.

    def test_discovery_finds_the_suites_the_old_globs_missed(self):
        self.assertIn("skills/ghc-search/scripts/test_ghc_search.py", self.ids)
        self.assertIn("skills/delegated-work-acceptance/scripts/tests/test_worktree_scope.py", self.ids)
        self.assertIn("skills/gdd/scripts/tests/test_paseo_run_python.py", self.ids)

    def test_dispatch_guards_are_accounted_through_their_parent(self):
        self.assertNotIn("skills/gdd/scripts/tests/test-dispatch-guards.py", self.ids)
        covered = {child.id: child for child in self.plan.covered}
        self.assertEqual(
            covered["skills/gdd/scripts/tests/test-dispatch-guards.py"].covered_by,
            "skills/gdd/scripts/tests/run-gdd-selftest.sh",
        )

    def test_paseo_package_is_declared_with_its_own_cwd_and_commands(self):
        suite = next(item for item in self.plan.scheduled if item.id == "pkg:paseo-run-observer")
        self.assertEqual(suite.cwd, ROOT / "paseo-plugins" / "gdd-run-observer")
        self.assertEqual(suite.provision, (("npm", "ci"),))
        self.assertEqual([argv[1] for argv in suite.commands], ["run", "test"])
        self.assertEqual(suite.assertion, "counter")

    def test_bun_packages_keep_their_separate_commands(self):
        for suite_id, directory in (
            ("pkg:cdp-shared", "scripts/shared"),
            ("pkg:teams-cdp", "skills/teams-cdp/scripts"),
            ("pkg:m365-copilot-cdp", "skills/m365-copilot-cdp/scripts"),
        ):
            suite = next(item for item in self.plan.scheduled if item.id == suite_id)
            self.assertEqual(suite.cwd, ROOT / directory)
            self.assertEqual(suite.provision, (("bun", "install", "--frozen-lockfile"),))
            self.assertEqual(suite.commands, (("bun", "run", "check"), ("bun", "test")))

    def test_unittest_suites_keep_their_declared_module_invocation(self):
        for path, module in (
            ("scripts/test_skill_config.py", "scripts.test_skill_config"),
            ("scripts/test_install_host_skills.py", "scripts.test_install_host_skills"),
            ("scripts/test_check_changelog.py", "scripts.test_check_changelog"),
            ("scripts/test_check_frontmatter.py", "scripts.test_check_frontmatter"),
            ("evals/test_judge_trigger_evals.py", "evals.test_judge_trigger_evals"),
            ("evals/test_validate_skill_method_cases.py", "evals.test_validate_skill_method_cases"),
        ):
            suite = next(item for item in self.plan.scheduled if item.id == path)
            self.assertEqual(suite.commands, ((sys.executable, "-B", "-m", "unittest", module),))

    def test_direct_python_suites_pin_interpreter_cwd_and_pythonpath(self):
        suite = next(item for item in self.plan.scheduled if item.id == "scripts/test_version.py")
        self.assertEqual(suite.commands, ((sys.executable, "-B", "scripts/test_version.py"),))
        self.assertEqual(suite.cwd, ROOT)
        environment = runner.base_environment(self.document, sys.executable)
        # The interpreter's own directory, never the directory its symlink resolves to: what that
        # costs is measured in `SuiteEnvironmentTests` against a real virtual environment.
        prefix = Path(environment["PATH"].split(os.pathsep)[0])
        self.assertEqual(prefix, Path(sys.executable).absolute().parent)

    def test_shell_suites_run_under_bash(self):
        suite = next(item for item in self.plan.scheduled
                     if item.id == "skills/gdd/scripts/tests/test-omp-run-stale.sh")
        self.assertEqual(suite.runtime, "bash")
        self.assertEqual(suite.commands, (("bash", "skills/gdd/scripts/tests/test-omp-run-stale.sh"),))

    def test_custom_assertion_suites_have_positive_count_adapters(self):
        for path, marker in (
            ("skills/hermes-models/scripts/tests/test-routing-inventory.py", "^routing-inventory:"),
            ("skills/hermes-models/scripts/tests/test-provider-metadata.py", "^provider-metadata:"),
            ("skills/gdd/scripts/tests/test-dispatch-guards.py", "^dispatch-guards:"),
            ("skills/gdd/scripts/tests/test-omp-run-stale.sh", "^stale-test:"),
        ):
            suite = next(item for item in self.plan.scheduled + self.plan.covered if item.id == path)
            self.assertEqual(suite.assertion, "counter")
            self.assertTrue(suite.count_regexes[0].startswith(marker), suite.count_regexes)

    def test_python_launcher_suites_declare_their_detached_workers(self):
        """Both launcher suites name the resource their own teardown stops (§4 item 4).

        The runner sweeps a timed-out suite's scratch whatever the declaration says (the suite that
        lost its cleanup callbacks is exactly the one that cannot clean up), so the declaration is
        what keeps the resource, its mechanism and its owning teardown visible in the manifest.
        """
        for path, adapter, teardown in (
            ("skills/gdd/scripts/tests/test_omp_run_python.py", "omp-run.py", "kill_hard"),
            ("skills/gdd/scripts/tests/test_paseo_run_python.py", "paseo-run.py", "stop_monitors"),
        ):
            suite = next(item for item in self.plan.scheduled if item.id == path)
            declaration = suite.detached or ""
            self.assertIn(adapter, declaration, path)
            self.assertIn("start_new_session", declaration, path)
            self.assertIn(teardown, declaration, path)

    def test_pull_request_gates_skip_outside_a_pull_request(self):
        skipped = {suite.id: suite for suite in self.plan.skipped}
        self.assertEqual(set(skipped), {"gate:version-bump", "gate:changelog", "gate:version-merge"})
        for suite in skipped.values():
            self.assertEqual(suite.condition, "pull_request")
            self.assertTrue(suite.skip_reason)

    def test_pull_request_event_schedules_those_gates(self):
        plan = runner.build_plan(ROOT, self.document, event="pull_request")
        ids = {suite.id for suite in plan.scheduled}
        self.assertIn("gate:version-bump", ids)
        self.assertIn("gate:changelog", ids)
        self.assertIn("gate:version-merge", ids)
        self.assertEqual(plan.skipped, [])

    def test_filtered_plan_skips_the_floor_check_and_keeps_children(self):
        plan = runner.build_plan(ROOT, self.document, event="local",
                                 only=["skills/gdd/scripts/tests/run-gdd-selftest.sh"])
        self.assertEqual(plan.problems, [])
        self.assertEqual(len(plan.scheduled), 1)
        self.assertEqual([child.id for child in plan.covered],
                         ["skills/gdd/scripts/tests/test-dispatch-guards.py"])


class SettleTests(unittest.TestCase):
    """Terminal states and the anti-false-green rules of §4.5/§4.6."""

    def suite(self, **overrides) -> runner.Suite:
        values = dict(id="s", origin="discovered", commands=(("cmd",),), cwd=ROOT,
                      runtime="python")
        values.update(overrides)
        return runner.Suite(**values)

    def test_unittest_suite_with_zero_collected_tests_is_error(self):
        state, counts, reason = runner.settle(
            self.suite(assertion="unittest"), exit_code=0, timed_out=False,
            output="Ran 0 tests in 0.000s\n\nOK\n")
        self.assertEqual(state, "ERROR")
        self.assertEqual(counts["executed"], 0)
        self.assertIn("Ran 0 tests", reason)

    def test_unittest_suite_without_a_summary_is_error(self):
        state, _, _ = runner.settle(self.suite(assertion="unittest"), exit_code=0,
                                    timed_out=False, output="ImportError: no module named thing\n")
        self.assertEqual(state, "ERROR")

    def test_unittest_summary_settles_pass_and_fail(self):
        output = "Ran 3 tests in 0.002s\n\nOK\n"
        self.assertEqual(runner.settle(self.suite(assertion="unittest"), exit_code=0,
                                       timed_out=False, output=output)[0], "PASS")
        self.assertEqual(runner.settle(self.suite(assertion="unittest"), exit_code=1,
                                       timed_out=False, output=output)[0], "FAIL")

    def test_unittest_skips_are_recorded(self):
        state, counts, _ = runner.settle(
            self.suite(assertion="unittest"), exit_code=0, timed_out=False,
            output="Ran 4 tests in 0.002s\n\nOK (skipped=1)\n")
        self.assertEqual((state, counts), ("PASS", {"executed": 4, "skipped": 1}))

    def test_unittest_suite_that_skips_every_test_is_error(self):
        """`Ran N tests` is collection, not execution: an all-skipped run executed nothing."""
        state, counts, reason = runner.settle(
            self.suite(assertion="unittest"), exit_code=0, timed_out=False,
            output="Ran 2 tests in 0.002s\n\nOK (skipped=2)\n")
        self.assertEqual(state, "ERROR")
        self.assertEqual(counts, {"executed": 2, "skipped": 2})
        self.assertIn("all skipped", reason)

    def test_counter_suite_with_zero_checks_is_error(self):
        suite = self.suite(assertion="counter", count_regexes=(r"^x: (?P<passed>\d+)/(?P<total>\d+) ok$",))
        state, counts, _ = runner.settle(suite, exit_code=0, timed_out=False, output="x: 0/0 ok\n")
        self.assertEqual(state, "ERROR")
        self.assertEqual(counts, {"passed": 0, "executed": 0, "total": 0})

    def test_counter_suite_without_its_line_is_error(self):
        suite = self.suite(assertion="counter", count_regexes=(r"^x: (?P<passed>\d+) ok$",))
        self.assertEqual(runner.settle(suite, exit_code=0, timed_out=False, output="nothing\n")[0],
                         "ERROR")

    def test_counter_line_that_hides_checks_is_error(self):
        suite = self.suite(assertion="counter",
                           count_regexes=(r"^x: (?P<passed>\d+)/(?P<total>\d+) ok$",))
        self.assertEqual(runner.settle(suite, exit_code=0, timed_out=False, output="x: 2/3 ok\n")[0],
                         "ERROR")

    def test_counter_accepts_declared_subcase_skips(self):
        suite = self.suite(assertion="counter", count_regexes=(
            r"^ *Tests +(?P<passed>\d+) passed(?: \| (?P<skipped>\d+) skipped)? \((?P<total>\d+)\)$",
        ))
        state, counts, _ = runner.settle(suite, exit_code=0, timed_out=False,
                                         output=" Test Files  3 passed | 1 skipped (4)\n"
                                                "      Tests  47 passed | 1 skipped (48)\n")
        self.assertEqual(state, "PASS")
        self.assertEqual(counts, {"passed": 47, "executed": 48, "total": 48, "skipped": 1})

    def test_counter_failure_settles_fail(self):
        suite = self.suite(assertion="counter", count_regexes=(r"^x: (?P<passed>\d+) ok$",))
        self.assertEqual(runner.settle(suite, exit_code=1, timed_out=False, output="x: 2 ok\n")[0],
                         "FAIL")

    def test_require_regex_miss_on_a_passing_exit_is_error(self):
        suite = self.suite(assertion="exit", require_regex=r"^PASS: ")
        self.assertEqual(runner.settle(suite, exit_code=0, timed_out=False, output="done\n")[0],
                         "ERROR")
        self.assertEqual(runner.settle(suite, exit_code=0, timed_out=False,
                                       output="PASS: validated\n")[0], "PASS")

    def covered_child(self, parent_log: str, *, assertion: str = "counter",
                      patterns: tuple[str, ...] = (r"^child: (?P<passed>\d+)/(?P<total>\d+) ok$",),
                      parent_state: str = "PASS") -> runner.Outcome:
        """Settle a covered child whose parent's whole log is written for one test."""
        directory = Path(tempfile.mkdtemp(prefix="covered-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        log = directory / "parent.log"
        log.write_text(parent_log, encoding="utf-8")
        child = self.suite(id="child", assertion=assertion, count_regexes=patterns)
        parent = self.suite(id="parent")
        parent_outcome = runner.Outcome(suite_id=parent.id, state=parent_state, log=str(log))
        return runner.settle_covered(child, parent, parent_outcome, log)

    def test_covered_counter_child_with_zero_checks_is_error(self):
        outcome = self.covered_child("child: 0/0 ok\n")
        self.assertEqual(outcome.state, "ERROR")
        self.assertIn("zero executed checks", outcome.reason)
        self.assertEqual(outcome.counts, {"passed": 0, "executed": 0, "total": 0})

    def test_covered_counter_child_with_a_disagreeing_line_is_error(self):
        """The consistency rule of a scheduled counter suite applies through `covered_by` too.

        A PASS parent with the real dispatch-guard pattern (`dispatch-guards: 1/100 ok`) used to
        settle this child PASS although `settle` rejects that identical summary as ERROR, so
        contradictory evidence went green by not being scheduled.
        """
        outcome = self.covered_child("dispatch-guards: 1/100 ok\n", patterns=(
            r"^dispatch-guards: (?P<passed>\d+)/(?P<total>\d+) ok$",
        ))
        self.assertEqual(outcome.state, "ERROR")
        self.assertEqual(outcome.counts, {"passed": 1, "executed": 100, "total": 100})
        self.assertIn("disagrees", outcome.reason)

    def test_covered_unittest_child_needs_a_summary_in_the_parent_log(self):
        outcome = self.covered_child("the parent ran the child without a summary\n",
                                     assertion="unittest", patterns=())
        self.assertEqual(outcome.state, "ERROR")
        self.assertIn("no unittest summary", outcome.reason)
        outcome = self.covered_child("Ran 4 tests in 0.002s\n\nOK\n",
                                     assertion="unittest", patterns=())
        self.assertEqual((outcome.state, outcome.counts), ("PASS", {"executed": 4}))

    def test_covered_unittest_child_that_skips_every_test_is_error(self):
        outcome = self.covered_child("Ran 2 tests in 0.002s\n\nOK (skipped=2)\n",
                                     assertion="unittest", patterns=())
        self.assertEqual(outcome.state, "ERROR")
        self.assertIn("all skipped", outcome.reason)

    def test_covered_child_of_a_skipped_or_failed_parent_is_never_pass(self):
        skipped = self.covered_child("", parent_state="SKIP")
        self.assertEqual(skipped.state, "SKIP")
        self.assertIn("parent parent skipped", skipped.reason)
        failed = self.covered_child("", parent_state="FAIL")
        self.assertEqual(failed.state, "ERROR")
        self.assertIn("parent parent settled FAIL", failed.reason)

    def test_timeout_signal_and_spawn_failures(self):
        self.assertEqual(runner.settle(self.suite(), exit_code=None, timed_out=True, output="")[0],
                         "TIMEOUT")
        self.assertEqual(runner.settle(self.suite(), exit_code=-9, timed_out=False, output="")[0],
                         "ERROR")
        self.assertEqual(runner.settle(self.suite(), exit_code=None, timed_out=False, output="")[0],
                         "ERROR")
        self.assertEqual(runner.settle(self.suite(), exit_code=0, timed_out=False, output="",
                                       provisioned=False)[0], "ERROR")

    def test_timeout_reason_reports_the_teardown_it_observed(self):
        """The record says what teardown established, not what it hoped for."""
        suite = self.suite()
        nothing = runner.settle(suite, exit_code=0, timed_out=True, output="",
                                teardown=runner.Teardown())
        self.assertEqual(nothing[0], "TIMEOUT")
        self.assertIn("no processes remained to be terminated", nothing[2])
        observed = runner.settle(suite, exit_code=0, timed_out=True, output="",
                                 teardown=runner.Teardown(clauses=("process group",)))
        self.assertIn("process group terminated", observed[2])
        unobserved = runner.settle(suite, exit_code=0, timed_out=True, output="")
        self.assertIn("teardown was not observed", unobserved[2])
        survivor = runner.settle(suite, exit_code=0, timed_out=True, output="",
                                 teardown=runner.Teardown(survivors=(4242,)))
        self.assertIn("4242", survivor[2])
        self.assertIn("survived SIGKILL", survivor[2])
        unverified = runner.settle(suite, exit_code=0, timed_out=True, output="",
                                   teardown=runner.Teardown(unverified=(runner.NO_ENUMERATION,)))
        self.assertIn("unverified", unverified[2])


class TeardownRecordTests(unittest.TestCase):
    """`Teardown` says what it established, and nothing it did not."""

    def test_a_surviving_detached_pid_does_not_suppress_a_terminated_group(self):
        """Clauses describe their own targets: a detached survivor is not the group."""
        described = runner.Teardown(clauses=("process group",), survivors=(4242,)).describe()
        self.assertIn("process group terminated", described)
        self.assertIn("4242 survived SIGKILL", described)

    def test_unverified_notes_are_deduplicated_as_units(self):
        """Merging keeps each note whole instead of joining first and deduplicating a string."""
        merged = (runner.Teardown(unverified=("a", "b"))
                  .merge(runner.Teardown(unverified=("b", "c"))))
        self.assertEqual(merged.unverified, ("a", "b", "c"))

    def test_unverified_notes_alone_mean_the_record_is_not_verified(self):
        """`verified` is derived from the notes: none, verified; any, not verified."""
        self.assertTrue(runner.Teardown().verified)
        self.assertFalse(runner.Teardown(unverified=("a limit this run cannot observe",)).verified)


class TeardownOwnershipTests(unittest.TestCase):
    """Every signal must be justified by identity this run recorded itself (module docstring)."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)
        self.log_path = ARTIFACTS / "ownership.log"

    def spawn(self, *, code: str = "import time; time.sleep(60)") -> subprocess.Popen:
        """A child that is a session (and process group) leader, and always reaped."""
        process = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def patch(self, target, attribute: str, value) -> None:
        """Set `target.attribute` for this test and restore it afterwards."""
        saved = getattr(target, attribute)
        setattr(target, attribute, value)
        self.addCleanup(setattr, target, attribute, saved)

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX process groups only")
    def test_group_teardown_refuses_a_recycled_group_id(self):
        """A reaped command's number is history; even if it now names a live group, it is not ours.

        Model: the command finished and this run reaped it, and the kernel recycled its number onto
        an unrelated live group — an intercepted `getpgid` answers with one, so the number looks
        live and self-consistent to anything that has only the number.  A bare-number teardown
        signals that group; this one must refuse and report teardown unverified.
        """
        victim = self.spawn()
        command = self.spawn(code="pass")
        command.wait()  # reaped: the run no longer holds the pid, so it no longer owns the group
        real_getpgid = os.getpgid
        self.patch(os, "getpgid",
                   lambda pid: victim.pid if pid == command.pid else real_getpgid(pid))
        attempts: list = []
        self.patch(os, "kill", lambda pid, signum: attempts.append(("kill", pid, signum)))
        self.patch(os, "killpg", lambda group, signum: attempts.append(("killpg", group, signum)))
        with self.log_path.open("ab") as log:
            teardown = runner._terminate_group(command, log)
        self.assertEqual(attempts, [],
                         "the teardown signalled a group it cannot prove is this run's")
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())
        self.assertIsNone(victim.poll(), "the unrelated group's leader was signalled")

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX process groups only")
    def test_group_teardown_reaches_the_group_without_proc(self):
        """The group is signalled through `os.killpg`, so a host without /proc still stops it.

        Model: POSIX with the group API but no `/proc` (macOS).  A teardown that starts from /proc
        enumeration sends nothing there; this one signals the group, and only its final observation
        is limited by the platform.  Delivery is real, so the group really empties.
        """
        victim = self.spawn()
        attempts: list = []
        real_killpg = os.killpg

        def deliver(group: int, signum: int) -> None:
            attempts.append((group, signum))
            real_killpg(group, signum)

        self.patch(os, "killpg", deliver)
        self.patch(runner, "PROC_ROOT", Path("/nonexistent-proc"))
        self.patch(runner, "KILL_GRACE_SECONDS", 0.5)
        with self.log_path.open("ab") as log:
            teardown = runner._terminate_group(victim, log)
        self.assertIn((victim.pid, signal.SIGTERM), attempts,
                      "the group was not signalled through os.killpg without /proc")
        self.assertIsNotNone(victim.poll(), "the signalled group's leader is still running")
        self.assertIn("process group terminated", teardown.describe())

    @unittest.skipUnless(hasattr(os, "waitid") and hasattr(os, "WNOWAIT"),
                         "the observation uses waitid(WNOWAIT)")
    def test_an_observed_exit_leaves_the_pid_reserved_for_the_teardown(self):
        """The exit is observed without reaping, so the ownership proof outlives the command.

        This is what still lets a signal-killed suite be torn down: the command is dead, but its
        pid — and with it the group it leads — stays reserved until this run reaps it itself.
        """
        exited = self.spawn(code="import sys; sys.exit(3)")
        self.assertEqual(runner._observe_exit(exited, 5), 3)
        self.assertIsNone(exited.returncode, "the observation reaped the command")
        self.assertEqual(os.getpgid(exited.pid), exited.pid,
                         "the pid stopped naming the group the teardown must still prove")
        killed = self.spawn()
        os.kill(killed.pid, signal.SIGKILL)
        self.assertEqual(runner._observe_exit(killed, 5), -signal.SIGKILL)
        self.assertIsNone(killed.returncode, "the observation reaped the signalled command")

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the anchor is the waitid(WNOWAIT) probe")
    def test_an_externally_reaped_child_is_no_longer_this_runs_to_signal(self):
        """A reaper outside `Popen` leaves `returncode` at None; the kernel probe is the anchor.

        Model: another waiter reaped the command (`os.waitpid`), and the pid's number was recycled
        onto a group that still looks self-consistent to `getpgid`.  The cached field — the old
        proof — cannot see the external reap; `waitid(WEXITED | WNOWAIT | WNOHANG)` raises once the
        child is gone, so the teardown must refuse the number and report teardown unverified.
        """
        process = self.spawn(code="pass")
        os.waitpid(process.pid, 0)  # reaped outside Popen: the cached returncode stays None
        self.assertIsNone(process.returncode, "the external reap must stay invisible to Popen")
        real_getpgid = os.getpgid
        self.patch(os, "getpgid",
                   lambda pid: process.pid if pid == process.pid else real_getpgid(pid))
        self.assertIsNone(runner._owned_group(process),
                          "a pid the kernel no longer holds as this run's child is not an anchor")
        attempts: list = []
        self.patch(os, "kill", lambda pid, signum: attempts.append(("kill", pid, signum)))
        self.patch(os, "killpg", lambda group, signum: attempts.append(("killpg", group, signum)))
        with self.log_path.open("ab") as log:
            teardown = runner._terminate_group(process, log)
        self.assertEqual(attempts, [],
                         "the teardown signalled a group the kernel no longer reserves for it")
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the non-reaping observation is waitid(WNOWAIT)")
    def test_an_externally_reaped_child_is_a_lost_exit_not_a_status(self):
        """A child reaped elsewhere is not waitable: the exit observation must say so.

        `waitid` raises `ChildProcessError` once the kernel no longer holds the child; returning
        that as a status (or letting it escape) would settle a suite on evidence that does not
        exist.  The observation reports the loss for the caller to settle as an error.
        """
        process = self.spawn(code="pass")
        os.waitpid(process.pid, 0)
        with self.assertRaises(runner._WaitabilityLost):
            runner._observe_exit(process, 5)

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX process groups only")
    def test_an_unowned_live_command_is_refused_without_claiming_survivors(self):
        """Nothing was signalled to an unowned live process, so nothing "survived SIGKILL".

        Model: ownership cannot be established (`_owned_group` answers None) while the command is
        still running.  The refusal must not wait out the kill grace on a process nothing stopped,
        and the record must not borrow the survivor wording of a signalled process.
        """
        process = self.spawn(code="import time; time.sleep(60)")
        self.patch(runner, "_owned_group", lambda owned: None)
        self.patch(runner, "KILL_GRACE_SECONDS", 5.0)
        started = time.monotonic()
        with self.log_path.open("ab") as log:
            teardown = runner._terminate_group(process, log)
        self.assertLess(time.monotonic() - started, 2.0,
                        "an unowned command was waited out instead of refused")
        self.assertEqual(teardown.survivors, ())
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())
        self.assertIsNone(process.poll(), "the probe's own child must stay untouched")

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the exit observation must not reap")
    def test_a_clean_exit_whose_group_cannot_be_checked_is_recorded_unverified(self):
        """When the group cannot be checked before the reap, the record must not claim it emptied.

        Model: the ownership proof is gone before the check (a host without `waitid(WNOWAIT)`
        reaps its command inside the exit observation) while the exit itself was observed
        normally; the reap must still happen, and the record must say the check did not.
        """
        process = self.spawn(code="pass")
        self.assertEqual(runner._observe_exit(process, 5), 0)
        self.patch(runner, "_owned_group", lambda owned: None)
        with self.log_path.open("ab") as log:
            teardown = runner._teardown_before_reap(process, log)
        self.assertFalse(teardown.verified)
        self.assertIn("unverified", teardown.describe())
        self.assertIsNotNone(process.poll(), "the command must still be reaped")


class EndToEndTests(unittest.TestCase):
    """One synthetic repository, run through main(): states, isolation, teardown."""

    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, ARTIFACTS, ignore_errors=True)
        self.report = ARTIFACTS / "report.json"
        # Short and outside the checkout, like the operator default -- the runner refuses
        # scratch roots that cannot hold a socket.
        self.scratch = runner.scratch_root_for()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def build(self) -> Path:
        root = synthetic_tree(
            patterns=["scripts/test_*.py", "scripts/tests/test*.py", "scripts/tests/test*.sh"],
            prune=["node_modules", "fixtures"],
            floor=["scripts/test_pass.py", "scripts/tests/test-shell.sh"],
            suites="\n".join([
                "[[suite]]",
                'id = "canned:missing-runtime"',
                'command = [["definitely-not-a-real-runtime-xyz", "run"]]',
                "",
                "[[suite]]",
                'id = "canned:empty-counter"',
                'command = [["{python}", "-c", "print(\'x: 0/0 ok\')"]]',
                'assertion = "counter"',
                'count_regexes = ["^x: (?P<passed>\\\\d+)/(?P<total>\\\\d+) ok$"]',
                "",
                "[[suite]]",
                'path = "scripts/tests/test-counter-child.py"',
                'covered_by = "parent"',
                'assertion = "counter"',
                'count_regexes = ["^child-counter: (?P<passed>\\\\d+)/(?P<total>\\\\d+) ok$"]',
                "",
                "[[suite]]",
                'id = "parent"',
                'path = "scripts/tests/parent.py"',
                'command = [["{python}", "scripts/tests/parent.py"]]',
                'assertion = "counter"',
                'count_regexes = ["^parent-counter: (?P<passed>\\\\d+)/(?P<total>\\\\d+) ok$"]',
                "",
                "[[suite]]",
                'path = "scripts/test_env.py"',
                # PYTHONCOERCECLOCALE=0 so the dump is exactly what the runner sets: under a C
                # locale the interpreter itself would add LC_CTYPE to its own environment
                # (PEP 538), which is a property of CPython, not of the suite's isolation.
                f'env = {{ DUMP_FILE = "{ARTIFACTS / "env-dump.json"}", '
                f'PYTHONCOERCECLOCALE = "0" }}',
                "",
                "[[suite]]",
                'path = "scripts/test_hang.py"',
                f'env = {{ PID_FILE = "{ARTIFACTS / "pids.txt"}" }}',
                "",
            ]),
        )
        write_suite(root, "scripts/test_pass.py", PASS_SUITE)
        write_suite(root, "scripts/test_fail.py", FAIL_SUITE)
        write_suite(root, "scripts/test_zero.py", ZERO_TEST_SUITE)
        write_suite(root, "scripts/test_skipped.py", SKIP_SUITE)
        write_suite(root, "scripts/test_syntax.py", "def broken(:\n    pass\n")
        write_suite(root, "scripts/test_env.py", ENV_SUITE)
        write_suite(root, "scripts/test_hang.py", HANG_SUITE)
        write_suite(root, "scripts/tests/test-shell.sh", "#!/usr/bin/env bash\nexit 0\n")
        write_suite(root, "scripts/tests/test-counter-child.py", "print('never scheduled on its own')\n")
        write_suite(root, "scripts/tests/parent.py",
                    "# executes scripts/tests/test-counter-child.py in production\n"
                    "print('parent-counter: 2/2 ok')\n"
                    "print('child-counter: 3/3 ok')\n")
        return root

    def run_main(self, root: Path, *extra: str) -> tuple[int, str, dict]:
        return run_synthetic(root, self.scratch, self.report, *extra)

    def states(self, payload: dict) -> dict:
        return states_of(payload)

    def test_every_suite_settles_and_the_run_goes_red_for_the_broken_ones(self):
        root = self.build()
        code, output, payload = self.run_main(root)
        states = self.states(payload)
        self.assertEqual(states["scripts/test_pass.py"]["state"], "PASS")
        self.assertEqual(states["scripts/tests/test-shell.sh"]["state"], "PASS")
        self.assertEqual(states["scripts/test_fail.py"]["state"], "FAIL")
        self.assertEqual(states["scripts/test_syntax.py"]["state"], "FAIL")
        self.assertEqual(states["scripts/test_zero.py"]["state"], "ERROR")
        self.assertIn("Ran 0 tests", states["scripts/test_zero.py"]["reason"])
        self.assertEqual(states["scripts/test_skipped.py"]["state"], "ERROR")
        self.assertIn("all skipped", states["scripts/test_skipped.py"]["reason"])
        self.assertEqual(states["canned:missing-runtime"]["state"], "ERROR")
        self.assertEqual(states["canned:empty-counter"]["state"], "ERROR")
        self.assertEqual(states["scripts/test_hang.py"]["state"], "TIMEOUT")
        self.assertEqual(code, 1)
        self.assertIn("failed:", output)

    def test_covered_child_settles_from_the_parent_output(self):
        root = self.build()
        code, _, payload = self.run_main(root, "--suite", "parent")
        states = self.states(payload)
        self.assertEqual(len(payload["suites"]), 2)
        self.assertEqual(states["parent"]["state"], "PASS")
        child = states["scripts/tests/test-counter-child.py"]
        self.assertEqual(child["state"], "PASS")
        self.assertEqual(child["counts"], {"passed": 3, "executed": 3, "total": 3})
        # Unpinned, and selected through its parent: still named in the record's discovery
        # section, and the run is green (owner decision, 2026-11-14).
        self.assertIn("scripts/tests/test-counter-child.py", payload["discovery"]["unpinned"])
        self.assertEqual(code, 0)

    def test_covered_child_without_parent_evidence_is_error(self):
        root = self.build()
        (root / "scripts/tests/parent.py").write_text(
            "# executes scripts/tests/test-counter-child.py in production\n"
            "print('parent-counter: 2/2 ok')\n", encoding="utf-8")
        code, _, payload = self.run_main(root, "--suite", "parent")
        child = self.states(payload)["scripts/tests/test-counter-child.py"]
        self.assertEqual(child["state"], "ERROR")
        self.assertIn("no evidence", child["reason"])
        self.assertEqual(code, 1)

    def test_covered_child_with_zero_checks_is_error(self):
        root = self.build()
        (root / "scripts/tests/parent.py").write_text(
            "# executes scripts/tests/test-counter-child.py in production\n"
            "print('parent-counter: 2/2 ok')\n"
            "print('child-counter: 0/0 ok')\n", encoding="utf-8")
        code, _, payload = self.run_main(root, "--suite", "parent")
        child = self.states(payload)["scripts/tests/test-counter-child.py"]
        self.assertEqual(child["state"], "ERROR")
        self.assertIn("zero executed checks", child["reason"])
        self.assertEqual(code, 1)

    def test_an_untrustworthy_plan_exits_two_and_says_so(self):
        """An empty discovery set or an unmet floor is a red job, not a printed note."""
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[],
                              floor=["scripts/test_gone.py"], suites="")
        code, output, payload = self.run_main(root)
        self.assertEqual(code, 2, output)
        self.assertEqual(payload["exit_code"], 2)
        problems = " ".join(payload["problems"])
        self.assertIn("produced no suites", problems)
        self.assertIn("floor unmet", problems)

    def test_a_condition_skipped_suite_is_recorded_not_dropped(self):
        """A whole-suite SKIP stays in the run record, with its declared reason."""
        root = synthetic_tree(
            patterns=["scripts/test_*.py"], prune=[], floor=[],
            suites="\n".join([
                "[[suite]]",
                'id = "gate:pr-only"',
                'command = [["{python}", "-c", "pass"]]',
                'condition = "pull_request"',
                'skip_reason = "pull-request guard: a push to main has nothing to do"',
                "",
            ]),
        )
        code, output, payload = self.run_main(root)
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["planned"], {"scheduled": 0, "covered": 0,
                                              "condition_skipped": 1})
        self.assertEqual(payload["settled"], 1)
        self.assertEqual((payload["summary"]["PASS"], payload["summary"]["SKIP"]), (0, 1))
        skipped = self.states(payload)["gate:pr-only"]
        self.assertEqual(skipped["state"], "SKIP")
        self.assertEqual(skipped["reason"],
                         "pull-request guard: a push to main has nothing to do")
        code, output, payload = self.run_main(root, "--event", "pull_request")
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["planned"]["condition_skipped"], 0)
        self.assertEqual(payload["summary"]["PASS"], 1)

    def test_suites_run_with_task_local_scratch_and_a_stripped_environment(self):
        root = self.build()
        os.environ["GDD_LAUNCHER"] = "must-not-leak"
        os.environ["OMP_RUN_ROOT"] = "must-not-leak"
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.addCleanup(os.environ.pop, "GDD_LAUNCHER", None)
        self.addCleanup(os.environ.pop, "OMP_RUN_ROOT", None)
        # Controlled, not this host's own setting: the shim pins belong to the exact set
        # asserted below, so they must not depend on what the operator happens to have.
        for name in ("MISE_STATE_DIR", "MISE_DATA_DIR"):
            directory = ARTIFACTS / f"operator-{name.lower()}"
            directory.mkdir(parents=True, exist_ok=True)
            self.addCleanup(os.environ.pop, name, None)
            os.environ[name] = str(directory)
        self.run_main(root, "--suite", "scripts/test_env.py")
        dump = json.loads((ARTIFACTS / "env-dump.json").read_text(encoding="utf-8"))
        scratch = str(self.scratch)
        # The exact set of names, not a subset: the synthetic manifest declares no `[env]`
        # allowlist, so only PATH may come from the operator, and a suite sees the runner's
        # task-local block, the two shim state pins and its own `env` table.  Frozen on
        # purpose: deriving it from the runner would follow the code it exists to police.
        self.assertEqual(set(dump), {
            "PATH", "NO_COLOR", "DUMP_FILE", "PYTHONCOERCECLOCALE",
            "HOME", "TMPDIR", "TMP", "TEMP",
            "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
            "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "GIT_TERMINAL_PROMPT",
            "MISE_STATE_DIR", "MISE_DATA_DIR",
        })
        for name in ("HOME", "TMPDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
                     "XDG_STATE_HOME"):
            self.assertTrue(dump[name].startswith(scratch), f"{name}={dump[name]}")
        self.assertEqual(dump["PYTHONPATH"], str(root))
        self.assertEqual(dump["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertNotIn("GDD_LAUNCHER", dump)
        self.assertNotIn("OMP_RUN_ROOT", dump)
        self.assertEqual(Path(dump["PATH"].split(os.pathsep)[0]),
                         Path(sys.executable).absolute().parent)

    def test_default_scratch_lives_outside_the_checkout(self):
        scratch = runner.scratch_root_for()
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.assertTrue(scratch.is_dir())
        self.assertFalse(scratch.is_relative_to(ROOT), scratch)
        if runner.SHORT_TEMP_ROOT.is_dir():
            self.assertTrue(scratch.is_relative_to(runner.SHORT_TEMP_ROOT), scratch)

    @unittest.skipUnless(runner.SHORT_TEMP_ROOT.is_dir(), "no short temp root on this platform")
    def test_default_scratch_stays_socket_sized_under_a_long_operator_tmpdir(self):
        """A long inherited TMPDIR must not reach the scratch tree (§4 item 4)."""
        long_tmpdir = ARTIFACTS / ("operator-tmpdir-" + "x" * 80)
        long_tmpdir.mkdir(parents=True, exist_ok=True)
        saved = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = str(long_tmpdir)
        try:
            scratch = runner.scratch_root_for()
        finally:
            if saved is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = saved
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.assertFalse(scratch.is_relative_to(long_tmpdir),
                         f"scratch inherited TMPDIR: {scratch}")
        suite_scratch = Path(tempfile.mkdtemp(prefix="skills-gdd-s-", dir=scratch))
        self.addCleanup(shutil.rmtree, suite_scratch, ignore_errors=True)
        plan = runner.build_plan(ROOT, runner.load_manifest(ROOT / runner.MANIFEST_RELATIVE),
                                 event="local")
        self.assertTrue(plan.socket_tail, "no suite declares the socket tree this bound models")
        worst_case = runner.socket_path_length(suite_scratch, plan.socket_tail)
        self.assertIsNotNone(worst_case)
        self.assertLess(worst_case, runner.AF_UNIX_PATH_LIMIT,
                        f"worst-case socket path {worst_case} bytes for {suite_scratch}")

    @unittest.skipIf(os.name != "posix", "AF_UNIX path limits do not apply")
    def test_a_scratch_root_too_long_for_a_socket_errors_before_running(self):
        """The bound is enforced, not assumed: no suite runs under an unusable root."""
        marker = ARTIFACTS / "should-not-exist.txt"
        marker.unlink(missing_ok=True)
        deep = ARTIFACTS / ("deep-" + "d" * 80) / "deeper"
        deep.mkdir(parents=True, exist_ok=True)
        suite = runner.Suite(
            id="scripts/test_marker.py", origin="declared", cwd=ROOT, runtime="python",
            commands=(("{python}", "-c", f"open({str(marker)!r}, 'w').close()"),),
        )
        log_root = ARTIFACTS / "logs"
        log_root.mkdir(parents=True, exist_ok=True)
        outcome = runner.run_suite(suite, root=ROOT, scratch_root=deep, log_root=log_root,
                                   environment=runner.base_environment({}, sys.executable))
        self.assertEqual(outcome.state, "ERROR")
        self.assertIn("AF_UNIX", outcome.reason)
        reported = re.search(r"worst case (\d+) bytes", outcome.reason)
        self.assertIsNotNone(reported, outcome.reason)
        self.assertGreaterEqual(int(reported.group(1)), runner.AF_UNIX_PATH_LIMIT)
        self.assertFalse(marker.exists(), "the suite ran despite an unusable scratch root")
        self.assertEqual([entry.name for entry in deep.iterdir()], [],
                         "the unusable per-suite scratch tree was not cleaned up")

    @unittest.skipUnless(runner.SHORT_TEMP_ROOT.is_dir(), "no short temp root on this platform")
    @unittest.skipIf(os.name != "posix", "AF_UNIX path limits do not apply")
    def test_a_declared_socket_tail_turns_a_usable_root_into_an_error(self):
        """The bound uses the manifest's declared tail, not just the scratch root length."""
        marker = ARTIFACTS / "tail-marker.txt"
        marker.unlink(missing_ok=True)
        plan = runner.build_plan(ROOT, runner.load_manifest(ROOT / runner.MANIFEST_RELATIVE),
                                 event="local")
        self.assertTrue(plan.socket_tail, "no suite declares the socket tree this bound models")
        padded = Path(tempfile.mkdtemp(prefix="hoa-tail-", dir=runner.SHORT_TEMP_ROOT)) / ("p" * 40)
        self.addCleanup(shutil.rmtree, padded.parent, ignore_errors=True)
        padded.mkdir()
        probe = Path(tempfile.mkdtemp(prefix="scripts-test-", dir=padded))
        probe_plain = runner.socket_path_length(probe, "")
        probe_tailed = runner.socket_path_length(probe, plan.socket_tail)
        shutil.rmtree(probe, ignore_errors=True)
        self.assertLess(probe_plain, runner.AF_UNIX_PATH_LIMIT,
                        "the probe root is already too long to control this bound")
        self.assertGreaterEqual(probe_tailed, runner.AF_UNIX_PATH_LIMIT,
                                "the declared tail is too short to model the bound")
        suite = runner.Suite(
            id="scripts/test_marker.py", origin="declared", cwd=ROOT, runtime="python",
            commands=((sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"),),
        )
        log_root = ARTIFACTS / "logs"
        log_root.mkdir(parents=True, exist_ok=True)
        environment = runner.base_environment({}, sys.executable)
        usable = runner.run_suite(suite, root=ROOT, scratch_root=padded, log_root=log_root,
                                  environment=environment)
        self.assertEqual(usable.state, "PASS", usable.reason)
        self.assertTrue(marker.exists(), "the suite did not run under the usable root")
        marker.unlink()
        bounded = runner.run_suite(suite, root=ROOT, scratch_root=padded, log_root=log_root,
                                   environment=environment, socket_tail=plan.socket_tail)
        self.assertEqual(bounded.state, "ERROR")
        self.assertIn("AF_UNIX", bounded.reason)
        self.assertFalse(marker.exists(), "the suite ran although its declared tail cannot fit")
        self.assertEqual([entry.name for entry in padded.iterdir()], [],
                         "the bounded-out per-suite scratch tree was not cleaned up")

    def test_timeout_tears_down_the_whole_process_group(self):
        root = self.build()
        code, _, payload = self.run_main(root, "--suite", "scripts/test_hang.py")
        self.assertEqual(code, 1)
        self.assertEqual(self.states(payload)["scripts/test_hang.py"]["state"], "TIMEOUT")
        pids = [int(value) for value in (ARTIFACTS / "pids.txt").read_text().split()]
        self.assertEqual(len(pids), 2)
        deadline = time.monotonic() + 10
        for pid in pids:
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                for leftover in pids:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(leftover, signal.SIGKILL)
                self.fail(f"pid {pid} survived the suite timeout")

    def assert_stopped(self, pids: list[int], message: str) -> None:
        """Every pid stops running inside the grace window, or the failure names the survivor."""
        deadline = time.monotonic() + 10
        for pid in pids:
            while time.monotonic() < deadline:
                if not process_running(pid):
                    break
                time.sleep(0.1)
            else:
                for leftover in pids:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(leftover, signal.SIGKILL)
                self.fail(f"{message}: pid {pid} is still running")

    def run_abnormal_fixture(self, name: str, source: str, *, env: dict[str, str],
                             timeout: str = "5") -> tuple[dict, list[int]]:
        """Run one synthetic single-suite fixture whose suite exits abnormally, and check teardown.

        `source` runs as `scripts/test_<name>.py`, records the pids it started in
        `<ARTIFACTS>/<name>-pids.txt` (the runner supplies its `PID_FILE`), and dies abnormally
        however the test arranged.  Whatever that abnormal exit is, the teardown owes the run the
        same observable outcome: the scratch tree is deleted, and every pid the fixture recorded is
        stopped.  Returns the suite's result entry and those pids.
        """
        pids_file = ARTIFACTS / f"{name}-pids.txt"
        variables = {"PID_FILE": str(pids_file), **env}
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  f'path = "scripts/test_{name}.py"',
                                  "env = { " + ", ".join(f'{key} = "{value}"'
                                                         for key, value in variables.items())
                                  + " }",
                                  "",
                              ]))
        write_suite(root, f"scripts/test_{name}.py", source)
        code, output, payload = self.run_main(root, "--timeout", timeout)
        self.assertEqual(code, 1, output)
        entry = self.states(payload)[f"scripts/test_{name}.py"]
        pids = [int(value) for value in pids_file.read_text().split()]
        self.assert_stopped(pids, f"a process of the {name} fixture")
        self.assertEqual([item.name for item in self.scratch.iterdir()], [],
                         "the per-suite scratch tree was not cleaned up")
        return entry, pids

    @unittest.skipUnless(hasattr(os, "killpg"), "the escalation is the POSIX group path")
    def test_timeout_escalates_while_a_group_member_ignores_sigterm(self):
        """Escalation follows the group: the leader exiting on SIGTERM must not end it.

        The leader here exits cleanly on SIGTERM while the child it leaves in the *same* group
        ignores it, and that child holds nothing a scratch sweep could match (empty environment,
        cwd `/`), so only group liveness can stop it.  Both rounds are pinned by their outcomes:
        the leader's exit code 0 says SIGTERM reached the group, and the child — which ignores
        SIGTERM by construction — being stopped says the escalation went on to SIGKILL after the
        leader was gone, the break-out the old leader-based loop took.
        """
        write_suite(ARTIFACTS, "stubborn-child.py", STUBBORN_CHILD)
        entry, pids = self.run_abnormal_fixture(
            "stubborn", STUBBORN_SUITE, timeout="3",
            env={"READY": str(ARTIFACTS / "stubborn-ready"),
                 "CHILD_FILE": str(ARTIFACTS / "stubborn-child.py")})
        self.assertEqual(entry["state"], "TIMEOUT")
        self.assertEqual(entry["exit_code"], 0, "the fixture leader did not exit on SIGTERM")
        self.assertEqual(len(pids), 2)
        self.assertIn("process group terminated", entry["reason"])

    @unittest.skipUnless(runner.WAITID_WNOWAIT, "the loss is only visible to waitid(WNOWAIT)")
    def test_a_suite_whose_child_is_not_waitable_settles_error_instead_of_crashing(self):
        """An inherited `SIGCHLD=SIG_IGN` hands the child's exit to the kernel.

        The status is then gone before this run can observe it — the probe raises
        `ChildProcessError` — and nothing can prove the group.  Each affected suite must settle
        ERROR with an unverified teardown, and the run must continue to settle the rest of the
        plan and publish its record instead of taking the whole discoverer down.
        """
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  'id = "canned:pass"',
                                  'command = [["{python}", "-c", "pass"]]',
                                  'assertion = "exit"',
                                  "",
                              ]))
        write_suite(root, "scripts/test_pass.py", PASS_SUITE)
        saved = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        self.addCleanup(signal.signal, signal.SIGCHLD, saved)
        code, output, payload = self.run_main(root)
        states = self.states(payload)
        self.assertEqual(sorted(states), ["canned:pass", "scripts/test_pass.py"])
        for suite_id, entry in states.items():
            self.assertEqual(entry["state"], "ERROR",
                             f"{suite_id}: {entry['state']} ({entry['reason']})")
            self.assertIn("unverified", entry["reason"])
        self.assertEqual(code, 1, output)

    def test_a_command_that_exited_cleanly_is_checked_before_its_reap(self):
        """A clean exit can still leave same-group members; the check must precede the reap.

        Command one starts a worker whose environment is empty and whose cwd is `/` — nothing a
        scratch sweep can match — and exits 0; command two times out.  While command one's own
        process is unreaped its group is provable, so the worker is stopped there, and the later
        timeout's record must not claim a clean teardown over a survivor it never saw.
        """
        pids_file = ARTIFACTS / "clean-exit-pids.txt"
        pids_file.unlink(missing_ok=True)
        root = synthetic_tree(patterns=["scripts/test_*.py"], prune=[], floor=[],
                              suites="\n".join([
                                  "[[suite]]",
                                  'id = "canned:exit-then-hang"',
                                  "command = [",
                                  f'  ["{{python}}", "scripts/exit_worker.py", '
                                  f'{json.dumps(str(pids_file))}],',
                                  '  ["{python}", "-c", "import time; time.sleep(120)"],',
                                  "]",
                                  "",
                              ]))
        write_suite(root, "scripts/exit_worker.py", CLEAN_EXIT_WORKER)
        code, output, payload = self.run_main(root, "--suite", "canned:exit-then-hang",
                                              "--timeout", "4")
        self.assertEqual(code, 1, output)
        entry = self.states(payload)["canned:exit-then-hang"]
        self.assertEqual(entry["state"], "TIMEOUT")
        pids = [int(value) for value in pids_file.read_text().split()]
        self.assertEqual(len(pids), 1)
        self.assert_stopped(pids, "the worker the cleanly exited first command left in its group")
        self.assertIn("process group terminated", entry["reason"])
        self.assertNotIn("unverified", entry["reason"])

    @unittest.skipUnless(runner.PROC_ROOT.is_dir(), "the scratch sweep reads /proc")
    def test_timeout_stops_detached_workers_before_the_scratch_goes(self):
        """A worker that left the suite's group is stopped before the records it polls are deleted.

        The fixture worker does what both launcher adapters do — `start_new_session`, then poll the
        suite's task-local scratch — and records `beat.gone` if that tree disappears while it is
        alive, which is what a naive `rmtree` after a timed-out suite leaves behind.
        """
        write_suite(ARTIFACTS, "detached-worker.py", DETACHED_WORKER)
        beat = ARTIFACTS / "beat"
        entry, pids = self.run_abnormal_fixture(
            "detached", DETACHED_SUITE,
            env={"BEAT": str(beat), "WORKER_FILE": str(ARTIFACTS / "detached-worker.py")})
        self.assertEqual(entry["state"], "TIMEOUT")
        self.assertEqual(len(pids), 1)
        self.assertGreaterEqual(int(beat.read_text(encoding="utf-8")), 1,
                                "the worker never wrote a heartbeat")
        self.assertFalse((ARTIFACTS / "beat.gone").exists(),
                         "the scratch tree was deleted while the worker still polled it")
        beats = int(beat.read_text(encoding="utf-8"))
        time.sleep(0.5)
        self.assertEqual(int(beat.read_text(encoding="utf-8")), beats,
                         "the worker kept polling after the run")
        self.assertIn("detached processes terminated", entry["reason"])

    @unittest.skipUnless(runner.PROC_ROOT.is_dir(), "the detection reads /proc")
    def test_scratch_detection_follows_the_cwd_symlink(self):
        """`cwd` is a symlink, not a file: readlink sees what read_bytes raised IsADirectoryError on.

        The worker empties its environment, so the cwd it was started in is the only tie to the
        suite's scratch — and the only way to find it is the `/proc/<pid>/cwd` symlink.
        """
        scratch = Path(tempfile.mkdtemp(prefix="cwd-detect-", dir=self.scratch))
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                  cwd=scratch, env={}, start_new_session=True)
        self.addCleanup(worker.wait)
        self.addCleanup(worker.kill)
        self.assertIn(worker.pid, runner._scratch_processes(scratch) or [],
                      "a worker whose only tie to scratch is its cwd was not found")

    @unittest.skipUnless(runner.PROC_ROOT.is_dir(), "the scratch sweep reads /proc")
    def test_timeout_stops_a_worker_only_its_cwd_identifies(self):
        """The environment check is not the only tie to scratch: the cwd symlink counts too.

        The fixture worker sanitizes its environment (`WORKER_SANITIZED`) and is started with its
        cwd inside the suite's task-local TMPDIR (`WORKER_CWD_SCRATCH`), so `environ` shows nothing
        and only the `/proc/<pid>/cwd` symlink finds it after the timeout.
        """
        write_suite(ARTIFACTS, "detached-worker.py", DETACHED_WORKER)
        beat = ARTIFACTS / "cwd-beat"
        entry, pids = self.run_abnormal_fixture(
            "cwd_detached", DETACHED_SUITE,
            env={"BEAT": str(beat), "WORKER_FILE": str(ARTIFACTS / "detached-worker.py"),
                 "WORKER_SANITIZED": "1", "WORKER_CWD_SCRATCH": "1"})
        self.assertEqual(entry["state"], "TIMEOUT")
        self.assertEqual(len(pids), 1)
        self.assertGreaterEqual(int(beat.read_text(encoding="utf-8")), 1,
                                "the worker never wrote a heartbeat")
        self.assertFalse((ARTIFACTS / "cwd-beat.gone").exists(),
                         "the scratch tree was deleted while the worker still polled it")
        self.assertIn("detached processes terminated", entry["reason"])

    @unittest.skipUnless(runner.WAITID_WNOWAIT and hasattr(os, "killpg"),
                         "a signalled command needs the non-reaping observation and the group API")
    def test_a_signal_killed_suite_still_tears_down_its_group(self):
        """A suite killed by a signal lost its cleanup callbacks; teardown must run anyway.

        The fixture's same-group child SIGKILLs the suite leader once it is ready, and the long
        timeout keeps the timeout path out of the picture.  The child sanitizes its environment and
        runs with `cwd="/"`, so only the group the leader leads can stop it — and the leader is
        still unreaped when its death is observed, which is what proves the group is this run's.
        """
        write_suite(ARTIFACTS, "signal-killer.py", SIGNAL_KILLER)
        ready = ARTIFACTS / "signal-ready"
        ready.unlink(missing_ok=True)
        entry, pids = self.run_abnormal_fixture(
            "signalled", SIGNALLED_SUITE, timeout="20",
            env={"READY": str(ready), "KILLER_FILE": str(ARTIFACTS / "signal-killer.py")})
        self.assertEqual(entry["state"], "ERROR")
        self.assertEqual(entry["exit_code"], -9, "the fixture leader was not killed by SIGKILL")
        self.assertEqual(len(pids), 1)
        self.assertIn("terminated by signal 9", entry["reason"])
        self.assertIn("process group terminated", entry["reason"])

    def test_covered_child_with_a_hiding_counter_line_is_error(self):
        """Contradictory counter evidence may not settle PASS by way of `covered_by`.

        The parent settles PASS on its own consistent line while the child's line claims 1 of
        100 checks passed; the same summary is ERROR for a scheduled suite, so it is ERROR here.
        """
        root = self.build()
        (root / "scripts/tests/parent.py").write_text(
            "# executes scripts/tests/test-counter-child.py in production\n"
            "print('parent-counter: 2/2 ok')\n"
            "print('child-counter: 1/100 ok')\n", encoding="utf-8")
        code, _, payload = self.run_main(root, "--suite", "parent")
        self.assertEqual(self.states(payload)["parent"]["state"], "PASS")
        child = self.states(payload)["scripts/tests/test-counter-child.py"]
        self.assertEqual(child["state"], "ERROR")
        self.assertEqual(child["counts"], {"passed": 1, "executed": 100, "total": 100})
        self.assertIn("disagrees", child["reason"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
