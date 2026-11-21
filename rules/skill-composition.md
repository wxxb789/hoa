<!-- index: areas=software-development; targets=repo-only; summary="hidden child skills: one visibility flag plus the Codex sidecar, Read-link chaining to flat siblings one level deep, must-hold rules in the parent, hidden is not authorization"; summary_zh="隐藏子技能：一个可见性标记加 Codex 旁路文件，以 Read 链接串联扁平同级目录且只下一层，必守规则留在父技能，隐藏不等于授权" -->

# Skill composition and visibility

A standing constraint for any skill that chains to another skill, and for any skill hidden from
model routing. **Hidden** means not advertised to the model; the user can still invoke it by name.
Install and path mechanics live in [cross-platform-skills.md](cross-platform-skills.md).

## Visibility

1. **One source of truth.** A hidden skill sets `disable-model-invocation: true` in its top-level
   SKILL.md frontmatter: a YAML boolean, kebab-case (DeepSeek Harness drops a skill whose key is
   camelCase). Claude Code, Pi, OMP, OpenCode and DeepSeek Harness honor it
   ([Claude Code](https://code.claude.com/docs/en/skills), [OpenCode](https://opencode.ai/docs/skills/)).
   Hermes does not honor the flag; the skill stays listed. Hermes can conditionally hide
   entries with platform metadata such as `metadata.hermes.session_platforms`;
   `skills.disabled` removes the skill rather than hiding it.
2. **Codex sidecar.** Codex ignores that key, so the same skill also ships `agents/openai.yaml` with
   `policy:` / `allow_implicit_invocation: false` ([Codex](https://learn.chatgpt.com/docs/build-skills)).
   Edit that key by hand: Codex's `generate_openai_yaml.py` rewrites the whole file. The flag and the
   sidecar always agree.
3. **Never set `user-invocable: false`.** It removes the skill from the `/` menu — the inverse of hidden.
4. **Hidden is a per-skill choice, not a `kind`.** `kind` stays the composition role; some mechanisms
   are invoked directly by users, so `kind: mechanism` never implies hidden.
5. **A hidden skill is never a routing target.** It must not appear in `must_pick` in
   `evals/trigger-cases.json`; it may be a distractor.
6. **Hidden is not authorization.** Hiding trims the listing and routing noise; it gates nothing.
   Every side-effecting step keeps its own explicit authorization inside the workflow, hidden or not
   ([Codex skill-creator](https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/skill-creator/SKILL.md):
   "Do not infer explicit-only invocation from sensitive operations").
7. **Manual entry differs per host** — document the user path with that in mind:

   | Host | Manual invocation |
   |---|---|
   | Claude Code, DeepSeek Harness | `/x` |
   | Codex | `$x` |
   | Pi, OMP | `/skill:x` |
   | OpenCode | `@x`, or a `.opencode/commands/x.md` shim for `/x` |

8. **Per-device hiding needs no frontmatter fork:** Claude `skillOverrides`
   (`on|name-only|user-invocable-only|off`), OMP `skills.manualSkills`, Codex `[[skills.config]]`
   `enabled = false`. Pi `!pattern` and OpenCode permission `deny` *remove* the skill instead of
   hiding it — never deny a skill a parent chains to.

## Chaining

1. **Same-category, flat install.** A child sits in the same source category as its parent,
   `skills/<category>/<child>/`, never nested under it; after install both are flat siblings in the
   host root. Discovery depth differs (Claude and OMP scan one level, Pi stops at the first
   SKILL.md, OpenCode does not search inside a skill directory, Codex recurses), so a nested child
   is top-level on some hosts and invisible on others.
2. **Exact link shape.** The parent writes:

   > Read `../<child>/SKILL.md` (relative to this skill's directory) and follow it. Do not call the
   > Skill tool for it.

   Never write "invoke skill X", `/x` or `$x` in a parent body. Claude Code and DeepSeek Harness
   refuse the skill tool for a hidden skill, and Claude Code's refusal ("Do not replicate this
   skill's workflow by other means") can make the model refuse the Read afterwards. The Read path is
   the only cross-host mechanism (OMP `skill://<name>/` and OpenCode's skill tool are host-specific),
   and the host does not enforce it — model compliance does.
3. **One level.** Parent → child only. A child never chains to another skill; its own references
   stay inside it, one level deep.
4. **1–3 children per task path.** Loading 1 skill gained +18pp, 2–3 gained +19pp, 4+ gained +10pp
   ([SkillsBench](https://arxiv.org/html/2602.12670)). Split a part into a child only when it needs
   its own activation or lifecycle, is shared by 2+ parents, or needs its own manual entry;
   otherwise it is a `references/` file inside one skill.
5. **Must-hold rules stay in the parent** or in an always-on rule: authority, safety, stop
   conditions, never-do-X. A lazily read child may never be read, or may be compacted away.
6. **Gates first.** Put invariants and gates at the head of parent and child. After compaction Claude
   Code re-attaches only the first 5k tokens of each Skill-tool-invoked skill (25k shared); a
   Read-loaded child has no documented re-attachment. A long-running parent tells the model to
   re-read the child after compaction.
7. **Host-only features go on the parent.** Skill-scoped `hooks` and `context: fork` apply only to a
   skill the host invoked; on a Read-chained child they never take effect.
8. **Horizontal knowledge is not a skill.** What every task needs goes in an always-on index
   (`AGENTS.md`, `rules/`): an 8KB AGENTS.md index scored 100% where the skill was never invoked in
   56% of cases ([Vercel](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)).

## Enforcement

CI (`.github/workflows/ci.yml`) fails on:

| Behavior | Check | Enforces |
|---|---|---|
| A model-visible description over 350 characters; a hidden one over 1024 (agentskills spec, Codex) | `scripts/check_frontmatter.py` | listing budget; hosts truncate long descriptions |
| `disable-model-invocation` not a kebab-case YAML boolean, or `true` without `agents/openai.yaml` `policy.allow_implicit_invocation: false`, or the reverse | `scripts/check_frontmatter.py` | Visibility 1–2 |
| A `../<sibling>/` reference in `SKILL.md` or `references/**/*.md` that names no sibling skill, no existing path, a sibling in another category, or a checkout-only path that climbs above the category | `scripts/check_skill_links.py` | Chaining 1–2 |
| A hidden skill in `must_pick` (`R10`) | `scripts/check_contract_graph.py` | Visibility 5 |
| A visible mechanism that no other skill names or links in its `SKILL.md` or `references/**/*.md` (`R11`) | `scripts/check_contract_graph.py` | visible mechanisms have a caller |
| A generated `npx skills add` row that does not name a skill's whole `../` closure, or an `npx skills remove` line that does not match `scripts/retired_skills.toml` (a registry entry that is a current skill or lacks `replacement`/`reason` fails too) | `scripts/generate_index.py --check` | install-closure invariant ([cross-platform-skills.md](cross-platform-skills.md)); stale names after a rename or split |

On a machine, the user-run hoa-skill-set-audit diagnoses an installed set: a parent's `../` closure
missing from the host root, or its lexical and physical siblings disagreeing, and duplicate names.

Not machine-checked, so review owns them: `user-invocable: false`, the exact link wording, one
level, 1–3 children per path, must-hold placement, gates first, and hidden-is-not-authorization.

## Provenance

Host documentation and binaries surveyed on 2026-11-17 for the hidden-child-skill convention; the
refusal text is Claude Code 2.1.326's skill-tool error for a hidden skill.
