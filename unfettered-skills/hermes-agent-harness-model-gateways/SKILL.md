---
name: hermes-agent-harness-model-gateways
description: "Use when an LLM endpoint/key must serve every harness."
version: 1.0.0
author: Zoe (Hermes)
license: MIT
metadata:
  hermes:
    tags: [providers, gateways, codex, opencode, dsh, hermes, credentials, rotation, multi-harness]
    related_skills: [hermes-agent, hermes-operations, hermes-models]
---

# Agent-harness model gateways

One gateway (base URL + key + model id) never lives in one place. A machine running several agent
harnesses keeps one provider entry per harness, each in that harness's own config file, each with its
own credential store. "Configure/rotate provider X" therefore means **every harness**, not the one
named in the request.

## When to Use

Trigger phrases: "config this provider to hermes and all agent/harness on this machine", "the provider
just changed endpoint and api-key, help me upgrade", "add model M as a provider", "verify the new key
works". Also load it to *choose a harness for a one-off model call* (§5) — "run this task on model X"
is a routing question, not a shell-scripting question. Also load it before deleting or disabling any
provider entry, and whenever a mirrored provider config may be stale — the failure mode here is
silent divergence, not an error message.

## 1. Enumerate before touching anything

```bash
for b in hermes pi omp omo opencode opencode2 codex claude dsh dsh-tui aider gemini crush goose vibe; do
  command -v "$b" >/dev/null && echo "$b: $(command -v "$b")"
done
ls -d ~/.pi/agent ~/.omp/agent ~/.omo/agent ~/.config/opencode ~/.opencode ~/.codex ~/.claude ~/.gemini ~/.dsh ~/.dsh-tui ~/.continue 2>/dev/null
ls ~/.hermes/profiles 2>/dev/null          # each profile is a separate HERMES_HOME
```

Enumerate by HOME DIRECTORY as well as PATH: a harness's config dir often exists while its binary is
off PATH, and a harness can be installed with no config yet. A rotation that updates only the harness
in the request leaves the others dialling the old endpoint, and nobody notices until that harness is
used. Say which harnesses you found before you start, so a missed one is visible early.

**Distinguish the upstream service from each harness's local registration.** Reuse existing
transport-compatible entries. If a harness lacks the entry, an all-harness request covers registering
the existing upstream there; do not invent a prohibition on new local entries. Preserve defaults and
credentials, and retain a Responses provider while using its chat sibling or a supported per-model
API override for chat-only models.

**Parallelize independent harness changes after inventory.** Give subagents disjoint config-file
ownership and a common upstream/model contract; keep route probes and final aggregation in the main
session. Split independent harnesses rather than putting the entire inventory behind one worker.
Require paths, backups, exact test mode, return codes and output excerpts; read back the live targets
before consolidating the final harness → status table.

## 2. Probe the endpoint BEFORE writing config

Route problems and auth problems read completely differently; identify the layer first. Load
`hermes-agent` and its **Providers & Model Aliases** reference for full triage. Short form:

- `404 "no Route matched with those values"` (Kong-shaped gateway) → wrong host or path.
- `404 {"detail":"Not Found"}` (app-level, from the model server) → the path is wrong; a missing
  `/v1` produces exactly this.
- `401 "No API key found in request"` → the gateway does not read that header NAME.
- `401 "Unauthorized"` → it read the credential and rejected it: the KEY VALUE is the problem. Stop
  trying header names and formats — no variant can succeed. Hand it back to the owner.
- **Per-route answers are independent.** `/v1/chat/completions`, `/v1/messages` (Anthropic) and
  `/v1/responses` (the Codex wire) can each be 200 or 404 on the same host. Probe every route you
  intend to use; gateways are frequently chat-only, and that fact decides which harnesses can be
  wired to them at all.
- **LiteLLM proxy specifically** — its virtual keys must start with `sk-` (a wrong-shaped key answers
  `401 LiteLLM Virtual Key expected` = URL/path are right), all three routes are normally mounted,
  and model ids are proxy aliases that need a valid key to enumerate. Wiring, probe and
  credential-placement detail: `references/litellm-proxy.md`.

Send a body shaped for the route — a chat body posted to `/v1/responses` returns a 400 validation
error, which is not an auth answer and will mislead you. Ready-made probe (route map + fingerprint,
secret-safe): skill `hermes-agent` → `scripts/probe-provider-endpoint.sh <KEY_ENV_VAR> <base-url>...`.

