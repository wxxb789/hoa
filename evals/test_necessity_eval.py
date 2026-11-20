import json
import sys

import pytest

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
prompt = sys.stdin.read()
assert prompt.startswith("same prompt for every arm")
assert ("report-claim-audit" in prompt) == (MODE == "forced" and HAS_SKILL)
assert ("frozen terse text" in str(sys.argv)) == IS_TERSE
if RUNTIME == "claude":
    tools = sys.argv[sys.argv.index("--tools") + 1].split(",")
    assert ("Bash" in tools) == SHELL
else:
    import tomllib
    config = tomllib.loads((Path(os.environ["CODEX_HOME"]) / "config.toml").read_text(encoding="utf-8"))
    assert config == {"model_provider": "mock", "model_providers": {
        "mock": {"name": "Stub", "env_key": "EVAL_STUB_TOKEN", "http_headers": {"unused": "private-header"},
                 "base_url": "http://local.invalid/v1", "wire_api": "responses"}}}
    assert os.environ["EVAL_STUB_TOKEN"] == "private-token"
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ
    assert "--dangerously-bypass-approvals-and-sandbox" in sys.argv
    assert ("shell_tool" not in sys.argv) == SHELL
    assert not (Path(os.environ["CODEX_HOME"]) / "auth.json").exists()
source = Path("input.txt")
assert source.read_text(encoding="utf-8") == "original"
source.write_text("changed in this arm only", encoding="utf-8")
home = "CLAUDE_CONFIG_DIR" if RUNTIME == "claude" else "CODEX_HOME"
skill = Path(os.environ[home]) / "skills" / "report-claim-audit" / "SKILL.md"
has_skill = skill.is_file()
assert HAS_SKILL == has_skill
access = (has_skill and LOAD) or (not has_skill and LEAK_BASELINE) or FAKE_LOAD
answer = json.dumps({"answer": SCORE, "cwd": str(Path.cwd()),
                     "secret": "private-token private-header" if RUNTIME == "codex" else ""})
if RUNTIME == "codex":
    if access:
        command = f'Get-Content "{skill}"' if HAS_SKILL else "Get-Content skills/alien/reference.txt"
        item = {"type": "command_execution", "id": "read1", "command": command}
        print(json.dumps({"type": "item.started", "item": item}))
        item.update(status="completed", exit_code=0 if has_skill else 1,
                    aggregated_output=skill.read_text(encoding="utf-8") if has_skill and LOAD else str(skill))
        print(json.dumps({"type": "item.completed", "item": item}))
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "cached_input_tokens": 8,
                                                        "output_tokens": 3, "reasoning_output_tokens": 1}}))
    sys.exit(0)
if access:
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "read1", "name": "Read", "input": {"file_path": str(skill)}}
    ]}}))
    print(json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "read1", "is_error": not has_skill}
    ]}}))
print(json.dumps({"type": "result", "subtype": "success", "num_turns": 2,
                  "usage": {"output_tokens": 3},
                  "result": answer}))
"""


def setup_trial(tmp_path, monkeypatch, *, runtime="claude", mode="forced", leak=False,
                load=True, shell=False, fake_load=False, scores=None, thresholds=None):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"untouched")
    config = """model_provider = "mock"
