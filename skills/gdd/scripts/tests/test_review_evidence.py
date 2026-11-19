#!/usr/bin/env python3
"""Offline schema, generator, and merge-gate regression tests; no GitHub/LLM calls.

Run: python skills/gdd/scripts/tests/test_review_evidence.py
"""

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import gdd_process
from machine_review import (  # noqa: E402
    DEFAULT_MARKER, EvidenceError, evidence_comment, make_evidence, parse_marker,
    report_digest, review_facts, validate_runtime_receipt, RESPONSES_APIS,
)

spec = importlib.util.spec_from_file_location("pr_merge_check", SCRIPTS / "pr-merge-check.py")
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
HEAD = "a1b2c3d4" + "0" * 32
OTHER = "b1b2c3d4" + "0" * 32
MODEL = "fixture-model"
PROVIDER = "fixture-provider"
REPORT = 'No findings. Unicode: café, e\u0301, 漢字, 😀.\r\nQuotes: " \\ < > & -->.\n'


def clean_evidence():
    return make_evidence(REPORT.encode("utf-8"), HEAD, MODEL, PROVIDER, False)


def comment(evidence, marker=DEFAULT_MARKER, comment_id=1):
    return {"id": comment_id, "body": evidence_comment(evidence, marker)}


class EvidenceTests(unittest.TestCase):
    def test_full_schema_roundtrip_and_default_marker(self):
        self.assertEqual(DEFAULT_MARKER, "machine-review-state:v1")
        evidence = clean_evidence()
        parsed = parse_marker(evidence_comment(evidence))
        self.assertEqual(parsed, evidence)
        facts = gate.evaluate_review([comment(evidence)], HEAD)
        self.assertTrue(facts["pass"])
        self.assertTrue(facts["head_match"])
        self.assertTrue(facts["hash_match"])
        self.assertEqual(facts["model"], MODEL)
        self.assertEqual(facts["provider"], PROVIDER)

    def test_unicode_exact_bytes_crlf_and_html_delimiters(self):
        evidence = clean_evidence()
        body = evidence_comment(evidence)
        report = parse_marker(body)["code_review"]["report"]
        self.assertEqual(report.encode("utf-8"), REPORT.encode("utf-8"))
        self.assertEqual(evidence["code_review"]["report_sha256"],
                         hashlib.sha256(REPORT.encode("utf-8")).hexdigest())
        self.assertEqual(body.count("-->"), 0)
        self.assertNotEqual(report_digest(REPORT), report_digest(REPORT.replace("\r\n", "\n")))
        self.assertNotEqual(report_digest("é"), report_digest("e\u0301"))

    def test_report_can_contain_marker_and_json(self):
        report = (DEFAULT_MARKER + ' {"code_review":null}\n').encode("utf-8")
        evidence = make_evidence(report, HEAD, MODEL, PROVIDER, False)
        self.assertTrue(gate.evaluate_review([comment(evidence)], HEAD)["pass"])
        self.assertEqual(parse_marker(evidence_comment(evidence)), evidence)

    def test_missing_every_required_field_blocks(self):
        for field in clean_evidence()["code_review"]:
            with self.subTest(field=field):
                evidence = clean_evidence()
                del evidence["code_review"][field]
                self.assertFalse(gate.evaluate_review([comment(evidence)], HEAD)["pass"])

    def test_malformed_field_types_and_values_block(self):
        mutations = {
            "status": [None, False, 0, 1, [], {}, "", "running", "COMPLETED", " completed"],
            "has_any_findings": [None, True, 0, 1, [], {}, "false", "", "no"],
            "commit_sha": [None, False, 0, [], {}, "", HEAD[:7], HEAD[:39], HEAD + "0",
                           "g" * 40, " " + HEAD, OTHER, HEAD.upper()],
            "model": [None, False, 0, [], {}, "", " \t\n", "\ud800"],
            "provider": [None, False, 0, [], {}, "", " \t\n", "\udfff"],
            "report": [None, False, 0, [], {}, "", " \t\n", "\ud800"],
            "report_sha256": [None, False, 0, [], {}, "", "a" * 63, "a" * 65,
                              "x" * 64, "0" * 64, " " + "0" * 64],
        }
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=repr(value)):
                    evidence = clean_evidence()
                    evidence["code_review"][field] = value
                    result = gate.evaluate_review([comment(evidence)], HEAD)
                    self.assertFalse(result["pass"])
                    reason = {"commit_sha": "sha", "has_any_findings": "findings"}.get(field, field)
                    self.assertIn(reason, result["reason"])

    def test_wrong_or_abbreviated_current_head_blocks(self):
        for head in [None, False, 0, [], {}, "", HEAD[:7], HEAD[:39], "z" * 40, OTHER, HEAD.upper()]:
            with self.subTest(head=head):
                self.assertFalse(gate.evaluate_review([comment(clean_evidence())], head)["pass"])

    def test_malformed_root_and_code_review_objects_block(self):
        for value in [None, False, True, 0, 1, "text", [], [clean_evidence()], {}]:
            with self.subTest(root=value):
                body = DEFAULT_MARKER + " " + json.dumps(value)
                self.assertFalse(gate.evaluate_review([{"id": 1, "body": body}], HEAD)["pass"])
            with self.subTest(code_review=value):
                self.assertFalse(gate.evaluate_review([comment({"code_review": value})], HEAD)["pass"])

    def test_malformed_json_and_no_brace_scanning(self):
        good = json.dumps(clean_evidence())
        bodies = [
            DEFAULT_MARKER, DEFAULT_MARKER + " {not json",
            DEFAULT_MARKER + " [" + good + "]",
            DEFAULT_MARKER + " prose " + good,
            DEFAULT_MARKER + " false " + good,
            DEFAULT_MARKER + " " + good + " trailing junk",
            "<!-- " + DEFAULT_MARKER + " " + good,
            "<!-- " + DEFAULT_MARKER + " " + good + " junk -->",
            DEFAULT_MARKER + ' {"code_review":NaN}',
            DEFAULT_MARKER + ' {"code_review":Infinity}',
            DEFAULT_MARKER + ' {"code_review":-Infinity}',
            DEFAULT_MARKER + ' {"code_review":{},"code_review":' + good + "}",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertIsNone(gate.extract_marker(body))
                self.assertFalse(gate.evaluate_review([{"body": body}], HEAD)["pass"])

    def test_duplicate_nested_keys_block_even_when_last_value_is_clean(self):
        evidence = clean_evidence()
        raw = json.dumps(evidence).replace('"has_any_findings": false',
                                            '"has_any_findings": true, "has_any_findings": false')
        self.assertFalse(gate.evaluate_review([{"body": DEFAULT_MARKER + " " + raw}], HEAD)["pass"])

    def test_hash_tamper_and_report_tamper_block(self):
        for field, replacement in [("report_sha256", "0" * 64),
                                   ("report_sha256", report_digest(REPORT).upper()),
                                   ("report", REPORT + "tamper")]:
            evidence = clean_evidence()
            evidence["code_review"][field] = replacement
            result = gate.evaluate_review([comment(evidence)], HEAD)
            self.assertFalse(result["pass"])
            self.assertFalse(result["hash_match"])

    def test_whitespace_report_with_correct_hash_still_blocks(self):
        evidence = clean_evidence()
        evidence["code_review"].update(report=" \r\n", report_sha256=report_digest(" \r\n"))
        self.assertFalse(gate.evaluate_review([comment(evidence)], HEAD)["pass"])

    def test_nonempty_model_provider_are_not_hardcoded(self):
        for model, provider in [("operator-model-a", "operator-provider-a"), ("模型", "供应者")]:
            evidence = make_evidence(b"No findings.\n", HEAD, model, provider, False)
            self.assertTrue(gate.evaluate_review([comment(evidence)], HEAD)["pass"])

    def test_dirty_completed_report_is_valid_evidence_not_permission(self):
        evidence = make_evidence(b"P2: reproduce the defect.\n", HEAD, MODEL, PROVIDER, True)
        result = gate.evaluate_review([comment(evidence)], HEAD)
        self.assertFalse(result["pass"])
        self.assertEqual(result["reason"], "findings")
        self.assertTrue(result["hash_match"])

    def test_newest_bad_evidence_blocks_older_clean_and_opt_out(self):
        mutations = []
        for field in clean_evidence()["code_review"]:
            evidence = clean_evidence()
            del evidence["code_review"][field]
            mutations.append(comment(evidence, comment_id=2))
        stale = clean_evidence()
        stale["code_review"]["commit_sha"] = OTHER
        mutations.extend([comment(stale, comment_id=2), {"id": 2, "body": DEFAULT_MARKER + " []"}])
        for newest in mutations:
            for allow in [False, True]:
                with self.subTest(newest=newest, allow=allow):
                    result = gate.evaluate_review([newest, comment(clean_evidence())], HEAD,
                                                  allow_no_machine_review=allow)
                    self.assertFalse(result["pass"])
                    self.assertFalse(result["allowed"])
                    self.assertEqual(result["comment_id"], 2)

    def test_first_bad_marker_in_same_comment_is_not_rescued(self):
        body = DEFAULT_MARKER + " {bad}\n" + evidence_comment(clean_evidence())
        self.assertFalse(gate.evaluate_review([{"body": body}], HEAD)["pass"])

    def test_excessively_nested_json_blocks_without_crashing(self):
        body = DEFAULT_MARKER + ' {"code_review":' + "[" * 2000 + "0" + "]" * 2000 + "}"
        self.assertFalse(gate.evaluate_review([{"body": body}], HEAD)["pass"])

    def test_malformed_comment_envelopes_fail_closed(self):
        for comments in [[None], [[]], [{"body": False}], [{"body": 0}], [{"body": []}]]:
            with self.subTest(comments=comments), self.assertRaises(gate.GateError):
                gate.evaluate_review(comments, HEAD, allow_no_machine_review=True)

    def test_custom_marker_has_identical_strict_schema(self):
        marker = "operator-review:v2"
        evidence = clean_evidence()
        self.assertTrue(gate.evaluate_review([comment(evidence, marker)], HEAD, marker)["pass"])
        for field in evidence["code_review"]:
            bad = copy.deepcopy(evidence)
            del bad["code_review"][field]
            with self.subTest(field=field):
                result = gate.evaluate_review([comment(bad, marker)], HEAD, marker, True)
                self.assertFalse(result["pass"])
                self.assertFalse(result["allowed"])
        legacy = {"code_review": {"status": "completed", "has_any_findings": False,
                                  "commit_sha": HEAD[:7]}}
        self.assertFalse(gate.evaluate_review([comment(legacy, marker)], HEAD, marker, True)["pass"])

    def test_no_marker_opt_out_only(self):
        comments = [{"body": "human approval is not machine evidence"}]
        self.assertFalse(gate.evaluate_review(comments, HEAD)["pass"])
        result = gate.evaluate_review(comments, HEAD, allow_no_machine_review=True)
        self.assertTrue(result["pass"])
        self.assertFalse(result["found"])
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "none")

    def test_invalid_marker_cannot_be_empty_opt_out(self):
        for marker in ["", " ", "<!--", "two words", None]:
            with self.subTest(marker=marker), self.assertRaises(EvidenceError):
                gate.evaluate_review([], HEAD, marker, True)

    def test_human_output_shows_report_provenance(self):
        result = gate.evaluate_review([comment(clean_evidence())], HEAD)
        out = io.StringIO()
        with redirect_stdout(out):
            gate.print_human({"review": result, "gates": {"rc": 0, "ts": "fixture"}}, [])
        for text in ["model=" + MODEL, "provider=" + PROVIDER, "report_hash=match"]:
            self.assertIn(text, out.getvalue())


class GeneratorCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="review-evidence-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.report = self.root / "report.md"
        self.output = self.root / "comment.md"
        self.report.write_bytes(REPORT.encode("utf-8"))
        self.args = ["--report", str(self.report), "--head", HEAD, "--model", MODEL,
                     "--provider", PROVIDER, "--findings", "false"]

    def run_cli(self, args):
        return gdd_process.run([sys.executable, str(SCRIPTS / "review-evidence.py"), *args],
                              capture_output=True)

    def test_real_file_to_comment_to_gate(self):
        result = self.run_cli(self.args + ["--output", str(self.output)])
        self.assertEqual(result.returncode, 0, result.stderr)
        body = self.output.read_bytes().decode("utf-8")
        review = parse_marker(body)["code_review"]
        self.assertEqual(review["report"].encode("utf-8"), self.report.read_bytes())
        self.assertEqual(review["report_sha256"], hashlib.sha256(self.report.read_bytes()).hexdigest())
        self.assertTrue(gate.evaluate_review([{"body": body}], HEAD)["pass"])

    def test_stdout_and_custom_marker_and_dirty_report(self):
        args = list(self.args)
        args[-1] = "true"
        result = self.run_cli(args + ["--marker", "operator:v2"])
        self.assertEqual(result.returncode, 0, result.stderr)
        body = result.stdout.decode("utf-8")
        review = gate.evaluate_review([{"body": body}], HEAD, "operator:v2")
        self.assertFalse(review["pass"])
        self.assertEqual(review["reason"], "findings")

    def test_custom_tokens_cannot_collide_with_generated_preamble(self):
        for marker in ["review", "evidence", "Machine", "JSON", "-", "--", "v1"]:
            with self.subTest(marker=marker):
                result = self.run_cli(self.args + ["--marker=" + marker])
                self.assertEqual(result.returncode, 0, result.stderr)
                body = result.stdout.decode("utf-8")
                self.assertTrue(body.startswith(marker + " "))
                self.assertTrue(gate.evaluate_review([{"body": body}], HEAD, marker)["pass"])

    def test_each_required_flag_is_required(self):
        for index in range(0, len(self.args), 2):
            with self.subTest(flag=self.args[index]):
                result = self.run_cli(self.args[:index] + self.args[index + 2:])
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"required", result.stderr)

    def test_invalid_cli_values_refuse_and_do_not_write_output(self):
        for flag, values in {"--head": [HEAD[:7], "z" * 40, ""],
                             "--model": ["", " \t"], "--provider": ["", " \t"],
                             "--findings": ["0", "False", ""], "--marker": ["", "two words"]}.items():
            for value in values:
                with self.subTest(flag=flag, value=value):
                    args = list(self.args)
                    if flag in args:
                        args[args.index(flag) + 1] = value
                    else:
                        args.extend([flag, value])
                    result = self.run_cli(args + ["--output", str(self.output)])
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(self.output.exists())

    def test_missing_empty_whitespace_and_invalid_utf8_report(self):
        self.report.unlink()
        result = self.run_cli(self.args + ["--output", str(self.output)])
        self.assertEqual(result.returncode, 2)
        for report in [b"", b" \t\r\n", b"bad \xff"]:
            with self.subTest(report=report):
                self.report.write_bytes(report)
                result = self.run_cli(self.args + ["--output", str(self.output)])
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.output.exists())

    def test_cannot_overwrite_source_report(self):
        result = self.run_cli(self.args + ["--output", str(self.report)])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.report.read_bytes(), REPORT.encode("utf-8"))

    def test_missing_output_directory_is_a_file_error(self):
        result = self.run_cli(self.args + ["--output", str(self.root / "absent" / "comment")])
        self.assertEqual(result.returncode, 2)


