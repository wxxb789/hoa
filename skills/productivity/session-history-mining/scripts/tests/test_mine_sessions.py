#!/usr/bin/env python3
"""Offline tests for skills/productivity/session-history-mining/scripts/mine_sessions.py."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
SCRIPT = SKILL_DIR / "scripts" / "mine_sessions.py"


class _StubDecisionsHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        inp = str(body.get("input", ""))
        questions = body.get("questions", [])
        is_pos = any(k in inp for k in ("anchor:pos_", "HOOK_ERROR", "CREATE_NO_WINDOW", "auto-merge", "NOVEL_TRAP"))
        is_novel = "NOVEL_TRAP" in inp

        answers = []
        for q in questions:
            qname = q["name"]
            qtype = q["type"]
            if qtype == "predicate":
                answers.append({"name": qname, "type": "predicate", "probability": 0.92 if is_pos else 0.04})
            elif qtype == "choice":
                choices = [c["value"] for c in q["choices"]]
                if is_novel and any("novel" in c for c in choices):
                    pick = next(c for c in choices if "novel" in c)
                elif is_pos:
                    pick = next(c for c in choices if "routine" not in c and "clean" not in c and "no_lesson" not in c)
                else:
                    pick = choices[0]
                probs = [
                    {"value": c, "probability": (0.88 if c == pick else round(0.12 / max(1, len(choices) - 1), 4))}
                    for c in choices
                ]
                answers.append(
                    {"name": qname, "type": "choice", "choice": pick, "confidence": 0.88, "probabilities": probs}
                )
            elif qtype == "score":
                lvls = q["levels"]
                hi = len(lvls) - 1
                sc_val = float(hi) * 0.92 if is_pos else 0.05
                probs = [
                    {"value": i, "label": l["label"], "probability": (0.92 if (is_pos and i == hi) or (not is_pos and i == 0) else 0.04)}
                    for i, l in enumerate(lvls)
                ]
                answers.append(
                    {"name": qname, "type": "score", "score": sc_val, "confidence": 0.90, "probabilities": probs}
                )

        raw = json.dumps({"model": body.get("model"), "answers": answers}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class SessionHistoryMiningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _Server(("127.0.0.1", 0), _StubDecisionsHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        for k in list(env):
            if k.startswith(("SESSION_HISTORY_MINING_", "GHC_DECISIONS_", "EVALS_")):
                env.pop(k)
        env["XDG_CONFIG_HOME"] = str(SKILL_DIR / ".nonexistent-xdg")
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            **kwargs,
        )

    def test_extract_judge_filter_residuals_and_anchor_gate_across_claude_and_omp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            claude_root = tmp / "claude_projects"
            omp_root = tmp / "omp_sessions"
            out_dir = tmp / "out"

            # 1. Allowed Claude session with hook error, secret token, and harness boilerplate
            c_allowed = claude_root / "Q--repos-cockpit"
            c_allowed.mkdir(parents=True)
            (c_allowed / "sess1.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "user", "message": {"role": "user", "content": "[Workflow harness — computed task] forged. The computed task text follows:\nFix NOVEL_TRAP with token ghp_1234567890abcdefghij1234567890"}}),
                        json.dumps({"type": "system", "subtype": "stop_hook_summary", "hookErrors": ["/bin/sh: 1: node: not found"]}),
                        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Diagnosed non-interactive hook PATH gap."}]}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            # 2. Denied work directory (must be physically skipped)
            c_denied = claude_root / "Q--src-corp"
            c_denied.mkdir(parents=True)
            (c_denied / "secret.jsonl").write_text(
                json.dumps({"type": "user", "message": {"content": "CORPORATE_DO_NOT_READ"}}) + "\n" * 3,
                encoding="utf-8",
            )

            # 3. Allowed OMP session with clean steps
            o_allowed = omp_root / "--Q--repos-hoa--"
            o_allowed.mkdir(parents=True)
            (o_allowed / "2026-11-20_omp1.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "session", "version": 3, "id": "omp1", "cwd": "Q:\\repos\\hoa"}),
                        json.dumps({"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "<system-reminder>Today</system-reminder>Run unit tests"}]}}),
                        json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "pytest -q"}}]}}),
                        json.dumps({"type": "message", "message": {"role": "toolResult", "toolCallId": "c1", "toolName": "bash", "isError": False, "content": [{"type": "text", "text": "5 passed"}]}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            ext = self._run(
                "extract",
                "--claude-root", str(claude_root),
                "--omp-root", str(omp_root),
                "--allow-regex", "(?i)repos-",
                "--deny-regex", "(?i)src-",
                "--out-dir", str(out_dir),
            )
            self.assertEqual(ext.returncode, 0, ext.stderr)
            manifest = json.loads(ext.stdout)
            self.assertEqual(manifest["skeleton_count"], 2)

            sk_text = (out_dir / "skeletons.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("CORPORATE_DO_NOT_READ", sk_text)
            self.assertNotIn("ghp_1234567890", sk_text)
            self.assertIn("<REDACTED_GH_TOKEN>", sk_text)
            self.assertNotIn("forged.", sk_text)

            # Judge L0
            j_l0 = self._run(
                "judge",
                "--stage", "l0",
                "--base-url", self.base_url,
                "--model", "stub-decisions",
                "--input", str(out_dir / "skeletons.jsonl"),
                "--output", str(out_dir / "l0-scored.jsonl"),
            )
            self.assertEqual(j_l0.returncode, 0, j_l0.stderr)

            # Filter spans (clean OMP session pruned, Claude hook-error session survives)
            flt = self._run(
                "filter-spans",
                "--l0", str(out_dir / "l0-scored.jsonl"),
                "--spans", str(out_dir / "spans.jsonl"),
                "--output", str(out_dir / "l1-candidates.jsonl"),
            )
            self.assertEqual(flt.returncode, 0, flt.stderr)
            flt_summary = json.loads(flt.stdout)
            self.assertEqual(flt_summary["l0_surviving_sessions"], 1)
            self.assertEqual(flt_summary["l0_pruned_sessions"], 1)

            # Judge L1 + extract OOD residuals
            j_l1 = self._run(
                "judge",
                "--stage", "l1-v1",
                "--base-url", self.base_url,
                "--model", "stub-decisions",
                "--input", str(out_dir / "l1-candidates.jsonl"),
                "--output", str(out_dir / "l1-scored.jsonl"),
            )
            self.assertEqual(j_l1.returncode, 0, j_l1.stderr)

            res = self._run(
                "residuals",
                "--stage", "l1-v1",
                "--scored", str(out_dir / "l1-scored.jsonl"),
                "--spans", str(out_dir / "l1-candidates.jsonl"),
                "--output", str(out_dir / "residuals.json"),
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            res_obj = json.loads((out_dir / "residuals.json").read_text(encoding="utf-8"))
            self.assertEqual(res_obj["novel_escape_top_choice_count"], 1)
            self.assertGreaterEqual(len(res_obj["ood_pool_top"]), 1)

            # Gold-anchor monotonicity check
            anc = self._run(
                "anchor-check",
                "--base-url", self.base_url,
                "--model", "stub-decisions",
            )
            self.assertEqual(anc.returncode, 0, anc.stderr)
            self.assertTrue(json.loads(anc.stdout)["passed"])

    def _extract_codex(self, out: Path, *args: str) -> tuple[dict, list[dict], list[dict]]:
        result = self._run("extract", "--out-dir", str(out), *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((out / "extract-manifest.json").read_text(encoding="utf-8"))
        skeletons = [json.loads(line) for line in (out / "skeletons.jsonl").read_text(encoding="utf-8").splitlines()]
        spans = [json.loads(line) for line in (out / "spans.jsonl").read_text(encoding="utf-8").splitlines()]
        return manifest, skeletons, spans

    def test_codex_rollout_prefers_completed_items_and_keeps_physical_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            root = Path(tmp_s)
            rollout = root / "sessions" / "2026" / "rollout-r1.jsonl"
            rollout.parent.mkdir(parents=True)
            records = [
                {"type": "session_meta", "payload": {"id": "r1", "cwd": r"\\?\Q:\src\Demo"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "duplicate raw user message"}]}},
                {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "Run checks"}]}}},
                None,  # interrupted write; the following locator still uses the physical line
                {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "CommandExecution", "command": ["check", "--fast"], "exit_code": 17, "aggregated_output": "assertion mismatch"}}},
                {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "content": [{"type": "Text", "text": "Fixed the assertion."}]}}},
            ]
            rollout.write_text("\n".join(json.dumps(rec) if rec else "{" for rec in records), encoding="utf-8")
            denied = root / "rollout-denied.jsonl"
            records[0] = {"type": "session_meta", "payload": {"id": "denied", "cwd": r"\\?\Q:\src\Demo\Excluded"}}
            denied.write_text("\n".join(json.dumps(rec) for rec in records), encoding="utf-8")

            manifest, (sk,), (span,) = self._extract_codex(
                root / "out", "--codex-root", str(root), "--allow-regex", r"^Q:\\src\\Demo",
                "--deny-regex", r"\\Excluded$",
            )
            self.assertEqual(sk["id"], "codex:Q-src-Demo:r1")
            self.assertEqual(sk["runtime"], "codex")
            self.assertEqual(sk["user_turns"], 1)
            self.assertEqual(sk["tool_errors"], 1)
            self.assertNotIn("duplicate raw", sk["text"])
            self.assertIn("[L3 USER] Run checks", sk["text"])
            self.assertIn("[L5 TOOL_ERR exec(check --fast)]", sk["text"])
            self.assertIn("[L6 ASST] Fixed the assertion.", sk["text"])
            self.assertEqual((span["path"], span["l_start"], span["l_end"], span["has_pivot"]), (str(rollout), 3, 6, True))
            self.assertEqual(manifest["coverage"]["codex"], [{
                "root": str(root), "status": "available", "included_threads": 1,
                "skipped_threads": 1, "jsonl_backed": 1, "sqlite_backed": 0,
            }])

    def test_codex_legacy_response_items_and_repeatable_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            root = Path(tmp_s)
            for name in ("first", "second"):
                archived = root / name / "archived_sessions"
                archived.mkdir(parents=True)
                records = [
                    {"type": "session_meta", "payload": {"id": name, "cwd": "/src/demo"}},
                    {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Run legacy checks"}]}},
                    {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "c1", "arguments": json.dumps({"cmd": "check"})}},
                    {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "Process exited with code 42\nfailed"}},
                    {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Diagnosed legacy failure."}]}},
                ]
                (archived / f"rollout-{name}.jsonl").write_text("\n".join(map(json.dumps, records)), encoding="utf-8")

            manifest, skeletons, spans = self._extract_codex(
                root / "out", "--codex-root", str(root / "first"), "--codex-root", str(root / "second"),
            )
            self.assertEqual({sk["id"] for sk in skeletons}, {"codex:src-demo:first", "codex:src-demo:second"})
            self.assertEqual([entry["jsonl_backed"] for entry in manifest["coverage"]["codex"]], [1, 1])
            self.assertEqual([(sp["l_start"], sp["l_end"]) for sp in spans], [(2, 5), (2, 5)])
            for sk in skeletons:
                self.assertEqual(sk["tool_errors"], 1)
                self.assertIn("[L4 TOOL_ERR exec(check)]", sk["text"])
                self.assertIn("[L5 ASST] Diagnosed legacy failure.", sk["text"])

    def test_codex_sqlite_reconstruction_role_filtering_and_read_only_stores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            root = Path(tmp_s) / "codex # history"
            root.mkdir()
            state = root / "state_5.sqlite"
            history = root / "thread_history_1.sqlite"
            rollout = root / "rollout-preferred.jsonl"
            rollout.write_text(json.dumps({"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "text": "Use the rollout."}}}), encoding="utf-8")
            cwd = r"\\?\Q:\src\Demo"
            with closing(sqlite3.connect(state)) as db, db:
                db.execute("CREATE TABLE threads (id TEXT, cwd TEXT, rollout_path TEXT, thread_source TEXT, agent_role TEXT)")
                db.executemany("INSERT INTO threads VALUES (?, ?, ?, ?, ?)", [
                    ("pruned", cwd, str(root / "rollout-gone.jsonl"), "user", None),
                    ("clean-review", cwd, None, "subagent", "review"),
                    ("failed-explorer", cwd, None, "subagent", "explorer"),
                    ("preferred", cwd, rollout.name, "subagent", "worker"),
                    ("excluded", cwd + r"\Excluded", None, "user", None),
                ])
            secret = "ghp_1234567890abcdefghij1234567890"
            items = [
                ("pruned", 1, "commandExecution", {"command": "check", "exitCode": 9, "aggregatedOutput": f"failed: {secret}"}),
                ("pruned", 0, "userMessage", {"content": [
                    {"type": "text", "text": "# AGENTS.md instructions for the repo\n\n<INSTRUCTIONS>INTERNAL_RULES</INSTRUCTIONS>"},
                    {"type": "text", "text": "<environment_context>INTERNAL_ENV</environment_context>\nCheck private.example"},
                ]}),
                ("clean-review", 0, "agentMessage", {"text": "Clean internal review"}),
                ("failed-explorer", 0, "mcpToolCall", {"server": "mock", "tool": "inspect", "status": "completed", "result": {"structuredContent": {"ok": False}}}),
                ("preferred", 0, "agentMessage", {"text": "Stale database copy"}),
                ("excluded", 0, "agentMessage", {"text": "Out of scope"}),
            ]
            with closing(sqlite3.connect(history)) as db, db:
                db.execute("CREATE TABLE thread_items (thread_id TEXT, rollout_ordinal INTEGER, item_type TEXT, item_json TEXT)")
                db.executemany("INSERT INTO thread_items VALUES (?, ?, ?, ?)", [(tid, ordinal, kind, json.dumps(item)) for tid, ordinal, kind, item in items])
            store_bytes = {p.name: p.read_bytes() for p in (state, history, rollout)}

            args = ("--codex-root", str(root), "--allow-regex", r"^Q:\\src\\Demo", "--deny-regex", r"\\Excluded$", "--redact-regex", r"private\.example")
            manifest, skeletons, spans = self._extract_codex(Path(tmp_s) / "out", *args)
            by_tid = {sk["id"].rsplit(":", 1)[1]: sk for sk in skeletons}
            self.assertEqual(set(by_tid), {"pruned", "failed-explorer", "preferred"})
            self.assertEqual(by_tid["preferred"]["path"], str(rollout))
            self.assertIn("Use the rollout.", by_tid["preferred"]["text"])
            self.assertEqual(by_tid["failed-explorer"]["tool_errors"], 1)
            self.assertTrue(next(sp for sp in spans if sp["session_id"].endswith(":failed-explorer"))["has_pivot"])
            sk = by_tid["pruned"]
            span = next(sp for sp in spans if sp["session_id"] == sk["id"])
            self.assertEqual((span["path"], span["l_start"], span["l_end"], span["has_pivot"]), (f"{history}#thread=pruned", 0, 1, True))
            for artifact in (sk, span):
                self.assertIn("[L0 USER] Check <REDACTED_SCOPE>", artifact["text"])
                self.assertIn("[L1 TOOL_ERR exec(check)]", artifact["text"])
                self.assertIn("<REDACTED_GH_TOKEN>", artifact["text"])
                for forbidden in (secret, "INTERNAL_RULES", "INTERNAL_ENV", "private.example"):
                    self.assertNotIn(forbidden, artifact["text"])
            self.assertEqual(manifest["coverage"]["codex"], [{
                "root": str(root), "status": "available", "included_threads": 3,
                "skipped_threads": 2, "jsonl_backed": 1, "sqlite_backed": 2,
            }])

            # A rollback-journal exclusive lock blocks reads through mode=ro.
            with closing(sqlite3.connect(state)) as lock:
                lock.execute("BEGIN EXCLUSIVE")
                _, all_skeletons, _ = self._extract_codex(Path(tmp_s) / "all", *args, "--include-codex-subagents")
            self.assertEqual({sk["id"].rsplit(":", 1)[1] for sk in all_skeletons}, {*by_tid, "clean-review"})
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, store_bytes)

    def test_codex_batches_unindexed_history_and_leaves_no_wal_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root = tmp / "store"
            root.mkdir()
            state = root / "state_5.sqlite"
            history = root / "thread_history_1.sqlite"
            ids = [f"thread-{i:03d}" for i in range(503)]
            with closing(sqlite3.connect(state)) as db, db:
                db.execute("PRAGMA journal_mode=WAL").fetchone()
                db.execute("CREATE TABLE threads (id TEXT, cwd TEXT, rollout_path TEXT, thread_source TEXT, agent_role TEXT)")
                db.executemany("INSERT INTO threads (id, cwd) VALUES (?, ?)", [(tid, "/repo") for tid in ids])
            with closing(sqlite3.connect(history)) as db, db:
                db.execute("PRAGMA journal_mode=WAL").fetchone()
                db.execute("CREATE TABLE thread_items (thread_id TEXT, rollout_ordinal INTEGER, item_type TEXT, item_json TEXT)")
                db.executemany("INSERT INTO thread_items VALUES (?, 7, 'agentMessage', ?)", [
                    (tid, json.dumps({"text": tid})) for tid in ids[:-1]
                ])

            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(set(before), {state.name, history.name})
            manifest, skeletons, spans = self._extract_codex(tmp / "out", "--codex-root", str(root))
            coverage, = manifest["coverage"]["codex"]
            self.assertEqual((coverage["sqlite_backed"], coverage["skipped_threads"]), (502, 1))
            self.assertEqual({sk["id"] for sk in skeletons}, {f"codex:repo:{tid}" for tid in ids[:-1]})
            self.assertEqual({(sp["l_start"], sp["l_end"]) for sp in spans}, {(7, 7)})
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)


if __name__ == "__main__":
    unittest.main()
