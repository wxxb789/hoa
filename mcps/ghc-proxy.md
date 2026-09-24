<!-- index: areas=software-development; targets=repo-only -->

# ghc-proxy (local Responses API)

A portable MCP-style definition for the local `ghc-proxy` search service —
the provider definition itself; runtime registration (which MCP client gets
it, with what credentials) is a chezmoi concern, not this file.

## Definition

| Field | Value |
|---|---|
| Name | `ghc-proxy` |
| Kind | local HTTP service, OpenAI-compatible Responses API |
| Endpoint | `http://127.0.0.1:4141/v1/responses` (env: `GHC_SEARCH_ENDPOINT`) |
| Health check | `GET /v1/models` returns `200` |
| Tools | web search (`gpt` engine), X/Twitter search (`x` engine) |
| Default models | `gpt-5.6-luna` (web), `grok-4.5` (X) — env-overridable |
| Consumers | `skills/ghc-search/` (CLI script, not MCP-wired) |

## Usage contract

- Callers build Responses-API request bodies: `model`, `input`, `tools`
  (`web_search` / `x_search`), `reasoning.effort`, optional date/domain/handle
  filters. See `skills/ghc-search/scripts/ghc_search.py` for the reference
  client.
- Claude models are rejected (HTTP 400) — the endpoint requires models that
  support the responses API.
- Latency runs ~3–20s; date-filtered X searches are the slow end.

## Registration (per runtime — chezmoi owns this)

Registering this as an actual MCP server in a specific runtime (Claude Code's
`settings.json`, OpenCode's `config.json`, …) is machine-specific settings
work: keep the registration in chezmoi, not in this repo. This file is the
portable definition both sides can point at.

## Provenance

Written for this repo when `skills/ghc-search/` needed its local proxy
documented as a portable artifact; the definition mirrors the reference client
in `skills/ghc-search/scripts/ghc_search.py` (endpoint, engines, default
models), which is the executable source of truth. Not adapted from a `ref/`
row — it describes this machine's own local service.
