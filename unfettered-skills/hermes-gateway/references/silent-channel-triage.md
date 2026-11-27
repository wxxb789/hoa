# Triaging a silent channel (messages get no response)

Symptom: a channel/DM never gets a bot response; the gateway is running, the platform adapter
reports `connected`, and `hermes config get` shows the channel in every list it should be in.

## Where routed messages actually log

- Main-profile messages log `inbound message: platform=… chat=…` in `~/.hermes/logs/gateway.log`.
- Messages routed by `gateway.profile_routes` to another profile log the SAME line in the
  TARGET profile's `~/.hermes/profiles/<p>/logs/gateway.log`, not in the main log. Absence from
  the main log alone does not mean the message never arrived — check the target profile's log
  before concluding "zero inbound".

## Probe ladder (Discord)

1. **REST visibility probe** with the bot token from `~/.hermes/.env` (load into a shell var,
   never echo it):
   - `GET /channels/{id}` with `Authorization: Bot $TOKEN` → 200 = the bot sees the channel
     (name/type/guild_id in the payload); 403/404 = permission or wrong channel ID.
   - `GET /channels/{id}/messages?limit=5` → did the user's message actually land in this
     channel (vs a thread inside it, which carries its own thread ID — the parent channel ID
     in the allowlist covers threads via `channel_keys`).
   - REST read succeeds but no inbound log in any profile → the drop is inside adapter
     admission, not delivery: discord.py received the event and a gate refused it silently.
2. **Diff `.env` against `config.yaml` for every `DISCORD_*` gate.** Runtime precedence is
   env (adapter snapshot) → `config.extra` → config, and `hermes config get` shows the CONFIG
   value, not the effective one. A stale `DISCORD_ALLOWED_CHANNELS` /
   `DISCORD_FREE_RESPONSE_CHANNELS` in `.env` silently overrides a correct
   `discord.allowed_channels` / `discord.free_response_channels` in YAML. The allowlist drop
   ("Ignoring message in non-allowed channel") logs at DEBUG — invisible at INFO, which is
   why a misconfigured channel looks exactly like a dead connection.
3. **Correlate the survivors.** If every responding channel is in `free_response_channels` and
   the silent one is not, suspect the mention-gating path even when `require_mention: false`
   reads correctly — first re-check step 2 for `DISCORD_REQUIRE_MENTION` /
   `DISCORD_IGNORE_NO_MENTION` overrides before assuming a code-level bug.

## Fix shape

- Keep `.env` and `config.yaml` in sync for the same gate (edit BOTH `DISCORD_ALLOWED_CHANNELS`
  and `DISCORD_FREE_RESPONSE_CHANNELS` when adding a channel); backup first, show the diff.
- Adapters snapshot gate env at `connect()`, so the fix needs a gateway restart (restart
  discipline in SKILL.md) to go live.

## Which "not allowed" notice fired

- `此机器人为私有…hermes pairing approve <platform> <request-id>`
  (`gateway.unauthorized.action_notice`) is the reply to an unauthorized **slash command** —
  slash has its own `DISCORD_ALLOWED_CHANNELS` check, separate from text-message admission. Do
  not chase `hermes pairing list` / pairing stores (they stay empty) when the trigger was a slash
  command; fix the channel gate and have the owner retry with plain text.
- `/proc/<gateway-pid>/environ` cannot verify dotenv-loaded gates — it shows only exec-time env.
  The only real verification of a gate-env fix is a live test message on the new process.

## Live test message etiquette

- Ask the owner to send one test message, then grep the logs afterwards — the log IS the
  record. Do not set up a `timeout N tail -f | grep …` trace to catch it: the trace expires
  before the owner replies and adds nothing over a post-hoc grep.
