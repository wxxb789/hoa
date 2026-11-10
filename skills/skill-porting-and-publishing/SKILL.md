---
name: skill-porting-and-publishing
description: >-
  Port a skill that grew inside one private runtime into a shared, publishable repository, and keep
  that repository canonical afterwards: choose the canonical side, de-couple on five axes, demote
  every literal to configuration, validate with the repo's own gates, and publish through a branch.
  Use when a skill names a person, a home path, a model id, a private repo or one vendor's CLI, or
  when a batch of such skills must be reviewed before it lands.
  Not for auditing a skill library (that is curation) and not for a prose-only edit in a repo that
  already owns the file.
metadata:
  version: "0.1.29"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  kind: "entry"
---

# Skill porting and publishing

Move a skill that grew inside a private runtime into a shared, publishable repo, and make that repo
the single source afterwards. Applies to any skill that has to survive leaving one machine: agent
roles → roles, home paths → env vars, one vendor CLI → a documented contract, private repos →
nothing.

## When to Use

- "refactor this skill and port it to <public repo>", "make it runtime-agnostic", "publish this skill".
- Any skill whose body names a person, a machine path, a model id, a private repo, or a bot product.
- A batch port whose reviewer needs one report: source → target, files, sections, demotions.

Not for: rewriting a skill's methodology (that is curation/audit territory), or a one-off doc edit in
a repo that already owns the file. When the destination repo's own contract governs skill ownership
and placement, decide repo-owned vs general capability first; porting a general capability into a
project repo pollutes it just as badly as leaving repo-bound methodology outside.

## 1. Decide the canonical side before writing a file

One copy, and it lives where future readers will find it. Default for a publishable collection: the
public repo is canonical, the runtime's skill directory becomes a **symlink** into it, and anything
machine-specific lives in a directory the repo ignores. Never ship a "public mirror" that a script
re-syncs — two copies of a protocol is the defect the protocol itself warns about.

Symptoms that the wrong side was chosen: a sync script, a "copy to publish" step, or two files whose
diff has to be eyeballed before every release.

## 2. Read the target repo's contracts before writing

Order matters — the catalog is usually generated and the shapes are enforced:

1. The repo's agent/contributor instructions (`AGENTS.md`, `README`, or the equivalent) — where a
   skill, a role, a rule and a prompt each belong.
2. `index.md` or catalog — hand-curated or generated? Find the generator (`scripts/*index*`).
3. CI workflow files — the exact commands CI runs; these are your acceptance criteria.
4. `.gitignore` — look for a private/ignore rule you can reuse instead of inventing a side channel.
5. One existing artifact as the shape template: its frontmatter, its version/areas/targets keys,
   whether it carries a LICENSE, whether sibling files sit in `references/`, `evals/`, `scripts/`.

Copy the shape from the repo you are joining, not from the repo you are leaving.

## 3. De-couple on five axes

Full before/after table: [`references/de-coupling-checklist.md`](references/de-coupling-checklist.md).

1. **Identity** — replace person names with roles (`the agent authors` / `the operator inspects`). A
   protocol written around roles reads better in public and loses nothing.
2. **Paths** — every default resolves from an env var with a neutral XDG-style fallback; script-relative
   paths for bundled assets; nothing under a home directory hardcoded.
3. **Transport** — do not delete the vendor knowledge, abstract it: write the launcher/adapter
   *contract* (subcommands, artifact layout, required JSON fields) and ship one reference adapter.
   The protocol must not require any particular CLI.
4. **Vendor constants** — bot markers, model ids, thinking-effort defaults, host sizing: turn each into
   a flag or env var; delete defaults you cannot justify to a stranger. An opt-out must be explicit
   (a flag), never a silent pass.
5. **Private data** — repo/project profiles, customer names, internal gate commands stay out. Keep the
   template public; put the real files in `private/<topic>/` and prove the ignore rule covers them with
   `git check-ignore -v <file>` before you rely on it.

### Configuration is a gate, not advice

Every value that differs between installs resolves in one order:

```
CLI flag → environment variable → operator config file → documented default
```

The operator config file is `$XDG_CONFIG_HOME/<skill>/config.yaml`, falling back to
`~/.config/<skill>/config.yaml`; one env var overrides one key. A skill may — and should — read that
file to customise itself. What it may not do is encode one machine's answer as the only answer.

Review each ported package against this list and record the outcome in the report:

- [ ] Every path, model id, threshold and host name is a flag/env/config key, or was removed.
- [ ] Every key has a documented default, and "no default" is stated where the value must be supplied.
- [ ] A stranger can answer every value from `--help` or the skill's Configuration section.
- [ ] The package still names the **capability** where it used to name a helper product.

