---
name: hermes-models
description: >-
  Configure Hermes model providers, transports and routing: provider entries, default-route
  switching, reasoning effort, delegation pins, per-profile copies, and proving a route with live
  signals. Use when a model 404s or rejects an endpoint, a profile ignores its key, config drifts
  between root and profiles, vision or image generation errors, or a relay's effort/cost looks
  wrong. Not for another harness's own model configuration.
metadata:
  version: "0.1.59"
  areas: "software-development"
  targets: "hermes"
  summary: "configure Hermes providers, transports and routing; prove every route with live signals, not `config get`"
  summary_zh: "配置 Hermes provider、传输与路由；用实时信号证明路由，而非 `config get`"
  kind: "entry"
---

## Install-side hooks (the check is required, the script is not)

`$HERMES_HOME/scripts/*.py` in these docs names a hook the install may ship — a config snapshot
(`config-snapshot.py`), an install-facts snapshot (`snapshot-install-facts.py`), a fleet-switch adapter
(`model-switch.py`), catalog sync/smoke helpers, and the fleet verification pair
(`profile-layer-reconcile.py`, `contract-drift-check.py`). What matters is the outcome each one
verifies (the route is live, the metadata resolves, the generated layer agrees with its source), not the
filename. Resolve the command from the install or from this skill's config keys; when the install ships
none, say the check is **unavailable** instead of implying it passed.

# Hermes Models & Providers

<!-- install-root: `$HERMES_HOME` below means the install root; it defaults to `~/.hermes` -->

Provider keys in these examples (`local-chat`, `local-openai`, …) belong to the reference install:
read your own `providers:` block and substitute.

## When to Use

| You hear / see | Load |
|---|---|
| 换默认模型 / 加 provider / 换 endpoint | rules below + `references/model-switching.md` |
| 某模型 404、`does not support the responses endpoint` | `references/custom-providers.md` |
| "让 subagent 用便宜点的模型" | `references/delegation-routing.md` |
| "routing 机制怎么运作" / "能不能按任务自动选模型" | rules 6 + 16 + 18, `references/delegation-routing.md` |
| profile 里模型/密钥不生效、只有 root 能用 | `references/delegation-routing.md` → per-profile provider |
| 配置在 root 和 profile 之间漂移 | `references/config-drift.md` |
| "review 全部 model routing" / 审计整条路由策略 | rules 16 + 18, `references/config-drift-audit.md` |
| vision / image_gen 报错、`auto` 路由 | `references/config-drift.md` |
| 给模型声明 context_length / 元数据 | `references/provider-metadata-audit.md` |
| 某 relay 的 effort/成本/流式行为异常 | `references/model-endpoint-matrix.md` |

**Not for**: harness-level endpoints (pi/omp/opencode/dsh) → `agent-harness-model-gateways`.

## Rules

1. **Transport is per model, not per endpoint.** One proxy serves `/v1/responses` for some ids and
   `/v1/chat/completions` for others; probe both before concluding a capability is missing.
2. **Provider entries** live under top-level `providers:`; `model.provider` normally names the bare
   key (`local-openai`). A `custom:<name>` prefix is also accepted for custom-gateway entries, so a
   drift check must strip a leading `custom:` before comparing against the `providers:` keys — a raw
   string compare reports every valid custom route as undefined. Declare `context_length` per model.
3. **Switching the default route:** writing `model.provider` **clears** `model.base_url` / `model.api_mode`.
   Order: backup → `model.default` → `model.provider` → `model.api_mode` → `model.base_url` →
   `agent.reasoning_effort`. Takes effect on `/new` or next session start. Promoting a provider that
   already led `fallback_providers` leaves the chain starting with the new default itself — reorder
   the chain in the same pass so entry 1 is a different provider.
4. **Prove the route with three signals**, never `config get`: one-shot `hermes chat -q 'Reply with
   exactly: PROBE_OK'`; the `sessions` row it created (read-only `state.db`); and
   `resolve_reasoning_config(load_config(), "<model>")`.
5. **`agent.reasoning_effort` is global**, not per model — change it and every selectable model re-tiers.
   Put per-model levels in `agent.reasoning_overrides` and say which models moved. The "not a recognized
   config key" warning is noise; the runtime reads it. Effort is also **per surface**: the Hermes session,
   `opencode` (`#max` variant), and `omp`/`omo` (thinking level) can legitimately sit on different tiers for
   the same id — e.g. `deepseek-v4.1-flash` at `high` inside Hermes while the CLIs run `max`. Ask which
   surface the owner means before "aligning" them; do not raise the session tier because a CLI is higher.
6. **Delegation pin** is global to the profile; `delegate_task` has no per-task model parameter and its schema
   is built at session start (never flip mid-conversation). Per-task granularity = Kanban card override, cron
   pin, or independent spawn. Verify with a real child spawn + its live transcript.
   The section is **re-read on every spawn** (`_load_config()` inside `delegate_task`), so editing
   `delegation.provider|model` applies to the next child — no restart, no `/new`; blank means "inherit the
   parent model". True per-task routing needs `delegation.backend` set to a registered
   `DelegationProvider` (`agent/delegation_registry.py`); the only bundled one is
   `plugins/delegation/default`, which merely applies the `delegation.*` section. A custom backend returns
   one route per task (`provider`, `model`, optional `reasoning_effort` / `profile`) and may declare extra
   `task_parameters()` to the model — that is the seam for "background work → cheap pool, hot path → fast
   pool". Until such a plugin exists, per-task routing is the caller's job: name the model explicitly on the
   `pi`/`omp` spawn.
