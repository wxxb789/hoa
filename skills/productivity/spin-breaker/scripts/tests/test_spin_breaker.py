#!/usr/bin/env python3
"""Offline CLI tests for skills/productivity/spin-breaker/scripts/spin_breaker.py."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
SCRIPT = SKILL_DIR / "scripts" / "spin_breaker.py"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
HOSTILE = "<script>alert(1)</script>"
STUB = (
    "import sys, pathlib;"
    " p = pathlib.Path(sys.argv[1]);"
    " p.write_text('ARGS=' + '|'.join(sys.argv[2:]) + '|STDIN|'"
    " + sys.stdin.buffer.read().decode('utf-8'), encoding='utf-8')"
)


def _yaml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class SpinBreakerCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.tmp = Path(self._temp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.config_root = self.tmp / "config"
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("SPIN_BREAKER_")}
        self.env["XDG_CONFIG_HOME"] = str(self.config_root)

    def _run(self, *args: str, stdin: str | None = None, cwd: Path | None = None,
             overrides: dict | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        env.update(overrides or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, encoding="utf-8", input=stdin,
            cwd=str(cwd) if cwd else None, env=env, creationflags=NO_WINDOW)

    def _store(self, bundle: str = "spin-breaker") -> Path:
        return self.repo / ".tmp-artifacts" / bundle / "parked-items.md"

    def test_park_breadcrumb_writes_exact_four_line_entry_and_rejects_empty_fields(self) -> None:
        result = self._run(
            "park", "--repo-root", str(self.repo), "--kind", "breadcrumb",
            "--outcome", "Ship the fix on the live surface",
            "--last-fact", "scripts/check.py:42 exits 0 against the live surface",
            "--eliminated", "stale config cache",
            "--next-command", "uv run scripts/check.py --surface live")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "parked")
        self.assertEqual(receipt["kind"], "breadcrumb")
        self.assertEqual(receipt["external_status"], "not_configured")
        store = self._store()
        self.assertEqual(receipt["local_path"], str(store))
        raw = store.read_bytes()
        self.assertNotIn(b"\r", raw)
        text = raw.decode("utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))
        lines = text.splitlines()
        self.assertEqual(len(lines), 6)
        self.assertRegex(
            lines[0], r"^## Restart breadcrumb — \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[2], "- outcome: Ship the fix on the live surface")
        self.assertEqual(lines[3],
                         "- last fact: scripts/check.py:42 exits 0 against the live surface")
        self.assertEqual(lines[4], "- eliminated: stale config cache")
        self.assertEqual(lines[5], "- next command: uv run scripts/check.py --surface live")

        empty = self._run(
            "park", "--repo-root", str(self.repo), "--kind", "breadcrumb",
            "--outcome", "outcome", "--last-fact", "   ",
            "--eliminated", "eliminated", "--next-command", "next")
        self.assertEqual(empty.returncode, 2)
        self.assertIn("--last-fact", empty.stderr)
        self.assertEqual(store.read_text(encoding="utf-8"), text)

        missing = self._run(
            "park", "--repo-root", str(self.repo), "--kind", "breadcrumb",
            "--last-fact", "fact", "--eliminated", "eliminated", "--next-command", "next")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--outcome", missing.stderr)
        self.assertEqual(store.read_text(encoding="utf-8"), text)

    def test_park_side_quest_appends_and_keeps_tmp_artifacts_root_clean(self) -> None:
        first = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                          "--title", "Idea A", "--why-deferred", "not in envelope",
                          "--origin-outcome", "original outcome", "--locator", "src/a.py:10")
        second = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                           "--title", "Idea B")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["status"], "parked")
        store = self._store()
        text = store.read_text(encoding="utf-8")
        self.assertIn("## Side quest — Idea A", text)
        self.assertIn("## Side quest — Idea B", text)
        self.assertLess(text.index("Idea A"), text.index("Idea B"))
        self.assertIn("- when: ", text)
        self.assertIn("- why deferred: not in envelope", text)
        self.assertIn("- origin outcome: original outcome", text)
        self.assertIn("- locator: src/a.py:10", text)
        self.assertEqual(sorted(p.name for p in (self.repo / ".tmp-artifacts").iterdir()),
                         ["spin-breaker"])
        self.assertEqual(
            sorted(p.name for p in (self.repo / ".tmp-artifacts" / "spin-breaker").iterdir()),
            [".gitignore", "parked-items.md"])
        self.assertEqual([p.name for p in self.repo.iterdir()], [".tmp-artifacts"])

        missing_title = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest")
        self.assertEqual(missing_title.returncode, 2)
        self.assertIn("--title", missing_title.stderr)
        traversal = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                              "--title", "Idea C", "--parking-bundle", "../escape")
        self.assertEqual(traversal.returncode, 2)
        self.assertIn("bundle", traversal.stderr.lower())
        self.assertFalse((self.tmp / "escape").exists())
        self.assertEqual(store.read_text(encoding="utf-8"), text)

    def test_config_resolution_precedence_flag_env_config_default(self) -> None:
        config = self.config_root / "spin-breaker" / "config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("parking_bundle: from-config\n", encoding="utf-8")

        def bundle_of(completed: subprocess.CompletedProcess[str]) -> str:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return Path(json.loads(completed.stdout)["local_path"]).parent.name

        config_only = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                                "--title", "config level")
        self.assertEqual(bundle_of(config_only), "from-config")

        env_level = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                              "--title", "env level",
                              overrides={"SPIN_BREAKER_PARKING_BUNDLE": "from-env"})
        self.assertEqual(bundle_of(env_level), "from-env")

        flag_level = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                               "--title", "flag level", "--parking-bundle", "from-flag",
                               overrides={"SPIN_BREAKER_PARKING_BUNDLE": "from-env"})
        self.assertEqual(bundle_of(flag_level), "from-flag")

        config.unlink()
        default_level = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                                  "--title", "default level")
        self.assertEqual(bundle_of(default_level), "spin-breaker")

        other_repo = self.tmp / "other-repo"
        env_root = self._run("park", "--kind", "side-quest", "--title", "env root",
                             cwd=self.tmp,
                             overrides={"SPIN_BREAKER_REPO_ROOT": str(other_repo)})
        self.assertEqual(bundle_of(env_root), "spin-breaker")
        self.assertEqual(Path(json.loads(env_root.stdout)["local_path"]),
                         other_repo / ".tmp-artifacts" / "spin-breaker" / "parked-items.md")

    def test_external_adapter_gate_text_stdin_and_failure(self) -> None:
        probe = self.tmp / "probe.txt"
        text_cmd = f'"{sys.executable}" -c "{STUB}" "{probe}"' + " {text}"
        stdin_cmd = f'"{sys.executable}" -c "{STUB}" "{probe}"'
        fail_cmd = f'"{sys.executable}" -c "import sys; sys.exit(3)"'

        guarded = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                            "--title", "guarded", "--parking-bundle", "b-guarded",
                            "--external-cmd", text_cmd)
        self.assertEqual(guarded.returncode, 0, guarded.stderr)
        self.assertEqual(json.loads(guarded.stdout)["external_status"], "skipped_unconfirmed")
        self.assertFalse(probe.exists())

        confirmed = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                              "--title", "confirmed", "--parking-bundle", "b-text",
                              "--external-cmd", text_cmd, "--confirm-external")
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        text_receipt = json.loads(confirmed.stdout)
        self.assertEqual(text_receipt["external_status"], "ok")
        entry = Path(text_receipt["local_path"]).read_text(encoding="utf-8")
        self.assertEqual(probe.read_text(encoding="utf-8"), "ARGS=" + entry + "|STDIN|")

        probe.unlink()
        via_stdin = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                              "--title", "stdin", "--parking-bundle", "b-stdin",
                              "--external-cmd", stdin_cmd, "--confirm-external")
        self.assertEqual(via_stdin.returncode, 0, via_stdin.stderr)
        stdin_receipt = json.loads(via_stdin.stdout)
        self.assertEqual(stdin_receipt["external_status"], "ok")
        entry = Path(stdin_receipt["local_path"]).read_text(encoding="utf-8")
        self.assertEqual(probe.read_text(encoding="utf-8"), "ARGS=|STDIN|" + entry)

        probe.unlink()
        failing = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                            "--title", "failing", "--parking-bundle", "b-fail",
                            "--external-cmd", fail_cmd, "--confirm-external")
        self.assertEqual(failing.returncode, 1)
        fail_receipt = json.loads(failing.stdout)
        self.assertEqual(fail_receipt["external_status"], "failed")
        self.assertEqual(fail_receipt["external_exit"], 3)
        self.assertFalse(probe.exists())
        self.assertIn("## Side quest — failing",
                      Path(fail_receipt["local_path"]).read_text(encoding="utf-8"))

        bad_timeout = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                                "--title", "timeout", "--parking-bundle", "b-timeout",
                                "--external-cmd", stdin_cmd, "--confirm-external",
                                "--external-timeout", "soon")
        self.assertEqual(bad_timeout.returncode, 2)
        self.assertIn("external_timeout", bad_timeout.stderr)
        self.assertFalse((self.repo / ".tmp-artifacts" / "b-timeout").exists())

        config = self.config_root / "spin-breaker" / "config.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(f"external_cmd: {_yaml_string(fail_cmd)}\n", encoding="utf-8")
        via_config = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                               "--title", "config adapter", "--parking-bundle", "b-config")
        self.assertEqual(via_config.returncode, 0, via_config.stderr)
        self.assertEqual(json.loads(via_config.stdout)["external_status"], "skipped_unconfirmed")

    def test_map_writes_self_contained_bundle_and_escapes_payloads(self) -> None:
        payload = {
            "outcome": f"Ship {HOSTILE} on the live surface",
            "verified_facts": [f"fact {HOSTILE}"],
            "hypotheses": [
                {"text": f"live {HOSTILE}", "status": "live", "note": f"note {HOSTILE}"},
                {"text": f"dead {HOSTILE}", "status": "eliminated"},
                f"plain live {HOSTILE}",
            ],
            "probe": {"command": f"run {HOSTILE}", "pass": f"pass {HOSTILE}",
                      "fail": f"fail {HOSTILE}"},
            "side_quests": [f"quest {HOSTILE}", {"title": f"named {HOSTILE}", "note": "later"}],
        }
        source = self.tmp / "board.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        result = self._run("map", "--repo-root", str(self.repo), "--input", str(source),
                           "--bundle", "board-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        bundle_dir = self.repo / ".tmp-artifacts" / "board-1"
        self.assertEqual(receipt["bundle"], "board-1")
        self.assertEqual(receipt["html_path"], str(bundle_dir / "board-1.html"))
        self.assertEqual(receipt["data_path"], str(bundle_dir / "_map_data.json"))
        self.assertEqual(sorted(p.name for p in (self.repo / ".tmp-artifacts").iterdir()),
                         ["board-1"])
        self.assertEqual(sorted(p.name for p in bundle_dir.iterdir()),
                         [".gitignore", "_map_data.json", "board-1.html"])

        raw_html = (bundle_dir / "board-1.html").read_bytes()
        self.assertNotIn(b"\r", raw_html)
        page = raw_html.decode("utf-8")
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertNotIn(HOSTILE, page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script", page.lower())
        self.assertNotIn("<link", page.lower())
        self.assertNotIn("@import", page)
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)
        self.assertIn("grid-template-columns: repeat(3", page)
        self.assertIn("prefers-color-scheme", page)
        self.assertIn("code { white-space: pre-wrap; overflow-wrap: anywhere; }", page)
        for heading in ("Target outcome", "live hypotheses", "Single discriminating probe",
                        "Eliminated", "Parked side quests"):
            self.assertIn(heading, page)
        for action in ("A. Run probe", "B. Freeze &amp; park", "C. Retire branch/approach"):
            self.assertIn(action, page)

        raw_data = (bundle_dir / "_map_data.json").read_bytes()
        self.assertNotIn(b"\r", raw_data)
        data_text = raw_data.decode("utf-8")
        self.assertNotIn(HOSTILE, data_text)
        stored = json.loads(data_text)
        self.assertEqual(stored["bundle"], "board-1")
        self.assertEqual(stored["outcome"], payload["outcome"])
        self.assertEqual(stored["verified_facts"], payload["verified_facts"])
        self.assertEqual(len(stored["hypotheses"]), 3)
        self.assertEqual(stored["hypotheses"][2]["status"], "live")
        self.assertEqual(stored["hypotheses"][1]["status"], "eliminated")
        self.assertEqual(stored["probe"]["command"], payload["probe"]["command"])
        self.assertEqual(stored["side_quests"][1]["title"], payload["side_quests"][1]["title"])

    def test_map_stdin_default_bundle_and_rejects_bad_bundles_and_inputs(self) -> None:
        feed = json.dumps({"outcome": "single outcome", "verified_facts": ["one fact"]})
        result = self._run("map", "--repo-root", str(self.repo), "--input", "-", stdin=feed)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertRegex(receipt["bundle"], r"^spin-map-\d{8}-\d{6}$")
        bundle_dir = self.repo / ".tmp-artifacts" / receipt["bundle"]
        self.assertTrue((bundle_dir / f"{receipt['bundle']}.html").is_file())
        self.assertTrue((bundle_dir / "_map_data.json").is_file())

        for bad_bundle in ("../escape", "a/b", "..", "bad\\path"):
            failed = self._run("map", "--repo-root", str(self.repo), "--input", "-",
                               "--bundle", bad_bundle, stdin=feed)
            self.assertEqual(failed.returncode, 2)
            self.assertIn("bundle", failed.stderr.lower())
        self.assertFalse((self.tmp / "escape").exists())
        self.assertEqual(sorted(p.name for p in (self.repo / ".tmp-artifacts").iterdir()),
                         [receipt["bundle"]])

        no_input = self._run("map", "--repo-root", str(self.repo))
        self.assertEqual(no_input.returncode, 2)

        for bad_input in ("not json", "[]", "{}", '{"outcome": "   "}',
                          '{"outcome": "x", "extras": []}',
                          '{"outcome": "x", "verified_facts": "not-a-list"}',
                          '{"outcome": "x", "hypotheses": [{"status": "live"}]}',
                          '{"outcome": "x", "hypotheses": [{"text": "t", "status": "maybe"}]}',
                          '{"outcome": "x", "probe": {"pass": "p"}}',
                          '{"outcome": "x", "side_quests": [{"note": "n"}]}'):
            failed = self._run("map", "--repo-root", str(self.repo), "--input", "-",
                               stdin=bad_input)
            self.assertEqual(failed.returncode, 2, bad_input)
            self.assertTrue(failed.stderr.startswith("spin_breaker:"), bad_input)
        self.assertEqual(sorted(p.name for p in (self.repo / ".tmp-artifacts").iterdir()),
                         [receipt["bundle"]])


    def test_bundle_guard_rejects_unsafe_names(self) -> None:
        feed = json.dumps({"outcome": "guarded"})
        bad_bundles = (".", "..", "C:outside", "NUL", "con.txt", "trail.", " lead",
                       "ctrl\x01", "../escape", "a/b", "bad\\path")
        for bad in bad_bundles:
            park = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                             "--title", "blocked", "--parking-bundle", bad)
            self.assertEqual(park.returncode, 2, bad)
            self.assertIn("spin_breaker:", park.stderr)
            mapping = self._run("map", "--repo-root", str(self.repo), "--input", "-",
                                "--bundle", bad, stdin=feed)
            self.assertEqual(mapping.returncode, 2, bad)
            self.assertIn("spin_breaker:", mapping.stderr)
        self.assertFalse((self.tmp / "escape").exists())
        self.assertFalse((self.repo / ".tmp-artifacts").exists())

    def test_bundle_guard_rejects_symlinked_artifacts_root(self) -> None:
        outside = self.tmp / "outside"
        outside.mkdir()
        artifacts = self.repo / ".tmp-artifacts"
        if sys.platform == "win32":
            created = subprocess.run(["cmd", "/c", "mklink", "/J", str(artifacts), str(outside)],
                                     capture_output=True, creationflags=NO_WINDOW)
            made = created.returncode == 0
            self.addCleanup(lambda: artifacts.rmdir() if artifacts.exists() else None)
        else:
            try:
                artifacts.symlink_to(outside, target_is_directory=True)
                made = True
            except OSError:
                made = False
            self.addCleanup(lambda: artifacts.unlink() if artifacts.exists() else None)
        if not made:
            self.skipTest("cannot create a directory junction or symlink here")
        result = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                           "--title", "escape attempt")
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr.lower())
        self.assertEqual(list(outside.iterdir()), [])

    def test_fields_reject_line_breaks_and_preserve_interior_spacing(self) -> None:
        forged = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                           "--title", "Idea\n\n## Forged")
        self.assertEqual(forged.returncode, 2)
        self.assertIn("--title", forged.stderr)
        carried = self._run("park", "--repo-root", str(self.repo), "--kind", "breadcrumb",
                            "--outcome", "o", "--last-fact", "f", "--eliminated", "e",
                            "--next-command", "line one\nline two")
        self.assertEqual(carried.returncode, 2)
        self.assertIn("--next-command", carried.stderr)
        carriage = self._run("park", "--repo-root", str(self.repo), "--kind", "breadcrumb",
                             "--outcome", "o", "--last-fact", "f", "--eliminated", "e",
                             "--next-command", "safe\rbad")
        self.assertEqual(carriage.returncode, 2)
        self.assertIn("--next-command", carriage.stderr)
        self.assertFalse((self.repo / ".tmp-artifacts").exists())

        spaced = self._run("park", "--repo-root", str(self.repo), "--kind", "breadcrumb",
                           "--outcome", "Ship  it", "--last-fact", "probe exits 0",
                           "--eliminated", "stale cache",
                           "--next-command", "rg -F 'a  b' file")
        self.assertEqual(spaced.returncode, 0, spaced.stderr)
        text = self._store().read_text(encoding="utf-8")
        self.assertIn("- outcome: Ship  it\n", text)
        self.assertIn("- next command: rg -F 'a  b' file\n", text)

    def test_external_validation_errors_are_clean_usage_errors(self) -> None:
        probe = self.tmp / "probe.txt"
        writing_cmd = f'"{sys.executable}" -c "{STUB}" "{probe}"'
        quiet_cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
        for flag, value in (("--external-cmd", "   "), ("--external-cmd", '"unterminated')):
            failed = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                               "--title", "bad adapter", flag, value)
            self.assertEqual(failed.returncode, 2, value)
            self.assertIn("spin_breaker:", failed.stderr)
            self.assertNotIn("Traceback", failed.stderr)
        for timeout in ("0", "-1"):
            failed = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                               "--title", "bad timeout", "--external-cmd", quiet_cmd,
                               "--confirm-external", "--external-timeout", timeout)
            self.assertEqual(failed.returncode, 2, timeout)
            self.assertIn("external_timeout", failed.stderr)
            self.assertNotIn("Traceback", failed.stderr)

        abbreviated = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                                "--title", "abbrev", "--external-cmd", writing_cmd, "--confirm")
        self.assertEqual(abbreviated.returncode, 2)
        self.assertFalse(probe.exists())
        self.assertFalse((self.repo / ".tmp-artifacts").exists())

    def test_malformed_config_yaml_is_a_usage_error(self) -> None:
        config = self.config_root / "spin-breaker" / "config.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("parking_bundle: [nested\n", encoding="utf-8")
        failed = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                           "--title", "config typo")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("spin_breaker:", failed.stderr)
        self.assertNotIn("Traceback", failed.stderr)
        self.assertFalse((self.repo / ".tmp-artifacts").exists())

    def test_strict_utf8_input_and_lone_surrogate_rejection(self) -> None:
        payload = {"outcome": "修复 café — clean", "verified_facts": ["fact"]}
        cjk = self._run("map", "--repo-root", str(self.repo), "--input", "-",
                        "--bundle", "utf8-board",
                        stdin=json.dumps(payload, ensure_ascii=False),
                        overrides={"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(cjk.returncode, 0, cjk.stderr)
        receipt = json.loads(cjk.stdout)
        self.assertEqual(receipt["bundle"], "utf8-board")
        page = Path(receipt["html_path"]).read_text(encoding="utf-8")
        self.assertIn("修复 café — clean", page)

        bom = self.tmp / "bom.json"
        bom.write_bytes(b"\xef\xbb\xbf" + json.dumps({"outcome": "bom outcome"}).encode("utf-8"))
        bom_run = self._run("map", "--repo-root", str(self.repo), "--input", str(bom),
                            "--bundle", "bom-board", overrides={"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(bom_run.returncode, 0, bom_run.stderr)

        surrogate = self._run("map", "--repo-root", str(self.repo), "--input", "-",
                              "--bundle", "surrogate-board", stdin='{"outcome": "\\ud800"}')
        self.assertEqual(surrogate.returncode, 2)
        self.assertIn("surrogate", surrogate.stderr)
        self.assertNotIn("Traceback", surrogate.stderr)
        self.assertFalse((self.repo / ".tmp-artifacts" / "surrogate-board").exists())

    def test_map_bundle_reuse_and_same_second_suffix_are_safe(self) -> None:
        feed = json.dumps({"outcome": "once"})
        first = self._run("map", "--repo-root", str(self.repo), "--input", "-",
                          "--bundle", "board-dup", stdin=feed)
        self.assertEqual(first.returncode, 0, first.stderr)
        html = self.repo / ".tmp-artifacts" / "board-dup" / "board-dup.html"
        before = html.read_bytes()
        duplicate = self._run("map", "--repo-root", str(self.repo), "--input", "-",
                              "--bundle", "board-dup", stdin=feed)
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("already exists", duplicate.stderr)
        self.assertEqual(html.read_bytes(), before)

        processes = [subprocess.Popen(
            [sys.executable, str(SCRIPT), "map", "--repo-root", str(self.repo),
             "--input", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=dict(self.env), creationflags=NO_WINDOW)
            for _ in range(4)]
        bundles = []
        for process in processes:
            stdout, stderr = process.communicate(feed)
            self.assertEqual(process.returncode, 0, stderr)
            bundles.append(json.loads(stdout)["bundle"])
        self.assertEqual(len(set(bundles)), 4)
        groups: dict[str, list[int]] = {}
        for bundle in bundles:
            match = re.match(r"^(spin-map-\d{8}-\d{6})(?:-(\d+))?$", bundle)
            self.assertIsNotNone(match, bundle)
            groups.setdefault(match.group(1), []).append(int(match.group(2) or 1))
        for suffixes in groups.values():
            self.assertEqual(sorted(suffixes), list(range(1, len(suffixes) + 1)))
        for bundle in bundles:
            self.assertTrue((self.repo / ".tmp-artifacts" / bundle / f"{bundle}.html").is_file())


    def test_park_refuses_symlinked_leaf_file(self) -> None:
        store = self.repo / ".tmp-artifacts" / "spin-breaker"
        store.mkdir(parents=True)
        outside = self.tmp / "outside.md"
        outside.write_text("original\n", encoding="utf-8")
        leaf = store / "parked-items.md"
        try:
            leaf.symlink_to(outside)
        except OSError:
            self.skipTest("cannot create a file symlink here")
        self.addCleanup(lambda: leaf.unlink() if leaf.is_symlink() else None)
        result = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                           "--title", "through link")
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr.lower())
        self.assertEqual(outside.read_text(encoding="utf-8"), "original\n")
        self.assertTrue(leaf.is_symlink())

    def test_external_command_split_preserves_windows_paths(self) -> None:
        probe = self.tmp / "probe.txt"
        unc = r"\\server\share\adapter.exe"
        unquoted = r"C:\dir\new\tool.exe"
        quoted_quote = 'a"b'
        template = (f'"{sys.executable}" -c "{STUB}" "{probe}" '
                    f'"{unc}" {unquoted} "a\\"b"')
        result = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                           "--title", "windows paths", "--parking-bundle", "b-paths",
                           "--external-cmd", template, "--confirm-external")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["external_status"], "ok")
        entry = Path(receipt["local_path"]).read_text(encoding="utf-8")
        recorded = probe.read_text(encoding="utf-8")
        self.assertEqual(recorded,
                         "ARGS=" + "|".join([unc, unquoted, quoted_quote]) + "|STDIN|" + entry)


    def test_external_text_placeholder_rejected_for_cmd_and_bat_adapters(self) -> None:
        for script in ("adapter.cmd", r'"C:\Tools\my adapter.bat"'):
            with self.subTest(script=script):
                refused = self._run("park", "--repo-root", str(self.repo), "--kind",
                                    "side-quest", "--title", "cmd adapter",
                                    "--external-cmd", f"{script} {{text}}",
                                    "--confirm-external")
                self.assertEqual(refused.returncode, 2)
                self.assertIn(".cmd/.bat", refused.stderr)
                self.assertIn("stdin", refused.stderr)
        self.assertFalse((self.repo / ".tmp-artifacts").exists())

        allowed = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                            "--title", "stdin mode", "--external-cmd", "adapter.cmd")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(json.loads(allowed.stdout)["external_status"], "skipped_unconfirmed")

    def test_park_refuses_hardlinked_leaf_file(self) -> None:
        store = self.repo / ".tmp-artifacts" / "spin-breaker"
        store.mkdir(parents=True)
        source = self.tmp / "README.md"
        source.write_text("shared content\n", encoding="utf-8")
        leaf = store / "parked-items.md"
        try:
            os.link(source, leaf)
        except OSError:
            self.skipTest("cannot create a hard link here")
        result = self._run("park", "--repo-root", str(self.repo), "--kind", "side-quest",
                           "--title", "through hard link")
        self.assertEqual(result.returncode, 2)
        self.assertIn("hard link", result.stderr)
        self.assertEqual(source.read_text(encoding="utf-8"), "shared content\n")
        self.assertEqual(leaf.read_text(encoding="utf-8"), "shared content\n")

    def test_bundles_stay_git_ignored_in_a_fresh_repository(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")
        git_repo = self.tmp / "git-repo"
        git_repo.mkdir()
        git = ["git", "-C", str(git_repo)]
        init = subprocess.run([*git, "init", "-q"], capture_output=True, creationflags=NO_WINDOW)
        self.assertEqual(init.returncode, 0, init.stderr)
        parked = self._run("park", "--repo-root", str(git_repo), "--kind", "side-quest",
                           "--title", "ignored")
        self.assertEqual(parked.returncode, 0, parked.stderr)
        mapped = self._run("map", "--repo-root", str(git_repo), "--input", "-",
                           "--bundle", "board-1", stdin=json.dumps({"outcome": "ignored"}))
        self.assertEqual(mapped.returncode, 0, mapped.stderr)
        status = subprocess.run([*git, "status", "--porcelain", "--untracked-files=all"],
                                capture_output=True, text=True, encoding="utf-8",
                                creationflags=NO_WINDOW)
        self.assertEqual(status.stdout, "")
        for relative in (".tmp-artifacts/spin-breaker/parked-items.md",
                         ".tmp-artifacts/board-1/board-1.html"):
            ignored = subprocess.run([*git, "check-ignore", "-q", relative],
                                     capture_output=True, creationflags=NO_WINDOW)
            self.assertEqual(ignored.returncode, 0, relative)


    def test_bundles_stay_git_ignored_with_comment_only_marker(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")
        git_repo = self.tmp / "git-repo"
        store = git_repo / ".tmp-artifacts" / "spin-breaker"
        store.mkdir(parents=True)
        marker = store / ".gitignore"
        marker.write_text("# comment only\n", encoding="utf-8")
        init = subprocess.run(["git", "-C", str(git_repo), "init", "-q"],
                              capture_output=True, creationflags=NO_WINDOW)
        self.assertEqual(init.returncode, 0, init.stderr)
        parked = self._run("park", "--repo-root", str(git_repo), "--kind", "side-quest",
                           "--title", "comment marker")
        self.assertEqual(parked.returncode, 0, parked.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "# comment only\n*\n")
        status = subprocess.run(["git", "-C", str(git_repo), "status", "--porcelain",
                                 "--untracked-files=all"],
                                capture_output=True, text=True, encoding="utf-8",
                                creationflags=NO_WINDOW)
        self.assertEqual(status.stdout, "")


if __name__ == "__main__":
    unittest.main()
