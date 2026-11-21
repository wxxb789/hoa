"""Run-plan tests for gdd.py: setup, accounting, caps, notes, routes and status (offline)."""
import json
import os
import re
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
import gdd_process
from gdd_test_support import finalized, route_fixture, wait_for_json
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

    def append_row(self, stage, note=None, *, repo=None, goal="0001"):
        args = [DELIVERY, "append", "--repo", repo or self.repo, "--goal", goal,
                "--stage", stage, "--base", self.base, "--head", self.head]
        if note is not None:
            args += ["--note", note]
        done = self.run_tool(*args)
        self.assertEqual(done.returncode, 0, done.stderr)

    def append_implement(self):
        self.append_row("implement")

    def append_dispatch(self, stage, run_name, *, repo=None, goal="0001"):
        self.append_row(stage, f"run={run_name}", repo=repo, goal=goal)

    def craft_usage_run(self, name, *, usage=None, state="done", exit_code=0, cwd=None):
        run_dir = os.path.join(self.state_home, "gdd", "runs", "2024-01-01", name)
        payload = {
            "name": name, "agent": "omp", "state": state,
            "exit": None if state == "running" else exit_code,
            "cwd": cwd or self.tmp,
            "started": "2024-01-01T00:00:00+00:00",
            "ended": None if state == "running" else "2024-01-01T00:01:00+00:00",
            "duration_s": None if state == "running" else 60,
            "usage": {} if usage is None else usage,
        }
        write(os.path.join(run_dir, "state.json"), json.dumps(payload))
        return run_dir

    def status(self):
        done = self.run_tool(GDD, "status", "--repo", self.repo, "--goal", "0001")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

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

    def test_multiline_note_bytes_are_appended_without_newline_translation(self):
        self.setup({"notes": ["line1\r\nline2", "line3"]})
        dry = self.stage("implement", "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        prompt = dry.stdout.splitlines()[0].removeprefix("prompt: ")
        raw = Path(prompt).read_bytes()
        suffix = b"\n\n## Owner notes (run plan)\n\n- line1\r\nline2\n- line3\n"
        self.assertTrue(raw.endswith(suffix), raw[-len(suffix):])
        self.assertNotIn(b"\r\r", raw)
        head = raw[:-len(suffix)].decode("utf-8").replace("\r\n", "\n")
        self.assertEqual(head, self.expected_implement_prompt().rstrip("\n"))


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

    def test_a_null_round_cap_still_enforces_the_default(self):
        self.setup({"budgets": {"rounds": {"implement": None}}})
        self.append_implement()
        self.append_implement()
        refused = self.stage("implement", "--dry-run")
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertIn("cap 2", refused.stderr)


class UsageNoteTests(RunPlanCase):
    def reported_launcher(self, name, *, state=None):
        launcher = os.path.join(self.tmp, name)
        payload = {"name": "workrepo-0001-implement", "state": "done", "exit": 0,
                   "cwd": self.repo, "started": "2024-01-01T00:00:00+00:00",
                   "ended": "2024-01-01T00:01:00+00:00", "duration_s": 3.5}
        payload.update(state or {})
        write(launcher, (
            "import json, os\n"
            "from datetime import datetime\n"
            "root = os.environ['GDD_RUN_ROOT']\n"
            "name = 'workrepo-0001-implement'\n"
            "run_dir = os.path.join(root, datetime.now().strftime('%Y-%m-%d'), name)\n"
            "os.makedirs(run_dir, exist_ok=True)\n"
            "with open(os.path.join(run_dir, 'state.json'), 'w', encoding='utf-8') as handle:\n"
            f"    json.dump({payload!r}, handle)\n"
            "print('started:', name)\n"
            "print('run dir:', run_dir)\n"
        ))
        return launcher

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
        launcher = self.reported_launcher("no-usage-launcher.py")
        done = self.stage("implement", "--wait", env={"GDD_LAUNCHER": launcher})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        note = self.ledger()[-1]["note"]
        self.assertIn("wall=3.5s tokens=unknown", note)
        self.assertNotIn("tokens=0", note)

    def test_completion_note_prefers_the_launcher_reported_fields(self):
        launcher = self.reported_launcher("reported-launcher.py", state={
            "agent": "actual-agent", "model": "actual-model", "thinking": "actual-thinking",
            "usage": {"total_tokens": 7}})
        done = self.stage("implement", "--wait", "--agent", "omp", "--model", "requested-model",
                          "--thinking", "requested-thinking", env={"GDD_LAUNCHER": launcher})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        note = self.ledger()[-1]["note"]
        self.assertIn("route=actual-agent", note)
        self.assertIn("model=actual-model", note)
        self.assertIn("thinking=actual-thinking", note)
        self.assertIn("tokens=7", note)

    def test_completion_note_marks_requested_values_the_launcher_did_not_report(self):
        launcher = self.reported_launcher("silent-launcher.py", state={"usage": {"total_tokens": 7}})
        done = self.stage("implement", "--wait", "--agent", "omp", "--model", "requested-model",
                          "--thinking", "requested-thinking", env={"GDD_LAUNCHER": launcher})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        note = self.ledger()[-1]["note"]
        self.assertIn("route=req:omp", note)
        self.assertIn("model=req:requested-model", note)
        self.assertIn("thinking=req:requested-thinking", note)


class UsageAccountingTests(RunPlanCase):
    def wait_finalized(self, run_dir):
        return wait_for_json(os.path.join(run_dir, "state.json"),
                             lambda value: finalized(run_dir, value), time.monotonic() + 30)

    def test_detached_run_usage_over_cap_refuses_the_next_stage(self):
        self.setup({"budgets": {"token_cap": 1}})
        dispatched = self.stage("implement")
        self.assertEqual(dispatched.returncode, 0, dispatched.stdout + dispatched.stderr)
        [run_dir] = self.run_dirs()
        state = self.wait_finalized(run_dir)
        self.assertGreater(state["usage"]["total_tokens"], 1)
        refused = self.stage("review")
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertIn("token cap 1", refused.stderr)
        self.assertIn(f"{state['usage']['total_tokens']} used", refused.stderr)
        self.assertIn("--over-budget", refused.stderr)
        forced = self.stage("review", "--dry-run", "--over-budget")
        self.assertEqual(forced.returncode, 0, forced.stderr)

    def test_failed_attempt_usage_counts_toward_the_cap(self):
        self.setup({"budgets": {"token_cap": 1}})
        dispatched = self.stage("implement", env={"STUB_EXIT": "1"})
        self.assertEqual(dispatched.returncode, 0, dispatched.stdout + dispatched.stderr)
        [run_dir] = self.run_dirs()
        state = self.wait_finalized(run_dir)
        self.assertEqual(state["state"], "failed")
        self.assertGreater(state["usage"]["total_tokens"], 1)
        refused = self.stage("review", "--dry-run")
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertIn("token cap 1", refused.stderr)

    def test_running_and_legacy_rows_stay_unknown_and_are_never_summed(self):
        self.setup({"budgets": {"token_cap": 10}})
        self.craft_usage_run("workrepo-0001-implement", usage={"total_tokens": 100}, state="running")
        self.append_dispatch("implement", "workrepo-0001-implement")
        self.append_row("implement")  # legacy: no run= reference
        out = self.status()
        self.assertIn("tokens: 0 used, 2 unknown (cap 10)", out)
        allowed = self.stage("review", "--dry-run")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_completion_rows_are_display_only_not_accounted(self):
        self.setup({"budgets": {"token_cap": 10}})
        self.append_row("implement", "exit=0 tokens=999")
        self.append_row("verify", "exit=0 tokens=777")  # a mechanical stage is never counted
        out = self.status()
        self.assertIn("tokens: 0 used, 0 unknown (cap 10)", out)
        allowed = self.stage("implement", "--dry-run")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_malformed_usage_is_unknown_and_never_fails_the_stage(self):
        self.setup({"budgets": {"token_cap": 10}})
        self.craft_usage_run("a", usage={"total_tokens": -5})       # negative
        self.craft_usage_run("b", usage={"total_tokens": 1.5})      # fractional
        self.craft_usage_run("c", usage={"total_tokens": "9"})      # not a number
        self.craft_usage_run("d", usage={"input_tokens": 3, "output_tokens": 4,
                                         "cache_read_tokens": 1000})
        self.craft_usage_run("e", usage={"input_tokens": 3, "cache_read_tokens": 1000})
        for name in ("a", "b", "c", "d", "e"):
            self.append_dispatch("implement", name)
        out = self.status()
        self.assertIn("tokens: 7 used, 4 unknown (cap 10)", out)
        allowed = self.stage("review", "--dry-run")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)


