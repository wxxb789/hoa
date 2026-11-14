#!/usr/bin/env python3
"""Offline schema, generator, and merge-gate regression tests; no GitHub/LLM calls.

Run: python skills/gdd/scripts/tests/test_review_evidence.py
"""

from contextlib import redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from machine_review import (  # noqa: E402
    DEFAULT_MARKER, EvidenceError, evidence_comment, make_evidence, parse_marker,
    report_digest, review_facts,
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
        return subprocess.run([sys.executable, str(SCRIPTS / "review-evidence.py"), *args],
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


class MergeGateIntegrationTests(unittest.TestCase):
    def evaluate(self, evidence=None, checks=None, threads=None, gates_rc=0, verified_head=HEAD):
        view = {"state": "OPEN", "isDraft": False, "headRefOid": HEAD, "headRefName": "feature"}
        responses = [HEAD, "feature", json.dumps(view), "fixture-owner/fixture-repo"]
        with patch.object(gate, "sh", side_effect=responses), \
             patch.object(gate, "fetch_checks", return_value=checks if checks is not None else
                          [{"state": "COMPLETED", "conclusion": "SUCCESS"}]), \
             patch.object(gate, "fetch_issue_comments", return_value=[comment(evidence or clean_evidence())]), \
             patch.object(gate, "fetch_review_threads", return_value=threads or []):
            return gate.evaluate(1, ".", gates_rc, verified_head=verified_head)

    def test_complete_clean_evidence_with_other_clauses_passes(self):
        facts, reasons = self.evaluate()
        self.assertEqual(reasons, [])
        self.assertTrue(facts["review"]["pass"])

    def test_evidence_does_not_bypass_checks_threads_local_gates_or_head(self):
        cases = [({"checks": []}, "no checks"),
                 ({"checks": [{"state": "PENDING"}]}, "checks"),
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
