# Model endpoint matrix (local proxy + relays)

What each endpoint actually accepts, per model, and how to measure it. Verified by probing; re-probe
before relying on any row, because the catalog churns. Endpoint hosts, model ids and key names below
are placeholders — the operator supplies them.

Probe shape (replace `<proxy-base>` and the proxy key):

```bash
# Responses protocol
curl -s <proxy-base>/v1/responses -H 'Authorization: Bearer <proxy-key>' -H 'Content-Type: application/json' \
  -d '{"model": "<id>", "input": "hi", "max_output_tokens": 16}'
# Chat-completions protocol
curl -s <proxy-base>/v1/chat/completions -H 'Authorization: Bearer <proxy-key>' -H 'Content-Type: application/json' \
  -d '{"model": "<id>", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 16}'
```

| Model family (example) | `/v1/responses` | `/v1/chat/completions` | Transport in Hermes |
|---|---|---|---|
| responses-only family | yes | no | `codex_responses` (responses provider) |
| chat-only family | no (HTTP 400 `does not support the responses endpoint`) | yes | `chat_completions` (chat provider) |

Rules that survive catalog changes:

- **Probe the model id on both routes before concluding anything.** Transport is per-model: one
  proxy serves responses-only, chat-only and both-route models side by side.
- **The Anthropic route is `/v1/messages`, not `/messages`.** A probe against `<proxy-base>/messages`
  returns `404 Unknown endpoint. Check the request path.` — a wrong-path artifact, not a dead proxy.
- **A gateway is not one host.** The same service can exist on two hosts with *different route maps
  and different keys*: one host may serve `/v1/chat/completions` only (`/v1/messages` →
  `404 no Route matched with those values`), while another serves `/v1/messages` but only with a
  specific key (`x-api-key` → 401). Same env var name, incompatible values. Probe (store, host) pairs
  and record which pairing answers, never assume the variable travels.
- On chat completions, reasoning tokens are charged against `max_tokens`. A 16k cap was consumed
  almost entirely by reasoning at `reasoning_effort: high` and the visible answer truncated
  mid-sentence; 40k is a working size for high-effort long-form work on one relay, and 60k triggered
  `504`. Re-measure per relay.
- Retry 5xx with backoff (transient upstream); never retry 4xx — those are config errors and retrying
  burns budget. `reasoning_effort` acceptance is not proof that effort engaged: read the returned
  reasoning-token count.
- Health: probe `/v1/models` (NOT `/api/v1/models`, which may 500 and look like the proxy is down).

## Reasoning-effort ladder benchmarking (chat-completions relays)

Measure a relay's effort→cost curve before choosing an effort level — ladder names
(low/medium/high/xhigh/max) are naming conventions, not a measured cost order. On one relay,
`medium` burned ~13k reasoning tokens, the same tier as `xhigh`/`max` (2.5–3-minute turns), while
`high` needed ~3.9k (~1 minute) and `low` ~0.8k (~20s). "Medium" was a rebranded max there, not a
middle setting.

Benchmark method that separates the tiers:

1. Use a prompt hard enough to force multi-step reasoning (a 3-variable system plus a follow-up
   question works); a simple prompt collapses every tier into seconds of noise.
2. Stream with `stream_options: {include_usage: true}`; record per-chunk timestamps for TTFT (first
   `reasoning_content` token, first `content` token), reasoning vs content char counts, and
   `usage.reasoning_tokens` (the authoritative measure — chars only feed rate math).
3. Run n≥2 per level and report medians; within-level variance ran 3.5× on a single tier.
4. Send a generous `max_tokens` (32k). Under a tight cap (8k) the heavy tiers spend the whole budget
   on `reasoning_content` and return ZERO visible content with `finish_reason: stop` — a "did it
   answer" check misreads budget exhaustion as success while the tokens still bill.
5. Measure the decode rate once (chars/s during the decode phase, roughly constant across tiers on
   one host). Total-time differences are length-driven, not speed-driven: there is no "fast" tier,
   only short-reasoning tiers.
6. Make aggregation None-safe before launching: an effort-`none` lane yields None TTFT/decode fields
   and empty median lists, and `%.1f % None` / `statistics.median([])` crash the summary after all
   the data was already collected.

