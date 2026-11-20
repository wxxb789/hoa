#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Opt-in structured rubric classifier via /v1/decisions or /v1/chat/completions.

Resolves configuration through skill_config.py (skill='ghc-decisions') with
fallback to EVALS_* environment variables so both interactive skill callers and
benchmark suites share one implementation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import skill_config as sc  # noqa: E402

SKILL = "ghc-decisions"
KEY_BASE_URL = "base_url"
KEY_MODEL = "model"
KEY_API = "api"
KEY_EFFORT = "effort"
KEY_API_KEY = "api_key"

API_DECISIONS = "decisions"
API_CHAT_COMPLETIONS = "chat-completions"
DEFAULT_API = API_DECISIONS
SUPPORTED_APIS = (API_DECISIONS, API_CHAT_COMPLETIONS)
DEFAULT_EFFORT = "low"
DEFAULT_API_KEY = "dummy"
TIMEOUT = 60.0
MAX_TOKENS = 1024
RUBRICS_PATH = HERE / "rubrics.json"


def load_rubrics(path: Path | None = None) -> dict[str, dict]:
    target = RUBRICS_PATH if path is None else Path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    presets = data.get("presets") if isinstance(data, dict) else None
    if not isinstance(presets, dict) or not presets:
        raise ValueError(f"{target} has no non-empty presets object")
    return presets


def decisions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/decisions") else f"{base}/decisions"


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def build_decisions_payload(model: str, state: dict | str, questions: list[dict]) -> dict:
    input_value = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, indent=2)
    return {
        "model": model,
        "input": input_value,
        "questions": questions,
    }


def parse_decisions_response(payload: dict, questions: list[dict]) -> dict[str, dict]:
    if not isinstance(payload, dict):
        raise ValueError("decisions response is not a JSON object")
    if payload.get("error"):
        raise ValueError(f"endpoint error: {payload['error']}")
    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, list) or len(raw_answers) != len(questions):
        raise ValueError(f"expected {len(questions)} answers, got {type(raw_answers).__name__}")
    by_name = {
        ans.get("name"): ans
        for ans in raw_answers
        if isinstance(ans, dict) and isinstance(ans.get("name"), str)
    }
    parsed: dict[str, dict] = {}
    for index, q in enumerate(questions):
        name = q["name"]
        ans = by_name.get(name) if name in by_name else (
            raw_answers[index] if isinstance(raw_answers[index], dict) else None
        )
        if not isinstance(ans, dict):
            raise ValueError(f"missing answer for question {name!r}")
        qtype = q["type"]
        atype = ans.get("type")
        if atype == "refusal":
            parsed[name] = {"type": "refusal", "value": None}
        elif qtype == "predicate":
            prob = float(ans["probability"])
            parsed[name] = {
                "type": "predicate",
                "value": prob >= 0.5,
                "probability": prob,
            }
        elif qtype == "choice":
            parsed[name] = {
                "type": "choice",
                "value": ans["choice"],
                "confidence": float(ans.get("confidence", 0.0)),
                "probabilities": {
                    item["value"]: float(item["probability"])
                    for item in ans.get("probabilities", [])
                    if isinstance(item, dict) and "value" in item and "probability" in item
                },
            }
        elif qtype == "score":
            probs = ans.get("probabilities", [])
            best_label = None
            if isinstance(probs, list) and probs:
                top = max(probs, key=lambda item: float(item.get("probability", 0.0)))
                best_label = top.get("label")
            parsed[name] = {
                "type": "score",
                "value": float(ans["score"]),
                "top_label": best_label,
                "confidence": float(ans.get("confidence", 0.0)),
            }
        else:
            raise ValueError(f"unsupported question type {qtype!r}")
    return parsed


def build_chat_prompt(state: dict | str, questions: list[dict]) -> str:
    state_text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, indent=2)
    q_lines = []
    for q in questions:
        name = q["name"]
        qtype = q["type"]
        instr = q["instructions"]
        if qtype == "predicate":
            q_lines.append(f'- "{name}" (boolean true/false): {instr}')
        elif qtype == "choice":
            opts = ", ".join(
                f'{c["value"]!r} ({c.get("description", "")})' if c.get("description") else repr(c["value"])
                for c in q["choices"]
            )
            q_lines.append(f'- "{name}" (one of: {opts}): {instr}')
        elif qtype == "score":
            lvls = ", ".join(
                f'{i}={lvl["label"]!r} ({lvl.get("description", "")})'
                for i, lvl in enumerate(q["levels"])
            )
            q_lines.append(f'- "{name}" (integer level index: {lvls}): {instr}')
    schema_hint = ", ".join(f'"{q["name"]}": ...' for q in questions)
    return (
        "Evaluate the following state against each question.\n\n"
        f"State:\n{state_text}\n\n"
        "Questions:\n" + "\n".join(q_lines) + "\n\n"
        f"Reply with ONLY a raw JSON object {{{schema_hint}}} with no markdown fences."
    )


