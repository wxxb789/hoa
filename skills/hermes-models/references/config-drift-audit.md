# Config drift audit: root vs served profiles

Profiles are separate `HERMES_HOME`s: nothing inherits from root, so a setting that exists only in root is
absent on every messaging surface. Drift is silent — no error, no warning, just a profile running stock
behavior the owner believes he configured. This file is the procedure behind the SKILL.md section of the same
name; `scripts/audit-config-drift.py` ships with this skill and runs the mechanical part — call it
at the path this skill was installed to (e.g. `skills/hermes-models/scripts/audit-config-drift.py`
under the install root), not a path from another install.

## When to run

- Owner asks to review/align settings, or "are there other missed configs?".
- After adding providers, models, or a new profile.
- A profile behaves differently from root for no visible reason.
- Before blaming a feature: confirm the setting even reached that profile.

## Pass 0 — inventory the whole routing surface

Routing is decided in seven places (SKILL.md rule 16). Enumerate **all** of them into one machine-readable
inventory before judging anything: a review that reads only root `config.yaml` sees a minority of the
surface, and the defects that matter live in the parts it skipped.

```bash
# 1. root + every profile home: model, delegation, fallback_providers, model_aliases,
#    agent.reasoning_effort/overrides, auxiliary, moa.presets
for f in ~/.hermes/config.yaml ~/.hermes/profiles/*/config.yaml; do …; done
# 2. cron — root AND each profile home, with the script field and the pin
~/.hermes/cron/jobs.json   ~/.hermes/profiles/*/cron/jobs.json
# 3. harness catalogs — ask the harness, never parse its file
export PATH="$HOME/.local/share/mise/shims:$PATH"; omp models | head -40
# 4. live proof from the DB, not from `config get`
#    sessions.model, sessions.model_config.gateway_runtime.{provider,base_url,fallback_active}
#    session_model_usage per task ('' / background_review / title_generation / …)
```

Defects that only appear when the whole surface is read:

- a per-home fallback whose provider equals that home's `model.provider` (self-fallback, no outage cover);
- one home's fallback chain sitting entirely on a single gateway while another gateway is idle;
- cron agent jobs with `provider: null` inheriting a paid/hot-path default while the tier policy says they
  belong on the cheap pool;
- two jobs for the same work at the same minute in different homes (root and a profile), with different
  prompts — double compute and two contradictory deliveries;
- the same model running at different effort tiers across Hermes / opencode / omp / omo, one of them below the
  level the owner's rule requires;
- MoA/paired lanes with two members on the same gateway and one dead id.

Deliverable shape: one artifact report (findings ranked P1–P3, each with the evidence path, why it matters,
proposed fix, and gate), and in chat a numbered summary plus one multi-select for the fix pack — never the raw
inventory. Fix the reversible findings yourself (backup → `hermes config set` → YAML read-back → live probe);
leave anything that changes scheduling behaviour or a peer harness for the owner to choose.

## Pass 1 — presence and value drift (mechanical)

```bash
HERMES_HOME=${HERMES_HOME:-$HOME/.hermes}
python3 "${HERMES_SKILLS_DIR:-$HERMES_HOME/skills}/hermes-models/scripts/audit-config-drift.py" --home "$HERMES_HOME"
```

It prints per profile: **MISS** (root deviates from the built-in default, profile lacks the key), **DIFF**
(present in both, different values), **ONLY** (profile-only keys). Provider catalogs are skipped — mirror and
probe those separately.

## Pass 2 — the "unrecognized key" sweep, and why it lies

`hermes_cli.config._validate_config_key(path)` backs the CLI's "not a recognized config key" warning, but it
validates against `DEFAULT_CONFIG`, which is an incomplete schema by design — runtime-read settings may have no
seeded default. Sweeping every leaf path of every config through it returns dozens of false positives
(`agent.personalities.*`, `auxiliary.<task>.*`, `session_reset.*`, `web.*`). Use it only to spot *typos*, and
verify any hit in source (grep the key in the repo) before treating it as dead.

## Pass 3 — live probes (the only real proof)

1. Model aliases: `hermes [--profile <p>] --ignore-rules chat -m <alias> -q "Reply with exactly: OK" -Q`.
   A dead alias fails at call time with the endpoint's own error, never at config-load time.
2. Auxiliary vision: one real image call per profile, not `hermes doctor` (see SKILL.md).
3. Default model + effort: `resolve_reasoning_config(load_config(), "<model>")` must return
   `{'enabled': True, 'effort': '<level>'}`.
