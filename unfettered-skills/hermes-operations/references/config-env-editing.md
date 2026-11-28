# Editing ~/.hermes/.env safely


## Editing ~/.hermes/.env safely (credential-store guard)

`~/.hermes/.env` is a protected credential store. The `read_file`, `patch`, and `write_file` tools all REFUSE it:

- `read_file` → `Access denied: ... is a Hermes credential store and cannot be read directly.`
- `patch` / `write_file` → `Write denied: ... is a protected system/credential file.`

This is a hard tool guard, not an environment problem — do not retry the file tools expecting them to work. Only `terminal` can mutate `.env` (it bypasses the guard, with an approval prompt on redirection).

Safe edit pattern for adding/changing an env line:

```bash
# 1. Backup first (Yellow change — always leave a restore point)
cp ~/.hermes/.env ~/.hermes/.env.bak.$(date +%Y%m%d_%H%M%S)

# 2. Guard against duplicate keys before appending
cd ~/.hermes && grep -c "FEISHU_HOME_CHANNEL" .env   # expect 0 before adding

# 3. Append (use printf, not write_file). For an in-place value change, prefer
#    a key-aware rewrite over blind append so you don't leave two definitions.
printf '\nFEISHU_HOME_CHANNEL=oc_xxxxxxxx\n' >> .env

# 4. Prove the change without leaking secrets — diff backup vs new shows only the delta
diff <(cat ~/.hermes/.env.bak.YYYYMMDD_HHMMSS) ~/.hermes/.env
```

Pitfalls:
- `search_files` / `grep -c` can match inside `.env` (counts/anchors work) but will not echo full secret values — use them to verify presence/absence, not to read values.
- `.env` changes do NOT hot-reload. Gateway/env changes take effect after `hermes gateway restart` (brief connection drop) or next process start. Treat the restart as a separate, user-gated step when the active channel is the one being reconfigured.
- Redirecting into `.env` triggers an approval prompt ("overwrite project env/config via redirection"); expect it and let the owner approve.
- Secrets can live OUTSIDE `.env` too — e.g. an inline `extra_headers: { Authorization: Bearer <tok> }`
  on a `providers:` entry in `config.yaml`. Tool output redacts secrets, so a value displayed as
  `Bearer d4f0a6...c0e3` is ambiguous. To prove it is a redacted REAL secret rather than a literal
  placeholder, search that file for a literal ellipsis (`search_files` pattern `\.\.\.`) — zero matches
  means the ellipsis was injected by redaction, so the file holds a real token. Flag it and move it to
  `.env` + `key_env` (the provider already carrying `key_env` makes the inline header redundant).
  When the header must stay (a gateway that only accepts `Authorization: Bearer`), reference the env var
  from config instead of duplicating the secret: config.yaml string values expand `${VAR}` / `${env:VAR}`
  (`hermes_cli/config.py::_expand_env_vars`), so `Authorization: Bearer ${TENCENT_GLM_API_KEY}` keeps the
  token in `.env` only. But first confirm the env var EQUALS the inline value — if they differ, the swap
  silently changes the credential. Prove the fix by reading the RAW file (the stored line must hold the
  literal `${...}` placeholder, not the token) and loading config at runtime, printing only the expanded
  LENGTH, never the value.

<!-- migrated from the bundled hermes-agent skill (local addition) -->
### Setting a nested block that has no scalar setter

`hermes config set key value` takes one argument, but the value may be a **JSON object/array** —
it is parsed and stored as real YAML, not a string. Use this for structured config that has no
dedicated `hermes <feature>` command, e.g. a MoA preset:

```
hermes config set moa.presets.<name> '{"reference_models":[{"provider":"...","model":"..."}],"aggregator":{"provider":"...","model":"..."},"enabled":true}'
```

- A "not a recognized config key" warning is **benign** for a known-but-unenumerated nested key
  (e.g. a preset name) — the value still round-trips to correct YAML.
- **Always verify the feature reads it with that feature's own list/status command**
  (`hermes moa list`), not just `hermes config get`.
- Back up first (`cp config.yaml config.yaml.bak.$(date +%Y%m%d-%H%M%S)`) and eyeball the YAML
  round-trip that `hermes config get <key>` prints after the write.

### Toolsets

Enable/disable via `hermes tools` (interactive) or `hermes tools enable/disable NAME`.
Full enumeration: `TOOLSETS` dict in `toolsets.py` (`_HERMES_CORE_TOOLS` is the default bundle most platforms inherit).

