---
name: hoa-skill-port
description: >-
  Port a skill from one private runtime into a shared, publishable repository and keep it canonical:
  de-couple it, demote every literal to configuration, publish through a branch. Use when a skill
  names a person, home path, model id, private repo or vendor CLI, or a batch of such skills needs
  review. Not for a prose-only edit in a repo that owns the file. Use hoa-skill-create to change
  behaviour, hoa-skill-curate for provenance and freshness; whole-set audits are the user-run
  hoa-skill-set-audit.
metadata:
  revision: "4"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "de-couple a private skill for publication: canonical side, five axes, config resolution, catalog/CI validation, branch-and-PR release"
  summary_zh: "把私有 skill 解耦到可发布仓库：确定权威副本、五轴改造、配置解析、目录与 CI 校验、走分支与 PR 发布"
  kind: "entry"
---

# hoa-skill-port

## Gates

- Configuration is a gate, not advice: no environment literals or private profiles in the
  package. Prove ignore coverage and block release on unresolved scan hits.
- Validate and back up before touching a live runtime; verify its loader after the swap.
  Compare allowed vs derived disabled lists and route policy changes to the owner.
- Publishing requires authority: use a branch and PR, never push to main or force-push.
  Merge and branch cleanup require explicit delegation.
- Never bake the repo's current version into a spec or prompt. Use the repo's version command;
  bump per-skill revisions only for touched skills. Regenerate catalogs, never hand-edit them.
- Use the repo's real validators and CI commands; inspect worker evidence and rerun acceptance.

Move a skill that grew inside a private runtime into a shared, publishable repo, and make that repo
the single source afterwards. Applies to any skill that has to survive leaving one machine: agent
roles → roles, home paths → env vars, one vendor CLI → a documented contract, private repos →
nothing.

## When to Use

- "refactor this skill and port it to <public repo>", "make it runtime-agnostic", "publish this skill".
- Any skill whose body names a person, a machine path, a model id, a private repo, or a bot product.
- A batch port whose reviewer needs one report: source → target, files, sections, demotions.

Not for: rewriting a skill's methodology or behaviour (hoa-skill-create), provenance or upstream
freshness (hoa-skill-curate), auditing the whole skill set (the user-run hoa-skill-set-audit
command), or a one-off doc edit in a repo that already owns the file. When the destination repo's
own contract governs skill ownership and placement, decide repo-owned vs general capability first;
porting a general capability into a project repo pollutes it just as badly as leaving repo-bound
methodology outside.

## 1. Decide the canonical side before writing a file

One copy, and it lives where future readers will find it. Default for a publishable collection: the
public repo is canonical, the runtime's skill directory becomes a **symlink** into it, and anything
machine-specific lives in a directory the repo ignores. Never ship a "public mirror" that a script
re-syncs — two copies of a protocol is the defect the protocol itself warns about.

Symptoms that the wrong side was chosen: a sync script, a "copy to publish" step, or two files whose
diff has to be eyeballed before every release.

## 2. Read the target repo's contracts before writing

Read agent instructions, catalog and its generator, CI commands, ignore rules and one neighboring
artifact. Match the destination's shape, not the source's. See [repo intake](references/pitfalls.md).


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

Every value that differs between installs resolves in the order defined in
[references/configuration.md](references/configuration.md); read it before reviewing a package.
In the shared repository that rule is implemented once, in the repo-level scripts/skill_config.py,
and the reference itself is one file in the repo-level scripts/shared directory. A skill whose
scripts resolve values vendors `skill_config.py`, and a skill that only documents the rule vendors
`configuration.md` and links it instead of restating it, both with `python scripts/vendor_shared.py`,
so the installed package stays self-contained.

Review each ported package against this list and record the outcome in the report:

- [ ] Every path, model id, threshold and host name is a flag/env/config key, or was removed.
- [ ] Every key has a documented default, and "no default" is stated where the value must be supplied.
- [ ] A stranger can answer every value from `--help` or the skill's Configuration section.
- [ ] The package still names the **capability** where it used to name a helper product.

## 4. Delegate the mechanical port, verify it yourself

For mechanical portability work, give the coding agent a spec with:

- the exact write scope, and an explicit "do not touch" list (skill prose, private dirs, other repos,
  git operations, live runs);
- the portability rules as testable assertions (no personal identifiers; these env vars; launcher
  contract; no defaults);
- acceptance commands **that print real output** — compile, the full self-test, one real read-only
  invocation, one end-to-end render, and a grep that must return zero hits.

Then run the acceptance yourself. A reported `N/N ok` is a claim: re-run the suite, and check it covers
launch/act paths and failure paths, not only `--dry-run`.

## 5. Swap the runtime over without a gap

Once authorized, follow [runtime swap](references/runtime-swap.md): archive, build and validate,
replace with a symlink, verify the runtime loader, then keep compatibility wrappers. Reconcile
and diff the exact settings and consumer-visible set; do not infer acceptance from a repair log.


## 6. Validate the way the repo validates

Run the repo's CI commands locally before pushing: structure, catalog `--check`, revision and
eval-fixture checks. Read failing output for the actual convention.

Extract the commands from the workflow rather than guessing them:

```bash
grep -nE '^\s+(run:|- name:)' "${PORTING_CI_FILE:-.github/workflows/ci.yml}"
```

## 7. Publish through a branch, not straight to main

After authorization, open a PR with scope, de-coupling decisions, evidence and known limits.
On red CI, read the failing log, rerun the real gate, and fix forward on the same branch.
After an authorized merge, pull the default branch before the next increment.
See [publishing and CI failures](references/pitfalls.md).


## 8. Keep the symlinked runtime honest

Use the [live drift probe](references/runtime-swap.md) for a symlinked runtime: report aged dirty
paths through an existing check, dedupe the finding, and prove clean and dirty behavior.


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

No key in this table is a repo name. These keys resolve in the order in
[references/configuration.md](references/configuration.md); the file is
`$XDG_CONFIG_HOME/hoa-skill-port/config.yaml` (fallback `~/.config/...`).

## Report shape

A port is not complete until the report carries, per artifact: source lines → ported lines, files
copied, sections merged or dropped **with the reason**, and every literal demoted with what replaced
it. A section that vanished without a row is indistinguishable from an accident.



## Support files

- [Runtime swap](references/runtime-swap.md): backups, loader checks, reconciliation and live drift.
- [Pitfalls](references/pitfalls.md): repo intake, publication, generators and portability failures.
- [Configuration keys](references/configuration-keys.md): install-specific overrides and defaults.
- `references/de-coupling-checklist.md` — the five axes with concrete before/after transforms, the
  configuration resolution rule, and the release-blocking scan.
