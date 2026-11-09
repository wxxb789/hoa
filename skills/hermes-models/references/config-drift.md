# Config drift, reasoning effort, auxiliary vision

## Config drift audit across root + served profiles

Profiles are separate `HERMES_HOME`s, so every setting the owner relies on must exist in root **and**
in each served profile. Run this audit when the owner asks to review settings, after adding
providers/models, or when a profile behaves differently. Runnable comparison:
`scripts/audit-config-drift.py`; full procedure, probes and pitfalls:
`references/config-drift-audit.md`.

Report findings as a **lettered tier menu** — zero-risk cleanup / small behavior fix / structural
change — one line of evidence per item plus the exact command. Apply only the tiers the owner names
(owners pick subsets across turns: "A", then "A2", then "agree with M2"), and treat a named item as
its own change with its own backup and read-back. Never bundle an unnamed tier into an approved one,
and never let a menu item go out without the evidence that justifies it.

1. Classify every root-only key before mirroring: **value == `DEFAULT_CONFIG` default** means the
   profile simply never overrode it (drift, safe to mirror); **value != default** means root
   deliberately deviates and the profile silently falls back to stock — that is the real miss. Keys
   present in both files with *different* values are usually per-profile tuning: ask, never flatten
   silently.
2. `hermes config get <key>`'s "not a recognized config key" warning is not proof a key is inert:
   runtime-read keys can be absent from the defaults registry and still work
   (`agent.reasoning_effort` warns while `hermes_constants.resolve_reasoning_config` reads it).
   Confirm in source before calling anything dead.
3. Mirror per key with `hermes config set` on every profile, then **read back** (`config get --json`
   for lists) and compare against root — a successful write is not proof of the stored value. For a
   list-valued key, feed the JSON straight back:
   `hermes config set <key> "$(hermes config get <key> --json)"`.
4. Run multi-step mirrors, and every read-only multi-line probe, from a **script file** (write it
   under the scratch dir, then `python3 <path>`) rather than an inline executable body — command
   substitution, a heredoc, or `python3 -c` / `-e`. Some approval scanners refuse nested executable
   bodies and report it as a timeout with nothing executed. Foreground wait/poll commands
   (`sleep N && …`, `for …; do …; sleep …; done`) hit the same gate in unattended sessions and read
   as a timeout with nothing executed — start long work as a background job with completion
   notification and wait on the process handle instead of sleeping in a foreground call.
5. Model ids contain dots, and **both** naive writes lose the value: an unescaped path splits into a
   phantom nested mapping (`<vendor>-<major>: {<minor>: {...}}`), while
   `hermes config set 'providers.<p>.models.<vendor>\-<major>\.<minor>.context_length'` stores a
   dot-escaped key that the context-length resolver **silently ignores**
   (`get_custom_provider_context_length` returns `None`; the runtime then quietly falls back to the
   catalog / 256k default). Declare dotted model ids by editing the YAML directly with plain dotted
   keys (`<vendor>-<major>.<minor>:`) and prove it with the resolver helper — a live `-m <id>` call
   resolves from the catalog and produces false greens.
6. Probe every `model_aliases` entry in root and in each profile with a real one-shot call. Dead
   aliases (model the endpoint does not serve → `400`) and aliases referencing providers a profile
   does not define are common; remove or repoint them, and keep the alias map empty unless something
   actually uses it.
7. Legitimately per-profile, never "align": `platforms.api_server.extra.port` (ports must differ),
   platform identities, and each profile's own provider catalog.
8. After any config change, regenerate the install's config snapshot if it keeps one, or the
   post-update checker reports the snapshot stale forever.

### Reasoning effort: audit every layer, not just the file

- `agent.reasoning_effort` is the main-loop knob — set it in root **and every profile**. Per-model
  `agent.reasoning_overrides` outranks it.
- `delegation.reasoning_effort: ''` is the schema default and means subagents **inherit** the parent
  level; do not "fix" it.
- Cron jobs carry `model: null` / `provider: null` and no effort field — agent-run jobs use their
  profile's default.
- Auxiliary task blocks support their own `reasoning_effort`; leaving them unset is correct for
  mechanical tasks (compression, session search, titles).
- Verify with the resolver, not the file: `resolve_reasoning_config(load_config(), "<model>")`.

### Auxiliary vision: pin it per profile — `auto` is a trap

`hermes doctor` reporting `✓ vision` proves routing resolved, **not** that the call works. With
`auto` the vision auto-detect can pick a catalog vision model and send it over the endpoint's
default transport (observed: a chat-only vision model posted to `/v1/responses` → `400 does not
support the responses endpoint`, while doctor stayed green and the tool surfaced "the current model
does not support this visual request"). Pin `auxiliary.vision.provider` + `model` in root **and
every profile** to a route that profile actually defines — a profile's provider set may lack the
provider root's pin uses — then verify with one real image call per profile.

**`auto` is not "pick something sensible" — it falls through to the SESSION model.** For text-only
auxiliary tasks that usually works, so the breakage hides. It fails loudly only for modality-specific
tasks (vision, and anything taking an image/audio/video block): the session model has no such
capability, so the upstream answers `400 The selected model could not be resolved` (OpenAI-style) or
`400 the requested model is not supported`.

Diagnosis when a modality tool errors out:

1. `hermes config get auxiliary.<task>.provider` — if it prints `auto`, that is the prime suspect.
   `hermes doctor` prints a decisive line: `✓ auxiliary task routing resolves: … vision→custom@localhost`.
   If the task is missing from that list, it has no backend.
2. Probe which models actually accept the modality, per transport — do not assume from the model
   name. Send a tiny real payload with the modality block to the provider endpoint
   (`/v1/responses` with `input_image`, `/v1/messages` with an `image` source block,
   `/v1/chat/completions` with `image_url`). Cheap models frequently beat expensive ones here, and a
   model listed in the config can still be rejected as an unknown id.
3. Pin the winner, then re-run the tool on a real asset — a successful config write proves nothing
   about the round-trip.

A gateway-free check of the class: `hermes doctor` flags sibling broken capabilities
(`⚠ image_gen`) in the same report. Some are unfixable by config — if the configured provider exposes
no such endpoint at all (e.g. a Responses-only proxy returns `404 Unknown endpoint` for
`/v1/images/generations`), record it as unavailable in the install's known-limitations register
instead of repeatedly "fixing" it.