## 3. Apply per harness, with that harness's own writer

Use a supported CLI writer when available (`hermes config set`, `opencode service set`). When no
writer exists for the provider catalog, inspect the installed schema and make a minimal config edit;
do not confuse a credential writer with a model-catalog writer. Back up every edited file first:
`cp -p <file> <file>.bak-$(date +%Y%m%d-%H%M%S)`.

| Harness | Provider entry | Credential store |
|---|---|---|
| Hermes root | `~/.hermes/config.yaml` → `providers.<name>`, plus `model_aliases.<name>` if the owner uses `/model <alias>` | `~/.hermes/.env` |
| Hermes profiles | `~/.hermes/profiles/<p>/config.yaml`, same keys via `HERMES_HOME=… hermes config set …` | `profiles/<p>/.env` — **never** inherits root |
| OpenCode | `~/.config/opencode/opencode.jsonc` → `providers.<name>` | `opencode service set env <VAR> <value>`, plus the shell env for `--standalone` |
| Codex | `~/.codex/config.toml` → `[model_providers.<name>]`, plus profile `~/.codex/<name>.config.toml` | env var read from the shell; supply it from a 600-mode file sourced by `~/.bashrc` |
| dsh / dsh-tui | `~/.dsh/cordis.patch.yml` → `llm-pi-ai.config.providers.<name>` | `~/.dsh/.credentials.yaml` `refs:` **and** the process env |

Exact copy-paste blocks: `references/harness-config-recipes.md` (this skill).
Hermes-specific detail (dotted-key handling, profile isolation and protected config files) lives in
`hermes-agent` under **Providers & Model Aliases** and **Local install specifics**.

## 4. Verify every harness with a real request

`config get` proving the key is set proves nothing. One one-shot per harness, then report a
harness → ok/fail table with the exact error body for failures:

```bash
hermes chat --provider <name> -m <ID> -q "Reply with exactly: OK" --oneshot
HERMES_HOME=~/.hermes/profiles/<p> hermes chat --provider <name> -m <ID> -q "…" --oneshot
opencode run --standalone --model <name>/<ID> "Reply with exactly: OK"
codex exec -p <name> --skip-git-repo-check "Reply with exactly: OK"
dsh --profile headless --patch <overlay.yml> "Reply with exactly: OK"
```

Report actual verification strength: a normal-config request, an isolated request, a catalog listing,
and shared-config inheritance are different proofs. Do not label a TUI generation verified from a
headless sibling's response, or label dormant config as CLI-tested. For clients rejecting a required
wire protocol, verify the rejection and the upstream route independently instead of saving an invalid
provider entry.

Also close the loop on the whole config, not just the file you edited: grep the config tree for the
OLD host (`grep -rn '<old-host>' ~/.hermes ~/.codex ~/.dsh ~/.config/opencode`) and account for every
remaining hit — fixed, or deliberately kept and explained to the owner.

## 5. Route one bounded task on a non-default model (pi-family CLIs)

When the goal is "run this one job on a specific model" (second opinion, deep review, one-off
generation) — not a durable multi-card workflow — call the pi-family CLI one-shot instead of writing
`curl`/SSE scripts or opening a Kanban board:

```bash
pi  -p --no-tools --no-skills --model <provider>/<id> --thinking high @prompt.md > out.md
omp -p --no-tools --no-skills --model <provider>/<id> --thinking high @prompt.md > out.md
omo -p --no-tools --no-skills --model <provider>/<id> --thinking high @prompt.md > out.md
```

Why: the CLIs own streaming, retries, provider quirks, response-shape parsing and credential
resolution. Hand-rolled HTTP repeatedly fails on gateway timeouts, stream stalls and response shapes
(a long reasoning prompt to a Tencent gateway 401s or stalls mid-stream, while the same call through
`omp` returns clean text). Kanban is for durable/multi-card shared work with review, not a single call.

**Harness preference order: `pi` first, `omp` as fallback.** Reach for
`omp` when `pi`'s catalog lacks the provider or errors; `omp` is the one that tends to hold the custom
gateway routes.

