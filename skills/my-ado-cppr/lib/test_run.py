from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

import run as commit_push_pr  # noqa: E402


class ReviewerFlowTests(unittest.TestCase):
    def _apply_ado_create(self, reviewer_ok: bool):
        calls: list[str] = []

        def create_pr(
            _repo,
            *,
            source_branch,
            target_branch,
            title,
            description,
            draft=False,
            debug=False,
        ):
            self.assertEqual(_repo, {"repo": "repo", "organization_url": "https://example"})
            self.assertEqual(source_branch, "feature/test")
            self.assertEqual(target_branch, "main")
            self.assertEqual((title, description), ("Test", "Test"))
            self.assertFalse(draft)
            self.assertFalse(debug)
            return {
                "ok": True,
                "pr_id": "42",
                "pr_url": "https://example/pr/42",
            }

        provider = SimpleNamespace(
            NAME="ado",
            AUTH_REMEDY="az login",
            parse_remote=lambda _url: {"repo": "repo", "organization_url": "https://example"},
            check_auth=lambda **_kwargs: (True, {}),
            create_pr=create_pr,
            add_reviewers=lambda _repo, pr_id, reviewers, **_kwargs: (
                calls.append(f"reviewers:{pr_id}:{','.join(reviewers)}") or reviewer_ok,
                "" if reviewer_ok else "reviewer lookup failed",
            ),
            set_auto_complete=lambda _repo, pr_id, **_kwargs: (
                calls.append(f"auto_complete:{pr_id}") or True,
                "",
            ),
            get_pr_status=lambda *_args, **_kwargs: {"pullRequestId": 42},
        )
        state_data = commit_push_pr.state.new_state(
            provider="ado",
            remote_url="https://dev.azure.com/org/project/_git/repo",
            branch="feature/test",
            head_at_start="abc123",
        )
        plan = {
            "provider": "ado",
            "pr": {
                "action": "create",
                "title": "Test",
                "description": "Test",
                "reviewers": ["reviewer@example.com"],
                "auto_complete": True,
            },
        }

        with (
            patch.object(commit_push_pr, "_get_provider_by_name", return_value=provider),
            patch.object(commit_push_pr.git, "git_root", return_value="repo"),
            patch.object(commit_push_pr.git, "current_branch", return_value="feature/test"),
            patch.object(
                commit_push_pr.git,
                "remote_origin_url",
                return_value="https://dev.azure.com/org/project/_git/repo",
            ),
            patch.object(commit_push_pr.git, "head_sha", return_value="abc123"),
            patch.object(commit_push_pr.state, "new_state", return_value=state_data),
            patch.object(commit_push_pr.state, "save"),
            patch.object(commit_push_pr.state, "clear"),
        ):
            result = commit_push_pr.apply(plan, repo_root="repo")

        return result, calls

    def test_ado_create_adds_reviewers_before_auto_complete(self) -> None:
        result, calls = self._apply_ado_create(reviewer_ok=True)

        self.assertTrue(result["ok"])
        self.assertEqual(
            calls,
            ["reviewers:42:reviewer@example.com", "auto_complete:42"],
        )
        self.assertIn("pr_reviewers", result["summary"]["succeeded"])

    def test_ado_reviewer_failure_stops_before_auto_complete(self) -> None:
        result, calls = self._apply_ado_create(reviewer_ok=False)

        self.assertFalse(result["ok"])
        self.assertEqual(calls, ["reviewers:42:reviewer@example.com"])
        self.assertIn("pr_reviewers", result["summary"]["failed"])


