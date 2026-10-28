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

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parent / "generate_index.py"
ARTIFACTS = SCRIPT.parent.parent / ".tmp-artifacts" / "index-tests"
spec = importlib.util.spec_from_file_location("skill_metadata", SCRIPT.parent / "skill_metadata.py")
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)
spec = importlib.util.spec_from_file_location("generate_index", SCRIPT)
gi = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"skill_metadata": sm}):
    spec.loader.exec_module(gi)

def make_temp_root() -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=ARTIFACTS))



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
                  "metadata:", '  version: "0.1.0"', "---", ""]
    parts += [f"<!-- index: {index} -->", "", f"# {name}", ""]
    (d / "SKILL.md").write_bytes("\n".join(parts).encode("utf-8"))
    return d


class ParseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_root()
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

    def test_custom_skill_version_comes_only_from_yaml_metadata(self):
        skill = make_skill(self.tmp, "standard") / "SKILL.md"
        metadata = gi.parse_skill_metadata(skill)
        self.assertEqual(metadata["version"], "0.1.0")
        self.assertNotIn("version", gi.parse_metadata(skill))

    def test_legacy_html_version_is_rejected_only_for_custom_skills(self):
        skill = make_skill(self.tmp, "legacy", index=
                           "areas=software-development; targets=runtime-agnostic; version=9.8.7")
        self.assertEqual(gi.parse_metadata(skill / "SKILL.md")["version"], "9.8.7")
        with self.assertRaisesRegex(ValueError, "legacy index version="):
            gi.parse_skill_metadata(skill / "SKILL.md")

    def test_custom_skill_missing_yaml_version_cannot_hide_behind_index_metadata(self):
        skill = make_skill(self.tmp, "missing") / "SKILL.md"
        skill.write_bytes(skill.read_bytes().replace(b'  version: "0.1.0"\n', b""))
        with self.assertRaises(ValueError):
            gi.parse_skill_metadata(skill)

    def test_duplicate_yaml_version_is_not_silently_overwritten(self):
        skill = make_skill(self.tmp, "duplicate") / "SKILL.md"
        skill.write_bytes(skill.read_bytes().replace(
            b'  version: "0.1.0"\n', b'  version: "0.1.0"\n  version: "0.2.0"\n'))
        with self.assertRaisesRegex(ValueError, "duplicate metadata.version"):
            gi.parse_skill_metadata(skill)


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_root()
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
        self.assertEqual(rows[0]["version"], "0.1.0")

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
        self.tmp = make_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _run(self, check):
        with patch.object(gi, "SKILLS", self.tmp / "skills"), \
             patch.object(gi, "ROOT", self.tmp), \
             patch.object(gi, "LIBRARY_FOLDERS", {}):
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
    FOLDERS = {"agents": "agent", "mcps": "mcp"}

    def setUp(self):
        self.tmp = make_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _collect(self):
        with patch.object(gi, "SKILLS", self.tmp / "skills"), \
             patch.object(gi, "ROOT", self.tmp), \
             patch.object(gi, "LIBRARY_FOLDERS", self.FOLDERS):
            return gi.collect()

    def _write_library_doc(self, text, folder="agents", name="reviewer", readme=False):
        make_skill(self.tmp, "s1")
        for other in self.FOLDERS:  # every configured folder must hold an artifact
            if other == folder:
                continue
            (self.tmp / other).mkdir(parents=True, exist_ok=True)
            (self.tmp / other / "filler.md").write_text(
                "---\nname: filler\ndescription: A filler artifact.\n---\n"
                "<!-- index: areas=software-development; targets=repo-only -->\n",
                encoding="utf-8")
        target = self.tmp / folder / (name + "/README.md" if readme else name + ".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def test_library_file_artifact_collected_and_indexed(self):
        self._write_library_doc(
            "---\nname: reviewer\ndescription: A reviewer role does things.\n---\n"
            "<!-- index: areas=software-development; targets=repo-only; version=9.8.7 -->\n")
        with patch.object(gi, "NOTES", {}):
            rows = self._collect()
            content = gi.render(rows, "en")
        lib = next(r for r in rows if r["name"] == "reviewer")
        self.assertEqual(lib["type"], "agent")
        self.assertEqual(lib["version"], "9.8.7")
        self.assertIn("| reviewer | agent | software-development | repo-only | "
                      "`agents/reviewer.md` |", content)

    def test_library_readme_directory_artifact_uses_directory_path(self):
        self._write_library_doc(
            "---\nname: proxy\ndescription: A local proxy definition.\n---\n"
            "<!-- index: areas=software-development; targets=repo-only -->\n",
            folder="mcps", name="ghc-proxy", readme=True)
        with patch.object(gi, "NOTES", {}):
            rows = self._collect()
            content = gi.render(rows, "en")
        lib = next(r for r in rows if r["name"] == "ghc-proxy")
        self.assertEqual(lib["path"], "mcps/ghc-proxy/")
        self.assertIn("`mcps/ghc-proxy/`", content)

    def test_library_artifact_without_doc_rejected(self):
        make_skill(self.tmp, "s1")
        orphan = self.tmp / "agents" / "no-doc"
        orphan.mkdir(parents=True)
        (self.tmp / "mcps" / "filler.md").parent.mkdir(parents=True, exist_ok=True)
        (self.tmp / "mcps" / "filler.md").write_text(
            "---\nname: filler\ndescription: A filler artifact.\n---\n"
            "<!-- index: areas=software-development; targets=repo-only -->\n",
            encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            self._collect()
        self.assertIn("no-doc", str(cm.exception))

    def test_library_folder_with_only_gitkeep_rejected(self):
        make_skill(self.tmp, "s1")
        for folder in ("agents", "mcps"):
            (self.tmp / folder).mkdir(parents=True)
            (self.tmp / folder / ".gitkeep").write_text("", encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            self._collect()
        self.assertIn("no artifacts", str(cm.exception))

    def test_missing_library_folder_rejected(self):
        make_skill(self.tmp, "s1")
        with self.assertRaises(ValueError) as cm:
            self._collect()  # neither agents/ nor mcps/ exists
        self.assertIn("configured library folder missing", str(cm.exception))

    def test_duplicate_artifact_name_rejected(self):
        self._write_library_doc(
            "---\nname: s1\ndescription: A skill-named agent role.\n---\n"
            "<!-- index: areas=software-development; targets=repo-only -->\n",
            name="s1")
        with self.assertRaises(ValueError) as cm:
            self._collect()  # library artifact "s1" collides with skill "s1"
        self.assertIn("duplicate artifact name 's1'", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
