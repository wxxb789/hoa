# Messaging channels and delivery targets


## Gateway home channel / default delivery target

"Home channel" = where cron results and proactive notifications land by default. It is platform-specific:

- **Feishu / Lark:** set `FEISHU_HOME_CHANNEL=<chat_id>` in `.env` (NOT `FEISHU_HOME_CHAT_ID` — that key does not exist; verify against the official docs page before guessing). The chat id is the `oc_...` (or `ou_...` for DM) value; the current DM's chat id is surfaced in the gateway session context. Cron delivery reads this var through the **job-owning profile's** secret scope, so a value that must serve profile-owned jobs belongs in that profile's `.env` too (see the cron health audit section).
- The authoritative env-var names live at `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/<platform>/`. Always confirm the exact key there rather than inventing a plausible-looking one.

Two distinct meanings of "home channel" the owner may conflate — disambiguate before acting:

1. **Per-job cron/notification delivery** — needs NO config change. Create the job from the target chat and leave `deliver` empty (resolves to origin), or pass `deliver=<platform>:<chat_id>` explicitly.
2. **Global gateway default** — set the platform's `*_HOME_CHANNEL` env var so ALL proactive output defaults to that chat. This is the `.env` edit above and needs a gateway restart.

Verification: after restart, create a one-shot cron with empty `deliver` and confirm the message lands in the intended chat (not the previous home channel).

## Discord slash command limit

If Discord logs show:

`Maximum number of application commands reached (100)`

then Hermes is trying to sync too many global slash commands. Recommended remediation order:

1. Short-term: disable or reduce Discord slash command syncing if text commands are acceptable.
2. Medium-term: keep only core slash commands and rely on `/help` or normal message commands for the rest.
3. Long-term: consolidate commands into a single grouped command such as `/hermes <command> <args>` plus `/skill`, instead of registering every command globally.

Do not frame this as Discord or Hermes being permanently broken; it is an application-command quota/registration design issue.

## Discord token lock false-positive after gateway/profile restart

If Discord channel delivery is broken but `hermes gateway status` says the user gateway service is running, check whether Discord failed to connect rather than assuming channel permissions are wrong.

Key signature:

`Discord bot token already in use (PID <pid>). Stop the other gateway first.`

Diagnostic pattern:

1. Run `hermes gateway status --deep` and inspect recent gateway health.
2. Check the alleged owner PID with `ps -fp <pid>` and `/proc/<pid>`.
3. Inspect non-secret gateway lock files:
   - `~/.hermes/gateway.lock`
   - `~/.hermes/profiles/*/gateway.lock`
   - `~/.local/state/hermes/gateway-locks/` if present
4. If the lock owner PID is dead, treat it as stale state from a profile/gateway restart handoff, not as a real second bot process.
5. Back up stale lock files before moving/removing them, then restart gateway and verify Discord connection.

Safe remediation shape:

```bash
backup="$HOME/.hermes/backups/gateway-locks-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
for f in "$HOME"/.hermes/profiles/*/gateway.lock; do
  [ -f "$f" ] || continue
  pid=$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("pid") or ""))' "$f" 2>/dev/null || true)
  if [ -n "$pid" ] && [ ! -d "/proc/$pid" ]; then
    mv "$f" "$backup/$(basename "$(dirname "$f")").gateway.lock"
  fi
done
hermes gateway restart
hermes gateway status --deep
```

Do not delete live root `~/.hermes/gateway.lock` for the currently running service. If in doubt, stop and ask before mutating gateway locks.

Session detail: `cases.md#discord-token-lock-and-webui-sidecar`.

## Gateway conversation resets (session_reset)

Upstream removed the built-in idle/daily reset timers, so a configured `session_reset` block
(`mode: daily|idle|both`, `at_hour`, `idle_minutes`) silently stops applying. Symptoms: every profile
logs `session_reset.mode: daily is no longer applied: gateway conversations reset only on /new or
/reset` at startup, and `hermes doctor` lists it under "found N issue(s)". Gateway conversations then
reset ONLY on `/new` or `/reset`.

Two owner-choice fixes — ask which, but restore the documented intent when it is clear (an install that
configures a real `session_reset` block means the owner wanted resets):

