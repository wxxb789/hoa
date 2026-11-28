---
name: verification-probes
description: Use when a claim must be proven by a probe you control.
version: "0.1.0"
metadata:
  version: "0.1.0"
  areas: "work-management,software-development"
  targets: "runtime-agnostic"
  summary: "stub the outside world, prove absence by shadowing, prove a test red on the old code, prove a record falsifiable"
  summary_zh: "用可控探针证明一个主张：桩化外部依赖、遮蔽式无依赖验证、旧代码跑新测试、记录可被否证"
  kind: "mechanism"
  consumes: "work-report"
  produces: "acceptance-verdict"
---

# Verification probes

## When to Use

- A reviewer or bot raises a finding and you must reproduce it before dispatching a fix.
- A test suite claims to be hermetic ("no network", "no tmux") and you need to know whether it passes
  because of the code or because of this machine.
- A sub-agent, teammate or previous stage reports numbers, a green gate, or a recorded measurement.
- A "fix" must be shown to be load-bearing: the new test has to fail on the code before it.

Not for: grading your own draft, or deciding what to do when the artifact itself is missing.

A claim is decided by a probe you control, not by the claimant's table of results. This skill is the
probe-design half of acceptance: `delegated-work-acceptance` makes the ruling, `ops-claim-verification`
handles the scheduled-job variant, and `gdd` is the loop the probe usually sits inside.

## 1. Stub the outside world, then read the artifact

| Dependency | Probe | Read afterwards |
|---|---|---|
| HTTP endpoint | stdlib `http.server` on `127.0.0.1` returning one fixed body | the written file, its counters, the exit code — never the log line |
| External binary | shell stub on `PATH` that records argv and exits with a chosen code | the recorded argv (did it receive the resolved value?) and the state file |
| Large stream | synthetic input on stdin, reader closed early | retained size, marker count, broken-pipe exit code |
| Time | fixed timestamps in the fixture, never `sleep` | any duration field is derived, not measured |

Run the stub twice — a valid answer and an invalid one — and require the outcomes to differ. Identical
outcomes mean the validation is not wired to the path you think it is.

**The input family is part of the probe, and the filesystem is one of the stubs.** When the subject
enumerates or reads a directory the caller supplies (`--home`, a cache root, a state dir), the adversarial
entries are the **dangling symlink**, the **unreadable file** and a **directory where a file is expected**:
`rglob`/`glob` lists all three like any other entry, so the read that follows raises inside code that never
considered a non-regular file. Feed one entry per class into a throwaway tree and read the outcome as a
claim: a clean named refusal (exit 2, the path in the message) is the property, and an **unhandled traceback
with a non-zero exit is itself a finding** — fail-closed code that dies ugly on a caller's half-synced home
reports nothing a caller can act on. Then re-read that caller's tree to prove the run left none of its own
writes behind, since the crash usually happens after the subject has already planted something.

**A subject with no `--home` seam can still be driven against a throw-away tree: export the root it derives
itself.** When the script resolves its own home from the environment, run the *shipped* script with
`HOME` / `<PRODUCT>_HOME` pointed at a fixture that satisfies its own discovery — a real `git init` upstream
with the drift committed, a real consumer home holding the file and lock entry it expects — and the
scheduled path executes end to end with nothing hand-copied into the subject. Then drive it twice from that
root: with the switch under test **absent** (the finding and the non-empty plan must appear) and with it
**present** (silence). Silence alone cannot be told from a probe that never ran, so the control run is what
makes the result evidence; removing the switch must reproduce the original finding on the same tree. Within
the switch-on run, assert the findings from every other source survive in full — a suppression that hides
the whole check is not a scoped pause, and it is indistinguishable from a blind spot. Build the fixture from
the subject's own discovery rules, never from an assumed layout: an identifier that does not resolve reads
as "nothing to suppress" and the pair then passes for the wrong reason. Design rules for the switch itself
(where it lives, what it may not hide): skill `mechanical-gate-design` §13.

## 1.5 A gate is a probe with a validity window

Two things void a gate result even when the gate itself is honest.

- **A tree still being written.** A stage that reports `done` may still be flushing files. Take two
  `git status --porcelain` reads and start only once they agree; otherwise the gate grades a half-written
  tree and the same head returns FAIL then PASS with no code change between. The false FAIL costs a full
  gate cycle to disprove and looks exactly like a real defect.
- **A platform the local run cannot represent.** When the repo ships on more than one OS, a green local
  gate seals nothing — the matrix is the evidence. A platform-only failure is a hypothesis about the test
  until proven otherwise; the commonest cause is a fixed input budget around a killed child (write N
  lines, kill, resume with `total − N`). The other recurring cause is a case asserting an undeclared **host
  premise** — POSIX path grammar, symlink or mode-bit semantics, case sensitivity — and it recurs in a new
  case each round until the premise layer exists; diagnose it as a class instead of patching the case again
  (recipe: `code-review-gates` → `references/platform-premises.md`). `child.kill()` on Windows is TerminateProcess with no flush
  window, so the committed count varies, the resumed run starves on stdin EOF, and the product correctly
  reports an interrupted run while the test fails. Repair by feeding more input than the run can consume,
  never by loosening the assertion, and state that only CI can confirm it.
- **A matrix leg that fails having executed zero steps is infrastructure, not a red build.** Check-run
  output carries a step count beside the result: a job that never started (a starved or queued runner)
  is not platform evidence about the code, must not trigger a fix round, and must not be reported as a
  regression — re-run it, and if it keeps happening the decision is about the leg, not the code.