7. **Profiles carry their own `providers:` and `.env`.** Add the block, delete any inherited inline
   `model.api_key` (it outranks `key_env`), copy the key into that profile's `.env`, then verify with a
   live one-shot under `HERMES_HOME=<profile>`.
8. **Dotted model ids** cannot go through a dotted path — `providers.<n>.models.deepseek-v4.1-flash.context_length`
   builds a phantom nested mapping. Set the whole map as one JSON value instead
   (`hermes config set providers.<n>.models '{"GLM-5.3":{"context_length":1048576},"deepseek-v4.1-flash":{"context_length":1000000}}'`),
   or edit YAML with plain dotted keys. Back up first, then read the file back with a YAML parse — a
   masked `config get` cannot prove the map shape, and a successful chat does not prove the override
   was read.
9. **Reasoning effort is a hint, not a guarantee**, and the effort→cost ladder is per relay and
   non-monotonic. Judge from `usage.reasoning_tokens`; size `max_tokens` per model because reasoning is
   charged against it on chat-completions transports.
10. **`auxiliary.vision: auto` is a trap** — doctor green only proves routing resolved. Pin provider+model
    in root **and** every profile, then run one real image call per profile.
11. **Config drift is the default failure mode.** Classify root-only keys as "never overrode" vs
    "deliberately different" before mirroring; read back after every write; regenerate
    `$HERMES_HOME/scripts/config-snapshot.py`.
12. **Text-only one-shot generation is `-t clarify`, not `-t ""`.** An empty `-t` value leaves the
    FULL toolset enabled — the model can write files and emits tool/diff previews into stdout,
    corrupting programmatic parsing; `-t none` is rejected as an unknown toolset name. Inert form:
    `hermes chat --query-file <f> -m <model> --provider <p> -t clarify -Q --ignore-rules --max-turns 1`,
    then strip the trailing `session_id:` line from stdout. `hermes chat` takes `-q/--query` (add
    `--oneshot` to answer and exit) — there is no `-p`; `-p` is the `pi`/`omp` flag. Prove inertness once
    per model by asking it to create a file and checking it cannot.
13. **Aliases and fallbacks are separate records from the provider entry.** `model_aliases.<name>` is a
    DirectAlias (`model`, `provider: custom`, `base_url`, `key_env`) resolved *before* the catalog, so
    it needs its own copy of the URL and key variable. `fallback_providers` entries are
    `{provider: <provider key>, model: <id>}` resolved through the provider registry, and they are
    per-home — set them in root **and** every profile. Prove both with one probe: point a throwaway
    alias at a nonexistent model id; the error names that id (alias routed) and the run continues on
    the fallback (`Model fallback: … via <provider>`), which proves the chain end to end. Delete the
    probe alias afterwards. A fallback entry must name a **different provider** than
    `model.provider` — same-provider fallback dies with the outage it was meant to cover, so a
    default on `opencode-go-flash` falls back to a second gateway, not to another id on the same one.
14. **A single bounded task on a non-default model: harness CLI first (`pi`, then `omp`), not
    `hermes chat`.** `pi -p --no-tools --no-skills --model <provider>/<id> --thinking high @prompt.md`
    carries the prompt and nothing else — no tool schemas, no session context — so instruction
    following on long writing/analysis prompts is measurably tighter. Resolve the binary before
    concluding it is missing: `command -v pi`, then the install's own lookup if it has one
    (`mise which pi`), then an explicit path the operator keeps. A CLI installed through npm, a
    tool manager, or a pinned path is just as valid — and `command -v` returning empty in a
    non-interactive shell means "not on this PATH", not "not installed". Export whatever directory
    holds it, or call the absolute path. `omp -p` is the fallback (it truncates large attachments).
15. **Long generation runs in the background; wait on the event, never on a foreground `sleep`.**
    `terminal(background=true, notify_on_complete=true)` then end the turn, or block once with
    `process_manage wait` (600 s) — do not poll a file size with `sleep 60..240` calls: each one
    blocks the same wall-clock, blocks every other task, and any sleep over the 180 s foreground
    timeout dies empty-handed. `sleep` is only for a fixed delay with no event to wait on (e.g. a
    CI run not yet visible in `gh run list`), and then ≤30 s. If a long generation comes back
    truncated (a few hundred bytes instead of a full answer), re-run with `--thinking medium` plus
    an explicit stop condition ("write through to the last section") rather than the same call again.
