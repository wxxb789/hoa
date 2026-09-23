#!/usr/bin/env python3
"""Run the LLM-judge pass over evals/trigger-cases.json (needs ghc-proxy).

Offline structure validation lives in run_trigger_evals.py; this script does
the judge pass: build the artifact catalog, ask a fresh-context judge which
artifact each request routes to, and report per-case pass/fail.

Usage: python evals/judge_trigger_evals.py [--limit N] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EVALS = Path(__file__).resolve().parent
ROOT = EVALS.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "ghc-search" / "scripts"))

import generate_index as gi  # noqa: E402
import ghc_search  # noqa: E402

JUDGE_MODEL = "gpt-5.6-luna"
MAX_WORKERS = 5


def catalog_text() -> str:
    return "\n".join(
        f"- {r['name']} ({r['type']}): {r['note_en']}" for r in gi.collect()
    )


def judge_one(catalog: str, request: str) -> str:
    prompt = (
        "You are routing a user request to exactly one artifact from this catalog.\n\n"
        f"Catalog:\n{catalog}\n\n"
        f"User request: {request}\n\n"
        "Reply with ONLY the artifact name from the catalog, nothing else."
    )
    body = ghc_search.build_body(prompt, "gpt", model=JUDGE_MODEL, effort="low",
                                 max_tokens=2048)
    payload = ghc_search.post(ghc_search.default_endpoint(), body, 120.0)
    answer, _sources = ghc_search.parse(payload)
    return answer.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="judge only the first N cases")
    ap.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = ap.parse_args()

    cases = json.loads((EVALS / "trigger-cases.json").read_text(encoding="utf-8"))["cases"]
    if args.limit:
        cases = cases[: args.limit]
    catalog = catalog_text()

    def run_case(case: dict) -> dict:
        try:
            pick = judge_one(catalog, case["request"])
            passed = pick in case["must_pick"]
        except ghc_search.SearchError as exc:
            pick, passed = f"error: {exc}", False
        result = {"id": case["id"], "pick": pick,
                  "must_pick": case["must_pick"], "passed": passed}
        if not args.json:
            mark = "PASS" if passed else "FAIL"
            print(f"{mark} {case['id']}: picked {pick!r} (want {case['must_pick']})",
                  flush=True)
        return result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(run_case, cases))

    passed = sum(r["passed"] for r in results)
    if args.json:
        print(json.dumps({"passed": passed, "total": len(results), "results": results},
                         indent=2, ensure_ascii=False))
    else:
        print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