class ResumeAdviceTests(RunPlanCase):
    def test_wait_failure_with_a_plan_points_at_gdd_stage_not_a_raw_resume(self):
        self.setup({})
        failed = self.stage("implement", "--wait", env={"STUB_EXIT": "1"})
        self.assertEqual(failed.returncode, 1, failed.stdout)
        self.assertNotIn("--resume", failed.stderr)
        self.assertIn("attempt is recorded", failed.stderr)
        self.assertIn("gdd.py stage", failed.stderr)
        self.assertIn("--over-budget", failed.stderr)

    def test_wait_failure_without_a_plan_keeps_the_raw_resume_hint(self):
        failed = self.stage("implement", "--wait", env={"STUB_EXIT": "1"})
        self.assertEqual(failed.returncode, 1, failed.stdout)
        self.assertIn("--resume", failed.stderr)


class ExactRepoMatchTests(RunPlanCase):
    def other_repo(self):
        other = os.path.join(self.tmp, "other-workrepo")
        os.makedirs(other, exist_ok=True)

        def run(*args):
            return gdd_process.run(["git", "-C", other, *args], env=self.env,
                                   capture_output=True, text=True, check=True)

        run("init", "-q", "-b", "main")
        write(os.path.join(other, "file.txt"), "x\n")
        run("add", "-A")
        run("commit", "-q", "-m", "init")
        return other

    def test_plan_governed_accounting_matches_the_repo_key_exactly(self):
        other = self.other_repo()
        self.append_row("implement", repo=other)
        self.append_row("implement", repo=other)
        # Without a plan, round counting keeps the legacy substring match.
        refused = self.stage("implement", "--dry-run")
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertIn("has already run 2x", refused.stderr)

        # With a plan, this repo's key is counted exactly: another repo's rows spend nothing.
        self.setup({"budgets": {"rounds": {"implement": 10}, "token_cap": 50}})
        self.craft_usage_run("other-workrepo-0001-implement", usage={"total_tokens": 100})
        self.append_dispatch("implement", "other-workrepo-0001-implement", repo=other)
        token_allowed = self.stage("implement", "--dry-run")
        self.assertEqual(token_allowed.returncode, 0, token_allowed.stderr)

        self.setup({"budgets": {"rounds": {"implement": 1}}})
        rounds_allowed = self.stage("implement", "--dry-run")
        self.assertEqual(rounds_allowed.returncode, 0, rounds_allowed.stderr)


