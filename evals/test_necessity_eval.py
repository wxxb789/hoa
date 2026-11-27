import io
import json
import os
import subprocess
import sys
from contextlib import chdir, redirect_stderr, redirect_stdout
from copy import deepcopy
from unittest.mock import patch

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
if os.name == "nt":
    assert Path(os.environ["HOMEDRIVE"] + os.environ["HOMEPATH"]) == Path(os.environ["USERPROFILE"])
assert "ARBITRARY_PARENT_SECRET" not in os.environ
assert "AUDIT_STATE_DIR" not in os.environ
assert "GIT_DIR" not in os.environ
assert "HERMES_HOME" not in os.environ
prompt = sys.stdin.read()
assert prompt.startswith("same prompt for every arm: report-claim-audit")
assert ("First read" in prompt) == (MODE == "forced" and HAS_SKILL)
assert ("frozen terse text" in str(sys.argv)) == IS_TERSE
if RUNTIME == "pi":
    home = Path.home()
    assert home == Path(os.environ["HOME"])
    assert not (home / ".agents" / "skills").exists()
    assert Path(os.environ["PI_CODING_AGENT_SESSION_DIR"]) == home / ".pi" / "sessions"
    agent = Path(os.environ["PI_CODING_AGENT_DIR"])
    assert agent == home / ".pi" / "agent"
    assert {p.name for p in agent.iterdir()} == {"skills", "models.json", "auth.json"}
    assert {p.name for p in (agent / "skills").iterdir()} == (
        {"report-claim-audit"} if HAS_SKILL else set()
    )
    assert json.loads((agent / "models.json").read_text(encoding="utf-8")) == {
        "providers": {"tencent-litellm": PI_CONFIG}}
    assert json.loads((agent / "auth.json").read_text(encoding="utf-8")) == {
        "tencent-litellm": PI_AUTH}
    assert os.environ["PI_STUB_HEADER"] == "private-pi-header"
    assert "OTHER_PI_KEY" not in os.environ
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ
    options = dict(zip(sys.argv, sys.argv[1:]))
    assert options["--mode"] == "json"
    assert options["--model"] == PI_MODEL
    assert options["--thinking"] == PI_THINKING
    assert {"--no-approve", "--no-session", "--no-extensions", "--no-mcp",
            "--no-context-files"} <= set(sys.argv)
    assert ("--no-skills" in sys.argv) == (not HAS_SKILL or MODE == "forced")
    assert ("--skill" in sys.argv) == (HAS_SKILL and MODE == "forced")
    if HAS_SKILL and MODE == "forced":
        assert Path(options["--skill"]) == agent / "skills" / "report-claim-audit"
    assert ("--append-system-prompt" in sys.argv) == IS_TERSE
    tools = options["--tools"].split(",")
    assert ("bash" in tools) == SHELL
    assert ("write" in tools) == (RESPONSE is not None)
elif RUNTIME == "claude":
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "not-for-codex"
    assert "EVAL_STUB_TOKEN" not in os.environ
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
home = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME", "pi": "PI_CODING_AGENT_DIR"}[RUNTIME]
skill = Path(os.environ[home]) / "skills" / "report-claim-audit" / "SKILL.md"
has_skill = skill.is_file()
assert HAS_SKILL == has_skill
access = (has_skill and LOAD) or (not has_skill and LEAK_BASELINE) or FAKE_LOAD
secret = {"codex": "private-token private-header",
          "pi": "private-pi-model-key private-pi-auth-key private-pi-header"}.get(RUNTIME, "")
answer = json.dumps({"answer": SCORE, "cwd": str(Path.cwd()), "secret": secret})
if RESPONSE is not None:
    answer = RESPONSE
    Path("artifact.txt").write_text("expected artifact", encoding="utf-8")
