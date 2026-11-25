"""Exercise commit and dispatch against real Git worktrees and a local bare remote."""
import csv
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SCOPE = SCRIPTS.parents[1] / "delegated-work-acceptance" / "scripts" / "worktree-scope.py"
sys.path.insert(0, str(SCRIPTS))
import gdd_process


class CommitTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = root / "repo"
        self.origin = root / "origin.git"
        self.result = root / "result.json"
        self.ledger = root / "ledger.tsv"
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("GDD_", "GIT_", "XDG_", "HOA_SCOPE_"))}
        self.env.update(
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid",
            GDD_STATE_FILE=str(self.ledger), XDG_STATE_HOME=str(root / "state"),
            XDG_CONFIG_HOME=str(root / "config"), HOA_SCOPE_STATE=str(root / "scope"), PYTHONUTF8="1",
        )
        self.run_cmd("git", "init", "-q", "--bare", "--template=", "-b", "main", self.origin, check=True)
        self.run_cmd("git", "init", "-q", "--template=", "-b", "main", self.repo, check=True)
        self.write("old name.txt", "original\n")
        self.write("notes.txt", "original\n")
        self.write("removed.txt", "original\n")
        self.write("docs/goals/173-task.md", "# Goal\nState: active\n")
        self.git("add", "--", "old name.txt", "notes.txt", "removed.txt", "docs/goals/173-task.md")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("config", "diff.renames", "true")
        self.git("remote", "add", "origin", self.origin)
        self.git("push", "origin", "main")
        self.git("switch", "-c", "topic")
        self.gate = f'"{sys.executable}" -c "raise SystemExit(0)"'

    def run_cmd(self, *argv, check=False):
        return gdd_process.run(list(map(str, argv)), env=self.env, check=check,
                               capture_output=True, text=True, timeout=60)

    def git(self, *argv):
        return self.run_cmd("git", "-C", self.repo, *argv, check=True).stdout.strip()

    def write(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")

    def scope(self, verb):
        return self.run_cmd(sys.executable, SCOPE, verb, "--repo", self.repo, "--label", "173", "--json")

    def snapshot(self):
        proc = self.scope("snapshot")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def gdd(self, verb, *argv):
        return self.run_cmd(sys.executable, SCRIPTS / "gdd.py", verb, "--repo", self.repo, "--goal", "173", *argv)

    def purposes(self, *paths):
        changes = [{"path": path, "purpose": f"Explain {path}."} for path in paths]
        self.result.write_text(json.dumps({
            "stage": "implement", "verdict": "DONE", "summary": "done",
            "changed_files": changes, "gates": [], "findings": [], "unmet_criteria": [],
        }), encoding="utf-8")
        return changes

    def commit(self, *argv, code=0, error=None):
        result = self.gdd("commit", "-m", "Ship increment", "--json", *argv)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["exit"], payload["ok"], payload["error_code"]), (code, code == 0, error))
        with self.ledger.open(encoding="utf-8", newline="") as handle:
            row = list(csv.DictReader(handle, delimiter="\t"))[-1]
        self.assertEqual(row["stage"], "commit")
        self.assertTrue(row["note"].startswith(f"exit={code} code={error or 'ok'} "), row)
        return payload

    def remote_topic(self):
        return self.run_cmd("git", "-C", self.origin, "show-ref", "--hash", "--verify", "refs/heads/topic")

    def test_commit_rename_then_reuse_the_same_oid(self):
        self.snapshot()
        self.write("notes.txt", "modified\n")
        self.write("new caf\u00e9.txt", "added\n")
        (self.repo / "removed.txt").unlink()
        self.git("mv", "old name.txt", "renamed name.txt")
        changes = self.purposes("new caf\u00e9.txt", "notes.txt")
        previous = self.result.rename(self.result.with_name("previous.json"))
        changes += self.purposes("old name.txt", "removed.txt", "renamed name.txt")
        output = self.commit("--result", previous, "--result", self.result, "--gate", self.gate)
        oid = self.git("rev-parse", "HEAD")
        self.assertEqual((output["oid"], output["committed"], output["pushed"]), (oid, True, True))
        self.assertEqual(output["paths"], changes)
        self.assertEqual(output["gates"][0]["exit_code"], 0)
        self.assertEqual(self.remote_topic().stdout.strip(), oid)
        self.assertEqual(self.git("log", "-1", "--format=%B").splitlines(), [
            "Ship increment", "", *[f"- {row['path']}: {row['purpose']}" for row in changes],
        ])
        self.assertEqual(self.git("status", "--porcelain"), "")

        # A committed increment needs no result file. The no-push path still verifies it.
        again = self.commit("--no-push", "--gate", f'{self.gate} impossible')
        self.assertEqual((again["oid"], again["scope_sha"], again["committed"], again["gates"]),
                         (oid, output["scope_sha"], False, []))
        import gdd
        self.assertEqual(gdd.ledger_rounds(self.ledger, "repo", "173", "commit"), 0)

    def test_baseline_dirt_is_excluded_unless_it_changes(self):
        self.write("notes.txt", "pre-existing\n")
        self.snapshot()
        self.write("new.txt", "increment\n")
        self.purposes("new.txt")
        output = self.commit("--result", self.result, "--no-push", "--gate", 'missing-gate')
        self.assertEqual((output["pushed"], output["gates"]), (False, []))
        self.assertNotEqual(self.remote_topic().returncode, 0)
        self.assertEqual(self.git("show", "HEAD:notes.txt"), "original")
        self.assertIn("notes.txt", self.git("status", "--porcelain"))

        self.write("notes.txt", "edited after snapshot\n")
        self.purposes("notes.txt")
        self.assertIn("notes.txt", self.commit("--no-push", code=3, error="OVERLAP")["detail"])
        self.git("add", "--", "notes.txt")
        self.write("notes.txt", "edited after staging\n")
        self.commit("--result", self.result, "--no-push", "--accept-overlap")
        self.assertEqual(self.git("show", "HEAD:notes.txt"), "edited after staging")

    def test_unexplained_phantom_and_outside_index_refuse_before_commit(self):
        self.write("notes.txt", "pre-existing\n")
        self.git("add", "--", "notes.txt")
        self.snapshot()
        self.write("new.txt", "increment\n")
        self.assertIn("new.txt", self.commit("--no-push", code=3, error="UNEXPLAINED_CHANGE")["detail"])
        self.purposes("new.txt", "missing.txt")
        self.assertIn("missing.txt", self.commit(
            "--no-push", "--result", self.result, code=3, error="PHANTOM_CHANGE")["detail"])
        self.purposes("new.txt")
        self.assertIn("notes.txt", self.commit(
            "--no-push", "--result", self.result, code=3, error="INDEX_MISMATCH")["detail"])
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "notes.txt")

    def test_main_moved_and_rebase_does_not_move_baseline(self):
        self.snapshot()
        self.write("new.txt", "increment\n")
        self.git("add", "--", "new.txt")
        self.git("commit", "-qm", "increment")
        self.git("switch", "main")
        self.git("commit", "--allow-empty", "-qm", "main advances")
        self.git("push", "origin", "main")
        self.git("switch", "topic")
        self.commit("--no-push", code=3, error="BEHIND_MAIN")
        self.git("rebase", "origin/main")
        self.commit("--no-push", code=3, error="BASELINE_MISMATCH")

    def test_partial_index_change_that_would_disappear_is_not_overwritten(self):
        self.snapshot()
        self.write("notes.txt", "staged edit\n")
        self.git("add", "--", "notes.txt")
        self.write("notes.txt", "original\n")
        self.purposes("notes.txt")
        refused = self.commit("--result", self.result, "--no-push", code=3, error="INDEX_MISMATCH")
        self.assertIn("notes.txt", refused["detail"])
        self.assertEqual(self.git("show", ":notes.txt"), "staged edit")

    def test_no_gates_failed_gate_and_configured_gate(self):
        self.snapshot()
        self.write("new.txt", "increment\n")
        self.purposes("new.txt")
        stopped = self.commit("--result", self.result, code=3, error="NO_GATES")
        self.assertTrue(stopped["committed"])
        failed = self.commit("--gate", self.gate.replace("(0)", "(7)"), "--gate", self.gate,
                             code=4, error="GATE_FAILED")
        self.assertEqual([gate["exit_code"] for gate in failed["gates"]], [7])
        self.assertNotEqual(self.remote_topic().returncode, 0)
        config = Path(self.env["XDG_CONFIG_HOME"]) / "gdd" / "config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("GDD_GATES: '" + json.dumps([self.gate]) + "'\n", encoding="utf-8")
        pushed = self.commit()
        self.assertEqual(self.remote_topic().stdout.strip(), pushed["oid"])
        self.assertFalse(pushed["committed"])

    def test_stage_guards_use_baseline_and_require_a_committed_range(self):
        self.write("notes.txt", "pre-existing\n")
        denied = self.gdd("stage", "--stage", "implement", "--dry-run")
        self.assertEqual(denied.returncode, 3, denied.stdout + denied.stderr)
        self.assertIn("snapshot", denied.stderr)
        self.assertNotEqual(self.scope("status").returncode, 0)
        self.snapshot()
        self.write("new caf\u00e9.txt", "increment\n")
        self.purposes("new caf\u00e9.txt")
        blocked = self.gdd("stage", "--stage", "review", "--dry-run")
        self.assertEqual(blocked.returncode, 3, blocked.stdout)
        self.assertIn("new caf\u00e9.txt", blocked.stderr)
        self.commit("--no-push", "--result", self.result)
        allowed = self.gdd("stage", "--stage", "review", "--dry-run")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_clean_implement_auto_snapshots_only_when_launching(self):
        rendered = self.gdd("stage", "--stage", "implement", "--dry-run")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn("would record", rendered.stdout)
        self.assertNotEqual(self.scope("status").returncode, 0)
        launcher = self.repo.parent / "launcher.py"
        launcher.write_text("import sys\nprint('started:', sys.argv[sys.argv.index('--name') + 1])\n",
                            encoding="utf-8")
        self.env["GDD_LAUNCHER"] = str(launcher)
        launched = self.gdd("stage", "--stage", "implement")
        self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
        self.assertIn("scope snapshot:", launched.stdout)
        status = self.scope("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["baseline"]["entries"], [])

    def test_commit_history_drift_stops_before_gate_or_push(self):
        self.snapshot()
        self.write("transient.txt", "out of scope\n")
        self.git("add", "--", "transient.txt")
        self.git("commit", "-qm", "add transient path")
        self.git("rm", "--", "transient.txt")
        self.git("commit", "-qm", "remove transient path")
        refused = self.commit("--gate", self.gate, code=1, error="SCOPE_DRIFT")
        self.assertIn("transient.txt", refused["detail"])
        self.assertEqual(refused["gates"], [])
        self.assertNotEqual(self.remote_topic().returncode, 0)

    def test_push_is_reported_even_when_ledger_cannot_be_written(self):
        self.snapshot()
        self.write("new.txt", "increment\n")
        self.purposes("new.txt")
        message = self.result.with_name("message.txt")
        message.write_text("Subject from file\n", encoding="utf-8")
        self.ledger.mkdir()
        proc = self.gdd("commit", "-F", message, "--result", self.result, "--gate", self.gate, "--json")
        self.assertEqual(proc.returncode, 5, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual((result["error_code"], result["pushed"]), ("LEDGER_FAILED", True))
        self.assertEqual(self.remote_topic().stdout.strip(), result["oid"])
        self.assertEqual(self.git("log", "-1", "--format=%s"), "Subject from file")

    def test_concurrent_first_appends_write_one_header_and_all_rows(self):
        def append(goal):
            return self.run_cmd(sys.executable, SCRIPTS / "delivery-state.py", "append",
                                "--state-file", self.ledger, "--repo", self.repo, "--goal", goal,
                                "--stage", "commit", "--note", "exit=0")

        goals = ["one", "two", "three", "four"]
        with ThreadPoolExecutor(max_workers=len(goals)) as pool:
            for proc in pool.map(append, goals):
                self.assertEqual(proc.returncode, 0, proc.stderr)
        with self.ledger.open(encoding="utf-8", newline="") as handle:
            self.assertCountEqual([row["goal"] for row in csv.DictReader(handle, delimiter="\t")], goals)


if __name__ == "__main__":
    unittest.main()
