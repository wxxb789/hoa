"""Offline CLI contract tests using an OpenAI-compatible local HTTP stub."""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from hoa_cli.cli import main


LABELS = ("routine", "alpha", "beta", "novel")
METRICS = {"precision", "recall", "f_beta", "worst_case_gap", "false_negatives",
           "false_positives", "confusion_pairs", "refusal_count"}


def rubric(variant: str) -> dict:
    return {
        "questions": [
            {"name": "anomaly_probe", "type": "predicate", "instructions": "Does this look unusual?"},
            {"name": "mechanism", "type": "choice", "instructions": variant,
             "choices": [{"value": label, "description": f"Category {label}"} for label in LABELS]},
            {"name": "strength", "type": "score", "instructions": "Rate signal strength", "levels": [
                {"label": label} for label in ("absent", "weak", "medium", "strong")
            ]},
        ],
        "mech_question": "mechanism",
        "score_question": "strength",
        "routine_labels": ["routine"],
        "novel_label": "novel",
    }


class Stub(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        chat = self.path == "/v1/chat/completions"
        if self.path not in ("/v1/decisions", "/v1/chat/completions"):
            self.send_error(404)
            return
        if chat:
            state_and_questions = body["messages"][0]["content"].partition("\n\nState:\n")[2]
            text, _, questions_text = state_and_questions.partition("\n\nQuestions:\n")
            variant = next(line.rsplit("): ", 1)[1] for line in questions_text.splitlines()
                           if line.startswith('- "mechanism" ('))
        else:
            text, questions = body["input"], body["questions"]
            variant = next(q["instructions"] for q in questions if q["name"] == "mechanism")
        self.server.requests.append((self.path, variant, text))
        if text.startswith("endpoint-error"):
            result = {"error": {"message": text}}
        elif text.startswith("short-answer"):
            result = {"answers": []}
        elif text.startswith("model-refusal"):
            result = {"choices": [{"message": {"refusal": "Declined", "content": None}}]} if chat else {
                "answers": [{"name": q["name"], "type": "refusal", "reason": "model_refusal"} for q in questions]
            }
        elif text.startswith("payload-refusal"):
            result = {"error": {"code": "model_refusal"}}
        else:
            top, probabilities, score, anomaly = "routine", {"routine": 1.0}, 2, 0.1
            if (text.startswith("case-positive") and variant != "baseline") or (
                    text.startswith("anchor-positive") and variant != "break-anchors"):
                top, probabilities, score, anomaly = "alpha", {"alpha": 0.95, "routine": 0.05}, 2, 0.8
            elif text.startswith("overlap"):
                top, probabilities, score, anomaly = "alpha", {"alpha": 0.48, "beta": 0.46, "routine": 0.06}, 2, 0.8
            elif text.startswith("escape"):
                top, probabilities, score, anomaly = "novel", {"novel": 0.9, "routine": 0.1}, 3, 0.95
            answers = [
                {"name": "anomaly_probe", "type": "predicate", "probability": anomaly},
                {"name": "mechanism", "type": "choice", "choice": top, "probabilities": [
                    {"value": label, "probability": p} for label, p in probabilities.items()
                ]},
                {"name": "strength", "type": "score", "score": score},
            ]
            result = {"choices": [{"message": {"content": "```json\n" + json.dumps({
                "anomaly_probe": anomaly >= 0.5, "mechanism": top, "strength": score
            }) + "\n```"}}]} if chat else {"answers": answers[::-1]}
        raw = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:
        pass


class HillclimbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        server.requests = []
        cls.server = server
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        cls.addClassCleanup(server.server_close)
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.server.requests.clear()
        self.baseline = self.write_json("baseline.json", rubric("baseline"))
        self.candidate = self.write_json("candidate.json", rubric("candidate"))
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("RUBRIC_HILLCLIMB_", "GHC_DECISIONS_", "EVALS_"))}
        self.env["XDG_CONFIG_HOME"] = str(self.root / "config")

    def write_json(self, name: str, obj: object) -> Path:
        path = self.root / name
        path.write_text(json.dumps(obj), encoding="utf-8")
        return path

    def write_rows(self, name: str, rows: list[dict]) -> Path:
        path = self.root / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def labeled(self, name: str, *examples: tuple[str, bool | str]) -> Path:
        return self.write_rows(name, [{"id": f"record-{i}", "text": text, "expected": want}
                                      for i, (text, want) in enumerate(examples)])

    def command(self, name: str, *args: Path | str, api: str | None = "decisions", status: int = 0) -> tuple[str, str]:
        flags = [] if api is None or name == "split" else [
            "--base-url", self.url, "--model", "fixture", "--api", api, "--workers", "2",
        ]
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), redirect_stdout(out), redirect_stderr(err):
            result = main(["hillclimb", name, *map(str, args), *flags])
        stderr = err.getvalue()
        self.assertEqual(result, status, stderr)
        if status != 2:
            self.assertEqual(stderr, "")
        return out.getvalue(), stderr

    def evaluate(self, path: Path, *args: Path | str, rubric_path: Path | None = None,
                 command: str = "eval", api: str | None = "decisions", status: int = 0) -> dict:
        stdout, _ = self.command(command, "--rubric", rubric_path or self.baseline, "--dataset", path,
                                 *args, api=api, status=status)
        return json.loads(stdout)

    def test_split_is_deterministic_and_stratified(self) -> None:
        rows = [{"id": f"{label}-{i}", "text": "Example", "expected": label}
                for label, count in (("alpha", 8), ("beta", 4), ("novel", 1)) for i in range(count)]
        inputs = [self.write_rows("ordered.jsonl", rows), self.write_rows("reversed.jsonl", rows[::-1])]
        for source in inputs:
            tag = source.stem
            stdout, _ = self.command("split", "--input", source, "--train-out", f"{tag}-train.jsonl",
                                     "--holdout-out", f"{tag}-holdout.jsonl", "--out-dir", self.root)
            self.assertEqual(json.loads(stdout), {"train_count": 10, "holdout_count": 3})
        train, holdout = ([(json.loads(line)) for line in (self.root / f"ordered-{kind}.jsonl")
                           .read_text(encoding="utf-8").splitlines()] for kind in ("train", "holdout"))
        self.assertEqual(Counter(row["expected"] for row in train), {"alpha": 6, "beta": 3, "novel": 1})
        self.assertEqual(Counter(row["expected"] for row in holdout), {"alpha": 2, "beta": 1})
        self.assertTrue({row["id"] for row in train}.isdisjoint(row["id"] for row in holdout))
        for kind in ("train", "holdout"):
            self.assertEqual((self.root / f"ordered-{kind}.jsonl").read_bytes(),
                             (self.root / f"reversed-{kind}.jsonl").read_bytes())

    def test_eval_train_exposes_bounded_errors_and_holdout_is_blind(self) -> None:
        train = self.labeled("train.jsonl", ("overlap private-training-sample " + "x" * 400, "beta"),
                             ("ordinary second-training-sample", "alpha"), ("ordinary", "routine"))
        result = self.evaluate(train, "--max-errors", "1")
        self.assertEqual(result["false_negatives"], 2)
        self.assertEqual(result["false_positives"], 2)
        self.assertAlmostEqual(result["f_beta"], 1 / 3)
        self.assertEqual(result["confusion_pairs"], [{"labels": ["alpha", "beta"], "count": 1}])
        self.assertEqual(len(result["error_samples"]), 1)
        self.assertIn("second-training-sample", result["error_samples"][0]["text"])
        all_errors = self.evaluate(train)["error_samples"]
        self.assertEqual(len(all_errors[1]["text"]), 300)
        holdout = self.write_rows("holdout.jsonl", [
            {"id": "blind-id-a", "text": "overlap secret-holdout-a", "expected": "secret-label-a"},
            {"id": "blind-id-b", "text": "ordinary secret-holdout-b", "expected": "routine"},
        ])
        outputs = []
        for command, args in (("eval", ("--mode", "holdout", "--max-errors", "5")), ("eval-holdout", ())):
            stdout, stderr = self.command(command, "--rubric", self.baseline, "--dataset", holdout, *args)
            for private in ("secret-holdout", "secret-label", "blind-id", "error_samples"):
                self.assertNotIn(private, stdout + stderr)
            outputs.append(json.loads(stdout))
        self.assertEqual(set(outputs[0]), METRICS)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0]["confusion_pairs"], [{"labels": ["alpha", "beta"], "count": 1}])

    def test_refusals_and_four_level_normalization(self) -> None:
        path = self.labeled("train.jsonl", ("case-positive", True), ("ordinary", False),
                            ("model-refusal positive", True), ("payload-refusal negative", False))
        stage = rubric("candidate")
        anchors = [{"id": "positive", "text": "anchor-positive", "expected": True},
                   {"id": "negative", "text": "ordinary", "expected": False}]
        staged = self.write_json("staged.json", {"stages": {"primary": stage, "other": stage}, "anchors": anchors})
        result = self.evaluate(path, "--stage", "primary", "--check-anchors", rubric_path=staged)
        self.assertEqual(result["false_negatives"], 1)
        self.assertEqual(result["false_positives"], 1)
        self.assertEqual(result["refusal_count"], 2)
        self.assertEqual(result["worst_case_gap"], -1)
        self.assertAlmostEqual(result["f_beta"], 0.5)
        self.assertTrue(result["anchors"]["passed"])
        self.assertAlmostEqual(result["anchors"]["worst_case_gap"], 0.38)
        self.assertEqual([err["reason"] for err in result["error_samples"]], ["model_refusal"] * 2)

    def test_step_ledger_accept_revert_and_anchor_gate(self) -> None:
        train = self.labeled("train.jsonl", ("case-positive", True), ("ordinary", False))
        anchors = self.labeled("anchors.jsonl", ("anchor-positive", True), ("ordinary", False))
        regression = self.write_json("regression.json", rubric("break-anchors"))
        best, ledger = self.root / "best.json", self.root / "rubric-ledger.jsonl"
        shared = ("--train", train, "--anchors", anchors, "--best-out", best, "--ledger", ledger)
        stdout, _ = self.command("step", "--baseline", self.baseline, "--candidate", self.candidate,
                                 *shared, "--note", "tighten the category")
        first = json.loads(stdout)
        self.assertTrue(first["accepted"])
        self.assertEqual(first["candidate"]["f_beta"], 1.0)
        self.assertEqual(best.read_bytes(), self.candidate.read_bytes())
        self.assertEqual(first["sha256"], hashlib.sha256(best.read_bytes()).hexdigest())
        stdout, _ = self.command("step", "--baseline", self.candidate, "--candidate", self.baseline, *shared)
        second = json.loads(stdout)
        self.assertFalse(second["accepted"])
        self.assertEqual(second["status"], "reverted")
        self.assertLess(second["candidate"]["f_beta"], second["baseline"]["f_beta"])
        stdout, _ = self.command("step", "--baseline", self.baseline, "--candidate", regression, *shared)
        third = json.loads(stdout)
        self.assertFalse(third["accepted"])
        self.assertGreater(third["candidate"]["f_beta"], third["baseline"]["f_beta"])
        self.assertEqual(third["candidate"]["anchors"]["false_negatives"], 1)
        self.assertEqual(best.read_bytes(), self.candidate.read_bytes())
        records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records, [first, second, third])
        self.assertEqual([record["iter"] for record in records], [1, 2, 3])
        result = self.evaluate(train, "--anchors", anchors, rubric_path=regression, command="eval-holdout", status=1)
        self.assertEqual(set(result), METRICS)

    def test_sample_unlabeled_pool(self) -> None:
        items = [
            {"id": "different", "text": "case-positive"},
            {"id": "ambiguous", "text": "overlap"},
            {"id": "outside", "text": "escape"},
            {"id": "unchanged", "text": "ordinary"},
        ]
        pool = self.write_rows("pool.jsonl", items)
        stdout, _ = self.command("sample", "--baseline", self.baseline, "--candidate", self.candidate,
                                 "--pool", pool, "--max-items", "1")
        result = json.loads(stdout)
        for name, item in (("disagreement_pool", "different"), ("confusion_pool", "ambiguous"), ("ood_pool", "outside")):
            self.assertEqual([entry["id"] for entry in result[name]], [item])
            self.assertNotIn("expected", result[name][0])
        self.assertGreater(result["ood_pool"][0]["priority"], 0.8)
        self.assertEqual(result["confusion_pairs"], [{"labels": ["alpha", "beta"], "count": 1}])
        self.assertEqual(Counter((variant, text) for _, variant, text in self.server.requests),
                         {(variant, entry["text"]): 1 for variant in ("baseline", "candidate") for entry in items})

    def test_chat_fallback_and_environment_resolution(self) -> None:
        self.env.update(GHC_DECISIONS_BASE_URL=self.url, EVALS_MODEL="fixture", RUBRIC_HILLCLIMB_API="chat-completions")
        train = self.labeled("chat.jsonl", ("case-positive", True), ("ordinary", False), ("model-refusal", True))
        result = self.evaluate(train, rubric_path=self.candidate, api=None)
        self.assertEqual(result["refusal_count"], 1)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual({endpoint for endpoint, _, _ in self.server.requests}, {"/v1/chat/completions"})

    def test_bad_wire_responses_fail_without_leaking_holdout(self) -> None:
        short = self.labeled("short.jsonl", ("short-answer", True))
        _, stderr = self.command("eval", "--rubric", self.baseline, "--dataset", short, status=2)
        self.assertIn("expected 3 answers, got 0", stderr)
        holdout = self.labeled("holdout.jsonl", ("endpoint-error secret-echo", True))
        stdout, stderr = self.command("eval-holdout", "--rubric", self.baseline, "--dataset", holdout, status=2)
        self.assertEqual(stdout, "")
        self.assertNotIn("secret-echo", stderr)
        self.assertNotIn("Traceback", stderr)

