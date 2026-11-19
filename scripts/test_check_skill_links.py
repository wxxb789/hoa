#!/usr/bin/env python3
"""Offline tests for check_skill_links: sibling and skill-relative references.

Run: python scripts/test_check_skill_links.py
Builds synthetic skills/ trees under .tmp-artifacts/; `gate:skill-links` runs the
check against this repository's own skills.
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
SCRIPT = Path(__file__).resolve().parent / "check_skill_links.py"
ARTIFACTS = SCRIPT.parent.parent / ".tmp-artifacts" / "skill-links-tests"
spec = importlib.util.spec_from_file_location("check_skill_links", SCRIPT)
links = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = links  # dataclass field resolution needs the module registered
spec.loader.exec_module(links)


def make_temp_root() -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=ARTIFACTS))


class CheckSkillLinksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.skills = self.tmp / "skills"
        self.skills.mkdir()

    def skill(self, name: str, body: str = "", files: dict[str, str] | None = None) -> Path:
        directory = self.skills / name
        directory.mkdir()
        (directory / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}\n",
                                            encoding="utf-8")
        for relative, text in (files or {}).items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return directory

    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(links, "SKILLS", self.skills), \
             redirect_stdout(out), redirect_stderr(err):
            code = links.main([])
        return code, out.getvalue(), err.getvalue()

    def test_sibling_references_resolve_relative_to_their_own_file(self):
        self.skill("child", files={"references/table.md": "rows\n"})
        self.skill("parent", "Read ../child/SKILL.md (relative to this skill's directory), "
                             "see [rows](../child/references/table.md#a) and "
                             "../child/references/<kind>/; not links: gh api .../contents/, "
                             "skills/x/../y/z, ../name and ../../scripts/tool.py.",
                   files={"references/phases/one.md": "See ../../../child/SKILL.md.",
                          "references/transport.md": "Also ../../child/SKILL.md."})
        code, out, err = self.run_main()
        self.assertEqual(code, 0, out + err)
        self.assertIn("sibling references OK", out)

    def test_broken_sibling_references_fail(self):
        self.skill("child")
        self.skill("parent", "Read `../gone/SKILL.md` and ../child/references/old.md.",
                   files={"references/x.md": "Read ../child/SKILL.md and ../local/notes.md.",
                          "references/local/notes.md": "own file\n",
                          "references/phases/one.md": "Read ../child/SKILL.md."})
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(len(out.splitlines()), 4, out)
        self.assertIn("skills/parent/SKILL.md:4: ../gone/SKILL.md names no sibling skill", out)
        self.assertIn("../child/references/old.md does not exist in skills/child/", out)
        self.assertIn("skills/parent/references/x.md:1: ../child/SKILL.md resolves inside "
                      "the skill; paths are relative to the file holding them, so the "
                      "sibling is ../../child/", out)
        self.assertIn("skills/parent/references/phases/one.md:1: ../child/SKILL.md resolves "
                      "inside the skill; paths are relative to the file holding them, so the "
                      "sibling is ../../../child/", out)
        self.assertIn("4 error(s)", err)

    PEP_723 = "# /// script\n# requires-python = \">=3.13\"\n# dependencies = []\n# ///\n"

    def test_script_commands_that_follow_the_uv_convention_pass(self):
        self.skill("other", files={"scripts/shared.py": self.PEP_723})
        self.skill("tool", "Without uv: run the script with `python3` (`python` on Windows).\n"
                           "```bash\nuv run scripts/run.py --flag\n"
                           "uv run \"$TOOL_DIR/scripts/run.py\" x\n"
                           "uv run --no-project --with pyyaml python - <<'PY'\n"
                           "uv run --no-project python scripts/plain.py\n"
                           "python3 -c 'import sys'\npython3 scripts/test_run.py\n"
                           "python3 <repo>/tools/own.py\n```\n"
                           "Run `uv run ../other/scripts/shared.py`; prose python3 scripts/plain.py.",
                   files={"scripts/run.py": "#!/usr/bin/env -S uv run --script\n" + self.PEP_723,
                          "scripts/plain.py": "print()\n", "scripts/test_run.py": "",
                          "references/x.md": "`uv run scripts/run.py`"})
        code, out, err = self.run_main()
        self.assertEqual(code, 0, out + err)
        self.assertIn("script commands OK", out)

    def test_script_commands_that_break_the_uv_convention_fail(self):
        self.skill("tool", "```bash\nuv run --with pyyaml scripts/plain.py\n"
                           "uv run scripts/gone.py\npython -B scripts/run.py --x\n"
                           "uv run scripts/run.py && uv run \"$(uv run scripts/plain.py scope)\"\n"
                           "uv run --with pyyaml python -c 'import yaml'\n```\n"
                           "Measure with `python3\nscripts/run.py draft.md`.",
                   files={"scripts/run.py": self.PEP_723, "scripts/plain.py": "print()\n"})
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), [
            "skills/tool/SKILL.md:5: uv run target skills/tool/scripts/plain.py has no PEP 723 "
            "'# /// script' block",
            "skills/tool/SKILL.md:6: uv run target scripts/gone.py does not resolve to a file "
            "under skills/",
            "skills/tool/SKILL.md:7: bare python runs skills/tool/scripts/run.py; "
            "write uv run scripts/run.py",
            "skills/tool/SKILL.md:8: uv run target skills/tool/scripts/plain.py has no PEP 723 "
            "'# /// script' block",
            "skills/tool/SKILL.md:9: uv run python without --no-project syncs the user's project; "
            "write uv run --no-project python",
            "skills/tool/SKILL.md:11: bare python runs skills/tool/scripts/run.py; "
            "write uv run scripts/run.py",
        ])
        self.assertIn("6 error(s)", err)


if __name__ == "__main__":
    unittest.main()
