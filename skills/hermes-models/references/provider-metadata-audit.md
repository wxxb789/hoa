# Provider / model metadata audit: declared vs authoritative

<!-- install-root: `$HERMES_HOME` below means the install root; it defaults to `~/.hermes` -->

When to run: the owner asks "are all the models' metadata configured correctly?", "are these providers
redundant?", or a session under-uses context, 400s on `reasoning_effort`, or compacts only after the
endpoint refused the request. Companion to `config-drift-audit.md` (which covers root-vs-profile key
drift); this file covers the **model catalog** layer.

Runnable probe: `scripts/audit-provider-metadata.py`.

## Sources of truth, in order

1. **The endpoint's own catalog.** For a local proxy, `GET <api>/dashboard/api/models` returns per model
   `upstream.capabilities.limits` (`max_context_window_tokens`, `max_output_tokens`, `max_prompt_tokens`,
   `vision.{max_prompt_images,max_prompt_image_size,supported_media_types}`),
   `upstream.capabilities.supports` (`tool_calls`, `parallel_tool_calls`, `vision`, `streaming`,
   `structured_outputs`, and the `reasoning_effort` ladder), plus `effective` routing flags
   (`defaultMessagesStrategy`, `responsesAvailable`, `nativeStructuredOutput`). `GET /v1/models` returns
   **ids only** — never hand-maintain numbers a catalog can hand you.
2. **Declared config**: every `providers.<name>.models.<id>` entry, in root *and* each served profile.
3. **Effective runtime value**: `agent.model_metadata.get_model_context_length(...)` for the full chain,
   and `hermes_cli.config_providers.get_custom_provider_context_length(model, base_url, config=...)` for
   the config-override step alone. Use the second as the "did my declared value land?" probe: `None` for a
   model that IS declared means the key is malformed (see the dotted-key pitfall).
4. **Real usage**: `$HERMES_HOME/state.db` → `session_model_usage` (`model`, `billing_provider`,
   `billing_base_url`, `billing_mode`, `task`, `api_call_count`, token sums, `first_seen`, `last_seen`).
   `task` empty = main loop; `vision` / `compression` / `session_search` / `title_generation` /
   `background_review` = auxiliary paths. Open read-only (`sqlite3.connect("file:...?mode=ro", uri=True)`).

## Measured on this host (2026-11-13) — which interface actually answers

| endpoint | what it returns |
|---|---|
| `:4141/v1/models` (GHC proxy: `local-openai`, `local-chat`) | 39 ids, fields **only** `id/object/type/created/created_at/owned_by/display_name` — **no limits** |
| `:4141/v1/models/<id>`, `:4141/model/info` | 404 `Unknown endpoint` — no per-model detail route |
| `:4141/dashboard/api/models` | **the catalog**: `models[].upstream.capabilities.limits.{max_context_window_tokens,max_prompt_tokens,max_output_tokens,vision.*}`, `upstream.capabilities.supports.{reasoning_effort,tool_calls,…}`, `upstream.endpoints`, `pickerEnabled` |
| tencent-litellm `/v1/models` | ids only |
| tencent-litellm `/model/info` | `input/output_cost_per_token`, `mode` — `max_input_tokens` / `max_output_tokens` come back **null**, so this pool has **no authoritative window**; a number in config for those ids is unsourced |
| opencode-go-flash `/v1/models` | 403 (no key in this shell) |

Consequences for a "fix the metadata" pass: read limits from `/dashboard/api/models`, never transcribe a
number from memory or from a sibling config; when the interface answers `null` (tencent pool) write
"no interface value" in the report instead of a plausible number, and pin nothing rather than guessing.

What the runtime does with an id that has **no** declared `context_length`: it falls through to
`agent/model_metadata.DEFAULT_CONTEXT_LENGTHS` (substring match on the model id), and only then to
`DEFAULT_FALLBACK_CONTEXT` (256,000). Measured: `gemini-4-carbon` resolves **1,048,576** from the table
while the catalog says **1,000,000** (prompt cap 936,000) — i.e. an undeclared id inherits a *wrong* table
value, not the 256K fallback. So "undeclared" is not automatically safe, and a table hit outranks `null`.

