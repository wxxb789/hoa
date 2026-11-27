---
name: mechanical-gate-design
description: Use when a gate must not pass a degenerate input.
version: "0.1.0"
metadata:
  version: "0.1.0"
  areas: "software-development"
  targets: "runtime-agnostic"
  summary: "gates that hold on degenerate inputs: empty sets, page 2, commit spellings, unbound verdicts, human-written records"
  summary_zh: "门禁在退化输入下才见真章：空集、第 2 页、同一个 commit 的多种写法、未绑定的裁决、靠人写的记录"
  kind: "entry"
  hermes:
    tags: ["gate", "merge", "verification", "fail-closed"]
    related_skills: ["delegated-work-acceptance", "verification-probes"]
---

# Mechanical gate design

A gate is the last thing between a claim and a merge, a publish or a delete. Every rule below is a shape
that lets a broken input through while the gate prints green. Apply them in order when writing a gate; use
the same order when auditing one.

## When to Use

- You are adding a pass/fail decision to a pipeline: a merge gate, a publish guard, an integrity check, a
  "nothing left to fix" condition.
- A gate reports clean on something you doubt, or a review bot just found a hole in one you shipped.
- You are accepting someone else's gate and need the shapes to probe before trusting its green line.
- Not for test-suite design (a test asserts behaviour; a gate decides an irreversible step), and not for
  judging a document's content.

## 1. An empty result set is not a pass

`pass = pending == 0 and failing == 0` is `True` for zero checks. The same shape appears as zero matching
rows, zero unresolved threads, zero findings, zero files in a glob. The empty set is produced by two
different worlds — "nothing is wrong" and "the query never ran" — and the gate cannot tell them apart.

- Refuse the empty case by default. Accept it only behind an explicit flag that names the intended state
  (`--allow-no-checks`), never as a silent default.
- Put the reason in the verdict (`no checks`), so the operator knows which world they are in.
- A tracker that dispatches no workflow at all (a conflicting PR, a path-filtered workflow) is the common
  producer of the empty set — exactly the input that must not merge.
- **A read that failed is not an empty set.** `except Exception: return {}`, a missing parser, a truncated
  or malformed file: the gate then reports zero of everything from the wrong world. Fail loudly with the
  path and the reason, and keep a fixture whose malformed input proves it stops.
- **A suite that ran zero tests is the same empty set one level down.** A scheduling gate that accepts
  "Ran 0 tests", a filter that skips everything, or a self-asserting suite printing its own PASS having
  executed no checks reports green from the world where nothing matched. Require a positive count from every
  suite the gate declares; let a newly discovered, unpinned test be a warning while a set that shrinks
  below a pinned floor is a failure — the floor is what turns a vanished check into a red line.
- **An arm that accepts any failure as its expected failure is vacuous, and it passes hardest where it
  matters.** A check that reads "the dependency refused" off *any* error — any nonzero exit, any exception, any
  `error` field — is green for a crash that has nothing to do with the input it planted: a malformed request, a
  missing argument, a rejected handshake all satisfy it, so the arm reports proof it never took. Require the
  failure to name the thing the arm planted (the id, the path, the token it wrote), leave every other error a
  not-PASS in its own words, and keep a control case whose error names nothing that must not read as the
  expected refusal. The report side matters as much: "the dependency refused it" printed from an unrelated
  error is a false positive the next reader takes as verified coverage.

## 2. Any list endpoint is truncated until you paginate

`first: 100`, `per_page=50`, "recent comments" — each has a page 2. A gate reading page 1 reports zero
unresolved items while item 101 is still open.

- Follow `pageInfo { hasNextPage endCursor }`, or loop `?page=N` until a short page arrives.
- Prefer the paginated API over a CLI convenience view: `gh pr view --json comments` truncates on a large
  PR where the paginated REST comments endpoint does not.

## 3. Compare identifiers by resolving them, not by string prefix

One commit has many spellings (`HEAD`, `HEAD~1`, a branch, 7 or 40 characters).

- `head.startswith(marker_sha)` accepts a 4-character marker as a match. Require a minimum length and a
  two-way prefix (>= 7 chars) in one shared helper.
- `base == head` as raw strings misses `--base <full sha> --head HEAD`, which is one commit written twice.
  Resolve both through `git rev-parse --verify --quiet` first, and keep the literal when git cannot resolve
  it (a SHA from another checkout, or a synthetic fixture).

## 4. Bind the verdict to the thing you verified

- A check result belongs to one tree: record the head SHA it ran on and refuse when the artifact has moved
  since (marker `commit_sha == headRefOid`, `--verified-head`), rather than accepting an older green.
- A report-only step (review, audit, scan) consumes the head it was dispatched against. When a later step
  backfills "current HEAD", the report step must keep the reviewed value — otherwise the record claims a
  review of code nobody read.
- **Enumerate the reviewer's open threads yourself, following pagination (§2).** A first-page query of a
  review with 40+ threads reports zero unresolved while two sit on page 2; the truncation a gate forbids
  elsewhere applies to the check you run by hand too.
- **Separate the reviewer's round snapshot from still-open work.** A summary marker
  (`has_any_findings`) describes the round it was written for: after you fix and resolve that round's
  findings it still reads true, and the next round re-raises the same text as a new thread. The
  authoritative pair is unresolved threads == 0 **and** a marker whose SHA equals the current head.
- **A push does not re-trigger a bot reviewer.** Post the explicit review request after each push and wait
  for the marker to name the new SHA; reading "no new marker" as clean merges on the previous head's
  verdict.
- **A pull-request-level check list is not bound to the head you are watching.** `gh pr checks` answers for
  the pull request, so for the first seconds after a push its rows still belong to the PREVIOUS head: the
  same read reports a red on a head whose CI has not started, and an all-green on a head nobody tested.
  Refuse both directions — a red counts only when this head carries a failing run, a green only when this
  head has completed runs and none failed — by reading the commit's own check runs
  (`gh api repos/<owner>/<repo>/commits/<sha>/check-runs`) until they agree with the watcher. An
  unreadable list is unknown, never agreement. A watcher's own head test does not cover this: it compares
  the PR's `headRefOid`, which updates the instant you push, while the check list lags behind it.
  Fix it in the **shared read every caller uses**, not in one consumer: a guard patched into the CI watcher
  leaves every other reader of the same list answering from the previous head, and the reader that must not is
  the merge gate, where that green authorizes the irreversible step. When two scripts read the same list,
  repair the read once and delete the per-caller guard.
