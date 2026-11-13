# Model endpoint matrix (local proxy + relays)

What each endpoint actually accepts, per model: the local ghc-proxy at `http://localhost:4141`,
and external chat-completions relays. Verified by probing; re-probe before relying on a row,
because the catalog churns.

Probe shape (header `Authorization: Bearer local`):

```bash
# Responses protocol
curl -s localhost:4141/v1/responses -H 'Authorization: Bearer local' -H 'Content-Type: application/json' \
  -d '{"model": "<id>", "input": "hi", "max_output_tokens": 16}'
# Chat-completions protocol
curl -s localhost:4141/v1/chat/completions -H 'Authorization: Bearer local' -H 'Content-Type: application/json' \
  -d '{"model": "<id>", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 16}'
```

| Model family | `/v1/responses` | `/v1/chat/completions` | Transport in Hermes |
|---|---|---|---|
| `gpt-5.6-*`, `gpt-6*` | yes | no | `codex_responses` (`local-openai`) |
| `gemini-*` | no (HTTP 400 `does not support the responses endpoint`) | yes | `chat_completions` (`local-chat`) |
| `grok-4.6` | yes | no | `codex_responses` (`local-openai`) |
| Claude family | **no** | **no** | unavailable on this account (2026-10-14) — configure nothing |

Rules that survive catalog changes:

- **Probe the model id on both routes before concluding anything.** Transport is per-model: this proxy
  serves responses-only, chat-only and both-route models side by side.
- **Claude is not available to this Copilot account (2026-10-14).** No claude id resolves — tested on
  both routes, and `GET /v1/models` lists none. Do not add claude entries, aliases or provider blocks.
- **The Anthropic route is `/v1/messages`, not `/messages`.** A probe against `localhost:4141/messages`
  returns `404 Unknown endpoint. Check the request path.` — a wrong-path artifact, not a dead proxy.
- **A gateway is not one host.** The Tencent GLM service exists on two hosts with *different route maps and
  different keys*: the new host (`1.14.219.252`) serves `/v1/chat/completions` only
  (`/v1/messages` → `404 no Route matched with those values`), while the old host
  (`svc-bytb2o81.gw.haihub.cn`) **does** serve `/v1/messages`, but only with
  `Authorization: Bearer <old key>` (`x-api-key` → 401). Same env var name, incompatible values: the
  `sk-…` (60-char) key is valid on the new host only, the `d4f0…` (64-char) key on the old host only.

- On chat completions, reasoning tokens are charged against `max_tokens`. A 16k cap was consumed
  almost entirely by reasoning at `reasoning_effort: high` and the visible answer truncated
  mid-sentence; 40k is the working size for high-effort long-form work, and 60k triggered `504`.
- Retry 5xx with backoff (transient upstream); never retry 4xx — those are config errors and retrying
  burns budget. `reasoning_effort` acceptance is not proof that effort engaged: read the returned
  reasoning-token count.
- Health: probe `/v1/models` (NOT `/api/v1/models`, which 500s and looks like the proxy is down).

## Reasoning-effort ladder benchmarking (chat-completions relays)

Measure a relay's effort→cost curve before choosing an effort level — ladder names
(low/medium/high/xhigh/max) are naming conventions, not a measured cost order. On the
tencent-glm relay (GLM-5.3), `medium` burned ~13k reasoning tokens, the same tier as
`xhigh`/`max` (2.5-3-minute turns), while `high` needed ~3.9k (~1 minute) and `low` ~0.8k
(~20s). "Medium" was a rebranded max there, not a middle setting.

Benchmark method that separates the tiers:

1. Use a prompt hard enough to force multi-step reasoning (a 3-variable system plus a follow-up
   question works); a simple prompt collapses every tier into seconds of noise.
2. Stream with `stream_options: {include_usage: true}`; record per-chunk timestamps for TTFT
   (first `reasoning_content` token, first `content` token), reasoning vs content char counts,
   and `usage.reasoning_tokens` (the authoritative measure — chars only feed rate math).
3. Run n≥2 per level and report medians; within-level variance ran 3.5× on a single tier.
4. Send a generous `max_tokens` (32k). Under a tight cap (8k) the heavy tiers spend the whole
   budget on `reasoning_content` and return ZERO visible content with `finish_reason: stop` —
   a "did it answer" check misreads budget exhaustion as success while the tokens still bill.
5. Measure the decode rate once (chars/s during the decode phase, ~60-90 tok/s here, roughly
   constant across tiers). Total-time differences are length-driven, not speed-driven: there
   is no "fast" tier, only short-reasoning tiers.
6. Make aggregation None-safe before launching: an effort-`none` lane yields None TTFT/decode
   fields and empty median lists, and `%.1f % None` / `statistics.median([])` crash the
   summary after all the data was already collected.

Pitfalls:

- `reasoning_effort: "none"` is not "fast": on hard prompts the model migrates the reasoning
  into visible content (21k chars, ~92s) — slower than `low` (1.3k chars, ~16s). Reserve
  `none` for pure chat/formatting lanes.
