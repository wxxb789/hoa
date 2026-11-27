# Provider aliases and endpoint/key rotation

<!-- install-root: `$HERMES_HOME` below means the install root; it defaults to `~/.hermes` -->

Keep secrets out of `config.yaml`, command output, and the transcript. Back up before changes. Editing
any `.env` from a session requires owner confirmation; prefer telling the owner the exact line to add
without the secret value.

<!-- migrated from the bundled hermes-agent skill (local addition) -->
## Adding a custom-endpoint provider alias

Register a user-named alias for a custom base URL:

```text
hermes config set model_aliases.<name>.model <model-id>
hermes config set model_aliases.<name>.provider custom
hermes config set model_aliases.<name>.base_url <url>
hermes config set model_aliases.<name>.key_env <NAME>_API_KEY
hermes config get model_aliases   # read back; not proof of routing
```

- `hermes config set` warns `not a recognized config key` for dotted `model_aliases.<name>.*` keys.
  The mapping is validated in aggregate (`hermes_cli/config.py`) and the set still lands; do not
  switch to `model_overrides` in response. `providers.<name>.*` keys set without this warning.
- Use the exact ID this endpoint serves, not the vendor catalog name. Ask the owner for the ID or
  leave a clearly marked placeholder in the proposed command if it is unknown.
- Set `<NAME>_API_KEY=...` in that home's `.env`. The alias is a `DirectAlias` resolved before the
  catalog, so it needs its own copy of the URL and key variable. Keep its URL aligned with the provider
  entry: a stale alias silently wins for `/model`.

<!-- migrated from the bundled hermes-agent skill (local addition) -->
## Rotating a provider endpoint / API key

Search the whole config for the old host and account for every hit before calling the rotation done:

- `model.base_url` — what the active model actually dials.
- `providers.<name>.api` — include any `<name>-messages` sibling that serves the same host over
  `anthropic_messages`. Repoint a sibling only after proving the new host serves its transport.
  If not, set `enabled: false` to hide it from the picker, `/models`, the resolver, and `doctor`
  rather than advertising a dead route at either URL.
- `model_aliases.<alias>.base_url` — include every affected alias.
- **Every profile:** `$HERMES_HOME/profiles/<p>/config.yaml` and that profile's own `.env`. Profiles
  inherit neither root config nor root credentials. For the write set and live proof per home,
  read [fleet provider rollout](fleet-provider-rollout.md).

Treat comments and prior notes as claims. Probe both the desired route and the old host/key pair
before deleting an entry or reporting it as retired. A route may have gained `/v1/responses`, and a
supposedly retired host may still authenticate and be a valid fallback.

Providers and aliases refer to secrets with `key_env: <NAME>_API_KEY`; the value belongs in the home's
`.env`. The credential store refuses `read_file`; use the terminal to load only the named key into a
shell variable without echoing it. `hermes config get` masks values: a masked `Authorization` header
can look like a literal even when the file contains `Bearer ${SOME_API_KEY}`. Inspect the raw config
block locally before claiming a second key needs rotation, without printing a literal secret.

Apply URLs with `hermes config set`, never by hand-editing `config.yaml`. Explain that changes take
effect in a new session or after a gateway restart; check traffic and get explicit approval before
any restart. Verify with a real request, not `config get`. The bundled `scripts/probe-provider-endpoint.sh`
(relative to the skill root) helps triage endpoint and auth responses.

### Gateway triage

Read the gateway's response body before changing config:

| Response | Meaning |
|---|---|
| `404 {"message":"no Route matched with those values"}` | Wrong path/route; try bare host, then `/v1`, then `/v1/chat/completions`. |
| `401 {"message":"No API key found in request"}` | The gateway does not read that header name. |
| `401 {"message":"Unauthorized"}` | The credential was read but rejected: the key value is the problem, not the URL. |
| `/v1/models` 404 while `/v1/chat/completions` answers | The gateway may only proxy chat. A missing `/models` alone proves nothing about the route. |
| `/v1/messages` 404 | No Anthropic route. Do not point an `anthropic_messages` sibling at this host. |
| `/v1/responses` 404 | No Responses route. `codex_responses` and the Codex CLI (which rejects `wire_api = "chat"`) cannot drive this gateway. |

**Stop probing at `401 Unauthorized`.** Before that point, the usual forms (`Authorization: <key>`,
`Authorization: Bearer <key>`, `X-API-KEY: <key>`) suffice to tell whether the gateway reads the
credential. `No API key found in request` identifies an unrecognized form; query-string variants
do not change the diagnosis. Once the credential is read but rejected, the owner must confirm the
key against its issuing source or check that the gateway has authorized it.

If a probe uses the key, redact it literally from every output line before printing. Show the owner
only a fingerprint (length, `first6…last4`, and `sha256[:12]`), never the value.
