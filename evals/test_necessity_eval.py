import json
import os
import sys
from pathlib import Path

from evals import run_necessity_eval as runner


STUB = r"""
import json, os, sys
from pathlib import Path

if "--version" in sys.argv:
    print("stub 1.0")
    sys.exit(0)

root = Path.cwd().parent
for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
            "XDG_CONFIG_DIRS", "XDG_DATA_DIRS", "CODEX_HOME", "CLAUDE_CONFIG_DIR",
            "TEMP", "TMP", "TMPDIR"):
    path = Path(os.environ[key])
    assert path.is_relative_to(root), (key, path)
    (path / (key + ".sentinel")).write_text("within trial", encoding="utf-8")
assert "ARBITRARY_PARENT_SECRET" not in os.environ
assert "AUDIT_STATE_DIR" not in os.environ
assert "GIT_DIR" not in os.environ
assert sys.stdin.read() == "same prompt for every arm"
source = Path("input.txt")
assert source.read_text(encoding="utf-8") == "original"
source.write_text("changed in this arm only", encoding="utf-8")
skill = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "skills" / "report-claim-audit" / "SKILL.md"
has_skill = skill.is_file()
if has_skill or LEAK_BASELINE:
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "read1", "name": "Read", "input": {"file_path": str(skill)}}
    ]}}))
    print(json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "read1", "is_error": not has_skill}
    ]}}))
print(json.dumps({"type": "result", "subtype": "success", "num_turns": 2,
                  "usage": {"output_tokens": 3},
                  "result": json.dumps({"answer": 42 if has_skill else 0})}))
"""


def setup_trial(tmp_path, monkeypatch, *, leak=False):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"untouched")
    for key in (*runner.PROFILE, "AUDIT_STATE_DIR", "GIT_DIR", "ARBITRARY_PARENT_SECRET"):
        monkeypatch.setenv(key, str(outside))
    # tempfile chooses its base independently of the untrusted agent profile.
    monkeypatch.setattr(runner.tempfile, "tempdir", str(tmp_path))
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "input.txt").write_text("original", encoding="utf-8")
    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "id": "test-eval", "skill": "report-claim-audit", "fixture": "fixture",
        "prompt": "same prompt for every arm", "rubric": {"answer": {"field": "answer", "equals": 42}},
    }), encoding="utf-8")
    process = runner.gdd_process.run
    seen = []

    def launch(argv, **kwargs):
        seen.append(kwargs["cwd"])
        return process([sys.executable, "-c", f"LEAK_BASELINE = {leak!r}\n" + STUB, *argv[1:]], **kwargs)

    monkeypatch.setattr(runner.gdd_process, "run", launch)
    results = tmp_path / "results"
    monkeypatch.setattr(sys, "argv", ["runner", str(task), "--claude", sys.executable,
                                     "--model", "stub-model", "--results", str(results), "--repeats", "2"])
    return results, seen


def test_paired_results_and_process_isolation(tmp_path, monkeypatch):
    results, seen = setup_trial(tmp_path, monkeypatch)
    assert runner.main() == 0
    assert len(set(seen)) == len(seen) == 5  # Version plus two independent pairs.
    assert all(not path.parent.exists() for path in seen[1:])
    assert not seen[0].exists()
    assert set(os.listdir(tmp_path / "outside")) == {"sentinel"}
    assert (tmp_path / "outside/sentinel").read_bytes() == b"untouched"
    assert (tmp_path / "fixture/input.txt").read_text(encoding="utf-8") == "original"
    report, = results.glob("*.json")
    assert report.with_suffix(".md").is_file()
    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["cli_version"] == "stub 1.0"
    assert record["order"] == ["skill", "baseline", "baseline", "skill"]
    assert record["summary"]["skill"]["pass^k"] is True
    assert record["summary"]["baseline"]["pass^k"] is False
    assert record["runs"]["skill"][0]["usage"]["output_tokens"] == 3
    assert record["outcome"] == "skill wins"


def test_baseline_skill_access_invalidates_pair(tmp_path, monkeypatch):
    results, _ = setup_trial(tmp_path, monkeypatch, leak=True)
    assert runner.main() == 1
    report, = results.glob("*.json")
    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["runs"]["baseline"][0]["contaminated"]
    assert record["summary"]["baseline"]["pass^k"] is None
    assert record["outcome"] == "inconclusive"


def test_reject_outside_rubric_path_before_starting_any_process(tmp_path, monkeypatch):
    results, seen = setup_trial(tmp_path, monkeypatch)
    path = tmp_path / "task.json"
    task = json.loads(path.read_text(encoding="utf-8"))
    task["rubric"] = {"escape": {"file": "../outside/sentinel", "contains": "untouched"}}
    path.write_text(json.dumps(task), encoding="utf-8")
    assert runner.main() == 2
    assert not seen
    assert not results.exists()


def test_fixture_must_not_include_answer_key(tmp_path, monkeypatch):
    results, seen = setup_trial(tmp_path, monkeypatch)
    path = tmp_path / "task.json"
    task = json.loads(path.read_text(encoding="utf-8"))
    task["fixture"] = "."
    path.write_text(json.dumps(task), encoding="utf-8")
    assert runner.main() == 2
    assert not seen
    assert not results.exists()
