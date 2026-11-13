# Fleet model cutover (quota outage, provider retirement, restore)

One gateway's quota or availability dying is not a default-model change: every surface that names it fails
on its own schedule, and the homes that do the real work are the ones you forget. Move the whole fleet in
one pass, leave the route reversible, verify per surface.

## 1. Inventory before editing anything

Enumerate, in one script, every place a default route is decided:

| Surface | Where the default lives |
|---|---|
| Hermes root | `~/.hermes/config.yaml`: `model.default`, `model.provider`, `model.base_url`, `model.api_mode`, `fallback_providers` |
| Hermes homes | `~/.hermes/profiles/*/config.yaml`, same keys |
| Generated homes | bot bindings in the generator repo (see §3) |
| omp | `~/.omp/agent/config.yml` → `modelRoles.default` (`<provider>/<id>:<effort>`) |
| omo | `~/.omo/omo.jsonc` → `[native].model_profile` → `model_profiles.<p>.models` → `categories.<lane>.{model,fallback_models}`; `~/.omo/agent/models.json` for the catalog; `~/.omo/agent/settings.json` is a second place to check |
| opencode | `~/.config/opencode/opencode.jsonc` → `model`, `agents.<name>.model`, `providers.<p>.models` |
| pi | `~/.pi/agent/models.json` → `providers` (the CLI usually gets `--model` per call) |
| dsh | `~/.dsh/cordis.patch.yml` + `profiles/*/` |
| Wrapper scripts | `~/claw/tools/omp-*.sh` (`DEFAULT_MODEL`) and any launcher that hardcodes a route |
| Cron | `hermes cron list`; each profile home keeps its own `cron/jobs.json` |

**omo's category routing is a third layer, and a base-profile swap does not touch it.** `categories.<lane>.model`
and every `fallback_models` entry name a provider independently of `[native].model_profile`, so the default
looks migrated while each lane keeps routing to the outage. Swap the dead provider id in *all* of them (native
profile, `model_profiles`, every category `model`, every fallback), and diverge from the base profile only where
the lane deliberately runs another family (a slow GLM lane on judgement-heavy categories stays). Decide by the
run record, not by the file you edited: the newest `~/.omo/agent/sessions/<cwd-slug>/*.jsonl` states the model
id the CLI actually resolved.

Scope the greps to config files. A `grep -rn opencode-go ~/.omp ~/.omo` walks multi-MB session JSONL
and returns megabytes of transcript instead of the three config lines you need.

**Scope the request before you flatten the fleet.** "Switch every agent to provider B" almost always
means "every surface that names the dead provider A". Homes and harnesses that legitimately run a
different gateway (local endpoints, a cross-family critic model) are not part of that outage: moving
them onto B silently destroys role differentiation — a critic that shares the writer's model family
cannot do adversarial review. Cut over the dead-provider surfaces in full, list the untouched ones with
their reason, and ask one closed question (keep / also switch) rather than choosing for the owner.

## 2. Keep the dying provider's definition

Delete it from `model.default`, `fallback_providers` and harness defaults — never from `providers:`.
A provider entry is cheap and inert; keeping it makes the monthly restore (quota resets, trial ends)
a one-key flip instead of a rebuild. Say this explicitly in the report so nobody "cleans up" the block.

## 3. Generated homes: the route belongs to the generator

Profile homes materialized from a repo (`*-nrs` from `nana-research/bots/bindings/hermes/<bot>.yaml`)
write `model.provider|default|base_url|api_mode` from their binding on every apply. Editing the live
profile config looks correct until the next `materialize.py --apply` silently reverts it.

1. Edit the binding (provider, id; drop `base_url`/`api_mode` that belonged to the old provider).
2. `python3 bots/bindings/hermes/materialize.py --apply`.
3. `python3 bots/bindings/hermes/materialize.py --check` — **silent and exit 0 means healthy**; any
   output is drift.
4. Commit + push the binding (repo is the SSOT; a hand-edited live home is drift by definition).

`fallback_providers` has no binding field, so hand-set fallbacks survive the apply — re-read them
anyway, because a generator rewrite of the `model:` block is exactly when a stale fallback hides. When the
binding's new provider is the one a home already fell back to, that fallback becomes a self-fallback: rewrite
it to a different provider in the same pass (rule 13), or the home loses its second leg without any error.

**Before you re-materialize, check who is writing the repo.** `--check` reporting SOUL drift for every bot
right after your route change is not caused by your change: `SOUL.md` is compiled from `bots/roles/ROLE.md` +
`_invariants.md` + `_shared-behaviour.md` and carries no model information, so a model switch cannot move it.
Stat the sources (`ls -l --time-style=+%Y-%m-%dT%H:%M:%S bots/roles/`) and compare with `date` — files written
minutes ago mean another session is mid-edit. Then do neither `--apply` (you would converge a half-written
role) nor commit (you would sweep their partial work): report the drift as pre-existing and leave the files
uncommitted for the repo-sync owner.

## 4. Harness surfaces and the effort-tier gap

A provider switch can quietly drop the reasoning tier: the new provider's model entry may not declare
`max` / `xhigh`.

- omo / pi: `thinkingLevelMap` per model. `{"max": null}` means the level is unsupported and a pinned
  `max` degrades to whatever is left.
- opencode: `variants` per model. Only listed variants exist, so `#max` on a model with `none|low|high`
  is a different effort than intended.
- omp: effort is the `:<effort>` suffix on `modelRoles.default`.

Probe the relay *first*, before editing any harness config — one `curl` per level:

```bash
KEY=$(grep -h '^<PROVIDER>_API_KEY=' ~/.hermes/.env | cut -d= -f2-)
curl -s -o /dev/null -w '%{http_code}\n' <base>/chat/completions \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"<id>","messages":[{"role":"user","content":"1+1?"}],"max_tokens":32,"reasoning_effort":"max"}'
```

