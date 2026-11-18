# Create a skill from a defined capability

Use this path only when the user has asked for a skill, or another applicable
instruction grants that authority. Start by finding the capability's current
owner and the target repository's packaging rules; inspect relevant local
skills, instructions, indexes, tests, and install metadata rather than assuming
a familiar plugin layout.

## Set the outcome before the mechanism

Write the intended skill's contract before choosing tools or prescribing a
workflow. Establish:

- the result a user can observe;
- who or what consumes it next;
- what evidence distinguishes done from not done;
- the work conditions that should activate it and the nearest condition that
  should not; and
- any material boundary or safe failure behavior that changes the result.

Choose the smallest sufficient number of skill packages. Keep one package when
the requested outcomes share an activation boundary and completion contract.
Split independently consumable outcomes only when they need distinct
activation or lifecycle; do not split merely to separate steps or mechanisms.
If a split materially changes the requested deliverable, make the distinction
and its effect explicit; ask only when a user preference determines whether
to split. When a split, a hidden skill, or a parent-to-child chain is on the
table, read [the composition protocol](compose.md) before choosing a layout.

Knowledge every task in a repository needs is horizontal: put it in an
always-on index (`AGENTS.md`, rules), not a skill. In
[Vercel's eval](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)
the skill went uninvoked in 56% of cases while an 8KB `AGENTS.md` index scored
100%. Keep skills for vertical procedures with a clear activation.

Use facts already in the request or repository. Ask only for a decision that
cannot be derived and would change the skill's outcome, authority, or scope.
Treat a user description as `user-provided` evidence. Do not imply that a
recurring pattern was found in history unless the relevant history was actually
examined.

If an existing skill owns the same outcome, avoid a second owner. Extend it
when the request fits; when the user needs a separate skill, state its
distinct result or activation boundary. If that distinction depends on a
material user choice, resolve that choice before creating a competing package.

## Package for the actual target

Follow the target repository's active instructions and existing packaging
conventions. Put always-needed outcome, activation, authority, and completion
rules in `SKILL.md`; move conditional procedures into one-level references
with a clear read condition. Add scripts, tests, metadata, and inventory changes
only when the skill's behavior or the target repository calls for them. Use the
target's native test and validation commands rather than assuming a particular
runtime, plugin, or package manager.

State capabilities and observable behavior before naming tools. Mention a host
or dependency as required only when the desired behavior truly needs it, and
describe what remains unproved when it is absent. Keep the package complete:
every referenced path, promised workflow, and required output contract must
exist, and the description must distinguish real activation conditions from
nearby work it does not own.

End `SKILL.md` with an "Additional resources" list naming every bundled file
and when to read it; an unlisted file is effectively invisible
([plugin-dev](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/plugin-dev/skills/skill-development/SKILL.md):
"Claude doesn't know references exist"). Links in the body's read conditions
count when they cover every file.

## Name it before writing it

The name barely moves model selection; the description does. Tune triggering
in the description, never by renaming. The name still matters: it is the stable
id, what users type into name-only autocomplete, and the only signal left when a
listing over budget drops descriptions. Use kebab-case equal to the directory;
inside a family, `<family>-<object>-<verb>` with one meaning per verb; no vague
words (`work`, `helper`, `utils`), superlatives, or numeric suffixes. Follow
the target repository's naming rule when it has one (in hoa,
`rules/skill-naming.md`), and register a renamed skill's old name as retired in
the same change.

## Write the description for selection

The description is paid for on every turn and is all a selector sees.

