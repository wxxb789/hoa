# Switching models and fallback hygiene

<!-- install-root: `$HERMES_HOME` below means the install root; it defaults to `~/.hermes` -->


### Switching the default model and proving the route

1. Back up config, then set the route in this order — writing `model.provider` **clears** the `model.base_url` / `model.api_mode` that belonged to the previous provider, so set those after the provider:
   `HERMES_HOME=${HERMES_HOME:-$HOME/.hermes}; BK="$HERMES_HOME/backups/model-switch-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$BK"; cp "$HERMES_HOME/config.yaml" "$BK/config.yaml"` (back up the home you are about to change, not the default one), then `hermes config set model.default <id>`, `model.provider <providers-key>`, `model.api_mode chat_completions` (`codex_responses` for Responses routes), `model.base_url <provider api>`, `agent.reasoning_effort <level>`. Use the exact bare `providers:` key (`opencode-go-flash`, not a made-up `opencode-go`).
2. `agent.reasoning_effort` is **global**, not per-model: changing it re-tiers every other selectable model too. Keep per-model levels in `agent.reasoning_overrides` rather than accepting that collateral change, and tell the owner which other models moved. The "not a recognized config key" warning on `config get agent.reasoning_effort` is noise — the runtime reads it.
3. Prove the route with three independent signals, never from `config get` alone:
   - one-shot: `hermes chat -q 'Reply with exactly: PROBE_OK'` must echo the token;
   - the row that run created: `SELECT model FROM sessions ORDER BY started_at DESC LIMIT 1` (read-only `state.db`) must name the new model;
   - `resolve_reasoning_config(load_config(), "<model>")` under the toolchain python with `PYTHONPATH=<repo>` must report the intended effort.
4. Regenerate `config-snapshot.py`, then restart the gateway if channels must pick it up. Profiles keep their own pins: root `model.default` governs unrouted channel traffic, so state plainly that profiles are still on the old model unless you mirror them.

Deployment recipe for ghc-proxy: `cases.md#ghc-proxy-systemd-user-service` (covers systemd unit, daily-restart timer, localhost firewall, concurrency tuning via `--upstream-queue-concurrency`, and the health-check endpoint pitfall — curl must probe `/v1/models`, NOT `/api/v1/models` which 500s as a false "service down").

With ghc-proxy in place, direct Copilot source patches to Hermes (enterprise token exchange, IDE auth headers, etc.) are no longer needed. Keep Hermes on clean upstream `main` and let ghc-proxy handle all Copilot API translation. The old `hermes-copilot-enterprise-amend-workflow` skill was absorbed here — its test/amend patterns are still valid for any Hermes source work, but Copilot-specific patches should not be reintroduced.

### Copilot supported-model fallback hygiene

When a provider deprecates model slugs, remove them from both the active runtime config and the static fallback catalogs — a retired id left as a cheap/fallback entry does not fail loudly, it advertises a route that answers 404 only when it is finally used. Which ids are retired is per-account and per-date: keep that list in the install's own policy overlay, re-probe `/v1/models` before repeating it as fact, and verify the surviving set against the endpoint rather than against a note.

Checklist:
1. Back up before editing `$HERMES_HOME/config.yaml`, `$HERMES_HOME/context_length_cache.yaml`, or Hermes source fallback files.
2. Active default profile first; do not silently mutate `$HERMES_HOME/profiles/*` unless the user asks for all profiles.
3. Source fallback files, when relevant: `hermes_cli/setup.py` `_DEFAULT_PROVIDER_MODELS["copilot"]` and `hermes_cli/models.py` `_PROVIDER_MODELS["copilot"]`.
4. Propagate the same ids everywhere they are declared: every served profile's `providers.*.models`, the sibling harness model lists (`~/.pi/agent/models.json`, `~/.omo/agent/models.json`, `~/.omp/agent/models.yml`), and `context_length_cache.yaml` — a tier retired in one place stays selectable in the others. Repoint auxiliary/delegation pins to a survivor **before** removing the entry.
5. Verify with `hermes config check`, targeted model tests, and a forced-static `curated_models_for_provider("copilot")` probe. Fan-out checklist and per-file edit mechanics: `references/provider-metadata-audit.md`.

Session detail: `cases.md#copilot-fallback-cleanup`.
