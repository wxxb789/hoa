# hermes-models — case notes

Compressed case notes: signal, cause, fix, proof — 5–8 lines each. The rules live in `SKILL.md`;
treat these commands as leads to re-verify against the current build.

## Fallback cleanup after a vendor deprecation

- **Signal**: a vendor retired fallback slugs (`*-1m`, `*-internal`, a small GPT tier) while aliases
  and cache entries kept pointing at them.
- **Places**: `config.yaml` (`model_aliases.*`, fallback chains) and `context_length_cache.yaml`; only
  for source maintenance, `hermes_cli/setup.py::_DEFAULT_PROVIDER_MODELS["<vendor>"]` +
  `hermes_cli/models.py::_PROVIDER_MODELS["<vendor>"]`.
- **Workflow**: back up → patch the default profile only (other profiles are a separate scope) →
  re-point fallbacks at a kept id → refresh context lengths → `hermes config check` + the
  model-validation pytest.
- **Pitfall**: live `/models` keeps serving retired ids for a while; follow the owner-confirmed set.
  An undeclared id resolves its context to the fallback window (272k in one observation), not its
  real window.
- **Rule**: if a model family is unavailable on the account, do not add an alias, provider entry or
  fallback for it without re-probing the endpoint.

## ghc-proxy systemd user service

- **Setup**: `bunx ghc-proxy@latest auth` once →
  `~/.config/systemd/user/ghc-proxy.service`
  (`ExecStart=… bunx ghc-proxy@latest start --wait --upstream-timeout 1800`, `Restart=on-failure`) →
  `daemon-reload && enable --now`; daily restart via `ghc-proxy-restart.timer` at a chosen hour
  (`Persistent=true`). Unit template: `templates/ghc-proxy.service`.
- **Port exposure**: by default the proxy binds `*:<port>` with no `--host` (ghc-proxy's default is
  4141; substitute the configured port); block outside traffic
  (`iptables -I INPUT 1 -i lo -p tcp --dport <port> -j ACCEPT`, then `-j DROP`).
  `iptables-persistent` can evict `ufw` — use a oneshot rule restore if ufw is live.
- **Probe the right path**: `curl -s -i <proxy-base>/v1/models` → 200. Bare curl on
  `/api/v1/models` returns an instant 500 `NOT_FOUND` from local routing: wrong path, not a dead
  proxy; the proxy log showing real 200s is ground truth.
- **Cold start**: `--wait` re-resolves deps, so the first 3–5 s can look broken; poll until
  `Listening on <proxy-base>` or `/v1/models` returns 200.
- **Throughput**: add `--idle-timeout=255 --upstream-queue-concurrency 50` to `ExecStart`, back the
  unit up first, then confirm with `systemctl --user show ghc-proxy.service -p ExecStart`.
