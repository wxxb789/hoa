"""opencode argv and event contract tests."""

import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "gdd" / "scripts" / "tests"))
from runner_cases import RunnerCase, fold_fixture
from agent_run import load_route


def test_argv():
    route = load_route("opencode")
    args = Namespace(name="Test Run", model=None, thinking=None, schema=None, resume=None, profile=None)
    base = ["run", "--standalone", "--format", "json", "--auto", "--title", "test-run"]
    assert route.argv(args, []) == base
    args.resume = "S1"
    assert route.argv(args, []) == base + ["-s", "S1"]
    args.resume = None
    args.model, args.thinking = "m1", "high"
    extra = ["--no-tools", "-x"]
    assert route.argv(args, extra) == base + ["-m", "m1#high", "--no-tools", "-x"]


def test_fold():
    route = load_route("opencode")
    expected = {
        "answer": "done",
        "session_id": "ses_000000000000000000000001", "turns": 2, "tool_calls": 1,
        "usage": {"input_tokens": 6, "output_tokens": 23, "cache_read_tokens": 15605, "total_tokens": 31269},
        "cost_usd": 0.040889,
    }
    success = fold_fixture(route, "ok")
    assert route.succeeded(success["success_marker"])
    assert {key: success[key] for key in expected} == expected

    acc = fold_fixture(route, "fail")
    assert not route.succeeded(acc["success_marker"])
    assert acc["success_marker"] == "error"
    assert "Model unavailable" in acc["error"]


class OpencodeIntegrationTests(RunnerCase):
    def test_thinking_without_model_is_refused_before_creating_a_run(self):
        proc = self.start("refused", "opencode", "ok", "--thinking", "high", expect=1)
        self.assertIn("--model", proc.stderr)
        self.assertFalse(Path(self.root).exists())
