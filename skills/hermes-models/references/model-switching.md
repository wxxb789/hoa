# Switching models and fallback hygiene

### Switching the default model and proving the route

1. Back up config, then set the route in this order — writing `model.provider` **clears** the
   `model.base_url` / `model.api_mode` that belonged to the previous provider, so set those after
   the provider:
   `mkdir -p "$HERMES_HOME/backups/model-switch-$(date +%Y%m%d-%H%M%S)" && cp "$HERMES_HOME/config.yaml" "$HERMES_HOME/backups/model-switch-$(date +%Y%m%d-%H%M%S)/config.yaml"`,
   then `hermes config set model.default <id>`, `model.provider <providers-key>`,
   `model.api_mode chat_completions` (`codex_responses` for Responses routes),
   `model.base_url <provider api>`, `agent.reasoning_effort <level>`. Use the exact bare
   `providers:` key (`<provider-key>`, not a made-up short form).
2. `agent.reasoning_effort` is **global**, not per-model: changing it re-tiers every other
   selectable model too. Keep per-model levels in `agent.reasoning_overrides` rather than accepting
   that collateral change, and tell the owner which other models moved. The "not a recognized
   config key" warning on `config get agent.reasoning_effort` is noise — the runtime reads it.
3. Prove the route with three independent signals, never from `config get` alone:
   - one-shot: `hermes chat -q 'Reply with exactly: PROBE_OK'` must echo the token;
   - the row that run created: `SELECT model FROM sessions ORDER BY started_at DESC LIMIT 1`
     (read-only `state.db`) must name the new model;
   - `resolve_reasoning_config(load_config(), "<model>")` under the toolchain python with
     `PYTHONPATH=<repo>` must report the intended effort.
4. Regenerate the install's config snapshot if it keeps one, then restart the gateway if channels
   must pick it up. Profiles keep their own pins: root `model.default` governs unrouted channel
   traffic, so state plainly that profiles are still on the old model unless you mirror them.

Deployment recipe for ghc-proxy: `cases.md#ghc-proxy-systemd-user-service` (covers systemd unit,
daily-restart timer, localhost firewall, concurrency tuning via `--upstream-queue-concurrency`, and
the health-check endpoint pitfall — curl must probe `/v1/models`, NOT `/api/v1/models` which 500s as
a false "service down").

With ghc-proxy in place, direct vendor-source patches to Hermes (enterprise token exchange, IDE auth
headers, etc.) are no longer needed. Keep Hermes on clean upstream `main` and let the proxy handle
the vendor API translation. Test/amend patterns remain valid for any Hermes source work, but
vendor-specific patches should not be reintroduced.

### Fallback hygiene after a vendor deprecates model ids

When a provider deprecates model slugs, remove them from both active runtime config and static
fallback catalogs. Do not keep a deprecated id as a fallback/cheap model. Prefer the vendor's current
supported set and verify it against `/v1/models` — which ids survive is a per-account fact, not a
skill constant.

Checklist:

1. Back up before editing `$HERMES_HOME/config.yaml`, `$HERMES_HOME/context_length_cache.yaml`, or
   Hermes source fallback files.
2. Active default profile first; do not silently mutate `profiles/*` unless the user asks for all
   profiles.
3. Source fallback files, when relevant: `hermes_cli/setup.py` `_DEFAULT_PROVIDER_MODELS["<vendor>"]`
   and `hermes_cli/models.py` `_PROVIDER_MODELS["<vendor>"]`.
4. Propagate the same ids everywhere they are declared: every served profile's
   `providers.*.models`, the sibling harness model lists (each harness has its own file, e.g.
   `~/.pi/agent/models.json`, `~/.omo/agent/models.json`, `~/.omp/agent/models.yml`), and
   `context_length_cache.yaml` — a tier retired in one place stays selectable in the others.
   Repoint auxiliary/delegation pins to a survivor **before** removing the entry.
5. Verify with `hermes config check`, targeted model tests, and a forced-static
   `curated_models_for_provider("<vendor>")` probe. Fan-out checklist and per-file edit mechanics:
   `references/provider-metadata-audit.md`.

Session detail: `cases.md#fallback-cleanup-after-a-vendor-deprecation`.
