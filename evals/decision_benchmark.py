#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Run the multi-domain decision benchmark across claim-audit, ci-triage, tool-risk, and skill-review.

Validates evals/decision-cases.json against evals/decision-rubrics.json offline when
invoked with --validate-only, or executes the live suite against a configured
endpoint (`--api decisions` or `--api chat-completions`).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EVALS = Path(__file__).resolve().parent
ROOT = EVALS.parent
sys.path.insert(0, str(ROOT / "scripts"))

import skill_config as sc  # noqa: E402

try:
    import decision_judge as dj  # noqa: E402
except ModuleNotFoundError as error:
    if error.name != "decision_judge":
        raise
    from evals import decision_judge as dj  # noqa: E402

CASES_PATH = EVALS / "decision-cases.json"
MAX_WORKERS = 5


def load_benchmark_cases(path: Path | None = None) -> list[dict]:
    target = CASES_PATH if path is None else Path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{target} has no non-empty cases list")
    return cases


def validate_cases(cases: list[dict], rubrics: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for idx, case in enumerate(cases):
        cid = case.get("id", f"cases[{idx}]")
        if cid in seen:
            errors.append(f"duplicate case id {cid!r}")
        seen.add(cid)
        preset_name = case.get("preset")
        if preset_name not in rubrics:
            errors.append(f"{cid}: unknown preset {preset_name!r}")
            continue
        questions_by_name = {q["name"]: q for q in rubrics[preset_name]["questions"]}
        expected = case.get("expected")
        if not isinstance(expected, dict) or not expected:
            errors.append(f"{cid}: expected must be a non-empty object")
            continue
        for qname, exp_val in expected.items():
            if qname not in questions_by_name:
                errors.append(f"{cid}: expected key {qname!r} not in preset {preset_name!r}")
                continue
            q = questions_by_name[qname]
            if q["type"] == "predicate" and not isinstance(exp_val, bool):
                errors.append(f"{cid}.{qname}: predicate expectation must be boolean")
            elif q["type"] == "choice":
                valid_choices = {c["value"] for c in q["choices"]}
                if exp_val not in valid_choices:
                    errors.append(f"{cid}.{qname}: {exp_val!r} not in {sorted(valid_choices)}")
    return errors


def grade_case(case: dict, result: dict) -> dict:
    answers = result.get("answers", {})
    checks: dict[str, dict] = {}
    all_passed = True
    for key, want in case["expected"].items():
        ans = answers.get(key)
        got = ans.get("value") if isinstance(ans, dict) else None
        ok = got == want
        if not ok:
            all_passed = False
        checks[key] = {
            "want": want,
            "got": got,
            "passed": ok,
            "confidence": ans.get("confidence") if isinstance(ans, dict) else None,
            "probability": ans.get("probability") if isinstance(ans, dict) else None,
        }
    return {
        "id": case["id"],
        "preset": case["preset"],
        "passed": all_passed,
        "elapsed_ms": result.get("elapsed_ms", 0.0),
        "usage": result.get("usage", {}),
        "checks": checks,
    }


def run_suite(
    cases: list[dict],
    rubrics: dict[str, dict],
    *,
    base_url: str,
    model: str,
    api: str,
    effort: str = dj.DEFAULT_EFFORT,
    api_key: str | None = None,
) -> dict:
    def _one(case: dict) -> dict:
        questions = rubrics[case["preset"]]["questions"]
        try:
            res = dj.evaluate_one(
                base_url,
                model,
                questions,
                case["state"],
                api=api,
                effort=effort,
                api_key=api_key,
            )
            return grade_case(case, res)
        except Exception as error:
            return {
                "id": case["id"],
                "preset": case["preset"],
                "passed": False,
                "elapsed_ms": 0.0,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "error": str(error),
                "checks": {},
            }

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        rows = list(executor.map(_one, cases))
    wall_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    by_preset: dict[str, dict] = {}
    total_checks = 0
    passed_checks = 0
    for row in rows:
        p = row["preset"]
        bucket = by_preset.setdefault(p, {"passed_cases": 0, "total_cases": 0, "passed_checks": 0, "total_checks": 0})
        bucket["total_cases"] += 1
        if row["passed"]:
            bucket["passed_cases"] += 1
        for chk in row.get("checks", {}).values():
            bucket["total_checks"] += 1
            total_checks += 1
            if chk["passed"]:
                bucket["passed_checks"] += 1
                passed_checks += 1

    return {
        "model": model,
        "api": api,
        "effort": effort if api == dj.API_CHAT_COMPLETIONS else None,
        "passed_cases": sum(1 for r in rows if r["passed"]),
        "total_cases": len(rows),
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "wall_ms": wall_ms,
        "mean_case_ms": round(sum(r["elapsed_ms"] for r in rows) / max(len(rows), 1), 1),
        "total_input_tokens": sum(r.get("usage", {}).get("input_tokens", 0) for r in rows),
        "total_output_tokens": sum(r.get("usage", {}).get("output_tokens", 0) for r in rows),
        "by_preset": by_preset,
        "results": rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="validate cases and rubrics offline without network")
    parser.add_argument("--preset", default=None, help="filter to a single preset")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL")
    parser.add_argument("--model", default=None, help="judge model ID")
    parser.add_argument("--api", default=None, help=f"wire API: {', '.join(dj.SUPPORTED_APIS)} (default: {dj.DEFAULT_API})")
    parser.add_argument("--effort", default=None, help=f"reasoning effort for chat-completions (default: {dj.DEFAULT_EFFORT})")
    args = parser.parse_args(argv)

    rubrics = dj.load_rubrics()
    cases = load_benchmark_cases()
    errors = validate_cases(cases, rubrics)
    if errors:
        for err in errors:
            print(f"decision_benchmark: {err}", file=sys.stderr)
        return 1
    if args.validate_only:
        print(f"PASS: {len(cases)} decision benchmark cases valid across {len(rubrics)} presets")
        return 0

    if args.preset:
        cases = [c for c in cases if c["preset"] == args.preset]
        if not cases:
            print(f"decision_benchmark: no cases for preset {args.preset!r}", file=sys.stderr)
            return 2

    base_url = sc.resolve(dj.SKILL, dj.KEY_BASE_URL, flag=args.base_url)
    model = sc.resolve(dj.SKILL, dj.KEY_MODEL, flag=args.model)
    api = sc.resolve(dj.SKILL, dj.KEY_API, flag=args.api, default=dj.DEFAULT_API)
    effort = sc.resolve(dj.SKILL, dj.KEY_EFFORT, flag=args.effort, default=dj.DEFAULT_EFFORT)
    api_key = sc.resolve(dj.SKILL, dj.KEY_API_KEY)

    if not base_url or not model:
        print("decision_benchmark: base_url and model are required", file=sys.stderr)
        return 2

    summary = run_suite(
        cases,
        rubrics,
        base_url=base_url,
        model=model,
        api=api,
        effort=effort,
        api_key=api_key,
    )
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        for row in summary["results"]:
            mark = "PASS" if row["passed"] else "FAIL"
            detail = ", ".join(
                f"{k}={v['got']!r} (want {v['want']!r})"
                for k, v in row.get("checks", {}).items()
            ) or row.get("error", "")
            print(f"{mark} [{row['preset']}] {row['id']} ({row['elapsed_ms']:.0f}ms): {detail}")
        print(
            f"\nSummary ({summary['model']} via {summary['api']}): "
            f"{summary['passed_cases']}/{summary['total_cases']} cases passed "
            f"({summary['passed_checks']}/{summary['total_checks']} checks), "
            f"wall={summary['wall_ms']:.0f}ms, mean={summary['mean_case_ms']:.0f}ms/case, "
            f"tokens={summary['total_input_tokens']} in / {summary['total_output_tokens']} out"
        )
    return 0 if summary["passed_cases"] == summary["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
