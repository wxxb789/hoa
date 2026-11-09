# Config drift audit: root vs served profiles

Profiles are separate `HERMES_HOME`s: nothing inherits from root, so a setting that exists only in
root is absent on every messaging surface. Drift is silent — no error, no warning, just a profile
running stock behavior the owner believes they configured. This file is the procedure behind the
SKILL.md section of the same name; `scripts/audit-config-drift.py` runs the mechanical part.

## When to run

- Owner asks to review/align settings, or "are there other missed configs?".
- After adding providers, models, or a new profile.
- A profile behaves differently from root for no visible reason.
- Before blaming a feature: confirm the setting even reached that profile.

## Pass 1 — presence and value drift (mechanical)

```bash
python3 scripts/audit-config-drift.py --hermes-home "$HERMES_HOME"
```

It prints per profile: **MISS** (root deviates from the built-in default, profile lacks the key),
**DIFF** (present in both, different values), **ONLY** (profile-only keys). Provider catalogs are
skipped — mirror and probe those separately.

## Pass 2 — the "unrecognized key" sweep, and why it lies

`hermes_cli.config._validate_config_key(path)` backs the CLI's "not a recognized config key"
warning, but it validates against `DEFAULT_CONFIG`, which is an incomplete schema by design —
runtime-read settings may have no seeded default. Sweeping every leaf path of every config through it
returns dozens of false positives (`agent.personalities.*`, `auxiliary.<task>.*`, `session_reset.*`,
`web.*`). Use it only to spot *typos*, and verify any hit in source (grep the key in the repo) before
treating it as dead.

## Pass 3 — live probes (the only real proof)

1. Model aliases: `hermes [--profile <p>] --ignore-rules chat -m <alias> -q "Reply with exactly: OK" -Q`.
   A dead alias fails at call time with the endpoint's own error, never at config-load time.
2. Auxiliary vision: one real image call per profile, not `hermes doctor` (see SKILL.md).
3. Default model + effort: `resolve_reasoning_config(load_config(), "<model>")` must return
   `{'enabled': True, 'effort': '<level>'}`.
4. Provider identity per profile: `hermes --profile <p> config get providers.<name>` — confirm `api`,
   `transport`, `api_key` present, and that models the profile pins actually live in that provider's
   list.
5. Declared per-model metadata actually resolves — call
   `get_custom_provider_context_length(<id>, <provider api>)` from `hermes_cli.config_providers` and
   compare with the value on disk. `None` for an id that IS declared means the key is malformed
   (dot-escaped) and the runtime is using a catalog/default window instead.
6. Per-model reasoning effort: run `resolve_reasoning_config(load_config(), "<model>")` for every
   declared model, not just the default — a global level outside a model's own ladder is rejected by
   the endpoint at call time (see `provider-metadata-audit.md`).

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
- Lists (e.g. `command_allowlist`) round-trip as JSON: write with a JSON array string, then read back
  with `config get <key> --json` and compare **against the source list**, not against your intent.
- Never batch these as one inline shell compound: `$(...)` substitution plus config writes trips the
  approval guard. Put the loop in a script file under the scratch dir and run that file — the guard
  accepts a reviewed script, and the script can carry the read-back assertion
  (`identical_to_root=True/False`).
- A timed-out approval is a NO. Report what is done, what is pending, and the exact command you
  intend to run; wait for the owner rather than rephrasing it.
- Secrets: config values can hold placeholder keys. Mask anything matching
  `api_key`/`token`/`secret`/`password` in your own output instead of printing raw config.
- After the writes: regenerate the install's config snapshot, run its post-update check, then a
  gateway restart when messaging surfaces must pick the change up, then a per-profile spot check.

## Pitfalls seen in practice

- **Dotted model ids lose their declared value under both naive writes.** An unescaped
  `providers.<p>.models.<vendor>-<major>.<minor>.context_length` path splits into a phantom nested
  mapping (`<vendor>-<major>: {<minor>: {context_length: ...}}`) nothing reads; escaping the dots for
  the shell stores a dot-escaped key (`<vendor>\-<major>\.<minor>:`) that
  `get_custom_provider_context_length(model, base_url)` **also never matches** — it returns `None` and
  the runtime silently takes the catalog value (or the 256,000 default when the catalog has none).
  Declare these entries by editing the YAML directly with plain dotted keys, then prove the value
  with the resolver helper. A live `hermes chat -m <id>` is a **false** verification: the call
  succeeds off the catalog even while the declared value is inert.
- **A profile's provider set is smaller than root's.** Pinning a profile to `custom:<provider>` that
  only root defines fails at call time. Check the profile's provider list first; pin to what it has
  (e.g. its chat provider + a chat-only model) instead of importing root's pin.
- **`auto` auxiliary routing can silently pick the wrong transport.** Doctor green ≠ working. Probe
  with a real input of the modality in question.
- **Health checks must not grep for the word `Traceback`** in a tool's output: a report that
  legitimately quotes log text contains it and reports a false crash. Assert on the tool's own exit
  code and its own frames (`File ".../<script>.py", line N`).
- **Maintainer scripts must not shell out to bare `python`/`python3`** on a package-manager-toolchain
  install — resolve an interpreter that can import the dependencies, or the check reports failures
  that are not real.
- Config snapshots go stale the moment you touch config; regenerate before reporting a green
  post-check.
