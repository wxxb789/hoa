"""pi argv and event contract tests."""

import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "gdd" / "scripts" / "tests"))
from runner_cases import fold_fixture
from agent_run import load_route, new_acc


def test_argv():
    route = load_route("pi")
    args = Namespace(name="Test Run", model=None, thinking=None, schema=None, resume=None, profile=None)
    base = ["--mode", "json", "--no-approve"]
    assert route.argv(args, []) == base
    args.resume = "S1"
    assert route.argv(args, []) == base + ["--session", "S1"]
    args.resume = None
    args.model, args.thinking = "m1", "high"
    extra = ["--no-tools", "-x"]
    assert route.argv(args, extra) == base + ["--model", "m1", "--thinking", "high", "--no-tools", "-x"]


def test_fold():
    route = load_route("pi")
    expected = {
        "answer": "done",
        "session_id": "00000000-0000-7000-8000-000000000006", "turns": 2, "tool_calls": 1,
        "usage": {"input_tokens": 6, "output_tokens": 28, "cache_read_tokens": 14695, "total_tokens": 29460},
        "cost_usd": 0.0,
    }
    success = fold_fixture(route, "ok")
    assert route.succeeded(success["success_marker"])
    assert {key: success[key] for key in expected} == expected

    acc = fold_fixture(route, "fail")
    assert not route.succeeded(acc["success_marker"])
    assert acc["success_marker"] == "error"
    assert "ghc API error (400)" in acc["error"]


def test_aborted_after_assistant_stop_is_not_success():
    route, acc = load_route("pi"), new_acc()
    route.fold(acc, {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop"}})
    assert route.succeeded(acc["success_marker"])
    route.fold(acc, {"type": "agent_settled", "aborted": True})
    assert not route.succeeded(acc["success_marker"])
    assert "agent_settled.aborted" in acc["error"]
