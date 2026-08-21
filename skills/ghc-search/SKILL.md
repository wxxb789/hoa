---
name: ghc-search
description: Open-ended web search and X/Twitter search via the local ghc-proxy. Use when you need to find something on the web and do not already have a URL, or when you need posts from X/Twitter. Built-in WebSearch is denied on this machine, so this is the web-search path. Use WebFetch instead when you already have the URL; use context7 MCP for library/API documentation; use agent-browser when you need raw Bing SERP links or to interact with a page.
---

<!-- index: areas=software-development; targets=runtime-agnostic -->

# ghc-search

Web and X search through the local `ghc-proxy` Responses API. The script owns request
building, parsing, inline-citation stripping, and URL dedup — you get an answer plus a
clean source list.

## Use it

The engine is a required first argument: `gpt` searches the web, `x` searches
X/Twitter. They hit different corpora, so there is no default.

The script is `scripts/ghc_search.py` in this skill's own directory — under
`~/.claude/skills/ghc-search/` for a global Claude Code install, and the
equivalent `skills/` dir for any other runtime `npx skills` installed it into.

```bash
S=~/.claude/skills/ghc-search/scripts/ghc_search.py   # adjust per runtime

python $S gpt "what is the current stable .NET SDK version"
python $S x --handle SpaceXAI "newest post"
python $S gpt --domain dotnet.microsoft.com --json "latest .NET SDK version"
python $S x --handle dotnet --from-date 2026-08-01 "what shipped this month"
```

| Flag | Engine | |
|---|---|---|
| `--model` | both | defaults `gpt-5.6-terra` (gpt), `grok-4.5` (x) |
| `--effort low\|medium\|high` | both | default `medium` |
| `--handle NAME` | x | restrict to a handle; repeatable |
| `--exclude-handle NAME` | x | repeatable |
| `--from-date` / `--to-date` | x | `YYYY-MM-DD` |
| `--domain HOST` / `--block-domain HOST` | gpt | repeatable |
| `--context-size low\|medium\|high` | gpt | how much page text the tool pulls back |
| `--country CC` | gpt | two-letter code, for geo-sensitive results |
| `--limit N` | both | sources listed, default 10 |
| `--json`, `--max-tokens`, `--timeout`, `--endpoint` | both | |

A flag from the wrong engine is rejected before any network call.

## What you need to know

- **Latency ~3-20s** measured; date-filtered X searches are the slow end.
- **Model must support the responses endpoint.** Claude models return HTTP 400 here.
- **`--handle` restricts results but does not steer the model**, so the script appends
  the handles to the prompt for you. That is why a terse `x --handle X "newest post"`
  works; without the appending it draws a clarifying question instead of a search.
- **An empty source list is possible** — the model sometimes answers from its own
  knowledge without searching. No sources means no citation; judge the answer
  accordingly, and add `--domain` or ask it to cite if you need provenance.
- A response cut off by `--max-tokens` keeps its answer, flagged `[truncated]`, rather
  than being discarded. Raise `--max-tokens` and re-run if the tail matters.
- Exit code is non-zero with a one-line stderr message on any failure; a partial parse is
  never printed as success.

## Prerequisite

`ghc-proxy` must be running locally — this skill is useless without it:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:4141/v1/models \
  -H "authorization: Bearer dummy"
```

`200` = up, and that endpoint also lists the models you can pass to `--model`. The
script prints `ghc-proxy not reachable at 127.0.0.1:4141` when it is not.

## When this is not the right tool

`ghc-proxy` is machine-local. On a host without it this skill cannot run at all,
and the fallback is `agent-browser` — drive **Bing** with `&setlang=en`; Google
serves it a block page.

Reach for something else when you already have what you need: fetch the page
directly when you have the URL, and prefer a documentation source (`context7`
MCP) over general search when looking up a named library or API.

## Check

```bash
python "$(dirname $S)/test_ghc_search.py"   # 9 tests, offline
```