200 for `high`/`xhigh`/`max` → add the missing variant/level so the existing per-surface policy still
holds. 4xx on the top level → cap that surface at the highest accepted level and report the change
rather than letting the pin fail at runtime.

## 5. Verification matrix

1. Parse every touched file — `yaml.safe_load` for YAML, `json.loads` for JSON. `opencode.jsonc` needs
   comment **and** trailing-comma stripping before parsing; a raw `json.loads` failure there is your
   parser, not the config.
2. Assert the invariant programmatically: no dead provider as any home's `model.provider` and no entry in
   any `fallback_providers`; fallback entry 1 is a different provider from every default.
3. Real one-shot per surface you switched — config parsing proves shape, not routing:
   `hermes chat -q 'Reply with exactly: PROBE_OK' --oneshot -t clarify -Q` for root, and
   `HERMES_HOME=~/.hermes/profiles/<p> hermes chat …` for one switched home. Do one switched home and
   one untouched home; the untouched one proves you did not break the routes you left alone.
4. Install-level checks: `profile-layer-reconcile.py --dry-run` (no `--check` flag), `contract-drift-check.py`,
   and the generator's `--check`.
5. Channel-served bots and the restart question: a config change reaches a home through agent construction,
   so a *new* session usually picks it up while an in-flight session keeps the old route. Do not assert either
   way from code reading — check the home's own `state.db` before/after pair after real traffic (details in
   SKILL.md → Proof). Restarting the gateway is the gated fallback, and it is actively harmful when another
   agent session is mid-write: ask, never restart to "finish" the task.
6. **Prove each harness from its own run record, not from the config you just wrote.** Hermes answers with a
   `state.db` session row; OMP writes `<run dir>/state.json` with `model` and `thinking` per run (its event
   stream repeats both on every call); omo writes the session JSONL above. Reading config only proves intent —
   the record is what separates "edited" from "routed".

## 6. Same-provider id swap (new variant of an existing model)

Adding `deepseek-v4.1-flash-fast` next to `-flash` is not a cutover: the provider entry stays, only the id in
every default/pin changes. Same inventory, three traps worth knowing:

- **`hermes config set` on an "unknown" dotted path exits 0 and writes nothing.** `model_aliases.<a>.model`
  is one: it prints `(Use --force to skip this notice.)` with exit status 0, so a batch loop that checks only
  the return code reports success and leaves the alias on the old id. `agent.reasoning_overrides` and
  `providers.<p>.models` (whole-map JSON) are accepted without `--force`; aliases are not. Re-run those with
  `--force` and read the YAML back — treat "notice printed" as failure.
- **Inserting a catalog copy needs the delimiter the source block did not have.** The model you copy is often
  the last key in its map (no trailing comma) and the next line closes the map: opencode's
  `providers.<p>.models.<id>` and omp's `models:` list both behave that way. Add `,` (JSONC) or insert *before*
  the list terminator (YAML), then parse the file before trusting it — a broken JSONC is not a config error you
  will see until the CLI starts ("Model unavailable: …").
- **Find the end of a YAML list block by section boundary, not by the next `- id:` line.** omp's
  `~/.omp/agent/models.yml` repeats 4-space `    - id:` items under every provider, so "next `- id:`" lands
  inside the following provider and duplicates its key; `yaml.safe_load` keeps one copy silently and the new
  model simply never appears in `omp models`.

Catalog ids are additive: keep the old entry (rollback, and other surfaces still name it) and only rewrite the
live defaults, aliases, MoA aggregator, delegation pin, fallbacks, cron pins and harness `model`/`modelRoles`.
omo needs three files (`omo.jsonc` lanes, `agent/settings.json` `defaultModel` — bare id, no provider prefix — and
`agent/models.json` catalog); dsh only carries catalog entries unless a profile sets a default.

Harness CLIs whose model list is generated (`sync-litellm-catalog.py`, `litellm-protocol-smoke.py` spec tables)
need the new id added to their own table, or the next sync drops the entry. A wrapper's `DEFAULT_MODEL` and a
provenance stamp (`distilled_by:`) count as usage too.

Probe each surface with the new id itself (`opencode run -m <p>/<id>#max`, `omp -p --model <p>/<id>`, `pi -p
--model <p>/<id>`, `omo -p --model <p>/<id>`), then `model-switch.py <live-preset> --check` — the preset must be
edited in the same pass or it reports drift against a state you just created on purpose.

Run these edit scripts with `/usr/bin/python3`: the first `python3` on PATH is a Hermes install venv that has
ruamel but no PyYAML, and the failure surfaces only after the first `import yaml`.

## 7. Rollback and hygiene

- One script, one backup root: `~/claw/backups/<cutover>/<ts>/` mirroring home-relative paths, printing
  the changed-file list so the report can cite it. Restore = copy back, then `git revert` the binding commit.
- Do the edits in a single idempotent script that prints `changed N files` plus any `MISS <pattern>` lines;
  a text-anchored replacement that silently misses leaves a half-cutover with a clean exit code.
- In a shared repo, `git add` only the files you touched. Another agent's dirty working tree
  (`studies/…` here) is in-flight work, not cleanup debt.
- **The cutover is not done while an always-loaded instruction file still names the old primary route.**
  The routing paragraph in the operating contract (which provider is "main", which pool is for
  background work) and any standing memory/fact entry written for the previous primary both go stale the
  same way; update them in the same pass, and state the temporary nature ("until the quota resets") so the
  next reader does not treat the emergency route as the new policy. Leaving the paragraph alone means the
  fleet obeys a rule it no longer follows.
