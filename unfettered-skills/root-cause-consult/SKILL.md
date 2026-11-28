---
name: root-cause-consult
description: "Use when fixes keep spawning defects: ask root cause."
version: "0.2.0"
license: MIT
metadata:
  version: "0.2.0"
  author: Zoe
  areas: "software-development,research"
  targets: "runtime-agnostic"
  summary: "frame a consult for the root cause, refuse recipe answers, break the patch-to-pass loop"
  kind: "mechanism"
  hermes:
    tags: [root-cause, consult, defect-class, lanes]
    related_skills: [multi-model-generation-pipeline, cross-agent-repair-routing, code-review-gates, verification-probes]
---

# Root-cause consult

Trigger: a defect came back in a new shape after you fixed it, the same file produced findings on several
rounds, or you judge you cannot fix it yourself. Then consult a stronger model — and ask for the **root
cause**, never for a fix.

Standing owner directive this skill exists to enforce: *"不要问它怎么 fix、怎么让你的 file pass。你要咨询的是：什么是
root cause，怎么 fix root。不要为了过 tests、过 CI 就不停地打补丁。"* A consult asked for a fix returns a patch
for the case you named; the next round supplies a different case and the class returns.

## When to Use

- A defect returned in a new shape after you fixed it, or the same file has produced findings on several
  rounds.
- You are about to write a consult prompt for another model and the job is diagnosis, not generation.
- You catch yourself phrasing the question as "which of these should I do" or "what is the smallest test that
  pins it" — the framing that produces recipes.
- You are choosing the lane: take a family **independent of the reviewer whose rounds kept returning the
  class**. The recurrence is that reviewer's blind spot expressed as a moving predicate, so a same-family
  consult answers with the same enumeration it produced. Record which family answered — the diagnosis's value
  is that it did not come from the instrument that generated the findings.
- The owner requires a design consult **before** a refactor, optimization or evolution change, or at a
  fixed reasoning effort: that is a trigger, not a courtesy — run it first and carry its ranked options
  into the owner's round with your own recommendation.
- Not for generating candidate text or code against a rubric; that is `multi-model-generation-pipeline`.
- Not for a defect sitting in another agent's write surface; route that with `cross-agent-repair-routing`.

## Ask these three, and nothing narrower

1. **What is the root cause** of this recurring class of defect?
2. **What does fixing the root mean** — what must change structurally, in the contract, or in how the work is
   done?
3. **How can I tell the root is fixed** rather than the symptom merely suppressed?

Add the three questions that turn a diagnosis into a decision:

- *If the whole approach is the cause rather than some part of its implementation, say so and say what should
  replace it.* Without this the model repairs the shape you handed it.
- *Which artifact should carry the information that is being reconstructed?* A class that recurs in different
  shapes usually means information is re-derived where it should have been carried — an answer reachable only
  if the question is asked.