class PlanPathTests(RunPlanCase):
    def test_unsafe_goal_segments_are_rejected_by_setup_and_stage(self):
        for goal in ("a/b", "a\\b", "..", ".", "C:/x", ""):
            with self.subTest(goal=goal):
                rejected = self.run_tool(GDD, "setup", "--repo", self.repo, "--goal", goal,
                                         "--plan-file", self.write_source({}))
                self.assertEqual(rejected.returncode, 2, rejected.stdout)
                self.assertIn("goal", rejected.stderr)
        refused = self.run_tool(GDD, "stage", "--repo", self.repo, "--goal", "../x",
                                "--stage", "implement", "--dry-run")
        self.assertEqual(refused.returncode, 2, refused.stdout)
        self.assertIn("goal", refused.stderr)

    def test_status_rejects_a_raw_path_selector(self):
        refused = self.run_tool(GDD, "status", "--repo", "../evil", "--goal", "0001")
        self.assertEqual(refused.returncode, 2, refused.stdout)
        self.assertIn("repo", refused.stderr)

    def test_a_linked_goal_directory_cannot_escape_the_task_root(self):
        outside = os.path.join(self.tmp, "outside-target")
        os.makedirs(outside)
        link = os.path.join(self.state_home, "gdd", "tasks", "workrepo-0001")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        reason = ""
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError as exc:
            reason = str(exc)
            if os.name == "nt":
                created = gdd_process.run(["cmd", "/c", "mklink", "/J", link, outside],
                                          capture_output=True, text=True, env=self.env)
                reason = "" if created.returncode == 0 else f"{reason}; mklink /J: {created.stderr.strip()}"
        if reason:
            self.skipTest(f"cannot create a directory link on this platform: {reason}")
        rejected = self.setup_without_file()
        self.assertEqual(rejected.returncode, 2, rejected.stdout)
        self.assertIn("outside", rejected.stderr)
        self.assertFalse(os.path.exists(os.path.join(outside, "run-plan.json")))

    def test_plan_write_replaces_atomically_and_keeps_the_previous_file(self):
        import gdd

        path = self.plan_path()
        write(path, '{"notes": ["first"]}')

        def interrupted(value, handle, **kwargs):
            handle.write('{"notes": ["sec')  # a partial write, as an interrupted update would make
            raise RuntimeError("interrupted")

        with mock.patch.object(gdd.json, "dump", interrupted):
            with self.assertRaises(RuntimeError):
                gdd.write_run_plan(path, {"notes": ["second"]})
        self.assertEqual(read(path), '{"notes": ["first"]}')
        leftovers = [name for name in os.listdir(os.path.dirname(path))
                     if name.startswith(".run-plan.json.")]
        self.assertEqual(leftovers, [])


