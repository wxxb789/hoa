#!/usr/bin/env python3
"""Offline check for ghc_search.parse — no network. Run: python test_ghc_search.py"""
import json
import pathlib
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from ghc_search import SearchError, build_body, main, parse, strip_citations  # noqa: E402

FIXTURE = json.loads((pathlib.Path(__file__).parent / "fixture_web_response.json").read_text())


class T(unittest.TestCase):
    def capture_request(self, argv):
        requests = []

        with patch(
            "ghc_search.post",
            side_effect=lambda endpoint, body, timeout: requests.append(body) or FIXTURE,
        ), redirect_stdout(StringIO()):
            self.assertEqual(main([*argv, "--json"]), 0)

        self.assertEqual(len(requests), 1)
        return requests[0]

    def test_cli_uses_per_engine_defaults(self):
        gpt = self.capture_request(["gpt", "q"])
        self.assertEqual(gpt["model"], "gpt-5.6-luna")
        self.assertEqual(gpt["reasoning"], {"effort": "high"})

        x = self.capture_request(["x", "q"])
        self.assertEqual(x["model"], "grok-4.5")
        self.assertEqual(x["reasoning"], {"effort": "medium"})

    def test_cli_preserves_explicit_model_and_effort_overrides(self):
        gpt = self.capture_request(["gpt", "q", "--model", "custom-gpt", "--effort", "low"])
        self.assertEqual(gpt["model"], "custom-gpt")
        self.assertEqual(gpt["reasoning"], {"effort": "low"})

        x = self.capture_request(["x", "q", "--model", "custom-x", "--effort", "high"])
        self.assertEqual(x["model"], "custom-x")
        self.assertEqual(x["reasoning"], {"effort": "high"})

    def test_real_response(self):
        answer, sources = parse(FIXTURE)
        # Citation markup stripped out of the answer.
        self.assertEqual(answer, "The capital of France is Paris.")
        self.assertNotIn("[[1]]", answer)
        # The Paris URL is in the annotation, the inline markup, AND the
        # web_search_call sources — it must appear exactly once.
        urls = [s["url"] for s in sources]
        self.assertEqual(urls.count("https://en.wikipedia.org/wiki/Paris"), 1)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(all(u.startswith("http") for u in urls))

    def test_strip_both_citation_styles(self):
        # grok-4.5 style and gpt-5.4 style.
        self.assertEqual(strip_citations("Paris.[[1]](https://a.test/x)")[0], "Paris.")
        self.assertEqual(strip_citations("Paris. ([a.test](https://a.test/x))")[0], "Paris.")

    def test_dedup_ignores_trailing_slash_and_fragment(self):
        payload = {"status": "completed", "output": [
            {"type": "web_search_call", "action": {"sources": [
                {"url": "https://a.test/p/"}, {"url": "https://a.test/p#frag"}, {"url": "ftp://a.test/x"},
                {"url": ""}, {"url": None}]}},
            {"type": "message", "content": [{"text": "hi", "annotations": [
                {"type": "url_citation", "url": "https://a.test/p", "title": "P"}]}]}]}
        _, sources = parse(payload)
        self.assertEqual([s["url"] for s in sources], ["https://a.test/p"])

    def test_rejects_non_completed(self):
        with self.assertRaises(SearchError):
            parse({"status": "incomplete", "output": FIXTURE["output"]})

    def test_token_truncation_keeps_the_answer(self):
        # gpt-5.4 spends heavily on reasoning and can hit the ceiling after
        # writing a usable answer -- measured. Keep it, flagged, rather than
        # discarding a real result.
        payload = dict(FIXTURE, status="incomplete",
                       incomplete_details={"reason": "max_output_tokens"})
        answer, sources = parse(payload)
        self.assertIn("Paris", answer)
        self.assertIn("[truncated", answer)
        self.assertTrue(sources)
        # A truncation with no message at all is still an error, not a blank pass.
        with self.assertRaises(SearchError):
            parse({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                   "output": [{"type": "web_search_call", "action": {}}]})

    def test_rejects_missing_message(self):
        with self.assertRaises(SearchError):
            parse({"status": "completed", "output": [{"type": "web_search_call", "action": {}}]})

    def test_handles_are_named_in_the_prompt(self):
        # allowed_x_handles alone does not steer the model -- measured: with a
        # terse query it asks who to look for instead of searching.
        body = build_body("newest post", "x", model="grok-4.5", effort="medium",
                          max_tokens=512, handles=["SpaceXAI"])
        self.assertIn("@SpaceXAI", body["input"][0]["content"])
        self.assertEqual(body["tools"][0]["allowed_x_handles"], ["SpaceXAI"])
        # A handle the caller already wrote is not appended twice.
        body = build_body("latest from @SpaceXAI", "x", model="grok-4.5", effort="medium",
                          max_tokens=512, handles=["SpaceXAI"])
        self.assertEqual(body["input"][0]["content"].count("SpaceXAI"), 1)
        # Web search leaves the query untouched.
        body = build_body("q", "gpt", model="gpt-5.6-luna", effort="medium", max_tokens=512)
        self.assertEqual(body["input"][0]["content"], "q")

    def test_effort_and_engine_shape(self):
        x = build_body("q", "x", model="grok-4.5", effort="high", max_tokens=512,
                       excluded_handles=["spam"], from_date="2026-08-01", to_date="2026-08-14")
        self.assertEqual(x["reasoning"], {"effort": "high"})
        self.assertEqual(x["tools"][0]["type"], "x_search")
        self.assertEqual(x["tools"][0]["excluded_x_handles"], ["spam"])
        self.assertEqual(x["tools"][0]["from_date"], "2026-08-01")

        g = build_body("q", "gpt", model="gpt-5.6-luna", effort="low", max_tokens=512,
                       domains=["a.test"], blocked_domains=["b.test"],
                       context_size="low", country="US")
        self.assertEqual(g["tools"][0]["type"], "web_search")
        self.assertEqual(g["tools"][0]["filters"],
                         {"allowed_domains": ["a.test"], "blocked_domains": ["b.test"]})
        self.assertEqual(g["tools"][0]["search_context_size"], "low")
        self.assertEqual(g["tools"][0]["user_location"]["country"], "US")
        # Absent options add no keys -- the proxy echoes back whatever it accepts,
        # so sending empty ones would muddy that signal.
        bare = build_body("q", "gpt", model="m", effort="medium", max_tokens=512)
        self.assertEqual(set(bare["tools"][0]), {"type"})

    def test_engine_is_required_and_flags_are_scoped(self):
        for argv in (["q"], ["web", "q"], []):
            with self.assertRaises(SystemExit):
                main(argv)
        # A gpt-only flag on the x engine is rejected before any network call.
        with self.assertRaises(SystemExit):
            main(["x", "q", "--domain", "a.test"])
        with self.assertRaises(SystemExit):
            main(["gpt", "q", "--handle", "someone"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
