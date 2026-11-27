# DSH context compaction

`@deepseek-ai/dsh-compaction-basic` uses `thresholdRatio` (snapshot default `0.8`, 50% example `0.5`).
Its effective trigger is `floor(min(W × thresholdRatio, W − outputCap − headroomTokens))`, where `W`
is the model window. The default headroom of 65536 tokens can dominate on small windows.

## Profile and preset layers

- Profiles reside in `${DSH_HOME:-$HOME/.dsh}/profiles/<name>/`. The profile's `package.json`
  lists `dsh.profile.bundles`; composition order is bundles → `cordis.patch.yml` → `--patch`
  overlays. Start with `cordis.yml` = `[]`; edits belong in `cordis.patch.yml`.
- The user override layer is `${DSH_HOME:-$HOME/.dsh}/cordis.patch.yml` and applies to every profile.
  `headless` mounts `compaction-basic` at host level, so this layer alone configures it.
- The `dsh-tui` and web profiles can have a top-level `compaction-basic` row marked
  `disabled: true`. The live one is in an agent preset's isolate realm, so a host patch can be inert.
- The TUI preset is in `${DSH_HOME:-$HOME/.dsh}/.agent-presets/<preset>/agent.cordis.yml`
  (managed; see `.dsh-tui-managed.json`). For an authorized 50% change in this realm, patch the
  `id: compaction-basic` entry with `config: {thresholdRatio: 0.5}`.
- Web presets (`standard`, `ptc`, `minimal`) ship under the installed npm package's
  `@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-web-app/presets/*.patch.yml`. Package upgrades can
  replace edits; back up authorized edits and replay them after upgrades.
- Read back with `dsh --profile <profile> --dump-config | grep -A4 'id: compaction-basic'`.
  Count the matches: more than one means there are preset copies as well as a host row. Verify
  which one is active before claiming parity.
