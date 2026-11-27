# Bot Mode & profile-layer mechanics (Hermes)

Operational reference for turning profiles into Bot Mode bots without the desktop UI, and for
not breaking the generated profile layer. Product docs: https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode

## Mental model

- **A Bot IS a profile.** Bot Mode is a UI over `~/.hermes/profiles/<name>/` — isolated config,
  memory, skills, credentials, chat history. No new primitive. `hermes -p <name> chat` opens the
  same agent.
- Existing profiles appear in the roster automatically; a **new Bot = a new profile**.
- The **Bots tab is a desktop-app UI** (Electron). Routines still run server-side on the gateway
  whether or not the desktop is open. Desktop connects to a remote/headless backend over SSH
  (multi-connection desktop) — Bot Mode works fine for a headless VM that way.
- **Group chats ("rooms")** live in the root `~/.hermes/shared-state.db` (`hosted_rooms*` tables)
  and are created by the desktop/gateway event protocol (seat/epoch/seq invariants). Do NOT
  hand-insert rows — you will break sequencing. Create rooms in the desktop UI (New Group Chat,
  2–6 members); from the CLI only pre-stage members + sections.

## Bot metadata lives in `profile.yaml`, not `config.yaml`

Per-profile roster presentation is `~/.hermes/profiles/<p>/profile.yaml`:

```yaml
description: ...
description_auto: false
ui_meta:
  hermes-bots:
    title: "Work · Career"     # roster display name
    sectionId: "work"          # section membership (folder)
    sectionName: "工作"
_ui_meta_revisions:
  hermes-bots: 1               # bump on every write (desktop CAS rejects stale writes)
```

- Safe to write directly with an atomic YAML write, or via the gateway `profiles.configure` RPC
  (`params.ui_meta` merges key-wise). When writing by file, bump `_ui_meta_revisions["hermes-bots"]`.
- Set `sectionId` + `sectionName` on each bot; the desktop **rebuilds section headings from
  members**. The section *list* (order / empty sections) is per-desktop localStorage — you can
  only set membership, not the list.
- The **`default` profile's meta file is `~/.hermes/profile.yaml`** (the root home), not under
  `profiles/`.

## `SOUL.md` is GENERATED — never hand-edit it

- `profiles/<p>/SOUL.md` = root `~/.hermes/SOUL.md` + that profile's `SOUL.delta.md`, produced by
  `~/.hermes/scripts/sync-profile-soul.py`. A missing `SOUL.delta.md` is itself a drift error.
- **PITFALL (cost a full redo):** to give a profile a specialist persona, write **`SOUL.delta.md`**
  (the overlay appended after root Zoe), NOT `SOUL.md`. A hand-edited `SOUL.md` silently reverts to
  root Zoe on the next reconcile (daily cron) — specialist identity wiped.
- Profile `skills/` are **symlinks** into root `skills/`; a copied skill is drift and gets relinked
  (destructive: replaces copies) by `~/.hermes/scripts/sync-profile-skills.py`.

## Reconcile

```bash
python3 ~/.hermes/scripts/profile-layer-reconcile.py --dry-run   # inspect drift count first
python3 ~/.hermes/scripts/profile-layer-reconcile.py             # apply (silent when healthy)
python3 ~/.hermes/scripts/profile-layer-reconcile.py --dry-run   # confirm clean
```
Runs both soul + skills layers; silent on success. Reach for it after creating/moving profiles or
hand-editing any profile SOUL.delta / skills, and whenever a profile "behaves like a different agent".

## Creating a specialist bot profile

```bash
hermes profile create <name> --clone-from default --description "..."
```

- `--clone-from default` copies `config.yaml`, `.env` (API keys), `SOUL.md`, and skills. The
  "no API keys yet" banner is generic/misleading — the clone DOES copy `.env`; verify key names in
  `profiles/<name>/.env` before believing it.
- After create: write `SOUL.delta.md` (specialist overlay), set `description`, set
  `ui_meta.hermes-bots` title/section, then reconcile.
- **Don't create a duplicate profile for a role that already has one** (e.g. team `researcher` when
  a `research` profile exists) — retitle the existing profile instead; duplicate names collide in the
  roster (`research` vs `researcher`).

## Per-profile model pin + verify

```bash
hermes -p <p> config set model.default  <model>
hermes -p <p> config set model.provider <provider>
hermes -p <p> config set model.api_mode <chat_completions|codex_responses|...>
hermes -p <p> config set model.base_url <url>
```

- `-p <profile>` targets that profile's `config.yaml` (protected from edit tools; `hermes config set`
  is the sanctioned writer). `hermes -p <p> config get model` reads it back.
- **Set `model.base_url` to match the provider's `api`.** A stale `base_url` inherited from the
  clone points at the old endpoint and the bot 404s even though the provider is right.
- **Verify end-to-end, don't trust the config write:** `hermes -p <p> -z "reply with exactly: PINOK"`.
  A real oneshot proves model + endpoint + api_mode + key all work together.
- **Probe candidate models with curl before pinning.** On the local ghc-proxy (`localhost:4141`) the
  transport split matters: `gemini-*` answer on `/v1/chat/completions` (`chat_completions`), while
  `gpt-*`/`grok-*` only answer on `/v1/responses` (`codex_responses`). Pinning a `gpt/grok` model with
  `chat_completions` returns "not accessible via the /chat/completions endpoint". Check what the
  endpoint actually serves (`/v1/models`) before choosing provider + api_mode.

## Cron job → Bot Routines pane

- A cron job shows under a Bot's **Routines** pane when its name is prefixed
  `[bot:<profile-name>] <routine>` (e.g. `[bot:work] weekly-impact-log`).
- Rename with `hermes cron edit <id> --name "[bot:work] ..."` — naming only; schedule, prompt,
  deliver target, and profile are unchanged.
- Match on the **profile name**, not the bot display title: the `default` profile is `[bot:default]`
  even though the bot is titled "Zoe".

## Nested config blocks via `hermes config set` (JSON value)

`hermes config set` takes a single value; to write a nested block, pass a JSON string — e.g. a MoA
preset with the user's own providers:

```bash
hermes config set moa.presets.<name> '{"reference_models":[{"provider":"...","model":"..."}],"aggregator":{"provider":"...","model":"..."},"enabled":true}'
```

It writes valid YAML and prints "'…' is not a recognized config key — saved anyway" — harmless for
known-but-unenumerated nested schemas (individual MoA preset names). Authoritative check is the
owning command (`hermes moa list`), not the warning.
