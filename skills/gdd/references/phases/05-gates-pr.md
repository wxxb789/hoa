# Phase 5 — gates, commit, PR

1. **Prove the branch is not behind main before measuring anything.** `git rev-list --count
   origin/main..HEAD` reads `1` whether you are one commit ahead of the current main or one commit
   ahead of a main that has since moved — it cannot see behind-ness. Compare the outputs of
   `git merge-base HEAD origin/main` and `git rev-parse origin/main`; if they differ, a sibling
   PR merged mid-increment and you must rebase onto `origin/main` first, or the review range is not
   exactly one increment. A rebase after this point discards every gate, seal and re-derived number
   below: restart this phase from here. Pushing a branch does not freeze its version claim: if a
   sibling PR merges, fetch again and re-run the profile's merge-time version gate (in `hoa`:
   `uv run --no-project --with-requirements scripts/requirements.txt python scripts/version.py check-revisions`)
   before asking for a merge. A repo whose profile declares no such gate skips it — never invent one
   and never skip one silently.
2. **Define the shipping increment.** Resolve the scope tool with
   `uv run scripts/gdd.py scope`, then read its recorded fact with
   `uv run "<scope-tool>" status --json --repo <path> --label <goal>`: `baseline.head` must equal the
   approved gdd review base. If a rebase onto newer `origin/main` moved the base, stop. Restart by
   preserving or resolving the original baseline dirt with the operator, taking a fresh snapshot at
   the new approved base **before** replaying the increment, and repeating review and the gates —
   never snapshot the shipping tip and never seal against a stale base. Phase 4 already committed
   the stage output to give the reviewer a range; this step seals the increment that ships, so it
   runs against the whole branch — every commit, including unit commits an accepted `ce-work`
   delegation made during implementation. Those commits are sealed with the rest, neither excluded
   nor re-committed as a separate increment, and the seal is not relaxed for them. Run `diff`; if
   `overlapping_paths` is non-empty, stop and ask the operator which writer owns each path — do not
   commit across it.
3. **Seal the intended index, then commit it.** Stage only the explicit goal paths — never
   `git add -A` or `git add .` — and run `uv run "<scope-tool>" seal --index --repo <path> --label
   <goal>`; an accepted overlap needs the operator's `--accept-overlap`. A failed seal stops the
   phase. Commit the sealed index with no path arguments and no `-a`; skip the commit when all
   changes were already committed. **Do not push yet**: verify the exact commit first.
4. **Verify the exact shipping commit before pushing.** Run `uv run "<scope-tool>" verify --commit
   <oid> --repo <path> --label <goal>` against the full commit that will be pushed. It recomputes
   the baseline-to-commit path set and each path's Git mode and OID from the commit itself, and
   walks `baseline.head..<oid>` for paths touched outside the seal, so the manual `git log
   --no-renames --name-status --format=%H <base>..HEAD` enumeration and the legacy working-tree
   check are no longer needed. Drift ⇒ stop, name the paths, and require either a re-review or an
   explicit operator acceptance recorded in the PR body. Record the verified full OID and push
   exactly that OID, not an unchecked moving ref; re-run this verification whenever the commit
   changes. Keep a fully expanded `git status --porcelain -z -uall --no-renames` inventory as a
   separate check for local leftovers — every uncommitted path stays out of the push and is
   reconciled with the operator before landing — and keep gating the shipping commit itself, in a
   clean checkout where the repo's profile requires one, since `verify --commit` reads Git objects
   only and cannot speak for the worktree. Do not move either check into `pr-merge-check.py`: that
   gate declares `Environment: none` and only judges the remote PR.
5. **Re-run the gates on the shipping commit.** Phase 2 gated the settled working tree; this run
   names the commit that ships, so record that SHA with the evidence.
6. **Check every number on the final tree:** every count, duration or table value in the PR body and
   the evidence record is re-derived on the final tree — never carried over from an earlier stage.
   Record the tree it was measured on (head SHA plus the sealed `scope_sha`).
7. **Optionally draft the body with a PR-writing skill, under gdd's contract.** Where the
   executing runtime's own skill discovery offers `ce-commit-push-pr` — never install it — check
   that the mode composes a body and prints it from the input it is given against the sealed range,
   with no authority to mutate a PR, commit, push or watch. Pass the sealed diff plus gdd's verified
   clause map, evidence and limits, and require the draft to describe exactly that input: a draft
   built from independently discovered input does not qualify. The draft is raw material for the
   body contract below, not a substitute: check it against that shape and the numbers re-derived on
   the final tree, and write the body from the recipe in [`references/pr-body.md`](../pr-body.md)
   directly when the mode is unsupported, the run failed, or the result is mismatched or
   incomplete. **Never run the skill's full shipping path**: it can push before the seal
   verification above and start a competing CI watcher. gdd keeps explicit staging with a no-path
   commit of the sealed index, the pre-push seal check, publication authority and its own CI watcher.
8. The PR body is a contract artifact — shape in [`references/pr-body.md`](../pr-body.md):
   what landed by subsystem, decisions with explicit non-adoptions naming the goal that owns them, one
   evidence table measured on the **final** tree, every "Done when" clause mapped to the command that
   observes it, and a **Known limits** section. Copy the previous goal's merged PR body as the starting
   shape rather than inventing one per goal.
9. **Publish from fresh probes, one direct call per probe.** Re-probe the branch, its target
   repository and any open PR immediately before the push, and again before opening the PR — an
   earlier snapshot is a hint, not ground truth. Give each probe its own process call: pass the
   program and its arguments directly and read that call's exit status; a semicolon list, a pipe, a
   substitution or a redirect exists only where a POSIX shell parses it, and fails outright under
   Windows PowerShell. Resolve the base repository first and push the head there explicitly. Query
   that repository for the unqualified branch name — the `<owner>:<branch>` form silently returns
   `[]` on a fork — and match the head owner and branch name, not the name alone. An exit-0 empty
   list (`[]`) means no open PR for this branch; a probe error is **unknown**, never "no PR" —
   resolve auth or connectivity, or stop rather than open a duplicate. Reuse the exact matching
   open PR; stop on an ambiguous or unknown PR state. Push the verified OID with
   `git push <remote> <oid>:refs/heads/<branch>` and open the PR as the operator's publication act,
   carrying the composed body. If a probe changes the candidate — a rebase or a
   moved head — restart from step 1, discard the gate, seal and number receipts, and redraft the
   body.
10. Treat PR checks as a floor, not a gate — Phase 6 decides.

## Pitfalls this phase answers

- **A commit message written through a shell heredoc containing `&` is treated as backgrounding.**
  Write the message to a file with the file tool and `git commit -F <path>`.
- **Never run the full gate chain twice on one commit.** If CI runs the whole chain, let CI print it on
  the pushed commit; if CI is only a light cross-OS check and the real gates live in the build harness,
  your local run is the only full-chain evidence and you run it on the final tree. One of them is the
  authority.
- **Re-measure the goal record's numbers on the final tree.** Fix rounds applied after the record was
  written leave it certifying an earlier tree — pass counts, bytes and digests all drift — so refresh
  them as the last step before landing.

Probe and drafting methods here adapt Compound Engineering (MIT, Copyright 2025 Every), paraphrased
rather than copied.
