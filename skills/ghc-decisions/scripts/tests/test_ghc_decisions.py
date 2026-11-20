#!/usr/bin/env python3
"""Offline tests for skills/ghc-decisions/scripts/ghc_decisions.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
SCRIPT = SKILL_DIR / "scripts" / "ghc_decisions.py"


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.requests.append({"path": self.path, "body": body})  # type: ignore[attr-defined]
        if self.path == "/v1/decisions":
            resp = {
                "model": body.get("model"),
                "answers": [
                    {"name": "resolution", "type": "choice", "choice": "resolved_root_cause", "confidence": 0.96, "probabilities": []}
                ],
                "usage": {"input_tokens": 120, "output_tokens": 0},
            }
        else:
            resp = {
                "model": body.get("model"),
                "choices": [{"message": {"content": json.dumps({"resolution": "symptom_patch"})}}],
                "usage": {"prompt_tokens": 110, "completion_tokens": 12},
            }
        raw = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args) -> None:  # noqa: A002
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class GhcDecisionsSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.requests = []  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _run(self, *args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        for k in list(env):
            if k.startswith(("GHC_DECISIONS_", "EVALS_")):
                env.pop(k)
        env["XDG_CONFIG_HOME"] = str(SKILL_DIR / ".nonexistent-xdg")
        if env_overrides:
            env.update(env_overrides)
        kwargs: dict = {}
        if os.name == "nt":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            kwargs["startupinfo"] = startup
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            **kwargs,
        )

    def test_list_presets_includes_nine_bundled_presets(self) -> None:
        proc = self._run("--list-presets")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data), 9)
        self.assertIn("claim-audit", data)
        self.assertIn("pr-feedback-triage", data)
        self.assertIn("spec-readiness", data)

    def test_if_configured_skips_cleanly_when_unconfigured(self) -> None:
        proc = self._run("--if-configured", "--preset", "pr-feedback-triage", "--state", '{"x":1}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("skipped"))

    def test_decisions_and_chat_completions_wire_modes(self) -> None:
        proc = self._run(
            "--preset", "pr-feedback-triage",
            "--base-url", self.base_url,
            "--model", "gpt-6-luna-decisions",
            "--api", "decisions",
            "--state", '{"finding":"item 1","candidate":"ok"}',
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["answers"]["resolution"]["value"], "resolved_root_cause")
        self.assertEqual(self.server.requests[-1]["path"], "/v1/decisions")  # type: ignore[attr-defined]

        proc_chat = self._run(
            "--preset", "pr-feedback-triage",
            "--base-url", self.base_url,
            "--model", "gemini-3.8-flash",
            "--api", "chat-completions",
            "--state", '{"finding":"item 1","candidate":"soft"}',
        )
        self.assertEqual(proc_chat.returncode, 0, proc_chat.stderr)
        data_chat = json.loads(proc_chat.stdout)
        self.assertEqual(data_chat["answers"]["resolution"]["value"], "symptom_patch")
        self.assertEqual(self.server.requests[-1]["path"], "/v1/chat/completions")  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
