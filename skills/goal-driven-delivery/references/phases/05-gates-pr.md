# Phase 5 — gates, commit, PR

1. Re-run gates on the exact tree you ship.
2. **Before committing, define the working increment.** `worktree-scope.py diff --repo <path>
   --label <goal>`, then `seal`. If `overlapping_paths` is non-empty, stop and ask the operator which
   writer owns each path — do not commit across it.
3. Commit with explicit paths; push; open the PR.
4. **After committing, verify the sealed scope.** `worktree-scope.py verify --repo <path> --label
   <goal>`. Drift ⇒ stop, name the paths, and require either a re-review or an explicit operator
   acceptance recorded in the PR body. Do not move this check into `pr-merge-check.py`: that gate
   declares `Environment: none` and only judges the remote PR.
5. **Check every number on the final tree:** every count, duration or table value in the PR body and
   the evidence record is re-derived on the final tree — never carried over from an earlier stage.
   Record the tree it was measured on (head SHA plus the sealed `scope_sha`).
6. **Before opening the PR, prove the branch is not behind main.** `git rev-list --count
   origin/main..HEAD` reads `1` whether you are one commit ahead of the current main or one commit
   ahead of a main that has since moved — it cannot see behind-ness. Check
   `test "$(git merge-base HEAD origin/main)" = "$(git rev-parse origin/main)"`; when it fails, a sibling
   PR merged mid-increment and you must rebase onto `origin/main` first, or the review range is not
   exactly one increment.
7. The PR body is a contract artifact — shape in [`references/pr-body.md`](../pr-body.md):
   what landed by subsystem, decisions with explicit non-adoptions naming the goal that owns them, one
   evidence table measured on the **final** tree, every "Done when" clause mapped to the command that
   observes it, and a **Known limits** section. Copy the previous goal's merged PR body as the starting
   shape rather than inventing one per goal.
8. Treat PR checks as a floor, not a gate — Phase 6 decides.

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