**The three are separate products with separate packages — never dedupe one against another.**
`pi` is its own tool; `@oh-my-pi/pi-coding-agent` ships the `omp` binary; `omo-ai` ships only `omo`.
Read a candidate's `package.json` `bin` map before removing it: a family mate that provides a
*different* command is a different tool, not a duplicate install, and uninstalling it silently
deletes a working harness. Each should be installed by exactly one manager, and all three stay. Do not write a shell/Python HTTP client "because it is quicker" — the script is the
part that breaks.

**A reasoning model's "empty response" is usually a cut channel, not a refusal.** Long-thinking models
stream `reasoning_content` first and the answer last, so a truncated or stalled channel yields
`content: 0` with tens of thousands of characters of reasoning behind it. Before concluding a model
failed: check the reasoning field, and re-run through the harness (`-p`) — a harness that retries and
buffers turns the same call into clean text. Never paste a raw SSE/JSON dump into the transcript as
evidence of a model's opinion.

Config homes for this family (verified on this machine, 2026-10):

| Harness | Providers | Credentials |
|---|---|---|
| pi | `~/.pi/agent/models.json` | `~/.pi/agent/auth.json` → `{"<provider>":{"type":"api_key","key":"…"}}` (also `"!cmd"`, `${ENV}`, or a literal `apiKey` in models.json) |
| omp | `~/.omp/agent/models.yml` | `~/.omp/agent/.env` (provider `apiKey:` names the var) |
| omo | `~/.omo/agent/models.json` | `~/.omo/agent/auth.json` (same shape as pi) |

`api` values: `openai-completions` (chat), `openai-responses` (the Codex wire — required for models a
gateway does not expose on chat), `anthropic-messages`. Verify a new route with `omp models` / `pi --list-models` and one real `-p` request. Record the model's `--thinking` levels and whether the route
returns `reasoning_content`; a route that only supports chat cannot drive a "responses"-only client.

**Large prompts and long single generations (measured on this machine, 2026-10).** A big prompt goes in as a positional `@file` argument — `pi -p --no-tools --no-skills --model <provider>/<id> --thinking medium -- "@packet.md" "<instruction>"` — an `@path` written inside the instruction text is NOT inlined, and several `@files` inline in argument order; ~150 KB packets work. But a single generation that runs past ~40 minutes can die mid-stream with zero output (`OpenAI Responses stream ended before a terminal response event`); a slow model (e.g. `gpt-6-astra`) then needs the text split into two halves — write half 1 (scoped instruction + a closing marker line), send half 2 as an independent continuation prompt with the half-1 text embedded, stitch and validate — each half completing in ~10–20 min where the single call never finishes. Validate a stitched artifact by content markers (closing section present + a size floor) — and when a batch combo reports failure, read what actually landed on disk before re-generating: a partially-validated attempt can leave a complete stitched file behind. `omp` does NOT take large prompts: it silently truncates a ~150 KB attachment to its first ~300 lines and the model (correctly) refuses; use `pi` for big packets and keep `omp` for small probes.

Sending one frozen prompt to several models and reconciling the disagreements: `references/multi-model-review.md`. Fanning out many generations across models × variants (a draft matrix) with a resumable runner, per-route split mode and receipt discipline: `references/draft-matrix-fanout.md`.

## 6. A shared variable NAME is not one credential

`TENCENT_GLM_API_KEY` held **two different values** on this machine: an `sk-` key for Hermes against
`1.14.219.252`, and a 64-char `hg` key for the pi-family against `svc-bytb2o81`. The shell-exported
value **overrides** a harness's own store, so `omp -p --model tencent-glm/GLM-5.3` returned
`401 status code (no body)` while omp's own key worked (verified: `curl` with the `.env` value → 200,
with the shell value → 401).

Rule: when a pi-family harness must use its own credential, clear the shell variable for that one
invocation (`env -u <VAR> omp …`), or pass `--api-key`. Never copy one harness's value into another's
store. Fingerprint both sides (`len` + `sha256[:12]`) to prove which one you are holding.

**Prove the pairing with a status-only matrix, not by reading values.** For every (store, host) pair,
POST a tiny 16-token probe and print only the HTTP status: `200` = that pair is live, `401` = wrong
pairing. **A `429` is NOT a pairing verdict — it means auth passed** and the gateway is throttling, so
re-probe after a pause instead of concluding the key is wrong. Build the whole matrix before changing
anything; a half-matrix invites "fixing" a working harness.

