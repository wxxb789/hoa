# Delegated lane delivery: dispatch contract and acceptance of the lane's head

Depth for the part of the loop where a fresh head is produced by a delegated agent lane (OMP/Codex/pi-style
run) that the main session then reviews, gates and merges. The library skill for acceptance is
`delegated-work-acceptance`; the launcher mechanics live in `omp-headless-orchestration`. This file carries
the two things that cost a full phase when they are missing.

## 1. The dispatch prompt decides whether the phase exists

Put these clauses in the prompt file, not in chat:

- Every long command runs **in the foreground**; the run must never start a background job and then end its
  turn. Why: the phase then produces nothing that anyone collects — a child of the run's process group is
  killed mid-flight, while a child the launcher detached (its own session) survives and appends results
  after the phase has already been recorded as done. Either way the report stops mid-plan while the exit
  code still reads `0`.
- A hit tool timeout means re-issuing the command with a longer timeout, not backgrounding it.
- Name the deliverables that must exist before the run may stop: the committed **and pushed** head sha, the
  gate chain output with exit codes and counts, the written report at a named path, and an empty
  `git status --porcelain`.
- Name the out-of-scope set explicitly (no merge, no publication, no credentials, no other worktree) so the
  lane's write surface is checkable afterwards.
- **Round-specific rules ride in the rendered template, not in the chat message.** The stage templates have
  no placeholder for a round's own intent summary, binding standards or do-not-report list: copy the
  template root into the task directory, append those sections to the copy's `<stage>.md` under a heading
  naming the round, and dispatch with `--templates <that dir>`. The copy is rendered and archived with the
  run's prompt, so the round reads back later with its rules attached — a rule stated only in chat never
  reaches the lane.
- **A dispatch refused on the per-goal round cap is a bookkeeping fact, not a verdict.** The cap counts the
  goal's rows in the ledger across *attempts*, so an abandoned or re-scoped attempt has already spent them
  and the new attempt's first dispatch is refused. Pass the tool's over-budget flag and record the reason in
  that round's own report — which rounds belonged to the superseded attempt, why this is a different
  increment rather than a third round of the same one — because the ledger alone cannot tell them apart.

## 2. `exit=0` is not the deliverable

Read the run's own trailing text (`answer.md`) before accepting the phase. A run that ends its turn with
"waiting for the gate" and a clean exit has produced a commit and nothing else. Verify each named
deliverable yourself:

```bash
cd <worktree> && git status --porcelain           # empty?
git fetch -q origin && git rev-parse HEAD origin/<branch>   # equal? a commit without a push is local-only
ls <report path>                                   # exists? the artifact the prompt named
```

A commit that was never pushed, a gate run that never happened, and a missing report all look identical to
a finished phase from the exit code alone. **Read the diff's file list against the round's declared surface before
anything else** (`git status --porcelain`, `git diff --stat`): a round that declares "both files lost the claim"
and touches one, or edits a path outside its scope, is a claim to correct in the report before its green counts. When the deliverables are missing but the work is sound, take
over the mechanical remainder (push, run the gate) rather than re-running the lane: the code is already in
the tree, and re-dispatching risks a second author on the same paths.

**A lane that parked a measurement leaves live evidence behind — harvest it before re-running anything.**
When the trailing text names a background job ("mutation pass ~3/28 running", "waiting for the third timer,
no action needed"), treat the named work as an unfinished deliverable and check whether the job is still
alive (`pgrep -af <driver>`); the rows it has already written are as valid as if the run had collected them.
Copy the runner and its raw output out of the scratch path into the task's evidence directory (`/tmp` and
per-run temp dirs are pruned), count what applies from the raw rows rather than from the lane's summary,
and continue in the lane's own session (`--resume <session-id>`) with a prompt that repeats the foreground
clause and lists the remaining steps in order — a fresh run re-pays for work already on disk.

**A test-side round is accepted by case name, not by count.** A fix that adds a fixture can delete a pin in the
same edit: the count grows while coverage falls, and the round's own summary still reads "116 → 118, pure
addition". Diff the case sets yourself, against the head the previous round reviewed:

```bash
git -C <worktree> worktree add --detach "$S/prev" <previous-head>
(cd "$S/prev" && python3 -B <focused case file> -v) | grep -oE '^[a-zA-Z_0-9]+ \($' | sort > "$S/prev.txt"
(cd <worktree> && python3 -B <focused case file> -v) | grep -oE '^[a-zA-Z_0-9]+ \($' | sort > "$S/now.txt"
comm -23 "$S/prev.txt" "$S/now.txt"   # empty = nothing removed
comm -13 "$S/prev.txt" "$S/now.txt"   # what the round actually added
```

An empty `< only` column is the fact; the lane's "no removals" sentence is a claim. Park the comparison worktree
outside the tree under review and `git worktree remove` it afterwards, so the next reader's
`git worktree list` still localizes branches. The same read also settles "the fix's cases reference symbols the
base revision does not define": the previous head's run dies at collection, which is a traceback rather than a
summary line — *the symbol exists, the assertion never executed* — and the pin check then has to be finished with
your own targeted mutation.

**Revert the implementation only, and verify the restore by hash.** On a round that left its work in the
tree (the dispatch contract reserves commit and push), the pre-fix implementation is at `HEAD:<path>`: copy
the file aside, write the base version over it (`git -C <worktree> show HEAD:<path> > <path>`), run
**exactly the new cases, one invocation each** so every red is attributable, require the pre-fix signature
in the assertion's own text, then restore from the copy and confirm the file's `sha256sum` returns to the
value you recorded. Do not settle for `git diff --stat` returning to the round's numbers — equal line
counts hide a byte change — and prefer copy-and-restore over `git stash` when another process (a gate, a
lane) may be reading the same worktree. A name filter runs one case without package import paths:
`python3 -m unittest discover -s <tests dir> -p '<case file>' -k '<case-name substring>'`.

**Your own targeted mutation, written so the file still parses.** When the pin cannot be settled by the
revert (the case references a symbol the base revision lacks), replace the call the case pins with a
constant and change nothing else, tests included — a regex substitution is enough
(`re.subn(r'probe\.unlink\([^)]*\)', 'None', src)`) and it keeps the module importable, so the red is the
assertion rather than a syntax error. Run the same single-case command, quote the case's own message, then
restore the original bytes and re-check the sha256 before any of it goes in the report.

**A claimed production-only mutation is re-probed with the test files byte-identical to the reviewed head.**
Copy the tree (symlinks preserved, `shutil.copytree(..., symlinks=True)`) to a scratch path **outside** the
worktree — a fix lane or a gate may be reading it — replace the one production line by exact string, and check
`git diff --stat` (or a recursive hash of the test file) before running: one changed file, and it is not a test
file, or the red you are about to quote came from your own edit. Run the focused case file, require `FAILED`,
and quote the assertion's own text (`'0' != '114038516'`) as the signature: a mutant that reds on an unrelated
case proves nothing about the pin.

## 3. Get the completion signal back

A headless lane pings nobody when it ends. With a systemd-hosted run (`--backend systemd`) the notification
can be bought back cheaply: launch a bounded watcher as a background job of the orchestrating session and
let its completion notify you.

```bash
while systemctl --user is-active --quiet <unit>; do sleep 15; done
```

Wrap it in `timeout <max-time + slack>` so a stuck unit cannot leave the watcher alive forever, and keep the
lane itself independent of the watcher. The watcher reports only that the unit ended; every claim about
what the lane produced still goes through §2.

## 4. The review prompt you write yourself

When the review lane is one you prompt directly (a CLI/API lane, or a PR that never entered the delivery
loop), the prompt is the contract for what counts as a verdict. Five clauses belong in it:

- **The axes, named, one verdict per axis over the frozen diff.** When the increment rewrites a gate's
  parse or mapping layer, the first two axes are fixed: (i) does the new mapping preserve the previous
  verdict semantics exactly — is any state now counted as success that should block, or silently dropped
  instead of blocking; (ii) fail-closed on unparseable output, empty output, a missing tool, and zero
  inputs. Test strength then gets its own axis, phrased as the mutation question: for each new test,
  would a plausible wrong implementation still pass it — name the mutation that slips through.
