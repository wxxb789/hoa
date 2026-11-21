"""Run-plan tests for gdd.py: setup, precedence, notes, caps, usage and status (offline)."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
from gdd_test_support import route_fixture
from test_gdd import DELIVERY, GddCase, read, write

GDD = os.path.join(SCRIPTS, "gdd.py")
REFERENCES = os.path.normpath(os.path.join(SCRIPTS, os.pardir, "references"))


class RunPlanCase(GddCase):
    def plan_path(self, goal="0001"):
        return os.path.join(self.state_home, "gdd", "tasks", f"workrepo-{goal}", "run-plan.json")

    def write_source(self, plan):
        source = os.path.join(self.tmp, "plan-source.json")
        write(source, plan if isinstance(plan, str) else json.dumps(plan))
        return source

    def setup(self, plan, *, env=None):
        return self.run_tool(GDD, "setup", "--repo", self.repo, "--goal", "0001",
                             "--plan-file", self.write_source(plan), env=env)

    def setup_without_file(self, *args, env=None):
        return self.run_tool(GDD, "setup", "--repo", self.repo, "--goal", "0001", *args, env=env)

    def append_row(self, stage, note=None):
        args = [DELIVERY, "append", "--repo", self.repo, "--goal", "0001",
                "--stage", stage, "--base", self.base, "--head", self.head]
        if note is not None:
            args += ["--note", note]
        done = self.run_tool(*args)
        self.assertEqual(done.returncode, 0, done.stderr)

    def append_implement(self):
        self.append_row("implement")

    def run_state(self, stage="implement"):
        [run_dir] = [d for d in self.run_dirs()
                     if ".prev-" not in os.path.basename(d) and d.endswith(f"-{stage}")]
        return json.loads(read(os.path.join(run_dir, "state.json")))


class SetupTests(RunPlanCase):
    def test_setup_writes_the_plan_and_appends_a_setup_row(self):
        plan = {"roles": {"implement": {"model": "m1"}}, "notes": ["first"]}
        done = self.setup(plan)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(read(self.plan_path())), plan)
        rows = self.ledger()
        self.assertEqual([(r["stage"], r["base_sha"], r["head_sha"]) for r in rows],
                         [("setup", "-", "-")])
        self.assertIn(self.plan_path(), rows[0]["note"])

        done = self.setup({"notes": ["second"]})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(read(self.plan_path())), {"notes": ["second"]})
        self.assertEqual([r["stage"] for r in self.ledger()], ["setup", "setup"])

    def test_setup_without_inputs_writes_an_empty_plan(self):
        done = self.setup_without_file()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(read(self.plan_path())), {})

    def test_defaults_file_merges_under_the_plan_file(self):
        defaults = {"roles": {"implement": {"model": "dm", "thinking": "dt"},
                              "review": {"model": "rm"}},
                    "budgets": {"rounds": {"implement": 3}, "max_time": 900, "token_cap": 100},
                    "notes": ["default note"]}
        defaults_path = os.path.join(self.tmp, "defaults.json")
        write(defaults_path, json.dumps(defaults))
        write(os.path.join(self.tmp, "config", "gdd", "config.yaml"),
              f"GDD_RUN_PLAN_DEFAULTS: {json.dumps(defaults_path)}\n")
        done = self.setup({"roles": {"implement": {"model": "pm"}},
                           "budgets": {"rounds": {"review": 1}},
                           "notes": ["file note"]})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(read(self.plan_path())), {
            "roles": {"implement": {"model": "pm", "thinking": "dt"}, "review": {"model": "rm"}},
            "budgets": {"rounds": {"implement": 3, "review": 1}, "max_time": 900, "token_cap": 100},
            "notes": ["file note"],
        })


class PrecedenceTests(RunPlanCase):
    def test_plan_beats_environment_per_field(self):
        self.setup({"roles": {"implement": {"agent": "claude", "model": "plan-model",
                                            "thinking": "plan-think", "max_time": "7m"}}})
        done = self.stage("implement", "--wait", env={
            "GDD_AGENT": "omp", "GDD_MODEL": "env-model", "GDD_THINKING": "env-think",
            "GDD_MAX_TIME": "9m", "STUB_FIXTURE": route_fixture("claude")})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = self.run_state()
        self.assertEqual((state["agent"], state["model"], state["thinking"], state["max_time"]),
                         ("claude", "plan-model", "plan-think", "7m"))

    def test_flag_beats_plan_then_no_plan_falls_back_to_defaults(self):
        self.setup({"roles": {"implement": {"agent": "dsh", "model": "plan-model",
                                            "thinking": "plan-think", "max_time": "7m"}}})
        done = self.stage("implement", "--wait", "--agent", "omp", "--model", "flag-model",
                          "--thinking", "flag-think", "--max-time", "11m", env={
                              "GDD_MODEL": "env-model", "GDD_THINKING": "env-think",
                              "GDD_MAX_TIME": "9m", "STUB_FIXTURE": route_fixture("omp")})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = self.run_state()
        self.assertEqual((state["agent"], state["model"], state["thinking"], state["max_time"]),
                         ("omp", "flag-model", "flag-think", "11m"))

        os.remove(self.plan_path())
        done = self.stage("implement", "--wait")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = self.run_state()
        self.assertEqual((state["agent"], state["model"], state["thinking"], state["max_time"]),
                         ("omp", None, None, None))
        self.assertNotIn("--model", json.loads(read(self.record))["argv"])

    def test_budget_max_time_falls_back_below_the_role_and_above_env(self):
        self.setup({"budgets": {"max_time": 900}, "roles": {"review": {"max_time": "7m"}}})
        done = self.stage("implement", "--wait", env={"GDD_MAX_TIME": "9m"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.run_state()["max_time"], "900")

        done = self.stage("review", "--base", self.base, "--wait", env={"GDD_MAX_TIME": "9m"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.run_state("review")["max_time"], "7m")


class NotesTests(RunPlanCase):
    def prompt_of(self, env=None):
        dry = self.stage("implement", "--dry-run", env=env)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        return read(dry.stdout.splitlines()[0].removeprefix("prompt: "))

    def expected_implement_prompt(self):
        text = read(os.path.join(REFERENCES, "stage-templates", "implement.md"))
        variables = {
            "REPO_PATH": self.repo,
            "REPO_NAME": "workrepo",
            "GOAL": "0001",
            "GOAL_FILE": os.path.join(self.repo, "docs/goals", "0001-first.md"),
            "BASE_SHA": self.base,
            "HEAD_SHA": self.head,
            "GATES": "-",
            "FINDINGS_FILE": "-",
            "RESULT_SCHEMA": os.path.join(REFERENCES, "stage-result.schema.json"),
        }
        for key, value in variables.items():
            text = text.replace("${" + key + "}", value)
        return text

    def test_notes_are_appended_verbatim_and_absent_without_a_plan(self):
        expected = self.expected_implement_prompt()
        self.assertEqual(self.prompt_of(), expected)

        self.setup({"roles": {"implement": {"model": "m"}}})
        self.assertEqual(self.prompt_of(), expected)  # a plan without notes changes nothing

        notes = ["Do not touch the ledger parser.", "Keep ${GOAL} verbatim."]
        self.setup({"roles": {"implement": {"model": "m"}}, "notes": notes})
        prompt = self.prompt_of()
        head, _, section = prompt.partition("## Owner notes (run plan)")
        self.assertEqual(head.rstrip("\n"), expected.rstrip("\n"))
        self.assertEqual(section.strip().splitlines(), [f"- {note}" for note in notes])


class RoundCapTests(RunPlanCase):
    def test_plan_round_cap_refuses_and_over_budget_overrides(self):
        self.append_implement()
        self.append_implement()
        self.setup({"budgets": {"rounds": {"implement": 3}}})
        allowed = self.stage("implement", "--dry-run")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)  # the default cap 2 would refuse

        self.setup({"budgets": {"rounds": {"implement": 1}}})
        refused = self.stage("implement", "--dry-run")
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertIn("has already run 2x for this goal (cap 1)", refused.stderr)
        self.assertIn("--over-budget", refused.stderr)
        allowed = self.stage("implement", "--dry-run", "--over-budget")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)


class UsageNoteTests(RunPlanCase):
    def test_completion_note_records_usage_fields(self):
        done = self.stage("implement", "--wait")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        note = self.ledger()[-1]["note"]
        self.assertTrue(note.startswith("exit=0 "), note)
        self.assertIn("role=implement", note)
        self.assertIn("route=omp", note)
        self.assertIn("model=default", note)
        self.assertIn("thinking=default", note)
        match = re.search(r"wall=([0-9.]+)s tokens=([0-9]+)", note)
        self.assertIsNotNone(match, note)
        self.assertEqual(int(match.group(2)), self.run_state()["usage"]["total_tokens"])

    def test_completion_note_reports_unknown_without_usage(self):
        launcher = os.path.join(self.tmp, "no-usage-launcher.py")
        write(launcher, (
            "import json, os\n"
            "from datetime import datetime\n"
            "root = os.environ['GDD_RUN_ROOT']\n"
            "name = 'workrepo-0001-implement'\n"
            "run_dir = os.path.join(root, datetime.now().strftime('%Y-%m-%d'), name)\n"
            "os.makedirs(run_dir, exist_ok=True)\n"
            "with open(os.path.join(run_dir, 'state.json'), 'w', encoding='utf-8') as handle:\n"
            "    json.dump({'name': name, 'state': 'done', 'exit': 0, 'cwd': " + repr(self.repo) + ",\n"
            "               'started': datetime.now().isoformat(), 'ended': datetime.now().isoformat(),\n"
            "               'duration_s': 3.5}, handle)\n"
            "print('started:', name)\n"
            "print('run dir:', run_dir)\n"
        ))
        done = self.stage("implement", "--wait", env={"GDD_LAUNCHER": launcher})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        note = self.ledger()[-1]["note"]
        self.assertIn("wall=3.5s tokens=unknown", note)
        self.assertNotIn("tokens=0", note)


class TokenCapTests(RunPlanCase):
    def append_completion(self, stage, tokens):
        self.append_row(stage, f"exit=0 dur=1.2 head=0000000 role={stage} route=omp "
                               f"model=default thinking=default wall=1.2s tokens={tokens}")

    def test_token_cap_refuses_unknown_rows_not_counted_and_over_budget(self):
        self.setup({"budgets": {"token_cap": 100}})
        self.append_completion("implement", "60")
        self.append_completion("implement", "unknown")
        self.append_completion("review", "30")
        allowed = self.stage("implement", "--dry-run")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)  # 90 reported + 1 unknown < 100
        self.append_completion("implement", "10")
        refused = self.stage("implement", "--dry-run")
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertIn("token cap 100", refused.stderr)
        self.assertIn("100 used", refused.stderr)
        self.assertIn("1 unknown", refused.stderr)
        self.assertIn("--over-budget", refused.stderr)
        forced = self.stage("implement", "--dry-run", "--over-budget")
        self.assertEqual(forced.returncode, 0, forced.stderr)


class StatusTests(RunPlanCase):
    def status(self):
        done = self.run_tool(GDD, "status", "--repo", self.repo, "--goal", "0001")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_status_without_a_plan_says_no_run_plan(self):
        self.append_implement()
        out = self.status()
        self.assertIn("no run plan", out)
        self.assertIn("implement: rounds=1/2 tokens=0 unknown=0", out)

    def test_status_prints_the_plan_and_per_role_usage(self):
        self.setup({"roles": {"implement": {"model": "m1"}},
                    "budgets": {"rounds": {"implement": 3}, "token_cap": 100}})
        self.append_implement()
        self.append_row("implement", "exit=0 dur=1.2 head=0000000 tokens=60")
        self.append_row("review", "exit=0 dur=1.2 head=0000000 tokens=unknown")
        out = self.status()
        self.assertIn(self.plan_path(), out)
        self.assertIn('"token_cap": 100', out)
        self.assertIn("implement: rounds=1/3 tokens=60 unknown=0", out)
        self.assertIn("review: rounds=0/2 tokens=0 unknown=1", out)


class InvalidPlanTests(RunPlanCase):
    def test_invalid_plan_names_the_offending_key_path(self):
        cases = [
            ({"rolez": {}}, "rolez"),
            ({"roles": {"implemnt": {"model": "m"}}}, "roles.implemnt"),
            ({"roles": {"implement": {"agnt": "x"}}}, "roles.implement.agnt"),
            ({"roles": {"implement": {"model": 7}}}, "roles.implement.model"),
            ({"budgets": {"rounds": {"implement": "2"}}}, "budgets.rounds.implement"),
            ({"budgets": {"token_cap": "many"}}, "budgets.token_cap"),
            ({"notes": "n"}, "notes"),
        ]
        for plan, path in cases:
            with self.subTest(path=path):
                rejected = self.setup(plan)
                self.assertEqual(rejected.returncode, 2, rejected.stdout)
                self.assertIn(path, rejected.stderr)
                self.assertFalse(os.path.exists(self.plan_path()))

    def test_stage_refuses_a_hand_edited_invalid_plan(self):
        write(self.plan_path(), json.dumps({"roles": {"implement": {"agnt": "x"}}}))
        refused = self.stage("implement", "--dry-run")
        self.assertEqual(refused.returncode, 2, refused.stdout)
        self.assertIn("roles.implement.agnt", refused.stderr)


if __name__ == "__main__":
    unittest.main()
