#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# ─── How to run ───
# python evals/run_evals.py
"""Run approval-gate fixtures against the real distillation helper scripts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final, TypedDict

FIXTURE_DIRECTORY: Final = Path(__file__).parent
PACKAGE_DIRECTORY: Final = FIXTURE_DIRECTORY.parent
SCRIPTS_DIRECTORY: Final = PACKAGE_DIRECTORY / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from approval import resolve_approval  # noqa: E402


class Candidate(TypedDict):
    """One candidate supplied to the production approval state machine."""

    id: str
    state: str


class Expected(TypedDict):
    """Observable output asserted by every approval fixture."""

    created_count: int
    created_ids: list[str]
    non_terminal_ids: list[str]
    reason: str
    exit_code: int


class Fixture(TypedDict):
    """The serialized eval fixture boundary."""

    name: str
    candidates: list[Candidate]
    approval: object
    duplicate_approval: bool
    expected: Expected


class Evaluation(TypedDict):
    """The expected-versus-actual result for one fixture."""

    fixture: str
    passed: bool
    actual: Expected
    expected: Expected


def fixture_from(path: Path) -> Fixture:
    """Parse a committed approval fixture with its required structural fields."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("fixture root must be an object")
    required = ("name", "candidates", "approval", "expected")
    if not all(field in raw for field in required):
        raise ValueError("fixture needs name, candidates, approval, and expected")
    return raw


def run_script(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run a real local helper script with stable text capture."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIRECTORY / script), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def assert_pii_gate() -> None:
    """Prove real pii_gate refuses tracked targets and allows external targets."""
    tracked_target = FIXTURE_DIRECTORY / "blocked-rule.md"
    tracked = run_script("pii_gate.py", str(tracked_target))
    assert tracked.returncode == 1, tracked.stderr
    assert json.loads(tracked.stdout) == {"allowed": False, "reason": "tracked-or-unignored-worktree-path"}
    with tempfile.TemporaryDirectory() as directory:
        outside_target = Path(directory) / "new" / "rule.md"
        outside = run_script("pii_gate.py", str(outside_target))
        assert outside.returncode == 0, outside.stderr
        assert json.loads(outside.stdout) == {"allowed": True, "reason": "outside-worktree"}


def validate_created_skill(output: Path, candidate_id: str) -> None:
    """Create one synthetic skill asset and validate it through the real validator."""
    skill = output / candidate_id / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text("---\nname: fixture\ndescription: fixture\n---\n\n# Fixture\n", encoding="utf-8")
    validation = run_script("validate_skill.py", str(skill))
    assert validation.returncode == 0, validation.stderr
    assert json.loads(validation.stdout)["valid"] is True


def evaluate(fixture: Fixture) -> Evaluation:
    """Resolve production approval, then validate only its single created asset."""
    decision = resolve_approval(fixture["candidates"], fixture["approval"])
    if fixture.get("duplicate_approval", False):
        assert decision == resolve_approval(fixture["candidates"], fixture["approval"])
    created_ids = decision["created"]
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        for candidate_id in created_ids:
            validate_created_skill(output, candidate_id)
        assert len(list(output.glob("*/SKILL.md"))) == len(created_ids)
    actual = {
        "created_count": len(created_ids),
        "created_ids": created_ids,
        "non_terminal_ids": decision["non_terminal"],
        "reason": decision["reason"],
        "exit_code": 0,
    }
    expected = fixture["expected"]
    return {"fixture": fixture["name"], "passed": actual == expected, "actual": actual, "expected": expected}


def main() -> int:
    """Run all approval fixtures plus the real PII-gate subprocess contract."""
    results = [evaluate(fixture_from(path)) for path in sorted(FIXTURE_DIRECTORY.glob("*.json"))]
    assert_pii_gate()
    for result in results:
        print(json.dumps(result, sort_keys=True))
    print(json.dumps({"pii_gate": "PASS", "production_approval_module": str(SCRIPTS_DIRECTORY / "approval.py")}, sort_keys=True))
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