- **When a leg goes away, the claim narrows in the same increment — and the narrowed claim gets a pin.**
  A verification claim and a rule's applicability are two different sentences: a host that is no longer
  verified on a runner still gets the rule (a macOS host missing a toolchain still fails), so state both
  — "ubuntu and windows run the gate on real runners; macOS is not verified on a runner, and its rules are
  pinned by the suite's executed host simulations" — and say plainly what a green run may not be read as.
  Fix the present-tense claim wherever it is stated (docs, evidence records' residual-risk sections) while
  leaving historical rows that record what a past round actually ran byte-for-byte alone: correcting a
  claim is not rewriting what happened. Then pin the claim to the artifact — the matrix's legs equal the
  labels the docs name, the job runs the gate file itself, no literal `runs-on` bypasses the matrix, each
  rule shown to fail when broken — because a claim with no check is the defect the increment exists to fix.
  A pin over prose or YAML read as raw text is defeated by equivalent spellings of the shape it forbids, so
  read it structurally and refuse what it cannot read (design rules, including the residue to disclose rather
  than fake: skill `mechanical-gate-design` §15).

- **A gate that iterates observations passes vacuously when there are none.** `pass = pending == 0 and
  failing == 0` is true for an empty check list, so a PR with zero CI checks — a `CONFLICTING` PR
  dispatches no workflows, a path-filtered workflow never starts — gets a clean verdict from the very gate
  that exists to stop it. Derive the verdict from a non-empty observation set, or make the override an
  explicit flag (`--allow-no-checks`) that the operator has to type. The same shape hides in a probe: "no
  requests on the second run" passes when the interception never loaded.
- **A positive control must force an observation, not merely be quiet.** A build that sends nothing looks
  identical whether the shim works or was absent, so keep it as the *negative* control and add a request
  you deliberately push through the shipped entry point, asserting the far side recorded its method and
  path. Likewise, when a shim rebuilds a call, copy every field you did not mean to change — `pathname`
  drops the query string, and `fetch(request, init)` applies `init` overrides the Request branch will
  discard — then assert the far side saw the same method, path, body and credential. A shim that
  reassembles the request from parts silently tests a different operation and reports a false verdict in
  either direction.
- **A validity window also expires when another writer touches the artifact.** On a host where more than
  one agent session runs, the script, config or fixture you are verifying can be edited between your read
  and your write. Detect it rather than assume sole ownership: a backup file whose stamp you did not
  create, a write-guard warning naming another session, a dependency whose bytes moved, or a re-run whose
  answer differs with no change of yours. Then re-read before writing and re-verify anything you already
  ruled on — an accepted verdict describes the bytes at the moment it was taken, not the path. When your
  own change propagates to every target (a sync or apply script), prove its **premise** with a direct probe
  first: one wrong entry reaches every target before anybody reads a diff.

- **Your own probe is a writer too.** A gate verdict describes the bytes at the instant it ran. Anything that writes the
  tree afterwards — your mutation probe, its restore, another session's commit — voids that verdict for the head you are
  about to push, so re-run the gate on what you are committing, or prove the tree is unchanged since the gate ran
  (`git status --porcelain` empty **and** the same `git diff --stat`). A green verdict quoted over a later revision is how
  a head that fails its own suite gets pushed with a green claim in the commit message.

## 1.6 A launched probe can fail before it starts

When the probe is a *dispatched run* (an agent CLI, a batch job, a harness) rather than a command you
typed, separate "never ran" from "ran and failed":

- **Sub-second `failed` with an untouched tree means the probe never reached its subject.** Read the
  launcher's own `stderr.log` inside the run directory — the state file records only *that* it failed.
  The two causes worth checking first: a binary path that resolves to a version-manager **shim** instead
  of the real install (`which <tool>` →  `readlink -f` → the version manager itself), and a flag in a form
  the CLI rejects (a duration like `1h30m` where it accepts a single unit, `90m`). **The same tell arrives when
  the *caller* gained a flag its host wrapper never learned** (`unknown arg '--schema'` in the wrapper's own
  stderr, a `launch-failed` row and no session): the wrapper is part of the interface, not a fixed shim, so
  the upgrade is to accept the flag, resolve it to an absolute path, export it to the child and record it in
  the run's state file, then prove the pair with one trivial dispatch — never to re-dispatch the same command
  unchanged. Fix the value, relaunch,
  and never report the first attempt as a result — a preflight failure says nothing about the subject
  (nor about the stage budgets: it never reached one). Two follow-ups this costs: a failed launch leaves
  its run name and directory behind, so the corrected relaunch needs the launcher's force flag, and the
  state file must be read seconds after dispatch rather than at the end — the dispatch line proves the
  launcher started, not that an agent is running.
- **A required input that was never written is the same sub-second failure, and the launcher's own summary can
  misname it.** A dispatch whose packet, diff or prompt is produced by redirecting into a directory that does
  not exist writes nothing, so the run exits before reaching its subject (`File not found: …combined.patch`) —
  while the wrapper a level up reports the symptom it observed last ("all attempts returned an empty answer,
  not a timeout"), which reads like a model or quota problem. `mkdir -p` every directory the dispatch writes
  into, `wc -c` the packet before launching and re-stat it after any edit to the dispatch (a hand-fixed prompt
  and a stale packet diverge silently), and read the innermost process's stderr rather than the wrapper's
  summary. **`wc -c` alone does not prove the packet carries its sections**: a build step that copies over the
  previous round's output directory drops the appended section while the file still looks well-formed, so grep
  the finished packet for a sentence belonging to each section (the intent summary, the list of findings the
  round must dispose of) before dispatching — a run whose packet section is empty still launches and still
  answers, and its report carries no sign of the omission. A unit reporting itself inactive seconds after launch has been graded on nothing — and a detached
  unit launched with `--collect` is garbage-collected the moment it exits, so the failed launch leaves behind
  neither a state nor a name: `systemctl --user status <unit>` answers *"could not be found"*, which reads as
  a typo in the unit name rather than a launch that failed. Make the **log file's existence and growth** the
  readiness check, and `mkdir -p` its directory in the same command that launches. The same holds for the
  Hermes terminal tool: shell-level detachment (`nohup`, `disown`, `setsid`, a trailing `&`) is rejected
  outright — launch with `background=true` (and `notify_on_complete`) so the runtime tracks the job and hands
  back a session id to poll.
- **Liveness comes from the pid and the growing event log, not from the state file's counters.** Counters
  such as `events_bytes` legitimately stay `0` until the run finalizes; `running` + live pid + a growing
  event file is healthy, `running` + dead pid is the stale case. Arm a small poller that exits when the
  state leaves `running` and notifies you, instead of sleeping in the foreground. **Keep that poller in a
  file, not inlined in the launch command** (`python3 -c '…'`, a shell heredoc): one syntax error inside an
  inline program kills the poller while the pipeline it was watching keeps running, and the notification
  that never arrives is indistinguishable from a healthy silent run — the state file is the only remaining
  witness. Compile-check it (`python3 -m py_compile <file>`, `bash -n <file>`) or run it once before
  detaching it.
- **A state field that under-reports is not evidence: read the run's own stream for what it ran.** A
  launcher's `state.json` / `status` answered `model: null` for a run that was demonstrably using one, so a
  claim about *which* model (or effort, or lane) a dispatched run used is decided by counting the ids in its
  event log — `grep -o '"model":"[^"]*"' <run>/events.ndjson | sort | uniq -c | sort -rn` — and that same
  read is what catches an unintended fallback mid-run. Dispatch with the exact `provider/model` pair,
  resolved from the catalog the runtime itself reads, rather than a fuzzy name or a recalled id: a model id
  is a config fact, and the audit that reports it must name where it was read from.
- **Rule out a hang with a probe set, never with an impression.** Sample the event file twice, read the
  harness's totals file (a shrinking file is a ring buffer), read the in-flight `tool_execution_update`'s
  own progress payload (token count and intent moving = alive), and confirm the process still holds a
  socket to the provider. Full recipe with commands and JSON keys:
  [`references/dispatched-run-liveness.md`](references/dispatched-run-liveness.md).
- **"This process is mine" and "it is really gone" are claims too.** A recorded pid/pgid is not identity
  (§pitfalls), a group outlives its reaped leader, and a cleanup line that asserts termination is not a
  measurement of one. `Popen.returncode` is **not** evidence that a child is still unreaped — it is a cached
  field, so a child collected by somebody else leaves it at `None` while its pid is already reusable; only a
  kernel probe (`waitid` + `WNOWAIT`) answers that question. Identity anchors, the `/proc` traps, which
  completions need teardown, and the cases that pin it:
  [`references/process-ownership-and-teardown.md`](references/process-ownership-and-teardown.md).

## 1.7 An accepted option is not a bound option

A runtime that accepts a flag, a config key or a preset and prints a load message may never wire it:
`<preset>: pending (waiting for service: …)` followed by behaviour byte-identical to the default run. The
load line is the runtime reporting what it *read*, not what it bound, and the same shape hides in a plugin
that “loads”, a mode switch, and a themeable config key.

- Diff the **effective surface** with and without the option — the inventory of tools/plugins/handlers, the
  resolved config dump, the entries the runtime actually loaded — and require a difference. Identical
  inventories mean the option took effect nowhere, so every claim built on it ("the mode is selected",
  "the plugin is running") is unproven rather than merely unverified.
- A knob that changes the inventory but not the behaviour is a second finding, not a pass; say which of the
  two you observed.
- Keep the negative control in the record: "the run with the flag behaved exactly like the run without it"
  is the finding. A screenshot of the load message is not.
- **The same shape at build time: a source that nothing reads.** When the claim is that a document, contract
  or config *reaches* its consumers — compiled into generated prompts, applied to a profile, merged into a
  rendered file — grep the consumer for its path (`grep <compiler|generator|loader> "<file>"`) and read the
  generated output for its content and wording. A tracked file that no generator opens changes no behaviour,
  yet it satisfies every "does it exist?" check and a status document can list its wiring as done. Then
  re-derive the outputs with the generator's own check/plan mode and require the expected diff, rather than
  trusting the file's own header text describing where it is compiled in.

## 1.8 Whose fixture is it?

When a deliverable proves a rule with a fixture set it also ships, the fixture and the assertion were
authored together — replaying them shows the script still prints its own expected line, not that the rule
holds. Rebuild the inputs from the contract (the schema, the rule's wording) in your own directory, run
the same commands, and require the whole outcome pattern: the accepting cases and the rejecting ones. All
accepting is the signature of a gate that never fires; one rejecting case that now accepts is a finding,
and an accepting case that now rejects means your fixture, not the gate, is wrong.

## 1.9 A spike that decides a later dispatch returns typed numbers against a declared floor

When a probe's verdict is what authorises an implementation run ("does the replacement handle what the repo
actually contains?"), four things decide whether it can carry that weight:

- **Measure the real artifact set first and size the work from the count.** Grep every consuming repo for
  current usages before writing the migration contract: the surface is the number of real artifacts, and it
  is routinely orders of magnitude below the "replace the engine" scale the plan assumed (measured once: 4
  documents, 3 of them carrying a single diagram of one type). That count is what the owner is approving and
  what the stages get budgeted against; a plan sized from the imagined platform is a wrong decision, not a
  cautious one.
- **Report per-type coverage, not a pass count.** `k/N parsed` hides which kinds failed: carry the
  categories (format version, variant, input class) so that "21/23" with both failures in the one kind the
  repo actually uses reads as the red it is.
- **Hand the numbers to the dependent run as its abort conditions.** The job that dispatches the
  implementation carries the floor — coverage under N, any real artifact failing to parse, no legal output —
  as "report and stop", not "proceed"; a probe result nobody downstream can act on is decoration.
- **Probe the constraint the target imposes, not only the parse.** If the output is consumed under a strict
  CSP (or a schema, a size budget, a licence header), the spike must show the replacement satisfies it (no
  inline `<style>` / `style=` when the policy is `style-src 'self'`), or the phase that assumes it is
  planned on an unverified premise.

## 1.10 A remembered constraint is a claim — probe it before it vetoes a design

A language, framework or platform limitation that decides a design is a claim about behaviour, and the
cheapest moment to test it is **before** the option is priced — above all when the limitation is being
*inherited*: a design rejected earlier, a rationale recorded in an accepted decision, "that is why we did
not do X". Such a rule is usually stated more broadly than it holds (the mechanism is narrower than the
summary sentence), and a design can then stay vetoed for months by a sentence nobody re-tested.

- Write the probe as a **pair** in a scratch tree: the arrangement the rule is said to forbid, and a variant
  that *must* be refused. A permissive result alone cannot be told from a probe that was never checked — the
  negative control is what makes "allowed" mean anything.
- Read the platform's own error text as the evidence and quote it (`use of internal package … not allowed` is
  a decision the toolchain made; "the build was quiet" is not).
- Write the finding where the veto lives. When a probe reverses an inherited constraint, correct the sentence
  that carries it — the decision record, the rationale, the option list — and say in the same place what the
  probe ran; otherwise the next reader re-inherits the veto from the unrevised text.

Worked pair (Go module boundary, probed in reverse of an earlier veto): a module whose path is a **subpath**
of another module's path may import that module's `internal/...` packages through a `replace`, while an
unrelated module path is refused — the rule is decided on import paths, not directories, so "this cannot be
split into two modules" was false. Re-runnable probe: `upstream-tree-carry` →
`scripts/go-internal-boundary-probe.py`.

## 2. Prove absence by shadowing, not by reading the code

A suite that claims to be hermetic ("no network", "no tmux", "no docker") is tested by removing the
dependency:

```bash
mkdir -p /tmp/shim && printf '#!/bin/sh\nexit 127\n' > /tmp/shim/<binary> && chmod +x /tmp/shim/<binary>
PATH=/tmp/shim:$PATH <the suite>
```

Green with the real binary and red with the shim means the suite was passing on the developer's machine.
Then sweep every call site: one stubbed invocation does not cover the rest, and the failure is usually in the
second one written.

**An absence claim is decided by enumerating the capability, not by reading the code that replaced it.**
"Nothing else is signalled any more", "this writer cannot touch the live file", "no path reaches the network"
are claims about every primitive that *can* perform the act: list them in the tree (`killpg`, `os.kill`,
`Popen.kill/terminate/send_signal`, `os.replace`/truncating opens, the HTTP client) and name each one's
target or guard. The removed route leaves no trace in the new code, so a read of the refactor finds nothing;
the leak hides in a helper two calls away, which is exactly what the enumeration surfaces.

## 2.5 Stub the layer the subject resolves through

- **A stub earlier on `PATH` is void if the subject rebuilds `PATH` itself.** Harnesses routinely prepend
their own managed toolchain (`os.environ["PATH"] = "<version-manager shims>:<local bin>:" + PATH`) before
execing the dependency, so the **real** binary runs while your stub's argv record stays empty and the
verdict you read is about the real dependency. Grep the subject for PATH construction (`shims`, `which`,
`readlink -f`) before trusting a PATH stub; if it prepends its own directories, stub the path the subject
will actually resolve (wrap that directory) or a higher call site. The tell is the empty argv recording —
read it, do not read only the exit code.
- **To read the command a harness *would* run, replace the module's own exec helper instead of stubbing
  `PATH`.** When the decision is made inside the subject — argv assembled in Python and handed to
  `subprocess.run` — no binary on `PATH` ever sees it. Import the module in a throwaway interpreter, bind its
  exec helper to a recorder that returns a benign result object carrying the exit code you want, keep the
  logger quiet, and call the deciding function by hand once per input class: the recorded argv, not the branch
  you read in the source, is what shows whether the flag, its value and the target line up. Then run a second,
  ordinary input and require it to carry **neither** of the special arguments — one run cannot tell a wired
  special case from one that fires on everything. This is how a decision that would otherwise only be
  discovered a stage (or hours) later gets proven at the moment it is made.
- **A bypassed stub usually still leaves usable evidence: read the subject's side-effect contract first.**
A lane that writes or posts **nothing** on the outcome it produced (a non-zero "findings" exit with no
publish step) has just given you a stronger probe than the stub would have — say so and quote its numbers
rather than discarding the run. A subject that publishes on that path is the case to stop and clean up.
- **For a fail-closed guard, probe the guard — not the pipeline.** Feeding a bad input through the whole
pipeline stops at whichever guard fires first (a dirty-tree preflight sits ahead of the manifest reader),
so you prove the wrong guard and quote its message as the one you meant to test. Import the module and call
the guard directly, one input per refusal class — corrupt, empty, missing — and require a distinct message
for each; one generic refusal covering all three means a class is unguarded. Verify too that the refusal
leaves **no artifact** behind, i.e. that there is no fallback to the unguarded path: "process everything
just in case" is the defect the guard exists to prevent. **Find the branch the arm lives in before you
build its input, because two things upstream of it answer instead.** A *mode flag* can exit before the
path your finding is in (an oracle-only `--validate` branch returns the oracle's own green and never
touches the binary the fingerprint arm records), so a probe run through the wrong mode grades a path the
fix never touched and reads as a pass. A *precheck* in front of the arm fires first as well (`<path> is
not on PATH` for a path that is absent — you meant to reach "the digest cannot be read"). Read the entry
point's argument handling for the dispatch table and the early exits, then engineer the arm's **own**
precondition — an executable-but-unreadable stub for the digest arm, not an absent path — and require the
arm's own message, not the nearest one that fires.
- **Scope filters are verified in both directions, and the probe's own parser is part of the evidence.**
Everything the filter must exclude has to be excluded, and the risk-bearing class has to be **present** in
the retained set (the paths the project owns, not the ones it inherited) — "no leaked exclusions" alone
passes a filter that dropped everything. Derive the source of truth's record shape from the file itself
(`awk '{print $1}' <manifest> | sort | uniq -c`) **before** writing the set comparison: a comparison built
on assumed columns reports a false containment failure and sends you hunting a defect in the artifact that
the probe invented. Account for every excluded entry: `<excluded> − <kind A>` should be the named remainder
of one other kind, not a gap.

## 3. "No repro" means suspect the probe

Different probe, different code path: closing a descriptor at exec (`>&-`) never reaches the buffered flush
that a reader closing mid-stream does. When a reviewer's claim does not reproduce first try, rebuild the
mechanism they described before ruling it out, and say which command you ran in the reply.

## 4. Negative proof of a new test

Revert only the implementation, keep the test, run it:

```bash
git stash push -q -- <file the fix touched>
<run the new test>          # must fail
git stash pop -q
```

Confirm the restore before believing the run: `git diff <file>` must show no leftover marker from the
experiment. A revert done by hand-editing the line back, rather than by stash, is the one that leaves a
stray comment or a dropped character behind — and the green that follows then grades a tree that no
longer exists.

When the diff under test is **uncommitted** — a lane that stopped before its commit step, or a candidate you
have not landed yet — do not stash it. `git stash push` moves the only copy of that work out of the tree, so
a failed or forgotten `pop` loses the candidate. Load the pre-fix bytes from git and drive the same probe
against both copies, leaving the worktree untouched:

```bash
git show HEAD:<path> > /tmp/before/<file>    # HEAD is still the pre-fix revision
```

Subject the two files to one probe and quote both answers. Worked pair on a bounded retention rule: an
oversized record fed through the writer loaded first from `git show HEAD:<path>` and then from the worktree
file — pre-fix the retained tail ends at the `truncated` marker (the record was evicted), post-fix it ends
with the record itself. Two paths, one probe, no tree mutation, and the pre-fix half is the part that proves
the pin is load-bearing; the post-fix half alone only proves the candidate runs.

**When the new cases live in a suite that imports the implementation by path, there is no read-side
variant.** The revision under test is resolved by the suite itself, so a copy parked in `/tmp` never reaches
it and the file has to move: park the candidate outside the tree (`cp <impl> /tmp/<candidate>.py`), restore
the base revision (`git checkout HEAD -- <impl>`), run the suite, and read the failures back **by name**
against the round's own case list — a green run means the pins are vacuous, and a failure in a case the round
did not add means the restore went to the wrong revision. Then copy the candidate back and prove the restore
by re-reading the round's own `git diff --stat` numbers. Run the whole window as a background job rather than
an inline foreground cell, so a timeout cannot strand the tree on the base revision — and run it **before you
commit** the round: `HEAD` is the pre-fix revision only while the fix is uncommitted, so once it is committed
name the previous head explicitly (`git show <previous-head>:<path>`).

Read *how* it failed. A signature mismatch (`takes 2 positional arguments but 3 were given`) proves
incompatibility, not that the assertion catches the defect — acceptable as a first cut, and it must be
reported as such rather than as "the test fails without the fix".

**A revert can produce no test output at all, and that is the weakest evidence class rather than a pass.**
When the round's new cases reference symbols the base revision does not define (a new module-level flag, a
helper the fix introduced), the suite dies at **collection**: unittest never prints its summary line, so a run
filtered down to summary lines returns nothing and reads as "nothing failed". Capture the traceback, name the
cause, and report the result for what it is — *the symbol exists; the assertion never executed*. Finish the
check with a **targeted mutation of the rule the case is supposed to pin** (make the decision/delivery site
take the weaker route the fix removed, leave everything else alone, run exactly that one case): a mutation
that turns it red is proof the assertion bites, and one mutation of the load-bearing rule beats a matrix you
cannot re-run yourself.