if not HAS_SKILL and CONTROL_PATH:
    access = True
    catalog = Path(CATALOG)
    config_read = r"../home\xdg/config/tool\skills/other/document.txt"
    if os.name == "nt":
        config_read = config_read.upper()
    paths = {
        "fixture": (Path.cwd() / "skills" / "report-claim-audit" / "input.txt").as_posix(),
        "relative-fixture": "skills/report-claim-audit/input.txt",
        "catalog": catalog / "research-writing" / "report-claim-audit" / "SKILL.md",
        "other-catalog": catalog / "research-writing" / "not-the-task-skill" / "SKILL.md",
        "catalog-probe": catalog / "research-writing" / "report-claim-audit",
        "workspace-probe": Path.cwd() / "skills" / "report-claim-audit",
        "catalog-failed": catalog / "research-writing" / "report-claim-audit" / "SKILL.md",
        "catalog-pending": catalog / "research-writing" / "report-claim-audit" / "SKILL.md",
        "host-reference": root.parent / "host/.agents/skills/another/references/guide.md",
        "host-root-file": root.parent / "host/.agents/skills/catalog.txt",
        "standalone": root.parent / "host/SKILL.md",
        "config": config_read,
        "skill-tool": "skills/report-claim-audit/input.txt",
        "skill-failed": "skills/report-claim-audit/input.txt",
        "skill-not-found": "skills/report-claim-audit/input.txt",
        "mcp-fixture": "skills/report-claim-audit/input.txt",
        "mcp-catalog": catalog / "research-writing" / "report-claim-audit" / "SKILL.md",
    }
    read_path = str(paths[CONTROL_PATH])
    assert CONTROL_PATH not in {"fixture", "relative-fixture"} or Path(read_path).is_file()
else:
    read_path = str(skill)
if RUNTIME == "pi":
    def emit(**event):
        print(json.dumps(event, ensure_ascii=False))

    def message(stop, content):
        emit(type="message_end", message={
            "role": "assistant", "model": PI_MODEL, "stopReason": stop, "content": content,
            "usage": {"input": 12, "output": 3, "cacheRead": 8, "cacheWrite": 2, "totalTokens": 25},
        })

    if access:
        if FAILURE != "marker":
            message("toolUse", [])
        scenario = None if HAS_SKILL else CONTROL_PATH
        tool, args = "read", {"path": read_path}
        if scenario in {"catalog-probe", "workspace-probe"}:
            tool, args = "find", {"path": read_path, "pattern": "**/SKILL.md"}
        elif scenario and scenario.startswith("skill-"):
            tool, args = "skill", {"skill": "report-claim-audit"}
        elif scenario == "host-reference" or FAKE_LOAD:
            tool, args = "bash", {"command": f'cat "{read_path}"'}
        emit(type="tool_execution_start", toolCallId="skill1", toolName=tool, args=args)
        if scenario != "catalog-pending":
            content = "Unknown skill" if scenario == "skill-not-found" else "completed"
            emit(type="tool_execution_end", toolCallId="skill1", toolName=tool,
                 isError=scenario in {"catalog-failed", "skill-failed"},
                 result={"content": [{"type": "text", "text": content}]})
        emit(type="turn_end")
    if FAILURE == "stream":
        print("not JSON")
    elif FAILURE != "marker":
        # A Unicode line separator inside JSON is not a JSONL record boundary.
        message("error" if FAILURE == "stop" else "stop",
                [{"type": "thinking", "thinking": "\u2028"}, {"type": "text", "text": answer}])
        emit(type="turn_end")
    emit(type="agent_settled", aborted=FAILURE == "aborted")
    sys.exit(7 if FAILURE == "exit" else 0)