class RuntimeReceiptTests(unittest.TestCase):
    def records(self, model=MODEL, api="openai-responses"):
        return [{"type": "model_change", "provider": PROVIDER, "modelId": model},
                {"type": "message", "message": {"role": "assistant", "provider": PROVIDER,
                 "model": model, "api": api, "stopReason": "stop",
                 "content": [{"type": "text", "text": "No findings."}]}}]

    def test_all_supported_responses_transports_and_namespaced_ids(self):
        for model in [MODEL, "namespace/fixture-model"]:
            for api in RESPONSES_APIS:
                with self.subTest(model=model, api=api):
                    value = validate_runtime_receipt(self.records(model, api), PROVIDER, model,
                                                     "responses", [api])
                    self.assertEqual(value["apis"], [api])

    def test_explicit_responses_lane_rejects_chat_regardless_of_model_name(self):
        for model in [MODEL, "namespace/fixture-model"]:
            with self.subTest(model=model), self.assertRaises(EvidenceError):
                validate_runtime_receipt(self.records(model, "openai-completions"), PROVIDER,
                                         model, "responses", ["openai-completions"])

    def test_model_provider_and_actual_api_mismatches_block(self):
        for field in ["model", "provider", "api"]:
            records = self.records()
            records[1]["message"][field] = "mismatch"
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                validate_runtime_receipt(records, PROVIDER, MODEL, "responses", ["openai-responses"])
        with self.assertRaises(EvidenceError):
            validate_runtime_receipt([], PROVIDER, MODEL, "responses", ["openai-responses"])

    def test_transport_and_api_inputs_have_no_implicit_defaults(self):
        for transport, apis in [(None, []), ("responses", []), ("responses", ["unknown"]),
                                ("responses", "openai-responses"), ("other", [""])]:
            with self.subTest(transport=transport, apis=apis), self.assertRaises(EvidenceError):
                validate_runtime_receipt(self.records(), PROVIDER, MODEL, transport, apis)
        self.assertEqual(validate_runtime_receipt(self.records(api="fixture-api"), PROVIDER,
                         MODEL, "other", ["fixture-api"])["apis"], ["fixture-api"])

    def test_failed_aborted_or_truncated_output_blocks(self):
        for reason in ["error", "aborted", "length"]:
            records = self.records()
            records[1]["message"]["stopReason"] = reason
            with self.subTest(reason=reason), self.assertRaises(EvidenceError):
                validate_runtime_receipt(records, PROVIDER, MODEL, "responses", ["openai-responses"])

    def test_final_stop_reason_must_be_successful_and_known(self):
        for reason in [None, "pending", "deferred", "toolUse", [], {}, True]:
            records = self.records()
            records[-1]["message"]["stopReason"] = reason
            with self.subTest(reason=reason), self.assertRaises(EvidenceError):
                validate_runtime_receipt(records, PROVIDER, MODEL, "responses", ["openai-responses"])

    def test_intermediate_tools_need_a_completed_final_response(self):
        for reason in ["toolUse", "deferred"]:
            records = self.records()
            intermediate = copy.deepcopy(records[-1])
            intermediate["message"]["stopReason"] = reason
            records.insert(1, intermediate)
            self.assertEqual(validate_runtime_receipt(records, PROVIDER, MODEL, "responses",
                             ["openai-responses"])["model"], MODEL)

    def test_final_report_text_cannot_be_missing_empty_or_malformed(self):
        for content in [None, [], {}, [{"type": "thinking", "text": "not a report"}],
                        [{"type": "text", "text": " "}], [{"type": "text", "text": False}]]:
            records = self.records()
            records[-1]["message"]["content"] = content
            with self.subTest(content=content), self.assertRaises(EvidenceError):
                validate_runtime_receipt(records, PROVIDER, MODEL, "responses", ["openai-responses"])

    def test_jsonl_literal_unicode_separators_are_not_record_delimiters(self):
        with tempfile.TemporaryDirectory(prefix="review-receipt-unicode-") as folder:
            for separator in ["\u0085", "\u2028", "\u2029"]:
                records = self.records()
                records[-1]["message"]["content"][0]["text"] = "No" + separator + "findings."
                (Path(folder) / "session.jsonl").write_text(
                    "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
                result = gdd_process.run([sys.executable, str(SCRIPTS / "review-receipt.py"),
                    "--session-dir", folder, "--provider", PROVIDER, "--model", MODEL,
                    "--transport", "responses", "--api-id", "openai-responses"], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_receipt_cli_and_missing_multiple_receipts(self):
        with tempfile.TemporaryDirectory(prefix="review-receipt-") as folder:
            root = Path(folder)
            receipt = root / "session.jsonl"
            receipt.write_text("\n".join(json.dumps(r) for r in self.records()) + "\n")
            args = [sys.executable, str(SCRIPTS / "review-receipt.py"), "--session-dir", folder,
                    "--provider", PROVIDER, "--model", MODEL, "--transport", "responses",
                    "--api-id", "openai-responses"]
            good = gdd_process.run(args, capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads(good.stdout)["model"], MODEL)
            (root / "second.jsonl").write_bytes(receipt.read_bytes())
            self.assertEqual(gdd_process.run(args, capture_output=True).returncode, 2)
            receipt.unlink()
            (root / "second.jsonl").unlink()
            self.assertEqual(gdd_process.run(args, capture_output=True).returncode, 2)


class MergeGateIntegrationTests(unittest.TestCase):
    def evaluate(self, evidence=None, checks=None, threads=None, gates_rc=0, verified_head=HEAD):
        view = {"state": "OPEN", "isDraft": False, "headRefOid": HEAD, "headRefName": "feature"}
        responses = [HEAD, "feature", json.dumps(view), "fixture-owner/fixture-repo"]
        with patch.object(gate, "sh", side_effect=responses), \
             patch.object(gate, "fetch_checks", return_value=(checks if checks is not None else
                          [{"state": "COMPLETED", "conclusion": "SUCCESS"}], "json")), \
             patch.object(gate, "fetch_issue_comments", return_value=[comment(evidence or clean_evidence())]), \
             patch.object(gate, "fetch_review_threads", return_value=threads or []):
            return gate.evaluate(1, ".", gates_rc, verified_head=verified_head)

    def test_complete_clean_evidence_with_other_clauses_passes(self):
        facts, reasons = self.evaluate()
        self.assertEqual(reasons, [])
        self.assertTrue(facts["review"]["pass"])

    def test_evidence_does_not_bypass_checks_threads_local_gates_or_head(self):
        cases = [({"checks": []}, "no checks"),
                 ({"checks": [{"state": "PENDING"}]}, "checks pending"),
                 ({"checks": [{"state": "PENDING"},
                              {"state": "COMPLETED", "conclusion": "FAILURE"}]}, "checks"),
                 ({"checks": [{"state": "COMPLETED", "conclusion": "FAILURE"}]}, "checks"),
                 ({"threads": [{"isResolved": False}]}, "threads"),
                 ({"gates_rc": 1}, "gates unverified"),
                 ({"gates_rc": None}, None),
                 ({"verified_head": OTHER}, "head mismatch")]
        for args, reason in cases:
            with self.subTest(args=args):
                facts, reasons = self.evaluate(**args)
                self.assertTrue(facts["review"]["pass"])
                if reason is not None:
                    self.assertIn(reason, reasons)
                else:
                    self.assertEqual(facts["gates"]["status"], "UNKNOWN")
                    # UNKNOWN local gates must never be implicit permission.
                    self.assertTrue(reasons, "missing --gates-rc must block merge")

    def test_bad_evidence_blocks_when_every_other_clause_passes(self):
        evidence = clean_evidence()
        evidence["code_review"]["report_sha256"] = "0" * 64
        facts, reasons = self.evaluate(evidence=evidence)
        self.assertFalse(facts["review"]["pass"])
        self.assertEqual(reasons, ["review"])


# gh >= 2.103 removed `--json conclusion` from `gh pr checks`; the surviving per-check verdict is
# `bucket`, and the human table exits 8 while a check is pending and 1 when one failed. These
# fixtures pin the mapping and the exit codes: pending is a reported state, not a crash.
MIXED_TABLE = ("verify\tfail\t4m9s\thttps://example/1\t\n"
                 "foreign-notes\tpass\t20s\thttps://example/2\t\n"
                 "docs\tpending\t1m2s\thttps://example/3\t\n")
GREEN_TABLE = ("lint\tskipping\t8s\thttps://example/1\t\n"
               "unit\tpass\t1m0s\thttps://example/2\t\n")
# What a run in flight looks like: nothing has failed yet, one check still running.
IN_FLIGHT_TABLE = ("foreign-notes\tpass\t20s\thttps://example/2\t\n"
                   "docs\tpending\t1m2s\thttps://example/3\t\n")
JSON_FIELD_GONE = (1, "", 'Unknown JSON field: "conclusion"')
BUCKET_ROW = {"name": "gates", "state": "PENDING", "bucket": "pending"}
# `gh pr checks` labels the columns `NAME STATUS ELAPSED URL DESCRIPTION` (gh 2.103, pkg/cmd/pr/
# checks/output.go). The fallback must recognize that header structurally, never by a `NAME`
# prefix: a check may be *named* `NAME-required`, and dropping it read a failing run as MERGE-OK.
TABLE_HEADER = "NAME\tSTATUS\tELAPSED\tURL\tDESCRIPTION\n"
NAME_PREFIXED_TABLE = (TABLE_HEADER
                       + "build\tpass\t1m0s\thttps://example/1\t\n"
                       + "NAME-required\tfail\t4m9s\thttps://example/2\t\n")
NAME_PREFIXED_PENDING_TABLE = (TABLE_HEADER
                               + "build\tpass\t1m0s\thttps://example/1\t\n"
                               + "NAME-required\tpending\t2m0s\thttps://example/2\t\n")
# The shape `gh pr checks` emits on this host (gh 2.103.3, non-TTY): name, state, elapsed, link,
# description — five tab-separated fields, the last empty. Rows observed live on a real PR.
REAL_GH_TABLE = ("release\tskipping\t0\thttps://example/runs/1/job/2\t\n"
                 "test\tpass\t1m52s\thttps://example/runs/1/job/3\t\n")


class CheckFetchTests(unittest.TestCase):
    def fetch_with_source(self, json_result, table_result):
        """`fetch_checks` rows, the surface that produced them, and the commands it ran."""
        calls = []

        def fake_sh_raw(cmd, cwd=None):
            calls.append(list(cmd))
            return json_result if "--json" in cmd else table_result

        with patch.object(gate, "sh_raw", side_effect=fake_sh_raw):
            checks, source = gate.fetch_checks(7, ".")
        return checks, source, calls

    def fetch(self, json_result, table_result):
        checks, _source, calls = self.fetch_with_source(json_result, table_result)
        return checks, calls

    def test_fetch_reports_the_surface_that_produced_the_rows(self):
        # The verdict's class-closing decision hangs on this label: a wrong "json" would let a
        # table-only read authorise a merge, and a wrong "table" would block a structured one.
        rows = [{"name": "build", "state": "SUCCESS", "bucket": "pass"}]
        _checks, source, calls = self.fetch_with_source((0, json.dumps(rows), ""), (0, "", ""))
        self.assertEqual(source, "json")
        self.assertEqual(calls[0][-2:], ["--json", "name,state,bucket"])
        _checks, source, calls = self.fetch_with_source(JSON_FIELD_GONE, (0, GREEN_TABLE, ""))
        self.assertEqual(source, "table")
        self.assertEqual(calls[1][:3], ["gh", "pr", "checks"])
        # gh's recognized empty message arrives on the table path too, so it is table-only.
        checks, source, _ = self.fetch_with_source(JSON_FIELD_GONE,
                                                   (1, "", "no checks reported on 'feature'"))
        self.assertEqual(source, "table")
        self.assertEqual(checks, [])

    def test_json_asks_for_the_bucket_not_the_removed_conclusion(self):
        rows = [{"name": "build", "state": "SUCCESS", "bucket": "pass"}]
        checks, calls = self.fetch((0, json.dumps(rows), ""), (0, "", ""))
        self.assertEqual(calls[0][-2:], ["--json", "name,state,bucket"])
        self.assertNotIn("conclusion", " ".join(calls[0]))
        self.assertEqual(checks, [{"name": "build", "state": "COMPLETED", "conclusion": "SUCCESS"}])

    def test_bucket_vocabulary_maps_ok_fail_and_pending(self):
        rows = [{"name": "unit", "state": "SUCCESS", "bucket": "pass"},
                {"name": "lint", "state": "SKIPPED", "bucket": "skipping"},
                {"name": "optional", "state": "NEUTRAL", "bucket": "neutral"},
                {"name": "e2e", "state": "FAILURE", "bucket": "fail"},
                {"name": "deploy", "state": "CANCELLED", "bucket": "cancel"},
                {"name": "gates", "state": "PENDING", "bucket": "pending"},
                {"name": "future", "state": "MYSTERY", "bucket": "unreleased-bucket"}]
        checks, _ = self.fetch((0, json.dumps(rows), ""), (0, "", ""))
        facts = gate.evaluate_checks(checks)
        self.assertEqual((facts["ok"], facts["pending"], facts["failing"]), (3, 2, 2))
        self.assertFalse(facts["pass"])
        # A bucket this version has not learned yet is never ok, and never a claimed failure.
        self.assertEqual(checks[6], {"name": "future", "state": "PENDING", "conclusion": None})

    def test_pending_table_on_nonzero_exit_is_data_not_a_crash(self):
        for returncode in (8, 1):
            with self.subTest(returncode=returncode):
                checks, calls = self.fetch(JSON_FIELD_GONE, (returncode, MIXED_TABLE, ""))
                self.assertEqual([check["name"] for check in checks],
                                 ["verify", "foreign-notes", "docs"])
                facts = gate.evaluate_checks(checks)
                self.assertEqual((facts["total"], facts["ok"], facts["pending"], facts["failing"]),
                                 (3, 1, 1, 1))
                self.assertEqual(calls[1][:3], ["gh", "pr", "checks"])

    def test_unparseable_output_still_raises(self):
        for name, table in [("blank pending run", (8, "", "checks pending")),
                            ("cli error text", (1, "gh: Not Found (HTTP 404)\n", "")),
                            ("stderr only", (1, "", "HTTP 401: Bad credentials"))]:
            with self.subTest(case=name), self.assertRaises(gate.GateError):
                self.fetch(JSON_FIELD_GONE, table)

    def test_non_json_stdout_falls_back_to_the_table(self):
        checks, _ = self.fetch((0, "<html>proxy</html>", ""), (0, GREEN_TABLE, ""))
        self.assertEqual([check["conclusion"] for check in checks], ["SKIPPED", "SUCCESS"])

    def test_zero_check_runs_rule_is_unchanged(self):
        # gh exits 1 with "no checks reported" when nothing registered (or ever, without CI).
        checks, _ = self.fetch(JSON_FIELD_GONE,
                               (1, "", "no checks reported on the 'feature' branch"))
        self.assertEqual(checks, [])
        facts = gate.evaluate_checks(checks)
        self.assertFalse(facts["pass"])
        self.assertEqual(facts["reason"], "no checks")
        self.assertTrue(gate.evaluate_checks(checks, allow_no_checks=True)["pass"])
        # ... and an empty table with a zero exit stays an empty list.
        self.assertEqual(self.fetch((0, "[]", ""), (0, "", ""))[0], [])

    def test_valid_non_list_json_stdout_falls_back_to_the_table(self):
        # json.loads succeeds but the payload is not a list: the same fallback as invalid JSON.
        checks, calls = self.fetch((0, '{"message": "not a list"}', ""), (0, GREEN_TABLE, ""))
        self.assertEqual([check["conclusion"] for check in checks], ["SKIPPED", "SUCCESS"])
        self.assertEqual(calls[1][:3], ["gh", "pr", "checks"])

    def test_non_object_check_row_raises_instead_of_being_dropped(self):
        # Dropping a malformed row would turn incomplete evidence into permission: a valid row
        # beside a null would read as an all-green list.
        for payload in [[{"name": "build", "state": "SUCCESS", "bucket": "pass"}, None],
                        [None], ["pass"]]:
            with self.subTest(payload=payload), self.assertRaises(gate.GateError) as raised:
                self.fetch((0, json.dumps(payload), ""), (0, GREEN_TABLE, ""))
            self.assertIn("object per check", str(raised.exception))

    def test_unknown_bucket_with_success_state_is_pending_not_ok(self):
        # gh's bucket — not the removed/raw `state` — is the per-check verdict (gh >= 2.103).
        rows = [{"name": "future", "state": "SUCCESS", "bucket": "unreleased-bucket"}]
        checks, _ = self.fetch((0, json.dumps(rows), ""), (0, "", ""))
        self.assertEqual(checks, [{"name": "future", "state": "PENDING", "conclusion": None}])
        facts = gate.evaluate_checks(checks)
        self.assertFalse(facts["pass"])
        self.assertEqual((facts["ok"], facts["pending"], facts["failing"]), (0, 1, 0))

    def test_empty_fallback_table_blocks_and_only_the_flag_passes_it(self):
        # JSON is unusable (removed field), so the table is the only source. An empty table is
        # zero check runs, not a green PR — this path returns before any JSON result is seen.
        checks, calls = self.fetch(JSON_FIELD_GONE, (0, "", ""))
        self.assertEqual(checks, [])
        self.assertEqual(calls[1][:3], ["gh", "pr", "checks"])
        facts = gate.evaluate_checks(checks)
        self.assertFalse(facts["pass"])
        self.assertEqual(facts["reason"], "no checks")
        allowed = gate.evaluate_checks(checks, allow_no_checks=True)
        self.assertTrue(allowed["pass"])
        self.assertEqual(allowed["reason"], "no checks (allowed by flag)")

    def test_missing_binary_raises_gate_error_not_oserror(self):
        # A missing gh/git must reach the exit-2 path (GateError), never an OSError traceback.
        with patch.object(subprocess, "run",
                          side_effect=FileNotFoundError("No such file or directory: 'gh'")):
            with self.assertRaises(gate.GateError) as raised:
                gate.sh_raw(["gh", "pr", "checks", "7"])
        self.assertIn("No such file or directory", str(raised.exception))

    def test_the_header_is_recognized_structurally_not_by_a_name_prefix(self):
        # The old filter was `line.startswith("NAME")`, which dropped every such check.
        checks, _ = self.fetch(JSON_FIELD_GONE, (1, NAME_PREFIXED_TABLE, ""))
        self.assertEqual([check["name"] for check in checks], ["build", "NAME-required"])
        facts = gate.evaluate_checks(checks)
        self.assertEqual((facts["total"], facts["ok"], facts["pending"], facts["failing"]),
                         (2, 1, 0, 1))
        self.assertFalse(facts["pass"])

    def test_a_pending_name_prefixed_row_is_counted_and_blocks(self):
        checks, _ = self.fetch(JSON_FIELD_GONE, (8, NAME_PREFIXED_PENDING_TABLE, ""))
        self.assertEqual([check["name"] for check in checks], ["build", "NAME-required"])
        facts = gate.evaluate_checks(checks)
        self.assertEqual((facts["total"], facts["ok"], facts["pending"], facts["failing"]),
                         (2, 1, 1, 0))
        self.assertFalse(facts["pass"])

    def test_the_header_row_is_not_counted_as_a_phantom_check(self):
        checks, _ = self.fetch(JSON_FIELD_GONE, (0, TABLE_HEADER + GREEN_TABLE, ""))
        self.assertEqual([check["name"] for check in checks], ["lint", "unit"])
        self.assertTrue(gate.evaluate_checks(checks)["pass"])

    def test_a_check_named_name_is_not_the_header(self):
        table = TABLE_HEADER + "NAME\tpass\t1s\thttps://example/0\t\n"
        checks, _ = self.fetch(JSON_FIELD_GONE, (0, table, ""))
        self.assertEqual(checks, [{"name": "NAME", "state": "COMPLETED", "conclusion": "SUCCESS"}])

    def test_allow_no_checks_never_forgives_a_failing_row(self):
        # The flag forgives zero check runs that were read successfully — not a reported failure.
        checks, _ = self.fetch(JSON_FIELD_GONE, (1, NAME_PREFIXED_TABLE, ""))
        facts = gate.evaluate_checks(checks, allow_no_checks=True)
        self.assertFalse(facts["pass"])
        self.assertEqual((facts["total"], facts["failing"]), (2, 1))

    def test_a_real_gh_table_parses_to_the_expected_verdicts(self):
        checks, _ = self.fetch(JSON_FIELD_GONE, (0, REAL_GH_TABLE, ""))
        self.assertEqual([(check["name"], check["conclusion"]) for check in checks],
                         [("release", "SKIPPED"), ("test", "SUCCESS")])
        self.assertTrue(gate.evaluate_checks(checks)["pass"])

    def test_a_recognized_bucket_governs_a_contradictory_raw_state(self):
        # gh's `bucket` is the per-check verdict; the raw `state` must not overrule it in either
        # direction. A fixture where the two agree cannot distinguish the precedence.
        rows = [{"name": "pass-bucket-failed-state", "state": "SUCCESS", "bucket": "fail"},
                {"name": "fail-bucket-passed-state", "state": "FAILURE", "bucket": "pass"},
                {"name": "pending-bucket-skipped-state", "state": "PENDING", "bucket": "skipping"}]
        checks, _ = self.fetch((0, json.dumps(rows), ""), (0, "", ""))
        self.assertEqual(checks, [
            {"name": "pass-bucket-failed-state", "state": "COMPLETED", "conclusion": "FAILURE"},
            {"name": "fail-bucket-passed-state", "state": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "pending-bucket-skipped-state", "state": "COMPLETED", "conclusion": "SKIPPED"},
        ])
        facts = gate.evaluate_checks(checks)
        self.assertEqual((facts["ok"], facts["pending"], facts["failing"]), (2, 0, 1))
        self.assertFalse(facts["pass"])

    def test_a_missing_or_null_bucket_is_pending_never_ok(self):
        # The bucket is the only verdict source; absent it nothing is known, so the row is pending.
        # A missing-bucket default of "pass" would turn an empty object into permission.
        for row in [{}, {"name": "required"}, {"name": "required", "state": "SUCCESS"},
                    {"name": "required", "state": "SUCCESS", "bucket": None},
                    {"name": "required", "bucket": ""}]:
            with self.subTest(row=row):
                checks, _ = self.fetch((0, json.dumps([row]), ""), (0, "", ""))
                self.assertEqual(checks,
                                 [{"name": row.get("name"), "state": "PENDING", "conclusion": None}])
                facts = gate.evaluate_checks(checks)
                self.assertFalse(facts["pass"])
                self.assertEqual((facts["ok"], facts["pending"], facts["failing"]), (0, 1, 0))

    def test_a_check_named_after_a_column_is_a_row_not_a_header(self):
        # Only a row whose every field is a column name is the header. A check legitimately named
        # `STATUS` (or any other printed column) must be counted; a name-based drop merges it away.
        for name in ("STATUS", "NAME", "ELAPSED", "URL", "DESCRIPTION"):
            for verdict, exit_code, pending, failing in (("fail", 1, 0, 1), ("pending", 8, 1, 0)):
                with self.subTest(name=name, verdict=verdict):
                    table = (TABLE_HEADER + GREEN_TABLE
                             + f"{name}\t{verdict}\t2m0s\thttps://example/2\t\n")
                    checks, _ = self.fetch(JSON_FIELD_GONE, (exit_code, table, ""))
                    self.assertEqual([check["name"] for check in checks], ["lint", "unit", name])
                    facts = gate.evaluate_checks(checks)
                    self.assertEqual(
                        (facts["total"], facts["ok"], facts["pending"], facts["failing"]),
                        (3, 2, pending, failing))
                    self.assertFalse(facts["pass"])

    def test_the_two_column_reserved_name_form_is_retained_and_blocks(self):
        for name, verdict, exit_code, pending, failing in [("STATUS", "pending", 8, 1, 0),
                                                           ("NAME", "fail", 1, 0, 1)]:
            with self.subTest(name=name):
                checks, _ = self.fetch(JSON_FIELD_GONE, (exit_code, f"{name}\t{verdict}\n", ""))
                self.assertEqual([check["name"] for check in checks], [name])
                facts = gate.evaluate_checks(checks)
                self.assertEqual((facts["total"], facts["ok"], facts["pending"], facts["failing"]),
                                 (1, 0, pending, failing))
                self.assertFalse(facts["pass"])

    def test_an_unknown_table_verdict_is_a_failure_not_an_ok(self):
        # An unrecognized verdict word is never green; the default must fail closed.
        checks, _ = self.fetch(JSON_FIELD_GONE, (0, "mystery\tunreleased\n", ""))
        self.assertEqual(checks, [{"name": "mystery", "state": "COMPLETED",
                                   "conclusion": "FAILURE"}])
        self.assertFalse(gate.evaluate_checks(checks)["pass"])

    def test_an_unordered_header_row_is_read_as_a_row_and_blocks(self):
        # The header is NAME then STATUS, in print order (gh 2.103 pkg/cmd/pr/checks/output.go: the
        # non-TTY header is NAME STATUS ELAPSED URL DESCRIPTION). Matching the column names as an
        # unordered set accepted `STATUS\tNAME` as the header, so the row — whose verdict is the
        # unknown word `NAME` — vanished and the remaining passing row reported MERGE-OK. Order is
        # part of the header, and every line that is not the header is a row.
        for flag in (False, True):
            with self.subTest(allow_no_checks=flag):
                checks, _ = self.fetch(JSON_FIELD_GONE, (0, "build\tpass\nSTATUS\tNAME\n", ""))
                self.assertEqual([(check["name"], check["conclusion"]) for check in checks],
                                 [("build", "SUCCESS"), ("STATUS", "FAILURE")])
                facts = gate.evaluate_checks(checks, allow_no_checks=flag)
                self.assertFalse(facts["pass"])
                self.assertEqual((facts["total"], facts["ok"], facts["failing"]), (2, 1, 1))

    def test_an_unordered_full_header_is_a_row_not_the_header(self):
        checks, _ = self.fetch(JSON_FIELD_GONE,
                               (0, "STATUS\tNAME\tELAPSED\tURL\tDESCRIPTION\n", ""))
        self.assertEqual([(check["name"], check["conclusion"]) for check in checks],
                         [("STATUS", "FAILURE")])
        self.assertFalse(gate.evaluate_checks(checks)["pass"])


class CheckFetchCliTests(unittest.TestCase):
    """main() end to end: the exit code, the checks line and the verdict, without a real gh."""

    def gate_main(self, *extra, table_result, json_result=JSON_FIELD_GONE):
        view = {"state": "OPEN", "isDraft": False, "headRefOid": HEAD, "headRefName": "feature"}
        responses = [HEAD, "feature", json.dumps(view), "fixture-owner/fixture-repo"]

        def fake_sh_raw(cmd, cwd=None):
            return json_result if "--json" in cmd else table_result

        out, err = io.StringIO(), io.StringIO()
        argv = ["pr-merge-check.py", "7", "--repo", ".", *extra]
        with patch.object(gate, "sh", side_effect=responses), \
             patch.object(gate, "sh_raw", side_effect=fake_sh_raw), \
             patch.object(gate, "fetch_issue_comments", return_value=[]), \
             patch.object(gate, "fetch_review_threads", return_value=[]), \
             patch.object(sys, "argv", argv), redirect_stdout(out), redirect_stderr(err):
            code = gate.main()
        return code, out.getvalue(), err.getvalue()

    def test_pending_run_blocks_with_a_pending_reason_and_exit_1(self):
        code, out, err = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                        "--allow-no-machine-review",
                                        table_result=(8, IN_FLIGHT_TABLE, ""))
        self.assertEqual(code, 1)
        self.assertIn("checks: 2 total, 1 ok, 1 pending, 0 failing", out)
        self.assertIn("verdict: BLOCKED: checks pending", out)
        self.assertEqual(err, "")

    def test_pending_bucket_json_blocks_identically(self):
        code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                      "--allow-no-machine-review",
                                      json_result=(0, json.dumps([BUCKET_ROW]), ""),
                                      table_result=(0, "", ""))
        self.assertEqual(code, 1)
        self.assertIn("checks: 1 total, 0 ok, 1 pending, 0 failing", out)
        self.assertIn("verdict: BLOCKED: checks pending", out)

    def test_the_unordered_header_repro_blocks_with_and_without_the_flag(self):
        # main() end to end on the fail-open: the row is counted, so neither run reports MERGE-OK
        # and --allow-no-checks cannot turn a counted row into permission.
        for extra in ((), ("--allow-no-checks",)):
            with self.subTest(extra=extra):
                code, out, err = self.gate_main(
                    "--verified-head", HEAD, "--gates-rc", "0", "--allow-no-machine-review",
                    *extra, table_result=(0, "build\tpass\nSTATUS\tNAME\n", ""))
                self.assertEqual(code, 1)
                self.assertIn("checks: 2 total, 1 ok, 0 pending, 1 failing", out)
                self.assertIn("verdict: BLOCKED: checks", out)
                self.assertEqual(err, "")

    def test_mixed_valid_and_malformed_check_rows_exit_2_without_a_verdict(self):
        # One valid row beside a null must not read as all-green, and the table must not rescue it.
        payload = [{"name": "build", "state": "SUCCESS", "bucket": "pass"}, None]
        code, out, err = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                        "--allow-no-machine-review",
                                        json_result=(0, json.dumps(payload), ""),
                                        table_result=(0, GREEN_TABLE, ""))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("object per check", err)

    def test_malformed_only_check_rows_exit_2_even_with_allow_no_checks(self):
        # --allow-no-checks forgives a PR with zero check runs, never a malformed list.
        for extra in [(), ("--allow-no-checks",)]:
            with self.subTest(extra=extra):
                code, out, err = self.gate_main(
                    "--verified-head", HEAD, "--gates-rc", "0", "--allow-no-machine-review",
                    *extra, json_result=(0, json.dumps([None]), ""),
                    table_result=(0, GREEN_TABLE, ""))
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("object per check", err)

    def test_a_table_only_green_read_blocks_and_the_opt_in_restores_it(self):
        # Round-5 class-closing rule: gh's table is a display format, not a contract, so a
        # table-only read is advisory. A green table blocks by default; only the documented
        # opt-in makes it authoritative again.
        code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                      "--allow-no-machine-review",
                                      table_result=(0, GREEN_TABLE, ""))
        self.assertEqual(code, 1)
        self.assertIn("checks: 2 total, 2 ok, 0 pending, 0 failing", out)
        self.assertIn("verdict: BLOCKED: checks unreadable", out)
        code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                      "--allow-no-machine-review", "--allow-table-only-checks",
                                      table_result=(0, GREEN_TABLE, ""))
        self.assertEqual(code, 0)
        self.assertIn("verdict: MERGE-OK", out)

    def test_the_opt_in_cannot_bypass_the_header_or_unknown_verdict_rules(self):
        for table in [(0, "build\tpass\nSTATUS\tNAME\n", ""), (0, "mystery\tunreleased\n", "")]:
            with self.subTest(table=table):
                code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                              "--allow-no-machine-review",
                                              "--allow-table-only-checks", table_result=table)
                self.assertEqual(code, 1)
                self.assertIn("verdict: BLOCKED: checks", out)

    def test_a_table_only_zero_check_read_blocks_and_the_opt_in_forgives_it(self):
        # The recognized "no checks reported" message arrives on the *table* path, so it is a
        # table-only read: advisory, blocked as `checks unreadable`. --allow-no-checks forgives a
        # *structured* zero-check read (see RealSubprocessBoundaryTests), never this one; the
        # opt-in makes the table authoritative, and only then does the zero-check flag apply.
        no_checks = (1, "", "no checks reported on the 'feature' branch")
        code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                     "--allow-no-machine-review", table_result=no_checks)
        self.assertEqual(code, 1)
        self.assertIn("checks: 0 total, 0 ok, 0 pending, 0 failing (no checks)", out)
        self.assertIn("verdict: BLOCKED: checks unreadable", out)
        code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                     "--allow-no-machine-review", "--allow-no-checks",
                                     table_result=no_checks)
        self.assertEqual(code, 1)
        self.assertIn("verdict: BLOCKED: checks unreadable", out)
        code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                     "--allow-no-machine-review", "--allow-table-only-checks",
                                     "--allow-no-checks", table_result=no_checks)
        self.assertEqual(code, 0)
        self.assertIn("verdict: MERGE-OK", out)

    def test_empty_fallback_table_blocks_main_and_needs_both_flags_to_merge(self):
        # The table is reached with a zero exit and empty stdout: a table-only read, not a
        # structured zero-check success. All four flag combinations are pinned, so the two opt-ins
        # are independent and an exchange of one for the other — reading the table opt-in as
        # --allow-no-checks, the conflation the harness mutates — cannot merge here: with neither
        # flag the read is unverifiable, with --allow-no-checks alone it is still unverifiable,
        # with the table opt-in alone the read is the zero-check state that only --allow-no-checks
        # forgives, and only both flags merge. The complete verdict line is compared, so
        # `BLOCKED: no checks` cannot pass as `BLOCKED: checks unreadable`.
        for extra, expected_code, expected_verdict in [
            ((), 1, "verdict: BLOCKED: checks unreadable"),
            (("--allow-no-checks",), 1, "verdict: BLOCKED: checks unreadable"),
            (("--allow-table-only-checks",), 1, "verdict: BLOCKED: no checks"),
            (("--allow-table-only-checks", "--allow-no-checks"), 0, "verdict: MERGE-OK"),
        ]:
            with self.subTest(flags=extra):
                code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                              "--allow-no-machine-review", *extra,
                                              json_result=JSON_FIELD_GONE,
                                              table_result=(0, "", ""))
                self.assertEqual(code, expected_code)
                self.assertEqual(
                    [line for line in out.splitlines() if line.startswith("verdict: ")],
                    [expected_verdict])
                self.assertEqual(
                    [line for line in out.splitlines() if line.startswith("checks: ")],
                    ["checks: 0 total, 0 ok, 0 pending, 0 failing (no checks)"])

    def test_unparseable_gh_output_exits_2_instead_of_guessing(self):
        code, out, err = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                        table_result=(8, "", "checks pending"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("pr-merge-check: checks pending", err)

    def test_missing_gh_binary_exits_2_with_one_stderr_line(self):
        # No gh on PATH is a tool error: exit 2 with one line, not a traceback and not a verdict.
        out, err = io.StringIO(), io.StringIO()
        argv = ["pr-merge-check.py", "7", "--repo", ".", "--verified-head", HEAD, "--gates-rc", "0"]
        missing = FileNotFoundError("[Errno 2] No such file or directory: 'gh'")
        with patch.object(subprocess, "run", side_effect=missing), \
             patch.object(sys, "argv", argv), redirect_stdout(out), redirect_stderr(err):
            code = gate.main()
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue().splitlines(),
                         ["pr-merge-check: [Errno 2] No such file or directory: 'gh'"])

    def test_name_prefixed_rows_reach_the_verdict_as_blocked(self):
        # A failing and a pending `NAME-required` row must both block main(), never merge.
        for table, expected_counts, expected_reason in [
            ((1, NAME_PREFIXED_TABLE, ""), "checks: 2 total, 1 ok, 0 pending, 1 failing", "checks"),
            ((8, NAME_PREFIXED_PENDING_TABLE, ""), "checks: 2 total, 1 ok, 1 pending, 0 failing",
             "checks pending"),
        ]:
            with self.subTest(table=table):
                code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                              "--allow-no-machine-review", table_result=table)
                self.assertEqual(code, 1)
                self.assertIn(expected_counts, out)
                self.assertIn(f"verdict: BLOCKED: {expected_reason}", out)

    def test_allow_no_checks_cannot_forgive_a_name_prefixed_row(self):
        code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                      "--allow-no-machine-review", "--allow-no-checks",
                                      table_result=(1, NAME_PREFIXED_TABLE, ""))
        self.assertEqual(code, 1)
        self.assertIn("verdict: BLOCKED: checks", out)

    def test_unparseable_output_exits_2_even_with_allow_no_checks(self):
        for table in [(1, "gh: Not Found (HTTP 404)\n", ""), (8, "", "checks pending")]:
            with self.subTest(table=table):
                code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                              "--allow-no-machine-review", "--allow-no-checks",
                                              table_result=table)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")

    def test_allow_no_checks_cannot_forgive_a_contradictory_or_absent_bucket(self):
        # The flag forgives zero check runs; a recognized bucket whose raw state disagrees, and a
        # row with no bucket at all, are reported checks and must both block.
        for rows, expected_counts in [
            ([{"name": "required", "state": "SUCCESS", "bucket": "fail"}],
             "checks: 1 total, 0 ok, 0 pending, 1 failing"),
            ([{}], "checks: 1 total, 0 ok, 1 pending, 0 failing"),
            ([{"name": "required", "state": "SUCCESS"}],
             "checks: 1 total, 0 ok, 1 pending, 0 failing"),
        ]:
            with self.subTest(rows=rows):
                code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                              "--allow-no-machine-review", "--allow-no-checks",
                                              json_result=(0, json.dumps(rows), ""),
                                              table_result=(0, GREEN_TABLE, ""))
                self.assertEqual(code, 1)
                self.assertIn(expected_counts, out)
                self.assertIn("verdict: BLOCKED", out)

    def test_allow_no_checks_cannot_forgive_a_pending_check(self):
        # Pending is a reported state, not an absent one: the flag must not reach it on either path.
        for json_result, table_result, expected_counts in [
            ((0, json.dumps([BUCKET_ROW]), ""), (0, "", ""),
             "checks: 1 total, 0 ok, 1 pending, 0 failing"),
            ((0, json.dumps([{"name": "build", "state": "SUCCESS", "bucket": "pass"}, BUCKET_ROW]),
              ""), (0, "", ""), "checks: 2 total, 1 ok, 1 pending, 0 failing"),
            (JSON_FIELD_GONE, (8, IN_FLIGHT_TABLE, ""),
             "checks: 2 total, 1 ok, 1 pending, 0 failing"),
            (JSON_FIELD_GONE, (0, IN_FLIGHT_TABLE, ""),
             "checks: 2 total, 1 ok, 1 pending, 0 failing"),
        ]:
            with self.subTest(json_result=json_result, table_result=table_result):
                code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                              "--allow-no-machine-review", "--allow-no-checks",
                                              json_result=json_result, table_result=table_result)
                self.assertEqual(code, 1)
                self.assertIn(expected_counts, out)
                self.assertIn("verdict: BLOCKED: checks pending", out)

    def test_a_reserved_column_name_row_reaches_the_verdict_as_blocked(self):
        # The reproduction: GREEN_TABLE plus a pending row named STATUS at exit 8 merged before,
        # because the row was dropped as a header. It must be counted and block.
        for row, exit_code, expected_counts, reason in [
            ("STATUS\tpending\n", 8, "checks: 3 total, 2 ok, 1 pending, 0 failing", "checks pending"),
            ("STATUS\tfail\n", 1, "checks: 3 total, 2 ok, 0 pending, 1 failing", "checks"),
        ]:
            with self.subTest(row=row):
                code, out, _ = self.gate_main("--verified-head", HEAD, "--gates-rc", "0",
                                              "--allow-no-machine-review",
                                              table_result=(exit_code, GREEN_TABLE + row, ""))
                self.assertEqual(code, 1)
                self.assertIn(expected_counts, out)
                self.assertIn(f"verdict: BLOCKED: {reason}", out)