**Precedence is per harness — verify, do not assume.** The shell export winning over a store is a
property of *that* harness. The tell: a harness run from a login shell that exports the *other* value
still succeeds — it ignores the shell and reads its own store. Establish the precedence empirically for
each harness you touch rather than generalising from one.

**One service can be two hosts with different route maps and different keys.** Same product, two base
URLs: a path that answers `200` on one host returns `404 no Route matched` on the other, and each host
accepts only its own key. Keep them as separate provider entries (named for the host, not just the
service), never copy one host's key to the other, and probe the route map per host — a "the provider
changed endpoint" rotation that keeps both hosts alive is a two-entry job, not a find-and-replace.

## 7. Retire models and persist the result

0. **Removing a provider is not one edit — it has referrers.** Before deleting an entry, grep for it
   and clear every pointer, or the harness fails at run time with a dangling target: Hermes
   `fallback_providers`, MoA/consensus `reference_models`, omp `modelRoles.default`
   (`provider/model:effort`), omo `defaultProvider`/`defaultModel`, dsh-tui `model.json`,
   OpenCode's `~/.local/state/opencode/model.json` recents/favourites/variants, and a Codex
   per-provider profile file. Repoint each to a surviving provider actually used on that harness and
   report the repoint as a behavior change. A whole-file chezmoi-managed config will also revert the
   deletion at the next `chezmoi apply` — refresh its source (`chezmoi add <target>`) in the same pass;
   `modify_` scripts only rewrite their owned providers and preserve the rest.

1. Refresh the upstream catalog and inspect the owner's requested provider scope. An omitted model
   alone is not proof it is unservable; distinguish catalog evidence from a route probe.
2. Remove retired IDs only from that provider's active declarations, aliases and actual catalog
   mirrors; clean matching selection/thinking caches. Retain other providers, historical sessions,
   logs and backups. Remove an emptied provider only after checking default-model references.
3. Filter by model family, not wire protocol: retiring Claude does not retire non-Claude models on
   the Anthropic Messages transport. Validate retained models and unchanged defaults after cleanup.
4. When asked to sync configuration, inspect generator coverage before claiming completion; a clean
   chezmoi status cannot prove an unmanaged harness was captured. Follow
   `references/config-sync.md` for selective, credential-preserving sync and remote verification.

## Pitfalls

1. **A `key_env`/`apiKeyEnv` name is not a credential.** It names a variable that EACH harness
   resolves from its own store. Writing the value into the root `.env` (or any single store) leaves
   every other harness unauthenticated while its config looks correct. Count the stores, not the
   env-var names.
2. **A provider entry and a same-named model alias are two independent records** with two base URLs.
   A user alias is resolved before the built-in table and outranks the provider for `/model`, so an
   alias left on the old URL breaks `/model <alias>` with no warning while `--provider <name>` works
   fine. Grep for both and keep them on the same URL.
3. **Hermes never appends `/v1`** — it posts to `{api}/chat/completions`. The stored URL must carry
   whatever prefix the gateway mounts the service under. A URL missing it answers an app-level
   `404 {"detail":"Not Found"}` that looks like a dead endpoint but is a client-side URL error.
4. **Codex ≥ 0.157 rejects `wire_api = "chat"`** — only the responses wire is accepted, so a
   chat-only gateway cannot drive Codex at all. Probe `/v1/responses` yourself rather than trusting a
   note that says it is unsupported; the route can be added upstream without the note changing.
5. **When EVERY model fails identically, suspect a tool schema or plugin, not the provider.** A tool
   whose JSON schema uses a non-standard keyword (for example `"optional"` on a property) makes each
   request fail before routing, with the upstream quoting the tool name. Isolate by running the same
   harness with plugins dropped from a throwaway config dir before you touch provider config.
6. **A credential store can be the wrong channel.** Some harnesses only inject their credential file
   into the process environment for specific entry points, so a byte-correct entry still 401s. If a
   harness rejects a key that a direct `curl` to the same URL accepts with the identical value, put
   the variable in the process environment as well and keep both stores updated.
7. **Config comments and earlier notes are claims, not evidence.** "Host X is retired", "route Y is
   not supported" — both can be stale in either direction. A "retired" host that still answers `200`
   with its old key is a working fallback, not litter. Verify before deleting an entry or repeating
   the claim to the owner.
