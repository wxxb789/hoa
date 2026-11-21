# Model-generation harness for contract-bound drafting

Depth for step 3b. The project's own harness (`DELIVERABLE_HARNESS_DIR`, default `<project>/.harness`)
ships a draft CLI and a providers module; read those for the current per-transport header quirks
rather than re-deriving them. This file carries the parts that are easy to get wrong.

## Provider registry entry

```json
"<registry-key>": {
  "base": "<full endpoint URL, e.g. <proxy-base>/v1/chat/completions>",
  "model": "<provider model id>",
  "slug": "<filename-safe tag>",
  "cap": 20000,
  "transport": "chat" | "responses",
  "key_env": "NAME_OF_ENV_VAR"        // never an inline secret
}
```

- `slug` becomes the draft filename tag (`draft-<tag>-<slug>.md`); make it provider+model
  unambiguous.
- Two entry styles: a local proxy model carries a local key default; a remote named-gateway model
  carries `key_env`.
- Read the env var the registry names (the project's `.env`, or the agent's env file) without
  printing its value.

## Transports

- `responses` (`/v1/responses`): reasoning via `reasoning.effort`, budget via `max_output_tokens`.
- `chat` (`/v1/chat/completions`): reasoning via `reasoning_effort`, budget via `max_tokens` — the
  reasoning budget is charged against it. Some gateways additionally require a session header and a
  browser User-Agent; the harness module documents which.
- Token-cap pitfall: a large `max_tokens` trips HTTP 504 on remote gateways; a cap around
  `DELIVERABLE_DRAFT_TOKEN_CAP` (default `16000`) is a known-good starting point. Retry a failed call
  with a lower cap before concluding the model failed.
- **The long write must stream.** A non-streaming reasoning write can sit silent past the client read
  timeout and die with a bare read timeout and no terminal text — the failure is an empty response,
  not an HTTP error, so lowering `max_tokens` does not save it. Send `"stream": true`, read the SSE
  `data:` lines, and accumulate `choices[0].delta.content` (count `delta.reasoning_content` for
  progress). A stream keeps emitting chunks through the silent reasoning phase, so the per-read idle
  timeout is never reached: use an *idle* timeout
  (`DELIVERABLE_STREAM_IDLE_TIMEOUT_S`, default `300`), not a total-call timeout, and make streaming
  the default for the long write call.
- Read the final chunk's `finish_reason`: `stop` = complete, `length` = truncated (raise the cap or
  split the write into two parts). When a non-streaming attempt times out, save a failed-attempt
  receipt before retrying so the round keeps its audit trail.

## Identity / effort preflight receipt

One small request per new model; keep the receipt with the round. Fields:
`requested_model`, `returned_model`, `transport`, `effort_requested`, `ok`, `response_text`
(echo a fixed token), `elapsed_s`, `usage.reasoning_tokens`, and a caveat that an accepted high
request is not independently observable provider-internal effort.

## Two-phase learn → write (stateless transport)

Build the message array explicitly; nothing is remembered between requests.

```
call 1: [ system(role) , user(learn-instruction + FULL packet) ]
call 2: [ system , user(learn-instruction + FULL packet) ,
          assistant(learn reply) , user(write-instruction) ]
```

- The write-instruction is the frozen prompt template with its `{packet}` body already supplied by
  the preceding user turn (do not append a second copy of the packet).
- The learn reply should restate the causal chain, per-section budgets, the evidence ceilings, and
  the citation rules — inspect it before spending a write call: a learn reply that misses a ceiling
  predicts a write that breaks it.
- Keep the raw output as a generation receipt (`generation/draft-<tag>-generation<NN>-<slug>.md`
  plus a `.meta.json`), and copy the accepted manuscript to its project-root name separately.

## Generator script rules

- Standard library only; no shared mutable client.
- Wrap the call in a retry that lowers the token cap on HTTP 504 (see transport pitfall), and stream
  the long write so a long silent reasoning phase cannot trip the read timeout.
- A reasoning-heavy write can run many minutes: launch it as a background job with completion
  notification and poll, rather than blocking the turn; save each phase's receipt as it completes so
  a later failure does not lose the learn output.
- After it returns, verify the contract metric (Unicode length range, every citation marker present,
  section count) with the project's own measuring script — never a private reimplementation.

### 3b. Adding a model that is not in the frozen registry

The owner will name a model to add to the comparison. Route it through the project's own registry;
never silently substitute a reachable model for the named one, and never hand-write "that model's"
draft yourself.

- **A new model needs a new versioned registry, not an edit to the frozen one.** Copy the project
  registry to `providers-vN+1.json`, add the entry, and leave the previous version file intact — the
  earlier drafts must stay reproducible against the registry that produced them.
- **Resolve the model→gateway mapping from the agent config before pronouncing a model unavailable.**
  The agent config (`DELIVERABLE_AGENT_CONFIG`, default `$XDG_CONFIG_HOME/<agent>/config.yaml`) may
  expose a named provider (with a `key_env`) that is absent from the local proxy's `/v1/models`
  list — a missing proxy listing means "not on the proxy", not "unavailable". Registry entries carry
  `key_env` (an environment-variable *name*), never an inline secret.
- **Run and keep an identity/effort preflight for every newly added model.** Send a trivial request
  at `effort=high`, and record the returned model id, whether the effort field was accepted, and
  reasoning tokens > 0; also record the standing caveat that the gateway echoing your request is not
  proof of the provider's internal effort mapping.
- **For "learn the context first, then write", use a multi-turn call.** These transports are
  stateless single-request endpoints: re-send the full frozen packet in *each* call's message array
  and carry the model's learn reply as the preceding assistant turn. A separate one-shot "learn"
  call that is not carried into the write call teaches the model nothing.
- **Label provenance when the only available path is direct authoring.** If the named model cannot
  be reached and you write the draft yourself, name the file for the real author and mark it
  direct-authored (no generation receipt) — never file your own prose under the requested model's
  name.