model = "not-copied"
[model_providers.other]
name = "Not copied"
[model_providers.mock]
name = "Stub"
base_url = "http://local.invalid/v1"
wire_api = "responses"
env_key = "EVAL_STUB_TOKEN"
[model_providers.mock.http_headers]
unused = "private-header"
[mcp_servers.real]
command = "do-not-run"
"""
    (outside / "config.toml").write_text(config, encoding="utf-8")
    (outside / "auth.json").write_text("do not copy", encoding="utf-8")
    for key in (*runner.PROFILE, "AUDIT_STATE_DIR", "GIT_DIR", "ARBITRARY_PARENT_SECRET"):
        monkeypatch.setenv(key, str(outside))
    monkeypatch.setenv("EVAL_STUB_TOKEN", "private-token")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "not-for-codex")
    # tempfile chooses its base independently of the untrusted agent profile.
    monkeypatch.setattr(runner.tempfile, "tempdir", str(tmp_path))
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "input.txt").write_text("original", encoding="utf-8")
    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "id": "test-eval", "skill": "report-claim-audit", "fixture": "fixture",
        "prompt": "same prompt for every arm", "terse": "frozen terse text", "shell": shell,
        "rubric": {"answer": {"field": "answer", "equals": 42}},
    }), encoding="utf-8")
    process = runner.run_process
    seen = []

    def launch(argv, **kwargs):
        cwd = kwargs["cwd"]
        seen.append(cwd)
        arm = next((name for name in ("none", "terse", "skill") if cwd.parent.name.startswith(
            f"hoa-eval-{name}-")), None)
        has_skill, is_terse = arm == "skill", arm == "terse"
        score = next(scores) if scores is not None and arm else (42 if has_skill else 0)
        constants = (runtime, mode, has_skill, is_terse, shell, load, leak, fake_load and has_skill, score)
        header = "RUNTIME, MODE, HAS_SKILL, IS_TERSE, SHELL, LOAD, LEAK_BASELINE, FAKE_LOAD, SCORE"
        return process([sys.executable, "-c", f"{header} = {constants!r}\n" + STUB, *argv[1:]], **kwargs)

    monkeypatch.setattr(runner, "run_process", launch)
    results = tmp_path / "results"
    argv = ["runner", str(task), "--runtime", runtime, "--mode", mode, f"--{runtime}", sys.executable,
            "--model", "stub-model", "--results", str(results), "--repeats", "2"]
    if thresholds is not None:
        policy = tmp_path / "thresholds.json"
        policy.write_text(json.dumps(thresholds), encoding="utf-8")
        argv.extend(("--thresholds", str(policy)))
    monkeypatch.setattr(sys, "argv", argv)
    return results, seen


@pytest.mark.parametrize(("runtime", "shell"), [("claude", False), ("codex", True)])
def test_three_arm_results_and_process_isolation(tmp_path, monkeypatch, runtime, shell):
    results, seen = setup_trial(tmp_path, monkeypatch, runtime=runtime, shell=shell)
    before = {path.name: path.read_bytes() for path in (tmp_path / "outside").iterdir()}
    assert runner.main() == 0
    assert len(set(seen)) == len(seen) == 7
    assert all(not path.parent.exists() for path in seen[1:])
    assert not seen[0].exists()
    assert {path.name: path.read_bytes() for path in (tmp_path / "outside").iterdir()} == before
    assert (tmp_path / "fixture/input.txt").read_text(encoding="utf-8") == "original"
    report, = results.glob("*.json")
    assert report.with_suffix(".md").is_file()
    record = json.loads(report.read_text(encoding="utf-8"))
    assert report.stem.endswith(f"-test-eval-{runtime}-forced")
    assert record["schema_version"] == 2
    assert record["cli_version"] == "stub 1.0"
    assert record["order"] == ["none", "terse", "skill", "skill", "terse", "none"]
    assert record["summary"]["skill"]["pass^k"] is True
    assert record["summary"]["none"]["pass^k"] is False
    assert record["runs"]["skill"][0]["usage"]["output_tokens"] == 3
    assert json.loads(record["runs"]["skill"][0]["output"])["cwd"].startswith("<trial>")
    assert record["verdict"] == "skill-wins"
    if runtime == "codex":
        assert record["runs"]["skill"][0]["tokens"] == 15
        assert "private-token" not in report.read_text(encoding="utf-8")
        assert "private-header" not in report.read_text(encoding="utf-8")


def test_redact_windows_paths_and_credentials(monkeypatch):
    root = r"R:\Trials\Long Trial Name"
    monkeypatch.setattr(runner, "path_forms", lambda path: (
        (root, r"R:\TRIALS\LONGTR~1") if path == root else (str(path),)
    ))
    monkeypatch.setenv("TEMP", r"C:\Users\ExampleUser\AppData\Local\Temp")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\ExampleUser")
    monkeypatch.setenv("USERNAME", "ExampleUser")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-only-secret")
    output = json.dumps([
        r"r:/tRiAlS\long trial NAME/work/file.md",
        r"R:\Trials/LONGTR~1\work\file.md",
        r"c:/users\exampleuser/AppData\Local/Temp",
        r"C:\Users\EXAMPL~1\cache",
        r"Z:\Other Host Path\cache",
        "/tmp/another-trial/report.md",
        "ExampleUser: test-only-secret",
        "subject/README.md",
    ])
    clean = json.loads(runner.redact(root, output, windows=True))
    assert all(path.startswith("<trial>") for path in clean[:2])
    assert clean[2:6] == ["<path>"] * 4
    assert clean[6:] == ["<redacted>: <redacted>", "subject/README.md"]


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_control_skill_access_invalidates_result(tmp_path, monkeypatch, runtime):
    results, _ = setup_trial(tmp_path, monkeypatch, runtime=runtime, leak=True)
    assert runner.main() == 1
    report, = results.glob("*.json")
    record = json.loads(report.read_text(encoding="utf-8"))
    for arm in ("none", "terse"):
        assert record["runs"][arm][0]["contaminated"]
        assert record["summary"][arm]["pass^k"] is None
    assert record["verdict"] == "inconclusive"


@pytest.mark.parametrize(("runtime", "mode", "shell", "fake", "exit_code"), [
    ("claude", "forced", True, False, 1),
    ("codex", "forced", True, True, 1),
    ("codex", "natural", False, False, 0),
])
def test_unobserved_treatment(tmp_path, monkeypatch, runtime, mode, shell, fake, exit_code):
    results, _ = setup_trial(tmp_path, monkeypatch, runtime=runtime, mode=mode,
                             shell=shell, load=False, fake_load=fake)
    assert runner.main() == exit_code
    report, = results.glob("*.json")
    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["verdict"] == "inconclusive"
    assert record["runs"]["skill"][0]["valid"] == (mode == "natural")
    assert record["runs"]["skill"][0]["skill_loaded"] is False


@pytest.mark.parametrize(("delta", "verdict"), [
    (0.25, "terse-suffices"), (0.5, "terse-suffices"), (0.75, "no-difference"),
])
def test_threshold_and_all_k_math(tmp_path, monkeypatch, delta, verdict):
    thresholds = {"min_mean_gain": delta, "max_terse_gap": 0.5, "min_pass_rate": 1.0,
                  "min_natural_load_rate": 1.0}
    results, _ = setup_trial(tmp_path, monkeypatch, thresholds=thresholds,
                             scores=iter([42, 42, 42, 0, 42, 0]))
    assert runner.main() == 0
    report, = results.glob("*.json")
    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["thresholds"] == thresholds
    assert record["verdict"] == verdict
    assert record["summary"]["skill"]["pass^k"] is False
    assert record["summary"]["skill"]["passed"] == 1
    assert record["summary"]["skill"]["mean_score"] == 0.5
    assert record["summary"]["skill"]["sample_stddev"] == pytest.approx(0.70710678)


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
