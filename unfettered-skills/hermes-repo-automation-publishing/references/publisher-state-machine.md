# Publisher state machine: cycle, state file, fixtures

Command-level detail for a scheduled routine that publishes into a shared repo. The PR cycle below is the
default for shared repos; **§ Direct-push variant** is the whole cycle for a repo whose operating contract
hands the automation its default branch. Pairs with the rules in the parent skill.

## The cycle

1. `git fetch origin` + fast-forward the local default branch (see the concurrent-repo skill for the peer
   checks that precede any write).
2. regenerate → prune (manifest-driven) → gate. A non-zero gate exit stops here: commit nothing, queue the
   finding for review, notify, exit non-zero.
3. local commit on the default branch (unconditional — a clean tree is what the next run needs).
4. floor check against the state file → hold (exit 0, one line) or continue.
5. `git push origin main:refs/heads/<branch>`; if the head branch has no open PR, `gh pr create --base main
   --head <branch> --title "<type>(<area>): <what> $(date +%F)" --body-file <tmp>`.
6. local CI on the committed tree (§ below). FAIL ⇒ queue + notify + exit non-zero, no comment, no merge.
7. PASS ⇒ post the `verify: CI pass（本地跑 <workflow>）` comment (the gate), `gh pr merge <n> --squash
   --subject <commit subject> --body <gate summary>`, then delete the head branch explicitly with
   `git push origin --delete <branch>` (`gh --delete-branch` also tries a local branch that a host-side
   automation does not have). Record `last_pr_state=MERGED`; the *next* run's merge detection refreshes main.
8. before the idle exit, ask the forge whether the head branch has an open PR (state file = cache, forge =
   truth): if one is open, this run owes a delivery — push the head if it is behind, run the gate, comment,
   merge, delete the branch. Skip the floor for that case (it is not a new action).
9. equal to the branch tip, nothing new to commit, no open PR → exit silently. This is the healthy idle path.
   With **no** head branch yet, "nothing new to commit" is not "nothing to deliver": a run the floor held
   already committed locally, so compare `HEAD` against `origin/<default>`
   (`git rev-list --count origin/main..HEAD`) before the idle exit, or that snapshot never ships.

State file (`<cache>/<name>-state.json`): `{branch, pr_number, last_action_at, last_pr_state, gate_sha}`.
`last_action_at` is written only by a successful *new* action (so a crashed run cannot burn the floor and a
resume does not refresh it); `gate_sha` is the head commit whose gate comment is already on the PR, so a
resume cannot post a duplicate. **`clear` keeps `last_action_at` and drops the rest** (branch, `pr_number`, `gate_sha`): the floor measures
the interval between *deliveries*, so a merge must not reset it — a `clear` that unlinks the file silently
sets the cadence equal to the timer period. Rebuildable from zero: losing the file costs at most one
duplicate comment and one unfloored delivery.

## The local-CI gate (when the forge's CI cannot run)

```bash
gh api "repos/{owner}/{repo}/commits/<sha>/check-runs"          # find the check-run
gh api "repos/{owner}/{repo}/check-runs/<check_run_id>/annotations"
```

A check-run that settled in ~1s with an empty `steps` list never ran; the annotation carries the reason
(billing / spending-limit stop, runner-image notice, allocation failure). Read it from the **annotations**
endpoint: on a job that never started, `output.title` and `output.summary` come back `null`, so a
"read the annotation" step that only looks at `output` silently degrades to a generic sentence. Prefer the
annotation that mentions billing/payment/quota over the runner-image notices that ride along, and fall back
to the base commit's check-run when the PR's own commit has none yet (the forge creates it seconds later).
If nothing is readable, say so in those words instead of inventing a reason. Then:

- export the **committed** tree — `git archive HEAD | tar -x -C <temp dir>` — and run the workflow's steps
  there, in order, one process per step, capturing stdout/stderr and exit codes;
- resolve `python-version` from the workflow file and pick an interpreter whose major.minor matches; verify it
  by running it. No match ⇒ fail the stage with `interpreter-pin-unmatchable` (never another minor); a missing
  workflow file ⇒ `workflow-python-pin-missing`;
