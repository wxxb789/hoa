# Pre-flight and publishing

## 0. Pre-flight: find the owning project, and check who else is writing in it

- **Locate the project that already owns the topic before creating one.** Search the target
  repo/workspace for an existing project on the same topic (search on topic keywords, recent commit
  history, the repo's index/registry) and read its README and plan. Building a parallel tree in a
  scratch workspace for work a governed repo already owns produces a duplicate that cannot merge
  cleanly and wastes the entire round.
- **Check for a concurrent writer before editing a shared project.** Another agent session may be
  editing the same files right now. Detect it with
  `find <project> -type f -newermt '-${DELIVERABLE_WRITER_WINDOW_MINUTES:-10} minutes'` (files
  touched during your session that you did not touch) and `git status -s` (untracked files appearing
  mid-session that you did not create). A file whose mtime moved but that `git status` reports clean
  was rewritten with identical bytes — still evidence of another writer.
- **On detecting one: stop writing into that project, do not commit, and report.** Shared-repo
  edits are sequential; two writers on the same files lose work silently. Read the other session's
  newest commit message first — it may explicitly hand you a file to commit, or state that it
  already absorbed your edit.

### Retire scratch work only after migration

- **Moving work out of a scratch workspace into the owning project: audit before deleting.** Walk
  the duplicate tree file by file and classify each item as migrated or superseded by a named
  artifact in the owning project; confirm nothing outside the tree references it and no process is
  still writing to it; only then delete, and remove the now-empty date/scratch directory too.
  Deleting on the assumption that "it is all in the repo now" loses exactly the one file you did
  not migrate. Also check what the duplicate encoded: a tool that automates a workflow the project's
  contract rejects (for example, a length-fitting loop over raw drafts) must not be migrated at all.

## 6. Publish the deliverable and its evidence

- Stage explicit paths; never blanket-stage, and keep unrelated working-tree changes out.
- **Treat commit and push as separate authorization gates.** Authorization to write commits does not
  extend to publishing them; wait for an explicit push instruction and do not infer it from "the work
  is done". Before pushing to a shared branch, `git fetch` and confirm
  `git log --oneline origin/<branch>..HEAD` is a clean fast-forward with no divergence. Never force.
  If the remote moved, report the divergence instead of pushing over another writer's commits.
- **A private repo answers an unauthenticated raw fetch with 404**, which is indistinguishable from
  a failed push. Verify the remote by SHA (`git ls-remote origin refs/heads/<branch>` compared against
  your local `HEAD`) and read files back through the authenticated API
  (`gh api repos/<owner>/<repo>/contents/<path>?ref=<branch>`, base64-decoding `.content`) — never
  conclude a push failed, or succeeded, from a raw link.
- **Before committing any binary, ask the repo what it does with that extension.** If
  `.gitattributes` routes it through Git LFS and the `git lfs` client is unavailable, `git add`
  writes the full blob into ordinary history — irreversible once pushed. Confirm with
  `git cat-file -p HEAD:<an already-tracked file of that type>` (an LFS pointer reads
  `version https://git-lfs.github.com/spec/v1`) and `command -v git-lfs`. When the client is
  missing: leave the binaries out, exclude the exact paths in `.git/info/exclude` (local,
  uncommitted, reversible, and it keeps `git status` clean for downstream automation), keep the files
  on disk, and record the retention decision plus each `sha256sum` in the provenance file. Report it
  as a known limitation instead of silently dropping artifacts.
- `git ls-files | grep '\.pdf$'` lies about what a repo tracks: git C-quotes paths containing
  non-ASCII bytes, so those lines end in a quote and the `$` anchor never matches. Use
  `git ls-files -z | xargs -0 ...` or drop the anchor.
- Read back every external write. Re-fetch a PR/issue body after creating it (a successful create
  call is not proof the body landed), and re-measure a written file rather than assuming.

## Pitfalls

- Treating a length target as a style preference. It is a gate; unverified means unfinished.
- Optimizing against a private proxy metric instead of the project's measuring script. The proxy can
  invert pass/fail, so the "fix" round makes compliant artifacts non-compliant while the report
  claims success.
- Letting one model's plausible addition into the final because it reads well.
- Measuring the deliverable file after leaving generation metadata inside it.
- Forcing a binary into git "just this once" when the repo's LFS client is unavailable.
- Reporting a length or citation result from an earlier build after re-editing the text.
- Re-running integrity hashes or the full verification loop on unchanged files between steps.
  Hash once where it decides something, batch edits, verify the final once — repeated
  re-confirmation reads as stalling and the owner will say so.
- Committing a regenerated artifact whose only diff is its timestamp. Deterministic generators
  (QA reports, lint reports) stamp the run time on every invocation; `git diff` them before staging
  and revert the ones whose only change is the stamp, so the round's commit carries substance only.
- Concluding a push failed because an unauthenticated raw fetch of a private repo returned 404.
  Confirm by remote SHA and authenticated read-back; a private repo's 404 says nothing about whether
  the push landed.
- Declaring a named model unavailable because it is not in the local proxy's model list. Check the
  agent config's named providers and aliases first — a configured gateway can serve it.
- Filing your own prose as the requested model's draft. It destroys the multi-model comparison the
  round exists to produce; if you must author it directly, label it direct-authored.
- Treating a gateway 504 on a long generation as a model failure and abandoning the round. These
  gateways 504 on a large `max_tokens`; retry with a lower cap. Run the long write as a background
  job with completion notification instead of blocking the session on a call that can run many
  minutes.
- Treating a non-streaming long generation's read timeout as a model failure. A reasoning write can go
  silent for tens of minutes and fail with an empty result and no terminal event, not an HTTP error;
  dropping `max_tokens` does not fix it. Retry with `stream=true` and accumulate the deltas.