- **An unattributed verdict spends a real budget, and the spend is invisible.** A red attributed to the
  wrong head consumes a repair round; where rounds are bounded, exhaustion then writes a block for an
  event that never happened, and the block is read as a real signal. Bound the unattributable polls too,
  so the outcome is a named block rather than a loop.

## 5. The machine writes the record, not the operator

A row written later from memory is a row that does not exist.

- Give the action a verb that lands the fact (`close --pr N`) instead of documenting "remember to append".
- Backfill what the action changed (post-run HEAD) and keep what the check consumed (reviewed HEAD).
- Empty columns are the tell: a field that is `-` in every row was never populated by any code path. Check
  the record's own history when deciding whether a protocol is followed.
- **A snapshot kept as evidence must record values, not labels.** An inventory of alias *names*, provider
  *keys* or catalog *entries* is byte-identical before and after a real change (an alias repointed, an
  endpoint moved, a provider disabled), so it certifies a change it never saw. Record the values that can
  change, and add a fixture that changes one and asserts the two snapshots differ.
- **A document that asserts its own verification is a data structure, not prose.** An evidence or obligation
  matrix whose rows are sentences ("this test pins that rule") can only be checked by reading, and a reader
  model asked to audit prose returns the same class forever — a claim stronger than the evidence it cites,
  every finding landing inside the previous repair's own wording. That loop is the *instrument*, not the
  increment: make each row a tuple the gate can resolve (obligation id → test id → the command that was
  executed and its recorded result) and have one script refuse per row when the citation does not exist,
  when the named test does not pass, or when the row's mutation was never executed. Land that change as its
  own increment — it changes what "passing" means, which is an owner-facing gate-rule change and must not
  ride inside the increment it would have judged. Recipe for the manifest, its per-row checks, its required-step
  semantics and its honest boundary: [`references/structured-citation-manifest.md`](references/structured-citation-manifest.md).

## 6. Make the guard pure, then unit-test the matrix

A guard buried in a CLI handler is tested only by accident.

- Extract the decision into a pure function returning the refusal reasons
  (`problems(stage, contract, dirty, base, head, force) -> list[str]`), and test each refusal, the
  override, and the legitimate pass.
- When a new guard breaks a fixture suite, give the fixtures an explicit escape (`<AREA>_GUARDS=off`,
  documented as test-only) instead of weakening the guard or rewriting every case — rewriting fixtures
  deletes the scenarios they were guarding.
- **Prove each rule by mutating the implementation, not by reading the assertion.** For every rule the
  code documents (counting, trimming, delimiter pairing, rounding, classification), apply the mutation
  mutation that violates exactly that rule and require the suite to FAIL. A mutation that leaves the suite green
  means the fixture does not pin the rule — close the gap before committing, because that green is what the
  next regression hides behind.
- **A stopping rule is proved on the failure that motivated it, plus the controls that must not trip it.**
  A predicate deciding when a loop stops (a growth threshold, a findings trend, a budget) is a gate, and the
  evidence it works is the *recorded input it was written for*: replay the failing run's own telemetry and
  require the trip at the round it should have fired on — the run that burned to the old cap must trip at round
  2, not at the cap — then run the controls in the same probe: a converging series, an empty artifact, a single
  round, each required to return **no** trip. Without the controls, a rule that fires on everything passes as a
  rule that fires on the failure. Define the **degenerate first input** explicitly: a comparator that reads its
  predecessor has no previous value on the first round, so the naive subtraction either raises or reads the
  absent predecessor as unbounded growth and trips on a legitimate round —  give that row its own case.
- **A threshold measured against a baseline that moves with the input needs an absolute companion, or it fires
  on the small increments and only on them.** A relative stopping rule (grow more than X% over the previous
  round) divides by its own subject: the pathology it was written for added tens of KB per round, while a
  legitimate 30 KB documentation increment that gained one test file is already +25% — so the rule trips on
  the benign run and blocks exactly the round where the loop was closing, then never fires on the shape it was
  built for. Require **both** a relative and an absolute trigger before the rule fires, set the floor from the
  observed size of the real pathology, and re-probe in both directions after the change: the history that
  motivated the rule must still trip at the same round it always did, and every legitimate increment size the
  series produces must return no trip. State the floor's unit in the artifact's own terms (bytes, files,
  lines) — a threshold you cannot say in those terms is the one that will misfire.
- **Calibrate a stopping rule against every run of both classes you already have — not against the failure
  that motivated it — and separate the classes on shape, not on a scalar.** Replaying a candidate rule over
  the whole historical corpus (the runs that converged and the runs that did not) routinely kills it: scalar
  magnitudes interleave the two classes, so a series that converged in twenty rounds over a 1.2 MB diff sits
  far *above* a divergent one at 300 KB, and any threshold placed between them by eye fires on the healthy
  increment while never firing on the pathology. Prefer the signals that describe **shape**, because they are
  what actually differ: whether the findings' severity is falling or rising, whether this round's findings land
  inside the files the previous round's repair touched (a fix editing its own verifier or its own newest helper
  is the signature of a loop that cannot close), and whether the outstanding set is shrinking. Ship a retired
  rule **with the history it would have blocked attached** — quote the corpus row a rejected scalar rule would
  have wrongly stopped, or the next reader re-derives the same simple rule and blocks a run that was closing.
