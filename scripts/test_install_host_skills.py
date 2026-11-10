#!/usr/bin/env python3
"""Offline checks for install_host_skills: absent / linked / drift / refusal.

Run: python -m unittest scripts.test_install_host_skills
Builds a synthetic skills/ tree and host root in a temp dir. No live host
directory is read or written.
"""
from __future__ import annotations

import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parent / "install_host_skills.py"
ARTIFACTS = SCRIPT.parent.parent / ".tmp-artifacts" / "install-host-tests"
spec = importlib.util.spec_from_file_location("install_host_skills", SCRIPT)
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def make_temp_root() -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=ARTIFACTS))


class InstallHostSkillsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.skills = self.tmp / "skills"
        self.skills.mkdir()
        self.host = self.tmp / "host"
        self.host.mkdir()

    def _skill(self, name: str, body: str = "v1") -> Path:
        directory = self.skills / name
        directory.mkdir()
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {body}\n---\n# {name}\n{body}\n",
            encoding="utf-8")
        (directory / "references").mkdir()
        (directory / "references" / "notes.txt").write_text(body + "\n", encoding="utf-8")
        return directory

    def _run(self, mode: str, root: Path | None = None):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(install, "SKILLS", self.skills), \
             redirect_stdout(out), redirect_stderr(err):
            code = install.main(["--root", str(root or self.host), mode])
        return code, out.getvalue(), err.getvalue()

    def _entries(self) -> list[str]:
        return sorted(path.relative_to(self.host).as_posix()
                      for path in self.host.rglob("*"))

    def test_check_names_every_absent_skill_and_writes_nothing(self):
        self._skill("alpha")
        self._skill("beta")
        before = self._entries()
        code, out, err = self._run("--check")
        self.assertEqual(code, 1)
        self.assertIn("absent: alpha", out)
        self.assertIn("absent: beta", out)
        self.assertIn("2 of 2 skills", err)
        self.assertEqual(self._entries(), before)

    def test_link_creates_symlinks_and_check_passes(self):
        alpha = self._skill("alpha")
        self._skill("beta")
        code, out, _ = self._run("--link")
        self.assertEqual(code, 0)
        self.assertIn("linked: alpha", out)
        for name in ("alpha", "beta"):
            entry = self.host / name
            self.assertTrue(entry.is_symlink())
            self.assertEqual(os.path.realpath(entry), os.path.realpath(self.skills / name))
        self.assertEqual(os.path.realpath(self.host / "alpha"), os.path.realpath(alpha))
        self.assertEqual(self._run("--check")[0], 0)

    def test_second_link_reports_nothing_to_do_and_changes_no_inode(self):
        self._skill("alpha")
        self.assertEqual(self._run("--link")[0], 0)
        entry = self.host / "alpha"
        before = entry.lstat()
        code, out, _ = self._run("--link")
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)
        self.assertEqual(entry.lstat().st_ino, before.st_ino)
        self.assertEqual(os.readlink(entry), str((self.skills / "alpha").resolve()))

    def test_identical_real_directory_is_installed(self):
        self._skill("alpha")
        shutil.copytree(self.skills / "alpha", self.host / "alpha")
        self.assertFalse((self.host / "alpha").is_symlink())
        code, out, _ = self._run("--check")
        self.assertEqual(code, 0, out)

    def test_drifted_real_directory_is_reported_and_refused(self):
        self._skill("alpha")
        shutil.copytree(self.skills / "alpha", self.host / "alpha")
        (self.host / "alpha" / "SKILL.md").write_text("host edit\n", encoding="utf-8")
        code, out, _ = self._run("--check")
        self.assertEqual(code, 1)
        self.assertIn("drifted: alpha", out)
        self.assertIn("changed SKILL.md", out)

        code, out, err = self._run("--link")
        self.assertEqual(code, 1)
        self.assertIn("refused: alpha", out)
        self.assertFalse((self.host / "alpha").is_symlink())
        self.assertEqual((self.host / "alpha" / "SKILL.md").read_text(encoding="utf-8"),
                         "host edit\n")
        self.assertIn("refused 1", err)

    def test_wrongly_linked_skill_is_reported_and_relinked(self):
        self._skill("alpha")
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (self.host / "alpha").symlink_to(elsewhere, target_is_directory=True)
        code, out, _ = self._run("--check")
        self.assertEqual(code, 1)
        self.assertIn("wrongly linked: alpha ->", out)
        code, out, _ = self._run("--link")
        self.assertEqual(code, 0)
        self.assertIn("relinked: alpha", out)
        self.assertEqual(os.path.realpath(self.host / "alpha"),
                         os.path.realpath(self.skills / "alpha"))
        self.assertEqual(self._run("--check")[0], 0)

    def test_broken_symlink_is_reported_and_relinked(self):
        self._skill("alpha")
        (self.host / "alpha").symlink_to(self.tmp / "missing", target_is_directory=True)
        code, out, _ = self._run("--check")
        self.assertEqual(code, 1)
        self.assertIn("wrongly linked: alpha", out)
        self.assertEqual(self._run("--link")[0], 0)
        self.assertEqual(self._run("--check")[0], 0)

    def test_regular_file_is_refused_untouched(self):
        self._skill("alpha")
        (self.host / "alpha").write_text("not a skill\n", encoding="utf-8")
        code, out, _ = self._run("--check")
        self.assertEqual(code, 1)
        self.assertIn("wrongly linked: alpha -> not a directory or symlink", out)
        code, out, _ = self._run("--link")
        self.assertEqual(code, 1)
        self.assertIn("refused: alpha", out)
        self.assertEqual((self.host / "alpha").read_text(encoding="utf-8"), "not a skill\n")

    def test_extra_host_entries_are_ignored(self):
        self._skill("alpha")
        (self.host / "other-skill").mkdir()
        (self.host / "README.md").write_text("host notes\n", encoding="utf-8")
        self.assertEqual(self._run("--link")[0], 0)
        code, out, _ = self._run("--check")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.host / "other-skill").is_dir())

    def test_linked_skill_follows_repository_changes(self):
        self._skill("alpha")
        self.assertEqual(self._run("--link")[0], 0)
        (self.skills / "alpha" / "SKILL.md").write_text("changed\n", encoding="utf-8")
        self.assertEqual(self._run("--check")[0], 0)

    def test_missing_root_is_a_usage_error(self):
        self._skill("alpha")
        code, _, err = self._run("--check", root=self.tmp / "no-such-root")
        self.assertEqual(code, 2)
        self.assertIn("root does not exist", err)

    def test_empty_skills_directory_is_a_repository_error(self):
        code, _, err = self._run("--check")
        self.assertEqual(code, 2)
        self.assertIn("no skills found", err)

    def test_skill_directory_without_skill_md_is_an_error(self):
        (self.skills / "broken").mkdir()
        code, _, err = self._run("--check")
        self.assertEqual(code, 2)
        self.assertIn("without SKILL.md", err)


if __name__ == "__main__":
    unittest.main()