class ValidatePlanTests(unittest.TestCase):
    def test_both_pr_and_provider_alias_rejected(self):
        # Same check, parametrized over the provider alias ("pr" + "ado_pr"
        # vs "pr" + "github_pr"); one code path in _validate_plan.
        for provider, alias in (("ado", "ado_pr"), ("github", "github_pr")):
            err = commit_push_pr._validate_plan(
                {"pr": {"action": "create"}, alias: {"action": "create"}}, provider
            )
            self.assertIn("use only one", err)

    def test_pr_alias_alone_ok(self):
        self.assertIsNone(
            commit_push_pr._validate_plan({"ado_pr": {"action": "create"}}, "ado")
        )

    def test_invalid_pr_action(self):
        err = commit_push_pr._validate_plan({"pr": {"action": "reopen"}}, "ado")
        self.assertIn("pr.action must be", err)

    def test_update_requires_id(self):
        err = commit_push_pr._validate_plan({"pr": {"action": "update"}}, "ado")
        self.assertIn("requires pr.id", err)

    def test_branch_create_requires_name(self):
        err = commit_push_pr._validate_plan({"branch": {"create": True}}, "ado")
        self.assertIn("requires branch.name", err)

    def test_commit_requires_message(self):
        err = commit_push_pr._validate_plan({"commit": {"do": True}}, "ado")
        self.assertIn("commit.message", err)

    def test_commit_amend_without_message_ok(self):
        self.assertIsNone(
            commit_push_pr._validate_plan({"commit": {"do": True, "amend": True}}, "ado")
        )

    def test_blank_commit_message_rejected(self):
        err = commit_push_pr._validate_plan({"commit": {"do": True, "message": "  "}}, "ado")
        self.assertIsNotNone(err)


class ResolveProviderTests(unittest.TestCase):
    def test_ado_urls_autodetect(self):
        for url in (
            "https://dev.azure.com/org/proj/_git/repo",
            "https://org.visualstudio.com/proj/_git/repo",
            "git@ssh.dev.azure.com:v3/org/proj/repo",
        ):
            prov, err = commit_push_pr.resolve_provider(url)
            self.assertIsNone(err)
            self.assertEqual(prov.NAME, "ado")

    def test_github_url_autodetects(self):
        prov, err = commit_push_pr.resolve_provider("https://github.com/org/repo.git")
        self.assertIsNone(err)
        self.assertEqual(prov.NAME, "github")

    def test_unknown_remote_errors(self):
        prov, err = commit_push_pr.resolve_provider("https://gitlab.com/org/repo")
        self.assertIsNone(prov)
        self.assertIn("Could not detect provider", err)

    def test_explicit_name_wins(self):
        prov, err = commit_push_pr.resolve_provider(
            "https://dev.azure.com/org/proj/_git/repo", "github"
        )
        self.assertIsNone(err)
        self.assertEqual(prov.NAME, "github")


class FinalizeResultTests(unittest.TestCase):
    def _result(self, steps, **art):
        return {
            "meta": {},
            "steps": steps,
            "artifacts": {"branch": "feature/x", **art},
        }

    def test_ok_when_only_warning_steps_fail(self):
        r = self._result(
            [{"name": "push", "ok": True},
             {"name": "pr_labels", "ok": False, "severity": "warning", "error": "not wired"}],
        )
        commit_push_pr._finalize_result(r)
        self.assertTrue(r["ok"])
        self.assertIn("pr_labels", r["summary"]["warnings"])
        self.assertNotIn("pr_labels", r["summary"]["failed"])

    def test_hard_failure_flips_ok_and_synthesizes_error(self):
        r = self._result(
            [{"name": "commit", "ok": True},
             {"name": "push", "ok": False, "error": "rejected"}],
        )
        commit_push_pr._finalize_result(r)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "push: rejected")

    def test_headline_prefers_pr_update_over_create(self):
        r = self._result(
            [{"name": "pr_create", "ok": True}, {"name": "pr_update", "ok": True}],
            pr_id="42", pr_url="https://x/42",
        )
        commit_push_pr._finalize_result(r)
        self.assertTrue(r["headline"].startswith("Updated PR #42"))

    def test_headline_falls_back_to_push_then_commit(self):
        pushed = self._result([{"name": "push", "ok": True}])
        commit_push_pr._finalize_result(pushed)
        self.assertEqual(pushed["headline"], "Pushed branch feature/x")

        committed = self._result([{"name": "commit", "ok": True}], commit_sha="abcdef1234")
        commit_push_pr._finalize_result(committed)
        self.assertEqual(committed["headline"], "Committed abcdef12")


