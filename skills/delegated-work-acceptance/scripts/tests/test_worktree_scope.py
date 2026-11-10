#!/usr/bin/env python3
"""End-to-end tests for worktree-scope.py against real temporary git repos.

Run: python skills/delegated-work-acceptance/scripts/tests/test_worktree_scope.py
Repositories live under .tmp-artifacts/worktree-scope-tests/.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = Path(__file__).resolve().parents[1] / "worktree-scope.py"
ARTIFACTS = ROOT / ".tmp-artifacts" / "worktree-scope-tests"
_DEFAULT = object()


class ScopeTests(unittest.TestCase):
    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(dir=ARTIFACTS))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.state = self.tmp / "state"
        self.env = dict(os.environ,
                        GIT_AUTHOR_NAME="Scope Test",
                        GIT_AUTHOR_EMAIL="scope@example.invalid",
                        GIT_COMMITTER_NAME="Scope Test",
                        GIT_COMMITTER_EMAIL="scope@example.invalid")
        self.repo = self.make_repo("repo")

    # -- helpers ---------------------------------------------------------

    def make_repo(self, name: str) -> Path:
        repo = self.tmp / name
        repo.mkdir()
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "commit", "-q", "--allow-empty", "-m", "init")
        return repo

    def git(self, repo: Path, *args: str) -> str:
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def commit(self, repo: Path, message: str) -> None:
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", message)

    def write(self, repo: Path, name: str, text: str) -> None:
        (repo / name).write_text(text, encoding="utf-8")

    def invoke(self, *args: str, state=_DEFAULT, label="t", env=None,
               expect: int | None = None):
        command = [sys.executable, str(SCRIPT), args[0], "--repo", str(self.repo),
                   "--label", label]
        if state is _DEFAULT:
            state = self.state
        if state is not None:
            command += ["--state-file", str(state)]
        command += list(args[1:])
        proc = subprocess.run(command, capture_output=True, text=True,
                              env=env or self.env)
        if expect is not None:
            self.assertEqual(proc.returncode, expect,
                             f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        return proc

    def invoke_json(self, *args: str, state=_DEFAULT, label="t", env=None,
                    expect: int = 0) -> dict:
        proc = self.invoke(*args, "--json", state=state, label=label, env=env,
                           expect=expect)
        return json.loads(proc.stdout)

    def state_file(self, state=None, label="t") -> Path:
        key = hashlib.sha256(os.fsencode(os.path.realpath(self.repo))).hexdigest()[:12]
        base = self.state if state is None else state
        return base / key / f"{label}.json"

    # -- snapshot --------------------------------------------------------

    def test_clean_snapshot_records_head_and_no_paths(self):
        self.write(self.repo, "tracked.txt", "base\n")
        self.commit(self.repo, "base")
        result = self.invoke_json("snapshot")
        self.assertEqual(result["baseline"]["entries"], [])
        self.assertEqual(result["baseline"]["head"],
                         self.git(self.repo, "rev-parse", "HEAD").strip())
        self.assertTrue(self.state_file().is_file())

    def test_snapshot_records_mode_and_digest_of_dirty_paths(self):
        self.write(self.repo, "tracked.txt", "base\n")
        self.commit(self.repo, "base")
        self.write(self.repo, "tracked.txt", "dirty\n")
        result = self.invoke_json("snapshot")
        entries = result["baseline"]["entries"]
        self.assertEqual([entry["path"] for entry in entries], ["tracked.txt"])
        self.assertEqual(entries[0]["mode"], "100644")
        self.assertEqual(entries[0]["sha256"],
                         hashlib.sha256(b"dirty\n").hexdigest())

    # -- diff ------------------------------------------------------------

    def test_preexisting_dirty_file_is_excluded_after_unrelated_edit(self):
        self.write(self.repo, "preexisting.txt", "base\n")
        self.write(self.repo, "other.txt", "base\n")
        self.commit(self.repo, "base")
        self.write(self.repo, "preexisting.txt", "base\npre-existing\n")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "other.txt", "base\nunrelated\n")

        result = self.invoke_json("diff")
        self.assertEqual(result["changed_paths"], ["other.txt"])
        self.assertEqual(result["excluded_preexisting_paths"], ["preexisting.txt"])
        self.assertEqual(result["overlapping_paths"], [])

    def test_new_file_appears_in_changed_paths(self):
        self.write(self.repo, "tracked.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "new\n")

        result = self.invoke_json("diff")
        self.assertEqual(result["changed_paths"], ["new.txt"])
        self.assertEqual(result["excluded_preexisting_paths"], [])

    def test_same_file_dirty_then_modified_overlaps_and_seal_refuses(self):
        self.write(self.repo, "shared.txt", "base\n")
        self.commit(self.repo, "base")
        self.write(self.repo, "shared.txt", "base\ndirty\n")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "shared.txt", "base\ndirty\nmore\n")

        result = self.invoke_json("diff")
        self.assertEqual(result["changed_paths"], ["shared.txt"])
        self.assertEqual(result["overlapping_paths"], ["shared.txt"])
        self.assertEqual(result["excluded_preexisting_paths"], [])

        refused = self.invoke("seal", expect=2)
        self.assertIn("overlapping shared.txt", refused.stderr)
        accepted = self.invoke_json("seal", "--accept-overlap")
        self.assertTrue(accepted["seal"]["accepted_overlap"])
        self.assertEqual(accepted["seal"]["overlap_paths"], ["shared.txt"])

    # -- seal / verify ---------------------------------------------------

    def test_seal_then_verify_passes_before_and_after_commit(self):
        self.write(self.repo, "tracked.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.invoke("diff", expect=0)
        seal = self.invoke_json("seal")["seal"]
        self.assertEqual(len(seal["paths"]), 1)

        proc = self.invoke("verify", expect=0)
        self.assertIn("scope ok: 1 paths", proc.stdout)
        self.assertIn(seal["scope_sha"][:12], proc.stdout)

        self.commit(self.repo, "work")
        proc = self.invoke("verify", expect=0)
        self.assertIn("scope ok: 1 paths", proc.stdout)

    def test_seal_then_modify_verify_reports_drift(self):
        self.write(self.repo, "tracked.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.invoke("diff", expect=0)
        self.invoke("seal", expect=0)

        self.write(self.repo, "new.txt", "two\n")
        proc = self.invoke("verify", expect=1)
        self.assertIn("SCOPE_DRIFT: 1 paths", proc.stdout)
        self.assertIn("modified new.txt", proc.stdout)

    def test_verify_added_and_removed_paths(self):
        self.write(self.repo, "tracked.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "sealed.txt", "sealed\n")
        self.invoke("diff", expect=0)
        self.invoke("seal", expect=0)

        self.write(self.repo, "added.txt", "added\n")
        proc = self.invoke("verify", expect=1)
        self.assertIn("SCOPE_DRIFT: 1 paths", proc.stdout)
        self.assertIn("added added.txt", proc.stdout)

        (self.repo / "added.txt").unlink()
        (self.repo / "sealed.txt").unlink()
        proc = self.invoke("verify", expect=1)
        self.assertIn("removed sealed.txt", proc.stdout)

    def test_missing_baseline_and_missing_seal_exit_two(self):
        missing = self.invoke("diff", state=self.tmp / "empty", expect=2)
        self.assertIn("run: worktree-scope.py snapshot", missing.stderr)
        self.invoke("seal", state=self.tmp / "empty", expect=2)
        self.invoke("verify", state=self.tmp / "empty", expect=2)

    # -- state location --------------------------------------------------

    def test_state_dir_override_flag_and_environment(self):
        flag_state = self.tmp / "flag-state"
        self.invoke("snapshot", state=flag_state, expect=0)
        self.assertTrue(self.state_file(state=flag_state).is_file())

        env_state = self.tmp / "env-state"
        env = dict(self.env, HOA_SCOPE_STATE=str(env_state))
        self.invoke("snapshot", state=None, env=env, expect=0)
        self.assertTrue(self.state_file(state=env_state).is_file())

    def test_two_repos_get_different_keys(self):
        second = self.make_repo("second")
        self.git(second, "commit", "-q", "--allow-empty", "-m", "init")
        self.invoke("snapshot", expect=0)
        subprocess.run([sys.executable, str(SCRIPT), "snapshot",
                        "--repo", str(second), "--label", "t",
                        "--state-file", str(self.state)],
                       check=True, capture_output=True, env=self.env)

        keys = sorted(path.name for path in self.state.iterdir() if path.is_dir())
        self.assertEqual(len(keys), 2, keys)
        self.assertNotEqual(keys[0], keys[1])
        self.assertEqual(len(keys[0]), 12)

    # -- refusals --------------------------------------------------------

    def test_nested_repository_refused(self):
        nested = self.repo / "nested"
        nested.mkdir()
        self.git(nested, "init", "-q")
        proc = self.invoke("snapshot", expect=2)
        self.assertIn("nested/", proc.stderr)
        self.assertIn("nested repository", proc.stderr)

    def test_dirty_submodule_refused(self):
        source = self.make_repo("submodule-source")
        self.write(source, "inside.txt", "one\n")
        self.commit(source, "inside")
        self.git(self.repo, "-c", "protocol.file.allow=always",
                 "submodule", "add", "-q", str(source), "sub")
        self.commit(self.repo, "add submodule")
        self.write(self.repo / "sub", "inside.txt", "one\ndirty\n")

        proc = self.invoke("snapshot", expect=2)
        self.assertIn("dirty submodule", proc.stderr)
        self.assertIn("sub", proc.stderr)


if __name__ == "__main__":
    unittest.main()
