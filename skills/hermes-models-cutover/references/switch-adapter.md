# Fleet switch adapter

**A provider outage is a fleet cutover, not a default change.** Every home and every harness that
names the dead provider moves in one pass, and the provider entry itself stays in `providers:` so
restoration is a single key flip. Two places make a half-cutover look finished: a generated home whose
route lives in its generator's repo (editing the generated config is reverted on the next apply), and
per-harness effort metadata (`thinkingLevelMap` / `#variant`) that lacks the new id's top tier, which
silently downgrades every "max" pin. Inventory → migrate → verify against every surface:
[fleet cutover](fleet-cutover.md).

**A fleet cutover is one command, not 16 edits.** An adapter — resolved as
`HERMES_MODELS_SWITCH_CMD` (env → `$XDG_CONFIG_HOME/hermes-models/config.yaml` → a `model-switch.py`
the install ships) — applies a preset from `HERMES_MODELS_PRESETS` across Hermes root + every enumerated profile,
`omp`, `omo` (settings + `thinkingLevelMap`), `opencode` (`model`, `agents.build.model`, effort
variants), the OMP wrapper script defaults and the roster repo's bot bindings; `<preset> --check`
reports drift, `--dry-run` diffs, `--rollback` restores the newest backup, `--restart-gateway`
schedules the post-cutover restart (whether a hosted bot needs it is per-home — read that home's own
`state.db` rows after real traffic instead of assuming, and treat restart as gated).
Edits are line/block
level so comments, key order and byte layout survive a round trip. Extend the preset file for a new
fleet state instead of hand-editing or writing another script; the binding files stay uncommitted
on purpose (repo sync owns commit+push). An install without such an adapter does the same cutover by
hand — the contract above is the requirement, the command is configuration. Document the adapter's
own usage next to it, not in a personal notes tree.
Two presets-file landmines abort every subcommand, `list` included: an `overrides` entry naming a
profile that no longer exists (`target file missing` kills the whole run), and a preset still
describing the *previous* fleet state, which silently reports "drift" and would apply the old route.
So the order is always `list`/`--check` → fix stale overrides + bring `free` up to the intended
state → `--dry-run` (read the 6 line-level diffs) → apply. A wrong-state preset is worse than no
preset: it is a one-command rollback to a route you already left.
**Preset targets are discovered, never typed.** `overrides` and `nana_bindings` keys must resolve as
exact name → glob (`*-nrs`) → `all`, expanded against what exists (`$HERMES_HOME/profiles/*/config.yaml`;
the roster repo's own bot matrix file — the SSOT the binding files must agree with). A hand-typed roster drifts **both** ways: a stale name aborts every subcommand, and a
missing name half-applies a "switch the fleet" pass while reporting success. So an unknown exact name is
a hard error that lists the discovered candidates, and an empty expansion (glob matching nothing, `all`
discovering nothing) is an error too — "switch everything" must never silently become "switch zero".
The caller that wants precision passes `--profiles a,b,*-nrs` / `--bots …` at invocation (and can list
candidates first with `--list-profiles` / `--list-bots`); the on-disk preset carries the fleet-wide
default. Those subcommands, the `--check`/`--dry-run`/`--rollback`/`--restart-gateway` surface and the
line-preserving edits are the adapter contract: a reference adapter implements them, a hand pass
reproduces them. Validate every target and print **all** errors before writing anything; `--check` = 0 match /
1 drift / 2 spec error. Any change to this tool ships a stdlib-unittest fixture suite under
the adapter's own test directory, driven through `--home <tmpdir>` — a fleet-switch script edited
without tests is an outage waiting for the next quota reset.

**A new id in the same provider is an id swap, not a cutover** — the old id stays in every catalog
(rollback), and only live routes move: `model.default`, `delegation.model`, MoA aggregator,
`model_aliases.*`, `fallback_providers`, cron pins, harness `model`/`modelRoles`, wrapper `DEFAULT_MODEL`.
Three silent-failure traps (`model_aliases` needs `--force`, catalog copies need a comma/section-boundary
insert, omo keeps the id in three files) → [fleet cutover](fleet-cutover.md) §6.
