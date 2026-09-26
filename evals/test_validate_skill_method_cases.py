"""Regression tests for skill-method fixture setup-file isolation."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evals import validate_skill_method_cases as validator


class SetupPathTests(unittest.TestCase):
    def validate_paths(self, paths: list[str]) -> list[str]:
        case = {
            "id": "setup-test",
            "skill": "hoa-skill-review",
            "prompt": "Review the disposable skill.",
            "expected_mode": "review-findings",
            "must_hold": ["Evidence-backed finding"],
            "must_not_hold": ["Modify the reviewed skill"],
            "setup_files": [{"path": path, "content": path} for path in paths],
        }
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "cases.json"
            fixture.write_text(json.dumps({"cases": [case]}), encoding="utf-8")
            with patch.object(validator, "CASES", fixture):
                return validator.validate()

    def test_valid_distinct_relative_files(self) -> None:
        self.assertEqual([], self.validate_paths([
            "skills/first/SKILL.md", "skills/second/SKILL.md"
        ]))

    def test_normalized_aliases_cannot_overwrite_setup_files(self) -> None:
        for alias in ("skills//first/SKILL.md", "skills/./first/SKILL.md",
                      "SKILLS/first/SKILL.md"):
            with self.subTest(alias=alias):
                errors = self.validate_paths(["skills/first/SKILL.md", alias])
                self.assertTrue(any("setup path" in error for error in errors), errors)

    def test_parent_and_windows_absolute_paths_cannot_escape(self) -> None:
        for path in ("skills/../outside.md", "C:/outside.md", "//server/share/outside.md",
                     "skills\\first\\SKILL.md", "skills/first/"):
            with self.subTest(path=path):
                errors = self.validate_paths([path])
                self.assertTrue(any("setup path" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
