#!/usr/bin/env python3
"""Exercise the CI release entry point with real Git and isolated local remotes.

Run: python scripts/test_release.py
No test contacts a network remote or changes this checkout's Git state.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / ".tmp-artifacts" / "release-tests"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="case-", dir=ARTIFACTS)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = self.root / "remote.git"
        self.seed = self.root / "seed"
        self.runner_count = 0
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("GIT_", "GITHUB_"))
        }
        self.env.update({
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        })
        self.git(self.root, "init", "--quiet", "--bare", "--initial-branch=main", str(self.remote))
        self.seed.mkdir()
        self.git(self.seed, "init", "--quiet", "--initial-branch=main")
        self.git(self.seed, "config", "user.name", "Release fixture")
        self.git(self.seed, "config", "user.email", "fixture@example.invalid")
        self.git(self.seed, "config", "core.autocrlf", "false")
        (self.seed / "scripts").mkdir()
        for filename in ("release.py", "version.py", "generate_index.py", "skill_metadata.py"):
            shutil.copyfile(ROOT / "scripts" / filename, self.seed / "scripts" / filename)
        self.write(self.seed, ".gitignore", "__pycache__/\n*.py[cod]\n")
        self.write(self.seed, "VERSION", "0.1.0\n")
        self.write(self.seed, "skills/custom/SKILL.md", self.skill("custom", "0.1.0", custom=True))
        for folder in ("agents", "orchestration", "rules", "prompts", "workflows", "mcps"):
            self.write(self.seed, f"{folder}/{folder}-fixture.md", self.skill(f"{folder}-fixture", "7.0.0"))
        self.write(self.seed, "ref/vendor/SKILL.md", self.skill("third-party", "9.8.7"))
        self.write(self.seed, "notes.txt", "Unrelated committed content.\n")
        self.command(self.seed, sys.executable, "scripts/version.py", "sync")
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "--quiet", "-m", "Fixture initial state")
        self.git(self.seed, "remote", "add", "origin", str(self.remote))
        self.git(self.seed, "push", "--quiet", "origin", "main")
        self.initial = self.git(self.seed, "rev-parse", "HEAD").stdout.strip()

    @staticmethod
    def skill(name, version, *, custom=False):
        metadata = (f'metadata:\n  version: "{version}"\n'
                    '  areas: software-development\n  targets: runtime-agnostic\n'
                    '  owner: unchanged\n') if custom else ""
        index = ("" if custom else
                 f"<!-- index: areas=software-development; targets=runtime-agnostic; version={version} -->\n\n")
        return (
            f"---\nname: {name}\ndescription: {name} fixture behavior.\n{metadata}---\n\n"
            f"{index}# {name}\n\n<!-- Template: preserve this body comment. -->\n"
            "Keep this body unchanged.\n"
        )

    @staticmethod
    def write(root, relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def command(self, cwd, *args, check=True, env=None):
        result = subprocess.run(
            args, cwd=cwd, env=self.env if env is None else env,
            text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if check and result.returncode:
            self.fail(f"{args!r} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
        return result

    def git(self, cwd, *args, check=True):
        return self.command(cwd, "git", *args, check=check)

    def refs(self):
        return self.git(self.remote, "for-each-ref", "--format=%(refname) %(objectname)").stdout

    def remote_head(self):
        return self.git(self.remote, "rev-parse", "refs/heads/main").stdout.strip()

    def runner(self, sha=None):
        self.runner_count += 1
        root = self.root / f"runner-{self.runner_count}"
        self.git(self.root, "clone", "--quiet", str(self.remote), str(root))
        self.git(root, "checkout", "--quiet", "--detach", sha or self.remote_head())
        return root

    def release(self, root, *, event="push", part=None, overrides=None, check=True):
        env = self.env | {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": event,
            "GITHUB_SHA": self.git(root, "rev-parse", "HEAD").stdout.strip(),
        }
        env.update(overrides or {})
        args = [sys.executable, "scripts/release.py"]
        if part is not None:
            args.extend(("--part", part))
        return self.command(root, *args, env=env, check=check)

    def tag_initial(self):
        self.git(self.seed, "tag", "v0.1.0")
        self.git(self.seed, "push", "--quiet", "origin", "refs/tags/v0.1.0")

    def advance_main(self):
        self.write(self.seed, "notes.txt", "A normal tested main update.\n")
        self.git(self.seed, "add", "notes.txt")
        self.git(self.seed, "commit", "--quiet", "-m", "Normal main update")
        self.git(self.seed, "push", "--quiet", "origin", "main")
        return self.remote_head()

    def assert_published(self, version):
        self.assertEqual(self.git(self.remote, "show", "refs/heads/main:VERSION").stdout, version + "\n")
        self.assertEqual(
            self.git(self.remote, "rev-parse", f"refs/tags/v{version}^{{commit}}").stdout.strip(),
            self.remote_head(),
        )

    def test_first_release_publishes_current_version_without_commit(self):
        runner = self.runner()
        result = self.release(runner)
        self.assertIn("Published v0.1.0", result.stdout)
        self.assert_published("0.1.0")
        self.assertEqual(self.remote_head(), self.initial)
        self.assertEqual(self.git(runner, "status", "--porcelain").stdout, "")

    def test_untagged_initial_dispatch_does_not_bump(self):
        self.release(self.runner(), event="workflow_dispatch", part="major")
        self.assert_published("0.1.0")
        self.assertEqual(self.remote_head(), self.initial)

    def test_subsequent_push_defaults_patch_and_preserves_unrelated_changes(self):
        self.tag_initial()
        tested = self.advance_main()
        runner = self.runner()
        original_skill = (runner / "skills/custom/SKILL.md").read_text(encoding="utf-8")
        self.write(runner, "notes.txt", "Keep this unrelated working-tree edit.\n")
        vendor = "Keep this staged third-party edit.\n"
        self.write(runner, "ref/vendor/SKILL.md", vendor)
        self.git(runner, "add", "ref/vendor/SKILL.md")
        self.write(runner, "untracked.txt", "Keep this untracked file.\n")
        self.release(runner)
        self.assert_published("0.1.1")
        changed = set(self.git(self.remote, "diff-tree", "--no-commit-id", "--name-only", "-r", "main").stdout.splitlines())
        self.assertTrue({"VERSION", "skills/custom/SKILL.md"} <= changed)
        self.assertTrue(changed <= {"VERSION", "skills/custom/SKILL.md", "index.md", "index.zh-CN.md"})
        self.assertEqual(self.git(self.remote, "rev-parse", "main^").stdout.strip(), tested)
        self.assertEqual(
            (runner / "skills/custom/SKILL.md").read_text(encoding="utf-8"),
            original_skill.replace('version: "0.1.0"', 'version: "0.1.1"'),
        )
        self.assertEqual((runner / "notes.txt").read_text(encoding="utf-8"), "Keep this unrelated working-tree edit.\n")
        self.assertEqual((runner / "ref/vendor/SKILL.md").read_text(encoding="utf-8"), vendor)
        self.assertEqual(self.git(runner, "diff", "--cached", "--name-only").stdout, "ref/vendor/SKILL.md\n")
        self.assertTrue((runner / "untracked.txt").is_file())
        self.assertIn("version=9.8.7", self.git(self.remote, "show", "main:ref/vendor/SKILL.md").stdout)
        self.assertIn("version=7.0.0", self.git(self.remote, "show", "main:agents/agents-fixture.md").stdout)
        self.command(runner, sys.executable, "scripts/version.py", "check")

    def check_dispatch(self, part, expected):
        self.tag_initial()
        self.release(self.runner(), event="workflow_dispatch", part=part)
        self.assert_published(expected)
        self.assertEqual(self.git(self.remote, "rev-parse", "main^").stdout.strip(), self.initial)

    def test_dispatch_minor(self):
        self.check_dispatch("minor", "0.2.0")

    def test_dispatch_major(self):
        self.check_dispatch("major", "1.0.0")

    def test_tagged_current_head_push_is_noop_including_rerun(self):
        self.tag_initial()
        self.advance_main()
        self.release(self.runner())
        before = self.refs()
        runner = self.runner()
        for _ in range(2):
            result = self.release(runner)
            self.assertIn("already published", result.stdout)
            self.assertEqual(self.refs(), before)
            self.assertEqual(self.git(runner, "status", "--porcelain").stdout, "")

    def test_stale_tested_head_is_reported_without_publishing(self):
        runner = self.runner()
        self.advance_main()
        before = self.refs()
        result = self.release(runner)
        self.assertIn("Skipped stale tested head", result.stdout)
        self.assertEqual(self.refs(), before)
        self.assertEqual(self.git(runner, "rev-parse", "HEAD").stdout.strip(), self.initial)
        self.assertEqual((runner / "VERSION").read_text(encoding="utf-8"), "0.1.0\n")

    def test_next_version_tag_collision_does_not_change_remote(self):
        self.tag_initial()
        self.git(self.seed, "tag", "v0.1.1")
        self.git(self.seed, "push", "--quiet", "origin", "refs/tags/v0.1.1")
        self.advance_main()
        runner = self.runner()
        before = self.refs()
        result = self.release(runner, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tag collision", result.stderr)
        self.assertEqual(self.refs(), before)
        self.assertEqual(self.git(runner, "rev-parse", "HEAD").stdout.strip(), self.remote_head())

    def test_current_version_tag_outside_tested_history_is_collision(self):
        self.write(self.seed, "notes.txt", "This commit is not on remote main.\n")
        self.git(self.seed, "add", "notes.txt")
        self.git(self.seed, "commit", "--quiet", "-m", "Unpublished branch work")
        self.git(self.seed, "tag", "v0.1.0")
        self.git(self.seed, "push", "--quiet", "origin", "refs/tags/v0.1.0")
        before = self.refs()
        result = self.release(self.runner(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tag collision", result.stderr)
        self.assertEqual(self.refs(), before)

    def test_rejected_branch_update_does_not_publish_tag(self):
        self.tag_initial()
        self.advance_main()
        hook = self.remote / "hooks/update"
        hook.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = refs/heads/main ]; then\n"
            "  echo 'fixture branch protection rejects update' >&2\n"
            "  exit 1\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        before = self.refs()
        result = self.release(self.runner(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture branch protection", result.stderr)
        self.assertEqual(self.refs(), before)
        self.assertNotIn("refs/tags/v0.1.1", self.refs())

    def test_ci_guards_reject_untrusted_or_mismatched_execution(self):
        runner = self.runner()
        before = self.refs()
        for override in (
            {"GITHUB_ACTIONS": "false"},
            {"GITHUB_REF": "refs/heads/topic"},
            {"GITHUB_EVENT_NAME": "pull_request"},
            {"GITHUB_SHA": "not-a-sha"},
            {"GITHUB_SHA": "0" * 40},
        ):
            with self.subTest(override=override):
                result = self.release(runner, overrides=override, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.refs(), before)
        result = self.release(runner, part="minor", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.refs(), before)

    def test_owned_dirty_metadata_is_not_committed(self):
        runner = self.runner()
        with (runner / "skills/custom/SKILL.md").open("a", encoding="utf-8") as target:
            target.write("\nUncommitted skill edit.\n")
        before = self.refs()
        result = self.release(runner, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release-owned paths", result.stderr)
        self.assertEqual(self.refs(), before)
        self.assertIn("Uncommitted skill edit.", (runner / "skills/custom/SKILL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
