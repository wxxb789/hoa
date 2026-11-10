---
name: agent-harness-settings-parity
description: >-
  Audit and apply one policy — model, thinking effort, compaction threshold, approval mode — across
  every installed coding harness, each with its own config file, knob name, and unit. Use when a
  setting must hold everywhere or before claiming it is already set. Not for a single-harness edit.
metadata:
  version: "0.1.25"
  areas: "software-development"
  targets: "runtime-agnostic"
---

# Agent harness settings parity

An operator runs several coding harnesses on the same machine (for example omp/oh-my-pi, pi, codex,
opencode, dsh) and expects a policy — model, thinking effort, compaction threshold — to hold on ALL
of them. Each harness has its own config file, its own knob name, and its own unit for the same
concept. Treat this as a repeatable audit-and-apply task, never as one edit.

## When to use

- "给所有 harness 配上 X" / "check whether every harness still has X" / "apply this on all machines".
- Any policy that must hold across several harnesses at once: model, thinking effort, compaction
  threshold, approval mode, telemetry.
- Before claiming a setting is already in place anywhere — the audit half is the point.

## Procedure

1. **Inventory what is installed before touching anything.** `command -v` for each CLI, then locate
   the real binary (version-manager installs and npm globals are usually NOT on PATH). Record each
   config root.
2. **Find each harness's own knob from its own docs or CLI.** Never map one harness's key name
   onto another: the same concept is `thresholdPercent` (omp), `buffer` (opencode),
   `reserveTokens` (pi), `model_post_turn_compact_threshold_percent` (codex), `thresholdRatio`
   (dsh), `compression.threshold` (the gateway harness).
3. **Read the current value and its default first.** "The operator already set this" is a
   hypothesis; most often nothing was ever written on this host. Report what was actually there.
4. **Write via the harness's own config command when one exists**, otherwise edit the file with a
   backup into the current task dir. Then **read the value back** — a successful write is not a
   verified setting.
5. **Verify with a parse/dump command, not by re-reading your own edit**: `codex doctor`
   ("config.toml parse ok"), `dsh --profile <p> --dump-config`, `omp config get <key>`, or the
   gateway harness's `config get <key>`. If a harness has no readback, say so instead of claiming
   success.
6. **Prove a value that only shows up at runtime from the session transcript.** Per-model settings
   (`thinkingLevel`, resolved compaction threshold) are not visible in the config file alone and the
   TUI banner shows only the model id. A fresh omp session writes its resolution into its session
   JSONL as `{"type":"thinking_level_change","thinkingLevel":"max"}` — read the newest file and
   quote that line as the proof.
7. **Report a per-harness table**: key, before → after, and the exact verification output. Grade
   anything you could not verify as unverified in the same table.

## Restart policy

- Every one of these harnesses reads config at process start: a running TUI keeps its old value.
- **Never restart a harness that is mid-turn on real work.** Apply the config, let the turn finish,
  then relaunch with the resume flag (`omp --resume`, `dsh --resume <session>`). Losing an hour of
  in-flight work to prove a setting is a bad trade.
- **Prefer a fresh session over a resume when the goal is to make a config change live.** A resumed
  session carries the value it resolved at its first start; only a new process re-reads config. When
  the next piece of work starts anyway, start it in a new session and let the setting load for free
  (the delivery pipeline's post-merge reset does exactly this).
- A gateway restart kills the live conversation turn and its background watchers. Config reaches new
  sessions anyway, so restarting is opt-in, stated explicitly with its cost.
- Harnesses that are not running need no restart; say so instead of listing them as pending.

## Pitfalls

- **A "reserve/buffer" knob is not a threshold.** `buffer`, `reserveTokens`, `autoCompactBufferTokens`
  are subtracted from the window: threshold = window − reserve, so 50% means reserve = half the
  window, and the same absolute reserve means something different on every model window. Prefer a
  percentage form when the schema accepts one.
- **Patch/write tools may refuse a gateway config file by design.** Use the harness's own
  `config set <dotted.key> <value>`; it edits and validates the file for you.
- **Some settings live in nested realms, not the top-level config.** dsh is the hard case: the host
  `compaction-basic` row is `disabled: true` because each agent preset owns its own isolate realm,
  so a host-layer patch changes nothing for TUI/web sessions. Patch the preset copy the session
  actually uses (`${DSH_HOME:-$HOME/.dsh}/.agent-presets/<preset>/agent.cordis.yml`).
- **Know which files an upgrade will overwrite.** Preset/config files inside an npm or
  version-manager package directory get reset on update; user-layer copies
  (`${DSH_HOME:-$HOME/.dsh}/.agent-presets/`, `${OMP_HOME:-$HOME/.omp}/agent/config.yml`,
  `${PI_HOME:-$HOME/.pi}/agent/settings.json`, `${CODEX_HOME:-$HOME/.codex}/config.toml`) survive.
  When you must touch a package file, say so in the report and keep the backup so the edit can be
  replayed after an upgrade.
- **`strings <binary>` is a last resort.** It returns megabytes of unrelated keys and eats context.
  The vendors publish real docs — read those first and use `strings` only to confirm a key name you
  already suspect.
- **A managed preset may be rewritten by its owner package.** dsh TUI presets carry
  `.dsh-tui-managed.json`; an edit there is legitimate but can be replaced on a preset update, so
  note it as such rather than treating it as permanent.

## References

- `references/context-compaction.md` — per-harness compaction knobs, defaults, and the exact
  verification command for each, plus the dsh realm map.