- **Two stopping rules that overlap are one rule plus a dead constant — say which is which before shipping
  the pair.** A predicate that fires unconditionally at N rounds (`round > 6 -> block`) puts every higher
  bound out of reach: a `MAX_ROUNDS = 12` beside it decides nothing, and the second tier it was meant to
  backstop (a further audit round, a self-continue allowance) never executes once, so a mechanism the report
  describes as live is unreachable code. Decide the split explicitly and write it down — the signal
  predicates (growth, trend) are the rule, the round count is where the rule terminates, and a constant above
  it is a backstop only for the case where the rule is deliberately disabled — then either make the replaced
  tier reachable or delete it together with the branches that read it. Probe both directions: the run that
  must trip, and a configuration where the backstop is the only thing left stopping it.
- **Freeze the oracle before the implementation it judges, and make the freeze mechanical.** When one loop may
  edit both the code under test and the checker that certifies it, rounds can read as converging while the
  property degrades: the checker's rules move with the implementation, so a diff-shaped gate sees repair where
  there is co-mutation, and the acceptance verdict afterwards describes no tree that ever existed. Order the
  work so the checker lands **first**, as its own increment, with its own fixtures — each rule carrying a
  mutation that turns it red — and with no change to the implementation at all. State in the checker's own file
  that it is frozen for the remainder of the series, and give the pipeline a signal that blocks a round whose
  diff touches it; the lock is what lets every later "the artifact is well-formed" claim mean something.
- **An assertion that cannot fail is not a pin, and a rewrite can delete one without moving the count.**
  The expected side must come from the contract's own literal, never from the collection under test:
  `assertEqual(len(set(d)), len(d))` on a `dict` is true for every input — `set(d)` is built from `d`'s own
  unique keys — and a dict literal assembled out of the constants under test whose values are never read
  asserts nothing about them. So when a round rewrites an assertion (usually to "add coverage"), name the
  input that would now make it fail; if no such input exists, the round deleted a pin while the test count
  stayed the same, and the value it stopped comparing — a constant's documented string, a mapped word —
  drifts undetected. Two more shapes of the same failure: the expected side is **the constant the
  implementation writes with** (`assert kind == <writer's own symbol>`), so writer and assertion rename
together and the check can never leave the implementation's spelling — pin the value from the external format
  or the spec instead; and a case that **passes the expected outcome into the call under test**
  (`continueDocumentOf(..., exitOK)`) asserts its own argument rather than the command's, which is how a case
  reports success over a run that actually failed — read the status the command returned and confirm the
  case's own setup is the one its name claims. Require the exact expected value back, one assertion per rule, and mutation-prove it.
- **A mutation that could not be applied is not a mutation.** When the patch's literal no longer matches
  the source (`SKIPPED-patch-not-found`, an empty application list, a rule name absent from the driver) the
  tree runs unmutated, so that row's green proves nothing about the rule — count rows that were *applied
  and failed*, never rows emitted, and treat the skipped row as an open gap: re-derive the patch against
  the current text, and when the text the rule claims no longer exists at all, that is a document defect
  to fix before it is a test gap. Read an unapplied row in neither direction: it shows neither that the pin
  holds **nor** that the pin is missing, and a green from a patch that never landed is how a working pin
  gets recorded as decoration, quoted, and re-dispatched as a repair — grep the literal you are about to
  replace out of the file's own bytes, re-derive the patch from them, and re-run before either verdict is
  written. **The mirror shape is a mutation that applied while the verifying command
  selected nothing.** A test-runner filter that names a case which does not exist exits `0` on an empty
  selection (`go test -run <name>` over a typo prints `no tests to run` and passes), so the mutated tree
  reads as a mutation nobody detected and a working pin gets recorded — or discarded — as decoration when it
  was the probe that never ran. Name the selector from the tree (grep the case's own function) rather than
  from memory, and require a positive test count in the probe's own output before either verdict is
  recorded. **Take the suite's own invocation out of the gate source too** (`grep -n unittest <gate>`, the CI
  step's command, the project's runner target): a discovery or filter command assembled from memory can die at
  collection — an unimportable start directory, a missing package marker, a runner whose top-level flag
  disagrees with the layout — and print no summary line at all, which a battery that reads summary lines
  records as a row nobody disputed. Budget the series as one full suite run per rule, serialized against the
  suite it mutates (a 117-case suite is ~80 s, so ~27 rules is ~40 min): run it detached and land the raw
  rows in the task's evidence directory — the rows are the evidence, a summary table is not.
- **Serialize a mutation against every other reader of the same tree, and make the restore the thing you
  recorded.** A gate run started while the tree carries a mutation reports on bytes nobody will merge, and
  the probe's result and the gate's result become unreadable together — restore, then re-run the gate alone,
  and re-derive the probe in the same pass instead of reading the overlap as evidence either way. Run the
  mutation from a script whose restore is unconditional (`try/finally`; or keep the round's cases and put
  back the implementation with `git stash push -q -- <impl paths>` / `git stash pop`, named paths only, so
  the tests stay) rather than from a heredoc: a shell killed mid-mutation — an interactive timeout, a dropped
  session — leaves the tree mutated, and the way back is re-writing the exact bytes you hashed before
  mutating and comparing that hash, which is also what lets a later process, or the acceptance matrix that
  recorded the pre-mutation hash, verify the restore happened.
- **A probe does not share a tree with work you have not committed.** `git restore` / `git checkout --` as a mutation
  rollback also wipes whatever else was uncommitted in those paths, and the next `git add -A` commits the wiped state —
  a green gate over half a fix, caught only by a later reader. Run the probe in an ephemeral worktree of the head
  (`git worktree add --detach <dir> <sha>`), or commit before probing; and before pushing, compare the staged diff
  against the list of files the round was supposed to change. When it has already happened, the lane's own run
  record still holds the work — replay procedure in skill `concurrent-agent-repo-workflow`.
