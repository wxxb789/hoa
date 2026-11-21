"""omp argv and event contract tests."""

import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "gdd" / "scripts" / "tests"))
from runner_cases import PROMPT, RunnerCase, fold_fixture
from agent_run import load_route


def test_argv():
    route = load_route("omp")
    args = Namespace(name="Test Run", model=None, thinking=None, schema=None, resume=None, profile=None)
    base = ["-p", "--mode=json", "--approval-mode", "yolo"]
    assert route.argv(args, []) == base
    args.resume = "S1"
    assert route.argv(args, []) == base + ["-r", "S1"]
    args.resume = None
    args.model, args.thinking = "m1", "high"
    extra = ["--no-tools", "-x"]
    assert route.argv(args, extra) == base + ["--model", "m1", "--thinking", "high", "--no-tools", "-x"]


def test_fold():
    route = load_route("omp")
    expected = {
        "answer": "done",
        "session_id": "00000000-0000-7000-8000-000000000001", "turns": 2, "tool_calls": 1,
        "usage": {"input_tokens": 6, "output_tokens": 54, "cache_read_tokens": 13420, "total_tokens": 26962},
        "cost_usd": 0.035599,
    }
    success = fold_fixture(route, "ok")
    assert route.succeeded(success["success_marker"])
    assert {key: success[key] for key in expected} == expected

    acc = fold_fixture(route, "fail")
    assert not route.succeeded(acc["success_marker"])
    assert acc["success_marker"] == "error"


class OmpIntegrationTests(RunnerCase):
    def test_legacy_start_flags(self):
        self.start("omp-old-flags", "omp", "ok", "--backend", "tmux", "--profile", "with spaces")
        self.assertEqual(self.recorded()["argv"][-3:], ["--profile", "with spaces", PROMPT])
        self.finished("omp-old-flags")
