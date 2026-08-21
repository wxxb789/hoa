from __future__ import annotations

import sys
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


if __name__ == "__main__":
    unittest.main()