Pitfalls:

- `reasoning_effort: "none"` is not "fast": on hard prompts the model migrates the reasoning into
  visible content (21k chars, ~92s) — slower than `low` (1.3k chars, ~16s). Reserve `none` for pure
  chat/formatting lanes.
- A relay may accept a reasoning knob and silently ignore it: one ignored `extra_body.thinking`
  (`{type: disabled}` still produced reasoning tokens) while honoring top-level
  `reasoning_effort: "none"` (0 reasoning tokens). Judge by the returned `usage.reasoning_tokens`,
  never by parameter acceptance.
- A vendor's published effort scale does not transfer to a relay fronting the same model family
  (one vendor's own ladder spread ran 4→125 tokens on its probe prompt; a relay's ran ~800→14k on a
  harder one — the shapes disagree). Re-measure per (relay, model) pair.

## Which reasoning wire shape a Hermes route sends

Config-defined providers (`providers:` entries in `config.yaml`) resolve to `CustomProfile`, not the
model family's vendor profile, unless the provider name or an alias matches a registered vendor
profile. Probe it live from the source tree before reasoning about wire shapes:

```bash
cd "$HERMES_HOME/hermes-agent" && python3 -c "
from providers import get_provider_profile
for n in ('<config-provider>', '<vendor-profile>'):
    print(n, '->', type(get_provider_profile(n)).__name__)"
```

`CustomProfile` sends top-level `reasoning_effort` clamped to the OpenAI-compat ladder (which includes
`xhigh`) — vendor-specific effort overrides (e.g. a profile's `xhigh → max`) never apply on this path.
With no `max_tokens` configured and no profile cap, the field is omitted entirely: no
budget-exhaustion risk, but also no guard against a heavy tier's 13k-token reasoning burn.

## External chat relays (not served by the localhost proxy)

- A relay can host a model that the local proxy's `/v1/models` does not list, so the harness registry
  must point at the relay directly. Verify with a tiny call that the returned `model` matches and
  that top-level `reasoning_effort: high` produces `reasoning_tokens > 0`.
- **Long reasoning calls must stream.** A non-streaming chat POST at `max_tokens: 20000` hit the
  client read timeout (~1800s) with no terminal event and no usable body; the identical request with
  `stream: true` completed (`finish_reason: stop`, ~4–5 min). Send `stream: true` and accumulate
  `choices[0].delta.content` (`delta.reasoning_content` carries the reasoning phase, which can run for
  minutes with zero visible content).
- A `max_tokens` that works on one relay may `504` on another; re-probe per relay.

## Two relays under one host (OpenCode Zen / Go)

Two relays can share a host but expose **different model sets** — the path segment picks the set, and
the same id can exist on one and not the other, so probe both before concluding a model is absent:

- the `/zen` path (the vendor's own ids; may host a `-free` tier)
- the `/zen/go` path (a second id namespace)

Hermes route resolution already encodes this: `hermes_cli.models` maps the relay family to its path
and re-derives the wire mode per model (the relay mixes responses-only, chat, and anthropic-wire
models behind one provider) — always re-derive from the effective model, never pin a provider-level
`api_mode`.

Rules that survive catalog churn:

- **A free tier can be gated to the vendor's own client.** Raw HTTP and other agent harnesses may be
  rejected with `403 FreeTierError: … can only be used from within …`. Drive it through the client
  the gate accepts; a different harness is still not that client.
- **The vendor CLI's model list is authoritative.** The relay's `/v1/models` may also list ids it no
  longer serves; a delisted id answers `410 ModelDeprecated`. Hermes filters some of these for its
  pickers, so trust the CLI list over the raw one.
- **A listed id is not a servable id.** Free-tier ids come and go: probe each with a tiny prompt
  (`Reply with exactly: ROUTE_OK`) before a fan-out. Signals seen: `429 ... Endpoint is unavailable`
  (endpoint down), `400 ... Model is unavailable` (not on that relay), `410 ModelDeprecated`.
- **Any project config file in the run directory can flip the whole free tier to 403** — run
  free-tier probes from a clean directory with no project config.
- Key env names differ between the runtime entry and the vendor CLI; map one to the other when
  handing a key across.
