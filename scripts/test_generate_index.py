#!/usr/bin/env python3
"""Offline round-trip check for generate_index: parse, validate, --check drift.

Run: python scripts/test_generate_index.py
Builds a synthetic skills/ tree in a temp dir and exercises the failure paths
CI depends on: quoted metadata values, unknown areas/targets, missing index
comments, skill dirs without SKILL.md, note fallback from frontmatter, and
--check drift detection.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent / "generate_index.py"
spec = importlib.util.spec_from_file_location("generate_index", SCRIPT)
gi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gi)


def make_skill(root: Path, name: str, *, index=None, frontmatter=True, quoted=False):
    d = root / "skills" / name
    d.mkdir(parents=True)
    if index is None:
        index = "areas=software-development; targets=runtime-agnostic"
    if quoted:
        index = index.replace("software-development", '"software-development"')
    parts = []
    if frontmatter:
        parts += ["---", "name: " + name,
                  "description: " + name + " does one thing. And another.",
                  "---", ""]
    parts += [f"<!-- index: {index} -->", "", f"# {name}", ""]
    (d / "SKILL.md").write_text("\n".join(parts), encoding="utf-8")
    return d


class ParseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_plain_and_quoted_values_parse_equal(self):
        plain = make_skill(self.tmp, "plain")
        quoted = make_skill(self.tmp, "quoted", quoted=True)
        self.assertEqual(gi.parse_metadata(plain / "SKILL.md"),
                         gi.parse_metadata(quoted / "SKILL.md"))

    def test_unknown_area_or_target_rejected(self):
        # Same validation branch, parametrized over the two axes.
        for name, index in (
            ("bad-area", "areas=nonsense; targets=runtime-agnostic"),
            ("bad-target", "areas=software-development; targets=nonsense"),
        ):
            bad = make_skill(self.tmp, name, index=index)
            with self.assertRaises(ValueError):
                gi.parse_metadata(bad / "SKILL.md")

    def test_missing_index_comment_rejected(self):
        d = self.tmp / "skills" / "nocomment"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: x\ndescription: y.\n---\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            gi.parse_metadata(d / "SKILL.md")

    def test_missing_areas_key_rejected(self):
        bad = make_skill(self.tmp, "bad", index="targets=runtime-agnostic")
        with self.assertRaises(ValueError):
            gi.parse_metadata(bad / "SKILL.md")


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_dir_without_skill_md_rejected(self):
        make_skill(self.tmp, "good")
        (self.tmp / "skills" / "broken-pkg").mkdir()
        with patch.object(gi, "SKILLS", self.tmp / "skills"), \
             patch.object(gi, "LIBRARY_FOLDERS", {}):
            with self.assertRaises(ValueError) as cm:
                gi.collect()
        self.assertIn("broken-pkg", str(cm.exception))

    def test_note_falls_back_to_frontmatter(self):
        make_skill(self.tmp, "unlisted-skill")
        with patch.object(gi, "SKILLS", self.tmp / "skills"), \
             patch.object(gi, "NOTES", {}), \
             patch.object(gi, "LIBRARY_FOLDERS", {}):
            rows = gi.collect()
        self.assertEqual(rows[0]["note_en"], "unlisted-skill does one thing.")
        self.assertEqual(rows[0]["note_zh"], "unlisted-skill does one thing.")

    def test_notes_override_beats_fallback(self):
        make_skill(self.tmp, "listed-skill")
        with patch.object(gi, "SKILLS", self.tmp / "skills"), patch.object(
            gi, "NOTES", {"listed-skill": ("override-en", "override-zh")}
        ), patch.object(gi, "LIBRARY_FOLDERS", {}):
            rows = gi.collect()
        self.assertEqual(rows[0]["note_en"], "override-en")
        self.assertEqual(rows[0]["note_zh"], "override-zh")

    def test_no_frontmatter_and_no_override_rejected(self):
        make_skill(self.tmp, "bare", frontmatter=False)
        with patch.object(gi, "SKILLS", self.tmp / "skills"), \
             patch.object(gi, "NOTES", {}), \
             patch.object(gi, "LIBRARY_FOLDERS", {}):
            with self.assertRaises(ValueError):
                gi.collect()


class CheckDriftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _run(self, check):
        with patch.object(gi, "SKILLS", self.tmp / "skills"), \
             patch.object(gi, "ROOT", self.tmp):
            return gi.main(["--check"] if check else [])

    def test_check_passes_when_up_to_date(self):
        make_skill(self.tmp, "s1")
        self.assertEqual(self._run(check=False), 0)
        self.assertEqual(self._run(check=True), 0)

    def test_check_fails_on_drift(self):
        make_skill(self.tmp, "s1")
        self.assertEqual(self._run(check=False), 0)
        (self.tmp / "index.md").write_text("stale", encoding="utf-8")
        self.assertEqual(self._run(check=True), 1)

class LibraryCollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_library_artifact_collected_and_indexed(self):
        make_skill(self.tmp, "s1")
        agent_doc = self.tmp / "agents" / "reviewer.md"
        agent_doc.parent.mkdir(parents=True)
        agent_doc.write_text(
            "---\nname: reviewer\ndescription: A reviewer role does things.\n---\n"
            "<!-- index: areas=software-development; targets=repo-only -->\n",
            encoding="utf-8")
        with patch.object(gi, "SKILLS", self.tmp / "skills"), \
             patch.object(gi, "ROOT", self.tmp), patch.object(gi, "NOTES", {}):
            rows = gi.collect()
            content = gi.render(rows, "en")
        lib = next(r for r in rows if r["name"] == "reviewer")
        self.assertEqual(lib["type"], "agent")
        self.assertIn("| reviewer | agent | software-development | repo-only | "
                      "`agents/reviewer.md` |", content)

    def test_library_artifact_without_doc_rejected(self):
        make_skill(self.tmp, "s1")
        orphan = self.tmp / "agents" / "no-doc"
        orphan.mkdir(parents=True)
        with patch.object(gi, "SKILLS", self.tmp / "skills"), \
             patch.object(gi, "ROOT", self.tmp):
            with self.assertRaises(ValueError) as cm:
                gi.collect()
        self.assertIn("no-doc", str(cm.exception))

