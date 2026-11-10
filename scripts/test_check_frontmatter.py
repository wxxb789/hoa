#!/usr/bin/env python3
"""Checks for check_frontmatter: presence, name/description, catalog fields.

Run: python -m unittest scripts.test_check_frontmatter
"""
from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parent / "check_frontmatter.py"
ARTIFACTS = SCRIPT.parent.parent / ".tmp-artifacts" / "frontmatter-tests"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("check_frontmatter", SCRIPT)
frontmatter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frontmatter)


def make_temp_root() -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=ARTIFACTS))


def valid_frontmatter(name: str) -> str:
    return (f"---\nname: {name}\ndescription: {name} does one thing.\n"
            "metadata:\n  version: \"0.1.0\"\n  areas: \"software-development\"\n"
            "  targets: \"runtime-agnostic\"\n---\n\n# " + name + "\n")


class CheckFrontmatterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.skills = self.tmp / "skills"
        self.skills.mkdir()

    def skill(self, name: str, text: str | None = None) -> Path:
        directory = self.skills / name
        directory.mkdir()
        (directory / "SKILL.md").write_text(
            valid_frontmatter(name) if text is None else text, encoding="utf-8")
        return directory / "SKILL.md"

    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(frontmatter, "SKILLS", self.skills), \
             redirect_stdout(out), redirect_stderr(err):
            code = frontmatter.main()
        return code, out.getvalue(), err.getvalue()

    def test_valid_skill_passes(self):
        self.skill("alpha")
        self.assertEqual(frontmatter.check_skill(self.skills / "alpha" / "SKILL.md"), [])
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("1 skills OK", out)

    def test_missing_or_unclosed_frontmatter_fails(self):
        self.skill("no-open", "# no frontmatter\n")
        self.skill("no-close", "---\nname: no-close\n")
        self.assertEqual(len(frontmatter.check_skill(
            self.skills / "no-open" / "SKILL.md")), 1)
        self.assertIn("missing frontmatter closing",
                      frontmatter.check_skill(self.skills / "no-close" / "SKILL.md")[0])

    def test_name_must_match_directory(self):
        path = self.skill("wrong-name", valid_frontmatter("other"))
        findings = frontmatter.check_skill(path)
        self.assertTrue(any("does not match directory" in finding for finding in findings))

    def test_empty_description_fails(self):
        text = valid_frontmatter("empty-desc").replace(
            "description: empty-desc does one thing.", "description: \"\"")
        path = self.skill("empty-desc", text)
        self.assertTrue(any("description must be a non-empty string" in finding
                            for finding in frontmatter.check_skill(path)))

    def test_catalog_errors_are_reported(self):
        text = valid_frontmatter("bad-area").replace(
            'areas: "software-development"', 'areas: "nonsense"')
        path = self.skill("bad-area", text)
        self.assertTrue(any("unknown area" in finding
                            for finding in frontmatter.check_skill(path)))
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("bad-area", out)
        self.assertIn("finding(s)", err)

    def test_missing_skill_md_fails(self):
        (self.skills / "empty").mkdir()
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("missing", out)


if __name__ == "__main__":
    unittest.main()