16. **Name the layer before the model.** Seven places decide a model, each with its own lifetime:
    `model.default|provider` (per session, `/new` or `/model`), `delegation.*` (per spawn),
    `delegation.backend` (per task, plugin), per-job cron pin (`hermes cron edit --model/--provider`),
    each profile's `profile.yaml`, per-invocation `pi`/`omp --model`, and `fallback_providers`
    (runtime). Instruction files (AGENTS.md / SOUL.md) only steer **which** layer the agent reaches
    for — they never change resolution, so "I edited AGENTS.md" is not an implementation of routing.
    Always report which layers changed and which stayed instruction-only.
    A whole-surface audit must enumerate all seven **plus every cron store**: each profile home keeps its own
    `cron/jobs.json`, so a job pinned only in root leaves the same work unpinned where it actually runs. Pins
    on `no_agent` script jobs are inert — nothing reads them, so they never count as free-pool coverage — and
    a harness catalog must be read from that harness's own `models` command, not from its config file.
17. **`$HERMES_HOME/config.yaml` cannot be edited with `patch`/`write_file`** — the tool refuses it ("Refusing
    to write to Hermes config file"); route every write through `hermes config set <dotted.key> <value>`.
    List-valued keys take a JSON string (`hermes config set fallback_providers '[{"provider":"p",
    "model":"m"}]'`) and land as proper YAML; back up the file first, then `hermes config get <key>`
    plus a read of the YAML block for shape.
18. **Tiered routing: fast pool on the hot path, free/slow pool for everything that can wait.** The
    default session and anything the user waits on stay on the fast provider; subagents, cron agent
    jobs, batch lanes, self-improvement runs and isolated-context work go to the free pool; paired or
    multi-view lanes (blind review, MoA references) keep at least one free-pool model so the cheap
    capacity actually gets used. When the free pool is one gateway with several ids, a 5xx rotates
    across ids — the failure is the upstream id, not the route config, so probe each id once before
    blaming the config.
19. **A fallback or pin is only as real as that home's catalog.** `providers.<p>.models` is a per-home
    map: root can be missing an id that several profiles already run as their *default* (`gpt-6.1-sol`
    ran in three profiles while root's catalog never listed it), and a fallback entry naming a missing
    id fails at failover — exactly when it is needed. Read the catalog of the home you are editing and
    add the id there first (whole-map JSON, rule 8), then wire the fallback. Effort variants: a
    `#variant` is supplied by the client config, so prove the relay accepts it with a CLI override
    *before* editing anything — `opencode run -m <provider>/<id>#max 'Reply with exactly: V_OK'`.
    Editing the config first leaves you unable to tell a rejected variant from a flaky relay.
    Config surgery inside generated/provider files (repeated blocks) → `references/config-drift.md`.
20. **A provider outage is a fleet cutover, not a default change.** Every home and every harness that
    names the dead provider moves in one pass, and the provider entry itself stays in `providers:` so
    restoration is a single key flip. Two places make a half-cutover look finished: a generated home whose
    route lives in its generator's repo (editing the generated config is reverted on the next apply), and
    per-harness effort metadata (`thinkingLevelMap` / `#variant`) that lacks the new id's top tier, which
    silently downgrades every "max" pin. Inventory → migrate → verify against every surface:
    `references/fleet-cutover.md`.
21. **A fleet cutover is one command, not 16 edits.** An adapter — resolved as
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

21b. **A new id in the same provider is an id swap, not a cutover** — the old id stays in every catalog
    (rollback), and only live routes move: `model.default`, `delegation.model`, MoA aggregator,
    `model_aliases.*`, `fallback_providers`, cron pins, harness `model`/`modelRoles`, wrapper `DEFAULT_MODEL`.
    Three silent-failure traps (`model_aliases` needs `--force`, catalog copies need a comma/section-boundary
    insert, omo keeps the id in three files) → `references/fleet-cutover.md` §6.

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
python3 - <<'PY'                                                 # 2. the session row
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

## References

- `references/custom-providers.md` — provider YAML shape, transport table, per-model sizing, relay header
  quirks, and **the install's own policy overlay** (banned ids, unavailable families, vision pinning) —
  the method for each is above; the list itself belongs to the install, not to this skill.
- `references/model-switching.md` — switching order, three-signal proof, ghc-proxy deployment, Copilot
  fallback hygiene.
- `references/fleet-cutover.md` — multi-home, multi-harness provider cutover (quota outage, retirement,
  restore): inventory map, generated homes, effort-tier gaps, verification matrix, rollback.
- `references/delegation-routing.md` — which layer decides the model (7-row table), delegation precedence,
  fast-pool/free-pool tier policy + pool probe loop, per-profile provider migration checklist.
- `references/config-drift.md` — drift audit, lettered tier menu, reasoning-effort layers, auxiliary vision.
- `references/provider-metadata-audit.md`, `references/model-endpoint-matrix.md`,
  `references/config-drift-audit.md` — audit detail.
- `references/cases.md` — historical cases: Copilot fallback cleanup, ghc-proxy deployment.
- `scripts/audit-provider-metadata.py`, `scripts/audit-config-drift.py`,
  `scripts/audit-routing-inventory.py`, `scripts/probe-provider-endpoint.sh` — runnable probes (the
  inventory one dumps every routing layer for all homes into JSON and flags self-fallbacks and cron
  coverage); `templates/ghc-proxy.service` — unit template.