Verified catalog values, `:4141`, same date (window / prompt cap / max output):
`gemini-4-carbon` 1,000,000 / 936,000 / 64,000 · `gemini-4-argon` 1,048,576 / 983,040 / 65,536 ·
`gemini-3.8-flash` 1,048,576 / 983,040 / 65,536 · `gpt-6.1-sol` 1,050,000 / 922,000 / 128,000 ·
`gpt-6-luna` 1,000,000 / 872,000 / 128,000 · `grok-4.6` 500,000 / 372,000 / 128,000.
`gemini-3.7-flash` is declared in two homes but **absent from the catalog** — servable-but-unadvertised or
retired; probe with a real call before trusting its declared 1,000,000.

## What Hermes can and cannot hold per model

| metadata | config surface |
|---|---|
| context window | `providers.<p>.models.<id>.context_length`, or `model_overrides.<provider>.<model>.context_window` |
| tools / vision / reasoning | `model_overrides.<provider>.<model>.{supports_tools,supports_vision,supports_reasoning}` (`_default` = fill-gap only, never displaces catalog data) |
| per-model effort | `agent.reasoning_overrides.<model>` — outranks the global level |
| capability booleans | any bool under the model entry, read by `get_custom_provider_model_capability` (`prompt_caching`, `answer_in_reasoning`) |
| max output tokens | **none** — transport defaults + auto-boost + error-driven adaptation |
| max prompt tokens | **none** — fold the usable input budget into `context_length` |
| structured output | **none** per model — endpoint-dependent; a model whose catalog says `structured_outputs: false` fails a `json_schema` request |

## Procedure

1. Gather: raw YAML for root + profiles, the endpoint catalog, resolver values, and the usage aggregate.
2. Compare declared `context_length` against the catalog window; flag mismatches.
3. **Effort-ladder check**: for every declared model, run
   `resolve_reasoning_config(load_config(), "<model>")` and compare the level against the catalog's
   `supports.reasoning_effort`. A global level outside a model's ladder is a hard 400 at call time (the
   error names the model). Fix with `agent.reasoning_overrides` — and remember overrides are keyed by model
   id, so dotted ids hit the same write trap.
4. **Compaction-vs-prompt-cap check**: `compression.threshold` × declared `context_length` must stay below
   the model's `max_prompt_tokens`. If it does not, the session only compacts *after* the endpoint has
   already refused the prompt; declare `context_length` at the prompt cap for those models — the window
   above it is unusable input anyway.
5. **Redundancy pass**: duplicate model ids across entries; a `model_aliases` entry duplicating a
   `providers` entry for the same route (two names, one route); entries whose models all fail on their own
   transport; declared-but-never-used ids (from usage); served-but-undeclared ids.
6. **Cross-harness pass**: enumerate the same upstream services in the sibling harness configs
   (opencode / codex / pi / omp / omo / dsh). Expect value drift, not just duplication.
7. **Verify**: metadata changes are proven by the resolver helper, *not* by a chat call; routing changes are
   proven by a real one-shot call (`hermes --ignore-rules chat -m <id> --provider <p> -q "Reply with exactly: OK" -Q`).

## Delete vs declare — the trap nobody expects

Removing a model entry does **not** remove the ability to call it: custom routes resolve by `base_url`, so
`-m <retired-id>` still works while its context silently drops to the undeclared fallback (observed:
272,000 for models whose real window is 1,050,000; `DEFAULT_FALLBACK_CONTEXT` is 256,000 when the catalog
has no answer). Before deleting an entry, grep scripts, cron definitions and skills for the id **and** for
the auxiliary/delegation keys that pin it — an aux pin keeps working but loses its metadata, so repoint it
first. For a catalog this generous, declaring an entry is usually cheaper than being wrong later.

## Retiring a model tier (fan-out checklist)

A deliberate retirement is never one file, and it is never only Hermes. Run the parts in this order:

1. **Repoint pins before removing metadata.** Aux/delegation pins keep working after the entry is gone
   (routes resolve by `base_url`) but silently drop to the undeclared fallback window. Enumerate the pins —
   `auxiliary.<task>.{provider,model}`, `delegation.{provider,model}`, `smart_model_routing.cheap_model`,
   cron `--model` — and move each to a survivor first.
2. **Enumerate the declarations instead of recalling them**: root + every served profile's
   `providers.<p>.models`, the sibling harness model lists (`~/.pi/agent/models.json`,
   `~/.omo/agent/models.json`, `~/.omp/agent/models.yml`, opencode/codex/dsh), the source fallback
   catalogs, and `context_length_cache.yaml`. Grep the retire list across all of them in one pass.
3. **Edit per file type.** JSON model lists: parse → filter by `id` → re-dump (`indent=2`) → re-parse to
   prove it. YAML lists that carry comments (omp): remove the `- id:` line plus its deeper-indented
   continuation lines and write the rest back verbatim — a `yaml.safe_dump` round-trip strips the file's
   comments and turns a 2-line change into a whole-file rewrite. Validate every edited file by loading it
   before reporting success.
4. **Hermes provider blocks are YAML-with-comments too**: remove model entries by direct text edit (or
   `hermes config unset` for plain ids); dotted ids must be edited as plain dotted keys (see the pitfall
   below), never through `hermes config set`.
5. **Harness configs are partially generated.** On this install the pi/omo/omp model lists reach the
   versioned repo as chezmoi `modify_*` scripts, so editing live is correct — confirm the next sync commits
   a diff for those files rather than assuming the change is versioned.
6. **Verify with the resolver, then a live call for the survivors**: retired ids must be absent from every
   file (grep) and every file must still parse; surviving models must still resolve their declared
   `context_length`.
7. State the accepted trade-off: a retired id keeps answering on an ad-hoc `-m` call but resolves to the
   undeclared fallback window. That is fine when the owner wants the entry gone — say it out loud instead of
   letting a future session read the smaller window as a bug.

## Cross-harness credential drift (prove it, never print it)

The same variable name can hold **different values in different harness stores**, each valid on exactly one
host. Prove the pairing with a matrix: for every (store, host) pair POST a 16-token probe and print only the
HTTP status — 200 = live pair, 401 = wrong pairing. Never print, echo or copy a value; a status code is all
the evidence needed. Two traps this catches: one endpoint can have two hosts with different route maps (a
path that 404s on one and answers on the other), and a **shell-exported** variable overrides a harness's own
store, which is how an otherwise-working harness pair starts 401ing.

## When the owner's claim and the catalog disagree

An owner instruction often carries a factual claim ("that tier is retired", "every model except X
has a 1M window"). Check the claim against the catalog **before** acting, then do what was asked and
report the delta with numbers — do not silently argue, and do not silently adopt the wrong number:

- A **policy** removal (owner wants the entry gone) and an **upstream deprecation** (the endpoint no
  longer serves it) have different consequences: a removed-but-still-served id keeps answering while
  losing its declared metadata, so name the trade-off and keep a correct `context_length_cache.yaml`
  entry so an ad-hoc call is not blind.
- A "1M" belief is only true per family: quote the real values (`1,000,000`, `1,048,576`,
  `1,050,000`) and list the exceptions rather than flattening everything to 1M.

## Pitfalls

- **Dot-escaped model keys are silently ignored** — see `config-drift-audit.md`; declare dotted ids by direct
  YAML edit and prove them with the resolver helper.
- **A live `-m` call is not proof of metadata.** It succeeds off the catalog while the declared value is inert.
- **A model can be servable but unadvertised.** It answers 200 while `/v1/models` and the dashboard catalog
  omit it — live-discovery pickers then never offer it (select it explicitly, or pin
  `providers.<p>.discover_models: false` to use the declared list verbatim).
- **`supports.reasoning_effort` is a contract, not a suggestion**: verify per model, and quote the endpoint's
  own error text when reporting a mismatch.
- **Vision caps differ per model** (image count, accepted media types). Absent a per-model switch, treat
  multi-image or exotic-media requests as model-specific and probe before promising them.