if RUNTIME == "codex":
    if not HAS_SKILL and CONTROL_PATH in {"skill-tool", "skill-failed"}:
        print(json.dumps({"type": "item.completed", "item": {
            "type": "mcp_tool_call", "id": "skill1", "tool": "skill",
            "arguments": {"skill": "report-claim-audit"},
            "result": {"isError": CONTROL_PATH == "skill-failed", "content": [{"text": "stub output"}]},
        }}))
    elif not HAS_SKILL and CONTROL_PATH and CONTROL_PATH.startswith("mcp-"):
        print(json.dumps({"type": "item.completed", "item": {
            "type": "mcp_tool_call", "id": "read1", "tool": "read_file",
            "arguments": {"paths": [read_path]},
            "result": {"content": [{"text": str(Path(CATALOG) / "report-claim-audit" / "SKILL.md")}]},
        }}))
    elif access:
        command = f"powershell -Command 'Get-Content -LiteralPath \"{read_path}\"'"
        if not HAS_SKILL and CONTROL_PATH == "catalog-probe":
            command = f"/bin/bash -lc 'rg --files \"{read_path}\"; ls \"{read_path}\"'"
        if not HAS_SKILL and CONTROL_PATH == "host-reference":
            command = f"/bin/bash -lc 'rg instruction \"{read_path}\"'"
        item = {"type": "command_execution", "id": "read1", "command": command}
        print(json.dumps({"type": "item.started", "item": item}))
        item.update(status="completed", exit_code=int(not has_skill and CONTROL_PATH == "catalog-failed"),
                    aggregated_output=skill.read_text(encoding="utf-8") if has_skill and LOAD else str(skill))
        print(json.dumps({"type": "item.completed", "item": item}))
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "cached_input_tokens": 8,
                                                        "output_tokens": 3, "reasoning_output_tokens": 1}}))
    sys.exit(0)
if access:
    name, arguments = "Read", {"file_path": read_path}
    if not HAS_SKILL and CONTROL_PATH and CONTROL_PATH.startswith("skill-"):
        name, arguments = "Skill", {"skill": "report-claim-audit"}
    if not HAS_SKILL and CONTROL_PATH in {"catalog-probe", "workspace-probe"}:
        name, arguments = "Glob", {"path": read_path, "pattern": "**/SKILL.md"}
    if not HAS_SKILL and CONTROL_PATH == "catalog-probe":
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "local-glob", "name": "Glob", "input": {"pattern": "*.txt"}}
        ]}}))
        for i in range(4):
            print(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": f"local{i}", "name": "Read", "input": {"file_path": "input.txt"}}
            ]}}))
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "read1", "name": name, "input": arguments}
    ]}}))
    if HAS_SKILL or CONTROL_PATH != "catalog-pending":
        print(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "read1",
             "is_error": not HAS_SKILL and CONTROL_PATH in {"skill-failed", "catalog-failed"},
             "content": "Skill report-claim-audit not found" if not HAS_SKILL and
             CONTROL_PATH == "skill-not-found" else "stub output"}
        ]}}))
print(json.dumps({"type": "result", "subtype": "success", "num_turns": 2,
                  "usage": {"output_tokens": 3},
                  "result": answer}))
