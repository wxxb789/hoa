# Skill porting pitfalls

- **A generator that rewrites the whole file defeats the repo's line-ending convention — fix the generator.** If the catalog is stored with CRLF and the generator writes LF, every regenerate produces a whole-file diff that buries the real edit and makes an honest worktree look dirty; `--check` stays green because it reads with universal newlines. Normalizing by hand after each run is only a stopgap. Make the writer preserve the existing file's style (test the first bytes for `\r\n`, then write bytes), and verify the fix the only way that counts: a fresh regenerate on a clean tree produces `git status` output of zero lines.
- **Never bake the repo's current version into a port spec or a delegated prompt.** Any merge that lands first moves the version file, so a spec naming a number asks for a version the gate will reject. Say "bump with the repo's version command" instead of naming a number, and let that command set it at verification time.
- **Dedupe before porting a batch.** Two skills that share a section skeleton (`## 0 … ## 5`, same headings) are one skill wearing two names: diff them section by section, ship the union under the stronger name, and report which lines were unique. Do not recreate a `references/` file the source only ever pointed at — a dangling pointer in the original is a defect in the original, not a file to invent.
- **A folded description becomes a visible `>-` in the generated note column.** Repos that generate a catalog from frontmatter fall back to the description's first sentence when there is no per-artifact note; with `description: >-` the rendered cell starts with `>-`. Add the artifact to the generator's bilingual notes table instead of un-folding the description.
- **Never hand-edit a generated catalog.** If a generator exists, the source of truth is per-artifact frontmatter; a hand-added row is overwritten at best and a red CI at worst, and the error text tells you the annotation style is obsolete. Add the metadata keys, then run the generator.
- **Frontmatter is repo-specific.** A per-skill `metadata.revision` counter, a rejected `version` key, string-scalar `areas`/`targets`, an index comment that some repos forbid — copy a neighbouring artifact instead of reusing the previous repo's shape.
- **A helper needed by two skills ships once.** Keep the real file in the skill that owns the machinery and make the other a 6-line forwarder (`exec` target, PATH fallback, actionable error on miss). Duplicated launchers drift within one edit cycle.
- **Scan before pushing, with a list, not a feeling.** Grep the package for home directories, usernames, private repo names, model ids, email/URLs, and key prefixes; treat any hit as a release blocker even when it looks harmless.
- **Local branch older than origin: fetch and fast-forward before branching.** If `--ff-only` is blocked by your own edits to generator-owned files, restore theirs, fast-forward, then re-apply your content through the generator — do not commit a merge of two hand-edited catalogs.
- **A write tool may refuse to overwrite a file you have only seen through a paginated read.** Read the whole file first, or patch it. Burning a cycle on a refused write is avoidable.
- **Create executables with a write tool plus `chmod +x`, not a shell heredoc.** Multi-line heredocs written inline are treated as script creation and can block on an interactive approval an unattended run will never answer.
- **Do not publish a project profile just because it is only repo conventions.** Gate commands, contract locations and bot behaviour describe someone's private codebase; ship the template, keep the instances ignored.

## Read the target repo's contracts before writing

Order matters — the catalog is usually generated and the shapes are enforced:

1. The repo's agent/contributor instructions (`AGENTS.md`, `README`, or the equivalent) — where a
   skill, a role, a rule and a prompt each belong.
2. `index.md` or catalog — hand-curated or generated? Find the generator (`scripts/*index*`).
3. CI workflow files — the exact commands CI runs; these are your acceptance criteria.
4. `.gitignore` — look for a private/ignore rule you can reuse instead of inventing a side channel.
5. One existing artifact as the shape template: its frontmatter, its revision/areas/targets keys,
   whether it carries a LICENSE, whether sibling files sit in `references/`, `evals/`, `scripts/`.

Copy the shape from the repo you are joining, not from the repo you are leaving.

## Publish through a branch, not straight to main

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

After the merge, pull the default branch before branching the next increment: another merge may have
moved the version file. Never hand-set a version the repo's own version command owns, and where the
repo keeps a per-skill iteration counter (a `metadata.revision`, say), raise it only for the skills the
change touches.