- The first sentence states the capability and when to use it; then
  `Use when ...` and the nearest anti-trigger. No workflow steps, phases, or
  tool lists: a model that believes the description summarizes the procedure
  tends to skip the body
  ([Vincent](https://blog.fsck.com/2025/10/16/skills-for-claude/), anecdotal).
- Fit the smallest cap among target hosts. Listings truncate rather than
  reject: [Claude Code](https://code.claude.com/docs/en/skills) 1,536 chars for
  `description` plus `when_to_use` combined; the
  [agentskills spec](https://agentskills.io/specification) and Codex 1,024;
  DSH `catalogDescriptionMaxLength` default 500.
- The always-on listing has a budget. Claude Code gives it about 1% of the
  context window and drops descriptions of the least-invoked skills first;
  [Codex](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/render.rs)
  gives it 2% of the window (8,000 chars when the window is unknown) and
  on overflow drops all descriptions, then whole skills. Hidden skills add no
  description on Claude Code.
- Each visible skill can shadow another. In
  [Skill Shadowing](https://arxiv.org/abs/2605.24050), at 202 visible skills
  about two thirds of the pass-rate loss was mis-selection, and invocation of
  the known-helpful skill fell from 88.0% to 52.6%. Before adding a visible
  skill, name its nearest neighbors and the request that separates them;
  extend the owner or hide a mechanism when they cannot be separated.
- Explicit-only invocation is not a safety gate. Keep a side-effecting skill
  discoverable unless the user asks otherwise, and require authorization
  immediately before the mutation.

## Calibrate instructions and scripts

Match freedom to fragility, per part
([Anthropic best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)):
heuristics with their reason where judgment varies, a parameterized script
where a preferred pattern exists, an exact command ("do not modify") where a
sequence is fragile. Give one default plus an escape hatch, not a menu of
options.

Bundled scripts serve an agent caller
([agentskills](https://agentskills.io/skill-creation/using-scripts)):

- no interactive prompts; `--help` documents arguments, outputs, and exit codes;
- data on stdout, diagnostics on stderr, distinct documented exit codes;
- bounded, predictable output (harnesses truncate around 10-30K chars; offer
  `--offset` or `--output`);
- errors state what was received and what was expected; validate closed-set
  inputs;
- idempotent where possible; `--dry-run` and safe defaults only for stateful or
  destructive operations;
- stdlib plus `pathlib`, explicit UTF-8, CRLF-tolerant parsing, invoked as
  `uv run <path>` rather than through an executable bit or shebang. Unless the
  target repository sets another rule, each entry point carries a PEP 723
  `# /// script` block (`requires-python`, `dependencies`, `[]` when
  stdlib-only): without it, `uv run` inside a user's project installs that
  project's environment. A missing uv is handled by a vendored
  `references/troubleshooting.md` that SKILL.md says to read only when a
  script command fails; it asks the user before installing uv, never
  auto-installs, and allows `python3` only for a script with no dependencies.
  A script with dependencies says uv is required.

## Adopt imported skills as untrusted code

A third-party skill is code plus instructions. In
[Agent Skills in the Wild](https://arxiv.org/abs/2601.10338) 26.1% of skills had
at least one vulnerability, and skills bundling scripts were 2.12 times as
likely to. Before adopting one, read every script and hidden or non-rendered
text, pin the source by content hash
([OWASP AST07](https://owasp.github.io/www-project-agentic-skills-top-10/)),
and rescan on update. A Read-chained child likely bypasses host skill
permissions (inference), so it gets the same review as its parent.

## Finish the creation

Read the evaluation protocol and test a fresh-context main path and the nearest
meaningful adjacent-negative path. Test model-invoked activation in a fresh
host without manually injecting or naming the skill; a forced invocation tests
execution, not discovery. When the host also exposes direct invocation, test
that path separately. A hidden skill has no model-invoked activation; test it
through its parent's chain and the host's manual syntax instead. Include the
next-consumer contract when the skill hands off a structured result. For a
skill that enforces discipline, write the pressure scenarios and watch them
fail without the skill before writing it.

Compare against a no-skill baseline when it helps establish that the skill
improves the requested result. Grade the user's observable outcome, not whether
the agent repeats the skill's instructions. Report the package path, the
capability and activation it now serves, any local integration performed,
validation evidence, and limitations. If the environment cannot execute a
behavior check, say so instead of leaving a placeholder or claiming proof.
State the basis used to define the capability, such as direct user input,
inspected examples, observed history, or cited requirements; do not attribute
the skill's behavior to sources that were not consulted.
