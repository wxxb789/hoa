#!/usr/bin/env python3
"""Offline tests for skill_config.

Run: python -m unittest scripts.test_skill_config -v
Builds synthetic config trees under .tmp-artifacts/ so no operator config is read.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parent / "skill_config.py"
ARTIFACTS = SCRIPT.parent.parent / ".tmp-artifacts" / "skill-config-tests"
spec = importlib.util.spec_from_file_location("skill_config", SCRIPT)
sc = importlib.util.module_from_spec(spec)
sys.modules["skill_config"] = sc
spec.loader.exec_module(sc)


def make_temp_root() -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=ARTIFACTS))


def write_config(root: Path, skill: str, text: str, *, encoding="utf-8") -> Path:
    path = root / skill / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


class SkillConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def env(self, **values):
        return {key: str(value) for key, value in values.items()}

    def test_precedence_flag_env_config_default(self):
        write_config(self.tmp, "demo", "some_key: from-config\n")
        env = self.env(XDG_CONFIG_HOME=self.tmp, DEMO_SOME_KEY="from-env")
        self.assertEqual(
            sc.resolve("demo", "some_key", flag="from-flag", env=env, default="from-default"),
            "from-flag")
        self.assertEqual(
            sc.resolve("demo", "some_key", env=env, default="from-default"), "from-env")
        self.assertEqual(
            sc.resolve("demo", "some_key", env=self.env(XDG_CONFIG_HOME=self.tmp),
                       default="from-default"), "from-config")
        self.assertEqual(
            sc.resolve("demo", "some_key", env=self.env(XDG_CONFIG_HOME=self.tmp / "empty"),
                       default="from-default"), "from-default")

    def test_empty_flag_and_env_are_not_supplied(self):
        write_config(self.tmp, "demo", "some_key: from-config\n")
        env = self.env(XDG_CONFIG_HOME=self.tmp, DEMO_SOME_KEY="")
        self.assertEqual(
            sc.resolve("demo", "some_key", flag="", env=env, default="from-default"),
            "from-config")

    def test_env_name_derivation(self):
        self.assertEqual(sc.env_name("demo-skill", "some_key"), "DEMO_SKILL_SOME_KEY")
        self.assertEqual(sc.env_name("demo-skill", "some-key"), "DEMO_SKILL_SOME_KEY")
        self.assertEqual(sc.env_name("goal-driven-delivery", "GDD_STATE_FILE"),
                         "GDD_STATE_FILE")

    def test_xdg_then_home_then_root(self):
        xdg = self.tmp / "xdg"
        home = self.tmp / "home"
        explicit = self.tmp / "explicit"
        write_config(xdg, "demo", "some_key: from-xdg\n")
        write_config(home / ".config", "demo", "some_key: from-home\n")
        write_config(explicit, "demo", "some_key: from-root\n")
        self.assertEqual(
            sc.resolve("demo", "some_key",
                       env=self.env(XDG_CONFIG_HOME=xdg, HOME=home)), "from-xdg")
        self.assertEqual(
            sc.resolve("demo", "some_key", env=self.env(HOME=home)), "from-home")
        self.assertEqual(
            sc.resolve("demo", "some_key", env=self.env(HOME=home), root=explicit),
            "from-root")

    def test_missing_key_and_missing_file_use_default(self):
        write_config(self.tmp, "demo", "other_key: value\n")
        self.assertEqual(
            sc.resolve("demo", "some_key", env=self.env(XDG_CONFIG_HOME=self.tmp),
                       default="fallback"), "fallback")
        self.assertEqual(
            sc.resolve("demo", "some_key", env=self.env(XDG_CONFIG_HOME=self.tmp / "absent"),
                       default="fallback"), "fallback")

    def test_unreadable_config_names_the_path(self):
        directory = self.tmp / "demo" / "config.yaml"
        directory.mkdir(parents=True)
        with self.assertRaises(sc.ConfigError) as caught:
            sc.resolve("demo", "some_key", env=self.env(XDG_CONFIG_HOME=self.tmp))
        self.assertIn(str(directory), str(caught.exception))
        self.assertIn("not a regular file", str(caught.exception))

    def test_invalid_utf8_names_the_path(self):
        path = self.tmp / "demo" / "config.yaml"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"some_key: \xff\n")
        with self.assertRaises(sc.ConfigError) as caught:
            sc.resolve("demo", "some_key", env=self.env(XDG_CONFIG_HOME=self.tmp))
        self.assertIn(str(path), str(caught.exception))
        self.assertIn("not valid UTF-8", str(caught.exception))

    def test_flat_subset_scalars_comments_and_quotes(self):
        write_config(
            self.tmp, "demo",
            "\n"
            "# a comment\n"
            "  # an indented comment is still only a comment\n"
            "plain: value\n"
            "quoted: \"a # b: c\"   # trailing comment\n"
            "single: 'it''s fine'\n"
            "path: C:\\temp\\file\n"
            "hash: value#notacomment\n"
            "slash: \"a\\/b\"\n"
            "empty_quoted: \"\"\n",
        )
        values = sc.read_config(self.tmp / "demo" / "config.yaml")
        self.assertEqual(values["plain"], "value")
        self.assertEqual(values["quoted"], "a # b: c")
        self.assertEqual(values["single"], "it's fine")
        self.assertEqual(values["path"], "C:\\temp\\file")
        self.assertEqual(values["hash"], "value#notacomment")
        self.assertEqual(values["slash"], "a/b")
        self.assertEqual(values["empty_quoted"], "")

    def test_crlf_and_bom(self):
        path = self.tmp / "demo" / "config.yaml"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xef\xbb\xbfsome_key: value\r\n")
        self.assertEqual(sc.read_config(path), {"some_key": "value"})

    def test_rejected_constructs_name_path_and_line(self):
        cases = [
            ("nested:\n  child: value\n", 1, "nested mappings"),
            ("parent: value\n  child: value\n", 2, "indentation"),
            ("anchor: &base value\n", 1, "anchors"),
            ("alias: *base\n", 1, "aliases"),
            ("flow: {a: b}\n", 1, "flow collections"),
            ("sequence: [a, b]\n", 1, "flow collections"),
            ("block: |\n", 1, "block scalars"),
            ("tagged: !str value\n", 1, "not supported"),
            ("---\nsome_key: value\n", 1, "document markers"),
            ("...\nsome_key: value\n", 1, "document markers"),
            ("some_key value\n", 1, "expected 'key: value'"),
            ("some_key: value\nsome_key: again\n", 2, "duplicate key"),
            ("some_key: \"unterminated\n", 1, "unterminated quoted value"),
            ("some_key: \"bad \\q\"\n", 1, "unsupported escape"),
            ("some_key: \"a\" trailing\n", 1, "trailing characters"),
            ("some_key:\n", 1, "missing value"),
            ("some_key: # comment\n", 1, "missing value"),
            ("&bad: value\n", 1, "invalid key"),
        ]
        for text, line, reason in cases:
            with self.subTest(text=text):
                path = write_config(self.tmp, "demo", text)
                with self.assertRaises(sc.ConfigError) as caught:
                    sc.read_config(path)
                message = str(caught.exception)
                self.assertIn(str(path), message)
                self.assertIn(f":{line}:", message)
                self.assertIn(reason, message)

    def test_cli_provenance_line(self):
        path = write_config(self.tmp, "demo", "some_key: from-config\n")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(sc.main(["--skill", "demo", "--key", "some_key",
                                      "--root", str(self.tmp)]), 0)
        self.assertEqual(out.getvalue(),
                         f"some_key=from-config (from config {path})\n")

        with patch.dict(os.environ, {"DEMO_SOME_KEY": "from-env"}, clear=False):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(sc.main(["--skill", "demo", "--key", "some_key",
                                          "--root", str(self.tmp)]), 0)
        self.assertEqual(out.getvalue(), "some_key=from-env (from env DEMO_SOME_KEY)\n")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(sc.main(["--skill", "demo", "--key", "some_key",
                                      "--flag", "from-flag", "--root", str(self.tmp)]), 0)
        self.assertEqual(out.getvalue(), "some_key=from-flag (from flag)\n")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(sc.main(["--skill", "demo", "--key", "absent",
                                      "--default", "from-default", "--root", str(self.tmp)]), 0)
        self.assertEqual(out.getvalue(), "absent=from-default (from default)\n")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(sc.main(["--skill", "demo", "--key", "absent",
                                      "--root", str(self.tmp)]), 0)
        self.assertEqual(out.getvalue(), "absent=(unset) (from default)\n")

    def test_cli_malformed_config_exits_one(self):
        path = write_config(self.tmp, "demo", "nested:\n  child: value\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(sc.main(["--skill", "demo", "--key", "some_key",
                                      "--root", str(self.tmp)]), 1)
        self.assertIn(f"{path}:1:", err.getvalue())

    def test_gdd_state_file_from_config_and_flag(self):
        path = write_config(self.tmp, "goal-driven-delivery",
                            "GDD_STATE_FILE: /srv/state/from-config.tsv\n")
        self.assertEqual(
            sc.config_path("goal-driven-delivery", env=self.env(XDG_CONFIG_HOME=self.tmp)),
            path)
        self.assertEqual(
            sc.resolve("goal-driven-delivery", "GDD_STATE_FILE",
                       env=self.env(XDG_CONFIG_HOME=self.tmp)),
            "/srv/state/from-config.tsv")
        self.assertEqual(
            sc.resolve("goal-driven-delivery", "GDD_STATE_FILE", flag="/cli/ledger.tsv",
                       env=self.env(XDG_CONFIG_HOME=self.tmp)),
            "/cli/ledger.tsv")
        self.assertEqual(
            sc.resolve("goal-driven-delivery", "GDD_STATE_FILE",
                       env=self.env(XDG_CONFIG_HOME=self.tmp,
                                    GDD_STATE_FILE="/env/ledger.tsv")),
            "/env/ledger.tsv")

    def test_invalid_skill_and_key_are_rejected(self):
        for skill, key in (("../escape", "key"), ("demo", "bad.key"), ("", "key"),
                           ("demo", "")):
            with self.subTest(skill=skill, key=key):
                with self.assertRaises(sc.ConfigError):
                    sc.resolve(skill, key, env={})


if __name__ == "__main__":
    unittest.main()
