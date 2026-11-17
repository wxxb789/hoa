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


class VersionCliTests(unittest.TestCase):
    """origin/main holds VERSION 0.1.0 and skills kept (rev 2) and gone (rev 1)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        for name in ("version.py", "skill_metadata.py"):
            shutil.copy2(SCRIPTS / name, self.root / "scripts" / name)
        self.write("VERSION", "0.1.0\n")
        self.write("skills/kept/SKILL.md", skill_text("kept", "2"))
        self.write("skills/gone/SKILL.md", skill_text("gone", "1"))
        self.write("skills/gone/notes.md", "moved later\n")
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "base")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def write(self, relative: str, text: str) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), *args], env=GIT_ENV,
                       capture_output=True, check=True)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(self.root / "scripts" / "version.py"), *args],
                              env=GIT_ENV, text=True, encoding="utf-8", capture_output=True)

    def test_bump_rewrites_only_version(self):
        result = self.run_cli("bump")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "0.1.1"))
        self.assertEqual(self.run_cli("bump", "minor").stdout.strip(), "0.2.0")
        self.assertEqual((self.root / "VERSION").read_text(encoding="utf-8"), "0.2.0\n")
        self.assertIn('revision: "2"', (self.root / "skills/kept/SKILL.md").read_text())

    def test_check_bump_requires_exactly_one_patch(self):
        for current, status in (("0.1.1", 0), ("0.1.0", 1), ("0.1.2", 1), ("0.2.0", 1)):
            with self.subTest(current=current):
                self.write("VERSION", current + "\n")
                result = self.run_cli("check-bump")
                self.assertEqual(result.returncode, status, result.stderr)
                if status:
                    self.assertIn("expected 0.1.1", result.stderr)

    def test_check_revisions_names_each_unbumped_skill(self):
        self.write("skills/kept/notes.md", "changed\n")
        self.write("skills/fresh/SKILL.md", skill_text("fresh", "3"))
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 1)
        self.assertIn('skills/kept/SKILL.md: changed since', result.stderr)
        self.assertIn('set it to "3"', result.stderr)
        self.assertIn('skills/fresh/SKILL.md: new skill must start at metadata.revision "1"',
                      result.stderr)

    def test_check_revisions_counts_a_cross_skill_move_against_both(self):
        self.write("skills/kept/SKILL.md", skill_text("kept", "3"))
        self.git("mv", "skills/gone/notes.md", "skills/kept/notes.md")
        self.git("commit", "--quiet", "-am", "move")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 1)
        self.assertIn('skills/gone/SKILL.md: changed since', result.stderr)
        self.assertIn('set it to "2"', result.stderr)

    def test_check_revisions_accepts_bumped_new_and_deleted_skills(self):
        self.write("skills/kept/SKILL.md", skill_text("kept", "3"))
        self.write("skills/fresh/SKILL.md", skill_text("fresh", "1"))
        shutil.rmtree(self.root / "skills" / "gone")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 changed skill(s) OK", result.stdout)

    def test_unchanged_skills_need_no_bump(self):
        self.write("VERSION", "0.1.1\n")
        result = self.run_cli("check-revisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 changed skill(s) OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