**The line the mutation targets is part of the proof.** When the cheapest red is a text-replacement of
one literal in the implementation, that literal is an anchor, not an implementation detail: a later
refactor of it — even into byte-equivalent helper reuse — silently moves the proof, so it is a change to
the evidence and gets rejected unless the refactor is worth re-pointing the test. A two-line dedup never is.

**A surviving mutation is a probe error until the mutation is shown to control the decision the case asserts.**
A guard written as a chain — `if value is None: … elif value != expected: … else: pass` — has several branches
and only one decides the outcome the case is about. Replacing the first (`if False:`) leaves the comparison
intact: the suite stays green, and reading that green as "the pin is vacuous" reports a defect the pin never
had. Read the mutated construct, name the branch the case exercises, and re-point the mutation at *that* branch;
the aim is confirmed by the shape of the red (`FAILED (failures=1)` — the cited case, and only it). The mirror
case decides the same way: a mutation to an error path the case never reaches is a no-op however red it looks
on paper. When you disclose the mis-aimed attempt, call it your probe error, never a gap in the artifact.

## 5. Output equivalence: run the old implementation too

"Same result, faster" is a claim about the previous code, so the probe must include it:

```bash
git worktree add /tmp/before origin/main        # the tree as it shipped
```

Load both implementations against the same built input, serialise both results, compare digests — over
every variant the code branches on, not only the one the author's new test covers:

```js
const before = await import('/tmp/before/src/lib/query.ts');
const after = await import('/repo/src/lib/query.ts');
const variants = [undefined, ...tagKeys, 'missing-key'];   // unfiltered, every tag, the degenerate case
const digest = (v) => createHash('sha256').update(JSON.stringify(v)).digest('hex').slice(0, 16);
```

Equal digests on every variant is the acceptance; a difference names the variant in the reply. A test
written beside the change shares the author's assumptions about the contract, so it can show the new
code is self-consistent but not that it matches what it shipped.

**When the change lands inside an enumerator or planner, the equivalent output is its own listing.** A fix in
a discoverer, scheduler or filter must not alter what is selected, and the cheapest proof is the tool's own
plan surface, not reasoning about the patch: run the listing subcommand on both revisions and require
byte-identical output (`<tool> --list > /tmp/now.txt`, previous bytes back in the tree via the §4 stash, then
`diff -q`). The listing is the contract the change was not supposed to touch — a reader reconstructing the
plan from a diff has to be right about every branch, while the tool prints the answer. Pair it with the pin
(§4): the listing proves nothing was re-selected, the reverted implementation proves the new tests bite.

## 5.5 Probe the contract the artifact now has, not the one the harness remembers

A delivery can change what the artifact renders — an accumulating list becomes a bounded window — and
silently invalidate the wait condition your probe was built on. Waiting for `childElementCount` to grow
against a windowed list never resolves: the run looks alive for as long as you allow it, prints nothing,
and leaves no JSON. Nothing reports an error, because nothing failed.