- A relay may accept a reasoning knob and silently ignore it: this one ignored
  `extra_body.thinking` (`{type: disabled}` still produced reasoning tokens) while honoring
  top-level `reasoning_effort: "none"` (0 reasoning tokens). Judge by the returned
  `usage.reasoning_tokens`, never by parameter acceptance.
- A vendor's published effort scale does not transfer to a relay fronting the same model
  family (z.ai's own ladder spread runs 4→125 tokens on its probe prompt; this relay's ran
  ~800→14k on a harder one — the shapes disagree). Re-measure per (relay, model) pair.

## Which reasoning wire shape a Hermes route sends

Config-defined providers (`providers:` entries in config.yaml) resolve to `CustomProfile`, not
the model family's vendor profile, unless the provider name or an alias matches a registered
vendor profile. Probe it live from the source tree before reasoning about wire shapes:

```bash
cd ~/.hermes/hermes-agent && python3 -c "
from providers import get_provider_profile
for n in ('tencent-glm', 'zai', 'glm'):
    print(n, '->', type(get_provider_profile(n)).__name__)"
```

`CustomProfile` sends top-level `reasoning_effort` clamped to the OpenAI-compat ladder (which
includes `xhigh`) — vendor-specific effort overrides (the zai profile's `xhigh → max`) never
apply on this path. With no `max_tokens` configured and no profile cap, the field is omitted
entirely: no budget-exhaustion risk, but also no guard against a heavy tier's 13k-token
reasoning burn.

## External chat relays (not served by the localhost proxy)

- `kimi-k3` — Tencent gateway `https://ms-5l65wdcd-100040620266-sw.gw.ap-shanghai.ti.tencentcs.com/ms-5l65wdcd/v1` (chat-completions), key env `TENCENT_KIMI_API_KEY`. It is **not** in the localhost proxy catalog (`/v1/models` does not list it), so the harness registry must point at the relay directly. Verified 2026-10-11: returns `model: kimi-k3`, accepts top-level `reasoning_effort: high` (reasoning_tokens > 0).
- **Long reasoning calls must stream.** A non-streaming chat POST at `max_tokens: 20000` hit the client read timeout (~1800s) with no terminal event and no usable body; the identical request with `stream: true` completed (`finish_reason: stop`, ~4–5 min). Send `stream: true` and accumulate `choices[0].delta.content` (`delta.reasoning_content` carries the reasoning phase, which can run for minutes with zero visible content).
- On this relay `max_tokens: 20000` was enough for a ~8000-character Chinese deliverable and did not `504` (the `504`-at-60k note above is the tencent-glm relay, a different host — re-probe per relay).

## OpenCode Zen vs Go relays (opencode.ai)

Two relays on the same host, **different model sets** — the path segment picks the set, and the
same id can exist on one and not the other, so probe both before concluding a model is absent:

- `opencode-zen` → `https://opencode.ai/zen/v1` (the `opencode/...` ids; hosts the `-free` tier)
- `opencode-go`  → `https://opencode.ai/zen/go/v1` (the `opencode-go/...` ids)

Hermes route resolution already encodes this: `hermes_cli.models` maps family `opencode-zen` →
`/zen` and `opencode-go` → `/zen/go`, and re-derives the wire mode per model (Zen/Go mix
responses-only, chat, and anthropic-wire models behind one provider) — always re-derive from the
effective model, never pin a provider-level api_mode.

Rules that survive catalog churn:

- **The Zen free tier is gated to the OpenCode client.** Raw HTTP and other agent harnesses are
  rejected with `403 FreeTierError: OpenCode's free tier can only be used from within OpenCode`.
  Drive it through the `opencode` CLI, the only client that passes the gate:
  `opencode run --model "opencode/<id>" --format json "<prompt>"` (add `--standalone` for a private
  server). `pi` reaches small models on its own `opencode` provider id, but is not OpenCode, so the
  free tier rejects it — use `opencode` for free-tier work.
- **`opencode models` is the authoritative catalog.** The relay's `/v1/models` also lists ids it no
  longer serves; a delisted id answers `410 ModelDeprecated`. Hermes filters these for its pickers
  (`_OPENCODE_FREE_EXCLUDED_MODELS`), so trust the CLI list over the raw one.
- **A listed id is not a servable id.** Free-tier ids come and go: probe each with a tiny prompt
  (`Reply with exactly: ROUTE_OK`) before a fan-out. Signals seen: `429 ... Endpoint is unavailable`
  (endpoint down), `400 ... Model is unavailable` (not on that relay), `410 ModelDeprecated`.
- **Any `opencode.json` project config in the run directory flips the whole free tier to 403** — run
  free-tier probes from a clean directory with no project config.
- Key env: `OPENCODE_API_KEY` (the Hermes `opencode-go-flash` entry names it `OPENCODE_GO_API_KEY`;
  map one to the other when handing the key to a CLI that expects the other name).
- **`InvalidParameter: invalid JSON Schema in function parameters` is a transient relay-side tool
  schema check, not a local config error.** Seen intermittently on `opencode-go/deepseek-v4.1-flash`
  through the `opencode` CLI (both `#high` and `#max`, and with no variant at all); the identical
  command succeeds on retry. Retry once before touching variants or provider blocks.
