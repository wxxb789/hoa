# The review budget is spent and no round was ever clean

Open this when a review/fix loop has consumed its whole round budget and **every** round returned
findings. The ordinary ladder (budget the loop → systematic sweep of one file → normative spec) assumes
the loop is converging. This file is the branch where it is not, and it is the one case where the answer
is *not* another round of any kind.

## Step 0 — exhaustion is data, not a number to raise

A round cap is an anti-thrash budget. Reaching it is a signal to change the instrument. Raising the cap in
the driver's constant block buys nothing for the run in flight (the value is read at process start) and
converts a diagnosis into another cycle.

## Step 1 — converging or self-sustaining?

Read the per-round findings counts and the surfaces they name:

- **Converging**: the count falls, each round is on a new surface, nothing is re-raised. The budget was
  simply instantiated from a different increment — re-derive it from the comparable increment's observed
  round count and record the reason.
- **Self-sustaining**: map every finding to **the invariant it defends**, not to the file or rule title it
  cites. Findings that cite different files under different titles and all defend one invariant are a
  **single recurring surface**, and per-round patching can never close it — each patch reveals the next
  edge of the same rule (ordering, one-to-one matching, generation binding, ownership, lifecycle). Treat a
  cluster like that as one row, not as N closed findings.
- **Second tell — where the increment's growth went.** Measure the added lines split product vs
  tests/harness (`git diff --numstat`). If most of the growth is tests and self-verification code **added
  by earlier fix rounds**, later rounds are reviewing the instrument those rounds built: each fix can add
  surface faster than it removes defect, which is exactly the non-convergent shape. Put the split in the
  decision record; it is the number that makes "the loop is not converging" arguable rather than a feeling.

## Step 1b — converging at the cap: the fork belongs to the owner, asked with the next mandate already written

A loop whose rounds all carry **new, small, repeated-nowhere** findings is converging, and a cap reached
there is an **authorization** question, not a defect count — that cap was the owner's grant for this
increment. Neither spend another round in silence nor read "five more findings" as failure. Classify each
one first (pre-existing / introduced by this increment / documentation contradicting the shipped scope),
then put the fork to the owner as numbered, costed options, recommended first:

- one more bounded fix round on the named findings, then a fresh round on the repaired head;
- merge with the findings **declared as residuals** on the next increment — a marker carrying findings
  merges only as an explicitly owner-accepted residual named in the PR body; the gate blocks it otherwise;
- the hybrid: fix only what this increment's **own new code** introduced, and declare the rest.

**Write the next round's mandate before asking** — a task-directory file quoting each finding at its
`path:line` with the constraints restated, ready for one command — so the accepted option costs a dispatch
rather than a drafting round; and name the stop condition you will honour if that round is also non-clean.
A finding inside a module the **previous round itself added** is the classification that decides the
hybrid: the fix round's own new surface is this increment's blast radius, so it is repaired here, not
declared away.

When the mandate necessarily reaches paths the goal's `Bounds` do not list (the agent rules file, the
conventions document, sibling test modules), widen by **disclosure** in the goal file: add the paths to
`Bounds`, say why, expose each owner-level default the round took as an open question, and keep a backup of
that file. A silent widening deletes the increment's own account of its blast radius — and the path list is
exactly what lets a later round prove what this increment did and did not touch.

## Step 2 — the rungs, and the ones to refuse

| Reading | Rung |
|---|---|
| Code introduced by earlier fix rounds is out of contract | **Refuse.** A credential-copying check or a false-positive structural check is a real obligation whoever added it. "It arrived during a fix round" exempts nothing. |
| The expensive verification is not core to the goal | **Scope change → owner decision.** Never the loop's own choice; it redefines what "done" means. |
| The obligation surface was never enumerated as a whole | **The rung below.** |

## Step 3 — the systematic close-out (one lane, bounded)

Consult a cross-family model first, with the per-round history, the growth split and the options you have
already excluded; record the option it rejected and why. Then dispatch **one** close-out lane whose
deliverable is a **frozen obligation list** in the repo, not a prose report:

- Enumerate obligations from the goal's acceptance criteria, the public output claims, and the
  behavioural claims of the shipped checks and tests. **Every finding ever raised is an obligation too.**
  For a pipeline-shaped increment the surfaces usually fall out as: input selection, semantic translation,
  structural verification, installation and outcome reporting, native end-to-end verification, privacy and
  test integrity.
- One section per obligation: the clause; the discharge site (`path:line`); **positive evidence** (an
  executed command and its observed result); **one executed mutation**; the test that pins it.
- Do not weaken an obligation to match the implementation — where it is unmet, the fix is the
  implementation, in this same task, with the regression test that fails when the behaviour is removed.
