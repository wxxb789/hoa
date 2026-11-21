"""Copilot argv and JSONL result contract tests."""

import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "gdd" / "scripts" / "tests"))
from runner_cases import fold_fixture
from agent_run import load_route


def test_argv():
    route = load_route("copilot")
    args = Namespace(model=None, thinking=None, resume=None)
    base = ["--output-format", "json", "--allow-all", "--no-ask-user",
            "--no-eager-powershell-resolution", "--no-auto-update"]
    assert route.prompt == "argv"
    assert route.argv(args, []) == base + ["--prompt"]
    args.model, args.thinking, args.resume = "model", "high", "S1"
    assert route.argv(args, ["--disable-builtin-mcps"]) == base + [
        "--model", "model", "--reasoning-effort", "high", "--resume", "S1",
        "--disable-builtin-mcps", "--prompt",
    ]


def test_fold():
    route = load_route("copilot")
    acc = fold_fixture(route, "ok")
    assert route.succeeded(acc["success_marker"])
    assert acc["answer"] == "PROBE_OK"
    assert acc["session_id"] == "00000000-0000-7000-8000-000000000001"
    assert acc["turns"] == 1

    failed = fold_fixture(route, "fail")
    assert not route.succeeded(failed["success_marker"])
    assert failed["answer"] == "PROBE_OK"
    assert not route.succeeded(1)
    assert not route.succeeded(False)
