#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml>=6"]
# ///
"""Judge the trigger (routing) eval suite against a configured endpoint.

Offline structure validation lives in run_trigger_evals.py. This script does the
judge pass: build the artifact catalog, ask a fresh-context judge which artifact
each request routes to, report per-case pass/fail, and optionally record a
baseline.

Configuration
-------------
No endpoint, model, effort, API mode or credential is compiled in. Every value
is resolved through scripts/skill_config.py in the documented order:

    CLI flag -> environment variable -> $XDG_CONFIG_HOME/evals/config.yaml
             (fallback ~/.config/evals/config.yaml) -> documented default

    key       flag         environment       default
    base_url  --base-url   EVALS_BASE_URL    none (required)
    model     --model      EVALS_MODEL       none (required)
    effort    --effort     EVALS_EFFORT      low
    api       --api        EVALS_API         chat-completions
    api_key   (none)       EVALS_API_KEY     none (unauthenticated request)

`base_url` is the OpenAI-compatible base URL. By default (`api: chat-completions`),
`/chat/completions` is appended unless the value already ends with it, and
`effort` is sent as the request's `reasoning_effort` and recorded in the
baseline. When `api` is set to `decisions` (opt-in for OpenAI Decisions API
models such as `gpt-6-luna-decisions`), `/decisions` is appended unless the
value already ends with it, and the judge sends a single `choice` question over
the visible catalog artifact names plus `none`.

Without `base_url` and `model` the script exits 2, printing the keys it needs
and the config-file path. A malformed config file or unsupported `api` value
exits 2.
Usage
-----
    python evals/judge_trigger_evals.py [--limit N] [--json]
    python evals/judge_trigger_evals.py --record [--force]

`--record` writes evals/baseline.json only on an explicit request and only for
the full case set; an existing record is replaced only with `--force`. Before
writing, the proposed record is checked with the same rules the offline gate
applies (run_trigger_evals.baseline_errors). A run whose picks include transport
errors or non-catalog answers cannot be represented in the accepted schema, so
the file is left untouched and the script exits 2; a wrong-but-catalog pick is
an honest measurement and is recorded.

Exit codes: 0 every case passed, 1 at least one failed, 2 configuration/usage or
a record the offline gate would reject.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

EVALS = Path(__file__).resolve().parent
ROOT = EVALS.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate_index as gi  # noqa: E402
import skill_config as sc  # noqa: E402
import skill_metadata as sm  # noqa: E402
import yaml  # noqa: E402

try:  # `python evals/judge_trigger_evals.py` puts evals/ on sys.path
    import run_trigger_evals as gate  # noqa: E402
except ModuleNotFoundError as error:  # imported as evals.judge_trigger_evals
    if error.name != "run_trigger_evals":
        raise
    from evals import run_trigger_evals as gate  # noqa: E402

SKILL = "evals"
KEY_BASE_URL = "base_url"
KEY_MODEL = "model"
KEY_EFFORT = "effort"
KEY_API = "api"
KEY_API_KEY = "api_key"
DEFAULT_EFFORT = "low"
API_CHAT_COMPLETIONS = "chat-completions"
API_DECISIONS = "decisions"
DEFAULT_API = API_CHAT_COMPLETIONS
SUPPORTED_APIS = (API_CHAT_COMPLETIONS, API_DECISIONS)
MAX_WORKERS = 5
MAX_TOKENS = 2048
TIMEOUT = 120.0
BASELINE_PATH = EVALS / "baseline.json"


class RecordError(ValueError):
    """A baseline record that cannot be written without losing an earlier one."""


def visible_catalog_rows() -> list[tuple[str, str, str]]:
    """Return (name, type, description) for every visible catalog artifact."""
    rows: list[tuple[str, str, str]] = []
    for row in gi.collect():
        if row["type"] == "skill":
            skill_md = ROOT / row["path"] / "SKILL.md"
            frontmatter, _ = sm._frontmatter(skill_md.read_text(encoding="utf-8"), skill_md)
            fields = yaml.safe_load(frontmatter)
            if fields.get("disable-model-invocation") is True:
                continue
            description = fields["description"]
        else:
            description = row["note_en"]
        rows.append((row["name"], row["type"], description))
    return rows


def catalog_text() -> str:
    """Use frontmatter descriptions for visible skills and index notes otherwise."""
    return "\n".join(
        f"- {name} ({kind}): {description}"
        for name, kind, description in visible_catalog_rows()
    )


def catalog_choices(catalog: str) -> list[str]:
    """Extract artifact names from a rendered catalog_text() block, plus NO_MATCH."""
    names: list[str] = []
    for line in catalog.splitlines():
        if line.startswith("- ") and " (" in line:
            names.append(line[2:].split(" (", 1)[0])
    names.append(gate.NO_MATCH)
    return names

def build_prompt(catalog: str, request: str) -> str:
    return (
        "Route the user request to the best-fitting artifact, if any.\n\n"
        f"Catalog:\n{catalog}\n\n"
        f"User request: {request}\n\n"
        f"Reply with only the artifact name, or {gate.NO_MATCH} if no artifact applies."
    )


def chat_completions_url(base_url: str) -> str:
    """The chat-completions URL for an OpenAI-compatible base URL."""
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def decisions_url(base_url: str) -> str:
    """The decisions URL for an OpenAI-compatible Decisions API base URL."""
    base = base_url.rstrip("/")
    if base.endswith("/decisions"):
        return base
    return f"{base}/decisions"
def endpoint_host(base_url: str) -> str:
    """The recordable endpoint identity: host plus port, no path, query or key."""
    return urlsplit(base_url).netloc


def _validate_base_url(base_url: str) -> str | None:
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return f"base_url must be an http(s) URL, got {base_url!r}"
    return None


def build_body(model: str, effort: str, prompt: str) -> dict:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "reasoning_effort": effort,
    }


def build_decisions_body(model: str, catalog: str, request: str,
                         choices: list[str] | None = None) -> dict:
    names = catalog_choices(catalog) if choices is None else choices
    return {
        "model": model,
        "input": f"Catalog:\n{catalog}\n\nUser request: {request}\n",
        "questions": [
            {
                "name": "route",
                "type": "choice",
                "instructions": (
                    "Route the user request to the best-fitting artifact, if any, "
                    f"or {gate.NO_MATCH} if no artifact applies."
                ),
                "choices": [{"value": name} for name in names],
            }
        ],
    }


def parse_answer(payload) -> str:
    """Pull the artifact name out of one chat-completions reply."""
    if not isinstance(payload, dict):
        raise ValueError("response is not a JSON object")
    if payload.get("error"):
        raise ValueError(f"endpoint error: {payload['error']}")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("response has no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("response has no message content")
    return content.strip()


def parse_decisions_answer(payload) -> str:
    """Pull the chosen artifact name out of one /decisions reply."""
    if not isinstance(payload, dict):
        raise ValueError("response is not a JSON object")
    if payload.get("error"):
        raise ValueError(f"endpoint error: {payload['error']}")
    answers = payload.get("answers")
    if not isinstance(answers, list) or not answers or not isinstance(answers[0], dict):
        raise ValueError("response has no answers")
    answer = answers[0]
    if answer.get("type") == "refusal":
        raise ValueError("decision model refused to answer")
    choice = answer.get("choice")
    if not isinstance(choice, str) or not choice.strip():
        raise ValueError("response answer has no string choice")
    return choice.strip()


def judge_one(base_url: str, model: str, effort: str, api_key: str | None,
              catalog: str, request: str, *, api: str = DEFAULT_API) -> str:
    if api == API_DECISIONS:
        url = decisions_url(base_url)
        body = build_decisions_body(model, catalog, request)
        parser = parse_decisions_answer
    elif api == API_CHAT_COMPLETIONS:
        url = chat_completions_url(base_url)
        body = build_body(model, effort, build_prompt(catalog, request))
        parser = parse_answer
    else:
        raise ValueError(f"unsupported api {api!r}")
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {error.code}: {detail}".rstrip()) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"request failed: {error.reason}") from error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"response is not JSON: {error}") from error
    return parser(payload)

def resolve_settings(args, env=None):
    """Resolve (base_url, model, effort, api_key, api) through the shared resolver."""
    environ = os.environ if env is None else env
    base_url = sc.resolve(SKILL, KEY_BASE_URL, flag=args.base_url, env=environ)
    model = sc.resolve(SKILL, KEY_MODEL, flag=args.model, env=environ)
    effort = sc.resolve(SKILL, KEY_EFFORT, flag=args.effort, env=environ,
                        default=DEFAULT_EFFORT)
    api_key = sc.resolve(SKILL, KEY_API_KEY, env=environ)
    api = sc.resolve(SKILL, KEY_API, flag=getattr(args, "api", None), env=environ,
                     default=DEFAULT_API)
    return base_url, model, effort, api_key, api


def unconfigured_message(base_url, model, effort, env=None) -> str:
    missing = [name for name, value in (("base_url", base_url), ("model", model))
               if not value]
    path = sc.config_path(SKILL, env=env)
    rows = [
        ("base_url", "--base-url", sc.env_name(SKILL, KEY_BASE_URL), None),
        ("model", "--model", sc.env_name(SKILL, KEY_MODEL), None),
        ("effort", "--effort", sc.env_name(SKILL, KEY_EFFORT), DEFAULT_EFFORT),
        ("api", "--api", sc.env_name(SKILL, KEY_API), DEFAULT_API),
    ]
    lines = [
        "judge_trigger_evals: judge endpoint and model are not configured.",
        *(
            f"  {key:<9} {flag} / {variable}"
            + ("  (missing)" if key in missing else
               f"  default: {default}" if default is not None else "")
            for key, flag, variable, default in rows
        ),
        f"config file: {path}",
        "Set them in that file, in the environment, or with the flags.",
    ]
    return "\n".join(lines)

def baseline_record(cases, model, effort, base_url, results) -> dict:
    return {
        "case_count": len(cases),
        "model": model,
        "effort": effort,
        "passed": sum(1 for result in results if result["passed"]),
        "total": len(results),
        "judge_endpoint_host": endpoint_host(base_url),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "per_case": [
            {"id": result["id"], "pick": result["pick"], "passed": result["passed"]}
            for result in results
        ],
    }


def record_baseline(record: dict, *, path=None, force: bool = False) -> Path:
    """Write the record atomically; never replace an earlier one without force."""
    target = Path(BASELINE_PATH if path is None else path)
    if target.exists() and not force:
        raise RecordError(f"{target} already exists; pass --force to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".baseline-",
                                         suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise
    return target


def load_cases() -> list[dict]:
    data = json.loads((EVALS / "trigger-cases.json").read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("trigger-cases.json has no non-empty cases list")
    return cases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="judge only the first N cases (0 = all cases)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    parser.add_argument("--record", action="store_true",
                        help=f"write {BASELINE_PATH.relative_to(ROOT)} for the full run")
    parser.add_argument("--force", action="store_true",
                        help="with --record, replace an existing baseline record")
    parser.add_argument("--base-url", default=None,
                        help="OpenAI-compatible base URL (flag beats env and config)")
    parser.add_argument("--model", default=None,
                        help="judge model name (flag beats env and config)")
    parser.add_argument("--effort", default=None,
                        help=f"judge effort, sent as reasoning_effort (default: {DEFAULT_EFFORT})")
    parser.add_argument("--api", default=None,
                        help=f"judge wire API: {', '.join(SUPPORTED_APIS)} (default: {DEFAULT_API})")
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if args.force and not args.record:
        parser.error("--force only applies with --record")
    if args.record and args.limit:
        parser.error("--record needs the full case set; drop --limit")

    try:
        base_url, model, effort, api_key, api = resolve_settings(args)
    except sc.ConfigError as error:
        print(f"judge_trigger_evals: {error}", file=sys.stderr)
        return 2
    if not base_url or not model:
        print(unconfigured_message(base_url, model, effort), file=sys.stderr)
        return 2
    if api not in SUPPORTED_APIS:
        print(f"judge_trigger_evals: api must be one of {SUPPORTED_APIS}, got {api!r}",
              file=sys.stderr)
        return 2
    problem = _validate_base_url(base_url)
    if problem:
        print(f"judge_trigger_evals: {problem}", file=sys.stderr)
        return 2
    target = Path(BASELINE_PATH)
    if args.record and target.exists() and not args.force:
        print(f"judge_trigger_evals: {target} already exists; pass --force to replace it",
              file=sys.stderr)
        return 2

    try:
        cases = load_cases()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"judge_trigger_evals: cannot read trigger-cases.json: {error}",
              file=sys.stderr)
        return 1
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("judge_trigger_evals: no cases to judge", file=sys.stderr)
        return 1
    catalog = catalog_text()

    def run_case(case: dict) -> dict:
        try:
            pick = judge_one(base_url, model, effort, api_key, catalog,
                             case["request"], api=api)
            passed = pick in case["must_pick"]
        except Exception as error:  # per-case failure, never aborts the batch
            pick, passed = f"error: {error}", False
        return {"id": case["id"], "pick": pick,
                "must_pick": case["must_pick"], "passed": passed}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(run_case, cases))

    passed = sum(result["passed"] for result in results)
    if args.json:
        print(json.dumps({"passed": passed, "total": len(results), "results": results},
                         indent=2, ensure_ascii=False))
    else:
        for result in results:  # input order, not completion order
            mark = "PASS" if result["passed"] else "FAIL"
            print(f"{mark} {result['id']}: picked {result['pick']!r} "
                  f"(want {result['must_pick']})")
        print(f"\n{passed}/{len(results)} passed")

    if args.record:
        record = baseline_record(cases, model, effort, base_url, results)
        rejected = gate.baseline_errors(cases, record)
        if rejected:
            print("judge_trigger_evals: the run's failures cannot be represented in "
                  "the accepted baseline schema (typically transport errors or "
                  "non-catalog answers); re-run the judge instead of replacing an "
                  "earlier measurement:", file=sys.stderr)
            for error in rejected:
                print(f"  {error}", file=sys.stderr)
            print(f"judge_trigger_evals: {target} was not written", file=sys.stderr)
            return 2
        try:
            written = record_baseline(record, force=args.force)
        except (OSError, RecordError) as error:
            print(f"judge_trigger_evals: cannot record baseline: {error}", file=sys.stderr)
            return 2
        print(f"judge_trigger_evals: wrote {written}", file=sys.stderr)

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
