#!/usr/bin/env python3
"""Tests for inventory.py on synthetic skill trees. Run: python test_inventory.py"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory  # noqa: E402


def skill(root: Path, name: str, description: str = "Use when testing.", extra: str = "",
          body: str = "", newline: str = "\n", dirname: str | None = None) -> Path:
    directory = root / (dirname or name)
    directory.mkdir(parents=True)
    text = f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n# {name}\n{body}"
    (directory / "SKILL.md").write_bytes(text.replace("\n", newline).encode("utf-8"))
    return directory


def make_dir_link(link: Path, target: Path) -> bool:
    """Directory symlink, else a Windows junction; False when the OS refuses both."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return True
        except (ImportError, OSError):
            pass
    return False


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_cli(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env or {}, clear=False), redirect_stdout(out), redirect_stderr(err):
            code = inventory.main(list(argv))
        report = json.loads(out.getvalue()) if out.getvalue() else None
        return code, report, err.getvalue()

    def kinds(self, report, name=None):
        return {f["kind"] for f in report["findings"] if name is None or f["skill"] == name}

    def by_name(self, report, name):
        return next(s for s in report["skills"] if s["name"] == name)

    def test_crlf_folded_description_and_clean_exit(self):
        root = self.tmp / "skills"
        skill(root, "alpha", description=">-\n  Use when parsing.\n  Second line.",
              extra="metadata:\n  kind: \"entry\"\n", newline="\r\n")
        code, report, _ = self.run_cli("--root", str(root))
        self.assertEqual(code, 0, report["findings"])
        alpha = self.by_name(report, "alpha")
        self.assertEqual(alpha["description"], "Use when parsing. Second line.")
        self.assertEqual(alpha["kind"], "entry")
        self.assertEqual(report["totals"]["visible_names"], 1)

    def test_hidden_flags_and_codex_policy(self):
        root = self.tmp / "skills"
        both = skill(root, "both", extra="disable-model-invocation: true\n")
        (both / "agents").mkdir()
        (both / "agents" / "openai.yaml").write_text(
            "interface:\n  display_name: \"Both\"\npolicy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
        skill(root, "frontmatter-only", extra="disable-model-invocation: true\n")
        skill(root, "camel", extra="disableModelInvocation: true\n")
        skill(root, "quoted", extra="disable-model-invocation: \"true\"\n")
        skill(root, "menu-off", extra="user-invocable: false\n")
        _, report, _ = self.run_cli("--root", str(root))
        self.assertEqual(self.by_name(report, "both")["hidden"],
                         {"disable_model_invocation": True, "codex_allow_implicit": False, "opencode_autoinvoke": None})
        self.assertEqual(self.kinds(report, "both"), set())
        self.assertIn("codex-policy-missing", self.kinds(report, "frontmatter-only"))
        self.assertIn("hidden-key-camelcase", self.kinds(report, "camel"))
        self.assertIn("hidden-not-boolean", self.kinds(report, "quoted"))
        self.assertIn("user-invocable-false", self.kinds(report, "menu-off"))
        self.assertEqual(report["totals"]["visible_names"], 3)

    def test_quality_findings(self):
        root = self.tmp / "skills"
        skill(root, "long", description="x" * 1100)
        skill(root, "wrong", dirname="wrong-dir")
        bundled = skill(root, "bundled", body="See [guide](references/guide.md) and `scripts/gone.py`.\n")
        (bundled / "references").mkdir()
        (bundled / "references" / "guide.md").write_text("guide\n", encoding="utf-8")
        (bundled / "references" / "orphan.md").write_text("orphan\n", encoding="utf-8")
        (root / "broken").mkdir()
        (root / "broken" / "SKILL.md").write_text("no frontmatter\n", encoding="utf-8")
        _, report, _ = self.run_cli("--root", str(root))
        self.assertIn("description-over-cap", self.kinds(report, "long"))
        self.assertIn("name-mismatch", self.kinds(report, "wrong"))
        self.assertEqual(self.by_name(report, "bundled")["broken_links"], ["scripts/gone.py"])
        self.assertEqual(self.by_name(report, "bundled")["unreferenced_files"], ["references/orphan.md"])
        self.assertIn("frontmatter-invalid", self.kinds(report, "broken"))

    def test_same_name_diverged_aliases_and_same_content(self):
        first, second = self.tmp / "a", self.tmp / "b"
        skill(first, "alpha", body="one\n")
        skill(second, "alpha", body="two\n")
        skill(first, "twin", dirname="twin-a")
        shutil.copytree(first / "twin-a", second / "twin-b")
        code, report, _ = self.run_cli("--root", str(first), "--root", str(second))
        self.assertEqual(code, 1)
        alpha = next(d for d in report["duplicates"]["by_name"] if d["name"] == "alpha")
        self.assertFalse(alpha["same_content"])
        twin = next(d for d in report["duplicates"]["by_name"] if d["name"] == "twin")
        self.assertTrue(twin["same_content"])
        self.assertIn("same-name-diverged", self.kinds(report, "alpha"))
        self.assertNotIn("same-name-diverged", self.kinds(report, "twin"))

    def test_sibling_closure_flat(self):
        root = self.tmp / "skills"
        skill(root, "parent", body="Read ../child/SKILL.md (relative to this skill's directory) and follow it.\n"
                                    "Also ../absent/SKILL.md and ../child/SKILL.md#anchor.\n")
        skill(root, "child")
        _, report, _ = self.run_cli("--root", str(root))
        statuses = {l["ref"]: l["status"] for l in self.by_name(report, "parent")["sibling_links"]}
        self.assertEqual(statuses, {"../child/SKILL.md": "ok", "../absent/SKILL.md": "missing"})
        self.assertIn("closure-missing", self.kinds(report, "parent"))

    def test_nested_reference_back_link_is_intra_skill(self):
        root = self.tmp / "skills"
        parent = skill(root, "parent", body="See [x](references/x.md).\n")
        (parent / "references").mkdir()
        (parent / "references" / "x.md").write_text("Back to ../SKILL.md.\n", encoding="utf-8")
        _, report, _ = self.run_cli("--root", str(root))
        self.assertEqual(self.by_name(report, "parent")["sibling_links"], [])

    def test_nested_reference_sibling_is_relative_to_its_file(self):
        root = self.tmp / "skills"
        parent = skill(root, "parent", body="See [x](references/x.md).\n")
        (parent / "references").mkdir()
        (parent / "references" / "x.md").write_text(
            "Read [child](../../child/SKILL.md) and ../../absent/SKILL.md.\n", encoding="utf-8")
        skill(root, "child")
        _, report, _ = self.run_cli("--root", str(root))
        statuses = {l["ref"]: (l["source"], l["status"]) for l in self.by_name(report, "parent")["sibling_links"]}
        self.assertEqual(statuses, {"../../child/SKILL.md": ("references/x.md", "ok"),
                                    "../../absent/SKILL.md": ("references/x.md", "missing")})

    def test_other_skill_paths_in_prose_are_not_broken_links(self):
        root = self.tmp / "skills"
        skill(root, "gdd")
        skill(root, "port", body="The stage rule lives in skill `gdd` → `references/transport.md`.\n"
                                  "See [`scripts/tool.py`](../../scripts/tool.py).\n\n"
                                  "Run `scripts/own.py`.\n")
        _, report, _ = self.run_cli("--root", str(root))
        self.assertEqual(self.by_name(report, "port")["broken_links"], ["scripts/own.py"])

    def test_bundled_directory_needs_its_path_named(self):
        root = self.tmp / "skills"
        bundled = skill(root, "bundled", body="Keep a rollback path. Run `check.py`.\n")
        (bundled / "assets" / "rollback").mkdir(parents=True)
        (bundled / "assets" / "rollback" / "before.md").write_text("x\n", encoding="utf-8")
        (bundled / "scripts").mkdir()
        (bundled / "scripts" / "check.py").write_text("\n", encoding="utf-8")
        _, report, _ = self.run_cli("--root", str(root))
        self.assertEqual(self.by_name(report, "bundled")["unreferenced_files"], ["assets/rollback"])

    def test_linked_parent_resolves_lexically_and_physically_apart(self):
        source, host = self.tmp / "source", self.tmp / "host"
        skill(source, "parent", body="Read ../child/SKILL.md and follow it.\n")
        skill(source, "child")
        host.mkdir()
        if not make_dir_link(host / "parent", source / "parent"):
            self.skipTest("OS refused both a directory symlink and a junction")
        _, report, _ = self.run_cli("--root", str(host))
        parent = self.by_name(report, "parent")
        self.assertIn(parent["link"], ("symlink", "junction"))
        self.assertEqual(parent["realpath"], os.path.realpath(source / "parent"))
        self.assertEqual(parent["sibling_links"][0]["status"], "physical-only")
        self.assertIn("closure-physical-only", self.kinds(report, "parent"))

        skill(host, "child", body="diverged copy\n")
        _, report, _ = self.run_cli("--root", str(host))
        self.assertEqual(self.by_name(report, "parent")["sibling_links"][0]["status"], "diverged")
        shutil.rmtree(host / "child")
        shutil.copytree(source / "child", host / "child")
        _, report, _ = self.run_cli("--root", str(host))
        self.assertEqual(self.by_name(report, "parent")["sibling_links"][0]["status"], "ok-identical")

    def test_offered_listing_diff(self):
        root = self.tmp / "skills"
        skill(root, "alpha")
        skill(root, "secret", extra="disable-model-invocation: true\n")
        skill(root, "unlisted")
        listing = self.tmp / "listing.txt"
        listing.write_text("- alpha: Use when testing.\n- secret: Leaked.\n- plugin:remote: From a plugin.\n"
                           "- truncated\n", encoding="utf-8")
        _, report, _ = self.run_cli("--root", str(root), "--offered", str(listing))
        offered = report["offered"]
        self.assertEqual(offered["count"], 4)
        self.assertEqual(offered["without_description"], ["truncated"])
        self.assertEqual(offered["not_on_disk"], ["plugin:remote", "truncated"])
        self.assertEqual(offered["hidden_but_offered"], ["secret"])
        self.assertEqual(offered["visible_not_offered"], ["unlisted"])
        self.assertTrue({"hidden-but-offered", "listing-truncated"} <= self.kinds(report))

    def test_plugin_entry_never_matches_disk_copy(self):
        root = self.tmp / "skills"
        skill(root, "babysit", description="Babysit an open pull request until merge-ready.")
        listing = self.tmp / "listing.txt"
        listing.write_text("- babysit: Babysit an open pull request until merge-ready.\n"
                           "- ce:babysit: Babysit an open pull request until merge-ready.\n"
                           "- ce:weather: Report tomorrow's forecast.\n", encoding="utf-8")
        _, report, _ = self.run_cli("--root", str(root), "--offered", str(listing))
        offered = report["offered"]
        self.assertEqual(offered["not_on_disk"], ["ce:babysit", "ce:weather"])
        self.assertEqual(offered["offered_twice"], {"babysit": ["babysit", "ce:babysit"]})
        self.assertIn("offered-twice", self.kinds(report, "babysit"))
        self.assertEqual((report["overlap"][0]["a"], report["overlap"][0]["b"]), ("babysit", "ce:babysit"))

    def test_overlap_ranks_similar_descriptions(self):
        root = self.tmp / "skills"
        skill(root, "pdf-forms", description="Fill PDF forms, extract PDF fields, merge PDF pages.")
        skill(root, "pdf-tools", description="Extract PDF fields, merge PDF pages, split PDF documents.")
        skill(root, "weather", description="Report tomorrow's weather forecast.")
        _, report, _ = self.run_cli("--root", str(root))
        self.assertEqual((report["overlap"][0]["a"], report["overlap"][0]["b"]), ("pdf-forms", "pdf-tools"))
        self.assertNotIn("weather", {p["a"] for p in report["overlap"]} | {p["b"] for p in report["overlap"]})

    def test_host_preset_depth(self):
        config = self.tmp / "claude-config"
        skill(config / "skills", "flat")
        skill(config / "skills" / "category", "nested")
        _, report, _ = self.run_cli("--host", "claude", "--project", str(self.tmp / "project"),
                                    env={"CLAUDE_CONFIG_DIR": str(config)})
        labels = {r["label"]: r["exists"] for r in report["roots"]}
        self.assertEqual(labels, {"claude-user": True, "claude-project": False})
        self.assertIn("beyond-host-depth", self.kinds(report, "nested"))
        self.assertNotIn("beyond-host-depth", self.kinds(report, "flat"))
        self.assertNotIn("description-over-cap", self.kinds(report))

    def test_host_scoped_caps_and_omp_roots(self):
        config = self.tmp / "claude-config"
        skill(config / "skills", "wordy", description="x" * 600)
        env = {"CLAUDE_CONFIG_DIR": str(config)}
        _, report, _ = self.run_cli("--host", "claude", env=env)
        self.assertNotIn("description-over-cap", self.kinds(report, "wordy"))
        _, report, _ = self.run_cli("--root", str(config / "skills"))
        self.assertIn("description-over-cap", self.kinds(report, "wordy"))
        home = {"HOME": str(self.tmp / "home"), "USERPROFILE": str(self.tmp / "home")}
        _, report, _ = self.run_cli("--host", "omp", "--root", str(config / "skills"), env={**env, **home})
        self.assertNotIn("claude-user", {r["label"] for r in report["roots"]})

    def test_usage_errors_and_env_roots(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SKILL_SET_AUDIT_ROOTS", None)
            code, report, err = self.run_cli()
        self.assertEqual((code, report), (2, None))
        self.assertIn("no roots", err)
        code, _, err = self.run_cli("--root", str(self.tmp / "missing"))
        self.assertEqual(code, 2)
        self.assertIn("no root exists", err)
        root = self.tmp / "skills"
        skill(root, "alpha")
        code, report, _ = self.run_cli(env={"SKILL_SET_AUDIT_ROOTS": str(root)})
        self.assertEqual((code, report["roots"][0]["label"]), (0, "env"))
        code, _, _ = self.run_cli("--root", str(root), "--offered", str(self.tmp / "nope.txt"))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
