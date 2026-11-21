#!/usr/bin/env python3
"""Checks for check_frontmatter: presence, name/description, catalog fields,
visibility flag and description cap.

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
            "metadata:\n  revision: \"1\"\n  areas: \"software-development\"\n"
            "  targets: \"runtime-agnostic\"\n---\n\n# " + name + "\n")


class CheckFrontmatterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.skills = self.tmp / "skills"
        self.skills.mkdir()

    def skill(self, name: str, text: str | None = None,
              category: str = "engineering") -> Path:
        directory = self.skills / category / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            valid_frontmatter(name) if text is None else text, encoding="utf-8")
        return directory / "SKILL.md"

    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(frontmatter, "SKILLS", self.skills), \
             redirect_stdout(out), redirect_stderr(err):
            code = frontmatter.main()
        return code, out.getvalue(), err.getvalue()

    def test_valid_skills_in_two_categories_pass(self):
        alpha = self.skill("alpha")
        self.skill("beta", category="research-writing")
        self.assertEqual(frontmatter.check_skill(alpha), [])
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("2 skills OK", out)

    def test_missing_or_unclosed_frontmatter_fails(self):
        self.skill("no-open", "# no frontmatter\n")
        self.skill("no-close", "---\nname: no-close\n")
        self.assertEqual(len(frontmatter.check_skill(
            self.skills / "engineering" / "no-open" / "SKILL.md")), 1)
        self.assertIn("missing frontmatter closing",
                      frontmatter.check_skill(
                          self.skills / "engineering" / "no-close" / "SKILL.md")[0])

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

    def test_revision_must_be_a_positive_integer_and_version_is_retired(self):
        for number, (old, new, message) in enumerate((
            ('revision: "1"', 'revision: "0"', "metadata.revision must be a positive integer"),
            ('revision: "1"', 'revision: "0.1.0"', "metadata.revision must be a positive integer"),
            ('revision: "1"', 'version: "0.1.0"', "use metadata.revision"),
        )):
            with self.subTest(new=new):
                path = self.skill(f"rev-{number}", valid_frontmatter(f"rev-{number}")
                                  .replace(old, new))
                self.assertTrue(any(message in finding
                                    for finding in frontmatter.check_skill(path)))

    def test_missing_skill_md_fails_beside_a_valid_skill(self):
        self.skill("good")
        (self.skills / "engineering" / "empty").mkdir()
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("empty", out)
        self.assertIn("missing", out)

    def test_flat_skill_and_unknown_category_fail(self):
        self.skill("good")
        flat = self.skills / "flat"
        flat.mkdir()
        (flat / "SKILL.md").write_text(valid_frontmatter("flat"), encoding="utf-8")
        unknown = self.skills / "misc" / "other"
        unknown.mkdir(parents=True)
        (unknown / "SKILL.md").write_text(valid_frontmatter("other"), encoding="utf-8")
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("unknown skill category", out)
        self.assertIn("misc", out)
        self.assertIn("misplaced SKILL.md", out)

    def test_too_deep_skill_fails(self):
        self.skill("good")
        deep = self.skills / "engineering" / "deep" / "nested"
        deep.mkdir(parents=True)
        (deep / "SKILL.md").write_text(valid_frontmatter("nested"), encoding="utf-8")
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("misplaced SKILL.md", out)
        self.assertIn("nested", out)

    def test_duplicate_skill_name_fails_and_names_both_paths(self):
        self.skill("dup")
        self.skill("dup", category="hermes")
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("duplicate skill directory name 'dup'", out)
        self.assertIn("engineering/dup", out)
        self.assertIn("hermes/dup", out)

    def test_empty_catalog_fails(self):
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("no skill packages found", out)

    def test_hidden_flag_and_codex_policy_must_agree(self):
        for name, key, flag, policy, message in (
            ("quiet", "disable-model-invocation", "true", "false", None),
            ("no-policy", "disable-model-invocation", "true", None, "needs agents/openai.yaml"),
            ("allowed", "disable-model-invocation", "true", "true", "needs agents/openai.yaml"),
            ("policy-only", "disable-model-invocation", "false", "false",
             "add disable-model-invocation: true"),
            ("quoted", "disable-model-invocation", '"true"', "false", "must be a YAML boolean"),
            ("camel", "disableModelInvocation", "true", None,
             "'disableModelInvocation' is misspelled"),
            ("snake", "disable_model_invocation", "true", None,
             "'disable_model_invocation' is misspelled"),
        ):
            with self.subTest(name=name):
                path = self.skill(name, valid_frontmatter(name).replace(
                    "metadata:", f"{key}: {flag}\nmetadata:", 1))
                if policy is not None:
                    (path.parent / "agents").mkdir()
                    (path.parent / "agents" / "openai.yaml").write_text(
                        f"policy:\n  allow_implicit_invocation: {policy}\n", encoding="utf-8")
                findings = frontmatter.check_skill(path)
                if message is None:
                    self.assertEqual(findings, [])
                else:
                    self.assertTrue(any(message in finding for finding in findings), findings)

    def test_description_caps_depend_on_visibility(self):
        for name, length, hidden in (("visible-at-cap", 350, False), ("visible-long", 351, False),
                                     ("hidden-at-cap", 1024, True), ("hidden-long", 1025, True)):
            text = valid_frontmatter(name).replace(
                f"description: {name} does one thing.", "description: " + "x" * length)
            if hidden:
                text = text.replace("metadata:", "disable-model-invocation: true\nmetadata:", 1)
            path = self.skill(name, text)
            if hidden:
                (path.parent / "agents").mkdir()
                (path.parent / "agents" / "openai.yaml").write_text(
                    "policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("351 characters; cap for a model-visible skill is 350", out)
        self.assertIn("1025 characters; cap for a hidden skill is 1024", out)
        self.assertNotIn("visible-at-cap", out)
        self.assertNotIn("hidden-at-cap", out)


if __name__ == "__main__":
    unittest.main()
