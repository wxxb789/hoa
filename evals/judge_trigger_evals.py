#!/usr/bin/env python3
"""Run the LLM-judge pass over evals/trigger-cases.json (needs ghc-proxy).

Offline structure validation lives in run_trigger_evals.py; this script does
the judge pass: build the artifact catalog, ask a fresh-context judge which
artifact each request routes to, and report per-case pass/fail.

Usage: python evals/judge_trigger_evals.py [--limit N] [--json]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent
ROOT = EVALS.parent
GHC_SEARCH = ROOT / "skills" / "ghc-search" / "scripts" / "ghc_search.py"

spec = importlib.util.spec_from_file_location("generate_index", ROOT / "scripts" / "generate_index.py")
gi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gi)

JUDGE_MODEL = "gpt-5.6-luna"


def catalog_text() -> str:
    rows = gi.collect()
    lines = []
    for r in rows:
        lines.append(f"- {r['name']} ({r['type']}): {r['note_en']}")
    return "\n".join(lines)


def judge_one(ghc_search, catalog: str, request: str) -> str:
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

    sys.path.insert(0, str(GHC_SEARCH.parent))
    import ghc_search

    cases = json.loads((EVALS / "trigger-cases.json").read_text(encoding="utf-8"))["cases"]
    if args.limit:
        cases = cases[: args.limit]
    catalog = catalog_text()

    results = []
    for case in cases:
        try:
            pick = judge_one(ghc_search, catalog, case["request"])
            passed = pick in case["must_pick"]
        except ghc_search.SearchError as exc:
            pick, passed = f"error: {exc}", False
        results.append({"id": case["id"], "pick": pick,
                        "must_pick": case["must_pick"], "passed": passed})
        if not args.json:
            mark = "PASS" if passed else "FAIL"
            print(f"{mark} {case['id']}: picked {pick!r} (want {case['must_pick']})")

    passed = sum(r["passed"] for r in results)
    if args.json:
        print(json.dumps({"passed": passed, "total": len(results), "results": results},
                         indent=2, ensure_ascii=False))
    else:
        print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
