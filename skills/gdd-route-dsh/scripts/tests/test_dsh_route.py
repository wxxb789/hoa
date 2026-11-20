"""dsh argv and event contract tests."""

import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "gdd" / "scripts" / "tests"))
from runner_cases import RunnerCase, fold_fixture
from agent_run import load_route


def test_argv(monkeypatch):
    route = load_route("dsh")
    args = Namespace(name="Test Run", model=None, thinking=None, schema=None, resume=None, profile=None)
    for key in ("DSH_APPROVAL_POLICY", "DSH_RUN_PROFILE", "DSH_PERMISSION_MODE"):
        monkeypatch.delenv(key, raising=False)
    base = ["--profile", "headless", "--json", "--permission-mode", "workspace-write", "--approval-policy", "never", "-"]
    assert route.argv(args, []) == base
    args.resume = "S1"
    assert route.argv(args, []) == base[:3] + ["--session-id", "S1"] + base[3:]
    args.resume = None
    monkeypatch.setenv("DSH_RUN_PROFILE", "custom")
    monkeypatch.setenv("DSH_PERMISSION_MODE", "read-only")
    extra = ["--patch", "overlay"]
    assert route.argv(args, extra) == ["--profile", "custom", "--patch", "overlay", "--json", "--permission-mode", "read-only",
                                      "--approval-policy", "never", "-"]


def test_fold():
    route = load_route("dsh")
    expected = {
        "answer": "done",
        "session_id": "dsh-session-0001", "turns": 1, "tool_calls": 2,
        "usage": {"input_tokens": 250, "output_tokens": 40, "cache_read_tokens": 80, "total_tokens": 290},
        "cost_usd": None,
    }
    success = fold_fixture(route, "ok")
    assert route.succeeded(success["success_marker"])
    assert {key: success[key] for key in expected} == expected

    acc = fold_fixture(route, "fail")
    assert not route.succeeded(acc["success_marker"])
    assert acc["success_marker"] == "aborted"


class DshIntegrationTests(RunnerCase):
    def test_t13_dsh_env_scrub(self):
        scrubbed = {"DSH_PROFILE": "caller", "DSH_PROFILE_DIR": "/caller", "DSH_SESSION_ID": "caller-session"}
        self.start("scrub", "dsh", env={**scrubbed, "DSH_KEEP": "1"})
        seen = set(self.recorded()["env"])
        self.assertIn("DSH_KEEP", seen)
        self.assertFalse(seen & set(scrubbed), seen)
        self.finished("scrub")

    def test_legacy_start_flags(self):
        self.start("dsh-old-flags", "dsh", "ok", "--session-id", "S1")
        self.assertEqual(self.recorded()["argv"], [
            "--profile", "headless", "--json", "--session-id", "S1", "--permission-mode", "workspace-write",
            "--approval-policy", "never", "-",
        ])
        self.finished("dsh-old-flags")

    def test_start_refusals(self):
        for args, env, key in (
            (("--model", "m"), {}, "--model"),
            (("--thinking", "high"), {}, "--thinking"),
            ((), {"DSH_APPROVAL_POLICY": "on-request"}, "DSH_APPROVAL_POLICY"),
        ):
            with self.subTest(key=key):
                proc = self.start("refused", "dsh", "ok", *args, env=env, expect=1)
                self.assertIn(key, proc.stderr)
                self.assertFalse(Path(self.root).exists())
