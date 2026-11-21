# Compose skills: split, hide, and chain

Read this when a decision arises to split a skill, hide one from the model, or
have one skill load another. Invariants first; they hold on every host.

## Invariants

- Must-hold rules — authority, safety, stop conditions, never-do-X — live in
  the parent or in always-on rules, never only in a lazily read child.
- A parent loads a child only through the Read link below. Never write
  "invoke skill X", `/x`, or `$x` in a parent body.
- Hidden is a context and selection decision, not an authorization gate. A
  side-effecting step still asks for its own explicit authorization inside the
  workflow; do not hide a skill because it is sensitive ([Codex
  skill-creator](https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/skill-creator/SKILL.md):
  "Do not infer explicit-only invocation from sensitive operations").
- Every `../<sibling>/` reference resolves to the same skill content on every
  OS, and installing a parent installs its whole `../` closure into the same
  host root.

## When to split

Split a part into its own skill only when it needs separate activation or
lifecycle, is shared by two or more parents, or needs its own manual entry.
Otherwise keep it as a `references/` file inside one skill. A task path should
load 1-3 skills: [SkillsBench](https://arxiv.org/abs/2602.12670) reports +18pp
with 1, +19pp with 2-3, and +10pp with 4 or more (correlational; it supports
"avoid 4+", not "prefer 2-3").

If an always-needed fact would end up in every child, it is horizontal
knowledge: put it in an always-on index, not a skill (see
[create.md](create.md)).

## Layout

- Children are flat sibling directories under the same `skills/` root as the
  parent. Hosts disagree on discovery depth: Claude Code and OMP scan one level,
  Pi stops at the first `SKILL.md`, OpenCode does not search inside a skill
  directory, Codex recursive mode turns nested `SKILL.md` files into separate
  skills. Nesting a child inside its parent is never portable.
- One level of chaining: parent -> child. A child's own references stay inside
  the child, one level deep from its `SKILL.md`; a child never chains to a
  grandchild.
- `kind` stays the composition role. Hiding is a per-skill explicit choice; do
  not derive it from `kind: mechanism`.
- Name a hidden child `<parent family prefix>-<role>`, with no `-internal` or
  `-child` marker; a child shared by two or more parents takes the family
  prefix and its own verb. Never pick an obscure name to suppress invocation;
  hide the skill instead. In hoa the full rule is `rules/skill-naming.md`.

## The parent link

Write exactly this in the parent, at the step that needs the child:

```text
Read ../<child>/SKILL.md (relative to this skill's directory) and follow it. Do not call the Skill tool for it.
```

Reason: Claude Code and DSH block the skill tool for hidden skills, and Claude
Code's refusal ("Do not replicate this skill's workflow by other means") can
make the model refuse the Read path afterwards. OMP `skill://<name>/<path>` and
OpenCode's skill tool are not portable; the Read path is the only cross-host
mechanism. No host enforces it — it is model compliance, so verify it in a
transcript (see [evaluate.md](evaluate.md)).

## Hiding a child

A hidden skill is not advertised to the model but stays user-invocable.

- Set top-level frontmatter `disable-model-invocation: true` (YAML boolean,
  kebab-case; DSH drops a skill whose key is camelCase). Honored by Claude Code,
  Pi, OMP, OpenCode, and DSH.
- Codex ignores that key. Also ship `agents/openai.yaml` containing the block
  below, edited by hand: Codex's `generate_openai_yaml.py` overwrites the
  whole file.

  ```yaml
  policy:
    allow_implicit_invocation: false
  ```

- Never set `user-invocable: false`; it removes the `/` entry.
- Anthropic's `quick_validate.py` / `package_skill.py` and claude.ai uploads
  reject unknown frontmatter keys, so a hidden skill cannot ship through them.
- A hidden skill is never a routing target: keep it out of `must_pick` in
  `evals/trigger-cases.json` (it may be a distractor).

Manual invocation differs per host; document the one each target host uses:
Claude Code `/x`, Codex `$x`, Pi and OMP `/skill:x`, OpenCode `@x` (or a
`.opencode/commands/x.md` shim for `/`), DSH `/x`.

Settings-side controls hide a skill per device without forking frontmatter:
Claude Code `skillOverrides` (`on|name-only|user-invocable-only|off`), OMP
`skills.manualSkills`, Codex `[[skills.config]]` with `enabled = false`. Pi
`!pattern` excludes and OpenCode permission `deny` remove the skill instead of
hiding it — never deny a skill a parent chains to. A Read-chained child likely
bypasses host skill permissions entirely (inference), so permissions do not
gate it.

## Compaction, hooks, fork

- Put invariants and gates at the head of parent and child. After compaction,
  [Claude Code](https://code.claude.com/docs/en/skills) re-attaches only the
  first 5,000 tokens of the most recent invocation of each Skill-tool-invoked
  skill, within a shared 25,000-token budget that can drop older skills
  entirely. Read-loaded children have no documented re-attachment.
- A long-running parent tells the model to re-read the child after compaction.
- Skill-scoped `hooks` register only for a skill the host actually invokes; a
  Read-chained child's hooks never register. Put hooks on the parent, with a
  scoped matcher or `once: true` so they do not leak into later work.
- `context: fork` (Claude Code only) likewise applies only to a host-invoked
  skill. A Read-chained child runs inline; a hidden forked skill forks only when
  the user invokes it.

## Cross-platform `../` resolution

The same `../<sibling>` string can hit two directories when skills are
installed as links:

- Windows collapses `link/../sibling` lexically for junctions and directory
  symlinks: it resolves next to the link.
- Linux and macOS `open()` resolves `..` physically after following the link:
  it resolves next to the link target. Tools that normalize first (Node
  `path.resolve`, many harness Read tools) are lexical, so one POSIX host can
  see both.
- Hosts also differ in which base directory they show the model (link path or
  realpath).

So for every `../<sibling>/` reference, both the lexical sibling
(`<host-root>/<sibling>`) and the physical sibling
(`realpath(<host-root>/<parent>)/../<sibling>`) must exist and hold the same
skill (same realpath or byte-identical). Copy-based installers (Codex
skill-installer `copytree`, `npx skills` selective installs) copy one directory
and break the link unless the closure is copied too; say so in the parent's
install notes.

Windows link mechanics: directory junctions need no privilege but take
absolute local targets; directory symlinks need Developer Mode or admin. Never
commit symlinks inside the repository tree. Paths in `SKILL.md` and references
use forward slashes and resolve relative to the file holding them (in
`SKILL.md`, the skill directory), so a reference file reaches a sibling with
`../../<sibling>/`; keep the chain instruction in `SKILL.md`. No drive letters,
`~`, or backslashes. Frontmatter parsing must tolerate CRLF.

## Validate a composition

- Every Read link resolves from the parent directory, in the repository and in
  each installed host root, lexically and physically.
- In a fresh host, a parent run's transcript shows the child read and followed,
  with no Skill-tool call on it.
- The hidden child is absent from the model listing and reachable by the host's
  manual syntax.
- Must-hold rules are present in the parent, not only in the child.