## 4. Delegate the mechanical port, verify it yourself

Tool/script portability is a bounded mechanical job — dispatch it to a coding agent with a spec file
that states, verbatim:

- the exact write scope, and an explicit "do not touch" list (skill prose, private dirs, other repos,
  git operations, live runs);
- the portability rules as testable assertions (no personal identifiers; these env vars; launcher
  contract; no defaults);
- acceptance commands **that print real output** — compile, the full self-test, one real read-only
  invocation, one end-to-end render, and a grep that must return zero hits.

Then run the acceptance yourself. A reported `N/N ok` is a claim: re-run the suite, and check it covers
launch/act paths and failure paths, not only `--dry-run`.

## 5. Swap the runtime over without a gap

1. Back up the current skill dir and tools to one tarball first.
2. Build and validate the new package before touching the live directory.
3. Replace the live skill dir with a symlink to the canonical package; load it through the runtime's
   skill loader and confirm the body, linked files and scripts all resolve.
4. Make the old entry points thin wrappers (`exec` the canonical script, forward argv and exit code)
   so in-flight work keeps the old paths and the owner's layout.
5. Re-run the repo's own reconciliation/drift scripts afterwards, then **prove** what they changed:
   dump the pre-run backup and the new file for the exact key the script claims to have repaired
   (for a runtime config, the skills enable/disable list and the derived disabled set), and diff those
   two dumps. A `repaired: … applied` line is the script's claim, not evidence — and the
   consumer-visible set (which skills the agent can actually load) can move even when the key you
   diffed is byte-identical.
6. If a ported skill then drops out of the runtime's available list, that is a **policy** question,
   not a porting failure: compare the profile's allowed list against the derived disabled list before
   calling it a regression, and route the edit to the owner — an agent that rewrites its own skill
   policy is how a bot loses the skills it needs.

## 6. Validate the way the repo validates

Run the repo's own validators plus the CI command list locally before pushing: skill-structure
validator, catalog generator `--check`, version check, eval-fixture validators. A package that is
valid by your reading and invalid to the repo's generator is not done.

Extract the commands from the workflow rather than guessing them:

```bash
grep -nE '^\s+(run:|- name:)' "${PORTING_CI_FILE:-.github/workflows/ci.yml}"
```

A catalog/version generator failing in CI after your local "all green" is the normal shape of this
error: the repo's own scripts are the acceptance criteria, and its error text names the replacement
annotation style.

## 7. Publish through a branch, not straight to main

Pushing skill content to a public repo is an external, public act: branch → PR → report the link and
what CI said. Include in the PR body: what landed, the de-coupling decisions, the verification output,
and a **Known limits** section (what stays local, what has no evals yet).

When CI goes red on the open PR, fix forward on the same branch with a second commit — never
force-push a branch under review — and only after re-running the exact CI command list locally. Read
the failing step's log (`gh run view <id> --log-failed` when the CI is GitHub-hosted) before editing:
the error text usually names the convention that replaced yours, which is a smaller fix than it looks.

**When the owner has delegated the loop, finish it.** "Push it, merge when nothing is wrong, then start
the next goal" is a standing authorization for that repo: squash-merge on green, delete the branch,
pull the default branch, and open the next increment without asking. Stopping at the PR link to
request permission is the failure mode — it converts an autonomous loop into a chat turn. Without that
delegation the merge stays theirs, so the distinction is per-repo and belongs in the skill's
configuration or project profile, not in the PR.

After the merge, expect a release job to move the tree under you: it may bump the repo version, mirror
that version into every skill's `metadata.version`, and commit the result. Pull the default branch
before branching the next increment, and never hand-set the version — the repo's own version command
owns it.

## 8. Keep the symlinked runtime honest

Once the runtime reads the canonical repo through a symlink, an uncommitted edit in that worktree is
**live but unpublished**: the agent behaves differently while the source of truth says otherwise. Make
that state visible instead of relying on remembering to check it:

1. Attach one probe to an existing periodic health check — never a new job per concern; the rule is one
   check family per schedule.
2. The probe runs `git -C <repo> status --porcelain <skills-path>` and stays silent when clean, and
   when dirty it reports only if the oldest dirty path is older than a threshold
   (`PORTING_DIRTY_AGE_HOURS`, default 24) so an in-flight edit is not noise.
3. Give it a stable finding id (check + scope + violation) so the runner's dedupe emits it once rather
   than every morning, and an action line that names the fix: commit it on a branch and open the PR.
4. Prove both branches before trusting it: the probe runs clean on a clean tree, and a deliberately
   touched file shows up at the right level.

