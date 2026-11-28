# The shared git delivery engine: commands, reason keys, fixtures

Command-level contract for the one module every publish loop calls to land its snapshot on a remote. Pairs
with the parent skill's rule 13 and the direct-push variant — the same module serves a PR flow, which differs
only in the ref it pushes.

## Interface

`align <repo> [<branch>] [--report-only]` and `deliver <repo> [<branch>] [--no-reconcile] [--attempts N]`,
each printing **one** record (`--format shell` default, `json` on request) and exiting `0` ok / `1` refused /
`2` usage:

```
OK=1 ACTION=pushed REASON= BRANCH=main HEAD=<sha> REMOTE=<sha> BEHIND=0 AHEAD=0 PUSHED=1 ATTEMPTS=1
```

Callers `eval` the record, so validate its shape first and never eval anything else:

```bash
case "$out" in
  OK=1*|OK=0*) ;;
  *) OK=0; REASON=module-malformed; DETAIL="$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-120)"; return 1 ;;
esac
eval "$out"
```

A module that fails leaves the success field empty, so an unvalidated fallthrough is already a refusal. Reason
keys worth keeping distinct — each maps to a different operator action:

| key | meaning / action |
|---|---|
| `git-read-failed` | a git read (rev-parse/status/rev-list) failed — refuse; never treat as clean/0 |
| `git-fetch-failed` | cannot learn the remote's state — refuse rather than push on a guess |
| `remote-branch-missing` | the target ref does not exist on the push remote (per `ls-remote`) |
| `main-branch-guard` | the checked-out branch is not the target branch |
| `git-op-in-progress` | rebase/merge/cherry-pick/revert/sequencer marker present |
| `deferred-dirty` | dirty tree, nothing moved — the caller that commits first finishes the alignment |
| `dirty-behind` | the branch would have to move with a dirty tree — refuse, never rebase |
| `rebase-conflict` | conflict during rebase |
| `rebase-timeout` | the rebase exceeded its bound — roll back the same way, under this key |
| `rebase-abort-failed` / `rebase-abort-unconfirmed` | the rollback could not be performed, or could not be proven — always its own key, never folded into `rebase-conflict` |
| `push-denied` | permission/hook/policy refusal — **never retried** |
| `git-push-failed` | rejection that a re-fetch may clear (non-fast-forward) — retry once |
| `push-unverified` | the remote accepted (or cannot be read back) — `PUSHED=1`, and accounting follows |

## Align (read-only; never moves the branch)

```bash
git fetch -q <remote>
git ls-remote <push-url> "refs/heads/$branch"       # existence + the SHA the push will be measured against
git rev-parse --verify -q HEAD                      # failure ⇒ git-read-failed
git status --porcelain                              # failure ⇒ refusal, not "empty tree"
git rev-list --count "refs/remotes/$remote/$branch..HEAD"   # no `|| echo 0` anywhere
```