- **"Detached" means its own unit with an exit code you can read — not a background child of the stage that
  started it.** A transient unit (and any `KillMode=control-group` unit) kills the processes left in its
  cgroup when it finalizes, so a mutation series or gate started with `&`, `nohup` or a background job
  inside the authoring stage's own unit dies at that stage's exit, while the report still says the series
  is running. A green with no rows is §1's empty set wearing a third hat. Launch it with its own unit id
  (`systemd-run --user --collect --unit=<name>`) or poll the launcher's state file, and re-read the rows
  *after* the window — the starter's exit status is the one reading that always looks healthy. When that
  starter is an agent lane, **the unit belongs to the orchestrator, not the lane**: a lane whose last act
  is to launch the series and end its turn leaves a `done` over an empty evidence directory, so read the
  rows and then run the series yourself — re-dispatching a replacement lane for a command you can execute
  is the slowest route to the same evidence and adds a second claim to verify. Name each verification step
  in the dispatch as awaited-to-completion or as yours, or the next lane backgrounds it too.
- **A fixture whose expected value two opposing implementations both produce pins neither.** The traps,
  all seen in one small file: an inequality (`full_lines > body_lines`) that an off-by-one still
  satisfies — assert the exact value; **a bound assembled out of the inputs** (`head + cap + len(record)`)
  can sit above everything the input is able to produce, so the implementation that never enforces the rule
  passes it too — derive the exact expected value from the contract and name the implementation that must
  fail the assertion, since a limit nothing can reach is not a limit; a sample count that makes the rank integral (a `p90` over ten
  values) so `ceil` and `floor` agree — choose a size with a non-integral rank or a hand-computable
  small case; a fixture asserting only a final total, where one wrong item exposed and another wrongly
  swallowed cancel out — one fixture per rejected form, each ending at the construct under test so
  nothing can cancel.
- **An invariant about a live value is asserted after every mutating operation, not sampled at the end.**
  "The file never exceeds the ceiling" checked once after the last write measures the settled state: an
  implementation that rides above the ceiling between its rewrites and lands back inside it by luck passes,
  which is the one shape the assertion exists to catch (assert inside the loop, or track a running maximum,
  so it is the peak and not the final reading that must fit). Same for never-negative, never-grows and
  always-parseable — one sample pins one state, and the end of the sequence is the state a correct
  implementation is most likely to have reached anyway.
- **Fixtures are generated at run time; a binary file is not a fixture.** Build the docx/xlsx/pdf/image from
  text or code inside the test, and give the tool an Installation path in the docs instead of a copy in the
  tree: a committed binary cannot be reviewed or diffed, freezes the version the test depends on, and grows
  the clone for every contributor. Pin the generation inputs, not the artifact.
- **If consecutive review rounds keep finding the same class of under-pinning assertion in one file,
  stop patching one line per round.** Enumerate every rule that file claims to protect, pin each with an
  exact value, and mutation-prove all of them in a single pass; then re-review. A fourth single-line fix invites a fifth round, and the loop costs more than the sweep. When the sweep itself
    does not close the class — a fresh review of the swept tree returns the same structural shape — the next rung
    is a normative spec plus one conforming implementation round (see `code-review-gates`'s review–fix loop and
    its `references/design-first-hardening.md`), or the operator is asked to accept the residual.

- **Give the gate a root override and test the shipped file.** An env var that repoints the gate's root
  (`<PROJECT>_GATE_ROOT`) lets the suite run the real script against a throw-away tree, so the cases cover
  the artifact that ships rather than a copy that drifted from it.
- **Run the gate's own tests as a gate step** (`selftest`), so hosted CI covers them without a second CI
  entry point; and keep that invocation from dirtifying the tree (`PYTHONDONTWRITEBYTECODE=1`, ignore the
  bytecode directory) — a gate that leaves untracked files behind blocks every lane that refuses a dirty
  tree, including the review lane whose job is to read the gate.
- **Assert the observable outcome, not the implementation's wording.** A case that greps a log line or a
  channel label (`"teardown: SIGTERM"`, `"detached processes terminated"`) pins the message, not the rule: it
  goes red on every legitimate re-wording and never catches the message being false — the same string is
  printed when nothing was signalled at all. Assert what a reader can verify independently (the pid is gone,
  the tree is cleaned, the exit code), keep the message assertions out, and when the wording itself is the
  claim under test, pin it once at the level that owns it rather than in every case that happens to see it.
  A case that cannot run at all without a capability (`/proc`, `fork`, `/dev/shm`) carries its skip guard next
  to it — a case silently erroring on the platform it was meant to tolerate reads as a defect in the gate.
- **When a case must read the record the code produced, take its selector from the producer's own symbol and
  parse the field — then require the selection to be non-empty where the record must exist.** A case that finds
  its evidence by searching each line for a copied literal (`[l for l in text.splitlines() if "delivered to"
  in l]`) carries two defects at once: re-wording the producer's message empties the selection, so the assertion
  degrades to `[] == []` and passes on any log, and a substring test over the whole line also matches digits
  belonging to another field of the same record (a start time, a neighbouring target) — so an honest record
  fails it. Import the marker/pattern the producer itself exports, extract the field you are comparing
  (`int(target)` out of the matched line rather than a search for the digits anywhere), and assert the selection
  is non-empty on every host where the record must be produced; where the code legitimately produces no such
  record, assert the refusal it records instead. This is the **selector**, not the oracle: the value compared
  still comes from the contract (previous bullet) — coupling the *oracle* to the writer's symbol is the
  separate defect that lets writer and assertion rename together. Prove the repaired check against both inputs
  in one probe: the near-miss that used to false-positive, and the violation it must still refuse.
