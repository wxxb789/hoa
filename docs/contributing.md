# Contributing and working on skills

> **English** · [简体中文](contributing.zh-CN.md) · [Repository home](../README.md)

## Clone the repository

```sh
git clone https://github.com/wxxb789/hoa
```

A plain clone is enough for skills and repo tests. The
[external reference map](../ref/README.md) is for studying upstream projects
and reusing attributed patterns. Every submodule sets `update = none`, so plain
clones and `npx skills add` skip them. Fetch one on demand at depth 1 (omit the
path for all):

```sh
git submodule update --init --checkout --depth 1 ref/<name>
```

The [ref sync workflow](../.github/workflows/ref-sync.yml) pushes every pointer
to its upstream default-branch head daily, straight to `main`. The
[Dependabot config](../.github/dependabot.yml) groups weekly Actions and GDD
Observer npm updates. Dependabot alerts and security updates are enabled.

## Install, update, and develop skills

The repo has no custom installer. Use the generated [Install section](../index.md#install):
each command for a skill with sibling dependencies installs its whole closure
into one skills root. Skills without such a row have no sibling dependencies.
Use **Without Hermes** unless you want to operate Hermes; non-Hermes skills do
not link to the Hermes family. In the source tree each skill lives at
`skills/<category>/<name>/`; categories are source-only — installs stay flat at
`<skills-root>/<name>/` and every command is name-based. To include every skill,
or to list or update:

```sh
npx skills add wxxb789/hoa -g -s '*' -y
npx skills add wxxb789/hoa --list
npx skills update -g -y
```

- Global installs go into the selected runtimes' skills roots (for example
  `~/.claude/skills`, `~/.config/opencode/skills`, or `~/.agents/skills`).
  Omit `-g` for project scope. Use `-a <agent>` to target runtimes or `-a '*'`
  for all agents. The default uses links to one canonical copy; use `--copy`
  where links are unavailable or unwanted.
- For a local checkout, use `npx skills add <local-checkout> -g -s <skill> -y`.
  Include any sibling dependencies from the generated row. Re-run `add` after
  edits: `update` skips local sources. Once the changes are on the default
  branch, reinstall from `wxxb789/hoa` to resume upstream tracking.
- After renames or removals, `update` warns but leaves old names in place
  and does not install new ones. Check `npx skills ls -g`, then use the
  generated removal line, omitting same-name skills installed from other
  sources. Removal is by name and a no-op for names not installed. Reinstall
  using the current generated commands, not saved ones. Replacements are
  recorded in the [retired skill registry](../scripts/retired_skills.toml).
- Use [hoa-skill-set-audit](../skills/skill-authoring/hoa-skill-set-audit/SKILL.md) to diagnose
  missing or split sibling closures, duplicates, and shadowing. See the
  [cross-platform rules](../rules/cross-platform-skills.md) for root and link details.

