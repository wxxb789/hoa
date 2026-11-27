# Custom providers and per-model transport

## Custom providers (local proxy pattern)

When the user runs a local LLM proxy (e.g. ghc-proxy for GitHub Copilot), configure it under `providers:`
in `config.yaml`. `api_key: local` below is a non-secret placeholder for this local proxy pattern; for
an authenticated gateway, use `key_env` and follow [provider rotation](provider-rotation.md).

```yaml
providers:
  local-openai:
    name: local-openai
    api: http://localhost:4141       # replace with your proxy URL
    api_key: local
    transport: codex_responses       # for OpenAI Responses API
    models:
      <responses-model-id>: { context_length: 1000000 }
  local-chat:
    name: local-chat
    api: http://localhost:4141       # replace with your proxy URL
    api_key: local
    transport: chat_completions      # for chat-completions-only models
    models:
      <chat-model-id>: { context_length: 1048576 }
```

To set a default model from a `providers:` dictionary entry, use the exact bare dictionary key:

```yaml
model:
  default: <responses-model-id>
  provider: local-openai
  base_url: http://localhost:4141
  api_key: local
  api_mode: codex_responses
```

Transport types:
- `anthropic_messages` — Anthropic Messages protocol (availability depends on your upstream account;
  probe `/v1/models` and `/v1/messages` before configuring)
- `codex_responses` — OpenAI Responses protocol (GPT models)
- `chat_completions` — OpenAI Chat Completions protocol (Gemini models)
- Pick the provider by transport, not model family. In the example, Responses models belong in
  `local-openai` and Chat Completions models in `local-chat`.
- Declare per-model metadata with plain dotted keys (a dot-escaped key is silently ignored). See the
  [metadata audit](provider-metadata-audit.md) for how to verify the value actually resolves. For
  install-specific values, consult the generated `hermes-operations/references/local-install.md`
  sheet if the install provides it (`$HERMES_HOME/scripts/snapshot-install-facts.py`).

### Per-model transport and reasoning-budget sizing (probe, do not assume)

- **Transport is per-model, not per-endpoint.** One gateway can serve different protocols per
  model: on one local proxy, one model served `/v1/responses` but not `/v1/chat/completions`,
  while another served Chat Completions and returned HTTP 400 `does not support the responses endpoint`
  on `/v1/responses`. Probe both routes with the exact ID before concluding a capability is missing.
  Also confirm *that* endpoint serves the model: a model that lives on another provider can return
  `400 could not be resolved` / `not supported` and look like a protocol mismatch. Check the provider's
  catalog and `enabled` flag first.
- **On the chat-completions transport, reasoning tokens are charged against `max_tokens`.** At
  `reasoning_effort: high` a 16k cap was consumed almost entirely by reasoning and the answer was
  truncated mid-sentence at ~900 characters. Size the cap per model: reasoning appetite varies by
  ~70x across models on the identical prompt (251 → 18,620 tokens observed), so a cap that is
  comfortable for one model silently truncates another.
- **Very large caps are not free.** A 60k chat request tripped `504 Gateway Timeout` on the local
  proxy; an external gateway `504`d on every attempt at 40k while succeeding at 16k. Use the
  smallest cap that fits, and retry 5xx with backoff (transient upstream) but never 4xx (config
  error — retrying just burns the budget).
- **`reasoning_effort` is a request hint, not a guarantee.** Judge whether high effort actually
  engaged from the returned reasoning-token count, not from the parameter being accepted.
- **The effort ladder is per-relay and not monotonic in cost.** Benchmark the relay's
  effort→cost curve before settling on a level. On one relay `medium` used ~13k reasoning tokens
  (the same tier as `max`, 2.5–3-minute turns), while `high` needed ~3.9k. See the
  [endpoint matrix](model-endpoint-matrix.md) for the tier-separating benchmark method and pitfalls.
- **Verify which reasoning wire shape a route actually sends.** Config-defined providers resolve
  to `CustomProfile` (top-level `reasoning_effort`), not the model family's vendor profile, and
  a relay may honor one knob while silently ignoring another (`extra_body.thinking` ignored,
  top-level `reasoning_effort` honored). Probe with `get_provider_profile` and judge by the
  returned `usage.reasoning_tokens`.
- **Third-party gateways need their own headers.** The OpenCode Zen/Go relay requires a browser
  `User-Agent` (otherwise Cloudflare `403 error code: 1010`) *and* an
  `x-opencode-session: oneshot-<hex>` header (otherwise `400 MissingSessionID`). Hermes injects the
  session header itself (`agent/opencode_affinity.py`) when it is the caller, so a hand-rolled
  script must add both explicitly.
- **`usage` accounting is unreliable on some chat endpoints** (`total_tokens` does not reconcile
  with `prompt_tokens + completion_tokens`). Measure output by the text, not the token report.

See the [endpoint matrix](model-endpoint-matrix.md) for tested caps, the probe snippet, and the effort
ladder benchmark. For declared vs authoritative limits, redundancy, and delete-vs-declare decisions,
read the [metadata audit](provider-metadata-audit.md); the runnable probe is
`scripts/audit-provider-metadata.py` relative to the skill root.

Pitfalls:
- For `model.provider`, use the exact bare dictionary key (e.g. `local-openai`). Newer auxiliary
  routing can normalize `custom:<name>` aliases for named providers; probe the actual resolver
  being changed before rewriting a working auxiliary config.
- Verify provider resolution directly; a YAML/config-version check alone does not prove that the provider identity resolves.
- Provider model lists should include `context_length` so Hermes can manage compression thresholds correctly.
- Default model/provider changes take effect on `/new` or the next session start. Messaging-channel
  default changes need a gateway restart; follow the traffic and approval gate in `SKILL.md` first.
