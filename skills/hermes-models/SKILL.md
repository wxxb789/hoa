---
name: hermes-models
description: >-
  Configure Hermes model providers, transports and routing: provider entries, default-route
  switching, reasoning effort, delegation pins, per-profile copies, and proving a route with live
  signals. Use when a model 404s or rejects an endpoint, a profile ignores its key, config drifts
  between root and profiles, vision or image generation errors, or a relay's effort/cost looks
  wrong. Not for another harness's own model configuration.
metadata:
  version: "0.1.20"
  areas: "software-development"
  targets: "hermes"
---

# Hermes Models & Providers

Routing is configuration plus proof. `config get` proves neither the route nor the metadata.

## When to Use

| You hear / see | Load |
|---|---|
| change the default model / add a provider / change an endpoint | rules below + `references/model-switching.md` |
| a model 404s, `does not support the responses endpoint` | `references/custom-providers.md` |
| "run the subagent on a cheaper model" | `references/delegation-routing.md` |
| profile models/keys do not apply, only root works | `references/delegation-routing.md` → per-profile provider |
| config drifts between root and profiles | `references/config-drift.md` |
| vision / image_gen errors, `auto` routing | `references/config-drift.md` |
| declare context_length / metadata for a model | `references/provider-metadata-audit.md` |
| a relay's effort/cost/streaming behavior looks wrong | `references/model-endpoint-matrix.md` |

**Not for**: another agent harness's endpoints (pi/omp/opencode/dsh); those follow that harness's own
model configuration.

## Rules

1. **Transport is per model, not per endpoint.** One proxy serves `/v1/responses` for some ids and
   `/v1/chat/completions` for others; probe both before concluding a capability is missing.
2. **Provider entries** live under top-level `providers:`; `model.provider` normally names the bare
   key (`<provider-key>`). A `custom:<name>` prefix is also accepted for custom-gateway entries, so a
   drift check must strip a leading `custom:` before comparing against the `providers:` keys — a raw
   string compare reports every valid custom route as undefined. Declare `context_length` per model.
3. **Switching the default route:** writing `model.provider` **clears** `model.base_url` /
   `model.api_mode`. Order: backup → `model.default` → `model.provider` → `model.api_mode` →
   `model.base_url` → `agent.reasoning_effort`. Takes effect on `/new` or next session start.
4. **Prove the route with three signals**, never `config get`: one-shot `hermes chat -q 'Reply with
   exactly: PROBE_OK'`; the `sessions` row it created (read-only `state.db`); and
   `resolve_reasoning_config(load_config(), "<model>")`.
5. **`agent.reasoning_effort` is global**, not per model — change it and every selectable model
   re-tiers. Put per-model levels in `agent.reasoning_overrides` and say which models moved. The
   "not a recognized config key" warning is noise; the runtime reads it.
6. **Delegation pin** is global to the profile; `delegate_task` has no per-task model parameter and
   its schema is built at session start (never flip mid-conversation). Per-task granularity = Kanban
   card override, cron pin, or independent spawn. Verify with a real child spawn + its live transcript.
7. **Profiles carry their own `providers:` and `.env`.** Add the block, delete any inherited inline
   `model.api_key` (it outranks `key_env`), copy the key into that profile's `.env`, then verify with a
   live one-shot under `HERMES_HOME=<profile>`.
8. **Dotted model ids** cannot go through a dotted path —
   `providers.<n>.models.<vendor>-<major>.<minor>.<patch>.context_length` builds a phantom nested
   mapping. Set the whole map as one JSON value instead
   (`hermes config set providers.<n>.models '{"<dotted-model-id>":{"context_length":<n>}}'`), or edit
   YAML with plain dotted keys. Back up first, then read the file back with a YAML parse — a masked
   `config get` cannot prove the map shape, and a successful chat does not prove the override was read.
9. **Reasoning effort is a hint, not a guarantee**, and the effort→cost ladder is per relay and
   non-monotonic. Judge from `usage.reasoning_tokens`; size `max_tokens` per model because reasoning is
   charged against it on chat-completions transports.
10. **`auxiliary.vision: auto` is a trap** — doctor green only proves routing resolved. Pin
    provider+model in root **and** every profile, then run one real image call per profile.
11. **Config drift is the default failure mode.** Classify root-only keys as "never overrode" vs
    "deliberately different" before mirroring; read back after every write; regenerate the install's
    config snapshot if it keeps one.