def parse_chat_response(payload: dict, questions: list[dict]) -> dict[str, dict]:
    if not isinstance(payload, dict):
        raise ValueError("chat response is not a JSON object")
    if payload.get("error"):
        raise ValueError(f"endpoint error: {payload['error']}")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("chat response has no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("chat response has no message content")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("chat response content is not a JSON object")
    parsed: dict[str, dict] = {}
    for q in questions:
        name = q["name"]
        if name not in obj:
            raise ValueError(f"chat JSON missing key {name!r}")
        val = obj[name]
        qtype = q["type"]
        if qtype == "predicate":
            parsed[name] = {"type": "predicate", "value": bool(val), "probability": 1.0 if val else 0.0}
        elif qtype == "choice":
            parsed[name] = {"type": "choice", "value": str(val), "confidence": 1.0, "probabilities": {}}
        elif qtype == "score":
            levels = q["levels"]
            if isinstance(val, str):
                idx = next((i for i, lvl in enumerate(levels) if lvl["label"] == val), 0)
            else:
                idx = int(round(float(val)))
            idx = max(0, min(len(levels) - 1, idx))
            parsed[name] = {
                "type": "score",
                "value": float(idx),
                "top_label": levels[idx]["label"],
                "confidence": 1.0,
            }
    return parsed


def evaluate_one(
    base_url: str,
    model: str,
    questions: list[dict],
    state: dict | str,
    *,
    api: str = DEFAULT_API,
    effort: str = DEFAULT_EFFORT,
    api_key: str | None = None,
    timeout: float = TIMEOUT,
) -> dict:
    if api == API_DECISIONS:
        url = decisions_url(base_url)
        body = build_decisions_payload(model, state, questions)
    elif api == API_CHAT_COMPLETIONS:
        url = chat_completions_url(base_url)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": build_chat_prompt(state, questions)}],
            "max_tokens": MAX_TOKENS,
            "reasoning_effort": effort,
        }
    else:
        raise ValueError(f"unsupported api {api!r}")

    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {error.code}: {detail}".rstrip()) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"request failed: {error.reason}") from error
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    payload = json.loads(raw.decode("utf-8"))
    answers = (
        parse_decisions_response(payload, questions)
        if api == API_DECISIONS
        else parse_chat_response(payload, questions)
    )
    usage = payload.get("usage") or {}
    return {
        "model": payload.get("model", model),
        "api": api,
        "elapsed_ms": elapsed_ms,
        "usage": {
            "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens") or 0,
            "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens") or 0,
        },
        "answers": answers,
    }


def _resolve_setting(key: str, *, flag: str | None = None, default: str | None = None) -> str | None:
    val = sc.resolve(SKILL, key, flag=flag)
    if val is not None:
        return val
    evals_env = os.environ.get(f"EVALS_{key.upper()}")
    if evals_env is not None and evals_env != "":
        return evals_env
    return default


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-presets", action="store_true", help="list bundled preset names and exit")
    parser.add_argument("--if-configured", action="store_true", help="exit 0 with skipped JSON when base_url or model is not configured")
    parser.add_argument("--preset", default=None, help="preset name from rubrics.json")
    parser.add_argument("--state", default=None, help="inline JSON or text state")
    parser.add_argument("--state-file", default=None, help="path to JSON or text state file")
    parser.add_argument("--rubrics-file", default=None, help="override path to rubrics.json")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL")
    parser.add_argument("--model", default=None, help="judge model ID")
    parser.add_argument("--api", default=None, help=f"wire API: {', '.join(SUPPORTED_APIS)} (default: {DEFAULT_API})")
    parser.add_argument("--effort", default=None, help=f"reasoning effort for chat-completions (default: {DEFAULT_EFFORT})")
    args = parser.parse_args(argv)

    presets = load_rubrics(args.rubrics_file)
    if args.list_presets:
        out = {
            name: {
                "description": p.get("description", ""),
                "questions": [q["name"] for q in p.get("questions", [])],
            }
            for name, p in presets.items()
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if not args.preset:
        parser.error("--preset is required unless --list-presets is passed")
    if bool(args.state) == bool(args.state_file):
        parser.error("supply exactly one of --state or --state-file")

    try:
        base_url = _resolve_setting(KEY_BASE_URL, flag=args.base_url)
        model = _resolve_setting(KEY_MODEL, flag=args.model)
        api = _resolve_setting(KEY_API, flag=args.api, default=DEFAULT_API)
        effort = _resolve_setting(KEY_EFFORT, flag=args.effort, default=DEFAULT_EFFORT)
        api_key = _resolve_setting(KEY_API_KEY, default=DEFAULT_API_KEY)
    except sc.ConfigError as error:
        print(f"ghc_decisions: {error}", file=sys.stderr)
        return 2

    if not base_url or not model:
        if args.if_configured:
            print(json.dumps({"skipped": True, "reason": "ghc-decisions is not configured (set GHC_DECISIONS_BASE_URL and GHC_DECISIONS_MODEL to opt in)"}))
            return 0
        print(
            "ghc_decisions: base_url and model are required (--base-url / GHC_DECISIONS_BASE_URL, --model / GHC_DECISIONS_MODEL)",
            file=sys.stderr,
        )
        return 2

    if api not in SUPPORTED_APIS:
        print(f"ghc_decisions: api must be one of {SUPPORTED_APIS}, got {api!r}", file=sys.stderr)
        return 2
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        print(f"ghc_decisions: base_url must be an http(s) URL, got {base_url!r}", file=sys.stderr)
        return 2

    if args.preset not in presets:
        print(f"ghc_decisions: unknown preset {args.preset!r}; available: {sorted(presets)}", file=sys.stderr)
        return 2

    raw_state = Path(args.state_file).read_text(encoding="utf-8") if args.state_file else args.state
    try:
        state_val = json.loads(raw_state)
    except json.JSONDecodeError:
        state_val = raw_state

    try:
        result = evaluate_one(
            base_url,
            model,
            presets[args.preset]["questions"],
            state_val,
            api=api,
            effort=effort,
            api_key=api_key,
        )
    except Exception as error:
        if args.if_configured:
            print(json.dumps({"skipped": True, "reason": f"endpoint unreachable or failed: {error}"}))
            return 0
        print(f"ghc_decisions: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
