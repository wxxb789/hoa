# Delegation routing and per-profile providers

<!-- install-root: `$HERMES_HOME` below means the install root; it defaults to `~/.hermes` -->


## Delegation model routing (main session model A, subagents model B)

The "frontier planner, inexpensive workers" pattern: the parent keeps `model.default`; every
`delegate_task` child runs on the `delegation.model` pin. Set with `hermes config set
delegation.model <id>` plus `delegation.provider` or `delegation.base_url` for a different route.
Resolution lives in `tools/delegate_tool_config.py::_resolve_delegation_credentials` — rules that
are easy to get wrong:

1. Precedence: `delegation.base_url` → direct endpoint (`delegation.api_key` empty = inherit the
   parent key); else `delegation.provider` → full credential bundle via the runtime provider
   system; else pure inherit (parent provider + model + key + credential pool). `delegation.model`
   applies on every branch; empty = inherit the parent model.
2. The pin is global to the profile — `delegate_task` has no per-task model parameter. Per-task
   granularity needs another rail: the Kanban per-card override (see skill `kanban-workflows`), a
   per-job cron pin (`hermes cron edit --model/--provider`), or an independent spawn
   (`hermes chat -q -m <model> --provider <p>`).
3. A pinned child never borrows the parent's fallback chain — pin means single-route. Give children
   their own with `delegation.fallback_providers` when the pinned route can flake.
4. `api_mode` is re-derived, never inherited, when the child's provider differs from the parent's —
   inheriting the parent's wire 404s on the child's endpoint. On this install respect the per-model
   transport split above: `local-openai` for `/v1/responses` models (gpt-*, grok-*), `local-chat`
   for chat-completions models (gemini-*-flash).
5. Schema-bearing changes apply to NEW sessions only — the delegation tool schema is built at
   session start, so never flip the pin mid-conversation. Profiles never inherit root config: set
   the pin in each profile that must route children differently, then verify with a real child
   spawn and its live transcript (`$HERMES_HOME/cache/delegation/live/<id>/task-0.log`) —
   `hermes config get` proves nothing about the route.

### Moving a profile onto a provider it does not define

A profile config carries its **own** `providers:` map, so pointing `model.provider` at a provider
that only root declares fails at runtime, and `config set` alone cannot make it work. Checklist per
profile:

1. Inspect first: `hermes --profile <p> config get model` + `config get providers` (key list).
2. Add the provider block (`name`, `api`, `key_env`, `transport`, `discover_models`, `models`).
   A dotted model id (`deepseek-v4.1-flash`) cannot go through `hermes config set` — it splits into a
   phantom nested mapping — so round-trip the YAML with ruamel (`preserve_quotes`), then validate the
   temp file with a plain `yaml.safe_load` assert before replacing the live file. Back up first.
3. **Delete `model.api_key`.** Cloned profiles carry an inline `api_key: local` for the local proxy;
   it outranks the provider's `key_env` and gets sent as the bearer token → 401 on the new route.
4. Copy the provider's `key_env` value into **that profile's own** `.env` — secrets are per
   `HERMES_HOME`, so a key only in root `.env` fails as an unscoped secret.
5. Verify per profile with a live one-shot (`hermes --profile <p> chat -q 'Reply exactly: X'`) plus
   `resolve_reasoning_config(load_config(), <model>)` under `HERMES_HOME=<profile>`; `config get` alone
   does not prove key, transport or effort.

No gateway restart is needed when `gateway.profile_routes` is empty — channel traffic resolves to the
root/default profile, and profile config is read when a profile session starts.
6. Read live limits before promising fan-out: `hermes config get delegation`. This install
   overrides upstream defaults (e.g. concurrency 3 vs upstream 10, a nonzero child inactivity
   timeout vs upstream none) — quote the live values: an oversized batch returns a tool error, and
   a quiet child is abandoned at the local cap, not the documented one.

## Which layer decides the model

Before promising a routing behaviour, locate it in this table — each row has a different change cost
and a different time-to-effect.

| Layer | Key / mechanism | Granularity | Takes effect |
|---|---|---|---|
| Root session | `model.default` + `model.provider` | one per session | `/new`, `/model`, next session |
| Subagents | `delegation.provider` / `.model` | one per profile, all children | next spawn (config re-read in `delegate_task`) |
| Subagents, per task | `delegation.backend` → `DelegationProvider` plugin | one per task | next session (tool schema built at session start) |
| Cron jobs | `--model` / `--provider` on the job | per job | next run |
| Bots / profiles | `profiles/<n>/profile.yaml` `model` | per profile | next profile session |
| One-shot CLI calls | `pi`/`omp -p --model <provider>/<id>` | per invocation | immediately |
| Outage fallback | `fallback_providers` | ordered list | per request |

Instruction files (AGENTS.md, SOUL.md) appear in none of these rows: they change what the agent
*chooses* to do with these layers. A request like "send background work to the cheap pool" is only
half-implemented by documenting it — the other half is the `delegation.*` pin, the cron pins, and
the fallback chain.

