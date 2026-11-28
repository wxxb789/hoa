# The pointer-only reference corpus in the shared skills repo

A public skills repo often carries a `ref/` directory of third-party corpora (other people's skill
packs, design references) so the owner can read them without cloning each one. The convention that
makes this cheap: **submodules are declared but never checked out**. `git submodule status` then prints
`-<sha> ref/<name>` for every entry and `du -sh ref/` stays in kilobytes.

That shape changes how you maintain it: "update to latest" means moving gitlinks, not pulling trees.

## Re-pin every submodule to its upstream head without cloning

```bash
# resolve, per repository — no clone, no checkout, whole corpus in seconds
git ls-remote <url> refs/heads/<configured branch>   # fall back to HEAD if that branch is gone
git update-index --cacheinfo 160000,<sha>,ref/<name> # 160000 = gitlink
```

Drive it from `.gitmodules`, not from a hand-written list: parse `[submodule "<name>"]` blocks into
`{path, url, branch}`, compare against the recorded gitlinks (`git ls-tree -r HEAD ref/`, mode `160000`)
and print a `changed / already-current / failed` table before writing anything. Parallelise the
`ls-remote` calls (a handful of workers is enough) and treat a missing configured branch as "fall back
to HEAD, and say so" rather than a failure. After the write, `git status --short` must show only
`M ref/<name>` lines, and `git submodule status` must still show the `-` prefix — if a prefix disappeared,
something checked a tree out.

## Add a submodule without cloning it

`git submodule add` clones. To keep the corpus uninitialised, register it by hand:

```bash
git config -f .gitmodules submodule.ref/<name>.path ref/<name>
git config -f .gitmodules submodule.ref/<name>.url  <url>
git config -f .gitmodules submodule.ref/<name>.branch main
git config -f .gitmodules submodule.ref/<name>.ignore dirty
mkdir -p ref/<name>
git update-index --add --cacheinfo 160000,<sha>,ref/<name>
```

**Quoting trap:** `git config` already quotes the section name, so passing a pre-quoted key
(`submodule."ref/<name>".url`) writes `[submodule "\"ref/<name>\""]` — a section whose name includes
literal quote characters. `git submodule status` still works (it matches on `path`), so the damage hides
until something reads `.gitmodules` by name. Use the unquoted dotted key as above and check the tail of
the file with your own eyes.

## Land it

A gitlink refresh is not a skills release, but in a repo whose release job tags what the PR committed,
**the PR still bumps its own patch** — an unchanged `VERSION` fails the bump guard. Group the whole
corpus move into one commit (`.gitmodules` + every `M ref/…` + `VERSION`), describe it as pointer-only,
and say in the body how many were already current and that nothing was cloned — that sentence is what
stops a reviewer from assuming a 37-repo fetch happened.

## Diagnose a stranded worktree before touching the pointer

Read both reflogs before deciding who moved what — the shape reads like "the re-pin job drifted", and is
usually a local checkout nobody maintained:

```bash
git submodule status | grep -v '^-'        # which entries are materialised (healthy answer: none)
git -C ref/<name> reflog                   # when it was cloned/checked out, to which sha
git reflog                                 # when the recorded gitlinks arrived (pulls, merges)
git diff HEAD origin/<branch> -- ref/<name> # incoming commits that do not touch it
```

An empty last check means a plain fast-forward cannot dirty the tree: the writer was local, so a stranded
worktree belongs to a session's stray `--checkout`, not to the re-pin job. `git -C ref/<name> log --oneline
<local-sha>..<recorded-sha>` names the commits it is sitting behind.

Two remedies — pick by whether the read copy is still wanted:

```bash
# one-shot: clean the tree without discarding anything upstream owns, then follow the new pointer
git -C ref/<name> checkout <gitlink recorded in the local HEAD>   # tree clean again
git merge --ff-only origin/<branch>                                # records the newer gitlink
git -C ref/<name> checkout <gitlink recorded now>                  # match it ⇒ clean
# permanent: back to the documented pointer-only shape
git submodule deinit -f ref/<name>
```

Keep the read copy only if something actually reads it, and then the re-align step has to ride whatever
pulls that repo (post-merge), or it strands again the next time the pointer moves. Never "fix" it by
`remote set-url`, re-adding the submodule, or checking out an upstream-only sha by hand — restore the
gitlink the branch records and let the repo's own job own the pointer.

## Pitfalls

- **Never `git submodule update --init` "just to check" — not even for one entry.** It materialises a
  tree, and the corpus is read-on-demand by design; the `-` prefix on `git submodule status` is the
  invariant you break. `ignore = dirty` does **not** absorb the consequence: it hides modifications
  *inside* the worktree, never a HEAD that differs from the recorded gitlink, so the superproject
  reports ` M ref/<name>` from then on.
- **One materialised entry in a repo that also runs a publish loop is a permanent deadlock, not just
  status noise.** Whatever re-pins the corpus (the repo's own scheduled job) keeps moving recorded
  gitlinks while the local worktree stays where it was checked out, and a delivery engine will not rebase
  a tracked-dirty tree — dirty *plus* behind is the same failure every tick, with no self-heal. Consumer
  symptom and its recovery sequence → skill `repo-automation-publishing`,
  `references/git-delivery-engine.md` (*Wedge*).
- **A submodule whose `path` differs from its name** breaks any script that assumes they match; resolve
  from the `path =` key, never the section name.
- **An empty `ref/<name>/` directory with no gitlink** is not a submodule — `git submodule status` shows
  nothing and the path silently disappears from a fresh clone. Verify with `git ls-files -s ref/<name>`
  (mode `160000`) before believing the add worked.
