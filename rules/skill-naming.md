<!-- index: areas=software-development; targets=repo-only; summary="skill names are stable ids and the fallback routing signal: kebab-case equal to the directory, family-object-verb order inside a family, one meaning per verb, no vague words, hoa- only for the skill-library family, renames through the retired registry"; summary_zh="技能名是稳定 ID 和兜底路由信号：kebab-case 且与目录同名、族内按“族-对象-动词”排列、动词全库一义、禁用泛词、hoa- 只给技能库元技能族、改名走退役登记" -->

# Skill naming

A standing constraint for naming a new skill and for renaming one. Visibility and chaining live in
[skill-composition.md](skill-composition.md); Hermes-coupled naming is defined in `AGENTS.md`
("Hermes-evolved skills") and handed to Hermes as
[`prompts/hermes-skill-naming.md`](../prompts/hermes-skill-naming.md).

## What a name does

- **Descriptions route; names barely do.** In controlled studies renaming alone moved selection
  weakly and inconsistently (6 of 29 estimates significant, smaller than position bias; arXiv
  2610.14334), while shuffling descriptions moved it strongly (TV distance about 0.34–0.45; arXiv
  2510.00307). Names mattered strongly only at the extremes observed so far: a "best" in the name,
  numeric `1`/`2` siblings, or a full name collision with aligned descriptions (abstract only). To
  change triggering, edit the description or merge siblings, never the name.
- **The name is the fallback signal.** Claude Code drops descriptions of the least-used skills first
  when the listing exceeds its budget and always keeps names; Codex degrades to name and path; DSH
  truncates descriptions at 500 characters.
- **The name is what users type.** Codex `$`, Pi, OpenCode and DSH autocomplete match the name only.
  Claude Code, Pi, OMP and DSH rank a match on a whole `-`-separated segment highly, so `create`
  finds `hoa-skill-create`; a shared family prefix lists members together.
- A hidden skill is never in the model listing, so its name affects only the user's menu.

## Rules

1. **Form.** `^[a-z0-9]+(-[a-z0-9]+)*$`, ASCII, at most 64 characters, identical to the directory
   name (agentskills spec; DSH skips an invalid name, OpenCode invokes by directory name). Aim for at
   most four segments.
2. **Flat.** Every skill lives at `skills/<name>/`; a family is expressed by prefix, never by nesting
   (DSH scans one level, OpenCode grouping drops the prefix).
3. **Families use `<family>-<object>-<verb>`.** A family is skills that chain to each other through
   `../` or that a user chooses between for the same object (`hoa-skill-create`,
   `hoa-skill-review`). A standalone skill may keep a noun or gerund phrase.
4. **One meaning per verb across the library.** `review` judges one artifact read-only; `audit`
   judges a set; `curate` manages provenance, upstream freshness and retirement; `create` builds a new
   skill and also evolves or composes an existing one through the same method (say so in its
   description's first sentence); `port` moves a skill out of one runtime into a shared repository.
   A new verb gets one meaning, added here.
5. **Prefixes.** `hoa-` is only for the skill-library family (skills that act on skills or on the
   agent's own usage history). A domain skill takes its tool or domain as prefix (`tmux-`, `ghc-`); a
   skill coupled to the Hermes runtime takes `hermes-` and may keep a `hermes-<topic>` noun form, as
   `AGENTS.md` requires. The explicit-only `hoa-practice-retro` covers the owner's usage history.
   `hoa-repo-reckoning` keeps its name as an explicit prompt shortcut for a repository review,
   an owner-approved exception to the prefix scope, not a precedent for unrelated repository
   skills. `hermes-ops-claim-verification` targets Hermes.
6. **Banned words.** `work`, `do`, `handle`, `helper`, `utils`, `tools`, `misc`; a single generic word
   as the whole name; a verb that misdescribes the behaviour; superlatives (`best`, `ultimate`);
   numeric suffixes; implementation details (`cdp`, `headless`) in a new name. `workflow`,
   `orchestration`, `management`, `engineering`, `discipline` only after a concrete object.
7. **Reserved and taken names.** Never use `anthropic` or `claude` in a name, a Claude Code built-in
   command (`code-review`, `simplify`, `run`, `init`, `loop`; a user skill shadows it), the exact name
   of a skill the owner has installed from elsewhere, or a name in `scripts/retired_skills.toml`.
8. **Hidden children** are named `<parent family prefix>-<role>`, with no `-internal` or `-child`
   marker; a child shared by two or more parents takes the family prefix and its own verb. Never
   choose an obscure name to suppress invocation — hide the skill instead.
9. **Name and description divide the work.** The name carries family, object and action and stays
   stable; the description's first sentence says when to use it, carries the unique anchor words, and
   routes to siblings ("Use X for …").

## Renaming

Rename only for: a banned or misleading word, a single-word name, a break in a chained family's
pattern, an exact clash with an installed skill, or a Hermes-coupled skill missing its `hermes-`
prefix. A clash with an upstream skill the owner has not installed is not a reason. In one change:

1. `git mv` the directory and update `name:`, every `../<old>/` link and anchor, sibling
   descriptions that name it, `evals/trigger-cases.json`, `evals/baseline.json` picks, config paths
   named after the skill, and the generated indexes. Preserve historical names in dated records,
   but repair any live links the rename breaks.
2. Add `[retired.<old>]` to `scripts/retired_skills.toml` with `replacement` and `reason`, and
   regenerate the indexes: the entry joins the generated `npx skills remove -g …` line. A name that
   was never released gets no entry. Omit a name that the owner's selection still installs from an
   upstream source (as with mattpocock's `improve-codebase-architecture`): the remove command matches
   by name, not source.
3. The renamed directory restarts at `metadata.revision: "1"` (`scripts/version.py check-revisions`
   treats it as a new skill); bump the revision of every other skill whose directory the rename
   touched.
4. On each device, users run the generated remove line and then re-run the install-all command or
   the skill's current generated row (a saved command still names the old skill): `npx skills update`
   keeps the old name and never installs the new one. No host supports aliases, so `/old`, `$old`,
   `/skill:old` and `@old` stop working.
5. Run the paired routing eval before and after, with a positive control that must hit 100% first.
