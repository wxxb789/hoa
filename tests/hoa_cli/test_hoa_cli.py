import io
import json
import os
import sqlite3
import threading
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hoa_cli.cli import main
from hoa_cli.config import ConfigError, resolve_endpoint
from hoa_cli.decisions.client import parse_decisions_response


def stage(marker="baseline"):
    return {"mech_question": "axis", "score_question": "strength", "routine_labels": ["routine"], "novel_label": "novel",
            "questions": [{"name": "anomaly_probe", "type": "predicate", "instructions": marker},
                          {"name": "axis", "type": "choice", "instructions": "Classify the mechanism.",
                           "choices": [{"value": option} for option in ("routine", "workflow", "environment", "novel")]},
                          {"name": "strength", "type": "score", "instructions": "Rate the evidence.",
                           "levels": [{"label": label} for label in ("none", "low", "medium", "high")]}]}


class WireHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, request, self.headers.get("Authorization")))
        if self.path.endswith("/chat/completions"):
            reply = {"choices": [{"message": {"content": '```json\n{"anomaly_probe":true,"axis":"workflow","strength":"high"}\n```'}}]}
        else:
            text = request["input"]
            marker = request["questions"][0]["instructions"]
            positive = "positive" in text and not (marker == "baseline" and "miss" in text)
            if "transport-failure" in text:
                self._send(400, {"error": {"message": text}})
                return
            if "refuse" in text or (marker == "reject" and positive):
                reply = {"answers": [{"type": "refusal"} for _ in request["questions"]]}
            else:
                choice = "workflow" if positive else "routine"
                probabilities = {"workflow": 0.48, "environment": 0.44, "novel": 0.08} if positive else {choice: 1}
                score = (2 if "medium" in text else 3) if positive else 0
                reply = {"model": "fixture", "usage": {"prompt_tokens": 9, "completion_tokens": 3}, "answers": [
                    {"name": "strength", "type": "score", "score": score,
                     "probabilities": [{"label": ("none", "low", "medium", "high")[score], "probability": 1}]},
                    {"name": "axis", "type": "choice", "choice": choice,
                     "probabilities": [{"value": label, "probability": prob} for label, prob in probabilities.items()]},
                    {"name": "anomaly_probe", "type": "predicate", "probability": 0.95 if positive else 0.05},
                ]}
        self._send(200, reply)

    def _send(self, status, reply):
        body = json.dumps(reply).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HoaCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = cls.enterClassContext(ThreadingHTTPServer(("127.0.0.1", 0), WireHandler))
        cls.server.requests = []
        thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        cls.addClassCleanup(lambda: (cls.server.shutdown(), thread.join()))
        cls.endpoint = ("--base-url", f"http://127.0.0.1:{cls.server.server_port}/v1", "--model", "fixture")

    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        prefixes = ("RUBRIC_JUDGE_", "RUBRIC_TUNE_", "HOA_PRACTICE_MINE_",
                    "GHC_DECISIONS_", "SESSION_HISTORY_MINING_", "RUBRIC_HILLCLIMB_", "EVALS_")
        env = {key: value for key, value in os.environ.items() if not key.startswith(prefixes)}
        self.enterContext(patch.dict(os.environ, {**env, "XDG_CONFIG_HOME": str(self.root / "config")}, clear=True))
        self.server.requests.clear()

    def write(self, name, obj, *, lines=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "".join(json.dumps(row) + "\n" for row in obj) if lines else json.dumps(obj)
        path.write_text(content, encoding="utf-8")
        return path

    def invoke(self, *args, status=0, raw=False):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main([str(arg) for arg in args])
        self.assertEqual(rc, status, err.getvalue())
        return (out.getvalue(), err.getvalue()) if raw else json.loads(out.getvalue())

    def rows(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_decide_bundled_presets_config_skip_and_wire_payload(self):
        presets = self.invoke("decide", "--list-presets")
        self.assertEqual(len(presets), 9)
        self.assertTrue({"claim-audit", "pr-feedback-triage", "spec-readiness"}.issubset(presets))
        rubrics = self.write("presets.json", {"presets": {"evidence": stage()}})
        state = self.write("state.json", {"note": "positive café"})
        args = ("decide", "--rubrics-file", rubrics, "--preset", "evidence")
        self.assertTrue(self.invoke(*args, "--state-file", state, "--if-configured")["skipped"])
        with patch.dict(os.environ, {"RUBRIC_JUDGE_API_KEY": "fixture-token"}):
            result = self.invoke(*args, "--state-file", state, *self.endpoint)
        route, posted, token = self.server.requests[-1]
        self.assertEqual((route, json.loads(posted["input"]), token), ("/v1/decisions", {"note": "positive café"}, "Bearer fixture-token"))
        self.assertEqual(result["usage"], {"input_tokens": 9, "output_tokens": 3})
        self.assertEqual(result["answers"]["strength"]["probabilities"], {"high": 1.0})
        self.assertEqual(result["answers"]["strength"]["top_label"], "high")
        chat = self.invoke(*args, "--state", "positive café", *self.endpoint, "--api", "chat-completions")
        route, posted, _ = self.server.requests[-1]
        self.assertEqual(route, "/v1/chat/completions")
        self.assertIn("positive café", posted["messages"][0]["content"])
        self.assertEqual(chat["answers"]["axis"]["value"], "workflow")
        self.assertEqual(chat["answers"]["strength"]["value"], 3)
        questions = stage()["questions"]
        with self.assertRaisesRegex(ValueError, "expected 3 answers, got 0"):
            parse_decisions_response({"answers": []}, questions)
        with self.assertRaisesRegex(ValueError, "error payload"):
            parse_decisions_response({"error": {"message": "bad"}, "answers": []}, questions)

    def test_endpoint_config_precedence_and_flat_yaml(self):
        config = self.root / "custom" / "config.yaml"
        config.parent.mkdir()
        config.write_text('base_url: "https://example.test/v1" # endpoint\nmodel: \'two\'\'words\'\nworkers: 7\n', encoding="utf-8")
        env = {"CUSTOM_BASE_URL": "https://override.test/v1", "GHC_DECISIONS_MODEL": "fallback", "EVALS_EFFORT": "medium"}
        endpoint = resolve_endpoint("custom", flag_workers=2, env=env, root=self.root)
        self.assertEqual((endpoint.base_url, endpoint.model, endpoint.workers, endpoint.effort),
                         ("https://override.test/v1", "two'words", 2, "medium"))
        config.write_text("model: a\nmodel: b\n", encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "duplicate key"):
            resolve_endpoint("custom", env=env, root=self.root)

    def test_history_claude_omp_codex_rollouts_and_raw_show(self):
        secret = "private-marker"
        claude = [{"type": "user", "message": {"content": f"Claude pivot {secret}"}},
                  {"type": "assistant", "message": {"content": [{"type": "text", "text": "Assistant note"}]}},
                  {"type": "system", "hookErrors": ["hook failed"]}]
        self.write("claude/project/main.jsonl", claude, lines=True)
        self.write("claude/project/sub/journal.jsonl", [{"status": "failed", "agentId": "one"}] * 2, lines=True)
        self.write("claude/project/sub/agent-one.jsonl", claude[:1], lines=True)
        self.write("omp/project/s.jsonl", [{"type": "session", "parentSession": "parent"},
                   *({"type": "message", "message": {"role": role, "content": [{"type": "text", "text": text}]}}
                     for role, text in (("user", "OMP pivot"), ("toolResult", "Exit code 2")))], lines=True)
        self.write("codex/logs/rollout-one.jsonl", [{"type": "session_meta", "payload": {"id": "one", "cwd": "project"}},
                   {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "text": "Codex pivot"}}},
                   {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                       "type": "CommandExecution", "command": "fixture-tool", "aggregatedOutput": "retained output"}}}], lines=True)
        out = self.root / "extract"
        manifest = self.invoke("history", "extract", "--claude-root", self.root / "claude", "--omp-root", self.root / "omp",
                               "--codex-root", self.root / "codex", "--out-dir", out, "--redact-regex", secret,
                               "--high-signal-regex", "fixture-tool")
        self.assertEqual(manifest["skeleton_count"], 4)
        skeletons = {row["runtime"]: row for row in self.rows(out / "skeletons.jsonl")}
        self.assertNotIn(secret, skeletons["claude-code"]["text"])
        self.assertEqual(skeletons["claude-code"]["hook_errors"], 1)
        self.assertIn("retained output", skeletons["codex"]["text"])
        self.assertEqual((skeletons["omp"]["parent_session"], skeletons["omp"]["tool_errors"]), ("parent", 1))
        self.assertIn("Codex pivot", skeletons["codex"]["text"])
        raw, _ = self.invoke("history", "show", "--spans", out / "spans.jsonl", "claude:project:main@L1-3", raw=True)
        self.assertIn(f"Claude pivot {secret}", raw)
        self.assertIn("L3\t", raw)

    def test_codex_sqlite_wal_read_only_rollout_preference_role_and_since(self):
        codex = self.root / "codex"
        self.write("codex/rollout-present.jsonl", [{"type": "response_item", "payload": {"type": "message", "role": "user", "content": "preferred rollout"}}], lines=True)
        state, history = (codex / name for name in ("state_5.sqlite", "thread_history_1.sqlite"))
        with closing(sqlite3.connect(state)) as conn:
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
            conn.execute("CREATE TABLE threads(id TEXT, cwd TEXT, rollout_path TEXT, thread_source TEXT, agent_role TEXT, updated_at INT)")
            conn.executemany("INSERT INTO threads VALUES (?, 'project', ?, ?, ?, ?)", [
                ("db", None, "user", None, 2_000_000_000), ("roll", "rollout-present.jsonl", "user", None, 2_000_000_000),
                ("skip", None, "subagent", "planner", 2_000_000_000), ("old", None, "user", None, 1)])
            conn.commit()
        with closing(sqlite3.connect(history)) as conn:
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
            conn.execute("CREATE TABLE thread_items(thread_id TEXT, rollout_ordinal INT, item_type TEXT, item_json TEXT)")
            conn.executemany("INSERT INTO thread_items VALUES (?, ?, ?, ?)", [
                (tid, ordinal, kind, json.dumps({"text": text})) for tid, ordinal, kind, text in (
                    ("db", 0, "UserMessage", "SQLite pivot"), ("db", 42, "AgentMessage", "sparse evidence"),
                    ("roll", 7, "UserMessage", "stale copy"), ("skip", 7, "UserMessage", "clean planner"),
                    ("old", 7, "UserMessage", "old work"))])
            conn.commit()
        sidecars = [Path(f"{db}-{ext}") for db in (state, history) for ext in ("wal", "shm")]
        out = self.root / "extract"
        call = ("history", "extract", "--codex-root", codex, "--since", "2025-01-01", "--out-dir", out)
        self.assertFalse(any(path.exists() for path in sidecars))
        text, warnings = self.invoke(*call, raw=True)
        coverage = json.loads(text)["coverage"]["codex"][0]
        self.assertEqual((coverage["sqlite_backed"], coverage["jsonl_backed"], coverage["skipped_threads"]), (1, 1, 1))
        self.assertIn("immutable", warnings)
        self.assertFalse(any(path.exists() for path in sidecars))
        self.assertIn("preferred rollout", (out / "skeletons.jsonl").read_text(encoding="utf-8"))
        with closing(sqlite3.connect(history)) as writer:
            writer.execute("INSERT INTO thread_items VALUES ('db', 59, 'AgentMessage', '{\"text\":\"live WAL tail\"}')")
            writer.commit()
            self.invoke(*call)
            raw, _ = self.invoke("history", "show", "--spans", out / "spans.jsonl", "codex:project:db@L0-59", raw=True)
            self.assertIn("ordinal0-59", raw)
            self.assertIn("42\tAgentMessage\t", raw)
            self.assertIn("live WAL tail", raw)

    def test_mine_judge_filter_join_residuals_and_novelty(self):
        custom = self.write("rubrics.json", {"stages": {"first": stage(), "next": stage("candidate")}})
        spans = self.write("spans.jsonl", [{"id": name, "session_id": name, "has_pivot": True, "text": text}
                           for name, text in (("strong", "positive origin"), ("medium", "positive medium"),
                                              ("refusal", "refuse"), ("clean", "routine"))], lines=True)
        scored, selected, report = (self.root / name for name in ("scored.jsonl", "selected.jsonl", "residuals.json"))
        self.invoke("mine", "judge", "--stage", "first", "--rubrics", custom, "--input", spans, "--output", scored, *self.endpoint)
        self.assertNotIn("text", self.rows(scored)[0])
        common = ("--stage", "first", "--rubrics", custom, "--scored", scored, "--spans", spans)
        self.invoke("mine", "select-survivors", *common, "--output", selected)
        self.assertEqual([(row["id"], row["text"]) for row in self.rows(selected)], [("strong", "positive origin")])
        self.invoke("mine", "residuals", *common, "--output", report)
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["confusion_pairs"], [{"labels": ["environment", "workflow"], "count": 2}])
        self.assertEqual(data["refusals"][0]["reason"], "model_refusal")
        self.assertEqual([row["id"] for row in data["strong_positives_top"]], ["strong"])
        baseline = self.write("baseline.json", "current rules")
        self.invoke("mine", "judge", "--stage", "next", "--rubrics", custom, "--input", selected,
                    "--baseline-file", baseline, "--output", report, *self.endpoint)
        self.assertEqual(self.server.requests[-1][1]["input"], '"current rules"\n\n---\npositive origin')
        l0 = self.write("l0.jsonl", [*self.rows(scored), {"id": "failure", "judgment": {"ok": False, "error": "timeout"}}], lines=True)
        with spans.open("a", encoding="utf-8") as dest:
            dest.write(json.dumps({"id": "failure", "session_id": "failure", "has_pivot": True, "text": "retry"}) + "\n")
        filtered = self.invoke("mine", "filter-spans", "--l0", l0, "--spans", spans, "--output", selected,
                               "--stage", "first", "--rubrics", custom)
        self.assertEqual((filtered["l0_refusal_sessions"], filtered["l0_pruned_sessions"]), (1, 1))
        self.assertEqual({row["id"] for row in self.rows(selected)}, {"strong", "medium", "refusal", "failure"})

    def test_anchor_check_four_levels_and_refusal(self):
        anchors = [{"id": "keep", "expected": True, "text": "positive medium"}, {"id": "drop", "expected": False, "text": "routine"}]
        path = self.write("locked.json", {"anchors": anchors, "stages": {"base": stage(), "good": stage("candidate"), "bad": stage("reject")}})
        common = ("mine", "anchor-check", "--rubrics", path, "--baseline-stage", "base", *self.endpoint)
        passed = self.invoke(*common, "--candidate-stage", "good")
        self.assertAlmostEqual(passed["candidate"]["worst_case_gap"], 0.8)
        rejected = self.invoke(*common, "--candidate-stage", "bad", status=1)
        self.assertFalse(rejected["passed"])
        self.assertEqual(rejected["candidate"]["refused_anchors"], ["keep"])
        self.assertIsNone(rejected["candidate"]["worst_case_gap"])

    def test_hillclimb_split_eval_and_blind_failure(self):
        dataset = self.write("data.jsonl", [{"id": ident, "text": text, "expected": want} for ident, text, want in (
            ("p1", "positive", True), ("p2", "positive miss HOLDOUT_MARKER", True), ("n1", "routine", False), ("n2", "routine again", False))], lines=True)
        train, holdout = (self.root / filename for filename in ("train.jsonl", "holdout.jsonl"))
        self.assertEqual(self.invoke("hillclimb", "split", "--input", dataset, "--train-out", train, "--holdout-out", holdout),
                         {"train_count": 2, "holdout_count": 2})
        self.assertEqual({row["expected"] for row in self.rows(holdout)}, {True, False})
        self.assertTrue({row["id"] for row in self.rows(train)}.isdisjoint(row["id"] for row in self.rows(holdout)))
        rubric = self.write("rubric.json", stage())
        args = ("--rubric", rubric, "--dataset", dataset, *self.endpoint)
        training = self.invoke("hillclimb", "eval", *args, "--max-errors", "1")
        self.assertEqual(training["recall"], 0.5)
        self.assertEqual(len(training["error_samples"]), 1)
        self.assertIn("HOLDOUT_MARKER", training["error_samples"][0]["text"])
        blind = self.invoke("hillclimb", "eval-holdout", *args)
        self.assertEqual(blind, {key: value for key, value in training.items() if key != "error_samples"})
        gated = self.invoke("hillclimb", "eval", *args, "--anchors", dataset, status=1)
        self.assertFalse(gated["anchors"]["passed"])
        self.assertEqual(self.invoke("hillclimb", "eval-holdout", *args, "--anchors", dataset, status=1), blind)
        failed = self.write("failed.jsonl", [{"id": "p", "text": "transport-failure HOLDOUT_MARKER", "expected": True}], lines=True)
        out, err = self.invoke("hillclimb", "eval-holdout", "--rubric", rubric, "--dataset", failed, *self.endpoint, status=2, raw=True)
        self.assertFalse(out)
        self.assertIn("no holdout diagnostics disclosed", err)
        self.assertNotIn("HOLDOUT_MARKER", err)

    def test_hillclimb_step_sample_and_chat_label_fallback(self):
        base, cand = self.write("base.json", stage()), self.write("candidate.json", stage("candidate"))
        dataset = self.write("train.jsonl", [{"id": "p", "text": "positive miss", "expected": True},
                                             {"id": "n", "text": "routine", "expected": False}], lines=True)
        pair = ("--baseline", base, "--candidate", cand, *self.endpoint)
        ledger, best = self.root / "rubric-ledger.jsonl", self.root / "best.json"
        args = ("--train", dataset, "--ledger", ledger, "--best-out", best)
        accepted = self.invoke("hillclimb", "step", *pair, *args)
        self.assertTrue(accepted["accepted"])
        self.assertEqual(best.read_bytes(), cand.read_bytes())
        reverted = self.invoke("hillclimb", "step", "--baseline", cand, "--candidate", base, *self.endpoint, *args)
        self.assertFalse(reverted["accepted"])
        self.assertEqual(best.read_bytes(), cand.read_bytes())
        self.assertEqual([row["iter"] for row in self.rows(ledger)], [1, 2])
        pool = self.write("pool.jsonl", [{"id": "u", "text": "positive miss"}], lines=True)
        sampling = self.invoke("hillclimb", "sample", *pair, "--pool", pool)
        self.assertEqual([sampling[key][0]["id"] for key in ("disagreement_pool", "confusion_pool", "ood_pool")], ["u"] * 3)
        self.assertNotIn("expected", sampling["disagreement_pool"][0])
        chat = self.invoke("hillclimb", "eval", "--rubric", cand, "--dataset", dataset, "--api", "chat-completions",
                           "--effort", "medium", *self.endpoint)
        self.assertEqual((chat["recall"], chat["false_positives"]), (1.0, 1))
        self.assertEqual((self.server.requests[-1][0], self.server.requests[-1][1]["reasoning_effort"]),
                         ("/v1/chat/completions", "medium"))

    def test_subcommand_help(self):
        groups = {"decide": (), "history": ("extract", "show"),
                  "mine": ("judge", "filter-spans", "select-survivors", "residuals", "disagreements", "anchor-check", "baseline"),
                  "hillclimb": ("split", "eval", "eval-holdout", "step", "sample")}
        for args in [(), *((group,) for group in groups), *((group, leaf) for group, leaves in groups.items() for leaf in leaves)]:
            with self.subTest(args=args), redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as exit_code:
                main([*args, "--help"])
            self.assertEqual(exit_code.exception.code, 0)
            self.assertIn("usage: hoa", out.getvalue())

    def test_extract_memories_dedup_readable_show_and_strict_filter(self):
        secret = "secret-token-xyz"
        omp_lines = [
            {"type": "session", "parentSession": "root"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Fix the build"}]}},
            {"type": "message", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "long internal reasoning"},
                {"type": "text", "text": "Found root cause."},
            ]}},
            {"type": "message", "message": {"role": "toolResult", "toolName": "bash", "isError": True,
                                            "content": [{"type": "text", "text": "exit 1"}]}},
        ]
        self.write("omp/proj/branch-a.jsonl", omp_lines, lines=True)
        self.write("omp/proj/branch-b.jsonl", omp_lines, lines=True)
        mem_dir = self.root / "claude" / "proj" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("# Index\n", encoding="utf-8")
        (mem_dir / "lesson.md").write_text(f"Rule with {secret}", encoding="utf-8")
        out = self.root / "out"
        manifest = self.invoke(
            "history", "extract",
            "--claude-root", self.root / "claude",
            "--omp-root", self.root / "omp",
            "--include-memories",
            "--redact-regex", secret,
            "--out-dir", out,
        )
        self.assertEqual(manifest["skeleton_count"], 2)
        self.assertEqual(manifest["span_count"], 1)
        self.assertEqual(manifest["deduped_span_count"], 1)
        self.assertEqual(manifest["memory_count"], 1)
        mems = self.rows(out / "memories.jsonl")
        self.assertEqual(mems[0]["id"], "claude-memory:proj:lesson.md")
        self.assertNotIn(secret, mems[0]["text"])
        span_id = self.rows(out / "spans.jsonl")[0]["id"]
        readable, _ = self.invoke("history", "show", "--spans", out / "spans.jsonl", "--format", "readable", span_id, raw=True)
        self.assertIn("[USER] Fix the build", readable)
        self.assertIn("[ASSISTANT] Found root cause.", readable)
        self.assertIn("[TOOL_ERR bash] exit 1", readable)
        self.assertNotIn("long internal reasoning", readable)
        l0 = self.write("l0.jsonl", [{
            "id": self.rows(out / "spans.jsonl")[0]["session_id"],
            "hook_errors": 0,
            "judgment": {"ok": True, "answers": {
                "anomaly_probe": {"type": "predicate", "probability": 0.6},
                "user_correction_probe": {"type": "predicate", "probability": 0.05},
                "durability": {"type": "score", "score": 0.1},
                "primary_axis": {"type": "choice", "choice": "routine_clean", "probabilities": {"routine_clean": 0.9}},
            }},
        }], lines=True)
        loose = self.invoke("mine", "filter-spans", "--l0", l0, "--spans", out / "spans.jsonl", "--output", out / "loose.jsonl")
        strict = self.invoke("mine", "filter-spans", "--strict", "--l0", l0, "--spans", out / "spans.jsonl", "--output", out / "strict.jsonl")
        self.assertEqual(loose["l0_surviving_sessions"], 1)
        self.assertEqual(strict["l0_surviving_sessions"], 0)

    def test_cursor_min_lines_codex_memories_and_baseline(self):
        import sqlite3
        from contextlib import closing
        codex_root = self.root / "codex"
        codex_root.mkdir()
        with closing(sqlite3.connect(codex_root / "state_5.sqlite")) as sdb:
            sdb.execute("CREATE TABLE threads (id TEXT, cwd TEXT, rollout_path TEXT, thread_source TEXT, agent_role TEXT, updated_at REAL)")
            sdb.execute("INSERT INTO threads VALUES ('t1', '/repos/demo', '', 'cli', 'default', 1700000000)")
            sdb.execute("INSERT INTO threads VALUES ('t2', '/work/secret', '', 'cli', 'default', 1700000000)")
            sdb.commit()
        with closing(sqlite3.connect(codex_root / "thread_history_1.sqlite")) as hdb:
            hdb.execute("CREATE TABLE thread_items (thread_id TEXT, rollout_ordinal INT, item_type TEXT, item_json TEXT)")
            hdb.commit()
        with closing(sqlite3.connect(codex_root / "memories_1.sqlite")) as mdb:
            mdb.execute("CREATE TABLE stage1_outputs (thread_id TEXT, source_updated_at REAL, rollout_summary TEXT, raw_memory TEXT)")
            mdb.execute("INSERT INTO stage1_outputs VALUES ('t1', 1700000000, 'Allowlisted codex lesson', '')")
            mdb.execute("INSERT INTO stage1_outputs VALUES ('t2', 1700000000, 'Work secret must skip', '')")
            mdb.commit()
        cursor = self.root / "cursor.txt"
        out1 = self.root / "out1"
        m1 = self.invoke(
            "history", "extract",
            "--codex-root", codex_root,
            "--include-memories",
            "--cursor-file", cursor,
            "--allow-regex", "repos",
            "--deny-regex", "work",
            "--out-dir", out1,
        )
        self.assertEqual(m1["memory_count"], 1)
        self.assertTrue(cursor.is_file())
        mems = self.rows(out1 / "memories.jsonl")
        self.assertEqual(mems[0]["id"], "codex-memory:repos-demo:t1")
        self.assertIn("Allowlisted codex lesson", mems[0]["text"])
        # Second run with cursor skips older memories
        out2 = self.root / "out2"
        m2 = self.invoke(
            "history", "extract",
            "--codex-root", codex_root,
            "--include-memories",
            "--cursor-file", cursor,
            "--allow-regex", "repos",
            "--out-dir", out2,
        )
        self.assertEqual(m2["memory_count"], 0)
        # Baseline builder
        repo = self.root / "demo-repo"
        (repo / "docs").mkdir(parents=True)
        (repo / "AGENTS.md").write_text("# Demo Rules\nAlways test.\n", encoding="utf-8")
        (repo / "docs" / "guide.md").write_text("# Guide\nUse LF.\n", encoding="utf-8")
        base_out = self.root / "baseline.md"
        rep = self.invoke("mine", "baseline", "--repo", repo, "--output", base_out)
        self.assertEqual(rep["file_count"], 2)
        text = base_out.read_text(encoding="utf-8")
        self.assertIn("demo-repo/AGENTS.md", text)
        self.assertIn("demo-repo/docs/guide.md", text)

    def test_select_survivors_multihead_gating_and_residuals_quantized_profile(self):
        spans = self.write("spans.jsonl", [
            {"id": sid, "session_id": sid, "has_pivot": True, "text": f"text {sid}"}
            for sid in ("keep", "low_anom", "no_evid", "dead_neg", "tie_b", "tie_a")
        ], lines=True)
        def row(sid, anom, evid, tax, tax_probs, score):
            return {"id": sid, "judgment": {"ok": True, "answers": {
                "anomaly_probe": {"type": "predicate", "probability": anom},
                "evidence_backing": {"type": "choice", "choice": evid, "probabilities": {evid: 1.0}},
                "taxonomy_v2": {"type": "choice", "choice": tax, "probabilities": tax_probs},
                "systemic_score": {"type": "score", "score": score},
            }}}
        # Build 20 quantized rows so quantized_001 triggers cleanly.
        scored_rows = [
            row("keep", 0.90, "proven_operational_lesson", "os_shell_hook_subprocess", {"os_shell_hook_subprocess": 0.80, "routine_or_app_local": 0.20}, 1.80),
            row("low_anom", 0.15, "proven_operational_lesson", "os_shell_hook_subprocess", {"os_shell_hook_subprocess": 0.80, "routine_or_app_local": 0.20}, 1.80),
            row("no_evid", 0.95, "no_lesson_evidence", "os_shell_hook_subprocess", {"os_shell_hook_subprocess": 0.80, "routine_or_app_local": 0.20}, 1.80),
            row("dead_neg", 0.88, "no_lesson_evidence", "routine_or_app_local", {"routine_or_app_local": 0.89, "os_shell_hook_subprocess": 0.11}, 0.10),
            row("tie_b", 1.00, "proven_operational_lesson", "os_shell_hook_subprocess", {"os_shell_hook_subprocess": 1.00}, 2.00),
            row("tie_a", 1.00, "proven_operational_lesson", "os_shell_hook_subprocess", {"os_shell_hook_subprocess": 1.00}, 2.00),
        ]
        extra_spans = []
        for i in range(14):
            sid = f"pad_{i:02d}"
            extra_spans.append({"id": sid, "session_id": sid, "has_pivot": True, "text": f"pad {i}"})
            scored_rows.append(row(sid, 0.05, "no_lesson_evidence", "routine_or_app_local", {"routine_or_app_local": 0.95, "os_shell_hook_subprocess": 0.05}, 0.00))
        with spans.open("a", encoding="utf-8") as handle:
            for item in extra_spans:
                handle.write(json.dumps(item) + "\n")
        scored = self.write("l1v2-scored.jsonl", scored_rows, lines=True)
        selected, report = self.root / "sel.jsonl", self.root / "res.json"
        self.invoke("mine", "select-survivors", "--stage", "l1-v2", "--scored", scored, "--spans", spans, "--output", selected)
        self.assertEqual([r["id"] for r in self.rows(selected)], ["keep", "tie_b", "tie_a"])
        self.invoke("mine", "residuals", "--stage", "l1-v2", "--scored", scored, "--spans", spans, "--output", report)
        res = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(res["calibration_profile"]["quantized_001"])
        self.assertFalse(res["calibration_profile"]["binary_hard"])
        self.assertGreater(res["calibration_profile"]["head_discordance_pred_high_routine_rate"], 0.0)
        self.assertEqual([item["id"] for item in res["strong_positives_top"][:2]], ["tie_a", "tie_b"])
        self.assertEqual(res["strong_positive_count"], 3)

    def test_mine_disagreements_offline_continuous_mass_and_head_conflict(self):
        def flat_row(sid, p, cat, cat_probs, score):
            return {"id": sid, "answers": {
                "is_pitfall": {"type": "predicate", "probability": p},
                "category": {"type": "choice", "value": cat, "probabilities": cat_probs},
                "reusability": {"type": "score", "value": score},
            }}
        # Out-of-order inputs, plus refusal and missing id to verify id-join and coverage reporting.
        left = self.write("left.jsonl", [
            flat_row("busybox", 0.101, "none", {"none": 0.943, "wsl": 0.057}, 1.061),
            flat_row("lockfile", 0.616, "toolchain", {"toolchain": 0.853, "none": 0.147}, 0.380),
            flat_row("cargo_neg", 0.121, "none", {"none": 0.940, "toolchain": 0.060}, 0.050),
            flat_row("left_only_hit", 0.920, "wsl", {"wsl": 0.900, "none": 0.100}, 1.700),
            flat_row("tax_split", 0.900, "wsl", {"wsl": 0.800, "toolchain": 0.100, "none": 0.100}, 1.500),
            {"id": "refused_item", "judgment": {"ok": True, "reason": "model_refusal", "answers": {"is_pitfall": {"type": "refusal"}}}},
            flat_row("only_in_left", 0.500, "none", {"none": 1.0}, 0.0),
        ], lines=True)
        right = self.write("right.jsonl", [
            flat_row("tax_split", 0.920, "toolchain", {"toolchain": 0.850, "wsl": 0.050, "none": 0.100}, 1.600),
            flat_row("left_only_hit", 0.150, "none", {"none": 0.900, "wsl": 0.100}, 0.100),
            flat_row("cargo_neg", 0.880, "none", {"none": 0.890, "toolchain": 0.110}, 0.100),
            flat_row("lockfile", 0.990, "toolchain", {"toolchain": 0.670, "none": 0.330}, 1.640),
            flat_row("busybox", 0.920, "wsl", {"wsl": 0.750, "none": 0.250}, 0.050),
            flat_row("refused_item", 0.900, "wsl", {"wsl": 0.900, "none": 0.100}, 1.500),
        ], lines=True)
        out = self.root / "disagreements.json"
        summary = self.invoke(
            "mine", "disagreements",
            "--left", left, "--right", right,
            "--left-label", "primary", "--right-label", "challenger",
            "--predicate", "is_pitfall", "--choice", "category",
            "--routine-label", "none", "--score", "reusability", "--score-max", "2",
            "--output", out,
        )
        self.assertEqual(summary["coverage"]["valid_pairs"], 5)
        self.assertEqual(summary["coverage"]["left_only_missing_ids"], 1)
        self.assertEqual(summary["coverage"]["left_refusals"], 1)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in data["right_only_top"]], ["busybox", "lockfile"])
        self.assertEqual([item["id"] for item in data["left_only_top"]], ["left_only_hit"])
        self.assertEqual([item["id"] for item in data["taxonomy_split_top"]], ["tax_split"])
        self.assertEqual([item["id"] for item in data["head_conflict_top"]], ["cargo_neg"])
        self.assertEqual(data["head_conflict_top"][0]["conflict_sides"], ["challenger"])
        # Missing declared predicate head on one side fails closed instead of fabricating a disagreement.
        missing_pred = self.write("missing_pred.jsonl", [{"id": "busybox", "answers": {
            "category": {"type": "choice", "value": "none", "probabilities": {"none": 0.943, "wsl": 0.057}},
            "reusability": {"type": "score", "value": 1.061},
        }}], lines=True)
        _, err = self.invoke(
            "mine", "disagreements",
            "--left", left, "--right", missing_pred,
            "--predicate", "is_pitfall", "--choice", "category",
            "--routine-label", "none", "--score", "reusability", "--score-max", "2",
            "--output", self.root / "fail.json", status=2, raw=True,
        )
        self.assertIn("missing predicate question", err)