class RealSubprocessBoundaryTests(unittest.TestCase):
    """sh()/sh_raw() stay real here; only subprocess.run() is faked.

    CheckFetchCliTests patches sh()/sh_raw() themselves, so a mutation inside sh_raw() — dropping
    the exit code, or turning a non-zero exit into an empty success — is invisible there. At the
    real boundary that mutation reads an unsupported JSON field as zero checks and merges under
    --allow-no-checks. These tests put the fake at subprocess.run() so the forwarding itself runs.
    """

    THREADS = json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}}}})

    def run_boundary(self, *, json_result, table_result, extra=(), repo=".", record=None,
                     api=None, comments=(), threads=THREADS, merge_result=(0, "", "")):
        calls = []
        view = {"state": "OPEN", "isDraft": False, "headRefOid": HEAD,
                "headRefName": "feature", "baseRefName": "release/next"}

        def fake_run(cmd, cwd=None, capture_output=False, text=False, **_options):
            calls.append(list(cmd))
            if record is not None:
                record.append((list(cmd), cwd))
            if cmd[:1] == ["git"]:
                branch = "--abbrev-ref" in cmd
                return subprocess.CompletedProcess(cmd, 0, "feature" if branch else HEAD, "")
            if cmd[:3] == ["gh", "pr", "checks"]:
                return subprocess.CompletedProcess(cmd, *(json_result if "--json" in cmd
                                                          else table_result))
            if cmd[:3] == ["gh", "pr", "view"]:
                fields = cmd[cmd.index("--json") + 1].split(",")
                return subprocess.CompletedProcess(cmd, 0,
                                                   json.dumps({key: view[key] for key in fields}), "")
            if cmd[:3] == ["gh", "pr", "merge"]:
                return subprocess.CompletedProcess(cmd, *merge_result)
            if cmd[:3] == ["gh", "repo", "view"]:
                return subprocess.CompletedProcess(cmd, 0, "fixture-owner/fixture-repo", "")
            if cmd[:3] == ["gh", "api", "graphql"]:
                return subprocess.CompletedProcess(cmd, 0, threads, "")
            if cmd[:2] == ["gh", "api"]:
                if "/issues/7/comments?" in cmd[2]:
                    return subprocess.CompletedProcess(cmd, 0, json.dumps(comments), "")
                if api is not None:
                    return subprocess.CompletedProcess(cmd, *api[tuple(cmd[2:])])
            raise AssertionError(f"unexpected command: {cmd}")

        out, err = io.StringIO(), io.StringIO()
        argv = ["pr-merge-check.py", "7", "--repo", repo, *extra]
        with patch.object(subprocess, "run", side_effect=fake_run), \
             patch.object(sys, "argv", argv), redirect_stdout(out), redirect_stderr(err):
            code = gate.main()
        return code, out.getvalue(), err.getvalue(), calls

    REPO_API = ("repos/fixture-owner/fixture-repo", "-q", ".allow_auto_merge")
    RULES_API = ("repos/fixture-owner/fixture-repo/rules/branches/release%2Fnext",
                 "--paginate", "--slurp")
    CLASSIC_API = ("repos/fixture-owner/fixture-repo/branches/release%2Fnext"
                   "/protection/required_status_checks",)
    REQUIRED_RULE = {"type": "required_status_checks",
                     "parameters": {"required_status_checks": [{"context": "build"}]}}

    def run_auto(self, api, *, bucket="pending", comments=None, verified_head=HEAD,
                 gates_rc="0", threads=THREADS, merge_result=(0, "", "")):
        code, out, err, calls = self.run_boundary(
            json_result=(0, json.dumps([{"name": "build", "bucket": bucket}]), ""),
            table_result=(0, "", ""), api=api,
            comments=[comment(clean_evidence())] if comments is None else comments,
            extra=("--auto", "--verified-head", verified_head, "--gates-rc", gates_rc, "--json"),
            threads=threads, merge_result=merge_result)
        return code, json.loads(out) if out else {}, err, calls

    def test_auto_merge_uses_the_full_github_head_and_leaves_checks_to_github(self):
        for protection in (
            {self.RULES_API: (0, json.dumps([[], [self.REQUIRED_RULE]]), "")},
            {self.RULES_API: (0, "[[]]", ""),
             self.CLASSIC_API: (0, '{"contexts":[],"checks":[{"context":"build"}]}', "")},
        ):
            with self.subTest(protection=protection):
                code, facts, err, calls = self.run_auto({
                    self.REPO_API: (0, "true", ""), **protection,
                })
                self.assertEqual((code, facts.get("verdict"), err), (0, "MERGE-QUEUED", ""))
                self.assertEqual([cmd for cmd in calls if cmd[:2] == ["gh", "pr"]
                                  and cmd[2] in ("checks", "merge")],
                                 [["gh", "pr", "merge", "7", "--auto", "--squash",
                                   "--match-head-commit", HEAD]])

    def test_auto_unavailable_retains_the_manual_check_gate(self):
        for capability in (
            {self.REPO_API: (0, "false", "")},
            {self.REPO_API: (0, "true", ""),
             self.RULES_API: (0, '[[{"type":"required_status_checks","parameters":'
                                 '{"required_status_checks":[]}}]]', ""),
             self.CLASSIC_API: (1, "", "HTTP 404")},
        ):
            for bucket, expected in (("pending", (1, "BLOCKED")), ("pass", (0, "MERGE-OK"))):
                with self.subTest(capability=capability, bucket=bucket):
                    code, facts, err, calls = self.run_auto(capability, bucket=bucket)
                    self.assertEqual((code, facts.get("verdict")), expected)
                    self.assertEqual(err, "")
                    self.assertTrue(any(cmd[:3] == ["gh", "pr", "checks"] for cmd in calls))
                    self.assertFalse(any(cmd[:3] == ["gh", "pr", "merge"] for cmd in calls))

    def test_auto_still_requires_gdd_evidence(self):
        capability = {self.REPO_API: (0, "true", ""),
                      self.RULES_API: (0, json.dumps([[self.REQUIRED_RULE]]), "")}
        threads = json.loads(self.THREADS)
        threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"] = [
            {"isResolved": False}
        ]
        for options in ({"comments": []}, {"verified_head": HEAD[:8]}, {"gates_rc": "1"},
                        {"threads": json.dumps(threads)}):
            with self.subTest(options=options):
                code, facts, _, calls = self.run_auto(capability, **options)
                self.assertEqual((code, facts.get("verdict")), (1, "BLOCKED"))
                self.assertFalse(any(cmd[:3] == ["gh", "pr", "merge"] for cmd in calls))

    def test_auto_merge_submission_failure_is_not_permission_to_merge_manually(self):
        code, facts, err, calls = self.run_auto(
            {self.REPO_API: (0, "true", ""),
             self.RULES_API: (0, json.dumps([[self.REQUIRED_RULE]]), "")},
            merge_result=(1, "", "head changed"))
        self.assertEqual((code, facts), (2, {}))
        self.assertIn("head changed", err)
        self.assertEqual(sum(cmd[:3] == ["gh", "pr", "merge"] for cmd in calls), 1)

    def test_sh_raw_forwards_exit_code_and_both_streams_verbatim(self):
        def fake_run(cmd, cwd=None, capture_output=False, text=False, **_options):
            return subprocess.CompletedProcess(cmd, 8, "stdout text", "stderr text")

        with patch.object(subprocess, "run", side_effect=fake_run):
            self.assertEqual(gate.sh_raw(["gh", "pr", "checks", "7"]),
                             (8, "stdout text", "stderr text"))
            # sh() makes a non-zero exit an error; sh_raw() hands it back as data.
            with self.assertRaises(gate.GateError) as raised:
                gate.sh(["gh", "pr", "checks", "7"])
        self.assertEqual(str(raised.exception), "stderr text")

    def test_nonzero_json_exit_falls_through_to_the_table_at_the_real_boundary(self):
        code, out, err, calls = self.run_boundary(
            json_result=JSON_FIELD_GONE,
            table_result=(8, IN_FLIGHT_TABLE, ""),
            extra=("--verified-head", HEAD, "--gates-rc", "0", "--allow-no-machine-review"))
        self.assertEqual(err, "")
        self.assertEqual(code, 1)
        self.assertIn("checks: 2 total, 1 ok, 1 pending, 0 failing", out)
        self.assertIn("verdict: BLOCKED: checks pending", out)
        checks_calls = [call for call in calls if call[:3] == ["gh", "pr", "checks"]]
        self.assertEqual(len(checks_calls), 2)
        self.assertIn("--json", checks_calls[0])
        self.assertNotIn("--json", checks_calls[1])

    def test_a_command_error_cannot_become_an_allowed_zero_check_result(self):
        # A real failure (exit 1, no table) must exit 2 even with --allow-no-checks: only a
        # successful read of zero check runs is forgivable.
        code, out, err, _ = self.run_boundary(
            json_result=JSON_FIELD_GONE,
            table_result=(1, "gh: Not Found (HTTP 404)\n", ""),
            extra=("--verified-head", HEAD, "--gates-rc", "0", "--allow-no-machine-review",
                   "--allow-no-checks"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(err.splitlines(), ["pr-merge-check: gh: Not Found (HTTP 404)"])

    def test_a_successful_empty_read_is_genuinely_zero_checks_and_the_flag_forgives_it(self):
        code, out, err, _ = self.run_boundary(
            json_result=(0, "[]", ""),
            table_result=(0, "", ""),
            extra=("--verified-head", HEAD, "--gates-rc", "0", "--allow-no-machine-review",
                   "--allow-no-checks"))
        self.assertEqual(err, "")
        self.assertEqual(code, 0)
        self.assertIn("checks: 0 total, 0 ok, 0 pending, 0 failing (no checks)", out)
        self.assertIn("verdict: MERGE-OK", out)

    # The non-zero table exit is CI state only while the parsed rows report it. A truncated row
    # (the line without a tab) does not, so the table looks all green under exit 8; and a command
    # error on stderr beside a green table is ignored once passing rows exist. Both read as
    # MERGE-OK before the guard below; a non-zero exit is evidence the read was incomplete.
    TRUNCATED_TABLE = "build\tpass\t1s\thttps://example/1\t\nrequired\n"

    def test_a_nonzero_exit_with_a_partially_read_table_exits_2(self):
        code, out, err, _ = self.run_boundary(
            json_result=JSON_FIELD_GONE,
            table_result=(8, self.TRUNCATED_TABLE, ""),
            extra=("--verified-head", HEAD, "--gates-rc", "0", "--allow-no-machine-review"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("all-green table", err)

    def test_a_nonzero_exit_with_an_all_green_table_is_not_an_ignored_command_error(self):
        code, out, err, _ = self.run_boundary(
            json_result=JSON_FIELD_GONE,
            table_result=(1, GREEN_TABLE, "error reading checks: unexpected EOF"),
            extra=("--verified-head", HEAD, "--gates-rc", "0", "--allow-no-machine-review"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("error reading checks: unexpected EOF", err)
        self.assertIn("all-green table", err)

    def test_allow_no_checks_cannot_forgive_a_partial_read(self):
        for table in [(8, self.TRUNCATED_TABLE, ""),
                      (1, GREEN_TABLE, "error reading checks: unexpected EOF")]:
            with self.subTest(table=table):
                code, out, err, _ = self.run_boundary(
                    json_result=JSON_FIELD_GONE,
                    table_result=table,
                    extra=("--verified-head", HEAD, "--gates-rc", "0",
                           "--allow-no-machine-review", "--allow-no-checks"))
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("all-green table", err)

    def test_sh_raw_preserves_surrounding_whitespace_and_newlines_verbatim(self):
        # The callers re-read these bytes — the "no checks reported" match, the comment JSON — so
        # a `.strip()` inside sh_raw() must be visible here. The fixture carries padding in both
        # streams, or the normalization would be undetectable.
        stdout = "  leading\nbody\n\n"
        stderr = "\ttrailing \n\n"

        def fake_run(cmd, cwd=None, capture_output=False, text=False, **_options):
            return subprocess.CompletedProcess(cmd, 7, stdout, stderr)

        with patch.object(subprocess, "run", side_effect=fake_run):
            self.assertEqual(gate.sh_raw(["gh", "pr", "checks", "7"]),
                             (7, stdout, stderr))

    def test_the_repository_the_operator_named_reaches_every_child(self):
        # The fake above accepts `cwd`; this is the test that notices it being dropped. The
        # repository is deliberately distinct from the runner's directory, so a `cwd` the gate
        # failed to forward cannot coincide with the expected value. Every `gh` call must run in
        # that directory and every `git` call must carry it as `-C <path>` — each surface
        # forwards the repository a different way, and `gh` inspecting the caller's repository
        # instead of the one under test silently invalidates the gate's whole evidence base.
        repo = os.path.realpath(tempfile.mkdtemp(prefix="gdd-boundary-repo-"))
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        self.assertNotEqual(repo, os.path.realpath(os.getcwd()))
        record = []
        code, out, err, _ = self.run_boundary(
            json_result=(0, "[]", ""), table_result=(0, "", ""), repo=repo,
            extra=("--verified-head", HEAD, "--gates-rc", "0", "--allow-no-machine-review",
                   "--allow-no-checks"), record=record)
        self.assertEqual(err, "")
        self.assertEqual(code, 0)
        gh_calls = [(cmd, cwd) for cmd, cwd in record if cmd[:1] == ["gh"]]
        self.assertTrue(gh_calls)
        for cmd, cwd in gh_calls:
            self.assertEqual(cwd, repo, f"gh ran outside the repository under test: {cmd}")
        git_calls = [cmd for cmd, _ in record if cmd[:1] == ["git"]]
        self.assertTrue(git_calls)
        for cmd in git_calls:
            self.assertIn(repo, cmd, f"git did not carry the repository under test: {cmd}")

    def test_forwarding_of_directory_text_and_capture_at_a_real_child(self):
        # No fake at all: sh_raw() runs a real child, and the child reports the directory it ran
        # in. That is the honest boundary probe — one assertion covers three forwards at once:
        # the working directory (the child's getcwd()), text mode (bytes would not equal the
        # string) and captured output (an inherited stdio would hand back nothing).
        repo = os.path.realpath(tempfile.mkdtemp(prefix="gdd-boundary-probe-"))
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        self.assertNotEqual(repo, os.path.realpath(os.getcwd()))
        code, stdout, stderr = gate.sh_raw(
            [sys.executable, "-c", "import os; print(os.getcwd())"], cwd=repo)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(stdout.strip(), repo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