12. **Text-only one-shot generation is `-t clarify`, not `-t ""`.** An empty `-t` value leaves the
    FULL toolset enabled — the model can write files and emits tool/diff previews into stdout,
    corrupting programmatic parsing; `-t none` is rejected as an unknown toolset name. Inert form:
    `hermes chat --query-file <f> -m <model> --provider <p> -t clarify -Q --ignore-rules --max-turns 1`,
    then strip the trailing `session_id:` line from stdout. Prove inertness once per model by asking
    it to create a file and checking it cannot.
13. **Aliases and fallbacks are separate records from the provider entry.** `model_aliases.<name>` is
    a DirectAlias (`model`, `provider: custom`, `base_url`, `key_env`) resolved *before* the catalog,
    so it needs its own copy of the URL and key variable. `fallback_providers` entries are
    `{provider: <provider key>, model: <id>}` resolved through the provider registry, and they are
    per-home — set them in root **and** every profile. Prove both with one probe: point a throwaway
    alias at a nonexistent model id; the error names that id (alias routed) and the run continues on
    the fallback (`Model fallback: … via <provider>`), which proves the chain end to end. Delete the
    probe alias afterwards.
14. **A single bounded task on a non-default model: harness CLI first, not `hermes chat`.** A harness
    CLI invoked with `--no-tools --no-skills --model <provider>/<id>` carries the prompt and nothing
    else — no tool schemas, no session context — so instruction following on long writing/analysis
    prompts is measurably tighter. One form that supports this:
    `pi -p --no-tools --no-skills --model <provider>/<id> --thinking high @prompt.md`. Resolve the
    binary through the tool manager that installed it, not `command -v`: tool-manager shim directories
    are often absent from a non-interactive shell's PATH, so an empty `command -v` means "not on
    PATH", not "not installed". Export the shims directory or call the absolute path.
15. **Long generation runs in the background; wait on the event, never on a foreground `sleep`.**
    `terminal(background=true, notify_on_complete=true)` then end the turn, or block once with
    `process_manage wait` (600 s) — do not poll a file size with `sleep 60..240` calls: each one
    blocks the same wall-clock, blocks every other task, and any sleep over the 180 s foreground
    timeout dies empty-handed. `sleep` is only for a fixed delay with no event to wait on, and then
    ≤30 s. If a long generation comes back truncated, re-run with `--thinking medium` plus an explicit
    stop condition ("write through to the last section") rather than the same call again.

## Proof

```bash
hermes chat -q 'Reply with exactly: PROBE_OK'                    # 1. live answer
python3 - <<'PY'                                                 # 2. the session row
import sqlite3,os
c=sqlite3.connect(f"file:{os.path.expanduser('~/.hermes/state.db')}?mode=ro",uri=True)
print(c.execute("select model from sessions order by started_at desc limit 3").fetchall())
PY
HERMES_HOME=~/.hermes python3 - <<'PY'                            # 3. effort resolution
import os,sys; sys.path.insert(0,os.path.expanduser('~/.hermes/hermes-agent'))
from hermes_constants import resolve_reasoning_config
from hermes_cli.config import load_config
print(resolve_reasoning_config(load_config(), "<model>"))
PY
```

Delegation: spawn one real child and read `HERMES_HOME/cache/delegation/live/<id>/task-0.log`.
Vision: one real `vision_analyze` call per profile.

## References

- `references/custom-providers.md` — provider YAML shape, transport table, per-model sizing, relay
  header quirks, endpoint rotation, operator policy as a configuration choice.
- `references/model-switching.md` — switching order, three-signal proof, ghc-proxy deployment,
  fallback hygiene.
- `references/delegation-routing.md` — precedence rules, per-profile provider migration checklist.
- `references/config-drift.md` — drift audit, lettered tier menu, reasoning-effort layers, auxiliary
  vision.
- `references/provider-metadata-audit.md`, `references/model-endpoint-matrix.md`,
  `references/config-drift-audit.md` — audit detail.
- `references/cases.md` — historical cases: fallback cleanup, ghc-proxy deployment.
- `scripts/audit-provider-metadata.py`, `scripts/audit-config-drift.py`,
  `scripts/probe-provider-endpoint.sh` — runnable probes; `templates/ghc-proxy.service` — unit
  template.
