#!/usr/bin/env python3
"""Web / X search through the local ghc-proxy Responses API.

Owns the mechanical work so the caller doesn't: request building, response
parsing, inline-citation stripping, URL dedup, and actionable errors.
Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

DEFAULT_ENDPOINT = "http://127.0.0.1:4141/v1/responses"
# Per-engine defaults. There is deliberately no default engine: gpt and x search
# different corpora, and picking one for the caller guesses at intent.
ENGINE_MODEL = {"gpt": "gpt-5.6-terra", "x": "grok-4.5"}
DEFAULT_EFFORT = "medium"

# Inline citation markup, eating any space in front of it so removal leaves no
# double space. grok-4.5 emits "[[1]](url)", gpt-5.4 emits "([label](url))".
CITATION_RE = re.compile(
    r"[ \t]*(?:\[\[\d+\]\]\((https?://[^\s)]+)\)|\(\[[^\]]+\]\((https?://[^\s)]+)\)\))"
)


class SearchError(Exception):
    """Anything that must not be printed as a successful result."""


def strip_citations(text: str) -> tuple[str, list[str]]:
    """Return (text without inline citation markup, URLs that were in it)."""
    urls: list[str] = []

    def take(m: re.Match) -> str:
        urls.append(m.group(1) or m.group(2))
        return ""

    return CITATION_RE.sub(take, text).strip(), urls


def _dedup_key(url: str):
    p = urlsplit(url)
    # Fragment dropped, trailing slash ignored: same page, one entry.
    return (p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.query)


def parse(payload: dict) -> tuple[str, list[dict]]:
    """Pull (answer, sources) out of a Responses API payload.

    Raises SearchError when the payload is not a usable completed answer.
    """
    status = payload.get("status")
    truncated = False
    if status != "completed":
        detail = payload.get("incomplete_details") or payload.get("error") or ""
        # Hitting the token ceiling still leaves a usable (if cut off) answer --
        # gpt-5.4 spends heavily on reasoning before it writes. Anything else is
        # a real failure.
        if status == "incomplete" and (detail or {}).get("reason") == "max_output_tokens":
            truncated = True
        else:
            raise SearchError(f"response status={status!r}, expected 'completed'. {detail}".strip())

    sources: list[dict] = []
    seen: set = set()

    def add(url, title=""):
        if not isinstance(url, str):
            return
        url = url.strip()
        p = urlsplit(url)
        if p.scheme.lower() not in ("http", "https") or not p.netloc:
            return
        key = _dedup_key(url)
        if key in seen:
            return
        seen.add(key)
        sources.append({"url": url, "title": (title or "").strip() or p.netloc})

    answer_parts: list[str] = []
    inline_urls: list[str] = []
    tool_urls: list[tuple] = []
    saw_message = False

    for item in payload.get("output") or []:
        if item.get("type") == "message":
            saw_message = True
            for chunk in item.get("content") or []:
                text = chunk.get("text")
                if text:
                    clean, found = strip_citations(text)
                    if clean:
                        answer_parts.append(clean)
                    inline_urls.extend(found)
                for ann in chunk.get("annotations") or []:
                    if ann.get("type") == "url_citation":
                        add(ann.get("url"), ann.get("title", ""))
        else:
            # web_search_call / x_search_call / custom_tool_call — the pages the
            # model actually consulted. Lower priority than annotations.
            action = item.get("action") or {}
            tool_urls.append((action.get("url"), ""))
            for src in action.get("sources") or []:
                if isinstance(src, dict):
                    tool_urls.append((src.get("url"), src.get("title", "")))

    for url in inline_urls:
        add(url)
    for url, title in tool_urls:
        add(url, title)

    if not saw_message:
        raise SearchError(
            "no 'message' item in response output — nothing to report"
            + (" (ran out of output tokens before answering; raise --max-tokens)" if truncated else "")
        )
    answer = "\n\n".join(answer_parts).strip()
    if not answer:
        raise SearchError(
            "message item carried no text"
            + (" (ran out of output tokens; raise --max-tokens)" if truncated else "")
        )
    if truncated:
        answer += "\n\n[truncated: hit --max-tokens]"
    return answer, sources


def build_body(query, engine, *, model, effort, max_tokens,
               handles=(), excluded_handles=(), from_date=None, to_date=None,
               domains=(), blocked_domains=(), context_size=None, country=None):
    """Assemble the Responses request. `engine` is 'gpt' (web) or 'x'."""
    if engine == "x":
        tool = {"type": "x_search"}
        if handles:
            tool["allowed_x_handles"] = list(handles)
            # allowed_x_handles restricts what the tool may return, it does not
            # tell the model who to look for: with a terse query ("newest post")
            # the model asks a clarifying question instead of searching. Name the
            # handles in the prompt too, unless the caller already did.
            missing = [h for h in handles if h.lower() not in query.lower()]
            if missing:
                query = f"{query} (X handles: {', '.join('@' + h for h in missing)})"
        if excluded_handles:
            tool["excluded_x_handles"] = list(excluded_handles)
        if from_date:
            tool["from_date"] = from_date
        if to_date:
            tool["to_date"] = to_date
    else:
        tool = {"type": "web_search"}
        filters = {}
        if domains:
            filters["allowed_domains"] = list(domains)
        if blocked_domains:
            filters["blocked_domains"] = list(blocked_domains)
        if filters:
            tool["filters"] = filters
        if context_size:
            tool["search_context_size"] = context_size
        if country:
            tool["user_location"] = {"type": "approximate", "country": country}

    return {
        "model": model,
        "input": [{"role": "user", "content": query}],
        "tools": [tool],
        "tool_choice": "auto",
        "reasoning": {"effort": effort},
        "max_output_tokens": max_tokens,
        "store": False,
    }


def post(endpoint: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode(),
        headers={"authorization": "Bearer dummy", "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise SearchError(f"HTTP {e.code} from {endpoint}: {detail}") from None
    except urllib.error.URLError as e:
        host = urlsplit(endpoint).netloc
        raise SearchError(
            f"ghc-proxy not reachable at {host} ({e.reason}). "
            f"Start it, then check: curl -sS -o /dev/null -w '%{{http_code}}' {endpoint}"
        ) from None
    except TimeoutError:
        raise SearchError(f"timed out after {timeout:.0f}s waiting on {endpoint}") from None
    except json.JSONDecodeError as e:
        raise SearchError(f"proxy returned non-JSON: {e}") from None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("engine", choices=("gpt", "x"),
                    help="gpt = web search, x = X/Twitter search. No default: they search "
                         "different corpora, so the caller has to say which.")
    ap.add_argument("query")
    ap.add_argument("--model", help=f"default per engine: {ENGINE_MODEL['gpt']} (gpt), {ENGINE_MODEL['x']} (x)")
    ap.add_argument("--effort", choices=("low", "medium", "high"), default=DEFAULT_EFFORT,
                    help=f"reasoning effort (default {DEFAULT_EFFORT})")

    x = ap.add_argument_group("x only")
    x.add_argument("--handle", action="append", default=[], metavar="NAME",
                   help="restrict to this handle, and name it in the prompt (repeatable)")
    x.add_argument("--exclude-handle", action="append", default=[], metavar="NAME")
    x.add_argument("--from-date", metavar="YYYY-MM-DD")
    x.add_argument("--to-date", metavar="YYYY-MM-DD")

    g = ap.add_argument_group("gpt only")
    g.add_argument("--domain", action="append", default=[], metavar="HOST",
                   help="restrict to this domain (repeatable)")
    g.add_argument("--block-domain", action="append", default=[], metavar="HOST")
    g.add_argument("--context-size", choices=("low", "medium", "high"),
                   help="how much page context the tool pulls back")
    g.add_argument("--country", metavar="CC", help="two-letter code for geo-sensitive results")

    ap.add_argument("--limit", type=int, default=10, help="max sources listed (default 10)")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--json", action="store_true", dest="as_json", help="structured output")
    args = ap.parse_args(argv)

    x_only = {"--handle": args.handle, "--exclude-handle": args.exclude_handle,
              "--from-date": args.from_date, "--to-date": args.to_date}
    gpt_only = {"--domain": args.domain, "--block-domain": args.block_domain,
                "--context-size": args.context_size, "--country": args.country}
    wrong = [f for f, v in (gpt_only if args.engine == "x" else x_only).items() if v]
    if wrong:
        ap.error(f"{', '.join(wrong)} not valid for engine '{args.engine}'")

    model = args.model or ENGINE_MODEL[args.engine]
    mode = "x_search" if args.engine == "x" else "web_search"

    started = time.monotonic()
    try:
        body = build_body(
            args.query, args.engine, model=model, effort=args.effort,
            max_tokens=args.max_tokens,
            handles=args.handle, excluded_handles=args.exclude_handle,
            from_date=args.from_date, to_date=args.to_date,
            domains=args.domain, blocked_domains=args.block_domain,
            context_size=args.context_size, country=args.country,
        )
        answer, sources = parse(post(args.endpoint, body, args.timeout))
    except SearchError as e:
        print(f"ghc-search: {e}", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - started
    sources = sources[: args.limit] if args.limit > 0 else sources

    if args.as_json:
        json.dump({"model": model, "mode": mode, "effort": args.effort,
                   "elapsed_s": round(elapsed, 2), "answer": answer,
                   "sources": [dict(n=i, **s) for i, s in enumerate(sources, 1)]},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print(answer)
        if sources:
            print("\nSources:")
            for i, s in enumerate(sources, 1):
                print(f"  [{i}] {s['title']} — {s['url']}")
        print(f"\n({model}, {mode}, effort={args.effort}, {elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
