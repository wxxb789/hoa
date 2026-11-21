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
CREATIONFLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


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
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              text=True, env=self.env, creationflags=CREATIONFLAGS)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def raw_git(self, repo: Path, *args: str, input_bytes: bytes | None = None,
                env=None) -> bytes:
        proc = subprocess.run(["git", "-C", str(repo), *args], input=input_bytes,
                              capture_output=True, env=env or self.env,
                              creationflags=CREATIONFLAGS)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def commit(self, repo: Path, message: str) -> None:
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", message)

    def write(self, repo: Path, name: str, text: str) -> None:
        # Exact bytes: text mode would turn "\n" into "\r\n" on Windows and change the digest.
        (repo / name).write_bytes(text.encode("utf-8"))

    def invoke(self, *args: str, state=_DEFAULT, label="t", env=None,
               expect: int | None = None, repo=None):
        command = [sys.executable, str(SCRIPT), args[0], "--repo",
                   str(repo or self.repo), "--label", label]
        if state is _DEFAULT:
            state = self.state
        if state is not None:
            command += ["--state-file", str(state)]
        command += list(args[1:])
        proc = subprocess.run(command, capture_output=True, text=True,
                              env=env or self.env, creationflags=CREATIONFLAGS)
        if expect is not None:
            self.assertEqual(proc.returncode, expect,
                             f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        return proc

    def invoke_json(self, *args: str, state=_DEFAULT, label="t", env=None,
                    expect: int = 0) -> dict:
        proc = self.invoke(*args, "--json", state=state, label=label, env=env,
                           expect=expect)
        return json.loads(proc.stdout)

    def stage(self, repo: Path, *paths: str) -> None:
        self.git(repo, "add", "--", *paths)

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

    # -- commit-bound seal / verify --------------------------------------

    def test_index_seal_crlf_blob_verifies_on_commit(self):
        self.write(self.repo, "base.txt", "base\r\n")
        self.commit(self.repo, "base")
        self.git(self.repo, "config", "core.autocrlf", "true")
        self.invoke("snapshot", expect=0)
        # Disk bytes stay CRLF; the index normalizes them to LF.
        (self.repo / "crlf.txt").write_bytes(b"one\r\ntwo\r\n")
        self.stage(self.repo, "crlf.txt")
        self.invoke("diff", expect=0)
        seal = self.invoke_json("seal", "--index")["commit_seal"]
        staged = self.git(self.repo, "ls-files", "-s", "crlf.txt").split()[1]
        self.assertEqual(seal["paths"],
                         [{"path": "crlf.txt", "mode": "100644", "oid": staged}])
        self.git(self.repo, "commit", "-q", "-m", "work")
        self.assertTrue(self.invoke_json("verify", "--commit", "HEAD")["ok"])

    def test_commit_verify_ignores_dirty_worktree_and_index(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        self.write(self.repo, "new.txt", "two\n")
        self.write(self.repo, "scratch.txt", "scratch\n")
        self.stage(self.repo, "scratch.txt")
        result = self.invoke_json("verify", "--commit", "HEAD")
        self.assertTrue(result["ok"])
        self.assertEqual(result["paths"], 1)

    def test_index_seal_records_deletion_with_null_mode_and_oid(self):
        self.write(self.repo, "gone.txt", "gone\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.git(self.repo, "rm", "-q", "--", "gone.txt")
        self.invoke("diff", expect=0)
        seal = self.invoke_json("seal", "--index")["commit_seal"]
        self.assertEqual(seal["paths"],
                         [{"path": "gone.txt", "mode": None, "oid": None}])
        self.git(self.repo, "commit", "-q", "-m", "remove")
        self.assertTrue(self.invoke_json("verify", "--commit", "HEAD")["ok"])

    def test_empty_replacement_of_sealed_deletion_is_modified(self):
        self.write(self.repo, "gone.txt", "gone\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.git(self.repo, "rm", "-q", "--", "gone.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.write(self.repo, "gone.txt", "")
        self.stage(self.repo, "gone.txt")
        self.git(self.repo, "commit", "-q", "-m", "empty replacement")
        proc = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("modified", proc.stdout)
        self.assertIn('"gone.txt"', proc.stdout)

    def test_committed_content_change_after_seal_is_modified(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        self.write(self.repo, "new.txt", "two\n")
        self.stage(self.repo, "new.txt")
        self.git(self.repo, "commit", "-q", "-m", "rework")
        proc = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("modified", proc.stdout)
        self.assertIn('"new.txt"', proc.stdout)
        payload = self.invoke_json("verify", "--commit", "HEAD", expect=1)
        self.assertEqual(payload["drift"], [{"kind": "modified", "path": "new.txt"}])
        self.assertEqual(payload["commit"],
                         self.git(self.repo, "rev-parse", "HEAD").strip())

    def test_mode_only_change_after_seal_is_modified(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        self.git(self.repo, "update-index", "--chmod=+x", "new.txt")
        self.git(self.repo, "commit", "-q", "-m", "chmod")
        proc = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("modified", proc.stdout)
        self.assertIn('"new.txt"', proc.stdout)

    def test_unsealed_committed_path_is_added(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        self.write(self.repo, "extra.txt", "extra\n")
        self.stage(self.repo, "extra.txt")
        self.git(self.repo, "commit", "-q", "-m", "extra")
        proc = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("added", proc.stdout)
        self.assertIn('"extra.txt"', proc.stdout)

    def test_committed_baseline_exclusion_is_added(self):
        self.write(self.repo, "pre.txt", "base\n")
        self.commit(self.repo, "base")
        self.write(self.repo, "pre.txt", "base\ndirty\n")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        self.stage(self.repo, "pre.txt")
        self.git(self.repo, "commit", "-q", "-m", "accidental")
        proc = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("added", proc.stdout)
        self.assertIn('"pre.txt"', proc.stdout)

    def test_transient_add_then_remove_is_reported(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        self.write(self.repo, "scratch.txt", "scratch\n")
        self.stage(self.repo, "scratch.txt")
        self.git(self.repo, "commit", "-q", "-m", "scratch")
        self.git(self.repo, "rm", "-q", "--", "scratch.txt")
        self.git(self.repo, "commit", "-q", "-m", "unscratch")
        proc = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("transient", proc.stdout)
        self.assertIn('"scratch.txt"', proc.stdout)

    def test_merge_delta_only_against_non_first_parent_is_transient(self):
        self.write(self.repo, "shared.txt", "old\n")
        self.commit(self.repo, "root")
        older = self.git(self.repo, "rev-parse", "HEAD").strip()
        self.write(self.repo, "shared.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "sealed")
        self.git(self.repo, "checkout", "-q", "-b", "side", older)
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "empty side")
        self.git(self.repo, "checkout", "-q", "main")
        self.git(self.repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
        proc = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("transient", proc.stdout)
        self.assertIn('"shared.txt"', proc.stdout)

    def test_case_only_rename_keeps_both_spellings(self):
        self.write(self.repo, "Case.txt", "same\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.git(self.repo, "mv", "Case.txt", "case.txt")
        self.invoke("diff", expect=0)
        seal = self.invoke_json("seal", "--index")["commit_seal"]
        records = {entry["path"]: (entry["mode"], entry["oid"])
                   for entry in seal["paths"]}
        self.assertEqual(set(records), {"Case.txt", "case.txt"})
        self.assertIsNone(records["Case.txt"][0])
        self.assertIsNotNone(records["case.txt"][0])
        self.git(self.repo, "commit", "-q", "-m", "rename")
        result = self.invoke_json("verify", "--commit", "HEAD")
        self.assertEqual(result["scope_sha"], seal["scope_sha"])

    def test_non_ascii_path_in_commit_seal_json(self):
        name = "naïve-文件.txt"
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, name, "one\n")
        self.stage(self.repo, name)
        self.invoke("diff", expect=0)
        seal = self.invoke_json("seal", "--index")["commit_seal"]
        self.assertEqual([entry["path"] for entry in seal["paths"]], [name])
        self.git(self.repo, "commit", "-q", "-m", "work")
        result = self.invoke_json("verify", "--commit", "HEAD")
        self.assertEqual(result["scope_sha"], seal["scope_sha"])
        self.write(self.repo, name, "two\n")
        self.stage(self.repo, name)
        self.git(self.repo, "commit", "-q", "-m", "rework")
        proc = self.invoke("verify", "--commit", "HEAD", "--json", expect=1)
        drift = json.loads(proc.stdout)["drift"]
        self.assertEqual(drift, [{"kind": "modified", "path": name}])

    def test_index_seal_refuses_partially_staged_path(self):
        self.write(self.repo, "p.txt", "v1\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "p.txt", "v2\n")
        self.stage(self.repo, "p.txt")
        self.write(self.repo, "p.txt", "v3\n")
        self.invoke("diff", expect=0)
        proc = self.invoke("seal", "--index", expect=2)
        self.assertIn("unstaged", proc.stderr)
        self.assertIn("p.txt", proc.stderr)

    def test_index_seal_refuses_unstaged_new_path(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.invoke("diff", expect=0)
        proc = self.invoke("seal", "--index", expect=2)
        self.assertIn("unstaged", proc.stderr)
        self.assertIn("new.txt", proc.stderr)

    def test_index_seal_refuses_extra_staged_baseline_exclusion(self):
        self.write(self.repo, "pre.txt", "base\n")
        self.commit(self.repo, "base")
        self.write(self.repo, "pre.txt", "base\ndirty\n")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt", "pre.txt")
        self.invoke("diff", expect=0)
        proc = self.invoke("seal", "--index", expect=2)
        self.assertIn("staged", proc.stderr)
        self.assertIn("pre.txt", proc.stderr)

    def test_index_seal_refuses_unaccepted_overlap(self):
        self.write(self.repo, "shared.txt", "base\n")
        self.commit(self.repo, "base")
        self.write(self.repo, "shared.txt", "base\ndirty\n")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "shared.txt", "base\ndirty\nmore\n")
        self.stage(self.repo, "shared.txt")
        self.invoke("diff", expect=0)
        proc = self.invoke("seal", "--index", expect=2)
        self.assertIn("overlapping", proc.stderr)

    def test_index_seal_accepts_overlap_and_commit_verify_passes(self):
        self.write(self.repo, "shared.txt", "base\n")
        self.commit(self.repo, "base")
        self.write(self.repo, "shared.txt", "base\ndirty\n")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "shared.txt", "base\ndirty\nmore\n")
        self.stage(self.repo, "shared.txt")
        self.invoke("diff", expect=0)
        seal = self.invoke_json("seal", "--index", "--accept-overlap")["commit_seal"]
        self.assertTrue(seal["accepted_overlap"])
        self.assertEqual(seal["overlap_paths"], ["shared.txt"])
        self.git(self.repo, "commit", "-q", "-m", "work")
        self.assertTrue(self.invoke_json("verify", "--commit", "HEAD")["ok"])

    def test_verify_commit_refuses_without_index_seal(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke("seal", expect=0)
        proc = self.invoke("verify", "--commit", "HEAD", expect=2)
        self.assertIn("seal --index", proc.stderr)
        empty = self.invoke("verify", "--commit", "HEAD",
                            state=self.tmp / "empty", expect=2)
        self.assertIn("seal --index", empty.stderr)

    def test_commit_verify_refuses_non_descendant(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "checkout", "-q", "--orphan", "orphan")
        self.git(self.repo, "commit", "-q", "-m", "orphan")
        proc = self.invoke("verify", "--commit", "orphan", expect=2)
        self.assertIn("descend", proc.stderr)

    def test_index_seal_refuses_deleted_gitlink(self):
        source = self.make_repo("submodule-source")
        self.write(source, "inside.txt", "one\n")
        self.commit(source, "inside")
        self.git(self.repo, "-c", "protocol.file.allow=always",
                 "submodule", "add", "-q", str(source), "sub")
        self.commit(self.repo, "add submodule")
        self.invoke("snapshot", expect=0)
        self.git(self.repo, "rm", "-r", "-q", "sub")
        self.invoke("diff", expect=0)
        proc = self.invoke("seal", "--index", expect=2)
        self.assertIn("gitlink", proc.stderr)
        self.assertIn("sub", proc.stderr)

    def test_commit_verify_refuses_transient_gitlink(self):
        source = self.make_repo("submodule-source")
        self.write(source, "inside.txt", "one\n")
        self.commit(source, "inside")
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        self.git(self.repo, "-c", "protocol.file.allow=always",
                 "submodule", "add", "-q", str(source), "sub")
        self.commit(self.repo, "add submodule")
        self.git(self.repo, "rm", "-r", "-q", "sub")
        self.commit(self.repo, "drop submodule")
        proc = self.invoke("verify", "--commit", "HEAD", expect=2)
        self.assertIn("gitlink", proc.stderr)

    def test_commit_verify_reports_resolved_sha_for_non_head(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        work = self.git(self.repo, "rev-parse", "HEAD").strip()
        self.write(self.repo, "later.txt", "later\n")
        self.stage(self.repo, "later.txt")
        self.git(self.repo, "commit", "-q", "-m", "later")
        proc = self.invoke("verify", "--commit", "HEAD~1", expect=0)
        self.assertIn(f"commit: {work}", proc.stdout)
        self.assertEqual(self.invoke_json("verify", "--commit", "HEAD~1")["commit"],
                         work)

    def test_index_seal_refuses_shallow_repository(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        shallow = self.tmp / "shallow"
        self.git(self.tmp, "clone", "-q", "--depth", "1", self.repo.as_uri(),
                 str(shallow))
        subprocess.run([sys.executable, str(SCRIPT), "snapshot", "--repo", str(shallow),
                        "--label", "t", "--state-file", str(self.state)],
                       check=True, capture_output=True, env=self.env,
                       creationflags=CREATIONFLAGS)
        self.write(shallow, "new.txt", "one\n")
        self.invoke("diff", repo=shallow, expect=0)
        proc = self.invoke("seal", "--index", repo=shallow, expect=2)
        self.assertIn("shallow", proc.stderr)

    def test_commit_verify_refuses_active_graft(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        git_dir = Path(self.git(self.repo, "rev-parse", "--absolute-git-dir").strip())
        (git_dir / "info").mkdir(exist_ok=True)
        (git_dir / "info" / "grafts").write_bytes(b"deadbeef\n")
        proc = self.invoke("verify", "--commit", "HEAD", expect=2)
        self.assertIn("graft", proc.stderr)

    def test_whitespace_graft_override_is_refused_in_flagged_modes(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        graft_env = dict(self.env, GIT_GRAFT_FILE=" grafts")
        graft = self.repo / " grafts"
        graft.write_bytes(
            f"{self.git(self.repo, 'rev-parse', 'HEAD').strip()}\n".encode("ascii"))
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        refused = self.invoke("seal", "--index", env=graft_env, expect=2)
        self.assertIn("graft", refused.stderr)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        work = self.git(self.repo, "rev-parse", "HEAD").strip()
        self.write(self.repo, "scratch.txt", "scratch\n")
        self.stage(self.repo, "scratch.txt")
        self.git(self.repo, "commit", "-q", "-m", "scratch")
        self.git(self.repo, "rm", "-q", "--", "scratch.txt")
        self.git(self.repo, "commit", "-q", "-m", "unscratch")
        candidate = self.git(self.repo, "rev-parse", "HEAD").strip()

        plain = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("transient", plain.stdout)
        self.assertIn('"scratch.txt"', plain.stdout)

        graft.write_bytes(f"{candidate} {work}\n".encode("ascii"))
        plain_parents = self.git(self.repo, "rev-list", "--parents", "-n", "1",
                                 "HEAD").split()[1:]
        grafted_parents = self.raw_git(self.repo, "rev-list", "--parents", "-n", "1",
                                       "HEAD", env=graft_env).decode().split()[1:]
        self.assertEqual(plain_parents,
                         [self.git(self.repo, "rev-parse", "HEAD~1").strip()])
        self.assertEqual(grafted_parents, [work])

        refused = self.invoke("verify", "--commit", "HEAD", env=graft_env, expect=2)
        self.assertIn("graft", refused.stderr)

    def test_index_seal_refuses_file_to_directory_transition(self):
        (self.repo / "outer").mkdir()
        self.write(self.repo, "outer/leaf.txt", "leaf\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.invoke("diff", expect=0)
        self.git(self.repo, "rm", "-q", "-r", "outer")
        shutil.rmtree(self.repo / "outer", ignore_errors=True)
        self.write(self.repo, "outer", "now a file\n")
        self.stage(self.repo, "outer")
        proc = self.invoke("seal", "--index", expect=2)
        self.assertIn('"outer"', proc.stderr)
        self.assertIn('"outer/leaf.txt"', proc.stderr)

    def test_index_seal_refuses_directory_to_file_transition(self):
        self.write(self.repo, "outer", "was a file\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.invoke("diff", expect=0)
        self.git(self.repo, "rm", "-q", "--", "outer")
        (self.repo / "outer").mkdir()
        self.write(self.repo, "outer/leaf.txt", "leaf\n")
        self.stage(self.repo, "outer/leaf.txt")
        proc = self.invoke("seal", "--index", expect=2)
        self.assertIn('"outer"', proc.stderr)
        self.assertIn('"outer/leaf.txt"', proc.stderr)

    def test_commit_verify_refuses_undecodable_git_path(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        work = self.git(self.repo, "rev-parse", "HEAD").strip()
        blob = self.raw_git(self.repo, "hash-object", "-w", "--stdin",
                            input_bytes=b"raw\n").strip().decode("ascii")
        tree_input = self.raw_git(self.repo, "ls-tree", "-z", work)
        tree_input += b"100644 blob " + blob.encode("ascii") + b"\tbad-\xff.txt\0"
        tree = self.raw_git(self.repo, "mktree", "-z",
                            input_bytes=tree_input).strip().decode("ascii")
        candidate = self.git(self.repo, "commit-tree", tree, "-p", work,
                             "-m", "raw path").strip()
        proc = self.invoke("verify", "--commit", candidate)
        if os.name == "nt":
            self.assertEqual(proc.returncode, 2,
                             f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn(r"bad-\xff.txt", proc.stderr)
            self.assertIn("cannot be decoded", proc.stderr)
        else:
            self.assertEqual(proc.returncode, 1,
                             f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("added", proc.stdout)

    def test_index_seal_preserves_legacy_diff_and_seal_receipts(self):
        self.write(self.repo, "shared.txt", "base\n")
        self.commit(self.repo, "base")
        self.write(self.repo, "shared.txt", "base\ndirty\n")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "shared.txt", "base\ndirty\nmore\n")
        self.invoke("diff", expect=0)
        self.invoke("seal", "--accept-overlap", expect=0)
        before = json.loads(self.state_file().read_text(encoding="utf-8"))
        self.stage(self.repo, "shared.txt")
        refused = self.invoke("seal", "--index", expect=2)
        self.assertIn("overlapping", refused.stderr)
        after_refusal = json.loads(self.state_file().read_text(encoding="utf-8"))
        self.assertEqual(after_refusal["diff"], before["diff"])
        self.assertEqual(after_refusal["seal"], before["seal"])
        self.invoke_json("seal", "--index", "--accept-overlap")
        after = json.loads(self.state_file().read_text(encoding="utf-8"))
        self.assertEqual(after["diff"], before["diff"])
        self.assertEqual(after["seal"], before["seal"])
        payload = self.invoke_json("status")
        self.assertEqual(payload["diff"], before["diff"])
        self.assertEqual(payload["seal"], before["seal"])

    def test_commit_verify_refuses_malformed_commit_seal(self):
        self.write(self.repo, "gone.txt", "gone\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.git(self.repo, "rm", "-q", "--", "gone.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "remove")
        path = self.state_file()
        original = json.loads(path.read_text(encoding="utf-8"))

        def reinstall(seal):
            state = json.loads(json.dumps(original))
            state["commit_seal"] = seal
            path.write_text(json.dumps(state), encoding="utf-8")

        broken = json.loads(json.dumps(original["commit_seal"]))
        broken["paths"] = [{"path": "gone.txt"}]
        reinstall(broken)
        proc = self.invoke("verify", "--commit", "HEAD", expect=2)
        self.assertIn('"gone.txt"', proc.stderr)
        self.assertIn("explicit mode and oid", proc.stderr)

        broken = json.loads(json.dumps(original["commit_seal"]))
        del broken["scope_sha"]
        reinstall(broken)
        proc = self.invoke("verify", "--commit", "HEAD", expect=2)
        self.assertIn("scope_sha", proc.stderr)

        broken = json.loads(json.dumps(original["commit_seal"]))
        broken["scope_sha"] = "0" * 64
        reinstall(broken)
        proc = self.invoke("verify", "--commit", "HEAD", expect=2)
        self.assertIn("does not match", proc.stderr)

        broken = json.loads(json.dumps(original["commit_seal"]))
        broken["paths"] = [{"path": "gone.txt", "mode": "100644", "oid": "abc"}]
        reinstall(broken)
        proc = self.invoke("verify", "--commit", "HEAD", expect=2)
        self.assertIn("invalid oid", proc.stderr)

        broken = json.loads(json.dumps(original["commit_seal"]))
        broken["paths"] = [{"path": "gone.txt", "mode": "160000", "oid": "0" * 40}]
        reinstall(broken)
        proc = self.invoke("verify", "--commit", "HEAD", expect=2)
        self.assertIn("unsupported mode", proc.stderr)

        broken = json.loads(json.dumps(original["commit_seal"]))
        broken["paths"] = [{"path": "gone.txt", "mode": None, "oid": None},
                           {"path": "gone.txt/leaf.txt", "mode": None, "oid": None}]
        reinstall(broken)
        proc = self.invoke("verify", "--commit", "HEAD", expect=2)
        self.assertIn('"gone.txt/leaf.txt"', proc.stderr)

    def test_index_seal_refuses_missing_staging_with_accepted_overlap(self):
        self.write(self.repo, "p.txt", "v1\n")
        self.commit(self.repo, "base")
        self.write(self.repo, "p.txt", "dirty\n")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "p.txt", "v1\n")
        self.invoke("diff", expect=0)
        proc = self.invoke("seal", "--index", "--accept-overlap", expect=2)
        self.assertIn("missing", proc.stderr)
        self.assertIn("p.txt", proc.stderr)

    def test_commit_verify_sees_through_replacement_ref(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        work = self.git(self.repo, "rev-parse", "HEAD").strip()
        self.write(self.repo, "scratch.txt", "scratch\n")
        self.stage(self.repo, "scratch.txt")
        self.git(self.repo, "commit", "-q", "-m", "scratch")
        self.git(self.repo, "rm", "-q", "--", "scratch.txt")
        self.git(self.repo, "commit", "-q", "-m", "unscratch")
        candidate = self.git(self.repo, "rev-parse", "HEAD").strip()
        tree = self.git(self.repo, "rev-parse", f"{candidate}^{{tree}}").strip()
        replacement = self.git(self.repo, "commit-tree", tree, "-p", work,
                               "-m", "replacement").strip()
        self.git(self.repo, "replace", candidate, replacement)
        live = self.git(self.repo, "rev-list", "--parents", "-n", "1", "HEAD")
        self.assertEqual(live.split()[1:], [work])
        proc = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("transient", proc.stdout)
        self.assertIn('"scratch.txt"', proc.stdout)

    def test_commit_verify_root_fallback_flags_base_matching_root(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        base = self.git(self.repo, "rev-parse", "HEAD").strip()
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        self.invoke_json("seal", "--index")
        self.git(self.repo, "commit", "-q", "-m", "work")
        root = self.git(self.repo, "commit-tree", f"{base}^{{tree}}", "-m",
                        "unrelated root").strip()
        self.git(self.repo, "update-ref", "refs/heads/side", root)
        self.git(self.repo, "merge", "-q", "--no-ff", "--allow-unrelated-histories",
                 "-m", "merge side", "side")
        proc = self.invoke("verify", "--commit", "HEAD", expect=1)
        self.assertIn("transient", proc.stdout)
        self.assertIn('"base.txt"', proc.stdout)

    def test_commit_seal_scope_sha_matches_independent_record_hash(self):
        self.write(self.repo, "gone.txt", "gone\n")
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.git(self.repo, "rm", "-q", "--", "gone.txt")
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        seal = self.invoke_json("seal", "--index")["commit_seal"]
        self.assertEqual([entry["path"] for entry in seal["paths"]],
                         ["gone.txt", "new.txt"])
        digest = hashlib.sha256()
        for entry in sorted(seal["paths"], key=lambda item: item["path"]):
            digest.update(entry["path"].encode("utf-8"))
            digest.update(b"\0")
            digest.update((entry["mode"] or "").encode("ascii"))
            digest.update(b"\0")
            digest.update((entry["oid"] or "").encode("ascii"))
            digest.update(b"\n")
        self.assertEqual(seal["scope_sha"], digest.hexdigest())

    def test_index_seal_prints_full_scope_sha(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.write(self.repo, "new.txt", "one\n")
        self.stage(self.repo, "new.txt")
        self.invoke("diff", expect=0)
        seal = self.invoke_json("seal", "--index")["commit_seal"]
        proc = self.invoke("seal", "--index", expect=0)
        self.assertEqual(len(seal["scope_sha"]), 64)
        self.assertIn(seal["scope_sha"], proc.stdout)

    def test_index_seal_sees_committed_rename_with_renames_enabled(self):
        self.write(self.repo, "old.txt", "one\ntwo\nthree\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.git(self.repo, "mv", "old.txt", "new.txt")
        self.git(self.repo, "commit", "-q", "-m", "rename")
        self.git(self.repo, "config", "diff.renames", "true")
        self.invoke("diff", expect=0)
        seal = self.invoke_json("seal", "--index")["commit_seal"]
        records = {entry["path"]: (entry["mode"], entry["oid"])
                   for entry in seal["paths"]}
        self.assertEqual(set(records), {"old.txt", "new.txt"})
        self.assertIsNone(records["old.txt"][0])
        self.assertIsNotNone(records["new.txt"][0])

    def test_index_seal_quotes_flagged_diagnostic_paths(self):
        self.write(self.repo, "base.txt", "base\n")
        self.commit(self.repo, "base")
        self.invoke("snapshot", expect=0)
        self.invoke("diff", expect=0)
        nested = self.repo / "nested dir"
        nested.mkdir()
        self.git(nested, "init", "-q")
        proc = self.invoke("seal", "--index", expect=2)
        self.assertIn('"nested dir/"', proc.stderr)

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
                       check=True, capture_output=True, env=self.env,
                       creationflags=CREATIONFLAGS)

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