- **In an agreement assertion between several readings, a reading borrowed from the code under test is one
  reading, not several.** `kernel syscalls == record["delivered"] == parsed log lines` reads as three
  independent sources, but where the observer derives one compared field through the production helper
  (`runner._start_time(<pid>)`) and the record derives the same field the same way, that field is compared
  with itself — so a production-only mutation of the shared helper (one field index changed, tests untouched)
  keeps the whole assertion green while an independent read of the OS source shows both sides publishing a
  value that does not exist. For every field the assertion covers, name the independent source its probe
  value comes from; a field whose probe value comes from the subject is not verified. Parse that source
  yourself (the `/proc` file and its parsing quirks, the protocol, the peer's own record), pin the helper's
  own reading against your independent parse so a wrong index fails loudly, and check every other call site
  that indexes the same field — otherwise the one wrong index hides behind whichever reader the probe does
  not use. The mutation that used to survive is the acceptance for the repair.
- **A non-empty check is only as good as the field it reads: pin the fact, never the bucket it lands in.**
  A guard that reads a shared explanation list (`unverified`, `notes`, `problems`) as the evidence for one
  specific fact is skipped exactly where it must fire — the same field carries the ordinary case (a worker
  found and left alone, a disclosed platform limit), which is what the healthy fixture produces on its own,
  so the assertion is a no-op on a run that did the wrong thing while the case's name claims it checked.
  The tell is that only a mutation of the *producer* (delete the record line the delivery is logged with)
  turns it red, and the surest reproduction is that mutation, not a re-read. Fix the record, not the
  sentence: have the producer expose a field that answers only the pinned question (the deliveries this run
  refused, separate from the limits), publish it beside the general bucket, count it in whatever aggregate
  the record reports (`verified`), and let the check require the record on the healthy path *unless* that
  field carries the legitimate alternative. Keep the shape pinned by **indexing strictly**
  (`entry["teardown"]["refused"]`, never `.get(..., ())`): a forgiving default turns a rename into
  `None`/empty, which is a green check over a record that no longer exists — the same defect as an oracle
  borrowed from the writer's own symbol. Prove it in both directions on the shipped head: the legitimate
  alternative (the capability forced absent, so the refusal is the correct answer) passes, and the healthy
  path with the producer's record removed fails. When a fix moves an assertion to a new field, re-express
  the same comparisons there and say in the report that nothing was relaxed, or the next round reads the
  move as a weakening.
- **Write an attribution predicate as a case analysis, not as an equality between two expressions.** A
  shape like `(verdict_green) == (list_has_runs and not failing)` reads correct and collapses distinct
  worlds into one verdict: two `False` operands compare equal, so *unknown* (no runs on this head yet, an
  unreadable list) matches whichever side it arrives on — including the side that authorises the
  irreversible step. Name the cases explicitly (green / red / unknown), table-test every row plus the
  unreadable one, and require *unknown* to land on the refusing branch. Table-test it **before** trusting
  the guard: the row that fails is the empty or unreadable input, not the one you wrote the guard for.

## 7. Never name a bare command a protocol expects to resolve itself

A protocol line like `scope-tool.py snapshot` assumes a `PATH` entry the reader does not have.

- Resolve through one helper that walks the same configuration chain as every other setting (`tool scope`
  prints the absolute path), and quote it in the documented command so a path with a space survives.
- A repo-specific script is not a universal step. Write it as "the gate this project's profile declares
  for this phase", or every repo without that script silently skips the phase.
- A documented configuration key must resolve through the configuration chain: `${KEY:-default}` reads only
  the environment, so a value in the config file never reaches it.

## 8. A gate stricter than the contract fails valid input

The mirror of §1: a gate that rejects a legitimate artifact is as costly as one that passes a broken one,
and its FAIL sends the next session hunting a defect that does not exist.

- **A check whose verdict moves with the values the artifact describes is not a gate; it is a claim about
  the world.** A persistence/CI/merge gate answers exactly one question — is this artifact well-formed and
  integrable — so its inputs are code and structure, never the data's own values. An assertion that reads a
  live dataset (a portfolio snapshot, a ledger, a metrics table) turns red the moment the world legitimately
  changes, and no code edit can fix the world: the gate then refuses to record reality, which is not a safety
  property and not a review. Business-value thresholds (profit/loss, holdings, any "is the number good"
  condition) must never block a commit, a CI run or a merge. Put data-value assertions where a moving input
  is legitimate: a frozen fixture (deterministic, re-pinnable, can block again as a pure code test) or an
  advisory report on its own alert channel. Split any existing gate on this line — blocking checks are code
  and repository integrity (test suites over fixtures, secret scan, scope/size, schema), everything that
  judges the owner's real data is advisory — and say which is which in the gate's own source. An assertion
  with no fixture and no contract behind it — its only possible input is the owner's live data — has no
  advisory end state either: **delete the assertion**, or re-point it at a frozen fixture. Parking it as a
  permanent warning keeps a check nobody can ever act on, and the operator will rightly demand it removed;
  a loss on a real dataset is a fact about the world, not a defect in the commit that recorded it.

- **Judge the artifact on the contract, not on bytes, when the writer normalizes formatting.** A tool that
  rewrites files may legally reorder keys, reflow blocks or re-quote strings: a raw `sha256`/`cmp` against
  the pre-write tree reports a cosmetic difference as data loss. Pair the byte compare with a parsed-data
  comparison and keep byte equality only for the case that must not vary — two runs of the same input
  producing the same bytes.
- **Take each check's baseline immediately before the step it measures.** A baseline captured before an
  intervening write turns a correct rollback or restore into a FAIL. Sharing one baseline across a
  sequence of mutating steps is what produces it; recompute per step.
- **Enumerate targets at run time, with the same discovery the tool uses.** A hand-written roster keeps
  testing retired entries and fails on paths the tool never touches, so a green run and a red run both stop
  meaning anything.

## 9. A capacity gate belongs in the pre-step, not in the producer's judgement

A gate that throttles production (a topic pool that must not grow past N, a queue depth, a spend ceiling)
checks no artifact — nothing prints green, and the producer is an agent with an incentive to produce. Asking
it in its prompt to "keep the pool small" is a rule it grades itself against.

- **Compute the constraint in the deterministic step that builds the agent's input, and print a token.**
  The collector/seed script that assembles the prompt reads the record, counts it and emits an explicit
  verdict (`AT_LIMIT` / `ROOM: <n>`, `POOL_FULL` / `POOL_ROOM: N`); the prompt then branches on the token.
  The agent obeys a fact instead of judging its own limit, and the count is reproducible outside the run.
- **Count exactly what the rule counts, from the section that defines it.** Parse the table under its own
  heading, skip the header and separator rows, and refuse when the section is missing rather than returning
  0 (§1) — a renamed heading must not silently mean "no limit".
- **Keep the human-owned record out of the producer's write scope.** When the pool rounds towards a limit,
  the table holding the counted entries is the thing being measured: a producer allowed to append to it moves
  its own goalpost. Candidates go to their own dated file, promotion into the counted table is the owner's
  act, and the prompt says so explicitly.
- **Land the branch in the prompt in the same edit that adds the token.** A token nobody reads changes
  nothing, and a producer that only ever saw "pick 2 items" keeps picking 2 items.

## 10. A promoted check must change the verdict, not add a line

A gate has two verdict paths — the per-step statuses and the final `failed = [...]` computation — and a
list that promotes a step to mandatory is a third. Writing the promotion into only one of them is how a
check stops being mandatory without anyone editing the gate again.

- Compute the verdict from the **effective** status: rewrite every listed-required step that is not `PASS`
  to `FAIL` *before* the verdict is computed, so `SKIP`, `BOUNDARY`, `N/A` and an unknown step name all
  fail. Printing an extra `FAIL` line while the verdict still walks the original statuses is precisely the
  shape that passes a mandatory check with exit code 0.
- **Replacing a hand-written step list with a discoverer is a promotion event, not a refactor.** Reconcile
  old against new: every step the previous wiring ran maps to a schedule in the new one, or the report says
  why it is gone. Prove the replacement with injected faults (a syntax error, a deliberately failing suite)
  *before* deleting the old wiring — a check whose schedule disappears stops being mandatory while both the
  gate and its log stay green.
- Decide what "could not run" means per platform, in writing: on the platforms the project claims to
  support a missing toolchain or compiler is a failure, elsewhere it is a disclosed boundary. A run that
  skipped steps names them in the verdict (`PASS (partial: <steps>)`) so a partial run is visible in the
  CI log and in every transcript that quotes it.
- Prove the promotion with the case that has no *other* failure in it — a required step returning `SKIP` on
  a tree where every other step passes. A test that exercises the promotion alongside a real failure
  passes for the wrong reason, and a fixture that only feeds `PASS` never pins the rule.
- The step table is itself a check that must run at all: pin a tool to the module path that version
  *declares* (`go install <path>@<version>` fails outright when upstream renamed the module path) and
  verify the install once on a real host. An install step that cannot run turns every future run red for a
  reason no code change caused, and green-looking local runs hide it.

## 11. A gate must not inherit the caller's environment

Same tree, same code, different answer: a verdict that depends on what the caller exported is reproducible
only on the machine that wrote it.

- **Give the gate its own temp root.** A suite that creates an `AF_UNIX` socket under an inherited `TMPDIR`
  fails once that path is long (`sun_path` caps near 108 bytes), so the same tree is green under a short
  root and red under the operator's scratch directory. Create the root explicitly, hand children a short
  one, and probe the class by running the gate twice — long value, then unset — requiring both green.
- **Carry the toolchain's state directory into any child you isolate `HOME`/`XDG_*` for.** A suite given a
  task-local `HOME` cannot exec a shim-managed tool at all: mise resolves its trust database and state under
  `$HOME/.local/state/mise` and refuses with `Config files ... are not trusted`, so an installed `bun`/`node`
  reads as unprovisioned and the package fails for a reason unrelated to the change. Pass `MISE_STATE_DIR`
  (and `MISE_DATA_DIR` when set) as absolute paths into the child environment; never widen the isolation or
  declare the suite un-runnable in that environment (mechanism and probe: skill `toolchain-provisioning`).
- **Resolve the interpreter and helper tools by absolute path**, rather than trusting the `PATH` of the
  moment: a PATH that prepends toolchain shims changes which `python3` runs, and the repo's own checks then
  fail as though the tree were broken.
- **A case that narrows `PATH` to a stub directory must stub every tool its code path probes**, not only
  the one under test. Each unstubbed probe answers "missing", so the step returns its boundary or skip
  branch before reaching the mocked work: the case then passes for the wrong reason on the host that has the
  tool, and turns into a different status or a false red on the platform that lacks it — a hole no local run
  can show, but a static reader sees it immediately. Stub the whole set a step can consult (compiler,
  formatter, version manager) while keeping dedicated cases for the missing-tool rule itself.
- **Pin the fixture discipline, not just the cases.** Add one case that runs the suite's own logic under a
  stub-only `PATH`, and one that forces the platform probe to its other answer (no compiler), so the next
  case that forgets a stub fails here instead of on a runner nobody watches. A platform-shaped claim cannot
  be settled by a green run on the host that has the tool — settle it with that forced probe, executed, and
  quote the run. **The mirror shape is a guard that enumerates which cases may skip:** a hard-coded list of
  expected non-passes is the author's host written as a literal, so a newly added case that legitimately
  skips on a platform lacking the capability turns that leg red over a *correct* skip — derive the inventory
  from the same probe, and note that a forced platform answer does not move a probe measured at import
  (mechanism: skill `code-review-gates`, reference *platform-premises*).
- **A case that gates on a capability must reach its skip before it touches the capability.** Moving the
  `skipTest` later so a unit half runs on every platform is only safe while that half is portable:
  `mock.patch.object` on an attribute the running platform's module does not have raises `AttributeError`
  **while entering the patch**, before any skip executes (`os.killpg` on Windows, `os.fork`, a `/proc`
  reader), so the case hard-fails on exactly the platform it was written to tolerate. Pass `create=True` or
  guard the patch with `hasattr`, ideally through one shared helper, and settle the claim with a
  forced-absence probe — patch a stand-in namespace with the attribute removed and require the skip — since
  a green run on the host that has the tool refutes nothing.
- **Run from the root the gate assumes**, or pass it explicitly — never let relative paths resolve against
  whatever cwd the caller happened to have.
- The tell for all four: a red run nobody can reproduce by hand, or a green one that only ever happened on
  one host — including a green that exists only inside the implementer's own agent environment. Re-run the
  gate in an environment that differs from the author's (minimal `env -i`, real `HOME`, clean `TMPDIR`, the
  pinned interpreter) and keep stderr in the log: a capture that greps only summary lines reports a bare
  exit code with no cause, which is how an env-shaped defect gets filed as a flake.
