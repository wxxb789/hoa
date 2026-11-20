"""codex argv and event contract tests."""

import json
import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "gdd" / "scripts" / "tests"))
from runner_cases import REPORT, RESULT_SCHEMA, STAGE_RESULT, RunnerCase, fold_fixture
from agent_run import load_route


def test_argv():
    route = load_route("codex")
    args = Namespace(name="Test Run", model=None, thinking=None, schema=None, resume=None, profile=None)
    base = ["exec", "--json", "--dangerously-bypass-approvals-and-sandbox"]
    base += ["--disable", "computer_use", "--disable", "browser_use", "--disable", "browser_use_external",
             "--disable", "in_app_browser", "--disable", "remote_plugin", "--disable", "image_generation",
             "--disable", "skill_search", "--disable", "plugins", "--disable", "apps", "--disable", "memories"]
    assert route.argv(args, []) == base + ["-"]
    args.resume = "S1"
    assert route.argv(args, []) == base[:1] + ["resume"] + base[1:] + ["S1", "-"]
    args.resume = None
    args.model, args.thinking, args.schema = "m1", "high", "schema.json"
    extra = ["-c", "mcp_servers.example.enabled=false"]
    assert route.argv(args, extra) == base + [
        "-m", "m1", "-c", "model_reasoning_effort=high", "--output-schema", "schema.json", *extra, "-",
    ]


def test_fold():
    route = load_route("codex")
    expected = {
        "answer": json.dumps(STAGE_RESULT, separators=(",", ":")),
        "session_id": "00000000-0000-7000-8000-000000000002",
        "turns": 1, "tool_calls": 1, "cost_usd": None,
        "usage": {"input_tokens": 25409, "output_tokens": 72, "cache_read_tokens": 0, "total_tokens": 25481},
    }
    success = fold_fixture(route, "ok")
    assert route.succeeded(success["success_marker"])
    assert {key: success[key] for key in expected} == expected

    acc = fold_fixture(route, "fail")
    assert not route.succeeded(acc["success_marker"])
    assert acc["success_marker"] == "turn.failed"
    assert "The selected model" in acc["error"]


class CodexIntegrationTests(RunnerCase):
    def test_native_schema_and_report(self):
        extra = "-c mcp_servers.example.enabled=false"
        argv = self.assert_native_schema("codex", "--output-schema", RESULT_SCHEMA, {
            "type": "item.completed", "item": {"id": "item_r", "type": "agent_message", "text": REPORT},
        }, offset=2, options=("--model", "m1", "--thinking", "high", "--extra", extra))
        self.assertEqual(argv[-9:], ["-m", "m1", "-c", "model_reasoning_effort=high",
                                     "--output-schema", RESULT_SCHEMA, *extra.split(), "-"])
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", argv)
