import base64
import json
import os
import subprocess
from argparse import Namespace
from pathlib import PurePosixPath

import pytest

from evals import run_necessity_eval as runner
from evals import wsl_pi


@pytest.mark.parametrize("arm", ["none", "terse", "skill"])
def test_trial_transfers_only_fixture_treatment_events_and_rubric_files(tmp_path, arm):
    root = tmp_path / "trial"
    work = root / "work"
    work.mkdir(parents=True)
    (work / "fixture.txt").write_bytes(b"fixture\x00")
    (work / "deleted.txt").write_text("stale", encoding="utf-8")
    agent = root / "home/.pi/agent"
    skills = agent / "skills"
    skills.mkdir(parents=True)
    (agent / "auth.json").write_text("must not travel", encoding="utf-8")
    if arm == "skill":
        (skills / "test").mkdir()
        (skills / "test/SKILL.md").write_bytes(b"instructions")
    event = '{"type":"message_end"}\n'

    def process(command, **kwargs):
        assert command == [
            "C:/Windows/System32/wsl.exe", "--distribution", "Test Ubuntu", "--user", "root",
            "--cd", "/", "--exec", "/usr/bin/unshare", "--mount", "--propagation", "private", "--",
            "/usr/bin/python3", "-I", "/opt/hoa-pi-sandbox/wsl_pi.py", "--trial",
        ]
        assert kwargs["cwd"] == tmp_path
        assert kwargs["timeout"] == 53
        wire = json.loads(kwargs["input"])
        assert (wire["args"], wire["prompt"], wire["timeout"]) == (["--offline"], "prompt", 23)
        assert wire["outputs"] == ["deleted.txt", "nested/report.txt"]
        expected = {"work/deleted.txt": b"stale", "work/fixture.txt": b"fixture\x00"}
        if arm == "skill":
            expected["home/.pi/agent/skills/test/SKILL.md"] = b"instructions"
        assert {k: base64.b64decode(v) for k, v in wire["files"].items()} == expected
        result = {"events": event, "exit": 0, "timed_out": False, "outputs": {"nested/report.txt": "cmVwb3J0"}}
        return subprocess.CompletedProcess(command, 0, json.dumps(result))

    sandbox = wsl_pi.WslPi(process, "C:/Windows/System32/wsl.exe", "Test Ubuntu", tmp_path)
    proc = sandbox.run(root, [wsl_pi.PI, "--offline"], "prompt", {"deleted.txt", "nested/report.txt"}, 23)
    assert proc.stdout == event and proc.returncode == 0
    assert (work / "nested/report.txt").read_bytes() == b"report"
    assert not (work / "deleted.txt").exists()


def test_boundary_failure_prevents_all_trials(monkeypatch, tmp_path):
    calls = []

    def process(command, **_kwargs):
        calls.append(command[-1])
        return subprocess.CompletedProcess(command, 78, "", "must not echo private diagnostics")

    monkeypatch.setattr(runner, "run_process", process)
    monkeypatch.setattr(runner, "pi_provider", lambda _model: ({}, (), ()))
    monkeypatch.setattr(runner, "trial", lambda *_args: pytest.fail("launched a trial after a boundary failure"))
    args = Namespace(task=runner.EVALS / "tasks/set-b/ghc-search.json", runtime="pi", mode="natural",
                     model=runner.PI_DEFAULT_MODEL,
                     thresholds=runner.EVALS / "necessity-thresholds.json", results=tmp_path,
                     wsl_pi=wsl_pi.WslPi(process, "wsl.exe", "Ubuntu", tmp_path))
    with pytest.raises(OSError, match=wsl_pi.BOUNDARY):
        runner.run_eval(args)
    assert calls == ["--check"]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("operation", ["--check", "--trial"])
def test_boundary_failure_prevents_pi_launch(monkeypatch, operation):
    def fail(_uid):
        raise PermissionError(wsl_pi.BOUNDARY)

    monkeypatch.setattr(wsl_pi, "boundary", fail)
    monkeypatch.setattr(subprocess, "check_output", lambda *_a, **_kw: pytest.fail("started Pi"))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: pytest.fail("started Pi"))
    with pytest.raises(PermissionError, match=wsl_pi.BOUNDARY):
        wsl_pi.inside(operation, 1001)


def test_linux_trace_paths_classify_installed_and_external_reads():
    work = PurePosixPath("/trial/work")
    installed = PurePosixPath("/trial/home/.pi/agent/skills/ghc-search/SKILL.md")
    for path, expected in {
        "~/.pi/agent/skills/ghc-search/SKILL.md": "installed-copy-read",
        "/mnt/q/repos/hoa/skills/ghc-search/SKILL.md": "host-skill-read",
        "C:/Users/operator/.agents/skills/ghc-search/SKILL.md": "host-skill-read",
        "/trial/work/fixture.md": None,
    }.items():
        real, literal = runner.trace_path(path, work)
        assert runner.skill_read(real, literal, work, installed) == expected


@pytest.mark.skipif(os.name == "nt", reason="artifact read runs inside Linux")
def test_artifact_copy_never_follows_links_or_reads_special_files(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(wsl_pi, "TRIAL", tmp_path)
    (work / "regular.txt").write_bytes(b"safe")
    (work / "link.txt").symlink_to(work / "regular.txt")
    (work / "dirlink").symlink_to(work, target_is_directory=True)
    os.mkfifo(work / "pipe")
    (work / "oversize.txt").write_bytes(b"x" * 65537)
    assert base64.b64decode(wsl_pi.copy_artifact("regular.txt")) == b"safe"
    for path in ("link.txt", "dirlink/regular.txt", "pipe", "oversize.txt", "../regular.txt"):
        assert wsl_pi.copy_artifact(path) is None
