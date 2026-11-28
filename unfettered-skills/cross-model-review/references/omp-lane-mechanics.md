# OMP lane mechanics for cross-model review

Runner-specific facts needed to launch, probe and diagnose review lanes with `omp -p`. Keep the
methodology in SKILL.md; this file is the plumbing.

## Launch

- The maintained launcher is `gdd/scripts/adapters/omp-run.sh`; the copy in
  `omp-headless-orchestration` is a forwarder that resolves it as a *sibling directory*. With skills
  installed under category folders the forwarder misses and exits 127 before any run starts — call the
  absolute launcher path or export `OMP_RUN_SH` to it.
- Export `OMP_BIN` to the real binary. A non-interactive shell has no package-manager shim on `PATH`,
  so bare `omp` resolves to nothing while the install is healthy (mise installs live under
  `~/.local/share/mise/installs/oh-my-pi/<version>/omp`).
- Model flag takes `provider/model` (e.g. `tencent-litellm/GLM-5.3`). Thinking effort is per provider:
  pass it explicitly, do not inherit a default.
- `--max-time` accepts one unit only (`45m`, `2h`), never `1h30m`.

## Per-lane concurrency

There is no `--concurrency` flag. The config key is `task.maxConcurrency`, supplied as an overlay file:

```yaml
# lane.yml
task:
  maxConcurrency: 8
```

```bash
omp-run.sh start --name lane-a --prompt a.md --model tencent-litellm/GLM-5.3 \
  --extra "--config /abs/lane.yml" --max-time 45m
```

The launcher word-splits `--extra`, so quoting survives. Size each lane to its provider: a wide fan-out
on a proxy that rate-limits produces retry storms that look like model failure.

## Probing a lane

- Liveness: `state.json` → `state`, then count event types in `events.ndjson`. Never `tail` it — each
  event embeds full sub-agent prompts.
- Healthy: `turn_start` ≥ 3 with `tool_execution_start` ≥ 1.
- Suspect: `tool_execution_start` = 0 while `auto_retry_start` climbs. Read the first
  `auto_retry_start.errorMessage`; retries are capped (~10) and each may add minutes of backoff.
- Counting `grep -c 429` on the event log is unreliable — the literal appears inside files the agent
  read. Count retry events by type instead.

## Confirming a model alias / provider health

`omp models find <pattern>` prints the provider groups that carry a matching model; `omp models`
alone is not a search. A model the proxy serves may be registered under a provider id that does not
match the proxy's name — the same family is split across `ghc-proxy` and `ghc-proxy-chat`, and
`--model ghc-proxy/<id>` fails with `Model ... not found` for a model that lives in `ghc-proxy-chat`.
Launch with `<provider>/<model>` exactly as the table lists it. When a model is missing, read the
table before the config; when it is present but the completion 5xxes, verify against the provider
directly:

```bash
curl -s "$BASE/v1/models" -H "Authorization: Bearer $KEY" \
  | python3 -c "import json,sys;print([m['id'] for m in json.load(sys.stdin)['data']])"

curl -s -o /tmp/probe.json -w '%{http_code}\n' "$BASE/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"<alias>","messages":[{"role":"user","content":"OK"}],"max_tokens":8}'
```

Interpretation: alias present in `/v1/models` + 5xx on the completion + a sibling model answering on the
same key ⇒ that model group is unavailable upstream. Alias absent ⇒ configuration. Either way, stop the
retry churn and tell the operator which of the two it is.

## Dead lane: the pane is gone but `state.json` still says `running`

`tmux has-session` false + `state.json` state `running` with no `pid` + an event log that stops
mid-`message_update` + `stderr.log` ending in `EPIPE: broken pipe, write` = the CLI died writing to a
closed stdout, so the launcher's finalize never ran. `status` keeps reporting a live lane and nothing
will ever change it; waiting is the expensive mistake. Recover in three steps:

1. `python3 <run>/finalize.py <run> -1` — writes `failed`, the real duration and cost into `state.json`
   and the ledger, so the run stops lying.
2. `git -C <repo> branch --show-current` and `git status --porcelain` — the lane may have died mid-edit;
   know what it left before resuming.
3. Resume the same session (`--resume <session-id>`) with a continuation prompt that says the process
   died and what state the tree is in, and that splits the remaining work into several smaller commits.
   Splitting a large reshape into move → compress → reconcile commits is what makes a killed run
   resumable at all; one giant commit is lost work.

## Degraded lane

Park, do not kill: the session survives and resumes if the provider returns. Kill only when the
substitution is decided, and record in the report header which model actually produced which lane.
