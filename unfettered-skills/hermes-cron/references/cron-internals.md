# Cron internals and script pitfalls


## Cron scripting pitfall

Hermes cron `script` paths are relative to `~/.hermes/scripts/`. Put scripts there and pass only the filename, e.g. `owner-cockpit.py` or `impact-weekly-seed.py`. Absolute or `~` paths are rejected.

For `no_agent=True` cron watchdogs, stdout is delivered verbatim to the owner. Healthy checks must print nothing. Do not print optional dependency/setup diagnostics such as `psutil import failed`; silently degrade or use a fallback and reserve stdout for actionable alerts. For Linux process watchdogs, `/proc` is a good fallback for basic RSS scanning. See `cases.md#cron-no-agent-watchdog-silent-dependency-fallback`.

### Restart-safe cron worker dies without the runtime env (PM-toolchain installs)

Symptom: every script-mode cron job fails with
`Restart-safe cron worker dispatch failed: cron external worker exited before ownership acknowledgement (exit 1)`,
the worker stderr ending in `ModuleNotFoundError: No module named 'ruamel'` (or any other third-party dep), and the
result is not delivered (`could not read this profile's MATRIX_HOME_ROOM`). The gateway itself is active and fine,
and `hermes cron run <id>` from the CLI **succeeds** — that path executes in-process and proves nothing about the
worker. Blast radius is every cron job in a managed systemd gateway, not just the script ones.

Cause: on installs whose deps live in a PM environment venv (`~/.hermes/installs/<id>/environments/<hash>/venv`),
the gateway's own interpreter gets them injected at startup, while `cron/scheduler.py::_launch_external_cron_worker`
spawns the worker as `sys.executable -m cron.scheduler` — `sys.executable` being the bare PM *toolchain* python —
with `build_subprocess_env()`, which strips Hermes-owned PYTHONPATH entries and the venv marker vars.
`cron/scheduler_worker_env.py` pins only the repo root (fix for #112729) and `cron.scheduler` has no bootstrap, so
every third-party import fails before the job starts.

Diagnose (cheapest first):
1. `hermes cron list --all` — `error: Restart-safe cron worker dispatch failed` on every script job, with a
   consecutive-failure count.
2. `journalctl --user -u hermes-gateway --since ... | grep -A15 'external worker'` — the traceback names the module.
3. `ls ~/.hermes/cron/external-workers/*.stderr` — one traceback per failed execution.
4. Confirm the interpreter split: `sys.executable` for the worker is the toolchain python, and that python cannot
   `import ruamel.yaml` while the env venv python can.

Fix layers: no config knob disables external workers in managed topology. Do **not** patch Hermes source for this —
a local source edit leaves a dirty tree and the unattended updater fails closed. The durable fix is upstream
(`pin_hermes_tree_on_pythonpath` should also pin `pm.environments.site_packages(selected_venv(repo_root))`).

**Applied local fix (2026-09-28, verified):** the toolchain interpreter shim —
`~/.hermes/lib/hermes_toolchain_env.py` (resolves the *current* PM selection at import time) + a one-line
`.pth` in `<toolchain>/lib/python3.14/site-packages/`, installed/checked by
`~/.hermes/scripts/hermes-toolchain-shim.py` (`--check` is silent when healthy and exercises the worker's real
bootstrap). It survives environment rebuilds (new generation hash) but NOT a new toolchain version directory,
so `hermes-auto-update.py` re-applies it on both the update and already-current paths and
`post-update-check.py` has a `cron worker python env` check. Full record + rollback: `~/.hermes/LOCAL_OVERRIDES.md`.

Related trap in the same area: `python3`/`python` on PATH for a Hermes session is the PM toolchain interpreter
and has no third-party packages, so maintainer scripts that shell out to bare `python`/`python3` report false
failures (`No module named 'yaml'`). Resolve an interpreter that can import the deps instead (`sys.executable`
if capable, else `pm.environments.selected_venv(repo)/bin/python`).

## Agent cron fails before gateway admission

`GatewayClientError: Gateway connection failed; no local fallback` does not by itself prove a broken
model/provider or scheduler. `connect_gateway()` wraps OSError/TimeoutError over the entire connection
context. Check the causal timeline before changing config: worker dispatch, WS acceptance/ready,
event-loop stalls, admission receipt, and agent/API start.

A first `/api/ws` request can cold-import `tui_gateway.ws` / Pydantic contracts on the gateway loop;
a >10s import stalls the handshake, then the peer arrives after the client timed out (`ready_send_failed`,
zero messages). If the failure is confirmed BEFORE submit/admission, rerun the exact existing job once
and verify its durable execution row, output, failure_streak reset, and actual memory-store changes.
Keep the incident history. If admission is unknown or an admission journal exists, reconcile that fire
instead of blindly rerunning; otherwise the same memory work can execute twice.

A recovered manual run proves payload/transport, not the next scheduled fire. Report that boundary,
retain the schedule, and use existing scheduled worker evidence for scheduler liveness. Do not invent
a permanent script/config defect or widen timeouts merely to turn a transient failure into a patch.

## External liveness watchdog (cron cannot report its own death)

`~/.hermes/cron/ticker_heartbeat` holds `<epoch> <gateway-pid>` and is rewritten every tick. When the
ticker stops, every job stops, and that silence is indistinguishable from "everything is healthy". Any
check running *inside* cron inherits the blindness, so liveness must be driven from outside the
scheduler — a systemd user timer, not another job.

- `~/.config/systemd/user/hermes-cron-watchdog.service`: `Type=oneshot`,
  `ExecStart=/bin/bash %h/.hermes/scripts/cron-ticker-watchdog.sh`.
- `~/.config/systemd/user/hermes-cron-watchdog.timer`: `OnBootSec=5min`, `OnUnitActiveSec=15min`,
  `WantedBy=timers.target`.
- `systemctl --user enable --now hermes-cron-watchdog.timer`; confirm
  `loginctl show-user $USER -p Linger` is `yes`, otherwise the timer dies with the login session.

The script compares `now - heartbeat` against 3× the tick interval (15 min for a ~10 s ticker), stores
`down|up` in `~/.hermes/cache/ticker-watchdog.state`, and prints only on a transition (one alert, one
recovery) so a long outage is not a message per run. Deliver with
`hermes send -t discord:<chat_id>`: it reads the platform credentials directly and needs **no running
gateway** for bot-token platforms (Discord/Telegram/Slack/Signal) — exactly the state being reported.
Keep the script exit-0 and prove it with a temporary heartbeat path plus a `--dry-run` flag before
installing the unit; a watchdog that needs the thing it watches is not a watchdog.