- Derive the completion predicate from the logical model — the logical total, the last row's
  `aria-posinset`, the runtime's own counter — never from a count the change was designed to keep
  constant.
- Give every wait a hard timeout that fails, and read "running far past build+measure time" as a model
  mismatch before calling it slowness.
- Never accept a contract change whose justification is that it makes an old probe or an old gate pass;
  the probe adapts to the product, not the other way round.
- Timing is not the only claim. When a change removes work by rendering less, add a gesture probe beside
  the timing one — scroll back to the first item, move focus, run in-page find — because a metric can
  improve while the reader loses the ability to reach content at all.

## 6. Destructive probes: prove the restore

Copy the real artifact aside, then record `sha256sum` before and after and paste both. "I restored it" is
the same class of claim as everything else under audit.

- **A hardlink copy is not an isolation boundary.** `cp -al` shares inodes, so writing into the copy
  (`printf > copy/file`, a truncating editor, a tool that rewrites in place) changes the **original** bytes
  and can dirty the live repo you meant to protect. Remove the target first (`rm`, then recreate) so the copy
  owns its inode, or take a real copy — and re-read the source repo's `git status --porcelain` after the
  probe. Moving the copy's branch forward is the same hazard: commit inside a hardlinked tree only after
  checking which files the operation will rewrite, and prefer a real clone.

### The window is the hazard, not the mutation

- **Run it as a file with the restore on an `EXIT` trap — never as an inline foreground cell or one-liner.**
  The harness kills a foreground call at its cap **between** the mutate and the restore (the cap does not run
  your cleanup), so an abandoned window leaves the tree mutated and the next reader — often a gate you were
  waiting on as evidence — measures a file nobody edited. Backup → mutate → run → restore in a script, print
  the sha256 at each of the three points, and end with `git status --porcelain` empty;
  `git checkout -- <path>` is the recovery when a window was already abandoned. Restore **from** the
  pre-mutation copy rather than re-editing the line back, and prefer a pure read-side variant where one
  exists (loading the pre-fix bytes with `git show HEAD:<path>` needs no mutation at all).
- **Choose a tree that cannot be damaged instead of one you must restore: run the battery in a detached
  worktree of the commit under verification.** `git worktree add --detach <scratch>/<name> <sha>` gives a full
  checkout that shares the object store but not the working files, so mutations, restores and any abandoned
  window touch nothing a live stage has written; `git worktree remove --force <scratch>/<name>` afterwards leaves
  the live tree byte-identical, and the gate verdict already taken on it stays valid (a restore inside the live
  tree, by contrast, is what makes the bullet below reachable at all — the detached checkout removes the hazard
  rather than managing it). Mutate the checkout, keep the restore unconditional inside it, and never bring the
  battery's own copies back across into the live tree.
- **Take the pre-mutation copy at the start of the run that mutates; never restore from one an earlier round
  left behind.** A mutation probe is cheapest to derive from the previous round's by copy-and-edit, and that is
  exactly how the restore step ends up writing back bytes that are one or more rounds old: the run "restores the
  original", the tree silently reverts the work that landed since, and the probe's own green then reads as a
  clean result over a subject nobody wrote. Re-point every copy/fixture path in a derived script (edit the
  round-tagged names, read the script before running it), take the copies from the current head, and prove the
  round trip by comparing the post-restore `git diff --stat` against the numbers the tree carried before the
  mutation — equal counts on both sides is the only evidence that what came back is what left.
- **In a battery, every row proves its own application, and a lone green among reds is re-derived before it is
  believed.** A row applied by text replacement silently no-ops once its literal has moved in the file, so the
  table shows one `OK` among failures and reads as "this rule is not pinned" — when the finding is that the row
  never ran at all (the mis-read runs both ways: an unapplied row that would have been red hides a real hole).
  Assert per row that the target actually changed (`assert mutated != original`, or the edit's literal occurring
  exactly once) — and take the anchor from the artifact you are mutating (`grep -c` it first), never from a
  sibling file you remember: an anchor that lives in the *other* file (a same-named in-code fixture beside the
  committed one, a value only the test constructs) makes the edit a silent no-op whose green then reads as a
  vacuous pin — and that the runner printed a positive test count; when one row's result disagrees with its
  siblings, re-derive that row first and re-run the whole battery before reading either outcome.
- **Serialize it against everything else that reads the tree.** A gate, build or CI run that overlapped the
  window is **void, however green it printed**: re-run it on the restored tree before quoting it anywhere,
  and if that gate was evidence someone else already accepted, say the earlier green was withdrawn instead of
  re-running quietly.
- **A tree-reverting command destroys uncommitted work — never point one at a path a stage has written to and not yet
  committed.** `git restore <path>`, `git checkout -- <path>`, `git stash push` and a branch/worktree move all resolve
  against **HEAD**, so output the current stage has not committed is dropped silently and the path returns to its pre-stage
  revision. Copy the pre-mutation bytes aside (`cp <path> /tmp/<name>.before`) and restore from **that copy**, or commit the
  stage's output on a scratch branch first; the read-side alternative (`git show HEAD:<path>` for the pre-fix revision) needs
  no tree mutation at all. The damage compounds silently: the next `git add -A` commits the reverted tree *as* the stage's
  work, so before committing compare `git diff --stat` with the numbers the accepted stage produced (a smaller increment is
  the signature of a restore that ate uncommitted work) and re-run the stage's own tests on the exact tree you are committing.
- **A mutation's red only counts against a baseline you took with the same command.** Run the probe *before* mutating and
  record it green — a failure that already existed produces the identical red and the mutation gets credited with a proof it
  never made — and make the mutation's own edit assert its target was present (`old_string` occurs exactly once). That
  assertion, not the test result, is what proves the fixed text was in the file. Then run it again after the restore: green,
  red, green is the shape; anything else is a probe error to report as yours.