A dirty signal that fires on every regenerate is not a probe problem — it means the repo's generator is
fighting its own line endings (see Pitfalls). Fix that first, or the probe trains everyone to ignore it.

## Configuration

| Key | Env | Default |
|---|---|---|
| `repo` | `PORTING_REPO` | current working tree |
| `package_root` | `PORTING_PACKAGE_ROOT` | `skills` |
| `private_dir` | `PORTING_PRIVATE_DIR` | `private` (must be git-ignored) |
| `ci_file` | `PORTING_CI_FILE` | `.github/workflows/ci.yml` if present, else discover |
| `catalog_command` | `PORTING_CATALOG_CMD` | none — read it from the repo's CI |
| `validator_command` | `PORTING_VALIDATE_CMD` | none — read it from the repo's CI |
| `version_command` | `PORTING_VERSION_CMD` | none — the repo's own version command |
| `base_branch` | `PORTING_BASE_BRANCH` | the remote HEAD branch |
| `dirty_age_hours` | `PORTING_DIRTY_AGE_HOURS` | `24` |

No key in this table is a repo name. The skill reads the file at
`$XDG_CONFIG_HOME/skill-porting-and-publishing/config.yaml` (fallback `~/.config/...`) when present;
a flag beats an env var beats that file.

## Report shape

A port is not complete until the report carries, per artifact: source lines → ported lines, files
copied, sections merged or dropped **with the reason**, and every literal demoted with what replaced
it. A section that vanished without a row is indistinguishable from an accident.

## Pitfalls

- **A generator that rewrites the whole file defeats the repo's line-ending convention — fix the generator.** If the catalog is stored with CRLF and the generator writes LF, every regenerate produces a whole-file diff that buries the real edit and makes an honest worktree look dirty; `--check` stays green because it reads with universal newlines. Normalizing by hand after each run is only a stopgap. Make the writer preserve the existing file's style (test the first bytes for `\r\n`, then write bytes), and verify the fix the only way that counts: a fresh regenerate on a clean tree produces `git status` output of zero lines.
- **Never bake the repo's current version into a port spec or a delegated prompt.** A release job bumps the version file and mirrors it into every artifact's `metadata.version`, so a spec written before that commit asks for a version the validator will reject. Say "mirror the version file" instead of naming a number, and let the repo's version command set it at verification time.
- **Dedupe before porting a batch.** Two skills that share a section skeleton (`## 0 … ## 5`, same headings) are one skill wearing two names: diff them section by section, ship the union under the stronger name, and report which lines were unique. Do not recreate a `references/` file the source only ever pointed at — a dangling pointer in the original is a defect in the original, not a file to invent.
- **A folded description becomes a visible `>-` in the generated note column.** Repos that generate a catalog from frontmatter fall back to the description's first sentence when there is no per-artifact note; with `description: >-` the rendered cell starts with `>-`. Add the artifact to the generator's bilingual notes table instead of un-folding the description.
- **Never hand-edit a generated catalog.** If a generator exists, the source of truth is per-artifact frontmatter; a hand-added row is overwritten at best and a red CI at worst, and the error text tells you the annotation style is obsolete. Add the metadata keys, then run the generator.
- **Frontmatter is repo-specific.** A `metadata.version` that must equal the repo version, a rejected top-level `version`, string-scalar `areas`/`targets`, an index comment that some repos forbid — copy a neighbouring artifact instead of reusing the previous repo's shape.
- **A helper needed by two skills ships once.** Keep the real file in the skill that owns the machinery and make the other a 6-line forwarder (`exec` target, PATH fallback, actionable error on miss). Duplicated launchers drift within one edit cycle.
- **Scan before pushing, with a list, not a feeling.** Grep the package for home directories, usernames, private repo names, model ids, email/URLs, and key prefixes; treat any hit as a release blocker even when it looks harmless.
- **Local branch older than origin: fetch and fast-forward before branching.** If `--ff-only` is blocked by your own edits to generator-owned files, restore theirs, fast-forward, then re-apply your content through the generator — do not commit a merge of two hand-edited catalogs.
- **A write tool may refuse to overwrite a file you have only seen through a paginated read.** Read the whole file first, or patch it. Burning a cycle on a refused write is avoidable.
- **Create executables with a write tool plus `chmod +x`, not a shell heredoc.** Multi-line heredocs written inline are treated as script creation and can block on an interactive approval an unattended run will never answer.
- **Do not publish a project profile just because it is only repo conventions.** Gate commands, contract locations and bot behaviour describe someone's private codebase; ship the template, keep the instances ignored.

## Support files

- `references/de-coupling-checklist.md` — the five axes with concrete before/after transforms, the
  configuration resolution rule, and the release-blocking scan.
