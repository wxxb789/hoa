# Channel → profile routing (one bot token)

Use when the owner wants a channel to talk to a *specific* bot (e.g. `#nrs` → the research
front-door profile) without creating a second Discord/Feishu application.

## Why this works

One bot token = one bot identity. Hermes does not need a token per profile: the multiplexing
default gateway receives the message on the shared bot and routes the **turn** to another
profile. `gateway/profile_routing.py` — the reply comes from the shared bot's identity, but the
SOUL, memory, skills, tools and cwd are the target profile's.

## Config

```yaml
gateway:
  profile_routes:
    - {profile: nana-nrs, platform: discord, chat_id: "<channel_id>"}
    - {profile: nana-nrs, platform: feishu,  chat_id: "oc_..."}
```

```bash
hermes config set gateway.profile_routes '[{"profile":"nana-nrs","platform":"discord","chat_id":"<id>"}]'
```

- Matching is **conjunctive**; highest additive specificity wins: `user_id` 16, `thread_id` 8,
  `chat_id` 4, `guild_id` 2, else the default profile. So a `chat_id` route also captures every
  thread under that channel — no per-thread routes needed.
- A route only applies to messages received by the bot named in `bot_profile` (default: the
  shared bot of the `default` profile). Telegram DM `chat_id == user_id`, which is why
  `bot_profile` exists.
- The chat must also be reachable: append its id to `discord.allowed_channels` (comma string)
  or be covered by the platform's group policy on Feishu (`FEISHU_GROUP_POLICY=open`).
- Restart the gateway (detached unit) — routes are read at startup.

## Feishu specifics

- `im/v1/chats` lists **group chats the bot belongs to**. A DM/home channel
  (`FEISHU_HOME_CHANNEL=oc_...`) is not in that list, so an empty list does not mean "not
  configured".
- Creating a group through the API needs a real member id: with an empty `FEISHU_ALLOWED_USERS`
  the call fails `code 232043 … invalid user ids: []`. Ask the owner to create the group and add
  the bot, or supply an `ou_...` open_id.
- Tenant token: POST `https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal`
  with `app_id`/`app_secret` from `.env`, then send `Authorization: Bearer <tenant_access_token>`.
  In the Hermes sandbox `curl` reaches the endpoint while `.env`-parsing python `urllib` can fail
  DNS; prefer `curl` for the probe.

## Verification

```bash
hermes config get gateway.profile_routes        # both routes present
hermes gateway status                           # new MainPID after the detached restart
# then have the owner send "who are you" in the channel: the answer must come from the target
# profile's persona, not the front door's
```

A silent log is not evidence: routes load without an INFO line. Verify by persona, or by
`hermes -p <profile> cron list` showing that profile's own jobs.

## Pitfall: routing the only channel moves that platform

If Feishu has exactly one channel (the home/DM channel) and you route it to another profile,
that platform stops being the front door's entry point. Say so before writing the route.