- **Recovering a reverted candidate from the run's own event log.** When a dispatched stage's uncommitted edits have already
  been destroyed, they are usually still readable: the stage's `events.ndjson` records every edit tool call with its
  `old_string`/`new_string` verbatim. Replay those pairs in order onto the current file, asserting per edit that the old string
  occurs **exactly once** before replacing (a bare `str.replace` writes a plausible file with no check that it was at the
  expected revision), then re-run the stage's tests and the gate — the recovery is a claim like any other, and the ledger gets
  the operator error and the rule that follows from it.
- **Scope the command to what the mutation should break.** The single package or test that pins the rule,
  not the whole suite: a full suite turns a two-second window into minutes and puts every concurrent reader
  inside it.
- **Sample a claimed "executed mutation" matrix; do not read all of it.** (A class that recurs round after
  round is the exception — then every row is read as a claim, §6.4.) When a delivery claims N rules each
  pinned by an executed mutation, re-execute **one row yourself**, end to end, and compare three things with
  the record: the failure it produces, the exit status, and the restore hash (`templates/mutation-check.sh`
  is the copy-and-patch starter). One row that fails exactly as recorded beats reading forty, and it is the
  only way to tell a matrix that was run from a plausible one that was written. Two features of the record
  are evidence rather than decoration: a probe that **did not** detect, kept as a disclosed limit (dropping
  it is the tell), and a restore hash you can verify — a matrix that owns its own rollback can be checked at
  both ends.

### 6.4 When the class recurs, sweep the whole table — and classify every row

One sampled row proves the matrix was *run*, not that its rows are *true*. When the same class of claim comes
back round after round ("the bound holds", "the rule is enforced", "the comparison is detected"), stop
verifying row by row and re-read **every** row as a claim: is a "bound" a bound of the resource it names, and
would the cited evidence fail if the behaviour were removed?

- **Every row gets one of four verdicts, and none of them is silence.** *Repaired* (implementation or evidence
  fixed, with an executed two-way probe); *claim corrected, decision recorded* (the wording asserted more than
  the code does — correct the wording and record who decided it); *declared* (kept as an open limitation with
  its corrected wording and a one-line reason); *judged safe*, with the reason it holds. Never narrow a claim
  to match the implementation and never delete the row: a readable declaration is the honest form of "not
  fixed", while a narrowed or deleted row removes the only trace that the rule was ever claimed.
- **Split the declared rows into product defects and evidence gaps, and report the split.** They cost the same
  to declare and nothing like the same to close: behaviour that contradicts its claim is a defect; a rule that
  holds but has no test, or whose test passes with the behaviour deleted, is a gap. A class size reported
  without that split reads as that many bugs and buys a repair round the owner did not have to authorize.
- **The sweep's own answer decides the next rung.** Mostly gaps → a further audit is grading a *declaration*,
  so ask whether the declaration is acceptable instead of defaulting to another repair round. Mostly defects →
  repair, then audit.
- **A sweep of one row's concept is a sweep of every row's — expect the class to exist outside the cited
  file.** Re-reading "the diagnostics are bounded" surfaced the same unbounded accumulation in a sibling code
  path no row named; fix it in the same pass and add the row, because the class is a property of the concept
  rather than of the file the finding happened to cite.

## 6.5 "It has been promoted" is a claim about the bytes that landed

When the claim is that a reviewed candidate now occupies live state (a cache/ledger JSON, an inventory
snapshot, a generated config), probe identity rather than the writer's success line:

- Recompute `sha256(live)` yourself and require it to equal the candidate **you reviewed** — not one the
  writer re-made during the write.
- Require the pre-write `live` to have equalled the retained before-copy on size, mode, `st_mtime_ns` and
  digest. Four equal fields is what rules out a third writer; equal bytes with a moved `mtime_ns` means
  someone re-wrote the file.
- Require a same-directory sibling + `os.replace` rather than an in-place truncate, and a guard that
  refuses to write when either the candidate's digest or the live file's pre-digest has drifted. A step
  that cannot refuse is not safe to re-run.
- Read back the *semantic* identity (date, base commit, record counts), and check the neighbours you
  deliberately did not touch — mirror, generated identity, job definitions — by unchanged mtime.
- Keep the before-copy as the named rollback unit and do not let a retry overwrite it.

Order of operations, guard-script shape and receipt fields:
[`references/live-state-promotion.md`](references/live-state-promotion.md).

## 6.6 A deduplicating change is two artifacts, and only the pointer shows up in the diff

