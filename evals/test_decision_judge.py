#!/usr/bin/env python3
"""Offline tests for decision_judge.py and decision_benchmark.py."""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parent.parent
JUDGE = ROOT / "evals" / "decision_judge.py"
BENCHMARK = ROOT / "evals" / "decision_benchmark.py"
ARTIFACTS = ROOT / ".tmp-artifacts" / "decision-judge-tests"

from evals import decision_benchmark as bench  # noqa: E402
from evals import decision_judge as dj  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.stub.requests.append({"path": self.path, "body": body})
        status, payload = self.server.stub.reply(self.path, body)
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args) -> None:  # noqa: A002
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DecisionStub:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.server = _Server(("127.0.0.1", 0), _Handler)
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

    def reply(self, path: str, body: dict) -> tuple[int, dict]:
        if path.endswith("/decisions"):
            answers = []
            for q in body["questions"]:
                qtype = q["type"]
                if qtype == "predicate":
                    answers.append({"type": "predicate", "name": q["name"], "probability": 0.9})
                elif qtype == "choice":
                    first = q["choices"][0]["value"]
                    answers.append({
                        "type": "choice",
                        "name": q["name"],
                        "choice": first,
                        "confidence": 0.85,
                        "probabilities": [{"value": c["value"], "probability": 1.0 if c["value"] == first else 0.0} for c in q["choices"]],
                    })
                elif qtype == "score":
                    answers.append({
                        "type": "score",
                        "name": q["name"],
                        "score": 0.0,
                        "confidence": 0.95,
                        "probabilities": [{"value": i, "label": lvl["label"], "probability": 1.0 if i == 0 else 0.0} for i, lvl in enumerate(q["levels"])],
                    })
            return 200, {
                "model": body["model"],
                "answers": answers,
                "usage": {"input_tokens": 120, "output_tokens": 0},
            }
        return 200, {
            "model": body["model"],
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "tier": "safe_routine",
                        "out_of_scope": False,
                        "blast_radius": 0,
                    })
                }
            }],
            "usage": {"prompt_tokens": 150, "completion_tokens": 25},
        }


class DecisionJudgeTests(unittest.TestCase):
    def setUp(self) -> None:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(dir=ARTIFACTS))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.stub = DecisionStub()
        self.addCleanup(self.stub.close)

    def test_benchmark_cases_and_rubrics_validate_offline(self) -> None:
        rubrics = dj.load_rubrics()
        cases = bench.load_benchmark_cases()
        self.assertEqual(bench.validate_cases(cases, rubrics), [])
        self.assertGreaterEqual(len(cases), 16)

    def test_cli_decisions_and_chat_completions_modes(self) -> None:
        env = {
            **os.environ,
            "HOME": str(self.tmp),
            "XDG_CONFIG_HOME": str(self.tmp / "xdg"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        res_dec = subprocess.run(
            [
                sys.executable,
                str(JUDGE),
                "--preset",
                "tool-risk",
                "--state",
                '{"tool":"bash","arguments":"git status"}',
                "--base-url",
                self.stub.base_url,
                "--model",
                "gpt-6-luna-decisions",
                "--api",
                "decisions",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(res_dec.returncode, 0, res_dec.stderr)
        data_dec = json.loads(res_dec.stdout)
        self.assertEqual(data_dec["api"], "decisions")
        self.assertEqual(data_dec["answers"]["tier"]["value"], "safe_routine")
        self.assertEqual(data_dec["answers"]["out_of_scope"]["value"], True)
        self.assertEqual(self.stub.requests[-1]["path"], "/v1/decisions")

        res_chat = subprocess.run(
            [
                sys.executable,
                str(JUDGE),
                "--preset",
                "tool-risk",
                "--state",
                '{"tool":"bash","arguments":"git status"}',
                "--base-url",
                self.stub.base_url,
                "--model",
                "gpt-6-luna",
                "--api",
                "chat-completions",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(res_chat.returncode, 0, res_chat.stderr)
        data_chat = json.loads(res_chat.stdout)
        self.assertEqual(data_chat["api"], "chat-completions")
        self.assertEqual(data_chat["answers"]["tier"]["value"], "safe_routine")
        self.assertEqual(data_chat["answers"]["out_of_scope"]["value"], False)
        self.assertEqual(self.stub.requests[-1]["path"], "/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