- Restore the behavior: `hermes plugins install hermes-session-reset-policy`, then `hermes plugins
  enable hermes-session-reset-policy`. The community plugin reads the existing `session_reset` block
  (hook `pre_gateway_dispatch`) and starts a fresh session on the first inbound message past the
  boundary — no timers, no background writes. Enabling reloads plugins into the running gateway; a
  gateway restart removes all doubt.
- Accept the new behavior: delete the `session_reset` block from root and every served profile.
- Rollback of the restore: `hermes plugins disable hermes-session-reset-policy`.

## Routed channel silent: zero events, zero log lines

A channel in `gateway.profile_routes` / `discord.allowed_channels` never responds and the
logs show nothing at all. Adapter-side drops log at DEBUG only (invisible at INFO), so
"no log line" does NOT mean "no event" — run the discriminator chain before touching
config:

1. **Did any event reach dispatch?** Every admitted message logs
   `INFO gateway.run: inbound message: platform=discord user=… chat=<id>` — but for a
   `profile_routes` channel it logs in the TARGET profile's
   `~/.hermes/profiles/<p>/logs/gateway.log`, not the main one. Grep the chat id across the
   main gateway.log / agent.log / errors.log AND the routed profile's gateway.log; zero hits
   everywhere means MESSAGE_CREATE never reached dispatch (or was dropped inside the adapter —
   step 2 separates them).
2. **Confirm the message shape via REST** (bot token from `~/.hermes/.env`):
   `GET /channels/<id>/messages?limit=5`. An @mention of anyone in a channel NOT in
   `discord.free_response_channels` is dropped with no log (admission mention gate) —
   the one drop indistinguishable from non-delivery. No mentions + channel allowed +
   `require_mention: false` + human author ⇒ the adapter would have dispatched.
3. **Where would it have landed?** Query sessions across profiles with python's sqlite3
   module (`SELECT id, source FROM sessions WHERE chat_id='<id>'` against
   `~/.hermes/state.db` and `~/.hermes/profiles/*/state.db`). Zero sessions everywhere
   + zero inbound lines = non-delivery, not a routing miss.
4. **REST-vs-websocket split is the tell**: `GET /channels/<id>` returns 200 and history
   is readable while other channels deliver events fine ⇒ the bot's permission for that
   channel (a member/role overwrite granting VIEW_CHANNEL on a restricted channel) was
   granted AFTER the gateway's Discord session was established; Discord does not deliver
   events for channels absent from the session's guild state until reconnect. Fix = the
   detached restart, then re-test by persona in the channel.

Config liveness when in doubt: compare `stat -c %y ~/.hermes/config.yaml` with the
gateway's `ActiveEnterTimestamp`, and date each change via the timestamped backup chain
in `~/.hermes/backups/config/` — a value present in a backup that predates the restart
was live at startup.

5. **Date the breakage before blaming the change.** Grep the chat id across the FULL
log history (`grep 'chat=<id>' ~/.hermes/logs/gateway.log`), not just since the last
restart/config change: **zero inbound ever since the log's earliest line** = the
entrance never worked (wrong channel id in config, or non-delivery from day one) —
not a regression the restart caused. Zero only since a specific change = runtime
regression. For the wrong-id case, have the owner copy the real channel id (Discord
Developer Mode → right-click channel → Copy Channel ID) and diff it against
`discord.allowed_channels` / `profile_routes` before touching anything else.
6. **Feishu: `connected` ≠ delivering.** A Feishu websocket can report
`state: connected` with the current `writer_pid` and healthy reconnect cycles in the
journal (`connected to wss://msg-frontier.feishu.cn/…`) while the server pushes zero
events — a duplicate long-connection with the same app credentials elsewhere, or an
app-side event-subscription change. Rule out a local second process first
(`ps -eo pid,cmd | grep -i hermes`, plus `/proc/<pid>/cgroup`); if the gateway is the
only client, bounce the adapter via the detached restart and re-test. Judge only by
whether an inbound line appears, never by the platform state blob.

**Live test across turns:** do NOT catch an owner-triggered test message with a
bounded `timeout N tail -f` watcher — the owner replies on their own schedule and the
watcher expires silently, reading as "nothing arrived". The gateway log IS the
durable record: ask for the test message, then grep the log directly when the owner
confirms. If you must watch live, run the tail with no timeout and kill it yourself.