"""


STUB_CODE = compile(STUB, "<necessity-runtime-stub>", "exec")
STUB_NAMES = (
    "RUNTIME", "MODE", "HAS_SKILL", "IS_TERSE", "SHELL", "LOAD", "LEAK_BASELINE", "FAKE_LOAD", "SCORE",
    "CONTROL_PATH", "CATALOG", "RESPONSE", "PI_CONFIG", "PI_AUTH", "PI_MODEL", "PI_THINKING", "FAILURE",
)


def run_stub(argv, constants, *, cwd, env, input_text):
    # Keep the caller's launch inputs and a fresh namespace; only the code object is shared.
    scope = deepcopy(dict(zip(STUB_NAMES, constants, strict=True)))
    stdout, stderr = io.StringIO(), io.StringIO()
    with (patch.dict(os.environ, env, clear=True), chdir(cwd), patch.object(sys, "argv", argv),
          patch.object(sys, "stdin", io.StringIO(input_text)), redirect_stdout(stdout), redirect_stderr(stderr)):
        try:
            exec(STUB_CODE, scope)
        except SystemExit as exc:
            code = exc.code or 0
        else:
            code = 0
    return subprocess.CompletedProcess(argv, code, stdout.getvalue(), stderr.getvalue())


PI_CONFIG = {"baseUrl": "https://pi.invalid/v1", "apiKey": "private-pi-model-key",
             "headers": {"X-Stub": "${PI_STUB_HEADER}"}, "api": "openai-completions",
             "models": [{"id": "deepseek-v4.1-flash-fast"}, {"id": "stub-model"}]}
PI_AUTH = {"type": "api_key", "key": "private-pi-auth-key"}


def setup_trial(tmp_path, monkeypatch, *, runtime="claude", mode="forced", leak=False,
                load=True, shell=False, fake_load=False, scores=None, thresholds=None,
                control_path=None, response=None, repeats=2, pi_override=False, failure=None, real_process=False):
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
    for key in (*runner.PROFILE, "AUDIT_STATE_DIR", "GIT_DIR", "ARBITRARY_PARENT_SECRET", "HERMES_HOME"):
        monkeypatch.setenv(key, str(outside))
    if sys.platform == "win32":
        monkeypatch.setenv("HOMEDRIVE", outside.drive)
        monkeypatch.setenv("HOMEPATH", str(outside)[len(outside.drive):])
    monkeypatch.setenv("EVAL_STUB_TOKEN", "private-token")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "not-for-codex")
    if runtime == "pi":
        host_skill = outside / ".agents" / "skills" / "host-only" / "SKILL.md"
        host_skill.parent.mkdir(parents=True)
        host_skill.write_text("do not discover", encoding="utf-8")
        agent = outside / ".pi" / "agent"
        agent.mkdir(parents=True)
        (agent / "models.json").write_text(json.dumps({"providers": {
            "tencent-litellm": PI_CONFIG, "other": {"apiKey": "$OTHER_PI_KEY"},
        }}), encoding="utf-8")
        (agent / "auth.json").write_text(json.dumps({
            "tencent-litellm": PI_AUTH, "other": {"type": "api_key", "key": "unrelated-pi-auth"},
        }), encoding="utf-8")
        for name in ("settings.json", "extensions", "sessions", "skills"):
            (agent / name).write_text("do not copy", encoding="utf-8")
        monkeypatch.setenv("OTHER_PI_KEY", "unrelated-pi-env")
        monkeypatch.setenv("PI_STUB_HEADER", "private-pi-header")
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
        monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(agent / "sessions"))
    # tempfile chooses its base independently of the untrusted agent profile.
    monkeypatch.setattr(runner.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(runner, "codex_host_skill_rules", lambda: [])
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "input.txt").write_text("original", encoding="utf-8")
    if control_path:
        fixture_skill = fixture / "skills" / "report-claim-audit"
        fixture_skill.mkdir(parents=True)
        (fixture_skill / "input.txt").write_text("fixture, not treatment", encoding="utf-8")
    rubric = {"answer": {"field": "answer", "equals": 42}}
    if response is not None:
        rubric["artifact"] = {"file": "artifact.txt", "contains": "expected artifact"}
    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "id": "test-eval", "skill": "report-claim-audit", "fixture": "fixture",
        "prompt": "same prompt for every arm: report-claim-audit", "terse": "frozen terse text", "shell": shell,
        "rubric": rubric,
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
        constants = (runtime, mode, has_skill, is_terse, shell, load, leak, fake_load and has_skill,
                     score, control_path, str(runner.SKILLS), response, PI_CONFIG, PI_AUTH,
                     f"tencent-litellm/{'stub-model' if pi_override else 'deepseek-v4.1-flash-fast'}",
                     "high" if pi_override == "thinking" else "max", failure)
        if arm and failure == "timeout":
            raise runner.subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if real_process:
            header = ", ".join(STUB_NAMES)
            # Match the runtime's UTF-8 JSONL stream even on Windows legacy code pages.
            return process([sys.executable, "-X", "utf8", "-c", f"{header} = {constants!r}\n" + STUB, *argv[1:]],
                           **kwargs)
        return run_stub(argv, constants, cwd=cwd, env=kwargs["env"], input_text=kwargs.get("input", ""))

    monkeypatch.setattr(runner, "run_process", launch)
    results = tmp_path / "results"
    argv = ["runner", str(task), "--runtime", runtime, "--mode", mode, f"--{runtime}", sys.executable,
            "--results", str(results), "--repeats", str(repeats)]
    if runtime != "pi" or pi_override:
        argv.extend(("--model", "stub-model"))
    if pi_override == "thinking":
        argv.extend(("--thinking", "high"))
    if thresholds is not None:
        policy = tmp_path / "thresholds.json"
        policy.write_text(json.dumps(thresholds), encoding="utf-8")
        argv.extend(("--thresholds", str(policy)))
    monkeypatch.setattr(sys, "argv", argv)
    return results, seen


@pytest.mark.parametrize(("runtime", "shell"), [("claude", False), ("codex", True), ("pi", False)])
def test_three_arm_results_and_process_isolation(tmp_path, monkeypatch, runtime, shell):
    results, seen = setup_trial(tmp_path, monkeypatch, runtime=runtime, shell=shell, real_process=True)
    outside = tmp_path / "outside"
    before = {path: path.read_bytes() for path in outside.rglob("*") if path.is_file()}
    with patch.object(subprocess, "Popen", wraps=subprocess.Popen) as spawn:
        assert runner.main() == 0
    assert spawn.call_count == len(seen)
    if os.name == "nt":
        for call in spawn.call_args_list:
            assert call.kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
            startup = call.kwargs["startupinfo"]
            assert startup.dwFlags & subprocess.STARTF_USESHOWWINDOW
            assert startup.wShowWindow == subprocess.SW_HIDE
    assert len(set(seen)) == len(seen) == 7
    assert all(not path.parent.exists() for path in seen[1:])
    assert not seen[0].exists()
    assert {path: path.read_bytes() for path in outside.rglob("*") if path.is_file()} == before
    assert (tmp_path / "fixture/input.txt").read_text(encoding="utf-8") == "original"
    report, = results.glob("*.json")
    assert report.with_suffix(".md").is_file()
    record = json.loads(report.read_text(encoding="utf-8"))
    assert report.stem.endswith(f"-test-eval-{runtime}-forced")
    assert record["schema_version"] == 3
    assert record["cli_version"] == "stub 1.0"
    assert record["order"] == ["none", "terse", "skill", "skill", "terse", "none"]
    assert record["summary"]["skill"]["pass^k"] is True
    assert record["summary"]["none"]["pass^k"] is False
    assert record["runs"]["skill"][0]["usage"]["output_tokens"] == (6 if runtime == "pi" else 3)
    assert json.loads(record["runs"]["skill"][0]["output"])["cwd"].startswith("<trial>")
    assert record["verdict"] == "skill-wins"
    if runtime == "codex":
        assert record["runs"]["skill"][0]["tokens"] == 15
        assert "private-token" not in report.read_text(encoding="utf-8")
        assert "private-header" not in report.read_text(encoding="utf-8")
    elif runtime == "pi":
        assert record["model"] == "tencent-litellm/deepseek-v4.1-flash-fast"
        assert record["thinking"] == "max"
        run = record["runs"]["skill"][0]
        assert run["usage"] == {"input_tokens": 24, "output_tokens": 6, "cache_read_tokens": 16,
                                "cache_write_tokens": 4, "total_tokens": 50}
        assert run["tokens"] == 50
        assert run["exit_code"] == 0
        assert run["skill_loaded"]
        for path in results.iterdir():
            saved = path.read_text(encoding="utf-8")
            assert "private-pi-" not in saved and "unrelated-pi-" not in saved


@pytest.mark.parametrize("override", [True, "thinking"])
def test_pi_natural_skill_discovery_and_overrides(tmp_path, monkeypatch, override):
    results, _ = setup_trial(tmp_path, monkeypatch, runtime="pi", mode="natural",
                             pi_override=override, repeats=1)
    assert runner.main() == 0
    report, = results.glob("*.json")
    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["model"] == "tencent-litellm/stub-model"
    assert record["thinking"] == ("high" if override == "thinking" else "max")
    assert record["runs"]["skill"][0]["skill_loaded"]


@pytest.mark.parametrize(("failure", "exit_code"), [
    ("exit", 7), ("marker", 0), ("stop", 0), ("aborted", 0), ("stream", 0), ("timeout", None),
])
def test_pi_failure_does_not_score_answer(tmp_path, monkeypatch, failure, exit_code):
    results, seen = setup_trial(tmp_path, monkeypatch, runtime="pi", failure=failure, repeats=1)
    assert runner.main() == 1
    report, = results.glob("*.json")
    record = json.loads(report.read_text(encoding="utf-8"))
    run = record["runs"]["skill"][0]
    assert not run["valid"]
    assert run["error"]
    assert run["exit_code"] == exit_code
    assert run["answer_format"] == "none"
    assert run["score"] == 0
    assert record["verdict"] == "inconclusive"
    assert all(not path.parent.exists() for path in seen[1:])


def test_pi_rejects_credential_commands_before_launch(tmp_path, monkeypatch, capsys):
    results, seen = setup_trial(tmp_path, monkeypatch, runtime="pi", repeats=1)
    auth_file = tmp_path / "outside/.pi/agent/auth.json"
    auth_file.write_text(json.dumps({
        "tencent-litellm": {"type": "api_key", "key": "!never-run-private-command"},
    }), encoding="utf-8")
    assert runner.main() == 2
    assert not seen
    assert not results.exists()
    assert "never-run-private-command" not in capsys.readouterr().err


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


@pytest.mark.parametrize(("runtime", "path", "reason", "probes"), [
    ("claude", "fixture", None, 0),
    ("codex", "relative-fixture", None, 0),
    ("codex", "mcp-fixture", None, 0),
    ("claude", "catalog-probe", None, 1),
    ("codex", "catalog-probe", None, 1),
    ("claude", "workspace-probe", None, 0),
    ("claude", "skill-failed", None, 1),
    ("codex", "skill-failed", None, 1),
    ("claude", "skill-not-found", None, 1),
    ("claude", "catalog-failed", None, 0),
    ("claude", "catalog-pending", None, 0),
    ("codex", "catalog-failed", None, 0),
    ("claude", "catalog", "catalog-read", 0),
    ("codex", "catalog", "catalog-read", 0),
    ("claude", "other-catalog", "catalog-read", 0),
    ("codex", "mcp-catalog", "catalog-read", 0),
    ("claude", "host-reference", "host-skill-read", 0),
    ("claude", "host-root-file", "host-skill-read", 0),
    ("codex", "host-reference", "host-skill-read", 0),
    ("claude", "standalone", "host-skill-read", 0),
    ("claude", "config", "host-skill-read", 0),
    ("codex", "config", "host-skill-read", 0),
    ("claude", "skill-tool", "skill-load", 0),
    ("codex", "skill-tool", "skill-load", 0),
    ("claude", None, "installed-copy-read", 0),
    ("codex", None, "installed-copy-read", 0),
    ("pi", "relative-fixture", None, 0),
    ("pi", "catalog-probe", None, 1),
    ("pi", "workspace-probe", None, 0),
    ("pi", "catalog-failed", None, 0),
    ("pi", "catalog-pending", None, 0),
    ("pi", "skill-not-found", None, 1),
    ("pi", "catalog", "catalog-read", 0),
    ("pi", "host-reference", "host-skill-read", 0),
    ("pi", "skill-tool", "skill-load", 0),
    ("pi", None, "installed-copy-read", 0),
])
def test_control_skill_probes_and_contamination(tmp_path, monkeypatch, runtime, path, reason, probes):
    results, _ = setup_trial(tmp_path, monkeypatch, runtime=runtime, leak=path is None,
                             control_path=path, repeats=1)
    contaminated = reason is not None
    assert runner.main() == int(contaminated)
    report, = results.glob("*.json")
    record = json.loads(report.read_text(encoding="utf-8"))
    for arm in ("none", "terse"):
        run = record["runs"][arm][0]
        assert run["valid"] is not contaminated
        assert run["contaminated"] is contaminated
        assert run["skill_loaded"] is (reason == "skill-load"
                                       or (reason == "installed-copy-read" and runtime in {"claude", "pi"}))
        assert run["skill_probe_count"] == probes
        assert sum(event["skill_probe"] for event in run["trace"]) == probes
        assert run["contamination_reasons"] == ([reason] if reason else [])
        base = {"tool", "skill_probe", "skill_loaded", "contamination_reasons"}
        assert all(set(event) in (base, base | {"contamination_paths"}) for event in run["trace"])
        flagged = [p for event in run["trace"] for p in event.get("contamination_paths", [])]
        assert bool(flagged) is (reason in {"catalog-read", "host-skill-read"})
        assert record["summary"][arm]["pass^k"] is (None if contaminated else False)
    assert record["verdict"] == ("inconclusive" if contaminated else "skill-wins")


@pytest.mark.parametrize(("response", "answer_format", "passed"), [
    ('{"answer":42}', "bare", True),
    ('[{"answer":42}]', "bare", False),
    ('```json\n{"answer":0}\n```\n```json\n{"answer":42}\n```\n{"answer":0}', "fenced", True),
    ('```json\n[{"answer":42}]\n```\n{"answer":42}', "fenced", False),
    ('First {"answer":0}. Final {"answer":42,"nested":{"answer":0}}. Unfinished {"nested":{"answer":0}',
     "extracted", True),
    ('No JSON answer. [ {"answer":42} ]', "none", False),
])
def test_answer_format_preserves_content_and_artifact_scores(tmp_path, monkeypatch, response, answer_format, passed):
    results, _ = setup_trial(tmp_path, monkeypatch, response=response)
    assert runner.main() == 0
    report, = results.glob("*.json")
    run = json.loads(report.read_text(encoding="utf-8"))["runs"]["skill"][0]
    assert run["checks"] == {"answer": passed, "artifact": True}
    assert run["answer_format"] == answer_format


@pytest.mark.parametrize(("runtime", "cap", "order", "tokens"), [
    ("claude", 2, ["none"], 3),
    ("codex", 30, ["none", "terse"], 30),
    ("claude", 18, ["none", "terse", "skill", "skill", "terse", "none"], 18),
])
def test_token_budget_stops_between_trials(tmp_path, monkeypatch, runtime, cap, order, tokens):
    results, seen = setup_trial(tmp_path, monkeypatch, runtime=runtime)
    sys.argv.extend(("--max-total-tokens", str(cap)))
    complete = len(order) == 6
    assert runner.main() == int(not complete)
    assert len(seen) == 1 + len(order)
    report, = results.glob("*.json")
    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["order"] == order
    assert record["total_tokens"] == tokens
    assert record["limits"]["total_tokens"] == cap
    planned = ["none", "terse", "skill", "skill", "terse", "none"]
    assert record["skipped_trials"] == [
        {"arm": arm, "repeat": i // 3 + 1} for i, arm in enumerate(planned) if i >= len(order)
    ]
    assert record["verdict"] == ("skill-wins" if complete else "inconclusive")


def test_nonpositive_token_cap_starts_no_process(tmp_path, monkeypatch):
    results, seen = setup_trial(tmp_path, monkeypatch)
    sys.argv.extend(("--max-total-tokens", "0"))
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
    assert not seen
    assert not results.exists()


@pytest.mark.parametrize(("runtime", "mode", "shell", "fake", "exit_code"), [
    ("claude", "forced", True, False, 1),
    ("codex", "forced", True, True, 1),
    ("codex", "natural", False, False, 0),
    ("pi", "forced", True, True, 1),
    ("pi", "natural", False, False, 0),
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


def test_all_committed_necessity_tasks_validate():
    tasks_dir = runner.EVALS / "tasks"
    for suite in (tasks_dir, tasks_dir / "set-b"):
        seen_ids = set()
        files = sorted(suite.glob("*.json"))
        assert files
        for path in files:
            task, fixture = runner.load_task(path)
            assert task["id"] not in seen_ids, f"duplicate task id {task['id']!r} in {path}"
            seen_ids.add(task["id"])
            assert fixture.is_dir()
