# Custom providers and per-model transport


## Custom providers (local proxy pattern)

When the user runs a local LLM proxy (e.g. ghc-proxy for GitHub Copilot), configure Hermes to use it via `providers:` in config.yaml.

Key config shape:

```yaml
providers:
  local-openai:
    name: local-openai
    api: http://localhost:4141
    api_key: local
    transport: codex_responses       # for OpenAI Responses API
    models:
      gpt-6-luna: { context_length: 1000000 }
  local-chat:
    name: local-chat
    api: http://localhost:4141
    api_key: local
    transport: chat_completions      # for chat-completions-only models
    models:
      gemini-3.8-flash: { context_length: 1048576 }
```

To set a default model from a `providers:` dictionary entry, use the exact bare dictionary key:

```yaml
model:
  default: gpt-6-luna
  provider: local-openai
  base_url: http://localhost:4141
  api_key: local
  api_mode: codex_responses
```

Transport types:
- `anthropic_messages` — Anthropic Messages protocol (protocol is supported by ghc-proxy; on this account
  the Claude family is unavailable, so nothing is configured on this transport)
- `codex_responses` — OpenAI Responses protocol (GPT models)
- `chat_completions` — OpenAI Chat Completions protocol (Gemini models)
- Declare per-model metadata with plain dotted keys (a dot-escaped key is silently ignored) — full
  procedure and the "declared value does not resolve" trap: `references/provider-metadata-audit.md`;
  install-specific values: the generated `hermes-operations/references/local-install.md` sheet (`~/.hermes/scripts/snapshot-install-facts.py`).

### Per-model transport and reasoning-budget sizing (probe, do not assume)

- **Transport is per-model, not per-endpoint.** One gateway can serve different protocols per
  model: on the local proxy `gpt-5.6-*` answers on `/v1/responses` and rejects
  `/v1/chat/completions`, while `gemini-3.*-flash` answers on `/v1/chat/completions` and returns
  HTTP 400 `does not support the responses endpoint` on `/v1/responses`. A "this proxy is
  Responses-only" belief is wrong for mixed catalogs and costs a whole debugging cycle — probe both
  routes with the model id before concluding anything. Also confirm the model is served by *that*
  endpoint at all: a model that lives on another provider (an external relay, another `providers:`
  entry) answers `400 could not be resolved` / `not supported` on the local proxy and reads exactly
  like a capability gap — check the provider's model list and its `enabled` flag before concluding a
  capability is missing.
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
  effort→cost curve before settling on a level: on the tencent-glm relay `medium` burns ~13k
  reasoning tokens — the same tier as `max`, 2.5-3-minute turns — while `high` needs ~3.9k. A
  "middle" effort name is not a middle cost. Tier-separating benchmark method and pitfalls:
  `references/model-endpoint-matrix.md`.
- **Verify which reasoning wire shape a route actually sends.** Config-defined providers resolve
  to `CustomProfile` (top-level `reasoning_effort`), not the model family's vendor profile, and
  a relay may honor one knob while silently ignoring another (`extra_body.thinking` ignored,
  top-level `reasoning_effort` honored). Probe with `get_provider_profile` and judge by the
  returned `usage.reasoning_tokens`. Details: `references/model-endpoint-matrix.md`.
- **Third-party gateways need their own headers.** The OpenCode Zen/Go relay requires a browser
  `User-Agent` (otherwise Cloudflare `403 error code: 1010`) *and* an
  `x-opencode-session: oneshot-<hex>` header (otherwise `400 MissingSessionID`). Hermes injects the
  session header itself (`agent/opencode_affinity.py`) when it is the caller, so a hand-rolled
  script must add both explicitly.
- **`usage` accounting is unreliable on some chat endpoints** (`total_tokens` does not reconcile
  with `prompt_tokens + completion_tokens`). Measure output by the text, not the token report.

Endpoint matrix, caps that worked, the probe snippet, and the relay reasoning-effort ladder benchmark: `references/model-endpoint-matrix.md`.
Provider/model metadata audit (declared vs authoritative limits, redundancy, delete-vs-declare): `references/provider-metadata-audit.md`; runnable probe: `scripts/audit-provider-metadata.py`.