The backend seam is real but unpopulated: `agent/delegation_registry.py` resolves
`delegation.backend`, and the only bundled provider is `plugins/delegation/default`, which applies
the `delegation.*` section verbatim. Per-task automatic selection therefore needs a custom
`DelegationProvider` returning one `{provider, model, reasoning_effort?, profile?}` route per task;
until it exists, per-task routing belongs to the caller (`pi`/`omp` with an explicit `--model`).

## Tiered routing: fast pool vs free pool

When one gateway bills nothing and another is fast, split by **who waits**:

- hot path (default session, anything the user is watching, quality-critical review) → fast provider;
- subagents, cron agent jobs, batch/self-improvement runs, isolated contexts → free pool;
- paired or multi-view lanes (blind review, MoA references) → at least one member from the free pool, so
  heterogeneous capacity is used rather than idle;
- `fallback_providers` on a provider **different** from `model.provider`, otherwise the outage takes both.

A script that generates fallbacks must **compute** the heterogeneous pick per home, never hardcode one
provider: a hardcoded `opencode-go-flash` fallback written into every profile silently becomes a
self-fallback in the profiles whose default is already `opencode-go-flash`, and the drift is invisible
until that gateway dies. Pattern: read each home's `model.provider`, take the first candidate whose
provider differs, and `keep` the existing chain when it already spans a second gateway (so a
hand-tuned 3-entry chain is never flattened back to one).

Probe every id in the pool once before wiring it — one id can be down while its siblings answer:

```bash
export PATH="$HOME/.local/share/mise/shims:$PATH"
for m in <id1> <id2> <id3>; do
  echo "== $m"; timeout 240 pi -p --no-tools --no-skills --model <provider>/$m --thinking low 'Output exactly: PONG'
done
```

A 503 naming the model group (`LiteLLM: model group '<id>' failed`) is upstream capacity on that id,
not a credential or route problem: rotate to a sibling id instead of re-debugging the config, and
audit any weekly gateway smoke test whose `EXPECTED` matrix still claims 200 for that id.

### Pinning a whole class of background jobs

Each profile home keeps its **own** `cron/jobs.json`, so pinning the root store leaves every bot's
schedule on its profile default. Procedure:

1. Enumerate every store: `$HERMES_HOME/cron/jobs.json` plus `$HERMES_HOME/profiles/*/cron/jobs.json`.
2. Classify each job: an entry with a `script` is `no_agent` — its `provider`/`model` fields are
   **inert**, nothing reads them, so it never counts as free-pool coverage. Only entries without
   `script` are agent runs that resolve a model.
3. Pin each agent job in its own home: `hermes -p <profile> cron edit <id> --model <id> --provider <p> --pin`
   (root store: drop `-p`). `--pin` is what survives a later change of the profile default.
4. Verify by re-reading the stores and counting `provider == <free pool>` against the agent-job total —
   a config command returning `Updated job:` is not proof the pin persisted.

### Deprecating a duplicate or superseded job

Two enabled jobs on the same cron expression and the same topic = double model spend and two
conflicting deliveries at the same minute. Compare their prompts, keep the one whose output the owner
actually reads (a bot's richer job usually wins over a thin root shim), then
`hermes cron pause <id>` — kept, reversible, history intact — and confirm `enabled: false` in the
store. Deleting is for prompts worth nothing; a pause is the default for "deprecated but possibly
wanted back".

## Operational details

**Delegation pin** is global to the profile; `delegate_task` has no per-task model parameter and its schema
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

**Profiles carry their own `providers:` and `.env`.** Add the block, delete any inherited inline
`model.api_key` (it outranks `key_env`), copy the key into that profile's `.env`, then verify with a
live one-shot under `HERMES_HOME=<profile>`.

**A single bounded task on a non-default model: harness CLI first (`pi`, then `omp`), not
`hermes chat`.** `pi -p --no-tools --no-skills --model <provider>/<id> --thinking high @prompt.md`
carries the prompt and nothing else — no tool schemas, no session context — so instruction
following on long writing/analysis prompts is measurably tighter. Resolve the binary before
concluding it is missing: `command -v pi`, then the install's own lookup if it has one
(`mise which pi`), then an explicit path the operator keeps. A CLI installed through npm, a
tool manager, or a pinned path is just as valid — and `command -v` returning empty in a
non-interactive shell means "not on this PATH", not "not installed". Export whatever directory
holds it, or call the absolute path. `omp -p` is the fallback (it truncates large attachments).

**Name the layer before the model.** Seven places decide a model, each with its own lifetime:
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

**Tiered routing: fast pool on the hot path, free/slow pool for everything that can wait.** The
default session and anything the user waits on stay on the fast provider; subagents, cron agent
jobs, batch lanes, self-improvement runs and isolated-context work go to the free pool; paired or
multi-view lanes (blind review, MoA references) keep at least one free-pool model so the cheap
capacity actually gets used. When the free pool is one gateway with several ids, a 5xx rotates
across ids — the failure is the upstream id, not the route config, so probe each id once before
blaming the config.
