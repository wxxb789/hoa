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
4. Regenerate `config-snapshot.py`. Check live channel traffic before considering a restart; ask for explicit approval and avoid interrupting an active writer. Profiles keep their own pins: root `model.default` governs unrouted channel traffic, so state plainly that profiles are still on the old model unless you mirror them.

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

## Proof

**The scope is the operator's fleet, not a fixed roster.** A "switch the default model" request spans the
root `model` entry plus every home and binding that pins a model: enumerate `$HERMES_HOME/profiles/*/config.yaml`
(`hermes config` paths), the harness settings that carry ids, and the roster repo's per-bot bindings **before**
deciding the scope, then state what you enumerated. A home you could not enumerate is not covered — say so
rather than assuming it is. Bindings and a roster `tiers:` block are prose-level truth: the materializer only
validates tier *names*, so a tier left naming the old model makes that repo lie about the fleet after a cutover.

```bash
hermes chat -q 'Reply with exactly: PROBE_OK'                    # 1. live answer
hermes -p <profile> chat -q 'Reply with exactly: PROBE_OK' \
  -t clarify -Q --ignore-rules --max-turns 1                     # 1b. same, inside one home
uv run --no-project python - <<'PY'                              # 2. the session row
import glob, os, sqlite3
root = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))   # quoted heredoc: bash does not expand
for home in [root] + sorted(glob.glob(root + "/profiles/*")):
    c=sqlite3.connect(f"file:{home}/state.db?mode=ro",uri=True)
    print(home, c.execute("select model from sessions order by started_at desc limit 2").fetchall())
PY
python3 - <<'PY'                                                    # 3. effort resolution
import os, sys
root = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
sys.path.insert(0, root + "/hermes-agent")
from hermes_constants import resolve_reasoning_config
from hermes_cli.config import load_config
print(resolve_reasoning_config(load_config(), "<model>"))
PY
# if the install ships a fact-snapshot hook (look under $HERMES_HOME/scripts), run it here;
# with none, record this check as unavailable rather than implying the sheet matches
```

Read the session rows as a **before/after pair**: the newest row must show the new id *and* the row under it
must still show the old one — one new row alone cannot distinguish a real switch from a route that was already
there. Each home has its own `state.db` (`$HERMES_HOME/profiles/<p>/state.db`); root's rows say nothing about a
profile. The `sessions` table has **no `provider` column** — selecting it raises `no such column: provider`, so
prove the provider from the config/preset and let `model` carry the runtime evidence. Free-pool probes answer in
10–40 s each; run the per-home loop as one background command with a per-home `timeout`, not one foreground
call per profile.

Delegation: spawn one real child and read `$HERMES_HOME/cache/delegation/live/<id>/task-0.log`.
Vision: one real `vision_analyze` call per profile.
