# Profiles, bot mode, identity and skill consistency


## Profiles and gateway persona overlays

For broad operational separation, prefer class-level profiles:

- `work`: work execution, career impact, standup, weekday utility.
- `personal`: life admin, companion, low-noise personal tasks.
- `discord`: gateway-facing Discord profile and owner cockpit automation.
- `feishu`: Feishu/work-chat profile when the platform needs a distinct persona, isolated memory, skills, or config.
- `research`: source-heavy web/paper/news synthesis.

Create with `hermes profile create NAME --clone --description ...`, then lightly specialize config. Do not overfit profiles to one temporary task.

### Multi-profile gateway multiplexing rollout

When enabling `gateway.multiplex_profiles` on a live default gateway:

1. Upgrade Hermes first if multiplex support is only present on newer upstream `main`.
2. Back up root config, profile configs, `.env`, and source HEAD before changes.
3. Inspect every profile's platform config and `.env` before restart. Cloned profiles often inherit the same `DISCORD_BOT_TOKEN` and channel config.
4. Turn on the root/default flag with `hermes config set gateway.multiplex_profiles true`.
5. Disable duplicate secondary platform adapters unless they have distinct credentials, e.g. `hermes --profile personal config set discord.enabled false`. Multiplex intentionally fails closed when multiple profiles claim the same Discord token.
6. Do not run `hermes gateway restart` directly from inside a gateway-handled Discord/Feishu turn. It is blocked because the gateway would kill its own child command. Use a delayed `systemd-run --user --on-active=...` restart script and a one-shot post-restart verification cron delivered to origin.
7. Verify `hermes profile list`, `hermes gateway status --deep`, runtime `served_profiles` if present, and recent journal lines for `multiplex`, `startup_failed`, token conflict, and platform connection messages.

Session detail: `cases.md#multiplex-gateway-rollout`.

When the user asks for platform/channel-specific agent behavior, separate the layers:

- `SOUL.md` is profile-level identity/personality.
- `AGENTS.md` is profile-level operating protocol.
- Platform/channel prompt overlays are better for per-platform or per-chat tone, constraints, and work-context hints.
- Global `agent.system_prompt` is not channel-specific; avoid using it for one Feishu group or one Discord channel.

Design recommendation: use a separate profile only when the platform needs isolated state or a truly different persona. Use prompt overlays for lightweight adaptation such as “Feishu should be concise, work-oriented, and avoid flirty tone.” If implementing overlays in gateway source, resolve by `SessionSource.platform`, `chat_id`, and optionally `thread_id`, append through the existing `channel_prompt` / `combined_ephemeral` path, and include the overlay in the agent cache signature.

Session detail: `cases.md#channel-and-persona-overlays`.

## Multiplex: the expected "platform explicitly disabled" warning

Under `gateway.multiplex_profiles: true` with one shared messaging bot, every secondary profile must pin
the shared platform OFF in its own config or multiplex refuses to start. The pin is a **top-level**
platform block with an `enabled` key (e.g. `discord: { enabled: false }`), NOT `platforms.discord`.
Recognize the side effects instead of chasing them as faults:

- The gateway logs once per process: `Platform 'discord' is explicitly disabled by
  platforms.discord.enabled: false ... will NOT start its adapter` (source:
  `gateway/config_env.py::_enable_from_env` → `_warn_explicit_disable_beats_env`). This is the dedup
  working — the default profile alone owns the bot. Never "fix" it by removing the pin; that creates a
  duplicate-token conflict.
- Locate the pin in the TOP-LEVEL `<platform>:` block, not `platforms.<platform>`. A per-profile YAML dump
  of `platforms.discord` shows nothing while the real key is top-level `discord.enabled`, and
  `hermes config get platforms.discord.enabled` reports "not set" while the gateway still warns — that
  mismatch is the tell.
- `hermes profile list` then warns each secondary "shares its <platform> credential with default".
  Cosmetic, but `hermes gateway migrate --multiplex` refuses until the duplicate token is removed from
  those profiles' `.env` (the pin still holds; this is a cleanup, not a fix).
- With no `gateway.profile_routes` set, every inbound message resolves to the default profile regardless
  of channel — correct when the extra profiles are CLI-only (`hermes -p <p> chat`). Add routes
  (`gateway.profile_routes`, specificity: user_id 16 / thread_id 8 / chat_id 4 / guild_id 2) only when a
  channel must actually re-home to another profile.

## Profile identity & skill consistency (separate HERMES_HOMEs)

Profiles are separate `HERMES_HOME`s: a profile loads **only** its own `SOUL.md`, `memories/`, and `skills/`. Nothing inherits from the root home. When several profiles are served by one multiplexed gateway, stale profile-local identity or skills silently change behavior on the messaging side, with no error anywhere.

Symptoms: "a profile behaves like a different agent"; a skill the owner demonstrably has is missing in a profile session; a profile's skill count diverges sharply from the root.

Audit shape:
1. `md5sum ~/.hermes/SOUL.md ~/.hermes/profiles/*/SOUL.md` — identical hashes across profiles usually mean one old copy was cloned at profile-create time, not that they are correct.
2. Diff the *skill-name sets*, not just counts: `SKILL.md`-bearing dirs under `~/.hermes/skills` vs `~/.hermes/profiles/<p>/skills`. Report both directions — missing core skills **and** retired skills still present.
3. Check each profile's `model_aliases` and `terminal.cwd`. Cloned profiles carry whatever was current at clone time (banned `*-1m`/builtin-copilot aliases, or a cwd that prevents a context file from loading).

Preferred fix (one source of truth):
- identity: root `SOUL.md` + `profiles/<p>/SOUL.delta.md` → generated `profiles/<p>/SOUL.md` (never hand-edit the generated file)
- skills: per-entry symlinks `profiles/<p>/skills/<entry>` → `../../skills/<entry>`, leaving per-profile dotfiles (`.usage.json`, `.bundled_manifest`, `.curator_state`, `.hub`) untouched
- idempotent reconciler scripts exposing `--check` / `--apply` / `--dry-run`, wired into the post-update check and a daily silent-when-healthy cron

Pitfalls:
- Clearing a bundled skill's `.bundled_manifest` entry does **not** overwrite the local copy (`tools/skills_sync.py::_install_new_skill` skips a differing same-name copy) — but it also stops `hermes skills list-modified` from reporting the fork. Surface the divergence in your own post-update check instead.
- A bundled-skill sync can replace a profile symlink with a standalone copy (bundled changed + local copy pristine). Re-reconcile **after** an update, not only before.
- `hermes skills list-modified` reporting clean does not mean the skill tracks upstream if the fork was re-baselined.
- Removing empty category dirs is best-effort: the bundled sync re-seeds `DESCRIPTION.md` stubs for categories that still have bundled skills.
- Verify a fix from the profile side too (`hermes --profile work skills list | wc -l`), not only from the root home.