- Bound it: no mutation infrastructure, no new verification framework. Temporary edits and altered
  fixtures are the mechanism; a close-out that builds a mutation driver has added surface again, which is
  the defect it was dispatched to remove.

## Step 4 — the evidence standard (this is the whole value of the round)

- **One executed mutation per rule** means the behaviour was deliberately broken, the verifying command
  was run, and the failure was observed — mutation, command and exit status recorded, then restored. A
  passing test is not a mutation. A *proposed* mutation is not an executed one.
- **Read the matrix for a row that failed before it passed.** One whose probe *failed to detect* its
  mutation, with the gap it exposed and the repair that closed it, is evidence the rows were executed
  rather than filled in — an all-green table with no such row is the shape a summariser produces. Spot-check
  one row yourself regardless: re-apply its mutation, watch its own case fail, restore, and see that the
  recorded restore hash matches.
- **Both directions, for every verification rule.** A valid case that is accepted **and** an invalid case
  that is rejected. A verifier that rejects everything is not correct, and a rule demonstrated only by its
  rejected input is satisfied by exactly that broken verifier.
- Read the list as arithmetic, not as prose: the obligation count per surface, and for each row whether
  the mutation column names a real command.

## Step 5 — exactly one authorized acceptance audit

The audit is a **fresh, read-only round whose scope is the frozen list**, run at the head that contains
it. Three things make that real rather than nominal:

- **Pass the list to the lane as an argument, not as a sentence inside the review prompt.** Without an
  explicit scope argument the lane re-derives the whole branch and returns the same class under new
  titles — the failure this rung exists to break. The audit asks, per obligation: is it discharged or only
  claimed; is the evidence re-derivable, or only a passing test; is any obligation omitted, weakened to
  match the implementation, or unsupported by the evidence the list cites.
- **Any later tree change invalidates the exact-head acceptance.** Freeze the head, commit the list and
the record, then audit. The list itself is part of the increment.
- **Encode the stop condition.** An audit that returns findings **blocks for decomposition/replanning** —
it never starts another fix/review cycle, and it is never a reason to raise the budget again.

Record the authorization as *"N ordinary rounds **plus** one explicitly authorized acceptance audit"*. That
phrasing is load-bearing: it is a one-time grant for this increment, not a raised standing budget, and it
is reversible by one constant (`0` disables it). Write the reversal into the decision record.

**The constant counts audits, and only the owner may spend a second one.** When the authorized audit returns
findings, the stop condition above is the default — but the owner may choose *repair the findings, then
re-audit the repaired head* over decomposition. Encode that as the counter moving one rung (`1` -> `2`) with
an in-line comment naming both consumptions (the audit that found them; the audit of the repair) and
re-stating the negations, because a bare raised number is indistinguishable from the standing budget this
rung forbids — and it must never be written as a change to the ordinary-round cap. The repair is a fix lane
scoped to the audit's findings, not a resumed review loop; the re-audit is again one fresh read-only round
on the same frozen list, at the head that carries the repair, and a findings verdict there blocks exactly as
the first one did. Scope it in the record: the letters authorize this many audits on this increment, and
nothing about the next one.

## Step 6 — the merge rule that survives all of it

**A closed findings list is not a clean review.** Merging requires a clean verdict on the exact head, so a
PR whose 30-odd findings are all closed and evidenced still blocks — to the operator, an all-closed list
reads like done, and saying "all findings fixed" in place of "a clean round exists on this head" is how an
unaudited large increment merges.

State, when the audit is clean: the frozen list at that head, the gate result on that head, the
audit's marker on that head, and zero unresolved threads. When the audit is not clean: the finding, the
surface it belongs to, and the decomposition question — for the owner, not for the loop.

**The audit's verdict is not the merge marker, and the gate is the only authority on what is.** Run the
gate in its JSON mode against the head in hand and read its reasons *by name* (`marker unknown`, `threads`,
`checks`, `gates`) early — before the last round is spent, not after. A head whose only review evidence is
an acceptance audit, or a **foreign tool's own state comment** (a bot's `<tool>-review-state` token is not
the gate's marker), comes back `marker unknown`: that is a missing round on that head, not a formatting
nit, and an endgame discovered after the budget is gone can only be bought with an owner question or a
hand-run round nobody authorised. Budget the marker-producing round for the final head **beside** the audit
grant, so the two never compete for the same spent allowance.

**The endgame order, once every round is spent:** repair the last findings → verify them independently
(revert the implementation, run the executed mutation, require the failure) → commit and push → **run one
marker-producing, diff-scoped ordinary round on the final head** → resolve every open thread with its
verified control → gate → squash merge with the residual disclosed in the PR body (a squash merge writes
that body into history, so the disclosure *is* the record). Name that last ordinary round for what it is in
the decision record — it satisfies the marker clause on the final head and is neither a resumed audit nor a
raised standing budget.