class ShimGuardTests(RunPlanCase):
    @unittest.skipUnless(os.name == "nt", "the batch-shim guard is Windows-only")
    def test_plan_model_through_a_cmd_shim_is_rejected_before_spawn(self):
        launcher = os.path.join(self.tmp, "fake-launcher.cmd")
        write(launcher, "@echo off\necho started: %1\n")
        self.setup({"roles": {"implement": {"model": "bad%model"}}})
        refused = self.stage("implement", env={"GDD_LAUNCHER": launcher})
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertIn("shim", refused.stderr)
        self.assertEqual(self.run_dirs(), [])


class LedgerViewTests(RunPlanCase):
    def test_setup_rows_never_replace_an_earlier_actionable_checkpoint(self):
        appended = self.run_tool(DELIVERY, "append", "--repo", self.repo, "--goal", "0001",
                                 "--stage", "implement", "--base", self.base, "--head", self.head,
                                 "--next", "review")
        self.assertEqual(appended.returncode, 0, appended.stderr)
        done = self.setup_without_file()
        self.assertEqual(done.returncode, 0, done.stderr)
        show = self.run_tool(DELIVERY, "show", "--repo", self.repo, "--goal", "0001",
                             "--state-file", os.path.join(self.state_home, "gdd", "ledger.tsv"),
                             "--task-root", os.path.join(self.state_home, "gdd", "tasks"),
                             "--run-root", os.path.join(self.state_home, "gdd", "runs"))
        self.assertEqual(show.returncode, 0, show.stderr)
        latest, _, history = show.stdout.partition("HISTORY")
        self.assertIn("stage: implement", latest)
        self.assertIn("next_action: review", latest)
        self.assertNotIn("stage: setup", latest)
        self.assertIn("setup", history)
        listing = self.run_tool(DELIVERY, "list",
                                "--state-file", os.path.join(self.state_home, "gdd", "ledger.tsv"))
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn(" implement ", listing.stdout)
        self.assertNotIn(" setup ", listing.stdout)


