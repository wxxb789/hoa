# Delegation routing and per-profile providers

## Delegation model routing (main session model A, subagents model B)

The "frontier planner, inexpensive workers" pattern: the parent keeps `model.default`; every
`delegate_task` child runs on the `delegation.model` pin. Set with `hermes config set
delegation.model <id>` plus `delegation.provider` or `delegation.base_url` for a different route.
Resolution lives in `tools/delegate_tool_config.py::_resolve_delegation_credentials` — rules that
are easy to get wrong:

1. Precedence: `delegation.base_url` → direct endpoint (`delegation.api_key` empty = inherit the
   parent key); else `delegation.provider` → full credential bundle via the runtime provider
   system; else pure inherit (parent provider + model + key + credential pool). `delegation.model`
   applies on every branch; empty = inherit the parent model.
2. The pin is global to the profile — `delegate_task` has no per-task model parameter. Per-task
   granularity needs another rail: a Kanban per-card override, a per-job cron pin
   (`hermes cron edit --model/--provider`), or an independent spawn
   (`hermes chat -q -m <model> --provider <p>`).
3. A pinned child never borrows the parent's fallback chain — pin means single-route. Give children
   their own with `delegation.fallback_providers` when the pinned route can flake.
4. `api_mode` is re-derived, never inherited, when the child's provider differs from the parent's —
   inheriting the parent's wire 404s on the child's endpoint. Respect any per-model transport split
   in the install: a responses-transport provider for `/v1/responses` models, a chat provider for
   chat-completions models.
5. Schema-bearing changes apply to NEW sessions only — the delegation tool schema is built at
   session start, so never flip the pin mid-conversation. Profiles never inherit root config: set
   the pin in each profile that must route children differently, then verify with a real child
   spawn and its live transcript (`HERMES_HOME/cache/delegation/live/<id>/task-0.log`) —
   `hermes config get` proves nothing about the route.
6. Read live limits before promising fan-out: `hermes config get delegation`. An install may
   override upstream defaults (concurrency, child inactivity timeout); quote the live values — an
   oversized batch returns a tool error, and a quiet child is abandoned at the local cap, not the
   documented one.

### Moving a profile onto a provider it does not define

A profile config carries its **own** `providers:` map, so pointing `model.provider` at a provider
that only root declares fails at runtime, and `config set` alone cannot make it work. Checklist per
profile:

1. Inspect first: `hermes --profile <p> config get model` + `config get providers` (key list).
2. Add the provider block (`name`, `api`, `key_env`, `transport`, `discover_models`, `models`).
   A dotted model id (`<vendor>-<major>.<minor>.<patch>`) cannot go through `hermes config set` — it
   splits into a phantom nested mapping — so round-trip the YAML with ruamel (`preserve_quotes`),
   then validate the temp file with a plain `yaml.safe_load` assert before replacing the live file.
   Back up first.
3. **Delete `model.api_key`.** Cloned profiles may carry an inline `api_key: local` for a local
   proxy; it outranks the provider's `key_env` and gets sent as the bearer token → 401 on the new
   route.
4. Copy the provider's `key_env` value into **that profile's own** `.env` — secrets are per
   `HERMES_HOME`, so a key only in root `.env` fails as an unscoped secret.
5. Verify per profile with a live one-shot (`hermes --profile <p> chat -q 'Reply exactly: X'`) plus
   `resolve_reasoning_config(load_config(), <model>)` under `HERMES_HOME=<profile>`; `config get`
   alone does not prove key, transport or effort.

No gateway restart is needed when `gateway.profile_routes` is empty — channel traffic resolves to
the root/default profile, and profile config is read when a profile session starts.
