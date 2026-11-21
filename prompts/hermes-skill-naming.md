<!-- index: areas=software-development,self-management; targets=hermes; summary="brief for Hermes when it creates or evolves a skill: decide coupling, prefix coupled skills hermes-, never fork a built-in, check candidates into hoa's unfettered-skills/ after check_unfettered passes, and send promotions through hoa's port review"; summary_zh="交给 Hermes 的创建/演化 skill 须知：判定耦合、耦合 skill 加 hermes- 前缀、不分叉内置 skill、候选写入 hoa 的 unfettered-skills/ 并通过 check_unfettered、可移植化走 hoa 的移植评审" -->

# Hermes skill naming and hand-off

A standing brief to give Hermes whenever it creates a skill or evolves an existing one. It
decides the name before the content, keeps Hermes-only detail out of promoted skills, and
routes anything worth keeping through hoa's landing zone and port review instead of a copy.

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
   - Coupled skills are named `hermes-<topic>` (for example `hermes-updates`) in both tiers.
     Renaming an existing coupled skill to add the prefix is part of the change.
   - A portable skill never carries the prefix. Portability otherwise binds at promotion: the
     promoted package must have no Hermes paths, config keys, profile names, gateway ids or
     memory locations, and every environment-specific value must be read from configuration
     (flag -> env var -> config file -> documented default) with the default stated in the
     skill. Raw candidates stay unconstrained; the promotion edit supplies this.

Hand-off to hoa (the operator's skill library):
- hoa does not track Hermes built-in skills; do not propose them.
- Check in, don't fork. Write every non-built-in skill as a candidate to
  `unfettered-skills/<name>/SKILL.md` in hoa. That is the landing zone for this runtime's
  skills: unconstrained, reached only by explicit path, `--full-depth` or a name retry, and
  never a replacement for a curated skill. Never edit `skills/` directly.
- Before publishing, run `uv run --script scripts/check_unfettered.py` in a hoa checkout and
  fix every finding: sensitive content, a missing or mismatched candidate shape, or a name
  collision with `skills/` or the retired list.
- Promotion is the operator's move, never a sync or a copy. One authorized PR deletes the raw
  copy and lands the normalized package in `skills/<name>/` at `metadata.revision: "1"`
  through hoa's port review and curated gates. Send the operator what changed and why (the
  failure or improvement that drove it), every literal path/id/model you introduced, and the
  commands that show the skill works.
```

## Usage notes

- Hand it to Hermes once as a standing instruction, and again whenever a skill-evolution
  run starts; it is short enough to sit in the system prompt of that run.
- The coupling test is about what following the skill requires, not where it was born. A
  skill evolved on Hermes can be fully portable.
- This prompt is the Hermes-facing copy of the two-tier rule, the prefix requirement and
  the promotion gate in hoa's `AGENTS.md` ("Hermes-evolved skills" and "Portability").
- The general naming rules (form, one meaning per verb, banned vague words, renames through the
  retired registry) are in hoa's [`rules/skill-naming.md`](../rules/skill-naming.md); `hermes-` is
  the domain prefix those rules reserve for Hermes-coupled skills.

## Provenance

Written for hoa after a catalog cleanup removed 14 Hermes-origin skills that duplicated
Hermes built-ins or carried install-specific detail into the shared library.