Pitfalls:
- For the primary model path, `providers:` dictionary entries require the exact bare key (for example `local-openai`) when resolving `model.provider`; do not infer auxiliary behavior from that resolver alone. Newer auxiliary routing can normalize `custom:<name>` aliases for named providers, so probe the actual path being changed before rewriting a working auxiliary config.
- Verify provider resolution directly; a YAML/config-version check alone does not prove that the provider identity resolves.
- Provider model lists should include `context_length` so Hermes can manage compression thresholds correctly.
- After changing default model/provider, the change takes effect on `/new` or next session start. Restart the gateway when changing messaging-channel defaults.

<!-- migrated from the bundled hermes-agent skill (local addition) -->
### Adding a custom-endpoint provider alias (recipe)

To register a user-named provider on a custom base URL (e.g. a private gateway):

```
hermes config set model_aliases.<name>.model <model-id>
hermes config set model_aliases.<name>.provider custom
hermes config set model_aliases.<name>.base_url <url>
hermes config set model_aliases.<name>.key_env <NAME>_API_KEY
hermes config get model_aliases   # verify
```

- `hermes config set` warns "not a recognized config key" for each dotted
  `model_aliases.<name>.*` key — expected; the key is validated as a mapping in
  aggregate (`hermes_cli/config.py`), and the set still lands. Do not switch to
  `model_overrides` in response to the warning.
- The model id must be the id the ENDPOINT serves, not the vendor catalog name —
  ask the user for it or leave a placeholder and flag it.
- The API key goes in `~/.hermes/.env` as `<NAME>_API_KEY=...` — secrets never in
  config.yaml. Editing `.env` from a session requires owner confirmation (approval
  gate); prefer telling the user the exact line to add themselves.

<!-- migrated from the bundled hermes-agent skill (local addition) -->
### Rotating a provider endpoint / API key (gateway triage)

An endpoint rotation is never one config key. Grep the WHOLE config for the OLD host and fix
every hit before calling it done:

- `model.base_url` — what the active model actually dials
- `providers.<name>.api` — for the provider AND for any `<name>-messages` sibling that serves
  the same host over a different transport (`anthropic_messages`). A sibling can only be repointed
  if the NEW host actually routes that transport: gateways are often chat-only, and then the sibling
  is unusable — disable it (`enabled: false`, which hides it from the picker, `/models`, the resolver
  and `doctor`) instead of leaving it aimed at either host. Pointing a dead sibling at the new host
  trades one wrong answer for another.
- `model_aliases.<alias>.base_url` — if the endpoint was registered as an alias instead
- **every profile** — `~/.hermes/profiles/<p>/config.yaml` AND that profile's own `.env`. A profile
  is a separate HERMES_HOME and inherits neither the root `config.yaml` nor the root `.env`, so a
  provider that works in the default profile is unauthenticated (or absent) everywhere else.

Config-file comments and earlier notes are claims, not evidence. A comment reading "this gateway has
no `/v1/responses`, so Codex cannot drive it" — or "host X is retired" — can be stale in either
direction: the route may have been added, and the old host+key pair may still answer `200`. Probe the
route, and probe the old pair, before you delete an entry or repeat the claim to the owner. A
"retired" gateway that still authenticates with its old key is a working fallback, not litter.

Keys are not in `config.yaml`: a provider points at `key_env: <NAME>_API_KEY` and the secret
lives in `~/.hermes/.env` (per profile: `profiles/<p>/.env`). That file refuses `read_file`
(credential store) — read it through the terminal, never echo the value.

`hermes config get` MASKS values, so a line like `extra_headers: Authorization: Bear<a>...<d>`
looks like a hardcoded literal token when it is really `Bearer ${SOME_API_KEY}` env
interpolation. Before telling the owner there is a second credential to rotate, read the raw
block off disk (`sed -n 'A,Bp' ~/.hermes/config.yaml`).

Apply URLs with `hermes config set …` (never hand-edit config.yaml) and say plainly that the
change only lands in a NEW session / after a gateway restart. Verify with a real request, not
`config get` — `scripts/probe-provider-endpoint.sh`.

The gateway's own response body tells you which layer is broken. Triage before changing
anything:

| Response | Meaning |
|---|---|
| `404 {"message":"no Route matched with those values"}` | path/route wrong — try bare host, then `/v1`, then `/v1/chat/completions` |
| `401 {"message":"No API key found in request"}` | the gateway does not read that header NAME |
| `401 {"message":"Unauthorized"}` | credential read but rejected — the KEY VALUE is the problem, not the URL |
| `/v1/models` 404 while `/v1/chat/completions` answers | gateway proxies only the chat route; a missing `/models` proves nothing about the URL |
| `/v1/messages` 404 | no Anthropic route on this gateway — an `anthropic_messages` sibling cannot be pointed at it |
| `/v1/responses` 404 | no Responses route — a `codex_responses` transport (and the Codex CLI, which rejects `wire_api = "chat"`) cannot drive this gateway |