- *Is this an abstraction-boundary failure or a set of bounded residuals — and what in the trace decides it?*
  Ask it to **classify** the recurrence, name the deciding evidence, and state the bound outright ("if another
  fix round will keep finding sites, say so plainly"). Without the classification you are handed prose you must
  convert into a decision, and you end up choosing between "one more round" and "re-decompose" on your own
  authority. State your own hypothesis and the trace beside it so the answer can be graded against something —
  a lane that only restates your hypothesis has cost a round-trip.
- *Where does this stop?* A bound is part of the answer, and the residual it names (the window no cleanup can
  cover) is what you declare as a limit instead of re-reviewing for more of the same class.

## Ban the shapes you will not act on

Write the prohibitions into the prompt, by name: which line or function to change, how to make an existing
test pass, how to make a reviewer's counterexample stop reproducing, how to get CI green. Naming them is what
keeps the answer at the level you asked for. Pass the question as a **file**, not inline prose, so the exact
bytes are re-runnable and diffable.

## Procedure

1. **Write the question as a file**, with the prohibitions above and an explicit "I will not act on that".
   Consolidate the traces it must judge into a **dossier beside it** first: the contract paragraph, the
   acceptance clauses, the apparatus size, the per-round series (reviewed-diff bytes, finding count, clean
   rounds), the findings grouped into classes with **short IDs**, and your hypotheses with the evidence path
   beside each. The series is what lets the lane answer the classification and bound questions instead of
   restating your hypothesis, and the class IDs are what make its mapping checkable and the next round
   diffable.
2. **Give at least one lane read access to the tree** (`--tools read,grep,find,ls`) and point it at the
   readers, the helper and its tests, the contract paragraph, the plan and the evidence. A closed-book
   question about code returns a plausible design for code the model has not read — so when a closed-book
   lane is unavoidable (a model that does not converge while holding tools), say so in its prompt and treat
   every claim it makes about the current code as a hypothesis to check at step 5.
3. **Attach every earlier consult on the same question** and ask where they treat symptoms rather than the
   root — including your own earlier question, when its framing is what produced a recipe. Otherwise you get
   another variant of the same answer and adopt it because it is newer.
4. **Let it be uncomfortable.** "This helper is the wrong shape", "the contract is unenforceable as written",
   "the information must be captured at the boundary instead of reconstructed" are the answers you asked for,
   not a failure to answer.
5. **Adjudicate before anyone implements — and settle factual disagreement by reading the code, not by
   weighing the models.** The consult is a diagnosis, not a spec: diff the consults, name where they differ,
   then open the file each claim names and check it against the tree; adopt one, record what the tree
   confirmed and what it refuted, and hand the implementer an overriding spec (see
   `multi-model-generation-pipeline`, "Before a lane's spec becomes a dispatch"). Two lanes that disagree
   about what the code *currently does* are having a factual dispute, and the repository is the tiebreak — a
   closed-book lane demanding a whole new layer because it cannot see the seam, against a tools lane citing
   the line that already carries it, is resolved by reading that line. The resolution usually **narrows** the
   root cause ("the mechanism is missing" → "its coverage is incomplete"), which changes the option set you
   put to the owner, so do this before the round, never after. Write the result as a **claim → verdict → evidence table**
   beside the answer (`adjudication.md` in the run dir) with three verdicts — confirmed,
   refuted-or-imprecise, unproven — and hand the owner the corrections together with the fork: a diagnosis
   whose fork survives is still reported with what it got wrong, because that is what makes the fork
   trustworthy instead of quoted. Claim-type checks: `references/adjudicating-an-answer.md`.
6. **Do not dispatch the implementation round while the root answer is in flight.** A round dispatched on a
   recipe locks the framing in: it rewrites the function the way the last reviewer's counterexample wanted,
   the tree stays green, and the class survives. If a round is already running under the wrong framing, stop
   it and keep its diff as an artifact.

Question skeleton to copy: `templates/root-cause-consult-question.md`.

## Enforce the loop's bound mechanically, and supersede rather than raise it

A ≥3-round escalation written in a document is a suggestion; make it a predicate in the driver, evaluated on
telemetry the loop already writes — per-round **reviewed-diff bytes** and the **finding count**. Block when a
round *grows* the diff past a threshold (the measured pathology added +46% in one round) or when findings
fail to decrease strictly across a few rounds. Do **not** express the bound as a round count alone: a round
cap and a signal predicate are different things, and a hard round cap silently turns any larger `MAX_*`
constant into dead code — keep exactly one of each (a *signal* and an *absolute cap*), and say in the code
which one decides what.

**A bound already written down decides the fork — evaluate the run against it and quote it verbatim.** When
the repo's operating contract carries the trip conditions, check the current run against each before writing
the consult (diff growth in the round, whether the finding count ever strictly decreased, ordinary rounds
past the cap) and put the quoted clause in front of the owner. The ask then becomes "execute the rule you
wrote", the option that continues patching is priced as a contract violation rather than a judgement call,
and the ancestry — how many attempts already closed unmerged — is the number that makes re-decomposition
cheaper than another round.

When it trips, do not raise the cap. **Supersede the increment:** close the branch unmerged (tag its head
first, so nothing becomes unreachable), keep its review log as an adversarial-shape corpus, and rewrite the
contract to the smallest unit that can still prove the idea end to end — **one reference route, not five** —
then fan out one route per later increment. Verified numbers are the argument: a loop whose reviewed diff went
191 KB → 1.47 MB with zero clean rounds in 19 tries is not one round from converging.

## The patch-to-pass loop

Each round: take the reviewer's counterexample → change the code until that counterexample stops reproducing
→ add a case for it → ship. Green every round, class alive in a new shape. The signature is successive
findings on the same file, each a different instance, each fix small — by the third round the loop itself is
the defect, and the standing ≥3-round escalation in the operating contract is what fires this skill instead of
another patch round.

**The tell the consult is asked to decide on: did the predicate move every round?** A run of rounds each
widening the previous patch — one more existence check before the act, one more rule filtered out of the
reported set, one more `except` clause beside the call — is enumerating sites, not holding an invariant, so the
next defect always sits in the gap the latest predicate does not cover. The closure encodes the invariant in
the control flow, so a violating site cannot be written without going through the seam: one ownership object
for a resource created in a surface you do not own; one evaluation over the raw input, where a skipped or
disabled check is recorded rather than read as a pass; one result type, whose refusal variant only the one
matcher can construct. When the answer says "another round will keep finding sites", that *is* the answer —
carry the seam fix as the mandate for the next fix dispatch, and the residual it names (the window no cleanup
runs for) into the report as a declared limit. Closure shapes and their pins live in the
`design-first-hardening` reference of the `code-review-gates` skill, under "The cheaper rung first".

Second form of the same loop: enumerate the rules the contract **documents**, pin each with a test, and call
that a systematic sweep. It is necessary and it proves nothing about dimensions the document does not name —
whitespace, trimming and normalisation behaviour are typical next findings. A coverage claim must be about the
implementation's decision dimensions, not the document's sentences.

When comparing two proposed fixes, compare them on **what their invariant fails to check** (separators,
joiners, the final splice, anything bypassing the recogniser) rather than on which design sounds more modern,
and reject a guardrail whose safety story does not survive the counterexamples you already hold.

## When the loop cannot converge, and what replaces the cap

Count before you spend another round. The signature that a bounded review loop **cannot** converge at any
budget: no clean round at all, the reviewed diff growing monotonically, and each fix round adding more
reviewable surface than it retires — a **gain > 1** fix operator. Then the cap is not the constraint and
raising it is not a remedy, and "one more round" is the same purchase at a higher price. The missing
mechanism is a **contractive breaker** that halts instead of continuing: block the increment when a round's
diff grows by more than about a quarter, or when the findings count failed to strictly decrease over about
three rounds. Adopt it into the conductor as the loop's stopping rule — without it, "review until clean" has
no stopping rule at all — and put the fork to the owner structurally (narrow the contract so one route is
proved end to end, accept a disclosed residual, or abandon the branch).

**The cap's own block is the consult's dispatch point, not the owner's.** A run that reached a bounded review
cap with no clean round has already produced the evidence this section asks for — no clean round, monotonic
diff growth, a gain > 1 fix operator — so the event that blocks the run is the event that dispatches the
consult: report the block and the consult in one message. A fork put to the owner while the diagnosis is still
owed is answered blind, and its option set then has to be re-priced once the consult lands and narrows which
option is actually cheapest; verifying the consult's factual claims against the tree (step 5) is what does
that narrowing, so it belongs before the round.

**A letter choosing "one more round" authorizes that round, not the residual it named.** The option that
permits another bounded round usually carries its own fallback ("and if the same class recurs, land it with the
residuals declared"). That fallback is a *separate* decision: it lands an artifact asserting acceptance with
debt outstanding, so it stays parked until its condition is met **and** the owner names it — record it as
conditional with the word that releases it and carry it into the round's prompt header, so it is asked for at
the point it would be taken instead of being read as granted. The authorized round is then a **seam sweep**
(the closure shapes above), never another enumeration of the sites the finding named, and its findings file is
the accepted disposition: fix every FIX row, and state in the report which branch of the fork is in force.

A second engine keeps such a loop alive, and is worth naming separately: **an evidence ledger proves
existence, not soundness.** A citation table saying "at least one test exercises R" is a traceability index;
asked to certify that finite example tests pin a universal claim ("for every input, every configuration,
every target"), an attentive reviewer finds an unexercised dimension every round — an oracle that misses the
ordinary case, an assertion checking a count or a prefix instead of a value, an obligation named in prose but
never registered, a pin with no executed failing mutation of its own. Move the universal claims into the
**deterministic gate as executed invariants** (exhaustive small-input generation, property checks over the
combinations), restrict the ledger to discrete decisions plus the integration checks it can actually decide,
and leave the LLM audit the sensor role it is good at — the residual it reports is usually a real defect —
instead of the convergence proof it cannot be.

## The other consult shape: a draft design, not a defect

The same lane answers a second question — *is this design right?* — asked about a proposal (a goal file, a
plan, an interface, a contract change) **before** the owner is asked to decide it, sometimes because the
owner required exactly that order ("have the proposal read by <model>, integrate what it says, then bring it
to me for approval"). Keep the shapes apart: a defect consult asks for a root cause, a design consult asks
for a position, so it must also demand the argument *against* that position. Prompt shape, the option-set
brief, the stateless-lane rule and the GO / NO-GO gap check: `references/design-consult.md`.


## Operating the consult lane

- Launch it backgrounded with the prompt as a file and read the answer once the run reports done. Write the
  header line yourself so a 0-byte file is obviously "no output yet". A **single** medium-effort design
  consult is the exception that stays in the foreground: one brief returns in ~1–2 min, so
  `timeout <n> pi-run.sh --model <provider>/<model> @brief.md` is enough, and the runner leaves the raw
  answer plus an `attempts.jsonl` receipt (model, rc, ms, bytes) in its run dir — copy both beside the brief.
- **Run two heterogeneous lanes at once.** Pair a **tools lane** (`pi -p --provider <p> --model <m>
  @question.md`, cwd = the repo) with a **closed-book lane** (`pi-run.sh --model <provider>/<model> -o out.md
  @question.md`, no tools). A model that never converges while holding tools often answers the same question
  fine one-shot, and two families answering the same question blind to each other are what makes their
  agreement worth reading. State in each prompt whether it has tools.
- **Give each lane its own systemd unit.** `systemd-run --user --collect --unit=<name>
  --working-directory=<repo> bash -lc '…'`: a consult that rides the session dies on a gateway restart or a
  long turn, and a lost lane costs its whole timeout. Watch it with `systemctl --user is-active <unit>`. A
  transient `--user` unit gets the **manager's minimal environment** — no rc, no version-manager shims — so
  pass `--setenv=HOME=$HOME` and
  `--setenv=PATH=$HOME/.local/share/mise/shims:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin`, or a
  shim-provided `pi`/`omp` is `command not found` inside the unit while working fine in your shell.
- **Invoke the unit's payload as `bash <script>`, never `exec <script>`, and never rely on the file tool
  setting an executable bit.** A script the file tool just wrote lands `0644`, so `exec` fails with
  `Permission denied` and the unit exits `126` within a second — the launch line still says `Running as
  unit`, the answer file is absent and stderr is empty, which reads exactly like a very fast lane. Tell them
  apart by `systemctl --user is-active <unit>` **after** a wait (≈20–30 s) plus the answer file's byte
  count, and read `journalctl --user -u <unit>` when the unit is already gone. Give the unit
  `--working-directory` on the run dir so relative paths inside the script resolve.
- **Wake yourself with a monitor instead of blocking the turn.** One background job
  (`notify_on_complete=true`) polls both units until neither is `active`, then prints a **short** marker —
  completion time, byte counts, a tail of each answer — and you read the report files yourself. A
  notification carrying the full answers is one you skim; a notification carrying the marker sends you to the
  bytes.
- **Kill by exact PID.** `omp-run.sh kill <run>` prints the setsid pid; the run's state file carries it. Never
  `pkill -f <pattern>`: the pattern can appear inside the lane's own prompt text, the lane's argv carries the
  prompt, and the match takes out the lane *and* the calling shell — a whole round lost plus a shell that dies
  mid-report.
- `omp-run.sh` verbs are `start|list|status|tail|result|answer|kill` — there is no `stop`; `kill` terminates.
- A lane killed mid-round leaves its edits in the tree: copy `git diff` into an artifact before touching
  anything, check whether the tree is self-consistent (its gate may be green while its tests were never
  written), and decide explicitly whether to keep or revert.
- **Restart the proxy before reporting a model missing.** The GHC proxy caches its upstream catalog at
  startup: a model the owner names but the catalog lacks appears after `systemctl --user restart ghc-proxy`,
  with a changed model count. Verify by restart plus a re-read before telling the owner a model does not
  exist.
- **The harness keeps its own model catalog, separate from the proxy's.** The proxy can serve a model the
  lane cannot name: `pi` only routes ids present in its own catalog, and an unknown id exits non-zero before
  any request. Prove the row with `pi --list-models <substring>` before spending the call, and add the exact
  row when it is absent — restarting the proxy fixes a *stale* catalog, it does not add a row to the harness.
- **A design consult wants the purest closed-book lane: no tools, no session, no context files.**
  `pi -p --provider <p> --model <m> --thinking medium --no-tools --no-session --no-skills
  --no-context-files --mode text "$(cat brief.md)"`. The `--no-context-files` (and `--no-skills`) flags are
  what keep the working session's `AGENTS.md`/`SOUL.md` out of the lane — without them the model reasons from
  the rules the session already committed to and hands them back as a verdict. Keep the brief on disk and cat
  it, and wrap stdout in `=== started $(date -Is) ===` … `=== pi exit=$? finished ===` sentinel lines so
  completion is `grep -q finished out.md` and the exit code survives even when the answer is long (tens of KB
  in ~2 min at `--thinking medium` is the normal shape; a near-empty file with exit 0 means the id or
  transport is wrong, so read the stderr log before reporting anything).

## Pitfalls

- Coming back from a consult with "it is now (C) instead of (B)" and dispatching that — adopting a diagnosis as
  a spec without adjudicating it.
- Asking for "the smallest acceptance test" in the same prompt as "what is the root cause": the test question
  drags the answer back to the case at hand.
- Treating a green gate as evidence about the class. The gate enforces the rules you wrote down; the next
  finding lives outside them.
- Letting the newest consult win by recency; when two disagree, diff them and name the disagreement.
- Re-running one recipe-shaped question across models and calling the agreement a root cause — two models given
  the same recipe question produce two recipes.