- the credential-shaped tracked-file step reads `git ls-tree -r --name-only HEAD` (the committed-tree
  equivalent of the workflow's `git ls-files`);
- write one transcript per run (commit, pin, interpreter, both steps with output, verdict) and cite its path;
- on PASS post the comment, then merge; on FAIL post nothing and merge nothing. Keep `held`, `no changes` and
  `FAILED <stage>` as three distinct lines in the timer log.

The `--force-sync`/manual bypass belongs to the *floor* only: it must never skip this stage or the merge.

## Merge detection

```bash
gh pr list -R <owner>/<repo> --head <branch> --state all --json number,state,mergedAt,url
```

Newest entry `MERGED`/`CLOSED` ⇒ fetch, `git reset --hard origin/main`, `git push origin --delete <branch>`
(only when nothing is open), clear the branch/PR/gate fields and **keep `last_action_at`** so the action floor
survives the merge. Anything else ⇒ continue the current cycle. Read the PR
state from the forge, never infer it from a missing branch or a failed push.

## Direct-push variant (operating contract hands the automation the default branch)

The branch is the delivery target and the only ref the script may push. Command-level cycle:

```bash
git fetch -q origin                                   # always, before anything else
git ls-remote origin refs/heads/main                  # existence: a fetch does not prove the ref is there
git rev-parse --verify -q refs/remotes/origin/main    # unreadable ⇒ `git-read-failed`, never "in sync"
behind=$(git rev-list --count HEAD..refs/remotes/origin/main)   # no `|| echo 0`
ahead=$(git rev-list --count refs/remotes/origin/main..HEAD)
#   behind>0, ahead==0 : git merge --ff-only refs/remotes/origin/main
#   behind>0, ahead>0  : git merge-refusal check (git diff --quiet && git diff --cached --quiet), then
#                        git rebase refs/remotes/origin/main
#                        on failure/timeout: abort AND prove it (HEAD back at the pre-rebase sha, no
#                        REBASE_HEAD/sequencer left); queue `rebase-conflict` or `rebase-abort-failed`;
#                        deduped notify; exit 1
```

Then the unchanged middle: regenerate → prune → gate → staged guards → one commit per run. The idle exit is
`pending=$(git rev-list --count refs/remotes/origin/main..HEAD)` — exit `no changes` only when the run
committed nothing **and** `pending` is 0 (a held run's commit still ships). The floor reads the state file:

```json
{"last_action_at": 1700000000}
```

That is the **only** key this variant keeps (`--force-sync` bypasses the floor and nothing else; the local-CI
stage and the push always run). Delivery:

```bash
git push origin "$sha:refs/heads/main" --no-follow-tags --recurse-submodules=no
git ls-remote origin refs/heads/main    # must equal $sha; else `push-unverified` with PUSHED=1
```

Push the object the gate validated, by id — `HEAD:refs/heads/main` lets the ref move between the gate and
the push, so what ships is not what CI approved. A non-fast-forward rejection ⇒ re-fetch and retry **once**;
a permission/hook/policy denial ⇒ `push-denied`, no retry (no retry can succeed). Both leave the commit
local and the next run's fetch + rebase repairs the divergence. On success — and also when the remote
acknowledged but could not be read back, because the remote already moved — write
`last_action_at = int(time.time())` before reporting anything, and nothing else; an up-to-date push is not an
action and must not burn the floor. Failure keys worth keeping distinct in the queue: the gate/guard keys
unchanged, plus `git-read-failed`, `git-fetch-failed`, `remote-branch-missing`, `main-update-failed`
(ff-only failed, dirty tree with a rebase owed), `git-op-in-progress`, `rebase-conflict`,
`rebase-abort-failed`, `push-denied` and `push-unverified`. Full command set:
`references/git-delivery-engine.md`.

The local-CI stage is the same one as above (§ The local-CI gate) — same workflow resolution, same
committed-tree archive, one transcript per run — but there is no PR: the transcript path is the only
artifact and no `verify: CI pass` comment exists to carry the verdict.

Scenarios to pin in the fixture (hook inverted: **allow** the default branch, **refuse every other ref**;
a `gh` tripwire on PATH whose log must stay empty at all times). Set `receive.denyNonFastForwards=true` on
the bare remote so "cannot overwrite history" is enforced by the remote rather than by the code under test,
inject the fetch↔push race with a `pre-push` hook instead of waiting for one, and turn on `push.followTags`
with a local tag present to prove no other ref can leave — recipes in `references/git-delivery-engine.md`:

1. first change, not behind → exactly one push, of `refs/heads/<default>`; the remote advances to the new
   commit whose parent is the pre-push tip; no other ref on the remote; zero forge-CLI calls;
2. change inside the floor → `held`, remote unchanged, the snapshot committed locally, tree clean;
3. held change + remote moved → fetch, rebase onto the new tip, push; the pushed commit's **parent is the
   pre-push remote tip** (that is what proves rebase — a merge would have two parents, a force would have
   skipped it); nothing pending + remote moved + a fresh change → fast-forward onto the new tip first;
4. rebase conflict → `git rebase --abort` (assert no rebase in progress, tree clean, HEAD unchanged),
   non-zero exit, queue `rebase-conflict`, notify attempted, remote untouched; a repeat stays loud, keeps
   one queue entry, and the same-day notify is suppressed;
5. held then delivered → cycle 1 inside the floor commits and holds; cycle 2 regenerates **nothing** (after
   the window) → it must push that snapshot, not take the idle exit;
6. gate fail (unmatchable interpreter pin / missing workflow) → non-zero, no push, queue names the failing
   stage, transcript written;
7. push rejected (fixture injects a rejection of the default branch) → non-zero, **exactly one** push
   attempt offering **only** the default ref, no force, no fallback, queue + notify, remote untouched; once
   the rejection is gone the same commit ships;
8. credential/data-shaped file staged → refused and rolled back (index clean), nothing pushed; once the
   file is gone the next run stages/commits/pushes normally.

Assert `git ls-remote --refs origin` after **every** run (only the default branch may ever exist), and probe
the fixture's own hook once: a push of a non-default ref must be refused.

## Fixture harness

Under the task dir: `git init --bare` as `origin`, a shim for the forge CLI placed first on `PATH` that logs
its argv and answers `pr list` / `pr create` / `pr delete` from a file, and a stub for the regenerate+gate
steps. Scenarios to exercise with output kept:

1. first change, no PR → branch pushed once, `pr create` called once, remote default branch SHA unchanged;
2. second change inside the floor → `held`, remote branch identical, local tree clean;
3. change after the floor → same branch updated, **no second** `pr create`;
4. PR merged → reset to the new base, stale branch deleted, `clear` drops the branch/PR fields but keeps
   `last_action_at`; the next change opens a new PR **only after the floor expires** (not on the next tick);
5. push rejected (non-fast-forward) → non-zero exit, no force, nothing pushed to the default branch, queue +
   notify written;
6. local CI pass → `pr comment` called once with the marker as the first line, `pr merge --squash` called once,
   head branch deleted, remote default branch advanced **by the merge** (add a `pre-receive` hook that refuses
   any direct push to it — that is the claim the fixture must be able to falsify);
7. local CI fail (pin unavailable / workflow file missing) → non-zero exit, no comment, no merge, queue entry
   naming the failing step, notify written.
8. unfinished delivery: cycle 1 merge step fails once (shim returns non-zero) → non-zero exit, comment posted,
   PR left open, default branch unchanged; cycle 2 with **no new content** (and the floor inside its window) →
   resumes: no second comment for the same head, merges, deletes the branch, base branch advances, state
   `MERGED`; cycle 3 with the same input → `no changes`, exit 0, nothing posted, nothing merged.
9. held then delivered: cycle 1 inside the floor commits locally and holds; cycle 2 regenerates **no new
   content** (head branch still absent) → it must still push and open the PR, not exit `no changes`. Assert
   `git rev-list --count origin/main..HEAD` is what drives that decision, and that a merge does not reset the
   floor (cycle 3 with new content inside the window → `held` again).

Assert the merge's own commit sha equals the remote default branch sha after scenario 6, and that the *next*
run (scenario 6 followed by an idle rebuild) detects `MERGED`, refreshes the base and clears the state — a
same-cycle merge must not be assumed to clean itself up.

Assert `git ls-remote origin refs/heads/main` before and after each scenario: "it never pushed main" is the
claim the fixture exists to falsify.

## Notification dedup

Keep the last-delivered failure key (`{stage, exit_code, since}`) in its own state file so a persistent
failure notifies once and re-notifies only on a state change, and so a recovery is announced as recovery.
Notification state must be rebuildable from zero — losing the file must not silence the next failure.
Advisory findings dedup the same way but in a **separate** file keyed by a hash of the message: sharing the
failure file lets a warning overwrite the last-notified failure (silencing the next real one) and lets a
failure consume the warning's slot — exactly the masking the split exists to prevent. Both are one-line
`{signature, epoch}` records; a new signature re-alerts, a repeat is suppressed, and the log still carries
every occurrence.
