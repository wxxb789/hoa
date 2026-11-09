# Context-compaction thresholds per harness

Reference policy: auto-compact at **50% of the model window** on every harness. Each harness names and
scales the knob differently; these are the resolved answers. Config roots are written as environment
overrides with the harness's own default; substitute the root the host actually uses.

| Harness | Config file | Key | Default | 50% of a 1M window | Verify with |
|---|---|---|---|---|---|
| Gateway harness | its documented config root | `compression.threshold` (fraction 0–1) | `0.75` | `0.5` | the harness's `config get compression.threshold` |
| omp (oh-my-pi) | `${OMP_HOME:-$HOME/.omp}/agent/config.yml` | `compaction.thresholdPercent` (1–99) | `-1` = reserve-based (~80%) | `50` | `omp config get compaction.thresholdPercent` |
| opencode | `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.jsonc` | `compaction.buffer` (tokens OR percent string) | `20000` tokens | `"50%"` | schema: Percent pattern `^([1-9]\d?(\.\d+)?)%$` |
| pi | `${PI_HOME:-$HOME/.pi}/agent/settings.json` | `compaction.reserveTokens` (tokens; threshold = window − reserve) | `16384` | `500000` | JSON parses; threshold is implied |
| codex | `${CODEX_HOME:-$HOME/.codex}/config.toml` | `model_post_turn_compact_threshold_percent` (0–100) plus `model_auto_compact_token_limit` (absolute tokens) | unset | `50` / `500000` | `codex doctor` → "config.toml parse ok" |
| dsh | see realm map below | `thresholdRatio` on `@deepseek-ai/dsh-compaction-basic` | `0.8` | `0.5` | `dsh --profile <p> --dump-config` |

Useful adjacent facts: omp's own docs describe the trigger order
`[remote, snapcompact, handoff, shake, soft]`, `compaction.thresholdTokens` (absolute) takes
precedence over `thresholdPercent`, and manual `/compact` keeps working when auto is off. pi's
`reserveTokens`/`keepRecentTokens` accept per-model `compaction.modelOverrides`. pi is the only
harness here with NO percentage form — the schema requires non-negative safe integers, so express 50%
as reserve = half the window and use `modelOverrides` for any model whose window differs. dsh
resolves `floor(min(W × thresholdRatio, W − outputCap − headroomTokens))` with a 65536 default
headroom, so very small windows can be dominated by the headroom term.

## dsh realm map (why a host-layer patch can be a no-op)

- Profiles: `${DSH_HOME:-$HOME/.dsh}/profiles/<name>/` with `package.json` →
  `dsh.profile.bundles` listing the layer order; layers compose as bundles → `cordis.patch.yml` →
  `--patch` overlays. Start with `cordis.yml` = `[]`; edits belong in `cordis.patch.yml`.
- The user override layer is `${DSH_HOME:-$HOME/.dsh}/cordis.patch.yml` (applies to every profile).
- Host-layer rows are frequently `disabled: true` because agent presets own their own **isolate
  realm**: in the dsh-tui and web profiles the top-level `compaction-basic` row is disabled and the
  live one sits inside a preset.
- Live preset for the TUI copy: `${DSH_HOME:-$HOME/.dsh}/.agent-presets/<preset>/agent.cordis.yml`
  (managed; see `.dsh-tui-managed.json`). Patch `id: compaction-basic` there with
  `config: {thresholdRatio: 0.5}`.
- Web presets (standard/ptc/minimal) ship inside the npm package
  `@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-web-app/presets/*.patch.yml`, so an edit is lost on
  `npm i -g @deepseek-ai/dsh` — back them up and replay after upgrades.
- `headless` mounts compaction-basic at host level, so the user layer alone configures it.
- Verification: `dsh --profile <profile> --dump-config | grep -A4 'id: compaction-basic'`; count the
  matches — more than one means preset copies exist in addition to the host row.

## Verification depth actually applied

dump-config and `config get` prove the composed configuration; only a running session proves the
runtime behaviour. Do not claim "applies at 50%" for a profile you could not boot — say the config
is composed and will take effect at next start.
