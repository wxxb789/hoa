import argparse
import json
import sys
from pathlib import Path

from ..config import EndpointNotConfigured, resolve_endpoint
from .client import evaluate_one
from .rubric import load_presets


def _skip(reason: str) -> int:
    print(json.dumps({"skipped": True, "reason": reason}))
    return 0


def _decide(args: argparse.Namespace) -> int:
    presets = load_presets(args.rubrics_file)
    if args.list_presets:
        listing = {name: {"description": preset.get("description", ""),
                          "questions": [q["name"] for q in preset["questions"]]}
                   for name, preset in presets.items()}
        print(json.dumps(listing, indent=2, ensure_ascii=False))
        return 0
    if not args.preset:
        raise ValueError("--preset is required unless --list-presets is passed")
    if args.state is None and args.state_file is None:
        raise ValueError("supply exactly one of --state or --state-file")

    try:
        endpoint = resolve_endpoint("rubric-judge", args.base_url, args.model, args.api, args.effort, args.workers,
                                    fallback_prefixes=("GHC_DECISIONS", "EVALS"))
    except EndpointNotConfigured:
        if args.if_configured:
            return _skip("rubric-judge is not configured (set RUBRIC_JUDGE_BASE_URL and RUBRIC_JUDGE_MODEL to opt in)")
        raise
    if args.preset not in presets:
        raise ValueError(f"unknown preset {args.preset!r}; available: {sorted(presets)}")

    raw = args.state_file.read_text(encoding="utf-8") if args.state_file else args.state
    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        state = raw
    try:
        report = evaluate_one(endpoint.base_url, endpoint.model, presets[args.preset]["questions"], state,
                              **endpoint.request_options())
    except (OSError, RuntimeError, ValueError) as exc:
        if args.if_configured:
            return _skip(f"endpoint unreachable or failed: {exc}")
        print(f"hoa decide: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    decide = subparsers.add_parser("decide", help="classify state using a decision rubric preset")
    decide.add_argument("--list-presets", action="store_true", help="list preset names and questions and exit")
    decide.add_argument("--if-configured", action="store_true", help="emit skipped JSON if the endpoint is unavailable")
    decide.add_argument("--preset", help="rubric preset name")
    state = decide.add_mutually_exclusive_group()
    state.add_argument("--state", help="inline JSON or text state")
    state.add_argument("--state-file", type=Path, help="JSON or text state file")
    decide.add_argument("--rubrics-file", type=Path, help="override the bundled preset file")
    decide.add_argument("--base-url", help="OpenAI-compatible /v1 base URL")
    decide.add_argument("--model", help="endpoint model identifier")
    decide.add_argument("--api", help="decisions or chat-completions (default: decisions)")
    decide.add_argument("--effort", help="chat-completions reasoning effort (default: low)")
    decide.add_argument("--workers", type=int, help="configured endpoint worker count")
    decide.set_defaults(func=_decide)