When a change collapses a duplicated block into a pointer ("the rule now lives in `<file>` → *<section
title>*"), the diff you are handed contains one file: the pointer. The destination is a second write in a
second file, and nothing in the ordinary review path notices its absence — CI reads neither cross-file prose
references nor section anchors, a link checker validates the path while a cited *section* may not exist, and
a stanza authored in the forge's web editor leaves no trace at all unless it was committed. A rule that moved
is worse off than one duplicated: nothing left at the old home, nothing at the new, every check green, and
both artifacts the change meant to reconcile read as consistent to the next session.

- Probe the destination in the **target ref**, never in the conversation that claims it was pasted:
  `git show <ref>:<file> | grep -i <term>`, `git log --all -S "<exact phrase>"`, and the forge's own commit
  search (`gh api search/commits -f q='repo:<owner>/<repo> "<exact phrase>"' --jq .total_count`).
- Read the PR's changed-file list against the files the plan named: a dedup change that touches one file has
  landed half of itself, whatever its CI said.
- Report the result as a state — "the rule now has zero homes; here is the text ready to re-land" — not as a
  merge that finished, and never let the earlier claim of a paste stand as provenance.

## 6.7 When the product's own end-to-end path cannot run here, provenance is still decidable

A claim about what a tool writes into a field ("the export's title", "the row's name") does not die with an
unrunnable end-to-end path. Split it into two facts and report both:

- **Provenance, pinned by code:** read the writer that assigns the field, follow it to the function that
  produces the value, and cite the file and line. That fixes *which* upstream value reaches the field — a
  base64 blob in that field is then either impossible or must come from a named other source.
- **Values, measured at the producing seam:** drive that producing function — the tool's **own** reader,
  parser or selector, imported from the tool — over the real corpus, and report the distribution
  (how many of each shape, plus the count that are the shape under suspicion).

State the third fact too, in the same breath: the end-to-end path **stayed unverified**, with the failure
that blocked it. A parser-level measurement presented as "the export works" is the overclaim this section
exists to prevent — and never reimplement the tool's parsing to guess its answer: the tool's own code is the
oracle, and a disagreement with a hand-written copy is about the copy. When a regex has to stand in for the
reader, its false positives are yours to dispose of one by one before any count is quoted.

## 7. Prove the served artifact is the one you built

A deploy step reporting success proves the upload, not the serving. Probe the origin and compare an
identity the build produced with the identity it serves — a content-addressed filename is ideal because
it cannot match by accident. Follow the build's own reference chain rather than a hand-written URL:

```bash
chunk=$(curl -sS "$origin/" | grep -o '/_astro/Layout[^"]*\.js' | head -1)
served=$(curl -sS "$origin$chunk" | grep -o 'site\.[a-f0-9]\{64\}\.sqlite' | head -1)
test "$served" = "$built" || { echo "stale deploy: $served != $built" >&2; exit 1; }
test "$(curl -sS -o /dev/null -w '%{http_code}' "$origin/data/$served")" = 200
```

Run it twice, as with any stub: the healthy origin, then a deliberately wrong expected name, which must
fail. This is the one failure every pre-deploy gate hides — a site that keeps serving an older build
while every job is green.

## 8. A record must be falsifiable

Before accepting a recorded measurement, ask: does the validator recompute anything from the source, or
does it trust stored booleans; and can a failed run overwrite the last good record? A producer and a
validator that disagree about what a valid record is make the record a self-signed certificate. The fix is
one entry point that validates before writing — not a check at each call site.

## 9. A tool that rewrites config in place: prove the round trip on a copy

Byte-preserving editors (model/preset switchers, formatters, unifiers) fail in a way a unit test cannot
see: they are "done" when the live file looks right. Give the tool a `--home <path>` seam and accept it
against a throwaway tree built from every target file:

```bash
T=$(mktemp -d); cp --parents <every target file> "$T"        # or a small loop, keep the layout
cp -a "$T" "$T.orig"
tool <preset-a> --home "$T" && tool <preset-b> --home "$T"
diff -r "$T.orig" "$T"                 # every hit gets classified, not assumed fatal (below)
tool <preset-b> --home "$T"            # idempotency: must report 0 changed
D1=$(tree-sum "$T"); tool <preset-b> --home "$T"; D2=$(tree-sum "$T")
test "$D1" = "$D2"                     # stability: repeated runs are byte-identical
B=$(tree-sum "$T"); tool <preset-a> --home "$T"   # baseline IMMEDIATELY before the undo target
tool --rollback --home "$T" && test "$(tree-sum "$T")" = "$B"
```

**Judge stability, not identity.** A re-rendering editor is allowed to normalize formatting once — key
order in a block it rewrites, quoting, a trailing comma — so a raw `diff -r` or digest against the
pre-change tree reports a cosmetic reorder as a data change and buries the path that really broke. Parse
both sides of every byte hit and classify it: equal data = normalized (name the file and say so),
different data = the failure. Require two consecutive runs to be byte-identical, and take the rollback
baseline immediately before the apply it undoes — a baseline left over from an earlier case fails a
working undo, which is exactly how a cosmetic reorder gets escalated into a rollback bug report.

Check the things a round trip silently destroys: comment lines still present, key order, trailing commas,
file mode. Then run it on the live tree where a preset matching reality must report **zero** changes — a
live run that "fixes" something means the tool or the preset disagrees with the fleet, not that it worked.
And when the tool's own answer is "N targets differ", require the target list, not just the count: the
count can be right while the named files are the wrong ones. A shell suite written for one fleet layout
(hard-coded profile names, a file list that omits a discovery input) breaks silently as the fleet changes:
rebuild its file list by discovery and re-run it, or the "regression suite" is documentation.

## 10. The integration's success report is not the landed state

An adapter that reports `pushed/ok`, `imported`, `delivered` has reported what it *sent*. Read the effect
back through the third party's own API and compare the field the claim is actually about — the deck, the
folder, the label, the recipient, the account — not only the fields the integration chose to compare. A
system can accept your write and file it somewhere else (a default location) while your read-back, which
checks the fields you already knew about, stays green and the report stays confidently wrong.

- **Attribute before you blame.** Send the same call **directly** to the third party with the same
  parameters. Landing in the same wrong place proves the third party dropped it, not your payload; name
  which call proved it in the finding. The reverse matters too: the integration can be the one at fault,
  and one control call decides which sentence the report gets.
- **Make the gate able to represent the defect.** A stub that echoes whatever the caller sent cannot fail
  on this class of bug. Give it a mode that reproduces the third party's mis-assignment, and keep a second
  mode where the conforming behaviour is asserted byte-identical — the two-way proof is the acceptance,
  not the presence of a comparison.
- **Prefer reporting the mismatch to silently repairing it.** Re-filing the object is a write into someone
  else's system to make your own claim true. A typed mismatch (`deck_mismatch`), the value actually found,
  a kept identifier and a non-zero exit is the smaller change, and it stays honest if the third party later
  behaves correctly.
- Keep the identifier the integration already recorded (the remote id) so the next update targets the same
  object; marking the item failed-and-retryable instead invites a duplicate on the next push.

## 11. Reaching a real provider that does not speak the documented shape

When the point of the probe is "does this work against a real external service" and that service's response
does not match the shape the product parses, forwarding through a thin loopback adapter is legitimate — but
the adapter has to appear in the verdict, in the same sentence as the result: *real provider reached, five
candidates stored; a provider that natively speaks the documented shape remains unverified*. Never let the
reshaping drop out of the claim, and keep the adapter's own logging off the credential and off the query
text.

Driving a real desktop application on a headless host (display, first-run dialogs, reading state back
through the app's bridge API): [`references/headless-gui-probes.md`](references/headless-gui-probes.md).

## 12. Probe the surface the claim is about, not an intermediate that summarises it

A claim about what a **downstream consumer** receives — a screen reader, a client process, a proxy, a
replica — is decided on that consumer's own surface. An intermediate representation carries a different
subset of the truth in **both** directions: a browser's debugging/accessibility tree omitted the
`posinset`/`setsize` that the same rendered items exposed on the platform accessibility bus a screen
reader actually reads, so "the attribute never reaches accessibility" would have been a wrong conclusion
drawn from the debug view — and a field that *is* present in the intermediate is no more proof that the
consumer honoured it.

- Name the consumer and the exact channel **before** probing (which AT + which browser build + which
  bus/API, or which client + which log), and quote the versions: the answer is a property of that pair,
  and a later reader must be able to judge which pair it holds for.
- Read the consumer's own output instead of instrumenting the producer. Where the consumer logs what it
  received (a speech/utterance debug file, a request log), that log **is** the evidence; anything the probe
  had to add to elicit it (a focusability hack, a synthetic gesture) is reported as instrumentation, not as
  user-visible behaviour.
- When two surfaces disagree, the disagreement is the finding: state both, say which one the claim was
  about, and separate "the intermediate omits it" from "the consumer lacks it". An unavailable consumer is
  recorded as a stated limit, never quietly replaced by the intermediate's answer.
- A fix that the probe justifies still lands as a regression test on the surface the repo can host, with
  the manual path and its versions named in the report; "the debug tree now shows the field" is not the
  acceptance.

## Pitfalls

- **Pasting probe output produced outside the increment onto the already-merged branch it belongs to.**
  The record belongs beside the run (evidence file, raw logs, a handoff naming what stays unverified) and
  folds into the repo through the next increment's gated change; a transcript merged directly skips the
  gate that would have read it.
- Quoting a flag's load/accept message as evidence the option took effect, instead of diffing the effective
  surface (tool/plugin inventory, resolved config) with and without it.
- Reporting the claimant's gate table as your verification; re-run on the final tree, not on the diff.
- Accepting an integration's own success line as evidence about the *other* system's state, and then
  discovering the record sits in a default location while the report named the intended one.
- Repairing a mismatch inside the third party's system instead of reporting it — the repair makes the claim
  true without making it testable.
- Accepting a green suite as proof of the path you will run: read one case and confirm it exercises
  launch/act, not only `--dry-run`.
- Treating "the tests pass" as "the tests are hermetic" without the exit-127 shim run.
- Reading the log line instead of the artifact: sizes, counters, marker counts, exit codes.
- Ruling a finding invalid because the first probe returned clean.
- **Reading a surviving mutation as a vacuous pin before proving the mutation reached the decision the case
  asserts.** A mutation aimed at the wrong branch of a multi-branch guard (the `None` check rather than the
  comparison) leaves the suite green and produces a finding about the artifact out of the probe's own aim.
- Concluding that a field never reaches a consumer because an intermediate summarises it away (a debug
  tree, a DevTools panel, a proxy log): the intermediate omits fields the consumer gets and carries fields
  it ignores. Probe the consumer's own surface and quote its version.
- Letting a probe hang and reporting it as a slow run: no output is not a measurement, and a wait
  predicate the product no longer satisfies will never time out on its own.
- Accepting "identical output" from a test written beside the change. Run the previous implementation
  on the same input and diff digests instead; the author's oracle encodes the author's reading.
- Reading a green deploy job as "the origin serves this build". Nothing before the deploy can observe the
  deployed state, and a pinned or mislabelled artifact can sit on an older build indefinitely with a
  fully green pipeline.
- Quoting a restored file without the before/after digests.
- **Reverting a path that holds a stage's uncommitted output**, with `git restore` / `git checkout --` / `git stash` — all of
  them resolve against HEAD, so the stage's work disappears and the following `git add -A` commits its absence (and typically
  pushes it, with the stage's own "gate green" claim still attached to the message).
- **Reading a mutation's red off a tree that was already red**, or mutating without first recording the unmutated run green: the
  red is indistinguishable from the pre-existing failure, and the pin being "proved" may be absent from the tree entirely.
- Quoting a gate verdict after anything wrote the tree since it ran — the verdict belongs to those bytes, not the path.
- Running a destructive probe inline, or while a gate is live. The kill that abandons it lands after the
  mutation and before the restore, and the gate that ran in that window prints a verdict about a tree that
  never existed — so the contamination costs you the very evidence you were trying to make honest.
- Calling a re-render's formatting normalization a defect (or "fixing" the renderer to chase it) instead of
  parsing both sides and reporting "bytes differ, data identical". The mirror error is loosening the oracle
  to `diff | wc -l` so the real data change scrolls past with the cosmetic one.
- **Truncating a gate to its summary line.** Piping a can-fail gate through `tail -5` throws away the
  name of the failing check, which is the only part that makes a FAIL actionable — a "19 passed, 1
  failed" with no check named cannot be told apart from a flake, so it costs a whole extra cycle to
  re-run and disambiguate. Keep the failing check's own output; filter the passing ones at most.
- **Read the exit code of the command, not of the pipe.** `cmd | tail -1; echo $?` reports the last
  stage's status, so a crashing checker prints `exit=0`, and `grep -c` in a pipeline reports whether
  *grep* matched rather than whether the check passed. Capture the status of the command you mean to
  grade, or run it unpiped and read the tail from its saved output.
- **A probe that dies before reaching its assertion is not a finding.** `ModuleNotFoundError`, or any
  import/setup crash, from a probe you launched by hand means the *probe* never ran — an interpreter
  difference, not a defect in the thing under test. Before reporting red, confirm that the interpreter
  can import the probe's own dependencies and that you launched the entry point the scheduled or
  production path uses: a harness may resolve its interpreter itself and ignore the shebang entirely, in
  which case a scheduled check that is genuinely healthy fails only in your shell, and running it once on
  the right interpreter *is* the diagnosis. Prove it with the worst available interpreter, not the one you
  happen to have, and scrub the ambient environment before concluding anything: a `PYTHONPATH` / `PYTHONHOME`
  / `VIRTUAL_ENV` exported for a different checkout re-points the imports and turns a healthy gate red —
  re-run as `env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV <runner>`, and the failure that survives that is
  the artifact's.
- **A scenario whose setup silently no-ops passes for a reason unrelated to the rule.** Matrices assembled
  from chained one-liners are where this hides, because the setup commands are quiet: a `git commit -q` with
  nothing staged prints *nothing to commit* and exits non-zero, so the "foreign commit at HEAD" scenario ran
  against the previous head; `git remote set-url` leaves the old remote-tracking ref in place, so the
  "ref is unreadable" scenario still read it; a `git reset --hard` between scenarios discards the commit the
  next one meant to build on. Assert each setup's own precondition immediately after it (`git log -1
  --format=%s` equals the subject you planted, the ref you removed fails `git rev-parse --verify --quiet`),
  and derive the state with a command whose failure you can see rather than a quiet one. A single row whose
  result disagrees with its siblings is the tell — re-derive that row's setup first, exactly as with an
  unapplied mutation row.
- **A detection arm that suppresses its read cannot report absence.** An arm asking "is this process mine?"
  by reading `/proc/<pid>/cwd` as a file under `contextlib.suppress(OSError)` never matches: the path is a
  symlink, `read_bytes` raises `IsADirectoryError`, the handler eats it, and every candidate reads as "not
  ours" — silently, for as long as the code lives. Whenever an arm suppresses a read, catches broadly, or
  reads several fields in one loop, feed it one input that **must** match and require the match: silence is
  then distinguishable from a broken arm, and one raising field can no longer lose the whole arm. The same
  shape reaches a probe's own parser — a tolerant regex lets a malformed line drop out of the count instead
  of failing it. **The attribution version of the same shape: a count of files under a shared tree is a
  claim about provenance, not a measurement.** Resolve every entry (`readlink -f`) before reporting "N files
  are copies of repo X" — in a library assembled from symlinks the bytes live in the checkout and a snapshot
  generator that publishes the tree skips them, so the number is wrong about both the scale and which loop
  owns those files. The resolve-first read is also what tells you whether the sync/repair you are arguing
  about covers them at all.
- **Inheriting a constraint from an earlier decision instead of probing it.** A recorded "X is impossible
  here" is the cheapest claim in the tree to check and the most expensive to inherit: it removes options
  from a round, and it is usually true only of the shape someone happened to try.  Probe it (positive and
  negative control, §1.10) before repeating it as a reason.
- **Attributing leftover scratch state to the subject without measuring the delta across your own run.** A
temp directory full of the subject's tree names reads as a leak; count the entries immediately before and
after the *one* run you are judging (`ls -d <pattern> | wc -l` on both sides). A delta of 0 against a large
absolute count means the residue is your own earlier experiments and the subject cleans up after itself —
and a non-zero delta on a suite that claims cleanup is the finding. Reporting the absolute count instead
sends the owner to repair a leak that does not exist.
- **A fix that guards one site and leaves its twin is the commonest residue of a fix round — sweep the
predicate, not the finding.** When the finding names "this path cannot be read" or "this predicate accepts
too much", grep the file for the same call shape (the helper, the `rglob`, the `exists`) before accepting:
a guard added where the artifact is planted is worthless one screen later where the caller's own entries
are enumerated, and the second site is reachable by input the author never named.