- **An implicit bound inherited from the runtime is this section's defect under another name.** Where a rule's
  limit comes from the interpreter or the OS default — the recursion limit, a maximum path length, an fd cap —
  the rule's text and its behaviour disagree on every host whose default differs, and what it produces is a
  crash, not the refusal the rule promises. Replace the inherited limit with a stated constant, check it
  *before* the operation (a pre-scan that walks the input itself, skipping strings and escapes) and put the
  bound in the refusal message; then probe at two settings of the runtime limit — default and raised — and
  require the same verdict and the same message at both, because a bound that holds under one interpreter
  setting only is the host's rule rather than the artifact's. When a decoder runs the same input afterwards,
  state which of the two refuses first and prove the case only one of them can reach.

## 12. A dependency that did not run is a third state — not a pass, not an ordinary failure

Hosted CI, a remote scanner, a service container: the gate consumes the verdict of something it does not
control, and that something can be refused *before it starts*. Collapsing that into "failed" blocks the
pipeline forever for a reason no code change can fix; collapsing it into "green" is §1's empty set wearing
a different hat.

- Classify before deciding: **passed / ran-and-failed / never-ran**. The never-ran tells are structural —
  zero steps executed, sub-second duration, no runner or machine assigned, and an annotation naming
  quota, billing or availability rather than a step. Confirm the scope with a sibling target the same
  account *can* run: one target refused while the others are green is account- or target-side, not a
  broken tree.