**Once a request reaches `401 Unauthorized`, stop probing.** Two header forms
(`Authorization: <key>` / `Authorization: Bearer <key>`, plus `X-API-KEY: <key>`) are enough to
establish that the gateway reads the header; a key-auth gateway answers `No API key found in
request` for every name it does not read, and query strings (`?apikey=`, `?key=`) are the same
signal. Further variants cannot succeed. Hand it back: the owner confirms the key against the
source text it was issued in, or the gateway has not authorised it yet. Presenting this as a
client-side config bug sends the session into a probe loop with no possible exit.

Secret-safe handling when you must use the key for a probe: load it into a shell variable, pipe
every output line through `sed -e "s/$KEY/<KEY>/g"`, and show the owner only a fingerprint
(length + `first6…last4` + `sha256[:12]`) so they can confirm the value without it entering
the transcript.

### Adding / rotating a provider across the whole install

The full write set for one provider, then a live request per copy:

```bash
# root
hermes config set providers.<name>.name "<Label>"
hermes config set providers.<name>.api <url>          # must include the gateway's path prefix
hermes config set providers.<name>.key_env <NAME>_API_KEY
hermes config set providers.<name>.transport chat_completions
hermes config set providers.<name>.discover_models false
hermes config set providers.<name>.models.<model-id>.context_length <n>
hermes config set model_aliases.<name>.base_url <url>  # the /model handle, if the owner uses one

# every profile: same keys under a profile-scoped HOME …
HERMES_HOME=~/.hermes/profiles/<p> hermes config set providers.<name>.api <url>
# …and the key appended to that profile's OWN .env (back it up first)
```

- **Hermes never appends `/v1`** — it posts to `{api}/chat/completions`. The stored URL must carry
  whatever prefix the gateway mounts the service under (`…/v1`). A URL missing it answers
  `404 {"detail":"Not Found"}`: an app-level 404 from the model server, nothing like a gateway's
  `no Route matched with those values`.
- Keep the alias and the provider entry on the SAME URL. A user alias is resolved before the
  built-in table and outranks the provider for `/model`, so an alias left pointing at an old URL
  breaks the model with no warning.
- Verify every copy with a real one-shot; `config get` proving the key is set proves nothing:

```bash
hermes chat --provider <name> -m <model-id> -q "Reply with exactly: OK" --oneshot
hermes chat -m <alias> -q "Reply with exactly: OK" --oneshot
HERMES_HOME=~/.hermes/profiles/<p> hermes chat --provider <name> -m <model-id> -q "…" --oneshot
```

- `providers.<name>.*` dotted keys set cleanly and silently; the "not a recognized config key"
  warning is expected only for `model_aliases.<alias>.*` (the set still lands).

## Account-specific policy is the operator's, not this file's

Which ids an account can actually serve is per-account: one installation's retired tier is another's
working route. This skill therefore ships the **method**, not a ban list — a config that lists a provider
the account cannot serve silently advertises dead routes, and that is the defect worth catching.

- **Derive the live set, do not inherit it.** Probe `/v1/models` on each configured route, then call each
  candidate once. A 404, `does not support the responses endpoint`, or an auth failure means the route is
  dead *for this account*; the fix is to remove or gate it, not to retry it under a new alias.
- **Keep each install's own bans in that install's overlay** — `$HERMES_HOME/LOCAL_OVERRIDES.md` or the
  home's own memory — and treat a stale entry there as the same defect in the other direction: a ban that
  outlived the account change hides a route that now works. Re-probe before repeating a ban as fact.
- **A retired id is a catalog question, not a routing one.** If a model must stay reachable for rollback,
  leave the entry and remove only the live route (`model.default`, delegation pins) — that is what makes a
  rollback a single key flip.
- **`auxiliary.vision` must be pinned, never `auto`.** With `auto` the vision task resolves to the
  session model (expensive, and transport-mismatched on some routes). Pin `provider` + `model` in root
  **and** every profile to a route that profile actually defines (`local-chat` + a `gemini-*` model on
  this box), then prove with a real image call, not `hermes doctor`.
- **Transport picks the provider, not the model family**: `/v1/responses` models live in
  `local-openai`, chat-completions models in `local-chat`. Adding a model to the wrong provider looks
  like a capability gap (`400 does not support the responses endpoint`).
