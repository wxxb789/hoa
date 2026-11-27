# OpenCode context compaction

- Config: `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.jsonc`.
- `compaction.buffer` accepts tokens or a percent string. The snapshot default is `20000` tokens;
  the 50% example uses `"50%"`.
- Check the installed schema for percent support (snapshot `Percent` pattern:
  `^([1-9]\d?(\.\d+)?)%$`). Verify what the buffer means for the effective trigger; schema
  acceptance alone does not establish it.
