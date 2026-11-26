#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Run an eval rubric with the EVALS_* endpoint configuration.

Resolution order: flag, EVALS_* environment, evals/config.yaml, default.
Uses the presets and wire protocol shared with the hoa CLI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

# PEP 723 script invocation does not install the checkout's package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hoa_cli import config  # noqa: E402
from hoa_cli.config import SUPPORTED_APIS as SUPPORTED_APIS  # noqa: E402
from hoa_cli.decisions.client import (  # noqa: E402
    DEFAULT_API as DEFAULT_API,
    DEFAULT_EFFORT as DEFAULT_EFFORT,
    build_decisions_payload as build_decisions_payload,
    chat_completions_url as chat_completions_url,
    decisions_url as decisions_url,
    evaluate_one as evaluate_one,
)
from hoa_cli.decisions.responses import parse_decisions_response as parse_decisions_response  # noqa: E402
from hoa_cli.decisions.rubric import load_presets  # noqa: E402

SKILL = "evals"
KEY_BASE_URL = "base_url"
KEY_MODEL = "model"
KEY_API = "api"
KEY_EFFORT = "effort"
KEY_API_KEY = "api_key"
API_DECISIONS, API_CHAT_COMPLETIONS = SUPPORTED_APIS
evaluate_state = evaluate_one


def load_rubrics(path: Path | str | None = None) -> dict[str, dict]:
    return load_presets(Path(path) if path is not None else None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preset", required=True, help="preset name from the bundled rubrics")
    state = parser.add_mutually_exclusive_group(required=True)
    state.add_argument("--state", help="inline JSON or text state")
    state.add_argument("--state-file", type=Path, help="path to JSON or text state file")
    parser.add_argument("--rubrics-file", type=Path, help="override the bundled rubrics")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL")
    parser.add_argument("--model", help="judge model ID")
    parser.add_argument("--api", help=f"wire API: {', '.join(SUPPORTED_APIS)} (default: {DEFAULT_API})")
    parser.add_argument("--effort", help=f"reasoning effort for chat-completions (default: {DEFAULT_EFFORT})")
    args = parser.parse_args(argv)

    try:
        base_url = config.resolve(SKILL, KEY_BASE_URL, flag=args.base_url)
        model = config.resolve(SKILL, KEY_MODEL, flag=args.model)
        api = config.resolve(SKILL, KEY_API, flag=args.api, default=DEFAULT_API)
        effort = config.resolve(SKILL, KEY_EFFORT, flag=args.effort, default=DEFAULT_EFFORT)
        api_key = config.resolve(SKILL, KEY_API_KEY)
        if not base_url or not model:
            raise ValueError("base_url and model are required (--base-url / EVALS_BASE_URL, --model / EVALS_MODEL)")
        if api not in SUPPORTED_APIS:
            raise ValueError(f"api must be one of {SUPPORTED_APIS}, got {api!r}")
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"base_url must be an http(s) URL, got {base_url!r}")
        presets = load_rubrics(args.rubrics_file)
        if args.preset not in presets:
            raise ValueError(f"unknown preset {args.preset!r}; available: {sorted(presets)}")
        raw_state = args.state_file.read_text(encoding="utf-8") if args.state_file else args.state
    except (OSError, ValueError) as error:
        print(f"decision_judge: {error}", file=sys.stderr)
        return 2

    try:
        state_value = json.loads(raw_state)
    except json.JSONDecodeError:
        state_value = raw_state

    try:
        result = evaluate_one(base_url, model, presets[args.preset]["questions"], state_value,
                              api=api, effort=effort, api_key=api_key)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"decision_judge: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
