"""claude argv and event contract tests."""

import json
import sys
import uuid
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "gdd" / "scripts" / "tests"))
from runner_cases import REPORT, RESULT_SCHEMA, STAGE_RESULT, RunnerCase, fold_fixture, read
from agent_run import load_route


def test_argv():
    route = load_route("claude")
    args = Namespace(name="Test Run", model=None, thinking=None, schema=None, resume=None, profile=None)
    base = ["-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions"]
    fresh = route.argv(args, [])
    assert fresh[:-1] == base + ["--session-id"]
    assert uuid.UUID(fresh[-1]).version == 4
    args.resume = "S1"
    assert route.argv(args, []) == base + ["--resume", "S1"]
    args.model, args.thinking = "m1", "high"
    extra = ["--no-tools", "-x"]
    assert route.argv(args, extra) == base + ["--resume", "S1", "--model", "m1", "--effort", "high", "--no-tools", "-x"]


def test_fold():
    route = load_route("claude")
    expected = {
        "answer": json.dumps(STAGE_RESULT, separators=(",", ":")),
        "session_id": "00000000-0000-4000-8000-000000000004",
        "turns": 3, "tool_calls": 1, "cost_usd": 0.236953,
        "usage": {"input_tokens": 4, "output_tokens": 273, "cache_read_tokens": 44437, "total_tokens": 89232},
    }
    success = fold_fixture(route, "ok")
    assert route.succeeded(success["success_marker"])
    assert {key: success[key] for key in expected} == expected

    acc = fold_fixture(route, "fail")
    assert not route.succeeded(acc["success_marker"])
    assert acc["success_marker"] == "api_error"
    assert "API Error: 400 Model" in acc["error"]


class ClaudeIntegrationTests(RunnerCase):
    def test_native_schema_and_report(self):
        self.assert_native_schema("claude", "--json-schema", json.loads(read(RESULT_SCHEMA)), {
            "type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": REPORT}]},
        }, offset=3)
