# hermes-gateway — case notes

Compressed case notes: signal, cause, fix, proof — 5–8 lines each. The rules live in `SKILL.md`;
treat these commands as leads to re-verify against the current build.

## Discord token lock and WebUI sidecar

- **Signal**: `hermes gateway status --deep` → `discord: Discord bot token already in use (PID 3066351)`; that PID was dead (`/proc/<pid>` missing) and every `profiles/*/gateway.lock` named a dead `hermes gateway restart` process.
- **Diagnose**: `grep -iE 'discord|token already in use|failed to connect' ~/.hermes/logs/gateway.log | tail -80`; `ps -fp <pid>` + `test -d /proc/<pid>`; dump `.hermes/**/gateway.lock` (pid/kind/argv, never secrets).
- **Fix**: back up, move *only* locks whose PID is gone into `~/.hermes/backups/gateway-locks-<ts>/`, keep the live root lock, `hermes gateway restart`, re-check `--deep`.
- **WebUI sidecar**: real `HERMES_HOME=~/.hermes` + `HERMES_WEBUI_STATE_DIR=~/claw/hermes-webui-state`, bound to `127.0.0.1:8787` — config/model access without writing state into `~/.hermes/webui`.
- **Don't confuse**: `Maximum number of application commands reached (100)` is the slash-command quota — it breaks sync, never the connection.

## Channel and persona overlays

- **Question**: can one agent behave differently per channel (e.g. Feishu) without forking its identity?
- **Layers**: `SOUL.md` (identity) → `AGENTS.md` (protocol) → profile (state isolation) → `gateway.platform_prompts.<platform>` → `gateway.channel_prompts.<platform>.<chat_id>`; `gateway/run.py` appends both to `ephemeral_system_prompt`.
- **Rule**: identity is profile-level, per-channel behaviour is an overlay. No per-channel `SOUL.md` copies, no channel rules in global `agent.system_prompt`.
- **Separate profile** only when state must diverge: `hermes profile create feishu --clone` → edit that profile's `SOUL.md`.
- **Cache**: the overlay text belongs in the agent cache signature — it changes prompt content.

## Multiplex gateway rollout

- **Order**: upgrade first (the flag may exist only on newer `main`) → minimal backup (`config.yaml`, `.env` 0600, `profiles/*/config.yaml`, `git rev-parse HEAD`) — never tar whole profile dirs (state/cache) → `hermes profile list` + per-profile `.env` → `hermes config set gateway.multiplex_profiles true`.
- **Duplicate tokens**: cloned profiles carry the same `DISCORD_BOT_TOKEN`; multiplex fails closed, so disable the duplicate adapter first: `hermes --profile <name> config set discord.enabled false`.
- **Restart from outside**: a chat turn runs inside the gateway, so `systemctl --user restart hermes-gateway` from that turn kills itself. Use `systemd-run --user --on-active=40s … gateway-restart-verify.py` and let the unit verify.
- **Verify**: `gateway_state.json` (`pid` == new MainPID, `code_sha`, per-platform state), `runtime_status.json.served_profiles`, and `journalctl --user -u hermes-gateway -n 160 | grep -Ei 'multiplex|conflict|Discord bot token|connected'`.
