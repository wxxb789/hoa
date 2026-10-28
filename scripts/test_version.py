#!/usr/bin/env python3
"""Offline regression coverage for the repository-wide custom-skill version.

Run: python scripts/test_version.py
All mutations use isolated repositories under .tmp-artifacts/version-tests/.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parent
ARTIFACTS = SCRIPTS.parent / ".tmp-artifacts" / "version-tests"
spec = importlib.util.spec_from_file_location("skill_metadata", SCRIPTS / "skill_metadata.py")
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)
spec = importlib.util.spec_from_file_location("version_index", SCRIPTS / "generate_index.py")
gi = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"skill_metadata": sm}):
    spec.loader.exec_module(gi)
spec = importlib.util.spec_from_file_location("repository_version", SCRIPTS / "version.py")
version = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"generate_index": gi, "skill_metadata": sm}):
    spec.loader.exec_module(version)


def make_skill(root: Path, name: str, *, release="0.1.0", index=None,
               newline="\n", quote="", frontmatter=None) -> Path:
    if index is None:
        index = "areas=software-development; targets=runtime-agnostic; owner=unchanged"
    if frontmatter is None:
        frontmatter = (f"name: {name}\ndescription: {name} does one thing.\n"
                       f"metadata:\n  version: {quote}{release}{quote}\n"
                       "  owner: unchanged\n")
    text = (f"---\n{frontmatter}---\n\n"
            f"<!-- index: {index} -->\n\n# {name}\n\n"
            "Keep version=77.88.99 in prose, and non-ASCII text: 中文.\n"
            "```text\nversion: 42.0.0\n```\n")
    target = root / "skills" / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return target


class VersionTests(unittest.TestCase):
    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.tmpdir = tempfile.TemporaryDirectory(dir=ARTIFACTS)
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        (self.root / "VERSION").write_bytes(b"0.1.0\n")
        self.skill = make_skill(self.root, "sample")
        for folder in gi.LIBRARY_FOLDERS:
            target = self.root / folder / f"{folder}-item.md"
            target.parent.mkdir()
            target.write_bytes(
                b"---\ndescription: An independent library artifact.\n---\n"
                b"<!-- index: areas=software-development; targets=repo-only; "
                b"version=9.8.7 -->\n")
        self.context = contextlib.ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(patch.object(version, "ROOT", self.root))
        self.context.enter_context(patch.object(gi, "ROOT", self.root))
        self.context.enter_context(patch.object(gi, "SKILLS", self.root / "skills"))

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = version.main(list(args))
        return status, stdout.getvalue(), stderr.getvalue()

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def assert_indexes_current(self):
        rows = gi.collect()
        for lang, filename in (("en", "index.md"), ("zh", "index.zh-CN.md")):
            self.assertEqual((self.root / filename).read_bytes(),
                             gi.render(rows, lang).encode("utf-8"))

    def assert_rejected_without_writes(self, *args):
        before = self.snapshot()
        status, _, error = self.run_cli(*args)
        self.assertEqual(status, 1, error)
        self.assertTrue(error)
        self.assertEqual(self.snapshot(), before)

    def test_patch_is_default_and_explicit_patch_matches(self):
        self.assertEqual(self.run_cli("sync")[0], 0)
        status, output, error = self.run_cli("bump")
        self.assertEqual(status, 0, error)
        self.assertEqual(output, "0.1.1\n")
        self.assertEqual((self.root / "VERSION").read_bytes(), b"0.1.1\n")
        self.assertEqual(gi.parse_skill_metadata(self.skill)["version"], "0.1.1")
        self.assertEqual(self.run_cli("bump", "patch")[1], "0.1.2\n")
        self.assertEqual(gi.parse_skill_metadata(self.skill)["version"], "0.1.2")
        self.assert_indexes_current()
        self.assertEqual(self.run_cli("check")[0], 0)

    def test_minor_and_major_reset_lower_components(self):
        (self.root / "VERSION").write_bytes(b"3.8.9\r\n")
        self.assertEqual(self.run_cli("sync")[0], 0)
        self.assertEqual(self.run_cli("bump", "minor")[1], "3.9.0\n")
        self.assertEqual((self.root / "VERSION").read_bytes(), b"3.9.0\r\n")
        self.assertEqual(self.run_cli("bump", "major")[1], "4.0.0\n")
        self.assertEqual(gi.parse_skill_metadata(self.skill)["version"], "4.0.0")
        self.assert_indexes_current()

    def test_sync_preserves_bytes_quotes_and_unrelated_versions(self):
        quoted = make_skill(self.root, "quoted", release="7.6.5", newline="\r\n",
                            quote='"')
        plain = make_skill(self.root, "plain", release="7.6.5", newline="\r\n",
                           quote="'")
        nested = self.skill.parent / "third-party" / "SKILL.md"
        nested.parent.mkdir()
        nested.write_bytes(b"unowned version=11.12.13\r\n")
        third_party = self.root / "ref" / "vendor" / "SKILL.md"
        third_party.parent.mkdir(parents=True)
        third_party.write_bytes(b"not owned: version=10.20.30\r\n")
        before = self.snapshot()
        self.assertEqual(self.run_cli("sync")[0], 0)
        after = self.snapshot()
        for relative, content in before.items():
            if relative in {str(quoted.relative_to(self.root)),
                            str(plain.relative_to(self.root))}:
                self.assertEqual(after[relative], content.replace(b"7.6.5", b"0.1.0"))
            else:
                self.assertEqual(after[relative], content)
        self.assert_indexes_current()

    def test_check_is_read_only_and_detects_both_kinds_of_drift(self):
        self.assertEqual(self.run_cli("sync")[0], 0)
        self.skill.write_bytes(self.skill.read_bytes().replace(b"version: 0.1.0\n",
                                                             b"version: 1.0.0\n"))
        self.assert_rejected_without_writes("check")
        self.assertEqual(self.run_cli("sync")[0], 0)
        (self.root / "index.zh-CN.md").write_bytes(b"stale\r\n")
        self.assert_rejected_without_writes("check")
        self.assertEqual(self.run_cli("sync")[0], 0)
        before = self.snapshot()
        self.assertEqual(self.run_cli("check")[0], 0)
        self.assertEqual(self.snapshot(), before)

    def test_missing_indexes_fail_check_but_sync_creates_them(self):
        self.assert_rejected_without_writes("check")
        self.assertEqual(self.run_cli("sync")[0], 0)
        self.assert_indexes_current()

    def test_existing_crlf_indexes_are_preserved(self):
        self.assertEqual(self.run_cli("sync")[0], 0)
        for _, filename in version.INDEXES:
            target = self.root / filename
            target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
        before = self.snapshot()
        self.assertEqual(self.run_cli("check")[0], 0)
        self.assertEqual(self.run_cli("sync")[0], 0)
        self.assertEqual(self.snapshot(), before)

    def test_missing_canonical_marker_is_never_created_implicitly(self):
        (self.root / "VERSION").unlink()
        self.assert_rejected_without_writes("sync")
        self.assert_rejected_without_writes("bump")

    def test_no_custom_skills_is_rejected_even_with_library_artifacts(self):
        self.skill.unlink()
        self.skill.parent.rmdir()
        self.assert_rejected_without_writes("sync")

    def test_invalid_stable_versions_never_mutate(self):
        for invalid in ("1.2", "v1.2.3", "01.2.3", "1.02.3", "1.2.03",
                        "1.2.3-beta", "1.2.3+build", "-1.2.3", "1.2.3 ",
                        "１.2.3", "1.2.3\n\n", ""):
            with self.subTest(invalid=invalid):
                (self.root / "VERSION").write_bytes(invalid.encode("utf-8"))
                self.assert_rejected_without_writes("sync")
                self.assert_rejected_without_writes("bump")

    def test_marker_without_newline_is_supported_and_preserved(self):
        (self.root / "VERSION").write_bytes(b"0.1.0")
        self.assertEqual(self.run_cli("bump")[0], 0)
        self.assertEqual((self.root / "VERSION").read_bytes(), b"0.1.1")

    def test_yaml_version_errors_are_rejected_before_any_mutation(self):
        cases = (
            "owner: unchanged\n",
            "metadata: {}\n",
            "metadata: {owner: unchanged}\n",
            "metadata: {version: 0.1.0}\nmetadata: {version: 0.1.0}\n",
            "metadata: {version: 0.1.0, version: 0.1.0}\n",
            "metadata: {version: 1.0}\n",
            "metadata: {version: true}\n",
            "metadata: {version: [0.1.0]}\n",
            "metadata: {version: 01.1.0}\n",
            "metadata: {version: '1.2.3-beta'}\n",
            "metadata: {version: '0.1.0\"}\n",
            "metadata:\n\tversion: 0.1.0\n",
            "version: 0.1.0\nmetadata: {version: 0.1.0}\n",
            "metadata:\n  version: |-\n    0.1.0\n",
            "defaults: &v 0.1.0\nmetadata: {version: *v}\n",
            "defaults: &m {version: 0.1.0}\nmetadata: *m\n",
            "metadata: &m {version: 0.1.0}\ncopy: *m\n",
            "metadata: {version: &v 0.1.0}\ncopy: *v\n",
            "defaults: &m {version: 0.1.0}\nmetadata: {<<: *m}\n",
            "defaults: &m {metadata: {version: 0.1.0}}\n<<: *m\n",
        )
        for content in cases:
            with self.subTest(frontmatter=content):
                make_skill(self.root, "z-bad", frontmatter=
                           "name: invalid\ndescription: Invalid fixture.\n" + content)
                self.assert_rejected_without_writes("sync")
                self.assert_rejected_without_writes("bump")
                self.assert_rejected_without_writes("check")

    def test_flow_yaml_scalar_spans_preserve_tags_comments_and_other_values(self):
        target = make_skill(self.root, "complex", newline="\r\n", frontmatter=
                            "name: complex\ndescription: >-\n"
                            "  Preserve this multiline description.\n"
                            "  Keep version=7.6.5 in unrelated text.\n"
                            "notes: &notes {owner: unchanged}\n"
                            "copy: *notes\n"
                            'metadata: {owner: unchanged, version: !!str "7.6.5", '
                            'other-version: "7.6.5"} # retain this comment\n')
        before = target.read_bytes()
        self.assertEqual(self.run_cli("sync")[0], 0)
        self.assertEqual(target.read_bytes(), before.replace(
            b'version: !!str "7.6.5"', b'version: !!str "0.1.0"', 1))
        self.assertEqual(gi.parse_skill_metadata(target)["version"], "0.1.0")
        self.assertEqual(self.run_cli("check")[0], 0)

    def test_equivalent_escaped_string_is_not_rewritten_until_version_changes(self):
        target = make_skill(self.root, "escaped", frontmatter=
                            "name: escaped\ndescription: An escaped scalar.\n"
                            'metadata: {version: "0.1.\\x30"}\n')
        before = target.read_bytes()
        self.assertEqual(self.run_cli("sync")[0], 0)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self.run_cli("check")[0], 0)
        self.assertEqual(self.run_cli("bump")[0], 0)
        self.assertEqual(target.read_bytes(), before.replace(b'"0.1.\\x30"', b'"0.1.1"'))

    def test_legacy_duplicate_and_malformed_index_metadata_fail_preflight(self):
        cases = (
            "areas=software-development",
            "areas=software-development; targets=runtime-agnostic; version=0.1.0",
            "areas=software-development; areas=work-management; targets=runtime-agnostic",
            "areas=software-development; targets=runtime-agnostic; owner=",
            "areas=software-development; targets=runtime-agnostic; garbage",
            "areas=nonsense; targets=runtime-agnostic",
        )
        for index in cases:
            with self.subTest(index=index):
                make_skill(self.root, "z-bad", index=index)
                self.assert_rejected_without_writes("sync")
                self.assert_rejected_without_writes("bump")
                self.assert_rejected_without_writes("check")

    def test_missing_and_multiple_index_comments_fail_before_mutation(self):
        target = make_skill(self.root, "z-bad")
        valid = target.read_bytes()
        for content in (b"---\ndescription: No index metadata.\n---\n",
                        valid + b"\n<!-- index: areas=software-development; "
                        b"targets=runtime-agnostic -->\n"):
            with self.subTest(content=content):
                target.write_bytes(content)
                self.assert_rejected_without_writes("bump")

    def test_all_generator_inputs_are_validated_before_writes(self):
        make_skill(self.root, "z-valid", release="9.9.9")
        library = self.root / "agents" / "agents-item.md"
        library.write_bytes(b"missing metadata\n")
        self.assert_rejected_without_writes("sync")
        self.assert_rejected_without_writes("bump")

    def test_custom_skill_container_without_flat_skill_is_rejected(self):
        (self.root / "skills" / "vendor" / "nested").mkdir(parents=True)
        self.assert_rejected_without_writes("sync")

    def test_invalid_index_target_is_rejected_before_mirror_updates(self):
        make_skill(self.root, "z-valid", release="9.9.9")
        (self.root / "index.md").mkdir()
        self.assert_rejected_without_writes("sync")

    def create_symlink(self, target: Path, link: Path, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks are unavailable: {error}")

    def test_linked_skill_directory_is_not_followed(self):
        external = self.tmp / "outside"
        outside_skill = make_skill(external, "linked", release="9.9.9")
        original = outside_skill.read_bytes()
        self.create_symlink(outside_skill.parent, self.root / "skills" / "linked",
                            directory=True)
        status, _, error = self.run_cli("bump")
        self.assertEqual(status, 1, error)
        self.assertEqual(outside_skill.read_bytes(), original)
        self.assertEqual((self.root / "VERSION").read_bytes(), b"0.1.0\n")
        self.assertEqual(gi.parse_skill_metadata(self.skill)["version"], "0.1.0")

    def test_symlinked_custom_skill_root_is_rejected(self):
        destination = self.tmp / "moved-skills"
        (self.root / "skills").rename(destination)
        self.create_symlink(destination, self.root / "skills", directory=True)
        status, _, error = self.run_cli("bump")
        self.assertEqual(status, 1, error)
        self.assertEqual((self.root / "VERSION").read_bytes(), b"0.1.0\n")
        self.assertEqual(gi.parse_skill_metadata(destination / "sample" / "SKILL.md")["version"],
                         "0.1.0")

    def test_symlinked_file_targets_are_rejected_even_inside_repository(self):
        for relative in ("VERSION", "skills/sample/SKILL.md", "index.md"):
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_bytes() if path.exists() else b"outside data\n"
                other = self.root / "untouched-target"
                other.write_bytes(original)
                if path.exists():
                    path.unlink()
                self.create_symlink(other, path)
                status, _, error = self.run_cli("bump")
                self.assertEqual(status, 1, error)
                self.assertTrue(path.is_symlink())
                self.assertEqual(other.read_bytes(), original)
                path.unlink()
                if relative != "index.md":
                    path.write_bytes(original)
                other.unlink()

    def test_concurrent_body_edit_during_staging_is_preserved_before_any_replacement(self):
        original = self.skill.read_bytes()
        stage = version._stage
        for command in ("sync", "bump"):
            with self.subTest(command=command):
                before = self.snapshot()
                concurrent = original + b"\nConcurrent body edit during staging.\n"

                def edit_while_staging(target, content, staging):
                    temporary = stage(target, content, staging)
                    self.skill.write_bytes(concurrent)
                    return temporary

                with patch.object(version, "_stage", side_effect=edit_while_staging), \
                     patch.object(version.os, "replace", wraps=os.replace) as replace:
                    status, _, error = self.run_cli(command)
                self.assertEqual(status, 1, error)
                self.assertIn("update conflict", error)
                replace.assert_not_called()
                expected = dict(before)
                expected[str(self.skill.relative_to(self.root))] = concurrent
                self.assertEqual(self.snapshot(), expected)
                self.assertFalse(list(self.root.rglob(".version-*.tmp")))
                self.skill.write_bytes(original)

    def test_concurrent_body_edit_between_replacements_is_not_overwritten(self):
        second = make_skill(self.root, "z-second")
        before = self.snapshot()
        concurrent = second.read_bytes() + b"\nConcurrent body edit between replacements.\n"
        replace = os.replace

        def edit_after_first_replacement(source, destination):
            result = replace(source, destination)
            if Path(destination) == self.skill:
                second.write_bytes(concurrent)
            return result

        with patch.object(version.os, "replace", side_effect=edit_after_first_replacement):
            status, _, error = self.run_cli("bump")
        self.assertEqual(status, 1, error)
        self.assertIn("update conflict", error)
        expected = dict(before)
        expected[str(second.relative_to(self.root))] = concurrent
        self.assertEqual(self.snapshot(), expected)
        self.assertFalse(list(self.root.rglob(".version-*.tmp")))

    def test_rollback_preserves_concurrent_body_edit_in_already_applied_skill(self):
        self.assertEqual(self.run_cli("sync")[0], 0)
        before = self.snapshot()
        replace = os.replace
        concurrent = None

        def fail_marker_after_edit(source, destination):
            nonlocal concurrent
            if Path(destination) == self.root / "VERSION":
                concurrent = self.skill.read_bytes() + b"\nConcurrent body edit after apply.\n"
                self.skill.write_bytes(concurrent)
                raise OSError("injected canonical marker failure")
            return replace(source, destination)

        with patch.object(version.os, "replace", side_effect=fail_marker_after_edit):
            status, _, error = self.run_cli("bump")
        self.assertEqual(status, 1, error)
        self.assertIn("rollback conflict", error)
        self.assertIsNotNone(concurrent)
        expected = dict(before)
        expected[str(self.skill.relative_to(self.root))] = concurrent
        self.assertEqual(self.snapshot(), expected)
        self.assertFalse(list(self.root.rglob(".version-*.tmp")))

    def test_rollback_does_not_delete_new_index_changed_by_another_writer(self):
        before = self.snapshot()
        index = self.root / "index.md"
        replace = os.replace
        concurrent = None

        def fail_marker_after_index_edit(source, destination):
            nonlocal concurrent
            if Path(destination) == self.root / "VERSION":
                concurrent = index.read_bytes() + b"\nConcurrent index edit after creation.\n"
                index.write_bytes(concurrent)
                raise OSError("injected canonical marker failure")
            return replace(source, destination)

        with patch.object(version.os, "replace", side_effect=fail_marker_after_index_edit):
            status, _, error = self.run_cli("bump")
        self.assertEqual(status, 1, error)
        self.assertIn("rollback conflict", error)
        self.assertIsNotNone(concurrent)
        expected = dict(before)
        expected["index.md"] = concurrent
        self.assertEqual(self.snapshot(), expected)
        self.assertFalse(list(self.root.rglob(".version-*.tmp")))

    def test_canonical_marker_is_replaced_last_and_failure_rolls_back(self):
        self.assertEqual(self.run_cli("sync")[0], 0)
        before = self.snapshot()
        replace = os.replace
        replacements = []

        def fail_marker(source, destination):
            destination = Path(destination)
            replacements.append(destination)
            if destination == self.root / "VERSION":
                self.assertEqual(gi.parse_skill_metadata(self.skill)["version"], "0.1.1")
                raise OSError("injected canonical marker failure")
            return replace(source, destination)

        with patch.object(version.os, "replace", side_effect=fail_marker):
            status, _, error = self.run_cli("bump")
        self.assertEqual(status, 1, error)
        self.assertIn("injected canonical marker failure", error)
        self.assertIn(self.root / "VERSION", replacements)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.root.rglob(".version-*.tmp")))

    def test_missing_indexes_are_removed_again_if_commit_fails(self):
        before = self.snapshot()
        replace = os.replace

        def fail_marker(source, destination):
            if Path(destination) == self.root / "VERSION":
                raise OSError("injected commit failure")
            return replace(source, destination)

        with patch.object(version.os, "replace", side_effect=fail_marker):
            self.assertEqual(self.run_cli("bump")[0], 1)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.root.rglob(".version-*.tmp")))

    def test_staging_failure_leaves_every_original_untouched(self):
        before = self.snapshot()
        mkstemp = tempfile.mkstemp
        calls = 0

        def fail_staging(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected staging failure")
            return mkstemp(*args, **kwargs)

        with patch.object(version.tempfile, "mkstemp", side_effect=fail_staging):
            status, _, error = self.run_cli("bump")
        self.assertEqual(status, 1, error)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.root.rglob(".version-*.tmp")))

    def test_cli_uses_root_of_copied_script_not_working_directory(self):
        scripts = self.root / "scripts"
        scripts.mkdir()
        for filename in ("version.py", "generate_index.py", "skill_metadata.py"):
            shutil.copyfile(SCRIPTS / filename, scripts / filename)
        result = subprocess.run([sys.executable, str(scripts / "version.py"),
                                 "bump"], cwd=self.tmp, capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0.1.1\n")
        self.assertEqual((self.root / "VERSION").read_bytes(), b"0.1.1\n")
        self.assert_indexes_current()
        before = self.snapshot()
        timestamps = {str(p.relative_to(self.root)): p.stat().st_mtime_ns
                      for p in self.root.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, str(scripts / "version.py"), "check"],
                                cwd=self.tmp, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({str(p.relative_to(self.root)): p.stat().st_mtime_ns
                          for p in self.root.rglob("*") if p.is_file()}, timestamps)
        self.assertFalse((scripts / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