8. **Secret hygiene.** Never print a value or paste it into the transcript. Load it into a shell
   variable, pipe every output line through `sed -e "s/$KEY/<KEY>/g"`, and show the owner only a
   fingerprint (length + `first6…last4` + `sha256[:12]`) so they can confirm it without it entering
   the log. `opencode service get` prints every service env value in CLEARTEXT — never run it
   unredacted (pipe through a redactor, or use `opencode service get | sed` before it reaches the
   transcript). Writing to a credential store is an owner-approval action — when in doubt, hand over
   the exact line to add. **Error receipts are a second leak surface:** a credential failure can dump
   the live key into a `.err`/log receipt (pi prints `key: "sk-…"` on credential-sync errors).
   Before committing or sharing a receipt directory, scan with a length-thresholded pattern
   (`sk-[A-Za-z0-9_\-]{20,}` — a loose `sk-` pattern false-positives on ordinary text such as
   contract IDs), redact by blind regex replace of the value span without reading it
   (`(key:\s*")[^"]*(")` → `«redacted»`), and verify by counting pattern hits before/after —
   counts only, never the value.
9. **Smoke tests can persist model preferences even with `--no-session`.** Snapshot launch defaults
   and per-model thinking caches before one-shots. Remove only test-created cache entries afterwards
   (backup + surgical diff), so a low-effort connectivity probe does not become the owner's future
   model preference. Do not revert unrelated concurrent changes.
10. **Say when it takes effect.** Hermes config lands in a NEW session (or after a gateway restart);
   other harnesses pick it up on next start. Return the backup paths with the result, and never
   report a rotation complete on the strength of a config read alone.
11. **OpenCode's Zen/Go *free tier* accepts only the OpenCode client.** Raw HTTP and other harnesses
   (`pi`, curl) get `403 FreeTierError: OpenCode's free tier can only be used from within OpenCode`.
   Route free-tier model ids through the `opencode` / `opencode2` CLI. Two traps: (a) placing any
   `opencode.json` in the run directory — or invoking a non-default agent (`--agent <name>`) — flips
   the **entire** free tier to `403`; the default agent in a clean directory is the only path that
   passes, so a *tool-less* request cannot be sent (which is why free models that reject the client's
   tool schema, e.g. an upstream `400 Invalid JSON schema` quoting a tool keyword, are unusable from
   the CLI even though they are listed); (b) the `400`/schema failures are per-model upstream, not
   provider misconfig — sibling models on the same
   tier work, so it does not mean the tier is down. Free-tier ids also drift (`410 ModelDeprecated`)
   without leaving the catalog, so probe the id before wiring it. Replicating the client's request
   headers (`x-opencode-client: cli`, `x-opencode-project`, session ids, the `opencode/latest/x/cli`
   UA) does NOT defeat the gate — verified with both the Go API key and the `opencode` OAuth access
   token. `/zen/v1/models` answers 200 over plain HTTP, but chat/completions for `-free` ids answers
   `403 FreeTierError`; free-tier ids therefore cannot be routed through a generic OpenAI-compatible
   provider entry — drive them through the OpenCode CLI (`opencode` / `opencode2`). Free-tier ids also **throttle under concurrent batch use**: several simultaneous free-tier generations fail fast (`rc=1`, empty output, a `Rate limit exceeded` line on stderr) — the tier limits before it generates. In batch runs, route free-tier ids through their own serial queue: one call at a time, tens of seconds of pacing between calls, and backoff-retry cycles (~20 min) on the rate-limit string. A serial salvage pass recovers the combos a concurrent run lost; do not diagnose throttle failures as schema or route problems.

12. **Concrete case for pitfall 5 — `@prevalentware/opencode-goal-plugin` breaks EVERY id, paid included, until the config dir is clean.** With the plugin loaded, `update_goal_plan`'s schema carries a non-standard `"optional"` keyword and the upstream rejects the whole request (`400 Invalid schema for function 'update_goal_plan'`) for paid ids too, not just free ones. Workaround verified for both tiers: `XDG_CONFIG_HOME=<empty dir> opencode run --standalone -m <provider>/<id> --file <prompt> "<msg>"` from a cwd with no `opencode.json`. Note headless `opencode run` keeps its tools enabled — a model may spontaneously read repo files beyond the attachment; log that as a process note in the run receipt, not a failure.