Behind and clean ⇒ `git merge --ff-only`; behind and dirty ⇒ `deferred-dirty`; diverged and clean ⇒
`git rebase`; diverged and dirty ⇒ `dirty-behind`. Markers that mean an operation is already in progress:
`rebase-merge`, `rebase-apply`, `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `sequencer`.

Verified rollback after conflict / error / timeout:

```bash
git rebase --abort                  # failure ⇒ `rebase-abort-failed` (report and keep failing)
test "$(git rev-parse HEAD)" = "$start_sha"     # else rebase-abort-unconfirmed
! git rev-parse --verify -q REBASE_HEAD         # markers cleared
```

Give the rebase a timeout, and make the timeout path run the same verified rollback: a rebase left in
progress is refused by every later run, so a timeout that skips the abort converts one bad run into a
permanent outage.

## Wedge: a dirty submodule pointer behind the remote

A repo that tracks its refs as submodules can wedge the engine with no defect on either side. The ref sync
leaves the submodule's working tree on a commit the branch does not record — neither `HEAD`'s nor
the remote's — so `git status --porcelain --untracked-files=no` is non-empty while the loop's own commit sits
behind the remote. The engine refuses to reconcile a tracked-dirty tree (`deferred-dirty`), the branch is
still behind, so it escalates to `dirty-behind` — and no later tick can clear it, because the one action that
would remove the condition is the action the engine declines to take. The loop goes silently stale while every
line it prints reads as an ordinary refusal; the tell is the *same* reason key on every tick.

Repair in place — no force, no history rewrite, the rebase moves only the loop's own unpushed commit:

```bash
cd <repo>
git status --porcelain                 # confirm the only entry is the submodule pointer
git submodule update --checkout <sub>  # restore the commit the branch records ⇒ tree clean
git rebase <remote>/<branch>           # now permitted; the rebase records the remote's newer pointer
git submodule update --checkout <sub>  # match the pointer the rebase just recorded ⇒ clean again
git status --porcelain                 # empty is the precondition deliver asserts
deliver <repo>                         # through the engine: push-by-id + read-back
```

Restoring the pointer **twice** is the step that is missed: it must match `HEAD` before the rebase (or the
rebase is refused) and again after it (or the tree is dirty against the newly recorded pointer). Note what
makes the wedge permanent — a wrapper whose idle exit tests "nothing staged" instead of
`git rev-list --count <remote>/<branch>..HEAD` strands the commit its own failed tick created: the next tick
finds nothing to stage, exits 0, and the unpushed commit is never offered to the engine again. Publish through
the module rather than a hand `git push` (a hand push lands the object but drops the read-back half of the
contract), and write the repair into the loop's own journal — the journal is what the next triage reads, and
an unexplained `dirty-behind` followed by silence re-diagnoses from scratch.

Prevent it at the source rather than triaging it: a repo that keeps a **materialised** ref worktree can
reconcile before the align ever runs — bring every *initialised* submodule to the gitlink the branch records,
and no further. Two constraints keep that safe: touch initialised submodules only (a bare
`git submodule update --checkout <path>` skips the uninitialised rest, so a pointer-only corpus stays
pointer-only) and let the update abort rather than discard local edits inside one. Never widen it into a
refresh — an upstream fetch or `--remote` inside the refs advances the worktree past the recorded pointer and
reproduces the dirty state this removes. The refs are read-only to the loop: the repo's own scheduled workflow
owns which upstream commit each pointer names, and the loop only follows it. Put the reconcile in the repo's
own wrapper as a pre-align step — not the shared engine (a repo-shape fact, keep the engine generic) and not a
git hook (per-clone, unversioned, and `post-merge` never fires for the rebase that actually moves the branch).

Prove the reconcile instead of reading it: `git -C <sub> checkout <older-sha>` (the exact drift that wedged
it), assert ` M <sub>` in `status --porcelain`, run the loop's own entry point once, and require the journal's
realign line, exit 0 and no refusal — then run it again and require a silent no-op. A reconcile that fires on
a clean tree (a rewrite every tick) is a different defect from one that never fires.

## Deliver

```bash
git push <remote> "$sha:refs/heads/$branch" --no-follow-tags --recurse-submodules=no
#   non-fast-forward     → git fetch, recompute, retry ONCE (`--attempts 2`)
#   denied by policy/hook → `push-denied`, stop, no retry
git ls-remote <push-url> "refs/heads/$branch"        # must equal $sha ⇒ else push-unverified, PUSHED=1
```

- **Push by object id, never by branch name.** `HEAD:refs/heads/<branch>` and `<branch>:refs/heads/<branch>`
  both let the ref move between the gate and the push, so the artifact that ships is not the artifact CI
  approved.
- **`--no-follow-tags` + `--recurse-submodules=no`** keep a repo's `push.followTags` / submodule settings
  from exporting refs the routine never intended to touch.
- **Read back from the push URL on the push ref, by SHA.** A `git fetch` of a differently-configured refspec —
  or of a different URL — is not proof that *this* push landed.
- **Existence is a remote question.** Decide `remote-branch-missing` with `ls-remote` on the push remote; a
  stale tracking ref makes the local state look synchronised when the branch is gone.
- **Accounting follows the remote.** A push the remote acknowledged has already mutated it: record the action
  floor *before* reporting the read-back failure, or the floor window can re-push. An up-to-date push
  (`PUSHED=0`) is not an action and must not burn the floor.

## Fixtures

Bare remote + two clones, with `git config receive.denyNonFastForwards true` **on the remote** so "cannot
overwrite the remote's history" is enforced by the thing under test rather than by your code.

- **Inject the race instead of hoping for it.** A `pre-push` hook (or a second clone committing) that
  advances the remote branch before the push runs gives a deterministic "remote advanced between fetch and
  push" — exactly the case where a naive read-back passes while a force would have destroyed history.
- **Prove only the target ref can leave.** Enable `push.followTags` and create a local tag; assert with
  `git ls-remote --refs` that the tag never appears. Without that setup the claim "we only push the default
  branch" is unfalsifiable.
- Scenarios that earn their keep: retryable refusal (non-fast-forward, retried once) vs non-retryable denial
  (policy, exactly one attempt offered and only the target ref); acknowledged-then-unreadable push (assert
  `PUSHED=1` and that the caller still records its floor); up-to-date push (`PUSHED=0`, floor not burned);
  rebase timeout ⇒ verified rollback; half-aborted rebase ⇒ `rebase-abort-failed`; dirty tree at both
  boundaries; `rev-list` failure ⇒ refusal rather than "no changes".
- **Drive the loop's own entry point** (the script the timer runs, not just the module) at least once, and
  publish the change through the pipeline it modifies; then verify with an independent `git fetch` +
  `ls-remote`/`ls-tree` read-back rather than the script's own exit code. Each manual run of a floored
  pipeline burns the floor — expected behaviour, not a bug.

## Review checklist (a fixture-green first draft still fails these)

1. gate/deliver binding — is the object the gate validated the object that ships (is there a read-only align
   between gate and push, and does nothing reconcile in that window)?
2. read-back from the push URL, on the ref, by SHA — not a fetch, not a branch-name grep.
3. any `|| echo 0` or unguarded `status`/`rev-parse` — does a read failure masquerade as "clean"/"0 commits"?
4. timeouts — does every path that can leave an operation in progress roll back *and* prove it?
5. retry breadth — is a policy denial being retried, or a broad `--attempts` default offered?
6. accounting — floor recorded on acknowledge, not on success; no floor burned on up-to-date.
7. `eval` — is the record's shape validated before the shell sees it?
8. ref exports — are tag/submodule pushes pinned off, or left to repo config?

Push/rebase/state logic is worth one cross-family review before landing: it is the class where a
plausible-looking draft is wrong in ways its own fixtures cannot see (each finding above is a real defect
that survived a green suite).
