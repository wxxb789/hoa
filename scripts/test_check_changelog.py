#!/usr/bin/env python3
"""Checks for check_changelog: the version/changelog rule in both directions.

Run: python -m unittest scripts.test_check_changelog
Uses a disposable local git repository; no network and no remote.
"""
from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parent / "check_changelog.py"
ARTIFACTS = SCRIPT.parent.parent / ".tmp-artifacts" / "changelog-tests"
spec = importlib.util.spec_from_file_location("check_changelog", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def make_temp_root() -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=ARTIFACTS))


class CheckChangelogTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_temp_root()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.git("init", "-q", "-b", "main")
        self.write("VERSION", "0.1.0\n")
        self.write("CHANGELOG.md", "# Changelog\n")
        self.git("add", "VERSION", "CHANGELOG.md")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.repo), "-c", "user.name=Test",
             "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
             *arguments],
            text=True, encoding="utf-8", check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def write(self, name: str, content: str) -> None:
        (self.repo / name).write_text(content, encoding="utf-8")

    def run_check(self, *arguments: str):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(check, "ROOT", self.repo), \
             redirect_stdout(out), redirect_stderr(err):
            code = check.main(["--base", self.base, *arguments])
        return code, out.getvalue(), err.getvalue()

    def test_unchanged_version_passes(self):
        code, out, _ = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("VERSION unchanged", out)

    def test_changelog_only_passes(self):
        self.write("CHANGELOG.md", "# Changelog\n\n- entry\n")
        code, out, _ = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("VERSION unchanged", out)

    def test_version_only_fails(self):
        self.write("VERSION", "0.1.1\n")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("VERSION changed but CHANGELOG.md did not", err)

    def test_version_and_changelog_passes(self):
        self.write("VERSION", "0.1.1\n")
        self.write("CHANGELOG.md", "# Changelog\n\n- entry\n")
        code, out, _ = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("both changed", out)

    def test_committed_increment_is_seen_through_merge_base(self):
        self.git("checkout", "-q", "-b", "feature")
        self.write("VERSION", "0.1.1\n")
        self.write("CHANGELOG.md", "# Changelog\n\n- entry\n")
        self.git("add", "VERSION", "CHANGELOG.md")
        self.git("commit", "-q", "-m", "feature")
        code, _, _ = self.run_check()
        self.assertEqual(code, 0)

        self.git("checkout", "-q", "-B", "version-only", self.base)
        self.write("VERSION", "0.1.1\n")
        self.git("add", "VERSION")
        self.git("commit", "-q", "-m", "bump only")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("CHANGELOG.md did not", err)

    def test_unknown_base_is_an_error_not_green(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(check, "ROOT", self.repo), \
             redirect_stdout(out), redirect_stderr(err):
            code = check.main(["--base", "no-such-ref"])
        self.assertEqual(code, 2)
        self.assertIn("cannot resolve", err.getvalue())


if __name__ == "__main__":
    unittest.main()