- Never-ran keeps blocking by default. An override is legitimate only when it is (a) tied to a precondition
  the gate **re-reads every run** as derived state, never to a condition someone asserted once; (b)
  matched to the specific blocking evidence (that annotation text, that error class) so a real step
  failure on the same pipeline still blocks; and (c) self-expiring — it flips back to strict on its own
  once the precondition no longer holds.
- Disclose it in the record the gate already writes, in the same machine-readable form as every other
  verdict: which dependency did not run, the matched evidence, and the standing decision it acted on. A
  bypass that leaves no marker is indistinguishable from a gate that never ran.
- Substitute a check that binds to the same head (§4) instead of accepting a green from before the outage,
  and keep the remaining conditions mandatory — dropping the unavailable check is not dropping the others.
- Put the policy in the caller, not in the shared tool. A bypass committed inside a gate that every repo
  uses becomes a permanent licence to merge without that check; the caller owns when to relax it, and
  reports it in the same breath.

## 13. A silencer is scoped, re-derived, and proven in pairs

Switching a check off for a period is a gate change with no verdict line of its own: nothing prints green
because nothing runs — §1's empty set reached on purpose. The operator asks for it in the language of a
symptom ("stop the sync", "pause this until the refactor lands"), so the shape matters as much as the
mechanism, and the proof matters as much as the shape.

- **Keep it as data the gate re-reads, at the choke point every consumer already shares.** A state entry
  naming the source and the reason — not a flag threaded through one caller — leaves removal as the restore
  path, so the relaxation expires without a code edit, and every path that decides from those findings
  honours it at once. Repairing one consumer leaves the others healing or alerting from the same red.
- **Scope it to the named source, and require the neighbours to survive.** On the same run, findings from
  every other source must still be reported in full: a suppression that hides the whole check converts a
  scoped pause into a blind spot, which is worse than the alarm it replaced. Assert the surviving findings
  by name or count, not merely the absence of the suppressed ones. Matching a recorded identifier against
  the silenced root is §3's job again — resolve it first (a source reached through a symlink matches on its
  target, never on the link's path).
- **Prove it in pairs, on the shipped script, against a throw-away tree.** Repoint the entry's home/root env
  so the real scheduled script runs against a fake upstream and a fake profile, then drive it twice: with the
  switch absent the finding must appear and the plan must be non-empty, with it present the run must be
  silent. Silence alone cannot be told from "the probe never ran" (§1, §6) — the control run is what makes it
  evidence — and after removal the same tree must reproduce the original finding.
- **A silencer may not hide a red that was already true.** Run it against the live tree before landing and
  enumerate what it stops reporting: every entry it now skips must belong to the named source, while
  hand-edited, writable, or two-source collisions keep failing. Report that list with the change, because
  a pause that quietly swallowed an unrelated defect is how a refactor week costs a quarter of drift.

## 14. A count and the thing it summarizes disagree — the harder verdict wins

Every gate that reads a producer's output holds two verdicts at once: the producer's own process result,
and whatever the gate counted out of its text. They disagree exactly when the producer was healthy enough
to print but not healthy enough to succeed, and the count is the side that reads green.

- **A nonzero exit is a batch-level verdict no per-item marker may override.** A runner can print `PASS`
  for every test and still fail after its suite returns (a `TestMain` failing after `m.Run()`, a reporter
  error, a kill during teardown). A checker that reads the markers before the return code counts every row
  verified and exits zero. Check the exit code **independently of the row loop** and reject the whole batch
  — none of that batch's markers verify anything — and accept markers only from a run that exited zero.
  The mirror: an explicit failure marker (`FAIL`, `SKIP`) for an item that also carries a `PASS` must win,
  so read the failure branch before the pass branch, not after it.
- **Pin both directions, because the natural fixture covers only one.** The case that proves the rule feeds
  a run that prints `PASS` *and* exits nonzero; the existing "nonzero exit" fixture, which prints no
  markers at all, stays green against the broken code. Same for the override — one item carrying both
  markers — since a fixture with one outcome per item never reaches the ordering.
