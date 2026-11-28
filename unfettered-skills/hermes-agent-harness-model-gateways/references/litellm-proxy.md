# LiteLLM proxy as a provider

A LiteLLM gateway ("proxy server to call 100+ LLMs in the OpenAI format") is one host that fronts
many upstreams. Treat it as a *provider of aliases*, not as the vendor behind each alias.

## Route map

`/v1/chat/completions`, `/v1/messages` (Anthropic shape) and `/v1/responses` (Codex wire) are
normally all mounted on the same host. Probe each one you intend to use: a `401` (not `404`) with no
key proves the route exists.

**Route existence is not per-model support.** LiteLLM forwards each model to its own upstream, so
`/v1/responses` can be `200` for one alias and `501 "Responses endpoint not implemented"` for
another on the same proxy (seen with a GLM alias whose upstream lacked the endpoint, while the
DeepSeek and Kimi aliases answered). A `401` probe with no key cannot distinguish these — re-probe
every route *with* the key, per model, before declaring a harness wire usable.

```bash
BASE=https://<proxy-host>
for p in /health/readiness /v1/models /v1/chat/completions /v1/messages /v1/responses; do
  echo "$p -> $(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE$p" \
    -H 'Content-Type: application/json' -d '{"model":"x","messages":[{"role":"user","content":"hi"}]}')"
done
```

## Virtual keys

Keys are issued by the proxy (UI at `/ui`), not by the upstream vendor, and must start with `sk-`.
A key of the wrong shape answers:

```
401 LiteLLM Virtual Key expected. Received=PAST****HERE, expected to start with 'sk-'.
```

Read that as **URL and path are correct, only the credential is wrong** — it is the cheapest proof
that a provider entry is wired correctly before a real key exists. Put a visible placeholder
(`PASTE_<SOMETHING>_API_KEY_HERE`) in the credential store so this error names the placeholder
instead of looking like a real rejection.

## A 501 on `/v1/responses` is an upstream gap, not a LiteLLM gap

A deployment whose `custom_llm_provider` is `litellm_proxy` is a **native** Responses provider in
LiteLLM (`LiteLLMProxyResponsesAPIConfig.get_complete_url()` → `{api_base}/responses`), so the body
is forwarded untranslated. Bridging only happens when the provider has no Responses config at all, or
when the deployment sets `litellm_params.use_chat_completions_api: true`
(`litellm/responses/main.py`: `config is None or use_chat_completions_api is True`).

So `501 "Responses endpoint not implemented"` means the **upstream gateway** does not serve
`/responses` — the string does not exist anywhere in LiteLLM's own source (verified against the
1.105.1 PyPI sdist). Do not diagnose it as missing bridge support. Options, all server-side:

| Fix | Effect |
|---|---|
| `litellm_params.use_chat_completions_api: true` on that deployment | forces `/responses` → chat bridge |
| declare the upstream as `custom_openai/…` | no native Responses config → bridges by default |
| `openai/…` prefix | **no** — it also passes through natively, same 501 |
| `model_info.supported_endpoints: ["/v1/responses"]` | forces native passthrough — the wrong direction |

A client-side model string cannot turn the bridge on. Chat stays the universal wire; keep
responses-only clients (Codex) on the models whose upstream actually implements `/responses`.

## Per-model routing rules (measured on this proxy, 2026-10-31)

| Alias | chat | messages | responses | Notes |
|---|---|---|---|---|
| `GLM-5.3` | 200 | 200 | **501** | always-on reasoning: a tiny `max_tokens` is eaten by reasoning and returns empty content with `finish_reason=length`; `reasoning_effort: none` is not honoured. Give it real budget. 1M window (owner-stated). |
| `KimiK3` | **503** | — | — | **retired 2026-11-13** (owner-confirmed): the proxy still *advertises* the id in `/v1/models` but every call returns 503. Removed from all Hermes homes, pi/omo/omp/opencode/dsh catalogs and the NRS harness registry. A catalog listing is not evidence the model works — call it. |
| `deepseek-v4.1-flash` | 200 | 200 | 200 | cheapest, no rate ceiling observed; default choice for fan-out. 1M window (owner-stated). |
| `deepseek-v4.1-flash-fast` | 200 | 200 | 200 | low-reasoning variant, fleet default. 1M window (owner-stated). |

KimiK3 used to pass direct `/v1/responses` probes (streaming and non-streaming, with and without
`reasoning.effort`) but produced **empty output inside Codex's agent loop** (tools enabled, raw
chat-template tokens in the log). That lesson outlived the id: a 200 on the wire is not proof the
harness loop works — re-verify with a real `codex exec` run before wiring any new id as a Codex profile.

## Model catalog

Model ids are proxies' `model_name` aliases — they may or may not match the upstream vendor id, so
they cannot be guessed. `GET /v1/models` requires the virtual key; the unauthenticated surface is
`/public/model_hub`, which returns `[]` unless the deployment publishes models. Consequences:

- Hermes: set `discover_models: true` and omit a static `models` map; `/model` then lists the proxy
  catalog once the key is valid.
- pi / omp / omo / OpenCode / dsh / Codex: the catalog is static in config. Register the provider
  now (base URL + key reference) with an empty model list, and populate it after the key lands:

```bash
curl -s "$BASE/v1/models" -H "Authorization: Bearer $TENCENT_LITELLM_API_KEY" | jq -r '.data[].id'
```

Never transcribe the upstream vendor's model list into the provider as a guess.

## Credential placement per harness

LiteLLM adds no new credential model — each harness still resolves its own store (see
`harness-config-recipes.md`). Common partition on a multi-harness host:

| Harness | Entry | Key store |
|---|---|---|
| Hermes (root + every profile) | `providers.<name>` in each `config.yaml` | that home's `.env` — profiles never inherit root |
| pi / omo | `models.json` (`openai-completions`) | `auth.json` → `{provider: {type: api_key, key}}` |
| omp | `models.yml`, `apiKey:` holds the **env var name** | `~/.omp/agent/.env` |
| OpenCode | `opencode.jsonc` `"env": [VAR]` | `service.json` env (or shell env for `--standalone`) |
| Codex | `config.toml [model_providers.<name>]`, `env_key` | shell env, sourced from a 600-mode keys file by `~/.bashrc` |
| dsh | `cordis.patch.yml`, `apiKeyEnv` | `.credentials.yaml` `refs:` **and** process env |

One variable name, one value, one source: run a fingerprint check (`len` + `sha256[:12]`) before
assuming two harnesses share a credential; a shell export silently overrides a harness's own store.