13. **Batch-route failures come in three layers — the stderr line names the remedy.**
   `Rate limit exceeded` = tier throttling → pace, serialize, back off (pitfall 11).
   `Model unavailable` / `Upstream request failed: Model is unavailable.` while sibling ids on the
   same tier still answer = the model itself is down upstream; retries cannot succeed → leave a tiny
   timed probe (watcher) and run the leftover work on recovery. A `400` quoting a tool/schema keyword
   = plugin/config (pitfall 12). Before declaring a model unreachable, enumerate its sibling routes:
   one id can sit on several routes/tiers with **independent quotas** (`opencode models` /
   `pi --list-models`; free `opencode/<id>` vs paid `opencode-go/<id>`) — the paid sibling can carry
   a batch the free tier throttles for hours.

14. **Proxy-side one-shot tooling needs the id pinned and the budget declared.** `400 The selected
   model could not be resolved` means the requested id is not in that proxy's catalog right now —
   enumerate it (`curl -sS http://127.0.0.1:4141/v1/models -H 'authorization: Bearer dummy'`) and
   pass a listed id instead of trusting a documented default, which drifts between proxies and
   releases. Long or comparative prompts also need an explicit budget: driving the `ghc-search`
   script (skill `ghc-search`) against this proxy, use `--max-tokens 8000 --timeout 300` — a small
   token budget surfaces as `no 'message' item in response output` rather than a truncation warning,
   and the default request timeout expires mid-call on high-effort multi-part questions. Run
   independent prompts in parallel threads and write each answer to its own file: one answer is
   6–20k chars, so a dozen inline exhausts the context before any synthesis begins.
15. **`--no-tools` disables execution, not the model's attempt to call tools.** A model given a prompt
   that reads like an agent task can stream its tool-call template
   (`<|open|>tools … call tool=…`) into the answer with exit 0 — the CLI succeeds, the output is
   garbage. (Observed on `KimiK3`, retired 2026-11-13; treat the behaviour as a class, not one id.)
   Fix verified: prepend one explicit line ("You have NO tools in this session. Do NOT
   emit tool calls. Answer directly.") and rerun; treat any `call tool` string in the output as a
   retry signal, not as an answer. Also re-run §1's enumeration before quoting §5's commands:
   on this machine `pi`/`omp` are off PATH and the reachable family binary is `~/.bun/bin/omo`.

   **Same defect, silent variant (verified 2026-11-12 on `tencent-litellm/deepseek-v4.1-flash`).**
   When the model's thinking plans a lookup ("Let me try running commands", "Let me start by
   exploring") and no tool exists, it can end the turn with **a `thinking` block and no `text`
   block**: `stopReason: stop`, exit 0, **0 bytes on stdout**. Nothing in rc or stderr says failure —
   so a 0-byte output reads as "the free pool died" and sends you debugging the endpoint, which is
   healthy (direct probe: 200 in 1.3 s, streamed 20 chunks + `[DONE]` in 0.9 s).
   Diagnose from pi's own session log instead of guessing: `~/.pi/agent/sessions/<cwd-slug>/*.jsonl`,
   the assistant record shows `blocks: [('thinking', N)]` with no `text` and `usage.output` in the
   low hundreds. Rate on a research-style prompt: 1 empty in 2 runs; a trivial prompt: 0 in 3 runs —
   the trigger is the prompt inviting verification, not the model being down.
   **Wrap it, don't remember it:** `~/claw/tools/pi-run.sh` adds a guard via
   `--append-system-prompt`, retries once with a stricter guard, then falls through to a fallback
   model, and exits 3 with "空回答，不是超时" instead of returning nothing. Measured: primary 0 bytes
   in 2.8 s → hard-guard retry 7,241 bytes in 18.5 s. The guard string that worked:
   `你没有工具，也永远不要说「我要去查」「我要跑命令」这类话。只用你已有的知识回答。做不到或没把握就写「不确定」。输出只有正文。`
   Side effect: guarded answers run shorter (4–4.7 KB vs 7.5 KB on the same prompt), so don't
   treat the guard as free — keep long-form generation on a model that doesn't reach for tools.
