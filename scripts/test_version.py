#!/usr/bin/env python3
"""CLI contract of scripts/version.py against throwaway Git repositories.

Run: python scripts/test_version.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
GIT_ENV = {key: value for key, value in os.environ.items()
           if not key.startswith(("GIT_", "GITHUB_"))}
GIT_ENV.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1"})


def skill_text(name: str, revision: str) -> str:
    return (f"---\nname: {name}\ndescription: {name} does one thing.\nmetadata:\n"
            f'  revision: "{revision}"\n  areas: "software-development"\n'
            f'  targets: "runtime-agnostic"\n---\n\n# {name}\n')


class RepoFixture(unittest.TestCase):
    def make_repo(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        for name in ("version.py", "skill_metadata.py", "skill_paths.py"):
            shutil.copy2(SCRIPTS / name, self.root / "scripts" / name)
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.invalid")

    def write(self, relative: str, text: str) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), *args], env=GIT_ENV,
                       capture_output=True, check=True)

    def commit_all(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", message)

    def pin_origin(self) -> None:
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(self.root / "scripts" / "version.py"), *args],
                              env=GIT_ENV, text=True, encoding="utf-8", capture_output=True)


class VersionCliTests(RepoFixture):
    """origin/main holds categorized skills kept (rev 2) and gone (rev 1)."""

    def setUp(self):
        self.make_repo()
        self.write("skills/engineering/kept/SKILL.md", skill_text("kept", "2"))
        self.write("skills/engineering/gone/SKILL.md", skill_text("gone", "1"))
        self.write("skills/engineering/gone/notes.md", "moved later\n")
        self.commit_all("base")
        self.pin_origin()

    def test_check_revisions_names_each_unbumped_skill(self):
        self.write("skills/engineering/kept/notes.md", "changed\n")
        self.write("skills/productivity/fresh/SKILL.md", skill_text("fresh", "3"))
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 1)
        self.assertIn('skills/engineering/kept/SKILL.md: changed since', result.stderr)
        self.assertIn('set it to "3"', result.stderr)
        self.assertIn('skills/productivity/fresh/SKILL.md: new skill must start at metadata.revision "1"',
                      result.stderr)

    def test_check_revisions_counts_untracked_package_files(self):
        self.write("skills/engineering/kept/extra.txt", "untracked\n")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 1)
        self.assertIn('skills/engineering/kept/SKILL.md: changed since', result.stderr)

    def test_check_revisions_counts_a_cross_skill_move_against_both(self):
        self.write("skills/engineering/kept/SKILL.md", skill_text("kept", "3"))
        self.git("mv", "skills/engineering/gone/notes.md", "skills/engineering/kept/notes.md")
        self.git("commit", "--quiet", "-am", "move")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 1)
        self.assertIn('skills/engineering/gone/SKILL.md: changed since', result.stderr)
        self.assertIn('set it to "2"', result.stderr)

    def test_check_revisions_accepts_bumped_new_and_deleted_skills(self):
        self.write("skills/engineering/kept/SKILL.md", skill_text("kept", "3"))
        self.write("skills/productivity/fresh/SKILL.md", skill_text("fresh", "1"))
        shutil.rmtree(self.root / "skills" / "engineering" / "gone")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 changed skill(s) OK", result.stdout)

    def test_unchanged_skills_need_no_bump(self):
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 changed skill(s) OK", result.stdout)

    def test_category_to_category_pure_move_keeps_revision(self):
        (self.root / "skills" / "productivity").mkdir()
        self.git("mv", "skills/engineering/kept", "skills/productivity/kept")
        self.git("commit", "--quiet", "-am", "move category")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 changed skill(s) OK", result.stdout)

    def test_ambiguous_base_names_fail_instead_of_counting_as_new(self):
        self.write("skills/productivity/kept/SKILL.md", skill_text("kept", "1"))
        self.commit_all("collide")
        self.pin_origin()
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ambiguous skill name 'kept'", result.stderr)


class FlatBaseMigrationTests(RepoFixture):
    """origin/main still holds the old flat `skills/kept` layout at revision 2."""

    def setUp(self):
        self.make_repo()
        self.write("skills/kept/SKILL.md", skill_text("kept", "2"))
        self.write("skills/kept/notes.md", "stable\n")
        self.commit_all("base")
        self.pin_origin()

    def test_staged_then_committed_package_only_move_reports_zero_changed(self):
        (self.root / "skills" / "engineering").mkdir()
        self.git("mv", "skills/kept", "skills/engineering/kept")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 changed skill(s) OK", result.stdout)
        self.git("commit", "--quiet", "-am", "move")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 changed skill(s) OK", result.stdout)

    def test_unstaged_move_counts_as_changed_until_staged(self):
        (self.root / "skills" / "engineering").mkdir()
        self.git("mv", "skills/kept", "skills/engineering/kept")
        self.git("reset", "--quiet")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 1)
        self.assertIn('skills/engineering/kept/SKILL.md: changed since', result.stderr)
        self.git("add", "-A")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 changed skill(s) OK", result.stdout)

    def test_move_plus_edit_fails_until_revision_is_bumped(self):
        (self.root / "skills" / "engineering").mkdir()
        self.git("mv", "skills/kept", "skills/engineering/kept")
        self.write("skills/engineering/kept/notes.md", "edited\n")
        self.commit_all("move and edit")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 1)
        self.assertIn('skills/engineering/kept/SKILL.md: changed since', result.stderr)
        self.assertIn('set it to "3"', result.stderr)
        self.write("skills/engineering/kept/SKILL.md", skill_text("kept", "3"))
        self.commit_all("bump")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 changed skill(s) OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
