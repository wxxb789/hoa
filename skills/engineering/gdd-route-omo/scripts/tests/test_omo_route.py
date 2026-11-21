"""Omo argv and Senpi message-event contract tests."""

import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "gdd" / "scripts" / "tests"))
from runner_cases import fold_fixture
from agent_run import load_route


def test_argv():
    route = load_route("omo")
    args = Namespace(model=None, thinking=None, resume=None)
    base = ["--print", "--mode", "json", "--no-extensions", "--no-ask-user"]
    assert route.prompt == "stdin"
    assert route.argv(args, []) == base
    args.model, args.thinking, args.resume = "provider/model", "high", "saved session.jsonl"
    assert route.argv(args, ["--no-tools"]) == base + [
        "--model", "provider/model", "--thinking", "high", "--session", "saved session.jsonl", "--no-tools",
    ]


def test_fold():
    route = load_route("omo")
    acc = fold_fixture(route, "ok")
    assert route.succeeded(acc["success_marker"])
    assert acc["answer"] == "PROBE_OK"
    assert acc["session_id"] == "00000000-0000-7000-8000-000000000001"
    assert acc["turns"] == 1
    assert acc["usage"]["total_tokens"] == 6720

    failed = fold_fixture(route, "fail")
    assert not route.succeeded(failed["success_marker"])
