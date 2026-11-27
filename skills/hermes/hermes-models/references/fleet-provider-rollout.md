# Provider rollout across a Hermes install

<!-- install-root: `$HERMES_HOME` below means the install root; it defaults to `~/.hermes` -->

Use this when adding or rotating a provider across root and profiles. Follow the parent skill's
fleet cutover gate for an outage, retirement, restore, or same-provider ID swap. For an endpoint or
key rotation, also read [provider rotation](provider-rotation.md) before editing.

## Write set and live proof per home

Inventory whose `config.yaml` and `.env` need to change, then back up each affected file. Set the
provider and optional alias in the root home and in each affected profile's own home. This example
uses Chat Completions; confirm the actual route with [custom providers](custom-providers.md).

```text
# Root; repeat the same applicable keys with HERMES_HOME set to the affected profile's home.
hermes config set providers.<name>.name "<Label>"
hermes config set providers.<name>.api <url>
hermes config set providers.<name>.key_env <NAME>_API_KEY
hermes config set providers.<name>.transport chat_completions
hermes config set providers.<name>.discover_models false
hermes config set providers.<name>.models.<model-id>.context_length <n>
hermes config set model_aliases.<name>.base_url <url>  # if the owner uses a /model alias
```

- Each profile has its own `$HERMES_HOME/profiles/<p>/.env` under the install root; it does not inherit
  root's key. Remove any inherited inline `api_key` that takes precedence over `key_env`. Add or update
  the secret only with owner confirmation, or have the owner do it.
- **Hermes never appends `/v1`**: Chat Completions posts to `{api}/chat/completions`. Store the entire
  mount prefix (e.g. `…/v1`). An omitted prefix can yield `404 {"detail":"Not Found"}` from the model
  server, distinct from a gateway's `no Route matched with those values`.
- Keep the optional alias and provider entry at the same URL. It is the alias that wins for `/model`.
- **Dotted IDs:** `providers.<name>.models.<dotted-model-id>.context_length` builds a phantom nested
  mapping. Preserve the existing entries and set the whole `models` map as one JSON value, e.g.
  `hermes config set providers.example.models '{"example-model":{"context_length":1048576},"example-model-v1.2":{"context_length":1000000}}'`.
  A YAML generator should emit plain dotted keys. Read back the parsed YAML after writing; a masked
  `config get` cannot prove map shape and a successful chat does not prove an override was read.
- **Drift checks:** strip a leading `custom:` when comparing resolved provider references against
  `providers:` keys. Use the bare key for `model.provider` and probe the actual resolver for auxiliary
  routes. For generated/provider files with repeated blocks, see [config drift](config-drift.md).

Verify every copy with a real text-only one-shot, then follow the full [live proof](model-switching.md#proof)
to verify the home’s session row and resolved reasoning configuration. Example one-shots (`-t clarify`
avoids accidentally enabling all tools):

```text
hermes chat --provider <name> -m <model-id> -q "Reply with exactly: OK" -t clarify --oneshot
hermes chat -m <alias> -q "Reply with exactly: OK" -t clarify --oneshot
HERMES_HOME="$HERMES_HOME/profiles/<p>" hermes chat --provider <name> -m <model-id> -q "Reply with exactly: OK" -t clarify --oneshot
```

## Account availability, pins, and fallbacks

- **Derive the live set per account.** Probe `/v1/models` on each configured route, then call each
  candidate once. If the candidate's actual route returns 404, `does not support the responses endpoint`,
  or an auth failure, remove or gate the broken route instead of retrying it under another alias.
- **Keep account bans in the install's own overlay** (`$HERMES_HOME/LOCAL_OVERRIDES.md` or home memory),
  not in this skill. Re-probe before repeating a ban: stale bans can hide working routes too.
- **Keep catalog entries needed for rollback.** Retire a model from live routing (`model.default`,
  delegation pins) without removing its catalog entry if it must remain reachable for rollback.
- **Pin `auxiliary.vision`, never `auto`.** `auto` follows the session model, which can be expensive
  or transport-incompatible. Pin both `provider` and `model` to a route each home actually defines
  in root and every profile. Verify with a real image call per profile, not `hermes doctor`.
- **Aliases and fallbacks are separate records.** `fallback_providers` entries are
  `{provider: <provider key>, model: <id>}` resolved through the provider registry in each home.
  Configure them separately in root and every profile. A fallback must use a **different provider**
  from `model.provider`, not another model on the same gateway. To prove alias resolution and fallback
  together, point a throwaway alias at a nonexistent ID. Verify that the error names the ID and the
  run continues with `Model fallback: … via <provider>`. Remove the probe alias afterward.
- **A pin or fallback needs an entry in that home's catalog.** Root can lack an ID that profiles already
  use as their default. Read the target home's `providers.<name>.models`, add the ID there first by
  writing the whole map, and only then wire the fallback or pin.
- **Probe effort variants before editing config.** A `#variant` comes from the client config. Verify the
  relay accepts it with a CLI override, e.g. `opencode run -m <provider>/<id>#max 'Reply with exactly: V_OK'`.
  Editing first obscures whether the variant was rejected or the relay was flaky.
