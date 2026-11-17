<!-- index: areas=software-development,self-management; targets=hermes; summary="brief for Hermes when it creates or evolves a skill: decide coupling, prefix coupled skills hermes-, never fork a built-in, hand portable skills to hoa's port review"; summary_zh="交给 Hermes 的创建/演化 skill 须知：判定耦合、耦合 skill 加 hermes- 前缀、不分叉内置 skill、可移植 skill 走 hoa 的移植评审" -->

# Hermes skill naming and hand-off

A standing brief to give Hermes whenever it creates a skill or evolves an existing one. It
decides the name before the content, keeps Hermes-only detail out of portable skills, and
routes anything worth keeping to hoa through a review instead of a copy.

## Template

```text
You are about to create or change a skill. Before writing its content, settle three things.

1. Is this a Hermes built-in or bundled skill?
   Check the skills that ship with Hermes (the bundled/built-in set of this install). If the
   skill you are about to write duplicates, forks, or re-creates one of them, stop. Use the
   upstream skill as it is. If it is wrong or missing something, write the change up as an
   upstream contribution (issue or patch against Hermes) and tell the operator; do not keep a
   private copy under another name.

2. Is the skill coupled to Hermes?
   It is COUPLED if following it requires any of:
   - Hermes runtime paths (the Hermes home, its profiles, its install or log directories);
   - Hermes configuration (its config files, provider/model entries, profile settings);
   - Hermes tools or commands that other agent runtimes do not have;
   - the Hermes gateway (its messaging/platform adapters, delivery, sessions);
   - Hermes memory (its memory store, context files, or memory tools).
   It is PORTABLE if a coding agent in another runtime (Claude Code, Codex, OpenCode, pi)
   could follow it unchanged given ordinary shell, git, and the files the skill ships.
   Examples:
   - "Upgrade the Hermes install and verify the runtime afterwards" -> coupled.
   - "Configure model providers in the Hermes config" -> coupled.
   - "Trace which context files Hermes loads into the prompt" -> coupled.
   - "Verify a delegated agent's diff and tests before accepting it" -> portable.
   - "Search the web through an OpenAI-compatible proxy" -> portable, even if you happen to
     run it from Hermes; the endpoint is configuration, not coupling.
   When one skill mixes both, split it: a portable method plus a small hermes- skill that
   holds the Hermes-specific steps.

3. Name it.
   - Coupled skills are named `hermes-<topic>` (for example `hermes-updates`). Renaming an
     existing coupled skill to add the prefix is part of the change.
   - Portable skills never carry the prefix and never mention Hermes paths, config keys,
     profile names, gateway ids, or memory locations. Every environment-specific value is
     read from configuration (flag -> env var -> config file -> documented default) with the
     default stated in the skill.

Hand-off to hoa (the operator's skill library):
- hoa does not track Hermes built-in skills; do not propose them.
- A portable skill, or a hermes- skill worth keeping, is proposed to hoa as a port, never
  synced or copied. Give the operator: the skill directory, what changed and why (the
  failure or improvement that drove it), every literal path/id/model you introduced, and
  the commands that show the skill works.
- The operator runs hoa's port review: each literal is demoted to configuration, the
  skill's own acceptance commands are re-run, and only then does it land. Expect edits; a
  skill that only works on this install is not ready.
```

## Usage notes

- Hand it to Hermes once as a standing instruction, and again whenever a skill-evolution
  run starts; it is short enough to sit in the system prompt of that run.
- The coupling test is about what following the skill requires, not where it was born. A
  skill evolved on Hermes can be fully portable.
- The prefix rule and the review gate are defined in hoa's `AGENTS.md` ("Hermes-evolved
  skills" and "Portability"); this prompt is the Hermes-facing copy of those rules.

## Provenance

Written for hoa after a catalog cleanup removed 14 Hermes-origin skills that duplicated
Hermes built-ins or carried install-specific detail into the shared library.
