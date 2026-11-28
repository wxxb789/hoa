# Acceptance-probing a shipped publisher

Prove a commit-and-push wrapper on the script that actually ships, by running its whole pipeline for real —
without the real remote, or the real repo, ever being the target.

## Harness: one bare origin, one local clone

```bash
PROBE=$SCRATCH/publisher-probe
rm -rf "$PROBE"; mkdir -p "$PROBE/state"
git init --bare -q -b main "$PROBE/origin.git"
git clone -q --local "$REAL_REPO" "$PROBE/work"          # hardlinks the real objects; real repo untouched
cd "$PROBE/work"
git remote set-url origin "$PROBE/origin.git"            # the probe must never reach the real remote
git push -q origin main:main
git checkout -q -B main origin/main
REAL_HEAD_AT_START=$(git -C "$REAL_REPO" rev-parse HEAD)
REAL_DIRTY_AT_START=$(git -C "$REAL_REPO" status --porcelain)
```

- Run the wrapper through its own env overrides (`<TOOL>_REPO`, `STATE_DIR`, and a log path override). A
  wrapper hardcoded to the production repo path cannot be probed at all: give it the override in the same
  edit that makes it probe-able, rather than testing a copy that has already drifted from what ships.
- **Assert on the wrapper's log line and on the remote ref, not on its exit code.** A wrapper may exit 0
  while delivering its `FAILED <stage>` line; `rc` alone cannot tell a refusal from a success.
- Close with the two real-repo assertions: `HEAD` unchanged, and `git status --porcelain` equal to the
  pre-probe value. A repo whose worktree already carried an unrelated dirty path (a submodule pointer, an
  in-flight scratch file) is normal — compare, never require clean.

## Case matrix

Each row is a different defect; all five together are what "the scope holds" means.

1. **In-scope candidate** → committed, gated, pushed; the pushed name list is *exactly* the candidate path
   (`git -C "$PROBE/origin.git" diff --name-only "$BASE".."$HEAD"`), and the worktree is clean afterwards.
2. **Dirt outside the scope** → the candidate still lands; the outside path appears in neither the pushed
   name list nor the commit, and is *still dirty locally*. This is the row that pins "the loop owns a path,
   not the worktree".
3. **Sensitive content inside the candidate** → the refusal line is emitted, `HEAD` is unchanged (the
   wrapper uncommits what its gate rejected), and the remote ref never moves.
4. **Shape violation** (name does not match its directory, missing required field) → the same three
   assertions as row 3.
5. **The remote has advanced** → a second clone (`git clone <bare> other`, commit an unrelated path, push)
   puts the local clone one behind; a legitimate candidate must still publish, with no false refusal. Then,
   on that same tree, demonstrate the diff-base defect by hand: the checker run with `--base <remote-tracking
   ref>` refuses (its finding names the base inversion), while `--base $(git merge-base <ref> HEAD)` is clean;
   `git reset --hard HEAD~1`, re-seed, and let the wrapper do it for real. A defect shown by hand and then
   absent from the shipped path *is* the evidence — a green probe alone is not.

## Contaminating the production log

A wrapper that resolves its log path internally writes its probe lines into the automation's own log, where a
later reader takes them for production pushes. Either point the log at a probe path through the same env
override, or append one dated line naming the probe window and the evidence directory. Never rewrite the log
to hide them.

## Pre-flight a gate that will judge the new file

A new script lands in a tree the *host* generates (a dotfiles/chezmoi source, a port or allowlist tree) and is
scanned by a gate that cannot be run against a working copy. Hardlink-copy the generated tree, add the file
under the name the generator will give it, and run the gate against the copy:

```bash
cp -al "$GENERATED_TREE" "$SCRATCH/precheck"    # instant, hardlinks
rm -rf "$SCRATCH/precheck/.git"
"$GATE" --repo "$SCRATCH/precheck"              # baseline: must match the last known-good verdict/count
cp "$NEW_FILE" "$SCRATCH/precheck/<generated-name>"
"$GATE" --repo "$SCRATCH/precheck"              # the file's own verdict
```

- **Only add files to a hardlinked copy — never edit one in place.** Editing an existing path through the
  hardlink writes into the real tree.
- Do this *before* the generator's next tick. A gate failure there surfaces days later as "the automation
  broke by itself", and the fix is one line in a file nobody connects to the failure.
- Read the gate's literal detectors before the run when the file is new to that tree, and grep the new file
  against them: the verdict tells you *that* it failed, the detector list tells you which class of literal to
  refactor into config.