class SplitPorcelainTests(unittest.TestCase):
    def test_staged_unstaged_untracked(self):
        staged, unstaged, untracked = commit_push_pr.git._split_porcelain(
            ["M  src/a.py", " M src/b.py", "?? new.txt", "A  added.py"]
        )
        self.assertEqual(staged, ["src/a.py", "added.py"])
        self.assertEqual(unstaged, ["src/b.py"])
        self.assertEqual(untracked, ["new.txt"])

    def test_rename_keeps_new_path(self):
        staged, _, _ = commit_push_pr.git._split_porcelain(["R  old.txt -> new.txt"])
        self.assertEqual(staged, ["new.txt"])

    def test_short_lines_skipped(self):
        staged, unstaged, untracked = commit_push_pr.git._split_porcelain(["", "M "])
        self.assertEqual((staged, unstaged, untracked), ([], [], []))


class CommitScopeTests(unittest.TestCase):
    def _git(self, root: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def _repo(self) -> Path:
        directory = tempfile.TemporaryDirectory(prefix="cppr-scope-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self._git(root, "init", "-q")
        self._git(root, "config", "user.name", "Fixture")
        self._git(root, "config", "user.email", "fixture@example.invalid")
        (root / "selected.txt").write_text("base\n", encoding="utf-8")
        (root / "unrelated.txt").write_text("base\n", encoding="utf-8")
        self._git(root, "add", "selected.txt", "unrelated.txt")
        self._git(root, "commit", "-qm", "baseline")
        self._git(root, "checkout", "-qb", "feature/scope")
        return root

    def _committed_paths(self, root: Path) -> set[str]:
        return set(self._git(root, "show", "--pretty=format:", "--name-only", "HEAD").splitlines())

    def test_paths_commit_excludes_other_staged_files(self):
        root = self._repo()
        (root / "selected.txt").write_text("selected update\n", encoding="utf-8")
        (root / "unrelated.txt").write_text("unrelated update\n", encoding="utf-8")
        self._git(root, "add", "unrelated.txt")

        commit_push_pr.git.commit_with_paths("selected only", ["selected.txt"], cwd=str(root))

        self.assertEqual(self._committed_paths(root), {"selected.txt"})
        self.assertEqual(self._git(root, "diff", "--cached", "--name-only"), "unrelated.txt")

    def test_paths_commit_treats_metacharacters_as_literal_filenames(self):
        root = self._repo()
        (root / "src").mkdir()
        for name in ("[id].tsx", "i.tsx"):
            (root / "src" / name).write_text("base\n", encoding="utf-8")
        self._git(root, "add", "src")
        self._git(root, "commit", "-qm", "fixture files")
        (root / "src" / "[id].tsx").write_text("selected update\n", encoding="utf-8")
        (root / "src" / "i.tsx").write_text("unrelated update\n", encoding="utf-8")
        self._git(root, "add", "src/i.tsx")

        commit_push_pr.git.commit_with_paths("literal path", ["src/[id].tsx"], cwd=str(root))

        self.assertEqual(self._committed_paths(root), {"src/[id].tsx"})
        self.assertEqual(self._git(root, "diff", "--cached", "--name-only"), "src/i.tsx")

    def test_paths_commit_includes_selected_deletion_only(self):
        root = self._repo()
        (root / "selected.txt").unlink()
        (root / "unrelated.txt").write_text("unrelated update\n", encoding="utf-8")
        self._git(root, "add", "unrelated.txt")

        commit_push_pr.git.commit_with_paths("delete selected", ["selected.txt"], cwd=str(root))

        self.assertEqual(self._committed_paths(root), {"selected.txt"})
        self.assertEqual(self._git(root, "diff", "--cached", "--name-only"), "unrelated.txt")

    def test_amend_paths_keeps_other_staged_files(self):
        root = self._repo()
        (root / "selected.txt").write_text("first update\n", encoding="utf-8")
        commit_push_pr.git.commit_with_paths("selected only", ["selected.txt"], cwd=str(root))
        (root / "selected.txt").write_text("amended update\n", encoding="utf-8")
        (root / "unrelated.txt").write_text("unrelated update\n", encoding="utf-8")
        self._git(root, "add", "unrelated.txt")

        commit_push_pr.git.commit_with_paths("", ["selected.txt"], amend=True, cwd=str(root))

        self.assertEqual(self._committed_paths(root), {"selected.txt"})
        self.assertEqual(self._git(root, "diff", "--cached", "--name-only"), "unrelated.txt")

    def test_apply_stages_only_explicitly_authorized_changes(self):
        for stage_all, expected in ((None, {"selected.txt"}),
                                    (True, {"selected.txt", "extra.txt"})):
            with self.subTest(stage_all=stage_all):
                root = self._repo()
                self._git(root, "remote", "add", "origin", "https://dev.azure.com/org/project/_git/repo")
                (root / "selected.txt").write_text("selected update\n", encoding="utf-8")
                self._git(root, "add", "selected.txt")
                (root / "extra.txt").write_text("untracked extra\n", encoding="utf-8")
                provider = SimpleNamespace(
                    NAME="ado", AUTH_REMEDY="az login",
                    parse_remote=lambda url: {"repository": url},
                    check_auth=lambda **_kwargs: (True, {}),
                )
                plan = {"provider": "ado", "commit": {"do": True, "message": "scoped"}}
                if stage_all is not None:
                    plan["commit"]["stage_all"] = stage_all
                previous = Path.cwd()
                try:
                    os.chdir(root)
                    with patch.object(commit_push_pr, "_get_provider_by_name", return_value=provider):
                        result = commit_push_pr.apply(plan, repo_root=str(root))
                finally:
                    os.chdir(previous)

                self.assertTrue(result["ok"], result)
                self.assertEqual(self._committed_paths(root), expected)

    def test_apply_rejects_empty_or_conflicting_path_scopes_before_writes(self):
        invalid = (
            {"paths": []},
            {"paths": [], "stage_all": True},
            {"paths": ["selected.txt"], "stage_all": True},
            {"stage_all": "false"},
        )
        for selection in invalid:
            with self.subTest(selection=selection):
                root = self._repo()
                self._git(root, "remote", "add", "origin", "https://dev.azure.com/org/project/_git/repo")
                (root / "unrelated.txt").write_text("staged unrelated update\n", encoding="utf-8")
                self._git(root, "add", "unrelated.txt")
                (root / "extra.txt").write_text("untracked extra\n", encoding="utf-8")
                original_head = self._git(root, "rev-parse", "HEAD")
                provider = SimpleNamespace(
                    NAME="ado", AUTH_REMEDY="az login",
                    parse_remote=lambda url: {"repository": url},
                    check_auth=lambda **_kwargs: (True, {}),
                )
                plan = {"provider": "ado", "commit": {"do": True, "message": "scoped", **selection}}
                previous = Path.cwd()
                try:
                    os.chdir(root)
                    with patch.object(commit_push_pr, "_get_provider_by_name", return_value=provider):
                        result = commit_push_pr.apply(plan, repo_root=str(root))
                finally:
                    os.chdir(previous)
                self.assertFalse(result["ok"], result)
                self.assertEqual(self._git(root, "rev-parse", "HEAD"), original_head)
                self.assertEqual(self._git(root, "diff", "--cached", "--name-only"), "unrelated.txt")
                self.assertTrue((root / "extra.txt").exists())

if __name__ == "__main__":
    unittest.main()
