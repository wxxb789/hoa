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
import shutil
import signal
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

    def test_the_pinned_shim_state_is_exactly_two_named_directories(self):
        """What may reach every suite as operator state is pinned by name, not by count."""
        self.assertEqual(set(runner.SHIM_STATE_DEFAULTS), {"MISE_STATE_DIR", "MISE_DATA_DIR"})

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
        self.assertTrue(environment["PATH"].startswith(str(Path(sys.executable).resolve().parent)))

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
        ):
            suite = next(item for item in self.plan.scheduled + self.plan.covered if item.id == path)
            self.assertEqual(suite.assertion, "counter")
            self.assertTrue(suite.count_regexes[0].startswith(marker), suite.count_regexes)

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

    def test_timeout_signal_and_spawn_failures(self):
        self.assertEqual(runner.settle(self.suite(), exit_code=None, timed_out=True, output="")[0],
                         "TIMEOUT")
        self.assertEqual(runner.settle(self.suite(), exit_code=-9, timed_out=False, output="")[0],
                         "ERROR")
        self.assertEqual(runner.settle(self.suite(), exit_code=None, timed_out=False, output="")[0],
                         "ERROR")
        self.assertEqual(runner.settle(self.suite(), exit_code=0, timed_out=False, output="",
                                       provisioned=False)[0], "ERROR")


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
        self.assertTrue(dump["PATH"].startswith(str(Path(sys.executable).resolve().parent)))

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
        self.assertIn(str(runner.AF_UNIX_PATH_LIMIT), outcome.reason)
        self.assertFalse(marker.exists(), "the suite ran despite an unusable scratch root")
        self.assertEqual([entry.name for entry in deep.iterdir()], [],
                         "the unusable per-suite scratch tree was not cleaned up")

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


if __name__ == "__main__":
    unittest.main()
