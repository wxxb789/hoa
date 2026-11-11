#!/usr/bin/env python3
"""Offline tests for the configurable trigger-eval judge and its baseline gate.

No external network, no credentials: the judge is exercised against a stdlib
OpenAI-compatible chat-completions stub bound to 127.0.0.1. Fixtures live under
.tmp-artifacts/eval-judge-tests/ and the child environment is built from scratch,
so no operator config is read.

Run: python -m unittest evals.test_judge_trigger_evals -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
JUDGE = ROOT / "evals" / "judge_trigger_evals.py"
CASES = ROOT / "evals" / "trigger-cases.json"
ARTIFACTS = ROOT / ".tmp-artifacts" / "eval-judge-tests"

from evals import judge_trigger_evals as judge  # noqa: E402
from evals import run_trigger_evals as gate  # noqa: E402


def _cases() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


class _StubHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.stub.requests.append({
            "body": body,
            "authorization": self.headers.get("authorization"),
        })
        status, payload = self.server.stub.reply(body)
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args) -> None:  # noqa: A002 - stdlib signature
        pass


class _StubServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Stub:
    """A local OpenAI-compatible chat-completions endpoint."""

    def __init__(self, mode: str = "correct", fail_case: str | None = None):
        self.mode = mode
        self.fail_case = fail_case
        self.cases = _cases()
        self.requests: list[dict] = []
        self.server = _StubServer(("127.0.0.1", 0), _StubHandler)
        self.server.stub = self
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def reply(self, body: dict) -> tuple[int, dict]:
        prompt = body["messages"][0]["content"]
        case = next(case for case in self.cases
                    if f"User request: {case['request']}\n" in prompt)
        if self.mode == "garbage" and case["id"] == self.fail_case:
            return 200, {"choices": [{"message": {"content": "no-such-artifact"}}]}
        if self.mode == "http500" and case["id"] == self.fail_case:
            return 500, {"error": "stub failure"}
        return 200, {"choices": [{"message": {"content": case["must_pick"][0]}}]}


class JudgeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(dir=ARTIFACTS))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.xdg = self.tmp / "xdg"
        self.home = self.tmp / "home"
        self.xdg.mkdir()
        self.home.mkdir()

    def stub(self, **kwargs) -> Stub:
        stub = Stub(**kwargs)
        self.addCleanup(stub.close)
        return stub

    def env(self, **overrides) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.xdg),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
        }
        for key in ("SYSTEMROOT", "TEMP", "TMP"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update({key: str(value) for key, value in overrides.items()})
        return env

    def write_config(self, text: str) -> Path:
        path = self.xdg / "evals" / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_judge(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(JUDGE), *args],
            cwd=ROOT,
            env=env or self.env(),
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_unconfigured_exits_two_with_keys_and_config_path(self) -> None:
        result = self.run_judge()
        self.assertEqual(result.returncode, 2, result.stderr)
        for key in ("base_url", "model", "effort"):
            self.assertIn(key, result.stderr)
        self.assertIn(str(self.xdg / "evals" / "config.yaml"), result.stderr)
        self.assertEqual("", result.stdout)

    def test_malformed_config_exits_two_naming_path_and_line(self) -> None:
        config = self.write_config("base_url:\n")
        result = self.run_judge()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(f"{config}:1:", result.stderr)

    def test_flag_beats_env_beats_config_and_effort_has_a_default(self) -> None:
        flag, env_stub, config = self.stub(), self.stub(), self.stub()
        self.write_config(
            f"base_url: {config.base_url}\nmodel: config-model\neffort: high\n")

        result = self.run_judge(
            "--limit", "1", "--base-url", flag.base_url,
            "--model", "flag-model", "--effort", "flag-effort",
            env=self.env(EVALS_BASE_URL=env_stub.base_url,
                         EVALS_MODEL="env-model", EVALS_EFFORT="env-effort"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((len(flag.requests), len(env_stub.requests),
                          len(config.requests)), (1, 0, 0))
        self.assertEqual(flag.requests[0]["body"]["model"], "flag-model")
        self.assertEqual(flag.requests[0]["body"]["reasoning_effort"], "flag-effort")

        result = self.run_judge(
            "--limit", "1",
            env=self.env(EVALS_BASE_URL=env_stub.base_url,
                         EVALS_MODEL="env-model", EVALS_EFFORT="env-effort"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(env_stub.requests), 1)
        self.assertEqual(env_stub.requests[0]["body"]["model"], "env-model")
        self.assertEqual(env_stub.requests[0]["body"]["reasoning_effort"], "env-effort")

        result = self.run_judge("--limit", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(config.requests), 1)
        self.assertEqual(config.requests[0]["body"]["model"], "config-model")
        self.assertEqual(config.requests[0]["body"]["reasoning_effort"], "high")

        self.write_config(f"base_url: {config.base_url}\nmodel: config-model\n")
        result = self.run_judge("--limit", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(config.requests), 2)
        self.assertEqual(config.requests[1]["body"]["reasoning_effort"], "low")

    def test_api_key_env_beats_config_and_is_sent_as_bearer(self) -> None:
        stub = self.stub()
        self.write_config(
            f"base_url: {stub.base_url}\nmodel: config-model\napi_key: config-secret\n")
        result = self.run_judge(
            "--limit", "1", env=self.env(EVALS_API_KEY="env-secret"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stub.requests[0]["authorization"], "Bearer env-secret")
        result = self.run_judge("--limit", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stub.requests[1]["authorization"], "Bearer config-secret")

    def test_stub_run_limit_three_json(self) -> None:
        stub = self.stub()
        result = self.run_judge(
            "--limit", "3", "--json", "--base-url", stub.base_url,
            "--model", "stub-model")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["passed"], 3)
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["results"]), 3)
        for entry in data["results"]:
            self.assertIn(entry["pick"], entry["must_pick"])
            self.assertTrue(entry["passed"])
        self.assertEqual(len(stub.requests), 3)
        self.assertEqual(stub.requests[0]["body"]["model"], "stub-model")
        self.assertEqual(stub.requests[0]["body"]["reasoning_effort"], "low")
        self.assertIsNone(stub.requests[0]["authorization"])

    def test_non_catalog_reply_fails_one_case_with_verbatim_pick(self) -> None:
        cases = _cases()
        stub = self.stub(mode="garbage", fail_case=cases[1]["id"])
        result = self.run_judge(
            "--limit", "3", "--json", "--base-url", stub.base_url, "--model", "stub-model")
        self.assertEqual(result.returncode, 1, result.stderr)
        data = json.loads(result.stdout)
        failed = [entry for entry in data["results"] if not entry["passed"]]
        self.assertEqual([entry["id"] for entry in failed], [cases[1]["id"]])
        self.assertEqual(failed[0]["pick"], "no-such-artifact")
        self.assertEqual(data["passed"], 2)
        self.assertEqual(data["total"], 3)

    def test_network_failure_is_per_case(self) -> None:
        cases = _cases()
        stub = self.stub(mode="http500", fail_case=cases[0]["id"])
        result = self.run_judge(
            "--limit", "3", "--json", "--base-url", stub.base_url, "--model", "stub-model")
        self.assertEqual(result.returncode, 1, result.stderr)
        data = json.loads(result.stdout)
        failed = [entry for entry in data["results"] if not entry["passed"]]
        self.assertEqual([entry["id"] for entry in failed], [cases[0]["id"]])
        self.assertTrue(failed[0]["pick"].startswith("error: HTTP 500:"),
                        failed[0]["pick"])
        self.assertEqual(data["passed"], 2)

    def test_record_with_limit_is_a_usage_error(self) -> None:
        stub = self.stub()
        result = self.run_judge(
            "--record", "--limit", "3", "--base-url", stub.base_url,
            "--model", "stub-model")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--record needs the full case set", result.stderr)
        self.assertEqual(stub.requests, [])

    def test_force_without_record_is_a_usage_error(self) -> None:
        result = self.run_judge("--force")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--force only applies with --record", result.stderr)


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(dir=ARTIFACTS))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.baseline = self.tmp / "baseline.json"
        self.stub = Stub()
        self.addCleanup(self.stub.close)
        self.addCleanup(setattr, judge, "BASELINE_PATH", judge.BASELINE_PATH)
        self.environ = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.tmp / "home"),
            "XDG_CONFIG_HOME": str(self.tmp / "xdg"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        judge.BASELINE_PATH = self.baseline

    def run_main(self, *args: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.environ, clear=True), \
                contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr):
            code = judge.main([*args, "--base-url", self.stub.base_url,
                               "--model", "stub-model"])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_record_writes_exact_schema_and_refuses_silent_overwrite(self) -> None:
        code, _out, err = self.run_main("--record")
        self.assertEqual(code, 0, err)
        self.assertTrue(self.baseline.exists())
        record = json.loads(self.baseline.read_text(encoding="utf-8"))
        self.assertEqual(set(record), {
            "case_count", "model", "effort", "passed", "total",
            "judge_endpoint_host", "generated_at", "per_case"})
        self.assertEqual(record["case_count"], len(_cases()))
        self.assertEqual(record["total"], record["case_count"])
        self.assertEqual(record["passed"], record["case_count"])
        self.assertEqual(record["model"], "stub-model")
        self.assertEqual(record["effort"], "low")
        self.assertEqual(record["judge_endpoint_host"],
                         f"127.0.0.1:{self.stub.server.server_port}")
        self.assertRegex(record["generated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(len(record["per_case"]), record["case_count"])
        self.assertEqual(set(record["per_case"][0]), {"id", "pick", "passed"})

        before = self.baseline.read_bytes()
        requests = len(self.stub.requests)
        code, _out, err = self.run_main("--record")
        self.assertEqual(code, 2, err)
        self.assertIn("--force", err)
        self.assertEqual(self.baseline.read_bytes(), before)
        self.assertEqual(len(self.stub.requests), requests)

        code, _out, err = self.run_main("--record", "--force")
        self.assertEqual(code, 0, err)
        self.assertIn("wrote", err)
        replaced = json.loads(self.baseline.read_text(encoding="utf-8"))
        self.assertEqual(replaced["case_count"], record["case_count"])


class JudgeUnitTests(unittest.TestCase):
    def test_chat_completions_url(self) -> None:
        self.assertEqual(judge.chat_completions_url("http://host:1/v1"),
                         "http://host:1/v1/chat/completions")
        self.assertEqual(judge.chat_completions_url("http://host:1/v1/"),
                         "http://host:1/v1/chat/completions")
        self.assertEqual(judge.chat_completions_url(
            "http://host:1/v1/chat/completions"),
            "http://host:1/v1/chat/completions")

    def test_endpoint_host_has_no_path_or_query(self) -> None:
        self.assertEqual(judge.endpoint_host("http://host:1234/v1?key=x"), "host:1234")

    def test_parse_answer(self) -> None:
        self.assertEqual(judge.parse_answer(
            {"choices": [{"message": {"content": "  teams-cdp\n"}}]}), "teams-cdp")
        for payload in ({}, {"choices": []}, {"choices": [{}]},
                        {"choices": [{"message": {"content": ""}}]},
                        {"error": "bad"}, []):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    judge.parse_answer(payload)

    def test_build_body_carries_model_and_effort(self) -> None:
        body = judge.build_body("model-name", "high", "prompt")
        self.assertEqual(body["model"], "model-name")
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertEqual(body["messages"], [{"role": "user", "content": "prompt"}])


class BaselineGateTests(unittest.TestCase):
    def setUp(self) -> None:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(dir=ARTIFACTS))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cases = _cases()

    def record(self, **changes) -> dict:
        record = {
            "case_count": len(self.cases),
            "model": "stub-model",
            "effort": "low",
            "passed": len(self.cases),
            "total": len(self.cases),
            "judge_endpoint_host": "127.0.0.1:1",
            "generated_at": "2026-11-11T00:00:00Z",
            "per_case": [{"id": case["id"], "pick": case["must_pick"][0],
                          "passed": True} for case in self.cases],
        }
        record.update(changes)
        return record

    def errors(self, **changes) -> list[str]:
        return gate.baseline_errors(self.cases, self.record(**changes))

    def test_absent_record_is_allowed(self) -> None:
        self.assertIsNone(gate.load_baseline(self.tmp / "absent.json"))

    def test_valid_record_has_no_errors(self) -> None:
        self.assertEqual(self.errors(), [])

    def test_unknown_id(self) -> None:
        per_case = self.record()["per_case"]
        per_case[0] = {**per_case[0], "id": "not-a-case"}
        errors = self.errors(per_case=per_case)
        self.assertTrue(any("not in trigger-cases.json" in error for error in errors), errors)

    def test_duplicate_id(self) -> None:
        per_case = self.record()["per_case"]
        per_case[1] = {**per_case[1], "id": per_case[0]["id"]}
        errors = self.errors(per_case=per_case)
        self.assertTrue(any("duplicate id" in error for error in errors), errors)

    def test_passed_must_equal_the_sum(self) -> None:
        errors = self.errors(passed=len(self.cases) - 1)
        self.assertTrue(any("sum(per_case.passed)" in error for error in errors), errors)

    def test_case_count_must_match_the_suite(self) -> None:
        errors = self.errors(case_count=3)
        self.assertTrue(any("current case count" in error for error in errors), errors)

    def test_total_and_row_count_must_match_case_count(self) -> None:
        errors = self.errors(total=len(self.cases) - 1)
        self.assertTrue(any("total" in error and "case_count" in error for error in errors),
                        errors)
        per_case = self.record()["per_case"][:-1]
        errors = self.errors(per_case=per_case)
        self.assertTrue(any("per_case has" in error for error in errors), errors)

    def test_passed_rows_must_be_booleans(self) -> None:
        per_case = self.record()["per_case"]
        per_case[0] = {**per_case[0], "passed": 1}
        errors = self.errors(per_case=per_case)
        self.assertTrue(any("passed must be a boolean" in error for error in errors), errors)

    def test_missing_field(self) -> None:
        record = self.record()
        del record["model"]
        errors = gate.baseline_errors(self.cases, record)
        self.assertTrue(any("missing keys" in error for error in errors), errors)

    def test_unreadable_and_non_object_records(self) -> None:
        bad = self.tmp / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            gate.load_baseline(bad)
        self.assertIn("unreadable", str(caught.exception))
        array = self.tmp / "array.json"
        array.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            gate.load_baseline(array)
        self.assertIn("expected a JSON object", str(caught.exception))

    def test_main_reports_absent_consistent_and_broken_baselines(self) -> None:
        def run(path: Path) -> tuple[int, str, str]:
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(gate, "BASELINE", path), \
                    contextlib.redirect_stdout(stdout), \
                    contextlib.redirect_stderr(stderr):
                code = gate.main()
            return code, stdout.getvalue(), stderr.getvalue()

        code, out, err = run(self.tmp / "absent.json")
        self.assertEqual(code, 0, err)
        self.assertIn("no baseline recorded yet", out)

        valid = self.tmp / "valid.json"
        valid.write_text(json.dumps(self.record()), encoding="utf-8")
        code, out, err = run(valid)
        self.assertEqual(code, 0, err)
        self.assertIn("baseline consistent", out)

        broken = self.tmp / "broken.json"
        broken.write_text(json.dumps(self.record(passed=0)), encoding="utf-8")
        code, _out, err = run(broken)
        self.assertEqual(code, 1)
        self.assertIn("sum(per_case.passed)", err)


if __name__ == "__main__":
    unittest.main()