- **Nested deadlines must be ordered outward, and the outer one must still produce a verdict.** A gate that
  hands a component the same budget that component grants each of its own sub-steps leaves no room for the
  component's timeout handling to run: the outer deadline fires first, the child dies mid-report, and the
  gate raises an uncaught deadline error instead of writing a FAIL — so the run ends with **no verdict line
  at all**, which a watcher reads as an ordinary finish. Give the outer runner a budget strictly larger than
  the component's worst case, catch its own expired deadline and return a FAIL that names the budget, and
  make the **component** own a bound over its whole work rather than only per unit: `N` individually bounded
  batches still exceed any single batch's bound, so a per-batch timeout is never a total one. Test the chain
  by forcing the child to outlive the budget and asserting a FAIL verdict naming the budget — never that the
  exception propagates — and state both bounds in the document that describes the check.

## 15. A pin that reads a document as text is bypassable — read it structurally, or refuse it

A check that greps a file for the claim it protects accepts every equivalent spelling of the shape the rule
forbids. All seen in one workflow file: a mapping is unordered (an `include:`/`exclude:` block written
*before* `os:` is dropped by a reader that tracks position), a key may be quoted or carry a space before the
colon, a value may be a block or folded scalar, a quoted scalar may hold a comma-separated list, a runner
label has a family (`macos-14`, `windows-2022`), a step may carry `if:` or `continue-on-error:`, and the
whole job may live in a second workflow file the reader never opens. Each is a normal edit that leaves the
claim false while the pin prints green.

- **Read structurally and refuse what you cannot read exactly.** Parse the artifact into the structure the
  rule is about — steps as steps, a value as its whole value, the trigger block as a block — and treat every
  shape the reader does not understand (a literal `runs-on`, a scalar where a structure belongs) as a loud
  refusal. A silent skip is where the bypass hides — and the skip is not only at the top level: a walk that
  accepts a node and then steps over the lines beneath it certifies a value that may be *longer* than the
  line it opened on (a plain scalar folds, so `runs-on: ${{ matrix.os }}` continued on an indented line is a
  different runner), so the refusal bound must cover every line of the construct's own subtree, not just the
  line that opened it.
- **Model the reader's consumer, not only the syntax.** A structurally correct reading can still certify a shape the
  consumer runs differently, because the consumer has semantics of its own: `exclude` applies to the base matrix
  *before* `include` adds combinations back, so a label named by both is executed; branch patterns are *ordered*, so
  `[main, '!main']` removes `main` again and the presence of the string proves nothing; a quote inside a plain scalar
  is *literal*, so `windows-'latest'` is a different runner label. For every construct the reader interprets, implement
  that consumer's documented semantics with a positive case or refuse the construct loudly, and keep the
  modelled-vs-refused list in the pin's own docstring — a construct interpreted by "almost right" rules is what makes
  the next review round find a new instance.
- **Every accepting branch needs a positive case, and the refusal contract is pinned per branch.** A suite of
  rejection cases alone cannot tell "the reader refuses the bad shape" from "the reader refuses everything";
  and one case per rejection class (one crafted shape each, named) is what makes a *disabled* branch go red
  instead of quietly widening the accepted set.
- **When the same class comes back round after round, change the stance — do not add another refusal shape.**
  Enumerating spellings one per round does not converge (each round found a new one); the rung that closes it
  is the structurally-parsing, fail-closed reader applied to the whole surface in one pass. Report the residue
  that remains as residue.
- **Above that rung sits removing the duplication the pin exists to police.** When the pin's whole job is
  "this document matches that config", the shapes stop existing if the document is *generated* from the
  config: the gate then only checks that the generated artifact is not stale, a reader's mistake lands as a
  visible diff instead of a silent certification, and the hand-written semantics emulator shrinks to one
  staleness check. Its cost is a generated file no one may hand-edit; where that is too much for the
  increment, the rung below is narrowing the claim so the pin's assertion is small and true. **When the guard
  has outgrown the change it protects — a semantics emulator grown out of a two-line edit — say so and put
  these rungs to the owner as a decision with their costs, rather than hardening for another round in
  silence.**
- **Residue the mechanism cannot cover is disclosed, never papered over.** A raw-text pin cannot see rendered
  Markdown — a claim wrapped in an HTML comment is invisible to the pin while gone from the rendered document
  — and a pin that does not check its own existence leaves the gate green when the pin is deleted. State both
  in the pin's own docstring and in the document it protects, say what a green run may therefore not be read
  as, and do not substitute a decorative check that cannot fail for the disclosure.
- **A claim with two live copies is one claim with one pin.** When the same sentence is stated in two places
  (two sections of one document, a comment and its doc), the pin reads one and the other drifts into the same
  falsity a round later: dedupe, or read every copy. The tell during mutation work is a mutation of the claim
  that leaves the suite green — before reading that as a vacuous pin, check which copy the mutation landed on
  and how many copies the literal occurs in (`assert text.count(old) == 1` failing on the duplicate is the
  correct behaviour, not an obstacle).
- **When a comment promises more than the pin reads, make the promise true — narrowing the claim is the
  fallback.** A comment ("a case here fails one that reappears") is a claim about **content** while a
  substring or name-matching scan answers one about **spelling**: a guard that reads a fixture's *name*
  catches a fixture only while it keeps that name, and one that reads raw text accepts every equivalent
  spelling of the same content — JSON/unicode escapes (`"session\u005fmeta"` for the token the scan
  forbids), a re-quoted or re-wrapped literal, a case fold. Each reads green on an artifact any reader sees
  as carrying what the rule forbids. Settle it in this order: add the **decoded** form to the scanned
  surface (parse with the stdlib, walk object keys and string values recursively), pin it with the escaped
  input as the case that must fail, and narrow the sentence only when the decode would need a reader of
  your own — then disclose the boundary as residue (last bullet) instead of leaving the promise standing.
  Say in the fix dispatch which of the two the round is to do: an implementer handed this finding takes the
  cheaper arm, and a narrowed claim satisfies the round while leaving the guard exactly as bypassable as it
  was.

## Reporting

One line per check with the observed numbers, then one verdict line naming every reason it blocked. Quote
only numbers your own run printed; a gate that reports a count nobody can reproduce is worse than no gate.
Before reporting a FAIL, sanity-check the gate against the contract (§8): a false FAIL burns the same trust
as a silent pass.