4. Provider identity per profile: `hermes --profile <p> config get providers.<name>` — confirm `api`,
   `transport`, `api_key` present, and that models the profile pins actually live in that provider's list.
5. Declared per-model metadata actually resolves — call
   `get_custom_provider_context_length(<id>, <provider api>)` from `hermes_cli.config_providers` and compare
   with the value on disk. `None` for an id that IS declared means the key is malformed (dot-escaped) and the
   runtime is using a catalog/default window instead.
6. Per-model reasoning effort: run `resolve_reasoning_config(load_config(), "<model>")` for every declared
   model, not just the default — a global level outside a model's own ladder is rejected by the endpoint at
   call time (see `provider-metadata-audit.md`).

## The discriminator: drift vs deliberate

| Root value vs `DEFAULT_CONFIG` | Profile state | Reading | Action |
|---|---|---|---|
| root != default | key missing in profile | root deviates, profile silently stock | mirror (real miss) |
| root != default | profile == default | same as above, explicit | mirror |
| root != default | profile != default, both differ | per-profile tuning | ask the owner |
| root == default | key missing | profile would use the same default | nothing |
| key missing in root | profile has it | profile-only override | report, usually intentional |

Ports (`platforms.api_server.extra.port`) must differ per profile — never align them.

## Applying mirrors safely

- One `hermes config set <key> <value>` per profile; root writes omit `--profile`.
- Lists (e.g. `command_allowlist`) round-trip as JSON: write with a JSON array string, then read back with
  `config get <key> --json` and compare **against the source list**, not against your intent.
- Never batch these as one inline shell compound: `$(...)` substitution plus config writes trips the approval
  guard. Put the loop in a script file under the scratch dir and run that file — the guard accepts a reviewed
  script, and the script can carry the read-back assertion (`identical_to_root=True/False`).
- A timed-out approval is a NO. Report what is done, what is pending, and the exact command you intend to run;
  wait for the owner rather than rephrasing it.
- Secrets: config values can hold placeholder keys. Mask anything matching api_key/token/secret/password in
  your own output instead of printing raw config.
- After the writes: `python3 ~/.hermes/scripts/config-snapshot.py`, then `post-update-check.py`, then a gateway
  restart when messaging surfaces must pick the change up, then a per-profile spot check.

## Pitfalls seen in practice

- **Dotted model ids lose their declared value under both naive writes.** An unescaped
  `providers.local-openai.models.grok-4.6.context_length` path splits into a phantom nested mapping
  (`grok-4: {6: {context_length: ...}}`) nothing reads; escaping the dots for the shell stores a
  dot-escaped key (`grok\-4.6:`) that `get_custom_provider_context_length(model, base_url)` **also never
  matches** — it returns `None` and the runtime silently takes the catalog value (or the 256,000 default
  when the catalog has none). Declare these entries by editing the YAML directly with plain dotted keys,
  then prove the value with the resolver helper. A live `hermes chat -m <id>` is a **false** verification:
  the call succeeds off the catalog even while the declared value is inert.
- **A profile's provider set is smaller than root's.** Pinning a profile to `custom:<provider>` that only root
  defines fails at call time. Check the profile's provider list first; pin to what it has (e.g. chat-completions
  `local-chat` + a Gemini flash) instead of importing root's pin.
- **`auto` auxiliary routing can silently pick the wrong transport.** Doctor green ≠ working. Probe with a real
  input of the modality in question.
- **A per-profile cron store is invisible from root.** Each home has its own `cron/jobs.json`; auditing only
  root reports "one job" for work that actually runs twice, and misses every unpinned job in the profiles.
- **`model`/`provider` on a `no_agent` (script) job is decorative.** Only agent jobs resolve them, so counting
  script jobs as "the background tier is on the free pool" overstates coverage — count agent jobs only.
- **Never infer a harness catalog from its config file.** `omp models` lists providers that its
  `models.yml` does not contain (ids resolve from a managed store); a file-parse audit files a false
  "provider missing" finding and sends you editing the wrong layer.
- **Enumerating `profiles/*` picks up retired homes.** Dot directories such as `.deleted` survive a profile
  retirement; filter them or the report grows phantom profiles.
- **Health checks must not grep for the word `Traceback`** in a tool's output: a report that legitimately quotes
  log text contains it and reports a false crash. Assert on the tool's own exit code and its own frames
  (`File ".../<script>.py", line N`).
- **Maintainer scripts must not shell out to bare `python`/`python3`** on a PM-toolchain install — resolve an
  interpreter that can import the dependencies, or the check reports failures that are not real.
- Config snapshots go stale the moment you touch config; regenerate before reporting a green post-check.