class StatusTests(RunPlanCase):
    def legacy_show(self):
        return self.run_tool(DELIVERY, "show", "--repo", self.repo, "--goal", "0001",
                             "--state-file", os.path.join(self.state_home, "gdd", "ledger.tsv"),
                             "--task-root", os.path.join(self.state_home, "gdd", "tasks"),
                             "--run-root", os.path.join(self.state_home, "gdd", "runs"))

    def test_status_without_a_plan_is_exactly_the_legacy_show_output(self):
        self.append_implement()
        direct = self.legacy_show()
        self.assertEqual(direct.returncode, 0, direct.stderr)
        status = self.run_tool(GDD, "status", "--repo", self.repo, "--goal", "0001")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(status.stdout, direct.stdout)
        self.assertNotIn("RUN PLAN", status.stdout)

    def test_status_with_an_empty_plan_shows_the_path_and_default_caps(self):
        self.setup_without_file()
        out = self.status()
        self.assertIn("RUN PLAN", out)
        self.assertIn(f"plan: {self.plan_path()}", out)
        self.assertIn("implement: rounds=0/2 tokens=0 unknown=0", out)
        self.assertNotIn("no run plan", out)

    def test_status_reports_launcher_usage_and_links_the_goal_total_to_the_cap(self):
        self.setup({"roles": {"implement": {"model": "m1"}},
                    "budgets": {"rounds": {"implement": 3}, "token_cap": 100}})
        self.craft_usage_run("workrepo-0001-implement", usage={"total_tokens": 60})
        self.append_dispatch("implement", "workrepo-0001-implement")
        self.append_dispatch("review", "workrepo-0001-review")  # no state.json: unknown
        out = self.status()
        self.assertIn(f"plan: {self.plan_path()}", out)
        self.assertIn('"token_cap": 100', out)
        self.assertIn("implement: rounds=1/3 tokens=60 unknown=0", out)
        self.assertIn("review: rounds=1/2 tokens=0 unknown=1", out)
        self.assertIn("tokens: 60 used, 1 unknown (cap 100)", out)

    def test_status_normalizes_a_tilde_repo_like_delivery_state(self):
        self.setup({"budgets": {"rounds": {"implement": 3}}})
        env = {"HOME": self.tmp, "USERPROFILE": self.tmp}
        done = self.run_tool(GDD, "status", "--repo", "~/workrepo", "--goal", "0001", env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"plan: {self.plan_path()}", done.stdout)


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

    def test_zero_rounds_zero_durations_and_bad_role_values_are_rejected_by_key(self):
        cases = [
            ({"budgets": {"rounds": {"implement": 0}}}, "budgets.rounds.implement"),
            ({"budgets": {"max_time": 0}}, "budgets.max_time"),
            ({"budgets": {"max_time": "soon"}}, "budgets.max_time"),
            ({"roles": {"implement": {"max_time": "0m"}}}, "roles.implement.max_time"),
            ({"roles": {"implement": {"agent": "om p"}}}, "roles.implement.agent"),
            ({"roles": {"implement": {"model": "a=b"}}}, "roles.implement.model"),
            ({"roles": {"implement": {"thinking": "hi there"}}}, "roles.implement.thinking"),
        ]
        for plan, path in cases:
            with self.subTest(path=path):
                rejected = self.setup(plan)
                self.assertEqual(rejected.returncode, 2, rejected.stdout)
                self.assertIn(path, rejected.stderr)
                self.assertFalse(os.path.exists(self.plan_path()))

    def test_null_caps_and_valid_durations_are_accepted(self):
        done = self.setup({"roles": {"review": {"max_time": "7m"}},
                           "budgets": {"rounds": {"implement": None}, "max_time": "0.5h",
                                       "token_cap": None}})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