| Toolset | What it provides |
|---------|-----------------|
| `web` / `search` | Web search + extraction / search-only subset |
| `browser` | Browser automation (Browserbase, Camofox, or local Chromium) |
| `terminal` | Shell commands and process management |
| `file` | File read/write/search/patch |
| `code_execution` | Sandboxed Python execution |
| `coding` | Code-editing helpers (LSP-backed) |
| `computer_use` | Desktop GUI control (cua-driver) |
| `vision` | Image analysis |
| `image_gen` | Image generation and image-to-image editing |
| `video` / `video_gen` | Video analysis / video generation |
| `x_search` | X (Twitter) search (X OAuth or API key) |
| `tts` | Text-to-speech |
| `skills` | Skill browsing and management |
| `memory` | Persistent cross-session memory |
| `session_search` | Search past conversations |
| `context_engine` | Pluggable context-engine hooks |
| `project` | Named multi-folder workspace tools |
| `delegation` | Subagent task delegation |
| `cronjob` | Scheduled task management |
| `clarify` | Ask user clarifying questions |
| `todo` | In-session task planning |
| `kanban` | Multi-agent work-queue tools (gated to workers) |
| `debugging` | Extra introspection tools (off by default) |
| `safe` | Minimal low-risk toolset for locked-down sessions |
| `spotify`, `homeassistant`, `discord`, `discord_admin`, `feishu_doc`, `feishu_drive`, `yuanbao` | Service integrations (gated on their credentials) |

Tool changes take effect on `/reset` (new session) — never mid-conversation, to preserve prompt caching.

## Voice

### STT (Voice → Text)

Voice messages from messaging platforms are auto-transcribed.

```yaml
stt:
  enabled: true
  provider: local   # local (faster-whisper, free) | groq | openai | mistral | elevenlabs | deepinfra
  local:
    model: base     # tiny, base, small, medium, large-v3
```

Auto-detect priority: local faster-whisper (`pip install faster-whisper`) → Groq (`GROQ_API_KEY`, free tier) → OpenAI (`VOICE_TOOLS_OPENAI_KEY`) → Mistral Voxtral (`MISTRAL_API_KEY`).

### TTS (Text → Voice)

| Provider | Env var | Free? |
|----------|---------|-------|
| Edge TTS (default) | None | Yes |
| ElevenLabs | `ELEVENLABS_API_KEY` | Free tier |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | Paid |
| MiniMax | `MINIMAX_API_KEY` | Paid |
| Mistral | `MISTRAL_API_KEY` | Paid |
| Gemini | `GOOGLE_API_KEY` | Free tier |
| NeuTTS / Piper / KittenTTS (local) | None | Free |

Voice commands: `/voice on` (voice-to-voice), `/voice tts` (always voice), `/voice off`.

## `config.yaml` is protected the same way

`read_file` / `patch` / `write_file` also refuse `~/.hermes/config.yaml`; use `hermes config get|set|unset`
(and `config migrate` for version bumps). Back up with `cp` in the terminal before a multi-key change, and
remember liveness is **per key**: adapter/routing keys are read at process/adapter start, while the turn
budgets below are re-read on every turn.

**`hermes config set` leaves a post-write copy, not a rollback point.** It writes
`~/.hermes/backups/config/config.yaml.good.<ts>` *after* the edit, so that file is byte-identical to the
NEW config (read its `agent.max_turns` back to see the new number, not the old one). Take your own
pre-change copy — `cp -a config.yaml <backups>/config.yaml.pre-<change>.<ts>` — quote that path as the
rollback, and perform the rollback with `hermes config set <key> <old-value>`, never by copying a
`.good.*` file back.

## Tuning the agent's turn budgets

`agent.max_turns` is the tool-call/iteration ceiling **per turn**, and it is not the only ceiling — the
siblings do not follow it. Set each one you mean to change, and read it back:

| Key | Bounds |
|---|---|
| `agent.max_turns` | main-loop tool calls in one turn |
| `delegation.max_iterations` | a `delegate_task` subagent's own loop |
| `goals.max_turns` | one goal-mode turn |
| `code_execution.max_tool_calls` | calls inside a single `execute_code` run |

- Change it with `hermes config set agent.max_turns <n>`; never hand-edit the YAML (indentation breakage).
- **No gateway restart.** The gateway re-bridges this key from `config.yaml` at the start of every turn
  (`gateway/run.py:_current_max_iterations()` → `_reload_runtime_env_preserving_config_authority()` →
  `_bridge_max_turns_from_config()`), because it must not keep a stale `HERMES_MAX_ITERATIONS` from the
  process env. So the new number applies to the next turn, and scheduling a restart only costs a turn.
- Answer the complaint that was made, then name which sibling limits were left alone and offer them as one
  numbered choice — a subagent that dies at `delegation.max_iterations` arrives as the same complaint.
- Report the real ceiling: on a normal turn the binding limit is often the per-turn inactivity watchdog
  (seconds) or the context window, so a larger `max_turns` is headroom, not permission to run that many
  rounds.
- Verify with `hermes config get agent.max_turns` **and** a parse of the file
  (`python3 -c "import yaml;print(yaml.safe_load(open('.../config.yaml'))['agent']['max_turns'])"`), and
  keep the pre-change backup path in the report.

## Redacted output is not truncated input

A scanner hit printed as `AKIAIO...MPLE` is **not** necessarily a short or invalid key: tool output
redacts real-looking tokens, so the displayed text is shortened while the file holds the full value.
Before allowlisting a string or "fixing" a scanner, re-read the match raw —
`grep -oE '<pattern>' file | od -c` — and compare with a known documentation example
(`<aws-example-key>` for AWS docs). Allowlist the exact known-fake value, never the truncated display.
