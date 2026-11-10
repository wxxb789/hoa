#!/usr/bin/env python3
"""Offline tests for check_contract_graph.

Run: python scripts/test_check_contract_graph.py
Builds synthetic skills/, registry and trigger-case trees under
.tmp-artifacts/ and exercises every contract rule CI depends on.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parent / "check_contract_graph.py"
ARTIFACTS = SCRIPT.parent.parent / ".tmp-artifacts" / "contract-graph-tests"
spec = importlib.util.spec_from_file_location("skill_metadata",
                                              SCRIPT.parent / "skill_metadata.py")
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)
spec = importlib.util.spec_from_file_location("check_contract_graph", SCRIPT)
cg = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"skill_metadata": sm, "check_contract_graph": cg}):
    spec.loader.exec_module(cg)


def make_temp_root() -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=ARTIFACTS))


def make_skill(root: Path, name: str, *, kind=None, consumes=None, produces=None):
    d = root / "skills" / name
    d.mkdir(parents=True)
    parts = ["---", f"name: {name}",
             f"description: {name} performs one bounded step.",
             "metadata:", '  version: "0.1.0"',
             '  areas: "software-development"', '  targets: "runtime-agnostic"']
    for key, value in (("kind", kind), ("consumes", consumes), ("produces", produces)):
        if value is not None:
            parts.append(f'  {key}: "{value}"')
    parts += ["---", "", f"# {name}", ""]
    (d / "SKILL.md").write_bytes("\n".join(parts).encode("utf-8"))
    return d


def write_registry(root: Path, *, external=(), shared=(), required_kind=()):
    path = root / "scripts" / "contract_graph_registry.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, values in (("external", external), ("shared", shared),
                        ("required_kind", required_kind)):
        if values:
            lines.append(f"{key}:")
            lines.extend(f"  - {value}" for value in values)
        else:
            lines.append(f"{key}: []")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pad_skill_to(path: Path, lines: int) -> None:
    text = path.read_text(encoding="utf-8")
    missing = lines - len(text.splitlines())
    if missing < 0:
        raise ValueError(f"{path} already exceeds {lines} lines")
    if missing:
        text = text.rstrip("\n") + "\n" + "\n".join(
            f"filler {index}" for index in range(missing)) + "\n"
    path.write_text(text, encoding="utf-8")


def write_trigger_cases(root: Path, cases):
    path = root / "evals" / "trigger-cases.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")


class ContractGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_root()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def graph(self):
        return cg.analyze(self.tmp)

    def violations(self):
        return list(self.graph().violations)

    def assert_rule(self, rule: str):
        lines = [line for line in self.violations() if f": {rule}: " in line]
        self.assertEqual(len(lines), 1, self.violations())
        return lines[0]

    def test_valid_graph(self):
        make_skill(self.tmp, "gate-runner", kind="stage",
                   consumes="gate-spec", produces="gate-result")
        make_skill(self.tmp, "verdict-maker", kind="stage",
                   consumes="gate-result", produces="verdict")
        write_registry(self.tmp, external=["gate-spec"])
        result = self.graph()
        self.assertEqual(result.violations, ())
        self.assertEqual(len(result.skills), 2)
        self.assertEqual(result.artifacts,
                         frozenset({"gate-spec", "gate-result", "verdict"}))

    def test_r1_invalid_kind(self):
        make_skill(self.tmp, "bad-kind", kind="widget")
        line = self.assert_rule("R1")
        self.assertIn("skills/bad-kind/SKILL.md", line)
        self.assertIn("'widget'", line)

    def test_r2_consumes_without_kind(self):
        make_skill(self.tmp, "decorated", consumes="work-report", produces="result")
        write_registry(self.tmp, external=["work-report"])
        line = self.assert_rule("R2")
        self.assertIn("skills/decorated/SKILL.md", line)

    def test_r3_dangling_consume_and_registry_external(self):
        make_skill(self.tmp, "consumer", kind="stage",
                   consumes="work-report", produces="result")
        self.assertIn("R3", self.assert_rule("R3"))
        write_registry(self.tmp, external=["work-report"])
        self.assertEqual(self.violations(), [])

    def test_r4_mechanism_must_not_be_a_must_pick_but_may_be_a_distractor(self):
        make_skill(self.tmp, "runner", kind="mechanism", produces="gate-result")
        write_trigger_cases(self.tmp, [
            {"id": "route-to-runner", "must_pick": ["runner"], "distractors": []},
            {"id": "other-route", "must_pick": ["other"], "distractors": ["runner"]},
        ])
        line = self.assert_rule("R4")
        self.assertIn("route-to-runner", line)
        self.assertNotIn("other-route", line)
        write_trigger_cases(self.tmp, [
            {"id": "other-route", "must_pick": ["other"], "distractors": ["runner"]},
        ])
        self.assertEqual(self.violations(), [])

    def test_r5_controller_produces_only_chain_plan(self):
        make_skill(self.tmp, "router", kind="controller", produces="chain-plan,extra")
        line = self.assert_rule("R5")
        self.assertIn("'extra'", line)
        make_skill(self.tmp, "router-missing", kind="controller", produces="other")
        lines = [item for item in self.violations() if ": R5: " in item]
        self.assertEqual(len(lines), 3, self.violations())
        self.assertTrue(any("must produce 'chain-plan'" in item for item in lines))

    def test_r5_valid_controller(self):
        make_skill(self.tmp, "router", kind="controller", produces="chain-plan")
        self.assertEqual(self.violations(), [])

    def test_r6_duplicate_producer_and_shared_allowlist(self):
        make_skill(self.tmp, "first", kind="stage", produces="shared-artifact")
        make_skill(self.tmp, "second", kind="stage", produces="shared-artifact")
        line = self.assert_rule("R6")
        self.assertIn("shared-artifact", line)
        write_registry(self.tmp, shared=["shared-artifact"])
        self.assertEqual(self.violations(), [])

    def test_r7_required_skill_missing_kind(self):
        make_skill(self.tmp, "bare")
        write_registry(self.tmp, required_kind=["bare"])
        line = self.assert_rule("R7")
        self.assertIn("skills/bare/SKILL.md", line)
        self.assertIn("does not declare kind", line)

    def test_r7_unknown_required_name(self):
        write_registry(self.tmp, required_kind=["ghost"])
        line = self.assert_rule("R7")
        self.assertIn("required_kind names unknown skill 'ghost'", line)

    def test_r8_controller_over_cap(self):
        skill_md = make_skill(self.tmp, "router", kind="controller",
                              produces="chain-plan") / "SKILL.md"
        pad_skill_to(skill_md, cg.MAX_CONTROLLER_LINES + 1)
        line = self.assert_rule("R8")
        self.assertIn(f"{cg.MAX_CONTROLLER_LINES + 1} lines", line)
        self.assertIn(f"cap is {cg.MAX_CONTROLLER_LINES}", line)

    def test_r8_controller_at_cap_passes(self):
        skill_md = make_skill(self.tmp, "router", kind="controller",
                              produces="chain-plan") / "SKILL.md"
        pad_skill_to(skill_md, cg.MAX_CONTROLLER_LINES)
        self.assertEqual(self.violations(), [])

    def test_main_summary_and_list(self):
        make_skill(self.tmp, "runner", kind="mechanism",
                   consumes="gate-spec", produces="gate-result")
        make_skill(self.tmp, "plain")
        write_registry(self.tmp, external=["gate-spec"])
        with patch.object(cg, "ROOT", self.tmp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cg.main([]), 0)
        self.assertEqual(out.getvalue(),
                         "contract graph: 2 skills, 2 artifacts, ok\n")
        with patch.object(cg, "ROOT", self.tmp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cg.main(["--list"]), 0)
        self.assertEqual(out.getvalue(),
                         "runner → mechanism → gate-spec → gate-result\n")


if __name__ == "__main__":
    unittest.main()
