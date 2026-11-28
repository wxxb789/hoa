# Harness config recipes

Substitute `<name>` / `<NAME>` (provider id), `<Label>`, `<ID>` (model id the endpoint serves),
`<BASE_URL>` (includes the gateway's mount prefix — usually `/v1`), `<n>` (context/token numbers).

The key never goes in a provider file. Back every file up first:
`cp -p <file> <file>.bak-$(date +%Y%m%d-%H%M%S)`.

## Hermes — provider entry (+ the `/model` alias)

```bash
hermes config set providers.<name>.name "<Label>"
hermes config set providers.<name>.api "<BASE_URL>"                 # must include /v1
hermes config set providers.<name>.key_env <NAME>_API_KEY
hermes config set providers.<name>.transport chat_completions     # | anthropic_messages | codex_responses
hermes config set providers.<name>.discover_models false
hermes config set providers.<name>.models.<id>.context_length <n>

# the /model handle — keep it on the SAME URL as the provider block
hermes config set model_aliases.<name>.model <id>
hermes config set model_aliases.<name>.provider custom
hermes config set model_aliases.<name>.base_url "<BASE_URL>"
hermes config set model_aliases.<name>.key_env <NAME>_API_KEY
hermes config get providers.<name>          # read back (values are masked)
```

- Per profile: prefix `HERMES_HOME=$HOME/.hermes/profiles/<p>` on every command, and append
  `<NAME>_API_KEY=…` to that profile's own `.env`. Profiles inherit neither root config nor root
  `.env`.
- `providers.<name>.*` dotted keys set silently; the "not a recognized config key" warning is normal
  for `model_aliases.<name>.*` and the value still lands.
- Preserve dotted model IDs as literal mapping keys. Do not infer correct storage from a successful
  dotted-path command: an unescaped path can create nested mappings, while an escape can survive as
  part of the model ID. Inspect the exact stored key and verify
  `get_custom_provider_context_length(<id>, <base-url>, config=<loaded-config>)`; a catalog-derived
  window or successful chat does not prove the configured override was read. Check the installed
  CLI's mapping-update support before choosing a writer, and preserve sibling model declarations.
- `config.yaml` and `.env` refuse `read_file`/`patch`/`write_file` — use `hermes config set` and
  terminal redirection only.

### Hermes — a models map whose ids contain dots

`hermes config set providers.<n>.models.<dotted.id>.context_length <n>` builds a *nested* mapping
(`deepseek-v4.1-flash` becomes `deepseek-v4: {1-flash: …}`). Set the whole map as one JSON value
instead — the CLI stores it verbatim, dotted ids stay literal keys:

```bash
hermes config set providers.<name>.models \
  '{"GLM-5.3":{"context_length":1000000},"deepseek-v4.1-flash":{"context_length":1000000},"deepseek-v4.1-flash-fast":{"context_length":1000000}}'
hermes config set providers.<name>.discover_models false
```

(`KimiK3` was dropped from this example when the id was retired 2026-11-13 — keep the example on live ids.)

- `discover_models: true` is the right default while the catalog is unknown, but `GET /v1/models`
  normally returns ids with **no context window**; switch to `false` + an explicit map once you have
  the ids, or compaction budgets fall back to a default that understates a 1M window.
- Read back with a YAML parse, not `config get`: the masked display hides the `api` value and cannot
  prove the map shape.

## Model metadata blocks (pi / omp / omo / OpenCode / dsh / Codex)

A provider entry with no models is a **stub**: it authenticates, nothing can be selected. Ship one only
with a recorded follow-up, and fill it from the live catalog as soon as the key exists.

| Harness | Per-model fields |
|---|---|
| pi / omo (`models.json`) | `id`, `name`, `reasoning`, `contextWindow`, `maxTokens`, `thinkingLevelMap` (`off/minimal/low/medium/high/xhigh/max` → provider effort value or `null`), `input`, `cost{input,output,cacheRead,cacheWrite}` (USD per 1M) |
| omp (`models.yml`) | `id`, `name`, `reasoning`, `thinking{mode: effort, efforts: [...], requiresEffort}`, `contextWindow`, `maxTokens`, `compat{supportsReasoningEffort, reasoningContentField}`, `cost{…}`; provider `apiKey:` holds the **env var name** |
| OpenCode (`opencode.jsonc`) | `name`, `capabilities{tools,input,output}`, `limit{context,input,output}`, `cost{input,output,cache_read,cache_write}`, `variants[{id, body{reasoning_effort}}]`; the schema has `cost` but **no** `rpm`/`tpm` |
| dsh (`cordis.patch.yml`) | `id`, `name`, `contextWindow`, `maxTokens`, `reasoningEfforts{off,low,high,xhigh,max}` |
| Codex profile | `model`, `model_provider`, `model_reasoning_effort`, `model_context_window` — no max-output key needed |

Copy pricing from the gateway's own `/model/info` (`input_cost_per_token` × 1e6) instead of guessing;
the harnesses show session cost from it. Model ids that an upstream implements on one wire only (e.g.
`/responses` for some aliases, not others) belong in a comment in the profile file so the next session
does not re-probe them.

### Keeping N static catalogs in sync with the gateway

The endpoint is the source of truth for **ids**; metadata (context, max output, thinking levels, price)
is not in `/v1/models`, so keep a small local spec keyed by model id and merge it in:

- One script, one run: `GET /v1/models` → for each id take `MODEL_SPEC[id]` (conservative defaults for
  unknown ids) → rewrite every harness catalog plus the Hermes `models` map. Hand-editing five files is
  the failure mode this replaces.
- **Idempotent, and prove it:** a second run must report `0 updated, N unchanged`. Compare the
  serialized provider block before writing, not merely "the file exists".
- Ship `--dry-run`, back up each target into one timestamped tree, and print a per-target
  `updated|unchanged` table — that table is the receipt the owner reads.
- Hermes is the odd one out: write its map through `hermes config set …models '<json>'` under each
  `HERMES_HOME` (see the dotted-id section above), never by editing YAML in place.
- Enumerate profile dirs at run time (`profiles/*`); the set changes between runs and a hardcoded list
  silently skips the profile someone just created.

## OpenCode — `~/.config/opencode/opencode.jsonc`

```jsonc
"providers": {
  "<name>": {
    "name": "<Label>",
    "env": ["<NAME>_API_KEY"],
    "package": "@opencode/ai/providers/openai-compatible",   // or .../anthropic
    "settings": { "baseURL": "<BASE_URL>" },                 // includes /v1
    "models": {
      "<ID>": {
        "name": "<ID>",
        "capabilities": { "tools": true, "input": ["text"], "output": ["text"] },
        "limit": { "context": <n>, "input": <n>, "output": <n> },
        "variants": [ { "id": "none", "body": { "reasoning_effort": "none" } } ]
      }
    }
  }
}
```

Credential: `opencode service set env <NAME>_API_KEY <value>` (stored in `service.json`, used by the
background server). `--standalone` uses the shell environment instead, so export it there too.
Anthropic transport needs `"package": "@opencode/ai/providers/anthropic"` and an explicit
`"headers": { "Authorization": "Bearer {env:<NAME>_API_KEY}" }` when the gateway rejects `x-api-key`
alone.

For a verified keyless local proxy, omit credential `env` declarations instead of creating a new
credential store. When supported by the installed schema, set model
`compatibility.maxTokensField: max_tokens` for chat routes and expose reasoning choices through
`variants` with `body.reasoning_effort`. Test the normal configuration first; isolate plugins only
when an actual error implicates them.

## Codex — `~/.codex/config.toml` + a profile file

```toml
[model_providers.<name>]
name = "<Label>"
base_url = "<BASE_URL>"
wire_api = "responses"        # "chat" is rejected by Codex >= 0.157
env_key = "<NAME>_API_KEY"
```

```toml
# ~/.codex/<name>.config.toml   (CONFIG_PROFILE_V2)  ->  codex -p <name>
model = "<id>"
model_provider = "<name>"
model_reasoning_effort = "low"
# model_context_window = <n>   # pin the window for a model Codex's catalog does not know
```

Codex reads the key from the process environment. Write `export <NAME>_API_KEY='…'` into a 600-mode
file (and `chmod 700` its dir) and source it from `~/.bashrc`:

```bash
[ -f "$HOME/.config/tencent/keys.env" ] && . "$HOME/.config/tencent/keys.env"
```

Requires the gateway to serve `/v1/responses`; a chat-only gateway cannot drive Codex.

## dsh / dsh-tui — `~/.dsh/cordis.patch.yml` (+ `.credentials.yaml`)

```yaml
- id: llm-pi-ai
  config:
    providers:
      <name>:
        displayName: <Label>
        apiKeyEnv: <NAME>_API_KEY
        api: openai-completions
        baseURL: <BASE_URL>
        models:
          - id: <id>
            name: <id>
            contextWindow: <n>
            maxTokens: <n>
            reasoningEfforts:
              "off": none
              low: low
              xhigh: xhigh
```

- The home-level patch applies over every profile's own patch, so `headless`, `dsh-tui` and `web` all
  inherit the route.
- Credential: add `<NAME>_API_KEY: <value>` under `refs:` in `~/.dsh/.credentials.yaml` (600) **and**
  export the variable in the process environment. The ref alone has been observed to 401 with a
  byte-correct value.
- For a proxy already proven keyless, omit `apiKeyEnv`. If pi-ai rejects the request locally with
  `No API key for provider`, the supported `headers.Authorization: Bearer unused` nonsecret SDK
  placeholder can satisfy the client without changing credential files. Re-test the actual request;
  do not use this workaround for an endpoint that requires real authentication.
- Inspect composed providers with `dsh --profile <name> --dump-config` and
  `dsh-tui --dump-config`, filtering parsed output before printing because other providers may
  embed credentials. Compare the exact provider/model and retained defaults, not a short grep excerpt.
- A `settings.yaml` renamed to `settings.yaml.imported` by an upgrade no longer feeds live config —
  routes must be in `cordis.patch.yml`.

## Verification one-shots

```bash
hermes chat --provider <name> -m <id> -q "Reply with exactly: OK" --oneshot
hermes chat -m <name> -q "Reply with exactly: OK" --oneshot        # the alias path
HERMES_HOME=~/.hermes/profiles/<p> hermes chat --provider <name> -m <id> -q "…" --oneshot
opencode run --standalone --model <name>/<id> "Reply with exactly: OK"
codex exec -p <name> --skip-git-repo-check "Reply with exactly: OK"
dsh --profile headless --patch <overlay.yml> "Reply with exactly: OK"
```

Overlay that forces a dsh headless run onto the new route:

```yaml
- id: agent-default-model
  config:
    provider: <name>
    model: <id>
```

Isolating an OpenCode run from plugins (throwaway config, files untouched):

```bash
verify_dir=$(mktemp -d "${TMPDIR:?}/oc-verify.XXXXXX")
# Copy only the necessary config into "$verify_dir/opencode.jsonc", dropping plugins.
OPENCODE_CONFIG="$verify_dir/opencode.jsonc" XDG_CONFIG_HOME="$verify_dir" \
  opencode run --standalone --model <name>/<id> "Reply with exactly: OK"
```