For Hermes model routing, install [hermes-models](../skills/hermes/hermes-models/SKILL.md)
and [hermes-models-cutover](../skills/hermes/hermes-models-cutover/SKILL.md) together
using the parent's generated command. The child covers reversible fleet
cutovers and same-provider ID swaps, with live proof per affected surface.
Hermes does not honor `disable-model-invocation` and still lists the child.
For manual invocation on other runtimes, follow the
[host-specific syntax](../rules/skill-composition.md#visibility).

## Choose the skill maintenance workflow

| Need | Skill | Result |
|---|---|---|
| Review behavior or a proposed change | [hoa-skill-review](../skills/skill-authoring/hoa-skill-review/SKILL.md) | Evidence-backed findings, no edits to the reviewed skill |
| Create, evolve, or compose a defined capability | [hoa-skill-create](../skills/skill-authoring/hoa-skill-create/SKILL.md) | A change, validation results, and any unverified paths |
| Review practice across repos and agent sessions | [hoa-practice-retro](../skills/skill-authoring/hoa-practice-retro/SKILL.md) (explicit only) | Evidence-backed findings and recurring-work candidates, no automatic creation |
| Review one repo's practices and machinery | [hoa-repo-reckoning](../skills/skill-authoring/hoa-repo-reckoning/SKILL.md) (explicit prompt shortcut) | Free-form report with ranked, evidence-backed findings |
| Audit the set of skills offered to a session | [hoa-skill-set-audit](../skills/skill-authoring/hoa-skill-set-audit/SKILL.md) (explicit only) | Set-level findings and necessity verdicts, no changes |
| Recommend skills based on recent work | [hoa-skill-curate](../skills/skill-authoring/hoa-skill-curate/SKILL.md) | Evidence-backed recommendations, no changes |

Start with focused behavior checks and expand to variants, models, or runtimes
as reach, risk, or conflicting evidence warrants. Retro candidates need owner
approval one by one before creation; a direct request for a defined skill does
not need that intake. See the [public catalog admission rubric](../rules/generalization-rubric.md).

Claude Code's native `plugin eval` tests plugin-shaped packages; Anthropic's
`skill-creator` is a separate first-party plugin. The earlier `define-goal`
review used CE guidance and a session-written runner. None is a required
dependency of these runtime-agnostic skills. The
[Claude Code source study](../reflections/2026-09-25-claude-code-skill-source.md)
distinguishes the implementations and their evidence limits.

## Revisions and bilingual policy

There is no project version or release bundle: `npx skills` installs directly
from the GitHub default branch. Each skill tracks its own integer-string
`metadata.revision`. Raise it by one for each skill directory the PR changes.
New skill names, including renames, start at `"1"`; register a rename in the
[retired skill registry](../scripts/retired_skills.toml). A pure category move
is not a change: it keeps the old revision and needs no retired entry, while a
move plus any package edit must bump that skill.
Run `uv run --script scripts/version.py check-revisions`. The
[changelog](../CHANGELOG.md) is dated and optional; earlier entries preserve
historical project and per-skill versions.

For bilingual docs, English is the source of truth; update the Simplified
Chinese mirror in the same commit, in the same section order, with the same
facts and equivalent links. Keep technical terms and commands consistent.
The [indexes](../index.md) are generated in both languages from one source.

## Notes and project history

hoa began as a personal, public, versioned home for portable agent components:
manage them without scattered copies, deploy skills, and reflect on which setups
work. The name comes from Tony Stark's *Hall of Armor*, the workshop for
building, comparing, and improving gear for different missions. Fork or reuse
the parts you need. Track templates and sanitized artifacts only; keep
credentials and personal data out of Git (see [ignore patterns](../.gitignore))
or in a secret manager.

The owner's machine-specific provider, model, plugin registration, runtime
settings files, and secret templates are managed by chezmoi, applied separately
with `chezmoi apply`. hoa does not require chezmoi. Outside the skill catalog
and manually installed Paseo plugins, material here is for reference or
repository maintenance, not automatic deployment.

- The initial skeleton and labeled taxonomy were pressure-tested via Oracle.
  The [skills-first redesign](../reflections/2026-09-23-skills-first-split.md)
  split installation from settings and removed `runtimes/`. Catalog generation,
  routing cases, and written retrospectives followed.
- The [first upstream adaptations](../reflections/2026-09-23-first-steals.md)
  included ECC's skill scout and looper's typed verification gates. See
  [reflections](../reflections/), [goal contracts](goals/README.md), and
  [plans](plans/) for working and historical records, not a feature roadmap.
- Run `hoa-practice-retro` monthly; it reads only its own prior runs. Keep its
  artifacts in the configured private audit state directory, not in Git.

## Request a skill

Open a [bug report or skill request](https://github.com/wxxb789/hoa/issues/new/choose)
if a capability is missing or only partly covers your case. External requests
help prioritize what to build next.
