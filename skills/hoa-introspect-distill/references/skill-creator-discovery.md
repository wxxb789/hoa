# Discover a native skill creator

There is no portable `skill-creator` command. Runtimes expose materially different
plugins, system directories, commands, and interactive interfaces, so discovery comes
before delegation.

## Probe in the active runtime

1. Inspect the runtime’s installed skill/plugin registry, command help, and documented
   system-skill locations for a capability named or described as `skill-creator`,
   `create skill`, or equivalent. Ask the runtime to list available skills when that is
   its normal interface.
2. Check the runtime-specific locations or interfaces that are actually present: Claude
   plugins/commands, Codex `.system` capabilities, Kimi skills, Gemini CLI extensions,
   pi packages, OpenCode skills/plugins, and any other active runtime’s own registry.
3. Confirm the creator can accept the approved spec and learn its required hand-off
   format (command, prompt, file, or UI). Do not extrapolate one runtime’s syntax to
   another.
4. Record only a verified result: creator name/interface, what was supplied, and what it
   returned. A detected-but-incompatible creator is not a completed hand-off.

The discovery is successful only when the creator exists **and** accepts the approved
candidate. Do not hard-code `/skill-creator:skill-creator`: it is a Claude-specific
possibility, not a cross-runtime contract.

## Degrade safely

If no suitable native creator is available, say that no runtime creator was found and
author the asset inline using [inline authoring](inline-authoring.md). This fallback is a
first-class creation mechanism, not an error. Report it as `inline authoring`, never as
an external hand-off.

If a creator fails after discovery, preserve the approved spec, report the failure, and
offer either one focused retry or inline authoring only after the user confirms that
change of mechanism.
