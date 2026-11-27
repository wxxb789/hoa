# Bot Mode & Profiles-as-Bots (CLI ops)

How to stand up / configure Bot Mode from the CLI instead of clicking the desktop.
Docs: https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode

## Mental model (no new primitive)

- **A Bot IS a profile.** Bot Mode is desktop UI + per-profile metadata over the
  `profiles/<name>/` primitive. A Bot's Routines are plain cron jobs; its Bot Chat is a
  canonical session on that profile. `hermes -p <bot> chat` opens the same agent.
- **The roster shows one row per profile.** Every existing profile is already a bot
  candidate — grouping/titling is metadata (below), you do NOT "create a bot" to surface one.
- **Bots tab is a desktop-app surface.** The desktop can attach to a remote/headless backend
  (SSH / `hermes serve`); the roster polls (~5s) and renders profiles as bots. Routines run
  on the gateway whether or not desktop is connected. **Chatting a bot in the desktop needs
  NO messaging bot token** — that token is only for Discord/Telegram/etc inbound.

## Create a bot profile (CLI)

```
hermes profile create <name> --clone-from <src> --description "<1-2 sentences>"
```

- `--clone-from` copies config.yaml, **.env (all API keys)**, SOUL.md, and skills, so the new
  bot inherits the model + credentials. It implies `--clone`; `--no-skills` opts out of skill sync.
- After create it prints a generic **"This profile has no API keys yet"** warning — this is
  MISLEADING when `--clone-from` copied .env. Verify with
  `grep -oE '^[A-Z_]+=' $HERMES_HOME/profiles/<name>/.env`.
- Create is served live by a running multiplexed gateway (no restart). The "add its bot token"
  line only concerns messaging-platform inbound, not Bot Mode.
- **Promoting a specialist role to a bot:** set the profile's `SOUL.md` to the specialist persona.
  Back up the cloned Zoe SOUL first (`SOUL.zoe-backup.md`). If the specialist def splits into
  `SOUL.md` + `AGENTS.md` (common for team agents), concatenate BOTH into its `SOUL.md` — a
  profile's `SOUL.md` always loads, but a repo/`.agents` `AGENTS.md` does NOT auto-load unless
  the cwd is that repo.

## Bot metadata = profile.yaml `ui_meta['hermes-bots']` (writable from files/CLI)

`profile.yaml` (per profile, NOT `config.yaml`) holds `description`, `description_auto`,
`display_name`, `previous_names`, and:

```yaml
ui_meta:
  hermes-bots:
    title: "Gray · Finance"   # roster display name
    sectionId: team           # section membership id
    sectionName: 团队         # heading label (rebuilds on other desktops from members)
_ui_meta_revisions:
  hermes-bots: 1              # per-key CAS revision — BUMP on every write
```

- Reading: `hermes profile list` (model/gateway); `read_profile_meta` yields title only.
  `hermes profile describe <name>` sets `description` (drives kanban routing).
- **Writing safely** (mirrors the gateway's `profiles.configure` → `_configure_ui_meta`):
  load `profile.yaml` with `utf-8-sig`, merge into `ui_meta['hermes-bots']` (keep existing keys
  like `color`/`shape`), set `_ui_meta_revisions['hermes-bots'] = old+1`, then atomic write
  (temp file + `os.replace`). System `python3` has PyYAML.
- **Pitfall:** if you skip the revision bump, a desktop/client CAS write
  (`ui_meta_expected_revisions`) can reject or clobber your edit.
- **Sections:** the section LIST (order, empty sections) is per-desktop local storage; membership
  is per-bot. Stamping `sectionId`+`sectionName` on each bot is enough — a desktop that never made
  the section rebuilds the heading from its members' `sectionName`.
- The **default** profile's meta file is `$HERMES_HOME/profile.yaml` (default dir = root home),
  not under `profiles/default/`.

## Group chats (rooms) are desktop/gateway-driven — do NOT hand-create

- Rooms live in `$HERMES_HOME/shared-state.db` → `hosted_rooms` (`members_json`, `authority_epoch`,
  `next_seq`, `event_bytes`) with `hosted_room_events` sequencing. The desktop "New Group Chat"
  drives a room-event protocol; hand-INSERTing a room corrupts the seq/epoch contract.
- To deliver a group chat: pre-stage the bots (title/section/SOUL), then hand the user the
  one-click flow: Bots tab → **+ → New Group Chat** → pick 2–6 members → name it. Then
  `@member`, `@user` escalation, and up-to-3 serial rounds behave per the room.
- Rooms keep running on a gateway that owns the member set even when the desktop disconnects.
- `sqlite3` CLI may be absent on a minimal host; inspect via `python3 -c 'import sqlite3...'`.

## Verify

- `hermes profile list` — all bots present, gateway `running`.
- `cat profiles/<n>/profile.yaml` — `ui_meta.hermes-bots` present + `_ui_meta_revisions` bumped.
- Desktop reconnect → roster refreshes and shows the sections.