- **Report-only, stated as an instruction *and* enforced by inspection afterwards.** "Do not modify files,
  commit, post to GitHub, read credentials"; then check `git status --porcelain` in the reviewed tree
  before the verdict counts.
- **The verdict's machine-readable shape, verbatim** — the JSON the evidence tool consumes (the reviewed
  head sha plus the findings list/flag). Without it the report is prose and cannot become a marker comment.
- **Evidence hygiene.** The report becomes a posted comment: forbid absolute host paths, local session
  ids and internal channel names in it, so the reviewer quotes `path:line` inside the repo instead of the
  operator's filesystem.
- **When the round is the series' closing one, ask for two levels and require them separately: BLOCKING
  (shipped behaviour — a fail-open, a wrong verdict or exit-code contract, a document that contradicts the
  code) and RECORDED (coverage depth — a regression today's cells do not pin).** "Judge on two levels and
  separate them in your answer", plus what happens to each: recorded items go to the backlog file, blocking
  items stop the merge. Name the artefacts the series has accumulated (cell/mutation/probe counts, the live
  fixture set) so the round grades the current instrument instead of re-deriving it.
  The split changes what *blocks*, never whether a finding is fixed: a coverage item is still fixed before
  the marker may read clean (see the `code-review-gates` rule on test-completeness findings). Never send the
  level split as "feel free to ignore anything that is not blocking" — a prompt that raises the bar for
  BLOCKING without raising it for RECORDED returns a clean round that closed nothing.

Require the explicit sentence (`NO ACTIONABLE FINDINGS`, or `path:line` + impact + minimal fix per finding),
because a report that lists nothing because it was truncated or aborted otherwise reads exactly like a clean
one.

## 5. Resuming a series whose round stalled before landing

The failure shape: the dispatch contract reserves commit and push to the operator, so a fix round finishes
**by design** with the increment applied and the worktree dirty. If the orchestrating session ends before
landing it, the phase is recorded `done` with exit `0` and a full report — and nothing downstream ever reads
the tree. The stall is invisible in the ledger and only visible in the worktree:

```bash
git -C <worktree> status --porcelain        # the increment, still uncommitted
git -C <worktree> log -1 --format='%h %ad'  # the head the report's range was computed against
```

Recovery is a fixed order, and each step is what makes the next one possible:

1. **Diff the dirty path set against the round's findings file.** The prepared tree must be exactly the
   increment those findings named; a path nobody's findings mention is a second author, and the review that
   follows would grade their work as yours.
2. **Re-run the gate chain yourself, and report it as your run.** The numbers in the stalled report are
   claims about a tree that may have been written to since, and an interrupted session is exactly when the
   chain was never actually re-run.
3. **Commit and push before dispatching anything downstream.** A review is dispatched at a commit: the
   harness asserts `HEAD == --head`, builds its diff from that head, and the reviewer's marker names a sha
   that must exist on the remote.   Reviewing a dirty tree reviews nothing, so "verify" here means verify then
   land, not verify then queue. **Stage it before you commit:** the lane's output is unstaged by design, and
   `git commit -F <msg>` with nothing staged **exits `0` having committed nothing** — the push that follows
   then reads as success (`Everything up-to-date`) while the head never moved. `git add -A` (or `commit -a`)
   first, then assert the landing in three reads: `git rev-parse HEAD` is a new sha, `git status --porcelain`
   is empty, and `git ls-remote origin <branch>` equals local.
4. **Continue at the next round number, and put the new head sha in the prompt.** The previous round's
   verdict describes the previous head; a resumption that forgets to state the round and the sha leaves the
   series with two rounds of the same name and a verdict nobody can attribute.

Resuming a stalled series is its own report line — what the phase claimed, what the tree actually held, what
was re-verified, and the sha it landed as — because the next reader's ledger still says `done`.
